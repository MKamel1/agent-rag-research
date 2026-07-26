"""`app/ingest_local.py` -- staging core for the drop-in folder (T-DOC80, spec:
docs/superpowers/specs/2026-07-25-drop-in-folder-and-books-design.md).

Zero network: `fetch_by_ids` is always an injected fake here (real network resilience is
`app/assembly.py::_fetch_by_ids_with_backoff`'s job, already covered by its own tests). PDF
parsing goes through the REAL `pypdfium2`, using the committed `fixtures/golden/*.pdf` fixtures
(real arXiv PDFs, each self-identifying via an `arXiv:<id>` banner on page 1) plus a small
pypdfium2-built synthetic PDF (same pattern `rag/test_parser.py::_one_page_pdf_bytes` already
uses) for the one scenario that needs a PDF with NO arXiv id anywhere in it -- every golden
fixture IS an arXiv paper, so none of them can stand in for a non-arXiv drop.

The round-trip test (`test_stage_file_arxiv_path`) reads the staged sidecar back through the
REAL, unmodified `app.assembly._cached_ref` -- the whole point of reusing
`app.prefetch_pdfs._write_sidecar` instead of writing a second sidecar serializer that could
silently drift from what `_cached_ref` expects.
"""

import io
import sys
from datetime import date
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from app.assembly import _cached_ref
from app.ingest_local import (
    detect_arxiv_id,
    main,
    mint_local_ref,
    scan_drop_dir,
    stage_file,
)
from contracts.config import Config
from contracts.errors import TransientError
from contracts.harvester import PaperRef

_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "golden"
GOLDEN_PDF = _GOLDEN_DIR / "2409.01266.pdf"


def _synthetic_pdf_bytes() -> bytes:
    """A real, pypdfium2-parseable one-page PDF with no text and no metadata -- unlike every
    committed golden fixture (each one IS an arXiv paper, self-identifying via its own page-1
    `arXiv:<id>` banner), this has no arXiv id anywhere, filename or content. Same
    `PdfDocument.new()` pattern `rag/test_parser.py::_one_page_pdf_bytes` already uses."""
    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 200)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _known_ref(paper_id: str, doc_type: str = "paper") -> PaperRef:
    return PaperRef(
        paper_id=paper_id,
        version="v1",
        title=f"Fetched title for {paper_id}",
        abstract="a real abstract",
        authors=["A. Author"],
        categories=["stat.ME"],
        published=date(2024, 9, 1),
        updated=date(2024, 9, 1),
        pdf_url=f"https://arxiv.org/pdf/{paper_id}v1",
        doc_type=doc_type,
    )


class _RaisingFetcher:
    def __call__(self, ids):
        raise TransientError("arXiv is down")


class _EmptyFetcher:
    """Simulates 'no match' -- forces every ref through `mint_local_ref`, regardless of whether
    an arXiv id was detected in the source PDF's own content."""

    def __call__(self, ids):
        return []


# ---------------------------------------------------------------------------
# detect_arxiv_id
# ---------------------------------------------------------------------------


def test_detect_arxiv_id_from_filename():
    assert detect_arxiv_id("2409.01266v2.pdf", "") == "2409.01266"


def test_detect_arxiv_id_from_first_page_text():
    assert detect_arxiv_id("pearl-book.pdf", "... arXiv:2409.01266v1 [stat.ME] ...") == "2409.01266"


def test_detect_arxiv_id_none_for_plain_pdf():
    assert detect_arxiv_id("causality-pearl.pdf", "Causality: Models, Reasoning...") is None


# ---------------------------------------------------------------------------
# mint_local_ref
# ---------------------------------------------------------------------------


def test_mint_local_ref_is_content_addressed_and_deterministic():
    ref1 = mint_local_ref(b"same bytes", "a.pdf", "book", date(2026, 7, 25))
    ref2 = mint_local_ref(b"same bytes", "b.pdf", "book", date(2026, 7, 25))
    assert ref1.paper_id == ref2.paper_id and ref1.paper_id.startswith("local:")
    assert len(ref1.paper_id) == len("local:") + 12
    assert ref1.doc_type == "book" and ref1.pdf_url == "a.pdf"


def test_mint_local_ref_different_bytes_different_id():
    ref1 = mint_local_ref(b"bytes one", "a.pdf", "paper", date(2026, 7, 25))
    ref2 = mint_local_ref(b"bytes two", "a.pdf", "paper", date(2026, 7, 25))
    assert ref1.paper_id != ref2.paper_id


def test_mint_local_ref_falls_back_to_filename_stem_title():
    raw = _synthetic_pdf_bytes()  # no metadata, no first-page text
    ref = mint_local_ref(raw, "my-book-notes.pdf", "book", date(2026, 7, 25))
    assert ref.title == "my-book-notes"


# ---------------------------------------------------------------------------
# stage_file
# ---------------------------------------------------------------------------


