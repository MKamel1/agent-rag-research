# M1A-DORMANT (re-enable in M1b): the real-adapter cross-adapter tests skip until
# rag/vector_index.py exists. M1b DoD (CONVENTIONS §11) requires this suite active (importorskip
# resolves) and green. The rrf_fuse unit tests and the FakeVectorStore side of the cross-adapter
# smoke test run NOW (they touch only contracts.fusion + rag.fakes, which already exist) — that is
# the CI-green M1a portion (TEST-STRATEGY.md "VectorIndex" / "Contract tests").
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
   real-adapter side needs the vector service + opts out of the global `--disable-socket` in the
   nightly/M2 job, so it is guarded by `pytest.importorskip("rag.vector_index")` and skipped here
   (M1a does NOT build the nightly job or import the real backend SDK).
"""

from datetime import date

import pytest

from contracts.errors import ContractError
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
        "categories": ["cs.LG"],
        "published": "2026-06-01",
        "embedding_version": "v1",
    }
    fields.update(overrides)
    return fields


def _seed_dominant_fixture(adapter) -> str:
    """Upsert a fixture engineered so ONE document ("winner") dominates BOTH signals: its vector
    equals the query vector (dense rank 1) AND its section_path shares every query token (sparse
    rank 1). The other documents are dense-orthogonal and share no query tokens. Returns the id of
    the document that must come back top-1. Same fixture the real adapter reuses in the nightly job.
    """
    adapter.upsert("winner", [1.0, 0.0], _payload(section_path="method estimator"))
    adapter.upsert("dense_only", [1.0, 0.0], _payload(section_path="unrelated header"))
    adapter.upsert("sparse_only", [0.0, 1.0], _payload(section_path="method estimator"))
    adapter.upsert("noise", [0.0, 1.0], _payload(section_path="acknowledgements"))
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


CONTRACT = (
    assert_upsert_search_round_trips_id,
    assert_filters_by_category,
    assert_filters_by_date_range,
    assert_filters_by_kind,
    assert_top1_is_the_dominant_document,
    assert_rebuild_reproduces_results,
)


@pytest.mark.parametrize("check", CONTRACT, ids=[c.__name__ for c in CONTRACT])
def test_fake_adapter_satisfies_contract(check):
    # FakeVectorStore runs in CI now — it already fuses via the shared rrf_fuse (see its source).
    check(FakeVectorStore())


@pytest.mark.parametrize("check", CONTRACT, ids=[c.__name__ for c in CONTRACT])
def test_real_adapter_satisfies_contract(check):
    # Dormant until M1b: the real adapter needs the vector service and opts out of the global
    # --disable-socket in the nightly/M2 CI job. M1b replaces the skip below with:
    #     adapter = real.VectorIndex(<config + service handle>)
    #     check(adapter)
    # so the SAME contract functions above run against the real backend (top-1 agreement, etc.).
    real = pytest.importorskip("rag.vector_index")
    assert hasattr(real, "VectorIndex")
    pytest.skip("real vector adapter contract runs in the nightly/M2 job (needs vector service)")
