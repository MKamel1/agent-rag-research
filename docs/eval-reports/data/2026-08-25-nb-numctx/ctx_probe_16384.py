#!/usr/bin/env python
"""NB-NUMCTX context-window probe -- verifies, under controlled sentinels, that the judge's
generation window can be raised from `num_ctx=8192` (app/judge_llm.py, silently truncating) to
16384 (the qwen3-14b-16k Modelfile's own default), and that the worst real item prompt evaluates
whole at the raised value. Stub committed BEFORE any measurement run; the transcript of record is
`ctx_probe_16384_results.json` beside this file once executed.

Run against the SAME server/model/request shape the 2026-08-25 re-run used (Ollama v0.31.2,
qwen3-14b-16k:latest, /api/generate, stream=false, think=false), from the worktree root. GpuLock
honored around every inference call (same lock, same label convention, as app/judge_llm.LlmJudge).
Read-only over repo data; writes nothing except stdout.

Sections:
  P0 model capability -- /api/show: the model tag's own context_length + parameters, so "the
                         model supports 16384" is read off the served artifact, not assumed
                         from its name.
  P1 calibration      -- chars->tokens ratio for this tokenizer (filler text).
  P2 old boundary     -- num_ctx=8192 reproduced TODAY on this server instance: one overshoot
                         point + sentinel pair (start-sentinel lost, end-sentinel kept), so the
                         round-1 finding is re-established against the live server rather than
                         inherited from ctx_probe_results.json.
  P3 new capacity     -- filler sweep at num_ctx=16384: prompt_eval_count must track input up to
                         ~15k true tokens (capacity honored); the cliff located above it; the
                         post-cliff retained tail sized; sentinel pair on both sides of the
                         cliff.
  P4 worst real item  -- Q-WAYB-011's reconstructed prompt VERBATIM (52,901 chars -- largest of
                         the 84 census items in docs/eval-reports/data/2026-08-25-nb-judge-rerun/
                         ctx_probe_results.json) re-sent at num_ctx=16384: prompt_eval_count must
                         land well above the 4,098-tail signature (full delivery).

PRE-COMMITTED acceptance criteria for the fix (frozen before this probe runs -- see the report
skeleton `docs/eval-reports/2026-08-25-nb-numctx-clean-delivery.md`):
  C1. P3 shows capacity honored to >=13,000 true tokens AND the cliff lands above the worst
      real item's estimated true count -> raise app/judge_llm.py `_NUM_CTX` to 16384.
  C2. The estimator shipped with the guard must be >= true tokens on EVERY known-full
      (chars -> prompt_eval_count) pair from the round-1 census (conservative direction only).
  C3. If either check fails, STOP -- document what was measured instead of shipping a raise the
      serving stack does not honor.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))  # worktree root

import httpx

from app.judge_eval import load_items
from app.judge_llm import _JUDGE_PROMPT, _format_passages
from rag.config import load_config
from rag.gpu_lock import FileGpuLock

URL = "http://localhost:11434"
MODEL = "qwen3-14b-16k:latest"
OLD_NUM_CTX = 8192   # app/judge_llm._NUM_CTX as shipped -- the value whose cliff is reproduced
NEW_NUM_CTX = 16384  # the candidate value under verification (Modelfile default per round-1 §7)
CODE_A = "ZEBRAPRINT9"  # placed at char 0
CODE_B = "MANGOVOLT6"   # placed in the final lines
FILLER = (
    "The retrieval pipeline stores parsed page blocks with anchors and returns them ranked by "
    "a hybrid of dense and sparse scores. "
)
WORST_ITEM_ARM = "answerable"   # Q-WAYB-011 lives here in the round-1 census
WORST_ITEM_ID = "Q-WAYB-011"


def main() -> None:
    client = httpx.Client(base_url=URL, timeout=900.0)
    cfg_path = Path("../research-system-rag-data/config.yaml")
    cfg = load_config(path=cfg_path if cfg_path.exists() else None)
    lock = FileGpuLock(Path(cfg.gpu_lock_path))
    results: dict = {
        "probe_date": time.strftime("%Y-%m-%d"),
        "server": {"url": URL, "model": MODEL},
    }

    def gen(prompt: str, num_ctx: int, num_predict: int, label: str) -> dict:
        body = {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {
                "num_ctx": num_ctx,
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
            "num_ctx": num_ctx,
            "input_chars": len(prompt),
            "prompt_eval_count": d.get("prompt_eval_count"),
            "response_head": d.get("response", "")[:120],
            "wall_s": round(time.time() - t0, 1),
        }
        print(json.dumps(out), flush=True)
        return out

    # P0 -- what does the SERVED model artifact say about its own context?
    show = client.post("/api/show", json={"model": MODEL}).json()
    results["P0_model_capability"] = {
        k: v
        for k, v in show.get("model_info", {}).items()
        if "context_length" in k or k == "num_ctx"
    } | {"parameters_head": (show.get("parameters") or "").splitlines()[:3]}
    print(json.dumps(results["P0_model_capability"]), flush=True)

    # P1 -- calibration
    cal_prompt = "Summarize in five words: " + FILLER * 10
    p1 = gen(cal_prompt, NEW_NUM_CTX, 16, "P1 calibration")
    results["P1_calibration"] = {
        "input_chars": p1["input_chars"],
        "prompt_eval_count": p1["prompt_eval_count"],
        "chars_per_token": round(p1["input_chars"] / p1["prompt_eval_count"], 3),
    }

    def sentinel_prompt(reps: int) -> str:
        return (
            f"Memorize this code word: {CODE_A}. It appears exactly once.\n\n"
            + FILLER * reps
            + f"\n\nFinal instruction: another code word appears here: {CODE_B}. "
            "Output ONLY the two code words given anywhere in this text, separated by a single "
            "space, nothing else."
        )

    # P2 -- reproduce the OLD 8192 cliff today (one overshoot point + sentinel pair)
    p2 = gen(sentinel_prompt(390), OLD_NUM_CTX, 32, "P2 old-cliff sentinel x390 @8192")
    results["P2_old_boundary_repro"] = p2 | {
        "A_present": CODE_A in p2["response_head"],
        "B_present": CODE_B in p2["response_head"],
    }

    # P3 -- capacity sweep at 16384: track up to ~15k true tokens, then find the cliff
    sweep = []
    for reps in (700, 760, 1000, 2400):  # ~15.4k / ~16.8k / ~22k / ~52k true tokens (P1 ratio)
        row = gen(FILLER * reps, NEW_NUM_CTX, 4, f"P3 filler x{reps} @16384")
        ratio = results["P1_calibration"]["chars_per_token"]
        sweep.append(row | {
            "estimated_true_tokens": round(row["input_chars"] / ratio),
        })
    results["P3_capacity_sweep_16384"] = sweep

    # Sentinel pair straddling the expected cliff (~x700 below, x1000 above)
    sentinels = []
    for reps in (700, 1000):
        out = gen(sentinel_prompt(reps), NEW_NUM_CTX, 32, f"P3 sentinel x{reps} @16384")
        sentinels.append(out | {
            "A_present": CODE_A in out["response_head"],
            "B_present": CODE_B in out["response_head"],
        })
    results["P3_sentinel_pair_16384"] = sentinels

    # P4 -- the worst real item prompt, verbatim, at the candidate value
    rubric_text = Path("docs/eval-rubrics/fabrication-audit-rubric.md").read_text()
    run_path = Path(f"fixtures/eval/runs/2026-08-23-waymo-generation-run.{WORST_ITEM_ARM}.json")
    items = {it.question_id: it for it in load_items(run_path)}
    it = items[WORST_ITEM_ID]
    p = _JUDGE_PROMPT.format(
        rubric=rubric_text,
        question=it.question_text,
        passages=_format_passages(it.passages),
        answer=it.answer,
    )
    p4 = gen(p, NEW_NUM_CTX, 4, f"P4 real-item {WORST_ITEM_ID} @16384")
    results["P4_worst_real_item"] = p4

    Path(__file__).with_name("ctx_probe_16384_results.json").write_text(
        json.dumps(results, indent=2)
    )
    print("\nwrote ctx_probe_16384_results.json", flush=True)


if __name__ == "__main__":
    main()
