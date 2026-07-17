# M1b: real-adapter cross-adapter tests are active. They need a live vector-store service
# reachable at localhost:6333 (this repo's documented default, CONVENTIONS.md §2's example) and
# opt out of the global `--disable-socket` via the `enable_socket` marker (pytest-socket) on just
# those tests; if no service is reachable (the common case — this default job doesn't run one),
# they skip with a clear reason rather than failing the build, same as the nightly/M2 job's
# real-adapter contract tests are meant to.
"""M6 VectorIndex test suite (T-D2), written test-first (TEST-STRATEGY.md "VectorIndex" + the
`rrf_fuse`/cross-adapter "Contract tests" section, DATA-CONTRACTS.md §M6).

Two deliberately-separated layers (TEST-STRATEGY: a strict full-ordering fake-vs-real equality was
found unachievable):

1. **`rrf_fuse` unit tests** — the actual arbiter of "is the fusion formula right." Pure function,
   no adapter, runs in CI now. Both `FakeVectorStore` and the real adapter must CALL this shared
   `contracts.fusion.rrf_fuse` (RRF_K=60 + `hybrid_dense_weight`), never reimplement it.
2. **Cross-adapter "best-effort agreement" smoke test** — upsert→search round-trips the id,
   `SearchFilters` (categories / date-range / kind) filter identically, `rebuild()` reproduces
   results, and the **top-1** result (NOT full ordering) matches on a fixture engineered so one
   document dominates both the dense and sparse signal. The `FakeVectorStore` side runs now; the
   real-adapter side needs a live vector-store service and network, so
   `test_real_adapter_satisfies_contract` below is marked `@pytest.mark.enable_socket` and skips
   (not fails) if it can't reach one.
"""

import io
from datetime import date
from types import SimpleNamespace

import pytest

from contracts.errors import ContractError, TransientError
from contracts.fusion import RRF_K, rrf_fuse
from contracts.vector_index import SearchFilters, VectorPayload
from rag.fakes.fake_vector_store import FakeVectorStore

# ==================================================================================================
# Layer 1 — rrf_fuse unit tests (the formula arbiter; runs now, no adapter involved)
# ==================================================================================================


def test_rrf_k_is_60():
    assert RRF_K == 60


def test_rank_is_1_indexed():
    # A single dense-only list, full weight on dense: score = 1 / (RRF_K + rank), rank of the
    # first item is 1 (not 0). So score("a") == 1/61, proving the 1-indexing.
    (only,) = rrf_fuse(["a"], [], hybrid_dense_weight=1.0)
    assert only == ("a", pytest.approx(1.0 / (RRF_K + 1)))


def test_weight_shifts_winner_toward_dense():
    # "a" leads the dense list, "b" leads the sparse list. Full dense weight -> "a" wins; full
    # sparse weight -> "b" wins. This is the "changing hybrid_dense_weight changes the result in
    # the expected direction" assertion from TEST-STRATEGY.
    dense = ["a", "b"]
    sparse = ["b", "a"]
    assert rrf_fuse(dense, sparse, hybrid_dense_weight=1.0)[0][0] == "a"
    assert rrf_fuse(dense, sparse, hybrid_dense_weight=0.0)[0][0] == "b"


def test_union_no_id_dropped():
    # An id in only one list is kept (scored on that term alone), not dropped.
    result = dict(rrf_fuse(["a"], ["b"], hybrid_dense_weight=0.5))
    assert set(result) == {"a", "b"}
    assert result["a"] == pytest.approx(0.5 * 1.0 / (RRF_K + 1))  # dense term only
    assert result["b"] == pytest.approx(0.5 * 1.0 / (RRF_K + 1))  # sparse term only


def test_ties_break_by_id_ascending_deterministically():
    # dense=[a,b], sparse=[b,a], equal weights -> a and b get identical scores; the frozen tie-break
    # is id ascending, so ordering is deterministic (rebuild() reproducibility depends on it).
    fused = rrf_fuse(["a", "b"], ["b", "a"], hybrid_dense_weight=0.5)
    ordered = [doc_id for doc_id, _ in fused]
    assert ordered == ["a", "b"]


def test_duplicate_ids_raise_contract_error():
    with pytest.raises(ContractError):
        rrf_fuse(["a", "a"], [], hybrid_dense_weight=0.5)
    with pytest.raises(ContractError):
        rrf_fuse([], ["b", "b"], hybrid_dense_weight=0.5)


