# Extreme Value Theory in Road Safety: Why GEV, POT and Block Maxima, and How They Are Applied

*Why traffic-safety researchers model conflicts with extreme value theory instead of counting crashes,
and the exact machinery — block maxima vs. peaks-over-threshold, threshold selection, dependence
handling, and the extrapolation from a fitted tail to an expected crash count over an exposure.
Every claim is anchored to a verbatim passage from a paper in the local `waymo_av_safety` corpus.
Retrieved 2026-08-30.*

Companions: [`WAYMO-UNCERTAINTY-METHODS-REPORT.md`](WAYMO-UNCERTAINTY-METHODS-REPORT.md) ·
[`WAYMO-SAMPLING-METHODS-REPORT.md`](WAYMO-SAMPLING-METHODS-REPORT.md)

---

## Scope and method

Exhaustive regex scan (`scan_corpus`, recall 1.0 per pattern) over all 1,738 papers in the local
`waymo_av_safety` corpus for `extreme value theor|GEV|peaks-over-threshold|POT|block maxima|
generalized Pareto|Gumbel|return period`, followed by section-level reading of the papers that
apply the method rather than merely citing it.

| | count |
|---|---|
| Papers scanned | 1,738 |
| Papers matching EVT vocabulary | 65 |
| Papers that *apply* EVT to conflict-based crash estimation | ~20 |
| Papers read at section level for this report | 14 |

**A note on the quotations.** These are transcribed from the stored markdown, which was extracted
from PDFs. The extractor drops `fi`/`ff` ligatures, so the source text reads "trafic", "eficient",
"diferent". Those have been silently restored to "traffic", "efficient", "different"; nothing else
in any quotation has been altered. Mathematical notation is transcribed from rendered LaTeX into
plain symbols — the structure is the authors', the typography is mine. **Bold** inside quotations
is mine.

---

## Master summary

| Question | Answer in one line |
|---|---|
| **Why EVT at all?** | Crashes are too rare to observe; conflicts are frequent. EVT is the only principled way to extrapolate from the observed near-miss tail to the unobserved crash. |
| **Why not just regression on crash counts?** | That still requires crash data — the thing you don't have. |
| **What is modelled?** | A proximity indicator (negated TTC, PET, MTTC, BTN) so that "more extreme" = "closer to a crash", and a crash is the boundary value (TTC = 0). |
| **Block maxima → GEV** | Chop time (or distance) into blocks, keep each block's maximum. Objective, no threshold, but wasteful of data. |
| **POT → GPD** | Keep everything above a threshold `u`. Data-efficient, but threshold choice is subjective and consecutive exceedances are dependent. |
| **How do you get a crash count?** | Evaluate the fitted tail at the crash boundary to get a per-block crash probability, sum over blocks, scale by exposure ratio. |
| **How well does it work?** | Mixed. Validated against observed crashes by hit rate / MAE / RMSE; systematically over-estimates at severe thresholds and under-estimates at mild ones. |
| **What else is it used for?** | Bounding the AV scenario space — turning "reasonably foreseeable" (UNECE R157) into a number via an exceedance-frequency budget. See §12.1. |

---

## 1. Why EVT: the problem it solves

### 1.1 The reactive-analysis trap

Traditional road-safety evaluation waits for crashes to accumulate. Hewett et al. state the cost
plainly:

> "Standard road safety interventions are usually analysed **reactively**, once a threshold collision
> count has been over-topped during some pre-determined observation period. **Collisions are rare
> events and so prolonged observation periods are necessary, with much waiting for collisions to
> happen** to evaluate a treatment using a standard before/after (BA) analysis"
> — *Using extreme value theory to evaluate the leading pedestrian interval road safety intervention*
> (arXiv 2306.05925), §1

Anis et al. enumerate the full indictment:

> "Traditional safety analysis often relies on historical crash data to predict future extreme events
> or crashes within specific roadway entities (intersections, midblocks, corridors, etc.), widely
> known as the reactive approach… However, this approach has significant drawbacks, including **the
> rarity and randomness of crashes, the lengthy data collection process, limited sample sizes,
> unobserved heterogeneity, and inherent issues: under-reporting and subjective reporting.** These
> limitations hinder the accuracy of crash risk estimates, reliable safety inferences, and
> comprehensive safety assessments, thereby stalling advancements in highway safety research."
> — *Real-time risk estimation for active road safety: Leveraging Waymo AV sensor data with
> hierarchical Bayesian extreme value models* (arXiv 2407.16832), §1

### 1.2 Conflicts are the abundant substitute

> "**Traffic conflicts are generally defined as a situation in which a pedestrian and a vehicle
> approach each other in time and space to such an extent that they will collide if their movements
> remain unchanged. Traffic conflicts are more frequent than collisions, easy to observe and are of
> marginal social cost** (Tarko, 2018). As such, traffic conflict BA studies can be conducted over
> shorter time periods."
> — 2306.05925, §1

> "**Near-miss events are more frequent than crashes, providing an enriched dataset for robust
> analysis** and valuable insights into vehicle interactions and road network performance."
> — 2407.16832, §1

### 1.3 The specific job EVT does

Regression on conflicts still needs crashes to calibrate against. EVT does not:

> "Traditionally, a common approach has been to use regression analysis… **However, this regression
> analysis still relies on crash data, which are similarly limited in availability as in traditional
> crash-based safety assessment** (Farah & Azevedo, 2017). In contrast, **EVT-based methods infer
> unobserved crash probabilities from the tail behaviour of observed conflicts, without relying on
> crash records.**"
> — *Improving Crash Frequency Prediction from Simulated Traffic Conflicts Using Machine Learning
> Based Microsimulation* (arXiv 2606.12500), §2.4

The one-sentence justification that recurs across the literature:

> "**EVT has been widely adopted in recent years since its excellent ability to extrapolate from
> frequently occurring (near-misses) events to unobserved (crashes) events** (Coles et al., 2001).
> Songchitruksa and Tarko (2006) pioneered EVT-based crash estimation, and recent extensions by
> Zheng et al. (2019b; 2020) introduced Bayesian hierarchical structures that account for
> non-stationarity and unobserved heterogeneity, making EVT ideal for real-time safety analysis."
> — 2407.16832, §1

And the framing of the estimand:

> "An emerging direction for establishing the traffic conflict-crash relationship is to develop
> extreme value theory (EVT) models, which **takes interactions between conflicting road users as
> risky events and estimates the risk of crash conditional on such events measured by proximity
> indicators** (Songchitruksa and Tarko 2006). Previous studies have shown that using the EVT can get
> reliable crash estimations from traffic conflicts for different conflict/crash types, such as
> right-angle crashes…, lane-changing crashes…, run-off-road crashes…, head-on crashes…, freeway
> entrance merging crashes…, left-turn crashes…, rear-end crashes…"
> — *Investigating the transferability of Bayesian hierarchical extreme value model for traffic
> conflict-based crash estimation* (Zheng, Sayed & Essa), §1

### 1.4 The theoretical warrant: extremal types, not central limit

This is the deep reason the method is legitimate, and it is worth stating precisely. Ordinary
statistics leans on the central limit theorem, which describes *averages*. EVT leans on the
**extremal types theorem** (Fisher–Tippett), which describes *maxima* — and crucially, the limit law
is the same regardless of the parent distribution:

> "Commonly, statistical inference is based on averages obtained from datasets, with procedures
> utilising the **central limit theorem** being employed – supporting the use of the standard Normal
> distribution or associated t distribution. As we shall discuss…, **the LPI intervention, and
> associated traffic conflict data on collision near-misses, justifies the use of the extremal types
> theorem instead.** The associated extreme value distributions, introduced by Fisher and Tippett
> (1928), **arise as limits for the distribution of maxima (or minima) in sequences of independent,
> identically distributed random variables.** Typical applications occur in the environmental sciences
> to model, for example, extreme precipitation events or extreme wind speeds"
> — 2306.05925, §1

Stated from the anomaly-detection side, the same asymptotic robustness:

> "A key result from the Extreme Value Theory (EVT) shows that **the distribution of the extreme values
> is not highly sensitive to the parent data distribution. This enables us to accurately compute
> probabilities without first estimating the underlying distribution.** Under a weak condition, the
> extreme events have the same kind of distribution, regardless of the original one"
> — *LSTM-Based Anomaly Detection: Detection Rules from Extreme Value Theory* (arXiv 1909.06041), §3.3

**This is the whole trick.** You do not need to know the distribution of everyday driving. You only
need the tail to be in the domain of attraction of a GEV/GPD, which the extremal types theorem
guarantees under mild conditions. You then fit that tail on abundant near-miss data and evaluate it
at the crash boundary.

### 1.5 The stationarity precondition — and what violates it

The extrapolation is only valid if the process generating conflicts is the same process that would
generate a crash. The ACC paper is unusually explicit about the boundary:

> "The premise is that **car-following is a set of circumstances that has a non-zero probability of
> ending up in a conflict, so that when the process is repeated enough times it will result in a
> crash. The assumption is that car following is a stationary process** (Coles, 2001, Ch. 1).
> **Crashes that are the result of exceptional lead-vehicle situations (e.g., a lead vehicle slamming
> on the brakes suddenly) are not considered in this analysis, as these situations would violate that
> assumption**; the stability of the prevailing car-following process would be disrupted, and the
> situation would not be compatible with an EVT analysis."
> — *Extreme Value Analysis for Safety Benefit Estimation of Adaptive Cruise Control (ACC)*, §2.3

That is the scope limit of the entire method in one paragraph: **EVT estimates the crash risk
intrinsic to a stable interaction process. It cannot see crashes caused by a regime change.**

---

## 2. What gets modelled: the indicator and its sign

EVT models maxima, but danger in traffic is *small* TTC. Every study resolves this the same way — by
negating the indicator so that "large" means "dangerous", and a crash sits at the value 0.

Common choices in the corpus:

| Indicator | Definition | Crash boundary | Used in |
|---|---|---|---|
| **TTC** (time-to-collision) | time until collision if both parties continue unchanged | TTC = 0 | 2407.16832, 2606.12500 |
| **PET** (post-encroachment time) | time between one party leaving and the other entering the conflict point | PET = 0 | 2306.05925, `local:3e48f8f644b8` |
| **MTTC** (modified TTC) | TTC adjusted for differing speeds/accelerations | MTTC = 0 | Zheng et al. BHEVM |
| **BTN** (brake threat number) | braking effort required to avoid collision, as a fraction of available | BTN = 1 | ACC paper |

The sign convention, stated explicitly:

> "**RC_n = Pr(X_n ≥ 0)**… In this context, **a crash is defined as having a TTC equal to zero.** The RC
> index represents the probability that **the maximum negated TTC in a given block exceeds zero**."
> — 2407.16832, §3.3.3

> "…and **Z_ik is the maximum of negated MTTC** in block k at site i."
> — Zheng, Sayed & Essa, §4.2.2

And for the lower tail directly:

> "In this paper, we focus on **the lower tail of the data where small time values indicate a dangerous
> situation**: a near-miss or collision between a pedestrian and left-turning vehicle."
> — 2306.05925, §1

The 2D generalisation, using AV sensor data rather than a roadside camera:

> "This study proposes a generalized real-time traffic risk estimation framework that uses a
> **high-fidelity, 2D near-miss indicator (beyond specific crash patterns)**… Near-miss events are
> derived from high-resolution Waymo motion data, **updated every 0.1s**, across six locations in three
> major cities: San Francisco, Phoenix, and Los Angeles."
> — 2407.16832, §1

---

## 3. The two sampling schemes

### 3.1 Block maxima → the Generalised Extreme Value distribution

**The construction.** Partition the observation period into blocks; keep only each block's maximum;
fit a GEV to that set of maxima.

