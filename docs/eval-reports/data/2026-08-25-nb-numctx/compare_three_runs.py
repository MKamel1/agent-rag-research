#!/usr/bin/env python
"""Three-way fabrication-audit comparison for the NB-NUMCTX clean-delivery report. Read-only over
inputs; writes nothing except stdout.

Runs compared, per arm:
  R1  2026-08-23 provisional        rubric d82bbfa36155 (pre-amendment wording)
      fixtures/eval/runs/2026-08-23-waymo-fabrication-audit.{arm}.json
  R2  2026-08-25 qualified re-run   rubric 4add354fe464 delivered on only 38/84 items
                                    (docs/eval-reports/data/2026-08-25-nb-judge-rerun/)
  R3  2026-08-25 clean delivery     rubric 4add354fe464, harness _NUM_CTX=16384 + guard
      (this directory)

Same bounded lens as round 1: build_report retains only unsupported/contradicted claims, so
unchanged retained sets can still hide movement inside supported mass.
"""
from __future__ import annotations

import json
from pathlib import Path

R1 = Path("fixtures/eval/runs")
R2 = Path("docs/eval-reports/data/2026-08-25-nb-judge-rerun")
R3 = Path("docs/eval-reports/data/2026-08-25-nb-numctx")
NAME = {
    "R1": "2026-08-23-waymo-fabrication-audit.{arm}.json",
    "R2": "2026-08-25-waymo-fabrication-audit.{arm}.json",
    "R3": "2026-08-25-waymo-fabrication-audit.{arm}.json",
}

WRONG_SIDE = {  # hand classification from the provisional report §2 (input, not judge output)
    "invented": ["Q-WAYB-021", "Q-WAYB-022", "Q-WAYB-028"],
    "misattributed": ["Q-GTA-037", "Q-GTA-040", "Q-WAYB-035"],
}


def load(base: Path, key: str, arm: str) -> dict:
    return json.loads((base / NAME[key].format(arm=arm)).read_text())


def by_question(report: dict, channel: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in report[channel]:
        out[c["question_id"]] = out.get(c["question_id"], 0) + 1
    return out


for arm in ("absent", "answerable"):
    runs = {k: load(base, k, arm) for k, base in (("R1", R1), ("R2", R2), ("R3", R3))}
    print(f"### {arm.upper()} arm")
    print("  hashes     " + "  ".join(f"{k}={runs[k]['rubric_sha256_12']}" for k in runs))
    for k in runs:
        r = runs[k]
        print(
            f"  {k} items={r['n_items']:2d} errors={r['n_errors']} claims={r['n_claims']:3d} | "
            + " ".join(f"{v}={r['counts'][v]:3d} ({r['rates'][v]:.3f})" for v in
                       ("supported", "unsupported", "contradicted"))
        )
    # retained-set changes of the clean run vs each prior
    for prior in ("R1", "R2"):
        for ch in ("unsupported_claims", "contradicted_claims"):
            pq, cq = by_question(runs[prior], ch), by_question(runs["R3"], ch)
            changed = [q for q in sorted(set(pq) | set(cq)) if pq.get(q) != cq.get(q)]
            if changed:
                detail = ", ".join(f"{q}:{pq.get(q, 0)}->{cq.get(q, 0)}" for q in changed)
                print(f"  RETAINED vs {prior} [{ch}] ({len(changed)}): {detail}")
            else:
                print(f"  RETAINED vs {prior} [{ch}]: identical")
    lane = {q for qs in WRONG_SIDE.values() for q in qs}
    surfaced = {
        k: {c["question_id"] for c in runs[k]["unsupported_claims"]} & lane for k in runs
    }
    print("  wrong-side surfaced in unsupported_claims: "
          + "  ".join(f"{k}={sorted(v)}" for k, v in surfaced.items()))
    for mode, ids in WRONG_SIDE.items():
        row = "  ".join(
            f"{k}: {len(surfaced[k] & set(ids))}/{len(ids)} {sorted(surfaced[k] & set(ids))}"
            for k in runs
        )
        print(f"    {mode}: {row}")
    print()
