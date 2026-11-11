# Confidence Intervals, Standard Errors and Bootstraps in the Waymo Safety Papers

*Every uncertainty-quantification method used across the Waymo safety literature, with the exact
paper, the verbatim passage, and the stated rationale. Retrieved 2026-08-25 from the local
`waymo_av_safety` corpus.*

Companions: [`WAYMO-SAMPLING-METHODS-REPORT.md`](WAYMO-SAMPLING-METHODS-REPORT.md) ·
[`WAYMO-MISSING-DATA-METHODS-REPORT.md`](WAYMO-MISSING-DATA-METHODS-REPORT.md)

---

## Scope and method

Full-text literal search over the stored markdown of all **157 papers tagged Waymo-authored at the
curated tier** (`fixtures/waymo/waymo_authored_ids.txt` — an enumerated list from Waymo's own
publication index), then passage-level reading of every hit, cross-checked with semantic retrieval.

| Term | Papers (of 157) | Term | Papers |
|---|---|---|---|
| `confidence interval` | 23 | `Garwood` | 3 |
| `standard error` | 13 | `Nelson` | 4 |
| `bootstrap` | 16 | `Byar` | 2 |
| `Poisson bootstrap` | 2 | `Clopper-Pearson` | 1 |
| `multinomial bootstrap` | 1 | `beta prime` | 1 |
| `credibility` | 9 | `multiple comparison` | 3 |
| `jackknife` · `balanced repeated replication` · `Taylor series` · `credible interval` · `profile likelihood` · `Bonferroni` · `false discovery` · `overdispersion` · `negative binomial` | **0 each** | | |

**Headline.** There is no single house method. The corpus uses **eight distinct interval/SE
constructions**, and the choice is driven almost entirely by one variable: *how many events were
observed*. Small counts get exact Poisson methods; large counts get normal approximations; ratios of
two Poisson rates get Nelson (1970); and the one place a resampling method is the primary tool
(importance-sampled rate estimation) is also the one place a purpose-built new bootstrap had to be
invented.

---

## Master table

| Paper | Estimand | Method | Stated rationale |
|---|---|---|---|
| *Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million Miles* (2312.12675) | Rate (IPMM); rate ratio | Poisson exact via gamma quantiles; **Nelson (1970)** beta-prime for the ratio | Nelson "can be computed in the event of zero event counts"; kept over a parametric bootstrap because it is "more conservative" |
| *…by Crash Type…at 56.7 Million Miles* | Rate ratio | **Clopper–Pearson limits for the ratio of two Poisson means, per Nelson (1970, Appendix I)** | "the same method adopted by Kusano et al (2024)"; "Established statistical methodology was relied upon" |
| *Dynamic Benchmarks: Spatial and Temporal Alignment for ADS Performance Evaluation* (2410.08903) | Adjusted benchmark, multiplier | **Poisson bootstrap**, N=1000, 90% CI | *(mechanics only — no rationale given)* |
| *Confidence Intervals for Rate Estimation with Importance Sampling in AV Evaluation* (2604.03827) | Compound-Poisson rate under importance sampling | **Exponential bootstrap (EB)** + saddlepoint; benchmarks against Poisson bootstrap and Gamma methods | PB "can severely under-estimate the uncertainty when the observed true positives are rare"; Gamma methods violate monotonicity |
| *Baseline vulnerable road user injury risk in multiple U.S. dense urban driving environments* | Collision rate; injury-risk percentiles | **Byar's method**; plus **nonparametric resampling with replacement** (n=1,000) | Byar "represents an exact approximation to the Poisson distribution and retains high levels of accuracy for both small and large counts" |
| *High-resolution urban fatal crash rate benchmarks for ADS assessment* | Fatal crash rate per 100M miles | **Poisson–chi-squared exact limits** | crash counts assumed Poisson; notes a Poisson regression would be the better option if significance testing were the goal |
| *Comparative safety performance of autonomous- and human drivers* (Di Lillo et al., Swiss Re) and *Do Autonomous Vehicles Outperform Latest-Generation Human-Driven Vehicles?* | Claims frequency | **Normal approximation** for the human baseline, **Poisson Exact (Garwood 1936)** for Waymo; significance by **non-overlapping CIs** | Explicitly by sample size: "due to the large sample" vs "due to the smaller sample and exposure size" |
| *Safety Performance of Waymo RO at 1M miles* | Believability of a rate estimate | **Actuarial Credibility theory** (full-credibility standard n_f = 1082) | Classical framework from insurance rate-making; used to argue an ADS deserves the same "believability" standard as its benchmark |
| *An omni-directional model of injury risk in planar crashes* | Logistic regression coefficients | **Complex survey design variance** (NASS-CDS/CISS), R `survey` package | "used the method for combining surveys recommended by NHTSA (2019, p. 17)" |
| *Passenger and heavy vehicle collisions with pedestrians* | Logistic regression coefficients | **Pooling across 10 MICE imputations** | sensitivity analysis for missing data |
| *Collision Avoidance Testing of the Waymo ADS* (2212.08148) | Scenario-set adequacy | **Single-proportion z-test** on reference-model failure rates | ensures scenarios can discriminate pass from fail |
| *Benchmarks for Retrospective ADS Crash Rate Analysis* (2312.13228) | Required VMT | **Poisson–normal sample size formula** (α=0.05, 80% power) | see the sampling report |
| *Rate-Informed Discovery via Bayesian Adaptive Multifidelity Sampling* (2411.17826) | Failure-rate estimate | **Gaussian-process posterior variance**, minimized by design | "minimizing Var(p̂) provides a confident estimate of the probability" |
| *RAVE Checklist* | — (doctrine) | Recommendation 5 | "Quantify uncertainty of the estimates with statistical testing or other methods" |