> "The first layer models the traffic conflict extremes with the **generalized extreme value (GEV)
> distribution, for which observations are aggregated into fixed blocks over time and the maximum of
> each block is treated as an extreme** (Coles 2001). To be specific, let X_i1, X_i2, …, X_in be a
> sequence of traffic conflicts observed on site i for a certain time period T_i, and let z_ik be the
> **kth recorded block maximum at site i**, with i = 1,…,s and k = 1,…,T_i/t, **where t is the block
> interval**"
> — Zheng, Sayed & Essa, §2

**The distribution.**

> "Von Mises (1954) and Jenkinson (1955) independently derived a distribution which encompasses all
> three types of extreme value distribution; **the Generalised Extreme Value distribution (GEV)**."
> — 2306.05925, §3.2.1

    G(y; μ, σ, ξ) = exp[ −(1 + ξ(y − μ)/σ)^(−1/ξ) ]      ξ ≠ 0
                  = exp[ −exp(−(y − μ)/σ) ]               ξ = 0

defined on {y : 1 + ξ(y − μ)/σ > 0}, with **μ = location, σ > 0 = scale, ξ = shape**.

**Why block maxima quietly absorbs short-range dependence** — an underrated practical advantage:

> "It can be shown that F^(nθ) is also GEV with d.f. G(y; μ*, σ*, ξ), **provided long-range dependence
> is negligible**; technically, this requires Leadbetter's D(u_n) condition to hold… Hence, **for block
> maxima, in practical terms short-range dependence can be ignored.**"
> — 2306.05925, §3.2.1

**The cost.**

> "In practice, the GEV is used to model maxima over some convenient calendar unit – usually years.
> However, **choosing a suitable block size can sometimes be problematic**… **blocks would need to be
> large enough for the limiting results to hold, yet if they're too large there will be too few
> maxima from which to make inferences.** Additionally, as discussed above, **this method generally can
> be hugely wasteful of data – discarding, as it does, all but the block maxima.**"
> — 2306.05925, §3.2.1

### 3.2 Peaks over threshold → the Generalised Pareto distribution

**The construction.** Fix a high threshold `u`; model the excesses `X − u | X > u`.

> "Pickands (1975) showed that for θ = 1 and u large, **(X − u | X > u) follows a Generalised Pareto
> Distribution (GPD)**"
> — 2306.05925, §3.2.2

    H(y) = 1 − (1 + ξy/σ̃)^(−1/ξ)     ξ ≠ 0
         = 1 − exp(−y/σ̃)              ξ = 0

> "…defined on y > 0, with scale and shape parameters σ̃ and ξ respectively. Here, **σ̃ is related to the
> parameters in the corresponding GEV for block maxima through σ̃ = σ + ξ(u − μ)**. Threshold methods
> classify observations as extreme if they exceed some high threshold, usually denoted u; then, the
> GPD… is fitted to the excesses over this threshold."
> — 2306.05925, §3.2.2

**The catch that block maxima does not have:**

> "Unlike the case of modelling block maxima with the GEV, powering F^n by θ… **does not lead to another
> extreme value distribution whose parameters have absorbed the extremal index; thus, careful
> consideration of extremal dependence is required (and, unlike consecutive block maxima, extremal
> dependence is usually present between consecutive threshold excesses).**"
> — 2306.05925, §3.2.2

### 3.3 The trade-off, as the field states it

The two camps are explicit, and they disagree.

**Pro-POT** (more data, better estimates):

> "Several studies have indicated that **the peak over threshold method is superior to the block maxima
> method in terms of estimated accuracy and reliability** (Zheng et al., 2014a; Borsos et al., 2020).
> **This is because the peak over threshold utilizes more traffic conflict data while the block maxima
> method tends to discard a significant amount of conflict data.** A critical issue with the peak over
> threshold method is the determination of the threshold to distinguish the extreme conflicts and
> general conflicts. **If the threshold is set too low, it violates the asymptotic basis of the model,
> resulting in bias estimation**"
> — *Bayesian hierarchical non-stationary hybrid modeling for threshold estimation in peak over
> threshold approach* (arXiv 2503.14839), §1

**Pro-BM** (objective, and it fits streaming AV data):

> "…the **Block Maxima (BM)** method, which fits maxima or minima from fixed-duration blocks using the
> Generalized Extreme Value (GEV) distribution (Coles et al., 2001), and the **Peaks Over Threshold
> (POT)** method, which models threshold exceedances using the Generalized Pareto Distribution (GPD).
> **Although POT can be data-efficient, it is highly sensitive to threshold selection and typically
> requires declustering and handling of dependencies when applied to dense trajectory data. By
> contrast, BM aligns naturally with real-time AV unique-segmented data, avoids subjective thresholds,
> and supports scalable time-series analysis** (Fu and Sayed, 2022a; Songchitruksa and Tarko, 2006).
> **Consequently, this study adopts the BM–GEV framework.**"
> — *Learning from geometry-aware near misses to real-time COR: A corridor-wide grouped random
> parameters GEV framework* (arXiv 2509.02871), §3

| | Block maxima / GEV | POT / GPD |
|---|---|---|
| Tuning knob | block size `t` | threshold `u` (+ declustering `κ`) |
| Subjectivity | low — block size is a design choice | high — threshold choice drives results |
| Data efficiency | poor (one point per block) | good (all exceedances) |
| Short-range dependence | absorbed into the fitted parameters | must be handled explicitly |
| Fits streaming/segmented data | naturally | awkwardly |
| Corpus verdict | favoured for AV trajectory streams | favoured for fixed-site conflict counts |

---

## 4. Choosing the knob

### 4.1 Block size

The rule is a bias–variance trade-off between asymptotic validity and sample size:

> "We chunked the BTN time series into **7 km-long blocks. This block length was chosen to minimize
> temporal dependency (Coles, 2001, Ch. 5) and retain the most data.** Then, we extracted the maximum
> BTN value in each block (block maxima [BM]). On average, trials were about 21 km long, resulting in
> about 3 BM for each vehicle in each trial. **Blocks shorter than 75% of the desired block length…
> were discarded.**"
> — ACC paper, §2.3.1

