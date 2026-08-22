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

# TEI enforces THREE limits, and batching by item count alone only respects the first. Read live
# from the deployed container (`GET /info` on BAAI/bge-reranker-v2-m3): `max_client_batch_size` 32,
# `max_input_length` 8192 (tokens per query+document pair), and `max_batch_tokens` 16384 -- a budget
# for the WHOLE request, not per item. 32 items therefore fit only if they average ~512 tokens.
#
# They do not. Measured over 20k chunks: the causal corpus's median chunk is ~566 estimated tokens,
# so a full 32-item batch runs ~18,100 tokens against a 16,384 ceiling and TEI answers 413. That is
# not an edge case, it is the median case; the Waymo corpus (median ~400) merely sits under it more
# often. The observed symptom was one eval question (Q-158) failing outright on every run, because
# 413 is correctly non-retryable -- resending an identical oversized batch fails identically.
#
# The fix is to pack batches against the token budget rather than the item count. Headroom is
# deliberate on both numbers below: the estimate is a heuristic, and the cost of over-estimating is
# one extra HTTP round trip while the cost of under-estimating is a dropped query.
_MAX_BATCH_TOKENS = 12_000        # against TEI's 16_384
_MAX_ITEM_TOKENS = 8_000          # against TEI's max_input_length of 8_192

# Deliberately pessimistic: English averages ~4 characters per token, so dividing by 3
# OVER-estimates the token count and produces smaller, safer batches. Tokenising properly
# here would mean importing the model's tokenizer into a module whose whole job is to be a thin
# HTTP adapter (CONVENTIONS §1), for an accuracy this does not need -- the headroom absorbs it.
_CHARS_PER_TOKEN = 3


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN + 1


def _truncate_to_item_budget(text: str) -> str:
    """Cap a single document at the model's own input ceiling.

    Lossless in the only sense that matters: TEI truncates at `max_input_length` server-side anyway,
    so bytes beyond it never influence the score. Sending them only risks blowing the batch budget.
    """
    limit = _MAX_ITEM_TOKENS * _CHARS_PER_TOKEN
    return text if len(text) <= limit else text[:limit]


def _pack_batches(query: str, candidates: list[RerankCandidate]) -> list[list[RerankCandidate]]:
    """Split candidates into batches satisfying BOTH the item-count and token-budget limits.

    The query is counted once per candidate, not once per batch: `/rerank` scores (query, document)
    PAIRS, so a batch of n items tokenises the query n times. Forgetting that is how a batch that
    looks comfortably under budget still 413s.
    """
    query_tokens = _estimate_tokens(query)
    batches: list[list[RerankCandidate]] = []
    current: list[RerankCandidate] = []
    current_tokens = 0
    for candidate in candidates:
        item_tokens = query_tokens + _estimate_tokens(
            _truncate_to_item_budget(candidate.text)
        )
        over_items = len(current) >= _MAX_BATCH_SIZE
        over_tokens = current and (current_tokens + item_tokens) > _MAX_BATCH_TOKENS
        if over_items or over_tokens:
            batches.append(current)
            current, current_tokens = [], 0
        current.append(candidate)
        current_tokens += item_tokens
    if current:
        batches.append(current)
    return batches


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

    `ensure_ready` (optional, default `None`): called once per `rerank()` call, before any HTTP
    work, if the caller wants a readiness check/side effect run first — this adapter never
    interprets what it does or catches anything it raises; a caller that wants best-effort
    semantics must make its own hook best-effort.
    """

    def __init__(
        self,
        client: httpx.Client,
        gpu_lock: GpuLock,
        *,
        max_retries: int = 2,
        retry_sleep: RetrySleep | None = None,
        gpu_lock_timeout: float | None = _DEFAULT_GPU_LOCK_TIMEOUT_S,
        ensure_ready: Callable[[], None] | None = None,
    ):
        self._client = client
        self._gpu_lock = gpu_lock
        self._max_retries = max_retries
        self._retry_sleep = retry_sleep or _default_retry_sleep
        self._gpu_lock_timeout = gpu_lock_timeout
        self._ensure_ready = ensure_ready

    def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankCandidate]:
        if not candidates:
            return []

        # RI-28: the query rides in EVERY (query, document) pair, but only the document side was
        # ever capped (`_truncate_to_item_budget`) -- nothing bounded the query. Past
        # `_MAX_ITEM_TOKENS` estimated tokens (24,000 chars at the /3 overestimate below; verified
        # 23,999 chars still estimates 8,000) the query alone busts the per-pair input ceiling, so
        # every batch `_pack_batches` can emit is rejected with a non-retryable 4xx and the whole
        # search dies with a generic "server returned 413" that never names the query as the
        # cause. (The packer's own degenerate point -- where even a one-item batch exceeds
        # `_MAX_BATCH_TOKENS`, ~35,997 chars -- sits past this guard, so checking the item budget
        # here subsumes it.)
        #
        # Fail fast rather than truncate. Truncation is correct for documents because the excess
        # bytes never influence the score either way (the service truncates the same bytes
        # server-side); for the query there is no such lossless reading -- a truncated query is a
        # DIFFERENT question, and silently reranking against its prefix would return plausibly
        # ordered results for something the user never asked, exactly the quiet degradation this
        # codebase's absence-honesty work exists to prevent. `PermanentError`, not transient:
        # resending the identical query fails identically (same reasoning as the 413s the service
        # itself returns).
        query_tokens = _estimate_tokens(query)
        if query_tokens > _MAX_ITEM_TOKENS:
            raise PermanentError(
                f"query too large to rerank: {len(query)} chars (~{query_tokens} estimated "
                f"tokens, limit {_MAX_ITEM_TOKENS}); shorten the query"
            )

        if self._ensure_ready is not None:
            self._ensure_ready()

        # A batch over the vendor limit used to be TRUNCATED to the first 32, which silently
        # capped recall: `_RERANK_POOL_SIZE` was pinned to 32 to match, so no caller could ever put
        # more than 32 candidates in front of the cross-encoder however large a `k` it asked for.
        # Measured consequence on the Waymo corpus: `--k 60` returned 32 passages, and an
        # enumeration question ("which papers used method X") could not see past the 32 the
        # first-stage hybrid pass happened to favour.
        #
        # Batching instead of truncating removes that ceiling. Cross-encoder scores are absolute
        # per-(query, document) relevance values, NOT normalised within a request, so scores from
        # separate batches are directly comparable and a global sort over the merged results is
        # the same ordering a single oversized call would have produced -- which is exactly why
        # this is safe to do here and would not be for a scoring scheme that softmaxed per batch.
        #
        # Cost is linear: ceil(n/32) sequential HTTP calls, each taking the GPU lock in turn.
        # `_post_with_retry` keeps its own per-attempt lock discipline (OG-48#3), so a slow batch
        # never holds the lock across a backoff sleep.
        scored: list[tuple[int, float]] = []
        offset = 0
        for batch in _pack_batches(query, candidates):
            body = self._post_with_retry(query, batch)
            try:
                # Re-base each batch's local index onto the caller's original candidate list.
                scored.extend((offset + item["index"], item["score"]) for item in body)
            except (KeyError, TypeError, ValueError) as error:
                raise PermanentError(
                    f"reranker response malformed (expected [{{'index', 'score'}}, ...]): {error}"
                ) from error
            offset += len(batch)

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
                        json={
                            "query": query,
                            # Truncated per item: see `_truncate_to_item_budget`. The candidate
                            # objects themselves are never modified -- callers get back exactly
                            # what they passed in, reordered.
                            "texts": [_truncate_to_item_budget(c.text) for c in candidates],
                        },
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
