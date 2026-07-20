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
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import filelock
import yaml
from pydantic import ValidationError

from contracts.config import Config
from rag.config import load_config

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_NAME = "run_manifest.json"
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


class DoubleRunError(RuntimeError):
    """Raised when start/resume is refused because a run is already live (or not yet confirmed
    dead)."""


class NoRunError(RuntimeError):
    """Raised when pause/resume/stop is asked to act on a run that doesn't exist."""


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


def _capture_identity(pid: int) -> tuple[float | None, str | None]:
    """Best-effort identity capture right after spawn. A few quick retries: `/proc/<pid>/*` can
    lag a hair behind `Popen()` returning -- AND `_spawn`'s `env`-wrapper transition (see
    `_ENV_WRAPPER_CMDLINE_PREFIX`) can too: a real incident had this function win that race,
    permanently capturing `env`'s own (transitional) cmdline, which `/proc/<pid>/cmdline` never
    shows again once the exec into the real program completes. Every later `_verified_pid` check
    then mismatched forever -- an exact, healthy, actively-progressing run got downgraded to
    "failed" (and its scratch config dir queued for deletion, `_cleanup_run_cwd`) out from under
    it. Keeps retrying while the observed cmdline still IS that transitional wrapper, not just
    while `/proc` is unreadable; falls back to whatever was last observed (matching this
    function's existing best-effort contract) if every retry still shows the wrapper -- should
    never happen in practice, `env` execve()s near-instantly."""
    identity = None
    for _ in range(5):
        identity = _process_identity(pid)
        if identity is not None and not identity[1].startswith(_ENV_WRAPPER_CMDLINE_PREFIX):
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
    written before either existed) degrade to `False` (the old, conservative "done" behavior)."""
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
        # OG-49 M10: only "done"/"failed" are genuinely terminal here -- "paused" (from "pausing")
        # expects a later resume() that reuses run_cwd, so it must NOT be cleaned up.
        if manifest["status"] in ("done", "failed"):
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
    `collection` resolve against the real corpus location. Falls back to the repo-root
    `config.yaml` only when `data_dir` has none of its own (e.g. a fresh/test data dir): before
    this fix, `start`/`retarget` always loaded `_REPO_ROOT/config.yaml` regardless of `data_dir`,
    so `_write_override_config_dir`'s path resolution (below) resolved relative fields against the
    DASHBOARD SERVER PROCESS's own cwd -- not the corpus's actual data dir -- misdirecting every
    edited run's `papers.db`/`blobs` while it kept upserting into the real, shared vector-store
    collection (orphan vector points with no matching row in the misdirected db)."""
    data_dir_config = data_dir / "config.yaml"
    if data_dir_config.exists():
        return load_config(data_dir_config)
    return load_config(_REPO_ROOT / "config.yaml")


def _write_override_config_dir(cfg: Config, data_dir: Path) -> Path:
    """`data_dir` (OG-49#1): every relative-path field is resolved absolute against the REAL data
    dir, not `Path.resolve()`'s implicit `os.getcwd()` (the dashboard SERVER process's own cwd,
    unrelated to any run) -- `Path(base) / value` is a no-op when `value` is already absolute, so
    this is safe for both a relative default (e.g. `"papers.db"`) and an already-absolute value."""
    path_updates = {
        field: str((data_dir / value).resolve())
        for field in _OVERRIDE_PATH_FIELDS
        if (value := getattr(cfg, field))
    }
    resolved = cfg.model_copy(update=path_updates) if path_updates else cfg

    # OG-49 M10: unlike app/ingest.py's own override dir (torn down the instant its one-shot run
    # ends), THIS dir is a `run_cwd` a `pause`d run's later `resume()` reuses verbatim (see
    # `_resume_locked`) -- it must survive across pause/resume for the SAME run_id. `_cleanup_run_cwd`
    # below is the other half: it removes this dir once the run reaches a genuinely terminal state
    # ("done"/"failed") that will never `resume()` again, never on a merely "paused" one.
    tmpdir = Path(tempfile.mkdtemp(prefix="dashboard_override_"))
    (tmpdir / "config.yaml").write_text(yaml.safe_dump(resolved.model_dump()))
    return tmpdir


