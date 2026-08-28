"""Tests for `app/exp_chunk_boundary_neighbor_smooth.py` -- SB-1 arm (b).

Zero-GPU, zero-network: `TeiReranker`'s real HTTP call is stubbed via monkeypatching its
`rerank()` method directly (same posture as `app/test_exp_nb_rr_qwen_reranker.py` stubbing
`Qwen3Reranker._compute_scores`) -- what's pinned here is the smoothing CONTRACT (chunk-position
parsing, blend arithmetic, re-sort, the empty-input short-circuit, the monkeypatch itself), not a
real cross-encoder's numeric output.
"""

from __future__ import annotations

import app.assembly as assembly
from app.exp_chunk_boundary_neighbor_smooth import (
    NeighbourSmoothingReranker,
    _arm_tag,
    _looks_like_retrieval_eval_argv,
    apply_smoothing_patch,
    chunk_position,
    rank_proxy,
)
from contracts.retriever import RerankCandidate
from rag.fakes.fake_gpu_lock import FakeGpuLock


def _candidates(*ids: str) -> list[RerankCandidate]:
    return [RerankCandidate(id=i, text=f"text-{i}") for i in ids]


# --- chunk_position / rank_proxy -- pure helpers -------------------------------------------------


def test_chunk_position_parses_paper_and_index():
    assert chunk_position("2312.12675:c7") == ("2312.12675", 7)


def test_chunk_position_none_for_summary_id():
    assert chunk_position("2312.12675:summary") is None


def test_chunk_position_none_for_malformed_id():
    assert chunk_position("not-a-chunk-id") is None


def test_rank_proxy_monotonic_decreasing_in_rank():
    assert rank_proxy(0) > rank_proxy(1) > rank_proxy(2)


# --- argv-shape dispatch (same pattern as QW-3) --------------------------------------------------


def test_looks_like_retrieval_eval_argv_true_when_ground_truth_flag_present():
    argv = ["--ground-truth", "fixtures/eval/gt_wmr.json", "--config", "x.yaml", "--k", "10"]
    assert _looks_like_retrieval_eval_argv(argv) is True


def test_looks_like_retrieval_eval_argv_false_for_orchestrator_flags():
    argv = ["--arm", "smooth", "--out-dir", "docs/eval-reports/data/2026-08-28-sb1"]
    assert _looks_like_retrieval_eval_argv(argv) is False


def test_arm_tag_maps_both_arms():
    assert _arm_tag("bge") == "bge-baseline"
    assert _arm_tag("smooth") == "sb1b-smooth"


def test_apply_smoothing_patch_rebinds_assembly_tei_reranker(monkeypatch):
    original = assembly.TeiReranker
    monkeypatch.setattr(assembly, "TeiReranker", original)  # ensures pytest restores it after
    apply_smoothing_patch()
    assert assembly.TeiReranker is NeighbourSmoothingReranker


# --- NeighbourSmoothingReranker's contract --------------------------------------------------


def test_constructor_rejects_out_of_range_weight():
    import pytest

    with pytest.raises(ValueError):
        NeighbourSmoothingReranker(None, FakeGpuLock(), weight=1.5)


def test_rerank_returns_empty_list_for_no_candidates():
    reranker = NeighbourSmoothingReranker(None, FakeGpuLock())
    assert reranker.rerank("q", []) == []


def test_rerank_no_neighbours_in_pool_preserves_inner_order(monkeypatch):
    """Three chunks from three different papers -- no candidate has a position-adjacent sibling in
    the pool, so smoothing is a no-op and the inner (real) reranker's own order survives."""
    reranker = NeighbourSmoothingReranker(None, FakeGpuLock())
    candidates = _candidates("2312.12675:c7", "2011.00038:c2", "2403.14648:c9")
    # Inner TeiReranker's real order: c2 (paper B) best, then c9 (paper C), then c7 (paper A).
    inner_order = [candidates[1], candidates[2], candidates[0]]
    monkeypatch.setattr(reranker._inner, "rerank", lambda q, c: inner_order)

    result = reranker.rerank("q", candidates)

    assert [c.id for c in result] == [c.id for c in inner_order]


def test_rerank_blends_adjacent_chunk_up_when_neighbour_ranks_higher(monkeypatch):
    """c1's own rank-proxy is low (rank 2, last), but its neighbour c0 ranks first (high proxy).
    At weight=0.5 the blend should be enough to promote c1 above c2 (whose own rank is 1 / middle,
    with no neighbour in the pool at all)."""
    reranker = NeighbourSmoothingReranker(None, FakeGpuLock(), weight=0.5)
    c0 = RerankCandidate(id="P:c0", text="t0")
    c1 = RerankCandidate(id="P:c1", text="t1")
    c2 = RerankCandidate(id="Q:c5", text="t2")  # different paper -- never adjacent to c0/c1
    candidates = [c0, c1, c2]
    # Inner order: c0 (rank 0, proxy 1.0), c2 (rank 1, proxy 0.5), c1 (rank 2, proxy 0.333...).
    inner_order = [c0, c2, c1]
    monkeypatch.setattr(reranker._inner, "rerank", lambda q, c: inner_order)

    result = reranker.rerank("q", candidates)

    # c1 blended: 0.5*0.333 + 0.5*1.0 (its only neighbour, c0) = 0.667 > c2's own 0.5 -- c1 jumps
    # ahead of c2, while c0 (already rank 0, its only neighbour c1 scores lower) stays on top.
    assert [c.id for c in result] == ["P:c0", "P:c1", "Q:c5"]


def test_rerank_summary_ids_never_smoothed(monkeypatch):
    """`retrieve_papers()` routes through the same injected Reranker -- summary-kind ids must fall
    straight through with their own proxy score, never coerced into a chunk position."""
    reranker = NeighbourSmoothingReranker(None, FakeGpuLock())
    candidates = _candidates("2312.12675:summary", "2011.00038:summary")
    monkeypatch.setattr(reranker._inner, "rerank", lambda q, c: list(candidates))

    result = reranker.rerank("q", candidates)

    assert [c.id for c in result] == [c.id for c in candidates]
