"""Tests for FakeReranker (T-F4) — non-identity reversal and call recording.

TEST-STRATEGY.md is explicit that an identity fake was rejected because it made every Retriever
test pass whether or not `rerank()` was invoked at all — these tests assert the order genuinely
changes, matches the documented reversal, and that the call is recorded.
"""

from contracts.retriever import RerankCandidate
from rag.fakes.fake_reranker import FakeReranker


def _candidates(*ids: str) -> list[RerankCandidate]:
    return [RerankCandidate(id=i, text=f"text for {i}") for i in ids]


def test_output_order_differs_from_input_order():
    reranker = FakeReranker()
    candidates = _candidates("a", "b", "c")
    result = reranker.rerank("some query", candidates)
    assert [c.id for c in result] != [c.id for c in candidates]


def test_output_order_matches_documented_reversal():
    reranker = FakeReranker()
    candidates = _candidates("a", "b", "c")
    result = reranker.rerank("some query", candidates)
    assert [c.id for c in result] == ["c", "b", "a"]


def test_calls_records_query_and_pre_rerank_ids_in_input_order():
    reranker = FakeReranker()
    candidates = _candidates("x", "y")
    reranker.rerank("my query", candidates)
    assert reranker.calls == [("my query", ["x", "y"])]


def test_calls_accumulates_across_multiple_invocations():
    reranker = FakeReranker()
    reranker.rerank("q1", _candidates("a"))
    reranker.rerank("q2", _candidates("b", "c"))
    assert reranker.calls == [("q1", ["a"]), ("q2", ["b", "c"])]


def test_single_candidate_reversal_is_still_non_identity_safe_noop():
    # A single-element list reversed is itself — this documents that edge case rather than
    # hiding it; the "non-identity" property is about the *general* behavior (TEST-STRATEGY.md),
    # not a guarantee that every possible input changes order.
    reranker = FakeReranker()
    candidates = _candidates("only")
    result = reranker.rerank("q", candidates)
    assert [c.id for c in result] == ["only"]
