"""`app/dashboard/controller.py` -- the Run Controller: start/pause/resume/stop/retarget a corpus-
ingestion run via `run_manifest.json` + OS signals, the same coordination contract the real
launcher already writes (`docs/DESIGN-corpus-dashboard.md`, "The coordination contract").

The **sole reader and writer** of `run_manifest.json` (principal-design-review finding #6):
`status.py` never opens this file -- `server.py` composes the final `/api/status` response from
`controller.liveness()` (run identity + config) plus `status.py`'s pure telemetry/`ingest_state`
reads. This module never touches `papers.db` -- only the manifest and the `app.ingest` subprocess.

The launch invocation matches the live 3K run exactly: `env PYTHONPATH=<repo> python -m
app.ingest --parse-workers N --limit TARGET --events-path <path>`, `cwd=<data_dir>`.

**The real double-run guard is `app/ingest.py`'s own `.ingest.lock`** (`filelock`, acquired
non-blocking as that module's first action, held for the whole run) -- it catches a manual
`python -m app.ingest` too, which never touches this manifest. The guard in this module (below)
is a second, friendlier line of defense: a fast, clear refusal from the dashboard itself before
even trying to spawn a process that would just immediately lose the lock race.

**PID-reuse safety** (principal-design-review finding #1): a bare `os.kill(pid, 0)` cannot tell a
live process we spawned apart from an unrelated process the OS has since recycled that same PID
onto (crash, reboot, PID-space wraparound). Every spawn captures the child's `/proc/<pid>/stat`
start-time and full `/proc/<pid>/cmdline` into the manifest (`_capture_identity`); every later
signal is preceded by `_verified_pid`, which refuses to signal unless *both* still match the
process currently living at that PID. A mismatch is treated as "that process is already gone" --
never signaled, never trusted as still running.

**Process-group signaling** (finding #3b): `_spawn` launches `app.ingest` with
`start_new_session=True`, making it the leader of a fresh process group (pgid == pid). Its own
Pass-1 `subprocess.Popen` calls for `app.parse_phase` workers (`app/ingest.py`,
`_run_parse_phase_subprocesses`) never set their own session, so they inherit that same group.
Signaling the group (`os.killpg`) reaches the parse workers too -- a plain `os.kill(pid, ...)`
would only hit the leader, leaving workers to reparent to init and keep burning GPU while the
manifest says paused.

**Transitional states** (finding #5): `pause`/`stop` set `status` to `"pausing"`/`"stopping"`
before signaling, then poll (bounded) for the process to actually exit before settling on
`"paused"`/`"done"`. `resume` refuses to relaunch while a prior stop/pause hasn't yet been
confirmed dead (`DoubleRunError`) rather than assuming the signal already worked -- SIGTERM is a
request, not a guarantee.

**Atomic writes** (finding #4): every manifest write is `write-temp` + `os.replace()` (POSIX-
atomic rename) -- a concurrent reader (the dashboard's own `GET /api/status` poll) can never
observe a torn/partial JSON file and misread "no active run."
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from rag.config import load_config

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_NAME = "run_manifest.json"

# How long pause/stop/resume wait for a signaled process to actually exit before giving up and
# leaving status "pausing"/"stopping" (pause/stop) or refusing (resume) -- generous enough for a
# GPU process mid-batch to unwind, short enough not to hang an HTTP control request forever.
_DEATH_TIMEOUT_S = 8.0
_DEATH_POLL_S = 0.2

_LIVE_STATUSES = ("running", "pausing", "stopping")

# Injectable seam for tests: production always launches the real `app.ingest`; a test passes a
# fake (e.g. `sleep`) so a controller test never starts a real GPU-bound ingest (`spawn` accepts a
# dependency instead of constructing one -- codebase-design's testability principle #1).
SpawnFn = Callable[[Path, int, int, Path, Path], int]


class DoubleRunError(RuntimeError):
    """Raised when start/resume is refused because a run is already live (or not yet confirmed
    dead)."""


class NoRunError(RuntimeError):
    """Raised when pause/resume/stop is asked to act on a run that doesn't exist."""


