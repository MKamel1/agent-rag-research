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

`app.ingest` calls `run_preflight()` at startup (default on, `--no-preflight`/`--force` to skip
or downgrade to a warning) and refuses to start with every issue named in one message, instead of
quarantining papers or crashing partway through a multi-hour run.
"""

import argparse
import shutil
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

import filelock

from app import gpu_headroom, tei_lifecycle
from contracts.config import Config
from rag import parser as _parser_adapter
from rag import vector_index as _vector_index_adapter

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
        # start=None: a host service, not a container -- health-check only, never auto-started
        # (T-DOC43's original scope note, unaffected by this ticket's fix for the other two).
    ),
)

# ponytail: fixed floors, not per-run-tunable CLI flags -- nothing in this ticket's motivating
# incidents (a down reference-resolution service, containers lost to a power-cycle) needed a
# different threshold per run. Promote to a CLI flag if a real run ever needs a different floor.
_MIN_FREE_DISK_GIB = 5.0
_MIN_FREE_VRAM_MIB = 2000
_HEALTH_CHECK_TIMEOUT_SECONDS = 5.0


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
        return PreflightIssue("gpu_lock", f"{lock_path} is held by another live process")
    lock.release()
    return None


def _is_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=_HEALTH_CHECK_TIMEOUT_SECONDS) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def check_services(*, auto_start: bool = True) -> list[PreflightIssue]:
    """Health-ping every required service. T-DOC52/T-DOC78: if a service is unhealthy and carries
    a recovery path, one attempt goes through it (docker start + bounded health poll) before being
    reported as an issue -- a stopped-but-startable container (the OG-12 power-cycle case) is
    fixed automatically instead of just being named as broken. TEI goes through the already-tested
    `app.tei_lifecycle.start_tei_containers()`; the reference-resolution service and vector store
    go through their own adapter's `start` (T-DOC78 -- see module docstring for why that recovery
    code lives there, not here). The summarizer's host-service endpoint has no recovery path
    (`start=None`) and stays health-check only. `auto_start=False` skips every recovery attempt.
    """
    issues = []

    tei_healthy = _is_healthy(_TEI_EMBED_HEALTH_URL) and _is_healthy(_TEI_RERANK_HEALTH_URL)
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
        healthy = _is_healthy(service.health_url)
        if not healthy and auto_start and service.start is not None:
            service.start()
            healthy = _is_healthy(service.health_url)
        if not healthy:
            issues.append(PreflightIssue(service.name, f"unreachable at {service.health_url}"))

    return issues


def run_preflight(cfg: Config, *, auto_start: bool = True) -> list[PreflightIssue]:
    """Every T-DOC43/T-DOC52/T-DOC78 check in one call -- disk, GPU/VRAM, `.gpu.lock`, every
    required service (auto-starting each stopped-but-startable container first). Returns the full
    list of unresolved issues; empty means the environment is ready.
    """
    basic_checks = (
        check_disk_headroom(),
        check_gpu_headroom(),
        check_gpu_lock_free(cfg.gpu_lock_path),
    )
    issues = [issue for issue in basic_checks if issue is not None]
    issues.extend(check_services(auto_start=auto_start))
    return issues


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
    return parser.parse_args()


def main() -> None:
    from rag.config import load_config

    cfg = load_config()
    args = _parse_args()
    issues = run_preflight(cfg, auto_start=not args.no_auto_start)

    if not issues:
        print("doctor: OK -- disk/GPU/lock/all required services healthy.")
        return
    print(format_issues(issues))
    sys.exit(1)


if __name__ == "__main__":
    main()
