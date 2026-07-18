"""Unit tests for `app.assembly._PdfDownloadParser` (T-DOC4, T-DOC7) and the harvest-level
quarantine wiring (T-DOC10) — offline, no real network/GPU.

Covers the inter-request delay added to close the real-run risk of tripping arXiv's rate
limiting across ~100-120 sequential PDF downloads (see `_PDF_DOWNLOAD_DELAY_SECONDS` in
`app/assembly.py` for the reasoning), and the single bounded retry for a transient download
failure (429/502/503/504, timeout, transport error — CONVENTIONS.md §4) added in T-DOC7 so a
rate-limit burst quarantines a paper only after a retry, not on the first 429. Uses
`httpx.MockTransport` for the HTTP layer (same offline pattern as `rag/test_embedder.py`) and an
injected `sleep` hook that records its calls instead of really sleeping (same pattern as
`rag.harvester.ArxivSource`/its test suite).

Also covers T-DOC10: `build_ingestion_orchestrator` previously constructed `Harvester` with no
`quarantine=` kwarg, so a harvest-level failure (retry budget exhausted on repeated transient
`Source` errors) was a silent no-op -- see `_sqlite_harvest_quarantine_sink` in `app/assembly.py`.
"""

import logging
import os
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from app.assembly import (
    _METADATA_FETCH_BACKOFF_SECONDS,
    _METADATA_FETCH_MAX_RETRIES,
    _PDF_DOWNLOAD_DELAY_SECONDS,
    _PDF_DOWNLOAD_RETRY_BACKOFF_SECONDS,
    _RETRY_AFTER_MAX_SECONDS,
    _parse_retry_after,
    _PdfDownloadParser,
    _sqlite_harvest_quarantine_sink,
    build_ingestion_orchestrator,
    build_mcp_server,
    harvest_refs,
)
from contracts.config import Config
from contracts.errors import PermanentError, TransientError
from contracts.harvester import PaperRef


def _make_ref(paper_id: str = "2504.09999") -> PaperRef:
    return PaperRef(
        paper_id=paper_id,
        version="v1",
        title="A Paper",
        abstract="An abstract.",
        authors=["A. Author"],
        categories=["cs.LG"],
        published=date(2026, 1, 1),
        updated=date(2026, 1, 1),
        pdf_url=f"http://arxiv.local/pdf/{paper_id}",
    )


def _make_parser(
    monkeypatch, handler, sleeps: list[float], cache_dir=None,
) -> _PdfDownloadParser:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    # The real Parser (rag.parser.parse) needs an actual PDF/MinerU -- stub it so this test
    # exercises only the download+delay wiring, not the Parser module. Takes `paper_id` too
    # (T-DOC31) but this stub doesn't need it -- only `raw` flows into the assertions below.
    monkeypatch.setattr("app.assembly.parse_pdf_bytes", lambda raw, paper_id: raw)
    return _PdfDownloadParser(
        client, sleep=lambda seconds: sleeps.append(seconds), cache_dir=cache_dir
    )


def test_sleeps_the_fixed_delay_after_each_download(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-fake")

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)

    result_1 = parser.parse(_make_ref("2504.00001"))
    result_2 = parser.parse(_make_ref("2504.00002"))

    assert sleeps == [_PDF_DOWNLOAD_DELAY_SECONDS, _PDF_DOWNLOAD_DELAY_SECONDS], (
        "each download must be followed by the fixed inter-request delay"
    )
    assert result_1 == b"%PDF-fake"
    assert result_2 == b"%PDF-fake", "the downloaded bytes must actually reach parse_pdf_bytes"


def test_transient_failure_is_retried_once_then_quarantined(monkeypatch):
    """A 429 (or 502/503/504/timeout/transport error) is TransientError, not PermanentError --
    CONVENTIONS.md §4. Two 429s in a row exhaust the one retry, so this still ends in
    PermanentError (quarantine), but only after a real retry attempt."""

    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(429)

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)

    with pytest.raises(PermanentError):
        parser.parse(_make_ref())

    assert attempts["count"] == 2, "must retry exactly once before quarantining"
    assert sleeps == [_PDF_DOWNLOAD_RETRY_BACKOFF_SECONDS, _PDF_DOWNLOAD_DELAY_SECONDS], (
        "a retry-backoff sleep between the two attempts, then the inter-request delay once "
        "more on final failure"
    )


def test_transient_failure_recovers_on_retry(monkeypatch):
    """A single 429 followed by a 200 must succeed -- proves the retry actually recovers a
    transient failure instead of always eventually quarantining."""

    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, content=b"%PDF-recovered")

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)

    result = parser.parse(_make_ref())

    assert attempts["count"] == 2
    assert result == b"%PDF-recovered", "the retry's response bytes must reach parse_pdf_bytes"
    assert sleeps == [_PDF_DOWNLOAD_RETRY_BACKOFF_SECONDS, _PDF_DOWNLOAD_DELAY_SECONDS], (
        "one retry-backoff sleep between attempts, then the inter-request delay once on success"
    )


def test_permanent_failure_is_not_retried(monkeypatch):
    """A 404 is a genuinely permanent failure (CONVENTIONS.md §4) -- no retry, immediate
    quarantine, and only the inter-request delay (not a retry-backoff) fires."""

    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(404)

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)

    with pytest.raises(PermanentError):
        parser.parse(_make_ref())

    assert attempts["count"] == 1, "a 404 must not be retried"
    assert sleeps == [_PDF_DOWNLOAD_DELAY_SECONDS]


# ================================================================================================
# T-DOC18 Layer 2 — single-lookahead prefetch (`parse_batch` / `prefetch_next_batch`)
# ================================================================================================


def test_parse_batch_downloads_every_ref_and_returns_docs_in_order(monkeypatch):
    """No prefetch involved -- proves `parse_batch()`'s own baseline behavior (T-DOC16) is
    unchanged by the T-DOC18 refactor: every ref is downloaded, in order, and its bytes reach
    `parse_pdf_bytes_batch` positionally matched to its ref. Also proves T-DOC31: each ref's real
    `paper_id` reaches `parse_pdf_bytes_batch` too, positionally matched the same way."""

    def handler(request: httpx.Request) -> httpx.Response:
        paper_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=f"%PDF-{paper_id}".encode())

    calls: list[list[bytes]] = []
    id_calls: list[list[str]] = []

    def fake_parse_batch(contents: list[bytes], paper_ids: list[str]) -> list[str]:
        calls.append(contents)
        id_calls.append(paper_ids)
        return [c.decode() for c in contents]

    monkeypatch.setattr("app.assembly.parse_pdf_bytes_batch", fake_parse_batch)
    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)
    refs = [_make_ref("2504.00001"), _make_ref("2504.00002")]

    result = parser.parse_batch(refs)

    assert calls == [[b"%PDF-2504.00001", b"%PDF-2504.00002"]]
    assert id_calls == [["2504.00001", "2504.00002"]], (
        "each ref's real paper_id must reach parse_pdf_bytes_batch, in the same order as its bytes"
    )
    assert result == ["%PDF-2504.00001", "%PDF-2504.00002"]