---

## 1. Exact Poisson intervals for a single rate

Three different exact constructions appear, all solving the same problem — counts are small, so the
normal approximation is unsafe.

### 1a. Gamma-quantile form

**Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million Miles** (arXiv
2312.12675) — Kusano, Scanlon, Chen, McMurry, Chen, Gode & Victor.

> "Two types of confidence intervals are presented in this paper. First, **confidence intervals are
> estimated for incidents per million miles (IPMM) using a Poisson exact model.** The confidence
> interval, IPMM, can be computed as
>
> IPMM ∈ [ qgamma(α/2, n, 1) / m , qgamma(1 − α/2, n + 1, 1) / m ]
>
> where *qgamma* is the quantile function of the gamma distribution (i.e., inverse cumulative
> distribution function), α is the significance level (e.g., 0.05), *n* is the event count, and *m*
> is the number of miles driven."

### 1b. Byar's approximation

**Baseline vulnerable road user injury risk in multiple U.S. dense urban driving environments.**

> "Confidence intervals (95%) for these rates were developed using **Byar's method, which represents
> an exact approximation to the Poisson distribution and retains high levels of accuracy for both
> small and large counts (Breslow et al. 1980).**"

**Why.** The rationale is stated in the same sentence — Byar's closed form is accurate across the
whole count range, so a single formula serves both the sparse city-level cells and the pooled
estimates. It avoids needing the quantile function at all: the paper's Eq. (1)/(2) use only the
observed count *a* and the 1.96 z-multiplier.

> "where *a* is the number of observed events and **1.96 is reflective of the Z-score corresponding
> to a 95% confidence interval.** Subsequently dividing by the relevant mileage results in
> confidence intervals for the rate data."

### 1c. Poisson–chi-squared relation

**High-resolution urban fatal crash rate benchmarks for automated driving system assessment.**

> "Confidence intervals for the crash rates were calculated **assuming that crash counts follow a
> Poisson distribution.** Specifically, 95% confidence limits were derived using the **relationship
> between the Poisson distribution and the chi-squared distribution**, where the lower and upper
> bounds are determined by the 0.025 and 0.975 quantiles of the chi-squared distribution,
> respectively."

The same paper names the boundary of what this approach can do — a rare instance of a Waymo paper
recommending against its own method for a different question:

> "**If the research question shifts toward determining whether these differences are statistically
> significant, a unified, parametric model-based approach (such as a Poisson regression) may become
> the better option.** By treating these dimensions as covariates, a model can formally test for
> significance while adjusting for multiple factors simultaneously."

### 1d. Garwood (1936) fiducial limits

Used for the ADS arm in both Swiss Re collaborations (§3 below). The bibliography entry is *"Fiducial
limits for the Poisson distribution. Biometrika, 28(3/4), 437-442"* — the original exact Poisson
interval.

---

## 2. Rate-ratio intervals: Nelson (1970), and why not a bootstrap

This is the workhorse of the benchmarking papers, because the headline result is always a *ratio* of
two Poisson rates — ADS crashes per mile over human crashes per mile.

**7.1 Million Miles** (2312.12675) gives the form:

> "Second, **confidence intervals for the ratio** between the ADS crash rate of *Y* events over *t*
> miles and the benchmark crash rate of *X* events over *s* miles **were calculated using the method
> described by Nelson (1970)** as
>
> ρ ∈ [ s/t · qbetaprime(α/2, Y, X+1) , s/t · qbetaprime(1 − α/2, Y+1, X) ]
>
> where *qbetaprime* is the quantile function of the beta prime distribution. **This formulation of
> the confidence intervals can be computed in the event of zero event counts in the ADS data (i.e.,
> Y = 0)**, but as a result may be more conservative (i.e., wider confidence intervals) in the case
> of non-zero ADS events counts compared to the Poisson exact model."

**Why this method — reason one:** it survives Y = 0. That is not a corner case here; an ADS fleet
with genuinely rare crashes will produce zero-count cells, and most ratio intervals are undefined
there.

**Why this method — reason two:** they tested the alternative and chose the more conservative one.

> "Standard errors for counts that use the survey design variables are larger than standard errors
> calculated using conventional methods using just the weighted counts (Zhang and Diaz, 2020). To
> investigate the effect of the CRSS variance estimates on the confidence intervals for the rate
> ratio, **the authors constructed confidence intervals using a parametric bootstrap** using the
> standard error for the benchmark crash counts estimated using the survey design variables. **The
> rate ratio confidence intervals computed using the parametric bootstrap method were narrower than
> those computed using the method described in Equation 2.** This result suggests that the method
> from Nelson (1970) is more sensitive to the other parameters in the rate ratio calculation (i.e.,
> the count of ADS events) than a parametric bootstrap method. **The Nelson (1970) method is more
> conservative** (i.e., produces larger confidence intervals) relative to the parametric bootstrap
> method. **For this reason, the confidence intervals described in Equation 2 were used** to
> construct rate ratio confidence intervals for the national benchmark comparisons.

That is the clearest "why not bootstrap" statement in the corpus: the bootstrap was run, it produced
tighter intervals, and they rejected it *because* it produced tighter intervals — deliberately
choosing the method that makes their own favourable result harder to declare significant.

**The 56.7 Million Miles paper** carries this forward and names the underlying construction:

> "A statistical comparison between the ADS and benchmark crash rates was done using
> **Clopper-Pearson limits to estimate 95% confidence intervals for the ratio of two Poisson mean
> occurrence rates, as described by Nelson (1970, Appendix I), which is the same method adopted by
> Kusano et al (2024).**"
> — Statistical Testing

And its RAVE self-assessment restates the justification:

> "Rate ratio confidence intervals based on a Poisson model (Nelson 1970) were used to evaluate
> statistically significant differences between the benchmark and ADS crash rates. **Analysis in past
> studies has shown that the Nelson 1970 method produces wider (i.e., more conservative) confidence
> intervals compared to parametric bootstrapping (Kusano et al 2024)**" — conformance level:
> *Satisfactory*, justification: *"Established statistical methodology was relied upon."*

**Why this method — reason three: precedent.** The RAVE justification above is not a statistical
argument at all, it is an appeal to established practice, and the 56.7M paper's reference list for
its methods names "Chen et al 2024, Kusano et al 2024, Scanlon et al 2024, **Nelson 1970**". The
choice is now self-reinforcing across the Waymo benchmarking series: each paper cites the previous
one's adoption of it. 2312.12675 also notes "**Appendix A.3 provides example code and test cases**",
which is the only place in the corpus where an interval construction ships with runnable code.

### 2.1 The "% reduction" headline is the same interval, relabelled

Every widely-quoted Waymo figure of the form *"85% reduction in serious injury crashes (39% to 99%)"*
is the Nelson ratio interval under a change of variable, not a separate calculation:

> "Another interpretation of the ratio between ADS rate (μ = Y/t) and benchmark rate (λ = X/s) is a
> **relative difference in the rate**, δ,
>
> δ = (μ − λ)/λ = μ/λ − 1
>
> **Because this percent change in the rate is a direct product of the ratio, the same confidence
> intervals described in Equation 2 can be used to generate confidence intervals for the relative
> difference.**"
> — 2312.12675, Confidence Intervals

This is legitimate and worth stating explicitly: δ is a strictly monotone transform of ρ, so the
interval endpoints map through directly. No delta method, no variance propagation, no second
approximation is introduced. The percent-reduction interval inherits exactly the coverage properties
of the ratio interval — including its conservatism at non-zero counts.

### 2.2 There is no standard error in the rate-ratio calculation

