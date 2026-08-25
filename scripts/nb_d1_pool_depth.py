"""NB-D1 — candidate-pool depth instrumentation (completes PREC-1 §2).

QUESTION (one): for scored items whose rank-1 PAPER is correct but whose gold BLOCK is not at
rank 1 -- PREC-1 §1's C1 population (gold block inside the returned top-10, ranks 2-10) and C2
population (gold block absent from the returned top-10 entirely) -- does the gold chunk exist
DEEPER in the candidate pool? I.e. would retrieving k in {32, 64, 128} candidates before the
rerank-to-10 expose it (and at what depth), or is it absent from every pool size?

METHOD (reuse-first): this script reuses `app.retrieval_eval.load_questions` UNCHANGED to load a
fixture and calls the REAL production pipeline (`app.assembly.build_mcp_server`) exactly the way
`app/retrieval_eval.py::main()` wires it -- same config loader, same `--collection` threading,
same frozen hybrid_dense_weight from the corpus config. The only new thing it does is call
`retriever.retrieve(text, None, K)` for K > 10: `Retriever.retrieve()` already fetches
`max(k, rerank_pool_size)` hybrid candidates, reranks the WHOLE pool (the reranker packs
oversized pools into multiple batches), and truncates to k only afterwards (rag/retriever.py,
T-DOC24), so asking for k=K returns the full reranked order of up-to-K candidates -- the deep
list -- with `coverage.candidate_count` reporting the true pre-rerank pool size. Nothing else in
the repo exposes deeper-than-10 ordering, which is why this instrumentation exists.

Read-only on all stores. No config changes; the config's own hybrid_dense_weight is used as-is.

STATUS: stub committed before any real work (NB-D1 commit 1 of N). A dead dispatch must be
resumable from committed state -- see docs/superpowers/plans/2026-08-24-next-build-programme.md
§2 Global Constraints #1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_POOL_SIZES = (32, 64, 128)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--pool-sizes", type=int, nargs="+", default=list(DEFAULT_POOL_SIZES))
    parser.add_argument("--out-json", required=True)
    return parser.parse_args()


def run_fixture(questions, retriever, pool_size: int) -> list[dict]:
    """One question x one pool size: classify against the deep list's own top-10 prefix, then
    record presence + 1-based depth of gold_block_id in the full deep list."""
    raise NotImplementedError("NB-D1 commit 3+")


def main() -> None:
    args = parse_args()
    print(f"NB-D1 pool-depth stub: ground_truth={args.ground_truth} "
          f"config={args.config} collection={args.collection} "
          f"pool_sizes={args.pool_sizes} out={args.out_json}")
    raise NotImplementedError("NB-D1 commit 3+")


if __name__ == "__main__":
    main()
