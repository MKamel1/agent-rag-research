"""M7 Retriever (T-E1) — the crown-jewel deep module: two methods sharing one internal pipeline,
embed-query -> hybrid -> RRF -> rerank -> resolve. Full design intent: ARCHITECTURE.md "M7 ·
Retriever"; frozen envelope shapes: `contracts/retriever.py`; DATA-CONTRACTS.md §M7.

`retrieve()` is passage-level (kind="chunk", resolved into a grounded `GroundedResult` whose
`passage_text` is the matched `Chunk`'s own text — never a `get_span(anchor)` fetch, DATA-
CONTRACTS.md "Provenance & structure"). `retrieve_papers()` is whole-paper (kind="summary",
resolved into an unanchored `PaperSearchResult`). Both rerank through the same injected
`Reranker` — a constructor dependency, never hardcoded, so callers can pass `FakeReranker` (zero
GPU) or the real cross-encoder adapter interchangeably (CONVENTIONS §1/§2).
"""

from contracts.mcp_server import PaperSearchResult, PaperSummaryView
from contracts.retriever import Citation, GroundedResult, RerankCandidate
from contracts.vector_index import SearchFilters

_SUMMARY_ID_SUFFIX = ":summary"


class Retriever:
    """Constructor-injected collaborators only (CONVENTIONS §2): `embedder`, `vector_store`,
    `document_store`, `reranker`. Never constructs a vendor client itself — that stays inside
    each collaborator's own adapter (CONVENTIONS §1).
    """

    def __init__(self, embedder, vector_store, document_store, reranker):
        self._embedder = embedder
        self._vector_store = vector_store
        self._document_store = document_store
        self._reranker = reranker

    def retrieve(self, query: str, filters: SearchFilters | None, k: int) -> list[GroundedResult]:
        """Passage-level search. Every result is grounded: a resolvable `anchor` + `citation`,
        and `passage_text` is the resolved `Chunk`'s own full text (DATA-CONTRACTS.md
        "Provenance & structure" — NOT `get_span(anchor)`, which would silently drop the 2nd+
        block of a multi-block chunk).
        """
        hits = self._hybrid_hits(query, filters, k, kind="chunk")
        if not hits:
            return []
        scores = {hit.id: hit.score for hit in hits}
        chunks = {hit.id: self._document_store.get_chunk(hit.id) for hit in hits}
        candidates = [RerankCandidate(id=hit.id, text=chunks[hit.id].text) for hit in hits]

        results = []
        for candidate in self._reranker.rerank(query, candidates):
            chunk = chunks[candidate.id]
            # Block.section_path is the AUTHORITATIVE copy (Chunk.section_path is a derived copy
            # taken at chunk-build time, DATA-CONTRACTS.md "Provenance & structure") — the
            # citation reads it from the source block, not the derived copy.
            block = self._document_store.get_block(chunk.anchor.block_id)
            ref = self._document_store.get(chunk.paper_id).ref
            citation = Citation(
                paper_id=chunk.paper_id,
                title=ref.title,
                authors=ref.authors,
                arxiv_url=f"https://arxiv.org/abs/{chunk.paper_id}",
                section_path=block.section_path,
            )
            results.append(
                GroundedResult(
                    passage_text=chunk.text,
                    anchor=chunk.anchor,
                    paper_id=chunk.paper_id,
                    score=scores[candidate.id],
                    citation=citation,
                )
            )
        return results

    def retrieve_papers(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[PaperSearchResult]:
        """Whole-paper/summary-level search. Deliberately unanchored — a summary has no block to
        anchor to (DATA-CONTRACTS.md §M7) — so results are `PaperSearchResult`s, not
        `GroundedResult`s. `PaperSearchResult`/`PaperSummaryView` are `contracts/` shapes (owned
        by `contracts/mcp_server.py`, DATA-CONTRACTS.md §M8) that `Retriever.retrieve_papers()`'s
        own frozen interface (ARCHITECTURE.md §M7) returns — this is a `contracts/` shape import,
        not a dependency on the `McpServer` module's logic (CONVENTIONS §1's vendor rule doesn't
        apply to shared shapes within `contracts/`, same as `contracts/mcp_server.py` importing
        `Citation`/`GroundedResult` back from `contracts/retriever.py`).
        """
        hits = self._hybrid_hits(query, filters, k, kind="summary")
        if not hits:
            return []
        scores = {hit.id: hit.score for hit in hits}
        texts = {hit.id: self._document_store.get_summary(hit.id) for hit in hits}
        candidates = [RerankCandidate(id=hit.id, text=texts[hit.id]) for hit in hits]

        results = []
        for candidate in self._reranker.rerank(query, candidates):
            # `summary_id` is documented as "{paper_id}:summary" (DATA-CONTRACTS.md "IDs" — the
            # public spine, not a DocumentStore-internal secret the way chunk/block ids are
            # elsewhere): `Hit`/`get_summary` carry no paper_id field to resolve() against, so
            # this is the one legitimate place the format is read rather than parsed away by
            # `get_chunk`/`get_block`/`get_summary` (CONVENTIONS §12(h) bans slicing chunk_id/
            # block_id/summary_id to avoid *re-deriving* what those resolvers already hand back;
            # here there is no resolver that hands back paper_id at all).
            paper_id = candidate.id.removesuffix(_SUMMARY_ID_SUFFIX)
            record = self._document_store.get(paper_id)
            section_paths = self._distinct_section_paths(record.parsed.blocks)
            view = PaperSummaryView(
                paper_id=paper_id,
                title=record.ref.title,
                authors=record.ref.authors,
                summary_text=texts[candidate.id],
                section_paths=section_paths,
                citation=Citation(
                    paper_id=paper_id,
                    title=record.ref.title,
                    authors=record.ref.authors,
                    arxiv_url=f"https://arxiv.org/abs/{paper_id}",
                    section_path="",  # unanchored — no single section a whole-paper match is "at"
                ),
            )
            results.append(PaperSearchResult(view=view, score=scores[candidate.id]))
        return results

    def _hybrid_hits(self, query: str, filters: SearchFilters | None, k: int, *, kind: str):
        qvec = self._embedder.embed([query])[0]
        # `kind` is fixed by which method the caller called, never a caller choice (ARCHITECTURE
        # §M7) — any `filters.kind` the caller passed is overridden, not merged as a conflict.
        data = filters.model_dump() if filters is not None else {}
        data["kind"] = kind
        scoped_filters = SearchFilters(**data)
        return self._vector_store.hybrid_search(qvec, query, scoped_filters, k)

    @staticmethod
    def _distinct_section_paths(blocks) -> list[str]:
        ordered = sorted(blocks, key=lambda b: b.index)
        seen: list[str] = []
        for block in ordered:
            if block.section_path not in seen:
                seen.append(block.section_path)
        return seen
