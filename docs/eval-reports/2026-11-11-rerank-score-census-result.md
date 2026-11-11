# Cross-encoder (reranker) score census on absent queries (EV-19): result, 2026-11-11

**Verdict (pre-registered rule): CANDIDATE.** `rerank_top1` passes on 2 of the 3 qualifying sets (focus, standards); legacy
fails the question-length control. Per the pre-registration, CANDIDATE authorises only a larger, separately pre-registered
calibration study. No threshold, wiring or exposure of the score is authorised; RQ-4 stays gated.

Pre-registration: `docs/eval-reports/2026-11-11-ev19-rerank-score-census-prereg.md`. Register: `EXPERIMENT-REGISTER.md`.

## 1. Question asked

Does the best cross-encoder score among the returned passages separate queries whose answer is absent from the corpus from
answerable queries (hypothesis H1: absent scores lower)? Earlier "no abstention floor" verdicts tested the pre-rerank fusion
score, not this.

## 2. What was run

| item | value | source |
|---|---|---|
| code commit | `03cfd1854b7d37c8116d35545c3f54a309e6da40` | `GIT_COMMIT` |
| window | 2026-11-11 10:41:14 to 11:15:36 (-07:00), 34 min 22 s (estimate printed: about 56 GPU min) | `MANIFEST.txt` |
| collections / depth | `papers` at rerank depth 32 (focus, papers, books, legacy); `av_standards` at depth 128; shipped configs | `config-main-shipped.yaml`, `config-standards-shipped.yaml` |
| fixtures + hash check | focus_gt `c68210e0...`, papers_passage_gt `58cdbf47...`, causal_books_gt `3c21d57b...`, eval_known_absent `8c80ee40...`, eval_ground_truth `61e52db8...`, eval_questions_blind `7813ac0e...`, eval_equation_slice `d3fbe4ad...`, standards_gt `09b11061...`, hashes file `7f2fa1fc...`; recorded in MANIFEST and checked against `FIXTURE-HASHES.json` | `MANIFEST.txt` |
| instrument | `--record-rerank-scores` (EV-13), `scripts/rerank_score_census.py`, seed 20261111, 2000 stratified bootstrap resamples | prereg section 5, `census.txt` |
| rows scored, errors excluded | focus 49, books 74, legacy 24 + 210 + 40, papers 61 (secondary), standards 128; 0 errored rows excluded everywhere | `census.txt` header lines |

Evidence committed in full (2.5 MB): `docs/eval-reports/data/2026-11-11-rerank-score-census/runs/20261111T104113/`
(`census.txt`, `census.json`, per-set reports and logs, configs, MANIFEST). Console log:
`/tmp/claude-1000/-home-omar-ai-projects/3426f8b7-1c1a-4487-ad8c-3b6a5cbe5792/scratchpad/census.log`.

## 3. Results: AUROC of absent (positive) vs answerable, 95% bootstrap CI (source for all: `census.txt`)

Primary feature `rerank_top1`, with the two controls the rule compares against (control AUROCs are direction-agnostic max(A, 1-A)):

| set | n_absent / n_answerable | rerank_top1 AUROC [95% CI] | fusion_top_score | query_words | absent / answerable median top1 |
|---|---|---|---|---|---|
| standards (absent + partial-absent) | 22 / 106 | 0.801 [0.715, 0.879] | 0.637 | 0.602 | 0.709 / 0.960 |
| focus | 9 / 40 | 0.942 [0.861, 0.994] | 0.696 | 0.617 | 0.830 / 0.979 |
| legacy (24 fabricated entities vs 210 + 40) | 24 / 250 | 0.874 [0.819, 0.922] | 0.573 | **0.974** | 0.959 / 0.992 |
| books (does not qualify, n_absent < 9) | 5 / 69 | 0.562 [0.281, 0.838] | 0.780 | 0.610 | 0.986 / 0.976 |
| legacy vs papers_passage (secondary, does not count) | 24 / 61 | 0.786 [0.686, 0.874] | 0.555 | 0.899 | 0.959 / 0.988 |

