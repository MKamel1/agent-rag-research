"""NB-D4 — one-command dual-fixture evaluation runner (the next-build programme's ruler).

Runs BOTH retrieval ground-truth fixtures (`gt_wmr.json`, `waymo_gt_verified.json`) against the
current shipped config in one invocation and emits the standard combined table: per fixture,
the answerable arm's Recall@10 / MRR / block-P@1 WITH denominators, plus the known-absent arm
reported separately (never blended into any headline -- BENCH-1). Output: a dated JSON under
`docs/eval-reports/data/` plus a short markdown summary alongside it, and the raw per-fixture
reports exactly as `app/retrieval_eval.py` wrote them.

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

WHAT THIS MODULE ADDS OVER THE RAW REPORTS: nothing new is scored here. The combined table
reads `build_report`'s published aggregates (`paper_level.by_gold_status.answerable`,
`passage_level.by_vision_status.text_answerable`, `paper_level.by_gold_status.known_absent`)
and derives only display counts (hits / denominator) from the stored per-question rows,
cross-checked against those same aggregates -- a mismatch fails loudly rather than shipping
two disagreeing truths. block-P@1 follows PREC-1's published definition: share of
text-answerable passage-scored items whose gold block sits at rank exactly 1 (the VARM-1
text arm -- vision-derived items keep their own denominator and are never blended in).

Ticket: docs/superpowers/plans/2026-08-24-next-build-programme.md §4 D4.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Ordered: the standard combined table always reports both fixtures, in this order.
FIXTURES: tuple[tuple[str, str], ...] = (
    ("gt_wmr", "fixtures/eval/gt_wmr.json"),
    ("waymo_gt_verified", "fixtures/eval/waymo_gt_verified.json"),
)

DEFAULT_CONFIG = "/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml"
DEFAULT_COLLECTION = "waymo_av_safety"
DEFAULT_RUNNER_MODULE = "app.retrieval_eval"

# BENCH-1/VARM-1 honesty notes travel INTO the emitted artifacts: the never-blend rule belongs
# to the numbers themselves, not just to this docstring.
_NEVER_BLEND_NOTE = (
    "Known-absent items have an empty gold set and miss by construction; blending them into "
    "recall deflates the headline with guaranteed misses (BENCH-1). Their arm is reported "
    "through its size and top-score distribution only. block-P@1 covers the VARM-1 "
    "text_answerable passage-scored arm; vision_derived items keep their own denominator in "
    "the raw per-fixture JSON and are never blended in here."
)

_SUBPROCESS_TIMEOUT_S = 3600


def output_paths(out_dir: Path, date: str, tag: str | None) -> tuple[Path, Path, Path]:
    """The dated output trio: combined JSON, its md summary, and the raw-reports subdirectory."""
    stem = f"{date}-nb-d4-dual-fixture" + (f"-{tag}" if tag else "")
    base = out_dir / stem
    return base.with_suffix(".json"), base.with_suffix(".md"), base


def fixture_argv(
    python_exe: str,
    runner_module: str,
    ground_truth: str,
    config_path: str,
    collection: str,
    k: int,
    report_path: Path,
    sparse_mode: str,
    dense_weight: float | None,
    limit: int | None,
) -> list[str]:
    """The exact per-fixture command: the reuse seam's own CLI, nothing invented here."""
    cmd = [
        python_exe, "-m", runner_module,
        "--ground-truth", ground_truth,
        "--config", config_path,
        "--collection", collection,
        "--k", str(k),
        "--sparse-mode", sparse_mode,
        "--report-path", str(report_path),
    ]
    if dense_weight is not None:
        cmd += ["--dense-weight", str(dense_weight)]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    return cmd


def load_and_verify_report(report_path: Path) -> dict:
    """Silent-death guard, steps (b)+(c): the file must exist, parse, and describe a real run."""

    def _die(reason: str) -> None:
        raise SystemExit(
            f"NB-D4: fixture report failed verification: {report_path}: {reason} "
            "(exit 0 with no artifact is the known silent-death signature, not a measurement)"
        )

    if not report_path.exists():
        _die("report file was not written")
    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError as e:
        _die(f"report is not valid JSON ({e})")
    if not isinstance(report, dict):
        _die("report is not a JSON object")
    if report.get("n_questions", 0) <= 0:
        _die(f"n_questions={report.get('n_questions')!r} -- nothing was scored")
    return report


def _cross_check(label: str, derived: float, published: float | None) -> None:
    """Counts derived from per-question rows must agree with build_report's aggregate."""
    if published is None:
        return
    if abs(derived - published) > 1e-9:
        raise SystemExit(
            f"NB-D4: inconsistent report at {label}: per-question rows give {derived!r} but the "
            f"published aggregate says {published!r} -- refusing to emit a table carrying two "
            "disagreeing truths"
        )


