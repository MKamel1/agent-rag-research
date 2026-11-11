# EV-19 pre-registration: does the cross-encoder (reranker) score separate answerable from absent queries?

Written 2026-11-11, BEFORE any run that records cross-encoder scores. Committed in the stub commit of branch
`EP-EV13-rerank-score-census`; no metric, feature, threshold or set below changes after a run (dated addendum only).
Instrument: EV-13 (`--record-rerank-scores` in `app.retrieval_eval`, `scripts/rerank_score_census.py`).
Run script: `docs/eval-reports/data/2026-11-11-rerank-score-census/run_census.sh`.

## 1. Why this is worth measuring at all

The system review (`2026-11-10-system-review.md`, RV-1 F-1.1, RV-4) verified that the `score` returned to callers is the
pre-rerank RRF fusion score and the reranker's per-candidate scores are discarded after ordering
(`rag/reranker.py` sorts and drops them). The earlier "no separable abstention floor" verdicts (RI-M7,
`2026-08-25-nb-d3-abstention-census.md`) therefore tested rank arithmetic (fusion `top_score`), not the cross-encoder
score. Nobody has looked at the one signal that is a trained query-passage relevance judgment. This note pre-registers that look.

## 2. Hypothesis

H1: for a query whose answer is absent from the corpus, the cross-encoder score of the best retrieved passage is
LOWER than for an answerable query (direction fixed now: absent = lower). H0: no separation (AUROC 0.5).
Absent items are the positive class; AUROC = P(absent item scores lower than an answerable item), ties 0.5.

## 3. Frozen feature list (no feature is added after seeing data)

Cross-encoder features (recorded per question by `--record-rerank-scores`):
1. `rerank_top1` — the highest cross-encoder score among the returned top-k. PRIMARY feature (the only one that can trigger the verdict by itself).
2. `rerank_mean_top3` — mean of the top-3 scores.
3. `rerank_margin_12` — top1 minus top2.
4. `rerank_pool_best` — best score of the whole reranked pool (depth 32; standards 128). Equals `rerank_top1` except when a result is dropped after reranking (orphaned chunk); reported for that check, not an independent test.

Comparison / control features (computed from the same rows):
5. `fusion_top_score` — the pre-rerank fusion score the old verdict rested on.
6. `query_words` — question length in words: the authoring-leak control (absent questions were authored differently from answerable ones).

Multiplicity: four cross-encoder features over several sets inflates false positives, hence one primary feature; the other three are exploratory and a pass on them alone is labelled "exploratory, needs replication", never CANDIDATE. For `fusion_top_score` and `query_words` the AUROC is taken direction-agnostically, max(A, 1-A), which is the conservative comparison for the cross-encoder.

## 4. Sets (each reported alone; never pooled in the headline)

| set | corpus / collection | absent arm | answerable arm | counts (absent / answerable) | qualifies (n_absent >= 9) |
|---|---|---|---|---|---|
| standards | `av_standards`, depth 128 | `tests=absent` in `standards_gt.json` (9 `absent` + 13 `partial-absent`, also broken out) | the 106 `answerable` items | 22 / 106 | yes |
| focus | `papers`, depth 32 | `focus-absent` in `focus_gt.json` | `answerable` items of `focus_gt.json` | 9 / 40 | yes |
| legacy | `papers`, depth 32 | `fixtures/eval/eval_known_absent.json` (24 fabricated entities) | `eval_ground_truth.json` (210) + `eval_equation_slice.json` (40), the pairing `app/score_distribution_census.py` used | 24 / 250 | yes |
| books | `papers` (books), depth 32 | `partial-absent` in `causal_books_gt.json` | its 69 answerable items | 5 / 69 | NO (reported, cannot count) |
| legacy-vs-papers (secondary) | `papers` | the same 24 | `papers_passage_gt.json` (61, authored later, a different author pass) | 24 / 61 | secondary robustness read of `legacy`; does not count |

