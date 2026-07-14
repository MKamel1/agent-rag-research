# M1A-DORMANT (re-enable in M1b): skips until rag/parser.py exists. M1b's Definition of Done
# (CONVENTIONS §11) requires this suite active (importorskip resolves) and green.
"""M1a tests-first suite for M2 Parser (T-B1).

Written against the FROZEN interface `parse(raw: PdfBytes | LatexSource) -> ParsedDoc`
(ARCHITECTURE.md §M2) BEFORE `rag/parser.py` exists. Until it does, the whole module is SKIPPED
(the `importorskip` below) so CI stays green; it activates in M1b when the adapter lands.

What this suite asserts at M1a (interface contract — no real vendor, no golden fixtures needed):
  * `parse` is exposed and callable.
  * Unparseable input (empty / garbage / truncated bytes) -> `PermanentError` — the
    broken-PDF -> quarantine path (TEST-STRATEGY.md "Parser" bullet; ARCHITECTURE.md §M2 "parse
    failure -> typed error -> paper quarantined").
  * A reusable postcondition checker (`assert_parseddoc_invariants`) that encodes every guarantee
    parse()'s output must satisfy and that the type system alone does NOT enforce: every block /
    figure / table carries a real page+bbox (never the faked `bbox=(0,0,0,0)` — OWNER-B.md scope
    fence), reading order is 0-based and contiguous, `parser_id` and `markdown` are non-empty.
    The checker is exercised with both a valid and several invalid `ParsedDoc`s so it has teeth.

What waits on Spike-1 golden fixtures (DEFERRED — see PR body; TEST-STRATEGY.md "Golden fixtures"):
  * Parsing the ~8-12 hand-checked real PDFs (math-heavy, code-heavy, multi-column, table-heavy)
    and asserting the above invariants on the *actual* parser output, plus equations-as-LaTeX,
    section paths sane, references parsed.
  * The one deliberately scanned/broken golden PDF -> `PermanentError`.
  These live in `fixtures/golden/` (only `.gitkeep` at M1a). The golden tests below auto-skip
  while that directory holds no PDFs and activate — no code change — once Spike 1 commits them.
  Note: the golden PDFs are a Spike-1 OUTPUT; the raw Phase-0 input PDFs are NOT golden fixtures
  and this suite deliberately does not depend on them.
"""

import hashlib
import io
import json
import sys
import types
from pathlib import Path

import pypdfium2 as pdfium
import pytest

_mod = pytest.importorskip("rag.parser")  # SKIPS the whole module until rag/parser.py exists

from contracts.errors import PermanentError  # noqa: E402  (foundation — always importable)
from contracts.parser import Figure, ParsedDoc, Reference, TableItem  # noqa: E402
from contracts.provenance import Block  # noqa: E402

parse = _mod.parse
parse_batch = _mod.parse_batch

_FAKE_BBOX = (0.0, 0.0, 0.0, 0.0)  # the forbidden "fake" bbox (OWNER-B.md scope fence)
_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "golden"


# ---------------------------------------------------------------------------
# Inline builders (rag/ tests build contract shapes locally; conftest fixtures
# are scoped to contracts/). Defaults are a minimally-valid, invariant-satisfying doc.
# ---------------------------------------------------------------------------


def _block(**overrides) -> Block:
    fields = dict(
        block_id="2506.01234:b0",
        paper_id="2506.01234",
        text="Some prose.",
        type="prose",
        page=0,
        bbox=(10.0, 20.0, 110.0, 220.0),
        section_path="3. Method",
        index=0,
    )
    fields.update(overrides)
    return Block(**fields)


def _parsed_doc(**overrides) -> ParsedDoc:
    fields = dict(
        paper_id="2506.01234",
        markdown="# A Causal Method\n\nWe propose...",
        blocks=[_block(index=0), _block(index=1, block_id="2506.01234:b1")],
        figures=[],
        tables=[],
        references=[],
        parser_id="test-parser-1.x",
    )
    fields.update(overrides)
    return ParsedDoc(**fields)


# ---------------------------------------------------------------------------
# Postcondition checker — the guarantees parse()'s output must satisfy that
# pydantic construction does NOT enforce on its own.
# ---------------------------------------------------------------------------


