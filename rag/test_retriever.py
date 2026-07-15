# M1A-DORMANT (re-enable in M1b): skips until rag/retriever.py exists. M1b DoD (CONVENTIONS §11)
# requires this suite active (importorskip resolves) and green.
"""M7 Retriever — tests-first suite (T-E1), against the FROZEN interfaces + fakes.

Written before `rag/retriever.py` exists (M1a). Covers the TEST-STRATEGY.md "Retriever" bullet:
both methods share the embed-query -> hybrid -> RRF -> rerank -> resolve pipeline; `retrieve()` is
passage-level (kind="chunk", resolved via `get_chunk`/`get_block` into `GroundedResult`),
`retrieve_papers()` is whole-paper (kind="summary", resolved via `get_summary`/`get` into
`PaperSearchResult`). Grounding is asserted with a call-recording spy on the DocumentStore (not by
trusting output shape), and the rerank stage has its OWN wiring assertion for BOTH methods.

`GroundedResult.score` / `PaperSearchResult.score` source (the T-E1 decision the docs deliberately
leave open): the **pre-rerank RRF fused score** (`Hit.score`). Rationale — the corrected Reranker
seam (`rerank(query, candidates: list[RerankCandidate]) -> list[RerankCandidate]`) is a *pure
reorder*: `RerankCandidate` carries no score, so the reranker surfaces no cross-encoder score to
propagate. The only numeric score in the pipeline is the RRF score `VectorIndex.hybrid_search`
returns on each `Hit`. Every score assertion below reads that value back from the same fake store.
"""

import pytest

_mod = pytest.importorskip("rag.retriever")

from contracts.chunker import Chunk
from contracts.document_store import PaperRecord
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor, Block
from contracts.retriever import Citation, GroundedResult
from contracts.vector_index import SearchFilters
from rag.fakes import FakeEmbedder, FakeReranker, FakeVectorStore

from datetime import date

_BBOX = (0.0, 0.0, 100.0, 200.0)


# ---------------------------------------------------------------------------
# A call-recording spy standing in for the real DocumentStore (M5, owner D).
#
# There is no FakeDocumentStore in rag/fakes, and M7 must be testable without M5's real adapter, so
# this is a minimal in-memory stand-in that records every resolver call into `.calls`. The recording
# is the point: TEST-STRATEGY.md requires proving `retrieve()` actually invoked `get_chunk`/`get_block`
# (and `retrieve_papers()` `get_summary`/`get`) rather than hand-parsing id strings (CONVENTIONS §0.8) —
# a shortcut that would still produce a plausible-looking passing result if we only checked output shape.
# ---------------------------------------------------------------------------
class RecordingDocStore:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self._chunks: dict[str, Chunk] = {}
        self._blocks: dict[str, Block] = {}
        self._summaries: dict[str, str] = {}
        self._records: dict[str, PaperRecord] = {}

    def get_chunk(self, chunk_id: str) -> Chunk:
        self.calls.append(("get_chunk", chunk_id))
        return self._chunks[chunk_id]

    def get_block(self, block_id: str) -> Block:
        self.calls.append(("get_block", block_id))
        return self._blocks[block_id]

    def get_summary(self, summary_id: str) -> str:
        self.calls.append(("get_summary", summary_id))
        return self._summaries[summary_id]

    def get(self, paper_id: str) -> PaperRecord | None:
        self.calls.append(("get", paper_id))
        return self._records.get(paper_id)

    def get_span(self, anchor: Anchor) -> str:
        self.calls.append(("get_span", anchor))
        return self._blocks[anchor.block_id].text

    def get_blocks(self, paper_id: str) -> list[Block]:
        self.calls.append(("get_blocks", paper_id))
        return [b for b in self._blocks.values() if b.paper_id == paper_id]

    def method_names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def args_for(self, method: str) -> list[object]:
        return [arg for name, arg in self.calls if name == method]


def _make_ref(paper_id: str, categories=("cs.LG",)) -> PaperRef:
    return PaperRef(
        paper_id=paper_id,
        version="v1",
        title=f"Paper {paper_id}",
        abstract="We propose...",
        authors=["A. Author", "B. Author"],
        categories=list(categories),
        published=date(2026, 6, 1),
        updated=date(2026, 6, 1),
        pdf_url=f"https://arxiv.org/pdf/{paper_id}v1",
    )


