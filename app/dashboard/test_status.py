"""Tests for `app.dashboard.status` -- offline, no real GPU/network/manifest. Every function is
exercised against a temp migrated DB + synthetic events JSONL, asserting graceful degradation to
`null`s when a source is missing/unreachable (never an exception)."""

import json
import subprocess
import sqlite3

import app.dashboard.status as status_mod
from migrations.migrate import migrate


def _seed(
    db_path, stage_counts: dict[str, int], quarantine: list[tuple[str, str]] = (),
    updated_at: str = "2026-01-01T00:00:00",
):
    """`stage_counts`: {stage: n} -- writes n distinct paper_ids at that stage.
    `quarantine`: [(paper_id, error_type), ...] -- also writes a quarantine + diagnostics row."""
    migrate(str(db_path))
    conn = sqlite3.connect(str(db_path))
    i = 0
    for stage, n in stage_counts.items():
        for _ in range(n):
            conn.execute(
                "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, ?, ?)",
                (f"p{i}", stage, updated_at),
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


def _mark_done(db_path, paper_id: str, updated_at: str = "2026-01-01T00:00:00"):
    """Flips one existing `paper_id` to `stage='done'` -- used to simulate "quarantined, then
    succeeded on retry" (OG-44)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, 'done', ?) "
        "ON CONFLICT(paper_id) DO UPDATE SET stage = excluded.stage, updated_at = excluded.updated_at",
        (paper_id, updated_at),
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


def test_read_corpus_excludes_quarantined_papers_that_later_succeeded(tmp_path):
    """OG-44: `quarantine` is an append-only dead-letter log, never reconciled -- a paper that was
    quarantined and later succeeded on retry (now `stage='done'`) must not still count as
    quarantined. 3 quarantined, 2 later recovered -> only 1 truly stuck."""
    db_path = tmp_path / "papers.db"
    _seed(
        db_path, {"done": 1},
        quarantine=[("q1", "TransientError"), ("q2", "TransientError"), ("q3", "PermanentError")],
    )
    _mark_done(db_path, "q1")
    _mark_done(db_path, "q2")
    result = status_mod.read_corpus(tmp_path)
    assert result["funnel"]["quarantined"] == 1
    assert result["quarantine_reasons"] == [{"reason": "PermanentError", "count": 1}]


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
    result = status_mod.read_telemetry(None, 5)
    assert result["stage"] is None
    assert result["papers_per_hour"] is None
    assert result["wall_clock_s"] is None
    assert result["eta_s"] is None


def test_read_telemetry_missing_file_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    result = status_mod.read_telemetry(tmp_path / "nope.jsonl", 5)
    assert result["stage"] is None


def test_read_telemetry_mid_run_stage_and_wall_clock(tmp_path, monkeypatch):
    """Without `data_dir`/`started_at` (e.g. a fresh manifest with no run yet), `papers_per_hour`
    stays `None` -- stage/wall_clock still come from the events file regardless."""
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": 42.0, "vram_mib": 1000, "power_w": 50.0})
    monkeypatch.setattr(status_mod.time, "time", lambda: 1000.0 + 60.0)  # 60s after RUN_START
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, [
        {"event": "RUN_START", "run_id": "abc", "ts": 1000.0, "stage": None},
        {"event": "STAGE_START", "run_id": "abc", "ts": 1000.0, "stage": "parse"},
    ])
    result = status_mod.read_telemetry(events_path, 30)
    assert result["stage"] == "parse"
    assert result["wall_clock_s"] == 60.0
    assert result["papers_per_hour"] is None
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
    result = status_mod.read_telemetry(events_path, 10)
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
    result = status_mod.read_telemetry(events_path, 5)
    assert result["stage"] == "parse"
    assert result["wall_clock_s"] == 10.0


# --- read_telemetry: TRUE per-run rate (OG-44) ------------------------------------------------
#
# run-3995's smoking gun: `app.build_corpus` (PR #149) runs MULTIPLE `app.ingest` RUN_START/
# RUN_END cycles per dashboard run, and the OLD code divided the ALL-TIME cumulative `done` count
# (from ingest_state, includes every prior run) by THIS process's wall-clock -- inventing a rate
# even when the CURRENT run had completed zero papers. These tests seed a DB with both
# "prior-run" (updated_at before started_at) and "this-run" (updated_at at/after started_at) done
# rows, and stub `_elapsed_seconds_since` to avoid real-clock flakiness -- the DB does the real
# scoping work via `_count_done_since`.


def _events_with_run_start(events_path):
    _write_events(events_path, [
        {"event": "RUN_START", "run_id": "abc", "ts": 1000.0, "stage": None},
        {"event": "STAGE_START", "run_id": "abc", "ts": 1000.0, "stage": "parse"},
    ])


def test_read_telemetry_rate_is_scoped_to_this_run_not_alltime_cumulative(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 600.0)  # 10 min
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-18T03:00:00+00:00"
    _seed(db_path, {"done": 5}, updated_at="2026-07-18T02:00:00+00:00")  # prior run, before started_at
    _mark_done(db_path, "this-run-1", updated_at="2026-07-18T03:05:00+00:00")
    _mark_done(db_path, "this-run-2", updated_at="2026-07-18T03:06:00+00:00")
    _mark_done(db_path, "this-run-3", updated_at="2026-07-18T03:07:00+00:00")
    events_path = tmp_path / "events.jsonl"
    _events_with_run_start(events_path)

    result = status_mod.read_telemetry(
        events_path, 808,  # total_done: 5 prior + 3 this-run = 8, but pretend cumulative is huge
        data_dir=tmp_path, started_at=started_at,
    )
    assert result["papers_per_hour"] == 3 / (600.0 / 3600.0)  # ONLY the 3 this-run completions


def test_read_telemetry_rate_is_none_when_zero_completions_since_started_at(tmp_path, monkeypatch):
    """The exact run-3995 smoking gun: 809 all-time done, ZERO of them since this run started --
    must report `None`, never a fabricated rate from the all-time count."""
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 2918.0)
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-18T03:04:09.577666+00:00"
    _seed(db_path, {"done": 809}, updated_at="2026-01-01T00:00:00+00:00")  # all from prior runs
    events_path = tmp_path / "events.jsonl"
    _events_with_run_start(events_path)

    result = status_mod.read_telemetry(events_path, 809, data_dir=tmp_path, started_at=started_at)
    assert result["papers_per_hour"] is None
    assert result["eta_s"] is None


def test_read_telemetry_rate_is_none_when_elapsed_too_small(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 5.0)  # below the floor
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-18T03:00:00+00:00"
    _seed(db_path, {}, updated_at=started_at)
    _mark_done(db_path, "p0", updated_at="2026-07-18T03:00:03+00:00")
    events_path = tmp_path / "events.jsonl"
    _events_with_run_start(events_path)

    result = status_mod.read_telemetry(events_path, 1, data_dir=tmp_path, started_at=started_at)
    assert result["papers_per_hour"] is None


def test_read_telemetry_eta_scopes_rate_per_run_but_remaining_off_total_done(tmp_path, monkeypatch):
    """ETA = (target - TOTAL done) / the per-run rate -- the remaining-papers count still counts
    every paper ever finished (the corpus target is global), only the RATE is per-run-scoped."""
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 3600.0)  # 1 hour
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-18T03:00:00+00:00"
    _seed(db_path, {"done": 800}, updated_at="2026-01-01T00:00:00+00:00")
    _mark_done(db_path, "this-run-1", updated_at="2026-07-18T03:10:00+00:00")
    _mark_done(db_path, "this-run-2", updated_at="2026-07-18T03:20:00+00:00")
    _mark_done(db_path, "this-run-3", updated_at="2026-07-18T03:30:00+00:00")
    events_path = tmp_path / "events.jsonl"
    _events_with_run_start(events_path)

    result = status_mod.read_telemetry(
        events_path, 803, data_dir=tmp_path, started_at=started_at, target=806,
    )
    assert result["papers_per_hour"] == 3.0
    assert result["eta_s"] == (806 - 803) / 3.0 * 3600.0


def test_read_telemetry_eta_is_none_when_target_already_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 3600.0)
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-18T03:00:00+00:00"
    _seed(db_path, {})
    _mark_done(db_path, "this-run-1", updated_at="2026-07-18T03:10:00+00:00")
    events_path = tmp_path / "events.jsonl"
    _events_with_run_start(events_path)

    result = status_mod.read_telemetry(
        events_path, 100, data_dir=tmp_path, started_at=started_at, target=100,
    )
    assert result["eta_s"] is None


def test_elapsed_seconds_since_parses_iso_started_at():
    from datetime import UTC, datetime, timedelta

    started_at = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    elapsed = status_mod._elapsed_seconds_since(started_at)
    assert 110.0 < elapsed < 130.0  # generous tolerance for test execution time


def test_elapsed_seconds_since_degrades_to_none_on_bad_input():
    assert status_mod._elapsed_seconds_since("not-a-timestamp") is None
    assert status_mod._elapsed_seconds_since(None) is None


def test_count_done_since_scopes_by_updated_at(tmp_path):
    db_path = tmp_path / "papers.db"
    _seed(db_path, {"done": 2}, updated_at="2026-01-01T00:00:00+00:00")
    _mark_done(db_path, "later-1", updated_at="2026-07-18T03:10:00+00:00")
    _mark_done(db_path, "later-2", updated_at="2026-07-18T03:20:00+00:00")
    assert status_mod._count_done_since(tmp_path, "2026-07-18T03:00:00+00:00") == 2
    assert status_mod._count_done_since(tmp_path, "2026-01-01T00:00:00+00:00") == 4


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
    assert result == {"sqlite_done": 42, "vector_points": None, "consistent": None}


def test_read_consistency_reports_point_count(monkeypatch):
    monkeypatch.setattr(status_mod, "_query_vector_store_point_count", lambda collection: 999)
    result = status_mod.read_consistency(done_count=42, collection="papers")
    assert result == {"sqlite_done": 42, "vector_points": 999, "consistent": True}


def test_read_consistency_verdict_true_when_points_exist(monkeypatch):
    """809 papers done, 26196 vector points -- expected to differ by design (one paper produces
    many chunk+summary points) -- must read OK, not a 30x mismatch (OG-42/OG-44)."""
    monkeypatch.setattr(status_mod, "_query_vector_store_point_count", lambda collection: 26196)
    result = status_mod.read_consistency(done_count=809, collection="papers")
    assert result["consistent"] is True


def test_read_consistency_verdict_false_when_done_but_zero_points(monkeypatch):
    """The real failure class this verdict exists to catch (OG-16/T-DOC35): papers marked 'done'
    in SQLite with literally zero points in the vector store."""
    monkeypatch.setattr(status_mod, "_query_vector_store_point_count", lambda collection: 0)
    result = status_mod.read_consistency(done_count=59, collection="papers")
    assert result["consistent"] is False


def test_read_consistency_verdict_true_when_nothing_done_yet(monkeypatch):
    """0 done, 0 points is a fresh/empty corpus -- not drift."""
    monkeypatch.setattr(status_mod, "_query_vector_store_point_count", lambda collection: 0)
    result = status_mod.read_consistency(done_count=0, collection="papers")
    assert result["consistent"] is True


def test_read_consistency_verdict_none_when_done_count_unknown(monkeypatch):
    monkeypatch.setattr(status_mod, "_query_vector_store_point_count", lambda collection: 999)
    result = status_mod.read_consistency(done_count=None, collection="papers")
    assert result["consistent"] is None
