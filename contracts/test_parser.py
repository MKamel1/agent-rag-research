"""Sibling test for contracts/parser.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

import json

import pytest
from pydantic import ValidationError

from contracts.parser import Figure, ParsedDoc, Reference, TableItem


def test_figure_constructs_and_defaults_vlm_description_to_none(valid_bbox):
    fig = Figure(
        paper_id="2506.01234",
        image_path="/blobs/2506.01234/fig1.png",
        caption="Figure 1: overview",
        page=1,
        bbox=valid_bbox,
    )
    assert fig.vlm_description is None  # ALWAYS None in V0


def test_figure_wrong_type_raises(valid_bbox):
    with pytest.raises(ValidationError):
        Figure(
            paper_id="2506.01234",
            image_path="/blobs/fig1.png",
            caption="c",
            page="one",  # wrong type
            bbox=valid_bbox,
        )


def test_figure_bbox_survives_json_round_trip(valid_bbox):
    # Same fix as Anchor/Block (contracts/provenance.py's Bbox BeforeValidator) — Figure imports
    # the same Bbox alias, so it must benefit too, not just the models directly inside
    # provenance.py.
    valid_figure_dict = dict(
        paper_id="2506.01234",
        image_path="/blobs/2506.01234/fig1.png",
        caption="Figure 1: overview",
        page=1,
        bbox=valid_bbox,
    )
    round_tripped = json.loads(json.dumps(valid_figure_dict))
    assert isinstance(round_tripped["bbox"], list)

    fig = Figure(**round_tripped)

    assert fig.bbox == valid_bbox
    assert isinstance(fig.bbox, tuple)


def test_table_item_constructs(valid_bbox):
    table = TableItem(
        paper_id="2506.01234",
        markdown="| a | b |\n|---|---|\n| 1 | 2 |",
        caption="Table 1",
        page=2,
        bbox=valid_bbox,
    )
    assert "a" in table.markdown


def test_reference_optional_fields_default_to_none():
    ref = Reference(raw="Smith et al. 2024")
    assert ref.title is None
    assert ref.arxiv_id is None
    assert ref.doi is None


def test_parsed_doc_constructs_with_blocks_figures_tables_references(make_block):
    doc = ParsedDoc(
        paper_id="2506.01234",
        markdown="# Title\n\nSome prose.",
        blocks=[make_block(index=0), make_block(index=1, block_id="2506.01234:b1")],
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
