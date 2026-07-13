"""Tests for FakeIngestState (T-F4-style fake) — upsert/merge semantics, `done` clears artifacts,
quarantine removes the row. Mirrors the real `SqliteIngestState` contract these tests exercise
against a plain in-memory dict instead of a schema (rag/ingest_state_sqlite.py)."""

from contracts.ingest_state import CheckpointArtifacts
from rag.fakes.fake_ingest_state import FakeIngestState


def test_get_returns_none_for_unknown_paper():
    state = FakeIngestState()
    assert state.get("2506.01234") is None


def test_checkpoint_upserts_stage_and_artifacts():
    state = FakeIngestState()
    state.checkpoint("2506.01234", "parsed", CheckpointArtifacts(parsed=None))
    row = state.get("2506.01234")
    assert row.stage == "parsed"


def test_checkpoint_merges_artifacts_across_calls_without_unsetting_earlier_fields():
    state = FakeIngestState()
    state.checkpoint("2506.01234", "summarized", CheckpointArtifacts(summary_text="a summary"))
    state.checkpoint("2506.01234", "embedded", CheckpointArtifacts(relevance_score=0.9))
    row = state.get("2506.01234")
    assert row.stage == "embedded"
    assert row.artifacts.summary_text == "a summary"
    assert row.artifacts.relevance_score == 0.9


def test_checkpoint_with_no_artifacts_does_not_unset_earlier_fields():
    state = FakeIngestState()
    state.checkpoint("2506.01234", "summarized", CheckpointArtifacts(summary_text="a summary"))
    state.checkpoint("2506.01234", "embedded")
    row = state.get("2506.01234")
    assert row.artifacts.summary_text == "a summary"


def test_reaching_done_clears_artifacts():
    state = FakeIngestState()
    state.checkpoint("2506.01234", "embedded", CheckpointArtifacts(summary_text="a summary"))
    state.checkpoint("2506.01234", "done")
    row = state.get("2506.01234")
    assert row.stage == "done"
    assert row.artifacts == CheckpointArtifacts()


def test_quarantine_removes_the_row_and_records_it():
    state = FakeIngestState()
    state.checkpoint("2506.01234", "parsed")
    error = ValueError("unparseable")
    state.quarantine("2506.01234", "parsed", error)
    assert state.get("2506.01234") is None
    assert state.quarantined["2506.01234"] == ("parsed", error)


def test_stage_of_reflects_current_stage_and_none_when_unknown():
    state = FakeIngestState()
    assert state.stage_of("2506.01234") is None
    state.checkpoint("2506.01234", "chunked")
    assert state.stage_of("2506.01234") == "chunked"