def extract_row(name: str, ground_truth: str, report: dict) -> dict:
    """One fixture's standard-table row: answerable R@10/MRR/block-P@1 with exact
    denominators, plus the known-absent arm verbatim. The rates come from build_report's
    published aggregates unmodified; hits/denominators are counted from the stored
    per-question rows and cross-checked against those aggregates."""
    gold_status = report["paper_level"]["by_gold_status"]
    answerable_agg = gold_status["answerable"]
    absent_agg = gold_status["known_absent"]
    questions = report.get("questions")
    if questions is None:
        raise SystemExit(
            "NB-D4: report has no per-question rows (was it written with --no-per-question?). "
            "The runner needs them for exact denominators; rerun without it."
        )

    answerable_rows = [q for q in questions if q.get("gold_paper_ids")]
    scored_text_rows = [
        q for q in questions
        if q.get("passage_level", {}).get("scored") and not q.get("vision_derived", False)
    ]
    absent_rows = [q for q in questions if not q.get("gold_paper_ids")]

    a_hits = sum(1 for q in answerable_rows if q["paper_level"]["rank"] is not None)
    a_n = len(answerable_rows)
    _cross_check(f"{name}.answerable.recall",
                 a_hits / a_n if a_n else 0.0, answerable_agg.get("recall_at_k"))
    _cross_check(f"{name}.answerable.n", float(a_n), float(answerable_agg.get("n", a_n)))

    p1_hits = sum(1 for q in scored_text_rows if q["passage_level"]["rank"] == 1)
    p1_n = len(scored_text_rows)
    vision_split = report["passage_level"].get("by_vision_status")
    published_rate = (
        vision_split.get("text_answerable", {}).get("rank_1_rate") if vision_split else None
    )
    _cross_check(f"{name}.block_p_at_1", p1_hits / p1_n if p1_n else 0.0, published_rate)

    absent_scores = absent_agg.get("top_score", {})

    return {
        "fixture": name,
        "ground_truth": ground_truth,
        "k": report["k"],
        "scoring_rule": report["scoring_rule"],
        "n_questions": report["n_questions"],
        "n_errors": report.get("n_errors", 0),
        "answerable": {
            "recall_at_k": answerable_agg.get("recall_at_k"),
            "mrr": answerable_agg.get("mrr"),
            "hits": a_hits,
            "n": a_n,
        },
        "block_p_at_1": {
            "rate": (p1_hits / p1_n) if p1_n else None,
            "hits": p1_hits,
            "n": p1_n,
            "definition": "text-answerable passage-scored items whose gold block ranks exactly 1",
        },
        "known_absent": {
            "n": len(absent_rows),
            "n_with_top_result": absent_agg.get("n_with_top_result"),
            "top_score_median": absent_scores.get("median"),
            "top_score_min": absent_scores.get("min"),
            "top_score_max": absent_scores.get("max"),
        },
    }


def build_combined(rows: list[dict], args: argparse.Namespace, raw_paths: dict[str, Path]) -> dict:
    """The dated combined artifact: run identity, both rows, the never-blend note, and where
    each raw per-fixture report lives."""
    return {
        "generated_by": "scripts/nb_eval_runner.py (NB-D4)",
        "date": args.date,
        "tag": args.tag,
        "k": args.k,
        "config": args.config,
        "collection": args.collection,
        "sparse_mode": args.sparse_mode,
        "dense_weight": args.dense_weight,
        "limit": args.limit,
        "never_blend_note": _NEVER_BLEND_NOTE,
        "combined_table": rows,
        "raw_reports": {name: str(path) for name, path in raw_paths.items()},
    }


def _frac(hits: int | None, n: int | None) -> str:
    if hits is None or not n:
        return "n/a"
    return f"{hits}/{n} = {hits / n:.4f}"


