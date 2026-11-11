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
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db_guard import MissingDatabaseError
from app.snapshot import (
    SnapshotIntegrityError,
    backup_blobs,
    backup_sqlite,
    backup_vector_store,
    default_backup_root,
    main,
    prune_old_snapshots,
    run_snapshot,
    snapshot_sqlite_only,
    verify_snapshot,
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
    assert manifest["bytes"] == 5 and manifest["dest"] == "papers.snapshot"
    assert manifest["collection"] == "papers" and len(manifest["sha256"]) == 64
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


# ---------------------------------------------------------------------------
# main -- CLI entry point, T-DOC89 §4 resolved-path logging
# ---------------------------------------------------------------------------


class _FakeVectorIndexClass:
    """Stands in for `rag.vector_index.VectorIndex` itself (not just an instance) -- `main()`
    imports and constructs the real class locally, so this needs the same constructor signature,
    never a live connection to the real vector store (the real `VectorIndex.__init__` calls
    `_ensure_collection()`, a real network round trip)."""

    def __init__(self, host, port, collection_name, dim, hybrid_dense_weight=0.5):
        self.collection_name = collection_name

    def create_and_download_snapshot(self, dest_path: str) -> None:
        Path(dest_path).write_bytes(b"fake vector-store snapshot bytes")


def test_main_logs_resolved_paths(tmp_path, monkeypatch, caplog):
    # T-DOC89 §4: an operator standing in the wrong directory should see where this process
    # actually pointed, not guess. VectorIndex is faked (see _FakeVectorIndexClass) so this never
    # makes a real vector-store connection; sqlite/blob backup steps run for real against scratch
    # tmp paths only, never a real corpus.
    db_path = tmp_path / "papers.db"
    migrate(str(db_path))
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()
    cfg = _base_config(
        db_path=str(db_path), blob_dir=str(blob_dir), collection="papers",
        drop_in_dir=str(tmp_path / "drop_in"),
    )
    monkeypatch.setattr("app.snapshot.load_config", lambda path=None: cfg)
    monkeypatch.setattr("rag.vector_index.VectorIndex", _FakeVectorIndexClass)
    monkeypatch.setattr(sys, "argv", ["snapshot", "--backup-root", str(tmp_path / "backups")])
    caplog.set_level("INFO")

    main()

    assert f"db_path={cfg.db_path}" in caplog.text
    assert f"blob_dir={cfg.blob_dir}" in caplog.text
    assert f"collection={cfg.collection}" in caplog.text


# --- OP-3: integrity check, checksums, --verify, --sqlite-only ------------------------------------


def _full_snapshot(tmp_path) -> Path:
    cfg = _cfg_with_real_sources(tmp_path)
    return run_snapshot(
        cfg, tmp_path / "backups", keep=7, vector_index=_FakeVectorStore(),
        now=datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc),
    )


def test_manifest_records_quick_check_and_sha256_per_artifact(tmp_path):
    manifest = json.loads((_full_snapshot(tmp_path) / "manifest.json").read_text())
    assert manifest["sqlite"]["quick_check"] == "ok"
    assert len(manifest["sqlite"]["sha256"]) == 64
    assert list(manifest["blobs"]["sha256"]) == ["p.md"]
    assert len(manifest["vector_store"]["sha256"]) == 64


def test_corrupt_sqlite_copy_fails_the_snapshot_and_stays_partial(tmp_path, monkeypatch):
    monkeypatch.setattr("app.snapshot.sqlite_pragma_check", lambda *a, **k: "*** bad ***")
    cfg = _cfg_with_real_sources(tmp_path)
    with pytest.raises(SnapshotIntegrityError, match="quick_check"):
        run_snapshot(
            cfg, tmp_path / "backups", keep=7, vector_index=_FakeVectorStore(),
            now=datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc),
        )
    assert (tmp_path / "backups" / "snapshot-20260717T120000Z.partial").exists()
    assert not (tmp_path / "backups" / "snapshot-20260717T120000Z").exists()


def test_verify_passes_on_a_fresh_snapshot_and_detects_a_flipped_blob_byte(tmp_path):
    snap = _full_snapshot(tmp_path)
    report, problems = verify_snapshot(snap)
    assert problems == [] and "sqlite integrity_check: ok" in report
    (snap / "blobs" / "p.md").write_text("contenX")
    assert verify_snapshot(snap)[1] == ["sha256 mismatch: p.md"]


def test_verify_detects_a_tampered_vector_file_and_a_missing_file(tmp_path):
    snap = _full_snapshot(tmp_path)
    (snap / "papers.snapshot").write_bytes(b"other")
    (snap / "blobs" / "p.md").unlink()
    problems = verify_snapshot(snap)[1]
    assert "sha256 mismatch: papers.snapshot" in problems and "missing file: p.md" in problems


