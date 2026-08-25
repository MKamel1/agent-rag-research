# NB-A1 — abstention signal-source design doc (resolves the A-series fork)

Ticket: NB-A1, `docs/superpowers/plans/2026-08-24-next-build-programme.md` §4 Wave 3. Input
verdict it resolves: [`2026-08-25-nb-d3-abstention-census.md`](2026-08-25-nb-d3-abstention-census.md)
("no separation found", 17 features × both fixtures). This document designs NEW abstention signal
sources. **It builds no mechanism**: no threshold, no prompt change, no pipeline edit. Each candidate
carries a falsification criterion fixed *in this document, before any feasibility run*, a concrete
cheap measurement someone could run next, and its failure mode. None is promised to work.

---

## §0 What D3 ruled out, what it didn't, and the two facts that shape this design

**Ruled out (treat as settled):** no *thresholdable* abstention signal exists among retrieval-side
observables of a single retrieval pass — per-arm rank-1 scores, score gaps, arm agreement, top-k
overlap, distinct-paper counts, above-threshold result counts. The two features that looked strong
died the deaths D3 §4 documents: `distinct_papers_fused` (AUROC 0.866 GT-WMR → 0.574 ver84,
failed held-out replication) and query length (replicated, AUROC 0.07–0.13 both fixtures, rejected
as fixture-authoring leakage — it measures how the authors wrote, not what the corpus covers).

**The null's exact scope, sharpened by one structural fact** (verified against source and data):
the shipped pipeline is `embed-query → hybrid → RRF fuse → rerank → resolve`
(`rag/retriever.py` module header), so every score recorded in any run output lives on the
reciprocal-rank scale — the rank-1 value is RRF's 1/(60+1) = 0.016393…, and both fixtures' dense-arm
distributions cap at exactly that ceiling (`docs/eval-reports/data/2026-08-25-nb-d3/census_full.json`,
`fixtures.ver84.arms.dense.*.max` = 0.0163934; gt_wmr identical). **D3 therefore measured the rank
geometry of retrieved lists** — not term-level match content, not embedding-space similarity (no
cosine survives the fuser into any record), not generation-stage behaviour, and nothing beyond one
full-question retrieval per item. The candidate spaces below are exactly those unmeasured residues.

**Not ruled out, and load-bearing for this doc:**

1. **The generation layer has never been measured as a signal source.** D3's 17 features are all
   pre-generation. The one place the system ever behaved differently on absent vs answerable items is
   the refusal-affordance A/B ([`2026-08-24-waymo-refusal-affordance-ab.md`](2026-08-24-waymo-refusal-affordance-ab.md)):
   given permission to refuse and nothing else changed, wrong-side answers on the known-absent arm fell
   **6/16 → 1/16**, at a cost of **one clean regression out of 68 answerable** (`Q-WAYB-026`). Whatever
   quantity the generator uses to decide "these passages don't contain it", D3's features do not
   contain it — otherwise the affordance arm's discrimination could have been read off retrieval scores.
   (That report is PROVISIONAL with unsigned rubrics; this doc cites only its §1–§3 hand
   classifications, which do not depend on rubric sign-off.)
2. **Two direction-replicating tendencies survive inside the null.** The dense-arm rank-1 score came
   back "absent lower" on *both* fixtures with nearly identical AUROC (0.2852 / 0.2851 — on the RRF
   scale per the structural note above, so this is a pure rank-position signal), and cross-arm
   disagreement was right-signed on both (rank-1 agreement 0.40 vs 0.19; `jaccard_fused_dense` 0.38 vs
   0.23). Both are unusable as thresholds at today's operating points — but "no usable cut" is not
   "no information". See Method notes for why this doc still refuses to design composites from them.

**A second axis D3 left open:** every censused feature describes *one* retrieval view of the question
(three fixed arms of one pass). Nothing was measured across *perturbed* views (paraphrases) or at
*index* level ahead of ranking (does the fact-bearing token exist anywhere?). Those are structurally
different observable families, and candidates C2/C3 below live there.