Worth stating plainly, because it is easy to assume otherwise: **the headline safety comparison
never computes a standard error.** Nelson (1970) is an *exact* method — the endpoints come from
quantile functions of the beta prime distribution (equivalently, Clopper–Pearson limits on the
implied binomial). There is no variance estimate, no normal approximation, and no asymptotic
argument. Asking "what standard error did they report for the rate ratio?" has the answer: none, by
construction.

Standard errors do appear in the corpus, but never on this path:

| Where SEs appear | Method | Role |
|---|---|---|
| CRSS / NASS-CDS / CISS benchmark counts | complex survey-design variance (R `survey`, NHTSA 2019 combining guidance) — see §5 | correcting the human benchmark for its sampling design |
| Swiss Re claims comparisons | normal-approximation SE for the human baseline, accounting for the SF/Phoenix mileage split — see §3 | the large-sample half of a non-overlap test |
| Injury-risk logistic regressions | model-based coefficient SEs, weighted and unweighted | reported per coefficient with p-values |

The survey-design SE is the only one that touches the rate ratio, and only as a **diagnostic**: it
was the input to the parametric bootstrap that was run and then rejected (quoted above). So the
one place a properly design-corrected variance estimate enters the benchmarking pipeline is in a
sensitivity check whose result was *not* adopted.

### 2.3 The conservatism is not uniform across the pipeline

Two choices in the same paper pull in opposite directions, and this should be read together with
§10:

- **Conservative:** the wider of two available rate-ratio intervals was chosen deliberately, after
  measuring that the alternative was narrower.
- **Anti-conservative:** the 56.7M paper performs comparisons across "different outcome levels (3),
  crash modes (11), and locations (4)" — 132 cells — and states that "**no multiple comparison
  corrections have been made**."

Widening each interval raises the bar for any *individual* cell; running 132 uncorrected comparisons
lowers the bar for *at least one* cell reaching significance. The net effect on the family-wise error
rate of the reported table is undetermined, and neither paper attempts to characterise it. Choosing
the conservative interval is real methodological discipline; it does not substitute for a
family-wise correction, and it should not be read as though it does.

---

## 3. Normal approximation + non-overlapping intervals (the Swiss Re papers)

**Comparative safety performance of autonomous- and human drivers: A real-world case study of the
Waymo Driver** — Di Lillo et al.

> "For significance testing, we conclude that there is a statistically significant difference between
> claims frequencies **if the 95% confidence intervals of Waymo's operations and their corresponding
> human baselines do not overlap.** That is, that there is a difference even when accounting for
> statistical uncertainty due to the small mileage volume. **For the human baseline, due to the large
> sample size, we use a normal approximation confidence interval** and take the mileage distribution
> between San Francisco and Phoenix into account when computing the standard errors. **For Waymo's
> operations, due to the smaller sample and exposure sizes, confidence intervals are calculated using
> the Poisson Exact Method [17].**"
> — §4 Methods

The follow-up, **Do Autonomous Vehicles Outperform Latest-Generation Human-Driven Vehicles? A
Comparison…**, uses identical wording:

> "For the HDV benchmarks, **due to the large sample, a normal approximation confidence interval was
> used**, which considered the mileage distribution between San Francisco and Phoenix when computing
> the standard error. **For Waymo's operations, due to the smaller sample and exposure size,
> confidence intervals were calculated using the Poisson Exact Method (Garwood, 1936).**"

**Why.** The rationale is purely asymptotic: normal approximation where *n* supports it, exact
Poisson where it does not. Two things worth flagging:

1. **Asymmetric methods on the two arms of one comparison** is a deliberate choice, and it is the
   right one when the arms differ by four orders of magnitude in exposure (125 billion benchmark
   miles vs a few million ADS miles).
2. **The non-overlap rule is conservative, not exact.** Declaring significance only when two
   independent 95% intervals fail to overlap is a stricter test than a direct test on the
   difference — it under-rejects. The papers do not discuss this; they present it as the definition
   of their significance criterion. The effect runs in the same direction as the Nelson choice
   above: harder to claim a Waymo win.

The same papers note the intervals tightening with exposure:

> "…we note that **95% confidence intervals have narrowed substantially during this time.** As Waymo
> operations continue to scale, we expect that statistical confidence in this result will also
> increase."

---

## 4. The four bootstraps

### 4a. Poisson bootstrap — used, unjustified

**Dynamic Benchmarks: Spatial and Temporal Alignment for ADS Performance Evaluation** (arXiv
2410.08903) — Chen, Scanlon, Kusano, McMurry & Victor.