def test_stage_file_arxiv_path(tmp_path):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    src = papers_dir / "2409.01266.pdf"
    src.write_bytes(GOLDEN_PDF.read_bytes())
    cache_dir = tmp_path / "cache"

    calls = []

    def fetch_by_ids(ids):
        calls.append(list(ids))
        return [_known_ref("2409.01266")]

    paper_id = stage_file(src, "paper", cache_dir, fetch_by_ids=fetch_by_ids)

    assert paper_id == "2409.01266"
    assert calls == [["2409.01266"]]
    assert not src.exists()
    assert (tmp_path / "done" / "2409.01266.pdf").exists()
    assert (cache_dir / "2409.01266.pdf").read_bytes() == GOLDEN_PDF.read_bytes()
    assert (cache_dir / "2409.01266.json").exists()

    # The whole point: round-trip through the REAL, unmodified reader `app.assembly._cached_ref`
    # uses in production -- not a reimplemented check of our own sidecar format.
    reconstructed = _cached_ref(cache_dir, "2409.01266")
    assert reconstructed is not None
    assert reconstructed.paper_id == "2409.01266"
    assert reconstructed.title == "Fetched title for 2409.01266"
    assert reconstructed.doc_type == "paper"


def test_stage_file_sets_doc_type_from_caller_even_on_fetched_ref(tmp_path):
    """A file dropped under books/ but recognized as a real arXiv paper (e.g. a thesis) still
    gets tagged doc_type="book" -- the folder the file arrived in wins, not the fetched ref's own
    (always "paper") default."""
    books_dir = tmp_path / "books"
    books_dir.mkdir()
    src = books_dir / "2409.01266.pdf"
    src.write_bytes(GOLDEN_PDF.read_bytes())
    cache_dir = tmp_path / "cache"

    paper_id = stage_file(
        src, "book", cache_dir, fetch_by_ids=lambda ids: [_known_ref("2409.01266")]
    )

    assert paper_id == "2409.01266"
    reconstructed = _cached_ref(cache_dir, "2409.01266")
    assert reconstructed.doc_type == "book"


def test_stage_file_arxiv_fetch_failure_falls_back_to_local_id(tmp_path):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    src = papers_dir / "2409.01266.pdf"
    raw = GOLDEN_PDF.read_bytes()
    src.write_bytes(raw)
    cache_dir = tmp_path / "cache"

    paper_id = stage_file(src, "paper", cache_dir, fetch_by_ids=_RaisingFetcher())

    assert paper_id is not None
    assert paper_id.startswith("local:")
    assert not src.exists()
    assert (tmp_path / "done" / "2409.01266.pdf").exists()
    reconstructed = _cached_ref(cache_dir, paper_id)
    assert reconstructed is not None
    assert reconstructed.doc_type == "paper"


def test_stage_file_non_arxiv_uses_pdf_meta_or_filename_title(tmp_path):
    books_dir = tmp_path / "books"
    books_dir.mkdir()
    src = books_dir / "my-notes.pdf"
    src.write_bytes(_synthetic_pdf_bytes())
    cache_dir = tmp_path / "cache"

    def fetch_by_ids(ids):
        raise AssertionError("no arXiv id should have been detected -- fetch must not be called")

    paper_id = stage_file(src, "book", cache_dir, fetch_by_ids=fetch_by_ids)

    assert paper_id is not None
    assert paper_id.startswith("local:")
    reconstructed = _cached_ref(cache_dir, paper_id)
    assert reconstructed.title == "my-notes"
    assert reconstructed.doc_type == "book"


def test_stage_file_corrupt_pdf_goes_to_failed_with_err_file(tmp_path):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    src = papers_dir / "bad.pdf"
    src.write_bytes(b"not a pdf")
    cache_dir = tmp_path / "cache"

    def fetch_by_ids(ids):
        raise AssertionError("must not be reached -- the file never got far enough to detect an id")

    paper_id = stage_file(src, "paper", cache_dir, fetch_by_ids=fetch_by_ids)

    assert paper_id is None
    assert not src.exists()
    assert (tmp_path / "failed" / "bad.pdf").exists()
    err_path = tmp_path / "failed" / "bad.pdf.err"
    assert err_path.exists()
    assert err_path.read_text().strip() != ""
    assert list(cache_dir.glob("*")) == []  # nothing written to the cache for a bad file


def test_scan_drop_dir_sets_doc_type_by_subfolder(tmp_path):
    drop_dir = tmp_path / "drop"
    (drop_dir / "papers").mkdir(parents=True)
    (drop_dir / "books").mkdir(parents=True)
    (drop_dir / "papers" / "a.pdf").write_bytes(GOLDEN_PDF.read_bytes())
    other_pdf = (_GOLDEN_DIR / "2409.02332.pdf").read_bytes()
    (drop_dir / "books" / "b.pdf").write_bytes(other_pdf)
    cache_dir = tmp_path / "cache"

    staged = scan_drop_dir(drop_dir, cache_dir, fetch_by_ids=_EmptyFetcher())

    assert len(staged) == 2
    assert (drop_dir / "done").is_dir()
    assert (drop_dir / "failed").is_dir()
    refs = [_cached_ref(cache_dir, pid) for pid in staged]
    doc_types = {r.doc_type for r in refs}
    assert doc_types == {"paper", "book"}


