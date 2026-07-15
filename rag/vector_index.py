"""M6 VectorIndex (T-D2) — Qdrant adapter behind `VectorStore` (ARCHITECTURE.md §M6,
DATA-CONTRACTS.md §M6). The only module allowed to import `qdrant_client` (CONVENTIONS.md §1).

Hybrid search = one dense-only query + one sparse-only query against Qdrant (two named vectors on
the same collection), each turned into a rank-ordered id list, fused via the shared
`contracts.fusion.rrf_fuse` — never Qdrant's own (unweighted) native fusion, which can't express
`hybrid_dense_weight` (DATA-CONTRACTS.md §M6's explicit instruction). This mirrors
`rag/fakes/fake_vector_store.py` exactly, just with Qdrant standing in for the brute-force
cosine/token-overlap scan.

Sparse side: `VectorPayload.text` (the real chunk/summary passage text) is hashed into a raw
term-frequency bag-of-words sparse vector at `upsert()` time, and `qtext` is hashed the same way at
query time — same tokenization, same hasher, so the two sides are comparable. The collection's
sparse field is created with Qdrant's native IDF modifier (`_sparse_vector_params()`, server >=
1.10 — this repo's Qdrant is 1.18) — real BM25-style IDF weighting, computed by Qdrant itself from
this collection's own live document-frequency stats (applied to the query side at scoring time; see
Qdrant's sparse-vector indexing docs). `_sparse_vector` itself still only sends raw per-token
counts — no client-side df table to compute or keep in sync, T-DOC27. `section_path` remains in the
payload as metadata but is no longer the sparse channel's source; matches `FakeVectorStore`'s own
docstring/behavior (`FakeVectorStore` stays a plain token-overlap scan — it has no notion of
corpus-wide document frequency, so it does not attempt to approximate this IDF weighting).

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
# Depth cap on each side of hybrid_search's dense/sparse query, before RRF fusion. An accepted
# top-k approximation (not exhaustive retrieval) — a document ranked beyond this on both sides
# is dropped from fusion. Deliberate simplification, not a bug.
_FUSION_DEPTH_CAP = 10_000
# Per-page size for rebuild()'s scroll through the collection. Paged (see rebuild()) so this is
# just a page size, not a ceiling on how many points rebuild() can see.
_SCROLL_PAGE_SIZE = 100_000


def _point_id(external_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, external_id))


def _sparse_vector(text: str) -> models.SparseVector:
    # Raw per-token counts only -- Qdrant's IDF modifier (_sparse_vector_params()) does the actual
    # discriminative-term weighting server-side from the collection's own document-frequency
    # stats, so this function deliberately stays a plain hash-based term-frequency count on both
    # the upsert and query side (same as before T-DOC27).
    counts: dict[int, float] = {}
    for token in text.lower().split():
        index = int(hashlib.sha1(token.encode()).hexdigest(), 16) % _SPARSE_MODULUS
        counts[index] = counts.get(index, 0.0) + 1.0
    return models.SparseVector(indices=list(counts.keys()), values=list(counts.values()))


def _sparse_vector_params() -> models.SparseVectorParams:
    # T-DOC27: real IDF weighting via Qdrant's native sparse-vector modifier (server >= 1.10) --
    # the actual feature ADR-01 (PRD.md) chose Qdrant for ("Qdrant treats sparse vectors as
    # first-class beside dense"). Qdrant computes document-frequency stats itself, live, from
    # whatever's currently indexed in this collection, and scales the query vector's values by
    # IDF at scoring time -- no corpus-wide df table for this adapter to build or maintain.
    return models.SparseVectorParams(modifier=models.Modifier.IDF)


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
        exists = self._call(self._client.collection_exists, self._collection)
        if exists:
            return
        self._client.create_collection(
            self._collection,
            vectors_config={
                _DENSE_VECTOR: models.VectorParams(size=self._dim, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={_SPARSE_VECTOR: _sparse_vector_params()},
        )

    @staticmethod
    def _call(fn, *args, **kwargs):
        # Every Qdrant round-trip in this adapter goes through here, so a transient network blip
        # or a Qdrant restart mid-call is classified the same way everywhere (CONVENTIONS.md §4) —
        # the vendor's ApiException must never escape this module, the one seam whose job is to
        # hide the vendor.
        try:
            return fn(*args, **kwargs)
        except ApiException as e:
            raise TransientError(f"Qdrant call failed: {e}") from e

    def upsert(self, id: str, vector: list[float], payload: VectorPayload) -> None:
        stored_payload = dict(payload)
        stored_payload[_EXT_ID_KEY] = id
        self._call(
            self._client.upsert,
            self._collection,
            points=[
                models.PointStruct(
                    id=_point_id(id),
                    vector={
                        _DENSE_VECTOR: vector,
                        _SPARSE_VECTOR: _sparse_vector(payload["text"]),
                    },
                    payload=stored_payload,
                )
            ],
        )

    def hybrid_search(
        self, qvec: list[float], qtext: str, filters: SearchFilters | None, k: int
    ) -> list[Hit]:
        query_filter = _qdrant_filter(filters)

        dense_hits = self._call(
            self._client.query_points,
            self._collection,
            query=qvec,
            using=_DENSE_VECTOR,
            query_filter=query_filter,
            limit=_FUSION_DEPTH_CAP,
            with_payload=True,
        ).points
        sparse_hits = self._call(
            self._client.query_points,
            self._collection,
            query=_sparse_vector(qtext),
            using=_SPARSE_VECTOR,
            query_filter=query_filter,
            limit=_FUSION_DEPTH_CAP,
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
        points = []
        offset = None
        while True:
            page, offset = self._call(
                self._client.scroll,
                self._collection,
                limit=_SCROLL_PAGE_SIZE,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            points.extend(page)
            if offset is None:
                break
        self._call(self._client.delete_collection, self._collection)
        self._ensure_collection()
        if points:
            self._call(
                self._client.upsert,
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
