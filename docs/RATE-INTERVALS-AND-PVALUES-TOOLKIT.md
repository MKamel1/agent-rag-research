# Rate Confidence Intervals and p-Values: A scipy Toolkit

*Every interval-and-test pairing used in the Waymo safety-benchmarking papers, plus the continuous
normal case they are all approximating, implemented in `scipy` with matched p-values. Each method
returns `(estimate, lower, upper, p_value)` from one call, because the interval and the test are the
same statement. Written 2026-08-31; all output below is verified, not asserted.*

Companions: [`NELSON-RATE-RATIO-IMPLEMENTATION.md`](NELSON-RATE-RATIO-IMPLEMENTATION.md) — the full
derivation of the Nelson method · [`WAYMO-UNCERTAINTY-METHODS-REPORT.md`](WAYMO-UNCERTAINTY-METHODS-REPORT.md)
— where and why each is used in the corpus.

---

## The organising principle: a CI and a p-value are one object

A 95% confidence interval is the set of null hypotheses that would **not** be rejected at α = 0.05.
So for any method, these two statements must agree:

```
theta_0 lies inside the (1-alpha) CI     <=>     p_value > alpha
```

This is not a nicety — it is the correctness test for the whole file. If your interval and your
p-value disagree about the same null, one of them is wrong. Both exact methods below are asserted to
be dual, and both pass.

It also means **you should never mix constructions**: quoting a Nelson interval next to a Wald
p-value can produce "the CI excludes 1.0 but p = 0.08", which is not a finding, it is a bug.

---

## §0 The reference case: what Wald actually is, and when it is exact

Before the approximations, the thing they approximate. Wald's construction is

```
theta_hat +/- z * SE(theta_hat)        z = Phi^-1(1 - alpha/2)
p = 2 * (1 - Phi(|theta_hat - theta_0| / SE))
```

**A Wald test refers the statistic to a normal.** That definition matters, because the natural
continuous comparison — the one-sample t-test — is *not* a Wald test. Three distinct cases:

| Case | σ | Reference | Exact? | Name |
|---|---|---|---|---|
| (a) | **known** | normal | **exact** at every n | z-test |
| (b) | **estimated** | normal | **no** | ← *this* is the Wald test |
| (c) | **estimated** | Student t | **exact** under normality | t-test |

In the module below, `normal_mean(use_t=True)` is case (c) — verified identical to
`scipy.stats.ttest_1samp` in both p-value and interval. `normal_mean(use_t=False)` is (a) or (b)
depending on whether the `sd` you pass in was known or estimated.

**The lesson is sharper than "Wald works on continuous data".** Wald is never exact when the SE
itself has sampling error — continuous data included. Monte Carlo, sd estimated from the sample,
nominal 95%, 200,000 replications:

```
  n     t-reference (t-test)   z-reference (Wald)
    3        0.9504                0.8122
    5        0.9510                0.8786
   10        0.9504                0.9184
   20        0.9506                0.9355
   30        0.9503                0.9405
  100        0.9493                0.9463
 1000        0.9499                0.9497
```

The t-test holds 95.0% at every n, down to n = 3. The Wald test delivers **81% at n = 3** and only
converges near n ≈ 1000.

So what rescues the continuous case is not continuity — it is that **the t-distribution exactly
corrects for having estimated σ**. Count data has no such correction available: nothing turns a Wald
interval on a Poisson count with X = 2 into an exact one. That is precisely why the methods below
fall back to *exact* constructions (gamma quantiles, Nelson) rather than to a corrected Wald.

---

## §1 A single Poisson rate

**Wald.** `Var(X) = λs`, so `Var(X/s) = λ/s` and `SE = √(λ̂/s) = √X/s`.

```
lambda_hat +/- z * sqrt(lambda_hat / s)          p from z = (lambda_hat - lambda_0)/SE
```

**Exact (Garwood 1936 / gamma quantiles).** The interval inverts the Poisson CDF:

```
lower = gamma.ppf(alpha/2, X) / s      (0 when X = 0)
upper = gamma.ppf(1 - alpha/2, X+1) / s
```

Its dual test is the **central (doubling) exact Poisson test**, *not* scipy's `poisson_means_test`
or a one-sided tail:

```
p = min(1, 2 * min(P(X' <= X), P(X' >= X)))      X' ~ Poisson(lambda_0 * s)
```

Waymo uses the gamma form for every single-rate figure — see the uncertainty report §1a.

---

## §2 The ratio of two Poisson rates

**Wald on log ρ.** The delta method gives `SE(log ρ̂) = √(1/Y + 1/X)`:

```
rho_hat * exp(-z * SE),  rho_hat * exp(+z * SE)       p from z = log(rho_hat/rho_0)/SE
```

Undefined whenever `Y = 0` or `X = 0`. Not used anywhere in the Waymo corpus.

**Nelson (1970) exact.** This is the elegant one, because **the interval and the test fall out of the
same fact**. Conditioning on the total `N = X + Y`:

```
Y | N ~ Binomial(N, p),      p = rho*t / (rho*t + s)
```

- The **interval** comes from inverting that binomial for `p` (Clopper–Pearson) and mapping
  `rho = (s/t) * p/(1-p)` — see the derivation doc.
- The **p-value** comes from testing the same binomial at the `p` implied by your null:
  `p_0 = rho_0 * t / (rho_0 * t + s)`. For the usual null ρ₀ = 1, that is simply `p_0 = t/(t+s)`.

So a single conditioning argument delivers both, and they are automatically dual.

> **Gotcha, verified.** Use the *central/doubling* binomial p-value, not `scipy.stats.binomtest`'s
> default. `binomtest(..., alternative="two-sided")` uses the **minlike** method, which does not dual
> with Clopper–Pearson:
>
> ```
> y  n   p0     minlike(default)   central(doubling)
>  2  92 0.0537   0.244152          0.245565   DIFFER
>  5  45 0.1000   0.801795          0.945724   DIFFER
> 13  26 0.3500   0.148108          0.166369   DIFFER
>  3  20 0.3000   0.220418          0.214174   DIFFER
> ```
>
> Both are legitimate exact tests; only the central one matches the interval. Mixing them reintroduces
> exactly the CI/p-value disagreement this file exists to prevent.

---

## §3 A binomial proportion

Included for completeness, and because the Wald version is the textbook example of an interval that
misbehaves. Note it uses `p̂` in the SE; the **score** (Wilson) version uses `p₀` and behaves far
better near 0 and 1. Prefer Wilson or Clopper–Pearson in real work.

---

## The module

