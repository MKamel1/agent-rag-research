# Nelson (1970) Exact Rate-Ratio Confidence Intervals — Derivation and Python Implementation

*The method Waymo uses for every ADS-vs-human crash rate comparison: what it is, why the maths
works, and a verified `scipy` implementation. Written 2026-08-31.*

Companions: [`WAYMO-UNCERTAINTY-METHODS-REPORT.md`](WAYMO-UNCERTAINTY-METHODS-REPORT.md) §2, which
documents where and why Waymo adopts it, with the source quotations ·
[`RATE-INTERVALS-AND-PVALUES-TOOLKIT.md`](RATE-INTERVALS-AND-PVALUES-TOOLKIT.md), which pairs this
and the alternatives with matched p-values and adds the continuous normal reference case.

---

## What Waymo actually specifies

> "confidence intervals for the ratio between the ADS crash rate of *Y* events over *t* miles and the
> benchmark crash rate of *X* events over *s* miles were calculated using **the method described by
> Nelson (1970)** as
>
> ρ ∈ [ s/t · qbetaprime(α/2, Y, X+1) , s/t · qbetaprime(1 − α/2, Y+1, X) ]
>
> where *qbetaprime* is the quantile function of the beta prime distribution. **This formulation of
> the confidence intervals can be computed in the event of zero event counts in the ADS data (i.e.,
> Y = 0)**, but as a result may be more conservative (i.e., wider confidence intervals) in the case
> of non-zero ADS events counts compared to the Poisson exact model."
> — *Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million Miles*
> (arXiv 2312.12675), §Confidence Intervals, Eq. 2

And named as Clopper–Pearson in the successor paper:

> "A statistical comparison between the ADS and benchmark crash rates was done using
> **Clopper-Pearson limits to estimate 95% confidence intervals for the ratio of two Poisson mean
> occurrence rates, as described by Nelson (1970, Appendix I)**"
> — *…by Crash Type to Human Benchmarks at 56.7 Million Miles*, §Statistical Testing

Those two descriptions are the same interval. §3 below shows why.

---

## Step 0 — Setup and the point estimate

Two independent Poisson processes:

| | events | exposure | rate |
|---|---|---|---|
| ADS | `Y` | `t` miles | μ̂ = Y/t |
| Human benchmark | `X` | `s` miles | λ̂ = X/s |

**Point estimate of the rate ratio:**

```
ρ̂ = μ̂/λ̂ = (Y/t) / (X/s) = (Y·s) / (X·t)
```

ρ̂ < 1 means the ADS crashes less often per mile. The papers also report the **relative difference**

```
δ = (μ − λ)/λ = ρ − 1
```

so a "51% reduction" is ρ = 0.49. Exposure `t` and `s` may be in any unit as long as both use the
same one — miles, million miles, vehicle-hours.

---

## Step 1 — Condition on the total: a Poisson problem becomes a binomial one

This is the core idea, and the reason the interval is *exact* rather than approximate.

If `Y ~ Poisson(μt)` and `X ~ Poisson(λs)` independently, then **conditional on the observed total
`N = X + Y`**:

```
Y | N  ~  Binomial(N, p)        where   p = μt / (μt + λs)
```

The overall event intensity — a nuisance parameter nobody wants to estimate — **cancels**. What
remains is a one-parameter binomial problem, and binomial proportions have a textbook exact interval.

Now relate `p` back to `ρ`. Substituting μ = ρλ:

```
p = ρλt / (ρλt + λs) = ρt / (ρt + s)
```

and solving for ρ:

```
p(ρt + s) = ρt   →   p·s = ρt(1 − p)   →   ρ = (s/t) · p/(1 − p)
```

**ρ is a strictly increasing function of p.** That monotonicity is the licence for everything that
follows: an exact interval for `p` maps endpoint-to-endpoint onto an exact interval for `ρ`, with no
approximation introduced by the transform.

*Consistency check on the point estimate:* p̂ = Y/(X+Y), so p̂/(1−p̂) = Y/X, and
(s/t)·(Y/X) = Ys/(Xt) = ρ̂. ✓

---

## Step 2 — Clopper–Pearson exact limits on p

The exact binomial interval is obtained by inverting the Beta CDF:

