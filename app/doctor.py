"""`python -m app.doctor` -- T-DOC43/T-DOC52: preflight readiness check + service auto-start.

Real motivation (`LESSONS-LEARNED.md`, `reviews/OPERATIONAL-GAPS.md` OG-1/OG-8/OG-12): a real
100-paper run silently quarantined every paper because the parser's reference-resolution service
(rag/parser.py's adapter) was down and nothing checked first; a later run lost every required
container to a power-cycle with nothing noticing until an operator went looking by hand. Nothing
in `app.ingest` verified disk headroom, GPU/VRAM headroom, the `.gpu.lock` file, or that every
required service was actually reachable before starting real, expensive work.

This module is the fix: `run_preflight()` checks disk headroom, GPU/VRAM headroom (reuses
`app/gpu_headroom.py`'s real probe), that `.gpu.lock` isn't held by a live process, and
health-pings every required service -- both TEI containers, the parser's reference-resolution
service, the retrieval vector store, and the summarizer's model-serving endpoint. T-DOC52 folds
"restart policy" in here rather than a separate module (its own ticket note: no docker-compose
file exists in this repo to declare a restart policy on, so the equivalent is the preflight/
doctor check auto-starting a stopped container itself): an unhealthy TEI container gets one
recovery attempt via the already-tested `app.tei_lifecycle.start_tei_containers()` (T-DOC52
"extend the same docker start pattern", reusing it rather than duplicating its docker-start +
health-poll logic here) before being reported as still down.

**T-DOC78: the other two containerized services (reference-resolution, vector store) now get the
same one-shot recovery attempt.** Originally these were health-check-only -- their real container
names are vendor-restricted tokens under CONVENTIONS.md §1 (`ci/checks/vendor_isolation.py`'s
`VENDOR_RULES` allows each vendor's product name to appear only inside its own adapter file,
`rag/vector_index.py`/`rag/parser.py` respectively, and that check is scoped to
`rag/`+`contracts/`+`app/` alike, so this module could never spell either name itself without a
foundation-protected `ci/` change). The fix isn't a `ci/` change: `rag/vector_index.py`'s
`start_container()` and `rag/parser.py`'s `start_reference_resolution_container()` each do their
own vendor-specific `docker start` + bounded health poll (same shape as `app.tei_lifecycle`, just
living inside the one file each is allowed to name its own container in -- the same reasoning
`rag/vector_index.py`'s `create_and_download_snapshot()` already uses for `app/snapshot.py`'s
backup step). This module calls those two functions through the `_Service.start` field below
without ever naming a vendor or a container itself -- `check_services` doesn't know or care that
one recovery path shells into `app.tei_lifecycle` and the other two shell into their own adapter
modules; it just calls whatever `start` each `_Service` carries. The summarizer's model-serving
endpoint is a host service per T-DOC43's own scope note -- `start=None`, health-check only, never
auto-started, regardless of this fix.

**OP-1 `--cpu-only` (stub, implemented in the following commits):** `python -m app.doctor
--cpu-only` checks/starts only the services that need no GPU (vector store, reference-resolution
service), skips TEI, the VRAM-headroom check and the `.gpu.lock` check, prints which MCP tools work
in that mode and which do not, and exits 0 when the CPU services are ready. Default behaviour is
unchanged.

**OP-6 / OP-5 (`run_ops_checks`, called by `main()` only -- never by `run_preflight`, so
`app.ingest`'s startup gate is unchanged):** a corpus-pairing check (the configured database exists
and holds chunks/summaries; when the vector store is reachable, the collection exists and its point
count is within 5% of chunks + summaries), a data-device free-space warning (below the 20 GiB
snapshot abort rule), and a GPU contention report (free VRAM, compute processes via `nvidia-smi`,
the `.gpu.lock` holder record). Only a definite pairing mismatch is an issue; the rest is printed.

`app.ingest` calls `run_preflight()` at startup (default on, `--no-preflight`/`--force` to skip
or downgrade to a warning) and refuses to start with every issue named in one message, instead of
quarantining papers or crashing partway through a multi-hour run.
"""

import argparse
import asyncio
import logging
import os
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import filelock

from app import gpu_headroom, tei_lifecycle
from app.db_guard import MissingDatabaseError, require_existing_db
from contracts.config import Config
from contracts.errors import TransientError
from rag import gpu_lock as _gpu_lock_adapter
from rag import parser as _parser_adapter
from rag import vector_index as _vector_index_adapter

