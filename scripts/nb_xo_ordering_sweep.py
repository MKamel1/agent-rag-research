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
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reuse seams (sibling imports; see module docstring "REUSE-FIRST").
from nb_eval_runner import (  # noqa: E402 -- deliberate sibling imports, same pattern as nb_xp
    DEFAULT_COLLECTION,
    DEFAULT_CONFIG,
    FIXTURES,
    extract_row,
    fixture_argv,
    load_and_verify_report,
)
from nb_xp_deeppool_tables import (  # noqa: E402
    assert_within_jitter,
    newcomer_effect,
    ordering_divergence,
    top10_restricted,
)

DEFAULT_XP_RAW = Path("docs/eval-reports/data/2026-08-25-nb-xp/raw")
DEFAULT_OUT_DIR = Path("docs/eval-reports/data/2026-08-25-nb-xo")
_SUBPROCESS_TIMEOUT_S = 3600

# The NEW-GPU arms. `kind` selects the runner: "cli" = python -m app.retrieval_eval with a
# generated config copy (pool lever); "blend" = scripts/nb_xo_blend_arm.py with an alpha.
ARMS = (
    {"name": "p16", "kind": "cli", "pool": 16},
    {"name": "p128", "kind": "cli", "pool": 128},
    {"name": "b0.0_at_64", "kind": "blend", "pool": 64, "alpha": 0.0},
    {"name": "b0.3_at_64", "kind": "blend", "pool": 64, "alpha": 0.3},
    {"name": "b0.5_at_64", "kind": "blend", "pool": 64, "alpha": 0.5},
    {"name": "b0.7_at_64", "kind": "blend", "pool": 64, "alpha": 0.7},
)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
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


def write_config_copy(source_config: Path, pool: int, dest: Path) -> None:
    """One YAML copy of the corpus config with ONLY rerank_depth changed — the pool lever as a
    per-arm artifact, so no live file is ever edited and each arm's config is committed."""
    import yaml

    data = yaml.safe_load(source_config.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f"NB-X-O: {source_config} is not a YAML mapping")
    data["rerank_depth"] = int(pool)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(data, sort_keys=False))


def blend_argv(python_exe: str, ground_truth: str, config: str, collection: str, k: int,
               report_path: Path, pool: int, alpha: float, limit: int | None) -> list[str]:
    cmd = [
        python_exe, str(REPO_ROOT / "scripts" / "nb_xo_blend_arm.py"),
        "--ground-truth", ground_truth,
        "--config", config,
        "--collection", collection,
        "--k", str(k),
        "--pool", str(pool),
        "--alpha", str(alpha),
        "--report-path", str(report_path),
    ]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    return cmd


def load_baseline(xp_raw_dir: Path, name: str, k: int) -> dict:
    """Re-verify a reused X-P raw report on every invocation (it is an input, trusted only
    after the same silent-death guard every fresh report passes)."""
    path = xp_raw_dir / f"{name}.k{k}.json"
    report = load_and_verify_report(path)
    if report.get("k") != k:
        raise SystemExit(f"NB-X-O: baseline {path} has k={report.get('k')}, expected {k}")
    return report


def verify_new_report(report_path: Path, arm: dict) -> dict:
    """Silent-death guard + zero-error gate + provenance gate for a freshly-run arm."""
    report = load_and_verify_report(report_path)
    n_errors = report.get("n_errors", 0)
    if n_errors:
        raise SystemExit(
            f"NB-X-O: {report_path} carries {n_errors} errored questions -- an errored question "
            "is a missing observation, not a miss; investigate before publishing"
        )
    if arm["kind"] == "blend":
        prov = report.get("xo_provenance")
        if not prov or abs(prov.get("alpha", -1) - arm["alpha"]) > 1e-9:
            raise SystemExit(
                f"NB-X-O: {report_path} lacks matching xo_provenance for arm {arm['name']}"
            )
    return report


