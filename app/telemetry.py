"""`app/telemetry.py` -- T-DOC47/T-DOC54: built-in per-run performance telemetry, structured
JSON-line run events, and an end-of-run summary, so `app.ingest` can answer "was the GPU well
utilized during this run" and "how did the run go" about itself (`reviews/OPERATIONAL-GAPS.md`
OG-5/OG-6/OG-7) instead of requiring an external GPU dashboard and hand-stamped timestamps
(`.phase0-data/pass1-gpu-underutilization.md` and the hand-rolled `gpu_cpu_sampler.sh` this
replaces).

T-DOC54 (OG-16): mostly resolved by this module shipping at all. A real incident:
`workstation-dashboard` (an external MCP tool)'s `export_history` for a 736s Pass-1 window
silently returned only the last 217s of samples -- no error, warning, or row-count hint from the
tool itself. Once a run emits its own JSON-line events and end-of-run summary, THOSE are the
source of truth for analyzing that run; an external dashboard's retention should be cross-checked
against them, never trusted alone. The operator-facing version of this note lives in
`LESSONS-LEARNED.md`'s most recent `infra` entry -- this docstring is its other home, for whoever
lands here from the code instead of the doc.

Three pieces, composed by `RunTelemetry` so they share one run id and one set of GPU samples:

1. `GpuSampler` -- a start/stop background thread polling `nvidia-smi`, same probe-and-daemon-
   thread-loop pattern as `app/benchmark.py`'s sampler (`_query_gpu`/`GpuSample`/the sampling
   loop) -- not reinvented here, just tagged with whatever pipeline stage is current
   (`set_stage()`) and extended with a power-draw reading.
2. `RunEventLog` -- an append-only JSON Lines writer: one `{"event": ..., "run_id": ...,
   "ts": ..., ...}` object per line, so an external monitor can `tail -f`/replay it to correlate
   its own metrics against this run's boundaries. The path is a constructor arg / CLI flag
   (`--events-path` on `app.ingest`), never read from the process environment (CONVENTIONS.md §3).
3. `summarize_run` -- end-of-run report: N done / N quarantined (+ reasons, from the `quarantine`/
   `quarantine_diagnostics` tables), wall-clock, papers/hour, and a SQLite<->vector-store
   consistency check. The point count comes from the vector store's own REST API over stdlib
   `urllib` -- the same vendor-neutral stdlib-HTTP pattern `app/doctor.py` already uses to health-
   check this exact service (see that module's docstring for why the vendor name is never spelled
   here: `ci/checks/vendor_isolation.py`'s `VENDOR_RULES` allows it only inside its own adapter
   file, `rag/vector_index.py`, which is outside this ticket's file territory to extend).

`app/ingest.py`'s only stage boundaries are `_run_parse_phase_subprocesses` (Pass 1, "parse") and
`_run_finish_phase` ("finish" -- summarize+embed+store run as one in-process
`orchestrator.finish_phase()` call with no further boundary this module can instrument without
editing `rag/orchestrator.py`, also outside this ticket's file territory). GPU samples and events
are tagged/labelled "parse"/"finish" accordingly, not the finer parse/summarize/embed/store split
OG-5's wording names -- the finer split needs a stage-boundary hook inside `finish_phase()` itself.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Coarser than app/benchmark.py's 0.5s -- that harness times a few-minute controlled run; a
# production app.ingest run is hours long, so 5s keeps sample counts sane over a multi-hour run
# while still resolving per-stage GPU utilization. Overridable via app.ingest's
# --telemetry-poll-interval.
DEFAULT_GPU_POLL_INTERVAL_SECONDS = 5.0
_HIGH_UTIL_THRESHOLD_PCT = 90

# Same host/port app/doctor.py's own `_HEALTH_ONLY_SERVICES` health-pings for the vector store,
# duplicated here rather than imported -- "own your own copies" is that module's own stated
# convention relative to app/assembly.py, followed here relative to app/doctor.py for the same
# reason: no cross-module coupling on a private constant for a value this stable.
_VECTOR_STORE_HOST = "localhost"
_VECTOR_STORE_PORT = 6333


# --- GPU sampling (reuses app/benchmark.py's probe-and-thread-loop pattern) ------------------


@dataclass(frozen=True)
class GpuReading:
    util_pct: int
    mem_used_mib: int
    power_draw_w: float | None


@dataclass(frozen=True)
class GpuSample:
    epoch: float
    stage: str
    util_pct: int
    mem_used_mib: int
    power_draw_w: float | None


def _query_gpu() -> GpuReading | None:
    """One `nvidia-smi` sample (util/VRAM/power), or `None` on any failure -- same best-effort
    contract as `app/gpu_headroom.py::free_vram_mib` and `app/benchmark.py::_query_gpu`. Some
    cards report `power.draw` as `[N/A]` (no power sensor) -- that alone must not discard the
    whole sample, just leave `power_draw_w` unset.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=10.0, check=True,
        )
        util_str, mem_str, power_str = result.stdout.strip().splitlines()[0].split(",")
        power_draw_w: float | None
        try:
            power_draw_w = float(power_str.strip())
        except ValueError:
            power_draw_w = None
        return GpuReading(
            util_pct=int(util_str), mem_used_mib=int(mem_str), power_draw_w=power_draw_w
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError,
            ValueError, IndexError) as e:
        logger.warning("telemetry: nvidia-smi sample failed, discarding this sample: %s", e)
        return None


