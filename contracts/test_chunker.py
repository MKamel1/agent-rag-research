"""Sibling test for contracts/chunker.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

import pytest
from pydantic import ValidationError

from contracts.chunker import Chunk
from contracts.provenance import Anchor

VALID_BBOX = (0.0, 0.0, 100.0, 200.0)


def _make_anchor():
    return Anchor(
        paper_id="2506.01234",
        block_id="2506.01234:b0",
        page=0,
        bbox=VALID_BBOX,
        snippet="Some verbatim text.",
        section_path="3. Method",
    )


def test_constructs_with_required_fields_and_contextual_header_defaults_to_none():
    chunk = Chunk(
        chunk_id="2506.01234:c0",
        paper_id="2506.01234",
        text="Some chunk text.",
        anchor=_make_anchor(),
        section_path="3. Method",
        parent_id="2506.01234:b0",
    )
    assert chunk.contextual_header is None  # ALWAYS None in V0


def test_parent_id_is_required_but_may_be_explicitly_none():
    # parent_id has no default in DATA-CONTRACTS.md -> must be passed, even if the value is None.
    chunk = Chunk(
        chunk_id="2506.01234:c0",
        paper_id="2506.01234",
        text="t",
        anchor=_make_anchor(),
        section_path="3. Method",
        parent_id=None,
    )
    assert chunk.parent_id is None


def test_omitting_parent_id_entirely_raises():
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id="2506.01234:c0",
            paper_id="2506.01234",
            text="t",
            anchor=_make_anchor(),
            section_path="3. Method",
        )


def test_wrong_type_raises():
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id="2506.01234:c0",
            paper_id="2506.01234",
            text="t",
            anchor="not-an-anchor",  # wrong type
            section_path="3. Method",
            parent_id=None,
        )