def test_weight_out_of_range_raises_contract_error():
    with pytest.raises(ContractError):
        rrf_fuse(["a"], [], hybrid_dense_weight=1.5)
    with pytest.raises(ContractError):
        rrf_fuse(["a"], [], hybrid_dense_weight=-0.1)


def test_non_positive_rrf_k_raises_contract_error():
    with pytest.raises(ContractError):
        rrf_fuse(["a"], [], hybrid_dense_weight=0.5, rrf_k=0)


# ==================================================================================================
# Layer 2 — cross-adapter contract (the same assertions run against the fake now, real later)
# ==================================================================================================


def _payload(**overrides) -> VectorPayload:
    fields: VectorPayload = {
        "paper_id": "2506.01234",
        "kind": "chunk",
        "section_path": "3. Method",
        "text": "sample passage text",
        "categories": ["cs.LG"],
        "published": "2026-06-01",
        "embedding_version": "v1",
    }
    fields.update(overrides)
    return fields


def _seed_dominant_fixture(adapter) -> str:
    """Upsert a fixture engineered so ONE document ("winner") dominates BOTH signals: its vector
    equals the query vector (dense rank 1) AND its `text` shares every query token (sparse rank 1).
    The other documents are dense-orthogonal and share no query tokens. Returns the id of the
    document that must come back top-1. Same fixture the real adapter reuses in the nightly job.
    `section_path` is left at a plausible default throughout -- it's no longer the sparse source.
    """
    adapter.upsert("winner", [1.0, 0.0], _payload(text="method estimator"))
    adapter.upsert("dense_only", [1.0, 0.0], _payload(text="unrelated header"))
    adapter.upsert("sparse_only", [0.0, 1.0], _payload(text="method estimator"))
    adapter.upsert("noise", [0.0, 1.0], _payload(text="acknowledgements"))
    return "winner"


# --- contract assertions (each takes a constructed adapter) ---------------------------------------


def assert_upsert_search_round_trips_id(adapter):
    adapter.upsert("2506.01234:c0", [1.0, 0.0], _payload())
    hits = adapter.hybrid_search(qvec=[1.0, 0.0], qtext="method", filters=None, k=10)
    assert "2506.01234:c0" in [h.id for h in hits]


def assert_filters_by_category(adapter):
    adapter.upsert("a", [1.0, 0.0], _payload(categories=["cs.LG"]))
    adapter.upsert("b", [1.0, 0.0], _payload(categories=["stat.ME"]))
    hits = adapter.hybrid_search(
        qvec=[1.0, 0.0], qtext="method", filters=SearchFilters(categories=["stat.ME"]), k=10
    )
    assert [h.id for h in hits] == ["b"]


def assert_filters_by_date_range(adapter):
    adapter.upsert("old", [1.0, 0.0], _payload(published="2026-01-01"))
    adapter.upsert("new", [1.0, 0.0], _payload(published="2026-06-01"))
    hits = adapter.hybrid_search(
        qvec=[1.0, 0.0],
        qtext="method",
        filters=SearchFilters(published_after=date(2026, 3, 1)),
        k=10,
    )
    assert [h.id for h in hits] == ["new"]


def assert_filters_by_kind(adapter):
    adapter.upsert("c", [1.0, 0.0], _payload(kind="chunk"))
    adapter.upsert("s", [1.0, 0.0], _payload(kind="summary"))
    hits = adapter.hybrid_search(
        qvec=[1.0, 0.0], qtext="method", filters=SearchFilters(kind="summary"), k=10
    )
    assert [h.id for h in hits] == ["s"]


def assert_top1_is_the_dominant_document(adapter):
    winner = _seed_dominant_fixture(adapter)
    hits = adapter.hybrid_search(qvec=[1.0, 0.0], qtext="method estimator", filters=None, k=10)
    assert hits[0].id == winner


def assert_rebuild_reproduces_results(adapter):
    winner = _seed_dominant_fixture(adapter)
    before = adapter.hybrid_search(qvec=[1.0, 0.0], qtext="method estimator", filters=None, k=10)
    adapter.rebuild()
    after = adapter.hybrid_search(qvec=[1.0, 0.0], qtext="method estimator", filters=None, k=10)
    assert [h.id for h in after] == [h.id for h in before]
    assert after[0].id == winner


