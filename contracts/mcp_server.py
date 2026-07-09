"""M8 McpServer — response envelope (DATA-CONTRACTS.md "M8 McpServer — response envelope").

Every MCP tool returns results as records, never bare text (PRD §8.5). `McpServer`'s own
interface (the four tools: `search_papers`/`semantic_search`/`get_paper`/`get_span`) is the
module's own interface (ARCHITECTURE.md, owned by Owner E) — not reproduced here; only the
response shapes are.
"""

from pydantic import Field

from contracts._base import FrozenModel
from contracts.retriever import Citation, GroundedResult


class PaperSummaryView(FrozenModel):
    """`get_paper`'s return shape — named here instead of left as prose so it isn't reinvented per
    caller.
    """

    paper_id: str
    title: str
    authors: list[str]
    summary_text: str
    section_paths: list[str]  # distinct Block.section_path values, in reading order
    citation: Citation


class Coverage(FrozenModel):
    """How big was the haystack. Only meaningful for tools that return a top-k SAMPLE of a larger
    candidate set — `get_paper`/`get_span` each resolve one specific, fully-specified thing, so
    there is no 'you're seeing part of it' concept for them and they are NOT wrapped in this
    envelope.
    """

    returned: int = Field(ge=0)  # len(results) — after rerank + top_k truncation
    # len(Hit list) from VectorIndex.hybrid_search — the fused candidate pool BEFORE
    # rerank/top_k truncation — "how many were in the running"
    candidates: int = Field(ge=0)


class SearchResponse(FrozenModel):
    """`semantic_search`'s return shape. Replaces a bare `list[GroundedResult]` — the 'coverage
    note' was previously prose only (no field on any frozen type), so it was unwritable and
    untestable as specified. This is the fix: the shape that crosses the M8 seam is now fully
    typed.
    """

    results: list[GroundedResult]
    coverage: Coverage


class PaperSearchResult(FrozenModel):
    """`search_papers`'s per-item shape — a whole-paper/summary-level match, produced by
    `Retriever.retrieve_papers()` (§M7). Deliberately NOT a `GroundedResult`: a summary has no
    block/page/bbox to anchor to (`Anchor` is block-level only), so forcing it through the
    anchored envelope would require either a nullable `anchor` (breaks the "every result is
    grounded" invariant) or a dummy/abstract-block anchor (a fabricated citation). Wraps
    `PaperSummaryView` (the exact shape `get_paper` returns for one paper) with the ranking
    `score` search adds, instead of duplicating its fields.
    """

    view: PaperSummaryView
    score: float


class PaperSearchResponse(FrozenModel):
    """`search_papers`'s return shape — mirrors `SearchResponse` but for whole-paper results, which
    carry no `evidence_tier`/`metadata` envelope (that envelope stages passage-level grounding
    claims — tier A/B/C/D — which don't apply here; `PaperSummaryView.summary_text` already says
    in prose that this is a paraphrase, CONTEXT.md tier C, with no separate field needed to say
    it twice).
    """

    results: list[PaperSearchResult]
    coverage: Coverage
