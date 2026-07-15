"""M7 Retriever (T-E1) — the crown-jewel deep module: two methods sharing one internal pipeline,
embed-query -> hybrid -> RRF -> rerank -> resolve. Full design intent: ARCHITECTURE.md "M7 ·
Retriever"; frozen envelope shapes: `contracts/retriever.py`; DATA-CONTRACTS.md §M7.

`retrieve()` is passage-level (kind="chunk", resolved into a grounded `GroundedResult` whose
`passage_text` is the matched `Chunk`'s own text — never a `get_span(anchor)` fetch, DATA-
CONTRACTS.md "Provenance & structure"). `retrieve_papers()` is whole-paper (kind="summary",
resolved into an unanchored `PaperSearchResult`). Both rerank through the same injected
`Reranker` — a constructor dependency, never hardcoded, so callers can pass `FakeReranker` (zero
GPU) or the real cross-encoder adapter interchangeably (CONVENTIONS §1/§2).

T-DOC24: both methods fetch `_RERANK_POOL_SIZE` candidates for reranking, not just the caller's
`k` -- see `_RERANK_POOL_SIZE`'s own docstring for why a real T-EVAL investigation found the
previous "fetch exactly k, rerank those k" shape left the reranker unable to ever promote a
correct passage the cheaper first-pass hybrid/RRF ranking under-ranked.

T-DOC28: both methods return `(results, RetrievalCoverage)` rather than a bare results list, so
`McpServer` can report the true pre-truncation pool size (`len(hits)`, below) as
`Coverage.candidates` instead of the `len(results)` stand-in it used to fall back on.
"""

from contracts.errors import ContractError
from contracts.mcp_server import PaperSearchResult, PaperSummaryView
from contracts.retriever import Citation, GroundedResult, RerankCandidate, RetrievalCoverage
from contracts.vector_index import SearchFilters

_SUMMARY_ID_SUFFIX = ":summary"

# The reranker can only ever reorder the candidates it's given -- it never fabricates or drops any
# (TeiReranker.rerank()'s own contract: a length-preserving reordering by score). Fetching only
# `k` candidates before reranking means the reranker can't promote anything the earlier hybrid/RRF
# pass ranked below `k` -- a real T-EVAL investigation found every one of 30 real single-passage
# misses fit exactly this shape (correct paper always in the top 10, wrong specific passage of it
# ranked above the gold one). Fetch a meaningfully larger pool, then truncate to the caller's
# requested `k` only after reranking has had a chance to reorder it in.
#
# T-DOC25 (urgent correction to T-DOC24): the real TEI `/rerank` endpoint enforces a hard
# server-side max batch size -- confirmed live: a 50-text request gets a 422 `{"error":"batch
# size 50 > maximum allowed batch size 32", "error_type":"Validation"}`, a 32-text request
# succeeds. `TeiReranker.rerank()` maps that 422 to a `PermanentError` (rag/reranker.py, 422 is
# not in `_RETRYABLE_STATUSES`), so T-DOC24's original 50 broke every single real retrieve() call
# in production -- 100% failure, not caught before merge because the fakes-only test suite has no
# real batch-size ceiling to violate. 32 is the real, currently-deployed ceiling for this TEI
# container (`--model-id BAAI/bge-reranker-v2-m3`, no `--max-client-batch-size` override set); this
# is a plain tuning constant capped at that measured real limit, not a guess. Raising the server's
# own limit (a container restart with an explicit flag) is a separate, riskier infra change, out
# of scope for this fix -- this just makes the code respect the limit that already exists.
_RERANK_POOL_SIZE = 32


