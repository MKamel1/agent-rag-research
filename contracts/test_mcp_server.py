"""Sibling test for contracts/mcp_server.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

import pytest
from pydantic import ValidationError

from contracts.mcp_server import Coverage, PaperSearchResponse, PaperSearchResult, SearchResponse


def test_paper_summary_view_constructs(make_paper_summary_view):
    view = make_paper_summary_view()
    assert view.section_paths == ["1. Intro", "3. Method"]


def test_coverage_constructs_and_rejects_negative_counts():
    coverage = Coverage(returned=3, candidates=50)
    assert coverage.candidates >= coverage.returned

    with pytest.raises(ValidationError):
        Coverage(returned=-1, candidates=50)


def test_search_response_wraps_results_and_coverage(make_grounded_result):
    response = SearchResponse(
        results=[make_grounded_result()], coverage=Coverage(returned=1, candidates=10)
    )
    assert response.coverage.candidates >= response.coverage.returned
    assert len(response.results) == 1


def test_paper_search_response_wraps_paper_search_results_and_coverage(make_paper_summary_view):
    view = make_paper_summary_view(section_paths=["1. Intro"])
    result = PaperSearchResult(view=view, score=0.77)
    response = PaperSearchResponse(results=[result], coverage=Coverage(returned=1, candidates=5))
    assert response.results[0].score == pytest.approx(0.77)


def test_wrong_type_raises():
    with pytest.raises(ValidationError):
        SearchResponse(results="not-a-list", coverage=Coverage(returned=0, candidates=0))
