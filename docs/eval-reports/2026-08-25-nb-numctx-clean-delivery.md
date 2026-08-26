# Clean-delivery fabrication-audit re-run under a truncation-safe judge (NB-NUMCTX)

> **STUB — pre-committed acceptance criteria, frozen before the measurement runs.** This is the
> corrected re-run owed by `2026-08-25-nb-judge-rerun.md` §7 (filed as NB-JUDGE-CTX, picked up as
> NB-NUMCTX): fix the harness's silent context-window truncation, then re-run both arms so that
> every item receives the full amended signed rubric. Numbers appear in this file only after the
> probe and the audit have actually run; until then every section below is a criterion or a
> placeholder marked as such.

## Pre-committed criteria (written before measurement — do not edit after)

1. **C1 — capacity before raise.** `ctx_probe_16384.py` must show, on today's live server:
   (a) the 8192 cliff reproduced with sentinels (start-sentinel lost past the cliff), and
   (b) at `num_ctx=16384` the server honors capacity well beyond the worst real item's estimated
   true token count (~12.6k for Q-WAYB-011 at 52,901 chars). Only then does `app/judge_llm.py`'s
   `_NUM_CTX` move 8192 → 16384. If the serving stack does not honor it: STOP and document.
2. **C2 — estimator conservative by construction.** The guard shipped with the fix estimates
   prompt tokens from chars; the constant must satisfy estimate ≥ true tokens on **every**
   known-full (chars → `prompt_eval_count`) pair in the round-1 census
   (`data/2026-08-25-nb-judge-rerun/ctx_probe_results.json`, 38 pairs). Checked offline, zero GPU.
3. **C3 — loud, not silent.** A prompt whose estimate exceeds the usable window
   (`_NUM_CTX − _NUM_PREDICT`) must fail that item loudly (`PermanentError` naming the question,
   before any POST) instead of silently losing the rubric. Pinned by zero-GPU mocked tests.
4. **C4 — full delivery or non-comparability, again.** The re-run headline rates are quotable as
   amended-rubric rates ONLY if all 84 items deliver the full rubric (per-item delivery verified).
   Any partial delivery keeps the NON-COMPARABLE-BY-DELIVERY banner and says so.
5. **C5 — question of record re-answerable.** Q-GTA-037 AND Q-GTA-040 both judged under verified
   full delivery this time; F-A2's wrong-side answers get their first clean test on both items.
   The Q-WAYB-035 regression observed in round 1 is re-checked under full delivery.

## Scope of the code change (frozen)

- `app/judge_llm.py` only: raise `_NUM_CTX`, add the loud estimate-vs-window guard, correct the
  stale "max 228 words" safety comment (its GT-fixture measurement does not transfer to the
  captured generation run's k=5 retrieved passages). No foundation paths (`contracts/`,
  `rag/config.py`) — if sizing belonged in `Config`, this ticket stops and documents instead.
- Not touched, deliberately: `rag/contextual_header.py` (its input is chunker-bounded ≤1,500
  words + a few-sentence summary — its own comment documents why 8192 covers it; different
  failure mode), `rag/summarizer.py` / `app/generation_capture.py` (already carry the measured
  16384 ceiling). One choke point per lessons §5.4: the single `_NUM_CTX`/guard pair through
  which every `LlmJudge` call flows.

## Results

### Probe (2026-08-25, live Ollama v0.31.2 / qwen3-14b-16k:latest) — C1 satisfied

Transcript of record: `data/2026-08-25-nb-numctx/ctx_probe_16384_results.json`.

| check | result |
|---|---|
| P0 served model artifact | `qwen3.context_length` = **40,960**; Modelfile `num_ctx 16384` — the raise is inside the model's own declared capability |
| P2 old cliff reproduced | at `num_ctx=8192`, a 49,371-char prompt evaluates to the **4,098-token tail**; start sentinel lost, end sentinel kept — round-1 behavior confirmed on today's server instance |
| P3 capacity @16384 | 15,417 true tokens evaluate WHOLE; past 16,384 true tokens truncation resumes silently with an **8,194-token tail** (window/2 — same mechanism shape as 8192's 4,098); sentinels: both survive below the cliff, only the end sentinel above |
| P4 worst real item | Q-WAYB-011 verbatim prompt (52,901 chars) at `num_ctx=16384`: `prompt_eval_count=`**10,878** — evaluated whole, valid claim JSON returned |

### Estimator calibration (offline, zero GPU) — C2 satisfied

Across the round-1 census's 38 known-full prompts, true tokens-per-char peaked at **0.285**
(Q-WAYB-008: 23,887 chars → 6,798 tokens = 3.51 chars/token). The shipped guard therefore divides
chars by **3.5** and rounds up (`math.ceil`) — verified ≥ true count on all 38 pairs, and ≤ usable
window (16,384 − 1,024 = 15,360) even for the largest census item (52,901 chars → estimate
15,315). Pinned by `test_estimator_never_underestimates_a_measured_true_count` /
`test_largest_measured_real_prompt_fits_the_usable_window`.

### Harness fix (C3 satisfied)

`app/judge_llm.py`: `_NUM_CTX` 8192 → 16384; pre-send guard refuses (PermanentError naming the
question, before any POST or GPU-lock acquisition) any prompt estimated over the usable window;
per-call `prompt_eval_count` telemetry logged after decode so every future run's transcript proves
delivery without a reconstruction probe; stale "max 228 words" comments corrected.

_(audit-arm results filled after both arms run — see Status)_

## Status

- [x] Stub committed (criteria + probe design frozen)
- [x] Probe executed, C1 evaluated (capacity honored; worst item 10,878 tok whole)
- [x] Estimator validated offline against round-1 census (C2: 3.5 chars/token conservative)
- [x] Fix landed + tests green (C3)
- [ ] Absent arm re-run + hash verified
- [ ] Answerable arm re-run + hash verified
- [ ] Per-item delivery census for the new run (C4/C5)
- [ ] Analysis written, headline comparability decided
