# Groundedness rubric (RI-M6)

> **SIGNED OFF 2026-08-24 — this wording is now the baseline definition of "grounded".**
> The operator delegated the decision to an independent review by ox-alpha via opencode, with the
> instruction to sign off on that basis. That review
> (`2026-08-24-groundedness-rubric-review.md`) returned **"sign with amendments"** and supplied six
> amendments as exact replacement wording; all six are applied here, plus the review's optional
> companion where its anchor existed. Reviewer verification: the three misverdicts the review cites
> as evidence (`Q-GTA-004`, `Q-GTA-007`, `Q-GTA-021`) were each checked against the committed run
> JSON and reproduce.
>
> **The 2026-08-23 run's numbers do not carry across.** Amending the text changes the rubric hash
> the reports stamp, so by those reports' own rule the earlier rates are not comparable to anything
> produced under this version. One re-run is owed before any number is treated as a trend.
>
> **A rubric silently becomes the definition of "good" for every future run.** Changing this file
> again invalidates every comparison made under it — do so deliberately, with a dated note, not as
> a passing edit.

Read by a judge model, not by code — same mechanism as the fabrication-audit rubric
(`fabrication-audit-rubric.md`): `app/judge_eval.py` passes this file's text to whatever `Judge`
it is given, unmodified. Edit it here, not in Python, to change what "grounded" means for this
measurement.

**A judge model is itself fallible.** Every rate this rubric produces is one instrument's reading
of groundedness, not ground truth about the answer's quality.

## Task

You will be given the same three inputs as the fabrication-audit rubric: a QUESTION, one or more
PASSAGES, and an ANSWER. Where the fabrication-audit rubric asks "is each claim contradicted,
supported, or simply unaddressed by the passages," this rubric asks the stricter question: **whether each of the
ANSWER's claims, and the framing the answer applies to it, is traceable to the PASSAGES** -- the
PASSAGES are the only source of truth for this task, not your own knowledge -- rather than merely
non-contradictory with them.

Break the ANSWER into its individual claims, as in the fabrication-audit rubric (a claim is one
checkable assertion), splitting finely enough that each verdict rests on exactly one assertion:
when one sentence contains a part the passages ground and a part they do not, split it and record
the parts as separate claims -- a single verdict must never average over parts that would score
differently. Give each claim one of the same three verdicts:

- **supported** — a passage states this claim AND the answer's framing of it (the specific
  numbers, the direction of an effect, the named mechanism) matches what the passage actually
  says, not a plausible-sounding neighbor of it. Passage strength may exceed answer strength: a
  passage that asserts outright grounds an answer that merely hedges the same proposition. The
  strict reading catches answers that overshoot their passage, never answers that undershoot it.
- **unsupported** — some element the answer asserts (a specific number, a direction, a mechanism,
  a hedge level, or the claim's subject) is absent from every supplied passage, so no supplied
  passage grounds it — even if the claim happens to be true in general or elsewhere in the same
  source.
- **contradicted** — a passage states something that conflicts with this claim.

The difference from the fabrication-audit rubric is calibration, not the verdict vocabulary: apply
a stricter reading of "supported" here — a claim that a fabrication audit would wave through as a
reasonable paraphrase should be marked `unsupported` under this rubric if the passage's own wording
is weaker or narrower than the answer's framing of it — the answer claiming more certainty, more
precision, or a broader subject than the passage supports (e.g. the passage hedges with
"may" and the answer asserts it outright; the passage gives a range and the answer picks the
extreme; the passage is about a related-but-different quantity).

## Several passages

When several PASSAGES are supplied, attribute before you verdict. For each claim, work out which
passage it is actually about: a claim that names a specific paper, study, table, or figure belongs
to the passage carrying that identity, whichever position it holds in the list. Examine every
supplied passage before concluding that none grounds or addresses a claim. A passage conflicts with
a claim only if it speaks to the claim's own subject — two sources reporting different numbers about
their own versions of a thing do not conflict with a claim scoped to one of them. If one passage
supports a claim and another genuinely conflicts with it within the claim's scope, mark
`contradicted` and name both passages in the rationale.

## Output shape

Identical to the fabrication-audit rubric: for each claim, its text, verdict, and a rationale that
names the specific passage text the verdict rests on.

## What this rubric is not

- Not a second fabrication audit under a different name — if this rubric and the fabrication-audit
  rubric produce very similar rates on the same items, that is worth noticing (it may mean the
  stricter calibration above isn't actually stricter in practice, and should be revised).
- Not a completeness or answer-quality check, for the same reasons stated in the fabrication-audit
  rubric.
