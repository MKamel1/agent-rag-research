# Bootstrap Variants: One Skeleton, One Swappable Line

*Eight bootstrap variants plus four interval rules, as a single memorisable pattern. Learning
reference — no functions, no library. Written 2026-08-31.*

Companion: [`WAYMO-UNCERTAINTY-METHODS-REPORT.md`](WAYMO-UNCERTAINTY-METHODS-REPORT.md) §4, which
documents where each of these appears in the Waymo safety papers.

---

## The one idea

**Every bootstrap is: reweight the data, recompute the statistic, repeat, build an interval.**

```
STEP 0    prepare data                        <-- CLUSTER and BLOCK change this
STEP 1    for b in 1..B:                       (B = 1000 ... 10000)
STEP 2        w = <<<< AXIS 1: HOW YOU RESAMPLE >>>>
STEP 3        theta_b = statistic(data, weights = w)
STEP 4    CI  = <<<< AXIS 2: HOW YOU BUILD THE INTERVAL >>>>
```

**There are two independent axes, not one.** Most people learn Axis 1 and assume STEP 4 is always
"take percentiles". It isn't, and the choice matters as much as the resampling scheme — see
[STEP 4](#step-4--turning-the-replicates-into-an-interval) below. You can pair any Axis-1 line with
any Axis-2 rule.

**The unifying fact for Axis 1:** every weight scheme below has **mean 1 and variance ≈ 1** (verified:
multinomial 1.00/0.93, Poisson 0.95/0.90, exponential 1.03/1.08, Bayesian 1.00/1.05 at n=1000). They
differ only in whether the weights are *constrained to sum to n* and whether they are *integer or
continuous*. **The one exception is the wild bootstrap** — mean **0**, variance 1, because it
multiplies *residuals*, not observations.

---

## Axis 1 — the lines

```python
import numpy as np
rng = np.random.default_rng(0)
n = len(data)

# ================= THE CORE FOUR (memorise these first) =================

# ---------------------------------------------------------------- STANDARD
w = rng.multinomial(n, np.full(n, 1 / n))          # integer, SUM IS EXACTLY n
#   equivalently, the familiar index form:
idx = rng.integers(0, n, size=n); sample = data[idx]

# ---------------------------------------------------------------- POISSON
w = rng.poisson(1.0, size=n)                       # integer, sum is RANDOM (~n)

# ---------------------------------------------------------------- EXPONENTIAL
w = rng.exponential(1.0, size=n)                   # continuous > 0 -- LITERALLY the one-word swap
#   ...but Waymo's EB is a RATE estimator, not a reweighting -- it uses n+1 draws:
w = rng.exponential(1.0, size=n + 1)               # see "n+1" note below

# ---------------------------------------------------------------- CLUSTER
# (STEP 0 change -- group first, then resample GROUP ids, not rows)
g = rng.integers(0, n_clusters, size=n_clusters)

# ================= THE NEXT FOUR (know they exist) ======================

# ---------------------------------------------------------------- BLOCK  (time series)
# (STEP 0 change -- pick block length L, then resample START positions)
starts = rng.integers(0, n - L + 1, size=n // L)                 # moving block
boot   = np.concatenate([data[s:s + L] for s in starts])
#   circular variant -- wraps, so end points aren't underweighted:
starts = rng.integers(0, n, size=n // L)
boot   = np.concatenate([np.take(data, range(s, s + L), mode="wrap") for s in starts])

# ---------------------------------------------------------------- STRATIFIED
# opposite of cluster: resample WITHIN each group, preserving each group's size
boot = np.concatenate([rng.choice(data[strata == k], size=(strata == k).sum(), replace=True)
                       for k in np.unique(strata)])

# ---------------------------------------------------------------- PARAMETRIC
theta_hat = fit(data)                              # fit a model FIRST
boot = simulate_from(theta_hat, size=n)            # then resample from the MODEL, not the data

# ---------------------------------------------------------------- BAYESIAN (Rubin)
w = n * rng.dirichlet(np.ones(n))                  # continuous, sums to n, never 0

# ---------------------------------------------------------------- WILD  (regression residuals)
v = rng.choice([-1.0, 1.0], size=n)                # Rademacher: mean 0, var 1
y_boot = fitted + v * residuals                    # multiplies RESIDUALS, not observations
```

Everything below is the *why*.

---

## STEP 0 — data prep (CLUSTER and BLOCK change this)

For standard / Poisson / exponential / Bayesian, `data` is a flat array of `n` independent observations. Nothing
to do.

**For the cluster bootstrap, the data must be grouped first**, and the grouping key is whatever unit
the dependence lives at:

```
BEFORE (wrong -- rows are not independent)
    row_id   cluster_id   value
    1        A            3.2
    2        A            3.4        <-- these three are correlated
    3        A            2.9
    4        B            7.1
    5        B            6.8
    6        C            1.0

AFTER (group into a list of blocks, keep each block WHOLE)
    clusters = [
        [3.2, 3.4, 2.9],     # A
        [7.1, 6.8],          # B
        [1.0],               # C
    ]
    n_clusters = 3           <-- this, not 6, is your effective sample size
```

Then resample **whole clusters, with replacement**, and concatenate:

```python
g = rng.integers(0, n_clusters, size=n_clusters)   # e.g. [2, 0, 0] -> C, A, A
boot = np.concatenate([clusters[i] for i in g])    # keep every row of a chosen cluster
```

Three things to burn in:

1. **You resample the group index, not the row index.** Rows never move independently.
2. **Clusters may be different sizes**, so `len(boot)` varies between replications. That is correct,
   not a bug.
3. **`n_clusters` is your real sample size.** 10,000 rows in 12 clusters gives you roughly the
   precision of 12 observations, not 10,000. If `n_clusters` is small (< ~30) the bootstrap is
   unreliable and you want a different method.

Typical cluster keys: intersection / site, driver or vehicle, day, geographic cell, patient.

**For the block bootstrap, the "grouping" is positional instead of categorical.** The dependence is
in *time order*, so you cut the series into contiguous runs of length `L` and resample the runs:

```
series:   x1 x2 x3 x4 x5 x6 x7 x8 x9 x10 x11 x12       L = 4
blocks:  [x1..x4] [x2..x5] [x3..x6] ...                 <-- OVERLAPPING (moving block)
resample 3 block starts -> concatenate -> length 12
```

- **`L` is the only knob**, and it is the same trade as everywhere: too short destroys the dependence
  you are preserving, too long leaves too few blocks. `L ~ n^(1/3)` is the usual starting point.
- **Moving** = overlapping blocks. **Circular** = wraps around the end (`mode="wrap"`), which fixes
  the moving block's underweighting of the first and last few points. **Stationary**
  (Politis–Romano) = random geometric `L`, which keeps the resampled series stationary.
- **Cluster vs block vs stratified — do not confuse them.** Cluster: resample *whole groups*, groups
  are categorical. Block: resample *contiguous runs*, dependence is positional. Stratified: resample
  *within* groups, preserving each group's size, because you want the strata proportions fixed.

---

## Why each line looks like that

### Standard (nonparametric / multinomial) bootstrap

```python
w = rng.multinomial(n, np.full(n, 1 / n))
```

Drawing `n` indices with replacement **is** drawing multinomial counts — observation `i` appears
`w_i` times. The index form and the weight form are the same procedure.

- Weight marginal: `Binomial(n, 1/n)` → mean 1, variance `1 − 1/n` ≈ 1
- **Constraint: `sum(w) == n` exactly.** The weights are negatively correlated — if one goes up,
  another must come down.
- Needs `n` known up front and all data in memory.

### Poisson bootstrap

```python
w = rng.poisson(1.0, size=n)
```

**Drop the sum-to-n constraint** and let each weight be independent. As `n → ∞` the multinomial
counts converge to independent `Poisson(1)`, so this is the large-`n` limit of the standard
bootstrap. The corpus states the lineage directly:

> "the **Poisson bootstrap** (PB) for CP proposed by Bohm and Zech (2014); see **Chamandy et al.
> (2012)** and references therein which **derived the same Poisson bootstrap but as a variation of
> the standard multinomial bootstrap**."
> — *Confidence Intervals for Rate Estimation with Importance Sampling in AV Evaluation* (2604.03827)

- Weight: `Poisson(1)` → mean 1, variance 1
- **`sum(w)` is random**, ≈ n ± √n
- **Why anyone bothers:** independence makes it *streamable and embarrassingly parallel*. You can
  assign each record its B weights the moment you see it, without knowing `n` or holding the dataset.
  That is why it is the standard bootstrap at Google scale — and it is what Waymo's *Dynamic
  Benchmarks* paper uses: "a random number from a Poisson distribution with mean 1 (λ = 1) is
  generated for each crash event".
- ~37% of weights are 0 (`P(Poisson(1) = 0) = e⁻¹`), same as the standard bootstrap's out-of-bag rate.

### Exponential bootstrap — two different things share this name

**(a) The generic exponential-weight bootstrap is literally a one-word swap.**

```python
w = rng.poisson(1.0, size=n)          ->    w = rng.exponential(1.0, size=n)
```

Same data, same statistic, near-identical answers — both are mean-1, variance-1 weight schemes and
the difference is second order. Verified on the same 200-point sample:

```
WEIGHTED MEAN     poisson       CI=[2.5969, 3.1414]  sd=0.13984
                  exponential   CI=[2.6027, 3.1517]  sd=0.13930
                  bayesian      CI=[2.6027, 3.1517]  sd=0.13930   <- IDENTICAL to exponential
WEIGHTED SUM      poisson       CI=[478.4, 671.7]    sd=49.276
                  exponential   CI=[483.3, 675.1]    sd=49.134
```

**And note the third row: for a weighted *mean*, the exponential-weight bootstrap IS the Bayesian
bootstrap.** Not approximately — identically. `np.average` normalises the weights, and normalised
`Exp(1)` draws *are* `Dirichlet(1,…,1)`. Two names, one object.

**(b) Waymo's EB (`2604.03827`) is not that.** It is a specific estimator for a **rate under
importance sampling**, and the difference is the estimand, not the weight distribution:

| | generic exponential-weight | Waymo's EB |
|---|---|---|
| Estimand | mean of a fixed sample | **rate** = Σwᵢ / exposure |
| Sample size | fixed at `n` | **random** (compound Poisson — you sample, then review, to find events) |
| Draws | `n` | **`n+1`** |
| Same as | Bayesian bootstrap | nothing standard |

> "As the distribution of W tends towards a continuous distribution, intuitively each X_k becomes
> either 0 or 1. **Since the distribution of Gamma(shape = 1, rate = 1) is the same as
> Exponential(1)**, it is natural to construct a CI as follow[s]… where **e_i, i = 1, …, n+1, are
> i.i.d. Exponential(1)**"
> — 2604.03827 §5.3

**Why `n+1`, concretely.** When `n` is fixed you only need to capture *which* observations you got.
When the event count is itself random, you must also capture *how many* — the extra draw reserves
mass for an event that could have occurred but was not sampled.

**Where the extra draw comes from: `Exp(1)` draws are inter-arrival times.**

That is the fact that makes `n+1` inevitable rather than arbitrary. If events arrive as a rate-1
Poisson process, the gaps between arrivals are `Exp(1)`. So:

```
e_1 + e_2 + ... + e_n         = time of the n-th arrival        ~ Gamma(n, 1)
e_1 + ... + e_n + e_{n+1}     = time of the (n+1)-th arrival    ~ Gamma(n+1, 1)
```

Now read the two bounds as questions:

| bound | the question it answers | what it needs |
|---|---|---|
| **lower** | "I saw `n` events — how *small* could the rate be?" | time to the **n-th** arrival |
| **upper** | "how *large* could the rate be and I'd still have seen only `n`?" | time to the **(n+1)-th** arrival — the next event that **hadn't happened yet** |

The upper bound is a statement about an event you did **not** observe, so it needs a draw that is not
attached to any observed event. That is the `(n+1)`-th.

**Why you cannot just use `size=n`.** Each `e_i` *scales an event you actually found*. With five found
events you have five knobs, and no setting of those five knobs expresses "there might have been a
sixth." The sixth event is not in your data, so it needs its own slot. Verified — using `n` draws for
the upper bound falls short by:

```
  X    upper from n draws   correct (n+1)   shortfall
  1               0.36935         0.55716       33.7%
  2               0.55657         0.72247       23.0%
  5               1.02389         1.16683       12.3%
 20               2.96757         3.08884        3.9%
```

**Proof that `n+1` is the right number, not a fudge:** set every weight to 1 and EB must collapse onto
the textbook exact Poisson (Garwood) interval — and it does, to Monte Carlo error:

```
  X    EB lower (n draws)   Garwood lower     EB upper (n+1)   Garwood upper
  1               0.00252         0.00253            0.55831         0.55716
  2               0.02407         0.02422            0.72330         0.72247
  5               0.16247         0.16235            1.16645         1.16683
 20               1.22243         1.22165            3.09063         3.08884
```

`gamma.ppf(alpha/2, X)` for the lower limit and `gamma.ppf(1-alpha/2, X+1)` for the upper — the same
`X` vs `X+1` split, for the same reason. **EB is the weighted generalisation of Garwood**, and `w**`
is what the unobserved event would have been worth. When weights are all 1, `w** = 1` and the two
methods are the same thing.

> **The extra draw enters the UPPER bound only.** This is the part that is easy to get wrong. The
> paper specifies two *different* replicate statistics:
>
> ```
> theta_L^(b) = sum_i w_i e_i                 <- n draws       -> alpha/2 quantile = LOWER bound
> theta_U^(b) = theta_L^(b) + w** e_{n+1}     <- the (n+1)th   -> 1-alpha/2 quantile = UPPER bound
> ```
>
> — `2604.03827:b75-b76` and Table 2: "q_{α/2}(Σ wᵢeᵢ) **for the lower bound**" ·
> "q_{1−α/2}(Σ wᵢeᵢ + w\*\* e_{n+1}) **for the upper bound**".
>
> **This is not a percentile interval.** The two bounds come from two different (coupled) statistics,
> which is why you cannot just append `w**` to the weight vector and take both quantiles from one
> sequence. Doing that inflates the lower bound too — by **2.75x at n=2** in the table below.
>
> It mirrors Garwood exactly: `gamma.ppf(α/2, X)` for the lower limit, `gamma.ppf(1−α/2, X+1)` for
> the upper. The `+1` lives only in the upper limit in both methods, and for the same reason.

Correct implementation, vectorised:

```python
M  = rng.exponential(1.0, size=(B, n + 1))
tL = M[:, :n] @ iw / exposure                      # lower-bound replicates
tU = tL + w_next * M[:, n] / exposure              # upper-bound replicates
lo, hi = np.percentile(tL, 100*alpha/2), np.percentile(tU, 100*(1 - alpha/2))
```

Verified, weighted-rate estimator, exposure = 56.7, `w_next = max(iw)`:

```
  n               poisson          WRONG (one sequence)        CORRECT EB
  2      [ 0.000,  4.085]      [ 0.505,  6.046]        [ 0.184,  6.046]
  5      [ 0.647,  7.838]      [ 1.668, 10.697]        [ 1.048, 10.697]
 20      [ 5.752, 16.962]      [ 7.001, 19.415]        [ 6.156, 19.415]
100      [52.859, 85.951]      [55.736, 90.751]        [53.614, 90.751]

lower bound overstated by the wrong version:  n=2 2.75x · n=5 1.59x · n=20 1.14x · n=100 1.04x
```

Two things to read off it:

1. **Poisson and exponential at the same `n` are interchangeable.** The reweighting really is a
   one-word swap; everything distinctive about EB is the `n+1` term and where it is applied.
2. **The `n+1` widens the interval upward only, and the effect decays with `n`.** Note the Poisson
   lower bound of **0.000 at n=2**: all-zero weights are possible, so PB's interval collapses. That
   is its documented undercoverage, visible in one line of output — and EB fixes it at the top, not
   by propping up the bottom.

Also relevant: `w**` is not a free parameter. The paper derives a data-driven choice, because the
theoretical maximum weight "would make the EB **upper bound** too conservative to be useful"
(`b80`) — further confirmation that `w**` governs the upper limit alone.

- Weight: `Exp(1)` → mean 1, variance 1, **always strictly positive** (no observation is ever dropped)

### Cluster bootstrap

The weight line is unchanged — you can use *any* of the three above. What changes is **what gets
weighted**: clusters, not rows. See STEP 0.

Mentally: `w = rng.poisson(1.0, size=n_clusters)`, then observation `i` inherits its cluster's weight.

---

## STEP 4 — turning the replicates into an interval

**This is the axis people forget.** You have `{theta_1 ... theta_B}`; four standard ways to get a CI:

```python
# ------------------------------------------------- PERCENTILE  (the default)
lo, hi = np.percentile(theta_b, [100*alpha/2, 100*(1-alpha/2)])

# ------------------------------------------------- BASIC / reverse percentile
lo, hi = 2*theta_hat - np.percentile(theta_b, 100*(1-alpha/2)), \
         2*theta_hat - np.percentile(theta_b, 100*alpha/2)

# ------------------------------------------------- STUDENTIZED / bootstrap-t
# needs an SE per replicate:  t_b = (theta_b - theta_hat) / se_b
lo, hi = theta_hat - np.percentile(t_b, 100*(1-alpha/2))*se_hat, \
         theta_hat - np.percentile(t_b, 100*alpha/2)*se_hat

# ------------------------------------------------- BCa
# z0 = norm.ppf(mean(theta_b < theta_hat))            <- bias correction
# a  = skewness of the JACKKNIFE leave-one-out values <- acceleration
# then take adjusted percentiles instead of alpha/2, 1-alpha/2
from scipy.stats import bootstrap          # scipy does this for you:
# bootstrap((data,), statistic, method="BCa", confidence_level=0.95)
```

| Rule | Corrects for | Cost | Use when |
|---|---|---|---|
| **Percentile** | nothing | free | statistic ~symmetric and ~unbiased |
| **Basic** | a shifted bootstrap distribution | free | replicate distribution is off-centre |
| **Studentized** | scale variation; best coverage | needs an SE *per replicate* (often a nested bootstrap) | an SE is cheap to compute |
| **BCa** | median bias (`z0`) **and** skewness (`a`) | one jackknife pass | **skewed statistics — rates, ratios, variances** |

**Memorise the trigger:** if the statistic is **skewed or bounded** (a rate is bounded below at 0, a
ratio is bounded below at 0), percentile is mis-centred and **BCa is the right default**. Crash rates
are exactly this case — and the Waymo papers use percentile only.

---

## Side by side

| | Standard | Poisson | Exponential | Cluster |
|---|---|---|---|---|
| **The line** | `rng.multinomial(n, 1/n)` | `rng.poisson(1, n)` | `rng.exponential(1, n+1)` | resample group ids |
| Weight support | integers ≥ 0 | integers ≥ 0 | continuous > 0 | inherits |
| Mean / variance | 1 / ≈1 | 1 / 1 | 1 / 1 | inherits |
| `sum(w)` | **exactly n** | random ≈ n | random | random |
| Weights independent? | no (sum fixed) | **yes** | **yes** | across clusters only |
| Drops observations? | ~37% | ~37% | **never** | drops whole clusters |
| Streamable / parallel | no | **yes** | yes | no |
| Best at | general use | huge n, distributed | **rare events, sparse data** | **correlated data** |

> The Exponential column above describes **Waymo's EB** (`n+1`, rate estimand). As a *generic
> reweighting* (`size=n`), exponential is interchangeable with Poisson and identical to Bayesian —
> see [Why each line looks like that](#exponential-bootstrap--two-different-things-share-this-name).

Plus the second four:

| | Block | Stratified | Parametric | Bayesian | Wild |
|---|---|---|---|---|---|
| **The change** | resample block starts | resample within strata | simulate from a fitted model | `n*rng.dirichlet(ones(n))` | `rng.choice([-1,1], n)` on residuals |
| Preserves | serial dependence | strata proportions | the model's shape | — | conditional heteroskedasticity |
| Knob | block length `L` | none | the model itself | none | Rademacher vs Mammen weights |
| Weight mean/var | — | — | — | 1 / ≈1 | **0 / 1** |
| Watch out | `L` choice; too few blocks | not a fix for clustering | **wrong if the model is wrong** | never drops a point | regression only |
| Best at | **time series** | fixed design proportions | small n **with** a trusted model | smooth weights | **few clusters**, heteroskedastic errors |

---

## Choosing, in one pass

```
AXIS 1 -- how to resample
    Is the dependence in TIME ORDER (a series)?
        YES -> BLOCK bootstrap. Pick L. Circular if the ends matter.
    Is the dependence in GROUPS (repeat sites, days, vehicles, drivers)?
        YES -> CLUSTER bootstrap. n_clusters is your real sample size.
               (few clusters, and it's a regression? -> WILD CLUSTER)
    Are the events RARE (single-digit counts)?
        YES -> EXPONENTIAL bootstrap -- or skip bootstrapping, use an exact method
    Is the data huge / streaming / distributed?
        YES -> POISSON bootstrap
    Do you trust a parametric model more than the empirical distribution?
        YES -> PARAMETRIC bootstrap
    Otherwise                     -> STANDARD bootstrap

AXIS 2 -- how to build the interval
    Statistic skewed or bounded (rates, ratios, variances)?   -> BCa
    Cheap SE available per replicate?                          -> STUDENTIZED
    Bootstrap distribution visibly off-centre?                 -> BASIC
    Otherwise                                                  -> PERCENTILE
```

---

## Gotchas

- **Bootstrapping cannot rescue tiny n.** With 2 observed events there are 2 things to resample; the
  extreme quantiles a 95% interval needs are exactly the ones estimated worst. At single-digit counts
  prefer an exact method (gamma quantiles for a rate, Nelson for a rate ratio) — see
  [`RATE-INTERVALS-AND-PVALUES-TOOLKIT.md`](RATE-INTERVALS-AND-PVALUES-TOOLKIT.md).
- **Ignoring clustering makes intervals too narrow.** This is the single most common bootstrap error:
  resampling rows when the rows are correlated understates variance, and the answer looks *more*
  precise than it is.
- **Percentile CI is the default, not the best.** BCa corrects for bias and skewness; the percentile
  interval is fine for roughly symmetric statistics — see STEP 4.
- **Fix the seed** and report B. B = 1000 for exploration, 10,000 for anything published — Monte
  Carlo error in the tail quantiles scales as 1/√B.
- **Recompute the *whole* pipeline inside the loop.** If a step (threshold selection, model
  selection, imputation) was fitted on the data, it must be refitted on each resample or the interval
  will be too narrow.
- **Weights must actually be used by your statistic.** `np.average(x, weights=w)` respects them;
  `np.mean(x)` silently does not.

---

## Deliberately not here

- **m-out-of-n bootstrap / subsampling** — the fix for cases where the bootstrap is *inconsistent*
  rather than merely inefficient (the sample maximum and other extremes, boundary parameters). Worth
  knowing it exists; rarely worth implementing. It is why the EVT literature fits a parametric tail
  instead of bootstrapping extremes.
- **Bag of Little Bootstraps (BLB)** — subsample, bootstrap each subsample, average. For distributed
  data. The Poisson bootstrap already solves that problem more simply.
- **Smoothed bootstrap, .632/.632+** — the latter is a cross-validation estimator, not an inference
  tool.
- **Double / iterated bootstrap** — calibrates an interval by bootstrapping the bootstrap. `B²` cost.

---

---

## End to end — every variant as a complete program

Each block below is **self-contained and verified by execution** (2026-08-31, `agent-rag-research`
env). Same shape every time: build data → loop `B` times → resample → recompute → interval. Only the
marked line changes.

Shared preamble for all nine:

```python
import numpy as np
from scipy.stats import norm, bootstrap
B, ALPHA = 2000, 0.05
def pct(tb, a=ALPHA): return tuple(np.percentile(tb, [100*a/2, 100*(1-a/2)]))
```

### 1. Standard — the baseline everything else is measured against

```python
# ============================================================ 1. STANDARD
rng = np.random.default_rng(0)
data = rng.gamma(2.0, 1.5, size=200)                       # skewed, like a rate
theta_hat = data.mean()
tb = np.empty(B)
for b in range(B):
    idx = rng.integers(0, len(data), size=len(data))       # <-- THE LINE
    tb[b] = data[idx].mean()
print(f"1 STANDARD      mean={theta_hat:.4f}  CI={pct(tb)[0]:.4f},{pct(tb)[1]:.4f}")
```

**Output:** `mean=2.8638  CI=[2.5864, 3.1619]`

### 2. Poisson — same answer, but each weight is independent

```python
# ============================================================ 2. POISSON
rng = np.random.default_rng(0)
tb = np.empty(B)
for b in range(B):
    w = rng.poisson(1.0, size=len(data))                   # <-- THE LINE
    tb[b] = np.average(data, weights=w) if w.sum() else np.nan
print(f"2 POISSON       mean={theta_hat:.4f}  CI={pct(tb[~np.isnan(tb)])[0]:.4f},{pct(tb[~np.isnan(tb)])[1]:.4f}")
```

**Output:** `mean=2.8638  CI=[2.5994, 3.1656]`

Practically identical to the standard bootstrap at n=200, which is the point: it is the large-`n` limit. What you gain is that `w` can be drawn the moment a record arrives, without knowing `n`. Guard `w.sum() == 0`, which the constrained multinomial can never produce.

### 3. Exponential — (a) the one-word swap, (b) Waymo's rate estimator

```python
# ============================================================ 3. EXPONENTIAL (weighted rate)
rng = np.random.default_rng(0)
iw = np.array([12.0, 40.0, 7.5, 100.0, 25.0])              # importance weights of 5 found events
miles = 56.7
w_next = iw.max()                                          # illustrative "next weight"
theta_hat_r = iw.sum() / miles
n = len(iw)
M  = rng.exponential(1.0, size=(B, n + 1))                 # <-- THE LINE (n+1 draws)
tL = M[:, :n] @ iw / miles                                 # LOWER-bound replicates: n draws
tU = tL + w_next * M[:, n] / miles                         # UPPER-bound replicates: + the (n+1)th
lo = np.percentile(tL, 100*ALPHA/2)                        # lower from tL
hi = np.percentile(tU, 100*(1 - ALPHA/2))                  # upper from tU
print(f"3 EXPONENTIAL   rate={theta_hat_r:.4f}  CI={lo:.4f},{hi:.4f}")
```

**Output:** `rate=3.2540  CI=[0.7490, 11.4818]`

**(a) first — the generic swap, which is what most people mean by "exponential bootstrap":**

```python
# identical to block 2 except for ONE WORD
for b in range(B):
    w = rng.exponential(1.0, size=len(data))       # <-- poisson -> exponential
    tb[b] = np.average(data, weights=w)
# CI=[2.6027, 3.1517]   vs Poisson's [2.5969, 3.1414] -- interchangeable
# and identical to the Bayesian bootstrap, because np.average normalises Exp(1) -> Dirichlet(1)
```

**(b) the block above is Waymo's EB, which is a different animal** — the estimand is a rate whose
event count is random, hence `n+1` draws and no normalisation. Do not describe (a) and (b) as the
same method in a methods section.

Note the shape of the problem: five *found* events carrying importance weights, not five raw
observations. The interval is wildly asymmetric because five events is almost no information — which
is honest.

#### Reading that code: what `@` does, and why the two lines look different

**Start with the plain-loop version.** It does exactly the same thing and there is no `@` in it:

```python
for b in range(B):
    e = rng.exponential(1.0, size=n + 1)          # n+1 random numbers
    lower_b = sum(iw * e[:n]) / miles             # n weights x n draws, added up
    upper_b = lower_b + w_next * e[n] / miles     # plus ONE more term
```

Everything below is that loop, done for all `B` replicates at once.

**`@` means "multiply pairwise, then add up".** For one row it is `sum(a * b)`:

```python
iw = [10, 20, 30]
e  = [ 1,  2,  3]

iw * e   ->  [10, 40, 90]      # elementwise multiply
sum(...) ->  140               # add them up
iw @ e   ->  140               # both steps in one operator
```

**`M` holds all the random draws: one row per replicate, one column per draw.**

```python
M = [[1, 2, 3, 4],        # replicate 0 : 4 draws  (n=3, so n+1=4)
     [5, 6, 7, 8]]        # replicate 1 : 4 draws

M[:, :n]  = [[1, 2, 3],   # all rows, FIRST n columns  -> the n weighted draws
             [5, 6, 7]]
M[:, n]   =  [4, 8]       # all rows, the LAST column  -> the (n+1)th draw
```

`M[:, :n] @ iw` applies the `sum(iw * e)` step to **every row at once**:

```
row 0:  [1,2,3] * [10,20,30] = [10, 40, 90]   -> 140
row 1:  [5,6,7] * [10,20,30] = [50,120,210]   -> 380
M[:, :n] @ iw                                  -> [140, 380]
```

**Why the second line has no `@`.** Because there is nothing to add up:

| | how many weights | how many draws | needs a sum? |
|---|---|---|---|
| `tL` (lower) | `n` (the vector `iw`) | `n` (`M[:, :n]`) | **yes** → `@` |
| `tU` (upper) | **1** (the scalar `w_next`) | **1** (`M[:, n]`) | no → plain `*` |

The lower bound sums `n` products, so it needs the operator that sums. The upper bound adds a
*single* extra term — one weight times one draw — so ordinary multiplication is all you need. The
asymmetry in the syntax is just the asymmetry in the method: **`n` draws for the lower bound, one
more for the upper.**

If the `@` is distracting, this is identical and arguably clearer:

```python
tL = (M[:, :n] * iw).sum(axis=1) / miles      # multiply, then sum across each row
tU = tL + w_next * M[:, n] / miles            # unchanged -- nothing to sum
```

**The two replicate arrays are the point.** `tL` (n draws) gives the **lower** bound; `tU` (n+1
draws) gives the **upper**. The extra draw enters the upper limit only — exactly as `X+1` does in
the Garwood/gamma interval. This is *not* a percentile interval off one sequence: appending `w_next`
to the weight vector and taking both quantiles from the result inflates the **lower** bound by up to
**2.75x at n=2**. See the [why section](#exponential-bootstrap--two-different-things-share-this-name).

> **Caveat.** `2604.03827` derives a *data-driven* choice of the "next weight" `w**`; using `iw.max()` here is illustrative only, so treat this block as the mechanism, not a reproduction of their estimator.

### 4. Cluster — and what ignoring the clustering costs you

```python
# ============================================================ 4. CLUSTER
rng = np.random.default_rng(0)
sites = [rng.normal(loc, 1.0, size=k) for loc, k in
         zip(rng.normal(5, 2, 12), rng.integers(20, 60, 12))]   # 12 sites, correlated within
flat = np.concatenate(sites); n_cl = len(sites)
tb = np.empty(B)
for b in range(B):
    g = rng.integers(0, n_cl, size=n_cl)                   # <-- THE LINE
    tb[b] = np.concatenate([sites[i] for i in g]).mean()
naive = np.empty(B)
for b in range(B):
    naive[b] = flat[rng.integers(0, len(flat), len(flat))].mean()
print(f"4 CLUSTER       mean={flat.mean():.4f}  CI={pct(tb)[0]:.4f},{pct(tb)[1]:.4f}"
      f"   [naive row CI={pct(naive)[0]:.4f},{pct(naive)[1]:.4f} <- {(pct(tb)[1]-pct(tb)[0])/(pct(naive)[1]-pct(naive)[0]):.1f}x too narrow]")
```

**Output:** `mean=5.0564  CI=[4.1772, 5.9735]`   naive row CI `[4.8969, 5.2080]` — **5.8× too narrow**

**This is the single most valuable number in this document.** 12 sites, ~470 rows. Resampling rows instead of sites produces an interval nearly six times too tight — a result that looks far more precise than the data supports. The code runs both so you can see the gap, not just be told about it.

### 5. Block — and what ignoring serial dependence costs you

```python
# ============================================================ 5. BLOCK
rng = np.random.default_rng(0)
e = rng.normal(0, 1, 400); series = np.zeros(400)
for i in range(1, 400): series[i] = 0.8*series[i-1] + e[i]  # AR(1), serially dependent
n = len(series); L = int(round(n ** (1/3)))
tb = np.empty(B)
for b in range(B):
    starts = rng.integers(0, n, size=n // L)               # <-- THE LINE (circular)
    tb[b] = np.concatenate([np.take(series, range(s, s+L), mode="wrap") for s in starts]).mean()
naive = np.array([series[rng.integers(0, n, n)].mean() for _ in range(B)])
print(f"5 BLOCK  L={L:<3}   mean={series.mean():.4f}  CI={pct(tb)[0]:.4f},{pct(tb)[1]:.4f}"
      f"   [naive iid CI={pct(naive)[0]:.4f},{pct(naive)[1]:.4f} <- {(pct(tb)[1]-pct(tb)[0])/(pct(naive)[1]-pct(naive)[0]):.1f}x too narrow]")
```

**Output:** `L=7  mean=-0.1913  CI=[-0.5127, 0.1263]`   naive iid CI `[-0.3523, -0.0369]` — **2.0× too narrow**

AR(1) with φ=0.8. The naive interval **excludes the true mean of 0**; the block interval contains it. `L = round(n**(1/3))` = 7 here. Same failure mode as clustering, different axis.

### 6. Stratified — preserve the design proportions

```python
# ============================================================ 6. STRATIFIED
rng = np.random.default_rng(0)
strata = np.repeat([0, 1, 2], [150, 40, 10])
vals = np.concatenate([rng.normal(3, 1, 150), rng.normal(8, 1, 40), rng.normal(15, 1, 10)])
keys = np.unique(strata)
tb = np.empty(B)
for b in range(B):
    boot = np.concatenate([rng.choice(vals[strata == k], size=(strata == k).sum(), replace=True)
                           for k in keys])                 # <-- THE LINE
    tb[b] = boot.mean()
print(f"6 STRATIFIED    mean={vals.mean():.4f}  CI={pct(tb)[0]:.4f},{pct(tb)[1]:.4f}")
```

**Output:** `mean=4.6153  CI=[4.4872, 4.7475]`

Strata of 150/40/10. Each replicate keeps those sizes exactly, so a rare stratum can never vanish — which under the standard bootstrap it sometimes would.

### 7. Parametric — resample the model, not the data

```python
# ============================================================ 7. PARAMETRIC
rng = np.random.default_rng(0)
counts, expo = 7, 56.7
lam_hat = counts / expo
tb = np.empty(B)
for b in range(B):
    x_star = rng.poisson(lam_hat * expo)                   # <-- THE LINE (simulate the MODEL)
    tb[b] = x_star / expo
print(f"7 PARAMETRIC    rate={lam_hat:.4f}  CI={pct(tb)[0]:.4f},{pct(tb)[1]:.4f}")
```

**Output:** `rate=0.1235  CI=[0.0353, 0.2116]`

7 crashes in 56.7M miles. Nothing is resampled from the data at all — you draw fresh Poisson counts from the fitted λ̂. **This is the one Waymo ran and rejected.** It works when you trust the model, and it is wrong in a way you cannot detect from the interval when you don't. Compare against the exact gamma interval in the toolkit doc.

### 8. Bayesian (Rubin) — smooth weights, nothing ever dropped

```python
# ============================================================ 8. BAYESIAN
rng = np.random.default_rng(0)
tb = np.empty(B)
for b in range(B):
    w = rng.dirichlet(np.ones(len(data)))                  # <-- THE LINE (sums to 1)
    tb[b] = np.dot(w, data)
print(f"8 BAYESIAN      mean={theta_hat:.4f}  CI={pct(tb)[0]:.4f},{pct(tb)[1]:.4f}")
```

**Output:** `mean=2.8638  CI=[2.6058, 3.1564]`

`rng.dirichlet(np.ones(n))` sums to 1, so use `np.dot(w, data)` directly. Every observation always carries positive weight. Compare with the exponential bootstrap above: same Exp(1) family, but normalised and with `n` weights rather than `n+1`.

### 9. Wild — regression with heteroskedastic errors

```python
# ============================================================ 9. WILD (regression)
rng = np.random.default_rng(0)
X = rng.normal(0, 1, 150); beta = 2.0
y = 1.0 + beta*X + rng.normal(0, 0.5 + 0.8*np.abs(X))      # heteroskedastic
A = np.c_[np.ones(len(X)), X]
coef = np.linalg.lstsq(A, y, rcond=None)[0]
fitted, resid = A @ coef, y - A @ coef
tb = np.empty(B)
for b in range(B):
    v = rng.choice([-1.0, 1.0], size=len(X))               # <-- THE LINE (Rademacher)
    y_star = fitted + v * resid
    tb[b] = np.linalg.lstsq(A, y_star, rcond=None)[0][1]
print(f"9 WILD          beta={coef[1]:.4f}  CI={pct(tb)[0]:.4f},{pct(tb)[1]:.4f}")
```

**Output:** `beta=1.8032  CI=[1.4841, 2.1095]`

Error variance grows with |x|. You refit on `fitted + v*resid` each replicate, so the design matrix `X` is held **fixed** and only the residual signs flip. That is what preserves the conditional heteroskedasticity a pairs bootstrap would smear out.

### STEP 4 — all three interval rules on one dataset

```python
# ============================================================ STEP 4 on one dataset
rng = np.random.default_rng(0)
tb = np.array([data[rng.integers(0, len(data), len(data))].mean() for _ in range(B)])
p_lo, p_hi = pct(tb)
b_lo, b_hi = 2*theta_hat - p_hi, 2*theta_hat - p_lo
res = bootstrap((data,), np.mean, n_resamples=B, method="BCa", confidence_level=0.95,
                random_state=0)
print(f"\nSTEP 4 on the same data (theta_hat={theta_hat:.4f}):")
print(f"   percentile  [{p_lo:.4f}, {p_hi:.4f}]")
print(f"   basic       [{b_lo:.4f}, {b_hi:.4f}]")
print(f"   BCa (scipy) [{res.confidence_interval.low:.4f}, {res.confidence_interval.high:.4f}]")
```

**Output:** percentile `[2.6012, 3.1404]` · basic `[2.5873, 3.1264]` · BCa `[2.6164, 3.1575]`

Same replicates, three rules. The data is Gamma(2, 1.5) — right-skewed — and BCa shifts the interval *up* relative to percentile, correcting the mis-centring. Modest here because n=200; on single-digit crash counts the correction is much larger. `scipy.stats.bootstrap(..., method="BCa")` does the `z0` and jackknife-`a` work for you.

### The two numbers to remember from this section

```
CLUSTER   ignoring the grouping   ->  interval 5.8x too narrow
BLOCK     ignoring the time order ->  interval 2.0x too narrow, and it EXCLUDES the true mean
```

Both are failures of **STEP 0**, not of the resampling line. If the data is dependent and you
prepared it as if it were not, no choice of weight distribution and no interval rule will save you.

---

## Provenance

The skeleton, the two-axis framing, the line-by-line comparison, the decision tree, the gotchas and
the nine end-to-end programs are mine, written as a learning aid. **Every code block and every number
quoted is verified by execution, not asserted** — including the 5.8x and 2.0x interval-narrowing
demonstrations. Datasets in the end-to-end section are synthetic and chosen to make each variant's
failure mode visible; they are not Waymo data. The EB lower/upper asymmetry (`n` draws for the lower
bound, `n+1` for the upper) is quoted from `2604.03827:b75-b76` and Table 2; an earlier revision of
this file applied the extra draw to both bounds, which was wrong. The Poisson-bootstrap lineage from the multinomial bootstrap, the Exponential(1) /
Gamma(1,1) derivation, the `n+1` "next weight" term and the PB-undercoverage findings are quoted from
`2604.03827` in the local `waymo_av_safety` corpus; ligature artifacts from PDF extraction have been
restored and **bold** inside quotations is mine. The distinction between this exponential bootstrap
and Rubin's Bayesian bootstrap is my note, not the paper's.