def _payload(paper_id, kind, section_path, categories, embedder, text):
    return {
        "paper_id": paper_id,
        "kind": kind,
        "section_path": section_path,
        "text": text,
        "categories": list(categories),
        "published": "2026-06-01",
        "embedding_version": embedder.info.version,
    }


def _seed_chunk(store, docstore, embedder, *, chunk_id, paper_id, block_id, text,
                section_path="3. Method", categories=("cs.LG",), extra_blocks=()):
    """Seed one chunk into both the vector store and the doc store. `extra_blocks` lets a chunk span
    multiple blocks (the multi-block anchoring case) — the chunk's `text` is the caller's business;
    the anchor always points at `block_id` (the first block)."""
    anchor = Anchor(paper_id=paper_id, block_id=block_id, page=0, bbox=_BBOX,
                    snippet=text[:40], section_path=section_path)
    docstore._blocks[block_id] = Block(block_id=block_id, paper_id=paper_id, text=text[:40],
                                       type="prose", page=0, bbox=_BBOX,
                                       section_path=section_path, index=0)
    for i, (b_id, b_text) in enumerate(extra_blocks, start=1):
        docstore._blocks[b_id] = Block(block_id=b_id, paper_id=paper_id, text=b_text, type="equation",
                                       page=0, bbox=_BBOX, section_path=section_path, index=i)
    chunk = Chunk(chunk_id=chunk_id, paper_id=paper_id, text=text, anchor=anchor,
                  section_path=section_path, parent_id=block_id)
    docstore._chunks[chunk_id] = chunk
    docstore._records[paper_id] = PaperRecord(
        ref=_make_ref(paper_id, categories),
        parsed=ParsedDoc(paper_id=paper_id, markdown="# T", blocks=[], figures=[], tables=[],
                         references=[], parser_id="test-parser-1.x"),
        chunks=[chunk], summary_text="s", summary_id=f"{paper_id}:summary")
    store.upsert(chunk_id, embedder.embed([text])[0],
                 _payload(paper_id, "chunk", section_path, categories, embedder, text))
    return chunk


def _seed_summary(store, docstore, embedder, *, paper_id, summary_id, summary_text,
                  section_path="Abstract", categories=("cs.LG",)):
    docstore._summaries[summary_id] = summary_text
    docstore._records[paper_id] = PaperRecord(
        ref=_make_ref(paper_id, categories),
        parsed=ParsedDoc(paper_id=paper_id, markdown="# T", blocks=[], figures=[], tables=[],
                         references=[], parser_id="test-parser-1.x"),
        chunks=[], summary_text=summary_text, summary_id=summary_id)
    store.upsert(summary_id, embedder.embed([summary_text])[0],
                 _payload(paper_id, "summary", section_path, categories, embedder, summary_text))


def _make_retriever(store, docstore, reranker, embedder=None):
    embedder = embedder or FakeEmbedder()
    return _mod.Retriever(embedder=embedder, vector_store=store,
                          document_store=docstore, reranker=reranker)


def _seed_three_chunks(store, docstore, embedder):
    """Three chunks, one per paper, distinct texts/section_paths -> a non-trivial RRF order whose
    reversal genuinely differs from the original."""
    _seed_chunk(store, docstore, embedder, chunk_id="2506.00001:c0", paper_id="2506.00001",
                block_id="2506.00001:b0", text="difference-in-differences estimator staggered adoption",
                section_path="3. Method > 3.1 DiD")
    _seed_chunk(store, docstore, embedder, chunk_id="2506.00002:c0", paper_id="2506.00002",
                block_id="2506.00002:b0", text="instrumental variables two stage least squares",
                section_path="4. Identification")
    _seed_chunk(store, docstore, embedder, chunk_id="2506.00003:c0", paper_id="2506.00003",
                block_id="2506.00003:b0", text="double machine learning orthogonal moment",
                section_path="5. Estimator")


# --- pre-rerank RRF order helper: read straight from the same fake store the Retriever uses --------
def _rrf_hits(store, embedder, query, kind, k=100, categories=None):
    filters = SearchFilters(kind=kind, categories=categories)
    return store.hybrid_search(embedder.embed([query])[0], query, filters, k)


# ===========================================================================
# retrieve() — passage level
# ===========================================================================
def test_retrieve_empty_corpus_returns_empty_list():
    r = _make_retriever(FakeVectorStore(), RecordingDocStore(), FakeReranker())
    assert r.retrieve("any query", filters=None, k=10) == []