def run_arm_fixture(arm: dict, name: str, ground_truth: str, report_path: Path,
                    args: argparse.Namespace) -> dict:
    if args.reuse_raw and report_path.exists():
        try:
            report = load_and_verify_report(report_path)
            if report.get("k") == 10 and not report.get("n_errors"):
                print(f"[nb-xo] {arm['name']} {name}: reusing verified {report_path}", flush=True)
                return report
        except SystemExit:
            print(f"[nb-xo] {arm['name']} {name}: stale/unverifiable raw present, re-running",
                  flush=True)
    if arm["kind"] == "cli":
        cfg_copy = args.out_dir / "configs" / f"config.rerank{arm['pool']}.yaml"
        write_config_copy(Path(args.config), arm["pool"], cfg_copy)
        cmd = fixture_argv(
            args.python_exe, "app.retrieval_eval", ground_truth, str(cfg_copy),
            args.collection, 10, report_path, "fused", None, args.limit,
        )
    else:
        cmd = blend_argv(
            args.python_exe, ground_truth, args.config, args.collection, 10,
            report_path, arm["pool"], arm["alpha"], args.limit,
        )
    print(f"[nb-xo] {arm['name']} {name}: {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(  # noqa: S603 -- fixed argv built here, no shell
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S
        )
    except subprocess.TimeoutExpired as e:
        raise SystemExit(
            f"NB-X-O: {arm['name']} {name} timed out after {_SUBPROCESS_TIMEOUT_S}s"
        ) from e
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-30:])
        raise SystemExit(f"NB-X-O: {arm['name']} {name} exited {proc.returncode}:\n{tail}")
    print(f"[nb-xo] {arm['name']} {name}: exit 0, verifying...", flush=True)
    return verify_new_report(report_path, arm)


def analyze(baseline: dict, report: dict, gt: str, name: str, arm: dict,
            raw_path: Path, reuse_note: str | None = None) -> dict:
    """Everything derived from one arm's raw report, per fixture: standard row, top-10-
    restricted view, newcomer tables (gold block + gold paper, with identities), and the
    ordering divergence class vs the baseline (contextualizes every rank delta with the jitter
    envelope it must exceed to be real)."""
    entry = {
        "arm": arm["name"],
        "kind": arm["kind"],
        "fixture": name,
        "ground_truth": gt,
        "row": extract_row(name, gt, report),
        "top10_restricted": top10_restricted(report),
        "newcomer_vs_baseline": newcomer_effect(baseline, report),
        "ordering_divergence_vs_baseline": ordering_divergence(baseline, report),
        "raw_report": str(raw_path),
    }
    if reuse_note:
        entry["reuse_note"] = reuse_note
    return entry


def _frac(hits: int | None, n: int | None) -> str:
    if hits is None or not n:
        return "n/a"
    return f"{hits}/{n} = {hits / n:.4f}"


