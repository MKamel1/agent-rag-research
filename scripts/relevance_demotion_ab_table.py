"""RQ-3: one comparison table + pre-registered ADOPT/REJECT verdict per arm.

    python scripts/relevance_demotion_ab_table.py RUN_DIR      # RUN_DIR/<arm>/ written by run_relevance_demotion_ab.sh

Each arm dir holds: strata-focus.json, strata-papers.json, strata-papers-topic-{on,off}.json, strata-books.json
(from `eval_strata_report.py --json-out`) and the arm reports focus.json / papers.json / books.json. Arm
`baseline` is the comparator. The rule is the frozen protocol section 6 plus the books guard of the RQ-3 prereg
(`docs/eval-reports/2026-11-11-rq3-relevance-demotion-prereg.md`); counts are questions, never averaged across sets.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FLOOR = 0.04  # protocol section 6.1 floor clause: baseline focus contamination at or below this -> REJECT


def _only(path: Path) -> dict:
    return next(iter(json.loads(path.read_text()).values()))  # one report per strata file


def _hits(res: dict, dim: str | None = None) -> int:
    dims = res["per_dimension"]
    return sum(v["member_hit"]["hits"] for d, v in dims.items() if dim in (None, d))


def extract(arm: Path) -> dict:
    f, p = _only(arm / "strata-focus.json"), _only(arm / "strata-papers.json")
    po, pf = _only(arm / "strata-papers-topic-on.json"), _only(arm / "strata-papers-topic-off.json")
    b = _only(arm / "strata-books.json")
    fo = f["focus"]
    rows = [r for n in ("focus", "papers", "books") for r in json.loads((arm / f"{n}.json").read_text())["questions"]]
    return {
        "contam_focus": fo["on_gold_answerable"]["mean_off_share_topk"],
        "off_rank1_focus": fo["on_gold_answerable"]["off_at_rank1"]["hits"],
        "contam_papers": p["focus"]["on_gold_answerable"]["mean_off_share_topk"],
        "collision_hit": _hits(f, "collision"),
        "papers_on_hit": _hits(po), "papers_off_hit": _hits(pf), "books_hit": _hits(b),
        "legit_recall": f["per_dimension"]["offtopic-legit"]["paper_recall"]["hits"],
        "dist_outranks": fo["on_gold_answerable"]["distractor_outranks_gold"]["hits"],
        "lookalike_outranks": fo["offtopic_legit_lookalike_outranks_gold"]["hits"],
        "errors": sum(x["n_errored_rows"] for x in (f, p, po, pf, b)),
        "mean_results": sum(len(r["retrieved_paper_ids"]) for r in rows) / len(rows),
    }


def verdict(base: dict, arm: dict) -> tuple[str, list[str]]:
    drop = lambda k: base[k] - arm[k]  # noqa: E731  (questions lost vs baseline)
    rise = lambda k: arm[k] - base[k]  # noqa: E731
    checks = {
        "baseline focus contamination above floor 0.04": base["contam_focus"] > FLOOR,
        "focus contamination@10 <= 0.5 x baseline": arm["contam_focus"] <= 0.5 * base["contam_focus"],
        "papers-set contamination@10 does not rise": arm["contam_papers"] <= base["contam_papers"],
        "collision member hit drop <= 1": drop("collision_hit") <= 1,
        "papers on-topic member hit drop <= 1": drop("papers_on_hit") <= 1,
        "books member hit drop <= 1": drop("books_hit") <= 1,
        "offtopic-legit paper recall drop <= 1": drop("legit_recall") <= 1,
        "papers off-topic member hit drop <= 1": drop("papers_off_hit") <= 1,
        "distractor-outranks-gold rise <= 1": rise("dist_outranks") <= 1,
        "lookalike-outranks-gold rise <= 1": rise("lookalike_outranks") <= 1,
        "n_errors = 0": arm["errors"] == 0,
    }
    failed = [k for k, ok in checks.items() if not ok]
    return ("ADOPT-eligible" if not failed else "REJECT"), failed


def main(argv: list[str] | None = None) -> int:
    run = Path((argv or sys.argv[1:])[0])
    arms = {d.name: extract(d) for d in sorted(run.iterdir()) if (d / "strata-focus.json").exists()}
    base = arms.pop("baseline")
    cols = [("contam@10 focus", "contam_focus", ".3f"), ("off@rank1 focus", "off_rank1_focus", "d"),
            ("contam@10 papers", "contam_papers", ".3f"), ("collision hit/26", "collision_hit", "d"),
            ("papers-on hit/38", "papers_on_hit", "d"), ("papers-off hit/17", "papers_off_hit", "d"),
            ("books hit/74", "books_hit", "d"), ("legit recall/14", "legit_recall", "d"),
            ("dist>gold", "dist_outranks", "d"), ("lookalike>gold", "lookalike_outranks", "d"),
            ("errors", "errors", "d"), ("results/q", "mean_results", ".2f")]
    lines = ["| arm | " + " | ".join(c[0] for c in cols) + " | verdict |", "|---|" + "---|" * (len(cols) + 1)]
    notes = []
    for name, m in [("baseline", base), *arms.items()]:
        v, failed = ("(comparator)", []) if name == "baseline" else verdict(base, m)
        lines.append(f"| {name} | " + " | ".join(format(m[k], f) for _, k, f in cols) + f" | {v} |")
        if failed:
            notes.append(f"- {name}: fails {'; '.join(failed)}")
    print("\n".join(lines + ["", *notes]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
