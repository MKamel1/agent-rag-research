# NB-B0 — benchmark audit: do we have the RIGHT benchmarks for a 0.95-precision + agentic-RAG push?

Written 2026-08-25, branch `NB-B0-benchmark-audit`. **Read-only audit.** No fixture was edited, no
pipeline code touched, no new eval item authored, no retrieval re-run. Every number below is either
quoted from a committed report (cited inline) or recomputed read-only from the committed fixtures and
stored run records (`fixtures/eval/*.json`, `docs/eval-reports/data/2026-08-23-waymo-priority/*.json`)
via one-off inspection scripts that were not retained — each such computation is stated so it can be
re-derived in seconds. Deliverable: this document, §1–§4.

Question of record: before any optimization toward the operator's **precision ≥ 0.95 + agentic-RAG**
goal — do the instruments this repo actually owns support an *honest* 0.95 claim, and what benchmark
authoring is missing for the agentic half?

## Method notes

**Binding house rules applied throughout:**

- **Lessons §7.2** (`docs/AGENT-OPERATIONS-LESSONS.md`): every metric definition endorsed here
  carries its achievability bound as explicit arithmetic, computed from committed data, before any
  recommendation — "a frozen metric needs an achievability bound computed at freeze time". The P@10
  gate failure (below) is the cautionary tale this audit refuses to repeat in the other direction:
  we will not endorse a 0.95 target on any metric whose ceiling arithmetic has not been shown.
- **PREC-1 §5** (`2026-08-24-passage-precision-diagnosis.md`): block-P@1 is fixture-conditioned;
  `waymo_gt_verified.json` and `gt_wmr.json` are *structurally different instruments*, not two
  samples of one thing. Nothing below averages, compares across, or trades between them. Every count
  carries its denominator.

**Pre-committed verdict rubric** (fixed before §1 was written, so the audit cannot move goalposts
mid-report): an instrument is

- **SOUND** for a 0.95 claim iff its computed achievability bound is ≥ 0.95 in its shipped shape;
- **CONDITIONAL** iff the bound reaches 0.95 only under stated dependencies (a named config variant,
  a named upstream fix, or as a companion to a primary metric);
- **UNSOUND** iff it is structurally incapable of 0.95 under every reading (bound < 0.95 even under
  perfect execution), or if it does not measure what a "precision" claim needs.

**Three data corrections to the ticket brief** (data wins, per the NB-D3 precedent of checking
denominators against the loader rather than the brief):

1. **verified-84 scored denominators**: the file holds 84 items (68 answerable / 16 absent, incl.
   4 vision-derived). Both `duplicate_of` rows sit in the **absent arm** (Q-GTA-036/037 duplicate
   Q-WAYB-034/Q-WAYB-009), so after `load_questions` dedup the scored population is **82 =
   68 answerable / 14 absent** — the partition every stored run record and NB-D3 uses.
2. **Multi-paper exposure, precisely** (matters for §3): at paper level (`gold_paper_ids > 1` in the
   run records) ver84 exposes **9** items — 5 of them passage-scored; gt_wmr exposes **4**
   (Q-WMR-090..093) — **0** passage-scored, because those four carry `supporting_passages` but no
   single gold block. The brief's "~5 exposed / 0 scored" describes the passage-scored slice; the
   fuller counts are the honest denominator basis for agentic-gap sizing.