```
p_lower = Beta.ppf(α/2,     Y,     N − Y + 1) = Beta.ppf(α/2,     Y,     X + 1)
p_upper = Beta.ppf(1 − α/2, Y + 1, N − Y)     = Beta.ppf(1 − α/2, Y + 1, X)
```

(`N − Y = X`, which is why the shape parameters fall out in terms of X and Y directly.)

This is *exact*, not approximate: it inverts the actual discrete binomial CDF rather than a normal
approximation to it. Consequently **coverage is ≥ 1−α always, never below** — which is precisely
what makes it usable at counts of 0, 1 or 2, and also why it is conservative at larger counts.

---

## Step 3 — The odds transform gives Beta-prime

Final piece: **if `p ~ Beta(a, b)` then the odds `p/(1−p) ~ Beta-prime(a, b)`.** Beta-prime (the beta
distribution of the second kind) is the same distribution already expressed in odds space.

So rather than taking a Beta quantile and transforming it, read the Beta-prime quantile directly:

```
ρ_lower = (s/t) · BetaPrime.ppf(α/2,     Y,     X + 1)
ρ_upper = (s/t) · BetaPrime.ppf(1 − α/2, Y + 1, X)
```

**This is Waymo's Equation 2 exactly.** The "Nelson (1970) beta-prime" formulation and the
"Clopper–Pearson limits" description are two names for one interval — which is why the 7.1M-mile
paper writes the first and the 56.7M-mile paper writes the second without any change of method.

---

## The implementation

```python
import numpy as np
from scipy.stats import betaprime


def nelson_rate_ratio(y, t, x, s, alpha=0.05):
    """Exact CI for rho = (y/t)/(x/s), the ratio of two independent Poisson rates.

    y, t : ADS events, ADS exposure (miles)
    x, s : benchmark events, benchmark exposure
    Returns (point_estimate, lower, upper). Point estimate is nan if x == 0.
    """
    k = s / t                                   # exposure ratio: odds -> rate ratio
    point = (y / t) / (x / s) if x > 0 else np.nan
    lower = 0.0     if y == 0 else k * betaprime.ppf(alpha / 2,     y,     x + 1)
    upper = np.inf  if x == 0 else k * betaprime.ppf(1 - alpha / 2, y + 1, x)
    return point, lower, upper


def relative_difference(point, lower, upper):
    """delta = rho - 1. Monotone transform, so endpoints map straight through."""
    return point - 1, lower - 1, upper - 1
```

### Why each line is what it is

| Line | Reason |
|---|---|
| `k = s / t` | The exposure ratio. `betaprime.ppf` returns an interval on the **odds** `Y/X` — a ratio of counts. Multiplying by `s/t` converts counts-per-count into rate-per-rate. Invert this and every number inverts. |
| `betaprime` not `beta` | Saves the explicit `p/(1−p)` step; numerically identical. Use `beta` instead if you want the derivation visible in the code. |
| `y, x + 1` vs `y + 1, x` | The asymmetric `+1` is the Clopper–Pearson construction, not a typo. It is what makes the interval exact, and it is the source of the conservatism. |
| `y == 0 → lower = 0.0` | `betaprime.ppf` requires shape `a > 0` and returns `nan` at `a = 0`. The correct value is 0: observing zero events is consistent with an arbitrarily small rate. |
| `x == 0 → upper = inf` | No benchmark events ⇒ no finite upper bound on the ratio. |
| `alpha / 2`, `1 − alpha / 2` | Two-sided, α split equally. `alpha=0.05` reproduces the 95% intervals in the papers. |
| `relative_difference` subtracts 1 | δ is monotone in ρ, so endpoints map straight through. No delta method, no variance propagation — matching the paper: *"the same confidence intervals described in Equation 2 can be used to generate confidence intervals for the relative difference."* |

### Self-checks

