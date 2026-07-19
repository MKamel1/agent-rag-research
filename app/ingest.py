"""`python -m app.ingest` — the real IngestionOrchestrator composition root.

Runs Pass 1 (parse, MinerU/GPU-bound) as a subprocess (`app/parse_phase.py`) so its exit fully
releases MinerU's VRAM (ARCHITECTURE.md §3), then runs Pass 2 (finish: summarize+embed+store,
also GPU-bound) in this process. The two GPU-bound phases never share a process, so they never
have to share VRAM at the same instant.

T-DOC51: `--parse-workers N` (default 1, i.e. today's exact behavior) runs Pass 1 as N concurrent
`app.parse_phase` subprocesses instead of one, each parsing a disjoint shard of the same harvested
corpus -- measured +63% parse throughput (3 workers, `.phase0-data/pass1-gpu-underutilization.md`)
because the parser renders each doc with exactly 1 CPU process while the GPU idles, and a
second/third worker's GPU work fills that gap. Every worker still fully exits before Pass 2 starts
(two-phase VRAM isolation, unchanged).

T-DOC43 (`--preflight`, default on / `--no-preflight` / `--force`): a startup readiness gate
(`app/doctor.py`) that refuses to start with one clear message naming every missing prerequisite
(disk/GPU headroom, `.gpu.lock`, every required service) instead of quarantining papers or
crashing partway through a multi-hour run -- the real motivating incident
(`LESSONS-LEARNED.md`/T-DOC30) is a silently-down reference-resolution service that quarantined an
entire run before anyone noticed.

T-DOC44 (DB auto-provision): a fresh `db_path` used to crash deep in the pipeline with an opaque
`no such table` (`reviews/OPERATIONAL-GAPS.md` OG-2). `_ensure_db_migrated` detects an absent/
unmigrated DB on every startup and auto-provisions it (calls `migrations.migrate.migrate()` --
foundation-protected, called not edited) before either phase opens a connection against it.

T-DOC45 (`--limit N`) / T-DOC46 (`--scratch`): run-scoped `Config` overrides, applied once via
`_effective_config` before either phase starts. Because Pass 1 runs as a *separate process* that
loads its own `config.yaml` fresh (never receiving this process's in-memory `Config` object
directly), an override only reaches Pass 1 if handed through the one channel it already reads
unconditionally: `config.yaml` itself. `_write_override_config_dir` writes the already-overridden
`Config` to a scratch `config.yaml` (with every relative path resolved absolute first) and hands
its directory to the Pass-1 subprocess as `cwd=` -- see that function's docstring for why. Neither
flag changes anything when unset: `_effective_config` returns `cfg` unchanged, and
`_run_parse_phase_subprocesses`'s subprocess calls carry no `cwd` kwarg at all (byte-for-byte the
original calls), so today's exact default behavior is preserved.

T-DOC47 (`--events-path`, `--telemetry-poll-interval`): built-in run instrumentation, all owned by
`app/telemetry.py` (OG-5/OG-6/OG-7) -- this module only marks the stage boundaries it already has
(`_run_parse_phase_subprocesses` = "parse", `_run_finish_phase` = "finish") via
`telemetry.RunTelemetry.stage_start`/`stage_end`, and prints the end-of-run summary from a
`finally` block so a mid-run failure still reports partial progress instead of nothing. Telemetry
starts only after `_preflight_gate`/`_ensure_db_migrated` succeed, so its own SQLite reads never
race an unmigrated/absent database.

T-DOC59 (OG-25): "finish" alone lumps summarize+embed+store into one GPU-telemetry bucket, hiding
which of the three actually drives GPU time. `_run_finish_phase`'s `on_stage=run.set_stage` wires
`rag/orchestrator.py`'s new per-paper `on_stage` hook (fired inside `_finish`, see that module's
docstring) straight to `RunTelemetry.set_stage` -- re-tagging the running GPU sampler to
"summarize"/"embed"/"store" without an extra STAGE_START/STAGE_END event pair per paper (this is a
sub-stage re-tag, not a new phase boundary). The coarse "parse"/"finish" `stage_start`/`stage_end`
calls below are unchanged.

Whole-run lock (`.ingest.lock`, `app/dashboard/` control-plane review): `--parse-workers`'s
`.gpu.lock` only serializes the GPU-bound half of a run (`Config.gpu_lock_path`, acquired deep
inside the embed step) -- nothing stopped two whole `app.ingest` invocations (one manual, one
dashboard-launched, or two manual ones) from both running Pass 1 at once, each writing
`ingest_state` for an overlapping paper set. `filelock.FileLock(_ingest_lock_path(cfg))` is
acquired, non-blocking, as the first action once `cfg` (the EFFECTIVE, post-override config) is
known -- and held for the entire run (parse + finish); a second invocation whose effective
`db_path` resolves to the SAME directory refuses to start instead of racing the first. OG-49#2:
the lock path is now resolved ABSOLUTE against `db_path`'s own directory (`_ingest_lock_path`),
not a bare relative literal in whatever the process's cwd happens to be -- every overridden
dashboard run (a scratch `config.yaml` dir) and every `build_corpus --paper-ids-file` batch used
to get its OWN throwaway `.ingest.lock`, silently bypassing this guard (two runs could write the
same `papers.db` concurrently, the exact corruption the lock exists to prevent); a `--scratch` run
(its own unique `db_path` every time) still correctly gets its own lock, since it never shares a
corpus with anything else. This is the real double-run guard; `app/dashboard/controller.py`'s own
manifest-PID guard is a fast, friendly error message on top of it, not a substitute for it -- a
manual `python -m app.ingest` (which never touches the manifest) is caught here regardless. Note:
the lock is released the instant this process exits, cleanly or via SIGTERM/SIGKILL (the OS reclaims
an `flock` on process exit), so a paused/stopped run's lock is free again as soon as its PID is
actually gone -- no separate cleanup step needed. Runs launched before this lock existed (e.g. an
already-live run started prior to this change landing) are not holding it and are not protected by
it until they're restarted.
"""

