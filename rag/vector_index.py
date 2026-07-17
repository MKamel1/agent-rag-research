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
import shutil
import urllib.error
import urllib.request
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
# create_and_download_snapshot() streams a whole collection snapshot file over localhost -- large
# but not slow (no WAN hop), so a generous fixed ceiling rather than a caller-tunable knob is
# enough headroom without letting a wedged download hang the caller (app/snapshot.py) forever.
_SNAPSHOT_DOWNLOAD_TIMEOUT_S = 900


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
        self._host = host
        self._port = port
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
        try:
            self._client.create_collection(
                self._collection,
                vectors_config={
                    _DENSE_VECTOR: models.VectorParams(
                        size=self._dim, distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={_SPARSE_VECTOR: _sparse_vector_params()},
            )
        except ApiException as e:
            # Concurrent creators race here: with `--parse-workers N` sharing ONE fresh collection,
            # two workers can both pass the exists-check above and both call create_collection; the
            # loser gets a 409 "already exists". Re-check existence rather than parse the vendor's
            # error string -- if the collection is now present, a peer created it with the same schema
            # this call would have, so we're done. Any other failure (collection still absent) is a
            # real error, classified as TransientError like every other round-trip in this adapter.
            if self._call(self._client.collection_exists, self._collection):
                return
            raise TransientError(f"Qdrant call failed: {e}") from e

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

    def delete(self, ids: list[str]) -> None:
        """Removes the points for `ids` (chunk_ids/summary_ids) — T-DOC40, the vector-store half of
        `DocumentStore.delete()`'s cross-store cleanup. Idempotent: deleting an id with no matching
        point (already gone, or never upserted) is a safe no-op, matching Qdrant's own delete-by-id
        semantics. `ids=[]` skips the network call entirely -- an empty selector is never sent.
        """
        if not ids:
            return
        self._call(
            self._client.delete,
            self._collection,
            points_selector=models.PointIdsList(points=[_point_id(i) for i in ids]),
        )

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

    def point_count(self) -> int:
        """Current number of points in the collection -- `app/reindex_idf.py`'s (OG-27) before/
        after invariant check reads this on both sides of `rebuild()` and refuses to declare
        success if they differ (the same OG-28-style "don't silently lose data" posture as
        `app/snapshot.py`'s own artifact checks)."""
        info = self._call(self._client.get_collection, self._collection)
        return info.points_count

    def has_idf_modifier(self) -> bool:
        """Whether the sparse vector field is currently configured with the native IDF modifier
        (`_sparse_vector_params()`) -- `app/reindex_idf.py`'s pre-flight (skip a needless
        rebuild if already set) and post-rebuild (confirm T-DOC27's fix actually landed) check.
        """
        info = self._call(self._client.get_collection, self._collection)
        sparse_config = info.config.params.sparse_vectors or {}
        params = sparse_config.get(_SPARSE_VECTOR)
        return params is not None and params.modifier == models.Modifier.IDF

    def create_and_download_snapshot(self, dest_path: str) -> None:
        """Backup half of the vendor boundary (`app/snapshot.py`'s job, T-DOC57): create a
        server-side snapshot of this collection, then pull the resulting file out of the vector
        store's own storage onto the host filesystem at `dest_path` -- a snapshot that only lives
        inside the container is not a backup. `app/snapshot.py` itself never names or imports the
        vendor client (CONVENTIONS.md §1); this is the one method that does both vendor-specific
        steps on its behalf.

        The typed client wraps snapshot *creation* (`create_snapshot`, a normal JSON-returning
        call, routed through `_call` like every other vendor round-trip here), but its
        generated *download* method tries to JSON-decode the raw snapshot bytes and breaks -- so
        the download itself is a plain streamed GET against the same REST endpoint via `urllib`
        (stdlib, not a second vendor dependency to allowlist).
        """
        description = self._call(self._client.create_snapshot, self._collection)
        if description is None:
            raise TransientError(
                f"Qdrant returned no snapshot description for collection {self._collection!r}"
            )
        url = (
            f"http://{self._host}:{self._port}/collections/{self._collection}"
            f"/snapshots/{description.name}"
        )
        try:
            with urllib.request.urlopen(url, timeout=_SNAPSHOT_DOWNLOAD_TIMEOUT_S) as response:
                with open(dest_path, "wb") as out:
                    shutil.copyfileobj(response, out)
        except (urllib.error.URLError, OSError) as e:
            raise TransientError(f"snapshot download failed for {url!r}: {e}") from e

    @staticmethod
    def _ranked_ids(hits: list) -> list[str]:
        # Tie-break by external id ascending, same as FakeVectorStore — rrf_fuse's rank is purely
        # positional, so equal-score ties must be broken consistently here, not left to whatever
        # order Qdrant happens to return them in.
        ordered = sorted(hits, key=lambda p: (-p.score, p.payload[_EXT_ID_KEY]))
        return [p.payload[_EXT_ID_KEY] for p in ordered]