def assert_sparse_channel_distinguishes_real_text(adapter):
    """Two points share an IDENTICAL `section_path` (so a heading-based sparse signal could never
    tell them apart) but have different real `text`. Dense vectors are identical too (a tie), and
    ids are chosen so the id-ascending tie-break would pick the WRONG winner absent a real sparse
    signal -- so this only passes if the sparse channel is genuinely keying off `text`.
    """
    adapter.upsert(
        "aaa_wrong", [0.0, 1.0], _payload(section_path="3. Method", text="totally unrelated content")
    )
    adapter.upsert(
        "zzz_right", [0.0, 1.0], _payload(section_path="3. Method", text="a treatment effect estimator")
    )
    hits = adapter.hybrid_search(
        qvec=[0.0, 1.0], qtext="treatment effect estimator", filters=None, k=10
    )
    assert hits[0].id == "zzz_right"


def assert_summary_gets_real_sparse_signal_despite_empty_section_path(adapter):
    """Production code (`rag/orchestrator.py`) passes `section_path=""` for `kind="summary"`
    payloads -- before this fix that meant zero sparse signal for every summary vector. With `text`
    populated, a summary must still be reachable via the sparse channel even with `section_path`
    empty. Same tie-break trick as above: identical dense vectors, ids chosen so a broken/absent
    sparse signal would pick the wrong winner.
    """
    adapter.upsert(
        "decoy", [1.0, 0.0], _payload(kind="summary", section_path="", text="unrelated topic entirely")
    )
    adapter.upsert(
        "target",
        [1.0, 0.0],
        _payload(kind="summary", section_path="", text="a comprehensive causal discovery survey"),
    )
    hits = adapter.hybrid_search(qvec=[1.0, 0.0], qtext="causal discovery survey", filters=None, k=10)
    assert hits[0].id == "target"


def assert_rebuild_preserves_sparse_text_signal(adapter):
    """`rebuild()` copies payload+vectors verbatim (no re-embedding) -- confirm the new `text` field,
    and therefore the sparse channel's ability to distinguish real content, survives a rebuild.
    """
    adapter.upsert(
        "aaa_wrong", [0.0, 1.0], _payload(section_path="3. Method", text="totally unrelated content")
    )
    adapter.upsert(
        "zzz_right", [0.0, 1.0], _payload(section_path="3. Method", text="a treatment effect estimator")
    )
    adapter.rebuild()
    hits = adapter.hybrid_search(
        qvec=[0.0, 1.0], qtext="treatment effect estimator", filters=None, k=10
    )
    assert hits[0].id == "zzz_right"


def assert_delete_removes_points(adapter):
    # T-DOC40: the vector-store half of DocumentStore.delete()'s cross-store cleanup -- a deleted
    # id must stop appearing in search results, and an unrelated id must be untouched.
    adapter.upsert("keep", [1.0, 0.0], _payload(text="method estimator"))
    adapter.upsert("gone", [1.0, 0.0], _payload(text="method estimator"))

    adapter.delete(["gone"])

    hits = adapter.hybrid_search(qvec=[1.0, 0.0], qtext="method estimator", filters=None, k=10)
    ids = [h.id for h in hits]
    assert "gone" not in ids
    assert "keep" in ids


def assert_delete_of_unknown_id_is_a_safe_no_op(adapter):
    adapter.upsert("keep", [1.0, 0.0], _payload(text="method estimator"))
    adapter.delete(["never-upserted"])  # must not raise
    hits = adapter.hybrid_search(qvec=[1.0, 0.0], qtext="method estimator", filters=None, k=10)
    assert [h.id for h in hits] == ["keep"]


CONTRACT = (
    assert_upsert_search_round_trips_id,
    assert_filters_by_category,
    assert_filters_by_date_range,
    assert_filters_by_kind,
    assert_top1_is_the_dominant_document,
    assert_rebuild_reproduces_results,
    assert_sparse_channel_distinguishes_real_text,
    assert_summary_gets_real_sparse_signal_despite_empty_section_path,
    assert_rebuild_preserves_sparse_text_signal,
    assert_delete_removes_points,
    assert_delete_of_unknown_id_is_a_safe_no_op,
)


@pytest.mark.parametrize("check", CONTRACT, ids=[c.__name__ for c in CONTRACT])
def test_fake_adapter_satisfies_contract(check):
    # FakeVectorStore runs in CI now — it already fuses via the shared rrf_fuse (see its source).
    check(FakeVectorStore())