def test_prefetch_next_batch_downloads_overlap_the_current_batchs_gpu_call(monkeypatch):
    """The one test that actually proves the overlap exists (not just 'the code doesn't crash'):
    a fake slow download for the *next* batch's refs, and a fake slow `parse_pdf_bytes_batch`
    (the GPU-bound call) for the *current* batch, both logging real wall-clock timestamps to a
    shared event list. Asserts the next batch's download work is genuinely in flight *during* the
    GPU call's active window, not merely kicked off before it and finished instantly."""

    events: list[tuple[str, float]] = []
    NEXT_REF_IDS = {"2504.10001", "2504.10002"}
    DOWNLOAD_SLEEP = 0.05  # per next-batch ref; two refs -> ~0.1s of background download work
    GPU_SLEEP = 0.3  # comfortably longer than the ~0.1s background download, to avoid flakiness

    def handler(request: httpx.Request) -> httpx.Response:
        paper_id = request.url.path.rsplit("/", 1)[-1]
        events.append((f"download_start:{paper_id}", time.monotonic()))
        if paper_id in NEXT_REF_IDS:
            time.sleep(DOWNLOAD_SLEEP)
        events.append((f"download_end:{paper_id}", time.monotonic()))
        return httpx.Response(200, content=f"%PDF-{paper_id}".encode())

    def fake_parse_pdf_bytes_batch(contents: list[bytes], paper_ids: list[str]) -> list[str]:
        events.append(("gpu_start", time.monotonic()))
        time.sleep(GPU_SLEEP)
        events.append(("gpu_end", time.monotonic()))
        return [c.decode() for c in contents]

    monkeypatch.setattr("app.assembly.parse_pdf_bytes_batch", fake_parse_pdf_bytes_batch)
    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)

    current_refs = [_make_ref("2504.00001"), _make_ref("2504.00002")]
    next_refs = [_make_ref(pid) for pid in sorted(NEXT_REF_IDS)]

    # Exactly how `rag/orchestrator.py`'s `_prepare_batch` calls this: prefetch the next batch,
    # THEN call parse_batch() for the current one -- see its T-DOC18 docstring.
    parser.prefetch_next_batch(next_refs)
    result = parser.parse_batch(current_refs)

    assert result == ["%PDF-2504.00001", "%PDF-2504.00002"], (
        "the current batch's own (unrelated) result must be correct and unaffected"
    )

    by_label = dict(events)
    gpu_start, gpu_end = by_label["gpu_start"], by_label["gpu_end"]
    for paper_id in NEXT_REF_IDS:
        download_start = by_label[f"download_start:{paper_id}"]
        download_end = by_label[f"download_end:{paper_id}"]
        assert download_start < gpu_end, (
            f"{paper_id}'s prefetch download must start before the GPU call finishes"
        )
        assert gpu_start <= download_end <= gpu_end, (
            f"{paper_id}'s prefetch download must complete WHILE the GPU call is still running "
            f"(gpu window [{gpu_start}, {gpu_end}], download ended at {download_end}) -- proves "
            "real overlap, not just an early-but-sequential kickoff"
        )


def test_prefetch_next_batch_is_reused_by_the_matching_parse_batch_call_not_redownloaded(
    monkeypatch,
):
    """Once a batch has been prefetched, the later `parse_batch()` call for those exact refs must
    reuse the prefetched bytes -- proven by counting real HTTP requests per paper_id (must be
    exactly one, not two)."""

    request_counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        paper_id = request.url.path.rsplit("/", 1)[-1]
        request_counts[paper_id] = request_counts.get(paper_id, 0) + 1
        return httpx.Response(200, content=f"%PDF-{paper_id}".encode())

    monkeypatch.setattr(
        "app.assembly.parse_pdf_bytes_batch",
        lambda contents, paper_ids: [c.decode() for c in contents],
    )
    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)

    batch_0 = [_make_ref("2504.00001")]
    batch_1 = [_make_ref("2504.00002"), _make_ref("2504.00003")]

    parser.prefetch_next_batch(batch_1)
    result_0 = parser.parse_batch(batch_0)
    result_1 = parser.parse_batch(batch_1)  # must reuse the prefetch, not download again

    assert result_0 == ["%PDF-2504.00001"]
    assert result_1 == ["%PDF-2504.00002", "%PDF-2504.00003"], (
        "results for the prefetched batch must still come back in the right order, correctly "
        "attributed to their own refs"
    )
    assert request_counts == {"2504.00001": 1, "2504.00002": 1, "2504.00003": 1}, (
        "every paper_id must be downloaded exactly once -- no ref's bytes duplicated or refetched"
    )


