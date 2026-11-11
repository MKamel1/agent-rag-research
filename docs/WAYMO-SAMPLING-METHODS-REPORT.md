# How Waymo Sizes a Safety Study

*Sampling procedures and sample-size determination across the Waymo safety papers. Retrieved
2026-08-25 from the local `waymo_av_safety` corpus. Every claim carries the verbatim passage it
came from.*

Published as an artifact: <https://claude.ai/code/artifact/fccb8b6d-f671-418b-8085-a17e1819d1fc>

---

## The short answer: one question, four machines

Waymo's safety literature does not have *a* sampling procedure. It has four, each attached to a
different stage of what its authors call the safety determination lifecycle, and each with its own
logic for how much data is enough. Two are budget-constrained sampling designs, one is a stopping
rule, one is a census, and only the last answers "how many samples" with a power analysis.

| Method family | Sampling unit | Procedure | How "enough" is decided |
|---|---|---|---|
| Prospective rate estimation | Run segment / candidate event | Multi-stage importance sampling via Poisson sampling | Fixed human-review budget ratio *b*; allocation chosen for minimum variance |
| Scenario-based testing (CAT) | Concrete test scenario | ISO 34502 segmentation, not exhaustive parameter sweep | Stopping rule: single-proportion *z*-test on the reference model |
| Counterfactual reconstruction | Real fatal collision | Census of every fatal crash in the ODD, 2008–2017 | Not sized — the ODD defines the population |
| Retrospective benchmarking | Crashed vehicle per VMT | ADS: census. Benchmark: subselection + underreporting and spatial adjustment | Poisson power analysis: α = 0.05, 80% power, mileage from benchmark rate × effect size |

Throughout: the **ADS side** is measured, mandated and censused; the **human side** is estimated,
sampled and adjusted. That asymmetry is the subject of its own section below.

---

## Stage 1 — Predict, before deployment: multi-stage importance sampling

**Confidence Intervals for Rate Estimation with Importance Sampling in Autonomous Vehicle
Evaluation** (arXiv 2604.03827) — Chen, Zhou, Lee, Chamandy & Hohnhold, Waymo LLC, 2026.

This is the only paper in the set that is *about* a sampling procedure. The problem it solves is
that the events worth measuring are too rare to find by driving, and too expensive to adjudicate by
hand at scale.

### Why not simply drive more miles

> "Suppose that we want to evaluate today's software version and that it takes *k* days to collect a
> sufficiently large volume of on-road test data for the desired level of statistical precision. If
> we find after one round of data collection that there is need for improvement, we must first
> implement the required software changes, and then wait an additional *k* days to evaluate the
> system again. […] This cycle of waiting for on-road test driving data, making code changes, and
> waiting again to validate those changes makes AV software development purely using on-road test
> driving infeasible on any reasonable time scale."
>
> — §1 Introduction, p.0

### The procedure: three steps, two sampling stages

> "(1) Draw a large sample of data points (each data point is a short contiguous block of
> driving—referred to hereafter as a run segment) by importance sampling from logs saved from
> on-road testing over a total of *m* million miles, favoring interesting driving contexts (e.g.
> segments on busy roads with other road users in close proximity to the AV);
>
> (2) Simulate each run segment from Step 1 with the AV software to be evaluated, and automatically
> identify candidate events of interest […];
>
> (3) Draw a sample set of the candidate events obtained from Step 2 by importance sampling; pass
> these segments to human review, which identifies whether or not a candidate event is a true
> positive […].
>
> The sampling probabilities are determined by trained machine learning models […]. To minimize
> technical complexity, the implementation of importance sampling is based on Poisson sampling
> (McCormick (1937)); that is, whether a run segment is sampled for simulation or whether a
> simulated event is sampled for human review is determined by an independent Bernoulli trial, which
> can be performed in parallel to enable large-scale tasks."
>
> — §2.1 Multi-stage importance sampling, p.2

The reduction is severe and deliberate:

> "For a sense of scale, the original data set of on-road driving may contain 10s of millions of
> miles, from which we choose to simulate 10s of thousands to millions of miles, depending on the
> application."
>
> — §2 Rate estimation: problem and data specification, p.2

