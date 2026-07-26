# M1A-DORMANT (re-enable in M1b): skips until rag/mcp_server.py exists. M1b DoD (CONVENTIONS §11)
# requires this suite active (importorskip resolves) and green.
"""M8 McpServer — tests-first suite (T-E2), against the FROZEN interfaces + fakes.

Written before `rag/mcp_server.py` exists (M1a). Covers the TEST-STRATEGY.md "McpServer" bullet:
each tool returns RECORDS (never bare text); `get_paper` -> `PaperSummaryView`; `search_papers` ->
`PaperSearchResponse` composed from `Retriever.retrieve_papers()`; `semantic_search` ->
`SearchResponse` composed from `Retriever.retrieve()`; both carry a `Coverage` with
`candidates >= returned`; a citation resolves via `get_span`; and — the point of M8 being
"acceptably thin" — the server only CALLS the two `Retriever` methods and never touches
`Embedder`/`VectorStore`/`Reranker` or reimplements the embed/hybrid/RRF/rerank pipeline. That last
one is proven structurally: the server is constructed with only `retriever` + `document_store`, and
a spy `Retriever` records that each tool delegates to exactly one of the two methods.

T-DOC28: `SpyRetriever.retrieve()`/`retrieve_papers()` return `(results, RetrievalCoverage)`,
matching the real `Retriever`'s frozen interface (contracts/retriever.py), with a
`candidate_count` the caller can set independently of `len(results)` —
`test_semantic_search_coverage_invariant`/`test_search_papers_coverage_invariant` use that to
prove `Coverage.candidates` reports the true
pre-truncation pool, not a `len(results)` stand-in (the exact bug `_coverage()` used to have).
"""

import pytest

_mod = pytest.importorskip("rag.mcp_server")

from contracts.mcp_server import (
    PaperSearchResponse,
    PaperSearchResult,
    PaperSummaryView,
    SearchResponse,
)
from contracts.provenance import Anchor, Block
from contracts.retriever import Citation, GroundedResult, RetrievalCoverage

_BBOX = (0.0, 0.0, 100.0, 200.0)

# T-DOC80 imports for `seeded_server` below — a real Retriever + fakes, not the SpyRetriever used
# by every test above. These are only needed there, kept separate so the pre-existing spy-based
# tests above stay untouched.
from datetime import date

from contracts.chunker import Chunk
from contracts.document_store import ChapterSummary, PaperRecord
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from contracts.vector_index import SearchFilters
from rag.fakes import FakeEmbedder, FakeReranker, FakeVectorStore
from rag.retriever import Retriever as RealRetriever


# ---------------------------------------------------------------------------
# A spy Retriever: records which method each tool calls and returns canned results. This is how
# TEST-STRATEGY.md's "McpServer calls exactly one of its two methods per tool and does not touch
# Embedder/VectorStore/Reranker" is proven — the server is given ONLY a retriever + doc store, so it
# structurally cannot reach the pipeline, and the spy confirms the delegation.
# ---------------------------------------------------------------------------
class SpyRetriever:
    def __init__(self, results=(), paper_results=(), candidate_count=None):
        self.retrieve_calls: list[tuple] = []
        self.retrieve_papers_calls: list[tuple] = []
        self._results = list(results)
        self._paper_results = list(paper_results)
        # Defaults to len(results)/len(paper_results) so tests that don't care about Coverage still
        # get a self-consistent candidate_count; a test proving `candidates > returned` passes an
        # explicit, larger `candidate_count` instead (see the two coverage-invariant tests below).
        self._candidate_count = (
            len(self._results) if candidate_count is None else candidate_count
        )
        self._paper_candidate_count = (
            len(self._paper_results) if candidate_count is None else candidate_count
        )

    def retrieve(self, query, filters=None, k=10):
        self.retrieve_calls.append((query, filters, k))
        return list(self._results), RetrievalCoverage(candidate_count=self._candidate_count)

    def retrieve_papers(self, query, filters=None, k=10):
        self.retrieve_papers_calls.append((query, filters, k))
        return (
            list(self._paper_results),
            RetrievalCoverage(candidate_count=self._paper_candidate_count),
        )