Note that this study blocks by **distance, not time** — the natural exposure unit for a car-following
process. For real-time AV work the block is short and temporal:

> "Introduce a conflicting pair approach for Block Maxima (BM) based sampling (**each block size is
> 20s**), effectively addressing the **scarcity of samples in short-duration traffic segments**."
> — 2407.16832, §1

### 4.2 Threshold selection (POT)

The standard graphical toolkit:

> "…if it is a valid model for excesses over some threshold u₀, then it is valid for excesses over all
> thresholds u > u₀. Furthermore, for all u > u₀, **E[X − u | X > u] is a linear function of u**. In
> practice, this expectation can be estimated empirically as the sample mean of the excesses over u.
> **This leads to the mean residual life plot (MRL plot)**: a graphical procedure for identifying a
> suitably high threshold… in which mean excesses over u are plotted against a range of values for u,
> and **the optimal threshold is chosen at the lowest point above which we observe linearity in the
> plot.**"
> — 2306.05925, §4.1

> "Graphical diagnostics approach based on visual inspection of plots are widely utilized and
> considered the most popular method for determining thresholds. This method primarily includes the
> **mean residual life plot** (Davison and Smith, 1990), **threshold stability parameters plot** (Coles,
> 2001), and **Hill plot** (Drees et al., 2000). The threshold can be obtained **when the mean residual
> life plot exhibits approximate linearity, and the threshold stability plot demonstrates approximate
> constancy. However, this method is subjective and may result in multiple potential thresholds**"
> — 2503.14839, §2.2

A worked example, with numbers:

> "**As shown in Fig. 9 (a), the mean residual life is approximately linear when the negated TTC is less
> than −1.1, while both the modified scale and shape parameters exhibit stability around −1.1.
> Therefore, −1.1 was selected as the threshold** for this example."
> — 2606.12500, §3.3

And the honest admission that no true threshold exists:

> "…it must be noted that **in the real world a clear-cut threshold separating traffic conflicts from
> controlled interactions does not exist**: choosing a high enough threshold would allow no conflict to
> be missed, but would also wrongly include many controlled interactions; conversely, choosing a low
> enough threshold to exclude all controlled int[eractions]…"
> — *Before-after safety analysis of a shared space*, §3.3

There is a pragmatic escape — look for stability in the **output**, not the parameters:

> "…considering the resulting estimated number of crashes Inc_t, it is possible to observe a **'stable'
> zone in which, reducing the threshold value, the corresponding increase in P is compensated by a
> decrease in n**. **Choosing any threshold u in this zone would produce a similar estimated number of
> crashes.** Normally the highest value of u within this zone is chosen…, as it allows the most
> efficient use of data"
> — *Before-after safety analysis of a shared space*, §3.3

---

## 5. Handling dependence

Consecutive threshold exceedances are not independent — a single tense interaction produces a burst
of low TTC values. Two remedies appear in the corpus.

### 5.1 Declustering (the classical POT fix)

> "The aim of this approach for handling extremal dependence is to extract a series of independent
> threshold excesses… **An auxiliary 'declustering parameter', say κ, is chosen and a cluster of
> threshold excesses is then deemed to have terminated once at least κ consecutive observations fall
> sub-threshold.** This is repeated over the entire series to identify clusters of excesses. Then, **the
> maximum (or 'peak') observation from each cluster is extracted, and the GPD fitted to the set of
> (hopefully independent) cluster peak excesses.**"
> — 2306.05925, §3.3.1

> "This approach is often referred to as **the 'peaks over threshold' approach (POT, Davison and Smith,
> 1990)** and is the most commonly-used approach for dealing with clustered extremes. Although this
> approach is quite easy to implement, **there are issues surrounding the choice of κ. If κ is too
> small, the cluster peaks will not be far enough apart to safely assume independence; if κ is too
> large, there will be too few cluster exceedances on which to form our inference** (and of course, the
> approach will be wasteful of data). Furthermore, **parameter estimates have been shown to be
> sensitive to the choice of κ** (Fawcett and Walshaw, 2012)."
> — 2306.05925, §3.3.1

**Note the terminology trap:** "POT" in this literature often means *declustered* peaks-over-threshold,
i.e. GPD + declustering, not just "fit a GPD to exceedances".

### 5.2 Modelling the dependence instead (the modern fix)

Rather than throwing data away, model the transition from one extreme to the next:

> "An **extreme value Markov chain** was proposed to conduct a traffic conflict-based BA safety
> evaluation, **modelling threshold excesses with the GPD marginally, and using a bivariate extreme
> value model for the temporal evolution of our extremes**, at each intersection."
> — 2306.05925, §5

The motivating observation is worth keeping, because it is the same spatial/temporal structure that
appears everywhere in traffic data:

> "…even above a high threshold **there appears to be dependence between consecutive PET values. At
> busier times of the day – perhaps early morning or late-afternoon – we might expect more pedestrians
> to be using the crosswalks… and a greater number of vehicles turning into the intersections**"
> — 2306.05925, §3.3

---

## 6. From a fitted tail to a crash count over an exposure

**This is the step that answers "estimate collision over an exposure".** It is three lines of algebra
and it is where all the leverage — and all the extrapolation risk — sits.

### 6.1 Step 1 — per-block crash probability

Evaluate the fitted GEV at the crash boundary (negated indicator = 0):

> "The **Risk of Crash (RC)** index is a probabilistic measure derived from the GEV distribution, used to
> quantify the likelihood of a crash based on TTC data. In this context, **a crash is defined as having
> a TTC equal to zero.** The RC index represents **the probability that the maximum negated TTC in a
> given block exceeds zero.**"
> — 2407.16832, §3.3.3

    RC_n = Pr(X_n ≥ 0) = 1 − exp{ −[1 − ξ_n (μ_n / exp(ϑ_n))]^(−1/ξ_n) }     ξ_n ≠ 0
                       = 1 − exp{ −exp(μ_n / exp(ϑ_n)) }                      ξ_n = 0

