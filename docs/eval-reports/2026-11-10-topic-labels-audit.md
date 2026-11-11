# Topic-label audit (EV-2) and relevance_score as a focus signal (EV-3)

Date: 2026-11-10. Branch `EP-EV2-topic-audit`. Data: `docs/eval-reports/data/2026-11-10-topic-labels/`.

## 1. Purpose

About 37% of the main corpus (12,385 papers) is off-topic for causal methods. The operator is keeping those papers
to test whether retrieval "stays on focus". The on / borderline / off labels (Haiku labellers, `RUBRIC.md`) are the
instrument for that test, so (EV-2) their reliability is measured against an independent labeller, and (EV-3) the
existing but unused `papers.relevance_score` is tested as a possible query-time focus signal.

## 2. Pre-registered criteria (committed in stub commit 88fbde3 before any labelling or scoring)

- EV-2: Cohen's kappa (three-way, audit vs Haiku) >= 0.70 AND binary off vs not-off agreement >= 0.92 -> labels ACCEPTED as-is. Otherwise report the failing band and recommend a relabel of it.
- EV-3: AUROC (on vs off, borderline excluded) >= 0.85 -> usable as a query-time filter, propose thresholds; 0.70-0.85 -> ranking signal only; < 0.70 -> not usable.

## 3. Method

EV-2. `audit_sample.py`: `random.seed(20261110)`, 100 papers per Haiku label (300), shuffled, joined read-only to `papers`
(title, first 600 chars of abstract, categories). `audit_sample.tsv` has no Haiku column. I (Claude, Sonnet 5.5) read all 300 and
wrote `audit_labels.tsv` applying `RUBRIC.md` by hand (no keyword script), committed it, and only then ran `audit_score.py`.
Corpus re-weighting: each sampled paper in Haiku band h carries weight (corpus share of h)/100.
CIs are 2000 bootstrap resamples within each Haiku stratum.

EV-3. `relevance_score_study.py`: join labels to `papers.relevance_score`, AUROC by Mann-Whitney rank-sum with mid-ranks (no sklearn).

How the score is computed (`rag/orchestrator.py`): `relevance_score = _cosine(summary_vec, topic_query_vec)` (line 684; `_cosine` at
lines 105-111). `summary_vec` is the embedding of the LLM-generated paper summary (`texts = [summary_text] + ...`, lines 676-681).
`topic_query_vec` is ONE embedding of `" ".join(self._config.focus_area_queries)` (lines 486-490; hoisted per run at line 481). The
shipped config lists 33 queries across several sub-topics, so the reference vector is a single embedding of a ~33-phrase blob.
Reasons it could be weak: (a) one centroid-like vector for a multi-modal topic (econometrics, discovery, LLM-causality, fairness, ...)
is far from any single paper, so cosines are compressed (on-topic max about 0.61, median 0.42) and absolute thresholds are not
interpretable; (b) it ranks "similar to the blob", which favours papers with generic causal vocabulary and may penalise on-topic
niches (e.g. IV/DiD econometrics) relative to ML-flavoured ones; (c) it scores the summary, not the abstract the labellers saw;
(d) any change of embedder or query list silently shifts the scale, so a fixed cut-off is fragile. The data below show (a)-(b) cost
some separation but not much.

## 4. Results

### EV-2 confusion matrix (rows Haiku, columns audit; n=300, 100 per Haiku band)

| Haiku \ audit | on | borderline | off |
|---|---|---|---|
| on | 95 | 5 | 0 |
| borderline | 5 | 83 | 12 |
| off | 0 | 4 | 96 |

| Metric | Balanced sample | Corpus-weighted (95% CI) |
|---|---|---|
| Raw 3-way agreement | 0.913 | 0.944 |
| Cohen's kappa | 0.870 | 0.901 (0.850-0.947) |
| Binary off vs not-off agreement | 0.947 | 0.975 (0.957-0.989) |

Per band, share I labelled identically: on 0.95, borderline 0.83, off 0.96. Binary agreement per band: on 1.00, borderline 0.88, off 0.96.
There were zero on<->off disagreements, so there is no list of costly disagreements to show. All 26 disagreements involve `borderline`
(see `audit_score_output.txt`): 12 Haiku-borderline papers I called off (e.g. a distribution-shift or generic-inference paper with
no causal framing), 5 Haiku-borderline I called on, 5 Haiku-on I called borderline, 4 Haiku-off I called borderline.

Corrected off-topic share. Haiku: 4,630 / 12,385 = 37.4%. Using my labels as the reference, P(audit says off | Haiku band) x band share
gives **36.9%** (95% bootstrap CI 35.2%-38.3%). The net movement is small: Haiku-borderline papers I call off add about +1.0 point,
Haiku-off papers I call borderline subtract about -1.5 points.

### EV-3 relevance_score

0 NULL of 12,385 labelled papers (12,390 rows in `papers`; 5 unlabelled).

