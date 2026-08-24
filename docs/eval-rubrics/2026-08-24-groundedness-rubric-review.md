# Independent Review of the Groundedness Rubric (RUBRIC-G, 2026-08-24)

## Scope and posture

Reviewed `docs/eval-rubrics/groundedness-rubric.md` (53 lines) against its one production run,
`docs/eval-reports/2026-08-23-waymo-groundedness-provisional.md` (210 claims: 128 supported /
81 unsupported / 1 contradicted), plus `docs/eval-rubrics/fabrication-audit-rubric.md`, which the
groundedness rubric defines itself against ("The difference from the fabrication-audit rubric is
calibration, not the verdict vocabulary"). Read-only: nothing under `docs/eval-rubrics/` or
`fixtures/` was modified. **This document is input to the operator's sign-off decision, not the
sign-off** — per the rubric's own header, that decision "belongs to a human, not to whoever last
edited this file."

Method limits, stated up front: one reviewer, textual analysis only. No second rater, no re-run,
no empirical agreement statistics. Where this review says "two careful readers would diverge," it
means the wording admits divergent readings — the divergence was not measured.

## Q1. Would two careful readers agree?

**On routine single-passage claims, yes. On four identifiable loci, systematically no — and two of
those loci produced the observed misverdicts in the run.**

Where they would agree: the core `supported` bar is concrete and double-barreled — "a passage
states this claim AND the answer's framing of it (the specific numbers, the direction of an
effect, the named mechanism) matches what the passage actually says" — and the run's spot-check
shows it binding identically on human and judge for near-verbatim cases (Q-GTA-001, agreed
"trivially").

Where they would diverge:

1. **The `unsupported` threshold is an undefined degree.** "No passage addresses this claim
   *closely enough* to ground it" — nothing in the text says how close is close enough. The three
   calibration examples (hedge→assertion, range→extreme, related-but-different quantity) bound
   three cases but are illustrations, not a test; every borderline paraphrase falls outside them.
2. **The hinge word of the entire stricter calibration is itself uncalibrated.** The rubric's
   central instruction is to mark `unsupported` when the passage's wording is "*meaningfully*
   looser or narrower than the answer's framing." What amount of looseness is meaningful? A
   careful reader who treats a one-word intensifier as meaningful and one who doesn't will split
   on the same claim, and the rubric gives neither a rule.
