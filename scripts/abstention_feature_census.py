"""`python -m scripts.abstention_feature_census` -- NB-D3: does ANY observable quantity in the
stored 2026-08-23 waymo-priority run records separate known-absent questions from answerable
ones? The prior 0/24 finding (baseline report §3, programme plan §5) used fused top-score alone;
this census widens the feature set before anyone concludes "no signal exists".

INSTRUMENT ONLY: it decides nothing and adds no abstention anywhere. Its output feeds the A-1
design fork (signal -> threshold/calibration ticket; no signal -> new-signal-source design doc).

Data model: one record per question, built by joining THREE per-arm reports of the same fixture
(dense_only / fused / sparse_only) on question_id. A question is known-absent iff its gold_paper_ids
set is empty (the same partition `build_report`'s by_gold_status uses). Fixtures are NEVER pooled:
every statistic is computed per fixture and carries its own n.

Features censused offline (all derivable from stored per-question records):
  top_score_dense / _fused / _sparse   rank-1 score in each arm
  score_max_arms                       max of the three arms' rank-1 scores
  score_gap_dense_minus_sparse         dense rank-1 minus sparse rank-1 (arm-magnitude disagreement)
  arm_rank1_agreement                  # of pairwise equalities among arms' rank-1 papers (0..3)
  jaccard_fused_dense / _fused_sparse / _dense_sparse   |top-10 paper set intersection| / |union|
    distinct_papers_fused / _dense / _sparse             dedup count of each arm's top-10 paper list
    query_len_chars / _words             question_text length (joined from the eval fixtures)

EXCLUDED by construction: the stored records' `title_leak` flag. It is computed as "some retrieved
passage carries one of the question's GOLD papers' titles" -- for a known-absent question the gold
set is empty, so the flag is False for every absent item regardless of what was retrieved (measured:
0/14 and 0/12 True). It encodes the label, not retrieval behaviour; an AUROC on it (~0.09-0.11) is
leakage, not signal.


Two features from the ticket's candidate list are NOT computable offline -- stored records carry
only the rank-1 score, so "score gap rank1->rank2" and "count of results above a threshold" need
full score vectors; they are measured on this ticket's fresh confirmation runs instead (see
`--fresh-dir`, which adds them to the table when fresh-run JSONs are present).

Separation statistics per feature (absent = positive class):
  * AUROC via the Mann-Whitney U with tie handling (no external deps). <0.5 means the feature
    separates with absent items scoring LOWER; >0.5 means higher. 0.5 = coin flip.
  * Best-threshold FP/FN table: sweep every observed value as an "abstain if BELOW threshold"
    cut (orientation flipped automatically when the other direction does better), pick maximum
    Youden J. Reported as FP=a/n_answerable (false refusals) and FN=b/n_absent (missed
    detections), plus the threshold itself. An honest null here is a first-class outcome.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ARMS = ("dense_only", "fused", "sparse_only")
FIXTURES = ("ver84", "gt_wmr")


@dataclass(frozen=True)
class Item:
    """One question's observable quantities across all three arms. Absent iff no gold papers."""

    question_id: str
    absent: bool
    scores: dict[str, float]          # arm name -> rank-1 score
    top10_papers: dict[str, list[str]]  # arm name -> ordered top-10 paper ids (dupes preserved)
    title_leak: bool | None
    q_len_chars: int | None
    q_len_words: int | None


def load_items(data_dir: Path, fixtures_root: Path) -> dict[str, list[Item]]:
    """Join the three arm reports of each fixture on question_id.

    Raises if any arm file is missing or if the per-fixture question-id sets disagree across
    arms -- a silently half-joined census would carry wrong denominators, which is exactly what
    the ticket's "every cell carries n" rule exists to prevent.
    """
    fixtures: dict[str, list[Item]] = {}
    for fx in FIXTURES:
        rows_by_arm: dict[str, dict[str, dict]] = {}
        for arm in ARMS:
            path = data_dir / f"{fx}_{arm}.json"
            if not path.exists():
                raise FileNotFoundError(f"missing arm report: {path}")
            report = json.loads(path.read_text())
            rows_by_arm[arm] = {q["question_id"]: q for q in report["questions"]}
        id_sets = [set(rows) for rows in rows_by_arm.values()]
        if any(s != id_sets[0] for s in id_sets[1:]):
            raise ValueError(f"{fx}: question-id sets disagree across arms")

        text_by_id = _question_texts(fx, fixtures_root)
        items = []
        for qid, fused_row in rows_by_arm["fused"].items():
            gold = set(fused_row.get("gold_paper_ids") or [])
            items.append(
                Item(
                    question_id=qid,
                    absent=not gold,
                    scores={
                        arm: float(rows_by_arm[arm][qid]["top_score"])
                        for arm in ARMS
                        if rows_by_arm[arm][qid].get("top_score") is not None
                    },
                    top10_papers={
                        arm: list(rows_by_arm[arm][qid].get("retrieved_paper_ids") or [])
                        for arm in ARMS
                    },
                    title_leak=fused_row.get("title_leak"),
                    q_len_chars=(len(text_by_id[qid]) if qid in text_by_id else None),
                    q_len_words=(
                        len(text_by_id[qid].split()) if qid in text_by_id else None
                    ),
                )
            )
        n_absent = sum(1 for it in items if it.absent)
        logger.info("%s: %d items (%d answerable / %d known-absent)",
                    fx, len(items), len(items) - n_absent, n_absent)
        fixtures[fx] = items
    return fixtures


