# Fabrication-audit rubric (RI-M2)

Read by a judge model, not by code. `app/judge_eval.py` passes this file's text to whatever
`Judge` it is given as-is; editing this file changes what gets measured without touching any
module. It is an operator-owned artifact, same posture as a prompt template: read it, sharpen it,
disagree with it, and change it here.

**A judge model is itself fallible.** Every rate this rubric produces is one instrument's reading,
not ground truth. Treat disagreement between the judge and a human spot-check as useful signal
about the rubric or the judge, not as proof the number is wrong.

## Task

You will be given:
- a QUESTION,
- one or more PASSAGES (the only source of truth for this task — not your own knowledge),
- an ANSWER that was generated in response to the question, allegedly grounded in those passages.

Break the ANSWER into its individual factual claims (a claim is one checkable assertion — a
number, a named result, a stated mechanism, a causal or comparative claim, a definition). For each
claim, decide:

- **supported** — the passages state this claim, or something a careful reader would treat as the
  same claim (numbers must match; a paraphrase that preserves the meaning is fine, a paraphrase
  that changes the meaning is not).
- **unsupported** — the passages say nothing that confirms or denies this claim. This is not an
  accusation of fabrication — it may be a true fact the answer imported from outside the passages,
  or genuine model invention. The rubric cannot tell those apart from the text alone; that is why
  unsupported claims are retained for human inspection rather than just counted.
- **contradicted** — the passages state something that directly conflicts with this claim (a
  different number, an opposite direction, a denied mechanism).

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