class GpuSampler:
    """Background nvidia-smi poller -- same start/stop daemon-thread pattern as
    `app/benchmark.py`'s sampler, not reinvented. Every sample is tagged with whatever stage
    `set_stage()` last set (default `"unstaged"` until the caller sets one)."""

    def __init__(
        self,
        poll_interval_s: float = DEFAULT_GPU_POLL_INTERVAL_SECONDS,
        query_gpu: Callable[[], GpuReading | None] = _query_gpu,
    ):
        self._poll_interval_s = poll_interval_s
        self._query_gpu = query_gpu
        self._samples: list[GpuSample] = []
        self._stage = "unstaged"
        self._stage_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def set_stage(self, stage: str) -> None:
        with self._stage_lock:
            self._stage = stage

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            reading = self._query_gpu()
            if reading is not None:
                with self._stage_lock:
                    stage = self._stage
                self._samples.append(
                    GpuSample(
                        epoch=time.time(), stage=stage, util_pct=reading.util_pct,
                        mem_used_mib=reading.mem_used_mib, power_draw_w=reading.power_draw_w,
                    )
                )
            self._stop.wait(self._poll_interval_s)

    def stop(self) -> list[GpuSample]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        return list(self._samples)


@dataclass(frozen=True)
class StageGpuStats:
    avg_util_pct: float
    pct_at_high_util: float
    peak_vram_mib: int
    avg_power_w: float | None
    n_samples: int

    @classmethod
    def from_samples(cls, samples: list[GpuSample]) -> "StageGpuStats":
        if not samples:
            return cls(avg_util_pct=0.0, pct_at_high_util=0.0, peak_vram_mib=0, avg_power_w=None, n_samples=0)
        powers = [s.power_draw_w for s in samples if s.power_draw_w is not None]
        high = sum(1 for s in samples if s.util_pct >= _HIGH_UTIL_THRESHOLD_PCT)
        return cls(
            avg_util_pct=statistics.fmean(s.util_pct for s in samples),
            pct_at_high_util=100.0 * high / len(samples),
            peak_vram_mib=max(s.mem_used_mib for s in samples),
            avg_power_w=statistics.fmean(powers) if powers else None,
            n_samples=len(samples),
        )


def summarize_by_stage(samples: list[GpuSample]) -> dict[str, StageGpuStats]:
    by_stage: dict[str, list[GpuSample]] = {}
    for s in samples:
        by_stage.setdefault(s.stage, []).append(s)
    return {stage: StageGpuStats.from_samples(group) for stage, group in by_stage.items()}


# --- structured JSON-line run events -----------------------------------------------------------


class RunEventLog:
    """Append-only JSON Lines event writer -- one `{"event", "run_id", "ts", ...}` object per
    line, so an external monitor can `tail -f`/replay it to correlate its own metrics against
    this run's boundaries (OG-6). `path` is a constructor arg (an `app.ingest --events-path` CLI
    flag in practice), never read from the process environment.
    """

    def __init__(self, path: str | Path, run_id: str):
        self._path = Path(path)
        self._run_id = run_id
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, **fields) -> dict:
        record = {"event": event, "run_id": self._run_id, "ts": time.time(), **fields}
        with self._path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        return record


