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


class BlockMatch(FrozenModel):
    """One block whose text matched a `scan_corpus` pattern.

    `section_path` is the field that makes a match adjudicable: a method named under "Related Work"
    is a citation, one named under "Methods" is a use, and retrieval cannot tell those apart on its
    own. It is `""` when the parser could not detect a heading (measured: 5.0% of blocks in the
    Waymo corpus, but 61.7% for one paper) -- an empty value means "judge from the text", never
    "not in a section".
    """

    paper_id: str
    block_id: str
    page: int = Field(ge=0)
    section_path: str
    title: str  # the paper's title, so a caller can adjudicate without a second get_paper call
    snippet: str  # the matched text with surrounding context, verbatim


class ScanResponse(FrozenModel):
    """`scan_corpus`'s return shape.

    Deliberately NOT a `SearchResponse`: there is no ranking here and no `score`, because scanning
    answers a different question from searching. `semantic_search` answers "what are the best k
    passages for this query" — a top-k sample of a ranked list. `scan_corpus` answers "which
    documents contain this pattern" — an exhaustive enumeration whose recall is 1.0 by construction
    because every block is examined. A caller asking "which papers used method X" needs the second
    and will get a silently incomplete answer from the first.

    `papers_scanned` / `papers_matched` are what make the completeness claim checkable: a caller can
    see the denominator it was measured against rather than trust that the tool looked
    everywhere.
    `truncated` is set when `max_matches_per_paper` hid further matches within a paper — the paper
    still appears, so a truncated scan never loses a PAPER, only extra evidence within one.
    """

    matches: list[BlockMatch]
    papers_scanned: int = Field(ge=0)
    papers_matched: int = Field(ge=0)
    truncated: bool = False


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
    # Set when this routing hit resolved from a chapter summary ({paper_id}:summary:ch{n}) —
    # the chapter's title. None for whole-paper/whole-book hits.
    chapter: str | None = None


class PaperSearchResponse(FrozenModel):
    """`search_papers`'s return shape — mirrors `SearchResponse` for whole-paper results (no
    `evidence_tier`/`metadata`; that envelope doesn't apply to summary-level matches). Full
    reasoning: DATA-CONTRACTS.md §M8.
    """

    results: list[PaperSearchResult]
    coverage: Coverage