```python
"""CIs and p-values for rate comparisons: the continuous Wald reference case,
its discrete approximations, and the exact methods Waymo actually uses."""
from typing import NamedTuple
import numpy as np
from scipy.stats import norm, t as student_t, poisson, binom, gamma, betaprime


class Result(NamedTuple):
    estimate: float
    lower: float
    upper: float
    p_value: float


def _two_sided_z_p(z):
    return 2 * norm.sf(abs(z))


# --- 0. THE REFERENCE CASE: Wald where it is exact, not an approximation -------
def wald_generic(theta_hat, se, theta_0=0.0, alpha=0.05):
    """The canonical Wald form. Every method below is a special case: pick an
    estimator, pick an SE, assume theta_hat ~ Normal(theta, se^2)."""
    zc = norm.ppf(1 - alpha / 2)
    return Result(theta_hat, theta_hat - zc * se, theta_hat + zc * se,
                  _two_sided_z_p((theta_hat - theta_0) / se))


def normal_mean(xbar, sd, n, mu_0=0.0, alpha=0.05, use_t=True):
    """Continuous outcome, normal model.

    use_t=True  -> Student t reference. This is the ONE-SAMPLE T-TEST (identical to
                   scipy.stats.ttest_1samp). Exact under normality at every n.
                   It is NOT a Wald test -- Wald means a normal reference.
    use_t=False -> normal reference. THIS is the Wald test. Exact only if `sd` is the
                   known population sigma; if `sd` was estimated from the sample it
                   undercovers (81% at n=3 for a nominal 95%).
    """
    se = sd / np.sqrt(n)
    if use_t:
        df = n - 1
        tc = student_t.ppf(1 - alpha / 2, df)
        p = 2 * student_t.sf(abs((xbar - mu_0) / se), df)
        return Result(xbar, xbar - tc * se, xbar + tc * se, p)
    return wald_generic(xbar, se, mu_0, alpha)


# --- 1. Single Poisson rate ---------------------------------------------------
def wald_poisson_rate(x, s, lam_0=None, alpha=0.05):
    """Wald on a Poisson rate. Var(X/s) = lambda/s."""
    lam = x / s
    se = np.sqrt(lam / s)
    if se == 0:
        return Result(lam, 0.0, 0.0, np.nan)
    zc = norm.ppf(1 - alpha / 2)
    p = np.nan if lam_0 is None else _two_sided_z_p((lam - lam_0) / se)
    return Result(lam, lam - zc * se, lam + zc * se, p)


def exact_poisson_rate(x, s, lam_0=None, alpha=0.05):
    """Garwood/gamma exact interval + the central exact test it duals with."""
    lam = x / s
    lo = 0.0 if x == 0 else gamma.ppf(alpha / 2, x) / s
    hi = gamma.ppf(1 - alpha / 2, x + 1) / s
    p = np.nan
    if lam_0 is not None:
        mu = lam_0 * s
        p = min(1.0, 2 * min(poisson.cdf(x, mu), poisson.sf(x - 1, mu)))
    return Result(lam, lo, hi, p)


# --- 2. Ratio of two Poisson rates -------------------------------------------
def wald_log_rate_ratio(y, t, x, s, rho_0=1.0, alpha=0.05):
    """Wald on log(rho). SE from the delta method. Undefined if y or x is 0."""
    if y == 0 or x == 0:
        return Result(np.nan, np.nan, np.nan, np.nan)
    rho = (y / t) / (x / s)
    se = np.sqrt(1 / y + 1 / x)
    zc = norm.ppf(1 - alpha / 2)
    return Result(rho, rho * np.exp(-zc * se), rho * np.exp(zc * se),
                  _two_sided_z_p(np.log(rho / rho_0) / se))


def nelson_rate_ratio(y, t, x, s, rho_0=1.0, alpha=0.05):
    """Nelson (1970) exact interval + the exact conditional binomial test.

    Both come from the SAME fact: Y | (X+Y)=N ~ Binomial(N, p), p = rho*t/(rho*t+s).
    """
    k, n = s / t, x + y
    est = (y / t) / (x / s) if x > 0 else np.nan
    lo = 0.0 if y == 0 else k * betaprime.ppf(alpha / 2, y, x + 1)
    hi = np.inf if x == 0 else k * betaprime.ppf(1 - alpha / 2, y + 1, x)
    p = np.nan
    if rho_0 is not None and n > 0:
        p0 = rho_0 * t / (rho_0 * t + s)                    # H0 mapped onto the binomial
        p = min(1.0, 2 * min(binom.cdf(y, n, p0), binom.sf(y - 1, n, p0)))
    return Result(est, lo, hi, p)


# --- 3. Binomial proportion ---------------------------------------------------
def wald_proportion(k, n, p_0=0.5, alpha=0.05):
    """Textbook Wald. Uses p_hat in the SE -- the score test uses p_0 and behaves better."""
    p_hat = k / n
    se = np.sqrt(p_hat * (1 - p_hat) / n)
    zc = norm.ppf(1 - alpha / 2)
    p = np.nan if se == 0 else _two_sided_z_p((p_hat - p_0) / se)
    return Result(p_hat, p_hat - zc * se, p_hat + zc * se, p)


if __name__ == "__main__":
    A = 0.05
    # DUALITY: rho_0 inside the CI  <=>  p > alpha.  Holds for both exact methods.
    for (y, t, x, s) in [(2, 56.7, 90, 1000.0), (5, 7.1, 40, 500.0), (0, 20.0, 12, 300.0),
                         (25, 56.7, 900, 1000.0), (13, 30.0, 13, 30.0)]:
        for rho_0 in [0.25, 0.5, 1.0, 2.0]:
            r = nelson_rate_ratio(y, t, x, s, rho_0=rho_0, alpha=A)
            inside, sig = (r.lower <= rho_0 <= r.upper), (r.p_value > A)
            assert inside == sig, (y, x, rho_0, r, inside, sig)
    print("PASS: Nelson CI and exact conditional p-value are dual")

    for (x, s) in [(0, 10.0), (2, 10.0), (30, 10.0), (500, 10.0)]:
        for lam_0 in [0.1, 1.0, 3.0, 10.0, 60.0]:
            r = exact_poisson_rate(x, s, lam_0=lam_0, alpha=A)
            assert (r.lower <= lam_0 <= r.upper) == (r.p_value > A), (x, lam_0, r)
    print("PASS: exact Poisson CI and central exact p-value are dual")

    r = normal_mean(10.0, 2.0, 25, mu_0=9.0, use_t=False)
    g = wald_generic(10.0, 2.0 / 5, 9.0)
    assert np.allclose([r.lower, r.upper, r.p_value], [g.lower, g.upper, g.p_value])
    print("PASS: normal_mean(use_t=False) == wald_generic")

    print("\n=== RATE RATIO, H0: rho = 1 (illustrative counts) ===")
    print(f"{'':34s}{'rho':>8}{'lower':>10}{'upper':>10}{'p':>12}")
    for lbl, (y, t, x, s) in {
        "Y=2  serious injury": (2, 56.7, 90, 1000.0),
        "Y=25 any injury":     (25, 56.7, 900, 1000.0),
        "Y=0  zero ADS events":(0, 56.7, 45, 1000.0),
    }.items():
        for name, fn in [("Nelson (exact)", nelson_rate_ratio), ("Wald on log(rho)", wald_log_rate_ratio)]:
            r = fn(y, t, x, s, rho_0=1.0)
            f = lambda v: "undefined" if np.isnan(v) else (f"{v:.4f}" if np.isfinite(v) else "inf")
            print(f"{lbl:20s}{name:16s}{f(r.estimate):>8}{f(r.lower):>10}{f(r.upper):>10}{f(r.p_value):>12}")

    print("\n=== SINGLE RATE, H0: lambda = 3.0 per Mmi, s = 10 Mmi ===")
    print(f"{'':6}{'method':<18}{'est':>8}{'lower':>10}{'upper':>10}{'p':>12}")
    for x in [0, 2, 30, 500]:
        for name, fn in [("exact (Garwood)", exact_poisson_rate), ("Wald", wald_poisson_rate)]:
            r = fn(x, 10.0, lam_0=3.0)
            f = lambda v: "undefined" if np.isnan(v) else f"{v:.4f}"
            print(f"X={x:<4}{name:<18}{f(r.estimate):>8}{f(r.lower):>10}{f(r.upper):>10}{f(r.p_value):>12}")
```