def _paper_id_from_summary_hit_id(hit_id: str) -> str:
    """Recovers `paper_id` from a `summary`-kind `Hit.id`/`RerankCandidate.id` string.

    This is the ONE sanctioned place in the codebase that parses the `"{paper_id}:summary"`
    format (DATA-CONTRACTS.md "IDs — the spine"). `get_summary`/`Hit` carry no `paper_id` field to
    resolve() against (unlike `get_chunk`/`get_block`, which hand `paper_id` back on the resolved
    record) — there is no getter to call instead. `ci/checks/id_slicing.py` fences its check
    around this exact function by name; if a second call site ever needs this, that need is the
    signal to promote `paper_id` to a first-class field on `Hit` instead of adding a second ad-hoc
    parse site.
    """
    return hit_id.removesuffix(_SUMMARY_ID_SUFFIX)


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

    def retrieve(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> tuple[list[GroundedResult], RetrievalCoverage]:
        """Passage-level search. Every result is grounded: a resolvable `anchor` + `citation`,
        and `passage_text` is the resolved `Chunk`'s own full text (DATA-CONTRACTS.md
        "Provenance & structure" — NOT `get_span(anchor)`, which would silently drop the 2nd+
        block of a multi-block chunk).

        Returns `(results, coverage)`: `coverage.candidate_count` (T-DOC28) is the true
        pre-rerank/pre-top_k hybrid-search pool size (`len(hits)`, below) — always `>=
        len(results)`, since truncation to `k` only ever narrows the pool. `McpServer` uses it to
        build the real `Coverage.candidates` (contracts/mcp_server.py) instead of the `len(results)`
        stand-in it used to fall back on.
        """
        hits = self._hybrid_hits(query, filters, max(k, _RERANK_POOL_SIZE), kind="chunk")
        if not hits:
            return [], RetrievalCoverage(candidate_count=0)
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
            record = self._document_store.get(chunk.paper_id)
            if record is None:
                raise ContractError(f"DocumentStore has no record for paper_id={chunk.paper_id!r}")
            ref = record.ref
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
        # Reranked results are sized to the pool, not the caller's `k` -- truncate only now that
        # reranking has had the chance to promote a correct passage into the top `k` (T-DOC24).
        return results[:k], RetrievalCoverage(candidate_count=len(hits))

    def retrieve_papers(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> tuple[list[PaperSearchResult], RetrievalCoverage]:
        """Whole-paper/summary-level search. Deliberately unanchored — a summary has no block to
        anchor to (DATA-CONTRACTS.md §M7) — so results are `PaperSearchResult`s, not
        `GroundedResult`s. `PaperSearchResult`/`PaperSummaryView` are `contracts/` shapes (owned
        by `contracts/mcp_server.py`, DATA-CONTRACTS.md §M8) that `Retriever.retrieve_papers()`'s
        own frozen interface (ARCHITECTURE.md §M7) returns — this is a `contracts/` shape import,
        not a dependency on the `McpServer` module's logic (CONVENTIONS §1's vendor rule doesn't
        apply to shared shapes within `contracts/`, same as `contracts/mcp_server.py` importing
        `Citation`/`GroundedResult` back from `contracts/retriever.py`).

        Returns `(results, coverage)` — see `retrieve()`'s docstring for what `coverage` carries.
        """
        hits = self._hybrid_hits(query, filters, max(k, _RERANK_POOL_SIZE), kind="summary")
        if not hits:
            return [], RetrievalCoverage(candidate_count=0)
        scores = {hit.id: hit.score for hit in hits}
        texts = {hit.id: self._document_store.get_summary(hit.id) for hit in hits}
        candidates = [RerankCandidate(id=hit.id, text=texts[hit.id]) for hit in hits]

        results = []
        for candidate in self._reranker.rerank(query, candidates):
            # See `_paper_id_from_summary_hit_id`'s docstring for why this is the one sanctioned
            # parse of the "{paper_id}:summary" format (CONVENTIONS §12(h) / DATA-CONTRACTS.md
            # "IDs" — every other id-resolving read goes through a DocumentStore getter instead).
            paper_id = _paper_id_from_summary_hit_id(candidate.id)
            record = self._document_store.get(paper_id)
            if record is None:
                raise ContractError(f"DocumentStore has no record for paper_id={paper_id!r}")
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
        # See the matching comment in `retrieve()` -- truncate to `k` only after reranking (T-DOC24).
        return results[:k], RetrievalCoverage(candidate_count=len(hits))

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