### Why importance sampling rather than uniform

> "In both stages, probabilistic sampling is employed to reduce the pool of potentially interesting
> data to satisfy resource constraints, cutting down the data by orders of magnitude while retaining
> most of the signal of interest. We use importance sampling, and leverage machine learning models
> designed to favor events with a higher likelihood of being a true positive event of interest. This
> importance sampling approach allows for unbiased rate estimation while making more efficient use
> of resources, especially when events are rare. **Simple uniform sampling, by contrast, would
> generate few or even zero events of interest in some applications.** These machine learning models
> are typically tuned to a lower-precision, higher-recall operating point to avoid missing
> potentially impactful events […]. From the statistician's perspective, the models used as inputs
> to importance sampling probabilities can be treated as 'black boxes', and our estimation
> procedures should be robust to their precise structure and feature space."
>
> — §2, p.2

That last sentence is the design constraint that picks the estimator. Because the ML model is
treated as a black box, unbiasedness has to come from the *design*, not from the model being right —
which is exactly what a Horvitz–Thompson estimator buys:

> "Under this model, ∑ᵢ r(Vᵢ) would be a natural estimator of the rate θ; however, *r* is unknown.
> Instead, we adopt the Horvitz-Thompson estimator denoted as θ̂, which is unbiased, i.e. E(θ̂) = θ
> […] Wᵢ = Bᵢ / p(Vᵢ) × Yᵢ."
>
> — §3 The model formulation for rate estimation, p.4

### How many samples: a budget, not a power calculation

> "Let *b* ∈ (0,1) be the budget ratio for sampling (i.e. smaller *b* means less human review) and
> let p(v) be the sampling function."
>
> — §6 Numerical Studies, p.10

> "p(v) ∝ r(v)^γ where γ is the index and **γ = 1/2 corresponds to optimal importance sampling in
> terms of variance minimization** (e.g. Liu (2019)), while γ close to 0 corresponds to near uniform
> sampling. […] otherwise one may set γ̂ = 1/2, which per numerical studies often works reasonably
> well when sampling is not too far from optimal."
>
> — §5.3.1 Choice of next weight, p.9

And they name the reason to deliberately sample *worse* than optimal — hedging against their own
model's errors:

> "In the range γ < 0.5, which approaches simple random sampling at γ = 0, we describe sampling as
> **defensive**. In such a regime, the risk of missing interesting classes of events because of ML
> model errors is reduced. By contrast, the regime γ > 0.5 is characterized as **greedy** sampling,
> since it samples more heavily than optimal for candidates with high true positive probabilities
> and down-samples others."
>
> — §6 Numerical Studies, p.10

The real deployment runs at a budget ratio under one percent:

> "In this section, we report some results from a real case study which consists of millions of
> simulations and tens of thousands of human reviews with the budget ratio less than 1%. […] the
> distribution of overall sampling probabilities (i.e. p(Vᵢ)) is very heavy-tailed."
>
> — §7 Real-world data analysis, p.12

### Why a new confidence interval, and why "monotonicity"

The justification is unusually candid — it is about being read correctly by non-statisticians:

> "We also advocate for a new monotonicity criterion for rate CIs—summing the rates of disjoint
> types of events should produce not only a higher point estimate but also higher confidence bounds
> than for the individual rates—that facilitates interpretability in real applications. We propose a
> novel exponential bootstrap (EB) method for CI construction based on a fiducial argument; it
> satisfies the monotonicity property, while novel extensions of some existing methods do not."
>
> — Abstract, p.0

> "For example, the lower bound estimate of the rate of 5+ minute congestion events should not
> exceed the lower bound estimate of the rate of 1+ minute congestion events."
>
> — §2.2 Estimand, p.2

> "We discovered that these methods however do not have a desired monotonicity property […] which is
> important in the applied setting as it allows practitioners to communicate a consistent story to
> business decision-makers."
>
> — §4 Related work, p.4

### The successor: adaptive sampling that discovers as it estimates