`papers_passage_gt.json` has no absent items, so it is only an alternative answerable arm. The legacy absent arm is fabricated-entity questions, which makes any separation plausibly an UPPER BOUND (see `_KNOWN_ABSENT_LIMITATION_NOTE` in `app/score_distribution_census.py`); a null there is at least as strong as it looks.

## 5. Verdict rule (written now; mechanical)

> The cross-encoder score is a CANDIDATE abstention signal only if, on at least two sets with n_absent >= 9, the primary feature `rerank_top1` has AUROC 95% CI lower bound > 0.70 AND its AUROC beats `fusion_top_score`'s AUROC on those sets AND beats `query_words`' AUROC on those sets; otherwise NO SIGNAL at this sample size.

Operationalisation: AUROC is the point estimate; the CI is a seeded (seed 20261111) stratified percentile bootstrap, 2000 resamples, resampling absent and answerable items separately. "Beats" = point estimate strictly greater (the paired bootstrap CI of the difference is printed for information, not part of the rule). Qualifying sets are standards, focus, legacy; books and the secondary row never count. Items whose retrieval errored are excluded and their count printed.
Thresholds: 0.70 and "two sets" are the operator's, kept unchanged; no reason to adjust exists before a run.
Descriptive extra read-outs (not the verdict): the EV-19 ticket's earlier values (lower bound > 0.65 on two of three; a floor "viable" only at AUROC >= 0.85), and the RQ-4 closure note (CI contains 0.5 on two of the three qualifying sets).
Standards headline pools `absent` + `partial-absent` (n=22) because the rule needs n >= 9; the two classes are also reported separately, where n=9 and n=13 and the intervals will be wider.

## 6. Power: what is detectable at these n

Hanley-McNeil standard error, true AUROC A, 95% interval A +/- 1.96 SE. The smallest true AUROC whose expected lower bound clears 0.70:

| set | n_absent / n_answerable | SE at A=0.80 | SE at A=0.90 | smallest A with expected lower bound > 0.70 |
|---|---|---|---|---|
| standards | 22 / 106 | 0.059 | 0.045 | about 0.81 |
| focus | 9 / 40 | 0.093 | 0.071 | about 0.86 |
| legacy | 24 / 250 | 0.055 | 0.043 | about 0.81 |
| books (5 / 69) | 5 / 69 | 0.122 | 0.094 | about 0.89 (does not qualify) |

So the test can only confirm a strong signal (true AUROC of roughly 0.85 or more on focus, 0.81+ on the others). A true AUROC of 0.70 to 0.80 is expected to read "NO SIGNAL"; a NO SIGNAL verdict is therefore NOT evidence of absence of a weak signal, only that no strong one is visible at this n. A wide interval is reported as wide; the census prints n beside every number and never rounds an interval's width away.

## 7. Non-goals

- No threshold is shipped, chosen for use, or wired anywhere. The best-threshold table is in-sample (optimistic) and descriptive only; any threshold decision needs at least 60 distinct absent items (RV-3 F-1.10).
- No MCP wiring and no exposure of the score to callers (RQ-4 stays gated); the protected reranker contract is untouched.
- No claim about answer-level abstention. The earlier MiniCheck and CRAG-style results (CRAG instrument AUROC 0.94 / 0.80) judge the GENERATED ANSWER or its support, after generation; this census judges the RETRIEVAL stage, the best passage's relevance to the query, before any generation. A positive here would not replace them and a null here does not weaken them.
- CANDIDATE, if reached, authorises only a larger, separately pre-registered calibration study.

## 8. What this cannot show

Weak signals (section 6); real-but-uncovered topics (the legacy arm is fabricated entities); the standards absent items were authored by the same process as its answerable items, so the question-length control matters there; calibration across corpora (scores are model-relative, sets run on two corpora at two depths); a single reranker model. Each set is a single run at the shipped config (no repeats), retrieval is deterministic given a fixed index.
