"""Sibling test for contracts/vector_index.py (T-F1 DoD: imported by a trivial test; constructing
one with a wrong type raises).
"""

from datetime import date

import pytest
from pydantic import ValidationError

from contracts.vector_index import Hit, SearchFilters, VectorPayload


def test_hit_constructs_with_valid_fields():
    hit = Hit(id="2506.01234:c0", kind="chunk", score=0.42)
    assert hit.kind == "chunk"


def test_hit_kind_must_be_a_valid_literal():
    with pytest.raises(ValidationError):
        Hit(id="x", kind="paragraph", score=0.1)  # not "chunk" or "summary"


def test_hit_wrong_type_raises():
    with pytest.raises(ValidationError):
        Hit(id="x", kind="chunk", score="high")


def test_search_filters_all_fields_optional_and_default_to_none():
    filters = SearchFilters()
    assert filters.categories is None
    assert filters.published_after is None
    assert filters.published_before is None
    assert filters.kind is None


def test_search_filters_constructs_with_explicit_values():
    filters = SearchFilters(
        categories=["cs.LG", "stat.ME"],
        published_after=date(2026, 1, 1),
        published_before=date(2026, 6, 1),
        kind="summary",
    )
    assert filters.kind == "summary"


def test_search_filters_wrong_type_raises():
    with pytest.raises(ValidationError):
        SearchFilters(published_after="not-a-date")


def test_vector_payload_is_a_plain_dict_shape():
    # VectorPayload is a TypedDict (DATA-CONTRACTS.md defines it that way) — it's exactly the
    # dict handed to the vector store client's payload= argument, so it behaves as a normal dict
    # at runtime.
    payload: VectorPayload = {
        "paper_id": "2506.01234",
        "kind": "chunk",
        "section_path": "3. Method",
        "categories": ["cs.LG"],
        "published": "2026-06-01",
        "embedding_version": "1.0.0",
    }
    assert isinstance(payload, dict)
    assert payload["kind"] == "chunk"
