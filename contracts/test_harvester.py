"""Sibling test for contracts/harvester.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

import pytest
from pydantic import ValidationError

from contracts.harvester import PaperRef


def test_constructs_with_required_fields_and_defaults(make_paper_ref):
    ref = make_paper_ref()
    assert ref.paper_id == "2506.01234"
    assert ref.latex_url is None
    assert ref.relevance_score is None  # Harvester always produces None (DATA-CONTRACTS.md)


def test_optional_fields_can_be_set_explicitly(make_paper_ref):
    ref = make_paper_ref(latex_url="https://arxiv.org/e-print/2506.01234v1")
    assert ref.latex_url == "https://arxiv.org/e-print/2506.01234v1"


def test_wrong_type_raises(make_paper_ref):
    with pytest.raises(ValidationError):
        make_paper_ref(published="not-a-date")


def test_authors_must_be_a_list_not_a_bare_string(make_paper_ref):
    with pytest.raises(ValidationError):
        make_paper_ref(authors="A. Author")  # a single str is not a list[str] under strict mode


def test_paper_ref_doc_type_defaults_to_paper(make_paper_ref):
    assert make_paper_ref().doc_type == "paper"


def test_paper_ref_doc_type_book_round_trips_json(make_paper_ref):
    ref = make_paper_ref(doc_type="book")
    assert PaperRef.model_validate_json(ref.model_dump_json()).doc_type == "book"


def test_paper_ref_sidecar_without_doc_type_still_parses(make_paper_ref):
    # T-DOC48 sidecars written before this change have no doc_type key — must default, not fail
    data = make_paper_ref().model_dump_json(exclude={"doc_type"})
    assert PaperRef.model_validate_json(data).doc_type == "paper"
