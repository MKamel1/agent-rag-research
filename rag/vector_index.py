"""M6 VectorIndex (T-D2) — Qdrant adapter behind `VectorStore` (ARCHITECTURE.md §M6,
DATA-CONTRACTS.md §M6). The only module allowed to import `qdrant_client` (CONVENTIONS.md §1).

Hybrid search = one dense-only query + one sparse-only query against Qdrant (two named vectors on
the same collection), each turned into a rank-ordered id list, fused via the shared
`contracts.fusion.rrf_fuse` — never Qdrant's own (unweighted) native fusion, which can't express
`hybrid_dense_weight` (DATA-CONTRACTS.md §M6's explicit instruction). This mirrors
`rag/fakes/fake_vector_store.py` exactly, just with Qdrant standing in for the brute-force
cosine/token-overlap scan.

Sparse side: like the fake, there is no raw chunk/summary text available at this seam
(`VectorPayload` deliberately carries none — `DocumentStore` holds it) — `section_path` is the
only text-shaped field, so it is hashed into a bag-of-words sparse vector at `upsert()` time and
`qtext` is hashed the same way at query time. This is a fake-parity choice, not a real BM25/SPLADE
index — same caveat `FakeVectorStore`'s own docstring makes.

Qdrant point ids must be an unsigned int or UUID (never an arbitrary string), so the caller's
`id` (a `chunk_id`/`summary_id`) is mapped to a stable `uuid.uuid5` and the original string is
carried in the payload (under a key private to this adapter) so results can be reported back under
the caller's own id.
"""

import hashlib
import uuid

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import ApiException

from contracts.errors import TransientError
from contracts.fusion import rrf_fuse
from contracts.vector_index import Hit, SearchFilters, VectorPayload

_ID_NAMESPACE = uuid.UUID("a3f7e6b0-4b8b-4c1a-9c9a-2b6a2f9b7d10")  # fixed, arbitrary, stable
_EXT_ID_KEY = "_ext_id"  # private payload key carrying the caller's original string id
_DENSE_VECTOR = "dense"
_SPARSE_VECTOR = "sparse"
_SPARSE_MODULUS = 2_147_483_647  # keeps hashed token indices within Qdrant's u32 index range


def _point_id(external_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, external_id))


def _sparse_vector(text: str) -> models.SparseVector:
    counts: dict[int, float] = {}
    for token in text.lower().split():
        index = int(hashlib.sha1(token.encode()).hexdigest(), 16) % _SPARSE_MODULUS
        counts[index] = counts.get(index, 0.0) + 1.0
    return models.SparseVector(indices=list(counts.keys()), values=list(counts.values()))


def _qdrant_filter(filters: SearchFilters | None) -> models.Filter | None:
    if filters is None:
        return None
    must: list[models.FieldCondition] = []
    if filters.categories is not None:
        must.append(
            models.FieldCondition(key="categories", match=models.MatchAny(any=filters.categories))
        )
    if filters.kind is not None:
        must.append(models.FieldCondition(key="kind", match=models.MatchValue(value=filters.kind)))
    if filters.published_after is not None or filters.published_before is not None:
        must.append(
            models.FieldCondition(
                key="published",
                range=models.DatetimeRange(
                    gte=filters.published_after, lte=filters.published_before
                ),
            )
        )
    return models.Filter(must=must) if must else None