# --- manifest I/O (atomic) ----------------------------------------------------------------------


def _manifest_path(data_dir: Path) -> Path:
    return data_dir / _MANIFEST_NAME


def _read_manifest(data_dir: Path) -> dict | None:
    try:
        return json.loads(_manifest_path(data_dir).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_manifest(data_dir: Path, manifest: dict) -> None:
    """write-temp + `os.replace()`: the rename is POSIX-atomic, so a concurrent reader always
    sees either the old file or the new one in full, never a torn read mid-write."""
    path = _manifest_path(data_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, path)


# --- process identity (PID-reuse safety) ---------------------------------------------------------


def _process_identity(pid: int) -> tuple[float, str] | None:
    """(starttime_ticks, cmdline) for a currently-live `pid`, or `None` if it's dead or `/proc`
    is unreadable. `/proc/<pid>/stat`'s 22nd field (start-time, in clock ticks since boot) is
    immutable for a process's whole lifetime and never reused until the PID itself is -- pairing
    it with the full cmdline is enough to tell "still our process" from "OS recycled this PID."
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # `comm` (field 2) is parenthesized and may itself contain spaces/parens -- split after
        # the LAST ')' to skip it reliably. Remaining fields start at field 3 (state), so index
        # 19 in this array is field 22 (starttime).
        after_comm = stat.rsplit(")", 1)[1].split()
        starttime = float(after_comm[19])
        cmdline = Path(f"/proc/{pid}/cmdline").read_text()
    except (OSError, IndexError, ValueError):
        return None
    return starttime, cmdline


def _capture_identity(pid: int) -> tuple[float | None, str | None]:
    """Best-effort identity capture right after spawn. A few quick retries: `/proc/<pid>/*` can
    lag a hair behind `Popen()` returning."""
    for _ in range(5):
        identity = _process_identity(pid)
        if identity is not None:
            return identity
        time.sleep(0.02)
    return None, None


def _verified_pid(manifest: dict) -> int | None:
    """Returns `pid` only if it's confirmed to still be the exact process this controller spawned
    (matching start-time AND cmdline) -- never a PID the OS has since recycled onto something
    else. `None` for a manifest written before this identity-tracking existed (no stored
    start-time) -- treated as "not confirmed alive," the conservative side of the guard."""
    pid = manifest.get("pid")
    stored_starttime = manifest.get("pid_starttime")
    stored_cmdline = manifest.get("pid_cmdline")
    if not pid or stored_starttime is None or stored_cmdline is None:
        return None
    identity = _process_identity(pid)
    if identity is None:
        return None
    starttime, cmdline = identity
    if starttime != stored_starttime or cmdline != stored_cmdline:
        return None
    return pid


def _pid_running(pid: int) -> bool:
    """Plain liveness (no identity check) -- used only to poll a PID we already verified and just
    signaled ourselves, waiting for it to exit.

    Opportunistically reaps `pid` via a non-blocking `waitpid` first (`_spawn` calls
    `subprocess.Popen` directly, so this process is always its parent): a child this process
    spawned but never explicitly `wait()`d on stays visible to `os.kill(pid, 0)` as a zombie
    ('Z' state) even after it has fully exited and released every real resource (GPU, file
    descriptors, the `.ingest.lock`, ...) -- a zombie must read as dead here, not alive.
    """
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass  # not our child (a test's own fake pid, or already reaped) -- fine, keep checking
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_death(pid: int, *, timeout_s: float = _DEATH_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _pid_running(pid):
            return True
        time.sleep(_DEATH_POLL_S)
    return not _pid_running(pid)


def _signal_group(pid: int, sig: int) -> None:
    """Signals the whole process group `pid` leads (`start_new_session=True` at spawn makes
    pid == pgid), so Pass-1's parse-worker children -- which inherit that same group -- die too,
    instead of reparenting to init and continuing to run while the manifest says paused/stopped.
    """
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        os.kill(pid, sig)  # fallback: at least reach the leader we can signal


# --- reconciliation (the sole manifest read/write authority) ------------------------------------


def reconcile(data_dir: str | Path) -> dict | None:
    """If the manifest is in a live-looking status (`running`/`pausing`/`stopping`) but its PID
    is no longer confirmed to be our process, downgrade the persisted status to the matching
    terminal state (`running`->`done`, `pausing`->`paused`, `stopping`->`done`) -- there is no
    separate "crashed" signal available from outside the process, a dead/reused PID with nothing
    to inspect reads the same as "it finished." Idempotent and cheap enough to call on every
    status poll (`server.py` does, before every `GET /api/status`)."""
    data_dir = Path(data_dir)
    manifest = _read_manifest(data_dir)
    if manifest is None:
        return None
    status = manifest.get("status")
    if status in _LIVE_STATUSES and _verified_pid(manifest) is None:
        manifest["status"] = {"running": "done", "pausing": "paused", "stopping": "done"}[status]
        _write_manifest(data_dir, manifest)
    return manifest


def liveness(data_dir: str | Path) -> dict | None:
    """The authoritative view of the current run: the reconciled manifest. `status.py` never
    reads `run_manifest.json` directly -- `server.py` merges this with `status.py`'s pure
    telemetry/`ingest_state` reads to build the `/api/status` response."""
    return reconcile(data_dir)


# --- spawning ------------------------------------------------------------------------------------


def _spawn(data_dir: Path, target: int, parse_workers: int, events_path: Path, log_path: Path) -> int:
    """The real launch: `env PYTHONPATH=<repo> python -m app.ingest --parse-workers N --limit
    TARGET --events-path <path>`, `cwd=<data_dir>`, as its own process-group leader (see
    `_signal_group`). Returns the child's PID."""
    cmd = [
        sys.executable, "-m", "app.ingest",
        "--parse-workers", str(parse_workers),
        "--limit", str(target),
        "--events-path", str(events_path),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    log_f = log_path.open("a")
    proc = subprocess.Popen(
        cmd, cwd=str(data_dir), env=env, stdout=log_f, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc.pid


def _build_manifest(run_id: str, pid: int, target: int, parse_workers: int,
                     events_path: Path, log_path: Path, db_path: Path) -> dict:
    cfg = load_config(_REPO_ROOT / "config.yaml")
    starttime, cmdline = _capture_identity(pid)
    return {
        "run_id": run_id,
        "pid": pid,
        "pid_starttime": starttime,
        "pid_cmdline": cmdline,
        "status": "running",
        "target": target,
        "parse_workers": parse_workers,
        "events_path": str(events_path),
        "log_path": str(log_path),
        "db_path": str(db_path),
        "collection": cfg.collection,
        "started_at": datetime.now(UTC).isoformat(),
        "focus_queries": cfg.focus_area_queries,
        "params": {"parse_workers": parse_workers, "limit": target, "telemetry_poll_interval": None},
    }


# --- public control surface -----------------------------------------------------------------


def start(data_dir: str | Path, target: int, parse_workers: int = 3, *, spawn: SpawnFn = _spawn) -> dict:
    """Fresh run with a new target. Refuses if a run is already live (`running`/`pausing`/
    `stopping`) -- pause or stop it first."""
    data_dir = Path(data_dir)
    manifest = reconcile(data_dir)
    if manifest is not None and manifest.get("status") in _LIVE_STATUSES:
        raise DoubleRunError(
            f"run {manifest['run_id']!r} is still live (status={manifest['status']!r}) -- "
            "pause or stop it before starting a fresh run"
        )

    run_id = f"run-{target}-{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    events_path = data_dir / f"ingest_events_{run_id}.jsonl"
    log_path = data_dir / f"ingest_{run_id}.log"
    db_path = data_dir / "papers.db"
    pid = spawn(data_dir, target, parse_workers, events_path, log_path)
    manifest = _build_manifest(run_id, pid, target, parse_workers, events_path, log_path, db_path)
    _write_manifest(data_dir, manifest)
    return manifest


def pause(data_dir: str | Path) -> dict:
    """SIGTERM the running process group and mark `status: "paused"` once its death is confirmed
    (`status: "pausing"` in between). Safe by construction: ingestion is checkpointed
    (`ingest_state`/`ingest_checkpoint`), so a paused run loses at most the in-flight parse batch,
    which re-does on resume."""
    data_dir = Path(data_dir)
    manifest = reconcile(data_dir)
    if manifest is None or manifest.get("status") != "running":
        raise NoRunError("no running run to pause")
    pid = manifest["pid"]
    manifest["status"] = "pausing"
    _write_manifest(data_dir, manifest)
    _signal_group(pid, signal.SIGTERM)
    manifest["status"] = "paused" if _wait_for_death(pid) else "pausing"
    _write_manifest(data_dir, manifest)
    return manifest


def resume(data_dir: str | Path, *, spawn: SpawnFn = _spawn) -> dict:
    """Relaunch `app.ingest` with the SAME params as the existing manifest -- checkpoints make
    this safe, it picks up where it left off. Refuses (`DoubleRunError`) if the prior run is
    still `running`, or if a `pausing`/`stopping` run's process hasn't yet been confirmed dead --
    SIGTERM is a request, not a guarantee, and relaunching before the old process actually exits
    would duplicate the GPU work it's still mid-way through."""
    data_dir = Path(data_dir)
    manifest = reconcile(data_dir)
    if manifest is None:
        raise NoRunError("no run to resume")

    status = manifest.get("status")
    if status == "running":
        raise DoubleRunError(f"run {manifest['run_id']!r} is already running (pid {manifest['pid']})")
    if status in ("pausing", "stopping"):
        pid = manifest.get("pid")
        if not pid or not _wait_for_death(pid, timeout_s=_DEATH_TIMEOUT_S):
            raise DoubleRunError(
                f"run {manifest['run_id']!r} has not confirmed stopped yet (status={status!r}) "
                "-- refusing to resume until its process exits"
            )
        manifest["status"] = "paused" if status == "pausing" else "done"
        _write_manifest(data_dir, manifest)

    events_path = Path(manifest["events_path"])
    log_path = Path(manifest["log_path"])
    pid = spawn(data_dir, manifest["target"], manifest["parse_workers"], events_path, log_path)
    starttime, cmdline = _capture_identity(pid)
    manifest["pid"] = pid
    manifest["pid_starttime"] = starttime
    manifest["pid_cmdline"] = cmdline
    manifest["status"] = "running"
    _write_manifest(data_dir, manifest)
    return manifest


def stop(data_dir: str | Path) -> dict:
    """SIGTERM the running process group and mark the run `status: "done"` once its death is
    confirmed (`status: "stopping"` in between) -- a user-initiated stop is final (unlike
    `pause`, which expects a later `resume`); the checkpoints it leaves behind are still there if
    a later `start` happens to re-cover the same papers, but that's a fresh run's business."""
    data_dir = Path(data_dir)
    manifest = reconcile(data_dir)
    if manifest is None or manifest.get("status") != "running":
        raise NoRunError("no running run to stop")
    pid = manifest["pid"]
    manifest["status"] = "stopping"
    _write_manifest(data_dir, manifest)
    _signal_group(pid, signal.SIGTERM)
    manifest["status"] = "done" if _wait_for_death(pid) else "stopping"
    _write_manifest(data_dir, manifest)
    return manifest


def retarget(data_dir: str | Path, target: int, parse_workers: int = 3, *, spawn: SpawnFn = _spawn) -> dict:
    """"Start a fresh run with a new target": stop the current run if one is live, then start.
    Not exposed over the API directly (the frontend only offers "start" when nothing is live, per
    the double-run guard) -- kept for parity with the design's controller method list and for any
    caller that explicitly wants stop-then-start as one step."""
    data_dir = Path(data_dir)
    try:
        stop(data_dir)
    except NoRunError:
        pass
    return start(data_dir, target, parse_workers, spawn=spawn)