Standards by class (descriptive): `absent` n = 9: 0.905 [0.814, 0.979]; `partial-absent` n = 13: 0.729 [0.622, 0.826].
Pooled across sets (secondary only, scores not comparable across corpora): n_absent 60 / n_answerable 465, AUROC 0.827 [0.779, 0.872].
Exploratory features (not the verdict): `rerank_pool_best` equals `rerank_top1` on every set; `rerank_mean_top3` AUROC focus 0.922,
legacy 0.822, standards 0.692; `rerank_margin_12` focus 0.281, legacy 0.319, standards 0.616, but books 0.933 [0.864, 0.983]
on only 5 absent items (does not qualify; exploratory, needs replication).

## 4. Rule evaluated literally

Rule: CANDIDATE only if, on >= 2 sets with n_absent >= 9, `rerank_top1` has AUROC CI lower bound > 0.70 AND AUROC beats
`fusion_top_score` AND beats `query_words`; else NO SIGNAL. Qualifying sets: focus, legacy, standards.

| set | CI lower > 0.70 | beats fusion | beats length | pass |
|---|---|---|---|---|
| focus | 0.861, yes | 0.942 > 0.696, yes | 0.942 > 0.617, yes | **pass** |
| standards | 0.715, yes | 0.801 > 0.637, yes | 0.801 > 0.602, yes | **pass** |
| legacy | 0.819, yes | 0.874 > 0.573, yes | 0.874 < 0.974, **no** | fail |

Two sets pass, so the verdict is CANDIDATE (`census.json` `verdict`, `passing_sets: [focus, standards]`). Descriptive read-outs of
the ticket (not the verdict): CI lower bound > 0.65 on all three sets; AUROC >= 0.85 on focus and legacy; the CI contains 0.5 on
none of the three (so the RQ-4 kill criterion "CI contains 0.5 on two of three sets" is not met).

## 5. Validity and caveats

- Errors 0; one run per set at the shipped config; retrieval deterministic given a fixed index (prereg section 8).
- Power (prereg section 6): only a strong signal is confirmable. The focus pass rests on 9 absent items; its lower bound 0.861 is
  an interval from a single small sample.
- Length confound is real: on legacy the absent questions (fabricated entities, median 17 words vs 39) are separated by question
  length better (0.974) than by the reranker (0.874). The legacy arm therefore fails the control; on the secondary legacy-vs-papers
  row length also beats the reranker (0.899 vs 0.786). Absent items on focus and standards come from the same authoring process as
  the answerable items, so the control is more meaningful there, but length is not eliminated by construction.
- Standards pass depends on the pre-registered pooling of `absent` and `partial-absent`: `partial-absent` alone has a lower bound
  of 0.622 (< 0.70). The pre-registration states this pooling in advance (section 5).
- Legacy absent items are fabricated entities, an upper-bound-like case. Real-but-uncovered topics are not tested.
- Best-threshold false-abstain / missed-absence columns are in-sample and descriptive. At the in-sample best thresholds the false
  abstain rate on answerable items is large (standards 48/106, legacy 92/250, focus 3/40 at the top1 rows of `census.txt`).
  No threshold is chosen. A threshold decision needs at least 60 distinct absent items (RV-3 F-1.10); the sets hold 9 to 24 each.
- The census judges the retrieval stage, not generated-answer abstention (CRAG / MiniCheck results are separate).

## 6. Do not re-run unless

An identical re-run reproduces this table (34 GPU minutes). Re-run, or extend, only if:

1. The reranker model, its serving flags, the rerank depth (32 main, 128 standards) or the corpora changed (re-chunk, re-embed,
   point count different from 412,167 for `papers`). Scores are model-relative. Check: TEI container image and flags; `git diff
   03cfd18 -- rag/reranker.py rag/retriever.py`; collection point counts.
2. A new absent-question set exists with at least 60 distinct absent items whose length distribution matches the answerable items
   (to defeat the length confound seen on legacy). That is the separately pre-registered calibration study the CANDIDATE verdict
   allows; it needs its own pre-registration and fixture hash, not a re-run of this one.
3. The operator commissions an abstention feature (the gate that parks EV-13, EV-19 and RQ-4); then the question is the
   calibration study above, not this census.
4. A changed threshold or feature list: prereg changes only by dated addendum. The per-row scores are in `census.json` and the
   per-set reports, so re-analysis is CPU-only (`scripts/rerank_score_census.py`) and needs no GPU.