def test_prefetch_next_batch_is_a_noop_for_an_empty_list(monkeypatch):
    """The last group of a run has no next batch (`parse_phase` slices past the end of `refs` to
    `[]`) -- `prefetch_next_batch([])` must not submit any background work or raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-fake")

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)

    parser.prefetch_next_batch([])  # must not raise

    assert parser._prefetched is None


def test_parse_batch_falls_back_to_a_fresh_download_when_refs_dont_match_the_prefetch(
    monkeypatch,
):
    """A stale/mismatched prefetch (refs the caller never actually asks `parse_batch()` for) must
    not corrupt or be silently reused for a different batch -- `parse_batch()` downloads fresh
    instead, and the stale prefetch is simply never consumed."""

    request_counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        paper_id = request.url.path.rsplit("/", 1)[-1]
        request_counts[paper_id] = request_counts.get(paper_id, 0) + 1
        return httpx.Response(200, content=f"%PDF-{paper_id}".encode())

    monkeypatch.setattr(
        "app.assembly.parse_pdf_bytes_batch",
        lambda contents, paper_ids: [c.decode() for c in contents],
    )
    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)

    parser.prefetch_next_batch([_make_ref("2504.00099")])  # never actually requested below
    result = parser.parse_batch([_make_ref("2504.00001")])

    assert result == ["%PDF-2504.00001"]
    assert request_counts.get("2504.00001") == 1


# ================================================================================================
# T-DOC10 — harvest-level quarantine wiring
# ================================================================================================


class _AlwaysTransientSource:
    """A `Source` whose `fetch()` always raises `TransientError` -- stands in only for the
    injected `Source`, not for `Harvester` itself, so the retry/quarantine logic under test is
    the real thing `build_ingestion_orchestrator` wires up, not a fake standing in for it."""

    def fetch(self, focus_area, cap, ordering):
        raise TransientError("ArxivSource: arXiv API returned 429")


def test_harvest_failure_is_written_to_the_quarantine_table(monkeypatch, tmp_path):
    """Previously `Harvester` was constructed in `build_ingestion_orchestrator` with no
    `quarantine=` kwarg, so a harvest-level failure (retry budget exhausted) was completely
    invisible -- no DB row, no log line. Proves the fix: the real `Harvester`, built through the
    real composition root, writes a row to the real `quarantine` SQLite table other pipeline
    stages already use (rag/orchestrator.py's `self._state.quarantine(...)` calls)."""
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: _AlwaysTransientSource())
    # `Harvester`'s retry backoff isn't injectable through `build_ingestion_orchestrator` (no new
    # config lever added for this fix) -- stub the real sleep call site so the test stays fast.
    monkeypatch.setattr("rag.harvester.time.sleep", lambda seconds: None)
    # `VectorIndex.__init__` makes a real network call to Qdrant (`_ensure_collection`) -- this
    # test is only about harvest/quarantine wiring, so stub it out like `_PdfDownloadParser`'s
    # own tests stub `parse_pdf_bytes` for a collaborator that isn't under test.
    monkeypatch.setattr("app.assembly.VectorIndex", lambda *a, **k: object())

    db_path = str(tmp_path / "papers.db")
    cfg = Config(focus_area_queries=["causal inference"], gpu_lock_path=str(tmp_path / ".gpu.lock"))

    orchestrator = build_ingestion_orchestrator(
        cfg, db_path=db_path, blob_dir=str(tmp_path / "blobs")
    )
    refs = orchestrator.harvest(cfg.focus_area_queries, cap=5)

    assert refs == [], "every fetch attempt raised -- nothing should have been harvested"

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT paper_id, stage, error FROM quarantine").fetchone()
    conn.close()
    assert row is not None, "a harvest-level failure must leave a real quarantine row, not silence"
    paper_id, stage, error = row
    assert paper_id == "<unknown>"  # a page-level API failure carries no paper identity
    assert stage == "harvested"
    assert "429" in error


def test_quarantine_sink_logs_and_does_not_raise_when_the_write_itself_fails(caplog):
    """`Harvester.harvest()`'s documented postcondition is that it never raises, which requires
    the injected `quarantine` sink to never raise either. `"<unknown>"` is a fixed sentinel (not
    a real per-paper id), so a second harvest-level failure written to the same db would hit
    `quarantine.paper_id`'s PRIMARY KEY -- proves that failure degrades to a log line instead of
    crashing the run."""

    class _BrokenState:
        def quarantine(self, paper_id, stage, error):
            raise sqlite3.IntegrityError("UNIQUE constraint failed: quarantine.paper_id")

    sink = _sqlite_harvest_quarantine_sink(_BrokenState())

    with caplog.at_level(logging.ERROR):
        sink("<unknown>", TransientError("boom"))  # must not raise

    assert "quarantine" in caplog.text.lower()


# ================================================================================================
# T-DOC18 — PDF cache (giggly-tumbling-globe.md Part 0 Layer 1): `_PdfDownloadParser` reads
# `app/prefetch_pdfs.py`'s on-disk `<paper_id>.pdf` cache before doing any HTTP call, and
# write-throughs a live download's bytes to that same cache afterward.
# ================================================================================================


def test_cache_hit_returns_cached_bytes_with_zero_http_calls(monkeypatch, tmp_path):
    """A pre-placed `<paper_id>.pdf` in `cache_dir` (the prefetcher's own naming convention) must
    be read directly -- no call reaches the injected `httpx.Client` at all."""
    ref = _make_ref("2504.00001")
    (tmp_path / f"{ref.paper_id}.pdf").write_bytes(b"%PDF-cached")

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, content=b"%PDF-live")  # would prove the cache was skipped

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps, cache_dir=tmp_path)

    result = parser.parse(ref)

    assert result == b"%PDF-cached", "must return the cached bytes, not live-download them"
    assert call_count["n"] == 0, "a cache hit must make zero HTTP calls"


def test_cache_miss_downloads_live_and_writes_through(monkeypatch, tmp_path):
    """No file in `cache_dir` yet -- unchanged live-download behavior (one HTTP call, same
    delay), PLUS the downloaded bytes get written to `cache_dir/<paper_id>.pdf` afterward so the
    live pipeline also grows the prefetcher's cache."""
    ref = _make_ref("2504.00002")

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, content=b"%PDF-live")

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps, cache_dir=tmp_path)

    result = parser.parse(ref)

    assert result == b"%PDF-live"
    assert call_count["n"] == 1, "a cache miss must still make exactly one live HTTP call"
    assert sleeps == [_PDF_DOWNLOAD_DELAY_SECONDS], "unchanged inter-request delay behavior"

    cached_path = tmp_path / f"{ref.paper_id}.pdf"
    assert cached_path.exists(), "a live download must be written through to the cache"
    assert cached_path.read_bytes() == b"%PDF-live"
    assert not (tmp_path / f"{ref.paper_id}.pdf.tmp").exists(), (
        "the atomic tmp file must be renamed away, not left behind"
    )


def test_cache_miss_retry_path_still_writes_through_on_eventual_success(monkeypatch, tmp_path):
    """Cache-miss + a transient failure that recovers on retry (existing retry/backoff behavior,
    unchanged) must still write the eventually-successful bytes through to the cache."""
    ref = _make_ref("2504.00003")
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, content=b"%PDF-recovered")

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps, cache_dir=tmp_path)

    result = parser.parse(ref)

    assert attempts["count"] == 2, "retry/backoff behavior must be unchanged by caching"
    assert result == b"%PDF-recovered"
    assert (tmp_path / f"{ref.paper_id}.pdf").read_bytes() == b"%PDF-recovered"


def test_no_cache_dir_configured_skips_cache_check_entirely(monkeypatch):
    """`cache_dir=None` (the default) must behave exactly like caching didn't exist -- always a
    live HTTP call, no attempt to read or write any path."""
    ref = _make_ref("2504.00004")
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, content=b"%PDF-live")

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps, cache_dir=None)

    result = parser.parse(ref)

    assert result == b"%PDF-live"
    assert call_count["n"] == 1, "no cache_dir means every ref is a live download"


