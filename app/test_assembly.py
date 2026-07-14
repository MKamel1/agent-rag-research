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
