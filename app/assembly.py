"""Composition roots: wires real (non-fake) adapters into `IngestionOrchestrator` (M9) and
`McpServer` (M8) — the two places ARCHITECTURE.md's "Operational invariants" §3 says a real
`GpuLock` must be shared across process boundaries.

# ponytail: service endpoints/model ids are constants here, not `Config` fields — they don't vary
# yet (one dev workstation, one model per seam). Promote to `Config` if a second environment or
# model choice ever needs to differ.
"""

import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import httpx

from app import tei_lifecycle
from app.adaptive_batch_sizer import AdaptiveBatchSizer
from contracts.config import Config
from contracts.embedder import EmbedderInfo
from contracts.errors import PermanentError, TransientError
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from rag.chunker import Chunker
from rag.document_store import DocumentStore
from rag.embedder import TeiEmbedder
from rag.gpu_lock import FileGpuLock
from rag.harvester import ArxivSource, Harvester, QuarantineSink
from rag.ingest_state_sqlite import SqliteIngestState
from rag.mcp_server import McpServer
from rag.orchestrator import IngestionOrchestrator
from rag.parser import parse as parse_pdf_bytes
from rag.parser import parse_batch as parse_pdf_bytes_batch
from rag.reranker import TeiReranker
from rag.retriever import Retriever
from rag.summarizer import OllamaSummarizer
from rag.vector_index import VectorIndex

logger = logging.getLogger(__name__)

_TEI_EMBED_URL = "http://localhost:8080"
_TEI_RERANK_URL = "http://localhost:8082"  # serves BGE-reranker-v2-m3 -- fixed server-side, TEI's
# /rerank endpoint takes no model param per request, so there's nothing to pass TeiReranker here.
_OLLAMA_URL = "http://localhost:11434"
# Must stay tag-qualified ("qwen3:14b", not "qwen3"): OllamaSummarizer.unload()'s /api/ps
# eviction check matches this string exactly against Ollama's loaded-model list -- an untagged
# name would silently defeat eviction confirmation.
_OLLAMA_MODEL = "qwen3:14b"
_EMBEDDER_INFO = EmbedderInfo(model_id="Qwen3-Embedding-4B", dim=2560, version="v1")
_QDRANT_HOST = "localhost"
_QDRANT_PORT = 6333
# `IngestionOrchestrator.parse_phase` calls `parser.parse(ref)` once per paper, sequentially, for
# the whole ~100-120 paper corpus -- with no delay this is a tight loop of GETs against arXiv,
# a real risk of tripping their rate limiting (429s, which this class already maps to
# PermanentError -> a quarantined paper, shrinking the corpus for no good reason). arXiv's
# published API guidance is "no more than one request every 3 seconds" (see
# rag/harvester.py's own _RATE_LIMIT_SECONDS for that same number, applied to the search API);
# this is direct PDF fetching, not the query API, so half that is a defensible, simpler bound --
# enough spacing to avoid 429s without meaningfully slowing the parse phase.
_PDF_DOWNLOAD_DELAY_SECONDS = 1.5
# One-time backoff before the single retry below -- deliberately not the harvester's
# retry_counts/max_retries/exponential-backoff machinery (rag/harvester.py's `Harvester`): that's
# sized for a paginated 15k-paper search stream, not a single-file download with one bounded
# retry. A second constant, not reused, because it answers a different question (how long to
# wait before re-attempting) than the inter-request delay above (how long to wait after
# resolving, before the next paper).
_PDF_DOWNLOAD_RETRY_BACKOFF_SECONDS = 2.0
# Statuses worth one retry -- rate-limited or a transient server-side hiccup. Not 404/permanent
# statuses (CONVENTIONS.md §4: those are `PermanentError`, no retry).
_RETRYABLE_STATUSES = {429, 502, 503, 504}


