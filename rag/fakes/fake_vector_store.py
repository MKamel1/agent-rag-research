"""FakeVectorStore — the in-memory `VectorStore`/`VectorIndex` adapter that powers every zero-GPU
`Retriever` test (T-F4).

Real interface (ARCHITECTURE.md M6, owner D):
`upsert(id, vector, payload) -> None`, `hybrid_search(qvec, qtext, filters, k) -> list[Hit]`,
`rebuild() -> None`. `contracts/vector_index.py` owns the data shapes (`Hit`, `SearchFilters`,
`VectorPayload`); `contracts/fusion.py` owns the RRF formula itself — this fake calls
`rrf_fuse`, it never reimplements it (DATA-CONTRACTS.md "RRF fusion formula (frozen)":
"both `FakeVectorStore` and the real vector-store adapter call it").
"""

import math

from contracts.embedder import Vector
from contracts.fusion import rrf_fuse
from contracts.vector_index import Hit, SearchFilters, VectorPayload


class FakeVectorStore:
    """Brute-force in-memory dense+sparse hybrid search, fused via the shared `rrf_fuse`.

    - Dense ranking: cosine similarity of `qvec` against every stored vector that survives
      `filters`, ranked descending (ties broken by id ascending for determinism).
    - Sparse ranking: token-overlap of `qtext` against the stored payload's `text` — the real
      chunk/summary passage text (`VectorPayload.text`). This matches what the real vector-store
      adapter's sparse index scores against: both sides index real passage content, not a
      heading. A candidate with zero token overlap is excluded from the sparse ranked list
      entirely (mirrors a real sparse/BM25 index simply not retrieving a document for a query it
      shares no terms with), rather than being included at some arbitrary tail rank.

    `hybrid_dense_weight` is a `Config` lever (DATA-CONTRACTS.md §Config, default `0.5`), not a
    per-call `hybrid_search` argument — same as the real adapter, which is constructed once with
    a `Config` and reuses that weight for every search.
    """

    def __init__(self, hybrid_dense_weight: float = 0.5):
        self._hybrid_dense_weight = hybrid_dense_weight
        self._store: dict[str, tuple[Vector, VectorPayload]] = {}

    def upsert(self, id: str, vector: Vector, payload: VectorPayload) -> None:
        self._store[id] = (vector, payload)

    def delete(self, ids: list[str]) -> None:
        """T-DOC40: mirrors the real adapter's by-id delete. Idempotent -- an id with no matching
        entry (already gone, or never upserted) is silently skipped, same as `dict.pop(id, None)`.
        """
        for doc_id in ids:
            self._store.pop(doc_id, None)

    def hybrid_search(
        self, qvec: Vector, qtext: str, filters: SearchFilters | None, k: int
    ) -> list[Hit]:
        candidate_ids = [
            doc_id
            for doc_id, (_, payload) in self._store.items()
            if self._passes_filters(payload, filters)
        ]

        dense_ranked_ids = sorted(
            candidate_ids,
            key=lambda doc_id: (-self._cosine(qvec, self._store[doc_id][0]), doc_id),
        )

        sparse_scores = {
            doc_id: self._token_overlap_score(qtext, self._store[doc_id][1]["text"])
            for doc_id in candidate_ids
        }
        sparse_ranked_ids = sorted(
            (doc_id for doc_id in candidate_ids if sparse_scores[doc_id] > 0),
            key=lambda doc_id: (-sparse_scores[doc_id], doc_id),
        )

        fused = rrf_fuse(dense_ranked_ids, sparse_ranked_ids, self._hybrid_dense_weight)
        top = fused[:k]
        return [
            Hit(id=doc_id, kind=self._store[doc_id][1]["kind"], score=score)
            for doc_id, score in top
        ]

    def rebuild(self) -> None:
        """No-op: a fake has no persistent staleness to fix (there's no `DocumentStore`
        reference here to reindex from, unlike the real adapter's
        `rebuild() -> drops + rebuilds the collection from DocumentStore.iter_papers()`,
        DATA-CONTRACTS.md §M6). Exists purely so callers written against the real interface don't
        need a special case for the fake.
        """

    def _passes_filters(self, payload: VectorPayload, filters: SearchFilters | None) -> bool:
        if filters is None:
            return True
        if filters.categories is not None:
            if not (set(filters.categories) & set(payload["categories"])):
                return False
        if filters.kind is not None and payload["kind"] != filters.kind:
            return False
        published = payload["published"]  # ISO date string
        if filters.published_after is not None:
            if published < filters.published_after.isoformat():
                return False
        if filters.published_before is not None:
            if published > filters.published_before.isoformat():
                return False
        return True

    @staticmethod
    def _cosine(a: Vector, b: Vector) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _token_overlap_score(qtext: str, text: str) -> int:
        query_tokens = set(qtext.lower().split())
        text_tokens = set(text.lower().split())
        return len(query_tokens & text_tokens)
