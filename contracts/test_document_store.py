"""Sibling test for contracts/document_store.py (T-F1 DoD: imported by a trivial test; constructing
one with a wrong type raises).
"""

import pytest
from pydantic import ValidationError

from contracts.author_orgs import AuthorOrgMatch
from contracts.document_store import ChapterSummary


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


def test_chapter_summary_shape():
    cs = ChapterSummary(summary_id="local:ab12cd34ef56:summary:ch0", title="Intro", text="...")
    assert cs.title == "Intro"


def test_paper_record_chapter_summaries_default_empty(make_paper_record):
    assert make_paper_record().chapter_summaries == []


def test_paper_record_raw_affiliations_and_author_orgs_default_empty(make_paper_record):
    record = make_paper_record()
    assert record.raw_affiliations == []
    assert record.author_orgs == []


def test_paper_record_accepts_raw_affiliations_and_author_orgs(make_paper_record):
    record = make_paper_record(
        raw_affiliations=["Waymo LLC, Mountain View, CA"],
        author_orgs=[AuthorOrgMatch(name="Waymo", method="keyword")],
    )
    assert record.raw_affiliations == ["Waymo LLC, Mountain View, CA"]
    assert record.author_orgs == [AuthorOrgMatch(name="Waymo", method="keyword")]


def test_paper_record_author_orgs_rejects_wrong_type(make_paper_record):
    with pytest.raises(ValidationError):
        make_paper_record(author_orgs=["Waymo"])  # must be AuthorOrgMatch, not bare str
