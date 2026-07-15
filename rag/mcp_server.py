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
from contracts.retriever import Citation, RetrievalCoverage
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
        """Passage-level search, delegated whole to `Retriever.retrieve()`. Always searches the
        full chunk index across the whole corpus — `filters` (`SearchFilters`) can narrow by
        category/date/kind, but has no paper-id field, so this tool alone cannot be scoped to one
        paper or a known handful of papers. If the query is about a specific paper or a small set
        of papers you already suspect matter, call `search_papers` first: it identifies which
        paper(s) are actually relevant from a cheap summary-level match before any chunk search
        runs, so you can decide whether a full-corpus chunk search is even needed and can check
        this tool's results (each carries its own `paper_id`) against that expectation instead of
        trusting an unscoped search alone. This project's agent-as-reasoner design (CONTEXT.md,
        PRD.md §11A) puts that sequencing decision on the calling agent; this server never
        auto-rewrites or narrows a query on its own. Postcondition: on an empty corpus/no hits,
        `results == []` — empty is a valid answer, not an error.
        """
        results, retrieval_coverage = self._retriever.retrieve(query, filters, k)
        return SearchResponse(results=results, coverage=self._coverage(results, retrieval_coverage))

    def search_papers(
        self, query: str, filters: SearchFilters | None = None, k: int = 10
    ) -> PaperSearchResponse:
        """Whole-paper/summary-level search, delegated whole to `Retriever.retrieve_papers()`. This
        is the right first call when a query is scoped to a specific paper or a handful of papers:
        it ranks whole papers by their summary — cheaply, before any chunk-level retrieval or
        reranking runs — so you can confirm which paper(s) actually matter, or find that a
        confirmed match's `get_paper` summary already answers the question without needing a
        broader `semantic_search` chunk search at all. Postcondition: on no hits, `results == []`.
        """
        results, retrieval_coverage = self._retriever.retrieve_papers(query, filters, k)
        return PaperSearchResponse(
            results=results, coverage=self._coverage(results, retrieval_coverage)
        )

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
    def _coverage(results: list, retrieval_coverage: RetrievalCoverage) -> Coverage:
        # T-DOC28: `Coverage.candidates` is the true pre-rerank/pre-top_k hybrid_search pool size
        # (DATA-CONTRACTS.md §M8) that `Retriever.retrieve()`/`retrieve_papers()` now reports via
        # `RetrievalCoverage` (contracts/retriever.py) alongside their results list — no longer a
        # `len(results)` stand-in. `returned` is still `len(results)`: truncation to `k` only ever
        # narrows the pool, so `candidates >= returned` remains the caller-facing invariant.
        return Coverage(returned=len(results), candidates=retrieval_coverage.candidate_count)

    @staticmethod
    def _distinct_section_paths(blocks) -> list[str]:
        ordered = sorted(blocks, key=lambda b: b.index)
        seen: list[str] = []
        for block in ordered:
            if block.section_path not in seen:
                seen.append(block.section_path)
        return seen