def _question_texts(fx: str, fixtures_root: Path) -> dict[str, str]:
    fixture_path = fixtures_root / (
        "waymo_gt_verified.json" if fx == "ver84" else "gt_wmr.json"
    )
    ground_truth = json.loads(fixture_path.read_text())["ground_truth"]
    return {row["question_id"]: row["question_text"] for row in ground_truth}


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------

FEATURE_NAMES = [
    "top_score_dense",
    "top_score_fused",
    "top_score_sparse",
    "score_max_arms",
    "score_gap_dense_minus_sparse",
    "arm_rank1_agreement",
    "jaccard_fused_dense",
    "jaccard_fused_sparse",
    "jaccard_dense_sparse",
    "distinct_papers_fused",
    "distinct_papers_dense",
    "distinct_papers_sparse",
    "query_len_chars",
    "query_len_words",
]

EXCLUDED_FEATURES = {
    "title_leak": (
        "leaky-by-construction for this comparison: the flag tests retrieved passages against the "
        "question's GOLD papers' titles, and a known-absent question has an empty gold set, so it "
        "is False for every absent item regardless of retrieval output (0/14 ver84, 0/12 gt_wmr). "
        "It encodes the label, not observable retrieval behaviour."
    ),
}

FRESH_FEATURE_NAMES = [
    "fresh_top_score",       # rank-1 score, shipped config, today
    "fresh_score_gap_r1_r2", # rank-1 minus rank-2 score (needs full vectors)
    "fresh_count_above_half_top",  # results scoring >= 50% of rank-1
]


def feature_value(item: Item, name: str) -> float | None:
    if name == "top_score_dense":
        return item.scores.get("dense_only")
    if name == "top_score_fused":
        return item.scores.get("fused")
    if name == "top_score_sparse":
        return item.scores.get("sparse_only")
    if name == "score_max_arms":
        vals = list(item.scores.values())
        return max(vals) if len(vals) == len(ARMS) else None
    if name == "score_gap_dense_minus_sparse":
        d, s = item.scores.get("dense_only"), item.scores.get("sparse_only")
        return d - s if d is not None and s is not None else None
    if name == "arm_rank1_agreement":
        r1 = {}
        for arm in ARMS:
            papers = item.top10_papers.get(arm) or []
            if papers:
                r1[arm] = papers[0]
        pairs = [("dense_only", "fused"), ("dense_only", "sparse_only"), ("fused", "sparse_only")]
        return float(sum(1 for a, b in pairs if r1.get(a) == r1.get(b)))
    if name.startswith("jaccard_"):
        arm_map = {"fused": "fused", "dense": "dense_only", "sparse": "sparse_only"}
        arm_a_name, arm_b_name = name.removeprefix("jaccard_").split("_")
        sa = set(item.top10_papers.get(arm_map[arm_a_name]) or [])
        sb = set(item.top10_papers.get(arm_map[arm_b_name]) or [])
        union = sa | sb
        return len(sa & sb) / len(union) if union else None
    if name.startswith("distinct_papers_"):
        arm = {"fused": "fused", "dense": "dense_only", "sparse": "sparse_only"}[
            name.removeprefix("distinct_papers_")
        ]
        papers = item.top10_papers.get(arm) or []
        return float(len(set(papers))) if papers else None
    if name == "title_leak":
        return None if item.title_leak is None else float(item.title_leak)
    if name == "query_len_chars":
        return float(item.q_len_chars) if item.q_len_chars is not None else None
    if name == "query_len_words":
        return float(item.q_len_words) if item.q_len_words is not None else None
    raise KeyError(name)


# ---------------------------------------------------------------------------
# separation statistics
# ---------------------------------------------------------------------------