class RecordingDocStore:
    """Minimal DocumentStore stand-in (M5, owner D) with a call log — enough for get_paper/get_span,
    plus (T-DOC80) `get_chunk`/`get_block`/`get_summary` so it also satisfies the REAL
    `rag.retriever.Retriever`'s document_store dependency — see `seeded_server` below, which wires
    a real Retriever (not SpyRetriever) through this store to prove `doc_type` filtering end-to-end.
    """

    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self._blocks: dict[str, Block] = {}
        self._records: dict[str, object] = {}
        self._blocks_by_paper: dict[str, list[Block]] = {}
        self._chunks: dict[str, object] = {}
        self._summaries: dict[str, str] = {}

    def get(self, paper_id):
        self.calls.append(("get", paper_id))
        return self._records.get(paper_id)

    def get_span(self, anchor: Anchor) -> str:
        self.calls.append(("get_span", anchor))
        return self._blocks[anchor.block_id].text

    def get_blocks(self, paper_id: str) -> list[Block]:
        self.calls.append(("get_blocks", paper_id))
        return self._blocks_by_paper.get(paper_id, [])

    def get_chunk(self, chunk_id: str):
        self.calls.append(("get_chunk", chunk_id))
        return self._chunks[chunk_id]

    def get_block(self, block_id: str) -> Block:
        self.calls.append(("get_block", block_id))
        return self._blocks[block_id]

    def get_summary(self, summary_id: str) -> str:
        self.calls.append(("get_summary", summary_id))
        return self._summaries[summary_id]

    def method_names(self):
        return [name for name, _ in self.calls]


def _citation(paper_id="2506.01234", section_path="3. Method"):
    return Citation(paper_id=paper_id, title="A Causal Method", authors=["A. Author"],
                    arxiv_url=f"https://arxiv.org/abs/{paper_id}", section_path=section_path)


def _anchor(paper_id="2506.01234", block_id="2506.01234:b0", snippet="The estimator is"):
    return Anchor(paper_id=paper_id, block_id=block_id, page=0, bbox=_BBOX, snippet=snippet,
                  section_path="3. Method")


def _grounded(paper_id="2506.01234", block_id="2506.01234:b0",
              passage_text="The estimator is defined as the sample analogue.", score=0.9):
    return GroundedResult(passage_text=passage_text, anchor=_anchor(paper_id, block_id, passage_text[:16]),
                          paper_id=paper_id, score=score, citation=_citation(paper_id))


def _paper_result(paper_id="2506.01234", score=0.8):
    view = PaperSummaryView(paper_id=paper_id, title="A Causal Method", authors=["A. Author"],
                            summary_text="A short summary.", section_paths=["1. Intro", "3. Method"],
                            citation=_citation(paper_id))
    return PaperSearchResult(view=view, score=score)


def _server(retriever, docstore=None):
    # Only two constructor deps by design — passing an embedder/vector_store/reranker is not even an
    # option, which is the structural proof M8 stays thin (it cannot reimplement M7's pipeline).
    return _mod.McpServer(retriever=retriever, document_store=docstore or RecordingDocStore())


# ===========================================================================
# semantic_search -> SearchResponse (via Retriever.retrieve())
# ===========================================================================
def test_semantic_search_returns_search_response_of_records():
    resp = _server(SpyRetriever(results=[_grounded()])).semantic_search("estimator", filters=None, k=10)
    assert isinstance(resp, SearchResponse)
    assert not isinstance(resp, str)
    assert all(isinstance(r, GroundedResult) for r in resp.results)


def test_semantic_search_coverage_invariant():
    # T-DOC28 regression: candidate_count (32, the real _RERANK_POOL_SIZE) is deliberately larger
    # than returned (2) so this fails loudly if `_coverage()` ever collapses back to reporting
    # `len(results)` for both fields (candidates == returned == 2, `>=` would still trivially pass).
    resp = _server(SpyRetriever(
        results=[_grounded("2506.00001", "2506.00001:b0"),
                 _grounded("2506.00002", "2506.00002:b0")],
        candidate_count=32,
    )).semantic_search("estimator", filters=None, k=10)
    assert resp.coverage.returned == len(resp.results) == 2
    assert resp.coverage.candidates == 32
    assert resp.coverage.candidates > resp.coverage.returned


def test_semantic_search_delegates_only_to_retrieve():
    spy = SpyRetriever(results=[_grounded()])
    _server(spy).semantic_search("estimator", filters=None, k=10)
    assert len(spy.retrieve_calls) == 1
    assert spy.retrieve_papers_calls == []


# ===========================================================================
# search_papers -> PaperSearchResponse (via Retriever.retrieve_papers())
# ===========================================================================
def test_search_papers_returns_paper_search_response_of_records():
    resp = _server(SpyRetriever(paper_results=[_paper_result()])).search_papers(
        "estimator", filters=None, k=10)
    assert isinstance(resp, PaperSearchResponse)
    assert all(isinstance(r, PaperSearchResult) for r in resp.results)


