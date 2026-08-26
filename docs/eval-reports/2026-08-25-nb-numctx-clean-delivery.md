# Clean-delivery fabrication-audit re-run under a truncation-safe judge (NB-NUMCTX)

> **COMPLETED — delivery verified on all 84 items; the amended instrument's fabrication signal
> collapsed, and the question of record closed adversely.** This is the corrected re-run owed by
> `2026-08-25-nb-judge-rerun.md` §7 (NB-JUDGE-CTX): harness fixed (window raised to the served
> model artifact's declared 40,960 after the interim 16384 window was itself caught silently
> truncating one prompt; loud pre-send guard + per-call delivery telemetry added), both arms
> re-run under one unchanged procedure, full rubric delivery proven post-hoc for every item from
> the run's own transcript. Headline rates are therefore **comparable as amended-rubric rates**
> (`4add354fe464`) — and they say the instrument, not just its delivery, is the problem.

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

## Amendment A1 (2026-08-25, post-first-re-run): C1/C4 force the window past 16384

Frozen criteria stand; this amendment records what measurement did to them, in the open.

The first clean-delivery re-run at `_NUM_CTX=16384` completed both arms, but its own per-call
`prompt_eval_count` telemetry caught **Q-WAYB-010 logging the exact truncation signature (8,194 =
the measured half-window tail)**. Root-caused by direct measurement
(`data/2026-08-25-nb-numctx/qwayb010_recheck.json` + 24,576/40,960-window probes): its true count
is **17,452 tokens** — 37,029 chars at **2.12 chars/token**, far denser than every one of the 84
census prompts used for calibration (floor was 3.51). The round-1 validation set was censored
above 8,192 true tokens, so this density tail was structurally unobservable when C2 froze 3.5.
Under frozen C4, 83/84 delivery is not clean delivery, and re-running only the failed item under
a different window than its siblings would recreate the mixture defect this ticket exists to
kill.

Amended handling, applied before any headline number is quoted:

- `_NUM_CTX` moves to **40,960** — the served artifact's own declared capability
  (`qwen3.context_length`, read off `/api/show`; the Modelfile's `num_ctx 16384` is a config
  default, not a bound), empirically honored (Q-WAYB-010 evaluated whole at 17,452). This covers
  a hypothetical rerun of even the largest prompt (52,901 chars) at Q-WAYB-010's density, with
  the `num_predict` reserve intact.
- C3's guard stays as shipped (it refused nothing it should not have); its documented blind spot
  below ~3.5 chars/token is carried explicitly, and the binding delivery evidence is the
  per-call telemetry census (C4), which proved sufficient to catch this case live.
- Both arms are re-run end-to-end under the amended harness; no numbers cross windows.

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

### Final clean-delivery re-run (both arms, `_NUM_CTX=40960`, one unchanged procedure)

Artifacts: `data/2026-08-25-nb-numctx/2026-08-25-waymo-fabrication-audit.{absent,answerable}.json`
(rubric hash stamped `4add354fe464` in both, = `sha256sum` of the signed rubric). Delivery census:
`data/2026-08-25-nb-numctx/delivery_census.json` — **84/84 items carry a `prompt_eval_count`, zero
at any truncation signature, none over window** (max true count 11,793; median 8,541).

| arm | items (errors) | claims | supported | unsupported | contradicted |
|---|---|---|---|---|---|
| known-absent (16) | 16 (0) | 29 | 29 (**1.000**) | 0 (**0.000**) | 0 (0.000) |
| answerable (68) | 68 (**1**: Q-GTA-043, malformed judge JSON) | 262 | 245 (**0.935**) | 14 (**0.053**) | 3 (**0.011**) |

Three-run comparison (R1 = 08-23 provisional `d82bbfa36155`; R2 = 08-25 qualified mixture;
R3 = this run), re-derived by `data/2026-08-25-nb-numctx/compare_three_runs.py`:

| rate | R1 | R2 (38/84 delivered) | R3 (84/84 delivered) |
|---|---|---|---|
| absent unsupported | 8/28 (0.286) | 7/28 (0.250) | **0/29 (0.000)** |
| answerable unsupported | 51/245 (0.208) | 61/248 (0.246) | **14/262 (0.053)** |
| answerable contradicted | 3/245 (0.012) | 1/248 (0.004) | 3/262 (0.011) |