**Rate-Informed Discovery via Bayesian Adaptive Multifidelity Sampling** (arXiv 2411.17826) — Sinha,
Nikdel, Paul & Whiteson, 2024.

> "since this approach essentially produces a Monte Carlo estimate of the AV's performance, the
> scale required for evaluation near human-level performance is too large [16] to repeat at regular
> intervals during development."
>
> "BAMS discovers 10 times as many issues as Monte Carlo (MC) and importance sampling (IS)
> baselines, while at the same time generating rate estimates with variances 15 and 6 times narrower
> than MC and IS baselines respectively."
>
> — §1 Introduction and Abstract, p.0

---

## Stage 2 — Test, before release: a stopping rule, not a sample size

**Collision Avoidance Testing of the Waymo Automated Driving System** (arXiv 2212.08148) — Kusano,
Beatty, Schnelle, Favaro, Crary & Victor, 2022.

CAT never asks "how many scenarios do we need?" in the abstract. It asks whether the scenario set
can still tell a passing driver from a failing one — and collects more only where it can't.

### Why a reference model instead of a rate target

> "The ISO draft standard on scenario-based safety evaluation (ISO, 2022b) brings forth two possible
> ways to approach the setting of safety test objectives: (a) the specification of 'an upper
> boundary value of the acceptable occurrence rate of a measurable behavior of the ADS' […]; and/or
> (b) the specification of 'a performance reference model regarding the capability of the ADS to
> handle certain scenarios safely, based on minimum performance levels required for these scenarios'
> […]. The two approaches are not in opposition with each other."
>
> — Method to Set the Test Objective, p.4

The reference model is NIEON — a driver who does not exist:

> "The reference model used in this study reflects the response time and evasive action (referred to
> as collision avoidance) of a human driver that is non-impaired, with eyes on the conflict (NIEON)
> - **a consistently performing, always-attentive driver that does not exist in the human
> population**. Notably, the NIEON model is a tool for evaluating collision avoidance only, as it
> inherits the pre-conflict behaviors (includes conflict avoidance) of the ADS that is being
> evaluated. In this way, the testing regime isolates the analysis to focus only on the collision
> avoidance effect."
>
> — *Collision Avoidance Effectiveness of an Automated Driving System Using a Human Driver Behavior
> Reference Model in Reconstructed Fatal Collisions*, Abstract, p.0

### The allocation rule: don't oversample what can't discriminate

> "because the acceptance criteria for the safety test is a comparison of the ADS performance to a
> reference behavior model (the NIEON model), the scenarios selected for testing must be able to
> differentiate between passing and failing behavior of the reference model. That is, scenarios in
> which the reference model easily passes (are 'too easy') or has no chance of avoiding
> ('unavoidable') need not be oversampled to achieve the test objective. […] considering that the
> CAT method employs a scoring methodology that compares the ADS and reference model performance,
> oversampling of the 'too easy' or 'too hard' space would not affect the results as both the ADS
> and reference model would have the same outcome."
>
> — Guiding Principles for Test Case Allocation, p.9

### How many test cases: a *z*-test that can't be gamed

> "To determine the appropriate mix of scenarios, the reference behavior model response time is
> varied by several fixed intervals. **A single-proportion z-test is then applied to the rate of
> failure of the different reference behavior model levels to determine if the rates are
> statistically different.** This z-test is performed on the safety groups that make up the
> aggregate scoring. **Additional scenarios are collected for safety groups that do not have a
> statistically significant difference in passing rate collision metric.** […] Note that this
> statistical diagnostic is performed only on the NIEON model results and is independent of the ADS
> performance."
>
> — Guiding Principles for Test Case Allocation, p.9

> **My reading, not the paper's words.** The final clause is the load-bearing one. Because the
> adequacy check runs only on the reference model, the system under test cannot influence how much
> testing it receives — a sample-size rule that stays honest when the thing being measured is also
> the thing being shipped.

### Why not sweep the parameter space

