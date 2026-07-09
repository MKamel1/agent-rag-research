"""Sibling test for contracts/mcp_server.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

import pytest
from pydantic import ValidationError

from contracts.mcp_server import (
    Coverage,
    PaperSearchResponse,
    PaperSearchResult,
    PaperSummaryView,
    SearchResponse,
)
from contracts.provenance import Anchor
from contracts.retriever import Citation, GroundedResult

VALID_BBOX = (0.0, 0.0, 100.0, 200.0)


def _make_citation():
    return Citation(
        paper_id="2506.01234",
        title="A Causal Method",
        authors=["A. Author"],
        arxiv_url="https://arxiv.org/abs/2506.01234",
        section_path="3. Method",
    )


def _make_grounded_result():
    anchor = Anchor(
        paper_id="2506.01234",
        block_id="2506.01234:b0",
        page=0,
        bbox=VALID_BBOX,
        snippet="Some verbatim text.",
        section_path="3. Method",
    )
    return GroundedResult(
        passage_text="The estimator is defined as...",
        anchor=anchor,
        paper_id="2506.01234",
        score=0.91,
        citation=_make_citation(),
    )


def test_paper_summary_view_constructs():
    view = PaperSummaryView(
        paper_id="2506.01234",
        title="A Causal Method",
        authors=["A. Author"],
        summary_text="A short summary.",
        section_paths=["1. Intro", "3. Method"],
        citation=_make_citation(),
    )
    assert view.section_paths == ["1. Intro", "3. Method"]


def test_coverage_constructs_and_rejects_negative_counts():
    coverage = Coverage(returned=3, candidates=50)
    assert coverage.candidates >= coverage.returned

    with pytest.raises(ValidationError):
        Coverage(returned=-1, candidates=50)


def test_search_response_wraps_results_and_coverage():
    response = SearchResponse(
        results=[_make_grounded_result()], coverage=Coverage(returned=1, candidates=10)
    )
    assert response.coverage.candidates >= response.coverage.returned
    assert len(response.results) == 1


def test_paper_search_response_wraps_paper_search_results_and_coverage():
    view = PaperSummaryView(
        paper_id="2506.01234",
        title="A Causal Method",
        authors=["A. Author"],
        summary_text="A short summary.",
        section_paths=["1. Intro"],
        citation=_make_citation(),
    )
    result = PaperSearchResult(view=view, score=0.77)
    response = PaperSearchResponse(results=[result], coverage=Coverage(returned=1, candidates=5))
    assert response.results[0].score == pytest.approx(0.77)


def test_wrong_type_raises():
    with pytest.raises(ValidationError):
        SearchResponse(results="not-a-list", coverage=Coverage(returned=0, candidates=0))
