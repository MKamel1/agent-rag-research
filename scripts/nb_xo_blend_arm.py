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
    alpha=1.0 reduces to sorting by BGE rank, alpha=0.0 to sorting by hybrid rank.
    """
    raise NotImplementedError("NB-X-O commit 2 implements the blend math")


class RrfBlendingReranker:
    """Wraps any Reranker: delegates the scoring call, then re-orders the returned candidates by
    `rrf_blend_scores` over (input-list position, returned-list position). Never fabricates,
    drops, or adds candidates — the wrapped contract's length preservation is preserved."""

    def __init__(self, inner, alpha: float, rrf_k: int = 60):
        raise NotImplementedError("NB-X-O commit 2")

    def rerank(self, query: str, candidates):
        raise NotImplementedError("NB-X-O commit 2")


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
    raise NotImplementedError(
        "NB-X-O commit 2 wires: load_config -> model_copy(rerank_depth) -> build_mcp_server -> "
        "wrap retriever reranker -> app.retrieval_eval.run/build_report UNMODIFIED -> report"
    )


if __name__ == "__main__":
    sys.exit(main())