> "the test case allocation used in the CAT methodology favors a segmentation approach to determine
> representative scenarios for all hazardous scenarios over an approach that exhaustively samples
> the logical scenario space. […] an exhaustive sampling of all parameter types (e.g., all colors of
> vehicles) would cause the number of scenarios to become excessively large, which is often referred
> to as the 'parameter explosion' problem. The segmentation approach is suggested in ISO 34502 (ISO,
> 2022b) as a possible solution […]. The type of 'unknown-unknown' scenario discovery that may be
> achieved by exhaustive or adaptive scenario generation are achieved through other simulation
> efforts (such as simulated deployments), hazard analysis, and platform V&V."
>
> — Guiding Principles for Test Case Allocation, p.9

---

## Stage 3 — Reconstruct, for rare severity: a census inside the ODD

**Waymo simulated driving behavior in reconstructed fatal crashes within an autonomous vehicle
operating domain** — Scanlon et al. (journal PDF).

For fatal crashes, sampling is abandoned entirely — and the paper explains why, in a passage that
names the trade-off directly.

### The ODD dilemma

> "The aforementioned prospective studies have most often relied on counterfactual simulation of
> nationally representative samples of crashes. For example, widely-used crash databases include the
> U.S. Fatal Accident Reporting Systems (FARS), National Automotive Sampling System (NASS), more
> recently the Crash Report Sampling System (CRSS) and Crash Investigation Sampling System (CISS)
> […].
>
> The ODD dilemma is the tradeoff between using large, robust datasets (e.g., aforementioned
> nationally representative databases) and small, ODD-specific datasets like the one used in this
> study. **The larger datasets may be representative of populations (e.g., the entire country) but
> not representative of a specific ODD. The smaller ODD-specific samples are representative of that
> ODD but may be smaller in size, and thus have larger variability potentially missing unobserved
> crashes.**"
>
> — §1.3 The ODD dilemma, p.2

### What "census" means in counts

> "A census of fatal, human-involved collisions was examined for years 2008 through 2017 for
> Chandler, AZ, which overlaps the current geographic ODD of the Waymo One fully automated
> ridehailing service. Crash reconstructions were performed on all available fatal collisions that
> involved a passenger vehicle as one of the first collision partners and an available map in this
> ODD […]. The final dataset consisted of a total of 72 crashes and 91 vehicle actors (52 initiators
> and 39 responders) for simulations."
>
> — Abstract, p.0

> "A total of 107 fatal collisions that occurred within Chandler, Arizona were identified from 2008
> to 2017. Public records requests […] were made to ADOT, the Chandler P.D, and the Arizona Dept of
> Public Safety for all 107 collisions. Relevant materials were available and provided for a total
> of 92 collisions. One of these collisions took place on a roadway that had changed substantially
> from the time of the crash and was excluded from further analysis due to a lack of environment for
> performing the simulation."
>
> — §3.1 Simulation case set, p.7

### The bias control that replaces randomization

> "A third-party engineering firm was contracted to perform the collision reconstructions according
> to reconstruction industry best practices. […] **The reconstructions were performed by trained
> experts without instruction or knowledge of the ADS design. The reconstructionists were also kept
> blind to the intended simulation purpose of the current study and were unaware of the identity of
> the simulating party (Waymo).**"
>
> — §2.4 Collision reconstruction, p.4

---

## Stage 4 — Confirm, after deployment: the power analysis that answers "how many miles"

**Benchmarks for Retrospective Automated Driving System Crash Rate Analysis Using Police-Reported
Crash Data** (arXiv 2312.13228) — Scanlon, Kusano, Fraade-Blanar, McMurry, Chen & Victor, 2023.
**From Stoplights to On-Ramps** (arXiv 2508.19425) — Scanlon, McMurry, Chen, Kusano & Victor, 2025.

This is the only family where a required sample size is computed in advance.

> "To investigate how many miles would need to be driven to have a high probability of showing
> retrospective safety impact at a statistically significant level, we performed a power analysis.
> For this calculation, we considered a fictive ADS which has a known crashed vehicle rate that is
> some percentage of the human benchmarks derived in this study. Using this setup, we calculated the
> mileage required to detect a statistically significant difference in performance. **We used sample
> size formulas based on the asymptotic normal approximation to the Poisson distribution and
> targeted 80% statistical power using 2-sided tests with α = 0.05.**"
>
> — 2312.13228, Statistical Power Analysis, p.5

