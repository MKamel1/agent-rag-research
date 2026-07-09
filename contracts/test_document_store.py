"""Sibling test for contracts/document_store.py (T-F1 DoD: imported by a trivial test; constructing
one with a wrong type raises).
"""

from datetime import date

import pytest
from pydantic import ValidationError

from contracts.chunker import Chunk
from contracts.document_store import PaperRecord
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor

VALID_BBOX = (0.0, 0.0, 100.0, 200.0)


def _make_paper_ref():
    return PaperRef(
        paper_id="2506.01234",
        version="v1",
        title="A Causal Method",
        abstract="We propose...",
        authors=["A. Author"],
        categories=["cs.LG"],
        published=date(2026, 6, 1),
        updated=date(2026, 6, 1),
        pdf_url="https://arxiv.org/pdf/2506.01234v1",
    )


def _make_parsed_doc():
    return ParsedDoc(
        paper_id="2506.01234",
        markdown="# Title",
        blocks=[],
        figures=[],
        tables=[],
        references=[],
        parser_id="mineru-1.x",
    )


def _make_chunk():
    anchor = Anchor(
        paper_id="2506.01234",
        block_id="2506.01234:b0",
        page=0,
        bbox=VALID_BBOX,
        snippet="Some verbatim text.",
        section_path="3. Method",
    )
    return Chunk(
        chunk_id="2506.01234:c0",
        paper_id="2506.01234",
        text="Some chunk text.",
        anchor=anchor,
        section_path="3. Method",
        parent_id="2506.01234:b0",
    )


def _make_paper_record(**overrides):
    fields = dict(
        ref=_make_paper_ref(),
        parsed=_make_parsed_doc(),
        chunks=[_make_chunk()],
        summary_text="A short summary.",
        summary_id="2506.01234:summary",
    )
    fields.update(overrides)
    return PaperRecord(**fields)


def test_constructs_with_relevance_score_defaulting_to_none():
    record = _make_paper_record()
    assert record.relevance_score is None
    assert record.summary_id == "2506.01234:summary"


def test_relevance_score_can_be_set_explicitly():
    record = _make_paper_record(relevance_score=0.87)
    assert record.relevance_score == pytest.approx(0.87)


def test_wrong_type_raises():
    with pytest.raises(ValidationError):
        _make_paper_record(chunks="not-a-list-of-chunks")