```python
from scipy.stats import beta

def _clopper_pearson_route(y, t, x, s, alpha=0.05):
    """Same interval derived the long way: Clopper-Pearson on p, then p/(1-p)*s/t."""
    n, k = x + y, s / t
    p_lo = 0.0 if y == 0 else beta.ppf(alpha / 2, y, n - y + 1)
    p_hi = 1.0 if y == n else beta.ppf(1 - alpha / 2, y + 1, n - y)
    return k * p_lo / (1 - p_lo), (np.inf if p_hi == 1 else k * p_hi / (1 - p_hi))


if __name__ == "__main__":
    # 1. The two routes must agree -- betaprime IS the odds transform of beta.
    for (y, t, x, s) in [(2, 56.7, 90, 1000.0), (5, 7.1, 40, 500.0), (0, 20.0, 12, 300.0)]:
        _, lo, hi = nelson_rate_ratio(y, t, x, s)
        lo2, hi2 = _clopper_pearson_route(y, t, x, s)
        assert np.isclose(lo, lo2) and (np.isclose(hi, hi2) or np.isinf(hi)), (y, lo, lo2, hi, hi2)
    print("PASS: betaprime route == Clopper-Pearson route")

    # 2. Interval must bracket the point estimate.
    pt, lo, hi = nelson_rate_ratio(2, 56.7, 90, 1000.0)
    assert lo < pt < hi
    print("PASS: interval brackets point estimate")

    # 3. Zero ADS events must still give a finite upper bound (the whole reason for this method).
    _, lo0, hi0 = nelson_rate_ratio(0, 20.0, 12, 300.0)
    assert lo0 == 0.0 and np.isfinite(hi0) and hi0 > 0
    print(f"PASS: y=0 gives finite CI [0, {hi0:.4f}]")
```

Verified output (run 2026-08-31, `scipy` in the `agent-rag-research` env):

```
PASS: betaprime route == Clopper-Pearson route
PASS: interval brackets point estimate
PASS: y=0 gives finite CI [0, 5.3984]
```

---

## Worked examples

**⚠️ The counts below are illustrative, chosen to show the behaviour at different event
counts. They are NOT Waymo's published figures — the papers' actual benchmark counts and
mileages are not reproduced here.**

```
serious-injury, 2 ADS crashes    rho= 0.3919  CI=[0.0467, 1.4575]
                                 reduction=  60.8%  CI=[-45.7%, 95.3%]
any-injury, 25 ADS crashes       rho= 0.4899  CI=[0.3153, 0.7280]
                                 reduction=  51.0%  CI=[27.2%, 68.5%]
zero ADS crashes                 rho= 0.0000  CI=[0.0000, 1.5067]
                                 reduction= 100.0%  CI=[-50.7%, 100.0%]
```

### Why the `Y = 0` row is the point of the whole method

A **finite upper bound from zero observed events**. Nothing based on a standard error can do this:
`log(ρ̂)` is `−inf`, and any normal-approximation interval `ρ̂ ± z·SE` collapses to a point. An AV
fleet with genuinely rare crashes produces zero-count cells routinely, so this is not a corner case
— it is the operating regime, and it is the first reason the papers give for the choice.

Note the interval straddles 1.0: a 100% observed reduction that is **not** statistically significant.
That is the correct and honest result from zero events.

### Why the 2-event row explains the papers' own caveat

Two events span "45% worse" to "95% better". This is the arithmetic behind the 56.7M-mile paper's
self-flag that its Suspected Serious Injury+ result "is subject to a low number of observations
(2 ADS crash) with large confidence intervals."

---

## Why Nelson, and not the alternatives

Four methods could plausibly produce a rate-ratio interval here. Summary first, evidence after.

| Method | Works at Y = 0? | Coverage at small counts | Verdict |
|---|---|---|---|
| **Nelson (1970)** exact | **Yes** — finite upper bound | ≥ nominal always (conservative) | **Used** for every rate ratio |
| Exact Poisson (gamma) | Yes, for a *single* rate | ≥ nominal | Used, but for a different estimand |
| Wald on log(ρ̂) | **No** — undefined | **Badly under-covers** | Never used; zero mentions in the corpus |
| Bootstrap | Depends on variant | Under-covers when events are rare | Run, measured, and rejected |

### vs. exact Poisson (the gamma-quantile interval)

**This is not a competing method — it answers a different question.** Both appear in the same paper:
Equation 1 is the exact Poisson interval for a *single* rate (IPMM), Equation 2 is Nelson for the
*ratio*. The papers use each for its own estimand.

The tempting shortcut is to build two single-rate intervals and compare them. That fails in two ways.

