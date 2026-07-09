"""Sibling test for contracts/provenance.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

import pytest
from pydantic import ValidationError

from contracts.provenance import Anchor, Block

VALID_BBOX = (10.0, 20.0, 110.0, 220.0)


def _make_anchor(**overrides):
    fields = dict(
        paper_id="2506.01234",
        block_id="2506.01234:b0",
        page=0,
        bbox=VALID_BBOX,
        snippet="This is the first two hundred characters of the block, verbatim.",
        section_path="3. Method > 3.2 Estimator",
    )
    fields.update(overrides)
    return Anchor(**fields)


def _make_block(**overrides):
    fields = dict(
        block_id="2506.01234:b0",
        paper_id="2506.01234",
        text="Some prose.",
        type="prose",
        page=0,
        bbox=VALID_BBOX,
        section_path="3. Method",
        index=0,
    )
    fields.update(overrides)
    return Block(**fields)


def test_anchor_constructs_with_valid_fields():
    anchor = _make_anchor()
    assert anchor.paper_id == "2506.01234"
    assert anchor.bbox == VALID_BBOX


def test_anchor_is_frozen():
    anchor = _make_anchor()
    with pytest.raises(ValidationError):
        anchor.page = 1  # type: ignore[misc]


def test_anchor_wrong_type_raises():
    with pytest.raises(ValidationError):
        _make_anchor(page="not-an-int")


def test_anchor_negative_page_raises():
    with pytest.raises(ValidationError):
        _make_anchor(page=-1)


def test_anchor_bbox_wrong_arity_raises():
    with pytest.raises(ValidationError):
        _make_anchor(bbox=(0.0, 0.0, 1.0))  # only 3 elements, Bbox needs 4


def test_block_constructs_with_valid_fields_and_accepts_every_block_type():
    for block_type in ("prose", "equation", "code", "table", "caption"):
        block = _make_block(type=block_type)
        assert block.type == block_type


def test_block_invalid_type_literal_raises():
    with pytest.raises(ValidationError):
        _make_block(type="not-a-real-type")


def test_block_wrong_type_raises():
    with pytest.raises(ValidationError):
        _make_block(index="zero")
