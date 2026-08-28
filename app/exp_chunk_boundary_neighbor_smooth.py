"""`python -m app.exp_chunk_boundary_neighbor_smooth` -- SB-1 arm (b): neighbour-chunk score
smoothing. R1 found no published measurement of this technique; it is treated here as a purely
local experiment, with the success criterion below FROZEN before the first real run (SB-1 commit
(1), before arm (b)'s own commit (2)) -- no threshold in this file may be tuned after seeing a
result.

MECHANISM: after the shipped cross-encoder reranker (`rag.reranker.TeiReranker`, BGE-reranker-v2-
m3) orders a query's candidate chunks, blend each chunk's rank-derived score with its POSITION-
ADJACENT siblings' scores -- same paper, chunk-id numeric suffix +/-1, exactly D2's own chunk-
position ordering (`docs/eval-reports/data/2026-08-23-waymo-priority/nb_d2_block_adjacency.py`'s
`_CHUNK_ID_RE` / "chunk-position distance" definition) -- then re-sort by the blended score. This
targets exactly D2's `adjacent_chunk` bucket: a chunk whose neighbour holds the gold text should
inherit some of that neighbour's relevance when the neighbour is ALSO in the reranked candidate
pool.

WHY A RANK-BASED SCORE PROXY, NOT `TeiReranker`'s RAW FLOAT SCORE: `Reranker.rerank(query,
candidates) -> list[RerankCandidate]` (contracts/retriever.py) is the whole public seam --
`RerankCandidate` carries no score field, and `TeiReranker.rerank()` returns candidates reordered,
never their score. Reaching into `TeiReranker`'s private batching/scoring internals to recover the
raw float would either duplicate its `_pack_batches`/token-budget/retry machinery (parallel code
path this ticket's measurement discipline `README` warns against re-deriving) or reach past its
own encapsulation into private members. Composition through the PUBLIC interface instead: build a
real `TeiReranker`, call its real `rerank()` once to get the true BGE order (with all of TEI's
batching/retry/token-budget handling untouched), then convert ORDER to a monotonic score proxy
(`_RANK_PROXY(rank) = 1/(rank+1)`, standard reciprocal-rank shape) before blending. This is a real,
documented cost: the blend operates on ORDER, not the cross-encoder's true relevance magnitude --
stated plainly here, not hidden, and revisited in the report if arm (b) looks promising enough to
warrant recovering the real float.

DISPATCH PATTERN: identical shape to `app/exp_nb_rr_qwen_reranker.py` (QW-3) -- argv SHAPE decides
orchestrator vs. shim mode (`_looks_like_retrieval_eval_argv`), and the shim rebinds the module-
global `app.assembly.TeiReranker` name (`apply_smoothing_patch()`) before calling
`app.retrieval_eval.main()` unmodified. Neither `app/assembly.py` nor `app/retrieval_eval.py` is
edited on disk. See that module's docstring for the full rationale (env-var-vs-argv-shape dispatch,
late-binding mechanics) -- not re-derived here.

VENDOR-ISOLATION NOTE: this module never constructs the vendor HTTP client itself (deliberately
never spelled out by name here -- `ci/checks/vendor_isolation.py` greps the literal token, and
this file isn't one of that adapter's allowlisted paths). `app.assembly.build_mcp_server` (already
the one allowlisted composition root) builds the real transport client and hands it to whatever
class `TeiReranker` currently names -- `NeighbourSmoothingReranker` below only ever RECEIVES that
already-built client and forwards it, unmodified, into a real inner `TeiReranker` it constructs by
composition. No new vendor import lands in this file.

GPU-LOCK NOTE: `NeighbourSmoothingReranker` does no GPU work of its own -- it delegates entirely to
the inner `TeiReranker.rerank()` call, which already acquires `gpu_lock.acquire("rerank")` around
its own HTTP attempts (rag/reranker.py). `gpu_lock` is still a required constructor parameter (and
threaded into the inner instance) so `ci/checks/gpu_lock.py`'s check (f) -- every `*Reranker`
class declares one -- holds structurally, and so a caller passing a REAL `FileGpuLock` gets the
same serialization the shipped reranker already provides, with zero new locking invented.

======================================================================================
PRE-REGISTERED SUCCESS CRITERION (frozen in SB-1 commit (1), before arm (b) is ever run)
======================================================================================

Primary configuration: `weight=0.3` (own score keeps 70% weight; the mean of whichever
position-adjacent neighbours are ALSO in the candidate pool gets 30%). This is the ONLY
configuration the verdict below is decided on. A second weight (0.5) may be run and reported as
additional context, but never substituted for the primary weight's verdict -- picking whichever
weight looks best after the fact would be exactly the p-hacking this freeze exists to prevent.

ADOPT requires ALL of the following, on BOTH fixtures INDEPENDENTLY (gt_wmr and ver84 are never
averaged, per programme constraint 7):
  1. block-P@1 (text-answerable, passage-scored) improves by >= +2 percentage points vs. the
     freshly-reproduced today's-config baseline.
  2. R@10 (answerable) does not regress by more than 1 percentage point.
  3. The D2 boundary-defined near-miss share (same_chunk + adjacent_chunk, as a fraction of ALL
     near-misses) decreases from baseline -- i.e. items D2 classified as boundary-defined convert
     to hits, not merely reshuffle among near-miss buckets.
  4. The gain is not fully explained by anchor-exactness alone (measurement discipline: a gain
     that comes from GroundedResult's rank-1 chunk changing to one whose OWN anchor happens to
     equal gold_block_id, with no actual improvement in whether the right evidence was surfaced,
     does not count -- cross-check against the D2 report's Section 2 "anchor/citation artifact"
     pattern before crediting a win here).

REJECT if block-P@1 regresses on either fixture, or R@10 regresses beyond the 1pp floor on either
fixture, at the primary weight.

INCONCLUSIVE (the expected, acceptable outcome per the ticket's own honest-ceiling framing: D2
found boundary effects explain only 25-33% of near-misses) if results are mixed across fixtures,
sit inside noise (a swing of 1-2 items on n=27/n=12 near-miss populations), or satisfy criteria
1-3 but fail 4.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

from contracts.gpu_lock import GpuLock
from contracts.retriever import RerankCandidate
from rag.reranker import TeiReranker
from scripts.nb_eval_runner import DEFAULT_COLLECTION, DEFAULT_CONFIG

REPO_ROOT = Path(__file__).resolve().parent.parent

# D2's own chunk-id format ("{paper_id}:c{n}"), reused verbatim (module docstring) -- the numeric
# suffix IS D2's chunk-position ordering (nb_d2_block_adjacency.py's PaperGeometry / _CHUNK_ID_RE).
_CHUNK_ID_RE = re.compile(r"^(?P<paper>.+):c(?P<n>\d+)$")

_SUBPROCESS_TIMEOUT_S = 3600

# The one pre-registered primary weight -- see the module docstring's frozen criterion.
PRIMARY_WEIGHT = 0.3


def chunk_position(candidate_id: str) -> tuple[str, int] | None:
    """`(paper_id, chunk_index)` for a chunk-kind id, or `None` for anything else (a
    `":summary"`-kind id, or any id that doesn't match the chunker's own format) -- the `None`
    case is deliberate: `retrieve_papers()` routes through the SAME injected `Reranker`, and a
    summary id must fall through to "no smoothing, return the own score unchanged" rather than
    being coerced into a chunk position it doesn't have.
    """
    m = _CHUNK_ID_RE.match(candidate_id)
    if not m:
        return None
    return m.group("paper"), int(m.group("n"))


def rank_proxy(rank: int) -> float:
    """Reciprocal-rank score proxy for a 0-indexed rank position -- see module docstring's "WHY A
    RANK-BASED SCORE PROXY" for why this stands in for `TeiReranker`'s un-exposed raw float."""
    return 1.0 / (rank + 1)