def test_verify_old_manifest_without_checksums_reports_a_note_not_a_failure(tmp_path):
    snap = _full_snapshot(tmp_path)
    manifest = json.loads((snap / "manifest.json").read_text())
    for key in ("sqlite", "blobs", "vector_store"):
        del manifest[key]["sha256"]
    (snap / "manifest.json").write_text(json.dumps(manifest))
    report, problems = verify_snapshot(snap)
    assert problems == [] and any("predates OP-3" in line for line in report)


def test_verify_checks_a_MANIFEST_sha256_directory(tmp_path):
    d = tmp_path / "vs-copy"
    (d / "collections").mkdir(parents=True)
    (d / "collections" / "a.json").write_text("{}")
    import hashlib

    digest = hashlib.sha256(b"{}").hexdigest()
    (d / "MANIFEST.sha256").write_text(f"{digest}  collections/a.json\n")
    assert verify_snapshot(d)[1] == []
    (d / "collections" / "a.json").write_text("{ }")
    assert verify_snapshot(d)[1] == ["sha256 mismatch: collections/a.json"]


def test_sqlite_only_writes_checked_copy_with_sha256_and_needs_no_vector_store(tmp_path):
    cfg = _cfg_with_real_sources(tmp_path, n_papers=3)
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    dest = snapshot_sqlite_only(cfg, tmp_path / "backups", now=now)

    assert dest.name == "papers.db.snapshot-20261110"
    assert (tmp_path / "backups" / "papers.db.snapshot-20261110.sha256").read_text().endswith(
        "  papers.db.snapshot-20261110\n"
    )
    report, problems = verify_snapshot(dest)
    assert problems == [] and any("'papers': 3" in line for line in report)
    with pytest.raises(FileExistsError):
        snapshot_sqlite_only(cfg, tmp_path / "backups", now=now)


def test_sqlite_only_verify_detects_a_flipped_byte(tmp_path):
    cfg = _cfg_with_real_sources(tmp_path)
    dest = snapshot_sqlite_only(cfg, tmp_path / "backups")
    data = bytearray(dest.read_bytes())
    data[-1] ^= 0xFF
    dest.write_bytes(bytes(data))
    assert any("sha256 mismatch" in p for p in verify_snapshot(dest)[1])


def test_sqlite_only_does_not_modify_the_source(tmp_path):
    cfg = _cfg_with_real_sources(tmp_path)
    before = Path(cfg.db_path).read_bytes()
    snapshot_sqlite_only(cfg, tmp_path / "backups")
    assert Path(cfg.db_path).read_bytes() == before


def test_sqlite_only_row_count_mismatch_fails_and_leaves_no_sha256(tmp_path, monkeypatch):
    cfg = _cfg_with_real_sources(tmp_path)
    monkeypatch.setattr("app.snapshot._ro_row_counts", lambda p: {"papers": 999})
    with pytest.raises(SnapshotIntegrityError, match="row counts differ"):
        snapshot_sqlite_only(cfg, tmp_path / "backups")
    assert not list((tmp_path / "backups").glob("*.sha256"))


def test_aborts_below_the_free_space_floor(tmp_path, monkeypatch):
    class _Low:
        free = 5 * 1024**3

    monkeypatch.setattr("app.snapshot.shutil.disk_usage", lambda p: _Low())
    cfg = _cfg_with_real_sources(tmp_path)
    with pytest.raises(SystemExit, match="abort rule"):
        snapshot_sqlite_only(cfg, tmp_path / "backups")


def test_main_verify_exits_nonzero_on_a_problem_without_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("app.snapshot.load_config", lambda path=None: pytest.fail("no config"))
    monkeypatch.setattr(sys, "argv", ["snapshot", "--verify", str(tmp_path / "nope")])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 1
    assert "FAILED" in capsys.readouterr().out


# --- OP-6: refuse a missing database -------------------------------------------------------


def test_run_snapshot_refuses_a_missing_db_and_creates_nothing(tmp_path):
    cfg = _base_config(db_path=str(tmp_path / "nodb" / "papers.db"), blob_dir=str(tmp_path))
    backup_root = tmp_path / "backups"
    with pytest.raises(MissingDatabaseError):
        run_snapshot(cfg, backup_root, keep=7, vector_index=_FakeVectorStore())
    assert not backup_root.exists() and not (tmp_path / "nodb").exists()


def test_main_refuses_a_missing_db_with_one_line(tmp_path, monkeypatch):
    cfg = _base_config(db_path=str(tmp_path / "papers.db"), blob_dir=str(tmp_path))
    monkeypatch.setattr("app.snapshot.load_config", lambda path=None: cfg)
    monkeypatch.setattr(sys, "argv", ["snapshot", "--sqlite-only"])
    with pytest.raises(SystemExit, match="no database at"):
        main()
    assert not (tmp_path / "papers.db").exists() and not (tmp_path / "backups").exists()
