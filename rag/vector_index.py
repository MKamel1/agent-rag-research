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
import logging
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import ApiException

from contracts.errors import ContractError, TransientError
from contracts.fusion import rrf_fuse
from contracts.vector_index import Hit, SearchFilters, VectorPayload
from rag.ligatures import repair_ligatures

logger = logging.getLogger(__name__)

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
# clone_points_into()'s own upsert batch size -- deliberately much smaller than
# _SCROLL_PAGE_SIZE. Measured live: a _SCROLL_PAGE_SIZE=100_000 page of real production points
# (2560-dim dense + sparse vectors) serializes to a ~3.8GB request body, which Qdrant's REST API
# rejects outright (its own fixed 32MB request-size ceiling, not a timeout) -- read and write
# sides need independent sizes, reading a big page is fine, sending it in one request is not.
# 1,000 points of this collection's real vector size measured ~38MB -- still over the 32MB
# ceiling -- so this is 400 (~15MB at that same per-point size), leaving real margin rather than
# retuning to the observed edge.
_CLONE_UPSERT_BATCH_SIZE = 400
# CQ-2: resparse() reads and writes SPARSE vectors only (no 2560-dim dense vector on the wire in
# either direction), so a page is just text + a few hundred (index, value) pairs per point --
# roughly 3-4MB of response and ~1MB of update body per 1,000 points, far under the 32MB REST
# ceiling that sized _CLONE_UPSERT_BATCH_SIZE. One number serves as both the scroll page and the
# update batch, so each page is one read round-trip and at most one write round-trip.
_RESPARSE_BATCH_SIZE = 1_000
# set_payload() batch: how many paper ids go into one `MatchAny` filter / how many point ids into
# one `HasId` filter per request.
_PAYLOAD_BATCH_SIZE = 200
# Keys set_payload() refuses to overwrite: `text` feeds the sparse vector (changing it without
# re-sparsing would desync them), the rest are the adapter's own identity/routing keys.
_PROTECTED_PAYLOAD_KEYS = frozenset({"text", "_ext_id", "paper_id", "kind"})
# create_and_download_snapshot() streams a whole collection snapshot file over localhost -- large
# but not slow (no WAN hop), so a generous fixed ceiling rather than a caller-tunable knob is
# enough headroom without letting a wedged download hang the caller (app/snapshot.py) forever.
_SNAPSHOT_DOWNLOAD_TIMEOUT_S = 900
# T-DOC94: the client's own construction-time `timeout` had no explicit value, so the vendor
# library's ~5s REST default applied to every call this adapter makes -- including
# create_and_download_snapshot()'s create_snapshot() call below, which (unlike query_points/
# upsert/delete/scroll) cannot receive a per-call timeout override -- the vendor client asserts its
# kwargs are empty for that one method -- so the client's construction-time default is the only
# lever it has. A live snapshot of the 372,741-point production collection measured 6.75s,
# marginally over that ~5s default: not a hang, a bulk operation sharing a timeout sized for
# ordinary search. Raised here to match _SNAPSHOT_DOWNLOAD_TIMEOUT_S's own headroom for the same
# operation's other half (module constant, not Config -- see this module's `VectorIndex.__init__`
# docstring for why).
_CLIENT_TIMEOUT_S = 900
# hybrid_search() is the one call in this adapter still on a live, synchronous, user-waiting path
# (an MCP tool call) -- it keeps the pre-T-DOC94 ~5s fail-fast behavior explicitly instead of
# silently inheriting _CLIENT_TIMEOUT_S's new generous ceiling, which is meant for the bulk
# snapshot/rebuild calls. An outage should still surface to a live search caller in seconds, not
# minutes.
_SEARCH_TIMEOUT_S = 5

# start_container()'s target -- confirmed via a live `docker ps` this session, same "no
# docker-compose file exists to read this from" situation as `app/tei_lifecycle.py`'s own
# container names (T-DOC78). Health URL matches `app/doctor.py`'s own copy of this same endpoint
# (that module owns a copy rather than importing this constant, same convention its docstring
# already follows for the TEI URLs).
_CONTAINER_NAME = "rag-qdrant"
_HEALTH_URL = "http://localhost:6333/collections"
_START_POLL_INTERVAL_SECONDS = 0.25  # matches app/tei_lifecycle.py's own constant
_START_POLL_TIMEOUT_SECONDS = 30.0  # Qdrant has no model to reload -- restarts fast; TEI's 60s
# floor was sized for VRAM reload, this one is conservative-but-shorter for a plain DB restart.


