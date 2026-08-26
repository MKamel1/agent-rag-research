# NB-VLM-PILOT — bounded VLM falsification pilot (Stage 0 gates + Stage 1 fidelity)

**Status: CLOSED — Stage 1 fidelity failed its pre-committed bar (50% < 80%); no Stage 2, no project.**
Ticket NB-VLM-PILOT, branch `NB-VLM-pilot`, worktree `.claude/worktrees/nb6-pilot`. Executes the
pre-committed protocol of `2026-08-25-nb6-vlm-scoping.md` §3 (NB-6), whose full text is binding.
Thresholds below are copied, not re-derived; none moved after results exist.

**Scope interpretation (pre-registered):** this ticket executes Stage 0 (G0.1–G0.3) and Stage 1
(description fidelity) plus the open/close decision those stages determine. NB-6 §3's Stage 2
(end-to-end rescue) is successor work if the pilot opens — it is not executed here. Recorded as
disagreement-register entry D1.

*(This file supersedes the stub `2026-08-25-nb6-vlm-pilot.md` (commit 772d4ac): same pre-registration,
now with results filled in; the stub is deleted to keep one canonical report. See register entry D5.)*

## Pre-committed criteria (quoted from NB-6 §3 — authoritative)

- **Population:** all 5 D1-unreachable items (ver84 Q-GTA-042/043/044 + Q-WAYB-027; GT-WMR
  Q-WMR-094) + N=100 figure-bearing pages stratified chart/diagram vs caption-only, strata weights
  recorded when drawn.
- **G0.1 VRAM posture:** co-resident with full TEI pair within headroom, OR serialized round-trip
  (evict → batch → reload) completes with serving restored. Measured, not modeled (per T-DOC15).
- **G0.2 per-page latency:** measured ≤ 30 s/page across the N=100 sample.
- **G0.3 true-vision audit:** re-audit all 5 items fitz-first (`get_text()` over the gold page
  region). Denominator shrinks to survivors; if < 3 survive → STOP, operator review.
- **Stage 1:** ≥ 80% of asked values verified correct (independent judge, blind describe).
  One pre-registered retry allowed ONLY for infrastructure failure — never for score disappointment.

## Pre-registered operationalizations (written BEFORE any measurement; frozen at stub commit 173fb96)

These definitions fill gaps NB-6 §3 deliberately left open. They were registered before the model was
pulled or any page described, so they could not be tuned post-hoc.

### O1 — Asked-value set (the Stage 1 numerator/denominator)

Extracted verbatim from each item's fixture `answer_text`/`question_text` at stub time:

| item | paper | page (0-idx) | asked values | n |
|---|---|---|---|---|
| Q-WAYB-027 | 2208.12833 | 35 | pillar = "Monitoring"; lifecycle phase = "While in Driver's Seat"; implementation block = "RT Vigilance Assessment" | 3 |
| Q-GTA-042 | 2508.19425 | 13 | vertical row-group label = "Crashed Passenger Vehicles (IPMM)" | 1 |
| Q-GTA-043 | 2506.08228 | 9 | pure power-law form constant = "-0.026" (as L ∝ C^-0.026); power-law-plus-constant constants = "-0.18", "+1.03" | 2 |
| Q-GTA-044 | 2104.10133 | 7 | Recall/Mean DE per panel: 99.29% & 0.1849 (Human Label Boxes); 93.50% & 0.1958 (Offboard Perception); 87.31% & 0.2738 (Baseline Detector) | 6 |
| Q-WMR-094 | 2312.12675 | 9 | Any-Injury-Reported reductions: 86% (San Francisco); 54% (All Locations/National) | 2 |

Total asked values across the 5 items' figure sets: **n = 14**. A value counts verified-correct iff
the VLM's blind description states it and the judge independently confirms it against the PDF under
O2's tolerance.

### O2 — Judge verification tolerance (fixed at stub time)

- **Printed strings** (labels, legend text): match case-/punctuation-insensitively against the PDF
  text layer (`page.get_text()` over the gold region) OR are legible in the page render.
- **Printed numerals**: exact digit-string match preferred (e.g. `99.29`, `-0.026`); a
  visually-equivalent rendering (`99.3`) passes only if the PDF text layer carries the exact form
  and the description's rounding is faithful (≤ 1 significant-digit loss, no sign error).
- **Pixel-estimated quantities** (bar heights, unlabeled gridline readings): correct within ± half a
  minor gridline unit or ± 2% relative, whichever is larger. (Expected to apply to zero of the 14
  asked values above — all five items target printed text — but pre-registered for the sampled-page
  spot checks.)
