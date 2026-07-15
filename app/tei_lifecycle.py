"""TEI (Text Embeddings Inference) container lifecycle — evict the Embedder+Reranker containers'
GPU memory during Pass 1 (parse, MinerU-bound) so MinerU can batch larger, then reload them before
Pass 2 (finish: summarize+embed+store) needs them (ARCHITECTURE.md §3's two-pass ingest).

This is process/container orchestration, not domain logic gated by `rag/`'s vendor-isolation scan
(CONVENTIONS.md §1) -- it belongs in `app/` alongside `app/ingest.py`/`app/parse_phase.py`, which
already shell out to run Pass 1 as its own subprocess. Uses stdlib `subprocess` (not the `docker`
SDK) to talk to the Docker CLI directly, matching that existing precedent -- no new vendor-isolation
rule is needed either way, since `app/` is outside `ci/checks/vendor_isolation.py`'s scanned scope
(`rag/`, `contracts/` only).

Same "issue lifecycle command -> poll a status endpoint until confirmed -> bounded timeout ->
best-effort continue" shape as `rag/summarizer.py`'s `OllamaSummarizer.unload()`: a failure here
isn't a reason to fail the caller's phase transition.
"""

import logging
import subprocess
import time

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


def start_tei_containers(client: httpx.Client | None = None) -> None:
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
    """
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

    urls = (_TEI_EMBED_HEALTH_URL, _TEI_RERANK_HEALTH_URL)
    deadline = time.monotonic() + _TEI_START_POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if all(_is_healthy(client, url) for url in urls):
            return
        time.sleep(_TEI_START_POLL_INTERVAL_SECONDS)

    logger.warning(
        "could not confirm TEI containers %s were healthy within %.1fs -- proceeding anyway "
        "(best-effort; caller's phase transition is not blocked)",
        _TEI_CONTAINERS,
        _TEI_START_POLL_TIMEOUT_SECONDS,
    )


def _is_healthy(client: httpx.Client, url: str) -> bool:
    try:
        return client.get(url).is_success
    except httpx.HTTPError:
        return False
