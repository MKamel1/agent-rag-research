"""Tests for `app.dashboard.status` -- offline, no real GPU/network/manifest. Every function is
exercised against a temp migrated DB + synthetic events JSONL, asserting graceful degradation to
`null`s when a source is missing/unreachable (never an exception)."""

import json
import os
import sqlite3
import subprocess
import time

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
    assert result["quarantine_reasons"][0] == {"reason": "TransientError @ parsed", "count": 2}
    assert {"reason": "PermanentError @ parsed", "count": 1} in result["quarantine_reasons"]


def test_read_corpus_quarantine_reasons_surfaces_an_unknown_bucket_for_pre_diagnostics_rows(
    tmp_path,
):
    """`quarantine_diagnostics` (T-DOC17/PR #83) postdates `quarantine` itself -- a paper
    quarantined before that landed has a `quarantine` row but no matching `quarantine_diagnostics`
    one. Observed live: funnel said 32 quarantined, the reasons breakdown alone summed to only 22,
    a silent, confusing gap. The reason breakdown must not just under-report -- the difference is
    surfaced as its own "unknown" bucket (still with a real stage, from `quarantine` itself) so the
    two numbers always reconcile."""
    db_path = tmp_path / "papers.db"
    _seed(
        db_path, {"done": 1},
        quarantine=[("q1", "TransientError"), ("q2", "PermanentError")],
    )
    # A legacy row: `quarantine` only, no `quarantine_diagnostics` -- unlike `_seed`'s own
    # quarantine entries, which always write both together.
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO quarantine (paper_id, stage, error, ts) VALUES ('q3', 'parsed', 'boom', ?)",
        ("2026-01-01T00:00:00",),
    )
    conn.commit()
    conn.close()

    result = status_mod.read_corpus(tmp_path)
    assert result["funnel"]["quarantined"] == 3
    reasons_total = sum(r["count"] for r in result["quarantine_reasons"])
    assert reasons_total == 3  # now reconciles with funnel["quarantined"]
    assert {
        "reason": "unknown (quarantined before diagnostics were recorded) @ parsed", "count": 1,
    } in result["quarantine_reasons"]


def test_read_corpus_quarantine_reasons_omits_unknown_bucket_when_fully_diagnosed(tmp_path):
    """The common case (every quarantine row has a matching diagnostics row, as `_seed` always
    writes) must not grow a spurious "unknown, count 0" entry."""
    _seed(tmp_path / "papers.db", {"done": 1}, quarantine=[("q1", "TransientError")])
    result = status_mod.read_corpus(tmp_path)
    assert all(
        "unknown (quarantined before diagnostics were recorded)" not in r["reason"]
        for r in result["quarantine_reasons"]
    )


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
    assert result["quarantine_reasons"] == [{"reason": "PermanentError @ parsed", "count": 1}]


