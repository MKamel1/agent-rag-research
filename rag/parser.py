"""rag/parser.py — Parser adapter (T-B1, M2 · owner B).

Wraps MinerU (`pipeline` backend — Phase-0 Spike 1's locked choice; Docling and Marker were
evaluated and dropped, PHASE0-RUNBOOK.md's Spike-1 footnote) for PDF body parsing, and GROBID (a
separate Docker service, `/api/processCitationList`) for reference extraction. Frozen interface
(ARCHITECTURE.md §M2): `parse(raw: PdfBytes | LatexSource) -> ParsedDoc`. Only this file may
import `mineru`/`grobid` tokens (CONVENTIONS §1 — `ci/checks/vendor_isolation.py` already scopes
both here).

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

- **`paper_id`.** The frozen `parse(raw)` signature takes only bytes — no id. arXiv PDFs print
  `arXiv:YYMM.NNNNN[vN] ...` somewhere on the page (MinerU emits it as its own text block, usually
  `aside_text`); the base id (version stripped, matching DATA-CONTRACTS.md §IDs' `paper_id`
  format) is regex-recovered from it when present. Falls back to a content hash
  (`sha256(raw).hexdigest()[:16]`) for non-arXiv/undetectable input, so `parse()` never raises just
  because an id couldn't be read off the page. No golden/frozen test pins an exact `paper_id`
  value — it only needs to be stable and internally consistent (it's used to build every
  `block_id`, DATA-CONTRACTS.md §IDs' `"{paper_id}:b{index}"` format).

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
  keyword argument for tests/deployment variance — never read from `os.getenv` (CONVENTIONS §3).

- **Output directory for extracted figure/table images.** `ParsedDoc.figures[].image_path` must be
  a real filesystem path (DATA-CONTRACTS.md "source-of-truth blob"). No `Config` field owns this
  either — `DocumentStore`'s own `blob_dir` (T-D1) is a separate, later concern. Defaults to a
  content-addressed directory under the OS temp dir (`output_dir=None`), never cleaned up here
  (ponytail: a real deployment should point `output_dir` at wherever `DocumentStore`'s blob storage
  lives, or add periodic cache eviction, once that integration is wired up — out of scope for a
  Parser that only has to hand back valid paths).
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
    *,
    output_dir: str | Path | None = None,
    grobid_url: str = _DEFAULT_GROBID_URL,
) -> ParsedDoc:
    """Parse `raw` PDF bytes into a `ParsedDoc` (ARCHITECTURE.md §M2).

    Preconditions: none the caller must check -- `raw` may be empty/garbage/corrupt; that is
    exactly the quarantine path below.
    Postconditions: every returned `Block`/`Figure`/`TableItem` carries a real (non-degenerate)
    `page` + `bbox` in PDF-point space; `blocks` is in 0-based contiguous reading order;
    `parser_id`/`markdown` are non-empty (`rag/test_parser.py`'s `assert_parseddoc_invariants`).
    Errors: unparseable/corrupt/scanned-with-no-extractable-content input -> `PermanentError`
    (quarantine, never a crash, ARCHITECTURE.md §M2). A GROBID connectivity failure ->
    `TransientError` (retry-then-quarantine, CONVENTIONS §4) -- that failure is about the GROBID
    *service*, not this paper's data, so it gets the retry-first class instead.
    """
    _reject_latex_archive(raw)
    # PermanentError for b""/garbage/truncated bytes -- before touching MinerU.
    n_pages = _validate_pdf(raw)

    stem = hashlib.sha256(raw).hexdigest()[:16]
    default_workdir = Path(tempfile.gettempdir()) / "rag-parser-mineru"
    workdir = Path(output_dir) if output_dir is not None else default_workdir
    workdir.mkdir(parents=True, exist_ok=True)

    content_list, page_sizes, markdown, page_dir = _run_mineru_pipeline(raw, workdir, stem)
    paper_id = _derive_paper_id(content_list, fallback=stem)
    blocks, figures, tables, raw_refs = _build_blocks(content_list, page_sizes, paper_id, page_dir)

    if not blocks:
        raise PermanentError(
            f"MinerU produced no usable content blocks for this {n_pages}-page PDF -- likely a "
            "scanned/image-only or otherwise unparseable document"
        )

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
        raise PermanentError(
            "input looks like a LaTeX-source archive (gzip/tar), not a PDF -- the arXiv-LaTeX "
            "ingest path is not implemented in V0 (PHASE0-RUNBOOK.md Spike-1 footnote); route this "
            "paper's PDF instead"
        )


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
        raise PermanentError(f"unparseable PDF: {e}") from e
    if n_pages == 0:
        raise PermanentError("PDF has zero pages")
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
    """Invoke MinerU's `pipeline` backend in-process (see module docstring for why not a CLI
    subprocess). Returns `(content_list, page_sizes, markdown, page_dir)`:
      - `content_list`: MinerU's own flattened per-block list (`*_content_list.json` shape),
        bbox normalized 0-1000 per page axis.
      - `page_sizes`: `page_idx -> (width, height)` in PDF points, read back from
        `*_middle.json`'s `pdf_info[i]["page_size"]` -- needed to rescale `content_list`'s bbox.
      - `markdown`: the full-document markdown MinerU renders (`*.md`), used for
        `ParsedDoc.markdown` as a whole.
      - `page_dir`: the directory holding these outputs (and `images/`), so figure/table image
        paths can be resolved to absolute paths.
    """
    from mineru.cli.common import do_parse  # lazy -- see module docstring

    try:
        do_parse(
            output_dir=str(workdir),
            pdf_file_names=[stem],
            pdf_bytes_list=[raw],
            p_lang_list=["en"],
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
        raise PermanentError(f"MinerU pipeline backend failed to parse this PDF: {e}") from e

    page_dir = workdir / stem / "auto"
    content_list_path = page_dir / f"{stem}_content_list.json"
    middle_json_path = page_dir / f"{stem}_middle.json"
    md_path = page_dir / f"{stem}.md"

    try:
        content_list = json.loads(content_list_path.read_text())
        middle = json.loads(middle_json_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise PermanentError(f"MinerU produced no readable output for this PDF: {e}") from e

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


def _derive_paper_id(content_list: list[dict], fallback: str) -> str:
    """Best-effort recovery of the base arXiv id (no version) from wherever MinerU's text blocks
    mention it -- arXiv PDFs print `arXiv:YYMM.NNNNN[vN] ...` on the page (commonly a margin
    `aside_text` watermark). Falls back to a content hash for non-arXiv/undetectable input; see
    module docstring for why the frozen interface leaves this to the adapter.
    """
    for item in content_list:
        text = item.get("text") or ""
        match = _ARXIV_ID_RE.search(text)
        if match:
            return match.group(1)
    return fallback


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
