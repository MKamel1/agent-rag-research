# The Waymo Safety Stack — as visible through the 55 safety-research papers

*2026-08-23 · Interview preparation companion to `WAYMO-SAFETY-METHODS-INTERVIEW-BRIEF.md`.
Scope: the publications on `waymo.com/safety/research/` (55 entries; 54 in corpus). Where a stack
element is only evidenced by Waymo's *general* research portfolio (`waymo.com/research/`) or a
companion methodology paper held in the corpus, it is marked **[adjacent]** so you never overclaim
it from the safety page alone.*

---

## The stack at a glance

```
L1  FLEET & INSTRUMENTATION        the Waymo Driver: sensor suite, 3-D maps, ride-hailing ops
L2  OPERATIONAL TELEMETRY          SGO crash reporting, contact-event taxonomy, mileage ledgers
L3  EXTERNAL DATA RESOURCES        FARS·GIDAS·CISS/NASS-CDS·NEISS·SHRP-2·CRSS·FHWA·INRIX·claims
L4  NATURALISTIC DATA GENERATORS   Nexar dashcam fleets (100M–500M+ mi), video+GPS+accelerometer
L5  RECONSTRUCTION & ANNOTATION    video/sensor/map fusion → impact speeds; GT annotation protocols
L6  SCENARIO ENGINEERING           logical scenarios, ODLI/conflict typologies, surrogate targets
L7  SIMULATION ENGINE              closed-loop ADS-in-the-loop, counterfactual role-swap runs
L8  BEHAVIOR REFERENCE MODELS      NIEON; active-inference driver models; surprise/belief measures
L9  STATISTICAL INFERENCE          bootstrap family (Poisson/parametric/exponential), importance
                                   sampling [adjacent], survey weights, conservative CI methods
L10 ASSURANCE PROCESSES            layered testing, AUR determinations, scoring rubrics, RAVE, FRM
```

---

## L1 — Fleet & instrumentation

- **Sensor suite**: "an array of sensors that allow our vehicle to see 360°, both in daytime and
  at night, and up to nearly three football fields away" (*Waymo Safety Report*,
  `local:2b0e7fb59b39`, p. "The Autonomous Driving System").
- **In-house 3-D mapping**: "our team builds our own detailed three-dimensional maps that
  highlight road profiles, curbs and sidewalks, lane markers, crosswalks, traffic lights, stop
  signs…" (same report, "Where Am I?") — mapping is a first-class data product, later reused as a
  reconstruction input (L5).
- **Operations footprint** powering retrospective statistics: rider-only ride-hailing across
  Phoenix, San Francisco, Los Angeles (7.1M-mile study `2312.12675`; 56.7M-mile by-crash-type
  study `local:6b9ccd0431f6`).

## L2 — Operational telemetry & public reporting

- **SGO regime as a data source**: NHTSA Standing General Order event-level crash reports are both
  an input (`2312.12675`, `local:6b9ccd0431f6`) and an output Waymo commits to refining
  (*Building scientific consensus*, `local:73b22bed599f`, "Making Data Available": event-level SGO
  data is public while "more sensitive data… may be better suited for aggregation").
- **Precise operational definitions matter**: e.g., a "not in-transport" mile requires park gear +
  designated parking space ("within 18 inches of a curb" rule) — `local:6b9ccd0431f6`, "Waymo SGO
  Data". Expect questions about definitional edge cases.
- **Contact-event taxonomy**: events classified into scenario types such as **ODLI**
  (opposite-direction lateral incursion) with per-event tables including location codes (PHX5G),
  speeds, and initiator roles (`local:4c3912bd5507`, Contribution/appendix).

## L3 — External data resources (the benchmark side)

| resource | used for | papers |
|---|---|---|
| **FARS** | fatal crash inventories | fatal benchmarks `local:79c782071ad2`; speed-compliance lives-saved `local:24cb2ca8ce9b` |
| **FHWA Highway Statistics (HM-71, VM-4)** | urban VMT by road type | `local:79c782071ad2` |
| **INRIX GPS probe data** | high-resolution exposure | `local:79c782071ad2` |
| **CISS / NASS-CDS** | nationally representative crash sampling w/ survey weights | ride-hailing counterfactual `local:0bce58005210`; omni-directional model `local:071d15c56158`; 1M-miles severity comparison `local:4c3912bd5507` |
| **GIDAS** | deep German in-depth crashes (injury-risk curves) | cyclist `local:7b943f45c1da`, motorcyclist `local:bb74867d2259`, pedestrian `local:c92c18fe2ac2` |
| **NEISS** | ED-based surveillance (dooring) | `local:442bfd3211f4` |
| **SHRP-2 NDS** | naturalistic crashes/near-crashes for response timing & CAT scenarios | `2208.08651`, `2212.08148` |
| **CRSS** | police-report variance estimates feeding rate-ratio CIs | `2312.12675` (Confidence Intervals section) |
| **Third-party auto liability claims** | consistent-reporting human baseline (500k+ claims, 125–200B mi) | Heliyon `local:5fa216c3425a`; Swiss Re 25.3M-mi `local:f6f1461f2c9a` |