def test_read_corpus_quarantine_reasons_group_by_stage_not_just_error_type(tmp_path):
    """T-DOC78: two papers with the SAME error_type but DIFFERENT pipeline stages must NOT be
    collapsed into one reason -- "PermanentError @ parsed" and "PermanentError @ embedded" answer
    a genuinely different "why" (a bad PDF vs. a broken embedding call)."""
    db_path = tmp_path / "papers.db"
    _seed(db_path, {"done": 1})
    conn = sqlite3.connect(str(db_path))
    for paper_id, stage in (("q1", "parsed"), ("q2", "embedded")):
        conn.execute(
            "INSERT INTO quarantine (paper_id, stage, error, ts) VALUES (?, ?, 'boom', ?)",
            (paper_id, stage, "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO quarantine_diagnostics (paper_id, error_type, diagnostics_json) "
            "VALUES (?, 'PermanentError', '{}')",
            (paper_id,),
        )
    conn.commit()
    conn.close()

    result = status_mod.read_corpus(tmp_path)
    assert result["funnel"]["quarantined"] == 2
    assert {"reason": "PermanentError @ parsed", "count": 1} in result["quarantine_reasons"]
    assert {"reason": "PermanentError @ embedded", "count": 1} in result["quarantine_reasons"]


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


def test_read_corpus_splits_the_funnel_by_doc_type(tmp_path):
    db = tmp_path / "papers.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ingest_state (paper_id TEXT PRIMARY KEY, stage TEXT NOT NULL, "
                 "updated_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE papers (paper_id TEXT PRIMARY KEY, doc_type TEXT)")
    conn.execute("CREATE TABLE quarantine (paper_id TEXT, stage TEXT)")
    conn.execute("CREATE TABLE quarantine_diagnostics (paper_id TEXT PRIMARY KEY, error_type TEXT)")
    rows = [
        ("b1", "done", "book"), ("b2", "done", "book"),
        ("b3", "parsed", "book"),                        # book still mid-pipeline
        ("p1", "done", "paper"), ("p2", "embedded", "paper"),
    ]
    for pid, stage, dt in rows:
        conn.execute("INSERT INTO ingest_state VALUES (?,?,'2026-07-31T00:00:00Z')", (pid, stage))
        conn.execute("INSERT INTO papers VALUES (?,?)", (pid, dt))
    conn.commit()
    conn.close()

    out = status_mod.read_corpus(tmp_path)

    # The combined funnel is UNCHANGED -- cumulative over all 5 documents.
    assert out["funnel"]["done"] == 3
    assert out["funnel"]["parsed"] == 5

    books = out["by_doc_type"]["book"]
    assert books["done"] == 2
    assert books["parsed"] == 3      # cumulative: 2 done + 1 sitting at parsed
    assert books["harvested"] == 3

    papers = out["by_doc_type"]["paper"]
    assert papers["done"] == 1
    assert papers["embedded"] == 2


def test_read_corpus_by_doc_type_is_empty_when_db_is_unreadable(tmp_path):
    out = status_mod.read_corpus(tmp_path / "no_such_dir")
    assert out["by_doc_type"] == {}
    assert out["funnel"]["done"] is None      # existing null-funnel behavior, unchanged


def test_read_corpus_by_doc_type_counts_quarantine_per_type(tmp_path):
    db = tmp_path / "papers.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ingest_state (paper_id TEXT PRIMARY KEY, stage TEXT NOT NULL, "
                 "updated_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE papers (paper_id TEXT PRIMARY KEY, doc_type TEXT)")
    conn.execute("CREATE TABLE quarantine (paper_id TEXT, stage TEXT)")
    conn.execute("CREATE TABLE quarantine_diagnostics (paper_id TEXT PRIMARY KEY, error_type TEXT)")
    conn.execute("INSERT INTO ingest_state VALUES ('b1','parsed','2026-07-31T00:00:00Z')")
    conn.execute("INSERT INTO papers VALUES ('b1','book')")
    conn.execute("INSERT INTO quarantine VALUES ('b1','parsed')")
    # A paper that was quarantined but LATER succeeded must not count (OG-44, same rule
    # quarantine_summary already applies to the combined number).
    conn.execute("INSERT INTO ingest_state VALUES ('p1','done','2026-07-31T00:00:00Z')")
    conn.execute("INSERT INTO papers VALUES ('p1','paper')")
    conn.execute("INSERT INTO quarantine VALUES ('p1','parsed')")
    conn.commit()
    conn.close()

    out = status_mod.read_corpus(tmp_path)

    assert out["by_doc_type"]["book"]["quarantined"] == 1
    assert out["by_doc_type"]["paper"]["quarantined"] == 0


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


# --- read_telemetry: sliding-window rate, not a cumulative average (cold-start fix) ------------
#
# The OG-44 fix above scoped the rate to THIS run via `started_at`, but still divided
# `count(done since started_at)` by the FULL elapsed time since `started_at` -- a cumulative
# average. This pipeline's cold start (hours of downloading + Pass-1 parsing before the first
# paper reaches `stage='done'`) sits in that denominator forever: measured on a real run, 11.7h of
# warm-up made the dashboard show 3.5 papers/h at the 12h mark when the true trailing rate was
# already 168/h -- 48x wrong, and it never converges. These tests pin the fix: a trailing
# `_RATE_WINDOW_S` (900s) window, clamped so it can never reach back before `started_at`.