import argparse
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import filelock
import yaml

from app import doctor, tei_lifecycle, telemetry
from app.assembly import build_ingestion_orchestrator, harvest_refs
from contracts.config import Config
from migrations.migrate import migrate
from rag.config import load_config

# Whole-run mutual-exclusion lock -- see module docstring "Whole-run lock". OG-49#2: the lock
# FILE NAME stays this same short literal, but the path it's resolved against is now `db_path`'s
# own directory (`_ingest_lock_path` below), not a bare relative literal in whatever the process's
# cwd happens to be -- see that function's docstring for why.
_INGEST_LOCK_NAME = ".ingest.lock"

# Config fields that hold a filesystem path -- resolved to absolute before being written into a
# scratch config.yaml for the Pass-1 subprocess (see _write_override_config_dir). Curated, not
# derived: every path-valued field contracts/config.py currently declares.
_PATH_FIELDS = ("gpu_lock_path", "db_path", "blob_dir", "pdf_cache_dir", "batch_size_log_path")

# migrations/0001_init.sql's first table -- present iff `db_path` has already been migrated
# (T-DOC44). A read-only existence check, never a write.
_SCHEMA_MARKER_TABLE = "ingest_state"


def _run_finish_phase(cfg: Config, *, on_stage=None) -> None:
    """Pass 2 setup + run -- pulled out of `__main__` so a test can drive it without spawning the
    real Pass 1 subprocess.

    Restarts TEI HERE, before `orchestrator.finish_phase()` is ever called (T-DOC19 bug fix):
    `finish_phase()` embeds its once-per-run `topic_query_vec` BEFORE its own `before_finish_phase`
    hook fires (`rag/orchestrator.py`, frozen -- see that module's `finish_phase` docstring), so a
    composition-root hook wired to `tei_lifecycle.start_tei_containers` restarts TEI too late: this
    process's own `docker stop` (from Pass 1's `before_parse_phase`, still in effect across the
    Pass-1-subprocess boundary) is still in effect when that embed call fires, and it fails.
    Calling `start_tei_containers()` explicitly out here, before `finish_phase()` is invoked at
    all, closes that gap -- see `app/assembly.py` (no longer wires `before_finish_phase` for this).

    `on_stage` (T-DOC59/OG-25, default `None`): forwarded to `build_ingestion_orchestrator` as its
    `on_stage=` hook, so `finish_phase()`'s per-paper summarize/embed/store work re-tags whatever
    telemetry `__main__` wired here (`run.set_stage`, `app/telemetry.py`). `None` leaves
    `IngestionOrchestrator`'s own no-op default in place -- today's exact behavior for any caller
    (e.g. this module's own tests) that doesn't pass one.
    """
    orchestrator = build_ingestion_orchestrator(
        cfg, db_path=cfg.db_path, blob_dir=cfg.blob_dir, collection=cfg.collection,
        on_stage=on_stage,
    )
    # harvest_refs (app/assembly.py): shared with app/parse_phase.py's identical call so both
    # phases of one run agree on the same explicit paper set (cfg.ingest_paper_ids, if set)
    # instead of Pass 2 falling back to a fresh query-driven harvest() that Pass 1 never used.
    refs = harvest_refs(cfg, orchestrator)
    tei_lifecycle.start_tei_containers()
    orchestrator.finish_phase(refs)