3. **Block-scored denominators**: ver84 **64** (= 68 answerable − Q-WAYB-010..013, the
   supporting-passage multi-paper items without a single gold block; ver84's four vision items all
   *do* carry `gold_block_id`), gt_wmr **66** (= 70 − Q-WMR-090..093; gt_wmr's one vision item,
   Q-WMR-094, also carries a gold block). Text-answerable arms (NB-D1's reading): **60 / 65**.

**Framing endorsement, plus one addition the brief did not ask for.** I endorse attaching the 0.95
target to rank-1 metrics, computed per fixture. The addition: lessons §7.2 also forces an
achievability statement for any precision definition priced over the **full question population** —
with no abstention mechanism (RI-M7; NB-D3), such a definition is capped at
N_answerable / N_total = 70/82 = **0.8537** (gt_wmr) and 68/82 = **0.8293** (ver84) *regardless of
retrieval quality*. That arithmetic is in §2 because "precision ≥ 0.95" without stating its
denominator is exactly how frozen gates B/D died.

---

## §1 Instrument inventory

### §1.0 The scoring harness and its metric menu (what any fixture can even be scored with)

`app/retrieval_eval.py` (frozen shape, plus additive `retrieved_paper_ids`/`retrieved_block_ids`
fields added post-freeze — priority-baseline §4) computes, per question: paper-level
Recall@k / Precision@k / MRR@k; passage-level hit/rank against `gold_block_id` (recall-style flag:
gold block *anywhere* in top-10 — PREC-1 §0); chunk-level diagnostics; known-absent arm display
(top score, mean score, was-returned). From stored records one can additionally derive **P@1
paper-level** (= R@1; rank-1 paper ∈ gold set) and **block-P@1** (gold block at rank exactly 1).
Around the harness sit the specialised instruments: `app/score_distribution_census.py` (RI-M7),
the generation captures + `app/judge_eval.py` judge stack, and the NB-series measurement scripts
(NB-D1 pool depth, NB-D2 adjacency, NB-D3 abstention census, NB-C2 anchor probe).

### §1.1 Inventory table

Conditioning column = the documented ways the instrument's number is a property of its authoring,
not of the system alone (PREC-1 §5 is the controlling finding). Ceilings are shown as arithmetic in
§1.2–§1.3; here they appear as their computed value.

| # | instrument | population / denominators | metrics it supports | conditioning / factor analysis | structural ceiling | defects on record | verdict for a 0.95-precision claim |
|---|---|---|---|---|---|---|---|
| 1 | `gt_wmr.json` (Waymo priority arm) × retrieval_eval | 82 items = 70 answerable / 12 absent; paper-denom 70; block-denom 66; text-arm 65 | R@10, P@10*, MRR@10, P@1, block-P@1, absent-arm display | short questions (median 19 words), numeric-heavy (36/70), mid-document golds, hard 15/70; 10 logged corrections; multi-paper exposed-but-block-unscored (4) | P@10 ≤ ~1/k (**UNSOUND**); paper-P@1 ≤ 0.9857; block-P@1 reorder-only 0.9394, bottomless K=128 0.9848 all-arm / 1.0000 text-arm | frozen P@10 definition flaw (owned in protocol addendum; gates B failed at ceiling 0.1057 vs measured ceiling 0.1086–0.1132) | **CONDITIONAL-SOUND** — viable primary instrument; P@1 metrics clear 0.95 bounds |
| 2 | `waymo_gt_verified.json` (full-corpus arm) × retrieval_eval | file 84 = 68/16 (incl. 4 vision); dedup → scored 82 = 68/14; paper-denom 68; block-denom 64; text-arm 60 | same menu as #1 | long questions (median 33.5 words), 42% hard, front-matter gold skew, negation/scope-heavy (7); dimension-mix explains only ~6 of 35 pts gap vs #1 (PREC-1 §5b/c) | paper-P@1 fused ≤ 0.8971 (< 0.95!); dense-only ≤ 0.9706; block-P@1 bottomless K=128 0.8750 all-arm / **0.9333 text-arm** | same frozen P@10 flaw; fusion eviction one-way (dense-hit/fused-miss = 5, fused-hit/dense-miss = 0) | **CONDITIONAL** for paper-P@1 dense-only; **UNSOUND** as sole basis for any 0.95 *block* claim (bound itself below target under every reading) |
| 3 | Book fixtures: `eval_book_questions.json` (115, QB-001..115), `eval_book_questions_tdoc87.json` (same 115-item population, T-DOC87-era copy), `eval_book_questions_outline_split.json` (40, Experiment-0 subset) | 115 items across 5 books; dual gold: `gold_chapter_title` (routing) + `gold_block_id` (passage) | chapter-routing accuracy, passage recall, chapter-level fields of retrieval_eval | conditioned on TODAY's chapter split (re-split invalidates `gold_chapter_title`, per own `_metadata.chapter_split_note`); duplicate-title ambiguity documented (4/7 and 12/44 units in two books) | n/a — different programme (book navigation/routing) | none on record beyond documented split-dependence | **OUT OF SCOPE** for the Waymo 0.95 push; CONDITIONAL within book programme only |
| 4 | `eval_equation_slice.json` (40) + `_topic_absent.json` (40), causal corpus | 40 equation/algorithm-chunk items each, 38 gold papers | passage-level R@10 | original slice **saturated**: R@10 = 1.000 by its own metadata → no headroom, regression-canary only; topic-absent variant baselines ~0.900 | saturated instrument cannot detect improvement at all | saturation (self-declared) | original: **UNSOUND** for progress claims (ceiling already reached); topic-absent variant CONDITIONAL — but causal-corpus only, not part of this push |
| 5 | `eval_ground_truth.json` (causal corpus, 210) | 210 items, paper-level gold only (no gold blocks); 60 multi-paper items (50 Multi-Paper-Reasoning + 10 Multi-Paper-Synthesis) folded via `additional_gold_paper_ids`; hit-on-ANY-gold scoring | paper-level R/P/MRR | legacy import (2026-07-15); largest multi-paper population in the repo but single-shot retrieval, hit-any semantics — measures nothing agentic | not applicable to Waymo claim | no gold blocks ⇒ no passage precision possible | **OUT OF SCOPE** for Waymo 0.95; relevant to §3 only as raw-material precedent |
| 6 | `eval_known_absent.json` (causal, 24 fabricated entities) | 24 absent-by-construction items; zero exact-term matches verified against 12,390-paper DB | RI-M7 score-distribution census (absence arm) | fabricated-entity design makes sparse-arm separation an upper bound (own `_metadata.limitation`) | n/a (absence GT, not a precision metric) | sparse-arm caveat self-recorded; feeds the RI-M7/D3 "no separation" verdicts | **SOUND** as absence ground truth for the causal corpus; binary-only, wrong corpus for this push |
| 7 | Known-absent arms of #1/#2: gt_wmr 12 (absence_search logs 12/12), ver84 16 file / 14 scored (logs 16/16, adversarially re-verified second pass) | total scored Waymo absence GT = **26** | absent-arm display; abstention feasibility measurement (NB-D3); refusal A/B denominator | real-fact absences (not fabrications) — plausible confusables by design (protocol §5.4) | full-population pricing cap 0.8537 / 0.8293 (see §2.3) | none; but n=26 cannot fit a 5-level calibration (see §4) | **SOUND** as absence GT; **INSUFFICIENT alone** for confidence-surface work |
| 8 | Generation captures + judge stack: `fixtures/eval/runs/2026-08-23-waymo-generation-run.*` (84 records, qwen3:14b, greedy, prompt verbatim; answer_text present 84/84 incl. absent arm) + 08-24 affordance arms; groundedness-provisional run; fabrication-audit judge runs (08-23 hash `d82bbfa36155`, 08-25 amended `4add354fe464`); refusal-affordance A/B hand classification | 68 answerable + 16 absent captured answers; ~248 answerable / 28 absent judged claims | answer-level supported/unsupported/contradicted; groundedness; wrong-side rate | both rubrics PROVISIONAL/unsigned at capture time; A/B hand classifications are rubric-independent but binary; **NB-JUDGE-RERUN §3: amended rubric delivered to the judge on only 38/84 items** (Ollama silent front-truncation) → every existing judge rate non-comparable-by-hash AND non-comparable-by-delivery | no honest answer-precision number exists today | delivery defect (NB-JUDGE-CTX filed, ledger `d62fb87`); unsigned rubrics; n=16 absence arm | **UNSOUND today** for any calibrated precision/confidence claim; salvageable after NB-JUDGE-CTX fix + one clean re-run over the *existing* captures |
| 9 | Blind sets: `eval_questions_blind.json` (210), `eval_questions_blind_waymo.json` (15) | question_text + question_type only; zero gold ids by design | intended input to judge_eval/human eval; nothing mechanically scoreable | unpaired with any gold record | n/a | unusable for precision claims until joined to gold or judged | **UNSOUND** for this push as-is |
| 10 | Legacy/stale: `eval_ground_truth_waymo.json` (15 seed, superseded by ver84), `waymo_gt_verified_answerable_split.json` (65) / `_known_absent_split.json` (8) (both cut from the 73-item v1 era — stale vs v2's 84), `waymo_gt_a/b.json` (authorship provenance sources), `waymo_safety_research_55{,_resolution}.json` (priority-list provenance: 53 ingested of 55) | see left | historical only | superseded partitions must not be reused as denominators (v1 splits ≠ v2 populations) | n/a | staleness (this audit's finding) | do not score against these |

Evidence layer backing every ceiling below (measurement reports, not fixtures): PREC-1 §1
(reorder ceilings), NB-D1 (pool-depth instrumentation, determinism-probed), NB-D2 (boundary
taxonomy, gate-checked against PREC-1 counts), NB-D3 (17-feature abstention census), NB-C2
(entity-anchor probe — DEAD, AUROC 0.4824/0.3563 vs ≥ 0.75 bar), NB-A1 (signal-source design),
NB-JUDGE-RERUN (judge delivery defect).

### §1.2 Ceiling arithmetic — retrieval-side precision definitions

**(a) Frozen P@10 — why gates B/D died.** For a query with a single gold paper,
`|top-k ∩ gold| / k ≤ min(k, 1)/k = 1/10 = 0.100`; multi-gold queries lift the macro slightly.
Measured macro ceiling across the six baseline runs: **0.1086–0.1132** (protocol ADDENDUM);
observed 0.0971–0.1057 sits AT the ceiling — i.e. the metric was measuring pool composition, not
retrieval quality. Arithmetic per lessons §7.2 (`max P@10 = min(distinct results, gold count)/k`);
thirty seconds at freeze time would have caught it. **Verdict: UNSOUND, permanently retired from
gate duty** (it stays admissible only as a purity diagnostic alongside a rank-1 metric).

**(b) Paper-level P@1.** Identity: P@1 = R@1 (baseline table confirms equality everywhere). Bound:
a rank-1 hit requires a top-10 hit, so perfect ordering promotes exactly the recall set —
**max P@1 = R@10** for the same run:

| fixture / arm | bound (= R@10) | bar needs | have now (P@1) | Δ to 0.95 |
|---|---|---|---|---|
| gt_wmr fused | 69/70 = 0.9857 | ⌈0.95·70⌉ = 67 | 64/70 = 0.9143 | **+3 items — feasible** |
| gt_wmr dense | 67/70 = 0.9571 | 67 | 65/70 = 0.9286 | +2 — feasible |
| ver84 fused | 61/68 = **0.8971** | ⌈0.95·68⌉ = 65 | 54/68 = 0.7941 | **infeasible in shipped shape** |
| ver84 dense-only | 66/68 = 0.9706 | 65 | 54/68 = 0.7941 | +11 — conditionally feasible |

The ver84-fused row is a hard wall: fusion evicts dense hits one-way (dense-hit/fused-miss = 5
questions, fused-hit/dense-miss = 0 — priority-baseline §2), so no ordering improvement inside the
fused top-10 can clear 0.95. The bound rises to feasible **only if the fusion-shape question (X-F)
resolves toward dense-dominant retrieval**, and then ordering quality (X-O) must convert 11 more
queries.

**(c) Block-level P@1.** Three regimes, all from committed measurements (PREC-1 §1; NB-D1):

| fixture (shipped w=0.7) | n | reorder-only (top-10) | bottomless K=32 | K=64 | K=128 | text-arm @K=128 |
|---|---|---|---|---|---|---|
| gt_wmr | 66 | 62/66 = 0.9394 | 63/66 = **0.9545** | 63/66 = 0.9545 | 65/66 = 0.9848 | 65/65 = **1.0000** (n=65) |
| ver84 | 64 | 49/64 = 0.7656 | 53/64 = 0.8281 | 55/64 = 0.8594 | 56/64 = 0.8750 | 56/60 = **0.9333** (n=60) |

Reading, per fixture, never blended:

- **gt_wmr clears 0.95 under a perfect reranker at any pool ≥ 32** (all-arm 63/66 = 0.9545;
  text-arm 63/65 = 0.9692); its residual is ordering (C1 = 11 of its 12 near-misses), X-O-class
  work. At K=128 the bound is 0.9848 all-arm / 1.0000 text-arm. **Block-P@1 ≥ 0.95 is achievable
  on the priority fixture.**
- **ver84 does not clear 0.95 under ANY ranking improvement over today's pools and extraction**:
  best case 56/64 = 0.8750 all-arm, 56/60 = 0.9333 text-arm — the text-arm sits exactly **one item
  short** (57/60 = 0.95). The four items still unexposed at K=128 decompose as: 4 vision-derived
  population members (Q-GTA-042/043/044, Q-WAYB-027 — unreachable by any text-side fix, NB-D1) plus
  4 D/E-class non-vision items whose gold blocks never enter even the 128-deep pool (computed from
  NB-D1's depth histogram: 56 exposed = 22 A-bucket + 23 exposed population + 11 of 15 D/E). The
  text-arm path to ≥ 0.95 therefore requires recovering ≥ 1 (exactly 1 reaches the bar, 57/60) of
  those D/E items via upstream work — see §2.4.

**(d) Full-population pricing (any definition that counts wrong-side answers on absent queries).**
With no abstention mechanism (RI-M7 pass-1; NB-D3's 17-feature census — no thresholdable signal),
every absent query returns a confident top-10 and every served answer is wrong-by-definition:

```
cap = N_answerable / N_total   (perfect retrieval, zero abstention ability)
gt_wmr: 70/82 = 0.8537     ver84: 68/82 = 0.8293
```

Structurally below 0.95 no matter what the retriever does. Any honest 0.95 precision claim must
therefore either exclude the absent arm (and say so) or wait for an abstention mechanism that does
not exist yet (NB-A1 is the design ticket; the refusal-affordance A/B is the only observed
generation-side discrimination: wrong-side 6/16 → 1/16 at a cost of one clean regression out of 68).

**(e) Answer/generation-level "precision".** No honest instrument exists today: the judge stack's
rates are non-comparable-by-hash *and* non-comparable-by-delivery (NB-JUDGE-RERUN §3 — amended
rubric arrived on 38/84 items only); groundedness ran once under unsigned rubrics; the absent arm of
the fixture carries no gold `answer_text` so groundedness could not run there at all (groundedness-
provisional §2). Ceiling arithmetic is meaningless until a delivered-rubric run exists.

### §1.3 What the conditioning analysis forbids

PREC-1 §5, restated as rules for everything downstream: the two fixtures' numbers must never be
averaged, compared across, or traded against each other; any fix bought to raise one fixture's
number must be validated against the other as held-out control before it is believed (the rule that
killed `distinct_papers_fused` in NB-D3 §4). Every §2 recommendation below is stated per fixture
with its own denominator and its own bound.

## §2 The metric definition for THIS push

### §2.1 Recommendation

The operator's "precision ≥ 0.95" attaches to **two named metrics, scored per fixture, never
averaged**, each reported with a five-part qualifier `{metric, fixture, arm (all/text), pool depth,
config}` — without all five parts a number is meaningless under PREC-1 §5's conditioning finding:

**Primary gate — paper-level P@1, answerable arm, shipped fused config:**

| fixture | achievability bound (arithmetic) | verdict |
|---|---|---|
| gt_wmr | max = R@10 = 69/70 = 0.9857; bar = 67/70; current 64/70 → Δ +3 | **feasible in shipped shape** |
| ver84 | max = R@10 = 61/68 = 0.8971 < 0.95 | **infeasible until the fusion-eviction question (X-F) resolves**; dense-only variant bound 66/68 = 0.9706, bar 65/68, current 54/68 → feasible conditional on X-F + X-O converting +11 |

Rationale for paper-P@1 as primary: it is the metric closest to what a user experiences first ("was
the right document served first"), its ceiling is exactly R@10 (shown), it is computable from every
stored run record since the additive-fields fix, and it is the precision half of frozen gates B/D
done honestly.

**Secondary gate — block-level P@1, text-answerable arm, pool depth stated:**

| fixture | bound @K=32 / K=128 (perfect reranker) | verdict |
|---|---|---|
| gt_wmr | 63/65 = 0.9692 / 65/65 = 1.0000 | **feasible now** (all-arm too: 0.9545 @K=32) |
| ver84 | 56/60 = 0.9333 @K=128 (all-arm 0.8750) | **infeasible as bounded today** — one item short at K=128 |

Rationale for block-P@1-text-arm as secondary rather than primary: passage-level correctness is
what the grounded-RAG product actually serves (the agent receives chunk text), but on ver84 its
bound sits below target under today's extraction/pools, so gating the whole push on it would repeat
gates B/D's failure mode in reverse — freezing a target the instrument cannot reach. NB-R0's
two-arm statement is the honest formulation: **priority fixture ✓ clearable; full-corpus text-arm
~0.93 achievable, all-arm bounded by vision/extraction limits.**

**Forbidden as gates:** P@10 (structural ~1/k wall); any full-population precision priced over
absent queries before abstention exists (cap 0.8537/0.8293, §1.2d); answer-level precision until a
delivered-rubric judge run exists (§1.2e). The absent arm stays *reported, never blended* (frozen
protocol's own rule).

### §2.2 What the bounds say the push must actually do

Per fixture, from the arithmetic above plus the failure decomposition:

1. **gt_wmr (priority)**: everything needed is ranking-side. Paper-P@1 needs +3 conversions;
   block-P@1 needs ordering quality over a ≥32-deep pool (C1 = 11 of 12 near-misses already sit in
   the shipped top-10 at ranks 2–8, unchanged by depth — NB-D1). No upstream dependency.
2. **ver84 (full corpus)**: three stacked dependencies, in order — (i) fusion shape (X-F): lifts
   the paper-P@1 bound from 0.8971 to 0.9706; (ii) reranker ordering (X-O): converts the exposed
   near-miss population (23/23 reachable by K=64 per NB-D1; promotion proven by Q-WAYB-031,
   absent-from-pool@32 → reranked #1@64, against the measured newcomer hazard); (iii) only then
   does the block-bound residual (one text-arm item) become visible work.

### §2.3 The denominator decision that must accompany the target

Because the system cannot abstain, the 0.95 claim must explicitly exclude known-absent queries —
and the excluded arm must be *displayed next to the headline* (frozen protocol's own semantics),
not hidden. If the operator wants precision **priced over all served answers** (absent included),
the honest statement today is that its ceiling is 0.8537 / 0.8293 and the prerequisite ticket is an
abstention signal source (NB-A1 C1–C5), not retrieval tuning — D3 ruled the retrieval side out.

### §2.4 What upstream changes would have to move FOR THE BOUND ITSELF TO RISE

These are the only levers that change the ceilings in §1.2c — cited to their boundary/extraction
evidence:

1. **Anchor-membership citation/scoring policy (X-C class).** NB-D2 §2: Q-WAYB-027 (gold block
   `2208.12833:b188` is a member of the rank-1 chunk anchored `b186`) and Q-WMR-094 (`b66` is the
   last block of rank-1 chunk span 63–66) had their gold text *physically served at rank 1* while
   anchor-exact scoring called them misses; Q-WMR-036 is the straddle case. Converting ~1–2
   items/fixture lifts ver84's all-arm block bound 56/64 → ≤58/64 = 0.9063 — real but does not
   close the gap (both named artifacts are vision-derived, hence outside the text arms). Cheap,
   rides with any PR, fixes real mis-groundings.
2. **Extraction repair for figure/table numerics.** Openevidence-programme §3's recorded finding:
   Q-GTA-044's nine inset values ARE selectable via `fitz.get_text()` — only this corpus's
   block/chunk extractor drops them — so part of the "vision-unreachable" slice is an
   extraction-pipeline artifact, not a true vision requirement. NB-VLM-pilot shows the render-read
   alternative currently fails its own fidelity bar (Stage 1: 50% < 80%, genuine chart-numerics
   drops), so extractor-side repair is the honest lever. Each recovered item converts an
   unreachable into a reachable.
3. **Chunk-boundary / re-chunking work.** NB-D2: boundary-defined misses (same_chunk +
   adjacent_chunk) are 9/27 (33%) of ver84-dense near-misses and 3/12 (25%) of gt_wmr-fused, but
   `same_doc_elsewhere` dominates both fixtures (63% / 75%); gold blocks up to 16–29 chunks away.
   The ver84 text-arm bound crosses 0.95 exactly when ONE of the four non-vision items unexposed at
   K=128 becomes exposed (57/60 = 0.95); two make it comfortable. This is the lever NB-R0 flagged
   as "upstream re-chunking beyond this programme's scope" — it must be commissioned explicitly if
   the operator wants the ver84 all-arm/text-arm bound itself to rise, rather than accepting the
   two-arm statement.
4. **Vision-path success (VLM programme).** Only affects the all-arm reading; gated today behind
   NB-6 scoping / Decision C unique-information-yield analysis after the pilot's Stage-1 fail.
5. **Abstention signal (NB-A1).** Does not raise these bounds; it raises the *denominator* a
   defensible precision claim may use (§2.3).

Sequencing note (lessons §7.2 compliance): all five are stated as bound-movers BEFORE the X-series
lands its remaining verdicts; none may be retro-fitted as an excuse after numbers disappoint.

## §3 Gap analysis: agentic-RAG evaluation

*(to land in commit 4)*

## §4 Confidence-benchmark gap

*(to land in commit 4)*

## Verdict

*(to land in commit 4)*