def test_read_telemetry_rate_reflects_recent_pace_not_the_cold_start_average(tmp_path, monkeypatch):
    """The regression this fix exists for: a run started 12h ago (all of it cold-start warm-up,
    zero completions) with 3 completions only in the last few minutes. The OLD cumulative
    implementation would compute 3 / 12h = 0.25/h -- this must instead report the true recent
    rate, off by roughly 3-4 orders of magnitude. This assertion fails against the old
    `per_run_done / (elapsed_s / 3600.0)` implementation."""
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 12 * 3600.0)
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-19T08:06:00+00:00"
    _seed(db_path, {}, updated_at=started_at)
    # window_start = started_at + (12h - 900s) = 19:51:00 -- land these just inside it.
    _mark_done(db_path, "p1", updated_at="2026-07-19T19:53:00+00:00")
    _mark_done(db_path, "p2", updated_at="2026-07-19T19:56:00+00:00")
    _mark_done(db_path, "p3", updated_at="2026-07-19T19:59:00+00:00")
    events_path = tmp_path / "events.jsonl"
    _events_with_run_start(events_path)

    result = status_mod.read_telemetry(events_path, 3, data_dir=tmp_path, started_at=started_at)
    old_cumulative_rate = 3 / 12.0  # what the buggy implementation would have reported
    assert result["papers_per_hour"] > old_cumulative_rate * 10  # right order of magnitude


def test_read_telemetry_rate_window_clamps_to_elapsed_for_a_young_run(tmp_path, monkeypatch):
    """A run only 5 min old must have its rate timed over its true 5-min age, not stretched to the
    full 15-min window -- clamping the denominator down (not up) to the shorter, real elapsed
    time."""
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 300.0)  # 5 min
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-18T03:00:00+00:00"
    _seed(db_path, {}, updated_at=started_at)
    _mark_done(db_path, "p1", updated_at="2026-07-18T03:02:00+00:00")
    _mark_done(db_path, "p2", updated_at="2026-07-18T03:04:00+00:00")
    events_path = tmp_path / "events.jsonl"
    _events_with_run_start(events_path)

    result = status_mod.read_telemetry(events_path, 2, data_dir=tmp_path, started_at=started_at)
    # 2 done / 5 real minutes -- NOT 2 / 15 min, which is what an unclamped fixed window would give.
    assert result["papers_per_hour"] == 2 / (300.0 / 3600.0)


def test_read_telemetry_rate_never_counts_a_prior_runs_papers_even_inside_the_wall_clock_window(
    tmp_path, monkeypatch,
):
    """A paper finished by a PRIOR run just before `started_at` falls inside a naive trailing
    wall-clock window (this run is only 5 min old, well under the 15-min window width) but must
    still never be counted -- the `started_at` floor holds regardless of window width."""
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 300.0)  # 5 min
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-18T03:00:00+00:00"
    # Prior run's paper, 2 min before this run's started_at -- inside a naive 15-min wall-clock
    # window, but must be excluded because it predates started_at.
    _seed(db_path, {"done": 1}, updated_at="2026-07-18T02:58:00+00:00")
    _mark_done(db_path, "this-run-1", updated_at="2026-07-18T03:02:00+00:00")
    events_path = tmp_path / "events.jsonl"
    _events_with_run_start(events_path)

    result = status_mod.read_telemetry(events_path, 2, data_dir=tmp_path, started_at=started_at)
    # Only the 1 this-run completion counts -- if the prior-run paper leaked in, this would be
    # 2 / (300/3600) instead.
    assert result["papers_per_hour"] == 1 / (300.0 / 3600.0)


def test_read_telemetry_rate_and_eta_are_none_together_when_window_has_zero_completions(
    tmp_path, monkeypatch,
):
    """Zero completions in the trailing window (even with plenty of elapsed time and an all-time
    done count) must yield `papers_per_hour is None`, and `eta_s` follows it to `None` too --
    `_eta_seconds` never fabricates an ETA from a missing rate."""
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 3600.0)  # 1 hour
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-18T03:00:00+00:00"
    _seed(db_path, {"done": 500}, updated_at="2026-01-01T00:00:00+00:00")  # all prior-run, all-time
    events_path = tmp_path / "events.jsonl"
    _events_with_run_start(events_path)

    result = status_mod.read_telemetry(
        events_path, 500, data_dir=tmp_path, started_at=started_at, target=1000,
    )
    assert result["papers_per_hour"] is None
    assert result["eta_s"] is None


