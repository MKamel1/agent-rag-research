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
"""

import argparse
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import yaml

from app import doctor, tei_lifecycle
from app.assembly import build_ingestion_orchestrator, harvest_refs
from contracts.config import Config
from migrations.migrate import migrate
from rag.config import load_config

# Config fields that hold a filesystem path -- resolved to absolute before being written into a
# scratch config.yaml for the Pass-1 subprocess (see _write_override_config_dir). Curated, not
# derived: every path-valued field contracts/config.py currently declares.
_PATH_FIELDS = ("gpu_lock_path", "db_path", "blob_dir", "pdf_cache_dir", "batch_size_log_path")

# migrations/0001_init.sql's first table -- present iff `db_path` has already been migrated
# (T-DOC44). A read-only existence check, never a write.
_SCHEMA_MARKER_TABLE = "ingest_state"


def _run_finish_phase(cfg: Config) -> None:
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
    """
    orchestrator = build_ingestion_orchestrator(
        cfg, db_path=cfg.db_path, blob_dir=cfg.blob_dir, collection=cfg.collection,
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
    """
    updates: dict = {}
    if args.scratch:
        updates.update(_scratch_overrides())
    if args.limit is not None:
        updates["corpus_cap"] = min(cfg.corpus_cap, args.limit)
    return cfg.model_copy(update=updates) if updates else cfg


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
        "--no-preflight", action="store_true",
        help="T-DOC43: skip the startup readiness check entirely",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="T-DOC43: run the startup readiness check but never refuse to start on a failure",
    )
    return parser.parse_args()


if __name__ == "__main__":
    cfg = load_config()
    args = _parse_args()

    cfg = _effective_config(cfg, args)

    _preflight_gate(cfg, no_preflight=args.no_preflight, force=args.force)
    _ensure_db_migrated(cfg.db_path)

    # T-DOC45/T-DOC46: only pay for a scratch config.yaml + a different Pass-1 subprocess cwd
    # when an override is actually in effect -- the default (neither flag set) path is untouched.
    subprocess_cwd = (
        str(_write_override_config_dir(cfg)) if (args.scratch or args.limit is not None) else None
    )

    # ponytail: no retry/backoff if a Pass-1 subprocess fails (e.g. external GPU pressure beyond
    # what eviction can clear) -- letting it raise stops the run; a re-run resumes from
    # ingest_state checkpoints. Add a poll-and-backoff `_ensure_vram` here if this ever proves to
    # be a real problem in practice (ARCHITECTURE.md §3).
    # No explicit env/cwd handoff needed for the DEFAULT path (T-DOC29): every subprocess inherits
    # this process's cwd by default and calls the same `load_config()` (see
    # app/parse_phase.py's `__main__`), so all of them read the identical config.yaml -- every
    # phase/shard agrees on db_path/blob_dir/collection/etc. by construction, not by propagating
    # env vars across process boundaries. The `--limit`/`--scratch` path above is the one
    # deliberate exception (`subprocess_cwd`), and only when one of those flags is actually set.
    _run_parse_phase_subprocesses(args.parse_workers, cwd=subprocess_cwd)

    _run_finish_phase(cfg)