- **Categorical facts** (pillar/phase/block assignments): semantically equivalent naming passes
  (e.g. "While in Driver's Seat" ≡ "while-in-seat"); wrong cell = fail.

### O3 — Judge independence

Describe step: scripted Ollama call, prompt contains NO fixture content (no question, no answer,
no excerpt). Judge step: separate session(s) receiving ONLY (a) the page render path, (b) the VLM's
raw description. Judges never see the fixture gold excerpts while judging; they verify against the
PDF itself (`fitz.get_text()` over the region + visual read of the render). Fixture answers are
compared in only afterwards, mechanically, to compute the asked-value hit rate.

### O4 — Stratified sample drawing

Frame: `figures` rows of the Waymo corpus DB (same corpus as the 5 gold items; keeps one
pdf_cache). Strata assigned from caption text signal: **chart** / **diagram** / **caption-only**.
Allocation proportional to stratum share, drawn once with a fixed seed, no redraws.

### O5 — Retry policy

Exactly one retry of an arm is permitted, only for infrastructure failure (model fails to load,
OOM, render error), logged as such. Score disappointment never triggers a rerun, prompt change, or
threshold movement.

### O6 — G0.3 survivor rule

An item is DISCOUNTED (extraction-gap, not true-vision) iff ≥ 50% of its audit tokens are
recoverable via `page.get_text()` — checked against BOTH the whole page and the gold block's
bbox padded ±20pt — after normalization; numeric tokens boundary-guarded. Measured result
(commit 60bb5da): 4/5 survive — gate PASS.

### O7 — Stage 1 denominator under G0.3 shrinkage + G0.1 success criteria

Registered before any inference ran:

- The **gating** Stage 1 asked-value set is the 4 surviving items' asked values: Q-WAYB-027 (3) +
  Q-GTA-042 (1) + Q-GTA-043 (2) + Q-WMR-094 (2) = **n = 8**. Q-GTA-044's page is still described and
  its fidelity reported informationally (6 asked values) but does not enter the gate denominator.
- **G0.1 posture A (co-resident)** succeeds iff the VLM loads and the describe batch completes
  while BOTH TEI services stay resident, with nvidia-smi-sampled peak usage leaving ≥ 2 GB free on
  the 24 GB card and zero OOM events. **Posture B (serialized)** is the recorded fallback if A fails.

## Model acquired

| field | value |
|---|---|
| exact tag | `qwen2.5vl:7b` |
| ollama ID | `5ced39dfa4ba` |
| size | 6.0 GB |
| family fit | NB-6 §2 row 1: Ollama-hosted qwen2.5-VL-class ~7B instruct, quantized GGUF + mmproj vision encoder |

## Population drawn (O4) — strata weights as measured

Frame: 11,334 figure-bearing pages with a PDF present (0 excluded). Seed 20260825, one draw
(`population.json`; allocation 75/16/9 by largest remainder):

| stratum | frame count | weight (frac of frame) | allocated |
|---|---|---|---|
| caption-only | 8,509 | 75.07% | 75 |
| diagram | 1,788 | 15.78% | 16 |
| chart | 1,037 | 9.15% | 9 |

Described population: 105 pages = 100 sampled + 5 gold-item pages. A 10-page judge spot-check set
was additionally drawn from the sampled 100 (seeded, `stage1_spot_selection.json`, frozen before
judging): 5 caption-only / 3 diagram / 2 chart.

## Stage 0 verdicts — all three gates PASS

### G0.1 VRAM posture — PASS (posture A held end-to-end)

nvidia-smi sampled every 2s across the describe batch (337 samples,
`vram_samples_postureA.csv`): min 18,926 MiB / median 18,989 / **peak 19,059 of 24,576 MiB →
5,517 MiB (≈5.65 GB decimal) free at peak**, against the pre-registered ≥ 2,048 MiB bar. The usage
floor (~18.9 GiB throughout ≈ 6 GB VLM + ~9.4 GiB TEI pair + activations) shows both TEI services
stayed resident for the whole batch — co-residency, not serialization. Zero OOM events (all 105
describe calls returned complete outputs; per-page records in `descriptions.jsonl`). Posture B never
needed.

### G0.2 per-page latency — PASS

Recomputed from the 105 describe records: min 4.8 s / median 8.1 s / p90 8.2 s / **max 14.4 s/page**
— bar ≤ 30 s/page cleared with > 2× margin, including the 5 gold pages.

