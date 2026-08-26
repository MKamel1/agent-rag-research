#!/usr/bin/env python
"""Extracts the per-item DELIVERY census for the NB-NUMCTX clean-delivery re-run from the run's own
transcript log (the INFO lines app/judge_llm emits per call since the fix), cross-checks every
prompt_eval_count against the truncation signatures measured by both probes (a count pinned at the
tail -- 4,098 under the old window, 8,194 under the new -- marks silent left-truncation), and
writes delivery_census.json beside this script. Run from the worktree root:

    conda run -n agent-rag-research python docs/eval-reports/data/2026-08-25-nb-numctx/delivery_census.py <run.log>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LINE_RE = re.compile(
    r"(?P<qid>Q-[A-Z]+-\d+): judge prompt_eval_count=(?P<count>\d+|None) "
    r"\(estimated (?P<est>\d+), window (?P<window>\d+)\)"
)
TAIL_SIGNATURES = {4098, 8194}


def main(log_path: str) -> None:
    entries: dict[str, dict] = {}
    for line in Path(log_path).read_text(errors="replace").splitlines():
        m = LINE_RE.search(line)
        if m:
            entries[m["qid"]] = {
                "prompt_eval_count": int(m["count"]) if m["count"] != "None" else None,
                "estimated": int(m["est"]),
                "window": int(m["window"]),
            }

    truncated = sorted(q for q, d in entries.items() if d["prompt_eval_count"] in TAIL_SIGNATURES)
    errored = sorted(q for q, d in entries.items() if d["prompt_eval_count"] is None)
    over_window = sorted(
        q for q, d in entries.items()
        if d["prompt_eval_count"] is not None and d["prompt_eval_count"] > d["window"]
    )
    census = {
        "source_log": str(log_path),
        "items_logged": len(entries),
        "truncated_signature": truncated,
        "no_telemetry_parse_errors": errored,
        "over_window": over_window,
        "per_item": entries,
    }
    print(json.dumps({k: v for k, v in census.items() if k != "per_item"}, indent=2))
    out = Path(__file__).with_name("delivery_census.json")
    out.write_text(json.dumps(census, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1])
