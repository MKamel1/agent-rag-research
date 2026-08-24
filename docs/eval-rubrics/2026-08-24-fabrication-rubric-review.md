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
