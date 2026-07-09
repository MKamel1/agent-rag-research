"""Sibling test for contracts/provenance.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

import json

import pytest
from pydantic import ValidationError

from contracts.provenance import Anchor


def test_anchor_constructs_with_valid_fields(make_anchor, valid_bbox):
    anchor = make_anchor()
    assert anchor.paper_id == "2506.01234"
    assert anchor.bbox == valid_bbox


def test_anchor_is_frozen(make_anchor):
    anchor = make_anchor()
    with pytest.raises(ValidationError):
        anchor.page = 1  # type: ignore[misc]


def test_anchor_wrong_type_raises(make_anchor):
    with pytest.raises(ValidationError):
        make_anchor(page="not-an-int")


def test_anchor_negative_page_raises(make_anchor):
    with pytest.raises(ValidationError):
        make_anchor(page=-1)


def test_anchor_bbox_wrong_arity_raises(make_anchor):
    with pytest.raises(ValidationError):
        make_anchor(bbox=(0.0, 0.0, 1.0))  # only 3 elements, Bbox needs 4


def test_anchor_bbox_wrong_arity_as_list_still_raises(make_anchor):
    # The list-coercion BeforeValidator (contracts/provenance.py) fixes the container type, not
    # arity — a wrong-length list must still be rejected by pydantic's normal strict validation.
    with pytest.raises(ValidationError):
        make_anchor(bbox=[0.0, 0.0, 1.0])


def test_bbox_survives_json_round_trip():
    # Regression test (PR #5 review): DATA-CONTRACTS.md's SQLite schema stores bbox/anchor as
    # JSON TEXT. json.loads() has no tuple type -- it always returns a list -- and Bbox's
    # strict=True tuple field used to reject that list outright. The BeforeValidator attached to
    # the Bbox type alias coerces it back to a tuple before the strict check runs.
    valid_anchor_dict = dict(
        paper_id="2506.01234",
        block_id="2506.01234:b0",
        page=0,
        bbox=(10.0, 20.0, 110.0, 220.0),
        snippet="Some verbatim text.",
        section_path="3. Method",
    )

    round_tripped = json.loads(json.dumps(valid_anchor_dict))
    assert isinstance(round_tripped["bbox"], list)  # confirms json.loads gives back a list

    anchor = Anchor(**round_tripped)

    assert anchor.bbox == (10.0, 20.0, 110.0, 220.0)
    assert isinstance(anchor.bbox, tuple)


def test_block_constructs_with_valid_fields_and_accepts_every_block_type(make_block):
    for block_type in ("prose", "equation", "code", "table", "caption"):
        block = make_block(type=block_type)
        assert block.type == block_type


def test_block_invalid_type_literal_raises(make_block):
    with pytest.raises(ValidationError):
        make_block(type="not-a-real-type")


def test_block_wrong_type_raises(make_block):
    with pytest.raises(ValidationError):
        make_block(index="zero")
