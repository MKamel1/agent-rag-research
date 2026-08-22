"""`app/dashboard/status.py` -- the Status Reader: read-only views of `ingest_state`, a run's
telemetry JSONL, `pdf_cache/`, and the vector store, so `server.py` never has to know WHERE each
metric lives.

**Never reads `run_manifest.json`** (principal-design-review finding #6): `controller.py` is the
sole reader/writer of the manifest -- the two modules would otherwise both need PID-reuse-aware
reconciliation logic, and a a stale/racing read here could show a run as live when the controller
has already reconciled it dead. Every function here instead takes the manifest-derived values it
needs (`db_path`, `events_path`, `target`, `collection`) as explicit parameters -- `server.py`
resolves those once via `controller.liveness()` and passes them in. Every function degrades
independently to `null` fields on any missing/locked/unreachable source and never raises.

Read-only guarantee on `papers.db`: every connection opens `mode=ro` over a `file:` URI
(`_ro_connect`) -- a mechanical guarantee, not just a convention, that this reader can never write
to the live ingest's database even by accident.

This module has no internal-project imports today (pure stdlib) and must stay that way:
`app/telemetry.py` now imports `quarantine_summary` from here (T-DOC78), so anything this module
imports back from the rest of the project risks a future circular import -- e.g. if someone later
shares an event-name constant from `app/telemetry.py` into `status.py`, since `status.py`'s
`read_telemetry` already reads telemetry's JSONL event format and would be a plausible place to
reach for one.

`ingest_state.stage` holds each paper's CURRENT stage only (one upserted row per `paper_id`,
`rag/ingest_state_sqlite.py::checkpoint`), not a per-stage-transition log. `rag/orchestrator.py`'s
`_STAGES` ordering (harvested -> parsed -> chunked -> summarized -> embedded -> stored -> done) is
monotonic, so the cumulative "how many papers have reached at least this stage" funnel the
dashboard wants is a running sum of per-stage counts from `done` backward to `harvested`
(`_funnel_from_stage_counts`).
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

_STAGES = ("harvested", "parsed", "chunked", "summarized", "embedded", "stored", "done")

# Same host/port `app/telemetry.py`/`app/doctor.py` already health-probe the vector store on --
# duplicated here rather than imported, matching `app/telemetry.py`'s own stated "own your own
# copies" convention for this exact constant (no cross-module coupling on a value this stable).
_VECTOR_STORE_HOST = "localhost"
_VECTOR_STORE_PORT = 6333

_DEFAULT_DB_NAME = "papers.db"


# --- ingest_state / quarantine (pure: data_dir only, no manifest) -------------------------------


# T-DOC78: shared with `app/telemetry.py::summarize_run` -- both need "how many quarantined, and
# why" against an open connection. Previously computed with two independently-drifting queries:
# telemetry's own copy never got the OG-44 "exclude papers that later succeeded" fix this one has,
# so the dashboard's live count and the end-of-run printed summary could legitimately disagree.
_UNDIAGNOSED_REASON = "unknown (quarantined before diagnostics were recorded)"


def quarantine_summary(conn: sqlite3.Connection) -> tuple[int, list[tuple[str, int]]]:
    """`(count, [(reason, count), ...])` -- total quarantined and a reason breakdown, BOTH
    excluding any paper_id that has since reached `stage='done'` (OG-44: `quarantine` is an
    append-only dead-letter log, never reconciled, so a paper that later succeeded on retry must
    not still count as stuck). `reason` is `"<error_type> @ <stage>"` (e.g.
    `"PermanentError @ parsed"`) -- `stage` comes from `quarantine` itself (always present);
    `error_type` comes from `quarantine_diagnostics` via a LEFT JOIN, since that table (T-DOC17/PR
    #83) postdates `quarantine` -- a pre-existing row has no diagnostics match and is labelled
    `_UNDIAGNOSED_REASON` rather than silently dropped. Safe because `quarantine_diagnostics.paper_id`
    is a PRIMARY KEY (`migrations/0003_quarantine_diagnostics.sql`) -- at most one diagnostics row
    per quarantined paper, so the join can never fan out and inflate the breakdown past `count`.
    Grouping by stage too (not just error_type) means the reason breakdown ALWAYS sums to `count` by
    construction -- no separate "top up the gap" step needed, unlike the previous single-column
    GROUP BY. Sorted by count descending, with stage/error_type as a tiebreak (SQLite doesn't
    guarantee row order among ties, and grouping by stage now produces many more of them) so results
    are deterministic. Takes an already-open connection (a `mode=ro` URI connection in `read_corpus`
    below, a plain read-write one in `app/telemetry.py`) rather than opening its own, so either
    caller's connection semantics apply."""
    count = conn.execute(
        "SELECT count(*) FROM quarantine q WHERE NOT EXISTS "
        "(SELECT 1 FROM ingest_state s WHERE s.paper_id = q.paper_id AND s.stage = 'done')"
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT q.stage, COALESCE(qd.error_type, ?) AS error_type, count(*) AS n "
        "FROM quarantine q LEFT JOIN quarantine_diagnostics qd ON qd.paper_id = q.paper_id "
        "WHERE NOT EXISTS "
        "(SELECT 1 FROM ingest_state s WHERE s.paper_id = q.paper_id AND s.stage = 'done') "
        "GROUP BY q.stage, error_type ORDER BY n DESC, q.stage, error_type",
        (_UNDIAGNOSED_REASON,),
    ).fetchall()
    return count, [(f"{error_type} @ {stage}", n) for stage, error_type, n in rows]


def read_corpus(data_dir: str | Path) -> dict:
    """Stage funnel (+ quarantine count) and top quarantine reasons, from `<data_dir>/papers.db`
    -- always the same fixed path (matches the HARD CONSTRAINT that this reader never touches
    anything but `papers.db`; every observed run's manifest `db_path` is this same path anyway).
    Returns `{"funnel": {...}, "by_doc_type": {...}, "quarantine_reasons": [...]}`."""
    db_path = Path(data_dir) / _DEFAULT_DB_NAME
    conn = _ro_connect(db_path)
    if conn is None:
        return {"funnel": _null_funnel(), "by_doc_type": {}, "quarantine_reasons": []}
    try:
        stage_counts = dict(
            conn.execute("SELECT stage, count(*) FROM ingest_state GROUP BY stage").fetchall()
        )
        quarantine_count, reason_pairs = quarantine_summary(conn)
        by_doc_type = _funnels_by_doc_type(conn)
    except sqlite3.Error:
        return {"funnel": _null_funnel(), "by_doc_type": {}, "quarantine_reasons": []}
    finally:
        conn.close()

    funnel = _funnel_from_stage_counts(stage_counts)
    funnel["quarantined"] = quarantine_count
    quarantine_reasons = [{"reason": reason, "count": count} for reason, count in reason_pairs]
    return {"funnel": funnel, "by_doc_type": by_doc_type, "quarantine_reasons": quarantine_reasons}


# Books and papers share one pipeline but are worth watching apart: a dropped book that stalls at
# `parsed` is invisible in the combined funnel, which is dominated by ~12k papers. The stage lives
# in `ingest_state`, the type in `papers`; they join on paper_id. Cumulative semantics come from
# `_funnel_from_stage_counts` -- reused per type rather than reimplemented, so the split can never
# drift from the combined funnel's meaning.
def _funnels_by_doc_type(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    rows = conn.execute(
        "SELECT p.doc_type, i.stage, count(*) FROM ingest_state i "
        "JOIN papers p ON p.paper_id = i.paper_id GROUP BY p.doc_type, i.stage"
    ).fetchall()
    per_type: dict[str, dict[str, int]] = {}
    for doc_type, stage, n in rows:
        per_type.setdefault(str(doc_type), {})[str(stage)] = int(n)

    quarantined = dict(
        conn.execute(
            # Same OG-44 exclusion `quarantine_summary` applies: `quarantine` is an append-only
            # dead-letter log, so a paper that later succeeded must not still read as stuck.
            "SELECT p.doc_type, count(*) FROM quarantine q "
            "JOIN papers p ON p.paper_id = q.paper_id "
            "WHERE NOT EXISTS (SELECT 1 FROM ingest_state s "
            "                  WHERE s.paper_id = q.paper_id AND s.stage = 'done') "
            "GROUP BY p.doc_type"
        ).fetchall()
    )

    out = {}
    for doc_type, stage_counts in per_type.items():
        funnel = _funnel_from_stage_counts(stage_counts)
        funnel["quarantined"] = int(quarantined.get(doc_type, 0))
        out[doc_type] = funnel
    return out


def _ro_connect(db_path: Path) -> sqlite3.Connection | None:
    """A guaranteed-read-only connection (`mode=ro` URI), or `None` if the file is missing, not
    yet migrated, or locked -- callers degrade to nulls rather than raising."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        conn.execute("SELECT 1")
        return conn
    except sqlite3.Error:
        return None


def _null_funnel() -> dict:
    funnel = dict.fromkeys(_STAGES)
    funnel["quarantined"] = None
    return funnel


def _funnel_from_stage_counts(stage_counts: dict[str, int]) -> dict[str, int]:
    cumulative_from = {}
    running = 0
    for stage in reversed(_STAGES):
        running += stage_counts.get(stage, 0)
        cumulative_from[stage] = running
    return {stage: cumulative_from[stage] for stage in _STAGES}


# --- live telemetry (events JSONL + a live GPU sample) ------------------------------------------


_MIN_ELAPSED_S_FOR_RATE = 60.0  # a rate extrapolated from a few seconds of elapsed time is noise

# Trailing window for `_per_run_papers_per_hour` (cold-start fix, see `read_telemetry`'s
# docstring). 15 min: checked live against `papers.db` (`SELECT substr(updated_at,1,16),
# count(*) FROM ingest_state WHERE stage='done' GROUP BY 1`) -- this pipeline runs a steady
# ~3-5 done/min once warm, so a 15-min window holds ~60 completions and moves smoothly
# minute-to-minute rather than swinging on a lumpy few-sample average.
_RATE_WINDOW_S = 900.0


def read_telemetry(
    events_path: str | Path | None,
    total_done: int | None,
    *,
    data_dir: str | Path | None = None,
    started_at: str | None = None,
    target: int | None = None,
) -> dict:
    """Current stage, papers/hour, ETA, wall-clock (from the run's telemetry JSONL at
    `events_path`, or `None` if there is no active/known run) plus a live GPU util/VRAM/power
    sample (independent of `events_path` -- always read fresh).

    `papers_per_hour` is a TRUE per-run rate, scoped to a trailing **sliding window**
    (`_RATE_WINDOW_S`), not a cumulative average since the run started: `app.build_corpus`
    (PR #149) is a supervisor that runs MULTIPLE `app.ingest` RUN_START/RUN_END cycles per
    dashboard run, so this process's own wall-clock no longer pairs meaningfully with
    `total_done` (the ALL-TIME cumulative count, including papers finished by prior runs) --
    dividing the two used to invent a papers/hour and ETA even when the CURRENT run had
    completed zero papers (OG-44). Anchoring the rate on `started_at` fixed that, but a first pass
    divided `COUNT(done since started_at)` by the FULL elapsed time since `started_at`, which is a
    cumulative average, not a current rate -- and this pipeline's cold start (downloading +
    Pass-1 parsing runs for hours before the first paper reaches `stage='done'`) means those
    warm-up hours sit in the denominator forever. Measured on a real run: 11.7h of warm-up before
    the first completion made the dashboard show 3.5 papers/h (ETA 32 days) at the 12h mark when
    the true trailing rate was already 168/h (ETA 0.67 days) -- 48x wrong, and it never fully
    recovers because the cold-start hours never leave the average. The same defect re-inflates
    the rate after any pause, since `controller.resume()` intentionally reuses the existing
    manifest's `started_at` rather than resetting it (a resumed run is the same run, not a new
    one) -- so paused wall-clock time would otherwise also sit in the denominator forever.

    The fix: `papers_per_hour` is `COUNT(ingest_state WHERE stage='done' AND updated_at >=
    window_start)` (`_count_done_since`) divided by the window's own width, where `window_start`
    is `min(_RATE_WINDOW_S, elapsed_since(started_at))` seconds before now -- clamped so the
    window can never reach back before `started_at` itself (a prior run's completions can never
    be counted, same guarantee the cumulative version had) and so a run younger than the window
    is timed over its own true elapsed age, not artificially stretched to the window width. Zero
    completions in the window, or too little elapsed time to be meaningful
    (`_MIN_ELAPSED_S_FOR_RATE`), yields `None` -- never a fabricated number. `eta_s`
    (`(target - total_done) / papers_per_hour`) is `None` whenever `papers_per_hour` is `None` for
    the same reason, or `target`/`total_done` is unknown, or the target has already been reached.
    """
    gpu = _read_gpu()
    null_telemetry = {
        "stage": None, "papers_per_hour": None, "wall_clock_s": None, "eta_s": None, **gpu,
    }
    if not events_path:
        return null_telemetry

    events = _read_latest_run_events(Path(events_path))
    if not events:
        return null_telemetry

    wall_clock_s = _wall_clock_seconds(events)
    papers_per_hour = _per_run_papers_per_hour(data_dir, started_at)
    eta_s = _eta_seconds(papers_per_hour, total_done, target)

    return {
        "stage": _current_stage(events),
        "papers_per_hour": papers_per_hour,
        "wall_clock_s": wall_clock_s,
        "eta_s": eta_s,
        **gpu,
    }


def _per_run_papers_per_hour(
    data_dir: str | Path | None, started_at: str | None
) -> float | None:
    if data_dir is None or not started_at:
        return None
    elapsed_s = _elapsed_seconds_since(started_at)
    if elapsed_s is None:
        return None
    # Clamp to elapsed_s so a run younger than the window is timed over its own true age (a
    # 5-min-old run reports a rate over 5 min, not artificially stretched to 15) -- and so
    # `window_start` below can never land before `started_at`, the same "never count a prior
    # run's papers" guarantee the old cumulative version had.
    window_s = min(_RATE_WINDOW_S, elapsed_s)
    if window_s < _MIN_ELAPSED_S_FOR_RATE:
        return None
    window_start = _iso_offset(started_at, elapsed_s - window_s)
    done_in_window = _count_done_since(data_dir, window_start)
    if not done_in_window:
        return None
    return done_in_window / (window_s / 3600.0)


def _elapsed_seconds_since(started_at: str) -> float | None:
    try:
        start = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return None
    now = datetime.now(UTC) if start.tzinfo is not None else datetime.now()
    return (now - start).total_seconds()


def _iso_offset(started_at: str, offset_s: float) -> str:
    """`started_at` shifted forward by `offset_s` seconds and re-serialized the same way
    (`datetime.now(UTC).isoformat()`), so `_count_done_since`'s plain string comparison against
    `ingest_state.updated_at` keeps working without parsing that side. Only ever called with
    `offset_s = elapsed_s - window_s >= 0` (`_per_run_papers_per_hour`), so the result can never
    sort before `started_at` itself."""
    start = datetime.fromisoformat(started_at)
    return (start + timedelta(seconds=offset_s)).isoformat()


def _count_done_since(data_dir: str | Path, since: str) -> int | None:
    """COUNT(*) of `ingest_state` rows at `stage='done'` with `updated_at >= since` -- `since` is
    either `started_at` itself or a later sliding-window start (`_iso_offset`), so this always
    excludes every paper finished by a prior run (OG-44) and, once the window clamp kicks in,
    everything from earlier in THIS run too. Both timestamps being compared are written via
    `datetime.now(UTC).isoformat()` (`rag/ingest_state_sqlite.py::checkpoint`,
    `controller.py::_build_manifest`), so a plain string comparison sorts correctly without
    parsing either side."""
    db_path = Path(data_dir) / _DEFAULT_DB_NAME
    conn = _ro_connect(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT count(*) FROM ingest_state WHERE stage = 'done' AND updated_at >= ?",
            (since,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return row[0] if row is not None else None


def _eta_seconds(
    papers_per_hour: float | None, total_done: int | None, target: int | None
) -> float | None:
    if not papers_per_hour or total_done is None or target is None:
        return None
    remaining = target - total_done
    if remaining <= 0:
        return None
    return remaining / papers_per_hour * 3600.0


def _read_latest_run_events(path: Path) -> list[dict]:
    """The events JSONL accumulates one short segment per `app.ingest` launch (resume relaunches
    append a fresh `RUN_START`..`RUN_END` segment under a new telemetry run id -- distinct from
    the manifest's own `run_id`, see `app/telemetry.py::RunTelemetry.start`). Only the most
    recent segment reflects "the current run"."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not events:
        return []
    latest_run_id = events[-1].get("run_id")
    return [e for e in events if e.get("run_id") == latest_run_id]


def _current_stage(events: list[dict]) -> str | None:
    stage = None
    for event in events:
        kind = event.get("event")
        if kind == "STAGE_START":
            stage = event.get("stage")
        elif kind == "STAGE_END" and event.get("stage") == stage:
            stage = None
        elif kind == "RUN_END":
            stage = "done"
    return stage


def _wall_clock_seconds(events: list[dict]) -> float | None:
    start_ts = next((e["ts"] for e in events if e.get("event") == "RUN_START"), None)
    if start_ts is None:
        return None
    end_event = next((e for e in events if e.get("event") == "RUN_END"), None)
    if end_event is not None:
        return end_event.get("wall_clock_s")
    return time.time() - start_ts


def _read_gpu() -> dict:
    """A live `nvidia-smi` sample (`app/telemetry.py`'s sampler only ever aggregates its per-run
    samples into an in-process end-of-run summary -- it does not stream them to the JSONL -- so a
    live reading is the only source for "GPU right now"). Same probe shape as
    `app/telemetry.py::_query_gpu`, duplicated per that module's own "own your own copies"
    convention. Degrades to nulls on any failure -- no GPU, no `nvidia-smi`, or a transient read
    error must never blank the rest of the snapshot."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5.0, check=True,
        )
        util_str, mem_str, power_str = result.stdout.strip().splitlines()[0].split(",")
        try:
            power_w = float(power_str.strip())
        except ValueError:
            power_w = None
        return {"gpu_util_pct": float(util_str), "vram_mib": int(mem_str), "power_w": power_w}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError,
            ValueError, IndexError):
        return {"gpu_util_pct": None, "vram_mib": None, "power_w": None}


# --- downloads (pdf_cache/) -----------------------------------------------------------------

# app/prefetch_pdfs.py:417 logs this every stalled pass and nothing has ever read it -- the system
# knew it had exhausted arXiv for the configured queries and never told the operator.
_DOWNLOAD_STALL_RE = re.compile(
    r"prefetch stalled: (\d+)/(\d+) cached, only (\d+) new available"
)


def read_downloads(
    data_dir: str | Path, prefetch_target: int | None,
    run_cwd: str | Path | None = None,
) -> dict:
    """Staged-PDF count paired with `prefetch_target` -- `Config.prefetch_target` (30,000), what
    `app.prefetch_pdfs` actually aims at, NOT the run's processing target (a different, usually
    much smaller, number `server._status_dict` used to pass here by mistake).

    `stalled`/`new_last_pass` come from the `<run_cwd>/prefetch.log` tail `read_downloader`
    already reads (`_DOWNLOAD_PACE_RE`) -- RI-30: an edited run's downloader writes that log in
    its override scratch dir (`run_manifest.json`'s `run_cwd`, OG-43), so defaulting to the data
    dir here tailed the last UNEDITED run's stale log: a lingering stall line held the
    "Harvest exhausted" banner up while nothing was wrong, or hid a live one -- while this same
    response's `read_downloader` fields described the correct file, two fields on one downloader
    disagreeing. Whichever of `_DOWNLOAD_STALL_RE` / `_DOWNLOAD_PACE_RE`'s last match sits LATER
    in the tail wins, so a stall line followed by a fresher pace line correctly clears
    `stalled`. Missing/unreadable log or no match ⇒ `stalled: False`, `new_last_pass: None` --
    never a fabricated `0`. The staged/sidecar counts stay rooted at `data_dir`: the override
    config's path fields resolve absolute against the real data dir (`_resolve_override_config`),
    so `pdf_cache` is where the cache actually lives even for an edited run."""
    cache_dir = Path(data_dir) / "pdf_cache"
    stalled, new_last_pass = _tail_download_stall(
        Path(run_cwd if run_cwd is not None else data_dir) / _PREFETCH_LOG_NAME
    )
    if not cache_dir.is_dir():
        return {
            "staged_pdfs": None, "sidecars": None, "prefetch_target": prefetch_target,
            "stalled": stalled, "new_last_pass": new_last_pass,
        }
    return {
        "staged_pdfs": len(glob.glob(str(cache_dir / "*.pdf"))),
        "sidecars": len(glob.glob(str(cache_dir / "*.json"))),
        "prefetch_target": prefetch_target,
        "stalled": stalled, "new_last_pass": new_last_pass,
    }


def _tail_download_stall(log_path: str | Path) -> tuple[bool, int | None]:
    """`(stalled, new_last_pass)` -- scans the same tail window `_tail_download_pace` does. The
    LATER of the last stall match and the last pace match wins (byte offset within the tail), so a
    stall immediately followed by fresh progress reads as NOT stalled."""
    try:
        path = Path(log_path)
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - _LOG_TAIL_BYTES))
            tail = f.read().decode(errors="replace")
    except OSError:
        return False, None
    stall_matches = list(_DOWNLOAD_STALL_RE.finditer(tail))
    if not stall_matches:
        return False, None
    pace_matches = list(_DOWNLOAD_PACE_RE.finditer(tail))
    last_stall = stall_matches[-1]
    if pace_matches and pace_matches[-1].start() > last_stall.start():
        return False, None
    return True, int(last_stall.group(3))


# --- downloader liveness + pace (app.prefetch_pdfs, OG-43) --------------------------------------

# Same names `app/build_corpus.py::_PREFETCH_PID_NAME`/`_PREFETCH_LOG_NAME` write -- duplicated
# (this file's own "own your own copies" convention, see module docstring) rather than imported,
# so this lightweight reader never pulls in `app.build_corpus`'s subprocess-launch machinery.
_PREFETCH_PID_NAME = "prefetch.pid"
_PREFETCH_LOG_NAME = "prefetch.log"

# app/prefetch_pdfs.py's own progress line: "prefetch_pdfs: downloaded %d / target %d (cache now
# %d)". `_spawn_prefetch` gives it a DEDICATED `<run_cwd>/prefetch.log` (this process's only
# writer) -- a real incident had this tail an OLDER shared log build_corpus/app.ingest also wrote
# their own, far more verbose, parse-progress logging into: one Pass-1 parse batch's spam pushed
# the last real pace line tens of MB further back than `_LOG_TAIL_BYTES` ever reached, permanently
# blanking these fields even while prefetch was alive and working.
_DOWNLOAD_PACE_RE = re.compile(r"downloaded (\d+) / target (\d+)")

# How far back to seek before tailing the prefetch log for the latest pace line -- a dedicated,
# single-writer log stays small, but this still bounds I/O for a many-day-long run, and this is
# read on every ~4s status poll.
_LOG_TAIL_BYTES = 65_536


def read_downloader(
    run_cwd: str | Path | None, manifest_pid: int | None = None, *,
    live_pids: Callable[[], list[int]] | None = None,
    data_dir: str | Path | None = None,
) -> dict:
    """Is `app.prefetch_pdfs` alive, and its download pace -- `run_cwd` is the directory
    `app.build_corpus` (its parent) was actually launched with as `cwd` (`run_manifest.json`'s
    `run_cwd`, OG-43): ordinarily the real data dir, but a run-scoped override-config scratch dir
    when `keywords`/`parse_batch_size` were edited for this run -- `app.prefetch_pdfs`'s own
    `<that dir>/prefetch.pid`/`prefetch.log` both move with it, so this must match wherever it
    actually landed rather than assuming the fixed data dir.

    D-6 Task 1: `manifest_pid` is the run manifest's own tracked pid, for EITHER mode. The
    AUTHORITY for "is anything downloading right now" is `live_pids()` -- a scan of the process
    table (`_live_prefetch_pids`, default) -- not `manifest_pid` or `prefetch.pid`: the
    2026-08-01 incident had a real `app.prefetch_pdfs` alive for ~20 hours, tracked by NEITHER,
    because `prefetch.pid` is written by both `app/build_corpus.py` and
    `controller._spawn_download` and reconciled by nobody. `tracked_pid` is `manifest_pid` only
    when it's actually confirmed live.

    RI-8: the default scan is qualified by `data_dir` -- the dashboard's own -- so a second live
    corpus's downloader is not counted as ours (see `_live_prefetch_pids`). An injected
    `live_pids` callable replaces the scan wholesale, its qualification included.

    D-10 Task 3: `orphan` is `True` iff at least one live pid is neither `manifest_pid` nor a
    DESCENDANT of it (`_is_descendant_of`, walking `/proc/<pid>/stat` PPID chains). A `mode="full"`
    run's manifest pid is a `build_corpus` SUPERVISOR, not a downloader itself, but it legitimately
    spawns `app.prefetch_pdfs` as a *child* -- the live 2026-08-01 bug was `server.py` passing
    `manifest_pid=None` for every `full` run (so the child matched nothing) rather than this
    function itself; now that the caller always passes the manifest pid, a plain `!=` check would
    still misreport that legitimate child as an orphan, hence the descendant walk.

    D-6 Task 3: `tags_pending` warns when `tag_pool.json` was edited AFTER the live downloader's
    own launch-time `load_config()` (`app/prefetch_pdfs.py:433`, called once, never re-read) --
    `None` (never a fabricated `False`) whenever there's nothing to compare a live downloader
    against."""
    pid = _read_prefetch_pid(run_cwd) if run_cwd else None
    downloaded, target = (
        _tail_download_pace(Path(run_cwd) / _PREFETCH_LOG_NAME) if run_cwd else (None, None)
    )
    # RI-8: the default scan is qualified by THIS dashboard's data_dir, so another corpus's
    # live downloader is not counted as ours. An injected `live_pids` callable owns its own
    # qualification (tests inject zero-arg fakes), hence the plain call on that branch.
    live = live_pids() if live_pids is not None else _live_prefetch_pids(data_dir=data_dir)
    orphan = any(
        p != manifest_pid and not _is_descendant_of(p, manifest_pid) for p in live
    )
    tracked_pid = manifest_pid if manifest_pid in live else None
    reference_pid = tracked_pid if tracked_pid is not None else (live[0] if live else None)
    return {
        "prefetch_alive": _is_live_prefetch(pid) if pid is not None else None,
        "downloaded": downloaded,
        "prefetch_target": target,
        "live_pids": live,
        "orphan": orphan,
        "tracked_pid": tracked_pid,
        "tags_pending": _tags_pending(data_dir, reference_pid),
    }


def _read_prefetch_pid(run_cwd: str | Path) -> int | None:
    try:
        return int((Path(run_cwd) / _PREFETCH_PID_NAME).read_text().strip())
    except (OSError, ValueError):
        return None


_PREFETCH_MODULE = "app.prefetch_pdfs"


def _read_cmdline_argv(pid: int, proc_root: str | Path = "/proc") -> list[str] | None:
    """`/proc/<pid>/cmdline`'s NUL-separated argv, or `None` if unreadable/vanished -- races and
    permission errors are normal while scanning and must never raise into a status poll.
    `proc_root` is a test seam (default the real `/proc`)."""
    try:
        raw = Path(proc_root, str(pid), "cmdline").read_bytes()
    except OSError:
        return None
    parts = raw.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()  # trailing NUL produces one empty element after the last real argv entry
    return [p.decode(errors="replace") for p in parts]


def _is_prefetch_argv(argv: list[str]) -> bool:
    """True iff `-m` is immediately followed by `app.prefetch_pdfs` as adjacent argv elements --
    what a real `python -m app.prefetch_pdfs` looks like, the same anchoring
    `scripts/dashboard.sh` already uses for its own PID lookup (`-m app\\.dashboard\\.server`).

    D-12: the previous check was a bare substring test (`"app.prefetch_pdfs" in cmdline`), which
    also matched a diagnostic `pgrep -af "app.prefetch_pdfs"` (the string is present but not
    preceded by `-m`) or a `bash -c "...app.prefetch_pdfs..."` one-liner (the whole script is one
    argv element, so adjacency is impossible). Exact equality, not a prefix, so
    `app.prefetch_pdfs_experimental` does not match either."""
    return any(a == "-m" and b == _PREFETCH_MODULE for a, b in zip(argv, argv[1:]))


def _process_cwd(pid: int, proc_root: str | Path = "/proc") -> str | None:
    """`/proc/<pid>/cwd` -- the kernel-maintained symlink to the process's working directory --
    fully resolved, or `None` if unreadable/vanished. Races and permission errors are normal
    while scanning and must never raise into a status poll, the same rule `_read_cmdline_argv`
    applies to cmdline. `proc_root` is a test seam (default the real `/proc`)."""
    try:
        return os.path.realpath(os.readlink(Path(proc_root, str(pid), "cwd")))
    except OSError:
        return None


def _process_cwd_within(pid: int, data_dir: str | Path, proc_root: str | Path = "/proc") -> bool:
    """True iff `pid`'s working directory resolves to `data_dir` itself or anywhere INSIDE it.
    Containment, not equality, because an edited run's downloader legitimately runs with
    cwd=`<data_dir>/.run_overrides/<run_id>`: `app.build_corpus` resolves its own data dir as
    `Path.cwd()` (build_corpus.py:779) and the controller launches it inside that scratch dir,
    so the spawned prefetch child inherits the scratch dir as its cwd. An unreadable cwd counts
    as outside, not an error (`_process_cwd`). Both sides are resolved so a symlinked data_dir
    compares against the kernel's canonical cwd target rather than failing a string comparison."""
    cwd = _process_cwd(pid, proc_root)
    if cwd is None:
        return False
    return Path(cwd).is_relative_to(Path(data_dir).resolve())


def _is_live_prefetch(
    pid: int, proc_root: str | Path = "/proc", data_dir: str | Path | None = None,
) -> bool:
    """pid+argv identity check -- same pattern as `app/build_corpus.py::_is_live_prefetch`
    (mirrored, not imported, for the same reason `_PREFETCH_PID_NAME` above is): alive AND its
    argv actually names `-m app.prefetch_pdfs` (D-12: argv-aware, not a substring match) --
    guards against both a stale pid file whose PID has since been recycled onto an unrelated
    process AND a process that merely mentions the module name somewhere in its own cmdline.

    RI-8: with `data_dir` set, a match is further qualified by WHERE the process runs
    (`_process_cwd_within`) -- argv alone cannot tell which corpus a matched downloader serves.
    `None` (the default) keeps the check argv-only, for the pid behind `read_downloader`'s
    `prefetch_alive`, which comes from `<run_cwd>/prefetch.pid` -- corpus-local by construction."""
    argv = _read_cmdline_argv(pid, proc_root)
    if argv is None or not _is_prefetch_argv(argv):
        return False
    if data_dir is not None and not _process_cwd_within(pid, data_dir, proc_root):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _self_and_ancestor_pids() -> set[int]:
    """D-12 belt-and-braces: this process's own pid plus its real PPID chain (always the actual
    `/proc`, independent of any `proc_root` test seam used for the candidate scan below) -- so a
    future caller that is itself launched with a matching argv can never count itself or an
    ancestor as a live downloader. Bounded by `_MAX_ANCESTOR_DEPTH`, same guard `_is_descendant_of`
    uses against a reparented process or corrupted `/proc` cycle."""
    pids = {os.getpid()}
    current = os.getpid()
    for _ in range(_MAX_ANCESTOR_DEPTH):
        parent = _process_ppid(current)
        if parent is None or parent <= 1 or parent in pids:
            break
        pids.add(parent)
        current = parent
    return pids


def _live_prefetch_pids(
    proc_root: str | Path = "/proc", data_dir: str | Path | None = None,
) -> list[int]:
    """Every live `app.prefetch_pdfs` PID downloading for THIS dashboard's corpus, from the
    process table rather than a pid file.

    `prefetch.pid` is written by BOTH `app/build_corpus.py` and `controller._spawn_download`, and
    reconciled by neither -- it was stale in every case observed on 2026-08-01. A running process
    cannot be stale, so the process table is the authority and the pid file becomes advisory.

    Reuses `_is_live_prefetch`'s argv-aware identity check, so a recycled PID cannot masquerade as
    a downloader, and excludes this process and its ancestors (`_self_and_ancestor_pids`) as a
    belt-and-braces guard against a future caller whose own argv happens to match. Unreadable
    `/proc` entries (races, permission errors) are normal while scanning and are silently skipped
    -- this must never raise into a status poll. `proc_root` is a test seam (default the real
    `/proc`).

    RI-8: argv anchoring (D-12) fixed what a matching cmdline looks like but not WHICH corpus the
    match downloads for -- with two data dirs live at once, each dashboard counted the other's
    downloader, inflating `live_pids` and tripping `orphan=True` on a healthy pair of runs. So a
    match is additionally qualified by the process's working directory against `data_dir`
    (`_process_cwd_within`, which explains why containment rather than equality). cwd, rather
    than "the config/db path the child loaded", because that is not observable from outside the
    process: `load_config()` closes the file after reading it and `SqliteIngestState` opens the
    database per-operation, so neither shows up in `/proc/<pid>/fd` at scan time -- while cwd is
    a real symlink that stays put for the process's lifetime (a grep for `chdir` in
    `app/prefetch_pdfs.py` finds none). `data_dir=None` skips the qualification -- the pre-RI-8
    behaviour, kept for callers with no data dir to qualify against; the status poll passes the
    dashboard's own."""
    excluded = _self_and_ancestor_pids()
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return []
    return sorted(
        pid for entry in entries if entry.isdigit()
        for pid in (int(entry),)
        if pid not in excluded and _is_live_prefetch(pid, proc_root, data_dir)
    )


# Bounds the PPID walk in `_is_descendant_of` so a reparented process or (in principle) a
# corrupted /proc cycle can never loop forever -- a real process tree is at most a handful of
# hops deep here (build_corpus -> prefetch_pdfs is 1), this is generous headroom, not a tuned
# limit.
_MAX_ANCESTOR_DEPTH = 32


def _process_ppid(pid: int) -> int | None:
    """Parent PID of `pid`, from `/proc/<pid>/stat` field 4 (`ppid`) -- same file/parsing
    convention as `_process_start_epoch` and `controller.py::_process_identity` (mirrored, not
    imported, this module's own "own your own copies" convention). `None` if `pid` is dead or
    `/proc` is unreadable."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        after_comm = stat.rsplit(")", 1)[1].split()
        return int(after_comm[1])
    except (OSError, IndexError, ValueError):
        return None


def _is_descendant_of(pid: int, ancestor_pid: int | None) -> bool:
    """True iff walking `pid`'s PPID chain reaches `ancestor_pid` within `_MAX_ANCESTOR_DEPTH`
    hops -- e.g. `app.build_corpus` (the manifest pid for a `mode="full"` run) spawning
    `app.prefetch_pdfs` as a direct child is one hop. `ancestor_pid=None` (no run at all) can
    never be reached, so this is always `False` in that case."""
    if ancestor_pid is None:
        return False
    current = pid
    for _ in range(_MAX_ANCESTOR_DEPTH):
        parent = _process_ppid(current)
        if parent is None or parent <= 1:
            return False
        if parent == ancestor_pid:
            return True
        current = parent
    return False


def _process_start_epoch(pid: int) -> float | None:
    """Wall-clock (UTC epoch) a process started, from `/proc/<pid>/stat` field 22 (jiffies since
    boot) converted via `/proc/uptime` and `os.sysconf("SC_CLK_TCK")`. `None` on any failure --
    a pid that has since exited, or `/proc` being otherwise unreadable, must never raise into a
    status poll. Same field `controller.py::_process_identity` already parses (duplicated, not
    imported -- this module's own "own your own copies" convention) -- that function keeps the
    raw tick count for pid-reuse identity comparison; this one converts it to wall-clock time,
    which has no use there."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # See `controller.py::_process_identity` for why the split happens after the last ')'.
        after_comm = stat.rsplit(")", 1)[1].split()
        starttime_ticks = float(after_comm[19])
        clk_tck = os.sysconf("SC_CLK_TCK")
        uptime_s = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, IndexError, ValueError):
        return None
    return time.time() - uptime_s + starttime_ticks / clk_tck


def _tags_pending(data_dir: str | Path | None, reference_pid: int | None) -> bool | None:
    """`True` iff `reference_pid`'s live downloader started BEFORE `tag_pool.json`'s last edit --
    `app/prefetch_pdfs.py:433` calls `load_config()` once, before its forever-loop, and never
    re-reads, so a running downloader keeps its launch-time queries no matter what the Tags panel
    shows now. `None` (never a fabricated `False`) whenever there's nothing to compare: no live
    downloader to reference, no `data_dir` to find the pool in, its start time can't be read, or
    the pool file doesn't exist yet."""
    if data_dir is None or reference_pid is None:
        return None
    start_epoch = _process_start_epoch(reference_pid)
    if start_epoch is None:
        return None
    try:
        mtime = (Path(data_dir) / "tag_pool.json").stat().st_mtime
    except OSError:
        return None
    return mtime > start_epoch


def _tail_download_pace(log_path: str | Path) -> tuple[int | None, int | None]:
    try:
        path = Path(log_path)
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - _LOG_TAIL_BYTES))
            tail = f.read().decode(errors="replace")
    except OSError:
        return None, None
    matches = list(_DOWNLOAD_PACE_RE.finditer(tail))
    if not matches:
        return None, None
    match = matches[-1]  # the LAST match in the tail window -- the most recent pace line
    return int(match.group(1)), int(match.group(2))