The 2025 freeway paper prints the formula itself:

```
                        ( sqrt(λ_ADS) · Φ⁻¹(1−β)  +  sqrt(λ_Human) · Φ⁻¹(α/2) )²
Required Mileage  =     ───────────────────────────────────────────────────────
                                      ( λ_ADS − λ_Human )²

λ_ADS, λ_Human = crash rates · Φ⁻¹ = standard normal quantile
1−β = desired power (e.g. 0.8) · α = type I error (e.g. 0.05)
```

> "Power analysis was relied upon to estimate the amount of VMT required to determine statistical
> significance given assumed ADS crash rates relative to the human benchmark. […] **The VMT required
> to draw statistically significant conclusions in a power analysis is a function of the benchmark
> rate and effect size (i.e., relative ADS performance).** Several ADS performance levels were
> evaluated, including 25%, 50%, 75%, and 90% reductions in crash rates and 25% and 50% increases in
> crash rates. Sample size formulas were used that model asymptotic normal approximations to a
> Poisson distribution. The method targeted 80% statistical power using two-sided tests with α =
> 0.05."
>
> — 2508.19425, Power Analysis Methodology, p.12

### What the formula returns

| Outcome level | Fictive ADS rate vs benchmark | Miles required |
|---|---|---|
| Suspected serious injury+ | 50% of benchmark | ≈ 240,000,000 |
| Suspected serious injury+ | 10% of benchmark | ≈ 56,000,000 |
| Police-reported | 75% of benchmark | 61,900,000 |
| Police-reported | 25% of benchmark | 5,400,000 |
| Fatal | range of effect sizes | 10⁸ – 10⁹ |

> "Consider, for example, a fictive ADS suspected serious injury+ crash rate that is observed to be
> 50% of the benchmark crash rate. This analysis indicates that approximately 240 million miles
> driven by the ADS would be required to determine statistical significance. Conversely, if that
> crash rate was 10% of the benchmark crash rate, the required mileage would only be approximately
> 56 million miles. […] For the fatal vehicle crash rates, the required ADS VMT to establish
> statistical significance ranges from hundreds of millions to billions of miles of driving. **An
> important conclusion from Table 3 is that both the magnitude of the benchmark rate and the
> magnitude of the relative ADS performance difference determines the VMT required for statistical
> significance.**"
>
> — 2312.13228, Statistical Power Analysis, p.8

A consequence that trips people up: *safer* road types need *more* miles.

> "**The required mileage is inversely proportional to the benchmark crash rate; a lower crash rate
> requires more data (mileage) to achieve statistical confidence. Therefore, because freeways have
> lower crash rates than their surface street counterparts, they require substantially more mileage
> to validate safety performance.**"
>
> — 2508.19425, Required Mileage for Statistical Testing

### Why this framing, and why it overturns a famous result

The power analysis exists partly to answer Kalra & Paddock's 2016 "you'd need billions of miles, so
this is infeasible" argument. The rebuttal is about effect size, not about statistics:

> "The conclusion of Kalra and Paddock (2016) was generally that it is infeasible to use public road
> testing data to draw conclusions about ADS safety performance due to the large number of miles
> needed. **The analysis of Kalra and Paddock (2016) assumed modest differences between the ADS and
> the benchmark crash rates, using an ADS that has a crash rate of 80% of the benchmark as a
> reference point.** This may have been a prudent reference at the time when only early testing data
> from ADS was available. The results of early ADS safety impact analysis using RO data (Kusano et
> al., 2024) suggest that […] Police-reported crashes reduced between 51% and 70% […]. The larger
> the reduction in crash rates due to the ADS, the fewer miles are needed for statistical
> significance. For example, for the police-reported benchmark, Table 3 showed that an ADS with 25%
> the human benchmark would require 5.4 million miles compared to 61.9 million miles for an ADS that
> had 75% the human benchmark, an order of magnitude difference in the required miles."
>
> — 2312.13228, A.7 Power Analysis Comparison to Kalra and Paddock, p.28