def _run_parse_phase_subprocesses(parse_workers: int, *, cwd: str | None = None) -> None:
    """Pass 1 -- pulled out of `__main__` (same pattern as `_run_finish_phase`) so a test can
    drive it with a mocked `subprocess.Popen`/`subprocess.run` instead of spawning real
    GPU-bound parse subprocesses.

    `parse_workers == 1` (default) is byte-for-byte the original single
    `subprocess.run(..., check=True)` call -- unchanged.

    `parse_workers > 1` spawns that many `app.parse_phase` subprocesses, each given a disjoint
    `--shard-index`/`--shard-count` slice of the same harvested corpus (`app/parse_phase.py`'s
    `_shard`). All N are waited on -- not just until the first failure -- before this function
    returns or raises, preserving two-phase VRAM isolation: `__main__` below only calls
    `_run_finish_phase` (Pass 2) after every Pass-1 worker has fully exited. Any non-zero exit
    fails the WHOLE run (`RuntimeError`), never just the workers that happened to fail: a dead
    shard must not silently ship a partial corpus -- exactly the failure mode that made one
    benchmark config look like a win when a worker had actually OOM'd
    (`.phase0-data/pass1-gpu-underutilization.md`).

    `cwd` (T-DOC45/T-DOC46, default `None`): if given, every subprocess is launched with that
    working directory instead of inheriting this process's -- see `_write_override_config_dir`.
    `None` (the default) omits the `cwd` kwarg entirely rather than passing `cwd=None`, so the
    default-flags call is byte-for-byte identical to the pre-T-DOC45/46 call.
    """
    kwargs: dict = {"check": True}
    if cwd is not None:
        kwargs["cwd"] = cwd

    if parse_workers == 1:
        subprocess.run([sys.executable, "-m", "app.parse_phase"], **kwargs)
        return

    popen_kwargs: dict = {} if cwd is None else {"cwd": cwd}
    procs = [
        subprocess.Popen(
            [
                sys.executable, "-m", "app.parse_phase",
                "--shard-index", str(i), "--shard-count", str(parse_workers),
            ],
            **popen_kwargs,
        )
        for i in range(parse_workers)
    ]
    failures = [(i, rc) for i, p in enumerate(procs) if (rc := p.wait()) != 0]
    if failures:
        raise RuntimeError(
            f"app.parse_phase: {len(failures)}/{parse_workers} shard worker(s) failed "
            f"(shard_index, returncode): {failures}"
        )