# --- disk headroom (OG-43) -----------------------------------------------------------------------


def read_disk(data_dir: str | Path) -> dict:
    """`shutil.disk_usage(data_dir)` -- one cheap stdlib call. Degrades to nulls if `data_dir`
    doesn't exist yet (a fresh dashboard pointed at a not-yet-created data dir)."""
    try:
        usage = shutil.disk_usage(data_dir)
    except OSError:
        return {"free_gb": None, "total_gb": None, "used_pct": None}
    return {
        "free_gb": usage.free / 1e9,
        "total_gb": usage.total / 1e9,
        "used_pct": (usage.used / usage.total * 100) if usage.total else None,
    }


# --- SQLite <-> vector-store consistency ------------------------------------------------------


def read_consistency(done_count: int | None, collection: str | None) -> dict:
    """`sqlite_done` (papers) vs `vector_points` (chunks+summaries -- one paper produces MANY
    points, so these are expected to differ by design, never a 1:1 match) plus the `consistent`
    verdict the design specifies (`app/telemetry.py::summarize_run`'s own `consistent = not
    (n_done > 0 and point_count == 0)` -- the OG-16/T-DOC35 failure class this is meant to catch:
    papers marked 'done' in SQLite with literally zero points in the vector store). `None` when
    either input is unknown -- no verdict can be formed without both numbers."""
    point_count = _query_vector_store_point_count(collection or "papers")
    consistent = (
        None if point_count is None or done_count is None
        else not (done_count > 0 and point_count == 0)
    )
    return {
        "sqlite_done": done_count,
        "vector_points": point_count,
        "consistent": consistent,
    }


