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
from contracts.retriever import Citation, GroundedResult

_BBOX = (0.0, 0.0, 100.0, 200.0)


# ---------------------------------------------------------------------------
# A spy Retriever: records which method each tool calls and returns canned results. This is how
# TEST-STRATEGY.md's "McpServer calls exactly one of its two methods per tool and does not touch
# Embedder/VectorStore/Reranker" is proven — the server is given ONLY a retriever + doc store, so it
# structurally cannot reach the pipeline, and the spy confirms the delegation.
# ---------------------------------------------------------------------------
class SpyRetriever:
    def __init__(self, results=(), paper_results=()):
        self.retrieve_calls: list[tuple] = []
        self.retrieve_papers_calls: list[tuple] = []
        self._results = list(results)
        self._paper_results = list(paper_results)

    def retrieve(self, query, filters=None, k=10):
        self.retrieve_calls.append((query, filters, k))
        return list(self._results)

    def retrieve_papers(self, query, filters=None, k=10):
        self.retrieve_papers_calls.append((query, filters, k))
        return list(self._paper_results)


class RecordingDocStore:
    """Minimal DocumentStore stand-in (M5, owner D) with a call log — enough for get_paper/get_span."""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self._blocks: dict[str, Block] = {}
        self._records: dict[str, object] = {}
        self._blocks_by_paper: dict[str, list[Block]] = {}

    def get(self, paper_id):
        self.calls.append(("get", paper_id))
        return self._records.get(paper_id)

    def get_span(self, anchor: Anchor) -> str:
        self.calls.append(("get_span", anchor))
        return self._blocks[anchor.block_id].text

    def get_blocks(self, paper_id: str) -> list[Block]:
        self.calls.append(("get_blocks", paper_id))
        return self._blocks_by_paper.get(paper_id, [])

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
    resp = _server(SpyRetriever(results=[_grounded("2506.00001", "2506.00001:b0"),
                                         _grounded("2506.00002", "2506.00002:b0")])).semantic_search(
        "estimator", filters=None, k=10)
    assert resp.coverage.returned == len(resp.results)
    assert resp.coverage.candidates >= resp.coverage.returned


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
    resp = _server(SpyRetriever(paper_results=[_paper_result("2506.00001"),
                                               _paper_result("2506.00002")])).search_papers(
        "estimator", filters=None, k=10)
    assert resp.coverage.returned == len(resp.results)
    assert resp.coverage.candidates >= resp.coverage.returned


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


def test_server_needs_only_retriever_and_document_store():
    # Structural proof of "acceptably thin": construction requires nothing from the pipeline layer.
    server = _mod.McpServer(retriever=SpyRetriever(), document_store=RecordingDocStore())
    assert server is not None