def test_retrieve_resolves_via_get_chunk_and_get_block_spy():
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_three_chunks(store, docstore, embedder)
    query = "causal estimator"
    r = _make_retriever(store, docstore, FakeReranker(), embedder)

    r.retrieve(query, filters=None, k=10)

    # Grounding proven by the spy, not by output shape: both resolvers were actually invoked...
    assert "get_chunk" in docstore.method_names()
    assert "get_block" in docstore.method_names()
    # ...and get_chunk was called for exactly the hybrid_search hit ids (no hand-parsed ids).
    expected_ids = {h.id for h in _rrf_hits(store, embedder, query, "chunk")}
    assert set(docstore.args_for("get_chunk")) == expected_ids


def test_retrieve_passage_text_equals_resolved_chunk_text():
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    chunk = _seed_chunk(store, docstore, embedder, chunk_id="2506.00001:c0", paper_id="2506.00001",
                        block_id="2506.00001:b0", text="the estimator is defined as the sample analogue")
    [result] = r_results = _make_retriever(store, docstore, FakeReranker(), embedder).retrieve(
        "estimator", filters=None, k=10)
    assert result.passage_text == chunk.text


def test_retrieve_multiblock_chunk_passage_covers_all_blocks():
    # Regression for the "get_span(anchor) instead of Chunk.text" bug: a 2-block chunk's passage_text
    # must be the whole Chunk.text (both blocks), NOT get_span(anchor) which resolves only block 1.
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    block1_text = "We define the estimator in prose."
    block2_text = r"\hat{\tau} = \frac{1}{n}\sum_i (Y_i(1) - Y_i(0))"
    chunk_text = block1_text + "\n" + block2_text
    chunk = _seed_chunk(store, docstore, embedder, chunk_id="2506.00009:c0", paper_id="2506.00009",
                        block_id="2506.00009:b0", text=chunk_text,
                        extra_blocks=[("2506.00009:b1", block2_text)])
    [result] = _make_retriever(store, docstore, FakeReranker(), embedder).retrieve(
        "estimator", filters=None, k=10)

    assert result.passage_text == chunk.text
    assert block2_text in result.passage_text          # the 2nd block's content is present...
    first_block_span = docstore._blocks["2506.00009:b0"].text
    assert result.passage_text != first_block_span     # ...so it is NOT a get_span(anchor) fetch.


def test_retrieve_evidence_tier_is_pinned_A():
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_three_chunks(store, docstore, embedder)
    results = _make_retriever(store, docstore, FakeReranker(), embedder).retrieve(
        "estimator", filters=None, k=10)
    assert results
    assert all(res.evidence_tier == "A" for res in results)


def test_retrieve_results_are_grounded():
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_three_chunks(store, docstore, embedder)
    results = _make_retriever(store, docstore, FakeReranker(), embedder).retrieve(
        "estimator", filters=None, k=10)
    assert results
    for res in results:
        assert isinstance(res.citation, Citation)
        # every result carries a resolvable anchor (re-grounding invariant): the anchor's snippet must
        # appear in what get_span returns for that same anchor.
        span = docstore.get_span(res.anchor)
        assert res.anchor.snippet in span


def test_retrieve_score_is_prerank_rrf_score():
    # T-E1 decision: GroundedResult.score == the pre-rerank RRF Hit.score (see module docstring).
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_three_chunks(store, docstore, embedder)
    query = "estimator"
    rrf_score_by_block = {}
    for h in _rrf_hits(store, embedder, query, "chunk"):
        rrf_score_by_block[docstore._chunks[h.id].anchor.block_id] = h.score

    results = _make_retriever(store, docstore, FakeReranker(), embedder).retrieve(
        query, filters=None, k=10)
    assert results
    for res in results:
        assert res.score == rrf_score_by_block[res.anchor.block_id]


def test_retrieve_rerank_wiring_is_its_own_assertion():
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_three_chunks(store, docstore, embedder)
    query = "estimator"
    reranker = FakeReranker()
    results = _make_retriever(store, docstore, reranker, embedder).retrieve(query, filters=None, k=10)

    pre_rerank_ids = [h.id for h in _rrf_hits(store, embedder, query, "chunk")]
    assert len(pre_rerank_ids) >= 2  # otherwise "differs from" is vacuous

    # (a) rerank() was actually called, with the pre-rerank candidate ids in RRF order.
    assert reranker.calls
    assert reranker.calls[-1] == (query, pre_rerank_ids)

    # (b) final order matches FakeReranker's reversal AND differs from the pre-rerank RRF order.
    final_blocks = [res.anchor.block_id for res in results]
    expected_final_blocks = [docstore._chunks[cid].anchor.block_id for cid in reversed(pre_rerank_ids)]
    prerank_blocks = [docstore._chunks[cid].anchor.block_id for cid in pre_rerank_ids]
    assert final_blocks == expected_final_blocks
    assert final_blocks != prerank_blocks