def _query_vector_store_point_count(collection: str) -> int | None:
    """Best-effort, read-only point count via the vector store's own REST API over stdlib
    `urllib` -- same vendor-neutral pattern `app/doctor.py`/`app/telemetry.py` already use to
    reach this exact service without ever spelling its vendor name here
    (`ci/checks/vendor_isolation.py`'s allowlist is scoped to `rag/vector_index.py` only)."""
    url = f"http://{_VECTOR_STORE_HOST}:{_VECTOR_STORE_PORT}/collections/{collection}"
    try:
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            body = json.loads(resp.read())
        return int(body["result"]["points_count"])
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        return None


# --- drop-in tray (app/ingest_local.py's drop_in/ tree) ------------------------------------------

_DROP_IN_DETAIL_CAP = 20  # per-file detail returned to the UI; counts are never capped

# SQLite's default host-parameter limit is 32,766 in modern builds but was 999 historically --
# chunked so a large manifest set never risks a single oversized IN (...) statement.
_SQLITE_IN_CHUNK = 900


# `done/` means "staged into pdf_cache with a paper_id minted" -- NOT "in the corpus". A staged
# file can still be unparsed, unembedded, or quarantined downstream. The only honest source for
# "processed" is the manifest's paper_ids joined against papers.db, which is what `_processed_*`
# below does. Reporting `done/`'s count as progress would tell an operator the corpus has
# documents it does not have.
def read_drop_in(drop_dir: str | Path, db_path: str | Path) -> dict:
    drop_dir = Path(drop_dir)
    manifest_ids, latest_manifest = _read_drop_in_manifests(drop_dir)
    processed = _processed_counts(Path(db_path), manifest_ids)
    failure_reasons, truncated = _drop_in_failure_reasons(drop_dir / "failed")
    return {
        "pending_papers": _count_pdfs(drop_dir / "papers"),
        "pending_books": _count_pdfs(drop_dir / "books"),
        "staged": _count_pdfs(drop_dir / "done"),
        "failed": _count_pdfs(drop_dir / "failed"),
        "excluded": _count_pdfs(drop_dir / "excluded"),
        "failure_reasons": failure_reasons,
        "failure_reasons_truncated": truncated,
        "manifest_ids": len(manifest_ids),
        "latest_manifest": latest_manifest,
        **processed,
    }