> "All confidence intervals presented in this paper are estimated using **Poisson bootstrap method
> (28)** with 90% confidence level. For each of the bootstrap iterations (N=1000), **a random number
> from a Poisson distribution with mean 1 (λ = 1) is generated for each crash event to represent the
> frequency of that particular event within the resampled data set.** The distribution of a quantity
> of interest (unadjusted benchmark, dynamic benchmark, or dynamic benchmark multiplier) across all
> bootstrap samples serves as an approximation of the sampling distribution. **The 5th and 95th
> quantiles of the distribution are then used to estimate the lower bound and upper bound.**"
> — Confidence Intervals

**Why this method:** not stated. The section gives mechanics only. Two observations:

- The cited "(28)" is the *SF County Transportation Authority TNCs and Congestion Report*. The
  Poisson-bootstrap source is almost certainly reference **(30)**, *Chamandy et al., "Estimating
  Uncertainty for Massive Data Streams" (Google, 2012)*, which appears in the bibliography and is
  never cited anywhere in the body text. This reads as a citation-numbering slip.
- The standard argument for `Poisson(1)` weights over multinomial resampling — no need to know *n*
  in advance, trivially parallel over a data stream — lives in that Chamandy paper, which is **not
  ingested in this corpus**. It is not stated in any Waymo paper here.

The method does fit the estimand: the dynamic benchmark is a weighted average over spatial slices,
so per-event Poisson weights propagate uncertainty through the re-weighting without disturbing the
slice structure.

### 4b. Nonparametric resampling with replacement

**Baseline vulnerable road user injury risk in multiple U.S. dense urban driving environments.**

> "The injury risk distributions at each severity level were quantified (median, 75th and 95th
> percentile injury risk values) to allow for relative event severity comparisons among extrinsic
> collision factors. **The data were resampled with replacement (n = 1,000) to generate 95%
> confidence intervals for these point estimates. The lower and upper bounds were obtained by sorting
> the samples and taking the 25th and 975th values, respectively. Resampling was done within each
> grouping to ensure fidelity of the bootstrap samples to the original data set.**"

**Why.** The estimands here are *quantiles of an injury-risk distribution* (median, 75th, 95th
percentile) — quantities with no closed-form standard error. That is the classic case for a
percentile bootstrap. The stratification clause ("within each grouping") preserves the grouping
structure the comparison is about. Note this paper uses **two different methods in one analysis**:
Byar's for the rates, percentile bootstrap for the risk quantiles.

### 4c. Parametric bootstrap — run and rejected

See §2 above: the 7.1M-mile paper's parametric bootstrap on CRSS survey-design standard errors,
discarded for producing narrower intervals than Nelson (1970).

### 4d. Exponential bootstrap — invented because the others failed

**Confidence Intervals for Rate Estimation with Importance Sampling in Autonomous Vehicle
Evaluation** (arXiv 2604.03827) — Chen, Zhou, Lee, Chamandy & Hohnhold, Waymo LLC.

The setting is the Horvitz–Thompson rate estimator under multi-stage importance sampling, which the
paper shows follows a **compound Poisson** distribution. The question is what interval to put around
it when true positives are rare.

**Why the existing bootstrap was the natural candidate:**

> "Traditional procedures for CI construction include bootstrap (Efron and LePage (1992)), the delta
> method […] and empirical likelihood (Owen (2001)), **which all rely on large sample
> approximation.** […] **The most interesting approach for our application, due to its simplicity and
> flexibility, is the Poisson bootstrap (PB) for CP proposed by Bohm and Zech (2014); see Chamandy et
> al. (2012) and references therein which derived the same Poisson bootstrap but as a variation of
> the standard multinomial bootstrap.** We also note that **PB may be viewed as a parametric
> bootstrap when the sampling probabilities are discrete**… **Unlike these methods, which only make
> use of {Wᵢ : Wᵢ > 0}, our method takes into account the sampling probabilities behind all
> observations.**"
> — §4 Related work

That last clause is the structural objection: PB resamples only the events that were *discovered*,
throwing away the sampling probabilities of every segment that was sampled and produced nothing.

**Why it was abandoned:**

> "It is worth pointing out that **the Poisson bootstrap CI does satisfy the monotonicity property.
> However, it can severely under-estimate the uncertainty when the observed true positives are
> rare**, which will be demonstrated later in numerical studies in Section 6."
> — Remark 5

> "The coverage of EB is more reliable than PB overall while **the coverage error for PB can be very
> large and even close to 100% when true positive data is sparse**, and both converge to the nominal
> level when the sampling rate goes up."
> — §6.1