def test_retrieve_restricts_to_chunk_kind():
    # A summary sharing the query terms must NOT surface via retrieve() (kind is forced to "chunk").
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_chunk(store, docstore, embedder, chunk_id="2506.00001:c0", paper_id="2506.00001",
                block_id="2506.00001:b0", text="double machine learning estimator")
    _seed_summary(store, docstore, embedder, paper_id="2506.00002", summary_id="2506.00002:summary",
                  summary_text="double machine learning estimator")
    results = _make_retriever(store, docstore, FakeReranker(), embedder).retrieve(
        "double machine learning", filters=None, k=10)
    assert [res.paper_id for res in results] == ["2506.00001"]


def test_retrieve_pool_size_lets_reranker_promote_a_passage_ranked_below_k():
    # T-DOC24 regression: before this fix, retrieve(k=10) fetched only the top 10 pre-rerank RRF
    # candidates, so a candidate ranked 11th or lower was never even shown to the reranker -- no
    # matter how the reranker would have scored it, it could not appear in the results. Seed a
    # pool of 20 candidates, find whichever one lands below the old k=10 cutoff in the real
    # pre-rerank RRF order, and confirm it now surfaces in the final results: the fix fetches
    # _RERANK_POOL_SIZE candidates (> k) before reranking, and FakeReranker's full-pool reversal
    # can promote a bottom-half candidate into the top-k after reranking, exactly what the fix
    # makes possible.
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    query = "double machine learning orthogonal moment estimator"
    for i in range(20):
        _seed_chunk(store, docstore, embedder, chunk_id=f"2506.{i:05d}:c0",
                    paper_id=f"2506.{i:05d}", block_id=f"2506.{i:05d}:b0",
                    text=f"unrelated filler content about topic number {i}",
                    section_path=f"{i}. Section")

    pre_rerank_ids = [h.id for h in _rrf_hits(store, embedder, query, "chunk", k=100)]
    assert len(pre_rerank_ids) == 20
    # Whichever chunk the real (arbitrary, hash-based) fake embedding ranks last pre-rerank: at
    # position 19 of 20, it's excluded from an old-style k=10 fetch by construction, and after a
    # full 20-item reversal lands at position 0 -- comfortably inside the new top-10.
    target_id = pre_rerank_ids[-1]
    target_block_id = docstore._chunks[target_id].anchor.block_id

    results = _make_retriever(store, docstore, FakeReranker(), embedder).retrieve(
        query, filters=None, k=10)

    assert len(results) == 10
    result_block_ids = [res.anchor.block_id for res in results]
    assert target_block_id in result_block_ids, (
        "a candidate ranked below the old k=10 cutoff must be reachable once reranking sees the "
        "full _RERANK_POOL_SIZE pool, not just the caller's k"
    )


def test_retrieve_filters_is_searchfilters_not_dict():
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_chunk(store, docstore, embedder, chunk_id="2506.00001:c0", paper_id="2506.00001",
                block_id="2506.00001:b0", text="synthetic control estimator", categories=("stat.ME",))
    _seed_chunk(store, docstore, embedder, chunk_id="2506.00002:c0", paper_id="2506.00002",
                block_id="2506.00002:b0", text="synthetic control estimator", categories=("cs.CL",))
    results = _make_retriever(store, docstore, FakeReranker(), embedder).retrieve(
        "synthetic control", filters=SearchFilters(categories=["stat.ME"]), k=10)
    assert [res.paper_id for res in results] == ["2506.00001"]


# ===========================================================================
# retrieve_papers() — whole-paper / summary level
# ===========================================================================
def test_paper_id_from_summary_hit_id_parses_frozen_format():
    # Pins the "{paper_id}:summary" convention (DATA-CONTRACTS.md "IDs — the spine", Rule 3) that
    # `_paper_id_from_summary_hit_id` is the ONE sanctioned place in the codebase allowed to parse
    # (ci/checks/id_slicing.py fences its check around this exact function). If this format ever
    # changes, this is the one place that depends on it, and it should break loudly here first
    # rather than silently parsing garbage at the call site.
    assert _mod._paper_id_from_summary_hit_id("2506.01234:summary") == "2506.01234"


