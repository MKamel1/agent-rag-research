"""`python -m app.prefetch_pdfs` — standalone, GPU-free PDF backlog builder.

**Why this exists:** the real ingest pipeline (`app/ingest.py`/`app/parse_phase.py`) fuses PDF
download and MinerU parsing into one GPU-bound step (`app/assembly.py`'s `_PdfDownloadParser`),
so its download rate is whatever MinerU's own (currently ~44% GPU-utilized) pace happens to be.
This script downloads PDFs on their own, continuously, with no MinerU/GPU involvement, building a
local `<paper_id>.pdf` cache the future MinerU-batching fix can read from later. It does not parse,
chunk, summarize, or embed anything, and never touches `blobs/` (the real pipeline's own store).

**Coordinating with the live pipeline instead of duplicating its traffic (the actual design
problem here):**

1. *Dedup.* Both processes independently harvest from the SAME `focus_area_queries` +
   `freshest_first` ordering (DATA-CONTRACTS.md §Config), so a naive second harvester would
   re-walk nearly the same paper list. Before downloading paper X, this script checks the SHARED
   `ingest_state` table (`rag/ingest_state_sqlite.py`'s `SqliteIngestState`, same real `papers.db`
   the live run writes) via `all_known_paper_ids()` — a single bulk, **read-only** `SELECT`. Any
   paper_id with an existing row (any stage) means the live pipeline already has it, so this
   script skips it.

   **This module never writes to the shared `papers.db` — no `state.checkpoint()`, no
   `state.quarantine()` call anywhere in this file.** An earlier version did (checkpointing its
   own downloads at a repurposed `"harvested"` stage), and design review (see PR discussion)
   found that unsafe: `SqliteIngestState.checkpoint()`/`quarantine()` are non-atomic
   read-merge-write/delete operations, and the adapter's `threading.Lock` only serializes calls
   *within one process* — it does nothing across the two-OS-process boundary a second writer
   introduces. A stale-snapshot write from this script could race the live pipeline's own write
   on the same paper_id and blind-downgrade or delete a row the live pipeline had already
   advanced past (e.g. resetting a `"done"` paper back to `"harvested"` and destroying its
   `ingest_checkpoint` artifacts) — which `IngestionOrchestrator._finish_checkpoint` is not
   guarded against and would crash the live multi-day run trying to re-summarize a suddenly-`None`
   `parsed`/`chunks`. Removing the write closes that risk by construction instead of narrowing it:
   this script's OWN progress and dedup are tracked entirely on disk — the `.pdf` cache file
   itself (durable, resumable — see `run()`) plus a `.pdf.skip` marker for a paper_id this
   script's own retries gave up on (see `_download_with_retry`). Nothing the live pipeline reads
   is ever touched.

2. *Second-harvest request-budget risk.* Calling `ArxivSource.fetch()` (export.arxiv.org's search
   API) is a REAL, separate cost against arXiv's documented "no more than one request every three
   seconds... single connection at a time" (arXiv API Terms of Use), independent of whether the
   results get deduped afterward — every page fetched is a request regardless of what happens to
   the response. Each individual harvest call stays within that budget (paced at the mandated 3s
   cadence `rag/harvester.py`'s `ArxivSource` already enforces, ~15 minutes for a 30k-paper
   harvest at 100/page) — but `main()` below re-harvests roughly every
   `_RE_HARVEST_INTERVAL_SECONDS` for as long as the corpus is below target, which over a
   multi-day run is dozens of full harvests in total, not the live pipeline's own
   one-or-two-per-run shape. Being honest about that instead
   of downplaying it: this is more cumulative search-API traffic than the live pipeline generates,
   even though no single call ever exceeds the documented rate. An immediate re-harvest would just
   re-fetch an unchanged result (arXiv's corpus doesn't change second-to-second), so the interval
   exists to bound that total, not to hide it — if this cadence ever needs to be lower-traffic
   still, raising `_RE_HARVEST_INTERVAL_SECONDS` is the knob. `ArxivSource`'s own retry/backoff on
   429/5xx is inherited unchanged (this script doesn't duplicate that logic) — real, automatic
   protection if two concurrent harvests DO land close enough together to trip a transient
   rate-limit response.

3. *PDF download pacing.* The live pipeline's `_PdfDownloadParser.parse()` (app/assembly.py) has
   **no explicit delay of its own** — verified by reading it, not assumed; its real-world pace is
   whatever MinerU's per-paper GPU time happens to impose. This script has no such natural pacing
   (no GPU step to wait on), so it needs an explicit one, chosen conservatively rather than
   guessed: arXiv's own `robots.txt` (https://arxiv.org/robots.txt) sets `Crawl-delay: 15` for the
   default user-agent class (this script isn't one of the explicitly special-cased crawlers like
   Googlebot) — the one authoritative, documented number available for arxiv.org's PDF-serving
   traffic specifically (a different host/policy than export.arxiv.org's 3-second search-API
   figure). `_PDF_DOWNLOAD_DELAY_SECONDS` uses that number, and `_download_with_retry`'s backoff
   is floored at it too — a 429/5xx retry never sleeps LESS than the routine pacing, so a real
   rate-limit signal from arXiv can never make this script hit it MORE often. This script's own
   worst-case contribution to combined PDF-endpoint load is capped at one request per 15 seconds,
   independent of the live pipeline's cadence.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from contracts.config import Config
from contracts.errors import PermanentError, TransientError
from contracts.harvester import PaperRef
from rag.config import load_config
from rag.harvester import ArxivSource, Harvester
from rag.ingest_state_sqlite import SqliteIngestState

# See module docstring point 3 — arXiv robots.txt's documented default Crawl-delay.
_PDF_DOWNLOAD_DELAY_SECONDS = 15.0

# See module docstring point 2 — only re-harvest after a real amount of wall-clock time, since an
# immediate re-harvest would just re-fetch arXiv's unchanged corpus for no new information.
_RE_HARVEST_INTERVAL_SECONDS = 3600.0

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_DOWNLOAD_RETRIES = 3


def _cache_dir_from_config(cfg: Config) -> Path:
    # T-DOC29: `cfg.pdf_cache_dir`'s default ("pdf_cache") is declared once in
    # contracts/config.py -- app/assembly.py's build_ingestion_orchestrator reads the SAME Config
    # field, so an ingestion run launched with an unedited config.yaml agrees on the same
    # directory by construction (previously two independently-guessed env-var-with-fallback
    # reads, the T-DOC18 bug this replaced).
    d = Path(cfg.pdf_cache_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _target_from_config(cfg: Config) -> int:
    return cfg.prefetch_target


def _pdf_path(cache_dir: Path, paper_id: str) -> Path:
    return cache_dir / f"{paper_id}.pdf"


def _skip_marker_path(cache_dir: Path, paper_id: str) -> Path:
    # This script's OWN dead-letter for a paper_id its own retries gave up on — local, on-disk,
    # never the shared `quarantine` table (see module docstring point 1).
    return cache_dir / f"{paper_id}.pdf.skip"


def _cached_count(cache_dir: Path) -> int:
    # Monotonic, resumable progress counter: a file placed here stays here regardless of what the
    # live pipeline later does with that paper_id (this script never touches shared state, so
    # there is nothing for the live pipeline's own progress to shadow or invalidate).
    return sum(1 for _ in cache_dir.glob("*.pdf"))


def _download_one(client: httpx.Client, ref: PaperRef, cache_dir: Path) -> None:
    """Fetch `ref`'s PDF bytes and write them atomically to `cache_dir/<paper_id>.pdf`.

    Postcondition on success: the final `.pdf` path exists and is complete — writes to a `.tmp`
    sibling first, then renames (atomic on the same filesystem), so a crash mid-download never
    leaves a partial file that `_cached_count`/the resume check would mistake for "done". Raises
    `TransientError` for a retryable failure (network error, 429/5xx — same taxonomy
    `rag/harvester.py`'s `ArxivSource` already uses) or `PermanentError` for anything else (e.g. a
    withdrawn paper's 404).
    """
    final_path = _pdf_path(cache_dir, ref.paper_id)
    tmp_path = cache_dir / f"{ref.paper_id}.pdf.tmp"
    try:
        resp = client.get(ref.pdf_url)
        resp.raise_for_status()
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in _RETRYABLE_STATUSES:
            raise TransientError(
                f"prefetch_pdfs: {ref.pdf_url} returned {status} paper_id={ref.paper_id!r}"
            ) from error
        raise PermanentError(
            f"prefetch_pdfs: {ref.pdf_url} returned {status} paper_id={ref.paper_id!r}"
        ) from error
    except httpx.HTTPError as error:
        raise TransientError(
            f"prefetch_pdfs: request failed for paper_id={ref.paper_id!r}: {error}"
        ) from error

    tmp_path.write_bytes(resp.content)
    tmp_path.rename(final_path)


def _download_with_retry(
    client: httpx.Client, ref: PaperRef, cache_dir: Path, sleep,
) -> bool:
    """Up to `_MAX_DOWNLOAD_RETRIES` retries on `TransientError`, exponential backoff floored at
    `_PDF_DOWNLOAD_DELAY_SECONDS` (see module docstring point 3 — a 429/5xx must never make this
    script hit arXiv more often than its routine pacing). A `PermanentError` writes a local
    `.pdf.skip` marker (this script's own dead-letter — never the shared `quarantine` table, see
    module docstring point 1) and returns `False`. Retries exhausted also returns `False` but
    leaves NO marker — this attempt had bad luck, not a permanent verdict, so a later pass retries
    it fresh."""
    attempt = 0
    while True:
        try:
            _download_one(client, ref, cache_dir)
            return True
        except PermanentError as error:
            _skip_marker_path(cache_dir, ref.paper_id).write_text(str(error))
            return False
        except TransientError:
            attempt += 1
            if attempt > _MAX_DOWNLOAD_RETRIES:
                return False
            sleep(max(_PDF_DOWNLOAD_DELAY_SECONDS, float(2**attempt)))


def run(
    cfg: Config,
    db_path: str,
    cache_dir: Path,
    target: int,
    *,
    harvester=None,
    client: httpx.Client | None = None,
    sleep=time.sleep,
) -> int:
    """One harvest-then-download pass. Returns how many NEW files this call downloaded.

    Reads the shared `papers.db` (`all_known_paper_ids()`) for cross-pipeline dedup but never
    writes to it — see module docstring point 1. `harvester`/`client` are injectable (default to
    the real `Harvester(ArxivSource())` / `httpx.Client`) so tests can run this against a stub
    harvester and an `httpx.MockTransport` instead of the real network — see
    `rag/test_prefetch_pdfs.py`.
    """
    state = SqliteIngestState(db_path)  # read-only here: only `all_known_paper_ids()` is called.
    harvester = harvester or Harvester(ArxivSource())
    owned_client = client is None
    client = client or httpx.Client(timeout=60.0)

    total_cached = _cached_count(cache_dir)
    if total_cached >= target:
        return 0

    handled = state.all_known_paper_ids()  # one bulk READ query, not one per paper_id
    harvest_cap = max(cfg.corpus_cap, target)
    refs = harvester.harvest(cfg.focus_area_queries, harvest_cap, cfg.ordering)

    new_downloads = 0
    first_request = True
    try:
        for ref in refs:
            if total_cached >= target:
                break
            if ref.paper_id in handled:
                continue  # live pipeline already has it — never re-downloaded, never re-checked
            if _pdf_path(cache_dir, ref.paper_id).exists():
                continue  # this script's own prior pass already has it
            if _skip_marker_path(cache_dir, ref.paper_id).exists():
                continue  # this script's own prior pass already gave up on it permanently

            if not first_request:
                sleep(_PDF_DOWNLOAD_DELAY_SECONDS)
            first_request = False

            if _download_with_retry(client, ref, cache_dir, sleep):
                new_downloads += 1
                total_cached += 1
    finally:
        if owned_client:
            client.close()

    return new_downloads


def main() -> None:
    cfg = load_config()
    db_path = cfg.db_path
    cache_dir = _cache_dir_from_config(cfg)
    target = _target_from_config(cfg)

    while _cached_count(cache_dir) < target:
        new = run(cfg, db_path, cache_dir, target)
        total = _cached_count(cache_dir)
        print(
            f"prefetch_pdfs: pass complete, +{new} this pass, {total}/{target} cached", flush=True
        )
        if total >= target:
            break
        print(
            f"prefetch_pdfs: below target, sleeping {_RE_HARVEST_INTERVAL_SECONDS:.0f}s "
            "before re-harvesting (avoids re-querying arXiv for an unchanged result set)",
            flush=True,
        )
        time.sleep(_RE_HARVEST_INTERVAL_SECONDS)

    print(f"prefetch_pdfs: target of {target} reached, exiting.", flush=True)


if __name__ == "__main__":
    main()