> "The value of RC_n ranges from 0 to 1, where 0 indicates no crash risk and values closer to 1 indicate
> higher crash risk."
> — 2407.16832, §3.3.3

### 6.2 Step 2 — sum over blocks to get expected crash frequency

    CF = Σ_{n=1..k} RC_n

> "For a site with m blocks during an observation period T_i, **the total risk of crash is R_i = Σ_{k=1..m}
> R_ik. Since R_i is a non-negative value, it can be taken as the expected crash frequency for the
> observation period T.**"
> — Zheng, Sayed & Essa, §4.2.2

The summation is legitimate because each RC_n is a Bernoulli success probability for "this block
contains a crash", and the expectation of a sum of Bernoullis is the sum of their probabilities —
**no independence assumption is needed for the expectation** (it *is* needed for its variance).

### 6.3 Step 3 — scale to the exposure of interest

    CF_year = (T / t) × CF

> "where CF is defined as crash frequency, **k is the number of BM used in the observation period, and T
> is the total annual BM data in the model.**"
> — 2407.16832, §3.3.3

> "The estimated crash risk **can be translated to extended periods beyond the observation period, such
> as annually.**"
> — 2407.16832, §3.3.3

**The exposure unit is whatever the block was defined over.** Block by 20 seconds of conflicting-pair
time → scale by blocks per year. Block by 7 km of car-following → scale by kilometres driven. The
ACC study reports its result in exactly that currency:

> "…the probability of a crash under ACC being extremely low—on the order of 1·10^15 blocks
> (**equivalent to 9·10^15 km**)"
> — ACC paper (abstract summary)

That number is the honest face of this method: a fitted three-parameter tail, extrapolated roughly
fifteen orders of magnitude beyond the observed data.

---

## 7. Non-stationarity: covariates in the tail parameters

Real traffic is not stationary — volume, platooning and shock waves all shift the conflict
distribution. The standard fix is to make the GEV parameters regressions on covariates.

> "The second layer is a process layer where **a latent Gaussian process underlying extremes is
> characterized by constructing a structure that relates the parameters of the data layer to certain
> covariates with identity link functions.** To capture the additional heterogeneity that is not
> addressed by the covariates, **site-specific random error terms are also introduced.**"
> — Zheng, Sayed & Essa, §2

    μ_ik = α_μ · X + ε_μi
    φ_ik = α_φ · X + ε_φi          (φ = log σ, to enforce σ > 0)
    ξ_ik = ξ    + ε_ξi

A concrete, fitted specification — note which covariates enter which parameter:

    μ_ik = α_μ0 + α_μ1·V + α_μ2·A + α_μ3·P + ε_μi
    φ_ik = α_φ0 + α_φ1·A + ε_φi
    ξ_ik = ξ_0  + ε_ξi

> "where V is the **traffic volume per cycle**, A is the **shock wave area of a signal cycle**, and P is the
> **platoon ratio** of a signal cycle."
> — Zheng, Sayed & Essa, §2

**The one rule everyone follows — never put covariates on the shape parameter:**

> "It is also noted that **no covariates are added to the shape parameter, because the shape parameter is
> difficult to estimate with precision and thus it is common practice to assume that the shape
> parameter is not affected by covariates** during the process (Coles 2001)."
> — Zheng, Sayed & Essa, §2

The AV version uses vehicle dynamics as the covariates:

> "**Incorporates conflicting vehicle dynamics (e.g., speed, acceleration, and deceleration) as
> covariates into non-stationary hierarchical Bayesian structure with random parameters (HBSRP) UGEV
> models**, allowing for the effective management of vehicle spatial, temporal, and behavioral
> heterogeneity."
> — 2407.16832, §1

---

## 8. The Bayesian hierarchical layer

Single-site EVT fits are unstable — few extremes, three parameters. Pooling across sites is the
standard remedy.

> "A recent advancement is the development of **Bayesian hierarchical extreme value models (BHEVM) which
> can combine conflict extremes of different sites and account for non-stationarity and unobserved
> heterogeneity for crash estimation.**"
> — Zheng, Sayed & Essa, Abstract

**The three layers:**

1. **Data layer** — block maxima z_ik ~ GEV(μ_ik, σ_ik, ξ_ik)
2. **Process layer** — parameters as covariate regressions + site random effects (§7 above)
3. **Prior layer**:

> "The uninformative priors for the regression parameters α_μ and α_φ are adopted. They are assumed to
> follow a normal distribution with zero mean and large variance, i.e., **Normal(0, 10⁶)**. **The prior for
> shape parameter is set as ξ ~ Uniform(−1.0, 1.0), because previous studies have shown that the
> estimated shape parameters are in general within the range of (−1.0, 1.0)** (Songchitruksa and Tarko
> 2006; Zheng et al. 2014b). The random effects are modeled as a zero mean Gaussian process… The prior
> distributions of precision for random error terms are set as diffused gamma distributions, i.e.,
> **Gamma(0.01, 0.01)**."
> — Zheng, Sayed & Essa, §2

    p(θ | Y) ∝ p₁(Y | θ₁) · p₂(θ₁ | θ₂) · p₃(θ₂)
                 ─────────   ──────────   ──────
                   Data        Process     Prior

**Why the ξ prior matters more than it looks.** ξ controls the tail's weight, it is estimated from a
handful of extremes, and it drives an extrapolation of many orders of magnitude. Bounding it to
(−1, 1) is a *substantive* modelling assumption dressed as a convenience, and it is where a
Bayesian analyst should look first when a result seems too clean.

### 8.1 Transferability

Because collecting conflict data is expensive, a live question is whether a model fitted in one
city works in another:

> "**The need for model transferability arises from the fact that some jurisdictions have too limited
> resources to fully develop their own models**… **Although traffic conflicts are more observable than
> crashes, existing approaches to observe them are time and labor consuming.**"
> — Zheng, Sayed & Essa, §1

