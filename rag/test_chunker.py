# M1A-DORMANT (re-enable in M1b): skips until rag/chunker.py exists. M1b DoD (CONVENTIONS §11)
# requires this suite active (importorskip resolves) and green.
"""Owner C · T-C1 — Chunker (M3) test suite, written test-first against the FROZEN interface.

Spec sources: TEST-STRATEGY.md "Chunker" bullet, ARCHITECTURE.md §M3, DATA-CONTRACTS.md §M3 +
§"Provenance & structure" (the multi-block anchoring rule). Frozen interface (ARCHITECTURE §M3,
owner C): a `Chunker` constructed with the injected `Config` (CONVENTIONS §3) exposing
`chunk(ParsedDoc) -> list[Chunk]`. `Config.child_parent_expansion` (DATA-CONTRACTS §M3) is the
grouping lever: `True` (V0 default) merges an equation/table block with its defining prose block;
`False` forces one `Chunk` per `Block`.

Everything here is zero-GPU, zero-network — Chunker injects no vendor/LLM client in V0
(ARCHITECTURE §M3 "Seam: none needed"). No real service, no fakes beyond the frozen contract
shapes.
"""

import pytest

# M1a CI convention (CONVENTIONS §0.7 / §11): skip the whole suite until the implementation lands,
# so CI stays green through M1a and this suite activates automatically in M1b.
_mod = pytest.importorskip("rag.chunker")

from contracts.config import Config  # noqa: E402
from contracts.parser import ParsedDoc  # noqa: E402
from contracts.provenance import Block  # noqa: E402

PAPER_ID = "2506.01234"
TITLE = "Deep Causal Estimation"
METHOD_PATH = "3. Method > 3.2 Estimator"
RESULTS_PATH = "4. Results"
CODE_PATH = "5. Implementation"

PROSE_TEXT = "We define the doubly-robust estimator used throughout this section."
EQUATION_LATEX = r"\hat{\tau} = E[Y \mid do(X{=}1)] - E[Y \mid do(X{=}0)]"
RESULTS_TEXT = "Table 1 reports the estimated average treatment effects across settings."
CODE_TEXT = "def estimate(y, x):\n    return doubly_robust(y, x)"


def _block(index: int, text: str, type_: str, section_path: str) -> Block:
    return Block(
        block_id=f"{PAPER_ID}:b{index}",
        paper_id=PAPER_ID,
        text=text,
        type=type_,
        page=index // 2,
        bbox=(10.0 * index, 20.0 * index, 100.0 + index, 200.0 + index),
        section_path=section_path,
        index=index,
    )


def _parsed_doc(**overrides) -> ParsedDoc:
    """A `ParsedDoc` whose Method section pairs a prose block (b0) with an equation block (b1) —
    the exact case the "equations never split from context" invariant is about — followed by a
    prose Results block (b2) and a code block (b3) in their own sections.
    """
    blocks = [
        _block(0, PROSE_TEXT, "prose", METHOD_PATH),
        _block(1, EQUATION_LATEX, "equation", METHOD_PATH),
        _block(2, RESULTS_TEXT, "prose", RESULTS_PATH),
        _block(3, CODE_TEXT, "code", CODE_PATH),
    ]
    fields = dict(
        paper_id=PAPER_ID,
        markdown=f"# {TITLE}\n\n## 3. Method\n\n{PROSE_TEXT}\n\n$$ {EQUATION_LATEX} $$",
        blocks=blocks,
        figures=[],
        tables=[],
        references=[],
        parser_id="test-parser-1.x",
    )
    fields.update(overrides)
    return ParsedDoc(**fields)


def _config(**overrides) -> Config:
    fields = dict(focus_area_queries=["causal inference"], child_parent_expansion=True)
    fields.update(overrides)
    return Config(**fields)


def _chunk(doc: ParsedDoc | None = None, cfg: Config | None = None):
    return _mod.Chunker(cfg or _config()).chunk(doc or _parsed_doc())


# ---------------------------------------------------------------------------
# Equations/code never split from their defining context (invariant, ARCH §M3)
# ---------------------------------------------------------------------------


def test_equation_is_never_emitted_stripped_of_its_prose_context():
    chunks = _chunk()
    equation_chunks = [c for c in chunks if EQUATION_LATEX in c.text]
    assert equation_chunks, "the equation's LaTeX must survive into some chunk"
    # With child_parent_expansion ON, the equation must ride along with the prose that defines it
    # — never a lone-equation chunk that a retriever would surface without its context.
    for c in equation_chunks:
        assert PROSE_TEXT in c.text, "equation was split from its defining prose block"


def test_code_block_is_never_emitted_stripped_of_context():
    chunks = _chunk()
    code_chunks = [c for c in chunks if "doubly_robust(y, x)" in c.text]
    assert code_chunks, "the code block's text must survive into some chunk"
    for c in code_chunks:
        # A code block in its own section still keeps its section context (title+section prefix);
        # it is never emitted as a bare, context-free fragment.
        assert CODE_PATH in c.text