def _count_pdfs(d: Path) -> int:
    """Counted without materializing a list -- a drop folder can hold thousands of files and this
    runs on every status poll."""
    if not d.is_dir():
        return 0
    return sum(1 for p in d.iterdir() if p.suffix.lower() == ".pdf")


def _read_drop_in_manifests(drop_dir: Path) -> tuple[set[str], str | None]:
    """Every `manifest-*.txt`'s paper_ids, unioned, plus the newest manifest's filename. Every
    manifest is read, not just the newest: each staging run writes its own, and a document staged
    three runs ago is still a dropped document."""
    if not drop_dir.is_dir():
        return set(), None
    manifests = sorted(drop_dir.glob("manifest-*.txt"))
    ids: set[str] = set()
    for m in manifests:
        try:
            ids.update(line.strip() for line in m.read_text().splitlines() if line.strip())
        except OSError:
            continue
    return ids, (manifests[-1].name if manifests else None)


def _processed_counts(db_path: Path, manifest_ids: set[str]) -> dict:
    """How many manifest paper_ids actually reached stage `done` in the corpus, split by doc_type.
    `None` (not 0) when the DB is missing/unreadable or there are no manifest ids to ask about --
    "we cannot tell" and "none made it" are different answers.

    Two tables, not one: `ingest_state.stage` carries the pipeline stage, `papers.doc_type` carries
    paper-vs-book -- `papers` itself has no `stage` column (confirmed against the live schema)."""
    null = {"processed": None, "processed_papers": None, "processed_books": None}
    if not manifest_ids:
        return null
    conn = _ro_connect(db_path)
    if conn is None:
        return null
    try:
        ids = sorted(manifest_ids)
        by_type: dict[str, int] = {}
        for i in range(0, len(ids), _SQLITE_IN_CHUNK):
            chunk = ids[i : i + _SQLITE_IN_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                "SELECT p.doc_type, COUNT(*) FROM ingest_state s "
                "JOIN papers p ON p.paper_id = s.paper_id "
                f"WHERE s.stage = 'done' AND s.paper_id IN ({placeholders}) "  # noqa: S608 - placeholders are '?' only
                "GROUP BY p.doc_type",
                chunk,
            ).fetchall()
            for doc_type, n in rows:
                by_type[str(doc_type)] = by_type.get(str(doc_type), 0) + int(n)
    except sqlite3.Error:
        return null
    finally:
        conn.close()
    return {
        "processed": sum(by_type.values()),
        "processed_papers": by_type.get("paper", 0),
        "processed_books": by_type.get("book", 0),
    }


