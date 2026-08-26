# NB-C1 — refusal-affordance detector falsification (A-series C1, stage 1)

**Status: COMPLETE — verdict DROPPED.** Ticket NB-C1 per programme plan Wave-3 successor chain;
mandate [`2026-08-25-nb-a1-abstention-signal-design.md`](2026-08-25-nb-a1-abstention-signal-design.md)
§C1 ("C1 — Generation-side behavioural signal", stage 1 only). Branch `NB-C1-refusal-detector`
(worktree off `main` @ `20d2882`). Measurement ticket: no pipeline change, no prompt change (the
clause file `fixtures/eval/prompts/refusal-affordance.txt` used byte-identical), no foundation path
touched (`contracts/`, `migrations/`, `fixtures/`, `rag/config.py`, `ci/`, `.github/`,
`pyproject.toml` untouched). Collection `waymo_av_safety` named explicitly on the capture;
GPU work serialized through the shared `.gpu.lock` via `FileGpuLock` — queued behind another lane's
holder, never bypassed or removed. Fixtures reported separately throughout; never averaged.

## Pre-committed criterion, evaluated verbatim

Fixed in A-1 §C1 *before any run*, applied here without modification:

> Write ONE fixed refusal-shape classification rule first … then: on ver84, judged from the *existing
> committed captures*, refusal-shaped answers must cover **≥12/16** known-absent items with **≤5**
> false refusals among 68 answerable; AND on gt_wmr … from one fresh capture, **≥9/12** with **≤4**
> false refusals among 70. Either side failing → candidate dropped entirely. No threshold tuning,
> prompt rewording, or rubric iteration is permitted to rescue a failure.

## Verdict table (both fixtures, denominators exact)

| fixture | source | known-absent covered | bar | | false refusals | bar | | half-verdict |
|---|---|---|---|---|---|---|---|---|
| ver84 | committed affordance-arm captures (`2026-08-24-waymo-generation-run-affordance.{absent,answerable}.json`) | **10/16** | ≥12 | ❌ | **7/68** | ≤5 | ❌ | **FAIL (both halves)** |
| gt_wmr | fresh capture this ticket (`docs/eval-reports/data/2026-08-25-nb-c1/gt_wmr-generation-affordance.json`, 82 items, 0 errors) | **11/12** | ≥9 | ✅ | **0/70** | ≤4 | ✅ | PASS |

**VERDICT: DROPPED.** The criterion is disjunctive ("either side failing → candidate dropped
entirely"); ver84 fails *both* of its halves, so the candidate is dropped regardless of gt_wmr's
clean pass. Per the pre-commitment, stage 2 (sample-consistency) is dead with it — its gate was
stage 1 clearing the bar. No rubric iteration, threshold change, or rewording was performed or is
permitted; the rule below is byte-identical to commit 1 (`9de6da1`), which predates every
classification.

## The frozen rule (v1.0)

Committed before any answer was seen (`app/exp_nb_c1_refusal_classifier.py`, `RULE_VERSION="1.0"`):

```
lead_region    = first min(2 sentences, 600 chars) of the answer
REFUSAL        = any of 9 frozen refusal-language classes matches lead_region (case-insensitive):
                 declarative-does-not · bare-no-information · not-any-information ·
                 capability-negation · not-participle · insufficient-information ·
                 lacks-information · not-possible-to-answer · mismatch-no-such
NUM_COMMIT     = any digit survives in lead_region after stripping calendar years \b(18|19|20)\d{2}\b
refusal-shaped := REFUSAL AND NOT NUM_COMMIT
```

Blind by construction: `classify_answer()` reads only the generated answer string; gold arms are
joined afterwards solely to compute the criterion's counts (the code orders it that way so the join
cannot influence classification). Scope limits accepted as part of the freeze and stated up front in
the module docstring: numbers written as words and entity-only commitments are not detected as
commitments; unit/milestone numerals are not distinguished from asserted figures.

## Method notes

- **Order of operations (audit trail):** commit 1 = full frozen rule, zero answers read; commit 2 =
  ver84 mechanical results; commit 3 = fresh gt_wmr capture artifacts; commit 4 = gt_wmr results +
  this report. Every number in this file is a field of a committed JSON under
  `docs/eval-reports/data/2026-08-25-nb-c1/`.
- **Fresh capture mirrors the A/B exactly:** same ground-truth loader defaults, `--collection
  waymo_av_safety`, retrieval k=10 / generation k=5 (module defaults, unflagged), `qwen3:14b`,
  `--prompt-file fixtures/eval/prompts/refusal-affordance.txt`. Result: 82 captured, **0 errored
  generations**, 2 truncated (same posture as both A/B arms).
