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
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_STAGES = ("harvested", "parsed", "chunked", "summarized", "embedded", "stored", "done")

# Same host/port `app/telemetry.py`/`app/doctor.py` already health-probe the vector store on --
# duplicated here rather than imported, matching `app/telemetry.py`'s own stated "own your own
# copies" convention for this exact constant (no cross-module coupling on a value this stable).
_VECTOR_STORE_HOST = "localhost"
_VECTOR_STORE_PORT = 6333

_DEFAULT_DB_NAME = "papers.db"


# --- ingest_state / quarantine (pure: data_dir only, no manifest) -------------------------------


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
        # OG-44: `quarantine` is an append-only dead-letter log, never reconciled -- a paper that
        # later SUCCEEDED on retry (now stage='done') stays in it forever, so a naive count
        # overstates "truly stuck" by however many later recovered. Exclude paper_ids that have
        # since reached 'done' from both the count and the reasons breakdown.
        quarantine_count = conn.execute(
            "SELECT count(*) FROM quarantine WHERE paper_id NOT IN "
            "(SELECT paper_id FROM ingest_state WHERE stage = 'done')"
        ).fetchone()[0]
        reason_rows = conn.execute(
            "SELECT error_type, count(*) AS n FROM quarantine_diagnostics "
            "WHERE paper_id NOT IN (SELECT paper_id FROM ingest_state WHERE stage = 'done') "
            "GROUP BY error_type ORDER BY n DESC"
        ).fetchall()
    except sqlite3.Error:
        return {"funnel": _null_funnel(), "quarantine_reasons": []}
    finally:
        conn.close()

    funnel = _funnel_from_stage_counts(stage_counts)
    funnel["quarantined"] = quarantine_count
    quarantine_reasons = [{"reason": reason, "count": count} for reason, count in reason_rows]
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

    `papers_per_hour` is a TRUE per-run rate (OG-44 fix): `app.build_corpus` (PR #149) is a
    supervisor that runs MULTIPLE `app.ingest` RUN_START/RUN_END cycles per dashboard run, so this
    process's own wall-clock no longer pairs meaningfully with `total_done` (the ALL-TIME
    cumulative count, including papers finished by prior runs) -- dividing the two used to invent
    a papers/hour and ETA even when the CURRENT run had completed zero papers. Anchored instead on
    the manifest's `started_at`: the rate's numerator is `COUNT(ingest_state WHERE stage='done'
    AND updated_at >= started_at)` (`_count_done_since`), its denominator is wall-clock elapsed
    since `started_at` itself (`now - started_at`), not any single events-file RUN_START. Zero
    completions since `started_at`, or too little elapsed time to be meaningful, yields `None` --
    never a fabricated number. `eta_s` (`(target - total_done) / papers_per_hour`) is `None`
    whenever `papers_per_hour` is `None` for the same reason, or `target`/`total_done` is unknown,
    or the target has already been reached.
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
    if elapsed_s is None or elapsed_s < _MIN_ELAPSED_S_FOR_RATE:
        return None
    per_run_done = _count_done_since(data_dir, started_at)
    if not per_run_done:
        return None
    return per_run_done / (elapsed_s / 3600.0)


def _elapsed_seconds_since(started_at: str) -> float | None:
    try:
        start = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return None
    now = datetime.now(UTC) if start.tzinfo is not None else datetime.now()
    return (now - start).total_seconds()


def _count_done_since(data_dir: str | Path, started_at: str) -> int | None:
    """COUNT(*) of `ingest_state` rows at `stage='done'` with `updated_at >= started_at` -- the
    THIS-run completion count (OG-44), excluding every paper finished by a prior run. Both
    timestamps are written via `datetime.now(UTC).isoformat()`
    (`rag/ingest_state_sqlite.py::checkpoint`, `controller.py::_build_manifest`), so a plain
    string comparison sorts correctly without parsing either side."""
    db_path = Path(data_dir) / _DEFAULT_DB_NAME
    conn = _ro_connect(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT count(*) FROM ingest_state WHERE stage = 'done' AND updated_at >= ?",
            (started_at,),
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