def test_build_ingestion_orchestrator_wires_pdf_cache_dir_config_field(monkeypatch, tmp_path):
    """`build_ingestion_orchestrator` must thread `config.pdf_cache_dir` into `_PdfDownloadParser`
    (previously not wired at all -- T-DOC18; T-DOC29 moved this off the process environment onto
    `Config`).
    When the field is set, the constructed parser's cache_dir must match it exactly (same
    convention as `app/prefetch_pdfs.py`'s own `config.pdf_cache_dir` read)."""
    monkeypatch.setattr("app.assembly.VectorIndex", lambda *a, **k: object())

    cache_dir = tmp_path / "pdf_cache"
    db_path = str(tmp_path / "papers.db")
    cfg = Config(
        focus_area_queries=["causal inference"],
        gpu_lock_path=str(tmp_path / ".gpu.lock"),
        pdf_cache_dir=str(cache_dir),
    )

    orchestrator = build_ingestion_orchestrator(
        cfg, db_path=db_path, blob_dir=str(tmp_path / "blobs")
    )

    assert orchestrator._parser._cache_dir == cache_dir
    assert cache_dir.is_dir(), "the composition root must ensure the configured dir exists"


def test_build_ingestion_orchestrator_default_matches_prefetch_pdfs_default(monkeypatch, tmp_path):
    """T-DOC18 bug fix: `app/prefetch_pdfs.py` defaults its cache dir to `"pdf_cache"` and fills
    that real directory continuously. `build_ingestion_orchestrator` previously had NO default of
    its own (`cache_dir=None` when the env var was unset), which made Layer 1's cache
    check/write-through a permanent, silent no-op -- the prefetcher's work was invisible to it.
    T-DOC29 makes this structurally impossible to drift again: both modules now read the SAME
    `Config.pdf_cache_dir` field, whose one default is declared once in `contracts/config.py`, so
    there's no second env-var-with-fallback read left to disagree with it."""
    monkeypatch.setattr("app.assembly.VectorIndex", lambda *a, **k: object())
    monkeypatch.chdir(tmp_path)  # the default is a relative dir -- don't pollute the real cwd

    db_path = str(tmp_path / "papers.db")
    cfg = Config(focus_area_queries=["causal inference"], gpu_lock_path=str(tmp_path / ".gpu.lock"))
    assert cfg.pdf_cache_dir == "pdf_cache", "sanity check on Config's own default"

    orchestrator = build_ingestion_orchestrator(
        cfg, db_path=db_path, blob_dir=str(tmp_path / "blobs")
    )

    assert orchestrator._parser._cache_dir == Path("pdf_cache")
    assert orchestrator._parser._cache_dir.is_dir()


def test_build_ingestion_orchestrator_empty_pdf_cache_dir_disables_cache_and_logs(
    monkeypatch, tmp_path, caplog
):
    """The only way `cache_dir` should still end up `None`: `config.yaml` explicitly sets
    `pdf_cache_dir: ""`. That must stay visible (a log line), not silently disable Layer 1."""
    monkeypatch.setattr("app.assembly.VectorIndex", lambda *a, **k: object())

    db_path = str(tmp_path / "papers.db")
    cfg = Config(
        focus_area_queries=["causal inference"],
        gpu_lock_path=str(tmp_path / ".gpu.lock"),
        pdf_cache_dir="",
    )

    with caplog.at_level(logging.WARNING):
        orchestrator = build_ingestion_orchestrator(
            cfg, db_path=db_path, blob_dir=str(tmp_path / "blobs")
        )

    assert orchestrator._parser._cache_dir is None
    assert "pdf_cache_dir" in caplog.text and "disabled" in caplog.text.lower()


# ================================================================================================
# T-DOC18 bug fix -- unique per-writer tmp filename (was a fixed `<paper_id>.pdf.tmp` shared with
# `app/prefetch_pdfs.py`'s own tmp convention, so the 24/7 prefetcher and this live pipeline could
# race to write the same tmp path and interleave into one sticky-corrupt cache file).
# ================================================================================================


def test_write_cache_tmp_path_is_pid_qualified_not_the_old_shared_fixed_name(monkeypatch, tmp_path):
    ref = _make_ref("2504.00005")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-live")

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps, cache_dir=tmp_path)

    captured: dict[str, str] = {}
    real_write_bytes = Path.write_bytes

    def spying_write_bytes(self: Path, data: bytes):
        captured["tmp_name"] = self.name
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", spying_write_bytes)
    monkeypatch.setattr("app.assembly.os.getpid", lambda: 4242)

    parser.parse(ref)

    assert captured["tmp_name"] == f"{ref.paper_id}.pdf.4242.tmp"
    assert captured["tmp_name"] != f"{ref.paper_id}.pdf.tmp", (
        "must not reuse prefetch_pdfs.py's shared fixed tmp name -- that shared name is the "
        "collision this fix removes"
    )
    assert not (tmp_path / f"{ref.paper_id}.pdf.tmp").exists(), (
        "the old fixed-name tmp path (prefetch_pdfs.py's own convention) must never be created"
    )
    assert (tmp_path / f"{ref.paper_id}.pdf").read_bytes() == b"%PDF-live", (
        "the pid-qualified tmp file must still be renamed into the normal final path"
    )


