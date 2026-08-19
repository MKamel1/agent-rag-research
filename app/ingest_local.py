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
   into (`ref.model_copy(update={"doc_type": doc_type, ...})` -- the folder wins over the fetched
   ref's own default, since e.g. a thesis dropped under `books/` IS an arXiv paper but should
   still be treated as a book). An explicit `title--` filename marker (T-DOC88) wins over the
   fetched title the same way -- a deliberate operator override outranks fetched metadata.
2. Anything else (a real book, a fetch failure, a paper arXiv just doesn't have) mints a
   content-addressed `local:<sha256-prefix>` id (`mint_local_ref`) -- same bytes always produce
   the same id regardless of filename, so re-dropping identical content is idempotent by
   construction.

A metadata-fetch failure (`fetch_by_ids` raising, or returning no match) NEVER fails the file --
it just falls back to path 2. Only a PDF pypdfium2 genuinely cannot open is a hard failure: the
source file moves to `failed/` with a sibling `.err` file, and `scan_drop_dir` continues past it.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

import pypdfium2 as pdfium
from pypdfium2._helpers.misc import PdfiumError

from app.assembly import _fetch_by_ids_with_backoff
from app.prefetch_pdfs import _pdf_path, _write_sidecar
from contracts.harvester import PaperRef
from rag.config import load_config
from rag.harvester import ArxivSource

logger = logging.getLogger(__name__)

# Matches a base arXiv id (new-style "YYMM.NNNNN", 4-5 digit suffix) explicitly flagged by an
# "arXiv:" prefix, with an optional "vN" version suffix -- the shape a PDF's own first-page
# banner uses ("arXiv:2409.01266v1 [stat.ME]").
_ARXIV_ID_PREFIXED = re.compile(r"arxiv[:\s/]*(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
# Matches the SAME id shape standing alone as the entire filename stem -- how arXiv PDFs are
# actually named ("2409.01266v2.pdf"). Deliberately NOT used against page text: a bare
# `\d{4}\.\d{4,5}` anywhere in body prose false-positives on things like a table/equation number
# ("Table 1234.5678") (T-DOC82) -- unlike a filename stem, page text has no "this whole string IS
# the id" guarantee.
_ARXIV_ID_BARE = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?\b")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")

# T-DOC88: an operator-opt-in filename prefix that marks the rest of the stem as the authoritative
# title -- e.g. "title--Causal Inference in Python.pdf". Deliberately not a heuristic blocklist of
# download-name shapes (T-DOC82 already rejected that as endless) and not "always prefer the
# stem" (libgen-style download names like "Matheus Facure - Causal Inference in Python_ ... -
# libgen.li.pdf" would make terrible titles) -- an explicit marker is the only deterministic way
# to state a title without either problem.
TITLE_PREFIX = "title--"


def detect_arxiv_id(filename: str, first_page_text: str) -> str | None:
    """Filename checked before content -- cheaper, and a deliberately-named file
    ("2409.01266v2.pdf") is a stronger signal than a substring match inside page text.

    An id must either carry an explicit "arXiv" prefix (filename or page text), or START the
    filename stem (e.g. "2409.01266v2 - Causal Discovery.pdf") -- a bare decimal number floating
    in body text (e.g. a table/equation number like "1234.5678") is NOT enough (T-DOC82)."""
    bare = _ARXIV_ID_BARE.match(Path(filename).stem)
    if bare:
        return bare.group(1)
    for source in (filename, first_page_text):
        m = _ARXIV_ID_PREFIXED.search(source)
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
        # Metadata is optional garnish (module docstring) -- logged for visibility, never
        # propagated. `stage_file` has already gated out genuinely unopenable PDFs before this
        # point, so a failure here is an unexpected anomaly worth a trace, not routine noise.
        logger.exception("ingest_local: could not read PDF metadata, continuing without it")
        return None, None
    return meta.get("Title"), meta.get("Author")


# Titles that are technically non-empty and technically what the PDF says, but are not the paper's
# title. Two sources, both observed in this corpus: PDF metadata written by the authoring tool
# ("untitled", "PowerPoint Presentation", "Microsoft Word - draft3.docx", "P398-cd.dvi" -- a LaTeX
# intermediate filename), and page furniture picked up as page 1's first line ("1", "February 2021",
# "Paper Number"). A junk title is not cosmetic: it silently defeats every title-based lookup, and
# in this corpus the Waymo Safety Report was stored as "February 2021" and an IWAI poster as
# "PowerPoint Presentation", so both were invisible to a title search that should have found them.
_JUNK_TITLE_PATTERNS = (
    r"^untitled$", r"^powerpoint presentation$", r"^microsoft word", r"^document\d*$",
    r"^paper number$", r"^fact sheet:?$", r"^an overview$",
    r"\.(dvi|doc|docx|indd|tex|pdf|pptx?)$",           # authoring-tool filenames
    r"^[\d\W]+$",                                       # digits/punctuation only -- page numbers
    r"^[\u2022\u25cf\u00b7*\-\u2013\u2014]\s",              # a bullet point, not a heading
    r"<[a-z/][^>]*>",                                   # markup fragment (e.g. "<sup>[1]</sup>")
    r"^(issn|isbn|doi)\b",                              # identifier lines
    r"[$\\]",                                           # LaTeX/math markup -- body text
    r"^(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{4}$",                                       # a date line
)
_MIN_TITLE_WORDS = 3


def _looks_like_a_title(candidate: str | None) -> bool:
    """A candidate is usable if it is not obviously page furniture or tool metadata.

    Deliberately conservative -- a wrongly REJECTED good title just falls through to the next
    candidate in `mint_local_ref`'s chain, while a wrongly ACCEPTED junk one becomes the paper's
    identity everywhere it is displayed or searched. The asymmetry is the whole reason for the
    word-count floor: real paper titles are several words long, and almost nothing that is 1-2
    words is a title rather than a header fragment.
    """
    if candidate is None:
        return False
    text = candidate.strip()
    if not text:
        return False
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _JUNK_TITLE_PATTERNS):
        return False
    return len(text.split()) >= _MIN_TITLE_WORDS