@pytest.mark.enable_socket  # opts out of the default job's --disable-socket for this test only
@pytest.mark.parametrize("check", CONTRACT, ids=[c.__name__ for c in CONTRACT])
def test_real_adapter_satisfies_contract(check):
    # Needs a live vector-store service at localhost:6333 (this repo's documented default). Most
    # default runs of this suite don't have one up, so a connection failure skips with a clear
    # reason rather than failing the build — the nightly/M2 job is where this is expected to
    # actually run and be required green. A fresh collection per `check` mirrors the fake's
    # fresh-instance-per-check isolation; it's torn down after, so reruns never see stale state.
    real = pytest.importorskip("rag.vector_index")

    collection = f"m1a_contract_{check.__name__}"
    try:
        adapter = real.VectorIndex(
            host="localhost", port=6333, collection_name=collection, dim=2, hybrid_dense_weight=0.5
        )
    except TransientError as e:
        pytest.skip(f"no live vector-store service reachable at localhost:6333: {e}")

    try:
        check(adapter)
    finally:
        adapter._client.delete_collection(collection)


# ==================================================================================================
# T-DOC27 — sparse-channel IDF weighting (ADR-01: the vector store treats sparse vectors as
# first-class beside dense).
#
# `_sparse_vector` itself is unchanged (still a plain raw-term-frequency hash, on purpose — see its
# updated comment in rag/vector_index.py): real IDF weighting is now the vector store's own native
# sparse-vector modifier, applied server-side from the collection's live document-frequency stats.
# That means the actual "does a rare/discriminative term outrank a common one" behavior cannot be
# proven by a fake or a pure-function test against `_sparse_vector` alone (`FakeVectorStore` has no
# notion of corpus-wide document frequency, and never will per its own docstring) — it can only be
# observed against a real vector-store collection, so the discriminative-weighting proof below is
# `enable_socket`-gated like `test_real_adapter_satisfies_contract` above, not "fake-based" as
# originally framed. The two zero-network tests below cover what a pure-function test *can* prove:
# `_sparse_vector`'s own output didn't change, and the collection config now actually requests the
# modifier.
# ==================================================================================================


def test_sparse_vector_stays_raw_term_frequency_no_client_side_idf():
    # Regression guard: _sparse_vector must keep sending plain per-token counts -- IDF weighting is
    # the vector store's job now (the modifier), not this function's. A repeated token accumulates
    # a count of 3.0, not some pre-scaled value; a token appearing once is 1.0, same as before
    # T-DOC27.
    real = pytest.importorskip("rag.vector_index")
    vec = real._sparse_vector("estimator estimator estimator treatment")
    values_by_index = dict(zip(vec.indices, vec.values))
    assert sorted(values_by_index.values()) == [1.0, 3.0]


def test_sparse_vector_params_requests_native_idf_modifier():
    # The actual T-DOC27 fix: the collection's sparse field must be created with the native IDF
    # modifier so common words stop carrying as much weight as discriminative ones (ADR-01/ADR-11
    # Tier A). No vendor client import needed here -- `.modifier.value` is a plain str off the
    # object `pytest.importorskip` already handed back (CONVENTIONS §1: the vendor client is
    # nameable only inside rag/vector_index.py, not this test file).
    real = pytest.importorskip("rag.vector_index")
    params = real._sparse_vector_params()
    assert params.modifier.value == "idf"


@pytest.mark.enable_socket
def test_real_adapter_sparse_channel_weights_rare_terms_over_common_ones():
    # The actual behavioral proof the ticket asks for: a document containing a corpus-RARE term
    # must outrank one that only repeats a term common across the whole corpus, even though both
    # have identical raw term frequency (1) for their respective term and identical (tied,
    # dense-weight-zeroed-out) dense vectors -- so only sparse IDF weighting can be deciding the
    # winner. Before T-DOC27 (raw term frequency, no IDF) this was a dead tie, broken arbitrarily by
    # the id-ascending tie-break -- "aaa_common_tied" would have won. It must not win now.
    real = pytest.importorskip("rag.vector_index")

    collection = "m1a_idf_weighting"
    try:
        adapter = real.VectorIndex(
            host="localhost", port=6333, collection_name=collection, dim=2, hybrid_dense_weight=0.0
        )
    except TransientError as e:
        pytest.skip(f"no live vector-store service reachable at localhost:6333: {e}")

    try:
        # "the" appears in 6 of 7 documents -> high document frequency -> low IDF once weighted.
        for i in range(5):
            adapter.upsert(f"common_{i}", [0.0, 1.0], _payload(text="the"))
        adapter.upsert("aaa_common_tied", [0.0, 1.0], _payload(text="the"))
        # "rare" appears in exactly 1 of 7 documents -> low document frequency -> high IDF.
        adapter.upsert("zzz_rare_wins", [0.0, 1.0], _payload(text="rare"))

        hits = adapter.hybrid_search(qvec=[0.0, 1.0], qtext="the rare", filters=None, k=10)
        assert hits[0].id == "zzz_rare_wins"
    finally:
        adapter._client.delete_collection(collection)