def render_markdown(combined: dict) -> str:
    lines = [
        "# Ordering-quality sweep — NB-X-O (raw tables; narrative lives in the dated report)",
        "",
        f"Config: `{combined['config']}` · collection: `{combined['collection']}` · all arms "
        f"serve k=10 · baseline + rerank-64 arm REUSED from NB-X-P same-day raw reports",
        "",
        "## Top-10-restricted view — R@10 / MRR@10 / block-P@1 (text arm) per fixture per arm",
        "",
        "| fixture | arm | R@10 | MRR@10 | block-P@1 |",
        "|---|---|---|---|---|",
    ]
    for fx in combined["fixtures"]:
        for entry in fx["arms"]:
            t = entry["top10_restricted"]
            bp = t["block_p_at_1"]
            r10 = t["recall_at_10"]
            mrr = f"{t['mrr_at_10']:.4f}" if t['mrr_at_10'] is not None else "n/a"
            lines.append(
                f"| {fx['fixture']} | {entry['arm']} | {_frac(r10['hits'], r10['n'])} | {mrr} "
                f"| {_frac(bp['hits'], bp['n'])} |"
            )
    lines += [
        "",
        "## Newcomer effect vs baseline (gold-block ranks; identities in the JSON)",
        "",
        "| fixture | arm | lost rank | fell out of top-10 | gained into top-10 | improved |",
        "|---|---|---|---|---|---|",
    ]
    for fx in combined["fixtures"]:
        for entry in fx["arms"]:
            gb = entry["newcomer_vs_baseline"]["gold_block"]
            lines.append(
                f"| {fx['fixture']} | {entry['arm']} | {gb['lost_rank_count']} | "
                f"{len(gb['lost_from_top10_ids'])} | {len(gb['gained_into_top10'])} | "
                f"{gb['improved_count']} |"
            )
    lines += [
        "",
        "Known-absent arm never blended into any headline (BENCH-1); fixtures never averaged "
        "(PREC-1 §5); cross-fixture held-out rule applies to any claimed win.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    args = parse_args(argv)
    requested = set(args.arms) if args.arms else None
    known = {a["name"] for a in ARMS}
    if requested is not None and requested - known:
        raise SystemExit(f"NB-X-O: unknown arms {sorted(requested - known)}; known: {sorted(known)}")
    arms = [a for a in ARMS if requested is None or a["name"] in requested]

    raw_dir = args.out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    baselines = {}
    for name, _gt in FIXTURES:
        baselines[name] = load_baseline(args.xp_raw_dir, name, 10)

    if args.dry_run:
        for arm in arms:
            for name, gt in FIXTURES:
                if arm["kind"] == "cli":
                    cfg_copy = args.out_dir / "configs" / f"config.rerank{arm['pool']}.yaml"
                    cmd = fixture_argv(args.python_exe, "app.retrieval_eval", gt, str(cfg_copy),
                                       args.collection, 10, raw_dir / f"{name}.{arm['name']}.json",
                                       "fused", None, args.limit)
                else:
                    cmd = blend_argv(args.python_exe, gt, args.config, args.collection, 10,
                                     raw_dir / f"{name}.{arm['name']}.json", arm["pool"],
                                     arm["alpha"], args.limit)
                print(f"[dry-run] {' '.join(cmd)}")
        return 0

    # Serialized sweep: fixture inner, one retrieval process alive at a time.
    fixtures_out = []
    for name, gt in FIXTURES:
        entries = []
        entries.append(analyze(
            baselines[name], baselines[name], gt, name,
            {"name": "baseline_pool32", "kind": "reused"},
            args.xp_raw_dir / f"{name}.k10.json",
            reuse_note="NB-X-P committed same-day raw baseline (pool 32 = shipped config)",
        ))
        entries.append(analyze(
            baselines[name], load_baseline(args.xp_raw_dir, name, 64), gt, name,
            {"name": "r64s10_rerank64", "kind": "reused"},
            args.xp_raw_dir / f"{name}.k64.json",
            reuse_note="computationally identical to 'rerank 64 -> serve 10': retrieve() draws "
                       "max(k, rerank_depth)=64 candidates, reranks all, truncates to 10",
        ))
        for arm in arms:
            report_path = raw_dir / f"{name}.{arm['name']}.json"
            report = run_arm_fixture(arm, name, gt, report_path, args)
            entries.append(analyze(baselines[name], report, gt, name, arm, report_path))
        fixtures_out.append({"fixture": name, "ground_truth": gt, "arms": entries})

    combined = {
        "ticket": "NB-X-O",
        "generated_by": "scripts/nb_xo_ordering_sweep.py",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "config": args.config,
        "collection": args.collection,
        "serve_k": 10,
        "limit": args.limit,
        "xp_raw_dir": str(args.xp_raw_dir),
        "arms_run": [a["name"] for a in arms],
        "fixtures": fixtures_out,
        "jitter_envelope_inherited_from": (
            "NB-X-P duplicate probe (its report's Cross-process jitter probe section): <=~4% of "
            "questions permute adjacently across processes, membership never changes; "
            "single-position rank movements carry that caveat"
        ),
    }
    out_json = args.out_dir / "nb-xo-ordering-sweep.json"
    out_md = args.out_dir / "nb-xo-ordering-sweep.md"
    out_json.write_text(json.dumps(combined, indent=2))
    out_md.write_text(render_markdown(combined))
    print(f"[nb-xo] wrote {out_json}")
    print(f"[nb-xo] wrote {out_md}")
    print(render_markdown(combined))
    return 0


if __name__ == "__main__":
    sys.exit(main())
