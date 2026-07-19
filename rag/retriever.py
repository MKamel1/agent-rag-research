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

import logging

from contracts.errors import ContractError
from contracts.mcp_server import PaperSearchResult, PaperSummaryView
from contracts.retriever import Citation, GroundedResult, RerankCandidate, RetrievalCoverage
from contracts.vector_index import SearchFilters

logger = logging.getLogger(__name__)

_SUMMARY_ID_SUFFIX = ":summary"

# The reranker can only ever reorder the candidates it's given -- it never fabricates or drops any
# (TeiReranker.rerank()'s own contract: a length-preserving-or-shorter reordering by score).
# Fetching only `k` candidates before reranking means the reranker can't promote anything the
# earlier hybrid/RRF pass ranked below `k` -- a real T-EVAL investigation found every one of 30
# real single-passage misses fit exactly this shape (correct paper always in the top 10, wrong
# specific passage of it ranked above the gold one). Fetch a meaningfully larger pool, then
# truncate to the caller's requested `k` only after reranking has had a chance to reorder it in.
#
# This is a pure retrieval-quality tuning knob, deliberately uncapped by `k` -- a caller-supplied
# `k > _RERANK_POOL_SIZE` is fine and expected here; the pool just grows to `k`. It is NOT where
# the reranker's own vendor batch-size ceiling belongs (T-DOC39 moved that into `TeiReranker`
# itself, `rag/reranker.py`'s `_MAX_BATCH_SIZE` -- the retriever shouldn't hardcode a vendor's
# batch limit, and the reranker defends its own limit regardless of how large a pool this fetches).
#
# 2026-07-18: this is now only the CONSTRUCTOR DEFAULT (`Retriever.__init__`'s `rerank_pool_size`
# param below) -- a caller that doesn't pass one still gets this same 32, unchanged. The live
# value is `Config.rerank_depth`, threaded in by the composition root
# (`app/assembly.py::build_mcp_server`), which -- per the T-DOC39 reasoning just above -- is also
# where it gets clamped to `rag/reranker.py`'s `_MAX_BATCH_SIZE=32` (a pool bigger than that is
# silently truncated by TEI anyway); this module still never imports or hardcodes that vendor
# constant itself.
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

    `rerank_pool_size` is not a collaborator, just a plain tuning knob (defaults to
    `_RERANK_POOL_SIZE`, this module's own docstring on that constant explains where the live
    value -- `Config.rerank_depth` -- gets threaded in from).
    """

    def __init__(self, embedder, vector_store, document_store, reranker,
                 rerank_pool_size: int = _RERANK_POOL_SIZE):
        self._embedder = embedder
        self._vector_store = vector_store
        self._document_store = document_store
        self._reranker = reranker
        self._rerank_pool_size = rerank_pool_size

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
        hits = self._hybrid_hits(query, filters, max(k, self._rerank_pool_size), kind="chunk")
        if not hits:
            return [], RetrievalCoverage(candidate_count=0)
        scores = {hit.id: hit.score for hit in hits}
        # OG-48#2: a vector-store hit whose chunk_id has NO backing DocumentStore row at all (a
        # genuinely stale/orphaned point -- distinct from the parent-paper-deleted case caught
        # below) must be dropped, not crash the whole query. `get_chunk` raises `ContractError` on
        # an unknown id; per-hit try/except mirrors the parent-paper orphan-skip further down.
        chunks = {}
        for hit in hits:
            try:
                chunks[hit.id] = self._document_store.get_chunk(hit.id)
            except ContractError:
                logger.warning(
                    "retrieve(): dropping unresolvable hit chunk_id=%r (no matching Chunk row -- "
                    "orphaned/stale vector point); returning the remaining resolvable hits "
                    "instead of failing the whole query",
                    hit.id,
                )
        candidates = [
            RerankCandidate(id=chunk_id, text=chunk.text) for chunk_id, chunk in chunks.items()
        ]

        results = []
        for candidate in self._reranker.rerank(query, candidates):
            chunk = chunks[candidate.id]
            # T-DOC38: an orphaned/stale chunk (parent paper row deleted without cascading —
            # ~8% of eval queries hit this against the real corpus, `.phase0-data/
            # known-issue-orphaned-chunks.md`) must not zero out the whole query. Drop just this
            # hit and keep going; the ingest side already quarantines bad papers instead of
            # failing a whole run, and the read side should mirror that instead of raising.
            record = self._document_store.get(chunk.paper_id)
            if record is None:
                logger.warning(
                    "retrieve(): dropping unresolvable hit chunk_id=%r (paper_id=%r has no "
                    "DocumentStore record -- orphaned/stale chunk, likely a deleted or "
                    "quarantined paper); returning the remaining resolvable hits instead of "
                    "failing the whole query",
                    candidate.id, chunk.paper_id,
                )
                continue
            # Block.section_path is the AUTHORITATIVE copy (Chunk.section_path is a derived copy
            # taken at chunk-build time, DATA-CONTRACTS.md "Provenance & structure") — the
            # citation reads it from the source block, not the derived copy.
            block = self._document_store.get_block(chunk.anchor.block_id)
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
        hits = self._hybrid_hits(query, filters, max(k, self._rerank_pool_size), kind="summary")
        if not hits:
            return [], RetrievalCoverage(candidate_count=0)
        scores = {hit.id: hit.score for hit in hits}
        # OG-48#2: same per-hit orphan-skip as retrieve() above, for a summary_id with no backing
        # DocumentStore row at all.
        texts = {}
        for hit in hits:
            try:
                texts[hit.id] = self._document_store.get_summary(hit.id)
            except ContractError:
                logger.warning(
                    "retrieve_papers(): dropping unresolvable hit summary_id=%r (no matching "
                    "summary row -- orphaned/stale vector point); returning the remaining "
                    "resolvable hits instead of failing the whole query",
                    hit.id,
                )
        candidates = [
            RerankCandidate(id=summary_id, text=text) for summary_id, text in texts.items()
        ]

        results = []
        for candidate in self._reranker.rerank(query, candidates):
            # See `_paper_id_from_summary_hit_id`'s docstring for why this is the one sanctioned
            # parse of the "{paper_id}:summary" format (CONVENTIONS §12(h) / DATA-CONTRACTS.md
            # "IDs" — every other id-resolving read goes through a DocumentStore getter instead).
            paper_id = _paper_id_from_summary_hit_id(candidate.id)
            record = self._document_store.get(paper_id)
            if record is None:
                # T-DOC38: same skip-and-continue fix as retrieve() above -- see that call site's
                # comment for the full rationale.
                logger.warning(
                    "retrieve_papers(): dropping unresolvable hit summary_id=%r (paper_id=%r has "
                    "no DocumentStore record -- orphaned/stale summary, likely a deleted or "
                    "quarantined paper); returning the remaining resolvable hits instead of "
                    "failing the whole query",
                    candidate.id, paper_id,
                )
                continue
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