def test_write_cache_tmp_path_differs_across_two_writer_pids(monkeypatch, tmp_path):
    """Direct proof two concurrent writers (e.g. this live pipeline and the standalone
    `app/prefetch_pdfs.py` prefetcher, or two instances of this process) can't collide: the tmp
    path generated for the SAME paper_id differs when the writer's pid differs."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-live")

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps, cache_dir=tmp_path)
    ref = _make_ref("2504.00006")

    tmp_names: list[str] = []
    real_write_bytes = Path.write_bytes

    def spying_write_bytes(self: Path, data: bytes):
        tmp_names.append(self.name)
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", spying_write_bytes)

    monkeypatch.setattr("app.assembly.os.getpid", lambda: 111)
    parser._write_cache(ref, b"%PDF-from-writer-111")
    monkeypatch.setattr("app.assembly.os.getpid", lambda: 222)
    parser._write_cache(ref, b"%PDF-from-writer-222")

    assert len(tmp_names) == 2
    assert tmp_names[0] != tmp_names[1], (
        "two writers racing the same paper_id must generate two different tmp paths -- whichever "
        "rename() lands last simply leaves one complete, valid file instead of a corrupt interleave"
    )
    assert tmp_names == [f"{ref.paper_id}.pdf.111.tmp", f"{ref.paper_id}.pdf.222.tmp"]


# ================================================================================================
# T-DOC18 bug fix -- the rate-limit-pacing sleep must not fire on a cache hit (zero HTTP calls
# happened, so there's nothing to pace -- the old unconditional `finally: self._sleep(...)` in
# both `parse()` and `_download_all()` undercut the whole point of the cache).
# ================================================================================================


def test_parse_cache_hit_makes_zero_sleep_calls(monkeypatch, tmp_path):
    ref = _make_ref("2504.00012")
    (tmp_path / f"{ref.paper_id}.pdf").write_bytes(b"%PDF-cached")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not reach the network on a cache hit")

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps, cache_dir=tmp_path)

    result = parser.parse(ref)

    assert result == b"%PDF-cached"
    assert sleeps == [], "a cache hit made zero HTTP calls -- nothing to rate-limit-pace"


def test_parse_live_download_still_sleeps_exactly_as_before(monkeypatch, tmp_path):
    """Regression guard: fixing the cache-hit case must not silently break the live-download
    case -- a genuine miss still sleeps the fixed inter-request delay exactly once."""
    ref = _make_ref("2504.00013")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-live")

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps, cache_dir=tmp_path)

    parser.parse(ref)

    assert sleeps == [_PDF_DOWNLOAD_DELAY_SECONDS]


def test_download_all_makes_zero_sleeps_when_the_whole_batch_is_cached(monkeypatch, tmp_path):
    """A fully-cached batch previously still slept `_PDF_DOWNLOAD_DELAY_SECONDS` per ref (pure
    idle time, no HTTP call to pace) -- directly contradicts what T-DOC18 (PR #84's
    WORK-BREAKDOWN.md entry) claims about this fix ("zero HTTP/rate-limit cost" on a hit)."""
    refs = [_make_ref("2504.00010"), _make_ref("2504.00011")]
    for ref in refs:
        (tmp_path / f"{ref.paper_id}.pdf").write_bytes(f"%PDF-{ref.paper_id}".encode())

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not reach the network on an all-cache-hit batch")

    monkeypatch.setattr(
        "app.assembly.parse_pdf_bytes_batch",
        lambda contents, paper_ids: [c.decode() for c in contents],
    )
    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps, cache_dir=tmp_path)

    result = parser.parse_batch(refs)

    assert result == [f"%PDF-{ref.paper_id}" for ref in refs]
    assert sleeps == [], "a fully-cached batch must make zero rate-limit sleeps"


def test_download_all_sleeps_only_for_the_live_ref_not_the_cached_one(monkeypatch, tmp_path):
    """Mixed batch (one cache hit, one live miss) in the same `parse_batch()` call: exactly one
    sleep, for the live ref -- proves the skip is per-ref, and that a genuine miss in the same
    batch still sleeps exactly as before (regression guard alongside the all-cached case above)."""
    cached_ref = _make_ref("2504.00008")
    live_ref = _make_ref("2504.00009")
    (tmp_path / f"{cached_ref.paper_id}.pdf").write_bytes(b"%PDF-cached")

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, content=b"%PDF-live")

    monkeypatch.setattr(
        "app.assembly.parse_pdf_bytes_batch",
        lambda contents, paper_ids: [c.decode() for c in contents],
    )
    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps, cache_dir=tmp_path)

    result = parser.parse_batch([cached_ref, live_ref])

    assert result == ["%PDF-cached", "%PDF-live"]
    assert call_count["n"] == 1, "only the live ref should reach the network"
    assert sleeps == [_PDF_DOWNLOAD_DELAY_SECONDS], (
        "exactly one sleep -- for the live download -- the cache hit must contribute none"
    )


# T-DOC19 -- before_parse_phase hook wiring to app.tei_lifecycle (before_finish_phase is back to
# the orchestrator's default no-op -- see the T-DOC19 bug-fix docstring on the noop test below)
# ================================================================================================
#
# `_FakeTeiLifecycle` below is a local, test-only stand-in for `app/tei_lifecycle.py`'s
# `stop_tei_containers()`/`start_tei_containers()` interface (both best-effort, never raise) so
# these wiring tests run standalone rather than depending on the real module's Docker/HTTP calls.
# These tests cover only that `build_ingestion_orchestrator` composes/wires the hooks correctly
# (composition-root level) -- not the orchestrator's own hook-calling mechanism, which
# `rag/test_orchestrator.py` already covers (`test_before_parse_phase_hook_fires_before_any_parsing`
# / `test_before_finish_phase_hook_fires_after_every_parse_and_before_any_summarize`).


class _FakeTeiLifecycle:
    def __init__(self):
        self.stop_calls = 0
        self.start_calls = 0

    def stop_tei_containers(self) -> None:
        self.stop_calls += 1

    def start_tei_containers(self) -> None:
        self.start_calls += 1


class FakeSummarizer:
    """Named without a leading underscore (unlike this file's other test-local fakes) so
    `ci/checks/gpu_lock.py`'s check (f) recognizes it as an intentional fake via its `Fake` prefix
    -- it ends in the `Summarizer` adapter suffix that check exists to police, and this class has
    no `gpu_lock` param on purpose (it's a spy, not a real adapter)."""

    def __init__(self):
        self.unload_calls = 0

    def unload(self) -> None:
        self.unload_calls += 1


def _build_orchestrator_for_hook_test(monkeypatch, tmp_path, on_stage=None):
    """Same stubbing pattern as `test_harvest_failure_is_written_to_the_quarantine_table` above --
    real orchestrator through the real composition root, with only the collaborators that would
    otherwise need a live network/GPU (VectorIndex's real Qdrant connection, OllamaSummarizer's
    real HTTP client) or don't exist yet in this branch (`app.tei_lifecycle`) stubbed out."""
    fake_summarizer = FakeSummarizer()
    fake_tei_lifecycle = _FakeTeiLifecycle()
    monkeypatch.setattr("app.assembly.OllamaSummarizer", lambda *a, **k: fake_summarizer)
    monkeypatch.setattr("app.assembly.VectorIndex", lambda *a, **k: object())
    monkeypatch.setattr("app.assembly.tei_lifecycle", fake_tei_lifecycle)

    cfg = Config(focus_area_queries=["causal inference"], gpu_lock_path=str(tmp_path / ".gpu.lock"))
    orchestrator = build_ingestion_orchestrator(
        cfg, db_path=str(tmp_path / "papers.db"), blob_dir=str(tmp_path / "blobs"),
        on_stage=on_stage,
    )
    return orchestrator, fake_summarizer, fake_tei_lifecycle


def test_before_parse_phase_composes_summarizer_unload_and_tei_stop(monkeypatch, tmp_path):
    orchestrator, fake_summarizer, fake_tei_lifecycle = _build_orchestrator_for_hook_test(
        monkeypatch, tmp_path
    )

    orchestrator._before_parse_phase()

    assert fake_summarizer.unload_calls == 1, "must still evict the Summarizer, as before T-DOC19"
    assert fake_tei_lifecycle.stop_calls == 1, "must also stop the TEI containers"


def test_before_finish_phase_is_left_as_the_default_noop(monkeypatch, tmp_path):
    """T-DOC19 bug fix: `build_ingestion_orchestrator` no longer wires `before_finish_phase` to
    `tei_lifecycle.start_tei_containers` -- `finish_phase()` embeds its once-per-run
    `topic_query_vec` BEFORE this hook fires (rag/orchestrator.py, frozen), so that wiring
    restarted TEI too late to help the very embed call that needed it (a real `httpx.ConnectError`
    against the still-`docker stop`-ped `rag-tei-embed` container, every real Pass 2 run). The
    restart now happens explicitly in `app/ingest.py`'s `_run_finish_phase`, before
    `finish_phase()` is called at all -- see `app/test_ingest.py` for the ordering proof."""
    orchestrator, fake_summarizer, fake_tei_lifecycle = _build_orchestrator_for_hook_test(
        monkeypatch, tmp_path
    )

    orchestrator._before_finish_phase()  # must not raise even though nothing is wired

    assert fake_tei_lifecycle.start_calls == 0, (
        "before_finish_phase must be back to the orchestrator's default no-op -- the TEI restart "
        "now happens in app/ingest.py, earlier than this hook ever fires"
    )
    assert fake_summarizer.unload_calls == 0, "before_finish_phase must not touch the summarizer"


def test_build_ingestion_orchestrator_wires_on_stage_when_given(monkeypatch, tmp_path):
    """T-DOC59 (OG-25): `on_stage=` is forwarded to `IngestionOrchestrator` unmodified --
    `app/ingest.py`'s `_run_finish_phase` passes `run.set_stage` (app/telemetry.py) here so GPU
    telemetry can re-tag the summarize/embed/store split inside "finish" without this module or
    `rag/orchestrator.py` importing `app.telemetry` (see that module's `on_stage` docstring)."""
    stages_seen: list[str] = []
    orchestrator, _, _ = _build_orchestrator_for_hook_test(
        monkeypatch, tmp_path, on_stage=stages_seen.append
    )

    orchestrator._on_stage("summarize")
    assert stages_seen == ["summarize"]


def test_build_ingestion_orchestrator_on_stage_defaults_to_the_orchestrators_own_noop(
    monkeypatch, tmp_path
):
    """Today's exact default behavior: a caller that doesn't pass `on_stage` (every other test in
    this file) gets `IngestionOrchestrator`'s own no-op default, unchanged."""
    orchestrator, _, _ = _build_orchestrator_for_hook_test(monkeypatch, tmp_path)
    orchestrator._on_stage("summarize")  # must not raise


def test_batch_size_provider_is_wired_to_an_adaptive_batch_sizer(monkeypatch, tmp_path):
    """T-DOC21: `build_ingestion_orchestrator` wires `batch_size_provider` to a real
    `AdaptiveBatchSizer.next_size`, seeded with `config.parse_batch_size` as the starting point --
    not left at the default (`None`, fixed-size) behavior."""
    orchestrator, _, _ = _build_orchestrator_for_hook_test(monkeypatch, tmp_path)

    assert orchestrator._batch_size_provider is not None

    sizer = orchestrator._batch_size_provider.__self__
    from app.adaptive_batch_sizer import AdaptiveBatchSizer

    assert isinstance(sizer, AdaptiveBatchSizer)
    assert sizer._current == Config(focus_area_queries=["x"]).parse_batch_size == 4


# ================================================================================================
# T-DOC48 (cache-first `harvest_refs`) + T-DOC49 (429 backoff/resume on the metadata fetch) --
# `harvest_refs(config, orchestrator)`'s `config.ingest_paper_ids` branch used to call
# `ArxivSource().fetch_by_ids(...)` unconditionally, even for a paper_id whose PDF (and now,
# T-DOC48, its metadata sidecar) was already cached locally -- and that call had no retry, so a
# single arXiv 429 crashed the whole run. Offline, no real network (`ArxivSource` monkeypatched
# to a stub, same pattern `test_harvest_failure_is_written_to_the_quarantine_table` above uses).
# ================================================================================================


class _StubArxivSource:
    """Records every `fetch_by_ids` call and returns canned refs / raises canned errors in
    sequence -- stands in for the real `ArxivSource` the same way `_AlwaysTransientSource` does
    above, so these tests exercise `harvest_refs`'s own retry/cache logic, not a fake pretending
    to have it."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    def fetch_by_ids(self, ids):
        self.calls.append(list(ids))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _StubOrchestrator:
    """Stands in for `IngestionOrchestrator` on the query-driven (no `ingest_paper_ids`) path --
    records the call so a test can prove that path is untouched by this ticket's changes."""

    def __init__(self, refs):
        self._refs = refs
        self.calls: list[tuple[list[str], int]] = []

    def harvest(self, focus_area, cap):
        self.calls.append((focus_area, cap))
        return self._refs


def _write_cached_ref(cache_dir: Path, ref: PaperRef) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{ref.paper_id}.pdf").write_bytes(b"%PDF-fake")
    (cache_dir / f"{ref.paper_id}.json").write_text(ref.model_dump_json())


def test_harvest_refs_cache_first_makes_zero_network_calls_when_both_files_are_cached(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(
        "app.assembly.ArxivSource",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not construct ArxivSource -- both refs were fully cached")
        ),
    )
    cache_dir = tmp_path / "pdf_cache"
    ref_1, ref_2 = _make_ref("2601.00001"), _make_ref("2601.00002")
    _write_cached_ref(cache_dir, ref_1)
    _write_cached_ref(cache_dir, ref_2)

    cfg = Config(
        focus_area_queries=["x"],
        ingest_paper_ids=[ref_1.paper_id, ref_2.paper_id],
        pdf_cache_dir=str(cache_dir),
    )

    refs = harvest_refs(cfg, orchestrator=None)

    assert refs == [ref_1, ref_2], "order must follow config.ingest_paper_ids"


def test_harvest_refs_falls_back_to_arxiv_for_a_pdf_only_cache_entry(monkeypatch, tmp_path):
    """Backwards compatibility: the current 2,542-file cache is `.pdf`-only (no `.json` sidecar,
    predates T-DOC48) -- that id must still resolve via a live `fetch_by_ids` call, exactly as
    before this ticket, not be silently dropped or treated as an error."""
    cache_dir = tmp_path / "pdf_cache"
    cache_dir.mkdir()
    pdf_only_id = "2601.00003"
    (cache_dir / f"{pdf_only_id}.pdf").write_bytes(b"%PDF-fake")  # no matching .json

    fetched_ref = _make_ref(pdf_only_id)
    stub_source = _StubArxivSource([[fetched_ref]])
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: stub_source)

    cfg = Config(
        focus_area_queries=["x"], ingest_paper_ids=[pdf_only_id], pdf_cache_dir=str(cache_dir),
    )

    refs = harvest_refs(cfg, orchestrator=None, sleep=lambda s: None)

    assert refs == [fetched_ref]
    assert stub_source.calls == [[pdf_only_id]]


def test_harvest_refs_only_fetches_the_ids_missing_from_cache(monkeypatch, tmp_path):
    cache_dir = tmp_path / "pdf_cache"
    cached_ref = _make_ref("2601.00001")
    _write_cached_ref(cache_dir, cached_ref)
    missing_ref = _make_ref("2601.00002")

    stub_source = _StubArxivSource([[missing_ref]])
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: stub_source)

    cfg = Config(
        focus_area_queries=["x"],
        ingest_paper_ids=[cached_ref.paper_id, missing_ref.paper_id],
        pdf_cache_dir=str(cache_dir),
    )

    refs = harvest_refs(cfg, orchestrator=None, sleep=lambda s: None)

    assert refs == [cached_ref, missing_ref]
    assert stub_source.calls == [[missing_ref.paper_id]], (
        "only the uncached id should ever reach the network"
    )


