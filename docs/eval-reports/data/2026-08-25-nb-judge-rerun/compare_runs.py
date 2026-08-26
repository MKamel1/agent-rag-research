#!/usr/bin/env python
"""Re-derives every cross-run comparison in `docs/eval-reports/2026-08-25-nb-judge-rerun.md` from
the committed audit JSONs. Read-only over inputs; writes nothing except stdout.

Inputs (all committed):
  OLD (2026-08-23, rubric d82bbfa36155):
    fixtures/eval/runs/2026-08-23-waymo-fabrication-audit.{absent,answerable}.json
  NEW (this re-run, amended rubric):
    docs/eval-reports/data/2026-08-25-nb-judge-rerun/2026-08-25-waymo-fabrication-audit.{absent,answerable}.json

The audits itemize only `unsupported_claims` / `contradicted_claims` (supported claims are not
retained by app/judge_eval.py::build_report), so verdict-change detection below is bounded the
same way the review was: an item whose retained sets are unchanged may still differ inside its
supported mass -- invisible to both runs' artifacts alike.
"""
from __future__ import annotations

import json
from pathlib import Path

OLD = Path("fixtures/eval/runs")
NEW = Path("docs/eval-reports/data/2026-08-25-nb-judge-rerun")
NAME = "2026-08-25-waymo-fabrication-audit.{arm}.json"
OLD_NAME = "2026-08-23-waymo-fabrication-audit.{arm}.json"

WRONG_SIDE = {  # hand classification from the provisional report §2 (input to Q2/Q3, not output)
    "invented": ["Q-WAYB-021", "Q-WAYB-022", "Q-WAYB-028"],
    "misattributed": ["Q-GTA-037", "Q-GTA-040", "Q-WAYB-035"],
}


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def by_question(report: dict, channel: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in report[channel]:
        out[c["question_id"]] = out.get(c["question_id"], 0) + 1
    return out


for arm in ("absent", "answerable"):
    old = load(OLD / OLD_NAME.format(arm=arm))
    new = load(NEW / NAME.format(arm=arm))
    print(f"### {arm.upper()} arm")
    print(f"  hash      old={old['rubric_sha256_12']}  new={new['rubric_sha256_12']}  "
          f"NON-COMPARABLE-BY-HASH={old['rubric_sha256_12'] != new['rubric_sha256_12']}")
    print(f"  denominators  old: n_items={old['n_items']} errors={old['n_errors']} "
          f"claims={old['n_claims']}   new: n_items={new['n_items']} errors={new['n_errors']} "
          f"claims={new['n_claims']}")
    for v in ("supported", "unsupported", "contradicted"):
        print(f"  {v:13s} old {old['counts'][v]:3d} ({old['rates'][v]:.3f})   "
              f"new {new['counts'][v]:3d} ({new['rates'][v]:.3f})")
    for ch in ("unsupported_claims", "contradicted_claims"):
        oq, nq = by_question(old, ch), by_question(new, ch)
        for qid in sorted(set(oq) | set(nq)):
            if oq.get(qid, 0) != nq.get(qid, 0):
                old_n, new_n = oq.get(qid, 0), nq.get(qid, 0)
                print(f"  RETAINED-SET CHANGE [{ch}] {qid}: old={old_n} new={new_n}")
    lane = {q for qs in WRONG_SIDE.values() for q in qs}
    surfaced_old = {c["question_id"] for c in old["unsupported_claims"]} & lane
    surfaced_new = {c["question_id"] for c in new["unsupported_claims"]} & lane
    print(f"  wrong-side items surfaced in unsupported_claims: old={sorted(surfaced_old)} "
          f"new={sorted(surfaced_new)}")
    for mode, ids in WRONG_SIDE.items():
        s_old = [i for i in ids if i in surfaced_old]
        s_new = [i for i in ids if i in surfaced_new]
        print(f"    {mode}: old surfaced {len(s_old)}/{len(ids)} {s_old} -> "
              f"new surfaced {len(s_new)}/{len(ids)} {s_new}")
    print()
