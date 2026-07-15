"""M7 Retriever output — the envelope, frozen shape, forward-compatible to V2 (DATA-CONTRACTS.md
"M7 Retriever output") — plus its internal Reranker collaborator's shape.

`Retriever`'s own interface (`retrieve`/`retrieve_papers`) and `Reranker`'s own interface
(`rerank`) are the modules' own interfaces (ARCHITECTURE.md, owned by Owner E) — not reproduced
here; only the data shapes that cross the seam are. `RetrievalCoverage` (T-DOC28) is one such
shape: both methods return it alongside their results list so `McpServer` can build a real
`Coverage.candidates` (see that class's own docstring).
"""

from typing import Literal

from pydantic import Field

from contracts._base import FrozenModel
from contracts.provenance import Anchor

EvidenceTier = Literal["A", "B", "C", "D"]


class Citation(FrozenModel):
    paper_id: str
    title: str
    authors: list[str]
    arxiv_url: str
    section_path: str


class GroundedResult(FrozenModel):
    """Passage-level retrieval envelope, grounded and forward-compatible to V1/V2. `passage_text`
    is the matched Chunk's own full text (not a `get_span` fetch); `anchor` is for citation
    display/re-grounding only. `evidence_tier`/`metadata` are the slots V1/V2 fill in place. Full
    reasoning: DATA-CONTRACTS.md §M7.
    """

    passage_text: str
    anchor: Anchor
    paper_id: str
    score: float
    citation: Citation
    evidence_tier: EvidenceTier = "A"  # PINNED to "A" in V0; B/C/D land in V1/V2 (PRD §8.5)
    # empty in V0; V1/V2 add status/conditions/confidence. Populating this field is a `contracts/`
    # shape change, not a free write by a downstream module — it goes through the T-F7
    # foundation-change protocol like any other contracts/ edit.
    metadata: dict = Field(default_factory=dict)


class RerankCandidate(FrozenModel):
    id: str  # chunk_id or summary_id — same id space as Hit
    text: str  # the text to score against the query (chunk/summary text)


class RetrievalCoverage(FrozenModel):
    """T-DOC28: the true pre-rerank/pre-top_k candidate-pool size behind one `retrieve()`/
    `retrieve_papers()` call — `len(Hit list)` from `VectorIndex.hybrid_search()`, before rerank
    truncates it down to the caller's `k` (`_RERANK_POOL_SIZE`, rag/retriever.py, tunes the floor
    of this pool). This is the number `contracts/mcp_server.py`'s `Coverage.candidates` is
    documented to report (DATA-CONTRACTS.md §M8) but `list[GroundedResult]`/
    `list[PaperSearchResult]` alone can't carry once top_k truncation has cut them down to `k`
    results. `McpServer` combines this with `len(results)` to build the public `Coverage`
    envelope — this type itself is never part of an MCP tool's response.
    """

    candidate_count: int = Field(ge=0)
