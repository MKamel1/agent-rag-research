"""`python -m scripts.rerank_score_census` -- EV-13/EV-19: does the cross-encoder (reranker) score
separate answerable from absent queries?

Pre-registered in docs/eval-reports/2026-11-11-ev19-rerank-score-census-prereg.md (frozen feature
list, sets, verdict rule, non-goals). INSTRUMENT ONLY: decides nothing, ships no threshold.

Input per set: one or more `app.retrieval_eval --record-rerank-scores` reports plus the ground-truth
file each was run on (`--set NAME REPORT GT`, repeatable; the same NAME again adds another arm, e.g.
legacy = known-absent + eval_ground_truth + equation slice). A question is ABSENT iff its report row
has no gold paper ids (the same partition `build_report` uses); a GT `tests` field that disagrees
raises. The GT `dimension` splits absent into `absent` vs `partial-absent`.

Reused, not rewritten: `auroc` and `best_threshold` (scripts/abstention_feature_census.py, NB-D3),
`distribution_stats` (app/score_distribution_census.py, RI-M7), `load_questions` (question text and
gold ids, app/retrieval_eval.py). New here only: the seeded bootstrap CI, the Wilson interval and
the pre-registered verdict.

Direction: cross-encoder features are oriented "absent = LOWER" (AUROC below 0.5 = wrong way). The
comparison features (fusion top_score, question length in words) use max(A, 1-A): the conservative
comparison for the cross-encoder, and the right one for a leak control.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.retrieval_eval import load_questions  # noqa: E402
from app.score_distribution_census import distribution_stats  # noqa: E402
from scripts.abstention_feature_census import auroc, best_threshold  # noqa: E402

SEED = 20261111
REPS = 2000
RERANK_FEATURES = ("rerank_top1", "rerank_mean_top3", "rerank_margin_12", "rerank_pool_best")
PRIMARY = "rerank_top1"
FUSION = "fusion_top_score"
LENGTH = "query_words"
FEATURES = (*RERANK_FEATURES, FUSION, LENGTH)  # FROZEN (prereg section 3)
MIN_ABSENT_TO_QUALIFY = 9
CI_LOWER_BOUND_TO_BEAT = 0.70
SETS_NEEDED = 2


@dataclass(frozen=True)
class Item:
    question_id: str
    cls: str  # "answerable" | "absent" | "partial-absent"
    values: dict  # feature -> float | None

    @property
    def absent(self) -> bool:
        return self.cls != "answerable"


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for k/n (scripts/eval_protocol_tools.py only has the half-width)."""
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def load_items(report_path: Path, gt_path: Path) -> tuple[list[Item], int]:
    """Items of one (report, ground truth) arm, plus the count of errored rows excluded."""
    report = json.loads(report_path.read_text())
    if "questions" not in report:
        raise ValueError(f"{report_path}: no per-question rows")
    raw = {r["question_id"]: r for r in json.loads(gt_path.read_text())["ground_truth"]}
    text = {q.question_id: q.question_text for q in load_questions(gt_path)}
    items, errored = [], 0
    for row in report["questions"]:
        qid = row["question_id"]
        if row.get("error"):
            errored += 1
            continue
        if "rerank" not in row:
            raise ValueError(
                f"{report_path}: row {qid} has no 'rerank' field -- run with --record-rerank-scores"
            )
        absent = not row["gold_paper_ids"]
        tests = raw[qid].get("tests")
        if tests is not None and (tests != "answerable") != absent:
            raise ValueError(f"{qid}: GT tests={tests!r} disagrees with the report's gold ids")
        cls = "answerable"
        if absent:
            cls = "partial-absent" if raw[qid].get("dimension") == "partial-absent" else "absent"
        rr = row["rerank"]
        values = {
            "rerank_top1": rr.get("max"),
            "rerank_mean_top3": rr.get("mean_top3"),
            "rerank_margin_12": rr.get("margin_12"),
            "rerank_pool_best": rr.get("pool_best"),
            FUSION: row.get("top_score"),
            LENGTH: float(len(text[qid].split())),
        }
        items.append(Item(qid, cls, values))
    return items, errored


def _oriented(feature: str, values: list[float]) -> list[float]:
    return [-v for v in values] if feature in RERANK_FEATURES else values  # absent = lower


def _auroc(feature: str, absent: list[Item], answerable: list[Item]) -> float | None:
    a = [i.values[feature] for i in absent if i.values[feature] is not None]
    b = [i.values[feature] for i in answerable if i.values[feature] is not None]
    if not a or not b:
        return None
    return auroc(_oriented(feature, a), _oriented(feature, b))


def _agnostic(a: float | None) -> float | None:
    return None if a is None else max(a, 1 - a)


def _comparable(feature: str, a: float | None) -> float | None:
    return a if feature in RERANK_FEATURES else _agnostic(a)


