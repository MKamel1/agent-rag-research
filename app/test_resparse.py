"""Tests for `app.resparse` -- offline; a fake stands in for `rag.vector_index.VectorIndex`
(same injection pattern as `app/test_reindex_idf.py`). The adapter's own sparse-only write
behaviour is tested in `rag/test_vector_index.py`."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from app import resparse
from contracts.errors import ContractError


def _report(changed=0, scanned=2, dry_run=True):
    return SimpleNamespace(
        dry_run=dry_run, scanned=scanned, changed=changed, unchanged=scanned - changed,
        stored_sparse_missing=0, skipped={"no_text": 1}, scanned_by_kind={"chunk": scanned},
        changed_by_kind={"chunk": changed},
    )


class _FakeIndex:
    def __init__(self, stale=1, count_after=None):
        self.calls = []
        self._count = 10
        self._count_after = count_after
        self._stale = stale

    def point_count(self):
        if self._count_after is not None and "write" in self.calls:
            return self._count_after
        return self._count

    def resparse(self, collection=None, *, batch_size=None, dry_run=False):
        self.calls.append("dry" if dry_run else "write")
        if not dry_run:
            self._stale = 0
        return _report(self._stale, dry_run=dry_run)

    def sample_sparse_staleness(self, n, collection=None):
        self.calls.append(f"sample{n}")
        return _report(self._stale, scanned=n)


def _run(index, tmp_path, **kw):
    args = dict(
        collection="papers_clone", apply=False, backup_root=lambda: tmp_path,
        have_snapshot=False, target_is_clone=False, clone_of=None,
        count_of=lambda name: 10,
    )
    args.update(kw)
    return resparse.run_resparse(index, **args)


def _snapshot(tmp_path, collection):
    d = tmp_path / "snapshot-20261110T000000Z"
    d.mkdir()
    (d / "vs.snapshot").write_bytes(b"x")
    (d / "manifest.json").write_text(
        json.dumps({"vector_store": {"collection": collection, "dest": "vs.snapshot"}})
    )


def test_default_is_dry_run_and_writes_nothing(tmp_path):
    index = _FakeIndex()
    out = _run(index, tmp_path)
    assert "DRY RUN" in out and "would change=1" in out
    assert index.calls == ["dry"]


def test_apply_without_guard_is_refused_and_nothing_is_written(tmp_path):
    index = _FakeIndex()
    with pytest.raises(ContractError, match="refusing to write"):
        _run(index, tmp_path, apply=True)
    assert index.calls == []


def test_apply_with_snapshot_flag_still_checks_one_exists(tmp_path):
    index = _FakeIndex()
    with pytest.raises(ContractError, match="not satisfied"):
        _run(index, tmp_path, apply=True, have_snapshot=True)
    assert index.calls == []
    _snapshot(tmp_path, "papers_clone")
    out = _run(index, tmp_path, apply=True, have_snapshot=True)
    assert "APPLIED" in out and "write" in index.calls


def test_apply_on_a_clone_needs_matching_source_and_point_count(tmp_path):
    with pytest.raises(ContractError, match="DIFFERENT"):
        _run(_FakeIndex(), tmp_path, apply=True, target_is_clone=True)
    with pytest.raises(ContractError, match="DIFFERENT"):
        _run(_FakeIndex(), tmp_path, apply=True, target_is_clone=True, clone_of="papers_clone")
    index = _FakeIndex()
    with pytest.raises(ContractError, match="not a complete clone"):
        _run(
            index, tmp_path, apply=True, target_is_clone=True, clone_of="papers",
            count_of=lambda n: 10 if n == "papers" else 9,
        )
    assert index.calls == []
    assert "APPLIED" in _run(index, tmp_path, apply=True, target_is_clone=True, clone_of="papers")


def test_point_count_change_raises(tmp_path):
    index = _FakeIndex(count_after=9)
    with pytest.raises(ContractError, match="POINT COUNT MISMATCH"):
        _run(index, tmp_path, apply=True, target_is_clone=True, clone_of="papers")


def test_post_apply_sample_must_be_clean(tmp_path):
    index = _FakeIndex()
    index.resparse = lambda collection=None, **kw: (index.calls.append("write"), _report(1))[1]
    with pytest.raises(ContractError, match="still stale"):
        _run(index, tmp_path, apply=True, target_is_clone=True, clone_of="papers")


def test_verify_sample_is_read_only(tmp_path):
    index = _FakeIndex()
    out = _run(index, tmp_path, verify_sample=50)
    assert "1/50" in out and index.calls == ["sample50"]
    with pytest.raises(ContractError, match="read-only"):
        _run(index, tmp_path, verify_sample=5, apply=True)


def test_collection_is_required_on_the_command_line(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["resparse"])
    with pytest.raises(SystemExit) as e:
        resparse._parse_args()
    assert e.value.code == 2
    assert "--collection" in capsys.readouterr().err


def test_apply_and_dry_run_are_mutually_exclusive(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["resparse", "--collection", "c", "--apply", "--dry-run"])
    with pytest.raises(SystemExit):
        resparse._parse_args()
