"""Tests for scripts/nb_xo_* — NB-X-O ordering-quality sweep.

All pure-function tests over synthetic candidate orderings — zero-GPU zero-network, mirroring
scripts/test_nb_xp_deeppool_tables.py. The GPU-backed blend-arm runner is exercised only
through --limit smoke runs inside the sweep, never here.
"""

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


blend_arm = _load("nb_xo_blend_arm")
rrf_blend_scores = blend_arm.rrf_blend_scores
RrfBlendingReranker = blend_arm.RrfBlendingReranker


def test_blend_arm_stub_imports_and_parses():
    args = blend_arm.parse_args([
        "--ground-truth", "fixtures/eval/gt_wmr.json",
        "--config", "/tmp/config.yaml",
        "--alpha", "0.5",
        "--report-path", "/tmp/report.json",
    ])
    assert args.alpha == 0.5 and args.k == 10 and args.collection == "waymo_av_safety"


def test_sweep_stub_imports_and_parses():
    mod = _load("nb_xo_ordering_sweep")
    args = mod.parse_args(["--dry-run"])
    assert args.dry_run and args.limit is None


@dataclass
class Cand:
    id: str
    text: str = "t"


def _ranks(order):
    return {c.id: i for i, c in enumerate(order, start=1)}


HYBRID = [Cand("h1"), Cand("h2"), Cand("h3"), Cand("h4")]
BGE = [Cand("h3"), Cand("h1"), Cand("h4"), Cand("h2")]


class FakeInner:
    """Returns the pre-set BGE ordering regardless of input — stands in for TeiReranker."""

    def __init__(self, order):
        self.order = order
        self.calls = []

    def rerank(self, query, candidates):
        self.calls.append((query, list(candidates)))
        by_id = {c.id: c for c in candidates}
        return [by_id[c.id] for c in self.order]


def test_rrf_alpha_one_is_pure_bge_order():
    scores = rrf_blend_scores(_ranks(HYBRID), _ranks(BGE), alpha=1.0)
    assert sorted(scores, key=lambda i: -scores[i]) == [c.id for c in BGE]


def test_rrf_alpha_zero_is_pure_hybrid_order():
    scores = rrf_blend_scores(_ranks(HYBRID), _ranks(BGE), alpha=0.0)
    assert sorted(scores, key=lambda i: -scores[i]) == [c.id for c in HYBRID]


def test_rrf_disagreement_case_moves_with_alpha():
    # h3 is BGE-best but hybrid-worst: raising alpha must monotonically raise its blended score.
    hyb, bge = _ranks(HYBRID), _ranks(BGE)
    lo = rrf_blend_scores(hyb, bge, alpha=0.0)["h3"]
    mid = rrf_blend_scores(hyb, bge, alpha=0.5)["h3"]
    hi = rrf_blend_scores(hyb, bge, alpha=1.0)["h3"]
    assert lo < mid < hi


def test_rrf_winner_tracks_alpha():
    # No rank-1 agreement in HYBRID/BGE (h1 is hybrid-1/bge-2, h3 is bge-1/hybrid-3): the
    # blended winner is h1 at alpha=0 and h3 by alpha=1, flipping exactly once.
    hyb, bge = _ranks(HYBRID), _ranks(BGE)
    winners = []
    for alpha in (0.0, 0.25, 0.5, 0.75, 1.0):
        scores = rrf_blend_scores(hyb, bge, alpha=alpha)
        winners.append(max(scores, key=lambda i: scores[i]))
    assert winners[0] == "h1" and winners[-1] == "h3"
    flips = sum(1 for a, b in zip(winners, winners[1:]) if a != b)
    assert flips == 1


def test_rrf_agreement_case_is_alpha_stable():
    # A candidate ranked 1 on BOTH arms stays maximal at every alpha.
    agree = [Cand("a1"), Cand("a2"), Cand("a3")]
    hyb, bge = _ranks(agree), _ranks(agree)
    for alpha in (0.0, 0.25, 0.5, 0.75, 1.0):
        scores = rrf_blend_scores(hyb, bge, alpha=alpha)
        assert max(scores, key=lambda i: scores[i]) == "a1"


def test_rrf_validates_inputs():
    with pytest.raises(ValueError):
        rrf_blend_scores({"a": 1}, {"a": 1}, alpha=1.5)
    with pytest.raises(ValueError):
        rrf_blend_scores({"a": 1}, {"b": 1}, alpha=0.5)


def test_wrapper_preserves_inner_order_at_alpha_one():
    inner = FakeInner(BGE)
    wrapped = RrfBlendingReranker(inner, alpha=1.0)
    out = wrapped.rerank("q", HYBRID)
    assert [c.id for c in out] == [c.id for c in BGE]
    # The inner reranker saw the candidates EXACTLY as handed over (same objects, same order).
    assert inner.calls[0][1] == HYBRID


def test_wrapper_restores_hybrid_order_at_alpha_zero():
    out = RrfBlendingReranker(FakeInner(BGE), alpha=0.0).rerank("q", HYBRID)
    assert [c.id for c in out] == [c.id for c in HYBRID]


def test_wrapper_never_fabricates_or_drops():
    out = RrfBlendingReranker(FakeInner(BGE), alpha=0.4).rerank("q", HYBRID)
    assert sorted(c.id for c in out) == sorted(c.id for c in HYBRID)
    assert all(isinstance(c, Cand) for c in out)


def test_wrapper_tie_breaks_toward_hybrid_rank():
    # Symmetric disagreement (two candidates swap the two ranks): equal blended scores — the
    # hybrid-rank tie-break decides, deterministically.
    a, b = Cand("x"), Cand("y")
    hybrid = [a, b]
    bge = [b, a]
    out = RrfBlendingReranker(FakeInner(bge), alpha=0.5).rerank("q", hybrid)
    assert [c.id for c in out] == ["x", "y"]


def test_wrapper_rejects_bad_alpha():
    with pytest.raises(ValueError):
        RrfBlendingReranker(FakeInner(BGE), alpha=-0.1)
