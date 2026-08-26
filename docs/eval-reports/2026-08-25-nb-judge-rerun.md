# Fabrication-audit judge re-run under the amended signed rubric (NB-JUDGE-RERUN)

> **COMPLETED — with a delivery defect that qualifies every number in it.** The re-run owed by
> Decision B ran to completion (0 transport-level surprises, parseable output on 81/84 calls),
> but post-run measurement (§3) shows the amended rubric was **never delivered to the judge on
> 46 of 84 items**: Ollama silently truncates oversized prompts from the FRONT, and the rubric
> sits at the front of the prompt. Headline rates below are therefore **NON-COMPARABLE-BY-HASH**
> *and* **NON-COMPARABLE-BY-DELIVERY** (a mixture of two different procedures). The question of
> record is answered for exactly one of its two named items; see §5.

## What this run is

The re-run owed by Decision B and recorded in the amended rubric's SIGNED OFF header: the
2026-08-23 fabrication audit ran under rubric hash `d82bbfa36155` (48-line wording); the rubric
was then amended (F-A1 split rule, F-A2 subject-binding, F-A3 several-passages — see
`docs/eval-rubrics/2026-08-24-fabrication-rubric-review.md`, applied+signed in commit `6d0b32b`).
By the reports' own rule, amending the text changes `rubric_sha256_12`, so one re-run is owed
under the new wording before any fabrication-audit number is treated as a trend. **This ticket is
that re-run — and the measurement that shows why it must be done once more.**

## Setup — mirrored from the provisional run for procedural comparability

| | |
|---|---|
| audited population | the SAME captured generation run: `fixtures/eval/runs/2026-08-23-waymo-generation-run.{answerable,absent}.json` (68 answerable / 16 known-absent records with their captured `answer_text` + retrieved `supporting_passages`) — no new generation |
| generation model / prompt | unchanged from 2026-08-23 (`qwen3:14b`, no-refusal-affordance prompt, verbatim in the provisional report) — only the JUDGE side re-runs |
| judge model | `qwen3-14b-16k:latest` via local Ollama v0.31.2 (`--judge-factory app.judge_llm:factory`, unmodified) |
| rubric | `docs/eval-rubrics/fabrication-audit-rubric.md` as committed on this branch — stamped hash `4add354fe464`, verified ≠ `d82bbfa36155` (file grew 2,688 → 5,350 bytes, +2,662 chars) |
| harness | `python -m app.judge_eval --ground-truth <arm JSON> --rubric docs/eval-rubrics/fabrication-audit-rubric.md --judge-factory app.judge_llm:factory` |
| GPU lock | shared cross-process lock honored |

## 1. Raw-artifact verification

Both files parse; populations mirror the 2026-08-23 provisional audits:

| arm | file | items old→new | errors old→new | claims old→new | rubric hash |
|---|---|---|---|---|---|
| absent | `data/…audit.absent.json` | 16 → 16 | 0 → 0 | 28 → 28 | `d82bbfa36155` → **`4add354fe464`** |
| answerable | `data/…audit.answerable.json` | 68 → 68 | 2 → 3 | 245 → 248 | `d82bbfa36155` → **`4add354fe464`** |

The stamp equals `sha256sum docs/eval-rubrics/fabrication-audit-rubric.md` as committed on this
branch, so the run was produced under exactly the amended signed wording — the instrument was
*shipped*; §3 measures how much of it *arrived*. Claim-total movement (245 → 248) is within normal
judge decomposition noise and cannot evidence F-A1 compliance either way (see §6). The +1 error is
counted by `build_report` but not attributed per item — identity unknowable from the artifacts.

## 2. Headline rates — NON-COMPARABLE-BY-HASH, NON-COMPARABLE-BY-DELIVERY

| arm | run | supported | unsupported | contradicted |
|---|---|---|---|---|
| known-absent (16 items) | 08-23 `d82bbfa36155` | 20/28 (0.714) | 8/28 (0.286) | 0 (0.000) |
| known-absent (16 items) | 08-25 `4add354fe464` | 21/28 (**0.750**) | 7/28 (**0.250**) | 0 (0.000) |
| answerable (68 items) | 08-23 `d82bbfa36155` | 191/245 (0.780) | 51/245 (0.208) | 3/245 (0.012) |
| answerable (68 items) | 08-25 `4add354fe464` | 186/248 (**0.750**) | 61/248 (**0.246**) | 1/248 (**0.004**) |

Same population ≠ same instrument (hash), **and** — per §3 — neither run's aggregate is even one
procedure: each new-run rate mixes 38 items judged under the delivered amended rubric with 46 items
judged by the model's prior notion of "supported/unsupported/contradicted" alone. **No number in
this table may be quoted as an amended-rubric rate, and none may be diffed against 08-23.**

