# NB-VLM-PILOT — bounded VLM falsification pilot (Stage 0 gates + Stage 1 fidelity)

**Status: IN PROGRESS** · Ticket NB-VLM-PILOT, branch `NB-VLM-pilot`, worktree
`.claude/worktrees/nb6-pilot`. Executes the pre-committed protocol of
`2026-08-25-nb6-vlm-scoping.md` §3 (NB-6), whose full text is binding. Thresholds below are copied,
not re-derived; none may move after results exist.

**Scope interpretation (pre-registered):** this ticket executes Stage 0 (G0.1–G0.3) and Stage 1
(description fidelity) plus the open/close decision those stages determine. NB-6 §3's Stage 2
(end-to-end rescue) is successor work if the pilot opens — it is not executed here. Recorded as
disagreement-register entry D1.

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

## Pre-registered operationalizations (written BEFORE any measurement; frozen at stub commit)

These definitions fill gaps NB-6 §3 deliberately left open. They are registered here, before the
model is pulled or any page described, so they cannot be tuned post-hoc.

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

### O2 — Judge verification tolerance (fixed now)

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
pdf_cache). Strata assigned from caption text signal: **chart** (caption/title contains
chart/graph/bar/line/plot/histogram), **diagram** (diagram/architecture/map/layout/timeline/flow),
**caption-only** (figure row whose caption is empty or generic "Figure N"). Allocation proportional
to stratum share, drawn once with a fixed seed (recorded in the population JSON), no redraws.
Strata weights recorded in the report when drawn.

### O5 — Retry policy

Exactly one retry of an arm is permitted, only for infrastructure failure (model fails to load,
OOM, render error), logged as such. Score disappointment never triggers a rerun, prompt change, or
threshold movement.

## Stage 0 verdicts

| gate | criterion | measurement | verdict |
|---|---|---|---|
| G0.1 VRAM posture | co-resident within headroom OR serialized evict→batch→reload restores serving | TBD | TBD |
| G0.2 latency | ≤ 30 s/page across N=100 | TBD | TBD |
| G0.3 true-vision audit | ≥ 3 of 5 items survive fitz-first audit | TBD | TBD |

## Stage 1 result

TBD — asked-values fidelity n/N and %; spot-check precision on sampled pages reported alongside.

## Verdict / open-close decision

TBD per pre-committed rules.

## Method notes & disagreement register

- **D1 — Stage 2 boundary.** Ticket brief executes Stages 0–1 + open/close decision; §3's Stage 2
  rescue run deferred to a successor ticket if the pilot opens. Interpretation, not deviation: §3
  remains authoritative for whatever stage runs next.
- *(further entries appended as encountered)*

## Artifacts index

TBD — populated as artifacts land (population JSON, renders/, descriptions JSONL, judge records,
gate logs).
