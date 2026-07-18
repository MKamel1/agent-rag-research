"""`app/dashboard/controller.py` -- the Run Controller: start/pause/resume/stop/retarget a corpus-
ingestion run via `run_manifest.json` + OS signals, the same coordination contract the real
launcher already writes (`docs/DESIGN-corpus-dashboard.md`, "The coordination contract").

The **sole reader and writer** of `run_manifest.json` (principal-design-review finding #6):
`status.py` never opens this file -- `server.py` composes the final `/api/status` response from
`controller.liveness()` (run identity + config) plus `status.py`'s pure telemetry/`ingest_state`
reads. This module never touches `papers.db` -- only the manifest and the `app.build_corpus`
subprocess (OG-41 -- see below; it was `app.ingest` directly before this).

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
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import yaml

from contracts.config import Config
from rag.config import load_config

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_NAME = "run_manifest.json"

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


# --- run-scoped config override (OG-43: edited keywords/parse_batch_size) ------------------------
#
# Mirrors `app/ingest.py::_write_override_config_dir` (T-DOC45/46): writes an already-overridden
# `Config` to a scratch `<tmpdir>/config.yaml`, resolving every relative-path field absolute first
# (the subprocess launched into this dir has a DIFFERENT cwd than this process) -- `data_dir` runs
# `PYTHONPATH=<repo> python -m app.build_corpus` with `cwd=<tmpdir>`, so IT and every child it
# launches in turn (`app.prefetch_pdfs`, each `app.ingest` batch) all `load_config()` this exact
# file: none of them receive this process's in-memory `Config` object directly, `config.yaml`
# itself is the only channel every one of them reads unconditionally.


def _write_override_config_dir(cfg: Config) -> Path:
    path_updates = {
        field: str(Path(value).resolve())
        for field in _OVERRIDE_PATH_FIELDS
        if (value := getattr(cfg, field))
    }
    resolved = cfg.model_copy(update=path_updates) if path_updates else cfg

    # ponytail: this scratch dir, like app/ingest.py's own `--scratch`/`--limit` override dirs, is
    # never cleaned up -- matches that module's existing (already-accepted) behavior rather than
    # inventing new cleanup machinery here. Add a reaper if scratch-dir accumulation ever becomes
    # a real problem in practice.
    tmpdir = Path(tempfile.mkdtemp(prefix="dashboard_override_"))
    (tmpdir / "config.yaml").write_text(yaml.safe_dump(resolved.model_dump()))
    return tmpdir


def _maybe_build_override(
    cfg: Config, keywords: list[str] | None, parse_batch_size: int | None, *,
    arxiv_categories: list[str] | None = None,
    arxiv_date_from: str | None = None,
    arxiv_date_to: str | None = None,
    ordering: str | None = None,
) -> tuple[Config, Path | None]:
    """Builds a run-scoped override `Config` + scratch `config.yaml` dir when `keywords` (AUGMENTED
    onto `focus_area_queries` -- owner decision: an edit adds topics to the one library, it never
    replaces it), `parse_batch_size`, the OG-45 arXiv DOWNLOAD filters
    (`arxiv_categories`/`arxiv_date_from`/`arxiv_date_to`), or the OG-46 `ordering` actually change
    anything relative to the base config. Returns `(cfg, None)` unchanged when nothing edits --
    a run that edits nothing launches exactly the old way (`cwd=data_dir`, no override dir, no
    scratch files)."""
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
    if not updates:
        return cfg, None
    effective = cfg.model_copy(update=updates)
    return effective, _write_override_config_dir(effective)


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


# --- public control surface -----------------------------------------------------------------


def start(data_dir: str | Path, target: int, parse_workers: int = 3, *,
          paper_ids_file: str | Path | None = None,
          telemetry_poll_interval: float | None = None, batch_size: int | None = None,
          keywords: list[str] | None = None, parse_batch_size: int | None = None,
          arxiv_categories: list[str] | None = None,
          arxiv_date_from: str | None = None, arxiv_date_to: str | None = None,
          ordering: str | None = None,
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

    base_cfg = load_config(_REPO_ROOT / "config.yaml")
    effective_cfg, override_dir = _maybe_build_override(
        base_cfg, keywords, parse_batch_size,
        arxiv_categories=arxiv_categories, arxiv_date_from=arxiv_date_from,
        arxiv_date_to=arxiv_date_to, ordering=ordering,
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
    """Relaunch `app.build_corpus` with the SAME params as the existing manifest -- checkpoints
    make this safe, it picks up where it left off (build_corpus/ingest are idempotent/resumable via
    `ingest_state`). Refuses (`DoubleRunError`) if the prior run is still `running`, or if a
    `pausing`/`stopping` run's process hasn't yet been confirmed dead --
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


def retarget(data_dir: str | Path, target: int, parse_workers: int = 3, *,
             paper_ids_file: str | Path | None = None,
             telemetry_poll_interval: float | None = None, batch_size: int | None = None,
             keywords: list[str] | None = None, parse_batch_size: int | None = None,
             arxiv_categories: list[str] | None = None,
             arxiv_date_from: str | None = None, arxiv_date_to: str | None = None,
             ordering: str | None = None,
             spawn: SpawnFn = _spawn) -> dict:
    """"Start a fresh run with a new target": stop the current run if one is live, then start.
    OG-43: this is now the "Apply new settings while a run is live" path -- `server.py` exposes it
    over `POST /api/control` (action `"retarget"`) alongside plain `"start"` (which still refuses
    via the ordinary double-run guard when something's live), so the frontend's single "Apply"
    button can call whichever fits the current state without the user pausing/stopping by hand
    first."""
    data_dir = Path(data_dir)
    try:
        stop(data_dir)
    except NoRunError:
        pass
    return start(
        data_dir, target, parse_workers, paper_ids_file=paper_ids_file,
        telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
        keywords=keywords, parse_batch_size=parse_batch_size,
        arxiv_categories=arxiv_categories, arxiv_date_from=arxiv_date_from,
        arxiv_date_to=arxiv_date_to, ordering=ordering, spawn=spawn,
    )