def test_scan_drop_dir_continues_after_a_corrupt_file(tmp_path):
    drop_dir = tmp_path / "drop"
    (drop_dir / "papers").mkdir(parents=True)
    (drop_dir / "papers" / "good.pdf").write_bytes(GOLDEN_PDF.read_bytes())
    (drop_dir / "papers" / "bad.pdf").write_bytes(b"garbage")
    cache_dir = tmp_path / "cache"

    staged = scan_drop_dir(drop_dir, cache_dir, fetch_by_ids=_EmptyFetcher())

    assert len(staged) == 1
    assert (drop_dir / "failed" / "bad.pdf").exists()
    assert (drop_dir / "failed" / "bad.pdf.err").exists()


def test_restage_same_file_is_idempotent(tmp_path):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    cache_dir = tmp_path / "cache"
    raw = GOLDEN_PDF.read_bytes()

    src1 = papers_dir / "book.pdf"
    src1.write_bytes(raw)
    id1 = stage_file(src1, "book", cache_dir, fetch_by_ids=_EmptyFetcher())

    # Re-drop the identical bytes under the SAME filename -- the first copy has already moved out
    # of papers/, so this is a legitimate second file, not a double-stage of one path.
    src2 = papers_dir / "book.pdf"
    src2.write_bytes(raw)
    id2 = stage_file(src2, "book", cache_dir, fetch_by_ids=_EmptyFetcher())

    assert id1 == id2  # same content -> same content-addressed local: id
    assert (tmp_path / "done" / "book.pdf").exists()
    assert (tmp_path / "done" / "book-1.pdf").exists()  # collision-safe rename, not an overwrite
    reconstructed = _cached_ref(cache_dir, id1)
    assert reconstructed is not None and reconstructed.doc_type == "book"


# ---------------------------------------------------------------------------
# main -- CLI entry point (T-DOC80 Task 8)
# ---------------------------------------------------------------------------


def _fake_config(tmp_path: Path) -> Config:
    return Config(
        focus_area_queries=["causal inference"],
        drop_in_dir=str(tmp_path / "drop"),
        pdf_cache_dir=str(tmp_path / "cache"),
    )


def _stage_one_synthetic_paper(tmp_path: Path) -> None:
    """No arXiv id anywhere in this PDF (`_synthetic_pdf_bytes`), so staging it never calls
    `fetch_by_ids` -- `main()`'s real fetcher (`ArxivSource` + backoff) is never exercised by
    these tests, only its wiring (module docstring: `fetch_by_ids` is always injected/faked in
    this test file)."""
    papers_dir = tmp_path / "drop" / "papers"
    papers_dir.mkdir(parents=True)
    (papers_dir / "book.pdf").write_bytes(_synthetic_pdf_bytes())


def test_main_stage_only_writes_manifest_and_skips_ingest(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingest_local.load_config", lambda: _fake_config(tmp_path))
    calls = []
    monkeypatch.setattr("app.ingest_local.subprocess.run", lambda *a, **k: calls.append(a))
    _stage_one_synthetic_paper(tmp_path)

    exit_code = main(["--stage-only"])

    assert exit_code == 0
    assert calls == []
    manifests = list((tmp_path / "drop").glob("manifest-*.txt"))
    assert len(manifests) == 1
    lines = [line for line in manifests[0].read_text().splitlines() if line]
    assert len(lines) == 1
    assert lines[0].startswith("local:")


def test_main_invokes_ingest_with_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingest_local.load_config", lambda: _fake_config(tmp_path))

    class _Result:
        returncode = 0

    captured = []

    def fake_run(argv, **kwargs):
        captured.append(argv)
        return _Result()

    monkeypatch.setattr("app.ingest_local.subprocess.run", fake_run)
    _stage_one_synthetic_paper(tmp_path)

    exit_code = main([])

    assert exit_code == 0
    manifests = list((tmp_path / "drop").glob("manifest-*.txt"))
    assert len(manifests) == 1
    assert captured == [
        [sys.executable, "-m", "app.ingest", "--paper-ids-file", str(manifests[0])]
    ]


def test_main_empty_drop_dir_exits_zero_without_ingest(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingest_local.load_config", lambda: _fake_config(tmp_path))
    calls = []
    monkeypatch.setattr("app.ingest_local.subprocess.run", lambda *a, **k: calls.append(a))

    exit_code = main([])

    assert exit_code == 0
    assert calls == []
    assert list((tmp_path / "drop").glob("manifest-*.txt")) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