def _drop_in_failure_reasons(failed_dir: Path) -> tuple[list[tuple[str, int]], bool]:
    """`(reason, count)` pairs from `failed/*.err`, most common first, capped at
    `_DROP_IN_DETAIL_CAP`. The bool is True when reasons were dropped by that cap."""
    if not failed_dir.is_dir():
        return [], False
    counts: dict[str, int] = {}
    for err in failed_dir.glob("*.err"):
        try:
            reason = err.read_text().strip().splitlines()[0].strip()
        except (OSError, IndexError):
            continue
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ordered[:_DROP_IN_DETAIL_CAP], len(ordered) > _DROP_IN_DETAIL_CAP


# --- TEI live health probe ------------------------------------------------------------------

# T-DOC78: same host/port app/tei_lifecycle.py already uses for its own health poll -- duplicated
# rather than imported (this module's own "own your own copies" convention, e.g. _PREFETCH_PID_NAME
# above), and deliberately stdlib urllib, not a third-party HTTP client library, matching this
# module's existing vendor-neutral live-probe style (_query_vector_store_point_count above).
_TEI_EMBED_HEALTH_URL = "http://localhost:8080/health"
_TEI_RERANK_HEALTH_URL = "http://localhost:8082/health"


def read_tei_status() -> dict:
    """Live health probe for both TEI containers -- `{"embed_healthy": bool, "rerank_healthy":
    bool}`. Each endpoint checked independently (one can be up while the other isn't). Best-effort:
    a connection failure/timeout means `False` (not healthy), never raises."""
    return {
        "embed_healthy": _probe_tei_health(_TEI_EMBED_HEALTH_URL),
        "rerank_healthy": _probe_tei_health(_TEI_RERANK_HEALTH_URL),
    }


def _probe_tei_health(url: str) -> bool:
    # A non-2xx response makes urlopen() itself raise urllib.error.HTTPError (a URLError
    # subclass) rather than returning -- so simply not raising already means "healthy", no
    # `.status` check needed (same pattern _query_vector_store_point_count above relies on
    # implicitly by only ever reading the body on the non-raising path).
    try:
        with urllib.request.urlopen(url, timeout=3.0):
            return True
    except (urllib.error.URLError, OSError):
        return False
