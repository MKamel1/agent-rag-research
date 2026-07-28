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


def test_detect_arxiv_id_from_filename_with_trailing_title():
    """T-DOC82: the bare-id match must anchor at the START of the stem, not require an exact
    full-stem match -- real drop-in files like "<id> - Title.pdf" must still resolve to real
    arXiv metadata rather than silently minting a content-addressed `local:` id (which is
    sticky: re-dropping the same bytes under a corrected filename mints the same id again)."""
    assert (
        detect_arxiv_id("2409.01266v2 - Causal Discovery.pdf", "") == "2409.01266"
    )


def test_detect_arxiv_id_from_first_page_text():
    assert detect_arxiv_id("pearl-book.pdf", "... arXiv:2409.01266v1 [stat.ME] ...") == "2409.01266"


def test_detect_arxiv_id_none_for_plain_pdf():
    assert detect_arxiv_id("causality-pearl.pdf", "Causality: Models, Reasoning...") is None


def test_bare_decimal_in_body_text_is_not_an_arxiv_id():
    """A body-text decimal shaped like an arXiv id (4 digits, dot, 4-5 digits -- e.g. a table or
    equation number) must not false-positive into the arXiv lookup path (T-DOC82) unless it
    carries an explicit arXiv prefix or IS the whole filename stem. (The brief's literal example,
    "Table 4.12345", doesn't actually reproduce the old bug -- "4" is only one digit before the
    dot, so even the old \\d{4}\\.\\d{4,5} regex never matched it; this uses a number shaped to
    actually trigger the old bare-anywhere match.)"""
    assert detect_arxiv_id("causality-pearl.pdf", "See Table 1234.56789 for results") is None


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
# mint_local_ref -- explicit `title--` marker (T-DOC88)
# ---------------------------------------------------------------------------


def test_mint_local_ref_title_prefix_used():
    raw = _synthetic_pdf_bytes()
    ref = mint_local_ref(
        raw, "title--Causal Inference in Python.pdf", "book", date(2026, 7, 25)
    )
    assert ref.title == "Causal Inference in Python"


def test_mint_local_ref_title_prefix_case_insensitive():
    raw = _synthetic_pdf_bytes()
    ref = mint_local_ref(raw, "TITLE--Causal Inference.pdf", "book", date(2026, 7, 25))
    assert ref.title == "Causal Inference"
    ref2 = mint_local_ref(raw, "Title--Causal Inference.pdf", "book", date(2026, 7, 25))
    assert ref2.title == "Causal Inference"


def test_mint_local_ref_title_prefix_strips_surrounding_whitespace_only():
    """The remainder is stripped, but NOT further transformed -- no underscore-to-space, no
    title-casing. The operator typed what they wanted (T-DOC88)."""
    raw = _synthetic_pdf_bytes()
    ref = mint_local_ref(raw, "title--  causal_inference IN python .pdf", "book", date(2026, 7, 25))
    assert ref.title == "causal_inference IN python"


def test_mint_local_ref_title_prefix_empty_remainder_falls_through():
    raw = _synthetic_pdf_bytes()  # no metadata, no first-page text
    ref = mint_local_ref(raw, "title--.pdf", "book", date(2026, 7, 25))
    assert ref.title == "title--"  # falls through to the stem, unmodified by the marker


def test_mint_local_ref_title_prefix_applies_to_papers_too():
    """No doc_type branch -- a paper with bad metadata benefits identically (T-DOC88)."""
    raw = _synthetic_pdf_bytes()
    ref = mint_local_ref(raw, "title--A Real Paper Title.pdf", "paper", date(2026, 7, 25))
    assert ref.title == "A Real Paper Title"


def test_mint_local_ref_title_prefix_does_not_change_content_addressed_id():
    """Renaming a file (adding/removing the `title--` marker) must never change its `paper_id` --
    it stays `sha256(pdf_bytes)[:12]`, load-bearing for an upcoming re-ingest (T-DOC88)."""
    raw = _synthetic_pdf_bytes()
    plain = mint_local_ref(raw, "my-book.pdf", "book", date(2026, 7, 25))
    prefixed = mint_local_ref(raw, "title--My Book.pdf", "book", date(2026, 7, 25))
    assert plain.paper_id == prefixed.paper_id


def test_mint_local_ref_no_prefix_title_unchanged():
    """Regression pin: a file WITHOUT the `title--` prefix must produce EXACTLY the title today's
    fallback chain already produces -- this is the assertion protecting the 11k-paper corpus and
    today's book behavior from an accidental change in T-DOC88. The golden fixture has no PDF
    metadata Title, so this exercises the `_first_nonempty_line` rung of the chain."""
    raw = GOLDEN_PDF.read_bytes()
    ref = mint_local_ref(raw, "2409.01266.pdf", "paper", date(2026, 7, 25))
    assert ref.title == "Double Machine Learning meets Panel Data - Promises, Pitfalls,"


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


def _fake_config_with_disabled_cache(tmp_path: Path) -> Config:
    """`pdf_cache_dir=""` is a documented, supported value elsewhere (contracts/config.py: ""
    disables the cache) but this module's whole staging mechanism depends on a working cache dir
    -- see test_main_disabled_pdf_cache_refuses_to_stage below."""
    return Config(
        focus_area_queries=["causal inference"],
        drop_in_dir=str(tmp_path / "drop"),
        pdf_cache_dir="",
    )


