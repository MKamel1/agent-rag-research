"""TEI (Text Embeddings Inference) container lifecycle — evict the Embedder+Reranker containers'
GPU memory during Pass 1 (parse, MinerU-bound) so MinerU can batch larger, then reload them before
Pass 2 (finish: summarize+embed+store) needs them (ARCHITECTURE.md §3's two-pass ingest).

This is process/container orchestration, not domain logic gated by `rag/`'s vendor-isolation scan
(CONVENTIONS.md §1) -- it belongs in `app/` alongside `app/ingest.py`/`app/parse_phase.py`, which
already shell out to run Pass 1 as its own subprocess. Uses stdlib `subprocess` (not the `docker`
SDK) to talk to the Docker CLI directly, matching that existing precedent. `app/` IS in
`ci/checks/vendor_isolation.py`'s scanned scope (T-DOC29 added it) -- this module has its own
explicit entry in the `httpx` `VendorRule`'s `allowed_paths` (T-DOC78) for the same reason every
other real adapter does: it's the one place that talks to `httpx` for this module's own purpose.

Same "issue lifecycle command -> poll a status endpoint until confirmed -> bounded timeout ->
best-effort continue" shape as `rag/summarizer.py`'s `OllamaSummarizer.unload()`: a failure here
isn't a reason to fail the caller's phase transition.
"""

import logging
import subprocess
import time
from pathlib import Path

import filelock
import httpx

logger = logging.getLogger(__name__)

# Confirmed real container names via `docker ps` this session -- no docker-compose file exists
# anywhere in this repo to read these from, so this module is the first place they enter version
# control (also cross-referenced in PHASE0-RUNBOOK.md).
_TEI_CONTAINERS = ("rag-tei-embed", "rag-tei-reranker")

# Same ports as app/assembly.py's _TEI_EMBED_URL/_TEI_RERANK_URL (the embedder/reranker adapters'
# own base URLs) -- this module owns its own copies rather than importing assembly's private
# constants, since assembly.py is the one wiring *this* module, not the other way around.
_TEI_EMBED_HEALTH_URL = "http://localhost:8080/health"
_TEI_RERANK_HEALTH_URL = "http://localhost:8082/health"

_TEI_START_POLL_INTERVAL_SECONDS = 0.25  # matches summarizer.py's existing constant exactly
# Conservative starting value, not a measured one -- a real-Docker validation step (separate, after
# this PR merges) will measure TEI's actual reload latency and tune this for real. Documented here
# so it isn't mistaken for an already-measured number.
_TEI_START_POLL_TIMEOUT_SECONDS = 60.0