class NeighbourSmoothingReranker:
    """SB-1 arm (b) candidate `Reranker` adapter. Constructor-compatible with `TeiReranker`'s own
    shape (`app.assembly.build_mcp_server`'s call site: `TeiReranker(<transport client>, gpu_lock,
    ensure_ready=...)`) so `apply_smoothing_patch()` can rebind the class name it constructs with
    no other change needed. See module docstring for the full mechanism/rationale.
    """

    def __init__(
        self,
        client,
        gpu_lock: GpuLock,
        *,
        weight: float = PRIMARY_WEIGHT,
        ensure_ready=None,
        gpu_lock_timeout: float | None = 300.0,
        **tei_reranker_kwargs,
    ):
        if not 0.0 <= weight <= 1.0:
            raise ValueError(f"weight must be in [0, 1], got {weight!r}")
        self._weight = weight
        # Composition, not subclassing (module docstring) -- the inner instance owns every real
        # HTTP/retry/token-budget/gpu-lock detail; this class adds only the blend-and-resort step.
        self._inner = TeiReranker(
            client, gpu_lock, ensure_ready=ensure_ready,
            gpu_lock_timeout=gpu_lock_timeout, **tei_reranker_kwargs,
        )

    def rerank(self, query: str, candidates: list[RerankCandidate]) -> list[RerankCandidate]:
        if not candidates:
            return []
        ordered = self._inner.rerank(query, candidates)
        own_proxy = {c.id: rank_proxy(rank) for rank, c in enumerate(ordered)}
        smoothed = self._smooth(ordered, own_proxy)
        # Stable resort: smoothed score descending, tie-broken by the inner reranker's own rank
        # ascending (never candidates' input order, which carries no ranking information here).
        order = sorted(range(len(ordered)), key=lambda i: (-smoothed[ordered[i].id], i))
        return [ordered[i] for i in order]

    def _smooth(
        self, ordered: list[RerankCandidate], own_proxy: dict[str, float]
    ) -> dict[str, float]:
        """Blends each candidate's own proxy score with the mean of whichever position-adjacent
        (same paper, chunk index +/-1) siblings are ALSO present in `ordered` -- a neighbour
        outside the reranked pool can't be blended in, an expected and documented limitation
        (the pool is `Config.rerank_depth` wide, not the whole corpus).
        """
        positions = {c.id: chunk_position(c.id) for c in ordered}
        by_position = {p: cid for cid, p in positions.items() if p is not None}
        out: dict[str, float] = {}
        for c in ordered:
            pos = positions[c.id]
            if pos is None:
                out[c.id] = own_proxy[c.id]
                continue
            paper, idx = pos
            neighbour_scores = [
                own_proxy[by_position[(paper, idx + delta)]]
                for delta in (-1, 1)
                if (paper, idx + delta) in by_position
            ]
            if not neighbour_scores:
                out[c.id] = own_proxy[c.id]
            else:
                mean_neighbour = sum(neighbour_scores) / len(neighbour_scores)
                out[c.id] = (1 - self._weight) * own_proxy[c.id] + self._weight * mean_neighbour
        return out