def _first_nonempty_line(text: str) -> str | None:
    """First line of page 1 that actually looks like a title, not merely the first non-blank one.

    Scans a bounded window rather than stopping at line 1: a running header, a page number or a
    date routinely occupies the first line or two of an extracted page, and taking it produced
    titles like "1" and "February 2021" in this corpus.
    """
    fallback = None
    for line in text.splitlines()[:15]:
        stripped = line.strip()
        if not stripped:
            continue
        if fallback is None:
            fallback = stripped
        if _looks_like_a_title(stripped):
            return stripped
    # Nothing title-shaped in the window -- hand back the old behaviour's answer rather than None,
    # so this can only ever improve on the previous result, never erase one.
    return fallback


def _explicit_title(filename: str) -> str | None:
    """The operator's own title, opted in via a `TITLE_PREFIX` filename prefix (T-DOC88).
    Matched case-insensitively on the stem -- a silent fall-through over capitalization (e.g.
    "Title--...") would be a footgun nobody notices until the corpus is inspected. Returns None
    (fall through to `mint_local_ref`'s normal chain) when the prefix is absent, or when the
    remainder is empty/whitespace-only (`title--.pdf` must not mint an empty title). The
    remainder is stripped but otherwise passed through verbatim -- no underscore-to-space, no
    title-casing; the operator typed what they wanted."""
    stem = Path(filename).stem
    if not stem.lower().startswith(TITLE_PREFIX):
        return None
    return stem[len(TITLE_PREFIX):].strip() or None


