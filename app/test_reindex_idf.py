"""Tests for `app.reindex_idf` (OG-27) -- offline, no real GPU/vector-store service.

Same "inject the vendor adapter, never construct/mock the real one in app/ tests" pattern as
`app/test_snapshot.py`/`app/test_benchmark.py`: a small fake stands in for
`rag.vector_index.VectorIndex`, exercising `run_reindex_idf`'s own logic (the snapshot-first
gate, the point-count invariant, the IDF post-check, the idempotent no-op, `--dry-run`) without
a live collection. `run_snapshot`'s own SQLite/blobs machinery is real (same helpers
`app/test_snapshot.py` uses) since the auto-snapshot path genuinely calls it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.reindex_idf import _verify_snapshot_present, run_reindex_idf
from contracts.config import Config
from contracts.errors import ContractError
from migrations.migrate import migrate

_TS = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)


def _base_config(**overrides) -> Config:
    data = {"focus_area_queries": ["causal inference"]}
    data.update(overrides)
    return Config(**data)


def _seeded_sources(tmp_path: Path) -> Config:
    """A real (tiny) SQLite db + blob dir -- what `run_snapshot` needs to actually succeed on
    the auto-snapshot path, same recipe as `app/test_snapshot.py`'s `_cfg_with_real_sources`."""
    db_path = tmp_path / "source" / "papers.db"
    db_path.parent.mkdir(parents=True)
    migrate(str(db_path))
    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        INSERT INTO papers
            (paper_id, version, title, abstract, authors_json, categories_json,
             published, updated, pdf_path, markdown_path, relevance_score)
        VALUES ('p1', 'v1', 't', 'a', '[]', '[]', '2026-01-01', '2026-01-01', 'u', 'm', 1.0)
        """
    )
    con.commit()
    con.close()

    blob_dir = tmp_path / "source" / "blobs"
    blob_dir.mkdir()
    (blob_dir / "p1.md").write_text("content")

    return _base_config(db_path=str(db_path), blob_dir=str(blob_dir), collection="papers")


class _FakeVectorIndex:
    """Fake `VectorIndex` for `run_reindex_idf`: pre-set point count / IDF state, `rebuild()`
    flips the modifier on (and can be told to also drop points, to prove the mismatch gate).
    """

    def __init__(self, *, points, has_idf, points_after_rebuild=None, idf_after_rebuild=True):
        self._points = points
        self._has_idf = has_idf
        self._points_after_rebuild = (
            points if points_after_rebuild is None else points_after_rebuild
        )
        self._idf_after_rebuild = idf_after_rebuild
        self.rebuild_calls = 0
        self.snapshot_calls: list[str] = []

    def point_count(self) -> int:
        return self._points

    def has_idf_modifier(self) -> bool:
        return self._has_idf

    def rebuild(self) -> None:
        self.rebuild_calls += 1
        self._points = self._points_after_rebuild
        self._has_idf = self._idf_after_rebuild

    def create_and_download_snapshot(self, dest_path: str) -> None:
        self.snapshot_calls.append(dest_path)
        Path(dest_path).write_bytes(b"fake vector-store snapshot bytes")


# ---------------------------------------------------------------------------
# idempotent no-op -- already has the modifier
# ---------------------------------------------------------------------------


def test_already_has_idf_modifier_is_a_noop_no_rebuild_no_snapshot(tmp_path):
    cfg = _base_config()
    vi = _FakeVectorIndex(points=100, has_idf=True)

    result = run_reindex_idf(
        cfg, vi, collection="papers", backup_root=tmp_path / "backups",
        dry_run=False, have_snapshot=False, keep=7, now=_TS,
    )

    assert "already has the IDF modifier" in result
    assert "100" in result
    assert vi.rebuild_calls == 0
    assert vi.snapshot_calls == []
    assert not (tmp_path / "backups").exists()


# ---------------------------------------------------------------------------
# --dry-run -- no mutation of any kind
# ---------------------------------------------------------------------------


def test_dry_run_reports_and_mutates_nothing(tmp_path):
    cfg = _base_config()
    vi = _FakeVectorIndex(points=50, has_idf=False)

    result = run_reindex_idf(
        cfg, vi, collection="papers", backup_root=tmp_path / "backups",
        dry_run=True, have_snapshot=False, keep=7, now=_TS,
    )

    assert "DRY RUN" in result
    assert "50" in result
    assert "NOT set" in result
    assert vi.rebuild_calls == 0
    assert vi.snapshot_calls == []
    assert not (tmp_path / "backups").exists()


def test_dry_run_with_i_have_a_snapshot_still_mutates_nothing_and_skips_verification(tmp_path):
    # Dry-run must short-circuit before the snapshot-verification gate too -- no need for a real
    # snapshot to be present just to preview what a real run would do.
    cfg = _base_config()
    vi = _FakeVectorIndex(points=50, has_idf=False)
    backup_root = tmp_path / "backups"  # deliberately does not exist

    result = run_reindex_idf(
        cfg, vi, collection="papers", backup_root=backup_root,
        dry_run=True, have_snapshot=True, keep=7, now=_TS,
    )

    assert "DRY RUN" in result
    assert vi.rebuild_calls == 0


# ---------------------------------------------------------------------------
# snapshot-first gate
# ---------------------------------------------------------------------------


def test_i_have_a_snapshot_refuses_when_no_snapshot_is_actually_present(tmp_path):
    cfg = _base_config()
    vi = _FakeVectorIndex(points=10, has_idf=False)
    backup_root = tmp_path / "backups"  # empty -- nothing was ever snapshotted

    with pytest.raises(ContractError, match="no completed snapshot"):
        run_reindex_idf(
            cfg, vi, collection="papers", backup_root=backup_root,
            dry_run=False, have_snapshot=True, keep=7, now=_TS,
        )

    assert vi.rebuild_calls == 0


def test_i_have_a_snapshot_refuses_when_snapshot_is_for_a_different_collection(tmp_path):
    cfg = _base_config()
    vi = _FakeVectorIndex(points=10, has_idf=False)
    backup_root = tmp_path / "backups"
    snap_dir = backup_root / "snapshot-20260717T000000Z"
    snap_dir.mkdir(parents=True)
    (snap_dir / "other_collection.snapshot").write_bytes(b"data")
    manifest = {
        "vector_store": {"collection": "other_collection", "dest": "other_collection.snapshot"}
    }
    (snap_dir / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ContractError, match="no completed snapshot"):
        run_reindex_idf(
            cfg, vi, collection="papers", backup_root=backup_root,
            dry_run=False, have_snapshot=True, keep=7, now=_TS,
        )
    assert vi.rebuild_calls == 0


def test_i_have_a_snapshot_proceeds_when_a_real_snapshot_is_present_and_takes_no_new_one(tmp_path):
    cfg = _base_config()
    vi = _FakeVectorIndex(points=10, has_idf=False)
    backup_root = tmp_path / "backups"
    snap_dir = backup_root / "snapshot-20260717T000000Z"
    snap_dir.mkdir(parents=True)
    (snap_dir / "papers.snapshot").write_bytes(b"data")
    (snap_dir / "manifest.json").write_text(
        json.dumps({"vector_store": {"collection": "papers", "dest": "papers.snapshot"}})
    )

    result = run_reindex_idf(
        cfg, vi, collection="papers", backup_root=backup_root,
        dry_run=False, have_snapshot=True, keep=7, now=_TS,
    )

    assert "verified existing snapshot" in result
    assert vi.rebuild_calls == 1
    assert vi.snapshot_calls == []  # no NEW snapshot taken -- the existing one was reused
    # backup_root must still contain exactly the one pre-existing snapshot dir, nothing new
    assert [p.name for p in backup_root.iterdir()] == ["snapshot-20260717T000000Z"]


def test_verify_snapshot_present_rejects_a_zero_byte_snapshot_file(tmp_path):
    backup_root = tmp_path / "backups"
    snap_dir = backup_root / "snapshot-20260717T000000Z"
    snap_dir.mkdir(parents=True)
    (snap_dir / "papers.snapshot").touch()  # exists but empty
    (snap_dir / "manifest.json").write_text(
        json.dumps({"vector_store": {"collection": "papers", "dest": "papers.snapshot"}})
    )

    with pytest.raises(ContractError, match="no completed snapshot"):
        _verify_snapshot_present(backup_root, "papers")


def test_default_flow_takes_a_fresh_snapshot_before_rebuilding(tmp_path):
    cfg = _seeded_sources(tmp_path)
    vi = _FakeVectorIndex(points=10, has_idf=False)
    backup_root = tmp_path / "backups"

    result = run_reindex_idf(
        cfg, vi, collection="papers", backup_root=backup_root,
        dry_run=False, have_snapshot=False, keep=7, now=_TS,
    )

    assert "took a fresh snapshot" in result
    assert vi.rebuild_calls == 1
    assert len(vi.snapshot_calls) == 1
    final_dir = backup_root / "snapshot-20260717T120000Z"
    assert final_dir.exists()
    assert (final_dir / "papers.db").exists()
    assert (final_dir / "blobs" / "p1.md").exists()
    assert (final_dir / "papers.snapshot").exists()


# ---------------------------------------------------------------------------
# point-count invariant (OG-28-style)
# ---------------------------------------------------------------------------


def test_point_count_mismatch_after_rebuild_raises_and_does_not_report_success(tmp_path):
    cfg = _seeded_sources(tmp_path)
    vi = _FakeVectorIndex(points=10, has_idf=False, points_after_rebuild=9)
    backup_root = tmp_path / "backups"

    with pytest.raises(ContractError, match="POINT COUNT MISMATCH"):
        run_reindex_idf(
            cfg, vi, collection="papers", backup_root=backup_root,
            dry_run=False, have_snapshot=False, keep=7, now=_TS,
        )
    assert vi.rebuild_calls == 1  # rebuild did run -- the mismatch is caught AFTER, not prevented


# ---------------------------------------------------------------------------
# IDF post-check
# ---------------------------------------------------------------------------


def test_idf_modifier_still_missing_after_rebuild_raises(tmp_path):
    cfg = _seeded_sources(tmp_path)
    vi = _FakeVectorIndex(points=10, has_idf=False, idf_after_rebuild=False)
    backup_root = tmp_path / "backups"

    with pytest.raises(ContractError, match="IDF modifier is still NOT set"):
        run_reindex_idf(
            cfg, vi, collection="papers", backup_root=backup_root,
            dry_run=False, have_snapshot=False, keep=7, now=_TS,
        )
    assert vi.rebuild_calls == 1


# ---------------------------------------------------------------------------
# success path, end to end
# ---------------------------------------------------------------------------


def test_successful_rebuild_reports_points_preserved_and_idf_set(tmp_path):
    cfg = _seeded_sources(tmp_path)
    vi = _FakeVectorIndex(points=250, has_idf=False)
    backup_root = tmp_path / "backups"

    result = run_reindex_idf(
        cfg, vi, collection="papers", backup_root=backup_root,
        dry_run=False, have_snapshot=False, keep=7, now=_TS,
    )

    assert "rebuilt collection 'papers'" in result
    assert "250" in result
    assert "IDF modifier now set" in result
    assert vi.rebuild_calls == 1