# --- SQLite<->vector-store consistency check + end-of-run summary ------------------------------


def _query_vector_store_point_count(host: str, port: int, collection: str) -> int | None:
    """Best-effort, read-only point count for `collection`, via the vector store's own REST API
    over stdlib `urllib` -- same vendor-neutral stdlib-HTTP pattern `app/doctor.py` already uses
    to health-check this exact service (see that module's docstring for why the vendor name is
    never spelled here). `None` on any failure -- an unreachable/misconfigured vector store must
    never crash the end-of-run summary, only skip the consistency check.
    """
    url = f"http://{host}:{port}/collections/{collection}"
    try:
        with urllib.request.urlopen(url, timeout=10.0) as resp:
            body = json.loads(resp.read())
        return int(body["result"]["points_count"])
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
        logger.warning("telemetry: vector-store point-count probe failed for %r: %s", collection, e)
        return None


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    n_done: int
    n_quarantined: int
    quarantine_reasons: dict[str, int]
    wall_clock_s: float
    papers_per_hour: float
    vector_store_point_count: int | None
    sqlite_done_count: int
    consistent: bool | None
    gpu_by_stage: dict[str, StageGpuStats]

    def format(self) -> str:
        """The printed end-of-run report (OG-7): N done, N quarantined (+ reasons), wall-clock,
        papers/hour, and the SQLite<->vector-store consistency check -- what OG-7's manual
        workaround queried by hand, plus what OG-5's manual GPU-util correlation used to need an
        external dashboard for.
        """
        lines = [
            f"=== app.ingest run {self.run_id} summary ===",
            f"done: {self.n_done}  quarantined: {self.n_quarantined}",
        ]
        if self.quarantine_reasons:
            reasons = ", ".join(f"{k}={v}" for k, v in sorted(self.quarantine_reasons.items()))
            lines.append(f"  quarantine reasons: {reasons}")
        lines.append(
            f"wall-clock: {self.wall_clock_s:.1f}s  papers/hour: {self.papers_per_hour:.1f}"
        )
        if self.vector_store_point_count is None:
            lines.append("vector-store point count: unavailable (probe failed) -- consistency check skipped")
        else:
            status = "OK" if self.consistent else "MISMATCH"
            lines.append(
                f"vector-store points: {self.vector_store_point_count}  "
                f"sqlite done: {self.sqlite_done_count}  [{status}]"
            )
        for stage, stats in sorted(self.gpu_by_stage.items()):
            power = f" avg_power={stats.avg_power_w:.0f}W" if stats.avg_power_w is not None else ""
            lines.append(
                f"  [{stage}] avg_util={stats.avg_util_pct:.1f}% "
                f"pct_at_high_util={stats.pct_at_high_util:.1f}% "
                f"peak_vram={stats.peak_vram_mib}MiB{power} n_samples={stats.n_samples}"
            )
        return "\n".join(lines)


