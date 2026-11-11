# ruff: noqa  (one-off data-repair script; dense on purpose)
"""EV-4b: apply the collision/offtopic fixes to author/items.json (idempotent; run from the focus-gt dir)."""
import json
P = "author/items.json"
d = json.load(open(P)); items = {i["question_id"]: i for i in d["ground_truth"]}

# qid -> (new question or None, trap_strength, alt gold chunks or None, extra field updates)
COLL = {
 "Q-FOC-001": (None, "moderate", ["2006.11386:c16"], {}),
 "Q-FOC-002": (None, "moderate", None, {}),
 "Q-FOC-003": (None, "moderate", None, {}),
 "Q-FOC-005": ("In the university study of AI-flagged at-risk learners, what do blocking and the caliper each do when matching supported students to untreated ones?", "moderate", None, {}),
 "Q-FOC-006": ("What does the weight-tile figure in the PanelMatch example show about how often each unit gets reused by the matching after propensity-score refinement?", "moderate", None, {}),
 "Q-FOC-007": ("What caution does the randomization-inference paper on imperfect matching give about matched datasets that look covariate-balanced by usual diagnostics?", "moderate", None, {}),
 "Q-FOC-008": ("In the university-grants dropout study using principal stratification, how does the local RD-SUTVA assumption treat interference among students?", "moderate", None, {}),
 "Q-FOC-009": ("In the work on validating counterfactual estimates under network interference, what bounds the sample size available to the second step of the algorithm?", "moderate", None, {}),
 "Q-FOC-010": ("For individualized effects of combinatorial treatments under network interference, why does naive local regression fail even when assignments were randomized?", "moderate", None, {}),
 "Q-FOC-011": ("In the Chile grade-retention paper's overview of regression discontinuity designs, why can units on either side of the cutoff be compared?", "weak", None, {}),
 "Q-FOC-012": ("In the Foundations part of the Cattaneo-Idrobo-Titiunik RD introduction, what does the bandwidth control in the local polynomial estimator of a discontinuity effect?", "weak", None, {}),
 "Q-FOC-013": ("In extreme-value causal structure learning, what intuition do recursive max-linear models formalize about large shocks in the graph?", "moderate", None, {}),
 "Q-FOC-014": ("For the instrumental-variable bounds on how important a shock is for forecast-error variance, what determines the lower and the upper bound of the identified set?", "moderate", None, {}),
 "Q-FOC-015": ("In the model where the network responds to the intervention in a randomized experiment, how does link formation after the intervention differ from before it?", "moderate", None, {}),
 "Q-FOC-016": ("In the taxonomy of common causal biases in observational studies, which category covers conditioning on a collider, and what does it do to the treatment-outcome relationship?", "moderate", ["2506.01191:c6"],
               {"answer_text": "The second category, collider bias: conditioning on a collider variable induces a spurious association between treatment and outcome."}),
 "Q-FOC-017": ("What risk does the multi-environment identification paper associate with including every available control variable when the causal graph is unknown?", "moderate", None, {}),
 "Q-FOC-018": ("In the coding-competition study of language effects, what property of a chosen set of regression variables makes it a valid backdoor adjustment set?", "moderate", None, {}),
 "Q-FOC-019": ("Why is the Shapley-based attribution of metric changes tested on simulated data before being applied to the advertising system?", "strong", None, {}),
 "Q-FOC-020": ("In the transformer framework for time-series causal discovery, how does the causal attention encoder impose the learned graph on its attention?", "moderate", ["2605.07280:c2"], {}),
 "Q-FOC-021": ("In the spatiotemporal transformer for synthetic counterfactuals in healthcare, how does the decoder's causal attention mask differ from a vanilla decoder's?", "strong", ["2207.04208:c2"], {}),
 "Q-FOC-022": ("In the study of continuous air-pollution exposures, how does the method single out the most harmful exposures while avoiding extrapolation from a fitted outcome model?", "moderate", None, {}),
 "Q-FOC-023": (None, "moderate", ["2506.16671:c2"], {}),
 "Q-FOC-024": (None, "weak", None, {}),
 "Q-FOC-025": ("In the econometrics data-fusion review, why does the classic female labor supply example create a sample selection problem for valid inference?", "moderate", None, {}),
 "Q-FOC-026": ("In the Earth-observation impact-evaluation paper, what does treatment geometry, a notion borrowed from radiation oncology, mean for a research design?", "strong", None, {}),
}
for qid, (q, ts, alt, extra) in COLL.items():
    it = items[qid]
    if q: it["question_text"] = q
    it["trap_strength"] = ts
    if alt: it["alternative_gold_chunk_ids"] = alt
    it.update(extra)

