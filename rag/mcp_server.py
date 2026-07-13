"""M8 McpServer (T-E2) — the protocol edge, acceptably thin. Full design intent:
ARCHITECTURE.md "M8 · McpServer"; frozen envelope shapes: `contracts/mcp_server.py`;
DATA-CONTRACTS.md §M8.

Four tools — `search_papers`/`semantic_search`/`get_paper`/`get_span` — every one returns a typed
record, never bare text (PRD §8.5). `search_papers`/`semantic_search` do nothing but call
`Retriever.retrieve_papers()`/`Retriever.retrieve()` and wrap the result in the typed
`PaperSearchResponse`/`SearchResponse` envelope: this module never touches `Embedder`/
`VectorStore`/`Reranker` and never reimplements the embed/hybrid/RRF/rerank pipeline — that
pipeline is M7's secret to keep (ARCHITECTURE.md "M7 · Retriever"). Only two constructor
dependencies (`retriever`, `document_store`) by design — a third pipeline-shaped dependency isn't
even an option here.
"""

from contracts.errors import ContractError
from contracts.mcp_server import Coverage, PaperSearchResponse, PaperSummaryView, SearchResponse
from contracts.provenance import Anchor
from contracts.retriever import Citation
from contracts.vector_index import SearchFilters


class McpServer:
    """Constructor-injected collaborators only (CONVENTIONS §2): `retriever`, `document_store`.
    Never constructs a vendor client or the retrieval pipeline itself.
    """

    def __init__(self, retriever, document_store):
        self._retriever = retriever
        self._document_store = document_store

    def semantic_search(
        self, query: str, filters: SearchFilters | None = None, k: int = 10
    ) -> SearchResponse:
        """Passage-level search, delegated whole to `Retriever.retrieve()`. Postcondition: on an
        empty corpus/no hits, `results == []` — empty is a valid answer, not an error.
        """
        results = self._retriever.retrieve(query, filters, k)
        return SearchResponse(results=results, coverage=self._coverage(results))

    def search_papers(
        self, query: str, filters: SearchFilters | None = None, k: int = 10
    ) -> PaperSearchResponse:
        """Whole-paper/summary-level search, delegated whole to `Retriever.retrieve_papers()`.
        Postcondition: on no hits, `results == []`.
        """
        results = self._retriever.retrieve_papers(query, filters, k)
        return PaperSearchResponse(results=results, coverage=self._coverage(results))

    def get_paper(self, paper_id: str) -> PaperSummaryView:
        """Precondition: `paper_id` is a stored paper; else `ContractError`. Postcondition:
        `section_paths` are the distinct `Block.section_path` values, in reading order.
        """
        record = self._document_store.get(paper_id)
        if record is None:
            raise ContractError(f"get_paper: unknown paper_id {paper_id!r}")
        section_paths = self._distinct_section_paths(record.parsed.blocks)
        return PaperSummaryView(
            paper_id=paper_id,
            title=record.ref.title,
            authors=record.ref.authors,
            summary_text=record.summary_text,
            section_paths=section_paths,
            citation=Citation(
                paper_id=paper_id,
                title=record.ref.title,
                authors=record.ref.authors,
                arxiv_url=f"https://arxiv.org/abs/{paper_id}",
                section_path="",  # whole-paper citation — no single section it's "at"
            ),
        )

    def get_span(self, anchor: Anchor) -> str:
        """Precondition: `anchor` resolves to a stored block; else `ContractError` (a dangling
        anchor is a grounding bug, not a normal "not found").
        """
        return self._document_store.get_span(anchor)

    @staticmethod
    def _coverage(results: list) -> Coverage:
        # `Coverage.candidates` is documented (DATA-CONTRACTS.md §M8) as the pre-rerank/pre-top_k
        # hybrid_search pool size. `Retriever.retrieve()`/`retrieve_papers()`'s frozen interface
        # (ARCHITECTURE.md §M7) returns only the final `list[GroundedResult]`/
        # `list[PaperSearchResult]` — it doesn't expose that pool size, by design (M8 stays thin
        # and never reaches past the two `Retriever` methods, CONVENTIONS §1). So the only value
        # this layer can honestly report is `len(results)` for both fields — `candidates >=
        # returned` still holds (with equality). Surfacing the true pre-rerank count would need a
        # `Retriever`/`contracts/` interface change, which is a T-F7 foundation-change decision,
        # not a free write here.
        return Coverage(returned=len(results), candidates=len(results))

    @staticmethod
    def _distinct_section_paths(blocks) -> list[str]:
        ordered = sorted(blocks, key=lambda b: b.index)
        seen: list[str] = []
        for block in ordered:
            if block.section_path not in seen:
                seen.append(block.section_path)
        return seen
