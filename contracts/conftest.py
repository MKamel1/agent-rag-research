"""Shared pytest fixtures for `contracts/`'s sibling test files.

Design-review finding (PR #5): construction of the frozen shapes here was copy-pasted across
5-6 test files as file-local `_make_*(**overrides)` helpers, and had already drifted — the same
logical object (e.g. a minimally-valid `Anchor`, or `PaperRef`) was built with different default
values, and sometimes a different signature (`**overrides` accepted in one file, not in its
sibling), depending on which file you looked at. `conftest.py` is pytest's own mechanism for
sharing fixtures across sibling test files in one directory, so this module holds the one copy
of "what's a minimally-valid X" for every shape `contracts/` defines, at two tiers:

- Leaf-level (`valid_bbox`, `make_anchor`, `make_citation`, `make_paper_ref`, `make_block`) —
  the shapes that don't nest another `contracts/` model.
- Composite-level (`make_chunk`, `make_parsed_doc`, `make_paper_record`, `make_grounded_result`,
  `make_paper_summary_view`) — shapes built from the leaf fixtures above, so a change to a leaf
  default (e.g. `valid_bbox`) propagates to every composite that uses it, instead of requiring a
  second edit.

Every `make_*` fixture is a factory (not the object itself) and takes `**overrides` — a test that
needs one field different from the default calls `make_anchor(page=3)` rather than rebuilding the
whole object or adding a second copy of the helper. Per-test variation always goes through
`**overrides`; if you're tempted to write a new file-local `_make_*` helper instead, that's the
signal the shared fixture is missing a field it should accept (all of them accept every field of
their model via `**overrides` — none restrict which fields can be overridden).

Where defaults were inconsistent across the files this consolidates (documented here so the
choice is visible, not silently picked): `test_provenance.py`'s old `_make_anchor` used
`snippet="This is the first two hundred characters..."` and `section_path="3. Method > 3.2
Estimator"`, while every other file's copy used `snippet="Some verbatim text."` and
`section_path="3. Method"` — the majority value won, and no test asserted on the specific
snippet/section_path text. `test_provenance.py`'s old `VALID_BBOX = (10.0, 20.0, 110.0, 220.0)`
similarly lost to the `(0.0, 0.0, 100.0, 200.0)` used everywhere else. `test_document_store.py`'s
old `_make_paper_ref` (no `**overrides`, single-item `authors`/`categories`) and
`test_harvester.py`'s old `_make_paper_ref(**overrides)` (two-item lists) were the same logical
object with two different contracts; the shared `make_paper_ref` here always accepts
`**overrides` (one contract, matching the `**overrides`-everywhere convention) and keeps the
richer two-item lists as the default since no test depended on the single-item version.
"""

from datetime import date

import pytest

from contracts.chunker import Chunk
from contracts.document_store import PaperRecord
from contracts.harvester import PaperRef
from contracts.mcp_server import PaperSummaryView
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor, Block
from contracts.retriever import Citation, GroundedResult

# ---------------------------------------------------------------------------
# Leaf-level fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_bbox() -> tuple[float, float, float, float]:
    return (0.0, 0.0, 100.0, 200.0)


@pytest.fixture
def make_anchor(valid_bbox):
    def _make(**overrides) -> Anchor:
        fields = dict(
            paper_id="2506.01234",
            block_id="2506.01234:b0",
            page=0,
            bbox=valid_bbox,
            snippet="Some verbatim text.",
            section_path="3. Method",
        )
        fields.update(overrides)
        return Anchor(**fields)

    return _make


@pytest.fixture
def make_block(valid_bbox):
    def _make(**overrides) -> Block:
        fields = dict(
            block_id="2506.01234:b0",
            paper_id="2506.01234",
            text="Some prose.",
            type="prose",
            page=0,
            bbox=valid_bbox,
            section_path="3. Method",
            index=0,
        )
        fields.update(overrides)
        return Block(**fields)

    return _make


@pytest.fixture
def make_citation():
    def _make(**overrides) -> Citation:
        fields = dict(
            paper_id="2506.01234",
            title="A Causal Method",
            authors=["A. Author"],
            arxiv_url="https://arxiv.org/abs/2506.01234",
            section_path="3. Method",
        )
        fields.update(overrides)
        return Citation(**fields)

    return _make


@pytest.fixture
def make_paper_ref():
    def _make(**overrides) -> PaperRef:
        fields = dict(
            paper_id="2506.01234",
            version="v1",
            title="A Causal Method",
            abstract="We propose...",
            authors=["A. Author", "B. Author"],
            categories=["cs.LG", "stat.ME"],
            published=date(2026, 6, 1),
            updated=date(2026, 6, 1),
            pdf_url="https://arxiv.org/pdf/2506.01234v1",
        )
        fields.update(overrides)
        return PaperRef(**fields)

    return _make


# ---------------------------------------------------------------------------
# Composite-level fixtures (built from the leaf fixtures above)
# ---------------------------------------------------------------------------


@pytest.fixture
def make_chunk(make_anchor):
    def _make(**overrides) -> Chunk:
        fields = dict(
            chunk_id="2506.01234:c0",
            paper_id="2506.01234",
            text="Some chunk text.",
            anchor=make_anchor(),
            section_path="3. Method",
            parent_id="2506.01234:b0",
        )
        fields.update(overrides)
        return Chunk(**fields)

    return _make


@pytest.fixture
def make_parsed_doc():
    def _make(**overrides) -> ParsedDoc:
        fields = dict(
            paper_id="2506.01234",
            markdown="# Title",
            blocks=[],
            figures=[],
            tables=[],
            references=[],
            parser_id="mineru-1.x",
        )
        fields.update(overrides)
        return ParsedDoc(**fields)

    return _make


@pytest.fixture
def make_paper_record(make_paper_ref, make_parsed_doc, make_chunk):
    def _make(**overrides) -> PaperRecord:
        fields = dict(
            ref=make_paper_ref(),
            parsed=make_parsed_doc(),
            chunks=[make_chunk()],
            summary_text="A short summary.",
            summary_id="2506.01234:summary",
        )
        fields.update(overrides)
        return PaperRecord(**fields)

    return _make


@pytest.fixture
def make_grounded_result(make_anchor, make_citation):
    def _make(**overrides) -> GroundedResult:
        fields = dict(
            passage_text="The estimator is defined as...",
            anchor=make_anchor(),
            paper_id="2506.01234",
            score=0.91,
            citation=make_citation(),
        )
        fields.update(overrides)
        return GroundedResult(**fields)

    return _make


@pytest.fixture
def make_paper_summary_view(make_citation):
    def _make(**overrides) -> PaperSummaryView:
        fields = dict(
            paper_id="2506.01234",
            title="A Causal Method",
            authors=["A. Author"],
            summary_text="A short summary.",
            section_paths=["1. Intro", "3. Method"],
            citation=make_citation(),
        )
        fields.update(overrides)
        return PaperSummaryView(**fields)

    return _make