def test_read_telemetry_eta_scopes_rate_per_run_but_remaining_off_total_done(tmp_path, monkeypatch):
    """ETA = (target - TOTAL done) / the per-run rate -- the remaining-papers count still counts
    every paper ever finished (the corpus target is global); only the RATE is scoped, now to the
    trailing 15-min window rather than the full per-run elapsed time (the cold-start fix), so the
    3 "this-run" completions must sit inside the last 15 min of the mocked 1h-elapsed run."""
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 3600.0)  # 1 hour
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-18T03:00:00+00:00"
    _seed(db_path, {"done": 800}, updated_at="2026-01-01T00:00:00+00:00")
    # window_start = started_at + (3600 - 900)s = 03:45:00 -- these must land at/after that.
    _mark_done(db_path, "this-run-1", updated_at="2026-07-18T03:47:00+00:00")
    _mark_done(db_path, "this-run-2", updated_at="2026-07-18T03:52:00+00:00")
    _mark_done(db_path, "this-run-3", updated_at="2026-07-18T03:57:00+00:00")
    events_path = tmp_path / "events.jsonl"
    _events_with_run_start(events_path)

    result = status_mod.read_telemetry(
        events_path, 803, data_dir=tmp_path, started_at=started_at, target=806,
    )
    assert result["papers_per_hour"] == 3 / (900.0 / 3600.0)  # 3 done / 15-min window
    assert result["eta_s"] == (806 - 803) / result["papers_per_hour"] * 3600.0


def test_read_telemetry_eta_is_none_when_target_already_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_read_gpu", lambda: {"gpu_util_pct": None, "vram_mib": None, "power_w": None})
    monkeypatch.setattr(status_mod, "_elapsed_seconds_since", lambda started_at: 3600.0)
    db_path = tmp_path / "papers.db"
    started_at = "2026-07-18T03:00:00+00:00"
    _seed(db_path, {})
    _mark_done(db_path, "this-run-1", updated_at="2026-07-18T03:50:00+00:00")  # inside the window
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
    result = status_mod.read_downloads(tmp_path, prefetch_target=100)
    assert result == {
        "staged_pdfs": 2, "sidecars": 1, "prefetch_target": 100,
        "stalled": False, "new_last_pass": None,
    }


def test_read_downloads_degrades_when_cache_dir_missing(tmp_path):
    result = status_mod.read_downloads(tmp_path, prefetch_target=100)
    assert result == {
        "staged_pdfs": None, "sidecars": None, "prefetch_target": 100,
        "stalled": False, "new_last_pass": None,
    }


def test_read_downloads_reports_stall_from_the_prefetch_log(tmp_path):
    (tmp_path / "pdf_cache").mkdir()
    (tmp_path / "prefetch.log").write_text(
        "INFO:__main__:prefetch_pdfs: pass complete, +6 this pass, 11556/30000 cached\n"
        "INFO:__main__:prefetch_pdfs: prefetch stalled: 11556/30000 cached, "
        "only 6 new available, next attempt in 3600s\n"
    )
    out = status_mod.read_downloads(tmp_path, 30000)
    assert out["stalled"] is True
    assert out["new_last_pass"] == 6
    assert out["prefetch_target"] == 30000


def test_read_downloads_stall_clears_when_a_newer_pace_line_follows(tmp_path):
    """A stall followed by fresh progress is not a stall -- whichever line appears LATER wins."""
    (tmp_path / "pdf_cache").mkdir()
    (tmp_path / "prefetch.log").write_text(
        "prefetch stalled: 11556/30000 cached, only 6 new available, next attempt in 3600s\n"
        "prefetch_pdfs: downloaded 40 / target 30000\n"
    )
    out = status_mod.read_downloads(tmp_path, 30000)
    assert out["stalled"] is False


def test_read_downloads_absent_log_is_not_a_stall_and_not_a_zero(tmp_path):
    (tmp_path / "pdf_cache").mkdir()
    out = status_mod.read_downloads(tmp_path, 30000)
    assert out["stalled"] is False
    assert out["new_last_pass"] is None      # absent != zero


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


# --- read_downloader (OG-43) -------------------------------------------------------------------