## L4 — Naturalistic data generators (the dashcam partnership line)

A distinctive Waymo move: instead of retrofitting research vehicles, they mine **commercial
dashcam fleets**:

- **Nexar fleets**: >100M mi in NYC for the ESV26 benchmarking work (*Refinements in Benchmarking…*
  `local:b12ef27e3cd6`: "vehicles equipped with Nexar dash cameras… anonymized video… GPS and
  accelerometers"); **>500 million VMT yielding 335 video-verified VRU collisions** (126 ped /
  144 cyc / 65 moto) for baseline VRU risk (C8, `local:bc031ecd9224`).
- Dense-urban LA pedestrian impacts (B10, `local:aa069e80dac9`) and U.S.-wide micromobility
  studies (`local:d45d629ccad0`) from "third-party vehicles equipped with aftermarket in-cabin
  dash cameras".
- Collision identification is itself a pipeline: "kinematic triggers, video review, and individual
  reporting" (C8, Data source).

## L5 — Reconstruction & annotation pipeline

- **Video + GPS + accelerometer + map fusion → impact speed**, corrected by "a global optimization
  routine" for sensor misalignment/asynchronicity (B10, `local:aa069e80dac9`).
- **Collision reconstruction without full ADS sensing**: "In the absence of high-fidelity sensing
  systems, such as a full ADS sensor suite or birds-eye cameras, variability exists within various
  elements of the reconstruction" (C23, `local:1d8d84d78b21`, §4.2) — uncertainty is named, not hidden.
- **Ground-truth annotation protocols**: brake-onset labeled against a "piecewise linear
  acceleration model" auto-estimator with manual GT + explicit "no response" labels
  (`2507.17943` / `local:ac6107f22da9`).

## L6 — Scenario engineering

- **Logical-scenario parameterization**: intersection-collision functional scenarios define
  variable spaces (speeds, accelerations, lane-violation flags) per PEGASUS-style methodology
  (Riedmaier et al. 2020 cited) — C20, `local:2e47fb1e0308`.
- **Conflict typology with contributing factors** for ADS safety evaluation (ESV, 
  `local:1023e9edcb19`): aggregation level chosen so a typology cell supports "a safety impact
  assessment of a potential system"; notes cloud-connected fleet data making large-scale NDS
  feasible.
- **Test-track reality check** (*Challenges … ADAS/active safety test track protocols*,
  `local:341648b7a22a`): ran Euro NCAP-style AEB VRU protocols against the Waymo Driver using
  **surrogate targets**; several tests deprioritized because "the increased capabilities of the
  Waymo Driver prevented the vehicle from even entering into a conflict" — i.e., classical ADAS
  test protocols saturate against a stronger system; occlusion creation was a practical difficulty.
- **Scenario taxonomies**: ODLI incident classes (L2); CAT urgent-evasive scenario sets drawn from
  real crashes + NDS near-crashes (`2212.08148`).

## L7 — Simulation engine (counterfactual, ADS-in-the-loop)

- **Role-swap counterfactuals**: reconstruct a real crash → replace one actor with the Waymo
  Driver as *initiator* or *responder*. Fatal-crash study (C23, `local:1d8d84d78b21`): avoided all
  as initiator; prevented 82% + reduced severity 10% more as responder. Insurance-grade honesty
  about assumptions: other road users simulated with **deterministic** human collision-avoidance
  behavior models "for simplicity" (`2011.00038`).
- **Disengagement counterfactuals**: 29 of 47 contact events in the 6.1M-mile dataset were
  simulated continuations of operator disengagements (`2011.00038`).
- **Fidelity commitments**: perception accuracy requirements give confidence that "CAT methodology
  performance across different variations of the same object is equivalent"; lighting/visibility
  effects acknowledged (`2212.08148`, Discussion).
- Scale context (public claims): 15B+ simulated miles behind the program (Safety Report).

## L8 — Behavior reference models (the "human" inside the machine)

