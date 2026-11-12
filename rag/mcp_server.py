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

import re

from contracts.errors import ContractError
from contracts.mcp_server import (
    BlockMatch,
    Coverage,
    PaperSearchResponse,
    PaperSearchResult,
    PaperSummaryView,
    ScanResponse,
    SearchResponse,
)
from contracts.provenance import Anchor, Block
from contracts.retriever import Citation, RetrievalCoverage
from contracts.vector_index import SearchFilters
from rag.method_aliases import build_method_regex, list_methods as _list_method_families, resolve_method
from rag.retriever import source_url

# OG-48#5: an unbounded/negative `k` reaches the retriever unclamped -- `?k=-1` makes `results[:k]`
# drop the LAST element (wrong-but-plausible, no error); a huge `k` fans out to thousands of
# per-hit SQLite point-queries from one caller. Clamped here (the one place both `semantic_search`
# and `search_papers` funnel `k` through) so every McpServer caller -- MCP tool calls AND
# app/dashboard/server.py's `/api/search` (which clamps the same way independently, since it may
# call a caller that isn't even this class, e.g. a test fake) -- gets a sane, bounded pool.
_MIN_K = 1
_MAX_K = 100

# MC-5a (RV-4 F-4.6): `search_papers` used to ship every distinct section path of every hit (standards
# median 68 paths = ~820 tokens per hit, max 1,285 = ~45k). 30 keeps a typical paper whole and cuts the
# long tail; `get_paper` still returns the full list.
_MAX_SECTION_PATHS = 30

# MC-5b: block cap on a `get_section` subtree read; a standards clause chapter is tens of blocks, and
# 100 blocks is a few thousand tokens, which stays readable in one call.
_MAX_SECTION_BLOCKS = 100


def _path_matches(block_path: str, query: str) -> bool:
    """MC-5b: `query` is a clause prefix of some " > " heading segment (so descendants match via
    their ancestor segment; a digit may not follow, so `9.4` skips `9.41`), or -- for a query not
    starting with a digit -- a case-insensitive substring of the whole path."""
    q = query.strip()
    prefix = re.compile(rf"{re.escape(q)}(?![0-9])", re.IGNORECASE)
    if any(prefix.match(segment.strip()) for segment in block_path.split(" > ")):
        return True
    return not q[:1].isdigit() and q.lower() in block_path.lower()


def build_instructions(stats: dict) -> str:
    """MC-2: the server `instructions` string an MCP client shows a cold agent, generated ONLY from
    `McpServer.corpus_stats()` (SQLite; no embedder, no vector store) plus static, corpus-neutral
    tool guidance -- so it is true for any corpus directory. Contract: under ~250 tokens; every
    number in it is a value from `stats` (the static text contains no digits)."""
    kinds = ", ".join(f"{n} {kind}" for kind, n in stats.get("doc_types", {}).items())
    parts = [
        f"Serving {stats.get('serving', 'an unlabelled corpus')}: {stats['papers']} documents "
        f"({kinds}), {stats['blocks']} text blocks, {stats['figures']} figures, "
        f"{stats['tables']} tables; published {stats['published_min']}..{stats['published_max']} "
        "(dates can be year-only placeholders, so treat as approximate).",
        "Tools: semantic_search ranks passages; search_papers ranks whole documents (use it first "
        "when unsure which document matters); scan_corpus/scan_methods exhaustively regex-scan "
        "every block (use for \"which documents mention X\": complete for the pattern, no "
        "ranking, you reject false positives); get_paper then get_section reads a document; "
        "get_span verifies a citation anchor; get_figures; corpus_stats; list_methods.",
        "Limits: search cannot abstain: every query returns its best results, so judge relevance "
        "from the text, and neither an empty nor a full page says the corpus covers or lacks a "
        "topic. filters.paper_id must be a stored id exactly as get_paper accepts it, else the "
        "call errors. author_org matches heuristic tags unless author_org_curated_only is true.",
    ]
    if len(stats.get("doc_types", {})) > 1:
        parts.append("filters.doc_type narrows to one document kind.")
    tags = list(stats.get("top_categories", {}).items())[:5]
    parts.append(
        "filters.categories tags (top, with counts): "
        + ", ".join(f"{t} {n}" for t, n in tags) + "."
        if tags else "No category tags are stored here, so filters.categories matches nothing."
    )
    return "\n".join(parts)