They also correct two errors in the earlier calculation — a units error and a rounding choice:

> "Kalra and Paddock (2016) improperly used a fatality rate (fatally injured persons per VMT) rather
> than a vehicle-level crash rate."
>
> "Another difference […] was that this paper rounded the number of expected events to the next
> lowest integer, whereas Kalra and Paddock (2016) appeared to have computed the number of miles
> using fractional event counts."
>
> — 2312.13228, A.7, p.28

> "We identified multiple publications that improperly compared human crash-level rates to ADS
> vehicle-level rates (Banerjee et al., 2018; Blanco et al., 2016; Cummings, 2024; Favarò et al.,
> 2017; Kalra and Paddock, 2016; Schoettle and Sivak, 2015)."
>
> — 2312.13228, A.4 Errors When Computing a Vehicle-level Crash Rate, p.23

---

## The asymmetry: why only the human side gets resampled

The sampling and adjustment machinery is applied to human crashes and not to Waymo's. There is a
documented answer in three parts.

### 1. The ADS crash count is fixed by regulation, so there is nothing to sample

> "As NHTSA SGO ADS crashes are a mandated and publicly available data source, Waymo's NHTSA SGO
> reportable crashes became the basis for the incidents examined in this study. **The SGO reporting
> is required in all states, and thus is the most complete crash reporting required for an ADS fleet
> operator.**"
>
> — *Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million Miles* (arXiv
> 2312.12675), Matching of Benchmark and ADS Data, p.4

And ADS exposure is measured, not estimated:

> "Waymo mileage totals and distributions are established through continuous tracking of sensors
> (e.g., vehicle odometer readings on the rear wheel)."
>
> — *Comparison of Waymo Rider-Only Crash Rates by Crash Type to Human Benchmarks at 56.7 Million
> Miles*, Human Benchmark Data, p.25

### 2. The human side is where the sampling actually is — in both numerator and denominator

> "The Arizona Department of Transportation (ADOT) and Texas Department of Transportation (TxDOT)
> both annually compile a census of all police-reported crashes within their state. **The California
> Highway Patrol (CHP) compiles a subset of the total police-reported crashes** within the Statewide
> Integrated Traffic Records System (SWITRS). […] crashes involving property damage only (PDO) are
> not universally reported as 'some agencies report only partial numbers of their PDO crashes, or
> none at all' (CHP 2021)."
>
> "All of these mileage totals are geographic-specific estimates **based on established traffic
> counting sampling methodologies on specific roadways for limited periods** within the respective
> jurisdictions. The extrapolation to all roadways is done using geographic-specific modeling
> techniques."
>
> — *…at 56.7 Million Miles*, Human Benchmark Data, p.25

> **My reading, not the papers' words.** Put those two together and the asymmetry stops looking like
> a thumb on the scale: the ADS arm is a census with instrument-measured exposure, and the human arm
> is a sample-based estimate on both sides of the fraction. Alignment work has to move the estimated
> population toward the measured one, because the measured one has no free parameters left to
> adjust.

### 3. Alignment is a named, standardized obligation — not an ad-hoc correction

> "Because many ADS and human data sources are reported separately, some amount of data alignment is
> required in order to make legitimate comparisons. […] Common comparability issues […] include: 1.
> Differing reporting practices between ADS and benchmark data sources for both crashes and
> exposure, 2. Varying exposure to influential factors, and 3. Mismatched outcome and exposure
> units."
>
> Method table: "**Subselection** — Subsetting data using inclusion criteria — Commonly relied upon
> in observational research to isolate control and treatment data that were collected under more
> comparable conditions (Portney and Watkins, 2009)"
>
> — *RAVE Checklist: Recommendations for Overcoming Challenges in Retrospective Safety Studies of
> Automated Driving Systems*, Ensure data alignment in ADS and benchmark data, p.6