def test_dry_run_stages_nothing_and_writes_no_manifest(tmp_path, monkeypatch, caplog):
    # T-DOC86: dropping a wrong file into a directory is a much easier mistake than writing a
    # wrong arXiv query, and a book costs GPU-minutes to find out.
    monkeypatch.setattr("app.ingest_local.load_config", lambda: _fake_config(tmp_path))
    _stage_one_synthetic_paper(tmp_path)
    drop_dir = tmp_path / "drop"
    cache_dir = tmp_path / "cache"

    with caplog.at_level("INFO", logger="app.ingest_local"):
        exit_code = main(["--dry-run"])

    assert exit_code == 0
    assert list(cache_dir.glob("*.pdf")) == []
    assert list(drop_dir.glob("manifest-*.txt")) == []
    # scan_drop_dir was never called (early return), so done/ was never even created.
    assert not (drop_dir / "done").exists()
    assert "book.pdf" in caplog.text
    # `_stage_one_synthetic_paper` writes "book.pdf" into `papers/` despite its name -- doc_type
    # comes from the SUBFOLDER, not the filename, and must be reported so an operator can catch a
    # book mistakenly dropped in papers/ (cross-task fix #5) before it costs GPU-hours.
    assert "doc_type: paper" in caplog.text
    assert "1 file(s) would be staged" in caplog.text


def test_dry_run_reports_doc_type_book_for_a_file_in_books(tmp_path, monkeypatch, caplog):
    # Cross-task fix #5: doc_type is what selects summarize_book over the truncating paper path,
    # so the dry-run preview must show it per file, sourced from the subfolder like scan_drop_dir.
    monkeypatch.setattr("app.ingest_local.load_config", lambda: _fake_config(tmp_path))
    books_dir = tmp_path / "drop" / "books"
    books_dir.mkdir(parents=True)
    (books_dir / "textbook.pdf").write_bytes(_synthetic_pdf_bytes())

    with caplog.at_level("INFO", logger="app.ingest_local"):
        exit_code = main(["--dry-run"])

    assert exit_code == 0
    assert "textbook.pdf" in caplog.text
    assert "doc_type: book" in caplog.text
    # mint_local_ref must have been called with the real "book" doc_type, not a hardcoded "paper"
    # -- a local: id is content-addressed and doesn't itself encode doc_type, but a wrong doc_type
    # passed in would still be a silent lie about what was previewed.
    assert "id:      local:" in caplog.text


def test_dry_run_skips_a_corrupt_pdf_and_continues(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("app.ingest_local.load_config", lambda: _fake_config(tmp_path))
    papers_dir = tmp_path / "drop" / "papers"
    papers_dir.mkdir(parents=True)
    (papers_dir / "good.pdf").write_bytes(_synthetic_pdf_bytes())
    (papers_dir / "bad.pdf").write_bytes(b"not a pdf")
    drop_dir = tmp_path / "drop"
    cache_dir = tmp_path / "cache"

    with caplog.at_level("INFO", logger="app.ingest_local"):
        exit_code = main(["--dry-run"])

    assert exit_code == 0
    assert list(cache_dir.glob("*.pdf")) == []
    assert not (drop_dir / "failed").exists()  # dry-run never quarantines
    assert "good.pdf" in caplog.text
    # Cross-task fix #8: bad.pdf is skipped (never previewed, and stage_file would quarantine it
    # to failed/, not stage it) -- the count must reflect files actually previewed, not every PDF
    # found.
    assert "1 file(s) would be staged" in caplog.text


def test_dry_run_reports_resolved_title(tmp_path, monkeypatch, caplog):
    """T-DOC88: the dry-run preview must surface the resolved title -- an operator who forgot a
    `title--` marker sees the wrong title before any GPU time is spent, rather than discovering it
    in the corpus afterwards."""
    monkeypatch.setattr("app.ingest_local.load_config", lambda: _fake_config(tmp_path))
    books_dir = tmp_path / "drop" / "books"
    books_dir.mkdir(parents=True)
    (books_dir / "title--Causal Inference in Python.pdf").write_bytes(_synthetic_pdf_bytes())

    with caplog.at_level("INFO", logger="app.ingest_local"):
        exit_code = main(["--dry-run"])

    assert exit_code == 0
    assert "title:   Causal Inference in Python" in caplog.text


def test_main_disabled_pdf_cache_refuses_to_stage(tmp_path, monkeypatch):
    """`pdf_cache_dir=""` means "cache disabled" (contracts/config.py). This module's staged files
    are cache-first entries `app.assembly.harvest_refs` reads back -- with the cache disabled,
    `harvest_refs` falls through to a live arXiv fetch for every id, including `local:`-prefixed
    ones arXiv can't resolve, and silently drops them from the corpus (harvest_refs' own documented
    contract). `main()` must refuse up front rather than stage files that then silently vanish."""
    monkeypatch.setattr(
        "app.ingest_local.load_config", lambda: _fake_config_with_disabled_cache(tmp_path)
    )
    scan_calls = []
    monkeypatch.setattr(
        "app.ingest_local.scan_drop_dir", lambda *a, **k: scan_calls.append((a, k))
    )
    _stage_one_synthetic_paper(tmp_path)

    exit_code = main([])

    assert exit_code != 0
    assert scan_calls == []
    assert list((tmp_path / "drop").glob("manifest-*.txt")) == []
    # The source file must be untouched -- nothing "staged" into done/ either.
    assert (tmp_path / "drop" / "papers" / "book.pdf").exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
