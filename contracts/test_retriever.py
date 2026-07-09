"""Sibling test for contracts/retriever.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

import pytest
from pydantic import ValidationError

from contracts.retriever import RerankCandidate


def test_grounded_result_constructs_with_pinned_defaults(make_grounded_result):
    result = make_grounded_result()
    assert result.evidence_tier == "A"  # PINNED in V0
    assert result.metadata == {}  # empty in V0


def test_grounded_result_evidence_tier_rejects_non_v0_values_by_default_but_accepts_the_v1_v2_set(
    make_grounded_result,
):
    # The Literal type itself allows B/C/D (forward-compat, DATA-CONTRACTS.md) — V0 code just
    # never produces them. Confirm the type doesn't reject them outright (that would break the
    # forward-compat promise), while an invalid tier string is still rejected.
    result = make_grounded_result(evidence_tier="B")
    assert result.evidence_tier == "B"

    with pytest.raises(ValidationError):
        make_grounded_result(evidence_tier="Z")


def test_grounded_result_wrong_type_raises(make_grounded_result):
    with pytest.raises(ValidationError):
        make_grounded_result(score="high")  # wrong type


def test_rerank_candidate_constructs():
    candidate = RerankCandidate(id="2506.01234:c0", text="Some chunk text.")
    assert candidate.id == "2506.01234:c0"


def test_rerank_candidate_wrong_type_raises():
    with pytest.raises(ValidationError):
        RerankCandidate(id="x", text=12345)