def summarize_run(
    db_path: str,
    *,
    wall_clock_s: float,
    collection: str,
    gpu_samples: list[GpuSample],
    vector_store_host: str = _VECTOR_STORE_HOST,
    vector_store_port: int = _VECTOR_STORE_PORT,
    run_id: str = "",
    query_point_count: Callable[[str, int, str], int | None] = _query_vector_store_point_count,
) -> RunSummary:
    """Builds one `RunSummary` from `ingest_state`/`quarantine`/`quarantine_diagnostics`
    (`db_path` must already be migrated -- `app.ingest._ensure_db_migrated` guarantees this before
    telemetry starts) plus a live vector-store point-count probe. A `sqlite3.Error` while reading
    the summary itself must never crash the run's shutdown path (this runs from a `finally` block
    in `app.ingest`, possibly after the run's own real failure) -- degrades to a zeroed report
    with a `logger.critical` instead.
    """
    try:
        conn = sqlite3.connect(db_path)
        try:
            n_done = conn.execute(
                "SELECT count(*) FROM ingest_state WHERE stage = 'done'"
            ).fetchone()[0]
            n_quarantined = conn.execute("SELECT count(*) FROM quarantine").fetchone()[0]
            reason_rows = conn.execute(
                "SELECT error_type, count(*) FROM quarantine_diagnostics GROUP BY error_type"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.critical(
            "telemetry.summarize_run: could not read %r for the end-of-run summary: %s",
            db_path, e, exc_info=True,
        )
        n_done, n_quarantined, reason_rows = 0, 0, []

    papers_per_hour = (n_done / (wall_clock_s / 3600.0)) if wall_clock_s > 0 else 0.0
    point_count = query_point_count(vector_store_host, vector_store_port, collection)
    # Loose but exactly the OG-16/T-DOC35 failure class this is meant to catch: papers marked
    # 'done' in SQLite with literally zero points in the vector store (a whole-collection version
    # of T-DOC35's "59 papers done with zero chunks"). Not an exact count match -- one paper
    # produces many points (one per chunk + one per summary), so raw equality would never hold.
    consistent = None if point_count is None else not (n_done > 0 and point_count == 0)

    return RunSummary(
        run_id=run_id,
        n_done=n_done,
        n_quarantined=n_quarantined,
        quarantine_reasons=dict(reason_rows),
        wall_clock_s=wall_clock_s,
        papers_per_hour=papers_per_hour,
        vector_store_point_count=point_count,
        sqlite_done_count=n_done,
        consistent=consistent,
        gpu_by_stage=summarize_by_stage(gpu_samples),
    )


# --- composition: one run's telemetry, sharing the same counters -------------------------------


class RunTelemetry:
    """Owns one run's GPU sampler + JSON-line event log + run id -- the "shared counters" T-DOC47
    asks per-run telemetry, run events, and the end-of-run summary to share. `app/ingest.py`
    usage:

        run = RunTelemetry.start(events_path=args.events_path, poll_interval_s=...)
        try:
            run.stage_start("parse"); _run_parse_phase_subprocesses(...); run.stage_end("parse")
            run.stage_start("finish"); _run_finish_phase(cfg); run.stage_end("finish")
        finally:
            run.finish(db_path=cfg.db_path, collection=cfg.collection)
    """

    def __init__(self, run_id: str, events: RunEventLog, sampler: GpuSampler, start_monotonic: float):
        self.run_id = run_id
        self._events = events
        self._sampler = sampler
        self._start_monotonic = start_monotonic

    @classmethod
    def start(
        cls,
        *,
        events_path: str,
        poll_interval_s: float = DEFAULT_GPU_POLL_INTERVAL_SECONDS,
        requested_paper_count: int | None = None,
        query_gpu: Callable[[], GpuReading | None] = _query_gpu,
    ) -> "RunTelemetry":
        run_id = uuid.uuid4().hex[:12]
        events = RunEventLog(events_path, run_id)
        events.emit("RUN_START", stage=None, paper_count=requested_paper_count)
        sampler = GpuSampler(poll_interval_s=poll_interval_s, query_gpu=query_gpu)
        sampler.start()
        return cls(run_id, events, sampler, time.monotonic())

    def stage_start(self, stage: str) -> None:
        self._sampler.set_stage(stage)
        self._events.emit("STAGE_START", stage=stage)

    def stage_end(self, stage: str) -> None:
        self._events.emit("STAGE_END", stage=stage)

    def finish(
        self,
        *,
        db_path: str,
        collection: str,
        vector_store_host: str = _VECTOR_STORE_HOST,
        vector_store_port: int = _VECTOR_STORE_PORT,
        query_point_count: Callable[[str, int, str], int | None] = _query_vector_store_point_count,
    ) -> RunSummary:
        samples = self._sampler.stop()
        wall_clock_s = time.monotonic() - self._start_monotonic
        summary = summarize_run(
            db_path,
            wall_clock_s=wall_clock_s,
            collection=collection,
            gpu_samples=samples,
            vector_store_host=vector_store_host,
            vector_store_port=vector_store_port,
            run_id=self.run_id,
            query_point_count=query_point_count,
        )
        self._events.emit(
            "RUN_END",
            n_done=summary.n_done,
            n_quarantined=summary.n_quarantined,
            wall_clock_s=round(summary.wall_clock_s, 2),
        )
        print(summary.format())
        return summary