logger = logging.getLogger(__name__)

# Same URLs app/tei_lifecycle.py health-polls -- this module owns its own copies rather than
# importing that module's private constants (same "own your own copies" convention that
# module's own docstring already follows relative to app/assembly.py).
_TEI_EMBED_HEALTH_URL = "http://localhost:8080/health"
_TEI_RERANK_HEALTH_URL = "http://localhost:8082/health"


@dataclass(frozen=True)
class _Service:
    name: str
    health_url: str
    # T-DOC78: best-effort recovery attempt if unhealthy, re-checked before being reported as an
    # issue -- same one-shot-recovery shape `check_services` already gives the two TEI endpoints
    # below via `app.tei_lifecycle`. `None` means health-check only, no recovery path exists (the
    # summarizer's host-service endpoint, by design -- see module docstring).
    start: Callable[[], None] | None = None
    # OP-1: True if the service needs the GPU to be useful; `--cpu-only` skips it.
    needs_gpu: bool = False


# Confirmed real ports via a live health probe this session -- see each URL's owning adapter
# module for the vendor/product this port belongs to (not named here -- see module docstring).
# `start` points at each adapter's own vendor-specific `docker start` + health-poll helper
# (T-DOC78) -- this module calls it without ever knowing or naming the vendor/container itself.
# Wrapped in a lambda (rather than bound directly, e.g. `start=_parser_adapter.start_...`) so a
# test's `monkeypatch.setattr(doctor_mod._parser_adapter, "start_...", fake)` is looked up at call
# time and actually takes effect -- a directly-bound reference would freeze in the real function
# at import time, before any test gets a chance to patch it.
_HEALTH_ONLY_SERVICES = (
    _Service(
        "parser reference-resolution service (rag/parser.py)",
        "http://localhost:8070/api/isalive",
        start=lambda: _parser_adapter.start_reference_resolution_container(),
    ),
    _Service(
        "vector store (rag/vector_index.py)",
        "http://localhost:6333/collections",
        start=lambda: _vector_index_adapter.start_container(),
    ),
    _Service(
        "summarizer model-serving endpoint (rag/summarizer.py, host service)",
        "http://localhost:11434/api/ps",
        needs_gpu=True,
        # start=None: a host service, not a container -- health-check only, never auto-started
        # (T-DOC43's original scope note, unaffected by this ticket's fix for the other two).
    ),
)

# ponytail: fixed floors, not per-run-tunable CLI flags -- nothing in this ticket's motivating
# incidents (a down reference-resolution service, containers lost to a power-cycle) needed a
# different threshold per run. Promote to a CLI flag if a real run ever needs a different floor.
_MIN_FREE_DISK_GIB = 5.0
_MIN_FREE_VRAM_MIB = 2000
# OP-6: the snapshot abort rule (app/snapshot.py MIN_FREE_GIB) -- below this the data device is
# too full to back up onto itself, so doctor warns.
_SNAPSHOT_MIN_FREE_GIB = 20.0
# OP-6: vector-store points should equal chunks + summaries (rag/orchestrator.py upserts exactly
# those two kinds); allow slack for an ingest in flight or a just-deleted paper.
_POINT_COUNT_TOLERANCE = 0.05
_VECTOR_STORE_HOST = "localhost"
_VECTOR_STORE_PORT = 6333
# OP-5: what the embedder + reranker need resident, per ARCHITECTURE.md §3 / CONVENTIONS.md §6
# ("~9.4GB together"; the embedder alone is ~9-10GB during a real batch). NOT the same number as
# `_MIN_FREE_VRAM_MIB` above, which is the older 2000 MiB preflight floor -- see
# `describe_gpu_contention`, which reports both instead of silently picking one.
_TEI_PAIR_RESIDENT_MIB = 9400
_HEALTH_CHECK_TIMEOUT_SECONDS = 5.0
# T-DOC66: generous relative to the HTTP health-check timeout above -- this spawns a real `conda`/
# `python` subprocess and imports app.serve's full composition root (every client object its
# query-path services need), not a single socket round trip. No network calls happen before
# list_tools responds, so this is bounded by process/import startup, not a slow downstream service.
_MCP_CHECK_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class PreflightIssue:
    check: str
    detail: str

    def __str__(self) -> str:
        return f"{self.check}: {self.detail}"