# offtopic-legit title-run fixes
items["Q-FOC-031"]["question_text"] = "In the two-stage prostate SBRT pencil-beam planning pipeline, how are the CT images aligned during preprocessing?"
items["Q-FOC-038"]["question_text"] = "In the robust-control study of a two-mass oscillator with fractional-order controllers, why are fractional-order extensions of PID attractive?"

# strict-tokenisation title-run fixes (hyphenated words count as separate words)
items["Q-FOC-030"]["question_text"] = "In the finite-volume discretisation of relativistic viscoresistive MHD, why is the one-dimensional shock-tube test demanding for the dissipative version?"
items["Q-FOC-033"]["question_text"] = "How many X-ray observations of solar-type stars were gathered, and how are they split between the two observatories?"
items["Q-FOC-034"]["question_text"] = "How does the any-to-image autoregressive generator keep conditioning tokens from leaking into content tokens?"

# Q-FOC-015: replace the doubtful distractor 2606.22349 with verified non-causal 'intervention' uses
it = items["Q-FOC-015"]
it["distractor_paper_ids"] = ["2606.27163", "2606.20880", "2411.05540", "2603.02551"]
it["distractor_evidence"] = [{"paper_id": "2606.27163", "chunk_id": "2606.27163:c55"},
                             {"paper_id": "2606.20880", "chunk_id": "2606.20880:c17"},
                             {"paper_id": "2411.05540", "chunk_id": "2411.05540:c3"},
                             {"paper_id": "2603.02551", "chunk_id": "2603.02551:c12"}]
it["colliding_domain"] = "human/manual intervention in robotics, software repair and testing; DAgger"


# Q-FOC-004: replaced (collision term "instrument" was at 4 items; new item built from term "mediation")
items["Q-FOC-004"] = {
 "question_id": "Q-FOC-004", "tests": "answerable", "dimension": "collision", "difficulty": "medium",
 "question_type": "Rationale", "source_paper_id": "2512.14764",
 "source_paper_title": "Scaling Causal Mediation for Complex Systems: A Framework for Root Cause Analysis",
 "section_path": "3 Generalized Natural Indirect Effect (NIE) Framework",
 "question_text": "In the method that extends mediation analysis to large logistics causal graphs, why must it give actionable insight even for factors operators cannot control?",
 "passage_excerpt": "Unlike simple textbook examples, real DAGs contain both controllable and non-controllable factors, making it critical to provide actionable insights even when the main root causes cannot be directly changed.",
 "answer_text": "Because real operational DAGs contain both controllable and non-controllable factors, so insight is needed even when the main root causes cannot be directly changed.",
 "paper_topic": "on", "collision_term": "mediation", "trap_strength": "moderate",
 "colliding_domain": "mediation layer / middleware and dispute mediation (software systems, negotiation, law)",
 "distractor_paper_ids": ["2606.09692", "2606.10173", "1304.3260"],
 "distractor_evidence": [{"paper_id": "2606.09692", "chunk_id": "2606.09692:c20"},
                         {"paper_id": "2606.10173", "chunk_id": "2606.10173:c2"},
                         {"paper_id": "1304.3260", "chunk_id": "1304.3260:c6"}],
}

# focus-absent rewrites / replacements. Hit counts are placeholders until verify reports reproduced counts.
def absent(qid, q, qt, diff, ev, near):
    items[qid] = {"tests": "absent", "dimension": "focus-absent", "difficulty": diff, "question_type": qt,
                  "question_text": q,
                  "answer_text": "Not in the corpus: no paper explains this; the only vocabulary matches are off-topic or passing citations.",
                  "absence_evidence": ev, "nearest_distractor_paper_id": near, "paper_topic": "absent", "question_id": qid}