- **NIEON** — Non-Impaired Eyes-On driver: the consistently attentive human benchmark used in CAT
  and effectiveness studies (prevents 84% of serious-injury risk; Waymo Driver −93%).
- **Active-inference driver models**: Expected-Free-Energy policies with looming perception,
  evidence accumulation, **norm-conditioned particle filtering**; implementation uses "particle
  filtering (for representing beliefs about future states) and the cross entropy method for policy
  selection" (`2311.06417`, Discussion). Validated against brake-RT meta-analyses and simulator
  studies with Bayesian parameter posteriors, Jensen-Shannon divergence and Wasserstein-distance
  fit checks (`2506.02215`).
- **Surprise measurement**: learned generative models over future positions; Residual Information
  and Antithesis measures (`2305.07733`) — the substrate for response-timing modeling (`2208.08651`,
  SHRP2-fit heuristic belief-update model).
- These models double as **scenario generators** of human behavior inside L7 simulations.

## L9 — Statistical inference toolkit

- **Bootstrap family** (choose per data structure):
  - *Poisson bootstrap*, N=1000, 90% CI — *Dynamic Benchmarks* `2410.08903` ("a random number from
    a Poisson distribution with mean 1…").
  - *Parametric bootstrap* using SE of benchmark crash counts — 7.1M-mile study `2312.12675`.
  - *Exponential (fiducial) bootstrap* for sparse-rate CIs — `2604.03827` **[adjacent]**.
  - *Nelson (1970) method* — reported as producing "wider (i.e., more conservative)" CIs in the
    56.7M-mile study's RAVE-conformance appendix (`local:6b9ccd0431f6`).
- **Importance sampling for rare events**: the rate-estimation framework requires "highly efficient
  importance sampling before it can be used to construct rate estimators", with a novel
  **monotonicity criterion** (summing disjoint event types raises point estimate *and* upper bound)
  — `2604.03827` **[adjacent]**. Historical AV accelerated-evaluation lineage cites Zhao et al.
  2016 lane-change importance sampling (`local:0983968f9ec2`, References). Adaptive importance
  sampling with likelihood-ratio correction + Distributionally Robust Optimization appears in the
  ML-side off-policy-experience paper `2212.01375` **[adjacent — research page]**.
- **Survey statistics**: NHTSA's method for combining NASS-CDS/CISS survey waves; CRSS variance
  estimates propagate into rate-ratio CIs (`2312.12675`).
- **Domain dose-response models**: logistic risk curves (L3 brief); Elvik exponential speed-risk
  model (`local:24cb2ca8ce9b`); biomechanical tolerance literature (Kent & Funk 2004; Yoganandan
  et al. 2016).

## L10 — Assurance processes wrapping the stack

Layered sim → closed-course → public-road verification under hazard analysis (`2011.00054`);
Acceptance-Criteria hazard space + layered dynamic safety case (`local:e402895b56ca`); twelve AUR
criteria integrating aggregate + event-level and prospective + retrospective evidence
(`local:39d37d41dd77`); bottom-up claim/evidence scoring rubrics 0–3 (`2506.09929`); RAVE's 15
recommendations (`local:4087ccce4c01`); SMS taxonomy (`local:750223d487eb`); fatigue KSS surveys
(`2208.12833`). Each statistical artifact above flows into this governance layer — numbers exist
to be consumed by claims.

---

## What the publications deliberately do NOT show

- Internal simulator architecture, perception-model internals, labeling/auto-label pipelines
  (these live in the general research portfolio — WOMD ecosystem, STELLAR, EMMA — not the safety
  pages).
- Proprietary scenario-mining thresholds and the exact generative scene models behind "15B+
  simulated miles".
- Anything identifying individual operators or exact geo-granular operations (SGO granularity is
  actively managed — `local:73b22bed599f`, "Providing Data Granularity").

If pressed on these in an interview, the defensible answer is structural: the safety pages publish
the *measurement and assurance* layers precisely because those are the parts regulators and peers
must be able to audit; the *generative* layers are published as methods research elsewhere.

## Rapid-fire interview cues

- "What data would you need to replicate their benchmarking?" → L3 table + L2 definitions + L9 CI
  method of choice.
- "Why is NIEON legitimate?" → normative grounding (Drivership), dual responder/initiator roles,
  meta-analytic validation of the underlying behavior models (L8).
- "Name three ways they handle rare-event statistics." → Poisson/parametric/exponential bootstraps;
  importance sampling [adjacent]; Nelson conservative CIs.
- "How do dashcams become science?" → L4→L5 pipeline: triggers → video review → fused
  reconstruction → risk-curve application.