3. **Claim decomposition is inherited by reference and observed to wobble.** Groundedness says
   only "Break the ANSWER into its individual claims, as in the fabrication-audit rubric"; the
   referenced definition there is "a claim is one checkable assertion." In practice the judge
   repeatedly emitted compound claims spanning a grounded and an ungrounded half — the report's
   own audit flags Q-GTA-004 ("the 'method was used' half of the claim is arguably supported, but
   the compound claim as extracted includes an ungrounded detail, and the rubric doesn't ask the
   judge to split a claim mid-sentence") and the same pattern at Q-GTA-007. Two careful readers
   who decompose differently produce different claim counts *and* different verdict distributions
   from identical inputs: disagreement upstream of any verdict call.
4. **Multi-passage items have no attribution rule and no precedence rule.** `supported` is
   existential ("*a* passage states this claim"), `contradicted` is existential ("*a* passage
   states something that conflicts with this claim") with no requirement that the conflicting
   statement bear on the claim's actual subject, and no rule for which verdict wins when one
   passage supports and another conflicts. On the run's two-passage comparative item (Q-GTA-021)
   the judge anchored on the wrong passage outright; but even a maximally careful human gets no
   help from this text deciding whether the *other* paper's different split numbers "conflict
   with" a claim scoped to the original paper.

A fifth, smaller asymmetry: the sibling rubric instructs that the passages are "the only source of
truth for this task — not your own knowledge"; groundedness drops that sentence, leaving the
passages-only stance implicit in "even if the claim happens to be true in general." A judge model
reading only this file is never told, in so many words, to ignore its own knowledge.

Net: agreement would be high on clear-cut cases and unpredictable exactly where verdicts matter
most — borderline paraphrase distance and multi-passage attribution. Both are wording gaps, not
conceptual ones.

## Q2. Does it measure what its name says?

The stated construct: "**is the ANSWER's own reasoning traceable to the PASSAGES**, not merely
non-contradictory with them." The name is *groundedness*; the promise is reasoning-traceability.

What it operationalizes is per-claim support with a framing match. That is a genuine tightening
over the fabrication audit's "something a careful reader would treat as the same claim" —
hedge→assertion, range→extreme, and related-but-different quantity all become `unsupported`
here, and none of the three has an analogue in the sibling rubric. The spot-check suggests the
stricter wording binds in practice (Q-GTA-002 agreed `unsupported` precisely because the
inferential phrase appeared nowhere in the passage). So the direction is right and the
calibration is real.

Two gaps between name and measurement:

**(a) It promises "reasoning" and delivers claims.** Only atomic assertions are checked; the
validity of the inference *joining* claims is never assessed. An answer whose every claim is
individually grounded but whose conclusion doesn't follow scores fully supported — unless the
judge happens to pack the invalid inference inside one extracted claim, which is the only reason
Q-GTA-002's leap was caught at all. Whether "reasoning" gets measured is therefore an accident of
decomposition granularity (Q1 locus 3). Either the name should narrow to claims-and-framing, or a
future rubric revision should add an inference check; today the bolded task sentence overpromises
what the procedure tests.

**(b) "Traceable to the PASSAGES" means the supplied excerpts, not the sources.** The rubric
judges against "one or more PASSAGES" — whatever excerpt set the harness supplies. Grounded in
the paper but absent from the excerpt scores `unsupported`. That is defensible (it makes the
number partly a retrieval-adequacy probe), but it is not what a downstream reader hears from the
plain word "groundedness," and the run needed a full section (§1) plus an explicit warning
("Reading it as '39% of claims are fabricated' would be wrong on this evidence") to defend its
headline against exactly that misreading. A measurement whose headline requires paragraphs of
defense has a naming problem.

**Verdict: partially.** It cleanly measures claim-content traceability to the supplied evidence
set — a coherent and useful construct — but the name promises more (reasoning, sources) than the
procedure tests (claims, excerpts).

## Q3. What does it systematically over- or under-penalise?

**Over-penalises:**

1. **Richer answers against thin excerpts — intended mechanism, undeclared consequence.** The
   judgments are excerpt-relative by design: `unsupported` is defined as "no passage addresses
   this claim closely enough to ground it, *even if the claim happens to be true in general*."
   The run confirms this fired deliberately, not by accident: several spot-checked `unsupported`
   claims were "specific numbers genuinely absent from the supplied excerpt even though the
   excerpt correctly supports the surrounding claim," which the report rules "the rubric working
   as designed." So for the known case — an answer richer than its single cited excerpt scoring
   unsupported even when the extra detail is true and appears elsewhere in the same paper — the
   mechanism is intended calibration. What looks like an accident is the silence around its
   consequence: nowhere does the wording acknowledge that retrieval shortfall converts into
   `unsupported` mass, folding "the answer drew on material its excerpt lacked" and "the model
   invented something" into one bucket. The sibling rubric explicitly refuses that conflation
   ("This is not an accusation of fabrication — it may be a true fact the answer imported from
   outside the passages"); groundedness inherits the verdict label but not the disclaimer.
   Deliberate mechanism, unmanaged meaning: the rubric's most likely misreading is undefended in
   its own text.
2. **Compound claims over-penalise their grounded half.** With decomposition granularity wobbling
   (Q1 locus 3), one ungrounded detail drags a jointly-extracted claim to `unsupported` wholesale.
   Observed twice in the nine spot-checks (Q-GTA-004, Q-GTA-007) — systematic, and traceable to
   wording rather than judge caprice.
3. **Strength asymmetry is unspecified — variance more than bias.** The calibration examples all
   run passage-weaker-than-answer (hedge→assertion, range→extreme). The reverse case — the
   passage asserts outright, the answer hedges prudently — is uncovered: a strict reader can call
   it a framing mismatch (`unsupported`); a sensible one says the passage entails the answer
   (`supported`). This is precisely the kind of case two careful humans split on.

**Under-penalises:**

4. **Cross-claim inference errors escape** (Q2a): an answer can be wrong in the join between its
   individually-grounded claims and still score clean.
5. **Contradictions can escape via single-passage anchoring.** Nothing obliges the judge to
   examine every supplied passage before concluding absence, and the `contradicted` definition
   lacks any subject-scope requirement — so both false contradictions (wrong-passage comparison,
   observed once at Q-GTA-021) and missed ones are live failure modes. The report's own caution
   applies: the 0.5% contradicted rate "can be too low (a real contradiction reported as none) as
   much as it can be too high."

## Q4. Multi-passage attribution

What the rubric says about multiple passages, exhaustively: the task setup's "one or more
PASSAGES," and the output shape's requirement that each rationale "names the specific passage text
the verdict rests on." That is all. There is no instruction to attribute a claim to the passage it
is actually about, none to examine every supplied passage before concluding that none addresses a
claim, no rule scoping what counts as a conflict when passages describe different things, and no
precedence rule for mixed evidence.

**Rubric gap or judge gap? Primarily a rubric gap, expressed through the judge.** The mechanism is
stated in the rubric's own second paragraph: "`app/judge_eval.py` passes this file's text to
whatever `Judge` it is given, unmodified... Edit it here, not in Python, to change what 'grounded'
means for this measurement." The rubric file *is* the behavioral contract for judging; anything it
omits is delegated to model default. Attribution across several supplied passages is a decision
the judge must make on every multi-passage item, so leaving it unspecified guarantees default-driven
behavior — which is exactly what the run observed: the sole `contradicted` verdict compared a claim
"explicitly about the original paper" against the later SWFormer passage and called it contradicted,
when the original-paper passage stated the claim verbatim. Calling that "a judge gap" would excuse
the very control surface this system designates as owning judging behavior. (A complementary
code-side mitigation exists outside this file — e.g., the harness verifying that a rationale's
quoted text appears in some supplied passage — but that is Python, and this architecture
deliberately puts meaning in the rubric.)

One further point the fix must respect: correct attribution alone would not have saved Q-GTA-021.
The two supplied passages legitimately state *different* splits — different papers describing their
own dataset versions — so a naive any-conflict reading fires even with both passages in view. A
conflict needs a subject-scope test, not just correct attribution; the two amendments have to land
together.