class McpServer:
    """Constructor-injected collaborators only (CONVENTIONS §2): `retriever`, `document_store`.
    Never constructs a vendor client or the retrieval pipeline itself.

    `default_k` is not a collaborator, just the fallback result count `semantic_search`/
    `search_papers` use when a caller doesn't pass its own `k` (2026-07-18: wires the previously-
    dead `Config.top_k` through `app/assembly.py::build_mcp_server` -- a caller-supplied `k` still
    always overrides it).
    """

    def __init__(
        self, retriever, document_store, default_k: int = 10,
        *, corpus_label: str | None = None,
    ):
        self._retriever = retriever
        self._document_store = document_store
        self._default_k = default_k
        # Each corpus is its own server process; without this label nothing in a tool result
        # says which one answered (2026-08-23: a session spent an hour diagnosing exactly that).
        self._corpus_label = corpus_label

    def _serving_suffix(self) -> str:
        return f" [serving {self._corpus_label}]" if self._corpus_label else ""

    @property
    def retriever(self):
        """Read-only access to the injected `Retriever`, for a caller that needs its raw
        `retrieve()`/`retrieve_papers()` interface directly (e.g. `app/retrieval_eval.py`'s
        offline recall/MRR harness) instead of this class's own typed tool wrappers. Construction
        stays exclusively in `app/assembly.py`'s composition root (CONVENTIONS §2) -- this is a
        getter, not a second way to inject one.
        """
        return self._retriever

    def semantic_search(
        self, query: str, filters: SearchFilters | None = None, k: int | None = None
    ) -> SearchResponse:
        """Passage-level search, delegated whole to `Retriever.retrieve()`. Always searches the
        full chunk index across the whole corpus by default — `filters` (`SearchFilters`) can
        narrow by category/date/kind, and, once you already know which paper matters (e.g. from a
        prior `search_papers` call), by `paper_id` to scope to that one document. If the query is
        about a specific paper or a small set of papers you don't yet suspect, call `search_papers`
        first: it identifies which paper(s) are actually relevant from a cheap summary-level match
        before any chunk search runs, so you can decide whether a full-corpus chunk search is even
        needed and can check this tool's results (each carries its own `paper_id`) against that
        expectation instead of trusting an unscoped search alone. This project's agent-as-reasoner
        design (CONTEXT.md, PRD.md §11A) puts that sequencing decision on the calling agent; this
        server never auto-rewrites or narrows a query on its own. Precondition: a `filters.paper_id`
        must be a stored paper id, else `ContractError` (same as `get_paper`) — an unknown id is a
        typo, not "this paper says nothing". Stored ids carry no `arxiv:` prefix. Postcondition:
        on an empty corpus/no hits, `results == []` — empty is a valid answer, not an error.

        `k=None` (a caller that omits it entirely) resolves to `self._default_k` (`Config.top_k`,
        wired via `app/assembly.py::build_mcp_server`); an explicit `k` always overrides it.
        Whichever value results is then clamped to `[_MIN_K, _MAX_K]` (OG-48#5) before it ever
        reaches the retriever.

        `Coverage.returned` has no further ceiling on top of `_MAX_K`: the candidate pool is
        `max(k, rerank_pool_size)` (live value `Config.rerank_depth`, threaded through unclamped
        by `app/assembly.py::build_mcp_server` -- pinned by its rerank-depth-passes-through-
        unclamped tests), and `rag/reranker.py` splits an oversized pool into vendor-size batches
        instead of truncating it, so a `k=60` request can return 60. A short result set therefore
        means the corpus/filters genuinely yielded little -- compare `Coverage.returned` against
        `Coverage.candidates` (the true pre-rerank pool size) to see whether the pool itself was
        small.

        A FULL result set is not evidence of the opposite, either. There is no relevance floor
        anywhere in this pipeline -- every stage (hybrid, RRF, rerank) only ever ranks the
        candidates it has and returns the best of them; none rejects a candidate for scoring low
        in absolute terms. `k` `GroundedResult`s are the `k` best-available passages, not `k`
        endorsements that any of them actually answer the query -- a caller still has to judge
        relevance from the passage text itself. (A floor was proposed and rejected in review; it
        stays rejected until a score-distribution census over known-answerable vs. known-absent
        queries, RI-M7, shows the two distributions actually separate -- an unseparated
        distribution means any threshold is a guess wearing a decision's clothes. Don't add one
        here on a single bad-looking case.)

        The corpus mixes research **papers** (latest methods/evidence) and **books** (foundational
        definitions/concepts). For conceptual/definitional questions, pass
        `filters={"doc_type": "book"}`; for state-of-the-art or empirical results, prefer
        `{"doc_type": "paper"}` (optionally with `published_after`); when cross-checking a paper's
        claim against textbook grounding, run both and cite each. `search_papers` returns individual
        book **chapters** as routing hits (`chapter` field set) — follow up with `semantic_search`
        for anchored passages.

        `filters.author_org` restricts to papers tagged as authored by that org (e.g.
        `{"author_org": "Waymo"}`) — by default this matches ANY tagging method and is NOT
        authoritative on its own. Two tiers exist, and they are not interchangeable:
        - `curated`: the paper id is on the org's own enumerated list of its published research
          (an enumerated fact, exact by construction — see `AuthorOrgMatch`'s docstring,
          `contracts/author_orgs.py`). Set `filters.author_org_curated_only=True` alongside
          `author_org` to demand ONLY this tier — this is the correct way to ask "what does
          Waymo's own research say" and get back only confirmed hits.
        - `email_domain`/`keyword`: a derived heuristic (`rag/author_org_tagger.py`) — measured
          precision 0.706 / recall 0.783 over 1,741 done Waymo-corpus papers against 138 known-
          positive ids (docs/eval-reports/2026-08-07-affiliation-retrieval-first-batch.md; the
          report calls it a lower bound; figures are Waymo-specific). Roughly 3 in 10 hits at
          this tier were wrong there. Fine for open-ended discovery ("candidates worth a closer
          look"), never for a claim that needs to be correct.
        """
        self._require_known_paper_filter("semantic_search", filters)
        results, retrieval_coverage = self._retriever.retrieve(
            query, filters, self._resolve_k(k)
        )
        return SearchResponse(results=results, coverage=self._coverage(results, retrieval_coverage))

    def search_papers(
        self, query: str, filters: SearchFilters | None = None, k: int | None = None
    ) -> PaperSearchResponse:
        """Whole-paper/summary-level search, delegated whole to `Retriever.retrieve_papers()`. This
        is the right first call when a query is scoped to a specific paper or a handful of papers:
        it ranks whole papers by their summary — cheaply, before any chunk-level retrieval or
        reranking runs — so you can confirm which paper(s) actually matter, or find that a
        confirmed match's `get_paper` summary already answers the question without needing a
        broader `semantic_search` chunk search at all. Precondition: a `filters.paper_id` must be
        a stored paper id, else `ContractError` (see `semantic_search`). Postcondition: on no
        hits, `results == []`.

        `k=None` resolves to `self._default_k`, same as `semantic_search` — see its docstring
        for the `[_MIN_K, _MAX_K]` clamp (OG-48#5) and why there is no further cap on how many
        results come back.

        Same absence-honesty caveat as `semantic_search`, and it applies here too: a full `k`-sized
        result set is `k` best-scoring papers, not `k` papers confirmed to address the query — see
        its docstring for why no relevance floor exists and why one stays rejected pending RI-M7.

        The corpus mixes research **papers** (latest methods/evidence) and **books** (foundational
        definitions/concepts). For conceptual/definitional questions, pass
        `filters={"doc_type": "book"}`; for state-of-the-art or empirical results, prefer
        `{"doc_type": "paper"}` (optionally with `published_after`); when cross-checking a paper's
        claim against textbook grounding, run both and cite each. `search_papers` returns individual
        book **chapters** as routing hits (`chapter` field set) — follow up with `semantic_search`
        for anchored passages.

        `filters.author_org` restricts to papers tagged as authored by that org — see
        `semantic_search`'s docstring for the full tier breakdown: `author_org_curated_only=True`
        demands the exact, enumerated `curated` tier; without it, a hit may be the derived
        `email_domain`/`keyword` heuristic (precision 0.706 / recall 0.783, measured on the Waymo
        corpus), not confirmed
        authorship.

        Each hit's `view.section_paths` is capped at `_MAX_SECTION_PATHS`; a longer list ends with
        a "[truncated: first N of M ...]" marker string (not a real path). `get_paper` has all.
        """
        self._require_known_paper_filter("search_papers", filters)
        results, retrieval_coverage = self._retriever.retrieve_papers(
            query, filters, self._resolve_k(k)
        )
        return PaperSearchResponse(
            results=[self._cap_section_paths(r) for r in results],
            coverage=self._coverage(results, retrieval_coverage),
        )

    def scan_corpus(
        self, pattern: str, paper_id: str | None = None, author_org: str | None = None,
        max_matches_per_paper: int = 3, context: int = 200,
    ) -> ScanResponse:
        """Exhaustive regex scan over every stored block. **Use this, not `semantic_search`, when
        the question is "WHICH PAPERS do/contain X".**

        The two tools answer different questions and are not substitutes:

        - `semantic_search` ranks passages by relevance and returns the best `k`. It cannot promise
          it surfaced every qualifying paper, because ranking is per-passage: a paper that states a
          method once, plainly, ranks below a paper that discusses it at length, and one verbose
          paper can occupy most of `k`. Measured on the Waymo corpus (docs/eval-reports/
          2026-08-19-retrieval-recall-precision.md), an enumeration question answered by
          retrieval alone found 3 of 4 qualifying papers.
        - `scan_corpus` examines every block, so recall is 1.0 **for the pattern given**. It does no
          ranking and no semantic matching whatsoever — a paper that describes a technique without
          ever naming it will not match, so the pattern's vocabulary is the real limit. Widen it
          (`bootstrap|resampl|jackknife`) rather than relying on one spelling.

        The tradeoff is deliberate: this returns lexical false positives (a "bootstrap particle
        filter" matches a "bootstrap" pattern while being an unrelated method) and leaves the caller
        to reject them. That is the right way round — precision can be repaired by reading the
        matches, recall cannot be repaired at all once a paper is missing.

        `section_path` on every match is what makes rejection cheap: a hit under "Related Work" is
        a citation, one under "Methods" is a use. Treat `""` as "judge from the text" rather than
        as evidence of anything — parsing does not always recover headings.

        `paper_id` narrows to one document, which is how to resolve a definition or an abbreviation.
        Retrieval is structurally bad at that (a defining aside is topically dominated by the
        surrounding prose and ranks below it), and this is a full-text lookup instead.

        `author_org` restricts to papers with a CURATED authorship tag for that org — the enumerated
        tier only (`AuthorOrgMatch.method == "curated"`), never the email/keyword heuristic, so
        "which of Waymo's own papers" means exactly that.
        """
        rows, scanned, matched, truncated = self._document_store.scan_blocks(
            pattern, paper_id=paper_id, curated_org=author_org,
            context=context, max_per_paper=max_matches_per_paper,
        )
        return ScanResponse(
            matches=[
                BlockMatch(paper_id=r_paper_id, block_id=block_id, page=page,
                           section_path=section_path, title=title, snippet=snippet)
                for r_paper_id, title, block_id, page, section_path, snippet in rows
            ],
            papers_scanned=scanned, papers_matched=matched, truncated=truncated,
        )

    def scan_methods(
        self, method: str, paper_id: str | None = None, author_org: str | None = None,
        max_matches_per_paper: int = 3, context: int = 200,
    ) -> ScanResponse:
        """`scan_corpus` with the synonym layer built in: "WHICH PAPERS use method X" where X may
        be known by several names.

        `method` is resolved against a curated alias map (`rag/method_aliases.py`): the family's
        surface forms — "RRF"/"reciprocal rank fusion"/"rank fusion", "NIEON"/"non-impaired
        eyes-on", "GIDAS"/"German in-depth accident study", stems like `\brerank` (reranking/
        reranked) and `\bmais` (MAIS3+/MAIS2+F) — are compiled into ONE alternation and scanned
        exactly like `scan_corpus` (`DocumentStore.scan_blocks`): every block examined, recall 1.0
        for the alias group, no ranking, lexical false positives you reject by reading. An unknown
        method scans its literal name rather than erroring — the map may not have learned it yet;
        an input ambiguous between families (e.g. "benchmark") raises rather than guessing.

        Scope honesty: this is an explicitly lexical ENUMERATION tool, `scan_corpus`'s mold — it
        is not query rewriting. `semantic_search`/`search_papers` remain untouched and
        un-rewritten (PRD §11A): a paper that uses a method without any of the family's surface
        forms will not match here, and semantic retrieval remains the tool for that case. To add
        or correct a family, edit `rag/method_aliases.py` (a normal rag/ change).

        `paper_id`/`author_org`/`max_matches_per_paper`/`context` mean exactly what they mean in
        `scan_corpus`; `author_org` is the CURATED tier only.
        """
        canonical, patterns = resolve_method(method)
        rows, scanned, matched, truncated = self._document_store.scan_blocks(
            build_method_regex(patterns), paper_id=paper_id, curated_org=author_org,
            context=context, max_per_paper=max_matches_per_paper,
        )
        return ScanResponse(
            matches=[
                BlockMatch(paper_id=p_paper_id, block_id=block_id, page=page,
                           section_path=section_path, title=title, snippet=snippet)
                for p_paper_id, title, block_id, page, section_path, snippet in rows
            ],
            papers_scanned=scanned, papers_matched=matched, truncated=truncated,
        )

    def list_methods(self) -> list[str]:
        """Canonical names of every method family `scan_methods` knows, sorted. Metadata for
        callers (what can be asked about), not evidence — the enumeration itself is
        `scan_methods`."""
        return _list_method_families()

    def get_figures(self, paper_id: str, kind: str = "all") -> list[dict]:
        """The figures and/or tables stored for one paper -- the structured artifact surface that
        pairs with `get_section` for reading a paper and with `scan_methods` for finding one.

        Returns plain dicts ordered by page (keys documented in
        `DocumentStore.get_artifacts`): figures carry `{kind, id, page, caption, image_path,
        bbox}`; tables carry `{kind, id, page, caption, markdown, bbox}`. `kind` selects
        `"figure"`, `"table"`, or `"all"` (default). A typed envelope for these is a deferred
        contracts/ (T-F7) change; until then the dicts are the interface, documented here and in
        the store. Raises `ContractError` for an unknown `paper_id` -- a typo should error, not
        silently return an empty list. `caption` can be empty (parsing does not always recover
        one); `markdown` on tables is the extracted table text, which is what makes a table's
        CONTENT answerable without vision."""
        if self._document_store.get(paper_id) is None:
            raise ContractError(f"get_figures: unknown paper_id {paper_id!r}{self._serving_suffix()}")
        return self._document_store.get_artifacts(paper_id, kind)

    def get_section(self, paper_id: str, section_path: str) -> list[Block] | dict:
        """One section of a paper, as its blocks in reading order -- linear reading over MCP.

        `get_paper` lists a paper's `section_paths`; this fetches the blocks under one of them
        (exact match on `Block.section_path`, returned as a plain list, uncapped -- unchanged).
        MC-5b: when NO block has that exact path, `section_path` is tried as a subtree query: a
        clause prefix (`9.4` matches the heading segment "9.4 Requirements..." and everything under
        it, not `9.41`) or a case-insensitive substring of the full path. That returns a dict
        `{blocks, truncated, total_blocks, matched_section_paths}` in document order, `blocks`
        capped at `_MAX_SECTION_BLOCKS`. Returns `[]` when nothing matches either way (parsing does
        not always recover headings -- see `scan_corpus`'s note on `""` section paths); raises
        `ContractError` for an unknown `paper_id`. Blocks are the same frozen provenance type
        `get_span` resolves, so any block here can be cited."""
        if self._document_store.get(paper_id) is None:
            raise ContractError(f"get_section: unknown paper_id {paper_id!r}{self._serving_suffix()}")
        blocks = self._document_store.get_blocks(paper_id)
        exact = [b for b in blocks if b.section_path == section_path]
        if exact or not section_path:
            return exact
        subtree = [b for b in blocks if _path_matches(b.section_path, section_path)]
        if not subtree:
            return []
        return {
            "blocks": subtree[:_MAX_SECTION_BLOCKS],
            "truncated": len(subtree) > _MAX_SECTION_BLOCKS,
            "total_blocks": len(subtree),
            "matched_section_paths": list(dict.fromkeys(b.section_path for b in subtree)),
        }

    def corpus_stats(self) -> dict:
        """Corpus-level aggregates for query calibration: paper/block/chunk/figure/table counts,
        published-date range, doc_type histogram, top categories. Use before searching -- knowing
        which corpus this is and how big changes how a caller scopes everything else. Plain dict;
        keys documented in
        `DocumentStore.corpus_stats`. When the composition root supplied a `corpus_label`, a
        `serving` key is merged in identifying the answering process."""
        stats = self._document_store.corpus_stats()
        if self._corpus_label:
            stats = {**stats, "serving": self._corpus_label}
        return stats

    def get_paper(self, paper_id: str) -> PaperSummaryView:
        """Precondition: `paper_id` is a stored paper; else `ContractError`. Postcondition:
        `section_paths` are the distinct `Block.section_path` values, in reading order.
        """
        record = self._document_store.get(paper_id)
        if record is None:
            raise ContractError(f"get_paper: unknown paper_id {paper_id!r}{self._serving_suffix()}")
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
                arxiv_url=source_url(paper_id, record.ref.pdf_url),
                section_path="",  # whole-paper citation — no single section it's "at"
                doc_type=record.ref.doc_type,
            ),
        )

    def get_span(self, anchor: Anchor) -> str:
        """Precondition: `anchor` resolves to a stored block; else `ContractError` (a dangling
        anchor is a grounding bug, not a normal "not found").
        """
        return self._document_store.get_span(anchor)

    def _require_known_paper_filter(self, tool: str, filters: SearchFilters | None) -> None:
        """MC-1: a `filters.paper_id` that is not in the corpus is a typo, not an empty answer --
        raise exactly what `get_paper` raises (RV-4 F-4.2: an `arxiv:`-prefixed id returned empty
        and read as "this standard does not discuss X"). Other filters are untouched."""
        paper_id = filters.paper_id if filters is not None else None
        if paper_id is None or self._document_store.get(paper_id) is not None:
            return
        hint = ""
        if paper_id.startswith("arxiv:"):
            hint = f" (stored ids have no 'arxiv:' prefix; try {paper_id.removeprefix('arxiv:')!r})"
        raise ContractError(f"{tool}: unknown paper_id {paper_id!r}{hint}{self._serving_suffix()}")

    @staticmethod
    def _cap_section_paths(result: PaperSearchResult) -> PaperSearchResult:
        """MC-5a: keep the first `_MAX_SECTION_PATHS` paths and end the list with a marker string
        saying how many exist (`PaperSummaryView` is a frozen contract with no `truncated` field, so
        the marker rides in the list itself; it is not a real section path)."""
        paths = result.view.section_paths
        if len(paths) <= _MAX_SECTION_PATHS:
            return result
        marker = (f"[truncated: first {_MAX_SECTION_PATHS} of {len(paths)} section paths; "
                  "get_paper returns all]")
        view = result.view.model_copy(
            update={"section_paths": [*paths[:_MAX_SECTION_PATHS], marker]})
        return result.model_copy(update={"view": view})

    def _resolve_k(self, k: int | None) -> int:
        """`k=None` -> `self._default_k`; either way, clamp to `[_MIN_K, _MAX_K]` (OG-48#5) before
        it ever reaches the retriever."""
        resolved = self._default_k if k is None else k
        return max(_MIN_K, min(resolved, _MAX_K))

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
