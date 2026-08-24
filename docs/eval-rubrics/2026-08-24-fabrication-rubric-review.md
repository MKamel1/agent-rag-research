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

## Q2. Does it measure what its name says?

The name is *fabrication audit*. What the procedure operationalizes is per-claim support against
the supplied excerpts: is each claim stated by the passages, denied by them, or untouched by them.

**Partially — and the name-vs-measurement gap runs in the opposite direction from the sibling's.**
Groundedness promised "reasoning" and delivered claims; this rubric promises *fabrication*
detection and delivers neither of the two things a reader most plausibly means by the word:

- **Invention is detected only as an undifferentiated subset.** The rubric says so itself:
  `unsupported` "is not an accusation of fabrication — it may be a true fact the answer imported
  from outside the passages, or genuine model invention. The rubric cannot tell those apart."
  That is an honest disclaimer — better than the sibling's pre-amendment silence on the same fold —
  but it concedes that the headline verb of the rubric's own title is not what the instrument
  measures.
- **Misattribution — real retrieved text attached to the wrong subject — is not merely missed; it
  scores `supported`, by construction**, whenever the extracted claim does not carry its subject.
  The run receipts are in Q4. The failure mode this corpus actually exhibits dominantly (3 of 6
  wrong-side answers) is invisible to the construct as worded.

What it does measure cleanly is claim-level grounding against the excerpt set — a coherent,
useful construct, and the right lax pole underneath groundedness's strict one ("the difference
from the fabrication-audit rubric is calibration," as the sibling puts it). The defect is naming,
and it is the sibling's Q2b problem again: a headline number that requires paragraphs of defense
in its own run report (§1: "looks like good news and is not"; the whole of §2 exists to
reinterpret §1) has a naming problem. Renaming is not proposed here — the rubric id
(`fabrication-audit-rubric.md`, RI-M2) is referenced by code paths and reports — but the operator
should know that "0.71 fabricated... sorry, supported" will keep needing that defense until
either the name narrows or the wording closes the misattribution blind spot (F-A2 below).

## Q3. What does it systematically over- or under-penalise?

**Over-penalises:**

