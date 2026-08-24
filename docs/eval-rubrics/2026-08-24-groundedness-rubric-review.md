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
