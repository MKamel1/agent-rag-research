"""Unit tests for `app.assembly._PdfDownloadParser` (T-DOC4) — offline, no real network/GPU.

Covers the inter-request delay added to close the real-run risk of tripping arXiv's rate
limiting across ~100-120 sequential PDF downloads (see `_PDF_DOWNLOAD_DELAY_SECONDS` in
`app/assembly.py` for the reasoning). Uses `httpx.MockTransport` for the HTTP layer (same
offline pattern as `rag/test_embedder.py`) and an injected `sleep` hook that records its calls
instead of really sleeping (same pattern as `rag.harvester.ArxivSource`/its test suite).
"""

from datetime import date

import httpx
import pytest

from app.assembly import _PdfDownloadParser
from contracts.errors import PermanentError
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

    parser.parse(_make_ref("2504.00001"))
    parser.parse(_make_ref("2504.00002"))

    assert sleeps == [1.5, 1.5], "each download must be followed by the fixed inter-request delay"


def test_delay_still_applies_when_the_download_fails(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    sleeps: list[float] = []
    parser = _make_parser(monkeypatch, handler, sleeps)

    with pytest.raises(PermanentError):
        parser.parse(_make_ref())

    assert sleeps == [1.5], "a failed download still counts against the rate limit"
