"""Sibling test for contracts/parser.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

import pytest
from pydantic import ValidationError

from contracts.parser import Figure, ParsedDoc, Reference, TableItem
from contracts.provenance import Block

VALID_BBOX = (0.0, 0.0, 100.0, 200.0)


def _make_block(index=0):
    return Block(
        block_id=f"2506.01234:b{index}",
        paper_id="2506.01234",
        text="Some prose.",
        type="prose",
        page=0,
        bbox=VALID_BBOX,
        section_path="1. Intro",
        index=index,
    )


def test_figure_constructs_and_defaults_vlm_description_to_none():
    fig = Figure(
        paper_id="2506.01234",
        image_path="/blobs/2506.01234/fig1.png",
        caption="Figure 1: overview",
        page=1,
        bbox=VALID_BBOX,
    )
    assert fig.vlm_description is None  # ALWAYS None in V0


def test_figure_wrong_type_raises():
    with pytest.raises(ValidationError):
        Figure(
            paper_id="2506.01234",
            image_path="/blobs/fig1.png",
            caption="c",
            page="one",  # wrong type
            bbox=VALID_BBOX,
        )


def test_table_item_constructs():
    table = TableItem(
        paper_id="2506.01234",
        markdown="| a | b |\n|---|---|\n| 1 | 2 |",
        caption="Table 1",
        page=2,
        bbox=VALID_BBOX,
    )
    assert "a" in table.markdown


def test_reference_optional_fields_default_to_none():
    ref = Reference(raw="Smith et al. 2024")
    assert ref.title is None
    assert ref.arxiv_id is None
    assert ref.doi is None


def test_parsed_doc_constructs_with_blocks_figures_tables_references():
    doc = ParsedDoc(
        paper_id="2506.01234",
        markdown="# Title\n\nSome prose.",
        blocks=[_make_block(0), _make_block(1)],
        figures=[],
        tables=[],
        references=[Reference(raw="Smith et al. 2024")],
        parser_id="mineru-1.x",
    )
    assert len(doc.blocks) == 2
    assert doc.blocks[0].index == 0


def test_parsed_doc_wrong_type_raises():
    with pytest.raises(ValidationError):
        ParsedDoc(
            paper_id="2506.01234",
            markdown="# Title",
            blocks="not-a-list",  # wrong type
            figures=[],
            tables=[],
            references=[],
            parser_id="mineru-1.x",
        )
