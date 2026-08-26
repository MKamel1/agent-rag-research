#!/usr/bin/env python
"""NB-NUMCTX anomaly recheck: Q-WAYB-010 logged prompt_eval_count=8194 (the exact silent-
left-truncation tail signature) during the clean-delivery re-run, despite an estimate of 10,580
tokens from 37,029 chars -- which would require ~2.26 chars/token, far denser than anything in
either census (family floor 3.51). This script re-sends its reconstructed prompt verbatim, same
server/model/options as the run, N times, to distinguish 'genuinely oversized' from 'transient
server-side anomaly'. GpuLock honored. Run from the worktree root."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

import httpx

from app.judge_eval import load_items
from app.judge_llm import _JUDGE_MODEL, _NUM_CTX, _NUM_PREDICT, _format_passages
from rag.config import load_config
from rag.gpu_lock import FileGpuLock

URL = "http://localhost:11434"
ARM = "answerable"
QID = "Q-WAYB-010"


def main() -> None:
    client = httpx.Client(base_url=URL, timeout=900.0)
    cfg_path = Path("../research-system-rag-data/config.yaml")
    cfg = load_config(path=cfg_path if cfg_path.exists() else None)
    lock = FileGpuLock(Path(cfg.gpu_lock_path))

    rubric_text = Path("docs/eval-rubrics/fabrication-audit-rubric.md").read_text()
    items = {it.question_id: it for it in load_items(
        Path(f"fixtures/eval/runs/2026-08-23-waymo-generation-run.{ARM}.json"))}
    it = items[QID]
    prompt = (
        "{rubric}\n\nQUESTION:\n{question}\n\nPASSAGES:\n{passages}\n\nANSWER:\n{answer}\n\n"
        "Break the ANSWER above into its individual factual claims"
    ).format(rubric=rubric_text, question=it.question_text,
             passages=_format_passages(it.passages), answer=it.answer)

    results = []
    for attempt in (1, 2, 3):
        body = {
            "model": _JUDGE_MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {"num_ctx": _NUM_CTX, "num_predict": 4,
                        "temperature": 0.0, "seed": 42},
        }
        t0 = time.time()
        with lock.acquire("judge-probe"):
            resp = client.post("/api/generate", json=body)
            resp.raise_for_status()
        d = resp.json()
        row = {
            "attempt": attempt,
            "chars": len(prompt),
            "prompt_eval_count": d.get("prompt_eval_count"),
            "wall_s": round(time.time() - t0, 1),
        }
        print(json.dumps(row), flush=True)
        results.append(row)
        time.sleep(2)

    Path(__file__).with_name("qwayb010_recheck.json").write_text(json.dumps({
        "qid": QID, "arm": ARM, "model": _JUDGE_MODEL,
        "requested_num_ctx": _NUM_CTX, "requested_num_predict_in_run": _NUM_PREDICT,
        "attempts": results,
    }, indent=2))
    print("wrote qwayb010_recheck.json")


if __name__ == "__main__":
    main()
