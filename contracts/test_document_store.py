"""Sibling test for contracts/document_store.py (T-F1 DoD: imported by a trivial test; constructing
one with a wrong type raises).
"""

import pytest
from pydantic import ValidationError


def test_constructs_with_relevance_score_defaulting_to_none(make_paper_record):
    record = make_paper_record()
    assert record.relevance_score is None
    assert record.summary_id == "2506.01234:summary"


def test_relevance_score_can_be_set_explicitly(make_paper_record):
    record = make_paper_record(relevance_score=0.87)
    assert record.relevance_score == pytest.approx(0.87)


def test_wrong_type_raises(make_paper_record):
    with pytest.raises(ValidationError):
        make_paper_record(chunks="not-a-list-of-chunks")
