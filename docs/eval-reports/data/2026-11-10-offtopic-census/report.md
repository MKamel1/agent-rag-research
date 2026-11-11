# Off-topic census: causal-methods corpus sample

Sample: 400 rows, doc_type='paper', seed 20261110. Corpus size 12,385.
Labels are judged from title + abstract (first 400 chars) only; they are a single-reviewer LLM judgement, not a validated gold standard.

## Label counts

| Label | Count | Share |
|---|---|---|
| on | 193 | 48.2% |
| borderline | 53 | 13.2% |
| off | 154 | 38.5% |

**Off share:** 38.5% (95% Wilson CI 33.9% to 43.4%)

**Extrapolated off-topic papers in corpus of 12,385:** 4,768 (95% CI 4,194 to 5,370), sampling error only.

## Label by primary arXiv category

| Primary category | on | borderline | off | total |
|---|---|---|---|---|
| cs.LG | 43 | 14 | 25 | 82 |
| stat.ME | 70 | 5 | 1 | 76 |
| cs.CV | 4 | 6 | 23 | 33 |
| stat.ML | 21 | 4 | 3 | 28 |
| econ.EM | 15 | 6 | 0 | 21 |
| cs.AI | 9 | 1 | 10 | 20 |
| cs.CL | 2 | 0 | 10 | 12 |
| stat.AP | 10 | 2 | 0 | 12 |
| cs.RO | 1 | 0 | 7 | 8 |
| cs.SE | 0 | 1 | 7 | 8 |
| econ.GN | 5 | 2 | 0 | 7 |
| cs.SI | 1 | 0 | 5 | 6 |
| quant-ph | 0 | 2 | 3 | 5 |
| cs.CY | 1 | 1 | 2 | 4 |
| astro-ph.GA | 1 | 0 | 3 | 4 |
| astro-ph.CO | 0 | 0 | 4 | 4 |
| cs.SD | 0 | 0 | 3 | 3 |
| astro-ph.HE | 0 | 0 | 3 | 3 |
| cs.IR | 2 | 0 | 1 | 3 |
| eess.AS | 0 | 0 | 3 | 3 |
| cs.NI | 0 | 0 | 3 | 3 |
| physics.chem-ph | 0 | 0 | 3 | 3 |
| cond-mat.mtrl-sci | 1 | 0 | 2 | 3 |
| cs.GR | 0 | 0 | 2 | 2 |
| cs.PL | 0 | 1 | 1 | 2 |
| physics.flu-dyn | 0 | 0 | 2 | 2 |
| hep-ph | 0 | 0 | 2 | 2 |
| stat.CO | 1 | 1 | 0 | 2 |
| physics.soc-ph | 1 | 1 | 0 | 2 |
| q-bio.NC | 1 | 0 | 1 | 2 |
| math.NA | 0 | 0 | 2 | 2 |
| physics.data-an | 1 | 0 | 1 | 2 |
| math.OC | 0 | 2 | 0 | 2 |
| gr-qc | 0 | 0 | 2 | 2 |
| cs.CR | 0 | 0 | 1 | 1 |
| cs.DB | 1 | 0 | 0 | 1 |
| cond-mat.stat-mech | 0 | 0 | 1 | 1 |
| q-bio.QM | 0 | 1 | 0 | 1 |
| q-bio.MN | 0 | 1 | 0 | 1 |
| astro-ph.EP | 0 | 0 | 1 | 1 |
| cs.CE | 0 | 1 | 0 | 1 |
| cs.HC | 0 | 0 | 1 | 1 |
| physics.bio-ph | 0 | 0 | 1 | 1 |
| physics.acc-ph | 0 | 0 | 1 | 1 |
| math.DS | 0 | 0 | 1 | 1 |
| nlin.AO | 0 | 0 | 1 | 1 |
| physics.pop-ph | 0 | 0 | 1 | 1 |
| cs.AR | 0 | 0 | 1 | 1 |
| nucl-th | 0 | 0 | 1 | 1 |
| cs.MA | 0 | 0 | 1 | 1 |
| eess.SP | 1 | 0 | 0 | 1 |
| physics.geo-ph | 0 | 0 | 1 | 1 |
| cond-mat.str-el | 0 | 0 | 1 | 1 |
| astro-ph.SR | 0 | 0 | 1 | 1 |
| cs.NE | 0 | 0 | 1 | 1 |
| physics.ao-ph | 0 | 0 | 1 | 1 |
| cs.MS | 0 | 0 | 1 | 1 |
| eess.SY | 0 | 0 | 1 | 1 |
| math.ST | 1 | 0 | 0 | 1 |
| q-fin.ST | 0 | 1 | 0 | 1 |
| math.GT | 0 | 0 | 1 | 1 |

## Label by publication year