- **Denominator discipline:** ver84 uses the raw-84 convention (16 absent / 68 answerable — the
  pre-split capture files' own partition); gt_wmr uses absence_note over the undeduplicated 82-row
  fixture (12 absent / 70 answerable — there are no `duplicate_of` rows in gt_wmr, so dedup changes
  nothing). Conventions never mixed within a table (A-1 §2).
- **Hand spot-checks were run on every flagged item after results existed**; they are logged below
  and changed nothing.

### Hand spot-check log

*ver84 (all 13 flagged items hand-read against their lead regions):*

- Rule's 3 true answerable-arm refusals — `Q-GTA-033`, `Q-WAYB-026`, `Q-WAYB-027` — are exactly the
  A/B §3 hand-set. Agreement.
- 4 answerable-arm **false positives** (`Q-GTA-023`, `Q-GTA-027`, `Q-WAYB-013`, `Q-WAYB-030`):
  explanatory "cannot"/"lacks" inside substantive answers, and a hedged aside inside a full answer
  (`Q-WAYB-013`, named as exactly this shape in A/B §3). These inflate 7 vs the hand-standard 3.
- 4 absent-arm **false negatives**: `Q-WAYB-022`, `Q-WAYB-039` (clean refusals demoted because the
  demanded *unit* carries digits — "per 1,000 miles", "100-million-mile"/"56.7-million-mile"),
  `Q-WAYB-034` (negative-existential "None of the papers … report" matches no pattern class),
  `Q-GTA-036` (refusal followed by explicitly-labelled contrast figures). These depress 10 vs the
  hand-standard ~14.
- `Q-GTA-035` (borderline quote of real figures) and `Q-GTA-037` (wrong-side "905 nm") classified
  non-refusal by rule and hand alike. Agreement.

*gt_wmr:* the single absent miss `Q-WMR-080` asserts a fabricated "20%" night-mile figure — the rule
is *right* that it is not refusal-shaped (it is a wrong-side answer; the criterion counts coverage,
so it still counts as a miss). Six of six sampled covers hand-confirmed genuine refusals; five of
five randomly sampled answerable items hand-confirmed genuine answers (0/70 false refusals is not an
artifact of a silent plumbing failure).

### What actually died, and what did not

The failed quantity is precise: **no single blind, fixed, lead-region rule can read the
refusal-shape signal off these captures at the required operating point.** On ver84 the rule loses
on both ends simultaneously — its commitment guard misfires on demanded units (dropping coverage
below bar) while its pattern classes fire on explanatory negation and honest hedged asides (pushing
false refusals above bar). Hand classification would have cleared ver84 (~14/16, 3/68) — but a hand
classification is not a detector, and the criterion was deliberately defined over the fixed rule.
That is the finding: **the abstention information the affordance arm demonstrably carries
(A/B: wrong-side 6/16→1/16) is not mechanically extractable by this rule family**, so the
detector-as-signal-source candidate is dropped per the pre-commitment.

Two things survive, recorded for successors rather than re-opened here:

1. A-1 §3's fallback reading gains weight: if any affordable abstention win exists at the generation
   layer, it is the **unconditional affordance clause** (already measured: 6/16 → 1/16 wrong-side at
   one clean answerable regression), with any detector treated as upside — not prerequisite. That is
   an operator decision, out of scope for this ticket.
2. gt_wmr's clean sweep (11/12 with the one miss being a genuine wrong-side catch, 0/70 false
   refusals) shows the *behavioural* separation on single-fact questions is real and large; what
   fails is rule-expressibility under multi-part/hedged question styles (ver84's strata). Any future
   attempt in this family must say up front how it escapes this exact trap — the pre-committed-rule
   protocol worked as designed and should be reused.

## Reproducibility

```bash
conda activate agent-rag-research
# ver84 (zero GPU):
python -m app.exp_nb_c1_refusal_classifier \
  --absent-capture fixtures/eval/runs/2026-08-24-waymo-generation-run-affordance.absent.json \
  --answerable-capture fixtures/eval/runs/2026-08-24-waymo-generation-run-affordance.answerable.json \
  --out docs/eval-reports/data/2026-08-25-nb-c1/ver84_classifications.json

# gt_wmr fresh capture (GPU; serialized on .gpu.lock; services up; collection named):
python -m app.generation_capture \
  --ground-truth fixtures/eval/gt_wmr.json \
  --config /home/omar/ai-projects/research-system-rag/waymo/data/config.yaml \
  --collection waymo_av_safety \
  --prompt-file fixtures/eval/prompts/refusal-affordance.txt \
  --output docs/eval-reports/data/2026-08-25-nb-c1/gt_wmr-generation-affordance.json

# gt_wmr classification:
python -m app.exp_nb_c1_refusal_classifier \
  --combined-capture docs/eval-reports/data/2026-08-25-nb-c1/gt_wmr-generation-affordance.json \
  --gt fixtures/eval/gt_wmr.json \
  --out docs/eval-reports/data/2026-08-25-nb-c1/gt_wmr_classifications.json
```

Artifacts: `app/exp_nb_c1_refusal_classifier.py` (frozen rule),
`docs/eval-reports/data/2026-08-25-nb-c1/{ver84_classifications.json,
gt_wmr_classifications.json, gt_wmr-generation-affordance.json,
gt_wmr-generation-affordance.absent.json, gt_wmr-generation-affordance.answerable.json}`.