def harvest_refs(config: Config, orchestrator: IngestionOrchestrator) -> list[PaperRef]:
    """`config.ingest_paper_ids` (optional list of base arXiv ids, T-EVAL harvest-scoping
    override, PR #89): fetch exactly these known papers via `ArxivSource.fetch_by_ids()` instead
    of the query-driven `harvest()` below -- guarantees the 210-question eval set's 100 source
    papers are actually in the corpus (a focus_area search can't guarantee hitting them). `None`
    (the default) leaves normal `harvest()` behavior completely unchanged.

    Shared by `app/ingest.py` (Pass 2) and `app/parse_phase.py` (Pass 1, run as a subprocess) so
    both phases of one run agree on the same explicit paper set by construction -- one function,
    not two copies a docstring asks someone to "keep in sync" (T-DOC29).
    """
    if config.ingest_paper_ids:
        return ArxivSource().fetch_by_ids(config.ingest_paper_ids)
    return orchestrator.harvest(config.focus_area_queries, config.corpus_cap)


class _PdfDownloadParser:
    """Bridges `IngestionOrchestrator`'s `parser.parse(ref: PaperRef)` call to the real Parser
    module's frozen `parse(raw: bytes) -> ParsedDoc` interface — the Orchestrator hands a
    `PaperRef`, the real Parser wants PDF bytes. Lives here, not in `rag/parser.py`: downloading
    is composition-root wiring, not part of the Parser module's own contract.

    `sleep` is constructor-injectable (default `time.sleep`), same pattern as
    `rag.harvester.ArxivSource`, so a unit test can assert the delay/backoff fire without a real
    sleep.

    A transient download failure (429/502/503/504, a timeout, or a transport error --
    CONVENTIONS.md §4) gets exactly one retry after a short backoff, then `PermanentError` if it
    fails again. A genuinely permanent failure (404, or whatever `rag.parser.parse` raises for an
    unparseable PDF) is not retried.

    `cache_dir` (T-DOC18, giggly-tumbling-globe.md Part 0 Layer 1): the standalone prefetcher
    (`app/prefetch_pdfs.py`) fills `config.pdf_cache_dir/<paper_id>.pdf` continuously, off the GPU
    critical path, but this class never read it -- every ref did a live HTTP GET regardless of
    whether the prefetcher already had it. If `cache_dir` is given, `_download` checks
    `cache_dir / f"{paper_id}.pdf"` first (same naming convention as `prefetch_pdfs._pdf_path`)
    and returns its bytes with zero HTTP call on a hit; on a miss it falls back to the unchanged
    live-download path below and then writes the result to the same path (atomically -- write to
    a per-process-unique `.tmp` sibling and rename, see `_write_cache`) so the live pipeline also
    grows the cache instead of only ever reading it. `cache_dir=None` skips the cache check
    entirely; `build_ingestion_orchestrator` only ever passes `None` if `config.pdf_cache_dir` is
    explicitly set to an empty value (T-DOC29: a real `Config` field now, not an env var) -- an
    unset/default value resolves to the SAME `"pdf_cache"` directory `app/prefetch_pdfs.py`
    defaults to (T-DOC18 bug fix: these two defaults used to disagree, silently disabling the
    cache; now structurally impossible to drift since both read the one Config field).

    Single-lookahead prefetch (T-DOC18 Layer 2): `parse_batch()`'s own download prefix used to be
    a solid block of GPU-idle time in front of every batch's `parse_pdf_bytes_batch()` (MinerU)
    call, and batch N+1's downloads never started until batch N's GPU call fully finished.
    `prefetch_next_batch(refs)` lets a caller that already knows the *next* batch's refs (see
    `rag/orchestrator.py`'s `parse_phase`/`_prepare_batch`) hand them over just before calling
    `parse_batch()` for the *current* batch -- a single background thread
    (`ThreadPoolExecutor(max_workers=1)`) starts resolving those bytes immediately, so they're
    downloading while the current batch's `parse_pdf_bytes_batch()` call is blocking the main
    thread on the GPU. The next `parse_batch()` call picks up the prefetched bytes (blocking only
    if the download genuinely hasn't finished yet) instead of downloading again. Deliberately
    bounded to one batch of lookahead, matching the plan's memory-pressure ceiling (roughly
    doubles, not unbounds, the "N raw PDFs in memory at once" peak) -- not the per-paper
    cross-*stage* prefetch thread the orchestrator's own module docstring says was removed for a
    real CUDA OOM; this prefetch only ever does CPU/network work (HTTP downloads), never touches a
    GPU model or `state`, so it doesn't reintroduce that risk. The prefetch's own downloads go
    through `_download` above, so a hit against `cache_dir` short-circuits it exactly the same way
    it short-circuits a foreground call -- the two pieces compose without either needing to know
    about the other.
    """

    def __init__(
        self,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
        cache_dir: Path | None = None,
    ):
        self._client = client
        self._sleep = sleep
        self._cache_dir = cache_dir
        self._executor = ThreadPoolExecutor(max_workers=1)
        # Set by `prefetch_next_batch()`, consumed (and cleared) by the next matching
        # `parse_batch()` call. Keyed by paper_id tuple, not the `PaperRef` objects themselves,
        # so a match is a simple equality check. Only ever read/written from the main thread --
        # the background thread only ever touches its own `_download_all` call, never this
        # attribute -- so no lock is needed.
        self._prefetched: tuple[tuple[str, ...], "Future[list[bytes]]"] | None = None

    def parse(self, ref: PaperRef) -> ParsedDoc:
        cache_hit = False
        try:
            content, cache_hit = self._download(ref)
        finally:
            # Fires exactly once per `parse()` call -- success or final failure -- once the
            # retry below (if any) has resolved, so it stays a once-per-paper spacing rather
            # than stacking with the retry backoff. Skipped on a cache hit: there was no real
            # HTTP request to pace, so pacing it anyway is pure idle time that undercuts the
            # whole point of the cache (T-DOC18). `cache_hit` defaults to False so a `_download`
            # exception (never a cache hit -- see `_download`) still sleeps, unchanged.
            if not cache_hit:
                self._sleep(_PDF_DOWNLOAD_DELAY_SECONDS)
        return parse_pdf_bytes(content)

    def parse_batch(self, refs: list[PaperRef]) -> list[ParsedDoc]:
        """Bridges `IngestionOrchestrator.parse_phase`'s batched `parser.parse_batch(refs)` call
        (T-DOC16) to the real Parser module's `parse_batch(raws: list[bytes]) -> list[ParsedDoc]`
        the same way `parse()` bridges to `parse()` above -- download every ref's PDF first (same
        per-request delay/one-retry-then-`PermanentError` policy as `_download`, applied to each
        ref in turn), then hand the whole batch of bytes to MinerU in one `do_parse` call.

        A download failure for ANY ref raises `PermanentError` here before `parse_pdf_bytes_batch`
        is even called -- consistent with `rag/parser.py`'s own whole-batch-fails contract, and
        exactly what `parse_phase`'s fallback (per-ref `_parse_with_retry`) expects: nothing in
        this batch was checkpointed, so re-attempting every ref individually is safe.

        If `prefetch_next_batch()` was already called for exactly these refs (the normal case once
        the lookahead is warmed up -- see the class docstring), this reuses that in-flight/finished
        download instead of starting a new one.
        """
        contents = self._resolve_contents(refs)
        return parse_pdf_bytes_batch(contents)

    def prefetch_next_batch(self, refs: list[PaperRef]) -> None:
        """Start resolving `refs`' PDF bytes on a background thread now, so they're ready by the
        time a later `parse_batch(refs)` call for this exact ref list needs them. Call this just
        before `parse_batch()` for the *current* batch, passing the *next* batch's refs -- see the
        class docstring. Non-blocking: returns as soon as the download is queued, not once it
        finishes.

        A no-op if `refs` is empty (nothing to prefetch -- e.g. the last batch of a run) or if an
        identical prefetch is already in flight/done (no double-submission on repeated calls with
        the same refs).
        """
        if not refs:
            return
        key = tuple(ref.paper_id for ref in refs)
        if self._prefetched is not None and self._prefetched[0] == key:
            return
        self._prefetched = (key, self._executor.submit(self._download_all, refs))

    def _resolve_contents(self, refs: list[PaperRef]) -> list[bytes]:
        key = tuple(ref.paper_id for ref in refs)
        if self._prefetched is not None and self._prefetched[0] == key:
            _, future = self._prefetched
            self._prefetched = None
            return future.result()
        return self._download_all(refs)

    def _download_all(self, refs: list[PaperRef]) -> list[bytes]:
        contents = []
        for ref in refs:
            cache_hit = False
            try:
                content, cache_hit = self._download(ref)
                contents.append(content)
            finally:
                # See `parse()`'s matching comment -- a cache hit made no real HTTP request, so
                # there's nothing to rate-limit-pace (T-DOC18).
                if not cache_hit:
                    self._sleep(_PDF_DOWNLOAD_DELAY_SECONDS)
        return contents

    def _download(self, ref: PaperRef) -> tuple[bytes, bool]:
        """Returns `(content, was_cache_hit)`. `was_cache_hit` is only ever `True` when
        `_read_cached` returned bytes with zero HTTP calls -- callers use it to skip the
        rate-limit-pacing sleep, which exists to pace real arXiv requests and has nothing to pace
        on a cache hit (T-DOC18)."""
        cached = self._read_cached(ref)
        if cached is not None:
            return cached, True
        try:
            content = self._download_once(ref)
        except TransientError:
            self._sleep(_PDF_DOWNLOAD_RETRY_BACKOFF_SECONDS)
            try:
                content = self._download_once(ref)
            except TransientError as retry_error:
                raise PermanentError(
                    f"failed to download PDF from {ref.pdf_url} after retry: {retry_error}"
                ) from retry_error
        self._write_cache(ref, content)
        return content, False

    def _cache_path(self, ref: PaperRef) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"{ref.paper_id}.pdf"

    def _read_cached(self, ref: PaperRef) -> bytes | None:
        path = self._cache_path(ref)
        if path is not None and path.exists():
            return path.read_bytes()
        return None

    def _write_cache(self, ref: PaperRef, content: bytes) -> None:
        path = self._cache_path(ref)
        if path is None:
            return
        # Atomic write -- tmp-then-rename, same convention as `prefetch_pdfs._download_one` --
        # so a crash mid-write never leaves a partial `.pdf` that a later cache-hit check would
        # mistake for complete. Unlike `prefetch_pdfs._download_one`'s fixed `<paper_id>.pdf.tmp`
        # name, this tmp path includes this process's pid: the 24/7 standalone prefetcher and
        # this live pipeline are structurally likely to grab the same newest paper_id around the
        # same time, and two processes writing the SAME tmp path can interleave into one
        # corrupted file that then gets renamed into place as a permanently-poisoned "valid"
        # cache entry (T-DOC18 bug -- sticky corruption, invisible to `exists()`). A pid-qualified
        # name can never collide with `prefetch_pdfs`'s tmp name (different pattern entirely) or
        # with another process's pid, so whichever process's atomic rename() lands last simply
        # leaves one complete, valid file.
        tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp_path.write_bytes(content)
        tmp_path.rename(path)

    def _download_once(self, ref: PaperRef) -> bytes:
        try:
            resp = self._client.get(ref.pdf_url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in _RETRYABLE_STATUSES:
                raise TransientError(f"failed to download PDF from {ref.pdf_url}: {e}") from e
            raise PermanentError(f"failed to download PDF from {ref.pdf_url}: {e}") from e
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise TransientError(f"failed to download PDF from {ref.pdf_url}: {e}") from e
        except httpx.HTTPError as e:
            raise PermanentError(f"failed to download PDF from {ref.pdf_url}: {e}") from e
        return resp.content


def _sqlite_harvest_quarantine_sink(state: SqliteIngestState) -> QuarantineSink:
    """Adapts `Harvester`'s `QuarantineSink` (`rag/harvester.py`: `Callable[[str, Exception],
    None]`) to `SqliteIngestState.quarantine`'s `(paper_id, stage, error)` shape, so a
    harvest-level failure lands in the same `quarantine` SQL table `IngestionOrchestrator` already
    uses for parse/summarize failures (rag/orchestrator.py's `self._state.quarantine(paper_id,
    "parsed"/"summarized", error)` calls) -- previously `Harvester` was constructed below with no
    `quarantine=` kwarg, silently defaulting to a no-op, so an exhausted-retry-budget harvest
    failure (rag/harvester.py's documented `"<unknown>"` bucket for a page-level API failure with
    no paper identity) left no DB row and no log line anywhere (T-DOC10).

    `Harvester.harvest()`'s postcondition is that it never raises, which means this sink must
    never raise either: unlike a real per-paper `paper_id`, `"<unknown>"` is a fixed sentinel, so
    a second harvest-level failure written to the same db would hit `quarantine.paper_id`'s
    PRIMARY KEY. Caught and logged rather than propagated, so a write failure degrades to
    log-only visibility instead of crashing the run.
    """

    def _sink(paper_id: str, error: Exception) -> None:
        try:
            state.quarantine(paper_id, "harvested", error)
        except Exception:
            logger.exception(
                "harvest-level quarantine (paper_id=%r, error=%s) could not be written to the "
                "quarantine table", paper_id, error,
            )

    return _sink


def build_ingestion_orchestrator(
    config: Config, *, db_path: str | None = None, blob_dir: str | None = None,
    collection: str = "papers",
) -> IngestionOrchestrator:
    gpu_lock = FileGpuLock(Path(config.gpu_lock_path))
    db_path = db_path or "papers.db"
    blob_dir = blob_dir or "blobs"

    state = SqliteIngestState(db_path)
    harvester = Harvester(ArxivSource(), quarantine=_sqlite_harvest_quarantine_sink(state))
    # Same Config field (T-DOC29: `config.pdf_cache_dir`, one default declared once in
    # contracts/config.py) app/prefetch_pdfs.py also reads -- both processes agree on the same
    # `./pdf_cache` default by construction now, closing off the T-DOC18 bug this used to guard
    # against by convention (two independently-guessed env-var-with-fallback reads that could
    # silently drift apart). `pdf_cache_dir` only ends up `None` here if config.yaml
    # explicitly sets `pdf_cache_dir: ""` -- logged below so a genuinely-disabled cache is visible,
    # not silent. mkdir here (not inside _PdfDownloadParser) because only the composition root
    # knows whether this run is even configured to use a cache at all.
    pdf_cache_dir = Path(config.pdf_cache_dir) if config.pdf_cache_dir else None
    if pdf_cache_dir is not None:
        pdf_cache_dir.mkdir(parents=True, exist_ok=True)
    else:
        logger.warning(
            "config.pdf_cache_dir is set to an empty value -- the PDF cache (T-DOC18 Layer 1) is "
            "disabled for this run: every download will be a live HTTP call with no "
            "write-through cache."
        )
    parser = _PdfDownloadParser(httpx.Client(timeout=60.0), cache_dir=pdf_cache_dir)
    chunker = Chunker(config)
    summarizer = OllamaSummarizer(
        httpx.Client(base_url=_OLLAMA_URL, timeout=300.0), gpu_lock, _OLLAMA_MODEL
    )
    embedder = TeiEmbedder(httpx.Client(base_url=_TEI_EMBED_URL, timeout=60.0), gpu_lock, _EMBEDDER_INFO)
    document_store = DocumentStore(db_path, blob_dir)
    vector_index = VectorIndex(
        _QDRANT_HOST, _QDRANT_PORT, collection, _EMBEDDER_INFO.dim, config.hybrid_dense_weight
    )

    def _before_parse_phase() -> None:
        # Composed because the `before_parse_phase` hook slot is a single callable, not a list
        # (rag/orchestrator.py). Both evictions free VRAM MinerU needs during Pass 1 -- see
        # rag/orchestrator.py's module docstring, ARCHITECTURE.md §3, and app/tei_lifecycle.py.
        summarizer.unload()
        tei_lifecycle.stop_tei_containers()

    return IngestionOrchestrator(
        harvester, parser, chunker, summarizer, embedder, document_store, vector_index,
        state, gpu_lock, config,
        # Evict the Summarizer, and stop the TEI Embedder/Reranker containers, before Pass 1
        # (MinerU needs the VRAM both hold). This hook does NOT reload MinerU's own VRAM: Pass 1
        # runs in a separate subprocess (`app/parse_phase.py`), so that process's own exit is what
        # releases MinerU's VRAM before Pass 2 -- verified empirically that clearing MinerU's
        # in-process model caches only partially frees memory (PaddlePaddle-backed OCR/table
        # sub-models don't release via torch.cuda.empty_cache()), so subprocess isolation is the
        # real mechanism for that, not an in-process unload callback.
        before_parse_phase=_before_parse_phase,
        # No `before_finish_phase` wiring for TEI here (T-DOC19 fix): `finish_phase()` embeds its
        # once-per-run `topic_query_vec` BEFORE this hook fires (rag/orchestrator.py, frozen), so
        # wiring the TEI restart to this hook restarts it too late -- the embed call already needs
        # a live TEI. `app/ingest.py`'s `_run_finish_phase` instead calls
        # `tei_lifecycle.start_tei_containers()` explicitly, before `finish_phase()` is invoked at
        # all, so TEI is confirmed up (or the best-effort timeout has already elapsed) beforehand.
        # Evict the Summarizer again before *each paper's* embed step, not just once before Pass
        # 1 -- found necessary 2026-07-13: within Pass 2, the Summarizer stays fully GPU-resident
        # (real measured ~11.5GB for a long paper) for the whole time the Embedder is working,
        # though nothing needs it loaded then. On a real long paper this left too little headroom
        # and the Embedder hit a real CUDA OOM (ruled out batch size and individual chunk length
        # first via direct measurement -- see .phase0-data/known-issue-pass2-oom.md). Real reload
        # cost for the next paper's summarize call: ~2.5s, negligible against a ~15-20s real
        # summarize call.
        before_embed=summarizer.unload,
        # T-DOC21 (.claude/plans/giggly-tumbling-globe.md): grow/shrink Pass-1 batches to real,
        # currently-free VRAM instead of the static parse_batch_size every time -- TEI eviction
        # above frees ~24GB during Pass 1 that a fixed small batch size never used. `initial_size`
        # is still config.parse_batch_size -- the safe starting point/floor, unchanged if the VRAM
        # probe is ever unavailable.
        batch_size_provider=AdaptiveBatchSizer(
            initial_size=config.parse_batch_size,
            # Unset (the default) writes no file, matching AdaptiveBatchSizer's own
            # decision_log_path=None default -- this is investigation tooling for a specific
            # run (the user's "keep a close log of it to investigate later" request), not a
            # default-on feature. Set config.batch_size_log_path to a path to capture one CSV row
            # per batch-size decision for that run.
            decision_log_path=config.batch_size_log_path,
        ).next_size,
    )


def build_mcp_server(
    config: Config, *, db_path: str | None = None, blob_dir: str | None = None,
    collection: str = "papers",
) -> McpServer:
    gpu_lock = FileGpuLock(Path(config.gpu_lock_path))  # same path as the ingest root -> same file
    db_path = db_path or "papers.db"
    blob_dir = blob_dir or "blobs"

    embedder = TeiEmbedder(httpx.Client(base_url=_TEI_EMBED_URL, timeout=60.0), gpu_lock, _EMBEDDER_INFO)
    document_store = DocumentStore(db_path, blob_dir)
    vector_index = VectorIndex(
        _QDRANT_HOST, _QDRANT_PORT, collection, _EMBEDDER_INFO.dim, config.hybrid_dense_weight
    )
    reranker = TeiReranker(httpx.Client(base_url=_TEI_RERANK_URL, timeout=60.0), gpu_lock)
    retriever = Retriever(embedder, vector_index, document_store, reranker)

    return McpServer(retriever, document_store)