## 3. The context-window finding (measured, not assumed)

The open measurement question, closed. Method: reconstruct every item's prompt verbatim
(`app.judge_eval.load_items` over the captured run + `app/judge_llm._JUDGE_PROMPT` with the amended
rubric), re-send it to the same server/model/options the run used, and read `prompt_eval_count`
from the API metadata — what the server actually evaluated. Saturation probes and sentinel words at
known positions characterize behavior; then all 84 real prompts are measured individually.
Transcript of record: `data/2026-08-25-nb-judge-rerun/ctx_probe_results.json`; reproducible via
`ctx_probe.py` beside it.

**How Ollama v0.31.2 behaved (all values measured):**

1. **The requested `num_ctx=8192` IS honored as capacity** — prompts whose true token count is
   ≤ 8,192 evaluate whole (largest observed true counts: filler 8,157; real item Q-GTA-003 at
   8,140).
2. **Past 8,192 tokens, truncation is silent and keeps only the FINAL 4,098 tokens**, regardless
   of overshoot (verified out to ~302K chars of input): no API error, no warning, response shape
   unchanged — downstream JSON parsing cannot detect it. Sentinel test: a code word in the final
   lines survives at every overshoot size; a code word at char 0 never does. Left-truncation,
   tail-keep.
3. **Consequence for this harness:** `_JUDGE_PROMPT` puts `{rubric}` FIRST. Any item whose prompt
   exceeds 8,192 tokens lost the entire rubric — not just F-A1/F-A2/F-A3, but the base verdict
   definitions themselves. The trailing instruction block ("give each one a verdict under the
   rubric above") sits after the answer and always survived, which is why outputs stayed parseable.

**Per-item census (84/84 measured individually):**

| arm | truncated (no rubric delivered) | full (amended rubric delivered) |
|---|---|---|
| absent | **12 / 16** | Q-WAYB-029 (6,078 tok), Q-GTA-037 (7,665), Q-GTA-038 (7,887), Q-WAYB-035 (8,007) |
| answerable | **34 / 68** | 34 items, 3,243–8,151 tok |
| total | **46 / 84** | 38 / 84 |

Real prompts run 15,352–52,901 chars (the captured generation run carries k=5 full retrieved
passages per item — not the short GT-fixture excerpts behind `app/judge_llm.py`'s "max 228 words"
comment, which does not transfer to this input and is now stale). Five full-delivery items sat
within ~190 tokens of the cliff (Q-WAYB-035 8,007 … Q-GTA-003 8,140).

**How this qualifies every downstream number:** each new-run headline rate is a 38/46 mixture of
two procedures; item-level verdicts are interpretable only relative to their exposure class
(`ctx_probe_results.json`, per item); the F-A1/F-A2/F-A3 wording was *tested* only on the 38
full-delivery items; anything observed on a truncated item is instructions-only judging and says
nothing about the amendments. Why the overflow window is 4,098 rather than the full requested
window is internal to this Ollama build (server env unreadable under systemd); reported as
measured behavior. The probe ran on the same server instance/version/model/options as the run
(server up since Aug 21; run earlier on Aug 25) — same-behavior inference is strong but stated as
an assumption.

## 4. Question of record: did F-A2 surface the wrong-side answers?

The review held sign-off hostage on F-A2 closing the misattribution blind spot, naming Q-GTA-037 /
Q-GTA-040 as the items that had sailed through clean. Checked exactly, **with exposure class** —
because a truncated item cannot testify about F-A2 at all:

| item | exposure | unsupported_claims 08-23 → 08-25 | reading |
|---|---|---|---|
| **Q-GTA-037** ("905 nm" misattribution) | **FULL** (7,665 tok — entire amended rubric incl. F-A2 delivered) | 0 → 0 | **No.** On its one clean test, F-A2 did NOT surface the wrong-side answer: the judge again retained nothing. Wording is not compliance — now measured, adversely, on the exact item the review built the case on. |
| **Q-GTA-040** (Swiss Re "underwriter") | **TRUNCATED** (zero rubric delivered) | 0 → 0 | **Untestable in this run.** Its result is instructions-only judging and carries zero information about F-A2. The question stays open for this item until a corrected re-run. |
| Q-WAYB-035 (Cruise "65%" misattribution) | **FULL** (8,007 tok) | **1 → 0** | **Regression.** The only absent-arm catch of a misattributed claim in the old run — rationale "The passage mentions a 65% reduction … for Waymo, not Cruise" — is GONE under the fully-delivered amended wording. |
| Q-WAYB-021 / 022 / 028 (invented) | TRUNCATED ×3 | 1 / 1 / 2 → identical sets | Stability across runs here reflects instructions-only judging twice, not amendment compliance. |

Net: across the three fully-delivered wrong-side-relevant items, the amended wording surfaced
nothing new and lost one prior catch. **The review's caveat "wording is not compliance" is no
longer hypothetical.**

## 5. F-A1 / F-A3 verdict-change scan

Bounded the same way the review was: `build_report` retains only `unsupported_claims` /
`contradicted_claims`, so an item whose retained sets are unchanged may still differ inside its
supported mass — invisible to both runs' artifacts alike. (`compare_runs.py` beside the data
re-derives everything below.)

