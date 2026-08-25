"""NB-X-P — deep-pool production tables (R0 rank 1): the standard dual-fixture table when the
reranker draws from deeper pools.

QUESTION (one): with the PRODUCTION retrieve→rerank pipeline (shipped BGE reranker,
w=0.7 FROZEN, config untouched), what do the standard retrieval numbers become at
K ∈ {10-baseline, 32, 64} — per fixture separately, answerable arm with denominators,
known-absent arm reported separately (never blended), plus the newcomer effect quantified:
how many previously-exposed gold blocks LOSE rank vs the K-baseline.

REUSE-FIRST — what is reused unchanged, and why this wrapper exists at all:

  * The measurement path is EXACTLY `scripts/nb_eval_runner.py`'s reuse seam: one
    `python -m app.retrieval_eval` subprocess per fixture per arm (`fixture_argv` builds the
    argv; `load_and_verify_report` is the silent-death guard; `extract_row` derives the
    published-aggregate row). Nothing here re-scores anything: every rate comes from
    `build_report`'s published aggregates via those imported functions.
  * Why the wrapper is new code anyway (nothing landed fits):
      - `nb_eval_runner.py` pins ONE k per invocation and stamps its own nb-d4 output stem;
        X-P needs three arms tied into one dated manifest under X-P-namespaced paths.
      - No landed script computes CROSS-ARM deltas: `nb_d1_pool_depth.py` tracks PREC-1's
        C1/C2 population membership across pool sizes, not per-item rank movement against a
        fresh same-run baseline, and not the full standard table.
    So the only new logic is orchestration (loop arms × fixtures, serialized) and arithmetic
    over committed per-question rows (top-10 restriction, newcomer categories) — both pure
    functions, unit-tested zero-GPU beside this file.

POOL MECHANICS being exercised (rag/retriever.py T-DOC24, verified in source): retrieve(q,
None, K) fetches max(K, rerank_depth) hybrid candidates, reranks the WHOLE pool, truncates to
K. With the frozen rerank_depth=32: K=10 → 32-candidate pool (the shipped shape); K=32 → the
SAME 32-candidate pool, untruncated ordering; K=64 → a genuinely deeper 64-candidate pool
where newcomers first appear. Consequence pinned as a hard guard below: the K=32 arm must
reproduce the baseline's per-question ranks exactly (same pool, deterministic pipeline — NB-D1
measured zero jitter across 256 repeated retrievals); any mismatch fails loudly instead of
shipping a phantom movement.

TWO READINGS of "the numbers at depth", both reported because they answer different questions:

  * serving-depth view — the runner's native aggregates at the arm's own k (R@32/R@64 …):
    what an agent asking for k results gets from a deeper served list.
  * top-10-restricted view — the standard metrics recomputed on each arm's OWN ordering
    truncated to its first 10: what the production top-10 becomes when drawn from a deeper
    pool. This is the reading R0's ranking question ("what does block-P@1 actually become at
    depth?") turns on, and where the newcomer hazard bites.

Ticket: docs/superpowers/plans/2026-08-24-next-build-programme.md §4 X-series X-P;
mandate docs/eval-reports/2026-08-25-nb-r0-fix-ranking.md rank 1.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# The reuse seam lives beside this file; import it rather than reimplementing any of it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nb_eval_runner import (  # noqa: E402 -- deliberate sibling import, see docstring
    DEFAULT_COLLECTION,
    DEFAULT_CONFIG,
    FIXTURES,
    extract_row,
    fixture_argv,
    load_and_verify_report,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_KS = (10, 32, 64)

_SUBPROCESS_TIMEOUT_S = 3600


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help="corpus config passed through unchanged (default: the Waymo corpus)")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION,
                        help="named vector-store collection (programme constraint 8)")
    parser.add_argument("--ks", type=int, nargs="+", default=list(DEFAULT_KS),
                        help="pool-depth arms; FIRST entry is the baseline the newcomer analysis "
                             "differs against (default: 10 32 64)")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("docs/eval-reports/data/2026-08-25-nb-xp"))
    parser.add_argument("--limit", type=int, default=None,
                        help="score only the first N questions per fixture (smoke test)")
    parser.add_argument("--python-exe", default=sys.executable,
                        help="interpreter for the per-fixture subprocess (default: this one)")
    parser.add_argument("--runner-module", default="app.retrieval_eval",
                        help="the reuse seam module (overridable only for tests)")
    parser.add_argument("--reuse-raw", action="store_true",
                        help="skip any fixture x k whose raw report already exists and verifies "
                             "(right k, n_questions > 0) -- lets the sweep be committed and "
                             "resumed one arm at a time without re-spending completed arms")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the planned per-arm commands and exit")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Pure aggregation over stored per-question rows (zero-GPU, unit-tested)
# ---------------------------------------------------------------------------

def _rows(report: dict) -> list[dict]:
    questions = report.get("questions")
    if questions is None:
        raise SystemExit(
            "NB-X-P: report has no per-question rows (--no-per-question?). The deep-pool "
            "analysis needs them; rerun without it."
        )
    return questions


def top10_restricted(report: dict) -> dict:
    """The standard metrics recomputed on THIS report's own ordering, truncated to 10.

    Paper-level R@10/MRR@10 over the answerable arm (same arm `extract_row` headlines);
    block-P@1 is rank-exactly-1 and therefore identical under truncation to the published
    VARM-1 text-arm rate, which is restated here rather than recomputed so there is only one
    authority for it. Every count carries its denominator.
    """
    rows = [q for q in _rows(report) if q.get("gold_paper_ids") and not q.get("error")]
    ranks10 = [
        q["paper_level"]["rank"] if (
            q["paper_level"]["rank"] is not None and q["paper_level"]["rank"] <= 10
        ) else None
        for q in rows
    ]
    hits = sum(1 for r in ranks10 if r is not None)
    rr_sum = sum(1.0 / r for r in ranks10 if r is not None)
    n = len(rows)
    bp = {
        "hits": sum(
            1 for q in rows
            if q.get("passage_level", {}).get("scored")
            and not q.get("vision_derived", False)
            and q["passage_level"]["rank"] == 1
        ),
        "n": sum(
            1 for q in rows
            if q.get("passage_level", {}).get("scored") and not q.get("vision_derived", False)
        ),
    }
    return {
        "recall_at_10": {"hits": hits, "n": n, "rate": (hits / n) if n else None},
        "mrr_at_10": (rr_sum / n) if n else None,
        "block_p_at_1": {
            **bp,
            "rate": (bp["hits"] / bp["n"]) if bp["n"] else None,
            "definition": "identical to the published VARM-1 text_answerable rank_1_rate "
                          "(rank 1 is inside any top-10); restated, not recomputed",
        },
    }


def newcomer_effect(baseline: dict, arm: dict) -> dict:
    """Cross-arm rank movement of GOLD BLOCKS and gold PAPERS vs the baseline run.

    Categories over items scored in BOTH runs without error (errored-in-either items are
    counted and listed, never silently dropped):

      * lost_rank            — previously exposed (baseline passage_rank not None), still
                               found, but deeper in the arm's list.
      * lost_from_top10      — was inside the baseline top-10, now beyond rank 10 OR gone.
      * gained_into_top10    — counterpart: outside the baseline top-10 (or unexposed),
                               inside the arm's top-10.
      * improved             — still found, strictly shallower than baseline.

    Same shape at paper level (gold-paper first-hit ranks), because R@k/MRR are paper-level
    metrics and newcomers can displace papers too. Identities travel so every count is
    auditable against the committed raw reports.
    """
    base_by_id = {q["question_id"]: q for q in _rows(baseline)}
    lost, lost10, gained10, improved, errored = [], [], [], [], []
    p_lost, p_improved = [], []
    for q in _rows(arm):
        b = base_by_id.get(q["question_id"])
        if b is None or q.get("error") or b.get("error"):
            errored.append(q["question_id"])
            continue
        br, ar = b["passage_level"]["rank"], q["passage_level"]["rank"]
        if br is not None and ar is not None and ar > br:
            lost.append({"question_id": q["question_id"], "baseline_rank": br, "arm_rank": ar})
        elif br is not None and ar is not None and ar < br:
            improved.append({"question_id": q["question_id"], "baseline_rank": br,
                             "arm_rank": ar})
        if br is not None and br <= 10 and (ar is None or ar > 10):
            lost10.append(q["question_id"])
        if (br is None or br > 10) and ar is not None and ar <= 10:
            gained10.append({"question_id": q["question_id"], "arm_rank": ar})
        bpr, apr = b["paper_level"]["rank"], q["paper_level"]["rank"]
        if bpr is not None and apr is not None and apr > bpr:
            p_lost.append({"question_id": q["question_id"], "baseline_rank": bpr,
                           "arm_rank": apr})
        elif bpr is not None and apr is not None and apr < bpr:
            p_improved.append({"question_id": q["question_id"], "baseline_rank": bpr,
                               "arm_rank": apr})
    return {
        "gold_block": {
            "lost_rank_count": len(lost),
            "lost_rank": lost,
            "lost_from_top10_ids": sorted(lost10),
            "gained_into_top10": gained10,
            "improved_count": len(improved),
            "improved": improved,
        },
        "gold_paper": {
            "lost_rank_count": len(p_lost),
            "lost_rank": p_lost,
            "improved_count": len(p_improved),
        },
        "errored_in_either_run": sorted(set(errored)),
        "note": "ranks are first-hit positions in each run's own returned list (1-based); "
                "'previously exposed' means the baseline run found the gold item at all.",
    }


def assert_deterministic_pair(baseline: dict, arm32: dict) -> None:
    """With rerank_depth=32 frozen, the K=32 arm draws the SAME hybrid pool as the K=10
    baseline (max(10,32) == max(32,32)) through a deterministic pipeline, so every
    per-question rank must match exactly. A mismatch means something moved mid-sweep
    (collection mutated, service change) — fail loudly, never publish phantom movements."""
    base_by_id = {q["question_id"]: q for q in _rows(baseline)}
    diffs = []
    for q in _rows(arm32):
        b = base_by_id.get(q["question_id"])
        if b is None:
            diffs.append(f"{q['question_id']}: missing from baseline run")
            continue
        for level in ("paper_level", "passage_level"):
            if b[level]["rank"] != q[level]["rank"]:
                diffs.append(
                    f"{q['question_id']}: {level} rank {b[level]['rank']!r} -> "
                    f"{q[level]['rank']!r}"
                )
        if bool(b.get("error")) != bool(q.get("error")):
            diffs.append(f"{q['question_id']}: error state differs ({b.get('error')!r} vs "
                         f"{q.get('error')!r})")
    if diffs:
        raise SystemExit(
            "NB-X-P: K=32 arm disagrees with the K=10 baseline on "
            f"{len(diffs)} per-question measurements (first few: {diffs[:5]}). With "
            "rerank_depth=32 both arms draw the identical candidate pool, so this is "
            "nondeterminism or a mutated store mid-sweep — investigate before publishing."
        )


# ---------------------------------------------------------------------------
# Orchestration (serialized: one retrieval process at a time, GPU modest-concurrency rule)
# ---------------------------------------------------------------------------

def load_reusable_report(report_path: Path, k: int) -> dict | None:
    """A previously-written raw report is reusable only if it verifies AND was produced at the
    requested k -- anything else (missing, unparseable, empty, wrong-k leftover) returns None
    and the caller re-runs that pair. Same silent-death posture as load_and_verify_report,
    applied to the resume path."""
    if not report_path.exists():
        return None
    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(report, dict) or report.get("n_questions", 0) <= 0:
        return None
    if report.get("k") != k:
        return None
    return report


def run_arm_fixture(k: int, name: str, ground_truth: str, report_path: Path,
                    args: argparse.Namespace) -> dict:
    if args.reuse_raw:
        reused = load_reusable_report(report_path, k)
        if reused is not None:
            print(f"[nb-xp] k={k} {name}: reusing verified {report_path}", flush=True)
            return reused
    cmd = fixture_argv(
        args.python_exe, args.runner_module, ground_truth, args.config, args.collection,
        k, report_path, "fused", None, args.limit,
    )
    print(f"[nb-xp] k={k} {name}: {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(  # noqa: S603 -- fixed argv built here, no shell
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S
        )
    except subprocess.TimeoutExpired as e:
        raise SystemExit(f"NB-X-P: k={k} {name} timed out after {_SUBPROCESS_TIMEOUT_S}s") from e
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-30:])
        raise SystemExit(f"NB-X-P: k={k} {name} exited {proc.returncode}:\n{tail}")
    print(f"[nb-xp] k={k} {name}: exit 0, verifying report...", flush=True)
    return load_and_verify_report(report_path)


def _frac(hits: int | None, n: int | None) -> str:
    if hits is None or not n:
        return "n/a"
    return f"{hits}/{n} = {hits / n:.4f}"


def render_markdown(combined: dict) -> str:
    lines = [
        "# Deep-pool production tables — NB-X-P",
        "",
        f"Config: `{combined['config']}` · collection: `{combined['collection']}` · "
        f"arms K={combined['ks']} (first = baseline) · generated "
        f"{combined['generated']}",
        "",
        "## Serving-depth view — runner-native aggregates at each arm's own k",
        "",
        "| fixture | K | answerable R@K | MRR@K | block-P@1 (text arm) | known-absent n |",
        "|---|---|---|---|---|---|",
    ]
    for row in combined["fixtures"]:
        for arm in row["arms"]:
            a, bp, ka = arm["row"]["answerable"], arm["row"]["block_p_at_1"], \
                arm["row"]["known_absent"]
            mrr = f"{a['mrr']:.4f}" if a["mrr"] is not None else "n/a"
            lines.append(
                f"| {row['fixture']} | {arm['k']} | {_frac(a['hits'], a['n'])} | {mrr} | "
                f"{_frac(bp['hits'], bp['n'])} | {ka['n']} |"
            )
    lines += [
        "",
        "## Top-10-restricted view — the production top-10 drawn from each depth",
        "",
        "| fixture | K | R@10 | MRR@10 | block-P@1 |",
        "|---|---|---|---|---|",
    ]
    for row in combined["fixtures"]:
        for arm in row["arms"]:
            t, bp = arm["top10_restricted"], arm["top10_restricted"]["block_p_at_1"]
            mrr = f"{t['mrr_at_10']:.4f}" if t["mrr_at_10"] is not None else "n/a"
            r10 = t["recall_at_10"]
            lines.append(
                f"| {row['fixture']} | {arm['k']} | {_frac(r10['hits'], r10['n'])} "
                f"| {mrr} | {_frac(bp['hits'], bp['n'])} |"
            )
    lines += [
        "",
        "## Newcomer effect vs baseline (gold-block first-hit ranks)",
        "",
        "| fixture | K | lost rank | of which fell out of top-10 | gained into top-10 | "
        "improved |",
        "|---|---|---|---|---|---|",
    ]
    for row in combined["fixtures"]:
        for arm in row["arms"]:
            if arm["k"] == combined["ks"][0]:
                continue
            gb = arm["newcomer"]["gold_block"]
            lines.append(
                f"| {row['fixture']} | {arm['k']} | {gb['lost_rank_count']} | "
                f"{len(gb['lost_from_top10_ids'])} | {len(gb['gained_into_top10'])} | "
                f"{gb['improved_count']} |"
            )
    lines += [
        "",
        "Known-absent arm never blended into any headline (BENCH-1); fixtures never averaged "
        "or compared across (PREC-1 §5).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ks = list(args.ks)
    baseline_k = ks[0]
    out_dir = args.out_dir
    raw_dir = out_dir / "raw"

    if args.dry_run:
        for k in ks:
            for name, gt in FIXTURES:
                cmd = fixture_argv(
                    args.python_exe, args.runner_module, gt, args.config, args.collection,
                    k, raw_dir / f"{name}.k{k}.json", "fused", None, args.limit,
                )
                print(f"[dry-run] {' '.join(cmd)}")
        print(f"[dry-run] would write {out_dir}/nb-xp-deeppool-tables.{{json,md}}")
        return 0

    raw_dir.mkdir(parents=True, exist_ok=True)

    # Serialized sweep: arm outer, fixture inner — exactly one retrieval process alive at a time.
    reports: dict[tuple[int, str], dict] = {}
    for k in ks:
        for name, gt in FIXTURES:
            report_path = raw_dir / f"{name}.k{k}.json"
            reports[(k, name)] = run_arm_fixture(k, name, gt, report_path, args)

    # Hard validity gate BEFORE anything is derived: same-pool arms must agree per question.
    # Applies whenever both arms of the pair are in THIS invocation (a baseline-only or
    # resumed single-arm run checks nothing here; the full-arm invocation re-checks on reuse).
    if baseline_k != 32 and 32 in ks:
        for name, _gt in FIXTURES:
            assert_deterministic_pair(reports[(baseline_k, name)], reports[(32, name)])

    fixtures_out = []
    for name, gt in FIXTURES:
        arms_out = []
        for k in ks:
            report = reports[(k, name)]
            row = extract_row(name, gt, report)
            arm = {
                "k": k,
                "row": row,
                "top10_restricted": top10_restricted(report),
                "raw_report": str(raw_dir / f"{name}.k{k}.json"),
            }
            if k != baseline_k:
                arm["newcomer"] = newcomer_effect(reports[(baseline_k, name)], report)
            arms_out.append(arm)
        fixtures_out.append({"fixture": name, "ground_truth": gt, "arms": arms_out})

    combined = {
        "ticket": "NB-X-P",
        "generated_by": "scripts/nb_xp_deeppool_tables.py",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "config": args.config,
        "collection": args.collection,
        "sparse_mode": "fused",
        "dense_weight_override": None,
        "limit": args.limit,
        "ks": ks,
        "baseline_k": baseline_k,
        "fixtures": fixtures_out,
    }
    out_json = out_dir / "nb-xp-deeppool-tables.json"
    out_md = out_dir / "nb-xp-deeppool-tables.md"
    out_json.write_text(json.dumps(combined, indent=2))
    out_md.write_text(render_markdown(combined))
    print(f"[nb-xp] wrote {out_json}")
    print(f"[nb-xp] wrote {out_md}")

    # Console summary mirrors the md tables so a run log alone carries the headline numbers.
    print(render_markdown(combined))
    return 0


if __name__ == "__main__":
    sys.exit(main())
