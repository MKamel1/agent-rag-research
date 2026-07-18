"""Tests for `app.dashboard.status` -- offline, no real GPU/network/manifest. Every function is
exercised against a temp migrated DB + synthetic events JSONL, asserting graceful degradation to
`null`s when a source is missing/unreachable (never an exception)."""

import json
import subprocess

import app.dashboard.status as status_mod
from migrations.migrate import migrate


def _seed(db_path, stage_counts: dict[str, int], quarantine: list[tuple[str, str]] = ()):
    """`stage_counts`: {stage: n} -- writes n distinct paper_ids at that stage.
    `quarantine`: [(paper_id, error_type), ...] -- also writes a quarantine + diagnostics row."""
    import sqlite3

    migrate(str(db_path))
    conn = sqlite3.connect(str(db_path))
    i = 0
    for stage, n in stage_counts.items():
        for _ in range(n):
            conn.execute(
                "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, ?, ?)",
                (f"p{i}", stage, "2026-01-01T00:00:00"),
            )
            i += 1
    for paper_id, error_type in quarantine:
        conn.execute(
            "INSERT INTO quarantine (paper_id, stage, error, ts) VALUES (?, 'parsed', 'boom', ?)",
            (paper_id, "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO quarantine_diagnostics (paper_id, error_type, diagnostics_json) "
            "VALUES (?, ?, '{}')",
            (paper_id, error_type),
        )
    conn.commit()
    conn.close()


# --- read_corpus: the cumulative funnel ----------------------------------------------------------


def test_read_corpus_funnel_is_cumulative_from_current_stage(tmp_path):
    """ingest_state holds each paper's CURRENT stage only -- a paper at 'chunked' has already
    passed 'harvested'/'parsed' too, so the funnel counts must accumulate backward from 'done'."""
    _seed(tmp_path / "papers.db", {"harvested": 2, "parsed": 1, "done": 3})
    result = status_mod.read_corpus(tmp_path)
    funnel = result["funnel"]
    assert funnel["done"] == 3
    assert funnel["parsed"] == 3 + 1  # done + parsed
    assert funnel["harvested"] == 3 + 1 + 2  # every paper has reached at least harvested
    assert funnel["chunked"] == 3  # nobody currently sitting at chunked/summarized/embedded/stored
    assert funnel["quarantined"] == 0
    assert result["quarantine_reasons"] == []


def test_read_corpus_quarantine_reasons_grouped_and_sorted(tmp_path):
    _seed(
        tmp_path / "papers.db", {"done": 1},
        quarantine=[("q1", "TransientError"), ("q2", "TransientError"), ("q3", "PermanentError")],
    )
    result = status_mod.read_corpus(tmp_path)
    assert result["funnel"]["quarantined"] == 3
    assert result["quarantine_reasons"][0] == {"reason": "TransientError", "count": 2}
    assert {"reason": "PermanentError", "count": 1} in result["quarantine_reasons"]


def test_read_corpus_degrades_to_nulls_when_db_missing(tmp_path):
    result = status_mod.read_corpus(tmp_path)  # no papers.db written at all
    assert result["funnel"] == {
        "harvested": None, "parsed": None, "chunked": None, "summarized": None,
        "embedded": None, "stored": None, "done": None, "quarantined": None,
    }
    assert result["quarantine_reasons"] == []


def test_read_corpus_is_read_only_never_writes(tmp_path):
    """Mechanical guarantee: the ro connection must fail (degrade to nulls), not fall back to a
    writable connection, if the file doesn't exist -- proves this reader can't create/touch it."""
    db_path = tmp_path / "papers.db"
    assert not db_path.exists()
    status_mod.read_corpus(tmp_path)
    assert not db_path.exists()  # never auto-created by the reader


# --- read_telemetry --------------------------------------------------------------------------


def _write_events(path, events):
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_read_telemetry_none_events_path_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    result = status_mod.read_telemetry(None, done_count=5)
    assert result["stage"] is None
    assert result["papers_per_hour"] is None
    assert result["wall_clock_s"] is None


def test_read_telemetry_missing_file_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    result = status_mod.read_telemetry(tmp_path / "nope.jsonl", done_count=5)
    assert result["stage"] is None


def test_read_telemetry_mid_run_stage_and_wall_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": 42.0, "vram_mib": 1000, "power_w": 50.0})
    monkeypatch.setattr(status_mod.time, "time", lambda: 1000.0 + 60.0)  # 60s after RUN_START
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, [
        {"event": "RUN_START", "run_id": "abc", "ts": 1000.0, "stage": None},
        {"event": "STAGE_START", "run_id": "abc", "ts": 1000.0, "stage": "parse"},
    ])
    result = status_mod.read_telemetry(events_path, done_count=30)
    assert result["stage"] == "parse"
    assert result["wall_clock_s"] == 60.0
    assert result["papers_per_hour"] == 30 / (60.0 / 3600.0)
    assert result["gpu_util_pct"] == 42.0


