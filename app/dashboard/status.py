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
    Returns `{"funnel": {...}, "quarantine_reasons": [...]}`."""
    db_path = Path(data_dir) / _DEFAULT_DB_NAME
    conn = _ro_connect(db_path)
    if conn is None:
        return {"funnel": _null_funnel(), "quarantine_reasons": []}
    try:
        stage_counts = dict(
            conn.execute("SELECT stage, count(*) FROM ingest_state GROUP BY stage").fetchall()
        )
        quarantine_count, reason_pairs = quarantine_summary(conn)
    except sqlite3.Error:
        return {"funnel": _null_funnel(), "quarantine_reasons": []}
    finally:
        conn.close()

    funnel = _funnel_from_stage_counts(stage_counts)
    funnel["quarantined"] = quarantine_count
    quarantine_reasons = [{"reason": reason, "count": count} for reason, count in reason_pairs]
    return {"funnel": funnel, "quarantine_reasons": quarantine_reasons}


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


def read_downloads(data_dir: str | Path, target: int | None) -> dict:
    cache_dir = Path(data_dir) / "pdf_cache"
    if not cache_dir.is_dir():
        return {"cached_pdfs": None, "sidecars": None, "target": target}
    return {
        "cached_pdfs": len(glob.glob(str(cache_dir / "*.pdf"))),
        "sidecars": len(glob.glob(str(cache_dir / "*.json"))),
        "target": target,
    }


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


def read_downloader(run_cwd: str | Path | None) -> dict:
    """Is `app.prefetch_pdfs` alive, and its download pace -- `run_cwd` is the directory
    `app.build_corpus` (its parent) was actually launched with as `cwd` (`run_manifest.json`'s
    `run_cwd`, OG-43): ordinarily the real data dir, but a run-scoped override-config scratch dir
    when `keywords`/`parse_batch_size` were edited for this run -- `app.prefetch_pdfs`'s own
    `<that dir>/prefetch.pid`/`prefetch.log` both move with it, so this must match wherever it
    actually landed rather than assuming the fixed data dir."""
    pid = _read_prefetch_pid(run_cwd) if run_cwd else None
    downloaded, target = (
        _tail_download_pace(Path(run_cwd) / _PREFETCH_LOG_NAME) if run_cwd else (None, None)
    )
    return {
        "prefetch_alive": _is_live_prefetch(pid) if pid is not None else None,
        "downloaded": downloaded,
        "prefetch_target": target,
    }


def _read_prefetch_pid(run_cwd: str | Path) -> int | None:
    try:
        return int((Path(run_cwd) / _PREFETCH_PID_NAME).read_text().strip())
    except (OSError, ValueError):
        return None


def _is_live_prefetch(pid: int) -> bool:
    """pid+cmdline identity check -- same pattern as `app/build_corpus.py::_is_live_prefetch`
    (mirrored, not imported, for the same reason `_PREFETCH_PID_NAME` above is): alive AND its
    `/proc/<pid>/cmdline` actually names `app.prefetch_pdfs`, guarding against a stale pid file
    whose PID has since been recycled onto an unrelated process."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text()
    except OSError:
        return False
    if "app.prefetch_pdfs" not in cmdline:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


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
