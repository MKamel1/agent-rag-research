#!/usr/bin/env python
"""NB-JUDGE-RERUN context-window probe -- closes the ticket's open measurement question: did
the judge SEE the amended rubric, given `_NUM_CTX = 8192` (app/judge_llm.py) and prompt lengths
far above the ~500-word assumption in that file's comment?

Run against the SAME server/model/request shape the re-run used (Ollama v0.31.2,
qwen3-14b-16k:latest, /api/generate with options num_ctx=8192, stream=false, think=false), so its
numbers describe the run's own conditions. Executed 2026-08-25 in two rounds; the committed
`ctx_probe_results.json` beside this file is the transcript of record.

Sections:
  P1 calibration       -- chars->tokens ratio for this tokenizer (filler text).
  P2 real items        -- re-send reconstructed prompts for selected items
                          (app.judge_eval.load_items + app.judge_llm formatting VERBATIM); read
                          `prompt_eval_count` metadata.
  P3 saturation sweep  -- filler at increasing sizes; find where prompt_eval_count stops tracking
                          input.
  P4 sentinel sides    -- CODE_A at char 0, CODE_B in the final lines; which survives overflow
                          names the kept side.
  P5 census            -- ALL 84 item prompts measured individually -> per-item FULL/TRUNCATED.

GpuLock honored around every inference call (same lock, same label convention, as
app/judge_llm.LlmJudge). Read-only over repo data; writes nothing except stdout.

KEY RESULT (see ctx_probe_results.json): prompts whose true token count <= 8192 are evaluated in
full (`num_ctx` IS honored); prompts beyond 8192 tokens are SILENTLY truncated to their FINAL
4,098 tokens (leading content discarded, no API error). The rubric sits FIRST in _JUDGE_PROMPT,
so every truncated item was judged with no rubric text at all -- not merely without F-A1/F-A2/F-A3.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # worktree root

import httpx

from app.judge_eval import load_items
from app.judge_llm import _JUDGE_PROMPT, _format_passages
from rag.config import load_config
from rag.gpu_lock import FileGpuLock

URL = "http://localhost:11434"
MODEL = "qwen3-14b-16k:latest"
NUM_CTX = 8192  # app/judge_llm._NUM_CTX -- the value under measurement
CODE_A = "ZEBRAPRINT9"  # placed at char 0
CODE_B = "MANGOVOLT6"   # placed in the final lines
FILLER = (
    "The retrieval pipeline stores parsed page blocks with anchors and returns them ranked by "
    "a hybrid of dense and sparse scores. "
)


def main() -> None:
    client = httpx.Client(base_url=URL, timeout=900.0)
    cfg_path = Path("../research-system-rag-data/config.yaml")
    cfg = load_config(path=cfg_path if cfg_path.exists() else None)
    lock = FileGpuLock(Path(cfg.gpu_lock_path))

    def gen(prompt: str, num_predict: int, label: str) -> dict:
        body = {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {
                "num_ctx": NUM_CTX,
                "num_predict": num_predict,
                "temperature": 0.0,
                "seed": 42,
            },
        }
        t0 = time.time()
        with lock.acquire("judge-probe"):
            resp = client.post("/api/generate", json=body)
            resp.raise_for_status()
        d = resp.json()
        out = {
            "label": label,
            "input_chars": len(prompt),
            "prompt_eval_count": d.get("prompt_eval_count"),
            "response_head": d.get("response", "")[:120],
            "wall_s": round(time.time() - t0, 1),
        }
        print(json.dumps(out), flush=True)
        return out

    # P1 -- calibration
    cal_prompt = "Summarize in five words: " + FILLER * 10
    p1 = gen(cal_prompt, num_predict=16, label="P1 calibration")
    print(f"P1 chars/token ~= {len(cal_prompt) / p1['prompt_eval_count']:.3f}\n")

    # P3 -- saturation sweep (before P2 here so a fresh reader sees the shape early)
    for reps in (100, 300, 370, 390, 600, 1000, 2400):
        gen(FILLER * reps, num_predict=4, label=f"P3 filler x{reps}")

    # P4 -- sentinel side test (near-threshold and deep-overshoot sizes)
    for reps in (370, 500, 2400):
        prompt = (
            f"Memorize this code word: {CODE_A}. It appears exactly once.\n\n"
            + FILLER * reps
            + f"\n\nFinal instruction: another code word appears here: {CODE_B}. "
            "Output ONLY the two code words given anywhere in this text, separated by a single "
            "space, nothing else."
        )
        out = gen(prompt, num_predict=32, label=f"P4 sentinel x{reps}")
        print(
            f"   A_present={CODE_A in out['response_head']}  "
            f"B_present={CODE_B in out['response_head']}",
            flush=True,
        )

    # P2/P5 -- every real item prompt, individually measured
    rubric_text = Path("docs/eval-rubrics/fabrication-audit-rubric.md").read_text()
    census: dict[str, dict[str, dict]] = {}
    for arm in ("absent", "answerable"):
        items = load_items(Path(f"fixtures/eval/runs/2026-08-23-waymo-generation-run.{arm}.json"))
        for it in items:
            p = _JUDGE_PROMPT.format(
                rubric=rubric_text,
                question=it.question_text,
                passages=_format_passages(it.passages),
                answer=it.answer,
            )
            out = gen(p, num_predict=4, label=f"P5 {arm}/{it.question_id}")
            census.setdefault(arm, {})[it.question_id] = {
                "chars": out["input_chars"],
                "prompt_eval_count": out["prompt_eval_count"],
            }

    truncated = sum(
        1 for a in census for d in census[a].values() if d["prompt_eval_count"] == 4098
    )
    print(f"\nP5 census: {truncated}/84 items truncated to the 4098-token tail")

    # mechanism color (may be unavailable under systemd -- failure is fine, recorded as such)
    try:
        show = client.post("/api/show", json={"model": MODEL}).json()
        info = {
            k: v
            for k, v in show.get("model_info", {}).items()
            if "context_length" in k or k == "num_ctx"
        }
        print("api/show context-related:", json.dumps(info))
        print("api/show parameters:", (show.get("parameters") or "").splitlines()[:2])
    except Exception as error:  # noqa: BLE001 -- diagnostic only
        print("api/show unavailable:", error)
    try:
        env = subprocess.run(  # noqa: S603,S607
            ["bash", "-lc",
             "tr '\\0' '\\n' < /proc/$(pgrep -f 'ollama serve' | head -1)/environ "
             "| grep -iE 'ctx|context' || echo unreachable"],
            capture_output=True, text=True, timeout=15,
        )
        print("server env:", env.stdout.strip() or "unreachable")
    except Exception as error:  # noqa: BLE001 -- diagnostic only
        print("server env unreadable:", error)


if __name__ == "__main__":
    main()
