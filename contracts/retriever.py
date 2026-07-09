"""M7 Retriever output — the envelope, frozen shape, forward-compatible to V2 (DATA-CONTRACTS.md
"M7 Retriever output") — plus its internal Reranker collaborator's shape.

`Retriever`'s own interface (`retrieve`/`retrieve_papers`) and `Reranker`'s own interface
(`rerank`) are the modules' own interfaces (ARCHITECTURE.md, owned by Owner E) — not reproduced
here; only the data shapes that cross the seam are.
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
    """`passage_text` is the matched `Chunk`'s own text, in full — NOT a `get_span(anchor)` fetch.
    This IS V0's small-to-big unit: the Chunker already grouped the right blocks at chunk-build
    time (`Config.child_parent_expansion`); nothing further is expanded at query time
    (DATA-CONTRACTS.md "What this means for GroundedResult.passage_text").

    `anchor` == the matched Chunk's own anchor (its first block, multi-block anchoring rule).
    Used for citation display and re-grounding (`get_span(anchor)`) — never the source of
    `passage_text` itself.

    `GroundedResult` is passage-level only — `Retriever.retrieve()` never returns a
    summary/whole-paper match (a summary has no block to anchor to). Whole-paper search has its
    own shape, `PaperSearchResult` (`contracts/mcp_server.py`).

    Why the envelope now (forward-compat): V1/V2 add evidence tiers, `status: superseded_by`,
    and `conditions`. Because this is already a record with `evidence_tier` + `metadata`, those
    land as filled fields, not a changed type — no V0 consumer breaks. Never return a bare
    string from retrieval.
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