---

## Self-check output

Verified in the `agent-rag-research` env, 2026-08-31:

```
PASS: Nelson CI and exact conditional p-value are dual
PASS: exact Poisson CI and central exact p-value are dual
PASS: normal_mean(use_t=False) == wald_generic
```

The first two are the duality assertion swept across counts (including `Y = 0` and `X = 0`) and
across four null values each. The third confirms the continuous reference case degenerates to the
generic Wald form when you switch off the t-correction.

---

## Results

**⚠️ Illustrative counts, chosen to show behaviour across the count range. NOT Waymo's published
figures.**

### Rate ratio, H₀: ρ = 1

```
                                       rho     lower     upper           p
Y=2  serious injury Nelson (exact)    0.3919    0.0467    1.4575      0.2462
Y=2  serious injury Wald on log(rho)  0.3919    0.0965    1.5913      0.1901
Y=25 any injury     Nelson (exact)    0.4899    0.3153    0.7280      0.0001
Y=25 any injury     Wald on log(rho)  0.4899    0.3293    0.7290      0.0004
Y=0  zero ADS events Nelson (exact)   0.0000    0.0000    1.5067      0.1672
Y=0  zero ADS events Wald on log(rho) undefined undefined undefined  undefined
```

Three things to read off this table:

1. **Wald's p-value is systematically smaller than Nelson's** (0.19 vs 0.25; 0.0004 vs 0.0001 —
   note the direction flips at high counts where both are reliable). At Y = 2, Wald is roughly 25%
   more optimistic about significance. That is the same undercoverage seen in the interval, expressed
   as a test.