# ---------------------------------------------------------------------------
# parent_id is ALWAYS a block_id (never a chunk_id) and resolves
# ---------------------------------------------------------------------------


def test_parent_id_is_always_a_resolvable_block_id_never_a_chunk_id():
    doc = _parsed_doc()
    chunks = _chunk(doc)
    block_ids = {b.block_id for b in doc.blocks}
    chunk_ids = {c.chunk_id for c in chunks}
    for c in chunks:
        assert c.parent_id in block_ids, "parent_id must resolve to a real source block_id"
        assert c.parent_id not in chunk_ids, "parent_id must never be a chunk_id"


def test_parent_id_equals_anchor_block_id_by_construction():
    # DATA-CONTRACTS §M3: parent_id is by construction the same block as anchor.block_id, so the
    # Retriever never has to guess which one it is.
    for c in _chunk():
        assert c.parent_id == c.anchor.block_id


# ---------------------------------------------------------------------------
# Multi-block anchoring rule: a grouped chunk pins to the FIRST block (reading order)
# ---------------------------------------------------------------------------


def test_multi_block_chunk_anchors_to_the_first_block_in_the_group():
    doc = _parsed_doc()
    first = doc.blocks[0]  # b0, the prose block that opens the Method section
    chunks = _chunk(doc)
    grouped = [c for c in chunks if EQUATION_LATEX in c.text and PROSE_TEXT in c.text]
    assert grouped, "prose+equation must be grouped into one chunk under child_parent_expansion=on"
    for c in grouped:
        # anchor must pin the FIRST block in the group (reading order), not the equation block.
        assert c.anchor.block_id == first.block_id
        assert c.parent_id == first.block_id
        # anchor bbox/page are the first block's — never an average or the later block's.
        assert c.anchor.bbox == first.bbox
        assert c.anchor.page == first.page


# ---------------------------------------------------------------------------
# Anchors preserved end-to-end
# ---------------------------------------------------------------------------


def test_every_chunk_anchor_is_grounded_in_a_real_source_block():
    doc = _parsed_doc()
    by_id = {b.block_id: b for b in doc.blocks}
    for c in _chunk(doc):
        a = c.anchor
        assert a.paper_id == PAPER_ID
        src = by_id[a.block_id]  # KeyError here == an invented anchor -> test fails loudly
        assert a.page == src.page
        assert a.bbox == src.bbox
        assert a.section_path == src.section_path
        assert a.snippet, "anchor snippet must be non-empty (display + re-grounding check)"
        assert a.snippet in src.text, "snippet must be verbatim from the anchoring block's text"


def test_chunk_section_path_is_the_anchoring_blocks_section_path():
    doc = _parsed_doc()
    by_id = {b.block_id: b for b in doc.blocks}
    for c in _chunk(doc):
        assert c.section_path == by_id[c.anchor.block_id].section_path


# ---------------------------------------------------------------------------
# Title + section-path prefix present (free, string-level — not an LLM call)
# ---------------------------------------------------------------------------


def test_chunk_text_is_prefixed_with_title_and_section_path_before_the_body():
    doc = _parsed_doc()
    for c in _chunk(doc):
        assert TITLE in c.text, "paper title must be part of the chunk prefix"
        assert c.section_path in c.text, "section path must be part of the chunk prefix"
        body_pos = c.text.index(PROSE_TEXT) if PROSE_TEXT in c.text else len(c.text)
        # Prefix means BEFORE the body: both title and section path precede the block text.
        assert c.text.index(TITLE) < body_pos
        assert c.text.index(c.section_path) < body_pos


# ---------------------------------------------------------------------------
# V0 scope guard: contextual_header is None on EVERY chunk (ADR-07 / V1 feature)
# ---------------------------------------------------------------------------


def test_contextual_header_is_none_for_every_chunk():
    for c in _chunk():
        assert c.contextual_header is None


# ---------------------------------------------------------------------------
# child_parent_expansion=off forces one chunk per block (equation split from prose)
# ---------------------------------------------------------------------------


def test_expansion_off_splits_each_block_into_its_own_chunk():
    doc = _parsed_doc()
    chunks = _chunk(doc, _config(child_parent_expansion=False))
    assert len(chunks) == len(doc.blocks), "off => exactly one chunk per block"
    # The equation is now on its own, split from the prose it belongs to (the behaviour the ON
    # default deliberately avoids).
    lone_equation = [c for c in chunks if EQUATION_LATEX in c.text and PROSE_TEXT not in c.text]
    assert lone_equation, "off must separate the equation from its defining prose"


def test_chunks_are_emitted_and_ids_are_unique():
    chunks = _chunk()
    assert chunks, "a non-empty ParsedDoc must yield at least one chunk"
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), "chunk_ids must be unique within a paper"
    assert all(c.paper_id == PAPER_ID for c in chunks)