def test_search_papers_coverage_invariant():
    # T-DOC28 regression — see test_semantic_search_coverage_invariant's comment.
    resp = _server(SpyRetriever(
        paper_results=[_paper_result("2506.00001"), _paper_result("2506.00002")],
        candidate_count=32,
    )).search_papers("estimator", filters=None, k=10)
    assert resp.coverage.returned == len(resp.results) == 2
    assert resp.coverage.candidates == 32
    assert resp.coverage.candidates > resp.coverage.returned


def test_search_papers_delegates_only_to_retrieve_papers():
    spy = SpyRetriever(paper_results=[_paper_result()])
    _server(spy).search_papers("estimator", filters=None, k=10)
    assert len(spy.retrieve_papers_calls) == 1
    assert spy.retrieve_calls == []


# ===========================================================================
# get_paper -> PaperSummaryView ; get_span -> source text
# ===========================================================================
def test_get_paper_returns_paper_summary_view():
    docstore = RecordingDocStore()
    from contracts.chunker import Chunk
    from contracts.document_store import PaperRecord
    from contracts.harvester import PaperRef
    from contracts.parser import ParsedDoc
    from datetime import date

    paper_id = "2506.01234"
    blocks = [
        Block(block_id=f"{paper_id}:b0", paper_id=paper_id, text="Intro prose.", type="prose", page=0,
              bbox=_BBOX, section_path="1. Intro", index=0),
        Block(block_id=f"{paper_id}:b1", paper_id=paper_id, text="Method prose.", type="prose", page=0,
              bbox=_BBOX, section_path="3. Method", index=1),
    ]
    for b in blocks:
        docstore._blocks[b.block_id] = b
    docstore._blocks_by_paper[paper_id] = blocks
    ref = PaperRef(paper_id=paper_id, version="v1", title="A Causal Method", abstract="We propose...",
                   authors=["A. Author", "B. Author"], categories=["stat.ME"], published=date(2026, 6, 1),
                   updated=date(2026, 6, 1), pdf_url=f"https://arxiv.org/pdf/{paper_id}v1")
    docstore._records[paper_id] = PaperRecord(
        ref=ref, parsed=ParsedDoc(paper_id=paper_id, markdown="# T", blocks=blocks, figures=[], tables=[],
                                  references=[], parser_id="test-parser-1.x"),
        chunks=[], summary_text="A short summary.", summary_id=f"{paper_id}:summary")

    view = _server(SpyRetriever(), docstore).get_paper(paper_id)
    assert isinstance(view, PaperSummaryView)
    assert view.paper_id == paper_id
    assert view.title == "A Causal Method"
    assert view.authors == ["A. Author", "B. Author"]
    assert view.summary_text == "A short summary."
    assert view.section_paths == ["1. Intro", "3. Method"]  # distinct block section_paths, reading order
    assert isinstance(view.citation, Citation)
    assert view.citation.arxiv_url == f"https://arxiv.org/abs/{paper_id}"
    assert view.citation.doc_type == "paper"


def test_get_paper_local_id_cites_pdf_url_verbatim_with_book_doc_type():
    # T-DOC80: a `local:` paper_id has no arXiv page -- get_paper's Citation must use source_url()
    # (pdf_url verbatim) and carry the record's own doc_type, not the "paper" default.
    docstore = RecordingDocStore()
    from contracts.document_store import PaperRecord
    from contracts.harvester import PaperRef
    from contracts.parser import ParsedDoc
    from datetime import date

    paper_id = "local:ab12cd34ef56"
    docstore._blocks_by_paper[paper_id] = []
    ref = PaperRef(paper_id=paper_id, version="v1", title="Causality", abstract="...",
                   authors=["J. Pearl"], categories=["stat.ME"], published=date(2026, 6, 1),
                   updated=date(2026, 6, 1), pdf_url="causality-pearl.pdf", doc_type="book")
    docstore._records[paper_id] = PaperRecord(
        ref=ref, parsed=ParsedDoc(paper_id=paper_id, markdown="# T", blocks=[], figures=[], tables=[],
                                  references=[], parser_id="test-parser-1.x"),
        chunks=[], summary_text="A book summary.", summary_id=f"{paper_id}:summary")

    view = _server(SpyRetriever(), docstore).get_paper(paper_id)
    assert view.citation.arxiv_url == "causality-pearl.pdf"
    assert view.citation.doc_type == "book"