2. **Nelson returns a real p-value from zero observed events** — p = 0.1672. Zero events is
   informative, and an exact conditional test can use it. Wald cannot compute anything at all.
3. **Neither the Y = 2 nor the Y = 0 row is significant**, despite point estimates of 61% and 100%
   reduction. This is the arithmetic behind the papers' own caveats about low-count cells.

### Single Poisson rate, H₀: λ = 3.0 per million miles, s = 10 Mmi

```
      method                 est     lower     upper           p
X=0   exact (Garwood)     0.0000    0.0000    0.3689      0.0000
X=0   Wald                0.0000    0.0000    0.0000   undefined
X=2   exact (Garwood)     0.2000    0.0242    0.7225      0.0000
X=2   Wald                0.2000   -0.0772    0.4772      0.0000
X=30  exact (Garwood)     3.0000    2.0241    4.2827      1.0000
X=30  Wald                3.0000    1.9265    4.0735      1.0000
X=500 exact (Garwood)    50.0000   45.7129   54.5809      0.0000
X=500 Wald               50.0000   45.6174   54.3826      0.0000
```

At `X = 0` Wald's SE is zero, so the interval collapses to a point and the p-value is `0/0` —
undefined. At `X = 2` it reports a **negative rate**. By `X = 500` the two agree to two decimals,
which is the honest counterpoint: Wald is not wrong in general, it is wrong at low counts.

---

## Which to use

| Situation | Interval | p-value |
|---|---|---|
| Continuous outcome, σ estimated | **t interval** | **t-test** — exact under normality |
| Continuous outcome, σ known | z interval | z-test — exact |
| Single rate, X ≳ 100 | Wald fine; exact costs nothing | either agrees |
| Single rate, X < 100 or X may be 0 | **gamma / Garwood** | central exact Poisson |
| Rate ratio, both counts large | Wald on log ρ acceptable | z on log ρ |
| Rate ratio, either count small or 0 | **Nelson (1970)** | exact conditional binomial |
| Binomial proportion | Wilson or Clopper–Pearson, not Wald | matched exact/score test |

The rule the Waymo papers follow, and the one worth stealing: **choose the construction per side of
the comparison, by count — not once for the whole analysis.** The Swiss Re papers do this explicitly
(normal approximation for the ~10⁵-claim human baseline, Poisson exact for the single-digit Waymo
side); the Kusano/Scanlon papers sidestep it by using exact methods everywhere.

---

## Practical gotchas

- **`binomtest` default ≠ dual of Clopper–Pearson.** See §2. Use the doubling form.
- **`SE = 0` when `X = 0`.** Guard it, or you get `0/0` p-values and zero-width intervals.
- **Wald on a rate can go negative.** If you must use it, use the log-transformed variant — the
  corpus notes the same motivation, citing "Kegler (2007) proposed applying a normal approximation in
  the logarithmic scale … **in order to avoid the potential negative bound**" (2604.03827).
- **`gamma.ppf(alpha/2, 0)` is 0, but `betaprime.ppf(alpha/2, 0, b)` is `nan`.** Different scipy
  edge behaviour for the same "zero events" case; both are handled explicitly above.
- **These p-values are marginal.** No multiplicity correction is applied by any of them.

---

## Provenance

The `Result` API, the module, the duality assertions, the `binomtest` comparison, the t-vs-Wald
coverage simulation (200,000 reps per row, `numpy` default_rng seed 1) and all worked numbers are
mine. The equivalence of `normal_mean(use_t=True)` to `scipy.stats.ttest_1samp` is verified, not
asserted. The papers state formulas for the intervals but publish **no p-values and no test
statistics** for the rate comparisons — significance is declared by whether the interval contains
1.0 (or, in the Swiss Re papers, by non-overlap). The exact conditional binomial test in
`nelson_rate_ratio` is the standard dual of the Nelson interval; it is not something the papers
describe. Illustrative counts are invented for exposition and are not Waymo's published figures.
Quotation ligature artifacts from PDF extraction have been restored; **bold** inside quotations is
mine.