def test_harvest_refs_empty_pdf_cache_dir_disables_the_cache_check(monkeypatch, tmp_path):
    """`config.pdf_cache_dir = ""` (T-DOC29's documented "explicitly disabled" sentinel, same one
    `build_ingestion_orchestrator` handles) must skip the cache check entirely and always fetch --
    matches how `_PdfDownloadParser`'s own cache_dir=None handling behaves."""
    cache_dir = tmp_path / "pdf_cache"
    ref = _make_ref("2601.00001")
    _write_cached_ref(cache_dir, ref)  # cached, but pdf_cache_dir below doesn't point at it

    stub_source = _StubArxivSource([[ref]])
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: stub_source)

    cfg = Config(focus_area_queries=["x"], ingest_paper_ids=[ref.paper_id], pdf_cache_dir="")

    refs = harvest_refs(cfg, orchestrator=None, sleep=lambda s: None)

    assert refs == [ref]
    assert stub_source.calls == [[ref.paper_id]]


def test_harvest_refs_query_driven_path_is_unaffected_when_ingest_paper_ids_is_unset(monkeypatch):
    monkeypatch.setattr(
        "app.assembly.ArxivSource",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("query-driven harvest must never construct ArxivSource directly")
        ),
    )
    ref = _make_ref("2601.00001")
    orchestrator = _StubOrchestrator([ref])
    cfg = Config(focus_area_queries=["causal inference"], corpus_cap=5)

    refs = harvest_refs(cfg, orchestrator)

    assert refs == [ref]
    assert orchestrator.calls == [(["causal inference"], 5)]