| Year | on | borderline | off | total |
|---|---|---|---|---|
| 2007 | 0 | 0 | 1 | 1 |
| 2008 | 0 | 0 | 1 | 1 |
| 2009 | 0 | 0 | 1 | 1 |
| 2011 | 1 | 0 | 1 | 2 |
| 2012 | 2 | 1 | 2 | 5 |
| 2013 | 3 | 0 | 1 | 4 |
| 2014 | 1 | 0 | 1 | 2 |
| 2015 | 3 | 1 | 4 | 8 |
| 2016 | 0 | 0 | 1 | 1 |
| 2017 | 6 | 0 | 2 | 8 |
| 2018 | 8 | 2 | 4 | 14 |
| 2019 | 7 | 1 | 3 | 11 |
| 2020 | 16 | 3 | 4 | 23 |
| 2021 | 22 | 5 | 2 | 29 |
| 2022 | 19 | 7 | 7 | 33 |
| 2023 | 16 | 6 | 4 | 26 |
| 2024 | 27 | 3 | 6 | 36 |
| 2025 | 35 | 11 | 9 | 55 |
| 2026 | 27 | 13 | 100 | 140 |

## relevance_score by label

| Label | n (non-NULL) | mean | median | NULL count |
|---|---|---|---|---|
| on | 193 | 0.416 | 0.422 | 0 |
| borderline | 53 | 0.358 | 0.365 | 0 |
| off | 154 | 0.261 | 0.263 | 0 |

Total NULL relevance_score in sample: 0 of 400.

## 20 clearly off-topic examples (first 20 off rows in sample order)

- 2606.17192: Constrained Diffusion Models with Primal-Dual Inference (constrained diffusion sampling; no causal content)
- 2606.06906: EASE-TTT: Evidence-Aligned Selective Test-Time Training for Long-Context Question Answering (long-context QA test-time training)
- 2607.06982: EdgeCompress: Coupling Multidimensional Model Compression and Dynamic Inference for EdgeAI (edge AI model compression)
- 2607.07903: Mechanistic Interpretability of LLM Jailbreaks via Internal Attribution Graphs (LLM jailbreak interpretability; no causal method)
- 2607.08321: Texture Representations in Deep Vision Models: Comparing CNNs, Vision Transformers, and Human Perception (vision model texture comparison)
- 2401.09379: Merging uncertainty sets via majority vote (merging uncertainty sets; generic statistics)
- 2606.06077: 3D Underwater Path Planning via Generative Flow Field Surrogates (underwater path planning)
- 2011.00592: Vec2Sent: Probing Sentence Embeddings with Natural Language Generation (sentence embedding probing)
- 2406.07866: Asymptotically Optimal Regret for Black-Box Predict-then-Optimize (predict-then-optimize regret, no causal content)
- 2606.27320: Elastic Time: Dynamic Frame Rate Bottlenecks for Neural Audio Coding (neural audio coding)
- 2606.10481: Advancing the State-of-the-Art in Empirical Privacy Auditing (privacy auditing of fine-tuned LLMs)
- 2607.08741: ARDY: Autoregressive Diffusion with Hybrid Representation for Interactive Human Motion Generation (human motion generation)
- 2607.08547: Potential Functions as Types (type theory and amortized analysis)
- 2108.09946: Pull Request Latency Explained: An Empirical Overview (pull request latency empirical study)
- 2606.06663: Explainable Runtime Dependency Tracking for AI-RAN Conflict Monitoring (AI-RAN dependency tracking)
- 2606.24994: ExTra: Exploratory Trajectory Optimization for Language Model Reinforcement Learning (RL for LLM reasoning)
- 2601.04386: Numerical Investigation of the Effect of a Magnetic Field on the Transport of Oxygen in Air (gas transport simulation)
- 2203.13619: Answering Should Self-Publishing Video Game Developers Market Their Game on Twitter (video game marketing)
- 2607.10474: Reinforcement Learning with Verifiable Physics: Post-training LLMs with Continuous Rewards (RL for PDE solvers)
- 1806.09613: Attention-based Few-Shot Person Re-identification Using Meta Learning (few-shot person re-identification)

## Empty abstracts

Sampled rows with empty abstract: 0 of 400.


## Caveats and findings

- Labels come from title + abstract only, by one reviewer (the agent), with no second-rater check; borderline cases (53) are where label noise concentrates. Off share could move several points under a different rater or a stricter "borderline" cut.
- The Wilson CI covers sampling error from n=400 only, not labelling error.
- Strong recency skew: 100 of the 154 off-topic sampled papers are dated 2026 (71% of the 140 sampled 2026 papers). Whether this reflects a bulk ingest of unrelated cs.LG/cs.CV/cs.AI content is worth checking directly against the DB before any cleanup.
- relevance_score separates the labels only partially (median 0.42 on vs 0.26 off, with substantial overlap). It has no NULLs in this sample, so it is usable as a ranking signal but not a reliable hard filter without a validated threshold.
- Top 5 primary categories among off-topic papers: cs.LG (25), cs.CV (23), cs.AI (10), cs.CL (10), cs.RO (7) (cs.SE also 7).
