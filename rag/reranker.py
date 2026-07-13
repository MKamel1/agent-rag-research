"""TeiReranker — the real `Reranker` adapter (Retriever's injected collaborator, ARCHITECTURE.md
§M7) over TEI's cross-encoder reranking endpoint (BGE-reranker-v2-m3, Spike-2 choice).

Vendor isolation (CONVENTIONS.md §1): talks to TEI over plain HTTP (`httpx`, already a core
dependency), so no vendor SDK import is needed — same pattern as `rag/summarizer.py`.
"""

import httpx

from contracts.errors import PermanentError, TransientError
from contracts.gpu_lock import GpuLock
from contracts.retriever import RerankCandidate

# Same taxonomy split as rag/summarizer.py: a rate-limited or momentarily-unhealthy server is
# transient (retry); any other 4xx is this request's fault (not retryable).
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class TeiReranker:
    """Real `Reranker` adapter: one cross-encoder call per `rerank()`, through an injected HTTP
    client pointed at TEI's `/rerank` endpoint.

    Acquires `gpu_lock.acquire("rerank")` around the inference call only (CONVENTIONS.md §6) —
    never around the empty-candidates short-circuit, so an empty query never queues behind the
    GPU lock. Returns the same `RerankCandidate` objects reordered by score descending — never
    fabricates new ones, per DATA-CONTRACTS.md "Reranker".
    """

    def __init__(self, client: httpx.Client, gpu_lock: GpuLock, model: str):
        self._client = client
        self._gpu_lock = gpu_lock
        self._model = model

    def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankCandidate]:
        if not candidates:
            return []

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