def auroc(absent_vals: list[float], answerable_vals: list[float]) -> float:
    """P(absent draws higher than answerable), ties counting 0.5 -- Mann-Whitney U over ranks."""
    labeled = [(v, 1) for v in absent_vals] + [(v, 0) for v in answerable_vals]
    labeled.sort(key=lambda pair: pair[0])
    n = len(labeled)
    rank_sum_pos = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and labeled[j + 1][0] == labeled[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # 1-based average rank across the tie block
        for k in range(i, j + 1):
            if labeled[k][1] == 1:
                rank_sum_pos += avg_rank
        i = j + 1
    n1, n2 = len(absent_vals), len(answerable_vals)
    u1 = rank_sum_pos - n1 * (n1 + 1) / 2
    return u1 / (n1 * n2)


def best_threshold(
    absent_vals: list[float], answerable_vals: list[float]
) -> dict:
    """Sweep every observed value as a cut and report the max-Youden-J one.

    Rule semantics: ABSTAIN when the feature falls on the absent side of the threshold. The
    orientation is chosen from the data (abstain-below vs abstain-above), so the caller must read
    `rule` alongside the number. FP counts false refusals (answerable flagged); FN counts missed
    detections (absent not flagged).
    """
    best: dict | None = None
    for direction in ("below", "above"):
        candidates = sorted(set(absent_vals) | set(answerable_vals))
        cuts = [candidates[0] - 1e-9] + [
            (a + b) / 2 for a, b in zip(candidates, candidates[1:])
        ] + [candidates[-1] + 1e-9]
        for t in cuts:
            if direction == "below":
                flagged = lambda v: v < t  # noqa: E731
                rule = f"abstain if < {t:.6g}"
            else:
                flagged = lambda v: v > t  # noqa: E731
                rule = f"abstain if > {t:.6g}"
            fp = sum(1 for v in answerable_vals if flagged(v))
            fn = sum(1 for v in absent_vals if not flagged(v))
            tp = len(absent_vals) - fn
            tn = len(answerable_vals) - fp
            j = (tp / len(absent_vals)) - (fp / len(answerable_vals))
            if best is None or j > best["youden_j"]:
                best = {
                    "threshold": t,
                    "rule": rule,
                    "FP_false_refusals": fp,
                    "n_answerable": len(answerable_vals),
                    "FN_missed_absent": fn,
                    "n_absent": len(absent_vals),
                    "TP_detected_absent": tp,
                    "TN_correct_answerable": tn,
                    "youden_j": j,
                }
    assert best is not None  # loop always runs; keeps mypy honest about the return
    return best


def census_feature(items: list[Item], name: str) -> dict:
    values = [(feature_value(it, name), it.absent) for it in items]
    scored = [(v, a) for v, a in values if v is not None]
    absent_vals = [v for v, a in scored if a]
    answerable_vals = [v for v, a in scored if not a]
    result: dict = {
        "n_answerable": len(answerable_vals),
        "n_absent": len(absent_vals),
        "n_excluded_null": len(values) - len(scored),
    }
    if not absent_vals or not answerable_vals:
        result.update({"auroc": None, "note": "an arm has zero scored items"})
        return result
    au = auroc(absent_vals, answerable_vals)
    thr = best_threshold(absent_vals, answerable_vals)
    result.update({
        "auroc": round(au, 4),
        "auroc_direction": "absent higher" if au > 0.5 else "absent lower" if au < 0.5 else "none",
        **thr,
    })
    return result


def distribution(items: list[Item], name: str, absent: bool) -> dict:
    vals = [feature_value(it, name) for it in items if it.absent is absent]
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"n": 0}
    vals.sort()

    def quantile(q: float) -> float:
        idx = min(len(vals) - 1, max(0, round(q * (len(vals) - 1))))
        return vals[idx]

    mean = sum(vals) / len(vals)
    return {
        "n": len(vals),
        "mean": round(mean, 6),
        "min": vals[0],
        "p25": quantile(0.25),
        "median": vals[len(vals) // 2],
        "p75": quantile(0.75),
        "max": vals[-1],
    }


# ---------------------------------------------------------------------------
# fresh-run join (optional): full score vectors captured by exp_nb_d3_fresh_run.py
# ---------------------------------------------------------------------------

def load_fresh_records(fresh_dir: Path) -> dict[str, dict[str, dict]]:
    """fixture -> question_id -> {scores: [...]} from the fresh-run capture files."""
    out: dict[str, dict[str, dict]] = {}
    for fx in FIXTURES:
        path = fresh_dir / f"{fx}_fresh.json"
        if not path.exists():
            raise FileNotFoundError(f"missing fresh-run capture: {path}")
        out[fx] = {r["question_id"]: r for r in json.loads(path.read_text())["questions"]}
    return out


FRESH_FEATURE_FNS = {
    "fresh_top_score": lambda rec: rec["scores"][0],
    "fresh_score_gap_r1_r2": lambda rec: (
        rec["scores"][0] - rec["scores"][1] if len(rec["scores"]) > 1 else None
    ),
    "fresh_count_above_half_top": lambda rec: float(
        sum(1 for s in rec["scores"] if s >= 0.5 * rec["scores"][0])
    ),
}


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def run_census(data_dir: Path, fixtures_root: Path, fresh_dir: Path | None) -> dict:
    fixtures = load_items(data_dir, fixtures_root)
    fresh = load_fresh_records(fresh_dir) if fresh_dir else None

    report: dict = {
        "provenance": {
            "stored_runs_dir": str(data_dir),
            "fixtures_root": str(fixtures_root),
            "fresh_dir": str(fresh_dir) if fresh_dir else None,
            "refresh_post_rerank": (
                "distributions shift if retrieval changes; re-run before reusing thresholds "
                "against a changed stack"
            ),
        },
        "excluded_features": dict(EXCLUDED_FEATURES),
        "fixtures": {},
    }
    for fx, items in fixtures.items():
        names = list(FEATURE_NAMES) + (list(FRESH_FEATURE_NAMES) if fresh else [])
        fx_report: dict = {
            "arms": {},
            "features": {},
        }
        n_ans = sum(1 for it in items if not it.absent)
        n_abs = len(items) - n_ans
        fx_report["denominators"] = {
            "n_items": len(items), "n_answerable": n_ans, "n_absent": n_abs,
        }

        for arm_file, arm_label in (("dense_only", "dense"), ("fused", "fused"),
                                    ("sparse_only", "sparse")):
            fx_report["arms"][arm_label] = {
                "answerable_dist": distribution(items, f"top_score_{arm_label}", absent=False),
                "absent_dist": distribution(items, f"top_score_{arm_label}", absent=True),
            }

        for name in names:
            if fresh and name in FRESH_FEATURE_FNS:
                fx_report["features"][name] = _census_fresh_feature(
                    [(fresh[fx].get(it.question_id), it.absent) for it in items], name
                )
            else:
                fx_report["features"][name] = census_feature(items, name)
        report["fixtures"][fx] = fx_report
    return report


def _census_fresh_feature(records: list[tuple[dict | None, bool]], name: str) -> dict:
    """Same AUROC/threshold machinery, over fresh-record-derived values. A record of None means
    the question had no fresh capture; it is counted in `n_excluded_null`, never dropped silently.
    """
    fn = FRESH_FEATURE_FNS[name]
    pairs = [(fn(rec) if rec is not None else None, absent) for rec, absent in records]
    scored = [(v, a) for v, a in pairs if v is not None]
    absent_vals = [v for v, a in scored if a]
    answerable_vals = [v for v, a in scored if not a]
    result: dict = {
        "n_answerable": len(answerable_vals),
        "n_absent": len(absent_vals),
        "n_excluded_null": len(pairs) - len(scored),
    }
    if not absent_vals or not answerable_vals:
        result.update({"auroc": None})
        return result
    au = auroc(absent_vals, answerable_vals)
    result.update({
        "auroc": round(au, 4),
        "auroc_direction": "absent higher" if au > 0.5 else "absent lower" if au < 0.5 else "none",
        **best_threshold(absent_vals, answerable_vals),
    })
    return result


def print_markdown(report: dict) -> None:
    for fx, fx_report in report["fixtures"].items():
        d = fx_report["denominators"]
        print(f"\n### {fx} — n={d['n_items']} "
              f"({d['n_answerable']} answerable / {d['n_absent']} absent)\n")
        header = ("| feature | n_ans | n_abs | AUROC | direction | threshold rule"
                  " | FP (false refusals) | FN (missed absent) | Youden J |")
        print(header)
        print("|---|---|---|---|---|---|---|---|---|")
        for name, stats in fx_report["features"].items():
            if stats.get("auroc") is None:
                print(f"| {name} | {stats['n_answerable']} | {stats['n_absent']}"
                      " | — | — | — | — | — | — |")
                continue
            fp, fn = stats["FP_false_refusals"], stats["FN_missed_absent"]
            print(
                f"| {name} | {stats['n_answerable']} | {stats['n_absent']} | {stats['auroc']:.4f} "
                f"| {stats['auroc_direction']} | {stats['rule']} | {fp}/{stats['n_answerable']} "
                f"| {fn}/{stats['n_absent']} | {stats['youden_j']:.3f} |"
            )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path,
                        default=Path("docs/eval-reports/data/2026-08-23-waymo-priority"))
    parser.add_argument("--fixtures-root", type=Path, default=Path("fixtures/eval"))
    parser.add_argument("--fresh-dir", type=Path, default=None,
                        help="dir holding {ver84,gt_wmr}_fresh.json full-score-vector captures; "
                             "adds the fresh_* features to the census when given")
    parser.add_argument("--out", type=Path, default=None, help="write the JSON census here")
    args = parser.parse_args()

    report = run_census(args.data_dir, args.fixtures_root, args.fresh_dir)
    print_markdown(report)
    if args.out:
        args.out.write_text(json.dumps(report, indent=2))
        print(f"\nwrote JSON census to {args.out}")


if __name__ == "__main__":
    main()