> "**PB systematically undercovers** under both (a) and (b)."
> — §6.3

**Why not the classical alternative either (Gamma methods):** they fail an interpretability criterion
the paper introduces and argues for.

> "The monotonicity property is intuitive and also important for real applications **due to better
> interpretability—when two different rates are summed up, the overall rate is known to be higher
> than each individual rate, thus the CI bounds for the overall rate should be correspondingly
> higher. In fact, none of the existing Gamma methods have this property** […]. Such violation often
> happens when the importance sampling quality is uneven, for example, very good at predicting one
> type of events (i.e. discovered lots of events with small weights), but very hard at predicting
> another type of events (discovered very few events but with high weights)."
> — §5.1

They then show it happening on real Waymo data:

> "In this case study, there were two disjoint groups of events which we denote simply by Category A
> and Category B. **This partitioning of events led to a violation of the monotonicity property by
> extensions of the traditional Gamma CIs** […]. In this case, **38 true positive events were
> identified from Category A, all having relatively small sampling weights; on the other hand, a
> single event with a high weight was identified from Category B.** […] at the 90% confidence level,
> GO2m violates this property (its lower bound for A exceeds that for A∪B), while at the 95%
> confidence level, both GO2m and GP2m violate this property. **As expected, the monotonicity
> property is always preserved by EB2m.**"
> — §7 Real-world data analysis

**The solution:**

> "There is no closed-form expression for quantiles of the weighted sum of independent exponential
> random numbers, but this can be implemented by the Monte Carlo procedure described in Table 2,
> **which we call "exponential bootstrap" (EB), to mimic Poisson bootstrap.** We also find that a
> fast algorithm for EB based on the saddlepoint approximation…"
> — §5.2

The two procedures differ in exactly one line: PB draws `eᵢ ~ Poisson(1)`, EB draws exponentials and
adds a "next weight" term chosen so the interval stays honest when almost nothing was observed.

> "**in sparse cases, EB2m is a clear winner over PB: it maintains coverage at the cost** [of width]"
> — §6.2

---

## 5. Survey-design variance and pooled variance

Three papers inherit their variance structure from the sampling design of a federal or national
survey rather than computing it themselves.

**An omni-directional model of injury risk in planar crashes with application for autonomous
vehicles** (McMurry et al.):

> "**Analyses accounted for NASS-CDS/CISS survey design and used the method for combining surveys
> recommended by NHTSA (2019, p. 17).**"
> — Methods

> "All statistical analyses were conducted in R (v4.0.3…) using the **survey package (v4.0, Lumley
> 2004)**."

**Why.** NASS-CDS and CISS are complex probability samples with case weights; ignoring the design
understates standard errors. The 7.1M-mile paper states the size of that effect explicitly:

> "**Standard errors for counts that use the survey design variables are larger than standard errors
> calculated using conventional methods using just the weighted counts (Zhang and Diaz, 2020).**"

**Passenger and heavy vehicle collisions with pedestrians** pools across imputations instead:

> "Logistic regression models were created for the ten imputed datasets, and **the ten estimates for
> each independent variable were pooled to produce an overall estimate.**"