def mint_local_ref(pdf_bytes: bytes, filename: str, doc_type: str, mtime: date) -> PaperRef:
    """Content-addressed `local:<12-hex>` id -- same bytes always mint the same id regardless of
    `filename`, so re-staging identical content is idempotent (`stage_file`'s docstring). Title
    falls back through an explicit `title--` filename marker (T-DOC88) -> PDF metadata -> first
    non-empty line of page 1 -> the filename's own stem; `published` falls back to a 19xx/20xx
    year found on page 1, else the file's own `mtime`.
    """
    digest = hashlib.sha256(pdf_bytes).hexdigest()[:12]
    title_meta, author_meta = _pdf_title_author(pdf_bytes)
    first_page = _safe_first_page(pdf_bytes)
    # `_explicit_title` short-circuits the title SEARCH below via `or` -- but both calls above
    # still run regardless of a marker: `_pdf_title_author` also yields `author_meta` (used for
    # `authors=` below) and `_safe_first_page` feeds the `published` year regex further down. A
    # marker only supersedes the title, not those other fields, so neither call can be skipped.
    # Metadata is consulted first but only if it is title-shaped: an authoring tool's default
    # ("untitled", "PowerPoint Presentation") is worse than the paper's own first heading, which is
    # what the next link in the chain recovers.
    title = (
        _explicit_title(filename)
        or (title_meta if _looks_like_a_title(title_meta) else None)
        or _first_nonempty_line(first_page)
        or title_meta                     # junk metadata still beats a bare filename stem
        or Path(filename).stem
    )
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
            # -- a metadata-fetch hiccup must never fail the whole file (module docstring). Logged
            # (not silent) since it's a real, if non-fatal, degradation worth knowing about.
            logger.exception(
                "ingest_local: arXiv metadata fetch failed for id=%r, falling back to a local: id",
                arxiv_id,
            )
            fetched = []
        if fetched:
            # The drop folder's doc_type wins over the fetched ref's own (always "paper")
            # default -- see module docstring point 1. An explicit title-- marker (T-DOC88 fix
            # round 2) wins over the fetched title too: it's a deliberate operator override, and
            # the operator's ruling is that a deliberate marker outranks fetched metadata.
            # Everything else about the fetched ref (authors, abstract, categories, published,
            # paper_id, version) is left exactly as arXiv supplied it -- only doc_type and title
            # are ever overridden here.
            update: dict[str, object] = {"doc_type": doc_type}
            explicit_title = _explicit_title(path.name)
            if explicit_title is not None:
                update["title"] = explicit_title
            ref = fetched[0].model_copy(update=update)
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


def _fetch_by_ids(ids: list[str]) -> list[PaperRef]:
    """Production `fetch_by_ids` for `main()` -- reuses `app.assembly`'s already 429-resilient
    backoff wrapper (T-DOC49) instead of reimplementing arXiv retry logic here."""
    return _fetch_by_ids_with_backoff(ArxivSource(), ids, sleep=time.sleep)