### G0.3 true-vision audit — PASS (4/5 survive; denominators shrunk per protocol)

Fitz-first re-audit executed and committed at 60bb5da (`g03_audit.json`, rule O6); re-run during this
session reproduces it byte-for-byte. Survivors: Q-WAYB-027, Q-GTA-042, Q-GTA-043, Q-WMR-094.
Discounted: Q-GTA-044 (9/9 inset tokens text-reachable — extraction gap, not true vision). n=4 ≥ 3 →
continue. Gate denominators shrink accordingly (O7).

## Stage 1 result — FAIL: gating fidelity 50% (4/8), bar ≥ 80%

### Judge execution (O3 provenance)

Every judged key received ONLY (a) its page render PNG and (b) the VLM's raw blind description;
judges verified claims against the PDF's own text layer plus their own visual read of the render,
under O2 tolerances, and wrote claim tables (`verdicts.json`: {claim, verdict ∈ CONFIRMED/REFUTED/
UNVERIFIABLE, evidence}). No judge saw any fixture excerpt; fixture answers entered only afterwards,
through the frozen mechanical scorer (`scripts/nb_vlm_stage1_score.py`, patterns copied verbatim from
the stub's O1 table). Realization note (register D3): each judge dir also carries `pagetext.txt`,
the deterministic whole-page `fitz.get_text()` extraction, so judges had the PDF text layer without
needing GPU or repo access. 15/15 keys judged; 564 claims total (510 CONFIRMED / 20 UNVERIFIABLE /
34 REFUTED). Verdict tables preserved at `data/2026-08-25-nb6-pilot/judge_verdicts/`.

Process note (register D2): an earlier continuation launched 15 fire-and-forget judge sessions that
exited without landing verdicts; only 3 verdict files survived on disk (2208.12833_p35,
2312.12675_p9, 2506.08228_p9 — validated intact and reused). This session re-ran the remaining 12
judges synchronously (bounded batches, actively waited). No verdict was regenerated where a valid
file already existed.

### Fidelity table — gating set (n = 8, the O7 denominator; bar ≥ 80%)

| # | item | asked value | stated in blind desc | judge | verified |
|---|---|---|---|---|---|
| 1 | Q-WAYB-027 | pillar = "Monitoring" | yes | CONFIRMED | ✅ |
| 2 | Q-WAYB-027 | lifecycle phase = "While in Driver's Seat" | yes | CONFIRMED | ✅ |
| 3 | Q-WAYB-027 | implementation block = "RT Vigilance Assessment" | yes | CONFIRMED | ✅ |
| 4 | Q-GTA-042 | "Crashed Passenger Vehicles (IPMM)" | **no** — desc paraphrases ("crash rates of passenger vehicles", glosses "(PMM)") | — | ❌ |
| 5 | Q-GTA-043 | power-law constant "-0.026" | yes | CONFIRMED | ✅ |
| 6 | Q-GTA-043 | "-0.18", "+1.03" | **no** — neither string anywhere in desc | — | ❌ |
| 7 | Q-WMR-094 | 86% (San Francisco) | **no** — desc has IPMM rate 5.86 but no reduction percentages | — | ❌ |
| 8 | Q-WMR-094 | 54% (All Locations/National) | **no** — "54" absent entirely | — | ❌ |

**Gating fidelity: k = 4 / n = 8 = 50.0%. Bar: ≥ 80%. → FAIL.**

All four misses are genuine transcription failures by the describer (values absent from its blind
output), not scorer artifacts: each was checked by hand against the raw description text and the
judge claim tables before accepting. Pattern: sparse text-in-figure labels survive (Q-WAYB-027 3/3),
but dense chart/table numerics get dropped or paraphrased (Q-GTA-043's constants, WMR-094's
reductions, GTA-042's verbatim label).

### Informational (outside the gate, per O7): Q-GTA-044 — 6/6 = 100%

The extraction-gap page's nine printed inset values include all six scored ones; every one was both
transcribed by the blind description and judge-CONFIRMED. Ironic but consistent with G0.3: the model
reads pixel-inset numerals well; it fails on dense tabular/chart content — exactly the content the
surviving true-vision items need.

### Spot-check precision off gold ground truth (10 seeded pages)

364 judged claims across the 10 spot pages: **337 CONFIRMED / 27 REFUTED / 15 UNVERIFIABLE →
precision 92.6%** (CONFIRMED ÷ (CONFIRMED+REFUTED)). Refuted-claim clusters are informative:
stacked-bar segment values misread as stack totals (one chart page alone: 12 refuted bar-values),
invented axis titles (2+2 on two pages), near-miss digit strings ("956" vs printed "976"; email
"lsl" vs printed "lsd"), and swapped subfigure captions. The describer is a competent page-summarizer
and a unreliable verbatim-transcriber of dense figures — the same conclusion the gating set reaches.

### Retry policy (O5)

Not exercised: describes completed cleanly (no load failure/OOM/render error), judges completed for
all 15 keys. The Stage-1 shortfall is score disappointment — exactly the case O5 forbids re-running.

## Verdict / open-close decision

Per NB-6 §3 Stage 1, pre-committed: success requires ≥ 80% of asked values verified correct;
measured 50.0% (4/8 gating). One retry was allowed only for infrastructure failure; none occurred.

**Verdict: PROJECT CLOSED.**

Consequences, exactly as the protocol frames them:

- Stage 2 (end-to-end rescue) is not run — there is no fidelity foundation to rescue with.
- NB-6 §1's CONDITIONAL CLEAR does not convert to a build: B2 (prevalence evidence) was always
  unmeasured; now B1's execution vehicle has failed its own quality gate. The unique-information
  floor (4 true-vision items, proven unreachable by text) still stands — but this model class, at
  this fidelity, cannot serve it.
- What survives as reusable fact: the Waymo corpus can hold a 7B-class VLM fully co-resident with
  serving (G0.1) at ~8 s/page (G0.2), and pixel-inset numeral transcription is already reliable
  (Q-GTA-044 6/6). Any future revisit should start from those three measured facts, with dense-table
  transcription named as the specific unsolved gap.
- Per §3's Stage-2 failure clause (applied here at Stage 1, mutatis mutandis): Q-GTA-044-class
  extraction gaps remain routed to a parser/chunker-fix ticket (text-side work), and vision items'
  accounting stays an operator decision among openevidence-programme §8's options.

## Method notes & disagreement register

- **D1 — Stage 2 boundary** (pre-registered at stub): ticket executes Stages 0–1 + open/close
  decision only.
- **D2 — Judge-session continuity.** Predecessor continuation launched 15 parallel judge sessions
  fire-and-forget and exited mid-flight; 3 valid verdict files landed and were reused unchanged; the
  other 12 were re-judged synchronously this session under the identical O3 prompt discipline.
  Deviation from house preference for parallel dispatch, adopted deliberately for wait-integrity;
  no effect on any measurement.
- **D3 — Text-layer realization.** O3 names `fitz.get_text()` over the region as the judge's PDF
  source. Judges received that layer as a pre-extracted `pagetext.txt` per key (whole page,
  deterministic call, made mechanically outside judging) plus the render. No judge ran code or
  touched the repo; independence surface unchanged.
- **D4 — No retry.** O5's single infrastructure-failure retry was not spent; failures here are score
  outcomes.
- **D5 — Report consolidation.** The instructed final path `2026-08-25-nb-vlm-pilot.md` differs from
  the stub's filename (`2026-08-25-nb6-vlm-pilot.md`); this file carries the stub's full
  pre-registration forward verbatim-with-results and replaces it, keeping one canonical pilot report
  (stub retained in git history at commit 772d4ac).
- **Miss verification.** Each gating MISS was manually confirmed against the raw description string
  (not just the regex) before being accepted — guards against false-negative mechanical matching.

## Artifacts index (all under `docs/eval-reports/data/2026-08-25-nb6-pilot/` unless noted)

| artifact | what it is |
|---|---|
| `population.json` | O4 frame, strata counts/weights, seeded draw (n=100) |
| `renders/` (105 PNGs) | 170-DPI pymupdf page renders (describe input) |
| `descriptions.jsonl` | 105 blind describe records: key, model, seconds, chars, text |
| `vram_samples_postureA.csv` | 337 two-second nvidia-smi samples spanning the batch (G0.1) |
| `g03_audit.json` | fitz-first true-vision audit, 5 items (G0.3; committed 60bb5da) |
| `stage1_spot_selection.json` | 10-page seeded judge spot-check set |
| `judge_verdicts/<key>.json` (15) | independent-judge claim tables (mirrored from the working copies) |
| `stage1_scores.json` | frozen scorer output: per-value rows + tallies |
| `scripts/nb_vlm_pilot.py` (repo `scripts/`) | harness: population / audit-g03 / render / describe |
| `scripts/nb_vlm_stage1_score.py` (repo `scripts/`) | frozen asked-value matcher + tally (patterns = stub O1) |
