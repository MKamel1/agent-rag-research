"""Tests for FakeVectorStore (T-F4) — round-trip, shared rrf_fuse formula, and filters.

The "fused score matches calling rrf_fuse directly" test is the one that proves the "a test that
passes here should pass against Qdrant" claim from TEST-STRATEGY.md — it doesn't just assert a
plausible-looking score, it recomputes the expected fused scores by calling `rrf_fuse` on the same
dense/sparse rank lists this fake would itself derive, and asserts equality.
"""

import pytest

from contracts.fusion import rrf_fuse
from contracts.vector_index import SearchFilters, VectorPayload
from rag.fakes.fake_vector_store import FakeVectorStore


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


def test_upsert_and_hybrid_search_round_trips_id():
    store = FakeVectorStore()
    store.upsert("2506.01234:c0", [1.0, 0.0], _payload())
    hits = store.hybrid_search(qvec=[1.0, 0.0], qtext="method", filters=None, k=10)
    assert [h.id for h in hits] == ["2506.01234:c0"]
    assert hits[0].kind == "chunk"


def test_fused_score_matches_calling_rrf_fuse_directly():
    store = FakeVectorStore(hybrid_dense_weight=0.5)
    # "a" is a near-exact dense match and shares no tokens with the query's section-path stand-in
    # source; "b" is dense-orthogonal but shares tokens with the query text via section_path.
    store.upsert("a", [1.0, 0.0], _payload(section_path="unrelated header"))
    store.upsert("b", [0.0, 1.0], _payload(section_path="3. Method Estimator"))

    qvec = [1.0, 0.0]
    qtext = "3. method estimator"
    hits = store.hybrid_search(qvec=qvec, qtext=qtext, filters=None, k=10)

    # Recompute independently: dense rank by cosine similarity to qvec; sparse rank by token
    # overlap of qtext against each payload's section_path (this fake's documented sparse-index
    # stand-in), then fuse via the shared contracts.fusion.rrf_fuse — the same function the fake
    # itself must call.
    dense_ranked_ids = ["a", "b"]  # cos(qvec, a)=1.0 > cos(qvec, b)=0.0
    sparse_ranked_ids = ["b"]  # only "b"'s section_path shares tokens with qtext
    expected = dict(rrf_fuse(dense_ranked_ids, sparse_ranked_ids, hybrid_dense_weight=0.5))

    got = {h.id: h.score for h in hits}
    assert got == pytest.approx(expected)


def test_filters_restrict_by_category():
    store = FakeVectorStore()
    store.upsert("a", [1.0, 0.0], _payload(categories=["cs.LG"]))
    store.upsert("b", [1.0, 0.0], _payload(categories=["stat.ME"]))
    hits = store.hybrid_search(
        qvec=[1.0, 0.0], qtext="x", filters=SearchFilters(categories=["stat.ME"]), k=10
    )
    assert [h.id for h in hits] == ["b"]


def test_filters_restrict_by_published_date_range():
    from datetime import date

    store = FakeVectorStore()
    store.upsert("old", [1.0, 0.0], _payload(published="2026-01-01"))
    store.upsert("new", [1.0, 0.0], _payload(published="2026-06-01"))
    hits = store.hybrid_search(
        qvec=[1.0, 0.0],
        qtext="x",
        filters=SearchFilters(published_after=date(2026, 3, 1)),
        k=10,
    )
    assert [h.id for h in hits] == ["new"]


def test_filters_restrict_by_kind():
    store = FakeVectorStore()
    store.upsert("chunk1", [1.0, 0.0], _payload(kind="chunk"))
    store.upsert("summary1", [1.0, 0.0], _payload(kind="summary"))
    hits = store.hybrid_search(
        qvec=[1.0, 0.0], qtext="x", filters=SearchFilters(kind="summary"), k=10
    )
    assert [h.id for h in hits] == ["summary1"]


def test_rebuild_does_not_crash():
    store = FakeVectorStore()
    store.upsert("a", [1.0, 0.0], _payload())
    store.rebuild()  # no-op; must not raise
    hits = store.hybrid_search(qvec=[1.0, 0.0], qtext="method", filters=None, k=10)
    assert [h.id for h in hits] == ["a"]
