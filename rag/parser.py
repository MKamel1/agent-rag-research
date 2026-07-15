"""rag/parser.py — Parser adapter (T-B1, M2 · owner B).

Wraps MinerU (`pipeline` backend — Phase-0 Spike 1's locked choice; Docling and Marker were
evaluated and dropped, PHASE0-RUNBOOK.md's Spike-1 footnote) for PDF body parsing, and GROBID (a
separate Docker service, `/api/processCitationList`) for reference extraction. Frozen interface
(ARCHITECTURE.md §M2, `contracts/parser.py`'s module docstring): `parse(raw: bytes, paper_id:
str) -> ParsedDoc`. Only this file may import `mineru`/`grobid` tokens (CONVENTIONS §1 —
`ci/checks/vendor_isolation.py` already scopes both here).

Ambiguities the frozen interface/tests don't resolve, decided here (rather than guessed silently):

- **In-process, not a CLI subprocess.** Spike 1 measured MinerU's CLI overhead at ~25-30s/call
  (FastAPI spin-up + model reload) against ~2-4s of real GPU inference once warm. `do_parse`
  (MinerU's own CLI entry point) is imported and called in-process instead: its `ModelSingleton`
  caches the loaded model for the life of the process, so only the *first* `parse()` call pays
  model-init cost — every later call in the same process reuses it. Imported lazily inside
  `_run_mineru_pipeline`, not at module level, so importing `rag.parser` (which
  `pytest.importorskip` does for every test in this suite, including the zero-GPU negative-path
  tests) never pulls in torch/mineru unless a PDF actually reaches MinerU.

- **bbox source: `content_list.json`, rescaled via `middle.json`'s `page_size`.** MinerU's
  `*_content_list.json` already flattens each block's nested lines/spans into one `text`/
  `table_body`/`img_path` string (reusing MinerU's own `pipeline_union_make` — reimplementing that
  flattening from `middle.json`'s raw `para_blocks` would just duplicate code MinerU ships), but
  its bbox is normalized to a 0-1000 unit square *per page axis*
  (`mineru.backend.pipeline.pipeline_middle_json_mkcontent._build_bbox`:
  `int(x0 * 1000 / page_width)`), not true PDF points. `contracts/provenance.py`'s `Bbox` is
  `(x0, y0, x1, y1)` in PDF page coordinates, so every bbox pulled from `content_list.json` is
  rescaled back (`_rescale_bbox`) using each page's real `(width, height)` from `middle.json`'s
  `pdf_info[i]["page_size"]` before a `Block`/`Figure`/`TableItem` is constructed. Verified
  empirically against `.phase0-data/parser-eval/mineru/full-batch/`: a `content_list` bbox of
  `[133, 154, 862, 224]` on a `page_size=[612, 792]` page rescales to
  `[81.4, 122.0, 527.6, 177.4]`, matching `middle.json`'s own point-space bbox for the same block
  (`[82, 122, 528, 178]`) to rounding.

- **`paper_id`.** (T-DOC31.) The caller — `IngestionOrchestrator`, via `app/assembly.py`'s
  `_PdfDownloadParser` — already knows the real `paper_id` (it came from the Harvester's
  `PaperRef`) before `parse`/`parse_batch` is ever called, so both take it as a required
  parameter and use it directly; nothing here re-derives it from the PDF's own watermark text.
  Previously this adapter regex-recovered `arXiv:YYMM.NNNNN[vN]` off the page and fell back to a
  content hash (`sha256(raw).hexdigest()[:16]`) when that regex didn't match — silently wrong
  whenever a real arXiv paper's watermark wasn't extracted as its own MinerU text block (confirmed
  real occurrence: `2411.14665` landed under `chunks.paper_id='211c443e9b22f24a'` in SQLite,
  `LESSONS-LEARNED.md` 2026-07-15 T-DOC31 entry). The hash fallback is gone, not just deprioritized
  — every real caller in this codebase already has an id, and a hash-derived `paper_id` is worse
  than an explicit error for the one case that would actually need it (a standalone/manual PDF
  with no known id): that caller should decide its own id (or generate one itself) rather than
  this adapter silently manufacturing an unstable one. `stem` (`sha256(raw)[:16]`) still exists
  below, unrelated to `paper_id` — it's only MinerU's own per-call working-directory/file-naming
  key, needed because `do_parse` writes output keyed by filename, not because of anything to do
  with paper identity.

- **LaTeX routing.** PHASE0-RUNBOOK.md's Spike-1 footnote records that the arXiv-LaTeX ingest path
  (ARCHITECTURE.md §M2's "PDF-vs-LaTeX routing") was *never run* in Spike 1 and is explicitly "not
  a gate condition" for locking MinerU. V0 therefore only implements the PDF half of the router:
  `raw` is validated as a PDF (`pypdfium2`); a gzip/tar-shaped input (the arXiv e-print/LaTeX-source
  archive format) is recognized and raises a specific, diagnosable `PermanentError` rather than a
  generic "not a PDF" one, but is not parsed — that's the recorded open follow-up, not a silently
  swallowed gap.

- **GROBID endpoint.** `contracts/config.py` has no `grobid_url` field (adding one is a
  foundation-adjacent change to `contracts/`, out of this ticket's scope). Defaults to this
  project's documented `docker-compose` address (`rag-grobid`, port 8070) and is overridable via a
  keyword argument for tests/deployment variance — never read from the process environment
  directly (CONVENTIONS §3).

- **Output directory for extracted figure/table images.** `ParsedDoc.figures[].image_path` must be
  a real filesystem path (DATA-CONTRACTS.md "source-of-truth blob"). No `Config` field owns this
  either — `DocumentStore`'s own `blob_dir` (T-D1) is a separate, later concern. Defaults to a
  content-addressed directory under the OS temp dir (`output_dir=None`), never cleaned up here
  (ponytail: a real deployment should point `output_dir` at wherever `DocumentStore`'s blob storage
  lives, or add periodic cache eviction, once that integration is wired up — out of scope for a
  Parser that only has to hand back valid paths).

- **`parse_batch(raws) -> list[ParsedDoc]`, whole-batch-fails, no partial results.** Real
  `nvidia-smi dmon` measurement of a live Pass 1 run found the GPU idling *inside* one document's
  sequential MinerU sub-model stages (layout -> OCR -> table -> formula), not between documents —
  `do_parse` natively pools pages from every open document into shared 64-page windows and runs
  one batched tensor call per stage across them, regardless of N
  (`.phase0-data/pass1-gpu-underutilization.md`, principal-design-reviewer-vetted). Because pages
  from all N documents are pooled into that one call, an exception on any page of any document
  aborts the whole `do_parse` invocation — true per-document isolation would require hooking
  MinerU's private `on_doc_ready` callback, which `do_parse`'s public signature never exposes, and
  would couple this adapter to MinerU internals it has no business depending on. The reviewed,
  locked-in answer is: `parse_batch` raises `PermanentError`/`TransientError` for the batch as a
  whole on ANY failure (missing/corrupt output for any member, or `do_parse` itself raising) —
  never a partial list, never a new return-type sentinel (`contracts/errors.py`'s three-typed-
  exception-only rule). `rag/orchestrator.py::parse_phase` is the caller that recovers per-paper
  isolation on a batch failure, by falling back to the existing singular `parse()` retry path for
  that batch's members — not this adapter's job.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import markdownify
import pydantic
import pypdfium2 as pdfium
from pypdfium2._helpers.misc import PdfiumError

from contracts.errors import ContractError, PermanentError, TransientError
from contracts.parser import Figure, ParsedDoc, Reference, TableItem
from contracts.provenance import Bbox, Block

_DEFAULT_GROBID_URL = "http://localhost:8070"
_GROBID_TIMEOUT = 60.0
_TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

_ARXIV_ID_RE = re.compile(r"\barxiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
_DOI_RE = re.compile(r'\b10\.\d{4,9}/[^\s"<>]+\b')
_SECTION_NUM_RE = re.compile(r"^([A-Za-z]?\d+(?:\.\d+)*)\b")

# MinerU content_list.json `type` -> our closed BlockType (contracts/provenance.py). A strict
# allowlist, not a passthrough: BlockType is a 5-value Literal, MinerU's layout model emits many
# more (aside_text, page_number, chart, list, ...). Anything not listed here that also isn't in
# _SKIP_TYPES/_FIGURE_TYPES falls back to "prose" (see _build_blocks) instead of raising -- an
# unrecognized future MinerU type shouldn't crash the whole paper.
_BODY_BLOCK_TYPE = {
    "equation": "equation",
    "table": "table",
    "code": "code",
    "algorithm": "code",  # faithfully passed through, incl. MinerU's known table<->algorithm
    # misclassification (Phase-0 Spike-1 note) -- the adapter's job is to relay MinerU's call,
    # never to "correct" it; that's a model accuracy ceiling, not an adapter bug.
}
# Margin/running furniture -- never real body content, never a Block.
_SKIP_TYPES = {"page_number", "page_footnote", "aside_text", "footnote", "header", "footer"}
# Non-text content -- becomes a Figure, never a Block (V0 doesn't chunk/embed images; figures[].
# vlm_description stays None until the V3 VLM enricher, contracts/parser.py).
_FIGURE_TYPES = {"image", "chart"}


def parse(
    raw: bytes,
    paper_id: str,
    *,
    output_dir: str | Path | None = None,
    grobid_url: str = _DEFAULT_GROBID_URL,
) -> ParsedDoc:
    """Parse `raw` PDF bytes into a `ParsedDoc` (ARCHITECTURE.md §M2).

    Preconditions: `paper_id` is the caller's already-known real id (T-DOC31 -- see module
    docstring's `paper_id` bullet); `raw` may be empty/garbage/corrupt -- that is exactly the
    quarantine path below, not a precondition the caller must check.
    Postconditions: `doc.paper_id == paper_id`, unconditionally. Every returned `Block`/`Figure`/
    `TableItem` carries a real (non-degenerate) `page` + `bbox` in PDF-point space; `blocks` is in
    0-based contiguous reading order; `parser_id`/`markdown` are non-empty
    (`rag/test_parser.py`'s `assert_parseddoc_invariants`).
    Errors: unparseable/corrupt/scanned-with-no-extractable-content input -> `PermanentError`
    (quarantine, never a crash, ARCHITECTURE.md §M2). A GROBID connectivity failure ->
    `TransientError` (retry-then-quarantine, CONVENTIONS §4) -- that failure is about the GROBID
    *service*, not this paper's data, so it gets the retry-first class instead.
    """
    _reject_latex_archive(raw)
    # PermanentError for b""/garbage/truncated bytes -- before touching MinerU.
    n_pages = _validate_pdf(raw)

    stem = hashlib.sha256(raw).hexdigest()[:16]
    workdir = _resolve_workdir(output_dir)

    content_list, page_sizes, markdown, page_dir = _run_mineru_pipeline(raw, workdir, stem)
    return _assemble_parsed_doc(
        content_list,
        page_sizes,
        markdown,
        page_dir,
        paper_id=paper_id,
        n_pages=n_pages,
        grobid_url=grobid_url,
    )


def parse_batch(
    raws: list[bytes],
    paper_ids: list[str],
    *,
    output_dir: str | Path | None = None,
    grobid_url: str = _DEFAULT_GROBID_URL,
) -> list[ParsedDoc]:
    """Parse N PDFs through one MinerU `do_parse` call instead of N separate ones -- see the
    module docstring's `parse_batch` bullet for why (real GPU-idle measurement, the pooled-window
    mechanism, and the whole-batch-fails-no-partial-results design decision this implements).

    Preconditions: same as `parse()`, applied to every member of `raws`; `paper_ids[i]` is
    `raws[i]`'s real id, so `len(paper_ids) == len(raws)`.
    Postconditions: on full success, returns exactly `len(raws)` `ParsedDoc`s, one per input, in
    the same order as `raws` (`docs[i].paper_id == paper_ids[i]`) -- each satisfying `parse()`'s
    own postconditions.
    Errors: raises `PermanentError`/`TransientError` for the WHOLE batch (never a partial list) if
    `do_parse` itself raises, or if any one member's expected output is missing/corrupt, or if
    assembling any one member's `ParsedDoc` fails for any of `parse()`'s own reasons.
    `ContractError` if `paper_ids` doesn't match `raws` 1:1 by length -- a caller bug, not a
    quarantinable paper problem.
    """
    if not raws:
        return []
    if len(raws) != len(paper_ids):
        raise ContractError(
            f"parse_batch: raws and paper_ids must be the same length, got "
            f"{len(raws)} raws vs {len(paper_ids)} paper_ids"
        )

    for raw in raws:
        _reject_latex_archive(raw)
    n_pages_list = [_validate_pdf(raw) for raw in raws]

    stems = [hashlib.sha256(raw).hexdigest()[:16] for raw in raws]
    workdir = _resolve_workdir(output_dir)

    _call_do_parse(workdir, stems, raws)

    docs = []
    for stem, paper_id, n_pages in zip(stems, paper_ids, n_pages_list, strict=True):
        content_list, page_sizes, markdown, page_dir = _read_mineru_output(workdir, stem)
        docs.append(
            _assemble_parsed_doc(
                content_list,
                page_sizes,
                markdown,
                page_dir,
                paper_id=paper_id,
                n_pages=n_pages,
                grobid_url=grobid_url,
            )
        )
    return docs


def _resolve_workdir(output_dir: str | Path | None) -> Path:
    default_workdir = Path(tempfile.gettempdir()) / "rag-parser-mineru"
    workdir = Path(output_dir) if output_dir is not None else default_workdir
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def _assemble_parsed_doc(
    content_list: list[dict],
    page_sizes: dict[int, tuple[float, float]],
    markdown: str,
    page_dir: Path,
    *,
    paper_id: str,
    n_pages: int,
    grobid_url: str,
) -> ParsedDoc:
    """Shared per-document assembly (bbox rescaling/`content_list` walk, the blocks-empty
    quarantine guard, GROBID reference resolution, final `ParsedDoc` construction) used by both
    `parse()` and `parse_batch()` -- the two entry points differ only in how `content_list`/
    `page_sizes`/`markdown`/`page_dir` get produced (one `do_parse` call vs. a batched one), never
    in what happens to them afterward. `paper_id` is the caller's real id (T-DOC31) -- used as-is,
    never re-derived from `content_list`.
    """
    blocks, figures, tables, raw_refs = _build_blocks(content_list, page_sizes, paper_id, page_dir)

    if not blocks:
        err = PermanentError(
            f"MinerU produced no usable content blocks for this {n_pages}-page PDF -- likely a "
            "scanned/image-only or otherwise unparseable document"
        )
        # No raw PDF bytes at hand here (this is post-do_parse assembly) -- page count is already
        # trivially available and is itself useful diagnostic context for this failure mode.
        err.diagnostics = {"page_count": n_pages}
        raise err

    references = _fetch_references(raw_refs, grobid_url) if raw_refs else []

    try:
        return ParsedDoc(
            paper_id=paper_id,
            markdown=markdown.strip() or "\n\n".join(b.text for b in blocks),
            blocks=blocks,
            figures=figures,
            tables=tables,
            references=references,
            parser_id=_parser_id(),
        )
    except pydantic.ValidationError as e:
        # Every value here is one this adapter itself derived and typed -- a rejection at this
        # final assembly means our own code built a wrong shape, not that the paper is bad
        # (contracts/errors.py: pydantic.ValidationError is a caller-code bug, fold it into
        # ContractError -- crash early, don't quarantine a good paper for our own mistake).
        raise ContractError(f"parser assembled an invalid ParsedDoc: {e}") from e


def _reject_latex_archive(raw: bytes) -> None:
    """Recognize the arXiv e-print/LaTeX-source archive shape (gzip/tar) and fail with a specific,
    diagnosable message instead of a generic "not a PDF" one. V0 does not implement the LaTeX
    ingest path (PHASE0-RUNBOOK.md Spike-1 footnote: never run, not a gate condition for locking
    MinerU) -- this surfaces that gap clearly rather than silently mis-parsing it as a broken PDF.
    """
    is_gzip = raw[:2] == b"\x1f\x8b"
    is_tar = len(raw) > 262 and raw[257:262] == b"ustar"
    if is_gzip or is_tar:
        err = PermanentError(
            "input looks like a LaTeX-source archive (gzip/tar), not a PDF -- the arXiv-LaTeX "
            "ingest path is not implemented in V0 (PHASE0-RUNBOOK.md Spike-1 footnote); route this "
            "paper's PDF instead"
        )
        err.diagnostics = {"pdf_size_bytes": len(raw)}
        raise err


def _validate_pdf(raw: bytes) -> int:
    """Open `raw` with pypdfium2 as a cheap, model-free validation gate -- catches empty/garbage/
    truncated bytes (the frozen negative-path cases in `rag/test_parser.py`) before ever invoking
    MinerU, so the zero-GPU/zero-net unit-test run never touches a model. Returns the page count
    (used only for a clearer `PermanentError` message if MinerU later yields nothing usable).
    """
    try:
        doc = pdfium.PdfDocument(raw)
        n_pages = len(doc)
        doc.close()
    except PdfiumError as e:
        err = PermanentError(f"unparseable PDF: {e}")
        err.diagnostics = {"pdf_size_bytes": len(raw)}
        raise err from e
    if n_pages == 0:
        err = PermanentError("PDF has zero pages")
        err.diagnostics = {"pdf_size_bytes": len(raw)}
        raise err
    return n_pages


def _parser_id() -> str:
    try:
        version = importlib.metadata.version("mineru")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return f"mineru-pipeline-{version}"


def _run_mineru_pipeline(
    raw: bytes, workdir: Path, stem: str
) -> tuple[list[dict], dict[int, tuple[float, float]], str, Path]:
    """Single-document convenience wrapper around `_call_do_parse`/`_read_mineru_output` -- see
    those two docstrings for what each step does. `parse_batch()` calls them directly instead,
    once for the whole batch (`_call_do_parse`) then once per member (`_read_mineru_output`).
    """
    _call_do_parse(workdir, [stem], [raw])
    return _read_mineru_output(workdir, stem)


def _call_do_parse(workdir: Path, stems: list[str], raws: list[bytes]) -> None:
    """Invoke MinerU's `pipeline` backend in-process (see module docstring for why not a CLI
    subprocess), for one document (`parse()`, `len(stems) == 1`) or N documents in a single call
    (`parse_batch()`) -- MinerU pools every open document's pages into shared windows and runs one
    batched tensor call per stage across them regardless of N (module docstring's `parse_batch`
    bullet), so this call itself doesn't otherwise vary with N. Writes each stem's output under
    `workdir/{stem}/auto/` as a side effect; `_read_mineru_output` reads it back.
    """
    from mineru.cli.common import do_parse  # lazy -- see module docstring

    try:
        do_parse(
            output_dir=str(workdir),
            pdf_file_names=stems,
            pdf_bytes_list=raws,
            p_lang_list=["en"] * len(stems),
            backend="pipeline",
            parse_method="auto",
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_orig_pdf=False,
            f_dump_model_output=False,
            f_dump_md=True,
            f_dump_middle_json=True,
            f_dump_content_list=True,
        )
    except (RuntimeError, ValueError, OSError, PdfiumError) as e:
        noun = "PDF" if len(stems) == 1 else f"batch of {len(stems)} PDFs"
        err = PermanentError(f"MinerU pipeline backend failed to parse this {noun}: {e}")
        # Opportunistic only -- pdf_size_bytes is cheaply at hand (raws is already in memory);
        # a per-document breakdown for a batch failure would need more than this catch site
        # trivially has, so this is a total, not a per-document list.
        err.diagnostics = {"pdf_size_bytes": sum(len(r) for r in raws)}
        raise err from e


def _read_mineru_output(
    workdir: Path, stem: str
) -> tuple[list[dict], dict[int, tuple[float, float]], str, Path]:
    """Read one document's MinerU output back off disk after `_call_do_parse` has run (whether
    that was a single-document or batched call). Returns `(content_list, page_sizes, markdown,
    page_dir)`:
      - `content_list`: MinerU's own flattened per-block list (`*_content_list.json` shape),
        bbox normalized 0-1000 per page axis.
      - `page_sizes`: `page_idx -> (width, height)` in PDF points, read back from
        `*_middle.json`'s `pdf_info[i]["page_size"]` -- needed to rescale `content_list`'s bbox.
      - `markdown`: the full-document markdown MinerU renders (`*.md`), used for
        `ParsedDoc.markdown` as a whole.
      - `page_dir`: the directory holding these outputs (and `images/`), so figure/table image
        paths can be resolved to absolute paths.
    """
    page_dir = workdir / stem / "auto"
    content_list_path = page_dir / f"{stem}_content_list.json"
    middle_json_path = page_dir / f"{stem}_middle.json"
    md_path = page_dir / f"{stem}.md"

    try:
        content_list = json.loads(content_list_path.read_text())
        middle = json.loads(middle_json_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        err = PermanentError(f"MinerU produced no readable output for this PDF: {e}")
        # No raw PDF bytes at hand at this point (output-reading happens after do_parse, off
        # disk) -- the stage name is the only thing trivially available here.
        err.diagnostics = {"stage": "read_mineru_output"}
        raise err from e

    page_sizes = {p["page_idx"]: tuple(p["page_size"]) for p in middle.get("pdf_info", [])}
    markdown = md_path.read_text() if md_path.exists() else ""
    return content_list, page_sizes, markdown, page_dir


def _rescale_bbox(bbox_norm, page_width: float, page_height: float) -> Bbox:
    """Undo MinerU's `content_list.json` 0-1000-per-axis bbox normalization
    (`mineru.backend.pipeline.pipeline_middle_json_mkcontent._build_bbox`) back to true PDF-point
    space, matching `contracts/provenance.py`'s `Bbox` convention.
    """
    x0, y0, x1, y1 = bbox_norm
    return (
        x0 / 1000.0 * page_width,
        y0 / 1000.0 * page_height,
        x1 / 1000.0 * page_width,
        y1 / 1000.0 * page_height,
    )


def _heading_depth(text: str) -> int:
    """Depth of a heading from its own numeric/alpha prefix ("3" -> 1, "3.2" -> 2, "4.5.1" -> 3,
    "A.1" -> 2). Un-numbered headings ("Abstract", "References") count as depth 1.

    ponytail: heuristic, not a true font/outline-based hierarchy -- MinerU's pipeline layout model
    gives every non-title heading the same flat `text_level` (verified empirically against
    `.phase0-data/parser-eval/`: "1 Introduction" and "3.2 Accounting for..." are both
    `text_level: 2`), so true depth isn't available from the model output. This recovers depth from
    the heading's own numbering instead. Ceiling: a paper with unnumbered subsection headings
    degrades to flat (depth-1) `section_path` grouping for those headings -- upgrade path is a
    real outline/font-size-based hierarchy if that degradation ever shows up as a chunking problem.
    """
    m = _SECTION_NUM_RE.match(text.strip())
    if not m:
        return 1
    return m.group(1).count(".") + 1


class _SectionTracker:
    """Tracks the current `section_path` (DATA-CONTRACTS.md example: "3. Method > 3.2 Estimator")
    while walking `content_list` in reading order. Call `.update(heading_text)` on every heading
    block; read `.path` for every block's `section_path` (including the heading block itself, which
    is labeled with the path it just pushed -- `Block.section_path` is AUTHORITATIVE and assigned
    once here, DATA-CONTRACTS.md "Provenance & structure").
    """

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    @property
    def path(self) -> str:
        return " > ".join(text for _, text in self._stack)

    def update(self, heading_text: str) -> None:
        depth = _heading_depth(heading_text)
        while self._stack and self._stack[-1][0] >= depth:
            self._stack.pop()
        self._stack.append((depth, heading_text.strip()))


def _build_blocks(
    content_list: list[dict],
    page_sizes: dict[int, tuple[float, float]],
    paper_id: str,
    page_dir: Path,
) -> tuple[list[Block], list[Figure], list[TableItem], list[str]]:
    """Walk MinerU's `content_list` (already in reading order) building the four `ParsedDoc`
    pieces that come from it. Returns `(blocks, figures, tables, raw_reference_strings)` --
    references themselves are resolved separately, via GROBID (`_fetch_references`), per the
    module docstring; `raw_reference_strings` is just MinerU's own `ref_text` list content handed
    up so the caller can send it there.

    Never constructs a `Block`/`Figure`/`TableItem` it doesn't have a real page+bbox for
    (contracts/parser.py's invariant) -- an item missing either, or whose rescaled bbox is
    degenerate, is skipped rather than faked.
    """
    blocks: list[Block] = []
    figures: list[Figure] = []
    tables: list[TableItem] = []
    raw_refs: list[str] = []
    section = _SectionTracker()
    index = 0

    for item in content_list:
        item_type = item.get("type")
        page_idx = item.get("page_idx")
        bbox_norm = item.get("bbox")
        if page_idx is None or not bbox_norm:
            continue  # no anchor -- never fake one
        page_size = page_sizes.get(page_idx)
        if not page_size:
            continue
        bbox = _rescale_bbox(bbox_norm, page_size[0], page_size[1])
        x0, y0, x1, y1 = bbox
        if x1 <= x0 or y1 <= y0:
            continue  # degenerate bbox -- skip rather than emit a fake one

        # text_level 1 is MinerU's document-title marker (exactly one per paper); only >= 2 is a
        # real section heading. Excluding level 1 keeps front-matter blocks (authors, affiliation,
        # date -- everything before the first real section) at section_path="" instead of nesting
        # them under the title, which the Chunker already prefixes onto every chunk separately
        # (DATA-CONTRACTS.md's Chunker note) -- folding it into section_path too would be redundant.
        if item_type == "text" and (item.get("text_level") or 0) >= 2:
            section.update(item["text"])  # heading -- also becomes its own prose Block below

        if item_type in _SKIP_TYPES:
            continue

        if item_type == "list" and item.get("sub_type") == "ref_text":
            raw_refs.extend(x for x in item.get("list_items", []) if x.strip())
            continue

        if item_type in _FIGURE_TYPES:
            img_path = item.get("img_path")
            if not img_path:
                continue
            caption = "\n".join(item.get(f"{item_type}_caption", []))
            figures.append(
                Figure(
                    paper_id=paper_id,
                    image_path=str(page_dir / img_path),
                    caption=caption,
                    page=page_idx,
                    bbox=bbox,
                )
            )
            continue

        if item_type == "table":
            html = item.get("table_body", "")
            md_table = markdownify.markdownify(html).strip() if html else ""
            caption = "\n".join(item.get("table_caption", []))
            tables.append(
                TableItem(
                    paper_id=paper_id, markdown=md_table, caption=caption, page=page_idx, bbox=bbox
                )
            )
            block_text = md_table or caption
            if not block_text.strip():
                continue
            blocks.append(
                Block(
                    block_id=f"{paper_id}:b{index}",
                    paper_id=paper_id,
                    text=block_text,
                    type="table",
                    page=page_idx,
                    bbox=bbox,
                    section_path=section.path,
                    index=index,
                )
            )
            index += 1
            continue

        # body text / equation / code / algorithm / non-reference list / anything unrecognized.
        text = item.get("text") or "\n".join(item.get("list_items", []))
        if not text or not text.strip():
            continue
        blocks.append(
            Block(
                block_id=f"{paper_id}:b{index}",
                paper_id=paper_id,
                text=text,
                type=_BODY_BLOCK_TYPE.get(item_type, "prose"),
                page=page_idx,
                bbox=bbox,
                section_path=section.path,
                index=index,
            )
        )
        index += 1

    return blocks, figures, tables, raw_refs


def _fetch_references(raw_refs: list[str], grobid_url: str) -> list[Reference]:
    """One batched call to GROBID's `/api/processCitationList` (not N calls, one per reference --
    GROBID ships a batch endpoint for exactly this). `Accept: application/xml` requests TEI
    (its default response for this endpoint is BibTeX, which has no `<idno>`-style field for the
    structured DOI/arXiv-id extraction below to read).

    `consolidateCitations="0"`: no external lookup (CrossRef etc.) -- keeps this deterministic and
    independent of whether the GROBID container itself has internet access; DOI/arXiv-id recovery
    for citations that already spell them out verbatim is instead handled locally in
    `_parse_grobid_tei` via regex on the raw string, which needs no network round-trip at all.
    """
    try:
        resp = httpx.post(
            f"{grobid_url}/api/processCitationList",
            data={"citations": raw_refs, "consolidateCitations": "0"},
            headers={"Accept": "application/xml"},
            timeout=_GROBID_TIMEOUT,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        # GROBID being unreachable/erroring is about the *service*, not this paper's data --
        # TransientError (retry-then-quarantine, CONVENTIONS §4), not PermanentError.
        raise TransientError(f"GROBID reference extraction failed: {e}") from e

    return _parse_grobid_tei(resp.text, raw_refs)


def _parse_grobid_tei(xml_text: str, raw_refs: list[str]) -> list[Reference]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise TransientError(f"GROBID returned unparseable TEI: {e}") from e

    structs = root.findall(".//tei:biblStruct", _TEI_NS)
    references = []
    for i, raw in enumerate(raw_refs):
        struct = structs[i] if i < len(structs) else None
        title = _extract_title(struct) if struct is not None else None
        doi = _extract_idno(struct, "DOI") if struct is not None else None
        arxiv_id = _extract_idno(struct, "arXiv") if struct is not None else None
        if not doi:
            m = _DOI_RE.search(raw)
            doi = m.group(0) if m else None
        if not arxiv_id:
            m = _ARXIV_ID_RE.search(raw)
            arxiv_id = m.group(1) if m else None
        references.append(Reference(raw=raw, title=title, arxiv_id=arxiv_id, doi=doi))
    return references


def _extract_title(struct: ET.Element) -> str | None:
    title = struct.find(".//tei:analytic/tei:title", _TEI_NS)
    if title is None:
        title = struct.find(".//tei:monogr/tei:title", _TEI_NS)
    return title.text.strip() if title is not None and title.text else None


def _extract_idno(struct: ET.Element, idno_type: str) -> str | None:
    idno = struct.find(f".//tei:idno[@type='{idno_type}']", _TEI_NS)
    return idno.text.strip() if idno is not None and idno.text else None
