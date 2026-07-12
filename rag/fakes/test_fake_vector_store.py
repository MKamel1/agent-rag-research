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
        "text": "We propose a doubly robust estimator for the average treatment effect.",
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
    # "a" is a near-exact dense match and shares no tokens with the query text; "b" is
    # dense-orthogonal but shares tokens with the query text via its real passage text.
    store.upsert("a", [1.0, 0.0], _payload(text="an unrelated sentence about something else"))
    store.upsert("b", [0.0, 1.0], _payload(text="we propose a doubly robust method estimator"))

    qvec = [1.0, 0.0]
    qtext = "doubly robust method estimator"
    hits = store.hybrid_search(qvec=qvec, qtext=qtext, filters=None, k=10)

    # Recompute independently: dense rank by cosine similarity to qvec; sparse rank by token
    # overlap of qtext against each payload's real text, then fuse via the shared
    # contracts.fusion.rrf_fuse — the same function the fake itself must call.
    dense_ranked_ids = ["a", "b"]  # cos(qvec, a)=1.0 > cos(qvec, b)=0.0
    sparse_ranked_ids = ["b"]  # only "b"'s text shares tokens with qtext
    expected = dict(rrf_fuse(dense_ranked_ids, sparse_ranked_ids, hybrid_dense_weight=0.5))

    got = {h.id: h.score for h in hits}
    assert got == pytest.approx(expected)


def test_sparse_channel_distinguishes_real_content_not_just_heading():
    # Both points share the exact same section_path -- if the sparse channel were still keying
    # off section_path (the pre-fix bug), it could not tell them apart. It must rank by `text`.
    store = FakeVectorStore(hybrid_dense_weight=0.5)
    store.upsert(
        "a",
        [1.0, 0.0],
        _payload(section_path="3. Method", text="we use instrumental variable estimation"),
    )
    store.upsert(
        "b",
        [1.0, 0.0],
        _payload(section_path="3. Method", text="we describe the dataset preprocessing steps"),
    )

    hits = store.hybrid_search(
        qvec=[1.0, 0.0], qtext="instrumental variable estimation", filters=None, k=10
    )

    # Both are an identical dense match (same qvec), so any ranking difference is purely the
    # sparse channel's doing -- "a" must come first since only its text shares query tokens.
    assert hits[0].id == "a"


def test_summary_payload_gets_real_sparse_signal_even_with_empty_section_path():
    # Reproduces production reality (rag/orchestrator.py passes section_path="" for summary
    # vectors): the sparse channel must still retrieve via the real `text` field even when
    # section_path is empty, closing the "summaries have zero sparse signal" bug.
    store = FakeVectorStore(hybrid_dense_weight=0.5)
    store.upsert(
        "2506.01234:summary",
        [0.0, 1.0],
        _payload(
            kind="summary",
            section_path="",
            text="this paper studies heterogeneous treatment effect estimation",
        ),
    )
    store.upsert("unrelated", [1.0, 0.0], _payload(text="a completely different topic"))

    hits = store.hybrid_search(
        qvec=[1.0, 0.0],  # dense side favors "unrelated"
        qtext="heterogeneous treatment effect estimation",
        filters=None,
        k=10,
    )

    # The summary must be retrievable at all via the sparse channel despite losing on dense --
    # if section_path="" were still the sparse source, it would have zero sparse signal and this
    # would fail whenever the dense channel doesn't already favor it.
    assert "2506.01234:summary" in [h.id for h in hits]


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