class VectorIndex:
    """`VectorIndex(host, port, collection_name, dim, hybrid_dense_weight=0.5)` — connection
    params, not a pre-built client (keeps `qdrant_client` importable/nameable in exactly this one
    file, CONVENTIONS.md §1). `dim` is the dense vector size (`EmbedderInfo.dim` in production).
    """

    def __init__(
        self,
        host: str,
        port: int,
        collection_name: str,
        dim: int,
        hybrid_dense_weight: float = 0.5,
    ):
        # QdrantClient is constructed here, and only here (CONVENTIONS.md §1/§2) — callers
        # (including the composition root) pass connection params, never a pre-built client, so
        # `qdrant_client` never has to be imported/named anywhere else, not even in this module's
        # own test file.
        self._client = QdrantClient(host=host, port=port, check_compatibility=False)
        self._collection = collection_name
        self._dim = dim
        self._hybrid_dense_weight = hybrid_dense_weight
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        # First network round-trip to Qdrant; a service that isn't there (down, wrong host/port)
        # is exactly CONVENTIONS.md §4's TransientError case, not a ContractError — this adapter
        # has no retry/backoff of its own (that's the caller's job), it just classifies the error.
        try:
            exists = self._client.collection_exists(self._collection)
        except ApiException as e:
            raise TransientError(f"could not reach Qdrant: {e}") from e
        if exists:
            return
        self._client.create_collection(
            self._collection,
            vectors_config={
                _DENSE_VECTOR: models.VectorParams(size=self._dim, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={_SPARSE_VECTOR: models.SparseVectorParams()},
        )

    def upsert(self, id: str, vector: list[float], payload: VectorPayload) -> None:
        stored_payload = dict(payload)
        stored_payload[_EXT_ID_KEY] = id
        self._client.upsert(
            self._collection,
            points=[
                models.PointStruct(
                    id=_point_id(id),
                    vector={
                        _DENSE_VECTOR: vector,
                        _SPARSE_VECTOR: _sparse_vector(payload["section_path"]),
                    },
                    payload=stored_payload,
                )
            ],
        )

    def hybrid_search(
        self, qvec: list[float], qtext: str, filters: SearchFilters | None, k: int
    ) -> list[Hit]:
        query_filter = _qdrant_filter(filters)

        dense_hits = self._client.query_points(
            self._collection,
            query=qvec,
            using=_DENSE_VECTOR,
            query_filter=query_filter,
            limit=10_000,
            with_payload=True,
        ).points
        sparse_hits = self._client.query_points(
            self._collection,
            query=_sparse_vector(qtext),
            using=_SPARSE_VECTOR,
            query_filter=query_filter,
            limit=10_000,
            with_payload=True,
        ).points

        dense_ranked_ids = self._ranked_ids(dense_hits)
        sparse_ranked_ids = self._ranked_ids(sparse_hits)
        fused = rrf_fuse(dense_ranked_ids, sparse_ranked_ids, self._hybrid_dense_weight)

        kind_by_id = {
            p.payload[_EXT_ID_KEY]: p.payload["kind"] for p in (*dense_hits, *sparse_hits)
        }
        return [Hit(id=doc_id, kind=kind_by_id[doc_id], score=score) for doc_id, score in fused[:k]]

    def rebuild(self) -> None:
        """Drop and recreate the collection in place, re-upserting every point it already held —
        a defragment/reindex operation. This does NOT re-embed from `DocumentStore` (that needs
        the `Embedder` too — a re-embed-after-model-swap job belongs to the orchestrator, which
        has both dependencies; `VectorIndex`'s own interface takes neither a `DocumentStore` nor
        an `Embedder`, DATA-CONTRACTS.md §M6). Reads every point straight back out of Qdrant
        first (no separate local cache to keep in sync).
        """
        points, _ = self._client.scroll(
            self._collection, limit=100_000, with_payload=True, with_vectors=True
        )
        self._client.delete_collection(self._collection)
        self._ensure_collection()
        if points:
            self._client.upsert(
                self._collection,
                points=[
                    models.PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points
                ],
            )

    @staticmethod
    def _ranked_ids(hits: list) -> list[str]:
        # Tie-break by external id ascending, same as FakeVectorStore — rrf_fuse's rank is purely
        # positional, so equal-score ties must be broken consistently here, not left to whatever
        # order Qdrant happens to return them in.
        ordered = sorted(hits, key=lambda p: (-p.score, p.payload[_EXT_ID_KEY]))
        return [p.payload[_EXT_ID_KEY] for p in ordered]
