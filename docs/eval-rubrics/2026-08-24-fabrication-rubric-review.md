# Fabrication-audit rubric review (2026-08-24)

## Scope and posture

Reviewed `docs/eval-rubrics/fabrication-audit-rubric.md` (48 lines) against its one production run,
`docs/eval-reports/2026-08-23-waymo-fabrication-provisional.md`, and the raw audits beside it
(`fixtures/eval/runs/2026-08-23-waymo-fabrication-audit.absent.json`, 28 claims;
`.answerable.json`, 245 claims). Read-only on all of them; this file is the only thing written.
**This document is input to the operator's sign-off decision, not the sign-off.**

Method limits, same as the sibling review (`2026-08-24-groundedness-rubric-review.md`): one
reviewer, textual analysis only. No second rater, no re-run, no agreement statistics. Where this
review says "two careful readers would diverge," it means the wording admits divergent readings —
the divergence was not measured.

Two checks that bound everything below:

- **The audited text is the text under review.** The absent-arm JSON stamps
  `rubric_sha256_12 = d82bbfa36155`; `sha256sum` of the committed rubric gives the same value, so
  the run numbers cited here were produced under exactly this wording, not an ancestor of it. The
  answerable arm's headline counts (191 / 51 / 3 over 245) were re-derived from the committed JSON
  and match the report.
- **One factual correction to this review's own brief: the rubric carries no PROVISIONAL header.**
  Its entire git history is a single commit (`637b60c`) and no version of it ever had one; the
  worktree, `origin/main`, and the main checkout's copy are byte-identical. The header language the
  brief quotes ("that decision belongs to a human, not to whoever last edited this file") was the
  *sibling* groundedness rubric's former banner — visible at `637b60c`, replaced by its SIGNED OFF
  banner at `c66a1d6`. Consequence worth the operator's attention: every audit report's disclaimer
  says "see the rubric file's own header for sign-off status" — a reference that dangles on this
  rubric, because no such header exists. Its unsigned status currently lives only in the prose of
  the run reports. If the operator amends or signs, adding a sign-off-status header of the kind
  this report format already points readers to would close that gap; per the brief I have not
  touched the rubric either way.

## Q1. Would two careful readers agree?

**On routine claims, yes — more often than under the pre-amendment sibling. On three identifiable
loci, systematically no.**

Where they would agree: the verdict vocabulary is small and each verdict has an anchor sentence;
the `supported` bar is concrete where it matters most ("numbers must match"); and `contradicted`
is defined by the strictest phrase in either rubric ("directly conflicts"). For near-verbatim
claims — most of the answerable arm's 245 — both rubrics bind identically and agreement would be
high.

Where they would diverge:

1. **The lax-calibration hinge is uncalibrated.** `supported` extends to "something a careful
   reader would treat as the same claim," and the only boundary given is "a paraphrase that
   preserves the meaning is fine, a paraphrase that changes the meaning is not." How much drift
   preserves meaning is exactly what careful readers disagree about; nothing bounds it. This is
   the same structural gap the groundedness review found in its undefined "closely enough"
   (its locus 1) — but here it sits inside `supported`, not `unsupported`, and it is partially
   deliberate: strict paraphrase-distance judgment lives in the sibling rubric by design.
   Deliberate looseness is still uncalibrated looseness; the mitigation this rubric does have —
   unsupported claims "retained for human inspection rather than just counted" — softens the
   consequence of a wrong call without removing the disagreement.
2. **Claim decomposition has no split rule.** "(a claim is one checkable assertion …)" defines
   the unit but never forbids averaging: when one sentence contains a part the passages ground
   and a part they do not, nothing tells the judge to split it. The sibling review observed the
   resulting wobble twice in its run (Q-GTA-004, Q-GTA-007); this rubric carries the identical
   silence, word-for-word the definition groundedness used before amendment A2 fixed it there.
3. **Multi-passage items have no attribution rule and no precedence rule.** Same as the sibling's
   locus 4: `supported` and `contradicted` are existential ("the passages state…"), with no duty
   to attribute a claim to the passage it is actually about, none to examine every supplied
   passage before concluding absence, and no subject-scope test for conflict. On this run's
   evidence the concern is not hypothetical — see Q4.

Net: agreement would be high on clear-cut cases and unpredictable exactly where this run actually
failed — borderline paraphrase distance and multi-passage attribution. Both are wording gaps, not
conceptual ones.
