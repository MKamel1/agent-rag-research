# The OpenEvidence programme — every sub-goal, its state, and what closes it

Written 2026-08-23, after execution rather than before it. That ordering is itself a finding: the
operator asked for the whole goal to be planned first, and it was not. Work was dispatched
incrementally as each piece became obvious, which produced results but left no single place showing
how the pieces depend on each other or what "done" means for each. This document is that place, and
it is written to be usable going forward, not as a retrospective.

Every number here is measured or cites the file it came from. Where something is unmeasured it says
so rather than estimating.

---

## 0. The goal, decomposed

The operator's request contains six sub-goals that are frequently conflated. They have different
success criteria and different achievability, and separating them is most of the value of this
document.

| # | sub-goal | success criterion | state |
|---|---|---|---|
| G1 | Understand OpenEvidence's stack | sourced account separating company claims from independent reporting | **done** — §1 |
| G2 | Re-parse if under 100 h, without breaking the corpus | measured runtime + content-hash proof | **done** — §2 |
| G3 | Ground truth, two models, mutually verified | both authors independent, each verified by the other | **done** — §3 |
| G4 | Deep questions across dimensions, testing FP and FN | quantified dimension and FP/FN coverage | **partial** — §4 |
| G5 | Test everything | every instrument run, or its inability to run explained | **partial** — §5 |
| G6 | Multiple parallel dispatches from opencode and Claude | — | **done** — §6 |

"Rival OpenEvidence" is not on this list because it is not a sub-goal, it is the frame. §7 says what
it decomposes into and which parts are achievable at all.

---

## 1. G1 — their stack (done)

Full account in [`2026-08-22-openevidence-gap-and-benchmark.md`](2026-08-22-openevidence-gap-and-benchmark.md) §1.
The load-bearing conclusions:

- **Their moat is the corpus, not verifiably the architecture.** 300+ licensed journals (NEJM full
  archive, JAMA's eleven-journal network, Cochrane, NCCN), ~35M papers indexed.
- **No independent technical audit of their retrieval stack has been published.** The "graph RAG /
  SystemAI" description traces to company statements. Two third-party sources *disagree* — one
  repeats the graph claim while flagging it as company-sourced, the other describes plain vector
  search with semantic mapping. Neither is confirmed.
- **Their published accuracy varies enormously by question type**: an independent MedXpertQA pilot
  put them at 31–39.5% on hard subspecialty reasoning, while a point-of-care-query study has them
  winning. Both are cited in the gap document with their source type.

**Consequence for this programme, and the honest answer to "how far are we":** there is no
apples-to-apples number, and there cannot be one without a shared benchmark. They are measured on
medical QA sets against a licensed medical corpus; this system is measured on an AV-safety corpus
with a bespoke ground-truth set. **Any claim of the form "we are X% of OpenEvidence" would be
fabricated.** What *can* be said is which capabilities each has, and that is §7.

---

## 2. G2 — the re-parse (done)

**Question:** does the corpus need re-parsing, does it fit under 100 hours, and did it break anything?

**Runtime: 2.58 h, comfortably inside the bar.** 1,738 papers in 9,298.8 s = 5.35 s/paper observed,
1,718 backfilled, 20 already done, **0 failures**.

Two prior estimates were both wrong, in opposite directions, and the reason matters more than the
error:

| source | estimate | error |
|---|---|---|
| `.phase0-data/100-paper-run-stats.md` (full ingest, different operation) | 8.05 s/paper → 3.9 h | 50% too slow |
| `.phase0-data/parser-eval/mineru/full-batch/summary.json` (101 papers, math-heavy sample) | 12.73 s/paper → 6.2 h | 2.4x too slow |
| **the actual run** | **5.35 s/paper → 2.58 h** | — |

Both derivations were arithmetically sound. Both samples were unrepresentative — one measured a
different operation, the other a harder subset. **A parse-rate benchmark does not transfer across
corpora or across operations.** Plan against the job itself or do not plan against a number.

**Corpus safety.** The write path is engine-enforced: `put_figures_and_tables` runs under a SQLite
connection authorizer, so the database refuses anything wider rather than the tool promising to
behave. Verified adversarially — `UPDATE papers`, `DELETE chunks`, `INSERT blocks`, `DROP TABLE`,
`CREATE TABLE`, `ALTER papers`, `UPDATE summaries`, `ATTACH database`, `PRAGMA writable_schema=1`,
all nine denied by SQLite; legitimate `figures` writes still pass.

Content hashes over every row (not row counts) against a pre-run snapshot:

```
blocks    235918  UNCHANGED      figures  0 -> 24,708 (1,724 papers)
chunks     46155  UNCHANGED      tables   0 ->  8,266 (1,586 papers)
summaries   1738  UNCHANGED
papers      1738  MOVED -- 4 rows, author_orgs only
```

The `papers` movement was **not** the backfill. It was `scripts/backfill_curated_author_orgs.py`
running concurrently: NULL → the curated Waymo value on four genuine Waymo papers, and those four
carry `author_orgs`/`curated_author_orgs` in Qdrant too — writing both stores is that script's
signature and something the figures backfill never does.

**The methodological point worth keeping: row counts were identical, 1738 before and after.** A
count-based gate would have reported success. Only the content hash caught it.

---

## 3. G3 — two independent ground-truth sets, mutually verified (done)

`fixtures/eval/waymo_gt_verified.json`, **84 items**: 68 answerable (4 vision-derived) + 16
known-absent. Authorship is genuinely balanced — 44 items from ox-alpha (`Q-GTA-*`), 40 from Claude
(`Q-WAYB-*`) — and neither saw the other's work while building.

Verification is layered, each layer by something that did not author the thing it checks:

1. **GT-X**, a third session, cross-verified the original 73 read-only against the corpus.
2. **This session** re-ran the mechanical checks independently: 519 checks on the 73-item set, then
   536 on the 84-item set. **0 failures both times.**
3. **A second pass** adversarially re-checked the 11 items that postdated GT-X — 8 absence claims
   and 3 vision items. **11/11 survived**, over a stated denominator: 78 recorded hit-count queries,
   29 new adversarial probes, 9 gold-block resolutions, 14 leak-check terms.
4. **A fourth agent** spot-checked the second pass rather than trusting it, and reproduced its
   numbers including the one drift it had disclosed.

Independence produced real corrections, which is the argument for having done it this way:

- ox-alpha corrected the reviewer on **Q-GTA-035**: the corpus *quotes* Tesla's self-reported 0.31
  crashes/million-mile figure ~800 characters into a chunk the reviewer had only read the first 300
  characters of. The absence still holds — no corpus author *measures* a Tesla rate — but the item
  now carries that context for its judge.
- ox-alpha corrected the reviewer's re-parse ETA (§2), from a source the reviewer had not found.
- The verification pass **disclosed a hit-count drift it could have hidden** (29/18 recorded vs
  31/17 measured), which is the strongest available signal that the rest of its counts are honest.

**Known limitations, recorded rather than smoothed over:**

- **Q-GTA-044 is a weak vision item.** Its nine inset values *are* selectable in the raw PDF via
  `fitz.get_text()`; only this corpus's block/chunk extractor drops them. It measures an
  extraction-pipeline gap, not a true vision requirement, and does not sit on the same footing as
  Q-GTA-042/043. Two independent reviewers reached this conclusion separately.
- **Q-GTA-036/037 duplicate Q-WAYB-034/009** (Zoox rate, lidar wavelength) — independent
  rediscovery, kept as signal, flagged with `duplicate_of` and a `_metadata.dedup_policy` so no
  scorer counts them twice.

---

## 4. G4 — dimension and FP/FN coverage (partial)

Measured over the 84-item set:

```
tests:        68 answerable / 16 known-absent      -> 19% of the set probes false positives
difficulty:   15 easy / 34 medium / 35 hard
structure:    55 single-passage / 4 multi-paper (no primary) / 5 primary+supporting
vision:        4  (4.8%)
```

**The false-negative / false-positive split is real and substantial.** 16 known-absent items is not
a token arm; it is what made the abstention finding in §5 possible at all, and those absences are
*real* questions about facts genuinely missing from the corpus, not fabricated entities — which is
why that finding is a direct measurement rather than an upper bound.

**The defect: the dimension taxonomy is split by label.** Nine labels, six actual dimensions —
the two authors wrote different wording for the same categories:

```
numeric/quantitative 14 + numeric/quantitative claims 10  ->  24
methodological       12 + methodological questions     7  ->  19
temporal/versioned    3 + temporal/versioned claims    4  ->   7
single-passage factual lookup 18, negation and scope 10, multi-paper synthesis 6
```

Any per-dimension breakdown splits three categories in two and reports both halves as separate,
undersized strata. Additionally **`question_type` is null on 40 of 84 items** (every `Q-WAYB-*`),
so `build_report`'s per-type breakdown covers under half the set with `"Unlabeled"` as its largest
bucket.

**What closes G4:** normalise the vocabulary to one label per category, pin it with a closed-set
invariant test so a future author cannot reintroduce a variant, and backfill `question_type` where
it is derivable from the item rather than guessed. *In flight.*

---

## 5. G5 — test everything (partial)

Four instruments. Three ran; one cannot, for a structural reason.

### Retrieval — answerable arm, n=65, paper-level Recall@10 / MRR

| mode | Recall@10 | MRR |
|---|---|---|
| **dense only** | **0.969** | 0.841 |
| fused (shipped config) | 0.892 | 0.828 |
| sparse only | 0.631 | 0.594 |

**The shipped hybrid config costs 7.7 points of recall.** Verified per question rather than in
aggregate: five questions the dense arm ranked and fusion lost (`Q-GTA-010/011/020/022`,
`Q-WAYB-002`) against **zero** in the other direction, plus rank collapses where fusion kept the
paper at all (`Q-GTA-007` 3→10, `Q-GTA-015` 1→7). n=65 makes the magnitude uncertain; 5–0 makes the
direction unambiguous.

### Abstention — n=8 known-absent vs n=65 answerable

```
answerable    mean 0.01129  IQR [0.00855, 0.01407]
known_absent  mean 0.01103  IQR [0.00819, 0.01447]
distributions_separate: false
```

**Indistinguishable.** No relevance floor is choosable; all 8 known-absent questions return a
confident top-10 result. Measured against the real absent items, so the fabricated-entity
upper-bound caveat does not apply. This is the finding that matters most for the OpenEvidence
frame — see §7.

### Truncation

Reranker item ceiling binds on 1 of 46,155 chunks (0.0%). Summarizer whole-document ceiling binds on
**1,669 of 1,738 papers (96.0%)**, dropping ~7.98M words. Real, but in the summarizer path, not
chunk retrieval.

### Groundedness — cannot run, and was not faked

`app/judge_eval.py` has no Judge implementation (`Judge` is a Protocol at :87, `--judge-factory`
required at :247, only `FakeJudge` exists in the test module) and the rubric is unsigned
PROVISIONAL. A score against a provisional rubric is worth less than no score. **Fabrication rate
and citation faithfulness — the axes OpenEvidence is actually judged on — have no number.**

### The vision arm — built, never evaluated

Vision constructed 4 ground-truth items. **No evaluation has measured whether retrieval can surface
the pages those questions depend on.** Note the scope of what the baseline covered: the 73-item set
the retrieval run measured contained exactly **one** vision item (`Q-WAYB-027`); the other three
postdate it. *In flight.*

---

## 6. G6 — the dispatch record (done)

Both model families contributed, and the failure pattern is worth recording because it shaped every
later brief.

- **ox-alpha via opencode** built GT-A, the figures write path and authorizer, and the retrieval
  harness fixes — across **nine silent mid-work deaths** (exit 0, no error, log ending at the model
  call, zeroed token counts). Not quota: a direct probe of the same model on the same key answered
  normally while three dispatches were dying.
- **Claude/Sonnet** built the vision items, finished the backfill tool, ran the benchmark, and did
  both verification passes.

**The mitigation that made the deaths survivable was a brief instruction, not a fix.** Three deaths
before "commit at every green point" lost 10–25 minutes each and left one repo file unparseable.
Every death after it cost nothing. The full lessons log is
[`docs/AGENT-OPERATIONS-LESSONS.md`](../../AGENT-OPERATIONS-LESSONS.md).

The second architectural consequence: **a 2.58-hour job cannot be supervised by a process that dies
every 20 minutes.** The backfill was built and gated inside agent sessions, then launched detached,
with resume-after-hard-kill as a stated requirement rather than a nicety.

---

## 7. What "rivalling OpenEvidence" actually decomposes into

Four separable claims, not one:

1. **Corpus/licensing parity — not achievable, and not the right target.** You cannot license NEJM.
   Within AV-safety and causal-methods literature the sources are open and the corpus can be
   *complete* in a way a general medical index cannot. Domain-scoped completeness is a different
   claim from general coverage; this programme does not conflate them.
2. **Retrieval parity — closer than the abstention gap suggests, but the shipped config is not what
   should be measured.** 0.969 paper-level recall dense-only is genuinely strong. The fused default
   currently costs 7.7 points of that.
3. **Abstention parity — not attempted, and the largest gap.** OpenEvidence's entire proposition is
   answering only from licensed evidence and refusing otherwise. This system **cannot do the
   refusing half at all**, and no retrieval improvement fixes that: the score distributions carry no
   signal to threshold on.
4. **Groundedness parity — unmeasured, which is not the same as fine.**

**The ranked path, defended in the gap document's §5:** retune the fusion weight (config, near-zero
cost, currently negative) → abstention (above every architecture item) → a real groundedness judge
(a prerequisite for evaluating anything downstream) → ColBERT → multi-hop → knowledge graph (last,
demoted further because their own graph claim is unaudited and the one independent measurement on
the reasoning class it should serve has them at 31–39.5%).

---

## 8. What is still open

| item | why it is open | closes when |
|---|---|---|
| dimension vocabulary + `question_type` | two authors, two labels per category; 40 nulls | normalised, closed-set invariant test added — *in flight* |
| vision arm evaluation | built but never measured | page-proximity numbers reported at n=4, with the denominator stated — *in flight* |
| groundedness | no Judge implementation, unsigned rubric | rubric signed, judge built, fabrication rate measured |
| external benchmark | none exists for this corpus | out of scope until the above land; note that no cross-system number is possible without one |
| causal corpus | Waymo was prioritised by the operator | same backfill tool, `--db` already takes a path; ~12,390 papers at the measured 5.35 s/paper ≈ 18.4 h |
