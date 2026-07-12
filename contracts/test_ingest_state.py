"""Sibling test for contracts/ingest_state.py (T-F1 DoD: imported by a trivial test;
constructing one with a wrong type raises). `merge`'s "overlay non-None fields, never un-set an
already-known field" rule is this contract's one piece of behaviour (not just a shape), so it's
covered directly here rather than only indirectly via `rag/test_ingest_state_sqlite.py`'s adapter
round-trip.
"""

import pytest
from pydantic import ValidationError

from contracts.ingest_state import Checkpoint, CheckpointArtifacts


def test_every_field_defaults_to_none():
    artifacts = CheckpointArtifacts()
    assert artifacts.parsed is None
    assert artifacts.chunks is None
    assert artifacts.summary_text is None
    assert artifacts.relevance_score is None


def test_constructs_with_a_partial_set_of_fields():
    artifacts = CheckpointArtifacts(summary_text="A short summary.")
    assert artifacts.summary_text == "A short summary."
    assert artifacts.parsed is None


def test_wrong_type_raises():
    with pytest.raises(ValidationError):
        CheckpointArtifacts(summary_text=123)  # wrong type (strict=True)


def test_unknown_field_raises():
    with pytest.raises(ValidationError):
        CheckpointArtifacts(claims="not a real field yet")  # extra="forbid"


def test_merge_overlays_only_non_none_fields():
    original = CheckpointArtifacts(summary_text="first draft")
    update = CheckpointArtifacts(relevance_score=0.5)

    merged = original.merge(update)

    assert merged.summary_text == "first draft"  # kept -- update left it None
    assert merged.relevance_score == 0.5  # overlaid


def test_merge_overwrites_a_field_present_in_both():
    original = CheckpointArtifacts(summary_text="first draft")
    update = CheckpointArtifacts(summary_text="final draft")

    merged = original.merge(update)

    assert merged.summary_text == "final draft"


def test_merge_with_an_all_none_update_returns_the_original_unchanged():
    original = CheckpointArtifacts(summary_text="first draft")

    merged = original.merge(CheckpointArtifacts())

    assert merged == original


def test_checkpoint_holds_stage_and_artifacts():
    artifacts = CheckpointArtifacts(summary_text="A short summary.")
    checkpoint = Checkpoint(stage="summarized", artifacts=artifacts)

    assert checkpoint.stage == "summarized"
    assert checkpoint.artifacts is artifacts
