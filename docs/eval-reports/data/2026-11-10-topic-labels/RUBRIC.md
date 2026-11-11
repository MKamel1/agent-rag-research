# Topic-label rubric (frozen 2026-11-10, identical for every labeller)

The corpus is meant to hold papers on CAUSAL METHODS:
causal inference, causal machine learning, causal discovery / structure learning, treatment-effect
estimation (ATE, CATE, uplift, heterogeneous effects), causal representation learning,
econometric identification (IV, difference-in-differences, regression discontinuity, synthetic
control, panel methods), experimentation (A/B testing, randomized trials methodology, off-policy
evaluation), counterfactual reasoning/explanations/fairness, mediation, causal reasoning with or
of LLMs/agents, and applied studies whose central contribution is a causal analysis.

Label each paper from its title, arXiv categories and abstract excerpt ONLY:

- `on`  — clearly about causal methods as defined above, or applies them as a central part of the work.
- `borderline` — causality is mentioned or used only peripherally; OR it is general statistics / ML
  methodology closely adjacent to causal work (generic regression, generic Bayesian inference,
  generic experimentation platforms, time-series forecasting, interpretability/attribution without a
  causal framing, domain-shift/robustness without a causal framing); OR you genuinely cannot tell.
- `off` — no meaningful causal-methods content (e.g. astronomy, particle/condensed-matter physics,
  pure mathematics, pure computer vision, speech, generic LLM serving/benchmarks, robotics control,
  chemistry) even if a word like "effect", "cause", "causal" (in the physics sense of causality),
  "intervention" or "treatment" appears in a non-methodological sense.

Notes:
- Physics "causality" (light cones, causal sets, causal structure of spacetime, Kramers-Kronig) is `off`.
- "Causal language modeling" / "causal attention mask" / "causal convolution" (autoregressive sense) is `off`.
- Granger causality, transfer entropy, causal discovery from time series are `on`.
- A medical/social-science study estimating an effect with an explicit causal design is `on`; a purely
  descriptive or predictive study is `off` or `borderline`.
- If the abstract excerpt is empty, judge from the title and categories; when unsure use `borderline`.

Output: one line per paper, tab-separated, exactly:
`<paper_id>\t<label>\t<reason of at most 8 words>`
No header, no blank lines, no other text. Every input paper_id appears exactly once.
