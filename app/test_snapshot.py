"""Tests for `app.snapshot` (T-DOC57) -- offline, no real GPU/vector-store service.

Mirrors house patterns: `migrations.migrate.migrate` builds a real (small) SQLite schema for the
`VACUUM INTO` tests (same tool `rag/document_store.py` uses to migrate a fresh db), and a small
fake vector-store client stands in for `rag.vector_index.VectorIndex` (same "inject the vendor
adapter, never construct/mock the real one in app/ tests" pattern as `app/test_benchmark.py`'s
`run_worker`/`query_gpu` seams).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.snapshot import (
    backup_blobs,
    backup_sqlite,
    backup_vector_store,
    default_backup_root,
    prune_old_snapshots,
    run_snapshot,
)
from contracts.config import Config
from migrations.migrate import migrate


def _base_config(**overrides) -> Config:
    data = {"focus_area_queries": ["causal inference"]}
    data.update(overrides)
    return Config(**data)


def _seeded_db(path: Path, n_papers: int) -> None:
    migrate(str(path))
    con = sqlite3.connect(str(path))
    for i in range(n_papers):
        con.execute(
            """
            INSERT INTO papers
                (paper_id, version, title, abstract, authors_json, categories_json,
                 published, updated, pdf_path, markdown_path, relevance_score)
            VALUES (?, 'v1', 't', 'a', '[]', '[]', '2026-01-01', '2026-01-01', 'u', 'm', 1.0)
            """,
            (f"paper-{i}",),
        )
    con.commit()
    con.close()


class _FakeVectorStore:
    """Records the call and writes a small fake snapshot file -- the offline stand-in for
    `rag.vector_index.VectorIndex.create_and_download_snapshot`."""

    def __init__(self, content: bytes = b"fake vector-store snapshot bytes"):
        self.calls: list[str] = []
        self._content = content

    def create_and_download_snapshot(self, dest_path: str) -> None:
        self.calls.append(dest_path)
        Path(dest_path).write_bytes(self._content)


class _FailingVectorStore:
    def create_and_download_snapshot(self, dest_path: str) -> None:
        raise RuntimeError("vector store unreachable")


# ---------------------------------------------------------------------------
# backup_sqlite -- VACUUM INTO against a real, read-only-opened temp DB
# ---------------------------------------------------------------------------


def test_backup_sqlite_copy_opens_and_has_the_same_row_count(tmp_path):
    db_path = tmp_path / "papers.db"
    _seeded_db(db_path, n_papers=3)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    manifest = backup_sqlite(str(db_path), dest_dir)

    dest_path = dest_dir / "papers.db"
    assert dest_path.exists()
    assert manifest["dest"] == "papers.db"
    assert manifest["row_counts"]["papers"] == 3
    assert manifest["bytes"] == dest_path.stat().st_size

    # the copy really does open and hold the same data, independent of the manifest's own claim
    copy = sqlite3.connect(str(dest_path))
    try:
        assert copy.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 3
    finally:
        copy.close()


def test_backup_sqlite_does_not_modify_the_source(tmp_path):
    db_path = tmp_path / "papers.db"
    _seeded_db(db_path, n_papers=2)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    backup_sqlite(str(db_path), dest_dir)

    con = sqlite3.connect(str(db_path))
    try:
        assert con.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 2
    finally:
        con.close()


# ---------------------------------------------------------------------------
# backup_blobs -- recursive copy
# ---------------------------------------------------------------------------


def test_backup_blobs_copies_every_file(tmp_path):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()
    (blob_dir / "a.md").write_text("paper a")
    (blob_dir / "b.md").write_text("paper bb")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    manifest = backup_blobs(str(blob_dir), dest_dir)

    copied = dest_dir / "blobs"
    assert (copied / "a.md").read_text() == "paper a"
    assert (copied / "b.md").read_text() == "paper bb"
    assert manifest["file_count"] == 2
    assert manifest["bytes"] == len("paper a") + len("paper bb")


# ---------------------------------------------------------------------------
# backup_vector_store -- delegates to the injected (fake) adapter
# ---------------------------------------------------------------------------


def test_backup_vector_store_calls_create_and_download_and_reports_the_written_file(tmp_path):
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    fake = _FakeVectorStore(content=b"12345")

    manifest = backup_vector_store(fake, "papers", dest_dir)

    assert fake.calls == [str(dest_dir / "papers.snapshot")]
    assert manifest == {"collection": "papers", "dest": "papers.snapshot", "bytes": 5}
    assert (dest_dir / "papers.snapshot").read_bytes() == b"12345"


def test_backup_vector_store_raises_if_the_adapter_writes_nothing(tmp_path):
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    class _SilentVectorStore:
        def create_and_download_snapshot(self, dest_path: str) -> None:
            pass  # doesn't actually write the file -- a bug the caller must not paper over

    with pytest.raises(FileNotFoundError):
        backup_vector_store(_SilentVectorStore(), "papers", dest_dir)


# ---------------------------------------------------------------------------
# run_snapshot -- atomic .partial -> final rename, manifest, pruning
# ---------------------------------------------------------------------------


def _cfg_with_real_sources(tmp_path, n_papers=2) -> Config:
    db_path = tmp_path / "source" / "papers.db"
    db_path.parent.mkdir(parents=True)
    _seeded_db(db_path, n_papers=n_papers)

    blob_dir = tmp_path / "source" / "blobs"
    blob_dir.mkdir()
    (blob_dir / "p.md").write_text("content")

    return _base_config(db_path=str(db_path), blob_dir=str(blob_dir), collection="papers")


def test_run_snapshot_writes_all_three_artifacts_and_a_manifest_then_renames_to_final(tmp_path):
    cfg = _cfg_with_real_sources(tmp_path)
    backup_root = tmp_path / "backups"
    fake_vs = _FakeVectorStore()
    ts = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)

    final_dir = run_snapshot(cfg, backup_root, keep=7, vector_index=fake_vs, now=ts)

    assert final_dir == backup_root / "snapshot-20260717T120000Z"
    assert final_dir.exists()
    assert not (backup_root / "snapshot-20260717T120000Z.partial").exists()
    assert (final_dir / "papers.db").exists()
    assert (final_dir / "blobs" / "p.md").exists()
    assert (final_dir / "papers.snapshot").exists()

    manifest = json.loads((final_dir / "manifest.json").read_text())
    assert manifest["timestamp_utc"] == "20260717T120000Z"
    assert manifest["sqlite"]["row_counts"]["papers"] == 2
    assert manifest["blobs"]["file_count"] == 1
    assert manifest["vector_store"]["collection"] == "papers"


def test_run_snapshot_leaves_partial_dir_and_raises_when_the_vector_store_fails(tmp_path):
    cfg = _cfg_with_real_sources(tmp_path)
    backup_root = tmp_path / "backups"
    ts = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(RuntimeError, match="vector store unreachable"):
        run_snapshot(cfg, backup_root, keep=7, vector_index=_FailingVectorStore(), now=ts)

    partial_dir = backup_root / "snapshot-20260717T120000Z.partial"
    final_dir = backup_root / "snapshot-20260717T120000Z"
    assert partial_dir.exists(), ".partial dir must survive a mid-run failure for inspection"
    assert not final_dir.exists(), "no final dir may exist unless every artifact succeeded"
    # the two artifacts that DID complete before the failure are still there, in the .partial dir
    assert (partial_dir / "papers.db").exists()
    assert (partial_dir / "blobs" / "p.md").exists()
    assert not (partial_dir / "papers.snapshot").exists()


def test_run_snapshot_prunes_to_the_newest_keep_snapshots_across_repeated_runs(tmp_path):
    cfg = _cfg_with_real_sources(tmp_path)
    backup_root = tmp_path / "backups"
    timestamps = [
        datetime(2026, 7, 15, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 16, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 17, 0, 0, 0, tzinfo=timezone.utc),
    ]
    for ts in timestamps:
        run_snapshot(cfg, backup_root, keep=2, vector_index=_FakeVectorStore(), now=ts)

    remaining = sorted(p.name for p in backup_root.iterdir())
    assert remaining == ["snapshot-20260716T000000Z", "snapshot-20260717T000000Z"], (
        "the oldest of the three runs must have been pruned, keep=2 kept"
    )


# ---------------------------------------------------------------------------
# prune_old_snapshots -- unit-level, never touches .partial dirs
# ---------------------------------------------------------------------------


def test_prune_old_snapshots_keeps_only_the_newest_n(tmp_path):
    names = [
        "snapshot-20260101T000000Z", "snapshot-20260102T000000Z", "snapshot-20260103T000000Z",
    ]
    for name in names:
        (tmp_path / name).mkdir()
    (tmp_path / "snapshot-20260104T000000Z.partial").mkdir()  # a crashed run -- must survive

    prune_old_snapshots(tmp_path, keep=1)

    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == ["snapshot-20260103T000000Z", "snapshot-20260104T000000Z.partial"]


def test_prune_old_snapshots_is_a_no_op_when_fewer_than_keep_exist(tmp_path):
    (tmp_path / "snapshot-20260101T000000Z").mkdir()

    prune_old_snapshots(tmp_path, keep=7)

    assert [p.name for p in tmp_path.iterdir()] == ["snapshot-20260101T000000Z"]


# ---------------------------------------------------------------------------
# default_backup_root
# ---------------------------------------------------------------------------


def test_default_backup_root_is_a_backups_dir_next_to_db_path(tmp_path):
    cfg = _base_config(db_path=str(tmp_path / "data" / "papers.db"))
    assert default_backup_root(cfg) == (tmp_path / "data" / "backups").resolve()