**Dividing the two intervals is over-conservative.** Taking worst-case-over-worst-case ignores the
joint distribution and inflates the result (illustrative counts, verified):

```
Y=2, X=90     Nelson (exact)         [0.0467, 1.4575]
              ratio of 2 exact-Pois  [0.0386, 1.7607]     <- wider, for no gain

Y=25, X=900   Nelson (exact)         [0.3153, 0.7280]
              ratio of 2 exact-Pois  [0.2970, 0.7729]
```

**Declaring significance by non-overlap costs power.** Two 95% intervals failing to overlap implies
significance at well *below* α = 0.05, so it is a stricter bar than a proper test of the ratio. This
is not hypothetical — it is what the Swiss Re papers in this corpus do:

> "we consider two variables statistically different if the confidence intervals of Waymo's
> operations and their corresponding human baselines **do not overlap**… For the human baseline, due
> to the large sample size, we use a **normal approximation** confidence interval… For Waymo's
> operations, due to the smaller sample and exposure sizes, confidence intervals are calculated using
> the **Poisson Exact Method**"
> — *Comparative safety performance of autonomous- and human drivers* (Di Lillo et al.)

Nelson tests the ratio directly, which is the better instrument. Two papers in the corpus use the
weaker one — see [`WAYMO-UNCERTAINTY-METHODS-REPORT.md`](WAYMO-UNCERTAINTY-METHODS-REPORT.md) §3.

### vs. Wald on the log rate ratio

The textbook quick answer would be a normal approximation on the log scale:

```
log(ρ̂) ± z · sqrt(1/Y + 1/X)
```

**Zero of the 157 curated Waymo-authored papers use it.** (Scan for `Wald`, `delta method`,
`log-transformed confidence interval`: one hit, and it is 2604.03827 citing the delta method as
related work, not applying it.) Three reasons, and the third is decisive.

**1. It is undefined at Y = 0.** `log(0) = −inf` and `1/0 = inf`. The single most common cell in AV
benchmarking cannot be computed at all.

**2. Its variance is an asymptotic approximation.** `sqrt(1/Y + 1/X)` comes from the delta method —
a first-order Taylor expansion valid as counts grow. At Y = 2 there is no meaningful asymptotic
regime. 2604.03827 makes the general point about this whole family:

> "Traditional procedures for CI construction include bootstrap…, the delta method… and empirical
> likelihood…, **which all rely on large sample approximation.**"

**3. It measurably under-covers.** Monte Carlo, 40,000 replications, nominal 95%:

```
E[Y]=2,  E[X]=90     Nelson=0.986   Wald=0.829   Wald undefined in 13.4% of reps
E[Y]=5,  E[X]=50     Nelson=0.972   Wald=0.961   Wald undefined in  0.7% of reps
E[Y]=25, E[X]=900    Nelson=0.961   Wald=0.952   Wald undefined in  0.0% of reps
```

At the count regime Waymo actually operates in, a nominal 95% Wald interval delivers **83% coverage
— and fails to exist at all in one run out of seven.** Nelson never drops below nominal at any count.
By Y = 25 the two agree closely, which is the honest counterpoint: Wald is not wrong in general, it
is wrong *here*.

Note that Wald is also **narrower** than Nelson at Y = 2 (log-width 2.80 vs 3.44) — undercoverage
and narrowness are the same fact. Anyone preferring Wald because "the intervals look tighter" is
choosing an interval that is wrong 17% of the time.

### vs. bootstrap

Two distinct objections, one empirical from Waymo and one structural.

**They ran it, measured it, and rejected it.** The 7.1M-mile paper bootstrapped the benchmark counts
using the CRSS survey-design standard error:

> "**The rate ratio confidence intervals computed using the parametric bootstrap method were narrower
> than those computed using the method described in Equation 2.**… The Nelson (1970) method is more
> conservative (i.e., produces larger confidence intervals) relative to the parametric bootstrap
> method. **For this reason, the confidence intervals described in Equation 2 were used**"

Read the logic carefully: the bootstrap gave them *tighter* intervals and easier significance, and
they declined it on those grounds. That is a choice against interest.

**Bootstraps under-cover in the rare-event regime — demonstrated inside this corpus.** The
importance-sampling CI paper benchmarks the Poisson bootstrap directly and abandons it:

> "It is worth pointing out that the Poisson bootstrap CI does satisfy the monotonicity property.
> **However, it can severely under-estimate the uncertainty when the observed true positives are
> rare**"
> — 2604.03827, Remark 5

> "the coverage error for PB **can be very large and even close to 100% when true positive data is
> sparse**" · "**PB systematically undercovers**"
> — 2604.03827, §6.1 and §6.3

The structural reason: a bootstrap resamples the observed data. With Y = 2 events there are two
things to resample, so the bootstrap distribution is lumpy and degenerate, and the extreme quantiles
you need for a 95% interval are precisely the ones it estimates worst. Bootstrapping cannot
manufacture information that two observations do not contain — but an exact method built on an
assumed Poisson likelihood can, because the distributional assumption supplies the tail shape.

That trade is the real story: **Nelson buys guaranteed coverage at tiny counts by assuming the counts
are Poisson.** The bootstrap makes weaker assumptions and pays for them with coverage exactly where
it matters most.

### What choosing Nelson costs

For completeness, the case against:

- **Conservatism costs power.** Clopper–Pearson over-covers because of discreteness — 98.6% actual
  coverage at a nominal 95% in the Y = 2 row above. A real effect can fail to reach significance
  because the interval is wider than it needs to be. This cuts against Waymo's own interest, which
  is why it reads as discipline rather than as a thumb on the scale.
- **It conditions on the total N = X + Y.** Conditional inference eliminates the nuisance parameter
  cleanly, but some information about the overall event intensity is discarded. This is a standard
  and defensible choice, not a free one.
- **It assumes both counts are Poisson.** If the benchmark count comes from a complex survey — as
  CRSS does — its true variance exceeds Poisson. Waymo's own diagnostic bootstrap was built to
  measure exactly this, and its result was set aside. The Poisson assumption on `X` is the least
  examined part of the method.
- **It corrects nothing for multiplicity.** Each interval is marginal.

---

## Practical notes

**There is no standard error in this calculation, by construction.** The endpoints come from quantile
inversion, not from `estimate ± z·SE`. If asked for an SE, the answer is that the method does not
produce one. Do not back one out by halving the interval width — the interval is asymmetric.

**It assumes both counts are Poisson with known exposure.** In Waymo's application the benchmark
count `X` usually comes from a *complex survey* (CRSS), whose true standard error exceeds a Poisson
count's. They tested this: bootstrapped using the survey-design SE, obtained *narrower* intervals,
and kept Nelson because it was wider. So the survey structure is acknowledged and then deliberately
not propagated — see [`WAYMO-UNCERTAINTY-METHODS-REPORT.md`](WAYMO-UNCERTAINTY-METHODS-REPORT.md)
§2.2.

**The conservatism is real and directional.** Clopper–Pearson over-covers because of discreteness, so
at moderate-to-large counts these intervals are wider than strictly necessary. That is a feature for
the party claiming a benefit, and it is the stated reason for the choice over the bootstrap.

**It applies no multiple-comparison correction.** Each interval is marginal. Running it across many
cells (the 56.7M-mile paper's 132) inflates family-wise error, and no correction is applied — see
§2.3 and §10 of the uncertainty report.

---

## Provenance

Quotations are from the local `waymo_av_safety` corpus, transcribed from the stored markdown with
PDF ligature-extraction artifacts restored; **bold** inside quotations is mine. Equations are
transcribed from rendered LaTeX into plain notation.

The derivation in Steps 1–3 (Poisson conditioning → binomial → Clopper–Pearson → Beta-prime odds
transform) is the standard textbook justification for Nelson's method; the papers state the
resulting formula but do not derive it. The code, the equivalence check between the two routes, and
the worked examples are mine, and the illustrative counts are invented for exposition.

**The method comparison is mine, not the papers'.** Waymo states only that Nelson survives Y = 0, is
more conservative than their parametric bootstrap, and is established methodology. The Wald
comparison, the naive ratio-of-two-intervals comparison, and the Monte Carlo coverage table
(40,000 replications per row, `numpy` default_rng seed 0) are my own analysis and simulation — no
paper in the corpus reports them. The claim that `Wald` appears zero times is a `scan_corpus` result
over the 157 curated Waymo-authored papers, exhaustive for that pattern.