def render_markdown(combined: dict) -> str:
    """The short summary: one headline row per fixture + the separate absent-arm table."""
    lines = [
        "# Dual-fixture retrieval evaluation — NB-D4 runner",
        "",
        f"Date: **{combined['date']}**"
        + (f" · tag: **{combined['tag']}**" if combined["tag"] else ""),
        f"Config: `{combined['config']}` · collection: `{combined['collection']}`"
        f" · k={combined['k']} · sparse-mode: {combined['sparse_mode']}"
        + (
            f" · dense-weight: {combined['dense_weight']}"
            if combined["dense_weight"] is not None
            else ""
        ),
        "",
        "| fixture | R@10 (answerable) | MRR | block-P@1 |",
        "|---|---|---|---|",
    ]
    for row in combined["combined_table"]:
        a, bp = row["answerable"], row["block_p_at_1"]
        mrr = f"{a['mrr']:.4f}" if a["mrr"] is not None else "n/a"
        block = _frac(bp["hits"], bp["n"]) if bp["rate"] is not None else "n/a"
        lines.append(f"| {row['fixture']} | {_frac(a['hits'], a['n'])} | {mrr} | {block} |")
    lines += [
        "",
        "## Known-absent arm (reported separately — never blended)",
        "",
        "| fixture | n | with a top result | top-score median | range |",
        "|---|---|---|---|---|",
    ]
    for row in combined["combined_table"]:
        ka = row["known_absent"]
        med = ka["top_score_median"]
        rng = (
            f"[{ka['top_score_min']:.4f}, {ka['top_score_max']:.4f}]"
            if ka["top_score_min"] is not None
            else "n/a"
        )
        lines.append(
            f"| {row['fixture']} | {ka['n']} | {ka['n_with_top_result']} | "
            + (f"{med:.4f}" if med is not None else "n/a")
            + f" | {rng} |"
        )
    lines += [
        "",
        f"Notes: {combined['never_blend_note']}",
        "",
        "Per-fixture raw reports (verbatim `app/retrieval_eval.py` output): "
        + ", ".join(f"`{p}`" for p in combined["raw_reports"].values()),
        "",
    ]
    return "\n".join(lines)


def run_fixture(name: str, ground_truth: str, report_path: Path, args: argparse.Namespace) -> dict:
    """One fixture end-to-end: subprocess the reuse seam, then apply the silent-death guard."""
    cmd = fixture_argv(
        args.python_exe, args.runner_module, ground_truth, args.config, args.collection,
        args.k, report_path, args.sparse_mode, args.dense_weight, args.limit,
    )
    print(f"[nb-eval] {name}: {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(  # noqa: S603 -- fixed argv built here, no shell
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S
        )
    except subprocess.TimeoutExpired as e:
        raise SystemExit(f"NB-D4: {name} timed out after {_SUBPROCESS_TIMEOUT_S}s") from e
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-30:])
        raise SystemExit(f"NB-D4: {name} exited {proc.returncode}:\n{tail}")
    print(f"[nb-eval] {name}: exit 0, verifying report...", flush=True)
    return load_and_verify_report(report_path)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help="corpus config passed through to app.retrieval_eval "
                             "(default: the Waymo corpus both fixtures score against)")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION,
                        help="named vector-store collection (programme constraint 8: name it "
                             "explicitly on every Qdrant-touching command)")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--sparse-mode", choices=("fused", "dense_only", "sparse_only"),
                        default="fused")
    parser.add_argument("--dense-weight", type=float, default=None,
                        help="FUSE-style override pinning hybrid_dense_weight; forwarded")
    parser.add_argument("--limit", type=int, default=None,
                        help="score only the first N questions per fixture (smoke test)")
    parser.add_argument("--out-dir", type=Path, default=Path("docs/eval-reports/data"))
    parser.add_argument("--date", default=time.strftime("%Y-%m-%d"),
                        help="dating label for the output filenames (default: today)")
    parser.add_argument("--tag", default=None,
                        help="label suffix, e.g. SAMPLE -- appended to the output stem")
    parser.add_argument("--runner-module", default=DEFAULT_RUNNER_MODULE,
                        help="the reuse seam (overridable only for tests)")
    parser.add_argument("--python-exe", default=sys.executable,
                        help="interpreter for the per-fixture subprocess (default: this one)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print each fixture's command and exit without running anything")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    out_json, out_md, raw_dir = output_paths(args.out_dir, args.date, args.tag)

    if args.dry_run:
        for name, gt in FIXTURES:
            cmd = fixture_argv(
                args.python_exe, args.runner_module, gt, args.config, args.collection,
                args.k, raw_dir / f"{name}.json", args.sparse_mode, args.dense_weight,
                args.limit,
            )
            print(f"[dry-run] {name}: {' '.join(cmd)}")
        print(f"[dry-run] would write {out_json}, {out_md}, and {raw_dir}/")
        return 0

    raw_dir.mkdir(parents=True, exist_ok=True)
    rows, raw_paths = [], {}
    for name, gt in FIXTURES:
        report_path = raw_dir / f"{name}.json"
        report = run_fixture(name, gt, report_path, args)
        raw_paths[name] = report_path
        rows.append(extract_row(name, gt, report))

    combined = build_combined(rows, args, raw_paths)
    out_json.write_text(json.dumps(combined, indent=2))
    out_md.write_text(render_markdown(combined))
    print(f"[nb-eval] wrote {out_json}")
    print(f"[nb-eval] wrote {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
