# NB-QW2 — confidence-surface v0: MiniCheck-FT5 support-checking over stored generation captures

**Status: COMPLETE (raw-score prototype, not a calibrated confidence surface).** Ticket NB-QW2
(precision-95 programme, R2 §3 Rank 1). Branch `NB-QW2-confidence-v0`, worktree
`.claude/worktrees/nb-qw2-confidence`, rebased onto `main` @ `8dc336e`. Fully offline: zero paid
APIs, one local checkpoint (`lytang/MiniCheck-Flan-T5-Large`, 770M) downloaded once and loaded
with `local_files_only=True` thereafter (refuses the network outright, scoped to the one load
call -- no process-env read, so this stays clear of CONVENTIONS §12(d)'s "env reads belong to
`rag/config.py`" rule). No foundation-gated path touched (`contracts/`, `rag/config.py`,
`config.example.yaml`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/` untouched —
`fixtures/eval/runs/*.json` were read-only inputs). GPU serialized on the shared `.gpu.lock`
(`rag/gpu_lock.py`'s `FileGpuLock`, held only for the scoring block, released cleanly on exit).

**What this ships: a raw score plus an explicit UNVALIDATED PROTOTYPE label. Nothing else.** No
level language ("high/medium/low"), no probability wording, no thresholds — anywhere in the code
or in this report. Five-level thresholds are explicitly out of scope, gated on IN-2's ≥100 graded
anchors (26 exist today, B0 §4). This measures **support by the served passages, not truth** — a
sentence can be perfectly "supported" and still wrong, as §2 shows directly.

## Question (one)

Does MiniCheck-class support-checking over the *actually-served* passages, applied to the existing
generation captures, produce a raw score that (a) separates the answerable arm from the
known-absent arm at all, and (b) is honestly reportable without smuggling in the level/probability
language the ticket forbids?

## Answer in one paragraph

**Partial separation, heavy overlap, and one important correction to this ticket's own worked
example.** The two arms differ by a real margin in mean raw score (primary prompt: answerable
0.747 vs. absent 0.579, a 0.168 gap on a metric where 17 retrieval-side features found ~zero
separation between these same two arms, NB-D3/NB-R0) — but the distributions overlap enormously:
15 of 16 absent-arm items fall inside the answerable arm's own score range, and 5 of 16 score above
the answerable arm's median. **This is a distributional difference, not a usable cut-point, and
none is fit here.** Q-GTA-037 — this ticket's named worked example of a generic-fact-to-
specific-subject misattribution — actually scores the **lowest of all 16 absent-arm items**
(0.0268), the opposite of the "scores high" narrative this ticket asked to test for. But the same
failure mechanism the ticket warns about **does** appear elsewhere in this same arm: `Q-GTA-040`'s
fabricated "Swiss Re underwrites Waymo" sentence scores 0.9388, because the served passage
genuinely discusses both Swiss Re *and* Waymo together (a real relationship, just not the invented
one) — a harder, better-camouflaged instance of the same class than the example named in the
ticket. §2 covers both in full.

## Method (what was actually run)

- `app/exp_confidence_v0_support.py` reimplements MiniCheck-FT5's own released scoring recipe
  directly on `transformers` (not the `minicheck` pip package — avoids pulling in unused runtime
  deps): `predict: {passage}</s>{sentence}` into `lytang/MiniCheck-Flan-T5-Large`, softmax over the
  fixed decoder-logit pair `[3, 209]` (no-support, support), score = the resulting two-way
  softmax weight on "support". **Verified against the checkpoint's own published demo before any real run**: this
  reimplementation reproduces the README's two-sentence example to 4 decimal places
  (0.9806 / 0.0071).
- Every served passage that ran past the model's 2048-token window (~10% of passages, up to ~4000
  words) was **word-chunked at 500 words (MiniCheck's own default) and max-aggregated**, not
  silently truncated — truncation would have blinded the scorer to whatever fell past the cut on
  exactly the long passages most likely to bury the relevant sentence.
- Per sentence: max over that item's served passages (`n_passages_used`, not the wider retrieved
  pool). Per answer: mean/median/min/max of its sentences' maxima — all four are in the committed
  JSON, nothing is binarized.
- Four arms scored, one GPU-lock acquire/release cycle, zero network calls during scoring:

| capture | arm | items | sentence×passage pairs |
|---|---|---|---|
| `2026-08-23-waymo-generation-run.answerable.json` | answerable | 68 | 1200 |
| `2026-08-23-waymo-generation-run.absent.json` | absent | 16 | 147 |
| `2026-08-24-waymo-generation-run-affordance.answerable.json` | answerable | 68 | 1038 |
| `2026-08-24-waymo-generation-run-affordance.absent.json` | absent | 16 | 119 |

  (The affordance capture pair — `qwen3:14b` with one added refusal-permitting prompt sentence,
  see `2026-08-24-waymo-refusal-affordance-ab.md` — carries no `_metadata.arm`; `load_capture` now
  falls back to the filename's own `.answerable.`/`.absent.` marker, tested in
  `app/test_exp_confidence_v0_support.py::test_load_capture_infers_arm_from_filename_when_metadata_omits_it`.)
- **No self-evaluation bias**: the generator (`qwen3:14b`) and the scorer (MiniCheck-FT5, a
  Flan-T5-Large fine-tune) are unrelated model families trained by unrelated teams — unlike the
  earlier judge-LLM work, this score cannot be inflating its own generator's answers by shared
  training data or a shared prompt-following prior.
- Score dumps (source of every number below): `docs/eval-reports/data/2026-08-28-confidence-v0/*.minicheck-v0.json`.

## 1. Per-arm distributions — reported separately, never blended (PREC-1 §5)

Every number below is a field of the committed JSON dumps.

| fixture / arm | n | mean | median | min | max |
|---|---|---|---|---|---|
| primary prompt — **answerable** | 68 | 0.747 | 0.822 | 0.044 | 0.988 |
| primary prompt — **absent (known-absent)** | 16 | 0.579 | 0.682 | 0.027 | 0.956 |
| refusal-affordance prompt — **answerable** | 68 | 0.794 | 0.884 | 0.315 | 0.988 |
| refusal-affordance prompt — **absent (known-absent)** | 16 | 0.667 | 0.737 | 0.027 | 0.951 |

Histogram (10 bins of width 0.1, `[0.0-0.1) ... [0.9-1.0]`, counts left→right):

| arm | histogram |
|---|---|
| primary answerable (n=68) | 3, 0, 1, 3, 5, 7, 5, 6, 11, 27 |
| primary absent (n=16) | 3, 1, 0, 1, 0, 0, 3, 3, 3, 2 |
| affordance answerable (n=68) | 0, 0, 0, 3, 5, 6, 4, 11, 9, 30 |
| affordance absent (n=16) | 1, 1, 0, 0, 1, 2, 3, 1, 3, 4 |

**Overlap, stated plainly (no cut-point fit or implied):**

- Primary: answerable median 0.822; **5 of 16 absent items (31%) score above it.** Absent max
  (0.956) sits well above the answerable arm's own min (0.044). 15 of 16 absent items fall inside
  the answerable arm's full score range.
- Affordance: answerable median 0.884; **4 of 16 absent items (25%) score above it.**
- **Context for the 0.168 / 0.127 mean gaps, verified against the committed source rather than
  quoted secondhand**: NB-D3's abstention census (`docs/eval-reports/2026-08-25-nb-d3-abstention-census.md`,
  "Arm-level rank-1 score distributions" table) reports the fused-retrieval-score mean for the
  `ver84` fixture (`waymo_gt_verified` — the same ground truth these captures answer against) as
  **0.01128 for the answerable arm vs. 0.01102 for the known-absent arm — a gap of 0.00026
  (≈0.0003)** on that score's own scale. Across NB-D3's full 17-feature retrieval-side census, no
  feature reached a usable AUROC either (best fused-feature AUROC 0.4674 on `ver84`, ~chance; every
  Youden-optimal cut it tried cost 25-41% of answerable items as false refusals to catch the
  absent arm at all). QW-2's mean gap (0.168 primary / 0.127 affordance) on a [0,1] support score
  is roughly **490-650x** the retrieval score's own absolute gap, and a qualitatively different
  amount of signal than that near-null retrieval result — which is *why* this is worth reporting at
  all. But it is still a population-level mean difference over heavily overlapping distributions
  (§1's overlap counts above), not a working per-item abstention rule, and no threshold is fit or
  implied here; that fit is IN-2's, gated on graded anchors (§4).

## 2. The failure mode this ticket asked to test — and the correction it produced

The ticket's worked example: **`Q-GTA-037`** — "What laser wavelength does the lidar sensor on
Waymo's production vehicles use?" The captured answer: *"The lidar sensor on Waymo's production
vehicles uses a laser wavelength of **905 nm**."* One of the five served passages genuinely
contains "the commonly used wavelength is 905 nm" — as a generic fact about LiDAR in general, in a
paper (`local:0a57c839728c`, "A Review of LiDAR sensor Technologies...") that never mentions Waymo
at all. Per FAB-2's hand classification, this is the one wrong-side known-absent answer that
**survived** the refusal-affordance prompt fix (`2026-08-24-waymo-refusal-affordance-ab.md` §1) —
the system asserts it in both prompt arms, verbatim, from the same source passage.

**Measured score: 0.0268 — the lowest of all 16 absent-arm items, in both prompt arms** (the answer
is byte-identical between arms, so the score is too). This is the **opposite** of what this ticket
asked to test for: MiniCheck-FT5 does not score this misattribution high. A quick ablation on the
same passage confirms why — this checker is sensitive to the *subject*, not just the topic or the
numeral:

| claim (against the same LiDAR-review passage) | score |
|---|---|
| "The lidar sensor on Waymo production vehicles uses a laser wavelength of 905 nm." (captured) | 0.016 |
| "LiDAR commonly uses a laser wavelength of 905 nm." (subject removed) | 0.986 |
| "The commonly used wavelength for LiDAR is 905 nm." (subject removed) | 0.979 |
| "Waymo invented the 905 nm laser." (subject present, different false claim) | 0.011 |

The literal "905 nm" numeral is not what moves this score — "Waymo" appearing as the claim's
subject against a passage that never names Waymo is what drives it to the floor. This checker's
ANLI-derived training evidently makes it more sensitive to entity substitution than the ticket's
narrative (grounded in a plausible, lexical-overlap intuition about NLI-style checkers) assumed.
**This is a genuinely useful, honest finding: this specific named worked example does not
demonstrate the warned failure mode under this checker.**

**But the mechanism itself is real, and appears elsewhere in the very same arm.** `Q-GTA-040`
("What insurance company underwrites Waymo's auto liability coverage?") answered, in the primary
prompt: *"The insurance company that underwrites Waymo's auto liability coverage is **Swiss
Re**."* Per FAB-2, this is a hand-confirmed wrong-side fabrication — the underwriter is never named
in the corpus. Its served passages do genuinely discuss **both** Swiss Re and Waymo together
("Waymo provided ... claims' data ... to Swiss Re", "reviewed by Swiss Re") — a real relationship
(claims-data review), just not the invented one (underwriting). **That sentence scores 0.9388** —
near the ceiling. This is a harder, better-camouflaged case of the same class than `Q-GTA-037`:
instead of a fully generic passage with the subject entirely absent, both named entities co-occur
in a genuinely on-topic passage, and only the specific *relationship* is invented. The checker has
every textual reason to score this high, and does.

**Net finding: the checker is not uniformly fooled by generic-to-specific misattribution
(`Q-GTA-037` proves that), but it is fooled by relationship-invention between two entities that
really do co-occur in the source (`Q-GTA-040` proves that too).** Both are real, measured,
committed data points from the same 16-item arm — reporting only the one this ticket named would
have understated how it actually fails.

## 3. The refusal-affordance prompt as a natural experiment on this score

FAB-2 (`2026-08-24-waymo-refusal-affordance-ab.md`) flipped 5 of the primary arm's 6 wrong-side
absent answers to correct refusals by adding one refusal-permitting sentence to the prompt,
holding retrieval and the model fixed. Re-scoring both captures with the identical instrument
gives a controlled before/after on the SAME 16 questions:

| question | FAB-2 disposition (control → affordance) | QW-2 score (control) | QW-2 score (affordance) |
|---|---|---|---|
| `Q-GTA-037` | wrong-side → wrong-side (not flipped) | 0.0268 | 0.0268 |
| `Q-WAYB-022` | wrong-side → correct refusal | 0.0497 | 0.4011 |
| `Q-WAYB-035` | wrong-side → correct refusal | 0.1355 | 0.6107 |
| `Q-WAYB-028` | wrong-side → correct refusal | 0.6114 | 0.6980 |
| `Q-WAYB-021` | wrong-side → correct refusal | 0.6208 | 0.8014 |
| `Q-GTA-040` | wrong-side → correct refusal | 0.7702 | 0.8471 |

**All five flips raised the score, none lowered it.** This drives the arm-level result the
orchestrator flagged as counterintuitive: the affordance arm's absent-arm mean (0.667) is *higher*
than the primary arm's (0.579), even though the affordance prompt produced strictly more correct
answers on this arm. The mechanism is visible sentence-by-sentence in the dumps: a correct-refusal
sentence like *"The information provided ... does not specify ..."* is itself scored against the
passages, and this checker scores that kind of hedge/negation sentence moderately-to-highly
regardless of whether refusing was the right call — it is not evaluating "was abstaining correct,"
it is evaluating "is this sentence's assertion (including a negative one) consistent with the
passage text," and a topical hedge reads as consistent almost by construction. **This score
therefore cannot be read as "the affordance prompt made the absent arm more supported" — it
measures a byproduct of what kind of sentence got generated, not answer quality.** Say this
plainly rather than let the number imply otherwise.

## 4. Is this worth feeding IN-2's conformal wrapper?

**Conditionally yes, as one candidate score among several — not yet, and not alone.**

What this run actually produced: raw, ungraded support scores over ~2500 sentence×passage pairs
across both fixture arms and both prompt variants — structurally the same shape as the "~200-300
answer-claim↔passage support pairs" R2 §3.4/the precision-95 plan lists as an IN-2 input
requirement (`docs/superpowers/plans/2026-08-25-precision95-programme.md` §4 IN-2 sequencing item
2). What it did **not** produce, and cannot produce by itself, is any human grading of whether
those pairs are actually correct — IN-2's ≥100 graded absence-arm anchors (26 exist today, B0 §4)
and the answer-claim↔passage grading are a separate, human-in-the-loop collection step this ticket
was explicitly not scoped to do.

Three things would have to be true before this score family is worth calibrating:

1. **IN-2's anchor collection actually lands** (≥100 graded absence-arm items, not 26) — a
   conformal/LTT fit on <20 items per level is the B0 rule-of-thumb floor this programme already
   rejected once.
2. **The Q-GTA-040-class failure needs to be sized, not just spotted once.** One item this
   detailed is a proof that the failure mode exists, not a rate. IN-2's grading pass should
   specifically flag "entities co-occur, relationship invented" as its own stratum — this
   instrument alone cannot tell how common it is versus the generic-swap case `Q-GTA-037` turned
   out not to exhibit.
3. **The sentence-level scores, not just the per-answer aggregate, should be the conformal fit's
   unit.** §2's `Q-WAYB-021` example shows why: its three sentences scored 0.075 / 0.967 / 0.820 —
   the fabricated numeral sentence was correctly near-floor, but two supporting sentences (an
   inferential restatement) scored near-ceiling. The per-answer mean (0.62) buries exactly the
   signal a claim-level conformal wrapper would want to keep.

Given those, this is a real, distinguishable-from-null score family (§1) with an honestly-measured
and non-trivial failure mode (§2) and no self-evaluation confound (§4 above) — a legitimate
candidate input, not a finished one.

## What this does not show

- Does not establish that MiniCheck-FT5 is "better" or "worse" than any other checker family
  (semantic entropy, verbalized confidence) considered and not built in R2's research — no
  comparison was run.
- Does not produce, fit, or imply any threshold, cut-point, or level. Any future use of the
  overlap counts in §1 to draw a line is a separate, IN-2-gated decision.
- Does not grade correctness of any answer — every "wrong-side"/"correct refusal" label used above
  is FAB-2's own prior hand classification, cited, not re-derived here.
- Does not extend past the four captures scored; a corpus refresh or generator swap would need a
  re-run (same caveat R2/IN-2 both carry for any calibrated artifact).
- Sample sizes are what the ticket's fixtures provide: 16 known-absent items per prompt arm is
  small enough that every count in §1-§3 should be read as descriptive, not as an estimate with a
  reportable confidence interval.

## Verification

- `pytest app/test_exp_confidence_v0_support.py` — 16 tests, all pure-Python (chunking, arm
  inference, aggregation math against a fake scorer); no torch/model import required for the suite.
- `MiniCheckScorer` cross-checked against the checkpoint's own published README demo before the
  real run (reproduces 0.9806 / 0.0071 to 4 decimals) — confirms the reimplementation, not just
  that it runs.
- Real run: fully offline (`local_files_only=True`; the run itself used an equivalent
  `HF_HUB_OFFLINE=1` env-set from `MiniCheckScorer.__init__`, since replaced with the
  enforcement-clean `local_files_only=True` call -- same network-refusal guarantee, no
  behavior difference, verified by re-running `MiniCheckScorer` after the change), one
  `.gpu.lock` acquire/release cycle, GPU
  utilization observed at 100% during scoring, lock file confirmed released on exit (picked up
  immediately by the next queued lane).
- `GITHUB_EVENT_PATH=/tmp/fake_push_event.json GITHUB_EVENT_NAME=push python -m ci.run_enforcement`
  → **PASS** (checks (a)-(d), (f)-(h), testpaths; check (e) skipped, no PR context on a push
  event).
- Grep-checked: no "confidence level," "probability of," or similar wording anywhere in
  `app/exp_confidence_v0_support.py`'s output, the score-dump `_metadata.prototype_label`, or this
  report.