> "Intuitively, it seems reasonable to assume that the Bayesian hierarchical extreme value model is
> transferable… Firstly, **traffic conflicts and crashes share similar processes and influence factors
> (Tarko 2018), which are unlikely to vary significantly among jurisdictions if they share similar
> road and traffic characteristics.**"
> — Zheng, Sayed & Essa, §1

Two transfer mechanisms are tested: **recalibrating the random-error terms**, and **using the source
model's posterior as an informative prior**.

---

## 9. Bivariate and multivariate extensions

One indicator is a lossy view of a conflict. Two indicators jointly are better:

> "…another method is **bivariate extreme value modelling that employs Generalised Extreme Value (GEV) or
> Generalised Pareto (GP) distributions to approximate the marginal distribution of the extremes of
> any two measures** (Zheng and Sayed, 2019c)."
> — *(survey paper `local:52b5fc5d767d`)*, §3.5

The dependence structure is carried by a single function:

> "…the **bivariate extreme value distribution L for component-wise maxima is characterized by a
> one-dimensional function A\*.** Common used functions are **the logistic, asymmetric logistic,
> Husler-Reiss, negative logistic, asymmetric negative logistic, bilogistic, negative bilogistic,
> Coles Tawn, and asymmetric mixed models.**"
> — *Road safety of passing maneuvers: a bivariate extreme value theory approach under non-stationary
> conditions* (arXiv 1812.06749), §2.3

The state of the art, as surveyed:

> "Several studies developed **stationary bivariate EVT models for crash estimation incorporating two
> conflict indicators** (Zheng et al., 2019a; Arun et al., 2021)… Tahir and Haque (2024) proposed a
> **non-stationary bivariate extreme value model to estimate real-time pedestrian crash risk by
> severity.** Cavadas et al. (2020) extended bivariate non-stationary EVT models for **the joint
> probability of head-on and rear-end crashes** during passing maneuvers"
> — 2503.14839, §2.1

---

## 10. Does it actually work? The validation evidence

### 10.1 The standard validation protocol

Compare the EVT-predicted crash frequency against the observed crash count, with the observed count's
own Poisson interval as the tolerance band:

> "To quantify the accuracy of crash frequency predictions, we used three different metrics: (1) **hit
> rate, defined as the percentage of predicted values that fall within the Poisson confidence
> intervals of the actual annual crash frequency** (Songchitruksa & Tarko, 2006), (2) **mean absolute
> error (MAE)**…, and (3) **root mean square error (RMSE)**"
> — 2606.12500, §2.4

The Poisson band itself:

> "where [λ] is the annual crash frequency, χ² is the Chi-squared distribution, [n] is the total
> observed crash counts for intersection i for [k] years, [α] is the significance level, **set to 0.05
> in current study (Songchitruksa & Tarko, 2006), corresponding to a 95% confidence interval.**"
> — 2606.12500, §2.1

Note the recursion: the ground truth against which EVT is validated is itself an exact-Poisson
interval on a handful of crashes — the same small-count machinery documented in the
[uncertainty report](WAYMO-UNCERTAINTY-METHODS-REPORT.md).

### 10.2 What the validation actually shows

The most detailed validation in the corpus is candid, and the failure mode is directional:

> "**The model overestimates near misses at severe thresholds**, suggesting that the model may be overly
> sensitive at these severe thresholds, leading to higher predicted values than found near misses…
> Conversely, **the model underestimates the near misses at less severe thresholds**… **The model seems to
> provide reasonable estimates, although there are instances where the observed near-misses fall
> outside the estimated confidence intervals**"
> — 2407.16832, §4.3

And a structural limitation that should be read carefully by anyone citing that paper's numbers:

> "Since the study dataset is anonymous, it lacks specific geolocation, date, and time information.
> Consequently, **no definitive ground truth is available for identifying real extreme events or actual
> crashes in the study area.**… A cross-fold validation approach was adopted to address this."
> — 2407.16832, §4.3

**That is validation against held-out near-misses, not against crashes.** The extrapolation from the
near-miss tail to TTC = 0 — the one step the whole method exists to perform — is not tested there.

---

## 11. Known weaknesses

Collected verbatim, because they are the questions a reviewer will ask.

**The tail-shape assumption is unverifiable where it matters.**
> "Although **Extreme Value Theory has been used within hierarchical Bayesian frameworks to extrapolate
> crash likelihoods from SSM tails**, it **still relies on strong, hard-to-verify assumptions about tail
> shape and does not systematically resolve these fundamental ambiguities.**"
> — *Simulating the Unseen: Crash Prediction Must Learn from What Did Not Happen* (arXiv 2505.21743), §3.2

**The indicator itself is model-dependent, so the tail inherits that dependence.**
> "…SSMs depend critically on **the chosen vehicle-dynamics model, assumed driver-behavior parameters,
> and encoded interaction scenarios.** Consequently, **correlations between SSM counts and crash counts
> fluctuate with context, threshold choice, and study design, making SSMs reliable for ranking
> relative severity but unreliable for quantifying absolute risk.**"
> — 2505.21743, §3.2

**Thresholds do not transfer across contexts.**
> "**As most SSMs are threshold sensitive, using the same threshold to measure conflicts in different
> traffic conditions may easily underestimate or overestimate safety.**… **Although there is no universal
> rule for SSM threshold selection**, a few methods were proposed and could be adopted."
> — *Advances and Applications of Computer Vision Techniques in Vehicle Trajectory Generation and
> Surrogate Traffic Safety Indicators* (arXiv 2303.15231), §5.3

**Threshold selection is a bottleneck, not a detail.**
> "…a conservative TTC threshold will classify a large number of interactions as unsafe which could
> potentially overstate risk. However, a more lenient threshold may overlook meaningful precursors to
> crashes. **Thus, threshold selection remains a bottleneck in conflict-based safety analysis.**"
> — *Latent Class Logit Kernel Framework for Surrogate Safety* (arXiv 2510.12012), §1