> "At its core, a safety impact assessment needs to compare a crash population, normalized by some
> exposure (usually driving distance), between two populations being compared. In order to enhance
> comparability of crash rates between two populations, **both the numerators (crash populations)
> and denominators (exposure) should be aligned as closely as possible.** As part of this alignment,
> the comparison should strive to account for influential features in the data that may bias the
> results and potentially lead to an incorrect conclusion."
>
> — *Dynamic Benchmarks: Spatial and Temporal Alignment for ADS Performance Evaluation* (arXiv
> 2410.08903), Introduction, p.2

### Which direction the adjustments push

The adjustments are not free parameters — their sign and size are reported, and they mostly make the
benchmark *harder* to beat:

> "The dynamic benchmark spatial adjustment generally resulted in higher adjusted benchmarks,
> ranging from 10% to 47% higher in San Francisco county, 12% to 20% higher in Maricopa county, and
> 7% lower to 34% higher in Los Angeles county, across severity levels. The time-of-day variations
> were evaluated for San Francisco county only (due to limited human data availability), and the
> differences were found to result in 2% lower to 16% higher adjusted crash rates, which represents
> a more modest effect compared to the spatial adjustment."
>
> — 2410.08903, Discussion, p.12

> "Human data is known to have underreporting, even for injury crashes. The driving environment
> within a geography can also affect crash rates, and the Waymo RO service travels in higher-density
> (and higher crash rate) areas more frequently than the overall human driving population. **The
> purpose of these sensitivity analyses is to bound the size of the effect of these benchmark
> adjustments and determine if the overall conclusions of the study would be changed if these
> adjustments were not made.**"
>
> — *…at 56.7 Million Miles*, Underreporting and Dynamic Benchmark Sensitivity Study, p.33

### Where they refuse an adjustment, and why

> "This current study did not compare the ADS to this Blanco-adjusted benchmark because **Blanco et
> al. (2016) only attempted to estimate unreported crashes (those that met the reporting threshold
> but were not reported) where the Blincoe et al. (2023) underreporting amount accounted for both
> unreported crashes and crashes that did not meet the reporting** [threshold]"
>
> — 2312.12675, Matching of Benchmark and ADS Data, p.6

> "Although the underreporting and reporting threshold issues are both being addressed, **the
> Blincoe et al. (2015, 2023) and Blanco et al. (2016) adjustments are inconsistent with each other
> and not necessarily representative of current case years and geographic areas being
> investigated.** Another limitation is that the data used to estimate underreporting in these
> previous studies does not have a clear lower reporting threshold."
>
> — 2312.13228, Selecting Benchmarks for ADS Evaluation, p.12

### What they concede

> "Although the study takes steps to align the benchmark and ADS data using dimensions available in
> both human and ADS data sources (such as geographic location, road type, vehicle type, and spatial
> driving density), **there is an endless list of possible factors to potentially account for and of
> adjustment methodologies to refine.**"
>
> — *…at 56.7 Million Miles*, Limitations, p.17

> "There are areas where conformance is not fully satisfactory, which we attribute primarily to
> **limited human benchmarking data quality that restricts the ability to fully account for
> potential confounders.**"
>
> — *…at 56.7 Million Miles*, Study Conformance to the RAVE Checklist, p.47

### And the limit they place on the whole family

> "**Retrospective studies cannot be used to make safety determinations prior to deployment.
> Therefore, an ADS with a crash involvement rate lower than the general driving population does
> not, by itself, allow for a determination that the ADS has an absence of unreasonable risk.**
> Assessment methodologies that use other benchmarks are important in addition to retrospective
> crash involvement (Webb et al., 2020)."
>
> — 2312.12675, Introduction, p.1

> **My reading, not the papers' words.** That quotation is what ties the four families into one
> system rather than four competing answers. Retrospective benchmarking is sized by power analysis
> but is explicitly barred from licensing a deployment; the prospective methods that *can* license
> one are sized by budget and by discriminative power instead, because their events are too rare for
> a mileage-based *n* to ever arrive in time.

---

## A different denominator: the insurance-claims variant

