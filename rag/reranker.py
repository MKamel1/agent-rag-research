"""TeiReranker — the real `Reranker` adapter (Retriever's injected collaborator, ARCHITECTURE.md
§M7) over TEI's cross-encoder reranking endpoint (BGE-reranker-v2-m3, Spike-2 choice).

Vendor isolation (CONVENTIONS.md §1): talks to TEI over plain HTTP (`httpx`, already a core
dependency), so no vendor SDK import is needed — same pattern as `rag/summarizer.py`.
"""

import logging

import httpx

from contracts.errors import PermanentError, TransientError
from contracts.gpu_lock import GpuLock
from contracts.retriever import RerankCandidate

logger = logging.getLogger(__name__)

# Same taxonomy split as rag/summarizer.py: a rate-limited or momentarily-unhealthy server is
# transient (retry); any other 4xx is this request's fault (not retryable).
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

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
    """

    def __init__(self, client: httpx.Client, gpu_lock: GpuLock):
        self._client = client
        self._gpu_lock = gpu_lock

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

        with self._gpu_lock.acquire("rerank"):
            try:
                response = self._client.post(
                    "/rerank",
                    json={"query": query, "texts": [c.text for c in candidates]},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status in _RETRYABLE_STATUSES:
                    raise TransientError(f"reranker server returned {status}") from error
                raise PermanentError(f"reranker server returned {status}") from error
            except httpx.HTTPError as error:
                raise TransientError(f"reranker request failed: {error}") from error

            try:
                scored = [(item["index"], item["score"]) for item in response.json()]
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