def assert_parseddoc_invariants(doc: ParsedDoc) -> None:
    """Raise AssertionError if `doc` violates any Parser output invariant.

    Encodes ARCHITECTURE.md §M2 + DATA-CONTRACTS.md "Parser invariant" + OWNER-B.md scope fence:
    every block/figure/table has a real page+bbox (never `(0,0,0,0)`), blocks are in 0-based
    contiguous reading order, and reproducibility/body fields are populated.
    """
    assert doc.parser_id.strip(), "parser_id must identify the adapter (reproducibility)"
    assert doc.markdown.strip(), "a real parse yields non-empty body markdown"

    def _has_real_anchor(item: Block | Figure | TableItem, kind: str) -> None:
        assert item.page >= 0, f"{kind} page must be >= 0"
        assert item.bbox != _FAKE_BBOX, f"{kind} must carry a real bbox, never the faked {_FAKE_BBOX}"
        x0, y0, x1, y1 = item.bbox
        assert x1 > x0 and y1 > y0, f"{kind} bbox must be a non-degenerate rectangle, got {item.bbox}"

    for i, block in enumerate(doc.blocks):
        _has_real_anchor(block, f"block[{i}]")
        assert block.index == i, (
            f"blocks must be in 0-based contiguous reading order; block[{i}] has index {block.index}"
        )
    for fig in doc.figures:
        _has_real_anchor(fig, "figure")
    for table in doc.tables:
        _has_real_anchor(table, "table")


# ---------------------------------------------------------------------------
# The checker itself has teeth (runs at M1b immediately — no golden fixtures).
# ---------------------------------------------------------------------------


def test_checker_accepts_a_wellformed_parsed_doc():
    assert_parseddoc_invariants(_parsed_doc())  # must not raise


def test_checker_rejects_fake_zero_bbox():
    doc = _parsed_doc(blocks=[_block(bbox=_FAKE_BBOX)])
    with pytest.raises(AssertionError):
        assert_parseddoc_invariants(doc)


def test_checker_rejects_broken_reading_order():
    # index gap (0, 2) — constructible under the contract, but a reading-order violation.
    doc = _parsed_doc(
        blocks=[_block(index=0), _block(index=2, block_id="2506.01234:b2")]
    )
    with pytest.raises(AssertionError):
        assert_parseddoc_invariants(doc)


def test_checker_rejects_empty_parser_id():
    with pytest.raises(AssertionError):
        assert_parseddoc_invariants(_parsed_doc(parser_id="  "))


def test_checker_rejects_figure_with_fake_bbox():
    fig = Figure(
        paper_id="2506.01234",
        image_path="/blobs/2506.01234/fig1.png",
        caption="Figure 1",
        page=1,
        bbox=_FAKE_BBOX,
    )
    with pytest.raises(AssertionError):
        assert_parseddoc_invariants(_parsed_doc(figures=[fig]))


# ---------------------------------------------------------------------------
# Interface smoke (activates in M1b as soon as rag/parser.py exists).
# ---------------------------------------------------------------------------


def test_parse_is_callable():
    assert callable(parse)


# ---------------------------------------------------------------------------
# Broken input -> quarantine (PermanentError). Representative unparseable inputs;
# no golden fixture needed — activates in M1b immediately.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_input, why",
    [
        (b"", "empty bytes"),
        (b"this is not a pdf", "garbage bytes with no PDF header"),
        (b"%PDF-1.7\n<truncated", "truncated PDF — valid header, corrupt body"),
    ],
)
def test_unparseable_input_raises_permanent_error(bad_input, why):
    # ARCHITECTURE.md §M2: parse failure -> typed error -> quarantine (NOT a crash, NOT Transient).
    with pytest.raises(PermanentError):
        parse(bad_input)


# ---------------------------------------------------------------------------
# parse_batch() (T-DOC16, .phase0-data/pass1-gpu-underutilization.md). Exercises the real
# `_call_do_parse`/`_read_mineru_output`/`_assemble_parsed_doc` plumbing against a fake
# `mineru.cli.common.do_parse` -- injected straight into `sys.modules`, never the real installed
# `mineru` package, so this stays exactly as zero-GPU/zero-heavy-import as the rest of this
# module's own "lazy import" design goal (module docstring: "importing rag.parser never pulls in
# torch/mineru unless a PDF actually reaches MinerU"). The fake writes the same three output files
# (`_content_list.json`, `_middle.json`, `.md`) a real `do_parse` call would, under
# `output_dir/{stem}/auto/`. Inputs are real (pypdfium2-built) one-page PDFs so `_validate_pdf` --
# which gates every call before MinerU is ever reached -- passes; distinct page sizes give each
# one a distinct content hash, so each gets its own `stem`.
# ---------------------------------------------------------------------------


