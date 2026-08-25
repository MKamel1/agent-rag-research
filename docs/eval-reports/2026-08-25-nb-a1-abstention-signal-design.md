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
2. **Two direction-replicating tendencies survive inside the null.** Dense rank-1 cosine came back
   "absent lower" on *both* fixtures with nearly identical AUROC (0.2852 / 0.2851), and cross-arm
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
token exist anywhere?* — which is exactly zero for a truly absent entity regardless of how BM25 ranks
what remains. Different quantity, different layer, uncensused.

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

<!-- NB-A1 commit 3 continues: C4, C5 -->