def _cleanup_run_cwd(data_dir: Path, manifest: dict) -> None:
    """OG-49 M10: removes a run's override `config.yaml` scratch dir (`_write_override_config_dir`)
    once its manifest has settled into a genuinely terminal status ("done"/"failed") -- called only
    from call sites that just set one of those, never from `pause` (`"paused"` expects a later
    `resume()`, which reuses `run_cwd` verbatim -- deleting it there would break resume).

    A no-op when this run never had an override (`run_cwd == data_dir`, an unedited run launched
    directly in the real data dir -- never a scratch dir, must never be removed) or when the dir is
    already gone (`ignore_errors=True` -- e.g. `stop()` and a later `reconcile()` both observing the
    same terminal transition must not make the second cleanup call fail on the first's work).
    """
    run_cwd = manifest.get("run_cwd")
    if not run_cwd or Path(run_cwd) == data_dir:
        return
    shutil.rmtree(run_cwd, ignore_errors=True)


def _maybe_build_override(
    cfg: Config, keywords: list[str] | None, parse_batch_size: int | None, *,
    data_dir: Path,
    arxiv_categories: list[str] | None = None,
    arxiv_date_from: str | None = None,
    arxiv_date_to: str | None = None,
    ordering: str | None = None,
    stranded_policy: str | None = None,
) -> tuple[Config, Path | None]:
    """Builds a run-scoped override `Config` + scratch `config.yaml` dir when `keywords` (AUGMENTED
    onto `focus_area_queries` -- owner decision: an edit adds topics to the one library, it never
    replaces it), `parse_batch_size`, the OG-45 arXiv DOWNLOAD filters
    (`arxiv_categories`/`arxiv_date_from`/`arxiv_date_to`), or the OG-46 `ordering` actually change
    anything relative to the base config. Returns `(cfg, None)` unchanged when nothing edits --
    a run that edits nothing launches exactly the old way (`cwd=data_dir`, no override dir, no
    scratch files).

    OG-49#6/M8: `cfg.model_copy(update=updates)` does NOT re-run pydantic validation (it's a plain
    field copy) -- a bad `parse_batch_size`/`ordering` from a `POST /api/control` body would
    otherwise silently build an invalid `Config`, write it to the override `config.yaml`, and only
    fail once the spawned subprocess loads it and crashes (after the manifest already says
    "running"). `Config.model_validate(...)` re-validates before that ever happens; a failure
    raises `InvalidOverrideError` here, pre-spawn.
    """
    updates: dict = {}
    if keywords:
        merged = cfg.focus_area_queries + [k for k in keywords if k not in cfg.focus_area_queries]
        if merged != cfg.focus_area_queries:
            updates["focus_area_queries"] = merged
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
    return effective, _write_override_config_dir(effective, data_dir)


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
) -> dict:
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
    return filelock.FileLock(str(data_dir / _CONTROL_LOCK_NAME))


# --- public control surface -----------------------------------------------------------------