**The method's own summary of its trade-off**, from a survey table:

> "**Extreme value estimation** — (1) Mean residual life plot (2) Threshold stability plot |
> *Strengths:* (1) Explain the heterogeneity in thresholds (2) **Estimation does not require crash data** |
> *Weaknesses:* (1) **Requires high-quality traffic conflict and crash data over a longer period**
> (2) **Sensitivity and specificity need to be improved**"
> — *Traffic flow clustering framework using drone video trajectories* (arXiv 2303.16651), Literature Review

---

## 12. EVT in AV safety validation: two uses that are not crash-rate estimation

Everything above answers "how many crashes per unit exposure". Two papers in this corpus point the
same machinery at different questions, and both matter for AV work.

### 12.1 Bounding the scenario space: quantifying "reasonably foreseeable"

UNECE R157 (Automated Lane Keeping Systems) contains a requirement that has no number in it:

> "Regarding the system safety and fail-safe response, the following requirement is mentioned…
> **'The activated system shall not cause any collisions that are reasonably foreseeable and
> preventable.'** This requirement leaves room for different interpretations, because **the terms
> 'reasonably foreseeable' and 'preventable' have not been quantified. The different interpretations
> might result in disagreements among ADS developers and the authorities that are requested to
> approve an ADS.**"
> — *A Quantitative Method to Determine What Collisions Are Reasonably Foreseeable and Preventable*
> (arXiv 2309.02177), §1

The paper's answer is to use the GPD not to estimate a crash rate, but to put an **upper bound on a
scenario parameter** — how fast a cut-in can be, how slow a lead vehicle can be — such that anything
beyond the bound is, by an agreed frequency budget, no longer "reasonably foreseeable".

> "our second approach for determining the parameter range makes use of a parametric distribution,
> namely the **Generalized Pareto Distribution (GPD)**. As we will explain next, **according to the
> Extreme Value Theory (EVT), this choice is justified as long as we only use the data that is above a
> certain threshold**"
> — 2309.02177, §2.1.4

**The bound is defined by an exceedance-frequency budget.** Let `L(u) = {i ; xᵢ > u}` be the indices
above threshold `u`, and `{yₗ} = {xᵢ − u}` the excesses. Then the upper bound `x_U` solves:

    E[n_C] · P(x > u) · (1 − G(x_U − u)) = ε_F                          (Eq. 12)
    P(x > u) = |L(u)| / N                                               (Eq. 13)

where `E[n_C]` is the expected number of scenarios in category C, `G` is the fitted GPD, and **ε_F is
the chosen foreseeability budget, expressed as a frequency**. The reported results make the knob
visible:

> "This results in a **lower bound of v_l/v_e,0 = 0.62 with ε_F = 0.1 h⁻¹** and a **lower bound of
> v_l/v_e,0 = 0.27 with ε_F = 0.01 h⁻¹**"
> — 2309.02177, §3.4

**Read that carefully.** Tightening the budget by one order of magnitude (0.1/hour → 0.01/hour) moves
the required speed-ratio bound from 0.62 to 0.27 — the ADS must now handle a *much* more aggressive
cut-in. **ε_F is the regulator's dial**, and this paper's contribution is to make it explicit rather
than leaving "reasonably foreseeable" to argument.

The honest self-assessment, including the same dimensionality limit that dogs bivariate EVT:

> "**The advantage of this approach is that the EVT justifies the choice of the GPD.** EVT has
> successfully been used to determine extremes that are beyond the most extreme values in the data
> (de Haan, 1994; Tarko, 2012). **A disadvantage of this approach is that it is typically applied to
> only one parameter**"
> — 2309.02177, §4.1

Three escapes from the one-dimension limit are offered: bound one parameter and treat the rest as
fully foreseeable; assume parameter independence; or **map the d-dimensional parameter space to 1-D,
bound there, and invert the map**. The third is the interesting one and is left unelaborated.

### 12.2 Learning the covariate function: NsBM-GAT

§7 showed the non-stationary GEV with **linear** covariate regressions on μ and log σ. NsBM-GAT
attacks exactly that linearity.

**The critique:**

> "In typical traffic scenarios, **vehicle interactions exhibit hexagonal spatial dependencies.
> Specifically, a subject vehicle's operational state is simultaneously influenced by six adjacent
> vehicles** (front/rear pairs in left, original, and right lanes). **This multi-agent interdependency
> creates nonlinear coupling effects that traditionally SSMs fail to quantify.**"
> — *NsBM-GAT: A Non-stationary Block Maximum and Graph Attention Framework for General Traffic Crash
> Risk Prediction* (arXiv 2503.04018), §II.C

> "**While current covariate formulations rely on linear operators, they inherently prevent the ability
> to predict crash risks across multiple driving tasks simultaneously.** For example, **a unified linear
> covariates formulation is insufficient to capture the distinct risk factors influencing both
> car-following and lane-changing maneuvers.** Furthermore, even when analyzing a single driving task,
> **the linear covariate function is not enough to capture the intricate interactions among vehicles.**"
> — 2503.04018, §II.C

**The fix:** replace `μ = α·X` with a graph attention network over the six-neighbour vehicle graph,
and train the GAT weights through the GEV likelihood.

> "In Section III-B, **we address the limitations of linear covariate formulations in the BM method by
> proposing a novel solution based on Graph Attention Networks (GAT).** Then, we describe **the design of
> the loss function and gradient computation for integrating the BM and GAT approaches**"
> — 2503.04018, §III

**A BM/POT hybrid worth noting**, because it contradicts the clean dichotomy of §3 — they take block
maxima *and then* apply a threshold:

    X^i = [X^i_1, …, X^i_t],  t = T/τ,  τ = 0.1 s                        (Eq. 1)
    M^i_k = max over block k of width w                                  (Eq. 2)
    Y^i = { M^i_j : M^i_j > Q }                                          (Eq. 3)

> "Following the approach in [7] and [55], **an initial threshold Q is applied to eliminate
> non-dangerous samples**, further refining the sequence Y^i"
> — 2503.04018, §III