| label | n | mean | median | d1 | d2 | d3 | d4 | d5 | d6 | d7 | d8 | d9 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| on | 6711 | 0.411 | 0.417 | 0.310 | 0.350 | 0.378 | 0.398 | 0.417 | 0.436 | 0.454 | 0.473 | 0.500 |
| borderline | 1044 | 0.328 | 0.328 | 0.231 | 0.259 | 0.285 | 0.308 | 0.328 | 0.351 | 0.372 | 0.394 | 0.427 |
| off | 4630 | 0.250 | 0.256 | 0.132 | 0.168 | 0.202 | 0.232 | 0.256 | 0.280 | 0.302 | 0.324 | 0.355 |

**AUROC on vs off = 0.923.** (on vs borderline+off 0.897; on vs borderline only 0.783.)

Threshold table (remove papers with score < t):

| t | off removed | on wrongly removed | borderline removed |
|---|---|---|---|
| 0.15 | 0.153 | 0.000 | 0.009 |
| 0.20 | 0.295 | 0.006 | 0.041 |
| 0.25 | 0.471 | 0.028 | 0.158 |
| 0.30 | 0.693 | 0.083 | 0.369 |
| 0.35 | 0.888 | 0.200 | 0.595 |
| 0.40 | 0.975 | 0.410 | 0.822 |
| 0.45 | 0.997 | 0.678 | 0.945 |
| 0.50 | 1.000 | 0.901 | 0.994 |

(Full 0.10-0.70 table in `relevance_score_output.txt`; t >= 0.55 removes essentially everything.)

By year (on/off counts, AUROC, off share): AUROC is 0.97-1.00 for 2012-2021, 0.93-0.94 for 2022-2024, 0.880 for 2025 and 0.918 for 2026.
Off share is 0.14 in 2023-2025 but **0.68 in 2026** (2,911 off vs 1,012 on); years before 2012 have too few on-topic papers to estimate.
Mean off-topic score rises from about 0.16 (2012-2017) to 0.23-0.28 (2022-2026), so the signal is weaker for recent off-topic papers (many are LLM/agent papers).

Top 15 primary categories among off-topic papers: cs.CV 636, cs.LG 586, cs.CL 368, cs.AI 264, cs.RO 211, astro-ph.GA 124, cs.CR 120,
quant-ph 111, astro-ph.CO 102, astro-ph.SR 91, astro-ph.HE 90, gr-qc 90, cs.SD 78, cs.IR 70, cs.SE 69. Physics/astro categories score lowest
(mean about 0.16-0.22). The hard cases are in-ML categories: off-topic cs.CL / cs.AI / cs.LG / cs.IR papers average 0.31-0.32, close to
borderline. Within-category AUROC: cs.CV 0.960, cs.LG 0.952, cs.CL 0.952, cs.AI 0.939, stat.ME 0.945, stat.ML 0.971, cs.IR 0.871, cs.SE 0.858, cs.CY 0.754.

## 5. Verdicts

- **EV-2: ACCEPTED as-is.** Kappa 0.901 (CI 0.850-0.947) >= 0.70 and binary agreement 0.975 (CI 0.957-0.989) >= 0.92. Even the unweighted
  balanced-sample figures pass (0.870 and 0.947). The weakest band is `borderline` (83% agreement), which is expected from its definition;
  no relabel is recommended. Corrected off-topic share 36.9% (35.2-38.3%).
- **EV-3: AUROC 0.923 >= 0.85 -> usable as a query-time filter.** Proposed thresholds (corpus-wide, current embedder and config):
  conservative **0.25** (drops 47% of off-topic, costs 2.8% of on-topic and 16% of borderline); balanced **0.30** (drops 69% off, costs 8.3% on,
  37% borderline). Above 0.35 the on-topic loss (>= 20%) is too high. Note the filter removes at most about half to two thirds of off-topic
  papers at tolerable on-topic loss, so it narrows rather than cleans retrieval; for the "stays on focus" test the off papers are
  deliberately kept, so the score is better used to stratify than to filter.

## 6. What this does not show

- The audit labeller is not ground truth and not independent of the Haiku labels in training lineage: same rubric, same title/abstract excerpt, and both are Anthropic models, so shared blind spots (and shared reading of the rubric) are not detected. Agreement measures consistency, not correctness. A human spot check of the 26 disagreements and of a sample of agreed `borderline` papers would be the stronger test.
- The off-share CI is sampling error only (n=100 per band); it excludes labeller bias. Borderline has the widest uncertainty because 1,044 papers are represented by 100.
- The audit sample was labelled from a 600-character abstract excerpt; labels may differ with full text.
- AUROC is measured against these labels, which were derived from abstracts, while the score uses the LLM summary; label noise (about 3% binary) would lower the true AUROC slightly or raise it, direction unknown.
- Thresholds are tied to the current embedder, summary prompt and 33-query list; they must be re-derived if any changes. No retrieval run was performed; nothing here shows that filtering improves answer quality.
- The 2026 off-topic surge (68% of 2026 papers) is a property of the corpus mix; the per-year breakdown does not explain it.

## 7. Reproduce

```
cd docs/eval-reports/data/2026-11-10-topic-labels
conda run -n agent-rag-research python audit_sample.py          # rewrites audit_sample.tsv (deterministic)
# audit_labels.tsv was written by hand, blind; not regenerated
conda run -n agent-rag-research python audit_score.py            # -> audit_score_output.txt
conda run -n agent-rag-research python relevance_score_study.py  # -> relevance_score_output.txt
```
All database access is `file:...papers.db?mode=ro`.
