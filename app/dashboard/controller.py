"""`app/dashboard/controller.py` -- the Run Controller: start/pause/resume/stop/retarget a corpus-
ingestion run via `run_manifest.json` + OS signals, the same coordination contract the real
launcher already writes (`docs/DESIGN-corpus-dashboard.md`, "The coordination contract").

The **sole reader and writer** of `run_manifest.json` (principal-design-review finding #6):
`status.py` never opens this file -- `server.py` composes the final `/api/status` response from
`controller.liveness()` (run identity + config) plus `status.py`'s pure telemetry/`ingest_state`
reads. This module otherwise never touches `papers.db` -- only the manifest and the
`app.build_corpus` subprocess (OG-41 -- see below; it was `app.ingest` directly before this) --
with ONE narrow, deliberate exception: `reconcile()`'s `_done_count` (OG-47#2) does a single
read-only `count(*) FROM ingest_state` so a crash mid-run (pid gone, done < target) can be told
apart from a clean finish, which the manifest alone can't answer.

**OG-41 — launches `app.build_corpus`, not `app.ingest`, directly.** `_spawn`'s command is `env
PYTHONPATH=<repo> python -m app.build_corpus --target TARGET --parse-workers N --events-path
<path>`, `cwd=<data_dir>`. `app.build_corpus` is a thin supervisor (see its own module docstring)
that keeps `app.prefetch_pdfs` running as ITS OWN child and repeatedly hands `app.ingest` a
cache-first batch (`--paper-ids-file`, OG-40) until `target` is reached -- so this controller still
launches exactly one process, but that process's process group now also holds a downloader and
however many ingest/parse-phase subprocesses are currently active, and `os.killpg` below reaches
all of them by construction (see "Process-group signaling").

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

**Process-group signaling** (finding #3b): `_spawn` launches `app.build_corpus` with
`start_new_session=True`, making it the leader of a fresh process group (pgid == pid). Every
process it launches in turn -- `app.prefetch_pdfs` (`app/build_corpus.py::_spawn_prefetch`), each
`app.ingest` batch it runs, and THAT process's own Pass-1 `subprocess.Popen` calls for
`app.parse_phase` workers (`app/ingest.py::_run_parse_phase_subprocesses`) -- never sets its own
session, so all of them inherit that same group. Signaling the group (`os.killpg`) reaches every
one of them -- downloader, ingest batch, and parse workers alike -- a plain `os.kill(pid, ...)`
would only hit the leader, leaving the rest to reparent to init and keep running while the
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
import logging
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import filelock
import yaml
from pydantic import ValidationError

from app import tei_lifecycle
from app.dashboard import tag_pool
from contracts.config import Config
from rag.config import load_config

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_NAME = "run_manifest.json"
# Where a run-scoped config override (`_write_override_config_dir`) lives: <data_dir>/.run_overrides/
# <run_id>/config.yaml -- NOT /tmp (the old `tempfile.mkdtemp` location). /tmp doesn't survive a
# reboot; a multi-day corpus build must. Keyed by run_id so pause/resume of the SAME run reuses
# the SAME dir, same lifetime contract the old tempdir had, just durable now.
_RUN_OVERRIDES_DIRNAME = ".run_overrides"
# OG-47#1: every control op (start/pause/resume/stop/retarget) is serialized under this ONE
# filelock, spanning the whole check-then-act (reconcile -> decide -> spawn/signal ->
# _write_manifest) -- see "control-op serialization" further down.
_CONTROL_LOCK_NAME = ".control.lock"

# Same path-valued Config fields as `app/ingest.py::_PATH_FIELDS` (T-DOC45/46's override
# mechanism, OG-43 reuses the same shape) -- duplicated rather than imported (`status.py`'s "own
# your own copies" convention, this module docstring's own precedent) so this lightweight,
# network-facing dashboard control process never pulls in `app.ingest`'s much heavier transitive
# import graph (`app.assembly` -> `rag.parser`/`rag.embedder`/...) just to reuse one pure helper.
_OVERRIDE_PATH_FIELDS = (
    "gpu_lock_path", "db_path", "blob_dir", "pdf_cache_dir", "batch_size_log_path",
)

# How long pause/stop/resume wait for a signaled process to actually exit before giving up and
# leaving status "pausing"/"stopping" (pause/stop) or refusing (resume) -- generous enough for a
# GPU process mid-batch to unwind, short enough not to hang an HTTP control request forever.
_DEATH_TIMEOUT_S = 8.0
_DEATH_POLL_S = 0.2

_LIVE_STATUSES = ("running", "pausing", "stopping")

# Injectable seam for tests: production always launches the real `app.build_corpus`; a test passes
# a fake (e.g. `sleep`) so a controller test never starts a real GPU-bound build (`spawn` accepts a
# dependency instead of constructing one -- codebase-design's testability principle #1).
SpawnFn = Callable[[Path, int, int, Path, Path], int]

# Same filename `app/build_corpus.py::_spawn_prefetch`/`_write_prefetch_pid` already write --
# duplicated rather than imported (this module's own "own your own copies" convention, e.g.
# `_OVERRIDE_PATH_FIELDS` above) so `app/dashboard/status.py::read_downloader` and
# `app/build_corpus.py::ensure_prefetch_running` (which only check "is a live app.prefetch_pdfs at
# this path," never who launched it) keep working against a download-only run with zero changes.
_PREFETCH_PID_NAME = "prefetch.pid"


def _spawn_download(data_dir: Path, target: int, parse_workers: int, events_path: Path,
                     log_path: Path) -> int:
    """T-DOC78: launches `app.prefetch_pdfs` directly -- no GPU-bound parser, no pass1/pass2 --
    instead of `app.build_corpus`. Matches `SpawnFn`'s shape so `_call_spawn`/`resume` need no
    changes; `target`/`parse_workers`/`events_path` don't apply to a bare downloader and are ignored
    (`app.prefetch_pdfs` reads its own stopping point from `config.prefetch_target`, unaffected by
    this run's `target`). `log_path` is expected to already be `<run_cwd>/prefetch.log` --
    `_start_locked` computes that when `mode == "download"` -- so
    `status.py::read_downloader`'s hardcoded log name keeps finding real pace lines.

    Same launch shape as `_spawn`: `env PYTHONPATH=<repo>`, `cwd=data_dir`, its own process group
    (`start_new_session=True`) so pause/stop's `os.killpg` reaches it."""
    cmd = ["env", f"PYTHONPATH={_REPO_ROOT}", sys.executable, "-m", "app.prefetch_pdfs"]
    log_f = log_path.open("a")
    proc = subprocess.Popen(
        cmd, cwd=str(data_dir), stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True,
    )
    (data_dir / _PREFETCH_PID_NAME).write_text(str(proc.pid))
    return proc.pid


def resolve_drop_dir(cfg: Config) -> Path:
    """`Config.drop_in_dir` is relative whenever config.yaml omits it (`rag/config.py::_resolve_paths`
    only resolves fields actually present in the YAML). A relative value would otherwise mean a
    different directory to the dashboard (cwd=<repo root>) than to the `app.ingest_local` child
    (cwd=<data_dir>) -- the dashboard would report a full tray while the run scanned an empty one
    and exited 0. Anchored on the repo root, which is where the tray actually lives and where the
    dashboard's own cwd already points."""
    d = Path(cfg.drop_in_dir)
    return d if d.is_absolute() else (_REPO_ROOT / d).resolve()


def _spawn_drop_in(data_dir: Path, target: int, parse_workers: int, events_path: Path,
                   log_path: Path) -> int:
    """Launches `app.ingest_local`, which stages everything under `cfg.drop_in_dir` into
    `pdf_cache` and then runs the normal ingest over the staged ids. Matches `SpawnFn`'s shape so
    `_call_spawn`/`pause`/`stop` need no changes; `target`/`parse_workers`/`events_path` do not
    apply (ingest_local's work is bounded by what is in the drop tray, not by a target) and are
    ignored, same as `_spawn_download` ignores them.

    `--drop-dir` is passed explicitly (`resolve_drop_dir`) rather than relying on the child's own
    cwd-relative default -- see that helper's docstring for why: `cfg.drop_in_dir` is relative
    whenever config.yaml omits it, and this child's cwd (`data_dir`) is NOT where the tray lives.

    `start_new_session=True` gives it its own process group, so `pause`/`stop`'s `os.killpg`
    reaches it exactly as it does a download or a full build."""
    drop_dir = resolve_drop_dir(_load_base_config(data_dir))
    cmd = ["env", f"PYTHONPATH={_REPO_ROOT}", sys.executable, "-m", "app.ingest_local",
           "--drop-dir", str(drop_dir)]
    log_f = log_path.open("a")
    proc = subprocess.Popen(
        cmd, cwd=str(data_dir), stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True,
    )
    return proc.pid


class DoubleRunError(RuntimeError):
    """Raised when start/resume is refused because a run is already live (or not yet confirmed
    dead)."""


class NoRunError(RuntimeError):
    """Raised when pause/resume/stop is asked to act on a run that doesn't exist."""


class DropInPendingError(RuntimeError):
    """A drop-in run is queued and must go first. Raised when a download/full run is started
    while `pending_drop_in` is set -- without this refusal a fresh download can be started the
    instant the previous one ends, starving the queued drop-in forever."""


class InvalidOverrideError(ValueError):
    """Raised when a config-derived override (`_maybe_build_override`) produces an invalid
    `Config` (OG-49#6/M8): `cfg.model_copy(update=...)` does NOT re-run pydantic validation, so a
    bad `ordering`/`parse_batch_size` from a `POST /api/control` body would otherwise reach a
    spawned subprocess only to crash post-spawn, after the manifest already says "running".
    Re-validating via `Config.model_validate(cfg.model_dump())` and raising this instead rejects
    it pre-spawn -- `server.py` maps it to a clean 400."""


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


# `_spawn`'s launch command's own argv[0] (see its docstring: `env PYTHONPATH=<repo> python -m
# app.build_corpus ...`) -- `env` execve()s itself away into the real long-lived program WITHIN
# THE SAME PID almost immediately. `_capture_identity` below must not let a read that lands in
# that brief transitional window permanently record `env`'s own argv as the run's "identity".
_ENV_WRAPPER_CMDLINE_PREFIX = "env\x00"


def _is_transitional_cmdline(cmdline: str) -> bool:
    """True for a `/proc/<pid>/cmdline` read caught mid-`execve()` rather than the process's real,
    settled argv -- `_capture_identity` must retry past either shape below, never accept one as
    final:

    - `_ENV_WRAPPER_CMDLINE_PREFIX` (T-DOC74): `_spawn`'s own `env PYTHONPATH=... python ...`
      wrapper execve()s itself away into the real long-lived program within the same PID; a read
      landing in that window sees `env`'s own (transitional) argv.
    - The empty string: found the hard way, chasing an intermittent flake in this very test suite
      (a *different* `app/dashboard` test failed every run, always the same family --
      `reconcile()` had downgraded a still-live `sleep 100`/`bash` test process to
      `"failed"`/`"paused"`/`"done"`). Instrumenting `_verified_pid` showed the stored cmdline was
      `""` while a fresh read of the SAME live pid came back correctly populated
      (`"sleep\\x00100\\x00"`, ...) -- `_capture_identity`'s first `/proc/<pid>/cmdline` read had
      landed in the kernel's brief "old argv cleared, new one not yet installed" window that
      exists around EVERY `execve()`, not just `_spawn`'s `env` wrapper -- so a plain `sleep 100`
      spawned with no wrapper at all can still be caught here under enough host load. Once that
      empty string is accepted as "the identity" and written to the manifest, it can never again
      match a later, correctly-populated read -- the exact permanent-mismatch failure mode
      T-DOC74 fixed for the `env`-wrapper case, one exec earlier and without the wrapper as a
      precondition.
    """
    return cmdline == "" or cmdline.startswith(_ENV_WRAPPER_CMDLINE_PREFIX)


def _capture_identity(pid: int) -> tuple[float | None, str | None]:
    """Best-effort identity capture right after spawn. A few quick retries: `/proc/<pid>/*` can
    lag a hair behind `Popen()` returning -- AND the transitional cmdline shapes `execve()` can
    briefly produce (see `_is_transitional_cmdline`) can too: a real incident had this function
    win that race, permanently capturing a transitional (wrapper or empty) cmdline that
    `/proc/<pid>/cmdline` never shows again once the exec settles. Every later `_verified_pid`
    check then mismatched forever -- an exact, healthy, actively-progressing run got downgraded to
    "failed" (and its scratch config dir queued for deletion, `_cleanup_run_cwd`) out from under
    it. Keeps retrying while the observed cmdline is still transitional, not just while `/proc` is
    unreadable; falls back to whatever was last observed (matching this function's existing
    best-effort contract) if every retry still shows a transitional cmdline -- should be rare in
    practice, `execve()` settles near-instantly, but not so rare it can be assumed away (see
    `_is_transitional_cmdline`'s empty-string case)."""
    identity = None
    for _ in range(5):
        identity = _process_identity(pid)
        if identity is not None and not _is_transitional_cmdline(identity[1]):
            return identity
        time.sleep(0.02)
    return identity if identity is not None else (None, None)


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


def _pgid_of(pid: int) -> int | None:
    """`pid`'s current process-group id, or `None` if it's already gone (`os.getpgid` raises
    `ProcessLookupError` for a dead pid) -- `_signal_group` treats that the same as any other
    "nothing left to signal" case."""
    try:
        return os.getpgid(pid)
    except ProcessLookupError:
        return None


def _signal_group(pid: int, sig: int) -> None:
    """Signals `pid` the way that actually reaches it.

    The common, INTENDED case is `pid == pgid`: every spawn (`_spawn`/`_spawn_download`/
    `_spawn_drop_in`) launches with `start_new_session=True`, making the child its own
    process-group leader. `os.killpg` there reaches the whole group, so Pass-1's parse-worker
    children -- which inherit that same group -- die too, instead of reparenting to init and
    continuing to run while the manifest says paused/stopped.

    An orphaned `app.prefetch_pdfs` is the exception: `app/build_corpus.py` deliberately spawns it
    WITHOUT `start_new_session`, so it inherits its supervisor's pgid. Once that supervisor dies,
    the child reparents to init but its pgid is unchanged -- now naming a group whose leader no
    longer exists. `killpg` REQUIRES `pid` to be a group leader; calling it on a non-leader pid
    signals nothing (measured 2026-08-01: Restart downloader left two such orphans running, while
    a plain `kill <pid>` killed them instantly). So: `killpg` only when `pid` is its own group
    leader, plain `kill` otherwise.
    """
    pgid = _pgid_of(pid)
    if pgid is None:
        return  # already gone -- nothing to signal
    try:
        if pgid == pid:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        if pgid == pid:
            os.kill(pid, sig)  # fallback: at least reach the leader we can signal


# OG-49#5: how long to wait after a RESEND of SIGTERM, and after the final SIGKILL, before giving
# up on escalation entirely -- shorter than the initial `_DEATH_TIMEOUT_S` wait since these are
# last resorts, not the normal graceful-shutdown window.
_ESCALATION_RESEND_TIMEOUT_S = 3.0
_ESCALATION_KILL_TIMEOUT_S = 3.0


def _terminate_with_escalation(pid: int) -> bool:
    """SIGTERM the process group and wait; if it's not confirmed dead within `_DEATH_TIMEOUT_S`,
    resend SIGTERM once more (some processes only act on a second delivery mid-syscall) and wait
    again; if STILL alive, escalate to SIGKILL before giving up. OG-49#5: a GPU process wedged in
    a blocking parse/generation/rerank call to one of its backing services could otherwise sit
    forever in "pausing"/"stopping" with no way out but a manual `kill -9` -- this is the one
    SIGTERM pause()/stop() used to send, now with a bounded escalation ladder instead of a single
    shot. Returns whether the process is confirmed dead by the end of this call.

    References `_DEATH_TIMEOUT_S`/`_ESCALATION_RESEND_TIMEOUT_S`/`_ESCALATION_KILL_TIMEOUT_S` as
    module globals (not as bound default-parameter values) so a test can `monkeypatch` them to
    shrink this function's total wall-clock without changing the escalation logic itself.
    """
    _signal_group(pid, signal.SIGTERM)
    if _wait_for_death(pid, timeout_s=_DEATH_TIMEOUT_S):
        return True
    _signal_group(pid, signal.SIGTERM)
    if _wait_for_death(pid, timeout_s=_ESCALATION_RESEND_TIMEOUT_S):
        return True
    _signal_group(pid, signal.SIGKILL)
    return _wait_for_death(pid, timeout_s=_ESCALATION_KILL_TIMEOUT_S)


# --- reconciliation (the sole manifest read/write authority) ------------------------------------


def _done_count(db_path: str) -> int:
    """Read-only `count(*) FROM ingest_state WHERE stage='done'` -- the one narrow, deliberate
    exception to this module's "never touches papers.db" rule (module docstring), needed so
    `reconcile()` can tell a genuine crash (pid gone, target not yet reached) from a clean finish
    (OG-47#2). Same `mode=ro` URI guarantee `app/dashboard/status.py`/`app/build_corpus.py` already
    use for the identical query; degrades to `0` on any read failure (missing/unmigrated/locked db)
    rather than raising -- reconcile() must never fail a status poll over this."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return 0
    try:
        row = conn.execute("SELECT count(*) FROM ingest_state WHERE stage='done'").fetchone()
        return row[0] if row is not None else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _crashed_before_target(manifest: dict) -> bool:
    """True iff this `running` manifest's own recorded `target` and `db_path` show fewer than
    `target` papers actually done -- the OG-47#2 crash signal. Missing/unusable fields (a manifest
    written before either existed) degrade to `False` (the old, conservative "done" behavior).

    T-DOC78: a `mode="download"` manifest's `target` is `prefetch_target`, a PDF-cache count --
    not a done-count -- and `app.prefetch_pdfs` never advances `ingest_state` at all, so
    `_done_count < target` would ALWAYS read true and every clean downloader exit would be
    misreported as a crash. This function has no meaningful crashed-vs-clean signal for that mode,
    so it degrades the same way as the missing-fields case above: treat every download-mode exit
    as clean."""
    if manifest.get("mode") == "download":
        return False
    target = manifest.get("target")
    db_path = manifest.get("db_path")
    if target is None or not db_path:
        return False
    return _done_count(db_path) < target


def reconcile(data_dir: str | Path) -> dict | None:
    """If the manifest is in a live-looking status (`running`/`pausing`/`stopping`) but its PID
    is no longer confirmed to be our process, downgrade the persisted status to the matching
    terminal state -- there is no separate "crashed" signal available from outside the process
    other than what the manifest+db already tell us. `pausing`->`paused`, `stopping`->`done`
    (a user-initiated stop is final either way); `running`->`failed` when `done_count < target`
    (OG-47#2: a crash mid-run, pid gone before reaching its own target -- previously collapsed
    into `done`, indistinguishable from a clean finish), else `running`->`done`. Idempotent and
    cheap enough to call on every status poll (`server.py` does, before every `GET /api/status`)."""
    data_dir = Path(data_dir)
    manifest = _read_manifest(data_dir)
    if manifest is None:
        return None
    status = manifest.get("status")
    if status in _LIVE_STATUSES and _verified_pid(manifest) is None:
        if status == "running":
            manifest["status"] = "failed" if _crashed_before_target(manifest) else "done"
        else:
            manifest["status"] = {"pausing": "paused", "stopping": "done"}[status]
        _write_manifest(data_dir, manifest)
        # Only "done" is cleaned up here. "paused" (from "pausing") expects a later resume() that
        # reuses run_cwd, so it must NOT be cleaned up -- unchanged (OG-49 M10). "failed" USED to
        # be cleaned up alongside "done" here, but that's exactly backwards: a crashed run is
        # precisely the one the user will resume (that's the whole point of `reconcile()` telling
        # a crash apart from a clean finish, OG-47#2) -- deleting its run_cwd out from under it
        # guaranteed `resume()`'s later `subprocess.Popen(cwd=<deleted dir>)` a `FileNotFoundError`
        # for every run that had edited keywords/filters/ordering (an override run_cwd, never the
        # real data_dir). `_resume_locked` below now rebuilds a missing run_cwd from the manifest's
        # own recorded params instead, so a "failed" run's scratch dir is left alone here; only a
        # final, user-initiated `stop()` (never resumed) or a later abandoning `start()`
        # (`_start_locked`'s own cleanup) removes it.
        if manifest["status"] == "done":
            _cleanup_run_cwd(data_dir, manifest)
    return manifest


def liveness(data_dir: str | Path) -> dict | None:
    """The authoritative view of the current run: the reconciled manifest. `status.py` never
    reads `run_manifest.json` directly -- `server.py` merges this with `status.py`'s pure
    telemetry/`ingest_state` reads to build the `/api/status` response."""
    return reconcile(data_dir)


# --- run-scoped config override (OG-43: edited keywords/parse_batch_size) ------------------------
#
# Mirrors `app/ingest.py::_write_override_config_dir` (T-DOC45/46): writes an already-overridden
# `Config` to a scratch `<tmpdir>/config.yaml`, resolving every relative-path field absolute first
# (the subprocess launched into this dir has a DIFFERENT cwd than this process) -- `data_dir` runs
# `PYTHONPATH=<repo> python -m app.build_corpus` with `cwd=<tmpdir>`, so IT and every child it
# launches in turn (`app.prefetch_pdfs`, each `app.ingest` batch) all `load_config()` this exact
# file: none of them receive this process's in-memory `Config` object directly, `config.yaml`
# itself is the only channel every one of them reads unconditionally.


def _load_base_config(data_dir: Path) -> Config:
    """OG-49#1: the run's BASE config, loaded from `<data_dir>/config.yaml` -- the real data
    directory's own config -- so an overridden run's `db_path`/`blob_dir`/`pdf_cache_dir`/
    `collection` resolve against the real corpus location. Falls back to discovery (T-DOC89 §3:
    `RAG_CONFIG` -> `config.yaml` in cwd -> walk up) only when `data_dir` has none of its own (e.g.
    a fresh/test data dir): before OG-49#1, `start`/`retarget` always loaded `_REPO_ROOT/
    config.yaml` regardless of `data_dir`, so `_write_override_config_dir`'s path resolution
    (below) resolved relative fields against the DASHBOARD SERVER PROCESS's own cwd -- not the
    corpus's actual data dir -- misdirecting every edited run's `papers.db`/`blobs` while it kept
    upserting into the real, shared vector-store collection (orphan vector points with no matching
    row in the misdirected db).

    T-DOC89 part-1-review Critical 1: §1 made `load_config()` always return ALREADY-ABSOLUTE path
    fields, resolved against wherever the loaded file's own directory is. In the fallback branch
    that "own directory" is whatever discovery happened to find (RAG_CONFIG / cwd / walk-up) --
    some OTHER corpus's location, unrelated to `data_dir`. Handing those absolute paths to
    `_resolve_override_config` below made its `(data_dir / value)` join a no-op (already absolute
    -> passed through unchanged), silently reopening the exact OG-49#1 bug: an edited run's
    `db_path` landing wherever discovery's fallback config lives, not under `data_dir`. Path
    fields are reset back to the plain `Config` class defaults here so `_resolve_override_config`
    can root them under `data_dir` as originally intended -- only the fallback's non-path levers
    (`focus_area_queries`, `ordering`, etc.) are actually meant to carry over."""
    data_dir_config = data_dir / "config.yaml"
    if data_dir_config.exists():
        return load_config(data_dir_config)
    cfg = load_config()
    defaults = {field: Config.model_fields[field].default for field in _OVERRIDE_PATH_FIELDS}
    return cfg.model_copy(update=defaults)


def _resolve_override_config(cfg: Config, data_dir: Path) -> Config:
    """`data_dir` (OG-49#1): every relative-path field is resolved absolute against the REAL data
    dir, not `Path.resolve()`'s implicit `os.getcwd()` (the dashboard SERVER process's own cwd,
    unrelated to any run) -- `Path(base) / value` is a no-op when `value` is already absolute, so
    this is safe for both a relative default (e.g. `"papers.db"`) and an already-absolute value.

    Shared by a fresh override write (`_write_override_config_dir`) and a rebuild-from-manifest
    when a run's `run_cwd` has gone missing (`_rebuild_missing_run_cwd`) -- both need the exact
    same path resolution, only the resulting `Config`'s edited fields differ."""
    path_updates = {
        field: str((data_dir / value).resolve())
        for field in _OVERRIDE_PATH_FIELDS
        if (value := getattr(cfg, field))
    }
    return cfg.model_copy(update=path_updates) if path_updates else cfg


def _write_config_yaml(cfg: Config, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump()))


def _write_override_config_dir(cfg: Config, data_dir: Path, run_id: str) -> Path:
    """Writes `cfg` (already resolved absolute -- see `_resolve_override_config`) to
    `<data_dir>/.run_overrides/<run_id>/config.yaml` and returns that directory.

    This dir is a `run_cwd` a `pause`d run's later `resume()` reuses verbatim (see
    `_resume_locked`) -- it must survive across pause/resume for the SAME run_id, and now across a
    reboot too (durable under `data_dir`, not `/tmp` -- see `_RUN_OVERRIDES_DIRNAME`).
    `_cleanup_run_cwd` is the other half: it removes this dir once the run reaches a genuinely
    terminal state that will never `resume()` again."""
    resolved = _resolve_override_config(cfg, data_dir)
    target_dir = data_dir / _RUN_OVERRIDES_DIRNAME / run_id
    _write_config_yaml(resolved, target_dir)
    return target_dir


def _rebuild_missing_run_cwd(data_dir: Path, manifest: dict, run_cwd: Path) -> None:
    """Reconstructs a resumed run's override `config.yaml` when its `run_cwd` no longer exists on
    disk (a reboot wiped the old `/tmp` location pre-dating the durable-dir fix above, or the
    directory was otherwise lost) -- rebuilt from the manifest's OWN recorded effective params
    (`focus_queries`/`parse_batch_size`/`ordering`/`arxiv_categories`/`arxiv_date_from`/
    `arxiv_date_to`, all persisted by `_build_manifest`), never from the unedited base config.

    This must NEVER silently fall back to `data_dir`'s defaults -- that would resurrect the run
    with the WRONG settings, exactly what this module's other docstrings warn a resumed edited run
    must not do. Re-validates through `Config.model_validate` the same way `_maybe_build_override`
    does, since these values came from a JSON manifest, not fresh pydantic construction, and
    `model_copy(update=...)` doesn't re-check invariants."""
    base_cfg = _load_base_config(data_dir)
    updates = {
        "focus_area_queries": manifest["focus_queries"],
        "parse_batch_size": manifest["parse_batch_size"],
        "ordering": manifest["ordering"],
        "arxiv_categories": manifest["arxiv_categories"],
        "arxiv_date_from": manifest["arxiv_date_from"],
        "arxiv_date_to": manifest["arxiv_date_to"],
    }
    unvalidated = base_cfg.model_copy(update=updates)
    try:
        effective = Config.model_validate(unvalidated.model_dump())
    except ValidationError as error:
        raise InvalidOverrideError(
            f"cannot rebuild run {manifest.get('run_id')!r}'s missing run_cwd: {error}"
        ) from error
    resolved = _resolve_override_config(effective, data_dir)
    _write_config_yaml(resolved, run_cwd)


# D-7: what gets rescued from a run's override scratch dir before it is deleted, and the flat
# per-run name it lands under in the data dir -- matching the existing
# `ingest_run-<run_id>.log` / `ingest_events_<run_id>.jsonl` convention.
#
# `prefetch.log` holds the harvest diagnostics that answer "I added a tag and nothing changed"
# ("4044 candidate papers found, 4031 already cached/claimed, 13 to download" -- 2026-08-01).
# `config.yaml` is the other half of that question: which queries this run actually used. Neither
# exists anywhere else once the scratch dir is gone. `prefetch.pid` is deliberately excluded --
# process state, meaningless after the run ends.
_ARCHIVED_RUN_ARTIFACTS = (("prefetch.log", "prefetch_{run_id}.log"),
                           ("config.yaml", "config_{run_id}.yaml"))


def _archive_run_artifacts(data_dir: Path, run_cwd: Path, run_id: str) -> list[Path]:
    """Copy a run's durable-worth artifacts out of its scratch dir into `data_dir`.

    Best-effort by contract: `_cleanup_run_cwd` is reached from `reconcile()`, which runs on every
    `/api/status` poll, so a copy failure must never raise or prevent the cleanup it precedes. A
    missing source file is normal (a run that never spawned a downloader), not an error."""
    archived: list[Path] = []
    try:
        for src_name, dest_template in _ARCHIVED_RUN_ARTIFACTS:
            src = run_cwd / src_name
            if not src.is_file():
                continue
            dest = data_dir / dest_template.format(run_id=run_id)
            shutil.copy2(src, dest)
            archived.append(dest)
    except Exception:  # noqa: BLE001 -- best-effort, must never block the cleanup it precedes
        logging.warning(
            "D-7: failed to archive run artifacts for run_id=%r from %s", run_id, run_cwd,
            exc_info=True,
        )
    return archived


def _cleanup_run_cwd(data_dir: Path, manifest: dict) -> None:
    """OG-49 M10: removes a run's override `config.yaml` scratch dir (`_write_override_config_dir`)
    once its manifest has settled into a genuinely terminal status ("done"/"failed") -- called only
    from call sites that just set one of those, never from `pause` (`"paused"` expects a later
    `resume()`, which reuses `run_cwd` verbatim -- deleting it there would break resume).

    A no-op when this run never had an override (`run_cwd == data_dir`, an unedited run launched
    directly in the real data dir -- never a scratch dir, must never be removed) or when the dir is
    already gone (`ignore_errors=True` -- e.g. `stop()` and a later `reconcile()` both observing the
    same terminal transition must not make the second cleanup call fail on the first's work).

    D-7: before removal, best-effort archives `prefetch.log` and the run's effective `config.yaml`
    into `data_dir` -- see `_archive_run_artifacts`.
    """
    run_cwd = manifest.get("run_cwd")
    if not run_cwd or Path(run_cwd) == data_dir:
        return
    _archive_run_artifacts(data_dir, Path(run_cwd), str(manifest.get("run_id") or "unknown"))
    shutil.rmtree(run_cwd, ignore_errors=True)


def _maybe_build_override(
    cfg: Config, keywords: list[str] | None, parse_batch_size: int | None, *,
    data_dir: Path, run_id: str,
    remove_keywords: list[str] | None = None,
    arxiv_categories: list[str] | None = None,
    arxiv_date_from: str | None = None,
    arxiv_date_to: str | None = None,
    ordering: str | None = None,
    stranded_policy: str | None = None,
) -> tuple[Config, Path | None]:
    """Builds a run-scoped override `Config` + scratch `config.yaml` dir when the composed tag
    pool, `parse_batch_size`, the OG-45 arXiv DOWNLOAD filters (`arxiv_categories`/
    `arxiv_date_from`/`arxiv_date_to`), or the OG-46 `ordering` actually change anything relative
    to the base config. Returns `(cfg, None)` unchanged when nothing edits -- a run that edits
    nothing launches exactly the old way (`cwd=data_dir`, no override dir, no scratch files).

    `focus_area_queries` is now composed from `tag_pool.active_queries(data_dir, ...)`, NOT from
    `cfg.focus_area_queries` directly -- `tag_pool.json` (seeded from `cfg.focus_area_queries` on
    first touch) is the persistent source of truth, so an edit made in a PRIOR run's request is
    still active here even when this call passes no `keywords`/`remove_keywords` at all. That is
    the fix for the bug this replaces: edits used to live only in a run-scoped scratch
    `config.yaml` that `_cleanup_run_cwd` deleted once the run went terminal, so the next run
    silently reverted to the base config's queries.

    `keywords` writes through `tag_pool.add` (augments the pool -- adds topics, reactivates a held
    one, never replaces -- owner decision); `remove_keywords` writes through `tag_pool.hold`
    (parks topics, applied AFTER `add` so add+remove in one request is well-defined -- a
    superseding owner decision for removal specifically). Both are the SAME add/remove meaning
    `keywords`/`remove_keywords` always had; they simply persist now instead of dying with the run.

    Holding a tag that isn't active is a harmless no-op. Holding every active tag is refused
    (`tag_pool.hold` raises `InvalidOverrideError`, pool left untouched) -- an empty
    `focus_area_queries` leaves the downloader with nothing to search.

    Removing a keyword only stops FUTURE downloads matching it; papers already ingested stay in
    the corpus -- deleting corpus content is a separate, out-of-scope, destructive action.

    OG-49#6/M8: `cfg.model_copy(update=updates)` does NOT re-run pydantic validation (it's a plain
    field copy) -- a bad `parse_batch_size`/`ordering` from a `POST /api/control` body would
    otherwise silently build an invalid `Config`, write it to the override `config.yaml`, and only
    fail once the spawned subprocess loads it and crashes (after the manifest already says
    "running"). `Config.model_validate(...)` re-validates before that ever happens; a failure
    raises `InvalidOverrideError` here, pre-spawn.
    """
    updates: dict = {}
    if keywords:
        tag_pool.add(data_dir, cfg.focus_area_queries, keywords)
    if remove_keywords:
        tag_pool.hold(data_dir, cfg.focus_area_queries, remove_keywords)
    composed_queries = tag_pool.active_queries(data_dir, cfg.focus_area_queries)
    if composed_queries != cfg.focus_area_queries:
        updates["focus_area_queries"] = composed_queries
    if parse_batch_size is not None and parse_batch_size != cfg.parse_batch_size:
        updates["parse_batch_size"] = parse_batch_size
    if arxiv_categories is not None and arxiv_categories != cfg.arxiv_categories:
        updates["arxiv_categories"] = arxiv_categories
    if arxiv_date_from is not None and arxiv_date_from != cfg.arxiv_date_from:
        updates["arxiv_date_from"] = arxiv_date_from
    if arxiv_date_to is not None and arxiv_date_to != cfg.arxiv_date_to:
        updates["arxiv_date_to"] = arxiv_date_to
    if ordering is not None and ordering != cfg.ordering:
        updates["ordering"] = ordering
    if stranded_policy is not None and stranded_policy != cfg.stranded_policy:
        updates["stranded_policy"] = stranded_policy
    if not updates:
        return cfg, None
    unvalidated = cfg.model_copy(update=updates)
    try:
        effective = Config.model_validate(unvalidated.model_dump())
    except ValidationError as error:
        raise InvalidOverrideError(
            f"invalid config override: {error}"
        ) from error
    return effective, _write_override_config_dir(effective, data_dir, run_id)


# --- spawning ------------------------------------------------------------------------------------


def _spawn(data_dir: Path, target: int, parse_workers: int, events_path: Path, log_path: Path,
           *, paper_ids_file: Path | None = None,
           telemetry_poll_interval: float | None = None, batch_size: int | None = None) -> int:
    """The real launch, literally: `env PYTHONPATH=<repo> python -m app.build_corpus --target
    TARGET --parse-workers N --events-path <path>`, `cwd=<data_dir>`, as its own process-group
    leader (see `_signal_group`). The `env` *command* -- not a Python-level env-dict read -- sets
    `PYTHONPATH` for just this one child -- `cwd=data_dir` means `-m app.build_corpus` can't
    otherwise find the `app` package, since data_dir has no `app/` of its own -- while this
    process's own environment is never inspected (CONVENTIONS.md §3 / `ci/checks/env_leak.py`: no
    reads of the process environment in `app/`). Returns the child's PID.

    `paper_ids_file` (OG-40) is still accepted here -- kept so `_call_spawn`'s uniform calling
    convention and the manifest's own threading (`start`/`resume` below) don't need
    special-casing -- but is NOT forwarded to the command line: `app.build_corpus` has no matching
    flag (OG-41: it computes its own cache-first id list every iteration from
    `pdf_cache/*.pdf` minus `ingest_state`). An explicit id-scoped run still works by invoking
    `app.ingest --paper-ids-file` directly outside the dashboard.

    `telemetry_poll_interval`/`batch_size` (OG-43): forwarded as `--telemetry-poll-interval`/
    `--batch-size` only when set -- both are plain pass-through CLI flags `app.build_corpus`
    already accepts, no config override needed. `data_dir` here is really "the cwd to launch
    `app.build_corpus` in" -- ordinarily the real data dir, but `start`/`resume` pass a run-scoped
    override-config scratch dir instead whenever `keywords`/`parse_batch_size` were edited (see
    `_maybe_build_override`)."""
    cmd = [
        "env", f"PYTHONPATH={_REPO_ROOT}",
        sys.executable, "-m", "app.build_corpus",
        "--target", str(target),
        "--parse-workers", str(parse_workers),
        "--events-path", str(events_path),
    ]
    if telemetry_poll_interval is not None:
        cmd += ["--telemetry-poll-interval", str(telemetry_poll_interval)]
    if batch_size is not None:
        cmd += ["--batch-size", str(batch_size)]
    log_f = log_path.open("a")
    proc = subprocess.Popen(
        cmd, cwd=str(data_dir), stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True,
    )
    return proc.pid


def _call_spawn(
    spawn: SpawnFn, data_dir: Path, target: int, parse_workers: int, events_path: Path,
    log_path: Path, paper_ids_file: Path | None, *,
    telemetry_poll_interval: float | None = None, batch_size: int | None = None,
) -> int:
    """Passes each of `paper_ids_file`/`telemetry_poll_interval`/`batch_size` to `spawn` only when
    set -- so the injected test fake (whose signature may be the bare 5-positional `SpawnFn`) is
    never handed a kwarg it doesn't accept, while the real `_spawn` gets whichever ones apply."""
    kwargs: dict = {}
    if paper_ids_file is not None:
        kwargs["paper_ids_file"] = paper_ids_file
    if telemetry_poll_interval is not None:
        kwargs["telemetry_poll_interval"] = telemetry_poll_interval
    if batch_size is not None:
        kwargs["batch_size"] = batch_size
    return spawn(data_dir, target, parse_workers, events_path, log_path, **kwargs)


def _build_manifest(
    run_id: str, pid: int, target: int, parse_workers: int, events_path: Path, log_path: Path,
    db_path: Path, paper_ids_file: Path | None = None, *,
    run_cwd: Path, effective_cfg: Config,
    telemetry_poll_interval: float | None = None, batch_size: int | None = None,
    mode: str = "full",
) -> dict:
    starttime, cmdline = _capture_identity(pid)
    return {
        "run_id": run_id,
        "pid": pid,
        "pid_starttime": starttime,
        "pid_cmdline": cmdline,
        "status": "running",
        "mode": mode,
        "target": target,
        "parse_workers": parse_workers,
        "events_path": str(events_path),
        "log_path": str(log_path),
        "db_path": str(db_path),
        "collection": effective_cfg.collection,
        "started_at": datetime.now(UTC).isoformat(),
        "focus_queries": effective_cfg.focus_area_queries,
        # OG-40: persisted so `resume` re-launches cache-first instead of reverting to query harvest.
        "paper_ids_file": str(paper_ids_file) if paper_ids_file is not None else None,
        # OG-43: the directory `app.build_corpus` was actually launched with as `cwd` -- the real
        # data dir for an unedited run, or a run-scoped override `config.yaml` scratch dir when
        # `keywords`/`parse_batch_size` were edited (`_maybe_build_override`). `resume` reuses this
        # verbatim so a paused edited run comes back with the SAME edits, and `status.py`'s
        # downloader check reads `<run_cwd>/prefetch.pid` (matching wherever `app.prefetch_pdfs`,
        # `app.build_corpus`'s own child, actually wrote it).
        "run_cwd": str(run_cwd),
        "parse_batch_size": effective_cfg.parse_batch_size,
        # OG-46: dashboard run-panel ordering-mode indicator ("relevance" vs "freshest_first").
        "ordering": effective_cfg.ordering,
        # The stranded-paper policy actually in effect for this run.
        "stranded_policy": effective_cfg.stranded_policy,
        # OG-45: DOWNLOAD-side arXiv filters actually in effect for this run (unedited base config
        # value when the run didn't override them) -- same "show what's actually active" role
        # `focus_queries` already plays for keyword edits.
        "arxiv_categories": effective_cfg.arxiv_categories,
        "arxiv_date_from": effective_cfg.arxiv_date_from,
        "arxiv_date_to": effective_cfg.arxiv_date_to,
        "params": {
            "parse_workers": parse_workers, "limit": target,
            "telemetry_poll_interval": telemetry_poll_interval, "batch_size": batch_size,
        },
    }


# --- control-op serialization (OG-47#1) -----------------------------------------------------
#
# Each control verb was check-then-act (reconcile -> decide -> spawn/signal -> _write_manifest)
# with no lock spanning it, and `ThreadingHTTPServer` runs every `POST /api/control` on its own
# thread -- two concurrent `start`s could both pass the double-run guard, both spawn, and the
# second `_write_manifest` would overwrite the first's pid (the first `app.build_corpus` orphaned
# from the manifest, unreachable by a later pause/stop). Every public control function below
# acquires ONE `<data_dir>/.control.lock` (`filelock`, cross-thread AND cross-process) around its
# entire body -- reusing the exact filelock dependency `app/ingest.py`'s `.ingest.lock` already
# uses, no new machinery. `retarget` (stop-then-start) acquires the lock ONCE for both halves via
# the `_locked` variants directly (never re-entering through the public `stop`/`start`, which would
# self-deadlock trying to acquire the same lock twice from one thread).


def _control_lock(data_dir: Path) -> filelock.FileLock:
    """`is_singleton=True` (filelock >= 3.29): every call for the same `data_dir` resolves to the
    SAME `FileLock` instance, so a nested `with _control_lock(data_dir):` from the SAME thread
    (`tag_pool.add`/`hold`/`restore`, called from `_maybe_build_override` while `start`/`retarget`
    already hold this lock) is a cheap, safe same-object reentrant increment -- not a second
    open-file-description racing the first, which plain per-call `FileLock(...)` construction
    would produce and which `filelock`'s own deadlock detector would then reject outright."""
    return filelock.FileLock(str(data_dir / _CONTROL_LOCK_NAME), is_singleton=True)


# --- public control surface -----------------------------------------------------------------


def start(data_dir: str | Path, target: int, parse_workers: int = 3, *,
          paper_ids_file: str | Path | None = None,
          telemetry_poll_interval: float | None = None, batch_size: int | None = None,
          keywords: list[str] | None = None, remove_keywords: list[str] | None = None,
          parse_batch_size: int | None = None,
          arxiv_categories: list[str] | None = None,
          arxiv_date_from: str | None = None, arxiv_date_to: str | None = None,
          ordering: str | None = None,
          stranded_policy: str | None = None,
          mode: str = "full",
          spawn: SpawnFn | None = None) -> dict:
    """Fresh run with a new target. Refuses if a run is already live (`running`/`pausing`/
    `stopping`) -- pause or stop it first.

    `paper_ids_file` (OG-40): ingest exactly the cached papers whose base ids are listed in that
    file (cache-first), instead of query-driven discovery. `target` is then just the progress-bar
    denominator (use the id count).

    `telemetry_poll_interval`/`batch_size` (OG-43): plain pass-through CLI flags, forwarded to
    `app.build_corpus` as-is -- no config involved.

    `keywords`/`remove_keywords`/`parse_batch_size`/`arxiv_categories`/`arxiv_date_from`/
    `arxiv_date_to`/`ordering` (OG-43/OG-45/OG-46): config-DERIVED edits -- reaching them requires
    a run-scoped override `config.yaml` (`_maybe_build_override`/`_write_override_config_dir`),
    since `app.build_corpus` and its `app.prefetch_pdfs`/`app.ingest` children each `load_config()`
    fresh from their own cwd rather than receiving this process's in-memory `Config`. `keywords`
    AUGMENTS `focus_area_queries` (adds topics, never replaces -- owner decision); `remove_keywords`
    removes topics, applied AFTER that augment merge (a superseding owner decision for removal
    specifically -- see `_maybe_build_override`). `arxiv_categories`/`arxiv_date_from`/
    `arxiv_date_to` (OG-45) REPLACE the base config's DOWNLOAD-side filters for this run (unlike
    keywords, there is no "augment a filter" semantics). `ordering` (OG-46) is `"freshest_first"`
    or `"relevance"`.

    `mode` (T-DOC78): `"full"` (default) launches `app.build_corpus` (pass1/pass2, needs the GPU);
    `"download"` launches `app.prefetch_pdfs` alone -- no GPU, no pass1/pass2 -- so an operator can
    build up the PDF cache while the GPU is busy with something else."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _start_locked(
            data_dir, target, parse_workers, paper_ids_file=paper_ids_file,
            telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
            keywords=keywords, remove_keywords=remove_keywords, parse_batch_size=parse_batch_size,
            arxiv_categories=arxiv_categories, arxiv_date_from=arxiv_date_from,
            arxiv_date_to=arxiv_date_to, ordering=ordering, stranded_policy=stranded_policy,
            mode=mode,
            spawn=spawn,
        )


def _start_locked(data_dir: Path, target: int, parse_workers: int = 3, *,
                   paper_ids_file: str | Path | None = None,
                   telemetry_poll_interval: float | None = None, batch_size: int | None = None,
                   keywords: list[str] | None = None, remove_keywords: list[str] | None = None,
                   parse_batch_size: int | None = None,
                   arxiv_categories: list[str] | None = None,
                   arxiv_date_from: str | None = None, arxiv_date_to: str | None = None,
                   ordering: str | None = None,
                   stranded_policy: str | None = None,
                   mode: str = "full",
                   spawn: SpawnFn | None = None) -> dict:
    """`start`'s actual body -- called with `_control_lock(data_dir)` already held (by `start`
    itself, or by `retarget` wrapping both halves in one acquisition).

    T-DOC78: `mode="download"` launches `app.prefetch_pdfs` (`_spawn_download`) instead of
    `app.build_corpus` (`_spawn`) -- no GPU, no pass1/pass2. `spawn`'s default is resolved HERE
    (not bound as a default parameter value) so a production caller that never passes `spawn`
    still gets the real `_spawn`/`_spawn_download` picked by `mode`; a test that injects a fake
    `spawn` bypasses this resolution entirely, unaffected by `mode`."""
    manifest = reconcile(data_dir)
    if manifest is not None and manifest.get("status") in _LIVE_STATUSES:
        raise DoubleRunError(
            f"run {manifest['run_id']!r} is still live (status={manifest['status']!r}) -- "
            "pause or stop it before starting a fresh run"
        )
    if manifest is not None and manifest.get("pending_drop_in"):
        raise DropInPendingError(
            "a drop-in run is queued and must run first -- it will start automatically, or "
            "stop() to clear it"
        )
    if manifest is not None:
        # Abandoning a non-live prior run (most commonly "paused" -- pause an edited run, then hit
        # Apply for a fresh one instead of resuming it) for good: its override run_cwd (if any) is
        # never coming back. "paused" was never cleaned up by `reconcile()` (a later `resume()`
        # expects it); "failed" no longer is either (see `reconcile()`'s own comment -- a crash is
        # exactly the thing `resume()` should still be able to rebuild from); "done" was already
        # cleaned up, so this is a no-op for it. This is the one place left that can catch all
        # three before the scratch dir leaks forever -- `_cleanup_run_cwd` is a no-op besides.
        _cleanup_run_cwd(data_dir, manifest)

    paper_ids_file = Path(paper_ids_file) if paper_ids_file is not None else None
    run_id = f"run-{target}-{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    events_path = data_dir / f"ingest_events_{run_id}.jsonl"
    db_path = data_dir / "papers.db"

    base_cfg = _load_base_config(data_dir)
    effective_cfg, override_dir = _maybe_build_override(
        base_cfg, keywords, parse_batch_size, data_dir=data_dir, run_id=run_id,
        remove_keywords=remove_keywords,
        arxiv_categories=arxiv_categories, arxiv_date_from=arxiv_date_from,
        arxiv_date_to=arxiv_date_to, ordering=ordering, stranded_policy=stranded_policy,
    )
    run_cwd = override_dir if override_dir is not None else data_dir

    # T-DOC78: a download-only run's log MUST be named exactly "prefetch.log" in run_cwd --
    # status.py::read_downloader tails that hardcoded filename for pace, regardless of who
    # launched it. A full run keeps its usual per-run ingest log name, unchanged.
    log_path = (
        run_cwd / "prefetch.log" if mode == "download" else data_dir / f"ingest_{run_id}.log"
    )
    spawn = spawn or (_spawn_download if mode == "download" else _spawn)

    pid = _call_spawn(
        spawn, run_cwd, target, parse_workers, events_path, log_path, paper_ids_file,
        telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
    )
    manifest = _build_manifest(
        run_id, pid, target, parse_workers, events_path, log_path, db_path, paper_ids_file,
        run_cwd=run_cwd, effective_cfg=effective_cfg,
        telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
        mode=mode,
    )
    _write_manifest(data_dir, manifest)
    return manifest


def start_drop_in(data_dir: str | Path, *, spawn: SpawnFn | None = None) -> dict:
    """Start a drop-in ingest run (`app.ingest_local`) over whatever is sitting in the drop tray.

    `target`/`parse_workers` are not operator-settable for this run type: the work is bounded by
    the drop tray's contents. `target=0` is recorded in the manifest so `_crashed_before_target`
    (`done_count < target`) can never misclassify a clean drop-in finish as a crash."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _start_drop_in_locked(data_dir, spawn=spawn)


def _start_drop_in_locked(data_dir: Path, *, spawn: SpawnFn | None = None) -> dict:
    manifest = reconcile(data_dir)
    if manifest is not None and manifest.get("status") in _LIVE_STATUSES:
        # Queue-jump, not preemption: the live run is never signalled. `promote_pending_drop_in`
        # spawns this the moment that run reaches a terminal state.
        manifest["pending_drop_in"] = True
        _write_manifest(data_dir, manifest)
        return manifest
    if manifest is not None:
        _cleanup_run_cwd(data_dir, manifest)
    run_id = f"dropin-{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    log_path = data_dir / "ingest_local.log"
    events_path = data_dir / f"ingest_events_{run_id}.jsonl"
    spawn_fn = spawn if spawn is not None else _spawn_drop_in
    pid = spawn_fn(data_dir, 0, 1, events_path, log_path)
    manifest = _build_manifest(
        run_id, pid, 0, 1, events_path, log_path, data_dir / "papers.db",
        run_cwd=data_dir, effective_cfg=_load_base_config(data_dir), mode="drop_in",
    )
    _write_manifest(data_dir, manifest)
    return manifest


def promote_pending_drop_in(data_dir: str | Path, *,
                            spawn: SpawnFn | None = None) -> dict | None:
    """Spawn a queued drop-in run if the previously live run has reached a terminal state.
    Returns the new drop-in manifest, or `None` when there is nothing to promote.

    Takes `_control_lock` and re-reconciles INSIDE it. `reconcile()` itself must not spawn:
    `liveness()` calls it with no lock held, and `server.py` is a ThreadingHTTPServer, so two
    concurrent `/api/status` polls would otherwise both see `terminal + pending` and both spawn.
    Idempotent and safe to call on every status poll."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        manifest = reconcile(data_dir)
        if manifest is None or not manifest.get("pending_drop_in"):
            return None
        if manifest.get("status") in _LIVE_STATUSES:
            return None
        return _start_drop_in_locked(data_dir, spawn=spawn)


def pause(data_dir: str | Path) -> dict:
    """SIGTERM (escalating to a resend, then SIGKILL -- OG-49#5, `_terminate_with_escalation`) the
    running process group and mark `status: "paused"` once its death is confirmed (`status:
    "pausing"` in between). Safe by construction: ingestion is checkpointed (`ingest_state`/
    `ingest_checkpoint`), so a paused run loses at most the in-flight parse batch, which re-does on
    resume."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _pause_locked(data_dir)


def _pause_locked(data_dir: Path) -> dict:
    manifest = reconcile(data_dir)
    if manifest is None or manifest.get("status") != "running":
        raise NoRunError("no running run to pause")
    pid = manifest["pid"]
    manifest["status"] = "pausing"
    _write_manifest(data_dir, manifest)
    manifest["status"] = "paused" if _terminate_with_escalation(pid) else "pausing"
    _write_manifest(data_dir, manifest)
    return manifest


def resume(data_dir: str | Path, *, spawn: SpawnFn | None = None) -> dict:
    """Relaunch the run's spawn command with the SAME params as the existing manifest --
    checkpoints make this safe, it picks up where it left off. Refuses (`DoubleRunError`) if the
    prior run is still `running`, or if a `pausing`/`stopping` run's process hasn't yet been
    confirmed dead -- SIGTERM is a request, not a guarantee, and relaunching before the old
    process actually exits would duplicate the work it's still mid-way through.

    T-DOC78: `spawn`'s default (`None`) is resolved from the manifest's own stored `"mode"` --
    `_spawn_download` for a download-only run, `_spawn` (`app.build_corpus`) otherwise -- so a
    paused download-only run resumes as a downloader, not a full pass1/pass2 run."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _resume_locked(data_dir, spawn=spawn)


def _resume_locked(data_dir: Path, *, spawn: SpawnFn | None = None) -> dict:
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
    stored_ids_file = manifest.get("paper_ids_file")  # OG-40: keep a cache-first run cache-first
    paper_ids_file = Path(stored_ids_file) if stored_ids_file else None
    # OG-43: reuse the SAME cwd (real data_dir, or a keywords/parse_batch_size override scratch
    # dir) and the SAME pass-through params the original run launched with -- a resumed edited run
    # must come back with its edits intact, not silently revert to config.yaml's unedited defaults.
    stored_run_cwd = manifest.get("run_cwd")
    run_cwd = Path(stored_run_cwd) if stored_run_cwd else data_dir
    if run_cwd != data_dir and not run_cwd.exists():
        # The override scratch dir is gone (a reboot wiped the old /tmp location, or it was
        # otherwise lost) -- rebuild it from the manifest's OWN recorded effective params rather
        # than let `_call_spawn` below hit `subprocess.Popen(cwd=<missing dir>)` ->
        # `FileNotFoundError`. NEVER falls back to `data_dir`/unedited defaults -- see
        # `_rebuild_missing_run_cwd`'s own docstring for why that would be worse than the crash.
        _rebuild_missing_run_cwd(data_dir, manifest, run_cwd)
    params = manifest.get("params") or {}
    # T-DOC78: resolved from the manifest's own recorded mode when the caller (production: always)
    # doesn't inject a spawn fake -- see `resume`'s docstring.
    spawn = spawn or (_spawn_download if manifest.get("mode") == "download" else _spawn)
    pid = _call_spawn(
        spawn, run_cwd, manifest["target"], manifest["parse_workers"],
        events_path, log_path, paper_ids_file,
        telemetry_poll_interval=params.get("telemetry_poll_interval"),
        batch_size=params.get("batch_size"),
    )
    starttime, cmdline = _capture_identity(pid)
    manifest["pid"] = pid
    manifest["pid_starttime"] = starttime
    manifest["pid_cmdline"] = cmdline
    manifest["status"] = "running"
    _write_manifest(data_dir, manifest)
    return manifest


def stop(data_dir: str | Path) -> dict:
    """SIGTERM (escalating to a resend, then SIGKILL -- OG-49#5) the running process group and mark
    the run `status: "done"` once its death is confirmed (`status: "stopping"` in between) -- a
    user-initiated stop is final (unlike `pause`, which expects a later `resume`); the checkpoints
    it leaves behind are still there if a later `start` happens to re-cover the same papers, but
    that's a fresh run's business."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _stop_locked(data_dir)


def _stop_locked(data_dir: Path) -> dict:
    manifest = reconcile(data_dir)
    if manifest is None or manifest.get("status") != "running":
        raise NoRunError("no running run to stop")
    pid = manifest["pid"]
    manifest["status"] = "stopping"
    _write_manifest(data_dir, manifest)
    manifest["status"] = "done" if _terminate_with_escalation(pid) else "stopping"
    # The operator's escape hatch: if a queued drop-in's wait target (ingest_local) wedges, stop()
    # must unblock downloads/full runs again rather than leaving pending_drop_in stuck set forever.
    manifest["pending_drop_in"] = False
    _write_manifest(data_dir, manifest)
    if manifest["status"] == "done":
        # OG-49 M10: a user-initiated stop is final (module docstring) -- no later resume() will
        # ever reuse this run's run_cwd, so its override scratch dir (if any) is safe to remove now.
        _cleanup_run_cwd(data_dir, manifest)
    return manifest


def retarget(data_dir: str | Path, target: int, parse_workers: int = 3, *,
             paper_ids_file: str | Path | None = None,
             telemetry_poll_interval: float | None = None, batch_size: int | None = None,
             keywords: list[str] | None = None, remove_keywords: list[str] | None = None,
             parse_batch_size: int | None = None,
             arxiv_categories: list[str] | None = None,
             arxiv_date_from: str | None = None, arxiv_date_to: str | None = None,
             ordering: str | None = None,
          stranded_policy: str | None = None,
             spawn: SpawnFn = _spawn) -> dict:
    """"Start a fresh run with a new target": stop the current run if one is live, then start.
    OG-43: this is now the "Apply new settings while a run is live" path -- `server.py` exposes it
    over `POST /api/control` (action `"retarget"`) alongside plain `"start"` (which still refuses
    via the ordinary double-run guard when something's live), so the frontend's single "Apply"
    button can call whichever fits the current state without the user pausing/stopping by hand
    first.

    OG-47#1: both halves run under ONE `_control_lock` acquisition (via the `_locked` variants
    directly, never the public `stop`/`start`) -- stop-then-start has no atomicity/crash-safety
    otherwise: a death between the two under the OLD unserialized code could leave the run stopped
    with no replacement, or race a concurrent `start`/`retarget` the same way OG-47#1's `start`
    fix addresses."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        try:
            _stop_locked(data_dir)
        except NoRunError:
            pass
        return _start_locked(
            data_dir, target, parse_workers, paper_ids_file=paper_ids_file,
            telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
            keywords=keywords, remove_keywords=remove_keywords, parse_batch_size=parse_batch_size,
            arxiv_categories=arxiv_categories, arxiv_date_from=arxiv_date_from,
            arxiv_date_to=arxiv_date_to, ordering=ordering, stranded_policy=stranded_policy,
            spawn=spawn,
        )


def free_gpu(
    data_dir: str | Path, *, stop_tei=tei_lifecycle.stop_tei_containers,
) -> dict:
    """T-DOC78: stops the TEI containers (embedder+reranker, ~9.4GB) on demand -- independent of
    pause/resume/stop, which deliberately leave TEI running (CONVENTIONS.md §6: live MCP search
    stays available except during Pass 1). Refuses while a FULL-mode run is actively running or
    mid-pause/stop -- freeing TEI out from under an in-flight Pass-2 embed/rerank call would fail
    real papers' retries and wrongly quarantine them. Safe anytime nothing is live, a run is
    paused/stopped, or a download-only run is live/paused (that mode never touches TEI at all)."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        manifest = reconcile(data_dir)
        if (
            manifest is not None
            and manifest.get("status") in _LIVE_STATUSES
            and manifest.get("mode", "full") == "full"
        ):
            raise DoubleRunError(
                f"run {manifest['run_id']!r} is a full run actively running -- pause or stop it "
                "before freeing the GPU (freeing TEI mid-Pass-2 would fail in-flight embed/rerank "
                "calls and wrongly quarantine real papers)"
            )
        stop_tei()
        return {"tei_stopped": True}


def _tracked_downloader_pid(manifest: dict | None) -> int | None:
    """The current manifest's pid, but ONLY when it actually names a downloader (`mode ==
    "download"`) -- a `mode == "full"` manifest's pid is a `build_corpus` SUPERVISOR, not a
    downloader itself (`app.prefetch_pdfs` is its own child, tracked separately, see this
    module's own docstring on the root cause); comparing IT against live `app.prefetch_pdfs`
    pids would never match, so its own legitimate prefetch child would be misread as an orphan
    and terminated out from under a live full run. Same gating `status.py`'s caller
    (`server.py`) already applies to `manifest_pid`."""
    if manifest is None or manifest.get("mode") != "download":
        return None
    return manifest.get("pid")


def restart_downloader(
    data_dir: str | Path, *, spawn: SpawnFn | None = None,
    live_pids: Callable[[], list[int]],
    terminate: Callable[[int], bool] | None = None,
) -> dict:
    """D-6 Task 2: stop + start as one locked operation -- fixes the 2026-08-01 root cause's
    operator-facing consequence, "stop -> change tags -> start" silently starting a SECOND
    downloader beside an orphan `stop` never reached (it only ever signaled the manifest's own,
    possibly-stale, pid). Terminates EVERY live `app.prefetch_pdfs` pid `live_pids()` reports --
    the tracked one AND every orphan -- then spawns exactly one fresh downloader via the same
    `mode="download"` path `start(..., mode="download")` uses, all under a SINGLE
    `_control_lock` acquisition so no window exists for a second downloader to start in between.

    `live_pids` has no safe default here: the real scan (`status._live_prefetch_pids`) lives in
    `status.py`, and this module must never import that (see this module's own docstring on why
    -- `run_manifest.json` is the only channel between them). The one real caller (`server.py`,
    the composition root that already imports both) always injects it explicitly; a test injects
    a fake so no test ever signals a real process. `terminate` defaults to
    `_terminate_with_escalation` (defined in this module, no import needed)."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _restart_downloader_locked(
            data_dir, spawn=spawn, live_pids=live_pids, terminate=terminate,
        )


def _restart_downloader_locked(
    data_dir: Path, *, spawn: SpawnFn | None = None,
    live_pids: Callable[[], list[int]],
    terminate: Callable[[int], bool] | None = None,
) -> dict:
    terminate = terminate or _terminate_with_escalation
    for pid in live_pids():
        terminate(pid)
    # `_start_locked` re-reconciles the manifest itself and refuses (DoubleRunError) only if it
    # STILL looks live after the terminations above -- no separate cleanup/guard needed here.
    target = _load_base_config(data_dir).prefetch_target
    return _start_locked(data_dir, target, 1, mode="download", spawn=spawn)


def terminate_orphan_downloaders(
    data_dir: str | Path, *, live_pids: Callable[[], list[int]],
    terminate: Callable[[int], bool] | None = None,
) -> list[int]:
    """The narrower half of what `restart_downloader` does unconditionally: terminates every live
    `app.prefetch_pdfs` pid NOT tracked by the current manifest (`_tracked_downloader_pid`),
    leaving a genuinely-tracked downloader running untouched. Returns the pids terminated.

    Same injectable-`live_pids`, no-safe-default reasoning as `restart_downloader` above."""
    terminate = terminate or _terminate_with_escalation
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        manifest = reconcile(data_dir)
        tracked_pid = _tracked_downloader_pid(manifest)
        orphans = [pid for pid in live_pids() if pid != tracked_pid]
        for pid in orphans:
            terminate(pid)
        return orphans


def load_for_mcp(
    data_dir: str | Path, *, start_tei=tei_lifecycle.start_tei_containers,
) -> dict:
    """T-DOC78: starts the TEI containers back up and waits for them to report healthy -- the
    explicit counterpart to `free_gpu`, for restoring live MCP search immediately instead of
    waiting for the next query to pay the reload cost inline (the query path also self-heals on
    its own via `ensure_ready`, `rag/embedder.py`/`rag/reranker.py` -- this is just the eager
    version).

    T-DOC78 (fix round 3): refuses (`DoubleRunError`) while Pass 1 is actively running
    (`app.tei_lifecycle`'s `.pass1.lock`, the same signal the query path's self-healing hook
    checks) -- reloading TEI's ~9.4GB mid-Pass-1 risks the exact CUDA OOM eviction exists to
    prevent (same reasoning as `free_gpu`'s guard, just checked via the lock instead of the run
    manifest, since `load_for_mcp` has no run-mode concept to key off). Safe at every other time --
    starting an already-started container is a no-op."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        lock_path = tei_lifecycle.pass1_lock_path(str(data_dir / "papers.db"))
        if tei_lifecycle.pass1_is_active(lock_path):
            raise DoubleRunError(
                "Pass 1 (parsing) is actively running -- reloading TEI now risks the exact CUDA "
                "OOM eviction exists to prevent; wait for Pass 1 to finish or for it to be paused/"
                "stopped first"
            )
        start_tei()
        return {"tei_started": True}
