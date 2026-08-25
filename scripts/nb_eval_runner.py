"""NB-D4 — one-command dual-fixture evaluation runner (the next-build programme's ruler).

Runs BOTH retrieval ground-truth fixtures (`gt_wmr.json`, `waymo_gt_verified.json`) against the
current shipped config in one invocation and emits the standard combined table: per fixture,
the answerable arm's Recall@10 / MRR / block-P@1 WITH denominators, plus the known-absent arm
reported separately (never blended into any headline -- BENCH-1). Output: a dated JSON under
`docs/eval-reports/data/` plus a short markdown summary alongside it.

ORCHESTRATION CHOICE -- subprocess, not direct import. This module never imports
`app.retrieval_eval`; it invokes `python -m app.retrieval_eval` as a subprocess per fixture.
Why:

  1. The reuse seam IS that CLI. Every prior measurement (T-DOC baselines, RI-M3 ablation,
     FUSE-1/FUSE-2 sweeps, the waymo-priority benchmark) drove exactly this entry point
     per-arm; orchestrating over it keeps D4's numbers on the identical measured path instead
     of a parallel in-process code path that could drift from what the CLI actually runs.
  2. Process isolation between two heavy wirings. Each fixture run builds its own MCP server
     (`app.assembly.build_mcp_server`: TEI embedder + reranker + Qdrant). Two of those in one
     process share module-level state and logging config, and let fixture 2's failure take
     down fixture 1's already-completed work only by luck. A subprocess boundary means each
     fixture lives or dies independently and its report lands on disk either way.
  3. It keeps GPU-backed adapter wiring out of THIS module entirely, so the unit tests
     (`scripts/test_nb_eval_runner.py`) exercise only pure aggregation/rendering functions --
     zero-GPU, zero-network, no services needed, matching the repo's CI posture.
The cost is one extra interpreter + service handshake per fixture (~seconds), noise next to
a full retrieval sweep.

SILENT-DEATH GUARD (programme constraint 4): a dispatch can exit 0 while doing nothing. Each
fixture's subprocess must (a) exit 0, AND (b) have written its report file, AND (c) that file
must parse and carry `n_questions > 0` -- otherwise the runner fails loudly instead of
emitting an empty table that looks like a measurement.

Ticket: docs/superpowers/plans/2026-08-24-next-build-programme.md §4 D4. Stub commit -- real
logic lands next commit.
"""

from __future__ import annotations

import argparse

# Ordered: the standard combined table always reports both fixtures, in this order.
FIXTURES: tuple[tuple[str, str], ...] = (
    ("gt_wmr", "fixtures/eval/gt_wmr.json"),
    ("waymo_gt_verified", "fixtures/eval/waymo_gt_verified.json"),
)

DEFAULT_CONFIG = "/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml"
DEFAULT_COLLECTION = "waymo_av_safety"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raise NotImplementedError("NB-D4 stub -- implemented in the next commit")


def main() -> None:
    _parse_args()


if __name__ == "__main__":
    main()