def test_retrieve_papers_empty_corpus_returns_empty_list():
    r = _make_retriever(FakeVectorStore(), RecordingDocStore(), FakeReranker())
    assert r.retrieve_papers("any query", filters=None, k=10) == []


def test_retrieve_papers_resolves_via_get_summary_and_get_spy():
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_summary(store, docstore, embedder, paper_id="2506.00001", summary_id="2506.00001:summary",
                  summary_text="a paper about instrumental variables")
    _make_retriever(store, docstore, FakeReranker(), embedder).retrieve_papers(
        "instrumental variables", filters=None, k=10)
    assert "get_summary" in docstore.method_names()
    assert "get" in docstore.method_names()


def test_retrieve_papers_returns_unanchored_paper_search_results():
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_summary(store, docstore, embedder, paper_id="2506.00001", summary_id="2506.00001:summary",
                  summary_text="a paper about instrumental variables")
    [result] = _make_retriever(store, docstore, FakeReranker(), embedder).retrieve_papers(
        "instrumental variables", filters=None, k=10)
    # It is a PaperSearchResult (view + score), explicitly NOT a GroundedResult / not anchored.
    assert not isinstance(result, GroundedResult)
    assert not hasattr(result, "anchor")
    assert result.view.paper_id == "2506.00001"
    assert result.view.summary_text == "a paper about instrumental variables"


def test_retrieve_papers_restricts_to_summary_kind():
    # A chunk sharing the query terms must NOT surface via retrieve_papers() (kind forced "summary").
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_summary(store, docstore, embedder, paper_id="2506.00001", summary_id="2506.00001:summary",
                  summary_text="regression discontinuity design")
    _seed_chunk(store, docstore, embedder, chunk_id="2506.00002:c0", paper_id="2506.00002",
                block_id="2506.00002:b0", text="regression discontinuity design")
    results = _make_retriever(store, docstore, FakeReranker(), embedder).retrieve_papers(
        "regression discontinuity", filters=None, k=10)
    assert [res.view.paper_id for res in results] == ["2506.00001"]


def test_retrieve_papers_rerank_wiring_is_its_own_assertion():
    # Independent of retrieve()'s rerank test: retrieve_papers() must wire the SAME injected reranker.
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_summary(store, docstore, embedder, paper_id="2506.00001", summary_id="2506.00001:summary",
                  summary_text="difference in differences")
    _seed_summary(store, docstore, embedder, paper_id="2506.00002", summary_id="2506.00002:summary",
                  summary_text="instrumental variables estimator")
    _seed_summary(store, docstore, embedder, paper_id="2506.00003", summary_id="2506.00003:summary",
                  summary_text="double machine learning")
    query = "causal estimator"
    reranker = FakeReranker()
    results = _make_retriever(store, docstore, reranker, embedder).retrieve_papers(
        query, filters=None, k=10)

    pre_rerank_ids = [h.id for h in _rrf_hits(store, embedder, query, "summary")]
    assert len(pre_rerank_ids) >= 2
    assert reranker.calls
    assert reranker.calls[-1] == (query, pre_rerank_ids)

    # summary_id -> paper_id via the seeded records (no id-string parsing in the test either).
    paper_of = {docstore._records[pid].summary_id: pid for pid in docstore._records}
    final_papers = [res.view.paper_id for res in results]
    expected_final = [paper_of[sid] for sid in reversed(pre_rerank_ids)]
    prerank_papers = [paper_of[sid] for sid in pre_rerank_ids]
    assert final_papers == expected_final
    assert final_papers != prerank_papers


def test_both_methods_use_the_same_injected_reranker():
    # The Reranker is a constructor arg, never hardcoded: the instance we inject is the one exercised
    # by BOTH methods (its .calls accumulates across a retrieve() and a retrieve_papers()).
    store, docstore, embedder = FakeVectorStore(), RecordingDocStore(), FakeEmbedder()
    _seed_chunk(store, docstore, embedder, chunk_id="2506.00001:c0", paper_id="2506.00001",
                block_id="2506.00001:b0", text="propensity score matching")
    _seed_summary(store, docstore, embedder, paper_id="2506.00001", summary_id="2506.00001:summary",
                  summary_text="propensity score matching")
    reranker = FakeReranker()
    r = _make_retriever(store, docstore, reranker, embedder)
    r.retrieve("propensity", filters=None, k=10)
    r.retrieve_papers("propensity", filters=None, k=10)
    assert len(reranker.calls) == 2