# Every test below that doesn't itself care about `live_pids` injects an empty fake explicitly --
# the operator's OWN real downloader is a live `app.prefetch_pdfs` process on THIS machine while
# these tests run (D-6's whole reason for existing), so leaving `read_downloader` to its real
# `_live_prefetch_pids()` default would make these tests' `live_pids`/`orphan`/`tags_pending`
# fields silently depend on whatever happens to be running on the host at test time.


def test_read_downloader_degrades_to_nulls_when_no_run_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_live_prefetch_pids", lambda: [])
    result = status_mod.read_downloader(None)
    assert result == {
        "prefetch_alive": None, "downloaded": None, "prefetch_target": None,
        "live_pids": [], "orphan": False, "tracked_pid": None, "tags_pending": None,
    }


def test_read_downloader_reports_dead_when_pid_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_live_prefetch_pids", lambda: [])
    result = status_mod.read_downloader(tmp_path)
    assert result["prefetch_alive"] is None  # no prefetch.pid at all -- distinct from "dead"


def test_read_downloader_reports_dead_for_a_stale_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_live_prefetch_pids", lambda: [])
    (tmp_path / "prefetch.pid").write_text("999999999")
    result = status_mod.read_downloader(tmp_path)
    assert result["prefetch_alive"] is False


def test_read_downloader_reports_alive_for_a_real_prefetch_pdfs_process(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_live_prefetch_pids", lambda: [])
    (tmp_path / "prefetch.pid").write_text("4242")
    monkeypatch.setattr(status_mod, "_is_live_prefetch", lambda pid: pid == 4242)
    result = status_mod.read_downloader(tmp_path)
    assert result["prefetch_alive"] is True


def test_read_downloader_tails_its_own_dedicated_log_for_the_latest_pace_line(tmp_path, monkeypatch):
    """`_PREFETCH_LOG_NAME` (`prefetch.log`), not the shared run log -- T-DOC<n>: a shared log
    also written by far more verbose parse-progress logging could push the real pace line outside
    `_LOG_TAIL_BYTES`'s window; a dedicated, single-writer log can't have that problem."""
    monkeypatch.setattr(status_mod, "_live_prefetch_pids", lambda: [])
    (tmp_path / "prefetch.log").write_text(
        "some other line\n"
        "prefetch_pdfs: downloaded 10 / target 30000 (cache now 10)\n"
        "more noise\n"
        "prefetch_pdfs: downloaded 25 / target 30000 (cache now 25)\n"
    )
    result = status_mod.read_downloader(tmp_path)
    assert result["downloaded"] == 25
    assert result["prefetch_target"] == 30000


def test_read_downloader_pace_degrades_when_log_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_live_prefetch_pids", lambda: [])
    result = status_mod.read_downloader(tmp_path)
    assert result["downloaded"] is None
    assert result["prefetch_target"] is None


def test_read_downloader_pace_degrades_when_no_pace_line_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_live_prefetch_pids", lambda: [])
    (tmp_path / "prefetch.log").write_text("nothing relevant here\n")
    result = status_mod.read_downloader(tmp_path)
    assert result["downloaded"] is None


def test_is_live_prefetch_false_for_non_prefetch_cmdline():
    # this test process's own cmdline, not app.prefetch_pdfs
    assert status_mod._is_live_prefetch(os.getpid()) is False


def test_is_live_prefetch_false_for_a_dead_pid():
    assert status_mod._is_live_prefetch(999999999) is False


# --- D-6 Task 1: read_downloader sees every live downloader via the process table --------------


def test_read_downloader_reports_an_untracked_live_downloader_as_an_orphan(tmp_path, monkeypatch):
    """The 20-hour blind spot: a prefetch process alive but named by neither prefetch.pid nor the
    manifest was invisible to the dashboard entirely."""
    monkeypatch.setattr(status_mod, "_live_prefetch_pids", lambda: [4242])
    out = status_mod.read_downloader(tmp_path, manifest_pid=None)
    assert out["live_pids"] == [4242]
    assert out["orphan"] is True


def test_read_downloader_is_not_an_orphan_when_the_manifest_names_it(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_live_prefetch_pids", lambda: [4242])
    out = status_mod.read_downloader(tmp_path, manifest_pid=4242)
    assert out["orphan"] is False
    assert out["tracked_pid"] == 4242


def test_read_downloader_no_live_process_is_not_an_orphan(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_live_prefetch_pids", lambda: [])
    out = status_mod.read_downloader(tmp_path, manifest_pid=None)
    assert out["live_pids"] == []
    assert out["orphan"] is False


# --- D-6 Task 3: tag-staleness warning -----------------------------------------------------------


def test_tags_pending_when_the_pool_was_edited_after_the_downloader_started(tmp_path, monkeypatch):
    pool = tmp_path / "tag_pool.json"
    pool.write_text('{"active": ["a"], "held": []}')
    # downloader started an hour before the pool was last written
    monkeypatch.setattr(status_mod, "_process_start_epoch", lambda pid: pool.stat().st_mtime - 3600)
    out = status_mod.read_downloader(
        tmp_path, manifest_pid=4242, live_pids=lambda: [4242], data_dir=tmp_path,
    )
    assert out["tags_pending"] is True


def test_tags_not_pending_when_the_downloader_started_after_the_last_edit(tmp_path, monkeypatch):
    pool = tmp_path / "tag_pool.json"
    pool.write_text('{"active": ["a"], "held": []}')
    monkeypatch.setattr(status_mod, "_process_start_epoch", lambda pid: pool.stat().st_mtime + 3600)
    out = status_mod.read_downloader(
        tmp_path, manifest_pid=4242, live_pids=lambda: [4242], data_dir=tmp_path,
    )
    assert out["tags_pending"] is False


def test_tags_pending_is_none_when_no_downloader_is_running(tmp_path, monkeypatch):
    """Absent != false. With nothing running there is nothing for tags to be pending against."""
    out = status_mod.read_downloader(
        tmp_path, manifest_pid=None, live_pids=lambda: [], data_dir=tmp_path,
    )
    assert out["tags_pending"] is None


def test_tags_pending_none_when_tag_pool_json_does_not_exist_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "_process_start_epoch", lambda pid: time.time() - 3600)
    out = status_mod.read_downloader(
        tmp_path, manifest_pid=4242, live_pids=lambda: [4242], data_dir=tmp_path,
    )
    assert out["tags_pending"] is None


# --- read_disk (OG-43) --------------------------------------------------------------------------


def test_read_disk_reports_usage(tmp_path):
    result = status_mod.read_disk(tmp_path)
    assert result["free_gb"] > 0
    assert result["total_gb"] > 0
    assert 0 <= result["used_pct"] <= 100


def test_read_disk_degrades_to_nulls_when_path_missing():
    result = status_mod.read_disk("/no/such/path/at/all")
    assert result == {"free_gb": None, "total_gb": None, "used_pct": None}


# --- T-DOC78: read_tei_status() -- live TEI health probe (mirrors read_consistency's vector-store
# point-count probe: a live HTTP call, best-effort, never raises) -------------------------------


def test_read_tei_status_reports_healthy_when_both_endpoints_respond_ok(monkeypatch):
    def fake_urlopen(url, timeout=None):
        import io
        return io.BytesIO(b"")  # health endpoints return an empty 200 body, not JSON

    monkeypatch.setattr(status_mod.urllib.request, "urlopen", fake_urlopen)

    result = status_mod.read_tei_status()

    assert result == {"embed_healthy": True, "rerank_healthy": True}


def test_read_tei_status_reports_unhealthy_on_connection_error(monkeypatch):
    def fake_urlopen(url, timeout=None):
        raise status_mod.urllib.error.URLError("connection refused")

    monkeypatch.setattr(status_mod.urllib.request, "urlopen", fake_urlopen)

    result = status_mod.read_tei_status()

    assert result == {"embed_healthy": False, "rerank_healthy": False}


def test_read_tei_status_checks_each_endpoint_independently(monkeypatch):
    """One up, one down -- must report each independently, not collapse to a single verdict."""
    def fake_urlopen(url, timeout=None):
        import io
        if "8080" in url:
            return io.BytesIO(b"")
        raise status_mod.urllib.error.URLError("connection refused")

    monkeypatch.setattr(status_mod.urllib.request, "urlopen", fake_urlopen)

    result = status_mod.read_tei_status()

    assert result == {"embed_healthy": True, "rerank_healthy": False}


# --- drop-in tray -------------------------------------------------------------------------------


def _seed_papers(db_path, papers: list[tuple[str, str]]):
    """`papers`: [(paper_id, doc_type), ...] -- minimal valid row for `papers`' NOT NULL columns
    (real schema: `migrations/`, confirmed via `.schema papers` against the operator's live DB)."""
    conn = sqlite3.connect(str(db_path))
    conn.executemany(
        "INSERT INTO papers (paper_id, version, title, abstract, authors_json, categories_json, "
        "published, updated, pdf_path, markdown_path, doc_type) "
        "VALUES (?, '1', 't', 'a', '[]', '[]', '2026-01-01', '2026-01-01', 'p', 'm', ?)",
        papers,
    )
    conn.commit()
    conn.close()


def test_read_drop_in_counts_each_bucket(tmp_path):
    drop = tmp_path / "drop_in"
    for sub in ("papers", "books", "done", "failed", "excluded"):
        (drop / sub).mkdir(parents=True)
    (drop / "papers" / "a.pdf").write_bytes(b"%PDF-1.4")
    (drop / "papers" / "b.pdf").write_bytes(b"%PDF-1.4")
    (drop / "books" / "c.pdf").write_bytes(b"%PDF-1.4")
    (drop / "done" / "a.pdf").write_bytes(b"%PDF-1.4")
    (drop / "failed" / "d.pdf").write_bytes(b"%PDF-1.4")
    (drop / "failed" / "d.pdf.err").write_text("unreadable PDF: bad xref")
    (drop / "excluded" / "e.pdf").write_bytes(b"%PDF-1.4")

    out = status_mod.read_drop_in(drop, tmp_path / "nonexistent.db")

    assert out["pending_papers"] == 2
    assert out["pending_books"] == 1
    assert out["staged"] == 1
    assert out["failed"] == 1
    assert out["excluded"] == 1
    assert out["failure_reasons"] == [("unreadable PDF: bad xref", 1)]


def test_read_drop_in_processed_is_none_when_db_unreadable(tmp_path):
    """Absent and zero are different facts: a missing papers.db must not read as
    'zero dropped documents made it into the corpus'."""
    drop = tmp_path / "drop_in"
    drop.mkdir()
    (drop / "manifest-20260730T000000Z.txt").write_text("local:aaaaaaaaaaaa\n")

    out = status_mod.read_drop_in(drop, tmp_path / "nonexistent.db")

    assert out["processed"] is None
    assert out["processed_papers"] is None
    assert out["processed_books"] is None


def test_read_drop_in_processed_counts_only_manifest_ids_at_stage_done(tmp_path):
    """Real schema (confirmed against the operator's live papers.db) splits this across two
    tables: `ingest_state.stage` (not `papers.stage` -- `papers` has no `stage` column) and
    `papers.doc_type`, joined on `paper_id`."""
    drop = tmp_path / "drop_in"
    drop.mkdir()
    (drop / "manifest-20260730T000000Z.txt").write_text(
        "local:aaaaaaaaaaaa\nlocal:bbbbbbbbbbbb\nlocal:cccccccccccc\n"
    )
    db = tmp_path / "papers.db"
    migrate(str(db))
    _seed_papers(db, [
        ("local:aaaaaaaaaaaa", "paper"),
        ("local:bbbbbbbbbbbb", "book"),
        ("local:cccccccccccc", "book"),
        ("2501.00001", "paper"),
    ])
    conn = sqlite3.connect(str(db))
    conn.executemany(
        "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, ?, '2026-01-01T00:00:00')",
        [
            ("local:aaaaaaaaaaaa", "done"),    # counted
            ("local:bbbbbbbbbbbb", "done"),    # counted
            ("local:cccccccccccc", "parsed"),  # staged but NOT processed
            ("2501.00001", "done"),            # not from drop_in, must not count
        ],
    )
    conn.commit()
    conn.close()

    out = status_mod.read_drop_in(drop, db)

    assert out["processed"] == 2
    assert out["processed_papers"] == 1
    assert out["processed_books"] == 1


def test_read_drop_in_tolerates_missing_tree(tmp_path):
    out = status_mod.read_drop_in(tmp_path / "no_such_dir", tmp_path / "no.db")
    assert out["pending_papers"] == 0
    assert out["staged"] == 0
    assert out["processed"] is None
    assert out["latest_manifest"] is None
