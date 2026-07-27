"""Tests for app/delete_docs.py -- zero-GPU, zero-network (TEST-STRATEGY)."""

import pytest

from app.delete_docs import _parse_args, main


class _RecordingOrchestrator:
    def __init__(self):
        self.deleted: list[str] = []

    def delete_paper(self, paper_id: str) -> None:
        self.deleted.append(paper_id)


def test_parse_args_takes_one_or_more_paper_ids():
    args = _parse_args(["2401.00001", "local:f0929288d4f3"])
    assert args.paper_ids == ["2401.00001", "local:f0929288d4f3"]


def test_parse_args_requires_at_least_one_id():
    with pytest.raises(SystemExit):
        _parse_args([])


def test_main_deletes_every_id_in_order(monkeypatch):
    orch = _RecordingOrchestrator()
    monkeypatch.setattr("app.delete_docs._build", lambda: orch)

    rc = main(["--yes", "2401.00001", "local:f0929288d4f3"])

    assert rc == 0
    assert orch.deleted == ["2401.00001", "local:f0929288d4f3"]


def test_main_without_yes_refuses_and_deletes_nothing(monkeypatch):
    # Deletion is irreversible and there is no undo -- an unattended run must not proceed.
    orch = _RecordingOrchestrator()
    monkeypatch.setattr("app.delete_docs._build", lambda: orch)

    rc = main(["2401.00001"])

    assert rc == 1
    assert orch.deleted == []


class _FailingOrchestrator:
    """Raises on one specific id, recording every id it was actually asked to delete."""

    def __init__(self, failing_id: str):
        self.failing_id = failing_id
        self.attempted: list[str] = []

    def delete_paper(self, paper_id: str) -> None:
        self.attempted.append(paper_id)
        if paper_id == self.failing_id:
            raise RuntimeError("boom")


def test_main_partial_failure_returns_2_and_stops_at_the_failing_id(monkeypatch):
    orch = _FailingOrchestrator(failing_id="bad")
    monkeypatch.setattr("app.delete_docs._build", lambda: orch)

    rc = main(["--yes", "2401.00001", "bad", "2401.00002"])

    assert rc == 2
    # ids before the failure were attempted, the failing id was attempted, the id after was not.
    assert orch.attempted == ["2401.00001", "bad"]