1. **Richer answers against thin excerpts — intended, and unusually well managed in text.**
   Excerpt-relative judging folds "true, but stated elsewhere" into `unsupported`; unlike the
   pre-amendment sibling, this rubric defends the fold explicitly ("not an accusation of
   fabrication…") and routes the consequence somewhere useful — unsupported claims "are retained
   for human inspection rather than just counted." Deliberate mechanism, managed meaning. No
   amendment needed; this is one place this rubric is *ahead of* where its sibling was.
2. **Compound claims over-penalise their grounded half.** With no split rule (Q1 locus 2), one
   ungrounded detail drags a jointly-extracted claim to `unsupported` wholesale. Inherited
   defect, observed twice in the sibling run; nothing in this run contradicts the inheritance.

**Under-penalises:**

3. **Subject-swapped real text escapes entirely.** The run's central finding restated in rubric
   terms: `supported` fires on "the passages state this claim," and nothing requires the claim to
   be extracted with the entity it is asserted about. `Q-GTA-037` ("905 nm", whose only corpus
   source is a laser tutorial that never mentions Waymo) and `Q-GTA-040` (Swiss Re as underwriter;
   zero corpus chunks contain `underwrit` and `swiss re`) scored **fully supported** and appear
   nowhere in the absent arm's `unsupported_claims` — the instrument's only output channel for
   suspicion. This is the systematic under-penalisation, and it is structural (wording), not
   judge caprice.
4. **Cross-claim inference leaps escape unless packed into one claim** — same shape the sibling
   review called Q2a. The harness audits assertions, never the join between them;
   `Q-WAYB-021`'s "0 pedestrian, 0 cyclist, and 0 vehicle-occupant fatalities" leap was caught
   only because the judge happened to extract the leap itself as a claim (and then scored it
   `unsupported`).
5. **Contradictions can escape or misfire via single-passage anchoring.** No examine-every-passage
   duty, no subject-scope conflict test. The absent arm's 0.000 `contradicted` is therefore as
   consistent with "no conflicts exist" as with "conflicts were sought against the wrong
   passage." The sibling report's caution transfers verbatim: a zero rate "can be too low (a real
   contradiction reported as none) as much as it can be too high."

## Q4. Should this rubric catch subject-misattribution?

**Direct answer: yes — it is legitimately within this rubric's scope, and it is the one defect
this review would hold sign-off hostage on. But catching it here does not make this rubric the
abstention instrument, and the two must not be conflated.**

Why it is in scope: misattribution is not a new judgment category — it is the existing
`supported` test applied to a *whole* claim. "Waymo uses 905 nm sensors" is simply not stated by
any passage; the passages state a different claim (a generic industry wavelength, in a paper that
never mentions Waymo). By the rubric's own definition — "**supported** — the passages state this
claim" — a subject-swapped claim is not supported; it belongs in `unsupported`, retained for
human inspection like every other unsupported claim. Nothing new is being asked of the judge:
only that the claim be extracted *with* its subject, so that "the passages state this claim"
has an unambiguous referent. Today the wording never binds subject to claim, so the judge can
audit a subject-stripped fragment ("905 nm sensors are commonly used") and score it supported,
correctly, while the answer's actual assertion sails through. That is how `Q-GTA-037` and
`Q-GTA-040` scored fully supported and left no trace in `unsupported_claims` — the instrument's
only channel for suspicion.

The run also shows the instrument is not hopeless even as worded, which sharpens rather than
softens the finding: **4 of the 6 wrong-side answers did produce `unsupported` claims** —
`Q-WAYB-021`'s fatality leap, `Q-WAYB-022`'s invented 0.18, both `Q-WAYB-028` claims, and,
notably, `Q-WAYB-035`: although the report lists it among the three misattributions, the judge
actually marked its claim `unsupported` with the rationale "The passage mentions a 65% reduction
… for Waymo, not Cruise." Exactly two passed through clean — the two whose answers phrased the
assertion without carrying its subject into the audited claim. (`Q-GTA-040`'s precise mechanism
cannot be verified from the committed artifacts — only `unsupported_claims` are itemized — but
both candidate mechanisms, subject-stripped extraction and compound-claim averaging, are closed
by F-A1/F-A2 below.) The human-inspection loop already works where the wording lets the judge
see the problem; the amendments extend the same net over the blind spot instead of adding a new
instrument.

What even an amended rubric cannot do, said plainly:

- **It cannot be the abstention signal.** It audits claims against supplied excerpts; a
  fully-supported rate on questions the corpus cannot answer remains possible, because retrieved
  text about adjacent subjects grounds many true-but-irrelevant claims — most of the absent arm's
  20/28 supported are exactly that. Whether the system should have answered at all lives
  upstream: the generation prompt's missing refusal affordance (report §4) and any retrieval-side
  answerability signal. Different instruments, complementary jobs; this rubric should catch the
  misattributed *claim*, not be blamed for the unrefused *answer*.
- **Wording is not compliance.** Whether qwen3-14b obeys the amended text is unknown until a
  re-run; nothing was re-run here.

## Recommendation

**Sign with amendments.**

One-line reason: the verdict vocabulary, the fallibility framing, the imported-vs-invented
disclaimer with its human-inspection loop, and the deliberately lax calibration that gives the
strict sibling its contrast class are all sound — but the wording's silence on claim subjects and
multi-passage attribution let 2 of this run's 6 wrong-side answers score fully supported
invisibly, and closing that costs three paste-in amendments whose wording is already proven in
the sibling review.

Where I would sign as-is: the three-verdict vocabulary and its definitions' core; "numbers must
match"; `contradicted`'s "directly conflicts"; the disclaimer that refuses to call `unsupported`
an accusation of fabrication, plus retaining unsupported claims for human inspection; the
fallibility header; the output-shape requirement to cite passage text; and the deliberate laxness
itself — it is the designed counterweight that makes the sibling's stricter calibration
measurable.

Where I would not sign: no split rule for compound claims; nothing binding a claim's subject to
the claim; total silence on multi-passage attribution, conflict scoping, and mixed-evidence
precedence; and the dangling reference every audit report makes to "the rubric file's own header
for sign-off status," which this file does not have.

### Amendments (exact replacement wording)

Three amendments, each given as location plus paste-in replacement. None touches calibration:
paraphrase tolerance, hedge tolerance, and the lax pole itself are left exactly as they are —
that is deliberate design, and flattening it into the sibling would destroy the pair's
measurement value. None removes or softens any existing line other than the two sentences named.

**F-A1 — Task, replace the decomposition sentence** (kills compound-claim averaging; ports the
sibling's A2 clause onto this rubric's own sentence):

> Current: "Break the ANSWER into its individual factual claims (a claim is one checkable
> assertion — a number, a named result, a stated mechanism, a causal or comparative claim, a
> definition). For each claim, decide:"

