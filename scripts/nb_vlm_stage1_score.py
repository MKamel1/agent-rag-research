"""NB-VLM-PILOT Stage 1 scorer — mechanical asked-value fidelity computation.

Consumes (all produced before this script runs):
  - docs/eval-reports/data/2026-08-25-nb6-pilot/descriptions.jsonl   (blind VLM describes)
  - g03_audit.json                                                   (survivor set, O6/O7)
  - /tmp/opencode/nb6-judge/<key>/verdicts.json   (independent judge claim tables)

Writes stage1_scores.json next to the other artifacts. The asked-value groups below are copied
verbatim from the stub report's O1 table (frozen at stub commit 173fb96) -- nothing here is tuned
post-hoc. A group (one asked value) counts VERIFIED iff every pattern in it is stated in the blind
description AND covered by a judge claim whose verdict is CONFIRMED (O1/O2/O3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "docs/eval-reports/data/2026-08-25-nb6-pilot"
JUDGE_DIR = Path("/tmp/opencode/nb6-judge")

# O1 asked values, grouped exactly as the stub's n-counts dictate. Each group = 1 asked value;
# a group verifies iff ALL its patterns hold (stated + judge-CONFIRMED).
#   gating set (O7): the 4 survivors -> 3 + 1 + 2 + 2 = n=8
#   informational:   Q-GTA-044 (discounted by G0.3) -> 6 values, not in the gate denominator
GROUPS = [
    # --- Q-WAYB-027 (2208.12833 p35), survivor ---
    {"item": "Q-WAYB-027", "key": "2208.12833_p35", "gate": True,
     "label": 'pillar = "Monitoring"', "patterns": [r"\bmonitoring\b"], "numeric": False},
    {"item": "Q-WAYB-027", "key": "2208.12833_p35", "gate": True,
     "label": 'lifecycle phase = "While in Driver\'s Seat"',
     "patterns": [r"while in driver'?s seat"], "numeric": False},
    {"item": "Q-WAYB-027", "key": "2208.12833_p35", "gate": True,
     "label": 'implementation block = "RT Vigilance Assessment"',
     "patterns": [r"rt vigilance assessment"], "numeric": False},
    # --- Q-GTA-042 (2508.19425 p13), survivor ---
    {"item": "Q-GTA-042", "key": "2508.19425_p13", "gate": True,
     "label": 'vertical row-group label = "Crashed Passenger Vehicles (IPMM)"',
     "patterns": [r"crashed passenger vehicles", r"\bipmm\b"], "numeric": False},
    # --- Q-GTA-043 (2506.08228 p9), survivor: 2 asked values (one per law form) ---
    {"item": "Q-GTA-043", "key": "2506.08228_p9", "gate": True,
     "label": 'power-law-form constant = "-0.026"', "patterns": [r"-0\.026"], "numeric": True},
    {"item": "Q-GTA-043", "key": "2506.08228_p9", "gate": True,
     "label": 'power-law-plus-constant constants = "-0.18", "+1.03"',
     "patterns": [r"-0\.18", r"\+?1\.03"], "numeric": True},
    # --- Q-WMR-094 (2312.12675 p9), survivor ---
    {"item": "Q-WMR-094", "key": "2312.12675_p9", "gate": True,
     "label": "Any-Injury-Reported reduction, San Francisco = 86%",
     "patterns": [r"\b86\s*%"], "numeric": True},
    {"item": "Q-WMR-094", "key": "2312.12675_p9", "gate": True,
     "label": "Any-Injury-Reported reduction, All Locations/national = 54%",
     "patterns": [r"\b54\s*%"], "numeric": True},
    # --- Q-GTA-044 (2104.10133 p7), DISCOUNTED by G0.3 -> informational only ---
    *[{"item": "Q-GTA-044", "key": "2104.10133_p7", "gate": False,
       "label": f"panel value {tok}", "patterns": [re.escape(tok)], "numeric": True}
      for tok in ("99.29", "0.1849", "93.50", "0.1958", "87.31", "0.2738")],
]


def normalize(text: str) -> str:
    text = text.lower()
    for a, b in (("\u2212", "-"), ("\u2013", "-"), ("\u2014", "-"),
                 ("\u2009", " "), ("\u00a0", " ")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text)


def stated(norm_desc: str, pattern: str, numeric: bool) -> bool:
    pat = pattern if not numeric else r"(?<![\w.])" + pattern + r"(?![\w])"
    return re.search(pat, norm_desc) is not None


def load_jsonl(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["key"]] = rec
    return out


def main() -> None:
    descs = {k: normalize(v["description"])
             for k, v in load_jsonl(OUT_DIR / "descriptions.jsonl").items()}
    g03 = json.loads((OUT_DIR / "g03_audit.json").read_text())

    results = []
    for g in GROUPS:
        desc = descs[g["key"]]
        st = [stated(desc, p, g["numeric"]) for p in g["patterns"]]
        # judge coverage: any CONFIRMED claim containing every pattern of the group
        vpath = JUDGE_DIR / g["key"] / "verdicts.json"
        claims = json.loads(vpath.read_text()) if vpath.exists() else []
        best, ev = "NO_JUDGE_FILE", ""
        for c in claims:
            cn = normalize(c["claim"])
            hits = [re.search(p if not g["numeric"]
                              else r"(?<![\w.])" + p + r"(?![\w])", cn) is not None
                    for p in g["patterns"]]
            if not all(hits):
                continue
            rank = {"CONFIRMED": 3, "UNVERIFIABLE": 2, "REFUTED": 1}.get(c["verdict"], 0)
            cur = {"CONFIRMED": 3, "UNVERIFIABLE": 2, "REFUTED": 1, "NO_JUDGE_FILE": 0}[best]
            if rank > cur:
                best, ev = c["verdict"], c.get("evidence", "")
        results.append({**{k: g[k] for k in ("item", "key", "label", "gate")},
                        "stated_all_patterns": all(st),
                        "judge_best": best, "judge_evidence": ev,
                        "verified": all(st) and best == "CONFIRMED"})

    def tally(rows: list[dict]) -> dict:
        k = sum(r["verified"] for r in rows)
        return {"n": len(rows), "k_verified": k, "fidelity_pct": round(100 * k / len(rows), 1),
                "not_itemized_by_judge": sum(r["judge_best"] == "NO_JUDGE_FILE" for r in rows)}

    gating = tally([r for r in results if r["gate"]])
    info = tally([r for r in results if not r["gate"]])

    # spot-check precision over the 10 seeded spot pages (any key with a judge file outside gold)
    gold_keys = {g["key"] for g in GROUPS}
    conf = ref = unver = 0
    per_page = {}
    for vd in sorted(JUDGE_DIR.glob("*/verdicts.json")):
        key = vd.parent.name
        if key in gold_keys:
            continue
        claims = json.loads(vd.read_text())
        c = sum(x["verdict"] == "CONFIRMED" for x in claims)
        r = sum(x["verdict"] == "REFUTED" for x in claims)
        u = sum(x["verdict"] == "UNVERIFIABLE" for x in claims)
        per_page[key] = {"claims": len(claims), "confirmed": c, "refuted": r, "unverifiable": u}
        conf += c
        ref += r
        unver += u
    spot = {"pages_judged": len(per_page), "confirmed": conf, "refuted": ref,
            "unverifiable": unver,
            "precision_pct": round(100 * conf / max(conf + ref, 1), 1),
            "per_page": per_page}

    out = {
        "rule": "group verified iff all patterns stated in blind description AND covered by a "
                "judge CONFIRMED claim (O1/O2/O3); gate denominator = survivors' n=8 (O7)",
        "g03_survivors": g03["survivors"],
        "gating_stage1": gating,
        "informational_qgta044": info,
        "spot_check_precision": spot,
        "per_value": results,
    }
    (OUT_DIR / "stage1_scores.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({"gating": gating, "informational_qgta044": info,
                      "spot": {k: v for k, v in spot.items() if k != "per_page"}}, indent=1))
    for r in results:
        flag = "HIT " if r["verified"] else "MISS"
        print(f"{flag} [{r['item']}] {r['label']} stated={r['stated_all_patterns']} "
              f"judge={r['judge_best']}")


if __name__ == "__main__":
    main()