def check_disk_headroom(
    path: str = ".", *, min_free_gib: float = _MIN_FREE_DISK_GIB
) -> PreflightIssue | None:
    """Free disk headroom at `path` (default: cwd -- where `db_path`/`blob_dir` land by default,
    CONVENTIONS.md's relative-path convention for `app/`'s own Config-driven paths)."""
    free_gib = shutil.disk_usage(path).free / (1024**3)
    if free_gib < min_free_gib:
        return PreflightIssue(
            "disk", f"only {free_gib:.1f} GiB free at {path!r} (need >= {min_free_gib} GiB)"
        )
    return None


def check_gpu_headroom(*, min_free_mib: int = _MIN_FREE_VRAM_MIB) -> PreflightIssue | None:
    """Reuses `app/gpu_headroom.py`'s real, already-built VRAM probe (T-DOC43: "reuse
    app/gpu_headroom.py if it fits") rather than re-implementing a second one."""
    free_mib = gpu_headroom.free_vram_mib()
    if free_mib is None:
        return PreflightIssue(
            "gpu", "could not read free VRAM (GPU probe failed) -- is a GPU attached?"
        )
    if free_mib < min_free_mib:
        return PreflightIssue("gpu", f"only {free_mib} MiB free VRAM (need >= {min_free_mib} MiB)")
    return None


def check_gpu_lock_free(lock_path: str) -> PreflightIssue | None:
    """A held `.gpu.lock` at preflight time means another real ingest/serve process already
    holds the cross-process GPU compute serializer (`rag/gpu_lock.py`'s `FileGpuLock`,
    CONVENTIONS.md §6) -- worth surfacing loudly rather than silently queuing an expensive run
    behind an already-running one. Non-blocking probe only: a zero-timeout `acquire()` that
    releases immediately on success, so this check never itself holds the lock past this
    function returning (the real orchestrator acquires it for real, later, per inference call).
    """
    lock = filelock.FileLock(lock_path)
    try:
        lock.acquire(timeout=0)
    except filelock.Timeout:
        holder = _gpu_lock_adapter.read_holder(Path(lock_path))
        who = (
            f" (pid {holder['pid']}, stage {holder.get('stage')!r}, since {holder.get('since')}: "
            f"{holder.get('command')})"
            if holder
            else ""
        )
        return PreflightIssue("gpu_lock", f"{lock_path} is held by another live process{who}")
    lock.release()
    return None


def check_data_disk_space(
    cfg: Config, *, min_free_gib: float = _SNAPSHOT_MIN_FREE_GIB
) -> str | None:
    """Warning text if the device holding the data dir (`db_path`'s directory) has less than
    `min_free_gib` free, else None. Walks up to the nearest existing directory."""
    path = Path(cfg.db_path).resolve().parent
    while not path.exists() and path != path.parent:
        path = path.parent
    usage = shutil.disk_usage(path)
    free_gib = usage.free / 1024**3
    if free_gib < min_free_gib:
        return (
            f"only {free_gib:.1f} GiB free on the device holding {path} "
            f"(snapshots abort below {min_free_gib:g} GiB)"
        )
    return None


def check_corpus_pairing(cfg: Config) -> tuple[list[PreflightIssue], list[str]]:
    """Do the configured database and collection belong together? (issues, notes).

    Knowable without the vector store: the database file exists (it is never created here) and
    holds chunks/summaries -- the database itself records no collection name, so the name cannot be
    checked from SQLite alone. With the store reachable: the collection exists and its point count
    is within `_POINT_COUNT_TOLERANCE` of chunks + summaries. An empty database is only a note (a
    brand-new corpus is legitimate); a missing database, a missing collection over a populated
    database, or a count mismatch is an issue. The store being down is a note, never an issue here
    (the service check reports that).
    """
    try:
        db = require_existing_db(cfg.db_path)
    except MissingDatabaseError as error:
        return [PreflightIssue("corpus pairing", str(error))], []
    try:
        con = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
        try:
            chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            summaries = con.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as error:
        return [PreflightIssue("corpus pairing", f"cannot read {db}: {error}")], []
    expected = chunks + summaries
    if expected == 0:
        return [], [f"database {db} holds 0 chunks and 0 summaries -- new corpus or wrong db?"]
    if not _is_healthy(f"http://{_VECTOR_STORE_HOST}:{_VECTOR_STORE_PORT}/collections"):
        return [], [
            f"database holds {expected} chunks+summaries; pairing with collection "
            f"{cfg.collection!r} not checked (vector store unreachable)"
        ]
    try:
        points = _vector_index_adapter.collection_point_count(
            _VECTOR_STORE_HOST, _VECTOR_STORE_PORT, cfg.collection
        )
    except TransientError as error:
        return [], [f"could not read collection {cfg.collection!r}: {error}"]
    if points is None:
        return [
            PreflightIssue(
                "corpus pairing",
                f"collection {cfg.collection!r} does not exist in the vector store but "
                f"{db} holds {expected} chunks+summaries -- wrong config for this database?",
            )
        ], []
    if abs(points - expected) > _POINT_COUNT_TOLERANCE * expected:
        return [
            PreflightIssue(
                "corpus pairing",
                f"collection {cfg.collection!r} has {points} points but {db} has {expected} "
                f"chunks+summaries (tolerance {_POINT_COUNT_TOLERANCE:.0%}) -- wrong pairing or "
                "an index out of sync",
            )
        ], []
    return [], [f"collection {cfg.collection!r}: {points} points vs {expected} expected: ok"]