def test_get_span_returns_verbatim_source_text():
    docstore = RecordingDocStore()
    docstore._blocks["2506.01234:b0"] = Block(
        block_id="2506.01234:b0", paper_id="2506.01234",
        text="The estimator is defined as the sample analogue of the moment condition.", type="prose",
        page=0, bbox=_BBOX, section_path="3. Method", index=0)
    span = _server(SpyRetriever(), docstore).get_span(_anchor(snippet="The estimator is"))
    assert not isinstance(span, dict)
    assert span == "The estimator is defined as the sample analogue of the moment condition."


def test_citation_resolves_via_get_span():
    # A citation from a search tool must be re-groundable: take a semantic_search result's anchor, hand
    # it to the get_span tool, and get back source text the anchor's snippet is a substring of.
    docstore = RecordingDocStore()
    passage = "The estimator is defined as the sample analogue of the moment condition."
    docstore._blocks["2506.01234:b0"] = Block(
        block_id="2506.01234:b0", paper_id="2506.01234", text=passage, type="prose", page=0, bbox=_BBOX,
        section_path="3. Method", index=0)
    server = _server(SpyRetriever(results=[_grounded(passage_text=passage)]), docstore)

    resp = server.semantic_search("estimator", filters=None, k=10)
    result = resp.results[0]
    span = server.get_span(result.anchor)
    assert "get_span" in docstore.method_names()
    assert result.anchor.snippet in span


# ===========================================================================
# default_k (2026-07-18): `Config.top_k` wired via the `default_k` constructor arg -- a caller's
# `k=None` (both tools' new default) resolves to it; an explicit `k` still overrides.
# ===========================================================================
def test_semantic_search_uses_default_k_when_caller_omits_it():
    spy = SpyRetriever(results=[_grounded()])
    server = _mod.McpServer(retriever=spy, document_store=RecordingDocStore(), default_k=7)
    server.semantic_search("estimator", filters=None, k=None)
    assert spy.retrieve_calls == [("estimator", None, 7)]


def test_semantic_search_explicit_k_overrides_default_k():
    spy = SpyRetriever(results=[_grounded()])
    server = _mod.McpServer(retriever=spy, document_store=RecordingDocStore(), default_k=7)
    server.semantic_search("estimator", filters=None, k=3)
    assert spy.retrieve_calls == [("estimator", None, 3)]


def test_search_papers_uses_default_k_when_caller_omits_it():
    spy = SpyRetriever(paper_results=[_paper_result()])
    server = _mod.McpServer(retriever=spy, document_store=RecordingDocStore(), default_k=7)
    server.search_papers("estimator", filters=None, k=None)
    assert spy.retrieve_papers_calls == [("estimator", None, 7)]


def test_search_papers_explicit_k_overrides_default_k():
    spy = SpyRetriever(paper_results=[_paper_result()])
    server = _mod.McpServer(retriever=spy, document_store=RecordingDocStore(), default_k=7)
    server.search_papers("estimator", filters=None, k=3)
    assert spy.retrieve_papers_calls == [("estimator", None, 3)]


def test_default_k_itself_defaults_to_10_when_not_passed():
    # A caller that doesn't pass `default_k` (every other test in this file) must keep today's
    # historical behavior: k=None resolves to 10.
    spy = SpyRetriever(results=[_grounded()])
    server = _mod.McpServer(retriever=spy, document_store=RecordingDocStore())
    server.semantic_search("estimator", filters=None, k=None)
    assert spy.retrieve_calls == [("estimator", None, 10)]


def test_server_needs_only_retriever_and_document_store():
    # Structural proof of "acceptably thin": construction requires nothing from the pipeline layer.
    server = _mod.McpServer(retriever=SpyRetriever(), document_store=RecordingDocStore())
    assert server is not None


# ===========================================================================
# OG-48#5: k is clamped to [_MIN_K, _MAX_K] before it ever reaches the retriever -- a negative k
# (results[:-1] silently drops the last element) or a huge k (thousands of per-hit SQLite queries
# from one unauth caller) must never pass through unclamped.
# ===========================================================================
def test_semantic_search_clamps_negative_k_to_min():
    spy = SpyRetriever(results=[_grounded()])
    server = _mod.McpServer(retriever=spy, document_store=RecordingDocStore())
    server.semantic_search("estimator", filters=None, k=-1)
    assert spy.retrieve_calls == [("estimator", None, _mod._MIN_K)]