def _percentile_ci(draws: list[float]) -> tuple[float, float] | None:
    if not draws:
        return None
    draws = sorted(draws)
    return (
        draws[int(0.025 * len(draws))],
        draws[min(len(draws) - 1, math.ceil(0.975 * len(draws)) - 1)],
    )


def bootstrap(
    absent: list[Item], answerable: list[Item], seed: int = SEED, reps: int = REPS
) -> dict:
    """Stratified, seeded percentile bootstrap: absent and answerable resampled separately; every
    feature is scored on the SAME resample so differences between features are paired."""
    rng = random.Random(seed)
    draws: dict[str, list[float]] = {f: [] for f in FEATURES}
    diffs: dict[str, list[float]] = {
        f"{f}-{c}": [] for f in RERANK_FEATURES for c in (FUSION, LENGTH)
    }
    for _ in range(reps):
        a = rng.choices(absent, k=len(absent))
        b = rng.choices(answerable, k=len(answerable))
        got = {f: _comparable(f, _auroc(f, a, b)) for f in FEATURES}
        for f, v in got.items():
            if v is not None:
                draws[f].append(v)
        for f in RERANK_FEATURES:
            for c in (FUSION, LENGTH):
                if got[f] is not None and got[c] is not None:
                    diffs[f"{f}-{c}"].append(got[f] - got[c])
    return {
        "auroc_ci": {f: _percentile_ci(d) for f, d in draws.items()},
        "diff_ci": {k: _percentile_ci(d) for k, d in diffs.items()},
    }


def analyse(absent: list[Item], answerable: list[Item]) -> dict:
    out: dict = {"n_absent": len(absent), "n_answerable": len(answerable), "features": {}}
    if not absent or not answerable:
        return out | {"note": "an arm is empty"}
    boot = bootstrap(absent, answerable)
    length_a = _comparable(LENGTH, _auroc(LENGTH, absent, answerable))
    for f in FEATURES:
        a_vals = [i.values[f] for i in absent if i.values[f] is not None]
        b_vals = [i.values[f] for i in answerable if i.values[f] is not None]
        entry: dict = {
            "n_absent": len(a_vals),
            "n_answerable": len(b_vals),
            "absent_dist": distribution_stats(a_vals),
            "answerable_dist": distribution_stats(b_vals),
        }
        a = _auroc(f, absent, answerable)
        entry["auroc_raw"] = a
        entry["auroc"] = _comparable(f, a)
        entry["auroc_ci95"] = boot["auroc_ci"][f]
        if a_vals and b_vals:
            thr = best_threshold(a_vals, b_vals)
            entry["best_threshold_in_sample"] = thr | {
                "false_abstention_wilson95": wilson_interval(
                    thr["FP_false_refusals"], thr["n_answerable"]
                ),
                "missed_absence_wilson95": wilson_interval(
                    thr["FN_missed_absent"], thr["n_absent"]
                ),
            }
        if f != LENGTH and entry["auroc"] is not None and length_a is not None:
            entry["no_better_than_length"] = entry["auroc"] <= length_a
        if f in RERANK_FEATURES:
            for c in (FUSION, LENGTH):
                entry[f"paired_diff_vs_{c}_ci95"] = boot["diff_ci"][f"{f}-{c}"]
        out["features"][f] = entry
    return out


def analyse_set(items: list[Item]) -> dict:
    answerable = [i for i in items if not i.absent]
    result = analyse([i for i in items if i.absent], answerable)
    classes = sorted({i.cls for i in items if i.absent})
    if len(classes) > 1:  # e.g. standards: absent vs partial-absent, same answerable arm
        result["by_absent_class"] = {
            c: analyse([i for i in items if i.cls == c], answerable) for c in classes
        }
    return result


def _passes(entry: dict, fusion: dict | None, length: dict | None) -> dict:
    ci = entry.get("auroc_ci95")
    a = entry.get("auroc")
    checks = {
        "ci_lower_gt_0.70": bool(ci and ci[0] > CI_LOWER_BOUND_TO_BEAT),
        "beats_fusion": bool(
            a is not None and fusion and fusion.get("auroc") is not None and a > fusion["auroc"]
        ),
        "beats_length": bool(
            a is not None and length and length.get("auroc") is not None and a > length["auroc"]
        ),
    }
    return checks | {"pass": all(checks.values())}


