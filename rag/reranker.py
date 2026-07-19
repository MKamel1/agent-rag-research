"""TeiReranker — the real `Reranker` adapter (Retriever's injected collaborator, ARCHITECTURE.md
§M7) over TEI's cross-encoder reranking endpoint (BGE-reranker-v2-m3, Spike-2 choice).

Vendor isolation (CONVENTIONS.md §1): talks to TEI over plain HTTP (`httpx`, already a core
dependency), so no vendor SDK import is needed — same pattern as `rag/summarizer.py`.
"""

import logging
import time
from collections.abc import Callable

import httpx

from contracts.errors import PermanentError, TransientError
from contracts.gpu_lock import GpuLock
from contracts.retriever import RerankCandidate

logger = logging.getLogger(__name__)

# Same taxonomy split as rag/summarizer.py: a rate-limited or momentarily-unhealthy server is
# transient (retry); any other 4xx is this request's fault (not retryable).
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Reliability-audit gap: unlike the ingest side (rag/harvester.py's Harvester, rag/orchestrator.py's
# IngestionOrchestrator), the query path used to raise on the FIRST transient failure — one TEI
# hiccup (429/502/503/504/timeout) failed a user's whole search. Bounded retry-with-backoff below,
# same shape (`max_retries`, injected `retry_sleep`, `2 ** (attempt - 1)` backoff) as those two
# ingest call sites, so this codebase has one retry idiom, not two. `PermanentError` is never
# retried.
RetrySleep = Callable[[float], None]

# OG-48#4: how long `rerank()` waits for a wedged/crashed GpuLock holder before giving up (raises
# TransientError instead of hanging forever) — see `rag/embedder.py`'s identical constant/rationale.
_DEFAULT_GPU_LOCK_TIMEOUT_S = 300.0


def _default_retry_sleep(seconds: float) -> None:
    time.sleep(seconds)


# T-DOC39: this vendor batch-size ceiling used to live in `rag/retriever.py` as
# `_RERANK_POOL_SIZE`'s hardcoded value -- wrong module, since it's a TEI deployment fact, not a
# retrieval-quality tuning knob (CONVENTIONS §1: a vendor constraint belongs inside the adapter
# that talks to the vendor). Confirmed live (T-DOC24/25 incident, `.phase0-data/teval-results.md`):
# the deployed TEI container (`--model-id BAAI/bge-reranker-v2-m3`, no `--max-client-batch-size`
# override) rejects a 50-text `/rerank` request with a 422 (`"batch size 50 > maximum allowed
# batch size 32"`) and accepts exactly 32. Because the retriever previously sent its whole
# `max(k, 32)` pool straight to `rerank()`, any caller-supplied `k > 32` (`McpServer` exposes `k`
# unclamped) reproduced that exact 422/0%-recall crash. Fixed here instead: `rerank()` defends this
# limit itself, unconditionally, regardless of how large a batch any caller hands it.
_MAX_BATCH_SIZE = 32


class TeiReranker:
    """Real `Reranker` adapter: one cross-encoder call per `rerank()`, through an injected HTTP
    client pointed at TEI's `/rerank` endpoint.

    Acquires `gpu_lock.acquire("rerank")` around the inference call only (CONVENTIONS.md §6) —
    never around the empty-candidates short-circuit, so an empty query never queues behind the
    GPU lock. Returns the same `RerankCandidate` objects reordered by score descending — never
    fabricates new ones, per DATA-CONTRACTS.md "Reranker".

    A `TransientError` from the `/rerank` HTTP call gets a bounded, backed-off retry
    (`max_retries`, `retry_sleep` — same shape as `rag/harvester.py`'s `Harvester`); a
    `PermanentError` (a non-retryable status, or a malformed/out-of-range response body) is never
    retried. Unlike the ingest-side retry sites, there is no quarantine outcome here — a
    query-path caller has no "skip this paper and continue" fallback, so once the retry budget is
    exhausted the (still-classified) error simply propagates.

    OG-48#3: `gpu_lock.acquire("rerank")` is held only around a SINGLE HTTP attempt — never across
    the retry/backoff loop (see `rag/embedder.py`'s identical fix/rationale). OG-48#4: a bounded
    `gpu_lock_timeout` (ctor param, default `_DEFAULT_GPU_LOCK_TIMEOUT_S`) is threaded into every
    acquire, so waiting for a wedged/crashed holder raises `TransientError` instead of hanging.
    """

    def __init__(
        self,
        client: httpx.Client,
        gpu_lock: GpuLock,
        *,
        max_retries: int = 2,
        retry_sleep: RetrySleep | None = None,
        gpu_lock_timeout: float | None = _DEFAULT_GPU_LOCK_TIMEOUT_S,
    ):
        self._client = client
        self._gpu_lock = gpu_lock
        self._max_retries = max_retries
        self._retry_sleep = retry_sleep or _default_retry_sleep
        self._gpu_lock_timeout = gpu_lock_timeout

    def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankCandidate]:
        if not candidates:
            return []

        if len(candidates) > _MAX_BATCH_SIZE:
            # Defend the vendor limit ourselves rather than trust every caller to pre-clamp --
            # never send a batch TEI will 422 on (T-DOC39). Truncating (not erroring) keeps this
            # consistent with the type's own "length <= len(candidates)" contract
            # (DATA-CONTRACTS.md "Reranker") and lets the caller's top-ranked candidates (the ones
            # a prior hybrid/RRF pass already favored) still get reranked instead of the whole
            # call failing.
            logger.warning(
                "rerank(): candidate batch (%d) exceeds the reranker's max batch size (%d) -- "
                "truncating to the first %d candidates instead of sending an oversized batch "
                "that would 422",
                len(candidates), _MAX_BATCH_SIZE, _MAX_BATCH_SIZE,
            )
            candidates = candidates[:_MAX_BATCH_SIZE]

        body = self._post_with_retry(query, candidates)
        try:
            scored = [(item["index"], item["score"]) for item in body]
        except (KeyError, TypeError, ValueError) as error:
            raise PermanentError(
                f"reranker response malformed (expected [{{'index', 'score'}}, ...]): {error}"
            ) from error

        # Sort by score descending ourselves (tie-broken by original index, ascending) rather than
        # trusting TEI's response ordering — a vendor detail this project doesn't control.
        try:
            scored.sort(key=lambda pair: (-pair[1], pair[0]))
            return [candidates[index] for index, _score in scored]
        except IndexError as error:
            raise PermanentError(f"reranker response index out of range: {error}") from error

    def _post_with_retry(self, query: str, candidates: list[RerankCandidate]) -> list:
        """The `/rerank` HTTP call, retried up to `_max_retries` times on `TransientError`
        (429/502/503/504, timeout, connection failure) with exponential backoff between attempts —
        same two-outcome shape as `rag/embedder.py`'s `_post_batch_with_retry`. A non-retryable
        status raises `PermanentError` immediately, same as before this method existed.

        `gpu_lock.acquire("rerank", timeout=...)` wraps only the single HTTP attempt inside the
        `try` below (OG-48#3) — released before `self._retry_sleep(...)` at the bottom ever runs.
        """
        attempt = 0
        while True:
            try:
                with self._gpu_lock.acquire("rerank", timeout=self._gpu_lock_timeout):
                    response = self._client.post(
                        "/rerank",
                        json={"query": query, "texts": [c.text for c in candidates]},
                    )
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status not in _RETRYABLE_STATUSES:
                    raise PermanentError(f"reranker server returned {status}") from error
                attempt += 1
                if attempt > self._max_retries:
                    raise TransientError(f"reranker server returned {status}") from error
            except httpx.HTTPError as error:
                attempt += 1
                if attempt > self._max_retries:
                    raise TransientError(f"reranker request failed: {error}") from error
            self._retry_sleep(self._backoff(attempt))

    @staticmethod
    def _backoff(attempt: int) -> float:
        # Same exponential curve (1s, 2s, 4s, ...) as rag/harvester.py's Harvester._backoff /
        # rag/orchestrator.py's IngestionOrchestrator._backoff / rag/embedder.py's
        # TeiEmbedder._backoff — not shared code across files (one line), just the same documented
        # shape (CONVENTIONS.md §4).
        return float(2 ** (attempt - 1))