def test_read_telemetry_run_end_reports_done_stage_and_summary_wall_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, [
        {"event": "RUN_START", "run_id": "abc", "ts": 1000.0, "stage": None},
        {"event": "STAGE_START", "run_id": "abc", "ts": 1000.0, "stage": "parse"},
        {"event": "STAGE_END", "run_id": "abc", "ts": 1050.0, "stage": "parse"},
        {"event": "RUN_END", "run_id": "abc", "ts": 1100.0, "n_done": 10, "n_quarantined": 1, "wall_clock_s": 100.0},
    ])
    result = status_mod.read_telemetry(events_path, done_count=10)
    assert result["stage"] == "done"
    assert result["wall_clock_s"] == 100.0


def test_read_telemetry_only_reflects_latest_run_id_segment(tmp_path, monkeypatch):
    """A resume relaunches app.ingest, which starts a NEW telemetry run id appended to the same
    events file -- only the most recent segment should drive the reported stage."""
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, [
        {"event": "RUN_START", "run_id": "old-run", "ts": 900.0, "stage": None},
        {"event": "STAGE_START", "run_id": "old-run", "ts": 900.0, "stage": "finish"},
        {"event": "RUN_END", "run_id": "old-run", "ts": 950.0, "n_done": 5, "n_quarantined": 0, "wall_clock_s": 50.0},
        {"event": "RUN_START", "run_id": "new-run", "ts": 1000.0, "stage": None},
        {"event": "STAGE_START", "run_id": "new-run", "ts": 1000.0, "stage": "parse"},
    ])
    monkeypatch.setattr(status_mod.time, "time", lambda: 1010.0)
    result = status_mod.read_telemetry(events_path, done_count=5)
    assert result["stage"] == "parse"
    assert result["wall_clock_s"] == 10.0


def test_read_gpu_degrades_to_nulls_when_nvidia_smi_missing(monkeypatch):
    def _raise(*a, **kw):
        raise FileNotFoundError("no nvidia-smi")
    monkeypatch.setattr(subprocess, "run", _raise)
    result = status_mod._read_gpu()
    assert result == {"gpu_util_pct": None, "vram_mib": None, "power_w": None}


# --- read_downloads --------------------------------------------------------------------------


def test_read_downloads_counts_pdfs_and_sidecars(tmp_path):
    cache = tmp_path / "pdf_cache"
    cache.mkdir()
    (cache / "a.pdf").write_bytes(b"")
    (cache / "b.pdf").write_bytes(b"")
    (cache / "a.json").write_text("{}")
    result = status_mod.read_downloads(tmp_path, target=100)
    assert result == {"cached_pdfs": 2, "sidecars": 1, "target": 100}


def test_read_downloads_degrades_when_cache_dir_missing(tmp_path):
    result = status_mod.read_downloads(tmp_path, target=100)
    assert result == {"cached_pdfs": None, "sidecars": None, "target": 100}


# --- read_consistency -------------------------------------------------------------------------


def test_read_consistency_degrades_when_vector_store_unreachable(monkeypatch):
    monkeypatch.setattr(status_mod, "_query_vector_store_point_count", lambda collection: None)
    result = status_mod.read_consistency(done_count=42, collection="papers")
    assert result == {"sqlite_done": 42, "vector_points": None}


def test_read_consistency_reports_point_count(monkeypatch):
    monkeypatch.setattr(status_mod, "_query_vector_store_point_count", lambda collection: 999)
    result = status_mod.read_consistency(done_count=42, collection="papers")
    assert result == {"sqlite_done": 42, "vector_points": 999}