def start(data_dir: str | Path, target: int, parse_workers: int = 3, *,
          paper_ids_file: str | Path | None = None,
          telemetry_poll_interval: float | None = None, batch_size: int | None = None,
          keywords: list[str] | None = None, parse_batch_size: int | None = None,
          arxiv_categories: list[str] | None = None,
          arxiv_date_from: str | None = None, arxiv_date_to: str | None = None,
          ordering: str | None = None,
          stranded_policy: str | None = None,
          spawn: SpawnFn = _spawn) -> dict:
    """Fresh run with a new target. Refuses if a run is already live (`running`/`pausing`/
    `stopping`) -- pause or stop it first.

    `paper_ids_file` (OG-40): ingest exactly the cached papers whose base ids are listed in that
    file (cache-first), instead of query-driven discovery. `target` is then just the progress-bar
    denominator (use the id count).

    `telemetry_poll_interval`/`batch_size` (OG-43): plain pass-through CLI flags, forwarded to
    `app.build_corpus` as-is -- no config involved.

    `keywords`/`parse_batch_size`/`arxiv_categories`/`arxiv_date_from`/`arxiv_date_to`/`ordering`
    (OG-43/OG-45/OG-46): config-DERIVED edits -- reaching them requires a run-scoped override
    `config.yaml` (`_maybe_build_override`/`_write_override_config_dir`), since `app.build_corpus`
    and its `app.prefetch_pdfs`/`app.ingest` children each `load_config()` fresh from their own
    cwd rather than receiving this process's in-memory `Config`. `keywords` AUGMENTS
    `focus_area_queries` (adds topics, never replaces -- owner decision). `arxiv_categories`/
    `arxiv_date_from`/`arxiv_date_to` (OG-45) REPLACE the base config's DOWNLOAD-side filters for
    this run (unlike keywords, there is no "augment a filter" semantics). `ordering` (OG-46) is
    `"freshest_first"` or `"relevance"`."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _start_locked(
            data_dir, target, parse_workers, paper_ids_file=paper_ids_file,
            telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
            keywords=keywords, parse_batch_size=parse_batch_size,
            arxiv_categories=arxiv_categories, arxiv_date_from=arxiv_date_from,
            arxiv_date_to=arxiv_date_to, ordering=ordering, stranded_policy=stranded_policy,
            spawn=spawn,
        )


def _start_locked(data_dir: Path, target: int, parse_workers: int = 3, *,
                   paper_ids_file: str | Path | None = None,
                   telemetry_poll_interval: float | None = None, batch_size: int | None = None,
                   keywords: list[str] | None = None, parse_batch_size: int | None = None,
                   arxiv_categories: list[str] | None = None,
                   arxiv_date_from: str | None = None, arxiv_date_to: str | None = None,
                   ordering: str | None = None,
          stranded_policy: str | None = None,
                   spawn: SpawnFn = _spawn) -> dict:
    """`start`'s actual body -- called with `_control_lock(data_dir)` already held (by `start`
    itself, or by `retarget` wrapping both halves in one acquisition)."""
    manifest = reconcile(data_dir)
    if manifest is not None and manifest.get("status") in _LIVE_STATUSES:
        raise DoubleRunError(
            f"run {manifest['run_id']!r} is still live (status={manifest['status']!r}) -- "
            "pause or stop it before starting a fresh run"
        )

    paper_ids_file = Path(paper_ids_file) if paper_ids_file is not None else None
    run_id = f"run-{target}-{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    events_path = data_dir / f"ingest_events_{run_id}.jsonl"
    log_path = data_dir / f"ingest_{run_id}.log"
    db_path = data_dir / "papers.db"

    base_cfg = _load_base_config(data_dir)
    effective_cfg, override_dir = _maybe_build_override(
        base_cfg, keywords, parse_batch_size, data_dir=data_dir,
        arxiv_categories=arxiv_categories, arxiv_date_from=arxiv_date_from,
        arxiv_date_to=arxiv_date_to, ordering=ordering, stranded_policy=stranded_policy,
    )
    run_cwd = override_dir if override_dir is not None else data_dir

    pid = _call_spawn(
        spawn, run_cwd, target, parse_workers, events_path, log_path, paper_ids_file,
        telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
    )
    manifest = _build_manifest(
        run_id, pid, target, parse_workers, events_path, log_path, db_path, paper_ids_file,
        run_cwd=run_cwd, effective_cfg=effective_cfg,
        telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
    )
    _write_manifest(data_dir, manifest)
    return manifest


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


def resume(data_dir: str | Path, *, spawn: SpawnFn = _spawn) -> dict:
    """Relaunch `app.build_corpus` with the SAME params as the existing manifest -- checkpoints
    make this safe, it picks up where it left off (build_corpus/ingest are idempotent/resumable via
    `ingest_state`). Refuses (`DoubleRunError`) if the prior run is still `running`, or if a
    `pausing`/`stopping` run's process hasn't yet been confirmed dead --
    SIGTERM is a request, not a guarantee, and relaunching before the old process actually exits
    would duplicate the GPU work it's still mid-way through."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _resume_locked(data_dir, spawn=spawn)


def _resume_locked(data_dir: Path, *, spawn: SpawnFn = _spawn) -> dict:
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
    params = manifest.get("params") or {}
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
    _write_manifest(data_dir, manifest)
    if manifest["status"] == "done":
        # OG-49 M10: a user-initiated stop is final (module docstring) -- no later resume() will
        # ever reuse this run's run_cwd, so its override scratch dir (if any) is safe to remove now.
        _cleanup_run_cwd(data_dir, manifest)
    return manifest


def retarget(data_dir: str | Path, target: int, parse_workers: int = 3, *,
             paper_ids_file: str | Path | None = None,
             telemetry_poll_interval: float | None = None, batch_size: int | None = None,
             keywords: list[str] | None = None, parse_batch_size: int | None = None,
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
            keywords=keywords, parse_batch_size=parse_batch_size,
            arxiv_categories=arxiv_categories, arxiv_date_from=arxiv_date_from,
            arxiv_date_to=arxiv_date_to, ordering=ordering, stranded_policy=stranded_policy,
            spawn=spawn,
        )