**And a construction that is genuinely different from everything in §6** — instead of evaluating one
fitted tail at the crash boundary, fit *two* GEVs and difference them:

> "Chen et al [7] extracted extremely dangerous events from 5s trajectories data before the crash
> moment across 20 crash samples and constructed corresponding GEV distributions. **Crucially, parallel
> GEV distribution was developed for non-crash scenarios under identical operational conditions. The
> differential of these GEV distributions enables real-time crash prediction.**"
> — 2503.04018, §II.C

This sidesteps the extrapolation problem: you never evaluate a tail at TTC = 0. You ask instead which
of two fitted tails the current observation looks more like. **It also abandons the exposure-based
crash-count estimand entirely** — the output is a classification score with a lead time, not a rate.
Reported as "95% accuracy in predicting crashes 2 seconds before impact", validated on drone
trajectory data from Nanjing.

**The trade-off is the usual one and should be stated plainly:** the GAT buys nonlinear covariate
structure at the price of the one property that made EVT attractive in the first place — a
three-parameter model whose extrapolation is justified by a limit theorem. A learned covariate
function has no such warrant, and the two-GEV differential needs labelled crashes, which returns you
to the data scarcity EVT existed to escape.

---

## 13. The recipe, end to end

1. **Extract trajectories** — roadside camera, drone, or AV sensor stream.
2. **Compute a proximity indicator** per conflicting pair per timestep (TTC, PET, MTTC, BTN).
3. **Negate it** so large = dangerous, and the crash sits at 0.
4. **Choose a sampling scheme:**
   - **BM** → pick a block size (time or distance) large enough for the GEV limit, small enough to keep
     sample count. Take each block's max.
   - **POT** → pick `u` via MRL plot + threshold stability plot; decluster with `κ`, or model the
     dependence with an extreme-value Markov chain.
5. **Fit** GEV (BM) or GPD (POT). Make μ and log σ regressions on covariates if non-stationary. Leave
   ξ constant.
6. **Pool across sites** with a Bayesian hierarchical structure; site random effects absorb
   unobserved heterogeneity; ξ ~ Uniform(−1, 1).
7. **Evaluate the fitted tail at 0** → per-block crash probability RC_n.
8. **Sum over blocks** → expected crash frequency for the observation period.
9. **Scale by the exposure ratio** (T/t) → crashes per year, per million km, or whatever the block
   unit implies.
10. **Validate** against observed crashes using hit rate within the observed count's Poisson interval,
    plus MAE / RMSE.

---

## 14. Where to read next, in this corpus

| Paper | ID | Why |
|---|---|---|
| Using extreme value theory to evaluate the leading pedestrian interval | `2306.05925` | **Best methodological exposition.** GEV vs GPD, declustering vs Markov chain, MRL plots, Bayesian inference. Start here. |
| Investigating the transferability of Bayesian hierarchical EVM | `local:01eeae2ed714` | The canonical three-layer BHEVM, with the full prior specification and the crash-estimation identity. |
| Real-time risk estimation… Waymo AV sensor data | `2407.16832` | BM-GEV on AV trajectory streams; explicit RC/CF equations; honest validation section. |
| Bayesian hierarchical non-stationary hybrid modeling for threshold estimation | `2503.14839` | The POT-vs-BM argument and the state of threshold-selection research. |
| Extreme Value Analysis for Safety Benefit Estimation of ACC | `local:a265a79504fe` | Distance-blocked BM; clearest statement of the stationarity precondition. |
| Improving Crash Frequency Prediction from Simulated Traffic Conflicts | `2606.12500` | The validation protocol (hit rate / MAE / RMSE) with a worked threshold selection. |
| Road safety of passing maneuvers: a bivariate EVT approach | `1812.06749` | Bivariate EVT, non-stationary, with the POT appendix. |
| Corridor-wide grouped random parameters GEV framework | `2509.02871` | Recent BM-GEV with grouped random parameters; states the BM-over-POT case. |
| Simulating the Unseen | `2505.21743` | The sharpest published critique of the whole conflict→crash extrapolation. |
| Video-Based Surrogate Safety Analysis… CCTV Footage and EVT | `local:3e48f8f644b8` | POT applied to PET/TTC from ordinary CCTV — the low-budget deployment case. |
| A Quantitative Method to Determine What Collisions Are Reasonably Foreseeable | `2309.02177` | **GPD used to bound the scenario space, not estimate a rate.** The UNECE R157 angle; makes the foreseeability budget ε_F explicit. |
| NsBM-GAT | `2503.04018` | Replaces the linear covariate function with a graph attention network; also the two-GEV differential trick. |

---

## Provenance and caveats

**Provenance.** Evidence was gathered by exhaustive regex scan (`scan_corpus`) over all 1,738 papers
in the local `waymo_av_safety` corpus, followed by `get_section` / `get_paper` reads of the
identified papers. Quotations reproduce the stored markdown with PDF ligature-extraction artifacts
(`fi`/`ff` dropped) restored; ellipses and bracketed completions are marked; **bold** inside
quotations is mine. Equations are transcribed from rendered LaTeX into plain notation.

**Caveats.** (1) This surveys what is *in this corpus*, which is an AV-safety collection — it is well
stocked with recent EVT road-safety work but is not a systematic review of the field, and the
foundational references (Songchitruksa & Tarko 2006; Coles 2001; Zheng & Sayed 2019) are cited *by*
these papers rather than ingested themselves. (2) Section numbers come from the parser's recovered
headings; a few journal PDFs have imperfect heading extraction. (3) The interpretive passages —
§1.4's framing of the extremal types theorem as the method's warrant, §6.2's note on why the
Bernoulli sum needs no independence assumption, §8's note on the ξ prior being substantive, and
§10.2's observation that the AV validation never tests the extrapolation, and §12.2's note that a
learned covariate function forfeits the limit-theorem warrant — are my analysis, not claims the
papers make.