def stop_tei_containers() -> None:
    """Best-effort: stop both TEI containers so their VRAM is freed for MinerU during Pass 1. A
    failure here isn't a reason to fail the caller's phase transition -- if docker isn't
    installed/on PATH, or the stop command fails, this logs a warning and returns anyway.
    """
    try:
        subprocess.run(["docker", "stop", *_TEI_CONTAINERS], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        logger.warning(
            "could not stop TEI containers %s -- best-effort, not blocking the caller's phase "
            "transition: %s",
            _TEI_CONTAINERS,
            error,
        )
        return
    # Breadcrumb for an on-call engineer debugging an unexpected outage during Pass 1 (T-DOC19
    # review finding): a successful stop was otherwise completely silent -- only the failure path
    # above logged anything -- so a live MCP query failing against these containers during this
    # window had no log line pointing back to this as the cause.
    logger.info(
        "stopped TEI containers %s for Pass 1 -- live MCP queries against them will fail until "
        "Pass 2's restart (app/ingest.py's _run_finish_phase)",
        _TEI_CONTAINERS,
    )


def start_tei_containers(
    client: httpx.Client | None = None, *, poll_timeout_s: float | None = None,
) -> None:
    """Best-effort: start both TEI containers back up, then block (bounded by
    `_TEI_START_POLL_TIMEOUT_SECONDS`) until both respond healthy -- "block until TEI is ready
    before Pass 2 needs it." `docker start` only launches the container; it says nothing about
    whether the model has finished reloading into VRAM, so this polls each container's `GET
    /health` endpoint every `_TEI_START_POLL_INTERVAL_SECONDS` until both are OK, same shape as
    `OllamaSummarizer.unload()`'s `/api/ps` poll. Still best-effort end to end: on a failed start
    command, or if the timeout elapses before both are healthy, this logs a warning and returns
    anyway -- a failure/timeout here isn't a reason to fail or block the caller's phase transition.

    `client` is injectable (defaults to a real `httpx.Client`) so tests can fake the health check
    without a real network call.

    `poll_timeout_s` (default `None`): overrides `_TEI_START_POLL_TIMEOUT_SECONDS` for this call
    only (T-DOC78) -- lets `ensure_tei_running`'s query-path caller use a shorter deadline than the
    phase-transition default, without changing that default for every other caller."""
    try:
        subprocess.run(["docker", "start", *_TEI_CONTAINERS], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        logger.warning(
            "could not start TEI containers %s -- best-effort, not blocking the caller's phase "
            "transition: %s",
            _TEI_CONTAINERS,
            error,
        )

    if client is None:
        client = httpx.Client(timeout=5.0)

    timeout_s = poll_timeout_s if poll_timeout_s is not None else _TEI_START_POLL_TIMEOUT_SECONDS
    urls = (_TEI_EMBED_HEALTH_URL, _TEI_RERANK_HEALTH_URL)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if all(_is_healthy(client, url) for url in urls):
            return
        time.sleep(_TEI_START_POLL_INTERVAL_SECONDS)

    logger.warning(
        "could not confirm TEI containers %s were healthy within %.1fs -- proceeding anyway "
        "(best-effort; caller's phase transition is not blocked)",
        _TEI_CONTAINERS,
        timeout_s,
    )


# T-DOC78 (fix round 3): the round-1 Critical bug was two independent derivations of this same
# path (app/ingest.py's own _pass1_lock_path, app/assembly.py's hardcoded ".pass1.lock" literal)
# silently drifting apart. One shared helper, used by every caller (app/ingest.py holds it for
# Pass 1's duration; app/assembly.py's build_mcp_server and app/dashboard/controller.py's
# load_for_mcp both check it before reloading TEI) -- both already import this module, so no
# circular-import risk.
_PASS1_LOCK_NAME = ".pass1.lock"


def pass1_lock_path(db_path: str) -> Path:
    """The `.pass1.lock` path for a given corpus's db_path -- shared by app/ingest.py (which holds
    it for Pass 1's exact duration), app/assembly.py's build_mcp_server (the query path's
    self-healing hook), and app/dashboard/controller.py's load_for_mcp (this same guard). Always
    derive from the EFFECTIVE db_path (already resolved by the caller), never a raw Config field
    directly -- see the T-DOC78 round-1 fix history in this repo for why that distinction matters."""
    return Path(db_path).resolve().parent / _PASS1_LOCK_NAME


def pass1_is_active(lock_path: Path) -> bool:
    """Non-blocking check: True iff `app.ingest` currently holds the Pass-1 lock at `lock_path`
    (`app.ingest._pass1_lock_path`) -- i.e. Pass 1's parser is actively running right now. A zero-timeout
    acquire attempt: succeeds (and is immediately released) when Pass 1 is NOT running, times out
    when it is. Best-effort like every other function in this module: a missing lock FILE (no
    ingest has ever run yet) is treated as "not active" -- the lock can still be acquired -- never
    an error.

    T-DOC78: this sits directly in a live query's call path (via `ensure_tei_running`), so an
    unhandled exception here would crash a real search, not just fail best-effort like the rest of
    this module. `OSError` (e.g. `PermissionError` on an unwritable/unreadable lock directory) is
    caught alongside `filelock.Timeout` -- but unlike every other "can't tell, so proceed anyway"
    case in this module, this is a SAFETY guard: when the probe itself can't be trusted, fail SAFE
    (assume Pass 1 might be active, refuse to reload) rather than fail open. Only the `OSError`
    branch logs -- `filelock.Timeout` (Pass 1 genuinely, routinely active) is the expected common
    case on a real query hot path and would spam the log every query during every Pass 1; an
    `OSError` (a broken/unwritable lock dir) is not routine and would otherwise silently disable
    query-path self-healing forever with zero operator-visible signal."""
    lock = filelock.FileLock(str(lock_path))
    try:
        lock.acquire(timeout=0)
    except filelock.Timeout:
        return True
    except OSError as error:
        logger.warning(
            "could not determine whether Pass 1 is active via lock %s -- conservatively skipping "
            "TEI self-heal (failing safe) rather than risking a reload mid-Pass-1: %s",
            lock_path,
            error,
        )
        return True
    lock.release()
    return False


def ensure_tei_running(
    client: httpx.Client | None = None, *,
    lock_path: Path | None = None, poll_timeout_s: float | None = None,
) -> None:
    """Best-effort, never raises (same contract as `stop_tei_containers`/`start_tei_containers`).
    If both containers are ALREADY healthy, this is two fast `GET /health` calls and nothing else
    -- no `docker` command. Otherwise falls through to `start_tei_containers` (docker start + the
    same bounded health poll that function already does).

    `client` is injectable for tests, same as `start_tei_containers`. When `None`, builds one
    short-lived `httpx.Client` and reuses it for both the health check here and (if needed) the
    poll inside `start_tei_containers`, rather than constructing two.

    T-DOC78: `lock_path` (default `None` -- existing callers unaffected), when given, is checked
    FIRST via `pass1_is_active` -- if Pass 1 is actively running, this returns immediately WITHOUT
    reloading TEI, even if unhealthy: reloading ~9.4GB mid-Pass-1 risks the exact CUDA OOM TEI
    eviction exists to prevent (ARCHITECTURE.md/CONVENTIONS.md Sec 6 -- Pass 1's real safety margin
    against the parse phase's peak VRAM usage is ~1GB). The caller's subsequent real HTTP call fails exactly as
    documented ("a live MCP query during Pass 1 fails outright, not delayed") instead of silently
    reintroducing the OOM risk.

    `poll_timeout_s` (default `None` -- falls back to `start_tei_containers`'s own
    `_TEI_START_POLL_TIMEOUT_SECONDS`): overrides the health-poll deadline forwarded to
    `start_tei_containers` on the fallthrough path -- the query path uses a much shorter one (see
    `app/assembly.py::build_mcp_server`) so a query with TEI genuinely unreachable fails in seconds,
    not up to a full minute; phase-transition callers (Pass 2's own explicit `start_tei_containers()`
    call) keep the original, more patient default by never passing this."""
    if lock_path is not None and pass1_is_active(lock_path):
        return

    if client is None:
        client = httpx.Client(timeout=5.0)

    urls = (_TEI_EMBED_HEALTH_URL, _TEI_RERANK_HEALTH_URL)
    if all(_is_healthy(client, url) for url in urls):
        return

    start_tei_containers(client=client, poll_timeout_s=poll_timeout_s)


def _is_healthy(client: httpx.Client, url: str) -> bool:
    try:
        return client.get(url).is_success
    except httpx.HTTPError:
        return False
