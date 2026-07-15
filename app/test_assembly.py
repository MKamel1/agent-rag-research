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
import sqlite3
import time
from datetime import date

import httpx
import pytest

from app.assembly import (
    _PDF_DOWNLOAD_DELAY_SECONDS,
    _PDF_DOWNLOAD_RETRY_BACKOFF_SECONDS,
    _PdfDownloadParser,
    _sqlite_harvest_quarantine_sink,
    build_ingestion_orchestrator,
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


def _make_parser(monkeypatch, handler, sleeps: list[float]) -> _PdfDownloadParser:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    # The real Parser (rag.parser.parse) needs an actual PDF/MinerU -- stub it so this test
    # exercises only the download+delay wiring, not the Parser module.
    monkeypatch.setattr("app.assembly.parse_pdf_bytes", lambda raw: raw)
    return _PdfDownloadParser(client, sleep=lambda seconds: sleeps.append(seconds))


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
    `parse_pdf_bytes_batch` positionally matched to its ref."""

    def handler(request: httpx.Request) -> httpx.Response:
        paper_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=f"%PDF-{paper_id}".encode())

    calls: list[list[bytes]] = []

    def fake_parse_batch(contents: list[bytes]) -> list[str]:
        calls.append(contents)
        return [c.decode() for c in contents]

    monkeypatch.setattr("app.assembly.parse_pdf_bytes_batch", fake_parse_batch)
    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)
    refs = [_make_ref("2504.00001"), _make_ref("2504.00002")]

    result = parser.parse_batch(refs)

    assert calls == [[b"%PDF-2504.00001", b"%PDF-2504.00002"]]
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

    def fake_parse_pdf_bytes_batch(contents: list[bytes]) -> list[str]:
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
        "app.assembly.parse_pdf_bytes_batch", lambda contents: [c.decode() for c in contents]
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
        "app.assembly.parse_pdf_bytes_batch", lambda contents: [c.decode() for c in contents]
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
