# Waymo Safety Research — Methods, Models & Concepts Brief

*Interview preparation · 2026-08-23. Covers the 54 of 55 publications on
`waymo.com/safety/research/` held in the `waymo_av_safety` corpus (the one gap, C10, is a
paywalled cyclist-injury paper not obtainable). §10 extends coverage to safety-relevant Waymo
methods found **only in the wider curated corpus** (general research index + companion statistics
papers) that the safety pages don't surface. Every claim traces to the ingested papers; quotes
are verbatim and citable by paper id via the corpus MCP (`get_span`).*

---

## 0. The research programme in one paragraph

The safety-page portfolio answers one question — *how do you demonstrate an autonomous driver is
safe?* — with seven interlocking method families: **(1)** retrospective crash-rate benchmarking
against human baselines, **(2)** counterfactual reconstruction & simulation of real crashes,
**(3)** injury-biomechanics risk curves built from deep crash databases, **(4)** computational
cognitive modeling of human drivers (active inference, affordances, surprise), **(5)** normative
behavior-reference frameworks (what "good driving" means), **(6)** safety-assurance governance
(safety cases, absence-of-unreasonable-risk determinations, checklists, standardization), and
**(7)** population-health / Vision-Zero counterfactual policy analyses. Families 1–3 are
*retrospective* (what happened), 2–4 are *prospective* (what would happen), 5–6 are *normative*
(what should count as safe), 7 connects AV safety to public health.

---

## 1. Retrospective crash-rate benchmarking

**Core idea:** you cannot run a randomized trial on crash outcomes, so compare observed ADS crash
rates per mile against carefully constructed human baselines matched to the same geography, road
types, and reporting thresholds.

**Key papers & headline numbers**

| paper | design | result |
|---|---|---|
| *Waymo Public Road Safety Performance Data* (`2011.00038`) | 6.1M mi Phoenix incl. 65k driverless; **counterfactual simulations** for operator disengagements | 47 contact events (18 actual + 29 simulated), none life-threatening |
| *Comparison … at 7.1 Million Miles* (`2312.12675`) | NHTSA Standing General Order (SGO) data vs police-reported + naturalistic (NDS) benchmarks, **under-reporting adjusted** | any-injury-reported 0.6 vs 2.8 IPMM (**−80%**); police-reported 2.1 vs 4.68 IPMM (−55%) |
| *…by Crash Type at 56.7 Million Miles* (`local:6b9ccd0431f6`) | state VMT + police crashes with **dynamic spatial adjustment** (vehicle/road/geography matching) | any-injury-reported reductions **63–96%** by crash type; worst case V2V intersection **−96%**; suspected serious injury+ **−85%** (CI 39–99) |
| *Do AVs Outperform Latest-Generation HDVs?* (Swiss Re, `local:f6f1461f2c9a`) | third-party **auto liability claims**, 25.3M autonomous miles vs 500k+ claims / 200B mi exposure | property damage **−88%**, bodily injury **−92%** vs overall; −86%/−90% vs 2018–2021 vehicles |
| *Comparative safety performance (Heliyon)* (`local:5fa216c3425a`) | liability claims **calibrated by zip code + crash responsibility** | rider-only: bodily-injury claims **−100%**, property damage −76% |
| *Benchmarks Using Police-Reported Crash Data* (`2312.13228`) | methodology paper: selection, under-reporting adjustment, exposure matching | SF highest urban rate: 5.82 any-PD-or-injury IPMM |
| *From Stoplights to On-Ramps* (`2508.19425`) | freeway vs surface-street benchmarks, AZ/CA/GA/TX | Atlanta freeway any-injury 2.4 IPMM ≈ 3.5× Phoenix (0.7) |
| *High-resolution fatal crash benchmarks* (C24, `local:79c782071ad2`) | FARS + FHWA + INRIX GPS probes, top-50 urban areas | fatal-crash involvement rate varies **7.5×** (Memphis vs Boston); surface streets 2.3× freeways; weekend-night 6.2× weekday-day |

**Concepts to be fluent in:** IPMM (incidents per million miles); SGO (NHTSA Standing General
Order — ADS crash reporting regime); exposure matching; under-reporting adjustment (most
crashes never enter police data); ODD matching (operational design domain); why benchmark choice
matters (insurance claims have consistent reporting but no severity detail; police data has
severity but under-reports).