(Rubin's rules in substance; not named as such — see the missing-data report.)

**Ride-hailing in the Safe System** caps influential survey weights:

> "**Case weights supplied as part of CISS were used to scale individual events appropriately for
> analysis, with all cases with a weight exceeding 5,000 capped at 5,000, in accordance with previous
> work.**"

---

## 6. Hypothesis tests rather than intervals

**Collision Avoidance Testing of the Waymo Automated Driving System** (arXiv 2212.08148) uses a test
as a *stopping rule* for how much testing to do:

> "**A single-proportion z-test is then applied to the rate of failure of the different reference
> behavior model levels to determine if the rates are statistically different.** […] **Additional
> scenarios are collected for safety groups that do not have a statistically significant difference
> in passing rate collision metric.** […] Note that this statistical diagnostic is performed only on
> the NIEON model results and is independent of the ADS performance."

**Benchmarks for Retrospective ADS Crash Rate Analysis** (2312.13228) uses the Poisson–normal sample
size formula for the same purpose in the retrospective setting (α = 0.05, 80% power) — covered in
the sampling report.

---

## 7. Actuarial credibility as an uncertainty framework

**Safety Performance of Waymo RO at 1M miles** imports a framework from insurance rate-making rather
than from statistics proper.

> "This is known in common actuarial practice in the insurance sector as the concept of
> **Credibility** (see Appendix 1), **which represents the degree of believability one can place on
> observed empirical data when trying to predict the future** (Mahler & Dean, 2001)."

> "Under the Classical Credibility Framework […] **a commonly-used full credibility standard for
> occurrence count is n_f = 1082, based on p = 90%, k = 5% and assuming the occurrence rate follows a
> Poisson distribution and the normal approximation to the Poisson** (Mahler & Dean, 2001). If we
> want to translate 1082 crashes into corresponding mileage, assuming a crash frequency *c*… we would
> need m = 1082/c miles to observe that many crashes."
> — Appendix 1: Credibility

**Why they used it, and the paradox they use it to name:**

> "**The more safety benefits a technology brings, the lower the crash occurrence rate (smaller c)
> becomes, thus more miles (m = 1082/c) are needed to reach the full credibility standard.** This
> problem is further magnified when it comes to rare events like high severity crashes… **However,
> benchmark-comparative methods to an agreed upon threshold, such as human driving performance,
> provide a framework that can lead to statistically significant conclusions on safety performance by
> drawing insights from differences, without the need to have a 100% credible crash occurrence
> estimate.**"

Elsewhere the paper names this the **"credibility irony"**:

> "**excellent safety performance can create a sort of 'credibility irony,' where improved performance
> leads to rarer observations of safety outcomes and larger requirements for mileage to gain
> sufficient statistical confidence.** As explained in Appendix 1, through comparison with a robust
> human baseline, detection of safer performance can be done with fewer collision observations, and
> therefore lower mileage."

And the fairness argument it is deployed to make:

> "**it is also reasonable to state that ADS empirical crash occurrence rate deserves at least the
> same level of 'believability' as the selected benchmark** […] if we have concluded through
> credibility theory that a human driving set of exposures is fully credible at 100M miles, it should
> stand to reason that an ADS should achieve the same 'believability' of its outcomes for the same
> set of miles driven, even if there are few to no crashes."

---

## 8. Model-based variance in the ML papers

**Rate-Informed Discovery via Bayesian Adaptive Multifidelity Sampling** (arXiv 2411.17826) does not
construct an interval at all — it makes the estimator's variance the *objective*:

> "Our goal of rate-informed discovery implies that **choosing evaluation points to minimize the
> variance of the estimator, Var(p̂γ(θ)), is beneficial.** In particular, minimizing Var(p̂γ(θ))
> provides a confident estimate of the probability."

> "the calculation of Var(p̂γ(θ)) **is dominated by regions in X that have both high likelihood under
> P and high uncertainty under θn.** Thus, minimizing Var(p̂γ(θ)) prioritizes sampling points x that
> are clustered near other points (high likelihood) and are far away from previously sampled points
> (high uncertainty)—**precisely our goal for rate-informed discovery.**"

**Why.** The variance functional does double duty: it is the precision target *and* the acquisition
function for finding new failure modes. Reported outcome: *"rate estimates with variances 15 and 6
times narrower than MC and IS baselines respectively."*

---

## 9. The doctrine

**RAVE Checklist**, Recommendation 5: *"Quantify uncertainty of the estimates with statistical testing
or other methods. Statistical conclusions are a fundamental result presented in safety impact studies
and researchers should catalog and quantify sources of uncertainty."*

> "It is best practice to leverage statistical methods to quantify uncertainty in retrospective
> safety impact analyses. **There are a wide variety of methods that can be used in this context,
> ranging from normal/Poisson confidence intervals to various regression models that account for
> covariates and other issues.** Researchers should use appropriate statistical methods to report
> standard errors and/or confidence intervals for any descriptive statistics or crash rate
> comparisons presented. The use of statistical testing accompanied with thorough documentation about
> the appropriateness of using the particular test or distribution choice given the data… is
> suggested. **For uncertainty in elements for which distributions are not known, sensitivity analysis
> and bootstrapping approaches can be useful.** It is also important to describe other sources of
> uncertainty that were not accounted for in the study and their potential effect on the results."

The checklist prescribes no specific estimator — it prescribes *disclosure*, including of the
uncertainty you did not quantify.

---

## 10. Uncertainty they say they did not capture

The corpus is unusually explicit about what its intervals leave out.

**Benchmarks for Retrospective ADS Crash Rate Analysis** (2312.13228):

> "**Two contributors of statistical randomness were considered** in this analysis: (1) the inherent
> randomness around the mean in the number of observed ADS events and (2) uncertainty in the
> estimated human-driven non-fatal crash totals due to the sampling structure in CRSS. **There are
> other forms of uncertainty that are unaccounted for** […]. First, there is uncertainty in the
> transformed estimates of Blanco-adjusted any property damage or injury and Blincoe-adjusted
> any-injury-reported due to the adjustments that were performed. **For this current study, we
> considered these adjustments as point estimates only.** Second, **the national VMT estimates are,
> themselves, the product of sampling and estimation by the various local, state, and federal
> agencies. Accounting for these additional uncertainties would lead to a higher estimated VMT
> required for detecting statistical significance.**"

**From Stoplights to On-Ramps** (2508.19425):

> "**The variance and bias due to these sampling methods have not been studied in this current
> study.** Future research should (a) look to better examine these biases and (b) look for
> complementary data sources…"

**Comparison of Waymo RO Crash Rates… at 56.7 Million Miles** — the multiple-comparisons admission:

> "If multiple comparisons are made across many different dimensions, the probability of detecting
> false positive significant results increases. **This study performs a number of comparisons across
> different outcome levels (3), crash modes (11), and locations (4).** […] **due to multiple
> comparisons, care should be taken when considering the statistical significance of individual
> comparisons as no multiple comparison corrections have been made.**"

That is 132 cells with no family-wise correction, disclosed rather than corrected. No paper in the
corpus applies a Bonferroni, Holm, or false-discovery-rate adjustment (0 hits for all three). The
RAVE checklist's bibliography contains Gelman & Loken's *"The garden of forking paths"* — but, like
the Chamandy bootstrap reference in §4a, it appears only in the reference list, never cited in the
body.

The same paper also shows how sensitive a sparse-cell conclusion is to an upstream modelling choice:

> "**The dynamic benchmark adjustment for the Suspected Serious Injury+ outcome did affect the
> statistical significance of the comparison.** Without the dynamic benchmark adjustment, the
> reductions in Suspected Serious Injury+ crashes was not statistically significant in Phoenix or San
> Francisco but was statistically significant in all locations combined, whereas it **was**
> statistically significant in Phoenix, San Francisco, and in all locations combined with the dynamic
> adjustment."

And it flags its own thinnest result:

> "The result of a 85% reduction in Suspected Serious Injury+ crashes (39% to 99% reduction 95%
> confidence interval) is an indication of an effect, but **is subject to a low number of
> observations (2 ADS crash) with large confidence intervals.**"