def describe_gpu_contention(cfg: Config) -> list[str]:
    """Plain-text GPU contention report (OP-5): free VRAM vs what the TEI pair needs, every compute
    process `nvidia-smi` lists (those that are not the recorded `.gpu.lock` holder are marked
    foreign -- TEI's own containers show up here too while they are up), and the lock holder.
    Informational; never raises, and prints a one-line "unavailable" when `nvidia-smi` is absent."""
    free_mib = gpu_headroom.free_vram_mib()
    procs = gpu_headroom.gpu_compute_processes()
    holder = _gpu_lock_adapter.read_holder(Path(cfg.gpu_lock_path))
    lines = []
    if free_mib is None:
        lines.append("GPU: nvidia-smi unavailable -- cannot read VRAM or processes")
    else:
        lines.append(
            f"GPU: {free_mib} MiB free VRAM (preflight floor {_MIN_FREE_VRAM_MIB} MiB; embedder + "
            f"reranker need ~{_TEI_PAIR_RESIDENT_MIB} MiB resident per ARCHITECTURE.md)"
        )
        if free_mib < _TEI_PAIR_RESIDENT_MIB:
            lines.append(
                f"GPU: free VRAM is below the ~{_TEI_PAIR_RESIDENT_MIB} MiB embedder + reranker "
                "need -- the TEI containers cannot start (CUDA out of memory) until it is freed"
            )
    holder_pid = holder["pid"] if holder else None
    for proc in procs or []:
        mem = "?" if proc.used_mib is None else f"{proc.used_mib} MiB"
        tag = "gpu lock holder" if proc.pid == holder_pid else "foreign"
        lines.append(f"GPU process [{tag}]: pid {proc.pid} {proc.name} {mem}")
    if procs == []:
        lines.append("GPU processes: none")
    if holder:
        lines.append(
            f".gpu.lock holder: pid {holder['pid']} stage {holder.get('stage')!r} since "
            f"{holder.get('since')} -- {holder.get('command')}"
        )
    return lines


def run_ops_checks(cfg: Config) -> tuple[list[PreflightIssue], list[str]]:
    """OP-6/OP-5 extras for `main()`: (issues, informational lines). Not part of `run_preflight`."""
    issues, lines = check_corpus_pairing(cfg)
    disk_warning = check_data_disk_space(cfg)
    if disk_warning:
        lines.append(f"WARNING: {disk_warning}")
    return issues, lines + describe_gpu_contention(cfg)