def _install_fake_do_parse(monkeypatch, fake_do_parse) -> None:
    """Inject a fake `mineru.cli.common` module (bearing `do_parse = fake_do_parse`) straight into
    `sys.modules`, so `rag.parser`'s lazy `from mineru.cli.common import do_parse` picks it up
    without ever importing the real (torch-heavy, optionally network-probing) `mineru` package --
    works whether or not `mineru` is actually installed in the environment running this test.
    """
    fake_common = types.ModuleType("mineru.cli.common")
    fake_common.do_parse = fake_do_parse
    fake_cli = types.ModuleType("mineru.cli")
    fake_cli.common = fake_common
    fake_mineru = types.ModuleType("mineru")
    fake_mineru.cli = fake_cli
    monkeypatch.setitem(sys.modules, "mineru", fake_mineru)
    monkeypatch.setitem(sys.modules, "mineru.cli", fake_cli)
    monkeypatch.setitem(sys.modules, "mineru.cli.common", fake_common)


def _one_page_pdf_bytes(width: float, height: float) -> bytes:
    doc = pdfium.PdfDocument.new()
    doc.new_page(width, height)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _stem_of(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def _write_fake_mineru_output(output_dir: Path, stem: str, *, text: str) -> None:
    """Write the same three files `_read_mineru_output` reads back, for one `stem` -- a minimal
    but real content_list/middle.json pair (one text block, on a page MinerU would have recorded
    at 612x792pt) so `_assemble_parsed_doc` builds a real, invariant-satisfying `ParsedDoc`.
    """
    page_dir = output_dir / stem / "auto"
    page_dir.mkdir(parents=True, exist_ok=True)
    content_list = [
        {"type": "text", "page_idx": 0, "bbox": [100, 100, 900, 200], "text": text, "text_level": 0}
    ]
    middle = {"pdf_info": [{"page_idx": 0, "page_size": [612, 792]}]}
    (page_dir / f"{stem}_content_list.json").write_text(json.dumps(content_list))
    (page_dir / f"{stem}_middle.json").write_text(json.dumps(middle))
    (page_dir / f"{stem}.md").write_text(f"# Doc\n\n{text}")


def _fake_do_parse_writing(output_dir: Path, texts_by_stem: dict[str, str], *, skip: set[str] = frozenset()):
    """A `mineru.cli.common.do_parse`-shaped stand-in: writes valid output for every stem in
    `texts_by_stem` except those in `skip` (simulating "MinerU produced no output for this one
    member" without needing a real corrupt PDF to trigger it)."""

    def _fake(*, output_dir: str, pdf_file_names: list[str], pdf_bytes_list: list[bytes], **kwargs):
        for stem in pdf_file_names:
            if stem in skip:
                continue
            _write_fake_mineru_output(Path(output_dir), stem, text=texts_by_stem[stem])

    return _fake


def test_parse_batch_is_callable():
    assert callable(parse_batch)


def test_parse_batch_empty_list_returns_empty_list():
    assert parse_batch([]) == []


def test_parse_batch_returns_parseddocs_in_order_on_full_success(tmp_path, monkeypatch):
    raws = [_one_page_pdf_bytes(w, h) for w, h in [(200, 200), (300, 300), (400, 400)]]
    stems = [_stem_of(r) for r in raws]
    texts = {stem: f"body text for document {i}" for i, stem in enumerate(stems)}
    _install_fake_do_parse(monkeypatch, _fake_do_parse_writing(tmp_path, texts))

    docs = parse_batch(raws, output_dir=tmp_path)

    assert len(docs) == 3
    assert [d.paper_id for d in docs] == stems  # same order as raws (no arXiv id -> falls back to stem)
    for doc, stem in zip(docs, stems, strict=True):
        assert texts[stem] in doc.markdown
        assert_parseddoc_invariants(doc)


def test_parse_batch_single_item_batch_works(tmp_path, monkeypatch):
    raw = _one_page_pdf_bytes(250, 250)
    stem = _stem_of(raw)
    _install_fake_do_parse(monkeypatch, _fake_do_parse_writing(tmp_path, {stem: "solo document"}))

    docs = parse_batch([raw], output_dir=tmp_path)

    assert len(docs) == 1
    assert_parseddoc_invariants(docs[0])


def test_parse_batch_raises_and_returns_nothing_when_one_members_output_is_missing(
    tmp_path, monkeypatch
):
    # T-DOC16's most important guarantee: one bad document must not silently lose or corrupt the
    # other N-1 good ones -- there is no return value at all on a batch failure, only a raise.
    raws = [_one_page_pdf_bytes(w, h) for w, h in [(200, 200), (300, 300), (400, 400)]]
    stems = [_stem_of(r) for r in raws]
    texts = {stem: f"body text for document {i}" for i, stem in enumerate(stems)}
    _install_fake_do_parse(
        monkeypatch,
        _fake_do_parse_writing(tmp_path, texts, skip={stems[1]}),  # the middle doc's output "never lands"
    )

    with pytest.raises(PermanentError):
        parse_batch(raws, output_dir=tmp_path)


def test_parse_batch_maps_do_parse_exception_to_permanent_error(tmp_path, monkeypatch):
    def _raising_do_parse(**kwargs):
        raise RuntimeError("simulated MinerU pipeline crash")

    _install_fake_do_parse(monkeypatch, _raising_do_parse)
    raws = [_one_page_pdf_bytes(200, 200), _one_page_pdf_bytes(300, 300)]

    with pytest.raises(PermanentError):
        parse_batch(raws, output_dir=tmp_path)


def test_parse_batch_rejects_unparseable_member_before_calling_do_parse(tmp_path, monkeypatch):
    # A batch member failing `_validate_pdf`/`_reject_latex_archive` fails the whole batch too --
    # same whole-batch-fails contract, cheaper (no MinerU call needed to know it's bad).
    def _unexpectedly_called_do_parse(**kwargs):
        raise AssertionError("do_parse must not be called when a batch member is unparseable")

    _install_fake_do_parse(monkeypatch, _unexpectedly_called_do_parse)
    raws = [_one_page_pdf_bytes(200, 200), b"not a pdf at all"]

    with pytest.raises(PermanentError):
        parse_batch(raws, output_dir=tmp_path)


# ---------------------------------------------------------------------------
# Golden-fixture parse (DEFERRED to Spike 1). Skips while fixtures/golden/ holds no PDFs;
# activates unchanged once the hand-checked golden set is committed.
# ---------------------------------------------------------------------------


def _golden_pdfs() -> list[Path]:
    if not _GOLDEN_DIR.is_dir():
        return []
    return sorted(p for p in _GOLDEN_DIR.glob("*.pdf") if "scanned" not in p.name and "broken" not in p.name)


def _scanned_golden_pdfs() -> list[Path]:
    if not _GOLDEN_DIR.is_dir():
        return []
    return sorted(p for p in _GOLDEN_DIR.glob("*.pdf") if "scanned" in p.name or "broken" in p.name)


_golden = _golden_pdfs()
_scanned = _scanned_golden_pdfs()


@pytest.mark.real_adapter  # needs a live GROBID + first-run MinerU model download (network)
@pytest.mark.skipif(not _golden, reason="Spike-1 golden PDFs not committed yet (fixtures/golden/)")
@pytest.mark.parametrize("pdf_path", _golden, ids=lambda p: p.name)
def test_golden_pdf_parses_and_satisfies_invariants(pdf_path):
    doc = parse(pdf_path.read_bytes())
    assert isinstance(doc, ParsedDoc)
    assert doc.blocks, "a real paper must yield at least one block"
    assert_parseddoc_invariants(doc)  # every block/figure/table anchored; reading order; parser_id


@pytest.mark.real_adapter  # needs a live GROBID + first-run MinerU model download (network)
@pytest.mark.skipif(not _golden, reason="Spike-1 golden PDFs not committed yet (fixtures/golden/)")
@pytest.mark.parametrize("pdf_path", _golden, ids=lambda p: p.name)
def test_golden_pdf_preserves_equations_as_latex(pdf_path):
    # TEST-STRATEGY.md "Golden fixtures": equations present as LaTeX (math-heavy fixtures).
    # Not every golden PDF is math-heavy, so assert the shape holds *when* equation blocks exist
    # rather than requiring one in every paper.
    doc = parse(pdf_path.read_bytes())
    for block in doc.blocks:
        if block.type == "equation":
            assert block.text.strip(), "equation block must carry its LaTeX in `text`"


@pytest.mark.real_adapter  # needs a live GROBID + first-run MinerU model download (network)
@pytest.mark.skipif(
    not _scanned, reason="Spike-1 scanned/broken golden PDF not committed yet (fixtures/golden/)"
)
@pytest.mark.parametrize("pdf_path", _scanned, ids=lambda p: p.name)
def test_scanned_golden_pdf_is_quarantined(pdf_path):
    # TEST-STRATEGY.md: the deliberately broken/scanned PDF must raise PermanentError, not crash.
    with pytest.raises(PermanentError):
        parse(pdf_path.read_bytes())


# References parsing is likewise golden-dependent — asserted here so it activates with
# the fixtures. A math/table-only page may legitimately have no references, so this checks shape
# (each parsed Reference has a non-empty `raw`) rather than requiring references to exist.
@pytest.mark.real_adapter  # needs a live GROBID + first-run MinerU model download (network)
@pytest.mark.skipif(not _golden, reason="Spike-1 golden PDFs not committed yet (fixtures/golden/)")
@pytest.mark.parametrize("pdf_path", _golden, ids=lambda p: p.name)
def test_golden_pdf_references_have_raw_strings(pdf_path):
    doc = parse(pdf_path.read_bytes())
    for ref in doc.references:
        assert isinstance(ref, Reference)
        assert ref.raw.strip(), "every parsed reference carries its raw string"