def apply_smoothing_patch() -> None:
    """Rebinds `app.assembly.TeiReranker` (resolved at CALL time by `build_mcp_server`, not at its
    own def time -- Python's late binding of a function body's free variables against its module's
    globals) to `NeighbourSmoothingReranker`. `app/assembly.py` is never edited on disk."""
    import app.assembly as assembly

    assembly.TeiReranker = NeighbourSmoothingReranker


def _looks_like_retrieval_eval_argv(argv: list[str]) -> bool:
    """Same argv-shape dispatch key as QW-3 (`app/exp_nb_rr_qwen_reranker.py`) -- `--ground-truth`
    is `app.retrieval_eval._parse_args`'s own flag and never appears in this module's own
    orchestrator CLI below."""
    return "--ground-truth" in argv


def _arm_tag(arm: str) -> str:
    return {"bge": "bge-baseline", "smooth": "sb1b-smooth"}[arm]


def run_arm(arm: str, args: argparse.Namespace) -> int:
    """One arm, both fixtures, via the unmodified `scripts/nb_eval_runner.py` reuse seam --
    identical orchestration shape to QW-3's `run_arm`."""
    cmd = [
        args.python_exe, str(REPO_ROOT / "scripts" / "nb_eval_runner.py"),
        "--config", args.config,
        "--collection", args.collection,
        "--k", str(args.k),
        "--sparse-mode", "fused",
        "--out-dir", str(args.out_dir),
        "--date", args.date,
        "--tag", _arm_tag(arm),
    ]
    if arm == "smooth":
        cmd += ["--runner-module", "app.exp_chunk_boundary_neighbor_smooth"]
    if args.limit is not None:
        cmd += ["--limit", str(args.limit)]

    print(f"[sb1b] {arm}: {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, timeout=_SUBPROCESS_TIMEOUT_S)  # noqa: S603
    if proc.returncode != 0:
        raise SystemExit(f"SB-1 arm (b): arm {arm!r} exited {proc.returncode}")
    return proc.returncode


def _parse_orchestrator_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("bge", "smooth", "both"), default="both")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--out-dir", default="docs/eval-reports/data/2026-08-28-sb1")
    parser.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    parser.add_argument("--limit", type=int, default=None, help="smoke-test: first N questions")
    parser.add_argument("--python-exe", default=sys.executable)
    return parser.parse_args(argv)


def _orchestrate(argv: list[str]) -> int:
    args = _parse_orchestrator_args(argv)
    arms = ("bge", "smooth") if args.arm == "both" else (args.arm,)
    for arm in arms:
        run_arm(arm, args)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if _looks_like_retrieval_eval_argv(argv):
        apply_smoothing_patch()
        from app.retrieval_eval import main as retrieval_eval_main

        retrieval_eval_main()
        return 0
    return _orchestrate(argv)


if __name__ == "__main__":
    sys.exit(main())