def _is_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=_HEALTH_CHECK_TIMEOUT_SECONDS) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def check_services(*, auto_start: bool = True, cpu_only: bool = False) -> list[PreflightIssue]:
    """Health-ping every required service. T-DOC52/T-DOC78: if a service is unhealthy and carries
    a recovery path, one attempt goes through it (docker start + bounded health poll) before being
    reported as an issue -- a stopped-but-startable container (the OG-12 power-cycle case) is
    fixed automatically instead of just being named as broken. TEI goes through the already-tested
    `app.tei_lifecycle.start_tei_containers()`; the reference-resolution service and vector store
    go through their own adapter's `start` (T-DOC78 -- see module docstring for why that recovery
    code lives there, not here). The summarizer's host-service endpoint has no recovery path
    (`start=None`) and stays health-check only. `auto_start=False` skips every recovery attempt.

    `cpu_only=True` (OP-1) checks/starts only the services that do not need the GPU: TEI and the
    summarizer's endpoint are skipped entirely.
    """
    issues = []

    tei_healthy = cpu_only or (
        _is_healthy(_TEI_EMBED_HEALTH_URL) and _is_healthy(_TEI_RERANK_HEALTH_URL)
    )
    if not tei_healthy and auto_start:
        tei_lifecycle.start_tei_containers()
        tei_healthy = _is_healthy(_TEI_EMBED_HEALTH_URL) and _is_healthy(_TEI_RERANK_HEALTH_URL)
    if not tei_healthy:
        if not _is_healthy(_TEI_EMBED_HEALTH_URL):
            detail = f"unreachable at {_TEI_EMBED_HEALTH_URL}"
            issues.append(PreflightIssue("TEI embedder", detail))
        if not _is_healthy(_TEI_RERANK_HEALTH_URL):
            detail = f"unreachable at {_TEI_RERANK_HEALTH_URL}"
            issues.append(PreflightIssue("TEI reranker", detail))

    for service in _HEALTH_ONLY_SERVICES:
        if cpu_only and service.needs_gpu:
            continue
        healthy = _is_healthy(service.health_url)
        if not healthy and auto_start and service.start is not None:
            service.start()
            healthy = _is_healthy(service.health_url)
        if not healthy:
            issues.append(PreflightIssue(service.name, f"unreachable at {service.health_url}"))

    return issues


async def _launch_and_list_tools(*, cwd: str, timeout: float) -> list[str]:
    """Spawns `python -m app.serve` over real MCP stdio and returns the tool names it advertises.

    Same subprocess spelling as `app.mcp_verify_client`'s own manual-verification tool
    (`command=sys.executable, args=["-m", "app.serve"]`), but built independently rather than
    importing that module's params builder -- that builder also forwards the entire process
    environment to the child, and copying that one piece of it here would repeat a
    process-environment read outside `rag/config.py` (CONVENTIONS.md §3 / `ci/checks/env_leak.py`
    check (d) flags that specific read wherever it lands in a diff, not just at its original site
    -- see that check's own module docstring). This check leaves `env` unset instead (the MCP
    SDK's own curated safe-subset default) -- sufficient because `-m app.serve` resolves its own
    package imports via `cwd` (Python's `-m` semantics add `cwd` to `sys.path[0]`), not via
    `PYTHONPATH`, as long as `cwd` names a real checkout root. True for `check_mcp_server`'s
    default (the calling process's own cwd, docs/RUNBOOK.md's documented "run from the repo root"
    convention).
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "app.serve"], cwd=cwd)
    async with asyncio.timeout(timeout):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [t.name for t in tools.tools]


def check_mcp_server(
    *,
    cwd: str | None = None,
    timeout: float = _MCP_CHECK_TIMEOUT_SECONDS,
    _list_tools: Callable[[], list[str]] | None = None,
) -> PreflightIssue | None:
    """T-DOC66: verifies `python -m app.serve` actually launches and answers `list_tools` --
    catches a broken MCP deploy (missing `PYTHONPATH`, wrong `cwd`, a crash on import) before an
    operator finds out the hard way mid-session, same "check before relying on it" shape as every
    other check in this module.

    `cwd` defaults to THIS process's own cwd -- the same one `load_config()` already resolved
    `main()`'s `cfg` from -- so the spawned server discovers the identical config, not always this
    repo's root regardless of where `doctor` itself was invoked from.

    `_list_tools` is the injection seam a test uses to substitute a fake instead of a real
    subprocess spawn (CONVENTIONS.md §2, same pattern as `_Service.start` above); real callers
    never pass it.

    CAVEAT: this does NOT spawn `python -m app.serve` the same way `app.mcp_verify_client` (or a
    real MCP client) does -- see `_launch_and_list_tools`'s own docstring for why it omits the
    full-environment forwarding that tool's spawn carries. A pass here is proof the server
    launches and speaks MCP under a curated, safe-subset environment; it is NOT proof a real
    client's launch (its own `PYTHONPATH`/full-environment config, `docs/RUNBOOK.md`) works. Use
    `python -m app.mcp_verify_client` for that, before treating a real client integration as done.
    """
    list_tools = _list_tools or (
        lambda: asyncio.run(_launch_and_list_tools(cwd=cwd or os.getcwd(), timeout=timeout))
    )
    try:
        tool_names = list_tools()
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see docstring
        # A real subprocess+protocol round trip fails in too many shapes to enumerate (spawn
        # OSError, asyncio.TimeoutError, an mcp protocol/handshake error, an import-time crash
        # inside the child surfacing as anything) -- same "report it as an issue, don't crash
        # doctor itself" reasoning every OTHER check in this module already gives a named issue
        # for, just with a wider exception surface than an HTTP health ping has.
        return PreflightIssue("mcp server", f"failed to launch or answer list_tools: {exc!r}")
    if not tool_names:
        return PreflightIssue("mcp server", "launched but advertised zero tools")
    return None


def run_preflight(
    cfg: Config, *, auto_start: bool = True, cpu_only: bool = False
) -> list[PreflightIssue]:
    """Every T-DOC43/T-DOC52/T-DOC78 check in one call -- disk, GPU/VRAM, `.gpu.lock`, every
    required service (auto-starting each stopped-but-startable container first). Returns the full
    list of unresolved issues; empty means the environment is ready.

    `cpu_only=True` (OP-1): disk headroom and the CPU services only -- no VRAM or `.gpu.lock`
    check, no TEI.
    """
    basic_checks = [check_disk_headroom()]
    if not cpu_only:
        basic_checks += [check_gpu_headroom(), check_gpu_lock_free(cfg.gpu_lock_path)]
    issues = [issue for issue in basic_checks if issue is not None]
    issues.extend(check_services(auto_start=auto_start, cpu_only=cpu_only))
    return issues


def format_cpu_only_tool_table() -> str:
    """Which MCP tools work with the GPU services down (OP-1)."""
    rows = [(tool, "available") for tool in tei_lifecycle.SQLITE_ONLY_TOOLS]
    rows += [(tool, "NOT available (needs TEI/GPU)") for tool in tei_lifecycle.TEI_TOOLS]
    width = max(len(tool) for tool, _ in rows)
    return "\n".join(f"  {tool:<{width}}  {status}" for tool, status in rows)


def format_issues(issues: list[PreflightIssue]) -> str:
    """One clear message naming everything that's missing (T-DOC43: "refusing to start ... with
    one clear message naming what's missing"), not N separate crashes/log lines."""
    lines = "\n".join(f"  - {issue}" for issue in issues)
    return f"doctor: {len(issues)} issue(s) found -- not ready:\n{lines}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-auto-start", action="store_true",
        help="health-check only; never attempt to start a stopped TEI/vector-store/"
        "reference-resolution container",
    )
    parser.add_argument(
        "--check-mcp", action="store_true",
        help="T-DOC66: also verify `python -m app.serve` launches and answers list_tools. Spawns "
        "a real subprocess, so it's opt-in -- app.ingest's own preflight gate (run_preflight, "
        "the default path below) never touches the MCP server and shouldn't pay for this on "
        "every ingest run.",
    )
    parser.add_argument(
        "--cpu-only", action="store_true",
        help="OP-1: bring up / check only the CPU services (vector store, reference-resolution) "
        "and skip TEI, the GPU-headroom check and the .gpu.lock check -- for when another process "
        "holds the GPU. Prints which MCP tools work in this mode; exit 0 when ready.",
    )
    return parser.parse_args()