absent("Q-FOC-042", "In a Blanchard-Quah decomposition, which shock is assumed to have no long-run effect on output, and how does that restriction pin down the impact matrix of a VAR?", "Procedure", "medium",
  [{"pattern": "Blanchard.{1,8}Quah", "hits": 3, "note": "3 chunks cite Blanchard & Quah (1989) in a list of SVAR identification schemes (2605.09870:c13 says only 'constraining cumulative effects'; c92; 2307.03074:c3); none says which shock or how the impact matrix is pinned down"},
   {"pattern": "(Blanchard.{1,8}Quah|long.run restrictions?).{0,300}(demand|supply|transitory|permanent).{0,200}(output|GDP)", "hits": 0, "note": "no chunk links the long-run restriction to a named shock and output"}],
  "2512.05661")
absent("Q-FOC-046", "In the Cochrane-Orcutt correction for AR(1) errors, what quasi-difference transformation is applied to the outcome and regressors before the treatment coefficient is re-estimated?", "Procedure", "hard",
  [{"pattern": "Cochrane.Orcutt", "hits": 2, "note": "2 passing mentions: 2603.17281:c12 lists it among error-structure options; 2403.08130:c7 says feasible BLUP needs iterative Cochrane-Orcutt or Prais-Winsten estimation of phi_1; neither gives the transformation"},
   {"pattern": "quasi.differenc.{0,250}(autocorrel|serial correl|AR\\(1\\))", "hits": 0, "note": "no chunk describes quasi-differencing for AR(1) errors"}],
  "2403.08130")
absent("Q-FOC-047", "How has a regression kink design been used to estimate the causal effect of galaxy-cluster membership on star formation, and what plays the role of the kinked assignment variable?", "Procedure", "medium",
  [{"pattern": "(regression kink|kink design|\\bRKD\\b).{0,300}galax|galax.{0,300}(regression kink|kink design|\\bRKD\\b)", "hits": 0, "note": "no regression-kink chunk mentions galaxies"},
   {"pattern": "galax.{0,300}(propensity|instrumental variable|regression discontinuity|difference.in.dif+erences?)", "hits": 11, "note": "astro papers using propensity-score matching for control samples (1603.06256, 2009.03915, 2203.07794 ...) and similar words, none uses a kink design"}],
  "1603.06256")
absent("Q-FOC-048", "Which identification strategy do Hirshleifer and Shumway use to show that morning sunshine causally affects daily stock returns, and how large is the estimated effect?", "Fact-Lookup", "medium",
  [{"pattern": "Hirshleifer.{0,40}Shumway|sunshine.{0,200}(stock|return|market)", "hits": 0, "note": "no chunk names the study or links sunshine to returns"},
   {"pattern": "sunshine", "hits": 35, "note": "broad: spurious (author surnames, bees/cat dialogue examples, astronomy); none links sunshine to returns"}],
  "2606.05318")
absent("Q-FOC-049", "What causal effect of solar sunspot activity on aggregate stock-market returns has been estimated, and which identification strategy makes that estimate credible?", "Fact-Lookup", "medium",
  [{"pattern": "sunspots?.{0,300}(stock|market|econom|GDP)|(stock|market|econom|GDP).{0,300}sunspots?", "hits": 1, "note": "1 chunk (2607.06702:c21) is a finance simulation chunk, not a sunspot-returns estimate"},
   {"pattern": "sunspot", "hits": 134, "note": "broad: solar-physics papers"}],
  "2606.05318")
absent("Q-FOC-050", "What causal effect of the lunar cycle on birth rates or violent crime has been estimated, and which quasi-experimental design makes that estimate credible?", "Fact-Lookup", "medium",
  [{"pattern": "(lunar|moon).{0,200}(birth|fertility|crime)", "hits": 3, "note": "3 spurious hits: 1712.02926:c14 (lunar new year), 2607.09598:c7, c19 (Moonshine ASR model, 'fertility' tokenizer)"},
   {"pattern": "\\bmoon\\b|lunar", "hits": 260, "note": "broad: astronomy / planetary-science papers"}],
  "2505.04651")

d["ground_truth"] = list(items.values())
json.dump(d, open(P, "w"), indent=1, ensure_ascii=False)
print("applied", len(items))