@dataclass
class ResparseReport:
    """What `VectorIndex.resparse()` / `sample_sparse_staleness()` saw. `changed` means "stored
    sparse vector differs from the one the current `_sparse_vector` computes" -- in a dry run these
    were NOT written. `skipped` maps reason -> count (today: "no_text" -- payload has no string
    `text`, so nothing to recompute from; the point's existing sparse vector is left as is)."""

    dry_run: bool
    scanned: int = 0
    changed: int = 0
    unchanged: int = 0
    stored_sparse_missing: int = 0  # subset of `changed`: point had no stored sparse vector at all
    skipped: dict[str, int] = field(default_factory=dict)
    scanned_by_kind: dict[str, int] = field(default_factory=dict)
    changed_by_kind: dict[str, int] = field(default_factory=dict)


def _point_id(external_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, external_id))


def _sparse_vector(text: str) -> models.SparseVector:
    # Raw per-token counts only -- Qdrant's IDF modifier (_sparse_vector_params()) does the actual
    # discriminative-term weighting server-side from the collection's own document-frequency
    # stats, so this function deliberately stays a plain hash-based term-frequency count on both
    # the upsert and query side (same as before T-DOC27).
    # CQ-1: ligature-dropped words ("efect") are repaired before hashing, so "effect" and "efect"
    # share a term; stored text is untouched. Index and query both come through here.
    counts: dict[int, float] = {}
    for token in repair_ligatures(text.lower()).split():
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
    must: list[models.Condition] = []
    if filters.categories is not None:
        must.append(
            models.FieldCondition(key="categories", match=models.MatchAny(any=filters.categories))
        )
    if filters.kind is not None:
        must.append(models.FieldCondition(key="kind", match=models.MatchValue(value=filters.kind)))
    if filters.paper_id is not None:
        must.append(
            models.FieldCondition(key="paper_id", match=models.MatchValue(value=filters.paper_id))
        )
    if filters.doc_type == "book":
        must.append(models.FieldCondition(key="doc_type", match=models.MatchValue(value="book")))
    elif filters.doc_type == "paper":
        # Legacy points (pre-T-DOC80) have no doc_type payload key but are all papers --
        # match either the explicit value or the key's absence, mirroring the fake's .get default.
        must.append(
            models.Filter(
                should=[
                    models.FieldCondition(key="doc_type", match=models.MatchValue(value="paper")),
                    models.IsEmptyCondition(is_empty=models.PayloadField(key="doc_type")),
                ]
            )
        )
    if filters.author_org is not None:
        # T-ORG1: VectorPayload.author_orgs is a list of names; MatchValue against a list-valued
        # payload field matches if the value equals ANY element of the array (Qdrant's standard
        # keyword-array behavior) -- exactly the "author_org is one of the matched org names"
        # semantics this filter wants, no MatchAny/list needed on the query side.
        # T-ORG3: author_org_curated_only switches the filtered key to curated_author_orgs (the
        # enumerated-only subset) instead of author_orgs (any method) -- same MatchValue shape.
        key = "curated_author_orgs" if filters.author_org_curated_only else "author_orgs"
        must.append(
            models.FieldCondition(key=key, match=models.MatchValue(value=filters.author_org))
        )
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

    The client's own `timeout` is `_CLIENT_TIMEOUT_S`, not `Config` — T-DOC94 weighed the two:
    `Config` (`contracts/config.py`) is CODEOWNERS-foundation, so a new field there needs the
    `foundation-change` label and widens that file's blast radius; this value is an infra safety
    ceiling (like `_SNAPSHOT_DOWNLOAD_TIMEOUT_S` right above it, already a module constant for the
    same class of problem), not a scope/retrieval lever an operator tunes per run the way
    `Config.top_k` or `Config.hybrid_dense_weight` are. It also has nowhere to land without a new
    constructor parameter either way, since every caller already passes individual connection
    params here rather than a `Config` instance.

    `create_if_missing=False` (CQ-2 maintenance CLIs): raise `ContractError` instead of creating
    the collection when it is absent.
    """

    def __init__(
        self,
        host: str,
        port: int,
        collection_name: str,
        dim: int,
        hybrid_dense_weight: float = 0.5,
        create_if_missing: bool = True,
    ):
        # QdrantClient is constructed here, and only here (CONVENTIONS.md §1/§2) — callers
        # (including the composition root) pass connection params, never a pre-built client, so
        # `qdrant_client` never has to be imported/named anywhere else, not even in this module's
        # own test file.
        self._client = QdrantClient(
            host=host, port=port, check_compatibility=False, timeout=_CLIENT_TIMEOUT_S
        )
        self._host = host
        self._port = port
        self._collection = collection_name
        self._dim = dim
        self._hybrid_dense_weight = hybrid_dense_weight
        exists = self._call(self._client.collection_exists, collection_name)
        if not create_if_missing and not exists:
            # CQ-2 maintenance CLIs pass False: a typo'd --collection must fail, not silently
            # create (and then "successfully" operate on) an empty collection.
            raise ContractError(f"collection {collection_name!r} does not exist")
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
            timeout=_SEARCH_TIMEOUT_S,
        ).points
        sparse_hits = self._call(
            self._client.query_points,
            self._collection,
            query=_sparse_vector(qtext),
            using=_SPARSE_VECTOR,
            query_filter=query_filter,
            limit=_FUSION_DEPTH_CAP,
            with_payload=True,
            timeout=_SEARCH_TIMEOUT_S,
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

        DANGER — between `delete_collection` and the re-upsert below, `points` (an in-process
        Python list) is the ONLY copy of every point in this collection; nothing on disk holds
        them. If the process running this call dies in that window — crash, OOM-kill, or (the
        2026-07-29 incident) its PARENT process/session ending and taking this one down with it —
        the collection is left empty, full stop, with no way for this method or its caller to
        detect or prevent it: a dead process runs no more code. That incident retrofitted the
        IDF modifier onto production `papers` (372,741 points) via `app/reindex_idf.py`, which was
        launched attached to an interactive agent session; the session churned mid-rebuild, the
        process died between step 2 and the re-upsert, and `papers` was left with 0 points until
        restored from an unrelated full-clone collection that happened to exist. Any caller of
        `rebuild()` on a collection whose loss would matter MUST run it fully detached from
        whatever launched it (see `app/reindex_idf.py`'s module docstring) — or better, prefer
        `migrate_via_clone_and_swap()` below, which never holds the only copy of the collection in
        memory in the first place.
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

    def clone_points_into(self, dest_collection: str) -> int:
        """Copies every point (id, dense+sparse vector, payload) from this collection into
        `dest_collection` VERBATIM -- no re-embedding, and unlike `upsert()` (which always derives
        the sparse vector fresh from `payload["text"]`), this reuses the ORIGINAL sparse vector
        byte-for-byte, so document-frequency stats computed at the source collection's write time
        carry over unchanged rather than resetting for the destination.

        Same scroll-then-upsert shape as `rebuild()` above, upserting per-page instead of
        accumulating the whole collection in memory first -- safe here because, unlike `rebuild()`,
        the source collection is never deleted, so there's no reason to hold every point at once.
        Creates `dest_collection` with this collection's own schema if it doesn't exist yet (via a
        second `VectorIndex`, which runs the same `_ensure_collection()` this instance did).

        The upsert side is additionally re-batched to `_CLONE_UPSERT_BATCH_SIZE` -- a full
        `_SCROLL_PAGE_SIZE` page is fine to READ in one round-trip, but sending it back in one
        `upsert` request is not: a real 372,741-point production collection's own
        `_SCROLL_PAGE_SIZE` page serializes to a multi-GB request body, and Qdrant's REST API
        rejects any single request over a fixed 32MB regardless of client-side timeout. Read and
        write sides need independent sizes; `_CLONE_UPSERT_BATCH_SIZE` is sized for the write side
        only (see its own comment).

        Used by experiment scripts that need a throwaway collection seeded from the full
        production corpus without spending GPU time recomputing every existing vector -- e.g.
        app/exp1_outline_split.py, which then deletes/upserts only the handful of points its A/B
        actually changes. Returns the number of points copied.
        """
        dest = VectorIndex(
            self._host, self._port, dest_collection, self._dim, self._hybrid_dense_weight
        )
        offset = None
        total = 0
        while True:
            page, offset = self._call(
                self._client.scroll,
                self._collection,
                limit=_SCROLL_PAGE_SIZE,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            for i in range(0, len(page), _CLONE_UPSERT_BATCH_SIZE):
                batch = page[i : i + _CLONE_UPSERT_BATCH_SIZE]
                self._call(
                    dest._client.upsert,
                    dest._collection,
                    points=[
                        models.PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                        for p in batch
                    ],
                )
                total += len(batch)
            if offset is None:
                break
        return total

    def copy_kind_into(self, dest_collection: str, kind: str) -> int:
        """SB-1: copies only the points whose `payload["kind"] == kind` (server-side filtered
        scroll, `_qdrant_filter`'s own `models.FieldCondition(key="kind", ...)` shape) from this
        collection into `dest_collection` VERBATIM -- same no-re-embedding, byte-identical-vector
        guarantee as `clone_points_into` (see that method's own docstring), just scoped to one
        `kind` instead of the whole collection.

        Motivating case: an experiment that re-embeds every `kind="chunk"` point into a fresh
        collection (e.g. `app/reembed_experiment.py`'s `--sb1-section-context-window`) never
        touches `kind="summary"` points at all -- they'd otherwise be silently absent from the
        new collection, changing the candidate pool for `retrieve_papers()`/summary-kind hybrid
        search as an unintended SECOND variable alongside the one actually under test. This copies
        the untouched kind across so the destination collection's composition matches the source's,
        without spending GPU time re-embedding vectors nothing about the experiment changed.

        Does NOT call `clone_points_into` (which copies every point and would overwrite any
        `kind="chunk"` points the destination already holds with the SOURCE's chunk vectors --
        exactly the unwanted overwrite this method exists to avoid) -- same scroll-then-batched-
        upsert shape, independently, with a server-side filter added. Returns the number of points
        copied.
        """
        dest = VectorIndex(
            self._host, self._port, dest_collection, self._dim, self._hybrid_dense_weight
        )
        kind_filter = models.Filter(
            must=[models.FieldCondition(key="kind", match=models.MatchValue(value=kind))]
        )
        offset = None
        total = 0
        while True:
            page, offset = self._call(
                self._client.scroll,
                self._collection,
                scroll_filter=kind_filter,
                limit=_SCROLL_PAGE_SIZE,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            for i in range(0, len(page), _CLONE_UPSERT_BATCH_SIZE):
                batch = page[i : i + _CLONE_UPSERT_BATCH_SIZE]
                self._call(
                    dest._client.upsert,
                    dest._collection,
                    points=[
                        models.PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                        for p in batch
                    ],
                )
                total += len(batch)
            if offset is None:
                break
        return total

    def migrate_via_clone_and_swap(self, *, temp_collection: str | None = None) -> int:
        """Non-destructive alternative to `rebuild()` for retrofitting a schema change (e.g.
        T-DOC27's IDF modifier) onto a large LIVE collection — see `rebuild()`'s own docstring for
        the 2026-07-29 incident this exists to prevent a repeat of. Shape: clone every point from
        THIS collection into a fresh temp collection (`clone_points_into` — already creates the
        temp collection via `_ensure_collection()`, so it gets today's schema, IDF modifier
        included, "for free"), VERIFY the clone (`_verify_migrated_clone` below), and only THEN
        touch the live collection. There is no window where the only copy of the data is in
        process memory — unlike `rebuild()`, a crash before the swap step leaves the live
        collection completely untouched, and a crash during/after it leaves the verified temp
        collection as a ready-made recovery copy (see below).

        Swap mechanism — investigated, not assumed: Qdrant (server 1.18 here; confirmed via
        `QdrantClient.update_collection_aliases`'s own docstring, "Alias changes are atomic,
        meaning that no collection modifications can happen between alias operations") DOES offer
        an atomic swap, but only for a collection already exposed through an ALIAS. Production
        `papers` is a plain collection name, not an alias — the 2026-07-29 incident proves this
        directly, since `rebuild()` drops and recreates a collection literally named "papers" —
        and Qdrant has no operation to rename or atomically replace a plain (non-aliased)
        collection in place. Converting `papers` to alias-based naming would itself require a
        first, separate, non-atomic step against the live collection (out of scope for this
        change, which ships code only and runs no migration against production). So this method
        does NOT claim atomicity it hasn't verified: the honest fallback is delete-then-clone-back
        — delete the original collection, then clone the ALREADY-VERIFIED temp collection back
        into a freshly-created collection under the original name. `self._collection` is briefly
        absent during that final step, same as `rebuild()` — the safety win over `rebuild()` is
        that the full point set is never ONLY in memory at any point: if this final step itself
        is interrupted, the temp collection is untouched and still holds every point, so recovery
        is just re-running the clone-back (`temp_index.clone_points_into(self._collection)`), not
        a snapshot restore.

        `temp_collection` defaults to this collection's name plus a random suffix. On success the
        temp collection is deleted; on ANY verification or swap-count failure it is deliberately
        left in place as the recovery copy and a `ContractError` is raised (CONVENTIONS.md §4) —
        callers must not retry blindly. Returns the number of points in the final, swapped-in
        collection.
        """
        temp = temp_collection or f"{self._collection}__migrate_{uuid.uuid4().hex[:8]}"
        source_count = self.point_count()

        self.clone_points_into(temp)
        temp_index = VectorIndex(self._host, self._port, temp, self._dim, self._hybrid_dense_weight)
        self._verify_migrated_clone(temp_index, source_count)

        # Swap: no true atomic rename available for a plain-named live collection (see docstring
        # above) -- delete the original, then clone the already-verified temp collection back into
        # a freshly-created collection under the original name. `temp` is deliberately left alone
        # until this fully succeeds -- it is the recovery copy if this step itself is interrupted.
        self._call(self._client.delete_collection, self._collection)
        self._ensure_collection()
        final_count = temp_index.clone_points_into(self._collection)
        if final_count != source_count:
            raise ContractError(
                f"migrate_via_clone_and_swap: swap into {self._collection!r} copied "
                f"{final_count:,} of {source_count:,} points -- the verified copy is still intact "
                f"at {temp!r}; do NOT delete it, re-run the swap from there instead of retrying "
                f"from scratch."
            )

        self._call(self._client.delete_collection, temp)
        return final_count

    @staticmethod
    def _verify_migrated_clone(temp_index: "VectorIndex", source_count: int) -> None:
        """Raises `ContractError` (never returns a bool for the caller to maybe-check,
        CONVENTIONS.md §4/§14) if the just-cloned temp collection doesn't actually match the
        source: point count equal (an independent live re-read via `point_count()`, not just
        trusting whatever `clone_points_into` claimed it copied) AND `has_idf_modifier()` holds —
        the two properties `migrate_via_clone_and_swap`'s caller needs before it's safe to touch
        the live collection at all. A silent mismatch here is exactly the class of bug the
        2026-07-29 incident's missing safety layer would have caught had the process survived to
        run it.
        """
        live_count = temp_index.point_count()
        if live_count != source_count:
            raise ContractError(
                f"migrate_via_clone_and_swap: temp collection {temp_index._collection!r} has "
                f"{live_count:,} points but the source had {source_count:,} -- refusing to swap "
                f"an incomplete clone into place."
            )
        if not temp_index.has_idf_modifier():
            raise ContractError(
                f"migrate_via_clone_and_swap: temp collection {temp_index._collection!r} was "
                f"cloned but does not have the IDF modifier set -- refusing to swap it into "
                f"place."
            )

    def _sparse_updates(self, points: list, report: ResparseReport) -> list:
        """Tallies `points` into `report` and returns the `PointVectors` that need writing: the
        ones whose stored sparse vector differs from `_sparse_vector(payload["text"])`. Unchanged
        points are not returned, which is what makes a re-run after an interruption cheap and
        idempotent (it only rewrites what is still stale)."""
        updates = []
        for p in points:
            payload = p.payload or {}
            kind = str(payload.get("kind", "unknown"))
            report.scanned += 1
            report.scanned_by_kind[kind] = report.scanned_by_kind.get(kind, 0) + 1
            text = payload.get("text")
            if not isinstance(text, str):
                report.skipped["no_text"] = report.skipped.get("no_text", 0) + 1
                continue
            fresh = _sparse_vector(text)
            vectors = p.vector if isinstance(p.vector, dict) else {}
            stored = vectors.get(_SPARSE_VECTOR)
            if stored is not None and dict(zip(stored.indices, stored.values)) == dict(
                zip(fresh.indices, fresh.values)
            ):
                report.unchanged += 1
                continue
            report.changed += 1
            report.changed_by_kind[kind] = report.changed_by_kind.get(kind, 0) + 1
            if stored is None:
                report.stored_sparse_missing += 1
            updates.append(models.PointVectors(id=p.id, vector={_SPARSE_VECTOR: fresh}))
        return updates

    def resparse(
        self,
        collection: str | None = None,
        *,
        batch_size: int = _RESPARSE_BATCH_SIZE,
        dry_run: bool = False,
    ) -> ResparseReport:
        """CQ-2: recompute every point's SPARSE vector from `payload["text"]` with the current
        `_sparse_vector` (CQ-1's ligature repair) and write ONLY that named vector via the client's
        update-vectors call. Dense vectors and payloads are never read or sent -- no embedder, no
        GPU. `collection=None` means this adapter's own collection.

        Idempotent and resumable: points whose stored sparse vector already equals the recomputed
        one are not written, so after a mid-run failure (a `TransientError` from any round-trip
        propagates; earlier batches stay written) simply re-running does only the remaining work.
        Every point kind carries a sparse vector built from its `text` -- chunks (chunk text) and
        summaries (paper `summary_text`, or a chapter's text for book chapter summaries) alike --
        so summaries are resparsed like chunks. A point with no string `text` cannot be
        recomputed; it is counted under `report.skipped["no_text"]` and left untouched.
        `dry_run=True` scans and reports what would change without writing.
        """
        name = collection or self._collection
        report = ResparseReport(dry_run=dry_run)
        offset = None
        while True:
            page, offset = self._call(
                self._client.scroll,
                name,
                limit=batch_size,
                offset=offset,
                with_payload=["text", "kind"],
                with_vectors=[_SPARSE_VECTOR],
            )
            updates = self._sparse_updates(page, report)
            if updates and not dry_run:
                self._call(self._client.update_vectors, name, points=updates)
            if offset is None:
                return report

    def sample_sparse_staleness(self, n: int, collection: str | None = None) -> ResparseReport:
        """Read-only: `n` random points, each compared with its recomputed sparse vector --
        `report.changed / report.scanned` estimates how stale the collection is (0 after a full
        `resparse()`). Never writes."""
        report = ResparseReport(dry_run=True)
        sample = self._sample_points(
            n, collection, with_payload=["text", "kind"], with_vectors=[_SPARSE_VECTOR]
        )
        self._sparse_updates(sample, report)
        return report

    def sample_payloads(self, n: int, collection: str | None = None) -> list[dict]:
        """Read-only: full payloads of `n` random points (read-back check for `set_payload`)."""
        return [dict(p.payload or {}) for p in self._sample_points(n, collection, True, False)]

    def _sample_points(self, n: int, collection, with_payload, with_vectors) -> list:
        return self._call(
            self._client.query_points,
            collection or self._collection,
            query=models.SampleQuery(sample=models.Sample.RANDOM),
            limit=n,
            with_payload=with_payload,
            with_vectors=with_vectors,
        ).points

    def paper_point_ids(self, collection: str | None = None) -> dict[str, list[str]]:
        """External ids (as passed to `upsert`) of every point, grouped by `paper_id` -- one light
        scroll (two payload keys, no vectors). Backs payload backfills: `len()` per paper is the
        before/after invariant, and the ids address `set_payload(point_ids=...)` directly, which
        avoids one full-collection filter scan per paper (no payload index on `paper_id`).
        Raises `ContractError` for a point with no `_ext_id` -- it could not be addressed."""
        by_paper: dict[str, list[str]] = {}
        offset = None
        while True:
            page, offset = self._call(
                self._client.scroll,
                collection or self._collection,
                limit=_SCROLL_PAGE_SIZE,
                offset=offset,
                with_payload=["paper_id", _EXT_ID_KEY],
                with_vectors=False,
            )
            for p in page:
                payload = p.payload or {}
                if _EXT_ID_KEY not in payload:
                    raise ContractError(f"point {p.id} has no {_EXT_ID_KEY} payload key")
                by_paper.setdefault(payload.get("paper_id"), []).append(payload[_EXT_ID_KEY])
            if offset is None:
                return by_paper

    def set_payload(
        self,
        fields: dict,
        *,
        paper_ids: list[str] | None = None,
        point_ids: list[str] | None = None,
        collection: str | None = None,
        batch_size: int = _PAYLOAD_BATCH_SIZE,
    ) -> int:
        """CQ-2: MERGE `fields` into the payload of every point of `paper_ids` (all chunk and
        summary points of those papers) or of `point_ids` (the caller's external ids, as passed to
        `upsert`). Exactly one selector. Existing payload keys not named in `fields` survive --
        Qdrant's set-payload merges, never replaces; vectors are untouched. Batched by
        `batch_size` ids per request. Returns the number of points that matched (and so were
        written): ids with no point are silently not counted.

        `fields` must not name `text` (it feeds the sparse vector), `paper_id`, `kind` or the
        adapter's own `_ext_id`: overwriting those would corrupt retrieval, so it raises
        `ContractError`.
        """
        if (paper_ids is None) == (point_ids is None):
            raise ContractError("set_payload: give exactly one of paper_ids / point_ids")
        if not fields:
            raise ContractError("set_payload: fields is empty")
        forbidden = _PROTECTED_PAYLOAD_KEYS & fields.keys()
        if forbidden:
            raise ContractError(
                f"set_payload: refusing to overwrite protected keys {sorted(forbidden)}"
            )
        name = collection or self._collection
        if paper_ids is not None:
            ids, make = paper_ids, lambda b: models.FieldCondition(
                key="paper_id", match=models.MatchAny(any=b)
            )
        else:
            ids, make = [_point_id(i) for i in point_ids], lambda b: models.HasIdCondition(has_id=b)
        total = 0
        for i in range(0, len(ids), batch_size):
            flt = models.Filter(must=[make(ids[i : i + batch_size])])
            matched = self._call(self._client.count, name, count_filter=flt, exact=True).count
            if matched:
                self._call(self._client.set_payload, name, payload=fields, points=flt)
            total += matched
        return total

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

        `create_snapshot` itself has no per-call timeout parameter (T-DOC94) -- it relies entirely
        on `self._client`'s own construction-time `_CLIENT_TIMEOUT_S`, which is sized for this
        bulk operation, not the search-sized `_SEARCH_TIMEOUT_S` `hybrid_search` pins explicitly.
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


def start_container() -> None:
    """Best-effort `docker start` for this collection's container, then a bounded poll of its
    health endpoint before returning (T-DOC78: `app.doctor` auto-starting a stopped-but-startable
    health-only service, generalizing the T-DOC52 TEI pattern). Same "issue command -> poll a
    status endpoint -> bounded timeout -> best-effort continue" shape as
    `app/tei_lifecycle.py`'s `start_tei_containers()` -- duplicated rather than shared because the
    container name is a vendor-restricted token (CONVENTIONS.md §1) only this file may spell,
    the same reason `create_and_download_snapshot()` above does its vendor-specific step on
    `app/snapshot.py`'s behalf instead of `app/snapshot.py` naming the vendor itself. `app.doctor`
    calls this without ever naming the vendor or the container.

    Never raises: a failed `docker start` or an unconfirmed health check after the timeout both
    just log a warning and return -- the caller (`app.doctor`) treats "still unhealthy after
    calling this" as an issue to report, not this function's problem to escalate.
    """
    try:
        subprocess.run(["docker", "start", _CONTAINER_NAME], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        logger.warning(
            "could not start container %s -- best-effort, not blocking the caller: %s",
            _CONTAINER_NAME,
            error,
        )
        return

    deadline = time.monotonic() + _START_POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _is_container_healthy():
            return
        time.sleep(_START_POLL_INTERVAL_SECONDS)

    logger.warning(
        "could not confirm container %s was healthy within %.1fs -- proceeding anyway "
        "(best-effort; caller is not blocked)",
        _CONTAINER_NAME,
        _START_POLL_TIMEOUT_SECONDS,
    )


def _is_container_healthy() -> bool:
    try:
        with urllib.request.urlopen(_HEALTH_URL, timeout=5.0) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False