def verdict(results: dict[str, dict], secondary: set[str]) -> dict:
    """The pre-registered rule, mechanically (prereg section 5)."""
    qualifying = [
        s
        for s, r in results.items()
        if s not in secondary and r["n_absent"] >= MIN_ABSENT_TO_QUALIFY and r["features"]
    ]
    per_set, exploratory = {}, {}
    for s in qualifying:
        feats = results[s]["features"]
        per_set[s] = _passes(feats[PRIMARY], feats[FUSION], feats[LENGTH])
        for f in RERANK_FEATURES[1:]:
            exploratory.setdefault(f, {})[s] = _passes(feats[f], feats[FUSION], feats[LENGTH])[
                "pass"
            ]
    passing = [s for s, c in per_set.items() if c["pass"]]
    candidate = len(passing) >= SETS_NEEDED
    ci_has_half = [
        s
        for s in qualifying
        if (ci := results[s]["features"][PRIMARY]["auroc_ci95"]) and ci[0] <= 0.5 <= ci[1]
    ]
    return {
        "rule": (
            "CANDIDATE only if, on >= 2 sets with n_absent >= 9, rerank_top1's AUROC CI lower "
            "bound > 0.70 AND AUROC beats fusion top_score AND beats question length; "
            "otherwise NO SIGNAL at this sample size"
        ),
        "qualifying_sets": qualifying,
        "per_set": per_set,
        "passing_sets": passing,
        "verdict": "CANDIDATE" if candidate else "NO SIGNAL at this sample size",
        "fewer_than_two_qualifying_sets_supplied": len(qualifying) < SETS_NEEDED,
        "exploratory_features_pass_by_set_NOT_THE_VERDICT": exploratory,
        "descriptive_ticket_readouts": {
            "primary_ci_lower_gt_0.65_sets": [
                s
                for s in qualifying
                if (ci := results[s]["features"][PRIMARY]["auroc_ci95"]) and ci[0] > 0.65
            ],
            "primary_auroc_ge_0.85_sets": [
                s for s in qualifying if (results[s]["features"][PRIMARY]["auroc"] or 0) >= 0.85
            ],
            "primary_ci_contains_0.5_sets": ci_has_half,
        },
    }


def _fmt_ci(ci) -> str:
    return "n/a" if ci is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def _print_analysis(title: str, r: dict) -> None:
    print(f"\n### {title}  (n_absent={r['n_absent']}, n_answerable={r['n_answerable']})")
    if not r["features"]:
        print("  no analysis: an arm is empty")
        return
    print(
        "| feature | AUROC | 95% CI (bootstrap) | absent median | answerable median "
            "| best-threshold false-abstain (Wilson) | missed-absence (Wilson) | flag |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for f, e in r["features"].items():
        t = e.get("best_threshold_in_sample")
        med = lambda d: "n/a" if d["n"] == 0 else f"{d['median']:.3f}"  # noqa: E731
        a = e["auroc"]
        flag = "no better than length" if e.get("no_better_than_length") else ""
        print(
            f"| {f} | {'n/a' if a is None else f'{a:.3f}'} | {_fmt_ci(e['auroc_ci95'])} | "
            f"{med(e['absent_dist'])} | {med(e['answerable_dist'])} | "
            + (
                f"{t['FP_false_refusals']}/{t['n_answerable']} "
                f"{_fmt_ci(t['false_abstention_wilson95'])} | "
                f"{t['FN_missed_absent']}/{t['n_absent']} "
                f"{_fmt_ci(t['missed_absence_wilson95'])} ({t['rule']}, in-sample)"
                if t
                else "n/a | n/a"
            )
            + f" | {flag} |"
        )
    for c, sub in r.get("by_absent_class", {}).items():
        _print_analysis(f"  class {c}", sub)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--set", nargs=3, action="append", metavar=("NAME", "REPORT", "GT"), required=True
    )
    p.add_argument(
        "--secondary",
        action="append",
        default=[],
        help="set NAME that never counts toward the verdict",
    )
    p.add_argument("--no-pooled", action="store_true")
    p.add_argument("--json-out", default=None)
    args = p.parse_args()

    by_set: dict[str, list[Item]] = {}
    for name, report, gt in args.set:
        items, errored = load_items(Path(report), Path(gt))
        by_set.setdefault(name, []).extend(items)
        print(f"{name}: {report}: {len(items)} scored rows, {errored} errored rows excluded")
    results = {name: analyse_set(items) for name, items in by_set.items()}
    for name, r in results.items():
        _print_analysis(
            f"SET {name}" + (" (secondary, not in verdict)" if name in args.secondary else ""), r
        )
    out: dict = {"seed": SEED, "reps": REPS, "sets": results}
    if not args.no_pooled:
        pooled = [i for n, items in by_set.items() if n not in args.secondary for i in items]
        out["pooled_secondary"] = analyse_set(pooled)
        _print_analysis(
            "POOLED across sets -- SECONDARY ONLY (scores not comparable across corpora/depths)",
            out["pooled_secondary"],
        )
    out["verdict"] = verdict(results, set(args.secondary))
    print("\n## Verdict (pre-registered rule, per set, never pooled)")
    print(json.dumps(out["verdict"], indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