def _write_manifest(drop_dir: Path, paper_ids: list[str]) -> Path:
    """`drop_in/manifest-<UTC timestamp>.txt`, one paper_id per line -- the exact format
    `app.ingest --paper-ids-file` already reads (`app/ingest.py::_effective_config`), also
    already used by `app/build_corpus.py::_write_batch_ids`."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = drop_dir / f"manifest-{timestamp}.txt"
    manifest_path.write_text("\n".join(paper_ids) + "\n")
    return manifest_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage-only", action="store_true",
        help="Stage drop_in/ files into pdf_cache and write the manifest, but don't invoke "
             "app.ingest",
    )
    parser.add_argument(
        "--drop-dir", default=None, metavar="PATH",
        help="Override cfg.drop_in_dir for this run",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what WOULD be staged -- detected id and the first lines of extracted text "
             "per file -- without staging anything or invoking app.ingest",
    )
    return parser.parse_args(argv)


def _report_dry_run(drop_dir: Path) -> int:
    """T-DOC86: print enough of each file for an operator to spot a wrong one, and stage nothing.

    Scans `papers/` and `books/` the same way `scan_drop_dir` does (same subfolder-then-filename
    traversal order) -- a dropped file only ever lands there (module docstring), never loose at
    the top of `drop_dir`. Also reports `doc_type`: it's what selects `summarize_book` over the
    truncating paper path, so a book mistakenly dropped in `papers/` costs GPU-hours and produces
    one truncated summary -- the exact mistake this preview exists to catch.

    Deliberately not a relevance *score*: thresholding a summary against `focus_area` needs a
    cutoff nobody has data to set, and would only run after parse+summarize have already been
    paid for. This costs one read and no model.
    """
    files = [
        (path, doc_type)
        for sub, doc_type in (("papers", "paper"), ("books", "book"))
        for path in sorted((drop_dir / sub).glob("*.pdf"))
    ]
    if not files:
        logger.info("ingest_local --dry-run: no PDFs in %s", drop_dir)
        return 0
    previewed = 0
    for path, doc_type in files:
        raw = path.read_bytes()
        try:
            first_page_text = _first_page_text(raw)
        except PdfiumError as error:
            # Same gate stage_file uses for a genuinely unreadable PDF (module docstring) -- one
            # bad file must not abort the preview of every other file. Not counted below: it
            # would never reach stage_file's actual quarantine-to-failed/ path either.
            logger.warning("ingest_local --dry-run: could not read %s (%s), skipping", path.name, error)
            continue
        arxiv_id = detect_arxiv_id(path.name, first_page_text)
        mtime = date.fromtimestamp(path.stat().st_mtime)
        # Reuse mint_local_ref's own title resolution (T-DOC88) rather than re-deriving it here --
        # a duplicate title chain could silently drift from what actually gets stored. An explicit
        # title-- marker is shown as-is regardless of arxiv_id: T-DOC88 fix round 2 made
        # stage_file's arXiv branch apply the marker over a fetched title too (it's a deliberate
        # operator override and wins over everything), so the preview is now accurate in both
        # branches. Absent a marker, when arxiv_id is set, the real staged title comes from
        # fetch_by_ids instead -- mint_local_ref's fallback chain (PDF metadata / first line /
        # stem) was never going to be used, so showing it here would be misleading; the label is
        # the honest answer, and --dry-run stays offline (no fetch_by_ids call).
        ref = mint_local_ref(raw, path.name, doc_type, mtime)
        paper_id = arxiv_id or ref.paper_id
        explicit_title = _explicit_title(path.name)
        if explicit_title is not None:
            title_display = explicit_title
        elif arxiv_id is not None:
            title_display = "(from arXiv metadata, not previewed offline)"
        else:
            title_display = ref.title
        preview = first_page_text[:500].replace("\n", " ")
        logger.info(
            "\n--- %s\n    doc_type: %s\n    id:      %s\n    title:   %s\n    preview: %s",
            path.name, doc_type, paper_id, title_display, preview,
        )
        previewed += 1
    logger.info(
        "ingest_local --dry-run: %d file(s) would be staged. Re-run without --dry-run to "
        "proceed, or move unwanted files out of %s first.", previewed, drop_dir,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    # Matches app/prefetch_pdfs.py::main's own __main__ convention -- without this, every
    # logger.* call above is a no-op.
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)
    cfg = load_config()
    # T-DOC89 §4: report what was resolved, same pattern as app/delete_docs.py -- an operator
    # standing in the wrong directory should see where this process actually pointed, not guess.
    # drop_in_dir is included here (unlike every other T-DOC89 §4 log line) because it's the field
    # that actually decides this module's behavior -- the directory it scans.
    logger.info(
        "ingest_local: resolved db_path=%s blob_dir=%s collection=%s drop_in_dir=%s",
        cfg.db_path, cfg.blob_dir, cfg.collection, cfg.drop_in_dir,
    )
    if not cfg.pdf_cache_dir:
        # contracts/config.py: "" is a supported, documented way to disable the PDF cache
        # elsewhere in this codebase -- but this module's entire staging mechanism depends on it.
        # Every staged file is a cache-first entry (module docstring); with the cache disabled,
        # app.assembly.harvest_refs falls through to a live arXiv fetch for every id, including
        # `local:`-prefixed ones arXiv can't resolve, and silently drops them from the returned
        # corpus (harvest_refs' own documented contract) -- a real silent-data-loss footgun for
        # exactly the scenario this feature exists to support. Refuse up front instead.
        logger.error(
            "ingest_local: cfg.pdf_cache_dir is empty (cache disabled) -- ingest_local requires "
            "a working pdf_cache_dir, since staged files are cache-first entries that "
            "app.assembly.harvest_refs would otherwise silently drop. Set pdf_cache_dir and "
            "re-run."
        )
        return 1
    drop_dir = Path(args.drop_dir) if args.drop_dir is not None else Path(cfg.drop_in_dir)
    cache_dir = Path(cfg.pdf_cache_dir)

    if args.dry_run:
        return _report_dry_run(drop_dir)

    staged = scan_drop_dir(drop_dir, cache_dir, fetch_by_ids=_fetch_by_ids)
    if not staged:
        logger.info("ingest_local: drop dir %s empty, nothing staged", drop_dir)
        return 0

    manifest_path = _write_manifest(drop_dir, staged)
    logger.info(
        "ingest_local: staged %d file(s), manifest written to %s", len(staged), manifest_path,
    )

    if args.stage_only:
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "app.ingest", "--paper-ids-file", str(manifest_path)],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