**Comparative safety performance of autonomous- and human drivers: A real-world case study of the
Waymo Driver** — Di Lillo et al. (Swiss Re), 2024.

One study swaps police reports for insurance claims, which changes the sampling frame entirely: the
benchmark becomes a population of policy-years rather than a set of reported crashes.

> "The human driver baselines are based on Swiss Re's property damage liability (PD) and bodily
> injury liability (BI) claims data for claims that occurred between 2016 and 2021. **For this study
> 600,000 claims and over 125 billion miles of exposure were used (i.e., post-zip code and
> responsibility calibration filtering), summed across over 25 million vehicle insurance policy
> years.** […] The baseline was calibrated using both mileage (driving exposure) and zip codes
> (geographic region)."
>
> — §4 Methods, p.3

Its own limitation is stated in the same section — the geographic key is the wrong event:

> "Although the use of the zip code of the registered vehicle address, as opposed to the collision,
> is a limitation of this study, we expect this to have a small-to-negligible impact on the
> frequency estimate."
>
> — §4 Methods, p.3

---

## Papers cited

| id | title |
|---|---|
| 2604.03827 | Confidence Intervals for Rate Estimation with Importance Sampling in Autonomous Vehicle Evaluation — Chen, Zhou, Lee, Chamandy, Hohnhold (2026) |
| 2411.17826 | Rate-Informed Discovery via Bayesian Adaptive Multifidelity Sampling — Sinha, Nikdel, Paul, Whiteson (2024) |
| 2212.08148 | Collision Avoidance Testing of the Waymo Automated Driving System — Kusano, Beatty, Schnelle, Favaro, Crary, Victor (2022) |
| 2312.12675 | Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million Miles — Kusano, Scanlon, Chen, McMurry, Chen, Gode, Victor (2023) |
| 2312.13228 | Benchmarks for Retrospective Automated Driving System Crash Rate Analysis Using Police-Reported Crash Data — Scanlon, Kusano, Fraade-Blanar, McMurry, Chen, Victor (2023) |
| 2410.08903 | Dynamic Benchmarks: Spatial and Temporal Alignment for ADS Performance Evaluation — Chen, Scanlon, Kusano, McMurry, Victor (2024) |
| 2508.19425 | From Stoplights to On-Ramps: A Comprehensive Set of Crash Rate Benchmarks for Freeway and Surface Street ADS Evaluation — Scanlon, McMurry, Chen, Kusano, Victor (2025) |
| journal PDF | Comparison of Waymo Rider-Only Crash Rates by Crash Type to Human Benchmarks at 56.7 Million Miles (Traffic Injury Prevention, 2025) |
| journal PDF | Waymo simulated driving behavior in reconstructed fatal crashes within an autonomous vehicle operating domain — Scanlon et al. |
| journal PDF | Collision Avoidance Effectiveness of an Automated Driving System Using a Human Driver Behavior Reference Model in Reconstructed Fatal Collisions |
| journal PDF | RAVE Checklist: Recommendations for Overcoming Challenges in Retrospective Safety Studies of Automated Driving Systems — Scanlon et al. (2024) |
| journal PDF | Comparative safety performance of autonomous- and human drivers: A real-world case study of the Waymo Driver — Di Lillo et al., Swiss Re (2024) |

---

## Provenance and caveats

**Provenance.** Every quotation above was retrieved from the local `waymo_av_safety` corpus —
separate from the 12,390-paper causal-methods corpus that the registered `research-system-rag` MCP
server points at — via `scripts/ask_waymo_corpus.py`, which spawns `app.serve --data-dir waymo/data`
over stdio and applies the curated `author_org=Waymo` filter by default. Quotations reproduce the
stored block text; ellipses and bracketed completions are marked. Four sources are non-arXiv journal
PDFs ingested as local documents and are named by title rather than by their `local:` id.

**Caveats.** Mileage figures in the required-mileage table are the numbers stated in the papers'
prose, not values read off Table 3 or Figure 4 — the tables themselves were not retrieved. Two
quotations end at a stored chunk boundary and say so. Passages marked *My reading* are synthesis,
not source text.
