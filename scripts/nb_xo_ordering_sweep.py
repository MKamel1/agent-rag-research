"""NB-X-O — ordering-quality sweep orchestrator (R0 rank 3): can CHEAP reranker-side levers
recover the deep-pool ordering losses WITHOUT a model swap?

QUESTION (one), from the ticket: at the deep-pool operating point (pool 64, serve 10 — where
NB-X-P realized ver84's newcomer hazard: 11 gold blocks lose rank, 2 leave the top-10, 2 enter
incl. Q-WAYB-031 at rank 1; text-arm block-P@1 23/60 = 0.3833 vs a 0.95 target), do any of
  (a) rerank-depth vs serve-depth split variations,
  (b) rank-agreement blending (reciprocal-rank of BGE order vs hybrid order),
  (c) other knobs the rag/reranker.py / runner seam exposes cheaply
recover ordering losses, measured per fixture with denominators and newcomer identities?

REUSE-FIRST — what is reused unchanged (named, per the mandate):
  * scripts/nb_eval_runner.py: FIXTURES, DEFAULT_CONFIG/DEFAULT_COLLECTION, fixture_argv
    (the exact reuse-seam CLI argv), load_and_verify_report (silent-death guard),
    extract_row (published-aggregate rows).
  * scripts/nb_xp_deeppool_tables.py: top10_restricted, newcomer_effect (gold block AND gold
    paper movement vs a same-parameter baseline, with identities), ordering_divergence +
    assert_within_jitter (X-P's measured cross-process jitter envelope).
  * app/retrieval_eval.py via subprocess for plain pool arms (lever a/c) — the identical path
    X-P ran; scripts/nb_xo_blend_arm.py for blend arms (lever b), which itself reuses
    app.retrieval_eval's load_questions/run/build_report UNMODIFIED in-process.
  * BASELINES ARE REUSED, NOT RE-SPENT: NB-X-P's committed same-day raw reports under
    docs/eval-reports/data/2026-08-25-nb-xp/raw/ are this sweep's baseline (pool 32 = shipped)
    and its rerank-64 point. "Rerank 64 -> serve 10" is COMPUTATIONALLY IDENTICAL to X-P's K=64
    arm truncated to its first 10 (retrieve() draws max(k, rerank_depth) candidates, reranks
    them all, truncates to k — pool and scoring are the same computation either way), so no GPU
    is spent re-measuring it; the report states this identity rather than assuming it silently.

ARM MATRIX (all arms serve k=10; serialized, one retrieval process at a time):
  baseline   pool 32 serve 10   REUSED  (X-P raw *.k10.json)
  r64s10     pool 64 serve 10   REUSED  (X-P raw *.k64.json, top-10-restricted view)
  p16        pool 16 serve 10   NEW GPU (app.retrieval_eval --config <copy w/ rerank_depth=16>)
  p128       pool 128 serve 10  NEW GPU (as above, rerank_depth=128; exercises multi-batch rerank)
  b0.0@64    alpha=0.0 pool 64  NEW GPU (control: pure hybrid pre-rerank order at depth)
  b0.3@64    alpha=0.3 pool 64  NEW GPU
  b0.5@64    alpha=0.5 pool 64  NEW GPU
  b0.7@64    alpha=0.7 pool 64  NEW GPU
Each NEW arm runs BOTH fixtures separately; nothing is averaged across fixtures (PREC-1 §5);
any claimed win must hold on both (cross-fixture held-out rule).

CONFIG COPIES, NOT LIVE FLIPS: pool arms get a generated config copy under
docs/eval-reports/data/2026-08-25-nb-xo/configs/config.rerank<N>.yaml — the live corpus
config.yaml is never edited. The live config's store paths are absolute, so copies resolve to
the same stores regardless of location.

Ticket: next-build programme §4 X-series X-O; mandates
docs/eval-reports/2026-08-25-nb-xp-deeppool-tables.md (evidence) +
docs/eval-reports/2026-08-25-nb-r0-fix-ranking.md (rank 3 + honest ceiling).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reuse seam imports land with commit 3; the stub keeps only argparse alive.
DEFAULT_XP_RAW = Path("docs/eval-reports/data/2026-08-25-nb-xp/raw")
DEFAULT_OUT_DIR = Path("docs/eval-reports/data/2026-08-25-nb-xo")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", default="/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml")
    parser.add_argument("--collection", default="waymo_av_safety")
    parser.add_argument("--xp-raw-dir", type=Path, default=DEFAULT_XP_RAW,
                        help="NB-X-P committed raw reports: <fixture>.k10.json is the baseline "
                             "all newcomer analyses diff against; <fixture>.k64.json is the "
                             "reused rerank-64 arm")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--arms", nargs="*", default=None,
                        help="subset of arm names to run (default: all NEW-GPU arms)")
    parser.add_argument("--limit", type=int, default=None, help="smoke-test: first N questions")
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--reuse-raw", action="store_true",
                        help="skip any arm x fixture whose raw report already exists and "
                             "verifies -- resume-after-dispatch support, one green arm per "
                             "commit (programme constraint 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print each planned command and exit without running anything")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    raise NotImplementedError(
        "NB-X-O commit 3 wires: arm registry -> serialized execution -> gates -> combined JSON/md"
    )


if __name__ == "__main__":
    sys.exit(main())