def test_harvest_refs_retries_a_429_with_backoff_then_succeeds(monkeypatch, tmp_path):
    ref = _make_ref("2601.00001")
    stub_source = _StubArxivSource(
        [TransientError("ArxivSource: arXiv API returned 429"), [ref]]
    )
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: stub_source)

    cfg = Config(focus_area_queries=["x"], ingest_paper_ids=[ref.paper_id], pdf_cache_dir="")
    sleeps: list[float] = []

    refs = harvest_refs(cfg, orchestrator=None, sleep=sleeps.append)

    assert refs == [ref]
    assert len(stub_source.calls) == 2, "must have retried after the 429, not crashed"
    assert sleeps == [_METADATA_FETCH_BACKOFF_SECONDS]


def test_harvest_refs_raises_once_the_429_retry_budget_is_exhausted(monkeypatch):
    """The retry is bounded, not infinite -- once genuinely exhausted this must still surface as a
    `TransientError` to the caller (CONVENTIONS.md §4), not be silently swallowed."""
    always_429 = [TransientError("429") for _ in range(_METADATA_FETCH_MAX_RETRIES + 1)]
    stub_source = _StubArxivSource(always_429)
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: stub_source)

    cfg = Config(focus_area_queries=["x"], ingest_paper_ids=["2601.00001"], pdf_cache_dir="")
    sleeps: list[float] = []

    with pytest.raises(TransientError):
        harvest_refs(cfg, orchestrator=None, sleep=sleeps.append)

    assert len(stub_source.calls) == _METADATA_FETCH_MAX_RETRIES + 1
    assert len(sleeps) == _METADATA_FETCH_MAX_RETRIES


# ================================================================================================
# T-DOC58/OG-24: the 429's `Retry-After` header, when present, is honored instead of the
# exponential guess above. `_transient_429` below sets `.diagnostics["retry_after"]` on a canned
# `TransientError` by hand, matching exactly what `rag/harvester.py`'s `_fetch_by_id_list` sets on
# the real raise site (`rag/test_harvester_arxiv_source.py` covers that raise site itself) --
# `.diagnostics` is a plain settable attribute either way (contracts/errors.py's T-DOC17
# convention), so this needs no real HTTP response to build.
# ================================================================================================


def _transient_429(retry_after: str | None) -> TransientError:
    error = TransientError("ArxivSource: arXiv API returned 429")
    error.diagnostics = {"retry_after": retry_after}
    return error


def test_fetch_by_ids_backoff_honors_retry_after_seconds_form(monkeypatch):
    ref = _make_ref("2601.00001")
    stub_source = _StubArxivSource([_transient_429("42"), [ref]])
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: stub_source)

    cfg = Config(focus_area_queries=["x"], ingest_paper_ids=[ref.paper_id], pdf_cache_dir="")
    sleeps: list[float] = []

    refs = harvest_refs(cfg, orchestrator=None, sleep=sleeps.append)

    assert refs == [ref]
    assert sleeps == [42.0], "must honor the server's Retry-After, not the exponential schedule"


def test_fetch_by_ids_backoff_honors_retry_after_http_date_form(monkeypatch):
    ref = _make_ref("2601.00001")
    target = datetime.now(UTC) + timedelta(seconds=42)
    stub_source = _StubArxivSource([_transient_429(format_datetime(target, usegmt=True)), [ref]])
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: stub_source)

    cfg = Config(focus_area_queries=["x"], ingest_paper_ids=[ref.paper_id], pdf_cache_dir="")
    sleeps: list[float] = []

    refs = harvest_refs(cfg, orchestrator=None, sleep=sleeps.append)

    assert refs == [ref]
    assert len(sleeps) == 1
    assert abs(sleeps[0] - 42.0) < 2.0, "HTTP-date form must resolve to ~seconds-from-now"