- **F-A1 (compound split):** total claims moved 245 → 248 (+3), with the absent arm flat at 28 →
  28. No finer-splitting signature is detectable in retained artifacts, and 46 items never saw the
  clause. Unresolved by design of the artifact format, not by omission here.
- **F-A3 (multi-passage attribution/conflict scoping):** answerable `contradicted` fell 3 → 1.
  Both dropped claims sit on Q-WAYB-026 — a TRUNCATED item that never saw F-A3 — so the drop is
  procedure noise, not a scoping improvement. The survivor (Q-WAYB-020, "2,860 temporal sequences",
  full delivery) is present in both runs. Absent-arm `contradicted` stayed 0 → 0, so the review's
  caution stands verbatim: a zero rate here is as consistent with "conflicts were sought against
  the wrong passage" as with "none exist".
- **Retained-set changes, answerable `unsupported` (51 → 61):** twelve question ids changed count;
  **eleven of the twelve are truncated items** (Q-GTA-001/004/016/019/027/033, Q-WAYB-006/007/
  011/012/026) — churn under instructions-only judging. The single full-delivery change is
  Q-GTA-032 (6,160 tok), whose unsupported mass grew under the delivered amendments — direction
  consistent with F-A1/F-A2 tightening, n=1, not claimable.

## 6. Caveats

- **This run does not establish amended-rubric rates.** 46/84 items were judged without any
  rubric. A corrected re-run is owed (§7); until it lands, the newest valid fabrication-audit
  numbers remain the 08-23 provisional ones under `d82bbfa36155`.
- **Probe-vs-run assumption:** truncation behavior measured today is attributed to the run on the
  strength of identical server build, model, request options, and deterministic saturation shape —
  not from logs captured during the run itself.
- **Judge fallibility / self-evaluation bias:** unchanged from the provisional report — generator
  and judge are closely related models; the hand classification of the six wrong-side answers is
  input to §4, not output of the judge.
- **Error identities unknown:** `build_report` counts errors without attributing them (old 2, new
  3 on the answerable arm).
- **Supported mass invisible:** verdict-change detection is bounded to retained sets, both runs.
- **What even a perfect re-run cannot do** (review §Q4, unchanged): this rubric is not the
  abstention signal; the generation prompt still has no refusal affordance.

## 7. Verdict and owed follow-up

**The re-run is procedurally complete and evidentially insufficient.** It verified the pipeline end
to end under the signed wording and bought the measurement that explains itself. Recorded as
**NB-JUDGE-CTX** in `docs/BACKLOG.md`: fix the harness (per-item context sizing à la
`rag/summarizer.py`, or raise `_NUM_CTX` toward the Modelfile's own 16384 default, plus a loud
estimated-tokens-vs-window assertion so truncation can never again be silent), correct the stale
228-word safety comment in `app/judge_llm.py`, then re-run both arms. Code changes are
deliberately out of this ticket's scope.

## Artifacts & reproduction

- Raw audits (this ticket): `data/2026-08-25-nb-judge-rerun/2026-08-25-waymo-fabrication-audit.{absent,answerable}.json`
- Cross-run comparison: `python docs/eval-reports/data/2026-08-25-nb-judge-rerun/compare_runs.py` (read-only)
- Context probe: `python docs/eval-reports/data/2026-08-25-nb-judge-rerun/ctx_probe.py` (needs live Ollama + GPU lock)
- Probe transcript: `data/2026-08-25-nb-judge-rerun/ctx_probe_results.json`
- Prior runs: `fixtures/eval/runs/2026-08-23-waymo-fabrication-audit.*.json`,
  `docs/eval-reports/2026-08-23-waymo-fabrication-provisional.md`

## Status

- [x] Stub committed (e0bb89b)
- [x] Absent arm run + hash verified (`4add354fe464`)
- [x] Answerable arm run + hash verified (`4add354fe464`)
- [x] Context-window measurement closed (46/84 truncated; §3)
- [x] Analysis written (this document)
- [x] Corrected re-run under a truncation-safe harness (**delivered**: NB-NUMCTX /
      `2026-08-25-nb-numctx-clean-delivery.md` — window raised to the artifact-declared 40,960
      after the interim 16384 itself caught Q-WAYB-010 silently truncating; delivery proven 84/84
      from per-call telemetry; outcome adverse — unsupported rates collapsed and F-A2 surfaced
      neither target item on clean tests)
