# Groundedness rubric (RI-M6)

> **PROVISIONAL — not a baseline.** Nobody has signed off on this rubric yet (see
> `docs/superpowers/plans/2026-08-22-review-implementation.md` wave 4, "operator decisions" item
> 6: "RI-M6 judge rubric sign-off"). Do not treat any report produced under this rubric as a
> baseline for future comparisons until an operator has reviewed and approved this file's wording.
> A rubric silently becomes the definition of "good" for every future run once it is accepted as
> one — that decision belongs to a human, not to whoever last edited this file.

Read by a judge model, not by code — same mechanism as the fabrication-audit rubric
(`fabrication-audit-rubric.md`): `app/judge_eval.py` passes this file's text to whatever `Judge`
it is given, unmodified. Edit it here, not in Python, to change what "grounded" means for this
measurement.

**A judge model is itself fallible.** Every rate this rubric produces is one instrument's reading
of groundedness, not ground truth about the answer's quality.

## Task

You will be given the same three inputs as the fabrication-audit rubric: a QUESTION, one or more
PASSAGES, and an ANSWER. Where the fabrication-audit rubric asks "is each claim contradicted,
supported, or simply unaddressed by the passages," this rubric asks the stricter question: **is
the ANSWER's own reasoning traceable to the PASSAGES**, not merely non-contradictory with them.

Break the ANSWER into its individual claims, as in the fabrication-audit rubric, and give each one
of the same three verdicts:

- **supported** — a passage states this claim AND the answer's framing of it (the specific
  numbers, the direction of an effect, the named mechanism) matches what the passage actually
  says, not a plausible-sounding neighbor of it.
- **unsupported** — no passage addresses this claim closely enough to ground it, even if the
  claim happens to be true in general.
- **contradicted** — a passage states something that conflicts with this claim.

The difference from the fabrication-audit rubric is calibration, not the verdict vocabulary: apply
a stricter reading of "supported" here — a claim that a fabrication audit would wave through as a
reasonable paraphrase should be marked `unsupported` under this rubric if the passage's own wording
is meaningfully looser or narrower than the answer's framing of it (e.g. the passage hedges with
"may" and the answer asserts it outright; the passage gives a range and the answer picks the
extreme; the passage is about a related-but-different quantity).

## Output shape

Identical to the fabrication-audit rubric: for each claim, its text, verdict, and a rationale that
names the specific passage text the verdict rests on.

## What this rubric is not

- Not a second fabrication audit under a different name — if this rubric and the fabrication-audit
  rubric produce very similar rates on the same items, that is worth noticing (it may mean the
  stricter calibration above isn't actually stricter in practice, and should be revised).
- Not a completeness or answer-quality check, for the same reasons stated in the fabrication-audit
  rubric.