**Statistics:** comparisons come with confidence intervals from resampling — parametric bootstrap
in the 7.1M-mile study ("parametric bootstrap using the standard error for the benchmark crash
counts"), **Poisson bootstrap** (N=1000, 90% CI) in *Dynamic Benchmarks* (`2410.08903`), and a
novel **exponential bootstrap / fiducial CI construction** in `2604.03827`.

**Acknowledged limitations:** geographic/mileage-mix differences vs benchmarks; benchmark may
understate risk of newer fleets; low-severity performance not predictive of high-severity outcomes.

## 2. Counterfactual reconstruction & simulation (prospective evaluation)

**Core idea:** reconstruct real crashes in high-fidelity simulation, then swap the human driver
for the Waymo Driver — a counterfactual "what would the ADS have done?"

- *Waymo simulated driving behavior in reconstructed fatal crashes* (C23, `local:1d8d84d78b21`):
  72 fatal crashes / 91 vehicle actors from Chandler AZ. As **initiator**: avoided all collisions;
  as **responder**: prevented 82%, reduced severity in another 10%. Explicitly models sensor
  limitations and system latency.
- ***Collision Avoidance Testing* (CAT)** (`2212.08148`): scenario-based testing against **NIEON**
  (*non-impaired eyes-on driver*) — a reference model of a consistently attentive, non-impaired
  human driver; NIEON prevents 84% of serious-injury risk in responder-role scenarios.
- *Collision Avoidance Effectiveness* (SAE, `local:0983968f9ec2`): 16 reconstructed fatal
  conflicts — Waymo prevented 75% vs NIEON 62.5%; serious-injury risk −93% vs −84%.
- *Methodology for determining maximum injury potential* (C21, `local:7bf8bf93e22e`): worst-case
  injury quantification for critical scenarios, combining inelastic-collision delta-V estimation
  (incl. relative headings) with extreme-value-theory approaches from the literature (Arun et al.
  2021; Laureshyn et al. 2017 "extended delta-V").

**Why:** real ADS fatalities are too rare to measure directly; counterfactuals turn rare events
into measurable distributions. **Attack surface to expect in interviews:** simulation fidelity,
reference-model fairness ("is NIEON a fair human?"), reconstruction uncertainty, small samples.

## 3. Injury biomechanics: risk curves from deep crash databases

**Core idea:** P(injury | collision intensity) curves estimated from decades of in-depth crash
data, used both to set absolute safety thresholds and to score simulated events.

- **Standard estimator: binary logistic regression** on MAIS-thresholded outcomes
  (MAIS2+F = "at least AIS-2 or fatality"), explicitly aligned with ISO 26262 practices.
- **Data:** GIDAS (German In-Depth Accident Study) dominates — 6,576 cyclist collisions (1999–2022),
  2,499 motorcycle ones (1999–2023), 3,112 + 154 pedestrian cases; U.S. side uses NASS-CDS/CISS
  (48,238 occupants for the omni-directional model) with NHTSA survey weights.
- **Mechanistic predictors:** **Effective Collision Speed (ECS)** — accounts for vehicle AND
  vulnerable-road-user speed plus frictional loss in side impacts (motorcyclist friction factor
  estimated at 0.8); **NPROJ** — probability of a "normal projection" after impact.
- **Omni-directional model** (C22, `local:071d15c56158`): direction of force enters as a
  **second-order Fourier series** interacted with delta-V → continuous periodic risk surface over
  impact direction; AUC ≈ **0.91 (MAIS3) / 0.96 (MAIS5)**.
- **Non-linear terms:** age modeled as a natural cubic spline "in the log odds space with a knot
  at age 20" (C18); heavy vehicles produce AIS3+ at far lower speeds than passenger cars.
- ***TARGET* framework** (`local:f2811feacd35`): converts curves into **safe impact-speed
  thresholds at 10% MAIS3+ risk** — pedestrians 34 kph, cyclists/motorcyclists 49 kph (German
  data); U.S. passenger vehicles 99 kph frontal / 73 near-side / 126 rear.
- **Known artifact, openly discussed:** logistic regression predicts non-zero injury risk at zero
  speed; field data are **censored** (injured = left-censored, uninjured = right-censored);
  Weibull/log-normal survival models are named as candidate refinements "depending on the research
  objectives" (Kent & Funk 2004; Yoganandan et al. 2016) — see companion review
  `docs/WAYMO-SURVIVAL-ANALYSIS-REVIEW.md`.
- **Naturalistic-data variant** (B10, `local:aa069e80dac9`): 42 real pedestrian collisions from
  ~66M fleet miles; video+GPS+20 Hz accelerometer fused by global optimization to recover true
  impact speed; AIS3+ risk ranged <2%→~55%.

## 4. Computational cognitive modeling of human drivers

This is the portfolio's most research-y arm — building *generative models of humans* so that
benchmarks and simulations encode realistic behavior rather than averages.

- **Active inference / free-energy framework**: agents act to minimize **Expected Free Energy
  (EFE)**, decomposed into pragmatic (goal) + epistemic (information-gathering) value.
  - General driving framework (IWAI poster, `local:b3dd74970ec8`): uncertainty management, urgent
    conflicts, social interaction.
  - Collision avoidance poster (`local:ebf093becfa1`): **looming-based perception + evidence
    accumulation** reproduces human brake reaction times, deceleration magnitudes, crash rates.
  - Unified model (`2506.02215`): validated across three conflict scenarios (lead-vehicle braking,
    lateral incursion, right-turn-into-path) against a **meta-analysis of brake response times**
    and simulator studies; includes **norm-conditioned particle filtering**.
  - Learning such models from data (`2303.15201`): **bi-level optimization** recovers the agent's
    internal model + preferences from demonstrations; beats imitation learning on average behavior,
    degrades on extremes.
- **Affordances & reachability**: *"Looking for an out"* (`2505.14842`) — simulator experiments
  (opposite-direction lateral incursion variants) + reachability analysis; when escape paths were
  ambiguous only **13.6%** of participants avoided collision. Extended into the **Field of Safe
  Motion** (`2604.27168`): computes whether a collision-free escape route exists given kinematic
  limits and replanning delays; "frame violations" = no out.
- **Surprise & response timing**: *"Measuring Surprise in the Wild"* (`2305.07733`) — generative
  models over future road-user positions; new measures **Residual Information** and **Antithesis**.
  Response-timing framework (`2208.08651`, journal version of the idea): response = **belief update
  driven by surprising evidence**, fit to SHRP2 naturalistic rear-end conflicts — replaces
  fixed perception-response-time (PRT) constants.
- **Space-sharing as uncertainty reduction** (`2604.19838`): implicit coupling + normative
  expectations + explicit communication; resolution fails if norms are violated.

## 5. Normative frameworks: what counts as good driving

***Drivership*** (`2502.08121`, Springer ARTS chapter): societal expectations disaggregated into
**Empirical / Normative / Furtherance**; good driving = meeting Normative Expectations; operationalized
through behavior reference models (NIEON; surprise-based models). This is the conceptual bridge
between the cognitive-modeling arm and the assurance arm.

## 6. Safety assurance & governance

- **Layered defense** (`2011.00054` *Safety Methodologies & Readiness Determinations*):
  simulation + closed-course + public road testing atop hazard analysis and scenario-based
  verification; hardware/software redundancy.
- **Absence of Unreasonable Risk (AUR)**: *Building a Credible Case for Safety*
  (`local:e402895b56ca`) — layered/dynamic safety case, **Acceptance Criteria framework** defining
  a multi-dimensional hazard-evaluation space (severity potential, conflict role, behavioral
  capability, functionality status, aggregation level), technology-agnostic by design.
  *Determining Absence of Unreasonable Risk* (`local:39d37d41dd77`) — **twelve methodological
  criteria** spanning architectural, behavioral, operational domains; aggregate + event-level,
  prospective + retrospective metrics combined.
- **Safety-case auditing** (`2506.09929`): bottom-up assessment of claim support
  (procedural + implementation) and evidence status; **0–3 scoring rubrics**; warns against
  over-granular claims harming the case's "survivability" (maintainability).
- **RAVE checklist** (`local:4087ccce4c01`): 15 recommendations for retrospective AV studies
  (data alignment, bias control, conservative uncertainty quantification) — multi-industry working
  group.
- **Standardization landscape** (`2306.17682`): 8 thematic areas organizing the standards world
  around "how safe is safe enough?".
- **Safety Management System** (`local:750223d487eb`): AV-tailored SMS taxonomy drawn from
  aviation/chemical/nuclear practice.
- **Fatigue Risk Management** (`2208.12833`): prevention/monitoring/mitigation layers; Periodic
  Fatigue Surveys on the 9-point **Karolinska Sleepiness Scale**.
- Foundational: *Waymo Safety Report* (`local:2b0e7fb59b39`) — "Safety by Design", 20B+ simulated
  miles backing the program.

## 7. Vision Zero / population-health counterfactuals

- *Ride-hailing in the Safe System* (`local:0bce58005210`): applying injury-risk curves to CISS
  (14,944 collided vehicles, 2017–2023): a "Vision Zero fleet" (100% seat-belt compliance +
  newest vehicles) ⇒ MAIS3+ **−75%+**, MAIS5+ **−90%** vs worst-case current ride-hailing fleet.
- *Speed-limit compliance* (`local:24cb2ca8ce9b`): >1M road-segment traversals of fleet sensor
  data to estimate free-flow speed distributions; **Elvik exponential model** links speed reduction
  to crash risk: compliance could cut serious injuries 18–30%, fatalities 27–43% (~82 lives/yr in
  SF+Phoenix). 33–49% of drivers speeding; 85th-percentile 3.6–7.2 mph over.
- *Cyclist dooring surveillance* (`local:442bfd3211f4`): first national NEISS analysis (weighted
  n=17,156 injured); explicit treatment of ED-sampling censoring biasing helmet odds ratios.

## 8. Cross-cutting glossary (fast recall)

| term | meaning |
|---|---|
| MAIS k+F | Maximum Abbreviated Injury Scale ≥ k or fatality; standard severity endpoint |
| delta-V | velocity change of a vehicle during a crash — the primary kinetic severity dose |
| ECS | Effective Collision Speed — mechanistic speed measure incl. friction losses (side impacts) |
| IPMM | incidents per million miles — the benchmarking unit |
| SGO | NHTSA Standing General Order — mandatory ADS crash reporting |
| ODD | Operational Design Domain — where/when the ADS is designed to operate |
| NIEON | Non-Impaired Eyes-On driver reference model — Waymo's attentive-human benchmark |
| EFE | Expected Free Energy — active-inference objective (pragmatic + epistemic value) |
| FST/FSM | Field of Safe Travel / Safe Motion — reachability-based escape-route formulation |
| AUR | Absence of Unreasonable Risk — the deployment-determination target |
| RAVE | Retrospective Automated Vehicle Evaluation checklist |
| GIDAS / NASS-CDS / CISS / FARS / NEISS / SHRP2 / NDS | the deep crash databases each method leans on |

## 9. Likely interview lines of questioning (and where your answers live)

1. *"How do you compare ADS safety to humans without a controlled trial?"* → §1: matched
   benchmarks, exposure alignment, under-reporting adjustment, multiple independent baselines
   (police, insurance, NDS) triangulating one answer.
2. *"Your confidence intervals?"* → bootstrap family per outcome; conservative reporting; RAVE's
   uncertainty recommendations.
3. *"Is NIEON a fair human benchmark?"* → §2 + §5: NIEON encodes normative expectations
   (Drivership); sensitivity via responder/initiator roles; results reported for both.
4. *"Why logistic regression for injury risk? It predicts nonzero risk at zero speed."* → §3:
   acknowledged verbatim in TARGET §4.3; remedies discussed (Weibull/log-normal survival models,
   re-weighting); chosen because objective is relative comparison across populations.
5. *"How does simulation prove anything about the real world?"* → §2: reconstructions calibrated
   with real sensor data; latency/sensor limits modeled; small-sample honesty.
6. *"What is active inference buying you vs imitation learning?"* → §4: interpretable internal
   states, epistemic behavior (glances), response-timing emergence; learned-from-demonstrations
   variant (bi-level optimization).
7. *"What does 'safe enough' mean?"* → §6: AUR determination structure, Acceptance Criteria space,
   layered metrics, twelve criteria.
8. *"How does AV safety relate to Vision Zero?"* → §7: seat-belt/model-year and speed-compliance
   counterfactuals show fleet-level levers beyond ADS itself.

*Companion documents:* `docs/WAYMO-SURVIVAL-ANALYSIS-REVIEW.md` (deep dive on the censoring/
survival-analysis thread), `docs/WAYMO-SAFETY-STACK-REPORT.md` (infrastructure/data-generator
view of the same portfolio), `docs/WAYMO-CORPUS-STATUS.md` (corpus provenance), MCP access via
`app.serve --data-dir waymo/data` (every quote above resolves through `get_span`).

---

## 10. Beyond the safety page — safety-relevant Waymo methods found only in the wider corpus

The curated Waymo set (157 papers) contains substantial safety methodology **not surfaced on
`waymo.com/safety/research/`** — mostly from the general research index (`waymo.com/research/`)
plus companion statistics papers. These are fair game in an interview ("how do you actually test
rare events?") even though the safety pages don't advertise them.

### 10.1 Rare-event rate estimation: importance sampling done properly

`2604.03827` (*Confidence Intervals for Rate Estimation with Importance Sampling*) is the
statistical engine room for everything in §1:

- **Three-stage multi-stage IS design**: (1) importance-sample run segments from m-million-mile
  logs, favoring high-context driving; (2) simulate each segment with the ADS under test,
  auto-flagging candidate events; (3) importance-sample candidates again before **human review**
  labels true positives (`b15–b17`).
- Proposals are **ML models used as black boxes**, tuned low-precision/high-recall so nothing
  impactful is missed; inclusion implemented as independent Bernoulli trials (**Poisson
  sampling**) for parallelism (`b13`, `b18`).
- Unbiased rates via **Horvitz–Thompson** inside a compound-Poisson framework; uncertainty via a
  novel **exponential bootstrap** (fiducial argument, saddlepoint-approximated) that satisfies a
  newly proposed **monotonicity criterion**: summing disjoint event types must raise both point
  estimate *and* CI bounds (`b3`).
- Stated motivation: mature systems yield near-zero point estimates that "may paint a misleading
  picture of performance when variance is large" (`b8`). Historical lineage: Zhao et al. 2016
  importance-sampling accelerated evaluation (cited in `local:0983968f9ec2`).
- Related: adaptive importance sampling with likelihood-ratio correction and Distributionally
  Robust Optimization appears in the off-policy experience paper `2212.01375`.

### 10.2 Adaptive scenario discovery: finding the failures you didn't script

- ***Bayesian Adaptive Multifidelity Sampling* (BAMS)** (`2411.17826`): estimates the probability
  of undesirable behavior p_γ across a scenario space by prioritizing exploration where
  performance may be low — "leading to the identification of novel and critical scenarios that
  traditional methods might miss", demonstrated on real AV data. Direct answer to "how do you
  find unknown-unknowns?"
- Its critique companion, *Why Black-Box Bayesian Safety Assessment… is Problematic*
  (`local:60d676fabfd0`), shows contrived examples where naive black-box assessment misleads —
  good evidence the team stress-tests its own estimators.
- Older heritage: *Experimental Resilience Assessment of an Open-Source Driving Agent*
  (`1807.06172`) — **fault-injection experiments** (faults activated in 65.2% of guided
  injections) with outcome analysis; the resilience-testing ancestor of today's program.

### 10.3 Generative simulation & synthetic data (the counterfactual factory)

- **Waymax** (`2310.08710`): accelerated, data-driven simulator built on WOMD for large-scale
  agent behavior research — the open counterpart of internal closed-loop simulation.
- ***SceneDiffuser* family**: controllable scene generation with diffusion (`2412.12129`,
  incl. **data augmentation via log perturbation** of ground-truth scenes); **city-scale traffic
  simulation via a generative world model** (`2506.21976`, with learned validity masks);
  *SceneCrafter* multi-view scene editing (`2506.19488`).
- ***Drive&Gen*** (`2510.06209`): co-evaluates driving models and video generators, then
  **fine-tunes the planner on ~1M generated videos** to improve real performance — closing the
  loop from generator to policy.
- **Sim-agent RL**: *Improving Agent Behaviors with RL Fine-tuning* (`2409.18343`) — maximum-
  likelihood pre-training then RL against a Verlet-wrapped action space; explicitly critiques
  open-loop ADE metrics as weakly connected to planner quality.
- Why this matters for safety interviews: the counterfactual simulations of §2 need *other road
  users*; this family is where realistic, controllable co-actors come from — and WOSAC
  (`2305.12032`) is the public benchmark scoring generated agents against ground truth with
  likelihood-based distribution-matching metrics.

### 10.4 Counterfactual perturbation as a robustness test

***CausalAgents*** (`2207.03586`): evaluates motion-forecasting robustness by **deleting agents**
from real logged scenes — perturbations that preserve labels while probing spurious feature
reliance; introduces sensitivity metrics (including one requiring no ground truth for the perturbed
scene). Conceptual cousin of the role-swap counterfactuals in §2, applied at the perception/
prediction layer.

### 10.5 The auto-labeling data engine (why fleet scale converts into supervision)

The safety claims rest on labeled data at scales no human annotation team could produce; the
generator stack:

- **Auto Meta Labeling** (`2210.08061`): LiDAR-only open-set pipeline using scene-flow estimation +
  temporal aggregation → amodal 3-D boxes for moving objects without human labels.
- **Offboard 3-D auto-labeling** (`2103.05073`) and **pseudo-labeling** (`2103.02093`) from point-
  cloud sequences.
- **PseudoAugment** (`2210.13428`): augmentation with pseudo-label uncertainty gating;
  **LidarAugment** (`2210.13488`): searched 3-D augmentations.
- **Cost-aware, track-level active learning** (`2210.08375`): selects rare tracks for human
  labeling — humans go where machines are least confident.
- **UP-VL** (`2309.14491`): pre-trained vision-language models generate higher-quality auto-labels
  for open-set categories — safety framing explicit: "unacceptable for autonomous vehicles to fail
  to handle a category that is not present in the training data."
- Long-tail mining with rich auto-labels (3-D detection/mapping/tracking/prediction) in WOD-E2E
  (`2510.26125`).

### 10.6 Synthetic sensing & cross-fleet translation

- **Block-NeRF** (`2202.05263`): photorealistic neighborhood reconstruction from fleet imagery —
  the digital-twin precursor for sensor simulation.
- **SurfletGAN** (`2005.03844`): synthesizing realistic LiDAR data — early synthetic-sensor work.
- **Sensor2Sensor** (`2605.22809`): translates in-the-wild monocular dashcam video into
  "high-fidelity, multi-modal sensor suite (AV logs)" (multi-view cameras + LiDAR) — turning any
  partner fleet into a Waymo-format data source.
- **WOMD-LiDAR** (`2304.03834`): >100k scenes of synchronized raw-LiDAR motion forecasting —
  opening the raw-sensor layer to end-to-end research.

### 10.7 The end-to-end / foundation-model driver line

- ***EMMA*** (`2410.23262`): end-to-end multimodal LLM-style planner (camera-only, world-model +
  joint motion prediction objectives); limitations stated bluntly (3-D spatial reasoning, halved
  inference cost needed, hallucination risk).
- **Scaling laws for motion forecasting** (`2506.08228`): power-law loss vs compute/data/model
  scaling (following Kaplan/Hoffmann methodology) — the planning analogue of LLM scaling, with
  iso-FLOP optimal-loss analysis.
- **STELLAR** (`2605.20390`): systematic study of scale in 3-D-perception foundation models.
- Interview angle: the safety-page portfolio is deliberately model-agnostic (NIEON comparisons,
   crash-rate benchmarks) precisely because the behavioral stack underneath is still evolving
  through these lines.

### 10.8 Glossary additions

| term | meaning |
|---|---|
| Horvitz–Thompson estimator | unbiased total/rate estimator inverse-probability weighting survey samples |
| Exponential bootstrap (EB) | fiducial CI method for rare-event rates; satisfies monotonicity; saddlepoint-fast |
| Poisson sampling | per-unit independent Bernoulli inclusion — parallelizable complex survey design |
| WOMD / WOSAC / Waymax | Waymo Open Motion Dataset / Open Sim Agents Challenge / its open simulator |
| minADE / MR | min Average Displacement Error / Miss Rate — standard trajectory-forecasting metrics |
| DRO | Distributionally Robust Optimization — worst-case-weighted objective over distribution shifts |

### 10.9 Extra interview lines unlocked by the wider corpus

9. *"How do you measure something that almost never happens?"* → §10.1: ML-proposal importance
   sampling at two stages + human-review labels; unbiased HT point estimates; EB confidence
   intervals satisfying monotonicity.
10. *"How do you discover failure modes nobody scripted?"* → §10.2 BAMS adaptive multifidelity
    sampling; long-tail mining in WOD-E2E; contrast with the black-box-assessment critique.
11. *"Where do your simulated road users come from?"* → §10.3: diffusion world models trained on
    fleet logs (SceneDiffuser++), sim-agent RL, WOSAC-scored realism; planners improve after
    training on generated videos (Drive&Gen).
12. *"Fleet scale is nice — how does it become labels?"* → §10.5: offline auto-labeling, active
    learning for rare tracks, vision-language distillation for open-set categories.

---

## 11. Simulation benchmarking, testing & validation — where data science meets engineering and safety evaluation

This is the working interface between data-science teams, the simulation/perception engineering
teams, and the safety-evaluation team: someone has to *design the benchmarks, build the metrics,
and defend their validity*. The corpus shows five concrete practices.

### 11.1 Open simulation benchmarks (metric engineering in public)

| benchmark | what it tests | metric machinery |
|---|---|---|
| **WOSAC** — Waymo Open Sim Agents Challenge (`2305.12032`) | do generated agents behave like real ones? | distribution matching via **KDE-based negative log likelihood** of ground-truth trajectories under sampled rollouts; minSADE-style average-distance metrics |
| **Waymax** (`2310.08710`) | open simulator for planning/behavior research | "runs entirely on hardware accelerators such as TPUs/GPUs and supports **in-graph simulation** for training"; ships **learned and hard-coded behavior models** for reactive co-actors |
| **WOMD / WOMD-LiDAR** (`2304.03834`; interactive config: 104k scenarios / 7.64M agent tracks) | motion forecasting incl. raw-sensor variant | minADE/MR family; joint probabilistic rollouts with discrete **motion tokens**, teacher-forcing (MotionLM `2309.16534`) |
| **WOD-E2E** (`2510.26125`) | end-to-end driving on mined long-tail scenarios | novel **Rater Feedback Score**: "measures how closely the predicted trajectory matches **rater-annotated trajectory preference labels**" instead of log-distance, because ADE/L2 fail on multi-modal futures and PDMS-style collision metrics are "impractical… involving novel or hard-to-detect objects (e.g., the flock of birds)" |

The RFS design is the cleanest example of DS ↔ safety-eval collaboration: humans encode *what
counts as reasonable driving* as preference labels; the metric converts those into a score;
release includes public validation labels plus a held-out challenge test set.

### 11.2 Validating the generators themselves

A simulator is only evidence if its outputs are validated:

- ***SceneDiffuser++*/"CitySim"** (`2506.21976`): a "city-scale closed-loop traffic simulation
  system… [enabling] point-to-point driving simulation for obtaining trip-level statistics…
  holistic driving assessment… evaluation of driving behaviors during the trip, including safety
  and driving quality", explicitly aimed at "**pre-release evaluation of AV software by estimating
  safety and quality related rates**". Learned **validity masks** are predicted jointly with
  trajectories (supervising diffusion models where agents enter/leave scenes).
- ***Drive&Gen*** (`2510.06209`): proposes the **Behavior Permutation Test (BPT)** — "a novel
  metric to assess whether generated videos can 'fool' the planner, by measuring how similarly the
  planner responds 'behaviorally' to the generated scene versus the real scene." Then closes the
  loop: fine-tune planner on ~1M synthetic videos → real videos → measure improvement.
- **Sim-agent RL** (`2409.18343`): argues imitative metrics (ADE) connect weakly to the actual
  goal ("assessing the AD planner performance") and evaluates agents by downstream planner effect.
- WOSAC's likelihood framework itself is presented as the principled alternative to ad-hoc
  distance metrics (§11.1).

### 11.3 Benchmark construction as a data-science product

- ***Dynamic Benchmarks*** (`2410.08903`): spatial-and-temporal alignment methodology so ADS rates
  compare against human baselines computed over the *same* places, times, and conditions — with
  Poisson-bootstrap CIs throughout.
- **Long-tail mining** (`2510.26125`): eval scenarios selected via "rich auto-labels available in
  our dataset, including 3D detection, mapping, tracking, and prediction" — i.e., the labeling
  engine (§10.5) doubles as the eval-set generator.
- **Test allocation under a reference model** (CAT, `2212.08148:b39`): scenarios that NIEON passes
  trivially or can never avoid aren't oversampled; NIEON response-time parameters varied over
  fixed intervals with **single-proportion z-tests** to pick a discriminative mix.
- **Fatal-crash benchmarks at city resolution** (C24): FARS × FHWA VMT × INRIX probes fused to
  localize fatal-crash involvement rates per urban area/road type/time-of-day.

### 11.4 Acceptance criteria and validation gates

- CAT combines both ISO 34502:2022 options — aggregate targets *plus* per-scenario comparisons vs
  NIEON — so "satisfactory performance at an aggregate level does not unintentionally conceal
  concerning performance at single scenario levels" (`b20–b21`). Stringency knob: shifting the
  NIEON response-time intercept ≈ choosing a stricter human percentile.
- Safety-case auditing rubrics (0–3 claim/evidence scores, `2506.09929`) and the AUR
  Acceptance-Criteria space (`local:e402895b56ca`) define when evidence counts.
- RAVE checklist governs the retrospective studies' uncertainty reporting (§6).

### 11.5 What this says about the DS role on these teams

Concretely, the data scientists behind these papers: design metrics that survive adversarial
scrutiny (RFS vs ADE; BPT vs pixel fidelity; monotone CIs); run statistical power/allocation
analyses for test programs; build auto-label pipelines whose output doubles as eval ground truth;
validate generative simulators against logged reality before they may inform release decisions;
and translate safety-team requirements ("comparable or better than an attentive human") into
falsifiable numeric criteria with documented knobs.

## Glossary additions (simulation/testing)

| term | meaning |
|---|---|
| RFS | Rater Feedback Score — open-loop E2E driving metric scored against human rater preference labels |
| BPT | Behavior Permutation Test — checks whether a planner responds identically to generated vs real scenes |
| CitySim | SceneDiffuser++'s city-scale closed-loop traffic simulation for trip-level and pre-release evaluation |
| in-graph simulation | simulator stepped inside ML training graphs (TPU/GPU-resident), enabling gradient-trained policies |
| KDE-NLL | negative log likelihood of ground truth under a kernel density estimate of model rollouts (sim-realism metric) |

---

## 12. Uncertainty quantification and the bootstrap family — what they use, what's absent, what to say

*Added 2026-08-31. Companions: [`WAYMO-UNCERTAINTY-METHODS-REPORT.md`](WAYMO-UNCERTAINTY-METHODS-REPORT.md)
(full method inventory), [`BOOTSTRAP-VARIANTS-CHEATSHEET.md`](BOOTSTRAP-VARIANTS-CHEATSHEET.md)
(mechanics), [`NELSON-RATE-RATIO-IMPLEMENTATION.md`](NELSON-RATE-RATIO-IMPLEMENTATION.md) and
[`RATE-INTERVALS-AND-PVALUES-TOOLKIT.md`](RATE-INTERVALS-AND-PVALUES-TOOLKIT.md) (code).*

### 12.1 Their entire bootstrap vocabulary is four variants

Exhaustive `scan_corpus` over the 157 curated Waymo-authored papers:

| Variant | Where | Status |
|---|---|---|
| **Poisson bootstrap** | *Dynamic Benchmarks* `2410.08903:b42`, N=1000, 90% CI | used, **no rationale given** |
| **Nonparametric resampling** | VRU baseline (`local:bc031ecd9224`), n=1,000 | used |
| **Parametric bootstrap** | 7.1M miles `2312.12675:b56`, on CRSS survey-design SEs | **run and rejected** |
| **Exponential bootstrap (EB)** | `2604.03827` §5.3 | **invented** because PB undercovers |

**Scans to zero across all 157:** BCa · studentized/bootstrap-t · wild · pairs/residual (as named
methods) · bag-of-little-bootstraps · m-out-of-n · **block bootstrap** · **Rao-Wu / BRR / jackknife /
replicate weights**. Each absence below is a defensible talking point, not a gotcha.

### 12.2 Interval construction — the likeliest question, and the one gap in their practice

Resampling scheme ≠ interval construction. Four ways to turn `{θ*_b}` into an interval:

| Method | Mechanics | Use when |
|---|---|---|
| **Percentile** | quantiles of `θ*_b` at α/2, 1−α/2 | symmetric, ~unbiased statistic |
| **Basic** (reverse percentile) | `2θ̂ − q_{1−α/2}`, `2θ̂ − q_{α/2}` | bootstrap distribution is shifted |
| **Studentized** (bootstrap-t) | bootstrap the *t*-statistic; needs an SE per replicate | best coverage when an SE exists |
| **BCa** | bias-correction `z₀` (share of `θ*_b < θ̂`) + acceleration `a` (jackknife skewness) | **skewed statistics — i.e. crash rates** |

**Waymo uses percentile only** — "The distribution of a quantity of interest… across all bootstrap
iterations" (`2410.08903:b42`). Zero BCa mentions.

> **Line to have ready.** Crash rates are right-skewed and bounded below at zero — the canonical BCa
> case. A percentile interval on a skewed statistic is mis-centred. This is a low-cost improvement to
> *Dynamic Benchmarks*, not a criticism of the headline results.

### 12.3 Block bootstrap — the temporal-dependence gap

Zero uses, and their data is temporally dependent (multi-year window, changing software versions,
repeated conflicts per site). Flavours: **moving block** (overlapping, length `ℓ`) · **circular block**
(wraps, fixes end-effect underweighting) · **stationary** (Politis–Romano, random geometric `ℓ`).
Tuning is `ℓ` alone; `ℓ ~ n^(1/3)` rule of thumb; too short destroys the dependence, too long leaves
too few blocks.

> **Strongest "what would you improve" answer.** The Poisson bootstrap in *Dynamic Benchmarks* draws
> an independent weight **per crash event**, so any within-S2-cell or within-period clustering is
> destroyed by the resampling scheme. The spatial/temporal adjustment moves the point estimate up to
> 47% but contributes **zero variance** — S2 weights and HPMS VMT are treated as fixed constants.

### 12.4 Survey replicate-weight bootstrap — the underrated one

The human benchmark is **CRSS / NASS-CDS / CISS**: complex probability samples with strata, PSUs and
case weights. Zero uses of Rao-Wu, BRR, jackknife or replicate weights; variance is delegated to R's
`survey` package (Taylor linearization) and NHTSA (2019) combining guidance.

- **You cannot bootstrap survey data by resampling rows.** That ignores stratification and clustering
  and understates variance. Correct: **Rao-Wu rescaling** (resample PSUs within strata, rescale
  weights), **BRR**, or the survey's published replicate weights.
- **The sharp observation:** the *only* bootstrap that ever touched the survey design — the
  parametric bootstrap on CRSS survey-design SEs — is the one they **ran and discarded** for being
  narrower than Nelson. So the single design-correct variance estimate in the benchmarking pipeline
  lives in a rejected sensitivity check.

### 12.5 Regression bootstraps — for the injury-risk curves (§3)

| Variant | Mechanics | Assumes |
|---|---|---|
| **Pairs / case** | resample `(x, y)` rows | least — robust to heteroskedasticity **and** misspecification; safe default |
| **Residual** | resample residuals, add to fitted values | homoskedasticity + correct model |
| **Wild** | multiply each residual by mean-0 var-1 draw (Rademacher) | heteroskedastic errors; **the standard fix for few clusters** |

"Wild cluster bootstrap when clusters are few" is the connective tissue back to §12.3.

### 12.6 When the bootstrap is *inconsistent* — the judgment answer

Not inefficient — **wrong**:

- **Sample maximum / extremes** → naive bootstrap is inconsistent. Fix: **m-out-of-n** or
  **subsampling**. Ties directly to the EVT literature's choice to fit a parametric tail rather than
  bootstrap the extremes (see `EVT-CONFLICT-CRASH-ESTIMATION-REPORT.md`).
- **Rare events** → demonstrated *inside their own corpus*: "**PB systematically undercovers**";
  "coverage error for PB can be very large and even **close to 100% when true positive data is
  sparse**" (`2604.03827` §6.1, §6.3).
- **Boundary parameters** (variance component at 0), non-smooth functionals.

### 12.7 The line to carry into the room

Don't lead with a taxonomy — lead with **knowing when not to bootstrap**, because their own papers
demonstrate it twice and echoing their reasoning back beats listing methods:

1. **7.1M miles:** ran a parametric bootstrap, got *narrower* intervals, **rejected it for being
   narrower**, kept exact Nelson (1970). A choice against their own interest.
2. **`2604.03827`:** measured PB undercovering in the rare-event regime and **built a new estimator**
   rather than accept it.

**The unifying trade, in one sentence:** *exact methods buy guaranteed coverage at tiny counts by
assuming a distribution; bootstraps assume less and pay for it in coverage exactly where it matters
most.* Bootstrapping cannot manufacture information two events don't contain — with Y=2 there are two
things to resample and the extreme quantiles a 95% interval needs are the ones estimated worst. Hence:
exact (gamma / Nelson) for the headline rate ratios, bootstrap only where no analytic variance exists
(the reweighted dynamic benchmark).

### Glossary additions (uncertainty)

| term | meaning |
|---|---|
| Poisson bootstrap | weights ~ iid Poisson(1) instead of multinomial; streamable/parallel; the large-n limit of the standard bootstrap |
| exponential bootstrap (EB) | weights ~ iid Exp(1) with an **n+1**-th "next weight" from a fiducial argument; reserves mass for an unobserved event, so it doesn't collapse when data is sparse |
| BCa | bias-corrected and accelerated bootstrap interval; `z₀` corrects median bias, `a` corrects skewness |
| Rao-Wu bootstrap | survey bootstrap: resample PSUs within strata and rescale weights |
| monotonicity (of a rate CI) | summing disjoint event types should raise the point estimate **and** both bounds; EB satisfies it, Gamma methods don't (`2604.03827`) |
| credibility (actuarial) | insurance framing for "how believable is this rate estimate"; full-credibility standard n_f = 1082 (`local:4c3912bd5507`) |