---

## 11. What is absent

Zero hits across all 157 papers, stated as an observation about this corpus rather than about
Waymo's internal practice:

- **jackknife**, **balanced repeated replication**, **Taylor series linearization** named as such —
  the survey variance is delegated to R's `survey` package and to NHTSA's combining guidance rather
  than described.
- **credible intervals / posterior intervals** for the benchmarking work. The only Bayesian
  machinery is the GP posterior in BAMS, and it is used as a design objective, not to report an
  interval.
- **Profile-likelihood** intervals, **negative binomial** / **overdispersion** modelling. Every count
  model in the corpus is Poisson; none tests the equidispersion assumption.
- **Multiple-comparison corrections** of any kind.

---

## Provenance and caveats

**Provenance.** Term counts come from a case-insensitive literal search over the stored markdown of
all 157 papers tagged `author_org=Waymo` at the curated tier in the local `waymo_av_safety` corpus
(`waymo/data/blobs/*.md`, paths resolved from `papers.markdown_path`), then read in place.
Cross-checked with `scripts/ask_waymo_corpus.py`, which surfaced no additional papers. Quotations
reproduce the stored text; ellipses and bracketed completions are marked; **bold** inside quotations
is mine. Formulae are transcribed from the papers' rendered LaTeX into plain notation — the symbols
and structure are theirs, the typography is mine.

**Caveats.** The sweep covers the 157 curated Waymo-authored papers ingested here, which is not
guaranteed to be Waymo's complete publication record; a paper not ingested cannot be found. Term
counts are per-paper and substring-matched, so `Wilson` (17) and `Fisher` (16) are excluded from the
table above as overwhelmingly author-name matches rather than the Wilson score interval or Fisher's
exact test — I did not find either method in use. Several sources are journal PDFs ingested as local
documents with imperfect heading extraction, so some citations name a section by its visible heading
rather than a numbered path. Interpretive passages — the note that non-overlap testing is
conservative; the observation about the direction of the Nelson choice; §2.1's point that the
relative-difference interval introduces no second approximation; §2.2's observation that the
rejected bootstrap was the only design-corrected variance to enter the benchmarking pipeline; and
§2.3's conservatism ledger — are my analysis, not claims the papers make.