def test_semantic_search_clamps_zero_k_to_min():
    spy = SpyRetriever(results=[_grounded()])
    server = _mod.McpServer(retriever=spy, document_store=RecordingDocStore())
    server.semantic_search("estimator", filters=None, k=0)
    assert spy.retrieve_calls == [("estimator", None, _mod._MIN_K)]


def test_semantic_search_clamps_huge_k_to_max():
    spy = SpyRetriever(results=[_grounded()])
    server = _mod.McpServer(retriever=spy, document_store=RecordingDocStore())
    server.semantic_search("estimator", filters=None, k=99999)
    assert spy.retrieve_calls == [("estimator", None, _mod._MAX_K)]


def test_search_papers_clamps_negative_and_huge_k():
    spy = SpyRetriever(paper_results=[_paper_result()])
    server = _mod.McpServer(retriever=spy, document_store=RecordingDocStore())
    server.search_papers("estimator", filters=None, k=-1)
    server.search_papers("estimator", filters=None, k=99999)
    assert spy.retrieve_papers_calls == [
        ("estimator", None, _mod._MIN_K), ("estimator", None, _mod._MAX_K),
    ]


def test_semantic_search_in_range_k_is_unaffected():
    spy = SpyRetriever(results=[_grounded()])
    server = _mod.McpServer(retriever=spy, document_store=RecordingDocStore())
    server.semantic_search("estimator", filters=None, k=42)
    assert spy.retrieve_calls == [("estimator", None, 42)]


# ===========================================================================
# T-DOC80: doc_type passthrough end-to-end, through a REAL `rag.retriever.Retriever` (fakes
# underneath: FakeVectorStore/FakeEmbedder/FakeReranker) — not the SpyRetriever every test above
# uses. Tasks 1-6 already proved doc_type filtering and chapter hits work AT the Retriever layer
# (rag/test_retriever.py); this proves the same thing survives unchanged through the McpServer
# tool wrappers, which is the only thing this task is on the hook for.
# ===========================================================================
def _real_ref(paper_id: str, doc_type: str = "paper") -> PaperRef:
    return PaperRef(
        paper_id=paper_id, version="v1", title=f"Title {paper_id}", abstract="We propose...",
        authors=["A. Author"], categories=["stat.ME"], published=date(2026, 6, 1),
        updated=date(2026, 6, 1), pdf_url=f"https://arxiv.org/pdf/{paper_id}v1", doc_type=doc_type,
    )


def _real_payload(paper_id: str, kind: str, section_path: str, embedder, text: str,
                  doc_type: str = "paper") -> dict:
    # T-DOC80: mirrors rag/orchestrator.py::_upsert_record's real payload_common -- `doc_type` is a
    # real payload key (not inferred from record), so it must be set here for FakeVectorStore's
    # `SearchFilters(doc_type=...)` filtering to have anything to match against.
    return {
        "paper_id": paper_id, "kind": kind, "section_path": section_path, "text": text,
        "categories": ["stat.ME"], "published": "2026-06-01",
        "embedding_version": embedder.info.version, "doc_type": doc_type,
    }


def _seed_real_chunk(store, docstore, embedder, *, chunk_id, paper_id, text, doc_type="paper",
                     section_path="3. Method"):
    block_id = f"{paper_id}:b0"
    anchor = Anchor(paper_id=paper_id, block_id=block_id, page=0, bbox=_BBOX, snippet=text[:40],
                    section_path=section_path)
    docstore._blocks[block_id] = Block(block_id=block_id, paper_id=paper_id, text=text[:40],
                                       type="prose", page=0, bbox=_BBOX,
                                       section_path=section_path, index=0)
    chunk = Chunk(chunk_id=chunk_id, paper_id=paper_id, text=text, anchor=anchor,
                 section_path=section_path, parent_id=block_id)
    docstore._chunks[chunk_id] = chunk
    docstore._records[paper_id] = PaperRecord(
        ref=_real_ref(paper_id, doc_type=doc_type),
        parsed=ParsedDoc(paper_id=paper_id, markdown="# T", blocks=[], figures=[], tables=[],
                         references=[], parser_id="test-parser-1.x"),
        chunks=[chunk], summary_text="s", summary_id=f"{paper_id}:summary")
    store.upsert(chunk_id, embedder.embed([text])[0],
                 _real_payload(paper_id, "chunk", section_path, embedder, text, doc_type=doc_type))