## Analysis

**1. The delivery fix is real and self-evidencing.** The failure that disqualified R2 cannot
recur unnoticed: every call now logs what the server actually evaluated, and the transcript is
the proof (this report's C4 check IS that census). The interim 16384 window's own re-run caught
Q-WAYB-010 live — the exact silent-starvation class this ticket set out to kill, detected within
the run instead of by a forensic reconstruction afterwards.

**2. Adverse headline: with delivery fixed, unsupported-flagging collapsed.** Absent-arm
unsupported went 0.286 → 0.250 → 0.000 across R1→R2→R3; answerable 0.208 → 0.246 → 0.053. The
known-absent arm's three INVENTED answers (Q-WAYB-021/022/028), flagged in both prior runs, are
now judged entirely "supported" against passages that do not contain them.

**3. Delivery status alone does not explain the movement — judge sampling variance does.** Items
with FULL delivery in both R2 and R3 still flipped wholesale (e.g. Q-GTA-001: 3 unsupported → 0;
Q-GTA-004: 6 → 0; Q-WAYB-036: 5 → 0), and one new catch appeared (Q-GTA-020: 0 → 1).
`LlmJudge` sets no `temperature`/`seed`, so every run samples at the server default (~0.8);
run-to-run movement of this magnitude means NO single-run fabrication rate — including the
08-23 provisional baseline — carries trend information without repeated sampling. The R2-era
reading ("truncated items inflated unsupported") survives only partially: churn is everywhere,
not concentrated in formerly-truncated items.

**4. Question of record (F-A2), answered adversely on clean tests.** Q-GTA-037 AND Q-GTA-040 —
the two misattributions F-A2 was written to surface — were both fully delivered the amended
rubric this time (R2 delivered only 037). Neither surfaced a single unsupported claim, in any
run. Q-WAYB-035's R1 catch stays lost. Across every clean test it has ever gotten, the amended
wording has surfaced none of the three wrong-side answers it was built to catch. "Wording is not
compliance" is no longer a caveat; it is the measured result.

**5. Error identities are now knowable** (a small but real instrument improvement): R1/R2
counted errors anonymously; R3's single error names itself in the transcript (Q-GTA-043, judge
emitted invalid JSON).

## Caveats

- Single sampling pass per item at server-default temperature: all rates above carry unquantified
  run variance (§Analysis 3). Treating any of them as a trend requires a seeded/repeated protocol.
- Generator and judge remain closely related models; hand classifications remain input, not
  output (unchanged from the provisional report).
- What even a perfect re-run cannot do (review §Q4, unchanged): this rubric is not the abstention
  signal; the generation prompt still has no refusal affordance.
- The first (interim-window) re-run's artifacts were superseded by the final run and deleted from
  `data/`; its delivery census survives only as the incident record in Amendment A1 and
  `qwayb010_recheck.json`.

## Verdict

NB-JUDGE-CTX's harness debt is paid: window sized to measured capability, guard + telemetry make
silent truncation impossible to miss, stale comments corrected, and the owed clean delivery is
delivered and proven. The measurement it bought is adverse twice over: the amended signed rubric
does not catch the wrong-side answers it was amended for, and single-pass judge rates move too
much between identical runs to support trend claims. Before the next fabrication-audit number is
treated as a measurement: pin judge sampling (`temperature`/`seed`) and repeat-sample. That is
new work, not this ticket.

## Status

- [x] Stub committed (criteria + probe design frozen)
- [x] Probe executed, C1 evaluated (capacity honored; worst item 10,878 tok whole)
- [x] Estimator validated offline against round-1 census (C2: 3.5 chars/token conservative)
- [x] Fix landed + tests green (C3)
- [x] Absent arm re-run + hash verified (`4add354fe464`)
- [x] Answerable arm re-run + hash verified (`4add354fe464`)
- [x] Per-item delivery census for the new run — **84/84 full delivery** (C4), after Amendment A1
      forced the window to 40,960 when the interim 16384 run itself caught Q-WAYB-010 truncating
- [x] Analysis written; headline comparability: quotable as amended-rubric rates, with the
      sampling-variance caveat of §Analysis 3 (C5 answered adversely — see §Analysis 4)