# ==================================================================================================
# T-DOC57 — create_and_download_snapshot (app/snapshot.py's vendor-boundary half). Offline: a fake
# `_client` stands in for the real one (no live service needed to prove the create->download wiring
# and error mapping), same "construct via __new__, skip __init__'s network round-trip" trick as
# every other offline test here that needs a VectorIndex instance without a live collection.
# ==================================================================================================


def _bare_adapter(real, *, client):
    """A `VectorIndex` with just enough attributes set for `create_and_download_snapshot` to run,
    without going through `__init__` (a real network round-trip via `_ensure_collection`)."""
    adapter = real.VectorIndex.__new__(real.VectorIndex)
    adapter._client = client
    adapter._host = "localhost"
    adapter._port = 6333
    adapter._collection = "papers"
    return adapter


def test_create_and_download_snapshot_downloads_the_created_snapshot(tmp_path, monkeypatch):
    real = pytest.importorskip("rag.vector_index")

    calls = []

    class _FakeSnapshotClient:
        def create_snapshot(self, collection_name):
            calls.append(collection_name)
            return SimpleNamespace(name="papers-2026-07-17.snapshot")

    adapter = _bare_adapter(real, client=_FakeSnapshotClient())

    requested_urls = []

    class _FakeResponse:
        def __enter__(self):
            return io.BytesIO(b"fake snapshot bytes")

        def __exit__(self, *exc_info):
            return False

    def fake_urlopen(url, timeout=None):
        requested_urls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(real.urllib.request, "urlopen", fake_urlopen)

    dest = tmp_path / "papers.snapshot"
    adapter.create_and_download_snapshot(str(dest))

    assert calls == ["papers"]
    assert requested_urls == [
        "http://localhost:6333/collections/papers/snapshots/papers-2026-07-17.snapshot"
    ]
    assert dest.read_bytes() == b"fake snapshot bytes"


def test_create_and_download_snapshot_raises_transient_error_when_no_description_returned(tmp_path):
    real = pytest.importorskip("rag.vector_index")

    class _FakeSnapshotClient:
        def create_snapshot(self, collection_name):
            return None

    adapter = _bare_adapter(real, client=_FakeSnapshotClient())

    with pytest.raises(TransientError, match="no snapshot description"):
        adapter.create_and_download_snapshot(str(tmp_path / "papers.snapshot"))


