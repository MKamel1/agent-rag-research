"""Sibling test for contracts/harvester.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

from datetime import date

import pytest
from pydantic import ValidationError

from contracts.harvester import PaperRef


def _make_paper_ref(**overrides):
    fields = dict(
        paper_id="2506.01234",
        version="v1",
        title="A Causal Method",
        abstract="We propose...",
        authors=["A. Author", "B. Author"],
        categories=["cs.LG", "stat.ME"],
        published=date(2026, 6, 1),
        updated=date(2026, 6, 1),
        pdf_url="https://arxiv.org/pdf/2506.01234v1",
    )
    fields.update(overrides)
    return PaperRef(**fields)


def test_constructs_with_required_fields_and_defaults():
    ref = _make_paper_ref()
    assert ref.paper_id == "2506.01234"
    assert ref.latex_url is None
    assert ref.relevance_score is None  # Harvester always produces None (DATA-CONTRACTS.md)


def test_optional_fields_can_be_set_explicitly():
    ref = _make_paper_ref(latex_url="https://arxiv.org/e-print/2506.01234v1")
    assert ref.latex_url == "https://arxiv.org/e-print/2506.01234v1"


def test_wrong_type_raises():
    with pytest.raises(ValidationError):
        _make_paper_ref(published="not-a-date")


def test_authors_must_be_a_list_not_a_bare_string():
    with pytest.raises(ValidationError):
        _make_paper_ref(authors="A. Author")  # a single str is not a list[str] under strict mode