def _ensure_db_migrated(db_path: str) -> None:
    """T-DOC44: `IngestionOrchestrator`/`DocumentStore` never create or verify schema themselves
    -- pointing a run at a fresh `db_path` used to crash deep in the pipeline with an opaque
    `no such table` (`reviews/OPERATIONAL-GAPS.md` OG-2). Detects an absent/unmigrated DB with a
    read-only `sqlite_master` query for a known table (`ingest_state`, the first table
    `migrations/0001_init.sql` creates) and auto-provisions it by CALLING
    `migrations.migrate.migrate()` (foundation-protected module -- called, never edited, per this
    ticket's constraint) before either pipeline phase opens a connection against it.

    A no-op if the table already exists: `migrate()` itself fails loudly (by design -- plain
    `CREATE TABLE`, no `IF NOT EXISTS`) if re-run against an already-migrated DB, so this guard is
    what makes it safe to call this function unconditionally on every `app.ingest` startup instead
    of requiring an operator to remember to run it once by hand.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (_SCHEMA_MARKER_TABLE,),
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        return
    print(
        f"app.ingest: {db_path!r} has no {_SCHEMA_MARKER_TABLE!r} table -- auto-provisioning "
        f"schema (migrations/migrate.py) before starting."
    )
    migrate(db_path)


def _ingest_lock_path(cfg: Config) -> Path:
    """OG-49#2: resolves the whole-run lock ABSOLUTE against `cfg.db_path`'s own directory -- not
    a bare relative literal (`.ingest.lock`) in whatever the process's cwd happens to be. Every
    overridden dashboard run (a scratch `config.yaml` dir, `app/dashboard/controller.py`) and every
    `build_corpus --paper-ids-file` batch used to get its OWN throwaway `.ingest.lock` in its own
    scratch cwd -- the double-run guard was bypassed by construction, since two runs targeting the
    identical `db_path` never contended for the same lock file. Deriving the lock path from
    `db_path`'s directory (non-foundation) means every run whose EFFECTIVE `db_path` resolves to
    the same directory shares the identical lock regardless of cwd -- a `--scratch` run (its own
    unique `db_path` every time) still gets its own lock, correctly, since it never shares a corpus
    with anything else."""
    return Path(cfg.db_path).resolve().parent / _INGEST_LOCK_NAME


def _validate_parse_workers(parse_workers: int) -> None:
    """OG-49#3: `--parse-workers 0` spawns ZERO Pass-1 subprocesses (`range(0)` in
    `_run_parse_phase_subprocesses`), so Pass 1 "succeeds" having parsed nothing; a caller looping
    batches on top of this (`app.build_corpus.build_to_target`) would resubmit the same non-empty
    batch forever with no progress -- an infinite no-op loop. Exits with one clear message instead
    of silently wedging the caller. Defensive here (not just the dashboard's own `/api/control`
    boundary, `app/dashboard/server.py::_validate_control_kwargs`) so a manual
    `python -m app.ingest --parse-workers 0` is rejected the same way.
    """
    if parse_workers < 1:
        print(f"app.ingest: --parse-workers must be >= 1, got {parse_workers}", file=sys.stderr)
        sys.exit(1)


def _preflight_gate(cfg: Config, *, no_preflight: bool, force: bool) -> None:
    """T-DOC43: refuse to start with one clear message naming every missing prerequisite instead
    of quarantining papers or crashing partway through a multi-hour run. `--no-preflight` skips
    this entirely (zero calls). `--force` still runs the check and prints what it found, but never
    refuses to start.
    """
    if no_preflight:
        return
    issues = doctor.run_preflight(cfg)
    if not issues:
        return
    message = doctor.format_issues(issues)
    if force:
        print(f"--force: proceeding despite preflight issues.\n{message}", file=sys.stderr)
        return
    print(message, file=sys.stderr)
    sys.exit(1)


def _scratch_overrides() -> dict:
    """T-DOC46: auto-provision isolated throwaway storage -- a temp `db_path` + `blob_dir` under
    one fresh directory, and a uniquely-named vector-store collection (rag/vector_index.py) -- so
    a benchmark/test run can't touch production even if `--scratch` is passed alongside a real
    config.yaml. Printed prominently so the operator knows where to look for/clean up scratch
    data afterward.

    ponytail: does not wire dedup read-only against the real production DB (T-DOC46's "production
    used read-only for dedup") -- that requires constructing the real `Harvester` with `seen_ids`
    drawn from production's `papers.db`, which happens in `app/assembly.py`
    (`build_ingestion_orchestrator`), outside this ticket's file territory. Flagged, not
    implemented: a scratch run currently re-harvests/re-downloads papers production may already
    have, rather than skipping them -- wasteful but never unsafe (it still never writes to
    production's db_path/blob_dir/collection). Add real dedup wiring in `app/assembly.py` if a
    scratch run's re-harvest cost ever becomes a real problem.
    """
    root = Path(tempfile.mkdtemp(prefix="app_ingest_scratch_"))
    collection = f"scratch_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    overrides = {
        "db_path": str(root / "papers.db"),
        "blob_dir": str(root / "blobs"),
        "collection": collection,
    }
    print(
        f"app.ingest --scratch: isolated run -- db_path={overrides['db_path']} "
        f"blob_dir={overrides['blob_dir']} collection={overrides['collection']!r} "
        f"(production untouched; clean up {root} and the collection when done)."
    )
    return overrides


def _effective_config(cfg: Config, args: argparse.Namespace) -> Config:
    """T-DOC45 (`--limit`) / T-DOC46 (`--scratch`): both are run-scoped overrides on the one
    `Config` object, applied once here (a CLI arg, never a `Config` field or an env var --
    CONVENTIONS.md §3 / this ticket's own constraint) rather than threaded through as separate
    parameters everywhere downstream. Returns `cfg` unchanged if neither flag is set -- today's
    exact default behavior.

    OG-49#6/M8: `cfg.model_copy(update=updates)` does not re-run pydantic validation on its own --
    re-validated via `Config.model_validate(...)` before being returned (defense-in-depth
    mirroring `app/dashboard/controller.py::_maybe_build_override`'s identical fix; every value
    built here today is already well-typed by construction -- argparse `int`/a plain string list --
    so this is a backstop against a future caller passing something looser, not a currently
    reachable bug).
    """
    updates: dict = {}
    if args.scratch:
        updates.update(_scratch_overrides())
    if args.limit is not None:
        updates["corpus_cap"] = min(cfg.corpus_cap, args.limit)
    if args.paper_ids_file is not None:
        # OG-40: one base arXiv id per line -> cfg.ingest_paper_ids, which routes harvest_refs
        # (app/assembly.py) through the cache-first `fetch_by_ids` path instead of query harvest.
        updates["ingest_paper_ids"] = [
            line.strip()
            for line in Path(args.paper_ids_file).read_text().splitlines()
            if line.strip()
        ]
    if not updates:
        return cfg
    return Config.model_validate(cfg.model_copy(update=updates).model_dump())


def _write_override_config_dir(cfg: Config) -> Path:
    """T-DOC45/T-DOC46: Pass 1 runs `python -m app.parse_phase` as a separate process (two-phase
    VRAM isolation, ARCHITECTURE.md §3) that loads its own `config.yaml` fresh from its cwd -- it
    never receives this process's in-memory, already-overridden `cfg` directly. The only channel
    available to hand it the SAME overrides without editing `app/parse_phase.py` (outside this
    ticket's file territory) is the one it already reads unconditionally: `config.yaml` itself,
    resolved relative to its process cwd.

    Writes `cfg` (already overridden by `_effective_config`) to a scratch `<tmpdir>/config.yaml`,
    with every relative-path-valued field (`_PATH_FIELDS`) resolved to an absolute path first --
    the subprocess is about to run with a DIFFERENT cwd (this tmpdir), so an unresolved relative
    field would silently resolve somewhere else entirely (in particular `gpu_lock_path`: Pass 1
    and this process must contend for the identical lock file, and an unresolved `pdf_cache_dir`
    would silently stop hitting the real, shared PDF cache). Returns the tmpdir -- the caller
    passes it as the Pass-1 subprocess's `cwd=`.

    OG-49 M10: the caller (`__main__`) removes this directory once every phase of THIS run has
    completed (its own `finally`, after `run.finish()`) -- never here and never right after Pass 1
    returns, since the returned path is a blocking `subprocess.run`/`Popen.wait()` cwd that must
    still exist for the whole of Pass 1. Not cleaned up on `_ensure_db_migrated`/preflight failure
    (this function isn't even called yet at that point) or on exceptions raised in between -- those
    paths only ever exist for a run that got at least as far as Pass 1, and `__main__`'s `finally`
    covers exactly that span unconditionally, success or failure.
    """
    path_updates = {
        field: str(Path(value).resolve())
        for field in _PATH_FIELDS
        if (value := getattr(cfg, field))
    }
    resolved = cfg.model_copy(update=path_updates) if path_updates else cfg

    tmpdir = Path(tempfile.mkdtemp(prefix="app_ingest_override_"))
    (tmpdir / "config.yaml").write_text(yaml.safe_dump(resolved.model_dump()))
    return tmpdir


def _cleanup_scratch_dir(path: str | None) -> None:
    """OG-49 M10: removes the scratch `config.yaml` dir `_write_override_config_dir` wrote (if
    any) -- `__main__` calls this from its outer `finally`, only after every phase of the run
    (parse + finish) has completed, so it never races Pass 1's subprocess still reading
    `<path>/config.yaml` from that directory as its cwd. A no-op for `None` (no override was ever
    written this run). `ignore_errors=True`: a dir a human already cleaned up by hand, or one that
    was never fully created, must never make cleanup itself the thing that fails.
    """
    if path is not None:
        shutil.rmtree(path, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parse-workers", type=int, default=1)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="T-DOC45: cap the harvested/ingested paper count at N for this run only",
    )
    parser.add_argument(
        "--scratch", action="store_true",
        help="T-DOC46: auto-provision isolated throwaway db/blob/collection storage for this run",
    )
    parser.add_argument(
        "--paper-ids-file", default=None,
        help="OG-40: ingest exactly the base arXiv ids listed in this file (one per line) via the "
             "cache-first path -- reconstructs each from pdf_cache/<id>.{pdf,json} with no network, "
             "only sidecar-less ids fetch metadata. Feed the cached PDF basenames to ingest every "
             "already-downloaded paper instead of re-discovering via the query API.",
    )
    parser.add_argument(
        "--no-preflight", action="store_true",
        help="T-DOC43: skip the startup readiness check entirely",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="T-DOC43: run the startup readiness check but never refuse to start on a failure",
    )
    parser.add_argument(
        "--events-path", default="ingest_events.jsonl",
        help="T-DOC47: append JSON-line run events (run id, stage, timestamps, paper counts) here",
    )
    parser.add_argument(
        "--telemetry-poll-interval", type=float, default=telemetry.DEFAULT_GPU_POLL_INTERVAL_SECONDS,
        help="T-DOC47: seconds between GPU util/VRAM/power samples during the run",
    )
    return parser.parse_args()


if __name__ == "__main__":
    cfg = load_config()
    args = _parse_args()
    _validate_parse_workers(args.parse_workers)

    cfg = _effective_config(cfg, args)

    # Whole-run lock -- see module docstring "Whole-run lock" and `_ingest_lock_path`'s own
    # docstring (OG-49#2: resolved absolute against the EFFECTIVE db_path's directory, not a bare
    # relative literal in whatever cwd happens to be -- needs the post-override `cfg`, hence this
    # runs after `_effective_config` above, not before `load_config()` as it used to). Acquired
    # non-blocking, before any real work starts: a second `app.ingest` targeting the SAME corpus
    # (manual or dashboard-launched, unedited or overridden) refuses to start instead of racing
    # this one for the GPU + ingest_state.
    _lock_path = _ingest_lock_path(cfg)
    _ingest_lock = filelock.FileLock(str(_lock_path))
    try:
        _ingest_lock.acquire(timeout=0)
    except filelock.Timeout:
        print(
            f"app.ingest: another app.ingest run already holds {str(_lock_path)!r} for this "
            "corpus -- refusing to start a second one (two runs would contend for the GPU "
            "and corrupt ingest_state). Wait for it to finish, or pause/stop it first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # OG-49 M10: `None` until (if ever) `_write_override_config_dir` actually creates one below --
    # the `finally` at the bottom of this block only removes it when it's still set to a real path,
    # so a run that never reaches that line (e.g. preflight/migration failure) has nothing to clean.
    subprocess_cwd = None
    try:
        _preflight_gate(cfg, no_preflight=args.no_preflight, force=args.force)
        _ensure_db_migrated(cfg.db_path)

        # T-DOC45/T-DOC46: only pay for a scratch config.yaml + a different Pass-1 subprocess cwd
        # when an override is actually in effect -- the default (neither flag set) path is untouched.
        subprocess_cwd = (
            str(_write_override_config_dir(cfg))
            if (args.scratch or args.limit is not None or args.paper_ids_file is not None)
            else None
        )

        # T-DOC47: telemetry starts only once the DB is confirmed migrated (above) -- its own
        # end-of-run SQLite reads (app/telemetry.py::summarize_run) must never race an unmigrated or
        # absent database.
        run = telemetry.RunTelemetry.start(
            events_path=args.events_path,
            poll_interval_s=args.telemetry_poll_interval,
            requested_paper_count=(
                len(cfg.ingest_paper_ids) if cfg.ingest_paper_ids else cfg.corpus_cap
            ),
        )
        try:
            # ponytail: no retry/backoff if a Pass-1 subprocess fails (e.g. external GPU pressure
            # beyond what eviction can clear) -- letting it raise stops the run; a re-run resumes
            # from ingest_state checkpoints. Add a poll-and-backoff `_ensure_vram` here if this ever
            # proves to be a real problem in practice (ARCHITECTURE.md §3).
            # No explicit env/cwd handoff needed for the DEFAULT path (T-DOC29): every subprocess
            # inherits this process's cwd by default and calls the same `load_config()` (see
            # app/parse_phase.py's `__main__`), so all of them read the identical config.yaml --
            # every phase/shard agrees on db_path/blob_dir/collection/etc. by construction, not by
            # propagating env vars across process boundaries. The `--limit`/`--scratch` path above is
            # the one deliberate exception (`subprocess_cwd`), and only when one of those flags is
            # actually set.
            run.stage_start("parse")
            _run_parse_phase_subprocesses(args.parse_workers, cwd=subprocess_cwd)
            run.stage_end("parse")

            run.stage_start("finish")
            _run_finish_phase(cfg, on_stage=run.set_stage)
            run.stage_end("finish")
        finally:
            # T-DOC47/OG-7: prints the end-of-run summary (done/quarantined/wall-clock/papers-per-hour
            # + SQLite<->vector-store consistency check) even on a mid-run failure, so a crashed run
            # still reports partial progress instead of nothing.
            run.finish(db_path=cfg.db_path, collection=cfg.collection)
            # OG-49 M10: Pass 1's subprocess.run/Popen.wait() calls above have already returned by
            # this point, so nothing still has this cwd open -- safe to remove now.
            _cleanup_scratch_dir(subprocess_cwd)
    finally:
        _ingest_lock.release()
