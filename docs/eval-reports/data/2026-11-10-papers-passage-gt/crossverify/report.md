# Cross-verification report

Items: 61 | survive 51 | fix 10 | kill 0

All 61 gold chunks were read; support, depth, label checked for each. No item killed: every answer is supported by its gold chunk, none is abstract/intro/conclusion.

## Non-survive items

- Q-PF-F-003 (fix): Appendix chunk 2412.20638:c29 (12.1 HIV Treatment) also states 2500 long-term trajectories, 500 on-policy short-term trajectories and 'Reward is given at every time step in the 200 horizon'; it answers the same question. Suggested: Add 2412.20638:c29 to alternative_gold_chunk_ids.
- Q-PF-F-007 (fix): Intro 1.1 chunk 2510.24781:c4 states 'averages kappa = 0.0435 per kilometer ... (standard deviation 0.0006)', the same answer (c60 already listed is only the table). Suggested: Add 2510.24781:c4 to alternative_gold_chunk_ids (keep c60).
- Q-PF-F-013 (fix): 2606.14654:c6 (4.1) says Layer 1 gives a detailed natural-language description of action sequences and Layer 2 infers the overall task, a near-duplicate answer to the first-two-layers question. Suggested: Add 2606.14654:c6 as alternative (weaker match), or tighten question to 'high-level activity' wording of c4.
- Q-PAPG-002 (fix): Appendix I.3 chunk 2606.22126:c56 explains softmax 'competitive normalization ... mutual suppression' vs gated fusion preserving multiple important variables and uniform fusion equal weighting; it covers the same why-question. Suggested: Add 2606.22126:c56 to alternative_gold_chunk_ids.
- Q-PAPG-015 (fix): Question reuses title run 'stacked difference in differences' (title: Covariate-Balanced Weighted Stacked Difference-in-Differences). Suggested: Reword, e.g. 'In the simulation for the covariate-balancing weighted stacked DiD estimator ...' or describe by setting (staggered adoption, covariates affect timing and trend).
- Q-PAPG-017 (fix): Conclusion chunk 2602.07825:c45 says N-bridging estimators 'dominated every other estimator in their respective subclass' and names the best SWR estimator; same answer as gold c41. Suggested: Add 2602.07825:c45 to alternative_gold_chunk_ids.
- Q-PAPG-022 (fix): Question reuses title run 'network surrogate for superconducting' (title: ...Graph Neural Network Surrogate for Superconducting Circuit Simulations). Suggested: Reword, e.g. 'the GNN emulator of tape-stack superconducting circuits benchmarked against ngspice ...'.
- Q-PAPG-024 (fix): Question reuses title run 'with dependent latent variables' (title: ...Linear DAGs with Dependent Latent Variables via Higher-order Cumulants). Suggested: Reword, e.g. 'In the LvLiNGAM simulations using higher-order cumulants, what distribution do the disturbances follow?'.
- Q-PAPG-025 (fix): Question reuses title run 'FluidFlower CO2 injection experiment' (title: ...Application to the "FluidFlower" CO2 Injection Experiment). Suggested: Reword, e.g. 'In the Bayesian parameter identification for the CO2 storage lab-bench (FluidFlower benchmark) surrogate ...'.
- Q-PAPG-026 (fix): Question reuses title run 'marginal and heterogeneous treatment effect' (title: Joint Estimation of Marginal and Heterogeneous Treatment Effects). Suggested: Reword, e.g. 'In the simulations for the NAMI-HTE model combining population-average and subgroup effects ...'.

## Notes (survive, judgement calls)
- Q-PAPG-003: gold 2212.13145:c28 is in the final 'Discussions' section (limitations paragraph), not a summary; kept. Appendix 2212.13145:c34 only partially overlaps (eight-class instability).
- Q-PF-F-003 is labelled paper-passage though numeric; acceptable.
