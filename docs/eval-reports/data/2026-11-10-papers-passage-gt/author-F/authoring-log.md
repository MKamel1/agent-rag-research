# Author F log (papers corpus, passage-level GT)

Sample: 32 papers (sample-F.json). Items: 31 (one per paper), verify = 0 failures.
Dimensions: numeric-result 8, method-detail 10, equation-context 6 (one over target of 5), paper-passage 7.
Difficulty: easy 9, medium 16, hard 6.

## Skipped / killed
- Skipped 1 paper: 2506.23374 (BiDD causal discovery). 55 of its 70 chunks have per-character `<sub>` tag corruption
  ("Synthetic Data Details. We roduce s nthetic bivariate causal airs ..."); no clean prose excerpt available.
- 0 papers skipped for thinness. 2505.05670 was kept (6th equation-context item) rather than dropped, so equation-context is 6 not 5.
- Killed/replaced candidates (5): 2504.09163 first pick (4.27%/4.80% is repeated in abstract c1, switched to 3.56%/2.98% in c19);
  1804.04622 (exponential-noise-as-confounders sentence is repeated in c6, switched to kernel-choice sentence in c9);
  2607.10126 (Cohen's kappa 0.72-0.83 repeated in c11 and discussion c18, switched to 478/1,435 double/single-coded split);
  2505.07729 (historical-experiments scenario stated in intro c2/c12, switched to sample-size design sentence);
  2211.10805 c22 (proof chunk, degenerate LaTeX, not usable).
- Alternative gold chunks recorded: 2510.24781 (c60 table), 2101.04025 (c14 table) via `alternative_gold_chunk_ids`.

## Text-quality observations (across the 32 papers, 1,430 chunks)
- Oversized chunks (>8,000 chars): 28 (2.0%); >10,000 chars: 13. Worst: 2208.00114:c26 "Supplementary Tables" 105,676 chars,
  2106.10141:c27 online-appendix descriptive statistics 64,194, 2604.14856:c63 AI-assistant appendix 28,800,
  2505.05670:c146/c149 17.3k/17.4k, 2606.14654:c19 12.8k. Intro sections of 8 papers are single 8-10k chunks mixing motivation, related work, contributions.
- Stub chunks (body < 60 chars): 126 (8.8%), mostly heading-only or dangling headers. Reference lists are effectively stripped:
  32 "References" chunks, 24 of them under 200 chars (bibliographies not indexed). Where kept (2211.10805 c36 2,555; 2501.06864 c22 2,799;
  2508.06662 c26 2,281; 2604.14856 c29 1,910) they are boilerplate content chunks. 2604.14856:c63 is 28.8k of appendix boilerplate.
- Math/table damage: 574 chunks (40%) contain heavy LaTeX; 147 (10%) contain markdown tables, often mis-split (2208.00114:c13 rows merged; 2411.03387:c16 table cells interleaved). Degenerate looping LaTeX in 2211.10805:c22 (`\mathcal{R} \leq \mathcal{R} ...`).
- Ligature loss ("efect", "difusion", "coeficient", "dificult", "ofer"): 17 of 32 papers, 449 chunks. Lexical match on "effect"/"diffusion" fails on these.
  Odd characters also seen: "Öur", "ž", U+FFFD in 2504.09163 ("number of categories (�)").
- Section-header damage / mixing: 2106.10141 sections 5.2-5.4 all headed "Figure 1: Evolution of ATE over time"; 2606.25601 (monograph) chapter 2
  spans 19 chunks under one "Hyperparameter Selection via Multiple Hypothesis Testing" header, other headers are fragments ("vector of hyperparameters", "criteria?");
  2510.24781 sections 5.3 onward nested under "(2) Spatial-Adjusted DID:"; 2606.09388 section "Which combination of adaptation method ..." is a body sentence.
- Documents concatenated: 2505.05670 contains main text plus a 166-chunk supplement with a second Abstract/Contents (and SA-x sections);
  2006.01366 supplement has a second References and restarts section numbers (1 Simulation study ... collides with main section numbers).
- Off-topic papers in a causal-inference corpus: 10 of 32 are not causal methods (2606.09987 white dwarf, 2606.26234 Lyman-alpha EFT, 2606.10912 deepfake speech,
  2606.09508 long-context LLM inference, 2606.26398 V2X compression, 2606.09388 on-device safety, 2607.10126 containerization, 2606.06036 agent memory,
  2606.14654 workflow abstraction, 2606.25601 hyperparameter guarantees). These are retrieval distractors with no causal vocabulary.
- Proof appendices are equation walls: 2411.03387 c28-c36 are 5-9k chars each; 2606.25601 chapter 2 is 19 chunks of derivations.