def test_create_and_download_snapshot_raises_transient_error_on_download_failure(
    tmp_path, monkeypatch
):
    real = pytest.importorskip("rag.vector_index")

    class _FakeSnapshotClient:
        def create_snapshot(self, collection_name):
            return SimpleNamespace(name="papers-2026-07-17.snapshot")

    adapter = _bare_adapter(real, client=_FakeSnapshotClient())

    def fake_urlopen(url, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(real.urllib.request, "urlopen", fake_urlopen)

    dest = tmp_path / "papers.snapshot"
    with pytest.raises(TransientError, match="snapshot download failed"):
        adapter.create_and_download_snapshot(str(dest))
    assert not dest.exists()


def test_ensure_collection_tolerates_concurrent_create_race(monkeypatch):
    """`--parse-workers N` sharing one fresh collection: two workers both pass the exists-check and
    both call create_collection; the loser gets a 409 ApiException. `_ensure_collection` must treat
    that as success (the collection now exists), not crash the worker (OG-28 / smoke-test finding)."""
    real = pytest.importorskip("rag.vector_index")
    # Raise the adapter's own already-imported vendor exception type (real.ApiException) rather than
    # importing the vendor name here -- the vendor-isolation check forbids naming it outside the
    # adapter file (rag/vector_index.py). The real 409 is an ApiException subclass; the base is enough
    # to exercise the except-clause.
    exists_calls = []

    class _RacingClient:
        def collection_exists(self, name):
            # First check: absent (this worker will try to create). After the failed create
            # (a peer won the race), the re-check sees it present.
            exists_calls.append(name)
            return len(exists_calls) > 1

        def create_collection(self, *a, **k):
            raise real.ApiException("simulated 409 already exists")

    adapter = _bare_adapter(real, client=_RacingClient())
    adapter._dim = 2560
    # Must NOT raise -- the peer's collection is accepted.
    adapter._ensure_collection()
    assert len(exists_calls) == 2  # initial check (absent) + post-conflict re-check (present)


def test_ensure_collection_reraises_when_create_fails_and_collection_still_absent(monkeypatch):
    """A create failure where the collection is genuinely still absent is a REAL error and must
    propagate as TransientError, not be swallowed by the concurrent-race tolerance above."""
    real = pytest.importorskip("rag.vector_index")
    from contracts.errors import TransientError

    class _BrokenClient:
        def collection_exists(self, name):
            return False  # never exists, even after the failed create

        def create_collection(self, *a, **k):
            raise real.ApiException("simulated create failure")

    adapter = _bare_adapter(real, client=_BrokenClient())
    adapter._dim = 2560
    with pytest.raises(TransientError):
        adapter._ensure_collection()


# ==================================================================================================
# OG-27 (T-DOC27 follow-up) -- point_count() / has_idf_modifier(), the two read-only checks
# app/reindex_idf.py needs around rebuild(): the before/after point-count invariant and the
# "did the fix actually land" post-check. Offline: a fake `_client.get_collection` stands in for
# the real vendor call (no live service needed to prove this adapter reads the right fields off
# `CollectionInfo`).
# ==================================================================================================


class _FakeInfoClient:
    def __init__(self, *, points_count, sparse_vectors):
        self._points_count = points_count
        self._sparse_vectors = sparse_vectors

    def get_collection(self, collection_name):
        return SimpleNamespace(
            points_count=self._points_count,
            config=SimpleNamespace(
                params=SimpleNamespace(sparse_vectors=self._sparse_vectors)
            ),
        )


def test_point_count_reads_points_count_off_collection_info():
    real = pytest.importorskip("rag.vector_index")
    client = _FakeInfoClient(points_count=42, sparse_vectors={})
    adapter = _bare_adapter(real, client=client)
    assert adapter.point_count() == 42


def test_has_idf_modifier_true_when_sparse_field_has_the_idf_modifier():
    real = pytest.importorskip("rag.vector_index")
    client = _FakeInfoClient(
        points_count=1,
        sparse_vectors={real._SPARSE_VECTOR: SimpleNamespace(modifier=real.models.Modifier.IDF)},
    )
    adapter = _bare_adapter(real, client=client)
    assert adapter.has_idf_modifier() is True


def test_has_idf_modifier_false_when_modifier_unset():
    # The exact pre-T-DOC27 production shape: the sparse field exists but its modifier is None.
    real = pytest.importorskip("rag.vector_index")
    client = _FakeInfoClient(
        points_count=1,
        sparse_vectors={real._SPARSE_VECTOR: SimpleNamespace(modifier=None)},
    )
    adapter = _bare_adapter(real, client=client)
    assert adapter.has_idf_modifier() is False


def test_has_idf_modifier_false_when_sparse_config_missing_entirely():
    real = pytest.importorskip("rag.vector_index")
    client = _FakeInfoClient(points_count=1, sparse_vectors=None)
    adapter = _bare_adapter(real, client=client)
    assert adapter.has_idf_modifier() is False


@pytest.mark.enable_socket
def test_real_adapter_point_count_and_idf_modifier_reflect_live_collection():
    # A fresh collection is always created WITH the IDF modifier now (_ensure_collection ->
    # _sparse_vector_params()), so this doubles as a regression guard on that invariant.
    real = pytest.importorskip("rag.vector_index")

    collection = "m1a_point_count_and_idf"
    try:
        adapter = real.VectorIndex(
            host="localhost", port=6333, collection_name=collection, dim=2, hybrid_dense_weight=0.5
        )
    except TransientError as e:
        pytest.skip(f"no live vector-store service reachable at localhost:6333: {e}")

    try:
        assert adapter.point_count() == 0
        assert adapter.has_idf_modifier() is True

        adapter.upsert("a", [1.0, 0.0], _payload(text="method estimator"))
        adapter.upsert("b", [0.0, 1.0], _payload(text="unrelated"))
        assert adapter.point_count() == 2
    finally:
        adapter._client.delete_collection(collection)
