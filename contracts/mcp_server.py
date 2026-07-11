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
    """How big was the haystack behind a top-k sample. Not used by `get_paper`/`get_span` (they
    resolve one fully-specified thing, not a sample). Full reasoning: DATA-CONTRACTS.md §M8.
    """

    returned: int = Field(ge=0)  # len(results) — after rerank + top_k truncation
    # len(Hit list) from VectorIndex.hybrid_search — the fused candidate pool BEFORE
    # rerank/top_k truncation — "how many were in the running"
    candidates: int = Field(ge=0)


class SearchResponse(FrozenModel):
    """`semantic_search`'s return shape — results plus a typed `Coverage`, not a bare
    `list[GroundedResult]`. Full reasoning: DATA-CONTRACTS.md §M8.
    """

    results: list[GroundedResult]
    coverage: Coverage


class PaperSearchResult(FrozenModel):
    """`search_papers`'s per-item shape — a whole-paper/summary-level match from
    `Retriever.retrieve_papers()`. Deliberately not a `GroundedResult` (a summary has no block to
    anchor to); wraps `PaperSummaryView` with the ranking `score`. Full reasoning:
    DATA-CONTRACTS.md §M8.
    """

    view: PaperSummaryView
    score: float


class PaperSearchResponse(FrozenModel):
    """`search_papers`'s return shape — mirrors `SearchResponse` for whole-paper results (no
    `evidence_tier`/`metadata`; that envelope doesn't apply to summary-level matches). Full
    reasoning: DATA-CONTRACTS.md §M8.
    """

    results: list[PaperSearchResult]
    coverage: Coverage