def test_fetch_by_ids_backoff_falls_back_to_exponential_when_retry_after_absent(monkeypatch):
    ref = _make_ref("2601.00001")
    stub_source = _StubArxivSource([_transient_429(None), [ref]])
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: stub_source)

    cfg = Config(focus_area_queries=["x"], ingest_paper_ids=[ref.paper_id], pdf_cache_dir="")
    sleeps: list[float] = []

    refs = harvest_refs(cfg, orchestrator=None, sleep=sleeps.append)

    assert refs == [ref]
    assert sleeps == [_METADATA_FETCH_BACKOFF_SECONDS]


def test_fetch_by_ids_backoff_falls_back_to_exponential_when_retry_after_unparseable(monkeypatch):
    ref = _make_ref("2601.00001")
    stub_source = _StubArxivSource([_transient_429("not-a-valid-value"), [ref]])
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: stub_source)

    cfg = Config(focus_area_queries=["x"], ingest_paper_ids=[ref.paper_id], pdf_cache_dir="")
    sleeps: list[float] = []

    refs = harvest_refs(cfg, orchestrator=None, sleep=sleeps.append)

    assert refs == [ref]
    assert sleeps == [_METADATA_FETCH_BACKOFF_SECONDS]


def test_fetch_by_ids_backoff_clamps_an_excessive_retry_after(monkeypatch):
    ref = _make_ref("2601.00001")
    stub_source = _StubArxivSource([_transient_429("99999"), [ref]])
    monkeypatch.setattr("app.assembly.ArxivSource", lambda *a, **k: stub_source)

    cfg = Config(focus_area_queries=["x"], ingest_paper_ids=[ref.paper_id], pdf_cache_dir="")
    sleeps: list[float] = []

    refs = harvest_refs(cfg, orchestrator=None, sleep=sleeps.append)

    assert refs == [ref]
    assert sleeps == [_RETRY_AFTER_MAX_SECONDS]


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("42", 42.0),
        ("0", 0.0),
        ("not-a-valid-value", None),
    ],
)
def test_parse_retry_after_seconds_and_absent_and_unparseable_forms(value, expected):
    assert _parse_retry_after(value) == expected


def test_parse_retry_after_http_date_form():
    target = datetime.now(UTC) + timedelta(seconds=42)
    parsed = _parse_retry_after(format_datetime(target, usegmt=True))
    assert parsed is not None
    assert abs(parsed - 42.0) < 2.0


def test_parse_retry_after_past_http_date_floors_to_zero():
    target = datetime.now(UTC) - timedelta(seconds=42)
    assert _parse_retry_after(format_datetime(target, usegmt=True)) == 0.0


def test_resolve_store_paths_falls_back_to_config_not_hardcoded_papers_db():
    """`build_mcp_server` must honor `config.db_path`/`config.blob_dir` when no explicit arg is
    given -- the old hardcoded `"papers.db"`/`"blobs"` fallback silently ignored a configured
    real data dir and produced a fake `Recall@10 = 0.000` (LESSONS-LEARNED 2026-07-17)."""
    from app.assembly import _resolve_store_paths

    cfg = Config(
        focus_area_queries=["x"], db_path="/data/real.db", blob_dir="/data/real_blobs"
    )
    # No explicit arg -> the Config's own paths win, NOT "papers.db"/"blobs".
    assert _resolve_store_paths(cfg, None, None) == ("/data/real.db", "/data/real_blobs")
    # An explicit caller arg still overrides the Config.
    assert _resolve_store_paths(cfg, "/x.db", "/y") == ("/x.db", "/y")
    # Default Config keeps the historical behaviour (unchanged for un-overridden callers).
    assert _resolve_store_paths(Config(focus_area_queries=["x"]), None, None) == (
        "papers.db", "blobs",
    )


# ================================================================================================
# 2026-07-18: `Config.top_k`/`Config.rerank_depth` were declared-but-dead fields (a code sweep
# found no code path that read either). `build_mcp_server` now threads them into
# `McpServer.default_k` / `Retriever.rerank_pool_size` -- the latter CLAMPED to the reranker's
# real vendor batch-size ceiling (`rag/reranker.py`'s `_MAX_BATCH_SIZE=32`), since a hybrid-search
# pool bigger than that would just be silently truncated by TEI's `/rerank` endpoint anyway
# (T-DOC39). `VectorIndex` is stubbed the same way every other `build_mcp_server`-adjacent test in
# this file stubs it (its real constructor makes an eager vector-store network call) -- nothing
# else `build_mcp_server` constructs makes a network call at construction time (TeiEmbedder/
# TeiReranker just store an HTTP client; `FileGpuLock` just wraps a file lock), so this stays
# fully offline.
# ================================================================================================


def test_build_mcp_server_clamps_rerank_pool_size_to_the_rerankers_max_batch_size(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr("app.assembly.VectorIndex", lambda *a, **k: object())

    cfg = Config(
        focus_area_queries=["x"], gpu_lock_path=str(tmp_path / ".gpu.lock"),
        rerank_depth=50,  # > _RERANKER_MAX_BATCH_SIZE=32 -- must clamp down, not pass through raw
    )
    server = build_mcp_server(
        cfg, db_path=str(tmp_path / "papers.db"), blob_dir=str(tmp_path / "blobs")
    )

    assert server._retriever._rerank_pool_size == 32


def test_build_mcp_server_rerank_pool_size_below_the_cap_passes_through_unclamped(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr("app.assembly.VectorIndex", lambda *a, **k: object())

    cfg = Config(
        focus_area_queries=["x"], gpu_lock_path=str(tmp_path / ".gpu.lock"), rerank_depth=10,
    )
    server = build_mcp_server(
        cfg, db_path=str(tmp_path / "papers.db"), blob_dir=str(tmp_path / "blobs")
    )

    assert server._retriever._rerank_pool_size == 10


def test_build_mcp_server_wires_default_k_from_configs_top_k(monkeypatch, tmp_path):
    monkeypatch.setattr("app.assembly.VectorIndex", lambda *a, **k: object())

    cfg = Config(
        focus_area_queries=["x"], gpu_lock_path=str(tmp_path / ".gpu.lock"), top_k=7,
    )
    server = build_mcp_server(
        cfg, db_path=str(tmp_path / "papers.db"), blob_dir=str(tmp_path / "blobs")
    )

    assert server._default_k == 7


def test_build_mcp_server_default_k_matches_configs_own_default_top_k(monkeypatch, tmp_path):
    monkeypatch.setattr("app.assembly.VectorIndex", lambda *a, **k: object())

    cfg = Config(focus_area_queries=["x"], gpu_lock_path=str(tmp_path / ".gpu.lock"))
    server = build_mcp_server(
        cfg, db_path=str(tmp_path / "papers.db"), blob_dir=str(tmp_path / "blobs")
    )

    assert server._default_k == 10  # Config.top_k's own default
