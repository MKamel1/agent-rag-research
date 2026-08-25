"""NB-X-O — blend-arm runner: ONE retrieval eval under an RRF rank-blended reranker.

Ticket NB-X-O (R0 rank 3, ordering quality at depth). This module is the measurement vehicle
for lever (b), rank-agreement blending: combine the cross-encoder's ordering with the hybrid
retriever's pre-rerank ordering, reciprocal-rank style, when the two disagree.

WHY A SEPARATE RUNNER (and not an app.retrieval_eval flag): the blend is runtime composition
around the injected `Reranker` collaborator (ARCHITECTURE §M7's seam) — `Retriever` takes its
reranker by constructor injection precisely so a different implementation can sit there
(CONVENTIONS §2). Wrapping at the composition point exercises the shipped pipeline end to end
(same embedder, same vector index, same DocumentStore, same `run()`/`build_report()` scoring)
while changing exactly ONE variable: the order the reranked candidates come back in. No source
file is edited; nothing foundation-gated is touched.

WHAT IS BLENDED, PRECISELY: `TeiReranker.rerank()` returns the candidate objects reordered by
cross-encoder score and DISCARDS the numeric scores (its contract: a length-preserving
reordering, DATA-CONTRACTS.md "Reranker"). The public seam therefore exposes the cross-encoder
only as an ORDERING, so the implemented blend is reciprocal-rank over the two orderings:

    score(c) = alpha / (rrf_k + bge_rank(c)) + (1 - alpha) / (rrf_k + hybrid_rank(c))

where hybrid_rank is the candidate's position in the list the RETRIEVER handed the reranker
(rag/retriever.py builds candidates in hybrid-hit order, minus dropped orphans) and bge_rank is
its position in the inner reranker's output. Ties break toward hybrid rank. alpha=1 reproduces
the pure BGE ordering exactly (control by construction); alpha=0 reproduces the pure hybrid
pre-rerank ordering (the no-reranker control). A score-scale blend (min-max/z-scored cross-
encoder logits mixed with rank priors) is NOT implementable through this seam without widening
the frozen Reranker contract or duplicating vendor HTTP code — see the ticket report's
follow-ups if the rank blend shows signal.

PROVENANCE: every emitted report stamps an `xo_provenance` block (alpha, rrf_k, effective pool,
wrapper description) AND carries the blend inside `scoring_rule`'s sparse_mode slot (build_report's
mode parameter is a free string here, so the artifact self-describes what produced it — RI-M3's
"two numbers produced under different rules cannot be compared silently", applied to this sweep).

Run shape mirrors `app.retrieval_eval.main()`: load config (optionally overriding
`Config.rerank_depth` via model_copy — the same frozen-pydantic pattern retrieval_eval itself
uses for the dense-weight override; NO live config file is edited), build_mcp_server, wrap the
retriever's reranker, run, build_report, write JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def rrf_blend_scores(
    hybrid_ranks: dict[str, int], bge_ranks: dict[str, int], alpha: float, rrf_k: int = 60
) -> dict[str, float]:
    """The blend itself, as a pure function over the two rank maps (unit-tested zero-GPU).

    score(id) = alpha/(rrf_k + bge_rank) + (1-alpha)/(rrf_k + hybrid_rank); ranks are 1-based.
    alpha=1.0 reduces to sorting by BGE rank, alpha=0.0 to sorting by hybrid rank. Both rank
    maps must cover the SAME id set (the wrapper guarantees this: both orderings are
    permutations of one candidate list).
    """
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha must be in [0, 1], got {alpha}")
    if rrf_k < 0:
        raise ValueError(f"rrf_k must be >= 0, got {rrf_k}")
    if set(hybrid_ranks) != set(bge_ranks):
        raise ValueError(
            "rank maps cover different id sets — both orderings must be permutations of the "
            f"same candidates ({len(hybrid_ranks)} hybrid vs {len(bge_ranks)} bge)"
        )
    return {
        cid: alpha / (rrf_k + bge_ranks[cid]) + (1 - alpha) / (rrf_k + hybrid_ranks[cid])
        for cid in bge_ranks
    }


class RrfBlendingReranker:
    """Wraps any Reranker: delegates the scoring call, then re-orders the returned candidates by
    `rrf_blend_scores` over (input-list position, returned-list position). Never fabricates,
    drops, or adds candidates — the wrapped contract's length preservation is preserved."""

    def __init__(self, inner, alpha: float, rrf_k: int = 60):
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"alpha must be in [0, 1], got {alpha}")
        self._inner = inner
        self._alpha = alpha
        self._rrf_k = rrf_k

    def rerank(self, query: str, candidates):
        # Inner call first: the cross-encoder sees the candidates EXACTLY as the retriever
        # handed them over (same query, same texts, same batch packing) — the blend changes
        # nothing about what is scored, only how the two orderings are merged afterwards.
        ordered = list(self._inner.rerank(query, candidates))
        bge_ranks = {c.id: i for i, c in enumerate(ordered, start=1)}
        hybrid_ranks = {c.id: i for i, c in enumerate(candidates, start=1)}
        scores = rrf_blend_scores(hybrid_ranks, bge_ranks, self._alpha, self._rrf_k)
        return sorted(ordered, key=lambda c: (-scores[c.id], hybrid_ranks[c.id]))


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--collection", default="waymo_av_safety")
    parser.add_argument("--k", type=int, default=10, help="serve depth (production top-10)")
    parser.add_argument("--pool", type=int, default=None,
                        help="override Config.rerank_depth for this arm (the candidate-pool "
                             "size the rerankers draw from); None keeps the config value")
    parser.add_argument("--alpha", type=float, required=True,
                        help="BGE weight in [0,1]; 1.0 = pure cross-encoder order, 0.0 = pure "
                             "hybrid pre-rerank order")
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--report-path", required=True)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    # Deferred imports: GPU-backed adapter wiring stays out of import time (same posture as
    # app/retrieval_eval.main, whose unit tests must never touch it).
    import app.retrieval_eval as r_eval
    from app.assembly import build_mcp_server
    from rag.config import load_config

    config = load_config(args.config)
    effective_pool = config.rerank_depth
    if args.pool is not None and args.pool != config.rerank_depth:
        config = config.model_copy(update={"rerank_depth": args.pool})
        effective_pool = args.pool

    server = build_mcp_server(config, collection=args.collection)
    # Runtime composition on the injected collaborator (ARCHITECTURE §M7's seam): the shipped
    # TeiReranker stays INSIDE the wrapper — every candidate still goes through it unchanged;
    # only the final ordering is merged with the hybrid prior.
    server.retriever._reranker = RrfBlendingReranker(
        server.retriever._reranker, alpha=args.alpha, rrf_k=args.rrf_k
    )

    questions = r_eval.load_questions(Path(args.ground_truth))
    if args.limit is not None:
        questions = questions[: args.limit]

    results = r_eval.run(questions, server.retriever, args.k)
    mode = (
        f"fused+rrf-rank-blend(alpha={args.alpha},rrf_k={args.rrf_k},pool={effective_pool})"
    )
    report = r_eval.build_report(
        results, args.k, mode=mode, hybrid_dense_weight=config.hybrid_dense_weight,
        include_per_question=True,
    )
    report["xo_provenance"] = {
        "ticket": "NB-X-O",
        "runner": "scripts/nb_xo_blend_arm.py",
        "blend": "reciprocal-rank of BGE order vs hybrid pre-rerank order "
                 "(score = alpha/(rrf_k+bge_rank) + (1-alpha)/(rrf_k+hybrid_rank); "
                 "ties -> hybrid rank)",
        "alpha": args.alpha,
        "rrf_k": args.rrf_k,
        "rerank_pool_size_effective": effective_pool,
        "config_rerank_depth": config.rerank_depth,
        "serve_k": args.k,
        "config_source": args.config,
        "collection": args.collection,
        "note": "numeric BGE scores are discarded by TeiReranker.rerank()'s contract, so the "
                "blend is rank-scale by construction; see module docstring",
    }
    Path(args.report_path).write_text(json.dumps(report, indent=2))
    print(f"[nb-xo-blend] wrote {args.report_path}")
    r_eval._print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
