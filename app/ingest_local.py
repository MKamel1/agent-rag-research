"""`app/ingest_local.py` -- staging core for the drop-in folder (T-DOC80, spec:
docs/superpowers/specs/2026-07-25-drop-in-folder-and-books-design.md).

Feeds arbitrary dropped PDFs (papers or books a user places under a `drop_in/` tree) into the
SAME cache format the real ingest pipeline already reads -- `<paper_id>.pdf` +
`<paper_id>.json` sidecar under `cfg.pdf_cache_dir`. This module deliberately does not write a
second sidecar serializer: it imports and calls `app.prefetch_pdfs._write_sidecar`/`_pdf_path`
(T-DOC48) directly, so a file staged here is read back by `app.assembly._cached_ref` -- unmodified,
zero network -- exactly like a paper the standalone prefetcher already downloaded.

Two ways a dropped file gets a `paper_id`:

1. It's recognizable as a real arXiv paper (`detect_arxiv_id` finds an id in the filename or the
   PDF's own first-page text, e.g. a "arXiv:2409.01266v1" banner) -- its real metadata is fetched
   via the injected `fetch_by_ids` (production wires `app.assembly._fetch_by_ids_with_backoff`,
   already 429-resilient), tagged with the `doc_type` implied by which subfolder it was dropped
   into (`ref.model_copy(update={"doc_type": doc_type})` -- the folder wins over the fetched ref's
   own default, since e.g. a thesis dropped under `books/` IS an arXiv paper but should still be
   treated as a book).
2. Anything else (a real book, a fetch failure, a paper arXiv just doesn't have) mints a
   content-addressed `local:<sha256-prefix>` id (`mint_local_ref`) -- same bytes always produce
   the same id regardless of filename, so re-dropping identical content is idempotent by
   construction.

A metadata-fetch failure (`fetch_by_ids` raising, or returning no match) NEVER fails the file --
it just falls back to path 2. Only a PDF pypdfium2 genuinely cannot open is a hard failure: the
source file moves to `failed/` with a sibling `.err` file, and `scan_drop_dir` continues past it.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pypdfium2 as pdfium
from pypdfium2._helpers.misc import PdfiumError

from app.prefetch_pdfs import _pdf_path, _write_sidecar
from contracts.harvester import PaperRef

# Matches a base arXiv id (new-style "YYMM.NNNNN", 4-5 digit suffix) with an optional "arXiv:"
# prefix and/or "vN" version suffix -- the same shape whether it comes from a filename
# ("2409.01266v2.pdf") or a PDF's own first-page banner ("arXiv:2409.01266v1 [stat.ME]").
_ARXIV_ID = re.compile(r"(?:arXiv[:\s/]*)?\b(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def detect_arxiv_id(filename: str, first_page_text: str) -> str | None:
    """Filename checked before content -- cheaper, and a deliberately-named file
    ("2409.01266v2.pdf") is a stronger signal than a substring match inside page text."""
    for source in (filename, first_page_text):
        m = _ARXIV_ID.search(source)
        if m:
            return m.group(1)
    return None


def _first_page_text(pdf_bytes: bytes) -> str:
    """Page-1 text via pypdfium2 -- already the repo's PDF-reading dependency (`rag/parser.py`,
    `app/benchmark.py`). Raises `PdfiumError` for bytes that aren't a real PDF at all (same
    exception `rag/parser.py::_validate_pdf` guards against) -- callers use that as the
    corrupt-PDF gate. A structurally-valid but zero-page PDF returns "" rather than raising."""
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        return pdf[0].get_textpage().get_text_bounded() if len(pdf) else ""
    finally:
        pdf.close()


def _safe_first_page(pdf_bytes: bytes) -> str:
    """`_first_page_text`, but extraction failure returns "" instead of raising -- used inside
    `mint_local_ref`, whose caller (`stage_file`) has ALREADY gated out unopenable PDFs before
    ever reaching here; this stays defensive anyway since `mint_local_ref` is also called
    directly (e.g. in tests) without that prior gate."""
    try:
        return _first_page_text(pdf_bytes)
    except PdfiumError:
        return ""


def _pdf_title_author(pdf_bytes: bytes) -> tuple[str | None, str | None]:
    """Best-effort PDF metadata (Title/Author document-info keys). Never fails: metadata is
    optional garnish for `mint_local_ref`'s title fallback chain, not something worth failing a
    staging attempt over."""
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            meta = pdf.get_metadata_dict(skip_empty=True)
        finally:
            pdf.close()
    except Exception:
        return None, None
    return meta.get("Title"), meta.get("Author")


def _first_nonempty_line(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def mint_local_ref(pdf_bytes: bytes, filename: str, doc_type: str, mtime: date) -> PaperRef:
    """Content-addressed `local:<12-hex>` id -- same bytes always mint the same id regardless of
    `filename`, so re-staging identical content is idempotent (`stage_file`'s docstring). Title
    falls back through PDF metadata -> first non-empty line of page 1 -> the filename's own stem;
    `published` falls back to a 19xx/20xx year found on page 1, else the file's own `mtime`.
    """
    digest = hashlib.sha256(pdf_bytes).hexdigest()[:12]
    title_meta, author_meta = _pdf_title_author(pdf_bytes)
    first_page = _safe_first_page(pdf_bytes)
    title = title_meta or _first_nonempty_line(first_page) or Path(filename).stem
    year = _YEAR.search(first_page or "")
    published = date(int(year.group(0)), 1, 1) if year else mtime
    return PaperRef(
        paper_id=f"local:{digest}",
        version="v1",
        title=title,
        abstract="",
        authors=[author_meta] if author_meta else [],
        categories=[],
        published=published,
        updated=mtime,
        pdf_url=filename,  # provenance note -- source_url() shows this verbatim for local: ids
        doc_type=doc_type,
    )


def _unique_dest(dest_dir: Path, name: str) -> Path:
    """`dest_dir / name`, or `dest_dir / "<stem>-1<suffix>"`, `-2`, ... if that name is already
    taken -- so re-staging a same-named file never clobbers a prior arrival (idempotent restaging,
    `stage_file`'s docstring)."""
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 1
    while True:
        candidate = dest_dir / f"{stem}-{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _quarantine(path: Path, failed_dir: Path, error: str) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_dest(failed_dir, path.name)
    path.rename(dest)
    dest.with_name(dest.name + ".err").write_text(error)


def _write_pdf_cache(cache_dir: Path, paper_id: str, raw: bytes) -> None:
    """Same atomic tmp-then-rename discipline as `app.prefetch_pdfs._download_one`'s PDF write --
    a crash mid-write must never leave a partial `.pdf` that a later cache-first read mistakes for
    complete."""
    final_path = _pdf_path(cache_dir, paper_id)
    tmp_path = cache_dir / f"{paper_id}.pdf.{os.getpid()}.tmp"
    tmp_path.write_bytes(raw)
    tmp_path.rename(final_path)


def stage_file(
    path: Path,
    doc_type: str,
    cache_dir: Path,
    *,
    fetch_by_ids: Callable[[list[str]], list[PaperRef]],
) -> str | None:
    """Stage one dropped PDF into `cache_dir` (same `<paper_id>.pdf` + `.json` sidecar shape
    `app.assembly._cached_ref` reads) and move the source file out of the drop folder.

    `path` is expected under `<drop_dir>/papers/` or `<drop_dir>/books/` -- `done/`/`failed/`
    (created here if absent) are resolved as `path.parent.parent / "done"` / `"failed"`, siblings
    of `papers/`/`books/` under the same `drop_dir` (matches `scan_drop_dir`'s four-subfolder
    layout).

    Returns the `paper_id` on success (file now under `done/`), or `None` on failure (file now
    under `failed/`, with a sibling `<name>.err` describing why) -- a corrupt/unreadable PDF is
    the only failure mode; a metadata-fetch failure falls back to `mint_local_ref` instead (module
    docstring).
    """
    drop_dir = path.parent.parent
    done_dir = drop_dir / "done"
    failed_dir = drop_dir / "failed"

    raw = path.read_bytes()
    try:
        first_page_text = _first_page_text(raw)
    except PdfiumError as error:
        _quarantine(path, failed_dir, f"unreadable PDF: {error}")
        return None

    arxiv_id = detect_arxiv_id(path.name, first_page_text)
    mtime = date.fromtimestamp(path.stat().st_mtime)

    ref: PaperRef | None = None
    if arxiv_id is not None:
        try:
            fetched = fetch_by_ids([arxiv_id])
        except Exception:
            # ANY fetch failure (network, rate limit, arXiv down) falls back to a local id below
            # -- a metadata-fetch hiccup must never fail the whole file (module docstring).
            fetched = []
        if fetched:
            # The drop folder's doc_type wins over the fetched ref's own (always "paper")
            # default -- see module docstring point 1.
            ref = fetched[0].model_copy(update={"doc_type": doc_type})
    if ref is None:
        ref = mint_local_ref(raw, path.name, doc_type, mtime)

    cache_dir.mkdir(parents=True, exist_ok=True)
    _write_pdf_cache(cache_dir, ref.paper_id, raw)
    _write_sidecar(cache_dir, ref)

    done_dir.mkdir(parents=True, exist_ok=True)
    path.rename(_unique_dest(done_dir, path.name))

    return ref.paper_id


def scan_drop_dir(
    drop_dir: Path,
    cache_dir: Path,
    *,
    fetch_by_ids: Callable[[list[str]], list[PaperRef]],
) -> list[str]:
    """Stage every `*.pdf` under `drop_dir/papers/` (doc_type="paper") and `drop_dir/books/`
    (doc_type="book"), creating all four subfolders (`papers/`, `books/`, `done/`, `failed/`) if
    absent. A corrupt file is quarantined by `stage_file` and the scan continues -- one bad PDF
    never aborts the rest of the drop. Returns the `paper_id`s of every file staged successfully,
    in `papers/` then `books/` order, each sorted by filename."""
    for sub in ("papers", "books", "done", "failed"):
        (drop_dir / sub).mkdir(parents=True, exist_ok=True)

    staged: list[str] = []
    for sub, doc_type in (("papers", "paper"), ("books", "book")):
        for pdf_path in sorted((drop_dir / sub).glob("*.pdf")):
            paper_id = stage_file(pdf_path, doc_type, cache_dir, fetch_by_ids=fetch_by_ids)
            if paper_id is not None:
                staged.append(paper_id)
    return staged