def main() -> None:
    from rag.config import load_config

    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    # T-DOC89 §4: report what was resolved, same pattern as app/delete_docs.py -- an operator
    # standing in the wrong directory should see where this process actually pointed, not guess.
    logger.info(
        "doctor: resolved db_path=%s blob_dir=%s collection=%s",
        cfg.db_path, cfg.blob_dir, cfg.collection,
    )
    args = _parse_args()
    issues = run_preflight(cfg, auto_start=not args.no_auto_start, cpu_only=args.cpu_only)
    ops_issues, ops_lines = run_ops_checks(cfg)
    issues.extend(ops_issues)
    if ops_lines:
        print("doctor: corpus / disk / GPU\n" + "\n".join(f"  {line}" for line in ops_lines))
    if args.check_mcp:
        mcp_issue = check_mcp_server()
        if mcp_issue is not None:
            issues.append(mcp_issue)

    if not issues and args.cpu_only:
        print(
            "doctor: OK (--cpu-only) -- vector store and reference-resolution service ready; "
            "TEI/GPU checks skipped.\nMCP tools in this mode:\n" + format_cpu_only_tool_table()
            + f"\nFull operation once the GPU is free: {tei_lifecycle.RECOVERY_COMMAND}"
        )
        return
    if not issues:
        print("doctor: OK -- disk/GPU/lock/all required services healthy.")
        return
    print(format_issues(issues))
    sys.exit(1)


if __name__ == "__main__":
    main()