> Replacement: "Break the ANSWER into its individual factual claims (a claim is one checkable
> assertion — a number, a named result, a stated mechanism, a causal or comparative claim, a
> definition), splitting finely enough that each verdict rests on exactly one assertion: when one
> sentence contains a part the passages ground and a part they do not, split it and record the
> parts as separate claims — a single verdict must never average over parts that would score
> differently. For each claim, decide:"

**F-A2 — Task, replace the `supported` bullet** (binds each claim to its subject — closes the
misattribution blind spot without importing the sibling's strictness):

> Current: "- **supported** — the passages state this claim, or something a careful reader would
> treat as the same claim (numbers must match; a paraphrase that preserves the meaning is fine, a
> paraphrase that changes the meaning is not)."

> Replacement: "- **supported** — the passages state this claim, or something a careful reader
> would treat as the same claim (numbers must match; a paraphrase that preserves the meaning is
> fine, a paraphrase that changes the meaning is not). A claim includes the entity it is asserted
> about: extract and record it with its subject attached — \"Waymo uses 905 nm sensors\", never
> \"905 nm sensors are commonly used\" — and mark `supported` only if some passage states that
> same subject-and-content pair. A passage that states the content about a different entity does
> not support the claim."

**F-A3 — insert a new subsection between the Task list and "## Output shape"** (verbatim port of
the sibling's A6, which was written against this shared task shape):

> "## Several passages
>
> When several PASSAGES are supplied, attribute before you verdict. For each claim, work out
> which passage it is actually about: a claim that names a specific paper, study, table, or
> figure belongs to the passage carrying that identity, whichever position it holds in the list.
> Examine every supplied passage before concluding that none grounds or addresses a claim. A
> passage conflicts with a claim only if it speaks to the claim's own subject — two sources
> reporting different numbers about their own versions of a thing do not conflict with a claim
> scoped to one of them. If one passage supports a claim and another genuinely conflicts with it
> within the claim's scope, mark `contradicted` and name both passages in the rationale."

**Deliberately NOT proposed:** porting the sibling's A4 (element-level `unsupported`
enumeration) or A5 (the "weaker or narrower" hinge). Both tighten paraphrase distance — the
strict sibling's job. Copying them across would flatten the calibration difference that makes
running both rubrics worth doing.

Operator-side notes, outside this review's write authority: (1) when acting on this decision,
add the sign-off-status header this rubric lacks — every audit report already points readers to
it; (2) applying any amendment changes the `rubric_sha256_12` stamp, so by the reports' own rule
the 2026-08-23 numbers become non-comparable and one re-run is owed before any number is treated
as a trend — the same sequencing note the sibling sign-off carries.

## What this review could not assess

- **Empirical inter-reader agreement.** Single reviewer, textual analysis only; no second human
  rater, no agreement statistic. Divergence claims are about what the wording admits, not what
  readers did.
- **Whether qwen3-14b complies with F-A1–F-A3.** Nothing was re-run; the amendments are judged
  on their text, not on judge behavior under them.
- **The exact claims behind `Q-GTA-037`'s and `Q-GTA-040`'s `supported` verdicts.** The audit
  JSONs itemize only `unsupported_claims`; which subject-stripped or compound claim each answer's
  supported mass rests on is inferred from those lists plus the report's §2 hand-read, not read
  off an artifact.
- **Independent re-adjudication of the run.** The report's hand classification of the six
  wrong-side answers and its corpus-wide string checks (`905 nm`, `underwrit` + `swiss re`) are
  cited as evidence, not replicated against `papers.db`. Headline counts *were* re-derived from
  both committed JSONs and match.
- **Uncommitted state of the other session's checkout beyond this one file** — the rubric was
  diffed byte-for-byte against the worktree (identical), but nothing else in the main checkout
  was compared.