def _seed_real_summary(store, docstore, embedder, *, paper_id, summary_text, doc_type="book",
                       chapter_summaries=()):
    summary_id = f"{paper_id}:summary"
    docstore._summaries[summary_id] = summary_text
    docstore._records[paper_id] = PaperRecord(
        ref=_real_ref(paper_id, doc_type=doc_type),
        parsed=ParsedDoc(paper_id=paper_id, markdown="# T", blocks=[], figures=[], tables=[],
                         references=[], parser_id="test-parser-1.x"),
        chunks=[], summary_text=summary_text, summary_id=summary_id,
        chapter_summaries=list(chapter_summaries))
    store.upsert(summary_id, embedder.embed([summary_text])[0],
                 _real_payload(paper_id, "summary", "Abstract", embedder, summary_text,
                               doc_type=doc_type))
    for cs in chapter_summaries:
        docstore._summaries[cs.summary_id] = cs.text
        store.upsert(cs.summary_id, embedder.embed([cs.text])[0],
                     _real_payload(paper_id, "summary", cs.title, embedder, cs.text,
                                   doc_type=doc_type))


@pytest.fixture
def seeded_server():
    """A real McpServer wired to a REAL `Retriever` (FakeVectorStore/FakeEmbedder/FakeReranker
    underneath, no SpyRetriever) — the point is that `SearchFilters.doc_type` and the `chapter`
    field survive the actual retrieval pipeline, not a canned fake return value. Seeded with:
    one paper chunk, one book chunk (both share the phrase "causal estimator" so an unfiltered
    query would match both — doc_type is the only thing that discriminates them), and a second
    book with a whole-book summary + one chapter summary (for the chapter-hit test).
    """
    store, embedder, reranker = FakeVectorStore(), FakeEmbedder(), FakeReranker()
    docstore = RecordingDocStore()
    _seed_real_chunk(
        store, docstore, embedder, chunk_id="2506.00001:c0", paper_id="2506.00001", doc_type="paper",
        text="the causal estimator uses regression adjustment for measured confounding",
    )
    _seed_real_chunk(
        store, docstore, embedder, chunk_id="local:causality-book:c0", paper_id="local:causality-book",
        doc_type="book",
        text="the causal estimator concept is foundational to structural causal models",
    )
    _seed_real_summary(
        store, docstore, embedder, paper_id="local:stats-book", doc_type="book",
        summary_text="a whole-book summary about probability foundations",
        chapter_summaries=[
            ChapterSummary(
                summary_id="local:stats-book:summary:ch1", title="Confounding",
                text="a chapter on the causal estimator and confounding adjustment",
            ),
        ],
    )
    retriever = RealRetriever(embedder=embedder, vector_store=store, document_store=docstore,
                              reranker=reranker)
    return _mod.McpServer(retriever=retriever, document_store=docstore)


def test_semantic_search_doc_type_filter_passthrough(seeded_server):
    resp = seeded_server.semantic_search(
        "causal estimator", filters=SearchFilters(doc_type="book"), k=10)
    # Non-empty is load-bearing here: an empty result would vacuously satisfy "all results are
    # books" without proving the filter actually discriminated anything.
    assert resp.results
    assert all(r.citation.doc_type == "book" for r in resp.results)
    assert all(r.paper_id == "local:causality-book" for r in resp.results)
    # The paper chunk shares the exact same query phrase -- it must be excluded, not just absent
    # by chance (proves doc_type, not the query, did the filtering).
    assert all(r.paper_id != "2506.00001" for r in resp.results)


def test_search_papers_returns_chapter_hits_with_chapter_field(seeded_server):
    resp = seeded_server.search_papers(
        "causal estimator confounding adjustment chapter", filters=None, k=10)
    chapter_hits = [r for r in resp.results if r.chapter is not None]
    assert chapter_hits, "expected at least one chapter-level routing hit"
    assert any(r.chapter == "Confounding" for r in chapter_hits)
    assert all(r.view.citation.doc_type == "book" for r in chapter_hits)
    assert all(isinstance(r, PaperSearchResult) for r in chapter_hits)


def test_tool_docstrings_carry_routing_guidance():
    assert "books" in _mod.McpServer.semantic_search.__doc__
    assert "doc_type" in _mod.McpServer.semantic_search.__doc__
    assert "books" in _mod.McpServer.search_papers.__doc__
    assert "doc_type" in _mod.McpServer.search_papers.__doc__
