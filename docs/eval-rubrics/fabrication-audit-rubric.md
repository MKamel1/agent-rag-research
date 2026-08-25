# Fabrication-audit rubric (RI-M2)

Read by a judge model, not by code. `app/judge_eval.py` passes this file's text to whatever
`Judge` it is given as-is; editing this file changes what gets measured without touching any
module. It is an operator-owned artifact, same posture as a prompt template: read it, sharpen it,
disagree with it, and change it here.

**A judge model is itself fallible.** Every rate this rubric produces is one instrument's reading,
not ground truth. Treat disagreement between the judge and a human spot-check as useful signal
about the rubric or the judge, not as proof the number is wrong.

> **SIGNED OFF 2026-08-25, with amendments — this wording is now the baseline definition of the
> fabrication audit.** The operator reviewed
> `2026-08-24-fabrication-rubric-review.md` (independent ox-alpha review, verdict **"sign with
> amendments"**) and directed that its three amendments be applied after verification; each was
> checked before application: F-A1 and F-A3 are faithful ports of the sibling groundedness rubric's
> A2 split clause and A6 "Several passages" section respectively (both already signed and in
> production there), F-A2's subject-binding was verified against the run evidence the review cites
> (`Q-GTA-037`, `Q-GTA-040`), and all three "Current:" quotes matched this file byte-for-byte at
> `d82bbfa36155` — the same hash stamped on the 2026-08-23 run.
>
> **The 2026-08-23 run's numbers do not carry across.** Amending the text changes the rubric hash,
> so by the reports' own rule one re-run is owed under this wording before any fabrication-audit
> number is treated as a trend. Deliberately NOT ported from the sibling: its A4/A5 strictness
> (element-level enumeration, the "weaker or narrower" hinge) — the calibration gap between the two
> rubrics is designed, and flattening it would destroy the pair's measurement value.

## Task

You will be given:
- a QUESTION,
- one or more PASSAGES (the only source of truth for this task — not your own knowledge),
- an ANSWER that was generated in response to the question, allegedly grounded in those passages.

Break the ANSWER into its individual factual claims (a claim is one checkable assertion — a
number, a named result, a stated mechanism, a causal or comparative claim, a definition), splitting
finely enough that each verdict rests on exactly one assertion: when one sentence contains a part
the passages ground and a part they do not, split it and record the parts as separate claims — a
single verdict must never average over parts that would score differently. For each claim, decide:

- **supported** — the passages state this claim, or something a careful reader would treat as the
  same claim (numbers must match; a paraphrase that preserves the meaning is fine, a paraphrase
  that changes the meaning is not). A claim includes the entity it is asserted about: extract and
  record it with its subject attached — "Waymo uses 905 nm sensors", never "905 nm sensors are
  commonly used" — and mark `supported` only if some passage states that same subject-and-content
  pair. A passage that states the content about a different entity does not support the claim.
- **unsupported** — the passages say nothing that confirms or denies this claim. This is not an
  accusation of fabrication — it may be a true fact the answer imported from outside the passages,
  or genuine model invention. The rubric cannot tell those apart from the text alone; that is why
  unsupported claims are retained for human inspection rather than just counted.
- **contradicted** — the passages state something that directly conflicts with this claim (a
  different number, an opposite direction, a denied mechanism).

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

For each claim, give:
1. the claim's own text (a short quote or tight paraphrase of the part of the ANSWER it comes
   from),
2. the verdict (`supported` / `unsupported` / `contradicted`),
3. a one- to two-sentence rationale that names the specific passage text your verdict rests on
   (or states plainly that no passage addresses it, for `unsupported`).

## What this rubric is not

- Not a grammar or fluency check — an awkward but accurate claim is `supported`.
- Not a completeness check — an answer that omits something true in the passages is not
  penalized here; that is a different question from whether what it *does* say is grounded.
- Not a judgment about whether the ANSWER is a *good* answer to the QUESTION — a claim can be
  perfectly supported and still not address what was asked. This rubric only audits grounding.