**Applicability of D3's REFRESH-POST-RERANK banner:** retrieval-touching candidates (C2, C3, C5)
inherit it wholesale — their distributions move with fusion weight, pool depth, reranker. The
generation-side candidates (C1, C4) do not: their signal lives above the retrieval layer and survives
stack changes by construction. This is one reason C1 is ordered first in §2.

Candidate selection rationale: the brief's suggested families map to C1 (generation-side),
C2 (pre-retrieval coverage probes), C3+C5 (embedding/retrieval-space features not in the census),
C4 (judge screening). Query-decomposition coverage checks are folded into C3 (multi-part instability
is that family's main failure mode, argued there) rather than spun as a fifth positive candidate;
C5 is retained *as an expected death* with its reasoning written down, per §2's honesty rule.

---

## §1 Candidate signal sources

### C1 — Generation-side behavioural signal: refusal-affordance detector, then sample-consistency

**Mechanism sketch.** One idea, two stages. Stage 1: generate with the existing refusal-affordance
clause (`fixtures/eval/prompts/refusal-affordance.txt`, loaded via `app/generation_capture.py
--prompt-file`; default prompt untouched) and use *"is the answer refusal-shaped"* as the abstention
signal — a post-generation binary detector. Stage 2 (only if stage 1 clears its bar): sample n≈5
answers at moderate temperature and score confidence by cross-sample agreement (numeric/entity overlap
across samples) — behavioural consistency à la SelfCheckGPT, *not* verbalized self-report, which the
A/B gives no reason to trust. Measured at the generation layer; retrieval untouched.

**Why the D3 null does not rule it out.** D3 censused pre-generation observables exclusively. The
generation layer was observed exactly twice (FAB-1 control, affordance arm), both times hand-classified
for a different question ("does the clause help"), never as a per-item separability measurement. The
affordance arm *is* direct evidence of item-level information the retrieval scores lack: permitted to
refuse, the generator refused 14/16 known-absent correctly (5 of FAB-1's 6 wrong-side answers flipped)
while refusing only 3/68 answerable items — one of which (`Q-GTA-033`) was itself trading a fabricated
answer for an honest non-answer. Compare D3's best fresh-run operating points: 11/68 false refusals to
catch 6/14 absent (ver84) and 14/70 for 10/12 (gt_wmr). Nothing in the census approaches a 14-vs-3 split.

**Falsification criterion (fixed before any run).** Write ONE fixed refusal-shape classification rule
first (see measurement); then: on ver84, judged from the *existing committed captures*, refusal-shaped
answers must cover ≥12/16 known-absent items with ≤5 false refusals among 68 answerable; AND on
gt_wmr (no generation capture exists — held-out by construction), from one fresh capture, ≥9/12 with
≤4 false refusals among 70. Either side failing → candidate dropped entirely. No threshold tuning,
prompt rewording, or rubric iteration is permitted to rescue a failure — that is the lesson of D3 §4's
multiple-comparisons accounting, applied to behaviour instead of features. If stage 1 passes, stage 2's
bar (pre-committed now): pairwise-sample-agreement AUROC ≥0.75 ver84 and ≥0.70 gt_wmr.

**Cheap feasibility measurement.** Data source: committed artifacts
`fixtures/eval/runs/2026-08-23-waymo-generation-run.{absent,answerable}.json` (control) and
`fixtures/eval/runs/2026-08-24-waymo-generation-run-affordance.{absent,answerable}.json` (affordance
arm) — 84+84 answers already on disk, zero GPU to classify. Cost: fix the classification rule
(e.g., lead-sentence pattern classes + invented-number check, spot-checked by hand on disagreements),
classify the 84 affordance-arm answers (~30–45 min including spot-checks); then ONE detached
generation pass over gt_wmr's 82 questions with the same clause (~15–25 min GPU, timed by analogy to
the A/B's captured runs). Decision rule: the falsification criterion verbatim; report BOTH fixtures'
tables separately (programme-plan global constraint 10).

**Failure mode it could introduce.** False refusals on answerable questions whose support is present
but partial — already observed once, on `Q-WAYB-026` (materially-correct answer refused outright), and
predictably concentrated in the multi-part/negation strata where verified-84 already collapses
(block-P@1 0.167 / 1/7 per PREC-1 §1). Inherited blindness: `Q-GTA-037` shows the generator treats a
genre-matched wrong-subject passage as answerable; the detector inherits exactly that blind spot.
Secondary cost: stage-2 multiplies generation latency ~5×.

### C2 — Pre-retrieval lexical anchor-coverage probe (index-level, before fusion)

**Mechanism sketch.** Before (or independent of) ranked retrieval, extract the query's high-IDF
discriminating anchors — named entities, numbers with units, rare technical terms — and issue
sparse-only presence queries per anchor against the corpus (reusing `rag/vector_index.py`'s
`_sparse_vector` tokenization against the Qdrant collection with its native IDF modifier; read-only).
Feature: **fraction of anchors with ≥1 corpus hit**, optionally IDF-weighted. Measured at the index
level; does not depend on what ranking later returns.

**Why the D3 null does not rule it out.** D3's sparse features (`top_score_sparse` 0.52/0.45,
`jaccard_fused_sparse` 0.73/0.66 with inconsistent direction) are properties of the *full-query ranked
result*: BM25 saturates happily on the question's residual common words even when the fact-bearing
token is absent corpus-wide. An anchor-level probe asks a different question — *does the specific
token exist anywhere?* — which is exactly zero for a truly absent entity regardless of how ranking
orders what remains. It is also invisible to every recorded score *by construction*: post-fusion
values carry rank information only (§0's structural note), so term-level match content cannot appear
in any quantity the census could compute. Different quantity, different layer, uncensused.

**Leakage guard (adopted from D3 §4's query-length lesson, pre-committed).** The feature must be
per-anchor normalized (a rate, not a count — absent questions being shorter must not be the signal),
and its Spearman correlation with query length is reported alongside every result. |ρ| > 0.8 →
authoring leakage in costume → rejected without further analysis.

**Falsification criterion (fixed before any run).** Hit-rate AUROC ≥0.75 on **both** fixtures
(D3's replication filter applied up front, not post hoc), with the best cut costing ≤10% of the
answerable arm in false refusals while catching ≥50% of absent items; plus the leakage guard above.
Any component failing → family dead, recorded as such.

**Cheap feasibility measurement.** Data source: both fixtures' question files (the same inputs
D3's scripts join, under `docs/eval-reports/data/2026-08-25-nb-d3/` and the fixture JSONs);
anchor extraction is regex-level (capitalized non-initial tokens, `\d+(\.\d+)?\s*<unit>` patterns);
presence checks need Qdrant up (~minutes per fixture by D3's fresh-capture timing, ~3.5 min/fixture).
Total: a small throwaway script (`app/exp_nb_a1_anchor_probe.py` shape, per house convention for
throwaway experiments) + roughly 10 min of compute. Decision rule: the criterion verbatim, both
fixtures reported separately.

**Failure mode it could introduce.** Lexical-mismatch false refusals: the corpus contains the fact
under a synonym or formatting variant (`.31` vs `0.31`, "driverless" vs "autonomous"), the probe sees
zero hits, the system refuses a covered question — worst precisely on numeric questions, the
highest-value stratum. And entity anchors for well-covered subjects (e.g., "Waymo") hit everywhere,
so the signal would live almost entirely in number/rare-term anchors, making anchor-extractor
precision load-bearing.

### C3 — Retrieval stability under meaning-preserving perturbation

**Mechanism sketch.** Retrieve k=10 independently for 2–3 deterministic, template-generated
paraphrases of each question (v1 needs no LLM: strip the interrogative frame, reorder clauses);
measure top-1-paper Jaccard and rank correlation across the variants. Hypothesis: an answerable topic
has a chunk that dominates *every* wording, so variant retrievals agree; an absent topic's top-10 is
driven by arbitrary residual-word matches, so variants disagree. A post-retrieval measurement over
*perturbed* views — an axis no single-pass feature touches.

**Why the D3 null does not rule it out — and honestly, how much it pressures it.** All 17 censused
features describe one retrieval view (or three fixed arms of one pass). Stability across independent
perturbed retrievals is a different observable. But the nearest censused relative is cross-arm
disagreement — three views of one pass — and D3 found it right-signed on both fixtures with
inconsistent magnitude and expensive operating points ("a real but weak tendency"). Paraphrase
stability generalizes that same underlying phenomenon with better-chosen variation; the honest prior
is that it may inherit the weakness. Included because the test is cheap, not because the prior is good.

**Relation to query-decomposition coverage checks** (the brief's suggested family): decomposition =
split the question into atomic subclaims and check each retrieves support. Its distinctive failure
mode is *genuine multi-part questions*, whose parts legitimately retrieve different chunks and look
"uncovered" under naive aggregation — the same stratum where verified-84 collapses (hard/negation,
PREC-1 §1's Q4 strata). Folding that family in here rather than pretending it's independent: its
feasibility question reduces to the same measurement (per-part retrieval agreement) with the same
failure axis.

**Falsification criterion (fixed before any run).** Variant-agreement AUROC ≥0.70 on **both**
fixtures; direction consistent across fixtures; and the C2 leakage guard applies unchanged (|ρ| with
query length >0.8 → reject). Additionally: if per-stratum breakdown shows the effect lives only in
single-passage questions and *inverts* on multi-part ones, record it as a question-type confounder,
not a signal. Any miss → dead.

**Cheap feasibility measurement.** Pure replay over the stored 164 questions:
`app.retrieval_eval.load_questions` unmodified (D3's denominator-preserving trick), 3 retrievals per
question, services up, ~10–15 min detached; analysis offline. Decision rule: criterion verbatim,
both fixtures' tables in the report.

**Failure mode it could introduce.** False abstentions on genuinely multi-part questions — instability
intrinsic to the question type, read as absence — colliding head-on with the exact strata X-H targets.
Second failure: paraphrase templates too timid produce near-identical retrievals, collapsing the
feature into `jaccard_fused_dense` (censused, weak) and wasting the run while looking like a clean
negative.

### C4 — Judge-model sufficiency screening (pre-generation gate)

**Mechanism sketch.** A small local model receives question + top-5 retrieved passages and answers
only "sufficient / insufficient to answer" *before* generation; abstain on insufficient. Differs from
C1: an explicit passage-fit judgment rather than refusal-shaped answer behaviour, firing pre-generation
so unsupported contexts never reach the generator. Same hardware class as the existing judge factory
(`app.judge_llm:factory`, qwen3-14b-16k per the A/B's §4 setup).

**Why the D3 null does not rule it out — with the adjacent evidence stated, not buried.** The census
expressed only numeric retrieval observables; model-read sufficiency is not expressible in them.
But two committed facts pressure this candidate and must shape its falsifier: the claim-level judge
audits are structurally blind to misattribution (A/B §4), and `Q-GTA-037` shows this model family
treats a genre-matched wrong-subject passage as answerable. A screener from the same family may
inherit that exact blindness — its plausible success region is "passages obviously don't address the
asked entities", which is nonetheless a region no D3 feature covers.

**Falsification criterion (fixed before any run).** Screen-insufficient recall ≥9/12 gt_wmr and
≥12/16 ver84 absent items, with ≤5 false screens per fixture's answerable arm; labels joined only
after the protocol line below is written into the run script. PLUS a length-matched control: on the
slice where absent and answerable query-length distributions overlap (D3's own leakage finding makes
this the obvious artifact), separation must persist — otherwise the screener learned question length,
not sufficiency, and it dies as authoring leakage like D3 §4 item 2. Fail either → dead.

**Cheap feasibility measurement.** One screening pass over both fixtures' 164 questions (short
prompts; ~20–40 min GPU detached by analogy to the generation captures), labels from the fixture
JSONs, output to a report JSON only — no pipeline change. Decision rule: the criterion verbatim,
both fixtures reported separately.

**Failure mode it could introduce.** Correlated false screens with the generator on hard/negation
strata — a double loss where the question loses its answer *and* the abstention error budget spends
itself on answerable items; plus self-evaluation bias (screener and generator closely related models),
the caveat both FAB reports carry. Also prompt-sensitivity: a screening clause is a prompt change by
another name, so during measurement it must stay in experiment harnesses (`app/exp_*`), never a
shipped default.

### C5 — Embedding-space relative-density features (expected to die; retained deliberately)

**Mechanism sketch.** Quantities of dense cosine space that no stored record contains (§0's structural
note: RRF leaves only ranks downstream, so these require reading Qdrant vectors directly, bypassing
fusion — legitimate for a measurement, impossible from replay): (a) *neighbourhood protrusion* =
mean cosine(query, ranks 1–3) − mean cosine(query, a random-10 corpus baseline) — how far the local
neighbourhood sticks out of ambient corpus density; (b) absolute query→corpus-centroid distance;
(c) mass decay = cos(rank-1) − mean(cos ranks 8–10) computed at k=100 depth rather than the shipped 10.

**Why the D3 null probably DOES rule most of it out — said plainly.** The fresh-run features were the
census's closest approach to profile *shape*, and they came back flat: rank1→rank2 gap AUROC
0.39/0.47, above-half-of-rank-1 counts 0.51/0.50 — degenerate partly *because* recorded scores are
rank-scale (half of 1/61 sits near rank 8, so the feature barely varies). That degeneracy means D3
never actually tested similarity-magnitude shape — but what it did measure of the dense arm
(direction-replicating at 0.285/0.285 yet unusable at every cut) argues the magnitude axis is weak
too. Prior: strongly negative. Retained because (a) k=100-depth decay and the random-baseline
contrast are genuinely unmeasured, (b) writing the expected death down is cheaper than a future
session rediscovering this family optimistically, and (c) if C1/C2 fail, this is the family a
next session will reach for anyway — better reached with the falsifier below.

**Falsification criterion (fixed before any run).** Deliberately high, per D3 §4's
multiple-comparisons reality (17 features × 2 fixtures produced 0.87-class outliers under the global
null): any of (a)/(b)/(c) must reach AUROC ≥0.80 on ver84 AND ≥0.75 held-out on gt_wmr, with best-cut
false refusals ≤10% of the answerable arm. Below that → the whole family closes permanently, recorded
as such in this doc's successor.

**Cheap feasibility measurement.** One capture script reading Qdrant directly (dense vectors +
cosine, k=100, plus a random-10 baseline sample per query), over 164 questions, services up;
~15–20 min including the baseline sampling; analysis offline. Decision rule: the criterion verbatim.

**Failure mode it could introduce** (if built on despite a negative): threshold drift with every
embedding-model or stack change — the worst REFRESH-POST-RERANK offender of the five candidates,
since raw-cosine geometry moves on any model swap or re-embed, silently rotting any calibration.

## §2 Method notes

- **Framing refinement** (stated because the ticket framing compresses it): D3 establishes *no usable
  threshold on retrieval-side observables*, not *no information anywhere* — its own tables retain two
  direction-replicating tendencies (dense-arm rank score 0.285/0.285; cross-arm disagreement
  right-signed both fixtures). This doc's mandate is new signal SOURCES; combining weak features into
  a calibrated composite is mechanism-building and belongs to a later A-series ticket, deliberately
  not designed here.
- **Concurrent-dispatch reconciliation**: while this document was being written, a parallel dispatch
  committed its own §0 framing to this branch (`3e58300`, between stub `3afae04` and this doc's
  commit 2), which this doc's full-file write initially overwrote. Its two substantive,
  independently verifiable findings are incorporated above with credit: the RRF rank-geometry
  observation (verified against `rag/retriever.py`'s header and `census_full.json`'s dense-arm max =
  1/61 exactly — this doc originally mislabeled the dense-arm score as cosine) and the fixture-
  denominator discipline below. Nothing else of substance was lost; candidate numbering follows this
  doc's, not that skeleton's.
- **Denominator discipline across sources**: D3 partitions dedup (`load_questions`) → ver84
  68 answerable / 14 absent, gt_wmr 70 / 12; the refusal-affordance A/B used the raw 84-row fixture
  → 68 / 16. Candidate bars in §1 state which convention they use; anyone executing the
  feasibility measurements must not mix them within one table.
- **Provisional-source posture**: the A/B report is PROVISIONAL (unsigned rubrics); this doc cites
  only its §1–§3 hand classifications, which do not depend on rubric sign-off, never its §4
  judge-derived rates.
- **Refresh caveat scope**: candidates C2/C3/C5 inherit D3's REFRESH-POST-RERANK banner wholesale;
  C1/C4 live above the retrieval layer and survive stack changes by construction — one reason §3
  orders them first.
- **What was actually run for this doc**: verification reads only (`rag/retriever.py` module header;
  `docs/eval-reports/data/2026-08-25-nb-d3/census_full.json` max-score values via a throwaway
  interpreter session, not committed as a script). No feasibility measurement was executed; every
  falsifier in §1 was fixed in this file before any of them could run. Cost estimates extrapolate
  D3/A-B logged timings (~3.5 min/fixture capture; generation passes ~15–25 min) — treat ±50%.
- **Compliance**: fixtures reported separately everywhere; no foundation path touched
  (`contracts/`, `migrations/`, `fixtures/`, `rag/config.py`, `ci/`, `.github/`, `pyproject.toml`);
  no other ticket's files touched; no mechanism, threshold, or prompt changed. Doc-only diff —
  nothing for `ruff` to check beyond the tree staying clean.

## §3 Recommendation ordering — which candidate to falsify first

1. **C1 stage-1 (refusal-affordance detector) — falsify first.** Half its feasibility evidence
   already exists committed and free (both generation captures under `fixtures/eval/runs/`); its
   measured operating point (14/16 detected vs 3/68 false refusals) dominates every census operating
   point by roughly an order of magnitude; and it is the only candidate whose signal survives
   retrieval-stack changes (REFRESH-POST-RERANK does not reach it). Cheapest decisive test in this
   document: classify existing captures (~30–45 min) + one fresh gt_wmr pass (~15–25 min).
2. **C2 (anchor-coverage probe) — second.** Cheapest genuinely NEW mechanism (minutes, read-only),
   orthogonal to everything censused *by construction* (term-level content cannot appear in
   rank-scale records), and it carries its anti-leakage guard pre-committed rather than hoped for.
3. **C3 (perturbation stability) — third.** Cheap, but it generalizes D3's weakest finding
   (cross-arm disagreement: right-signed, inconsistent magnitude); run it if C2 dies, expecting it
   to inherit the weakness.
4. **C4 (judge screening) — fourth.** Costlier than 1–3, carries correlated-blindness risk with the
   generator family, and overlaps C1's success region — if C1 clears its bar, C4 is redundant
   complexity; only worth running if C1 fails AND the failure mode suggests explicit passage-fit
   judgment would behave differently from answer-shaped behaviour.
5. **C5 (embedding relative-density) — last, likely never.** Adjacent to the null, bar set high on
   purpose, expected outcome is permanent closure of the family; run only if everything above died
   and the operator wants the space formally closed.

**Honest bottom line.** If C1 stage-1 fails its held-out gt_wmr criterion, this doc's prediction is
that abstention parity is blocked on generation-model capability, not on retrieval engineering — and
candidates 2–5 are ordered attempts to avoid that conclusion, not expectations of escaping it. The
programme fork then resolves toward the A/B report's own reading: the affordable abstention win may
be the *unconditional* affordance clause (already measured: 6/16 → 1/16 wrong-side at one clean
answerable-arm regression), with any detector on top treated as upside, not prerequisite.
