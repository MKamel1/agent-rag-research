# Bootstrap in Waymo-Authored Papers — Verified Re-run

**Date:** 2026-08-19
**Scope:** the 153 curated Waymo-authored papers. Curated means an enumerated list taken from
Waymo's own publication index (`waymo.com/research/`, `waymo.com/safety/research/`), so authorship
is exact by construction rather than a keyword guess. Third-party AV-safety literature elsewhere in
the 1,738-paper corpus is out of scope and appears nowhere below.

**Supersedes:** `2026-08-19-bootstrap-resampling-audit.md`, which reached 4 USED papers and
excluded `2506.02215` as a naming trap. That exclusion was wrong — see §5.

**Questions:** (1) which Waymo papers actually *conduct* a bootstrap, how, and with what stated
justification (§2–§4); (2) does any paper use a cluster bootstrap or another method for **dependent
observations** (§8).

---

## 1. Method

Two passes, because ranked retrieval cannot answer "which papers" — top-k samples a relevance
ordering and cannot report what it missed.

1. **Exhaustive scan** (`scan_corpus` / `scripts/enumerate_corpus.py`) over all 153 papers for
   `bootstrap`. 12 papers matched. Run with `--per-paper 12`, deliberately high (see §5).
2. **Synonym sweep** for bootstrap phrased without the word —
   `with replacement|resampl[a-z]* (the )?(data|dataset|sample)|percentile (interval|method)|jackknife|monte[ -]carlo (resampl|replicat)`.
   2 papers matched, both already in the set. **0 additional.** The enumeration is closed.
3. **Semantic search** over a live MCP stdio session for justification language, to catch reasoning
   that states no method name. Surfaced no paper outside the set.

`section_path` is the mention-vs-use discriminator throughout: a method named under Related Work or
Introduction is usually being cited; one named under Methods/Analysis is usually being used. It is
used as a hint, never as an automatic filter — section detection fails on some PDFs (notably
`2604.03827`, §3), and auto-excluding on it would reintroduce the recall hole this scan exists to
close.

---

## 2. Conducts a bootstrap — 6 papers

Five statistical, one machine-learning.

| Paper | ID | Variant | Purpose |
|---|---|---|---|
| Confidence Intervals for Rate Estimation with Importance Sampling in Autonomous Vehicle Evaluation | `2604.03827` | Exponential bootstrap (novel), + Poisson bootstrap as baseline | Rate CIs under rare events |
| Dynamic Benchmarks: Spatial and Temporal Alignment for ADS Performance Evaluation | `2410.08903` | Poisson bootstrap, N=1000, 90% CI | All CIs in the paper |
| Active inference as a unified model of collision avoidance behavior in human drivers | `2506.02215` | Nonparametric, 10,000 resamples | Model comparison |
| Baseline vulnerable road user injury risk in multiple U.S. dense urban driving environments | `local:bc031ecd9224` | Nonparametric, n=1,000, percentile CI | CIs on distribution percentiles |
| Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million Miles | `2312.12675` | Parametric | Sensitivity check — **then rejected** |
| MultiPath++: Efficient Information Fusion and Trajectory Aggregation for Behavior Prediction | `2111.14973` | Bootstrap aggregation (bagging) | Ensemble diversity |

---

## 3. Justification, per paper

### `2604.03827` — the methods paper (Chen, Zhou, Lee, Chamandy, Hohnhold; Waymo LLC)

Invents its bootstrap rather than applying one. Rate estimation via a Horvitz–Thompson estimator
over segments passing through both simulation and human review.

> Accounting for both rare events and complex sampling presents challenges when quantifying
> uncertainty for rate estimation in autonomous vehicle performance evaluation. […] Though
> asymptotic theory for the model is available, the inference of confidence intervals (CIs) in the
> presence of rare events requires new investigation. — p.0

The driving requirement is a **monotonicity criterion**: summing the rates of disjoint event types
should raise both the point estimate and the upper bound. The stated reason is operational, not
mathematical:

> We discovered that these methods however do not have a desired monotonicity property […] which is
> important in the applied setting as it allows practitioners to communicate a consistent story to
> business decision-makers. — p.5

They evaluate and reject the off-the-shelf option:

> It is worth pointing out that the Poisson bootstrap CI does satisfy the monotonicity property.
> However, it can severely under-estimate the uncertainty when the observed true positives are
> rare. — p.7

Exponential bootstrap is derived from a fiducial argument, extends weighted Gamma to continuous
sampling probabilities, and ships with a saddlepoint approximation for speed.

**Section-detection caveat:** every hit for this paper returns `(no section detected)`. The PDF
parsed without section paths, so mention-vs-use here is judged from the text, not from metadata.
The text is unambiguous — it is a full statistics paper with numbered sections.

### `2410.08903` — Poisson bootstrap

> All confidence intervals presented in this paper are estimated using Poisson bootstrap method (28)
> with 90% confidence level. For each of the bootstrap iterations (N=1000), a random number from a
> Poisson distribution with mean 1 (λ = 1) is generated for each crash event to represent the
> frequency of that particular event within the resampled data set. The distribution of a quantity
> of interest […] across all bootstrap samples serves as an approximation of the sampling
> distribution. — p.6, §Confidence Intervals

No explicit "we chose this because" sentence. The structural reason is that the dynamic benchmark
multiplier is a ratio of spatially/temporally reweighted counts with no tractable closed form.

### `2506.02215` — nonparametric bootstrap for model comparison

> Given the relatively small size of the ground truth dataset, we applied nonparametric
> bootstrapping [120] with 10000 resamples to estimate the sampling variability of each metric.
> — p.27, §Opposite-direction lateral incursion scenario

Bootstraps Jensen-Shannon divergence (collision-outcome distributions) and Wasserstein distance
(reaction times). The bootstrap SDs then drive model selection:

> To determine whether one model variant provided a statistically significant better fit than
> another, we computed the signal-to-noise ratio of the difference between models […] A
> signal-to-noise ratio exceeding 3 was considered indicative of a meaningful difference.
> — p.27, §Statistic significance

This is the only bootstrap in the corpus used for **model selection** rather than for reporting an
error bar.

### `local:bc031ecd9224` — nonparametric, and a deliberate split

> The data were resampled with replacement (n = 1,000) to generate 95% confidence intervals for
> these point estimates. The lower and upper bounds were obtained by sorting the samples and taking
> the 25th and 975th values, respectively. Resampling was done within each grouping to ensure
> fidelity of the bootstrap samples to the original data set. — p.4, §Injury risk distributions

Note the split: *rates* get Byar's method (closed-form Poisson-exact, chosen because it "retains
high levels of accuracy for both small and large counts"), while *percentiles* of the injury-risk
distribution get the bootstrap — percentiles have no analytic interval. Stratified resampling is
justified explicitly; the choice of bootstrap over a closed form is not.

### `2312.12675` — computed, then rejected

The one case where a bootstrap was run and deliberately kept out of the headline numbers.

> To investigate the effect of the CRSS variance estimates on the confidence intervals for the rate
> ratio, the authors constructed confidence intervals using a parametric bootstrap using the
> standard error for the benchmark crash counts estimated using the survey design variables. The
> rate ratio confidence intervals computed using the parametric bootstrap method were narrower than
> those computed using the method described in Equation 2. […] The Nelson (1970) method is more
> conservative (i.e., produces larger confidence intervals) relative to the parametric bootstrap
> method. For this reason, the confidence intervals described in Equation 2 were used.
> — p.7, §Confidence Intervals

That choice propagated into documented practice — see §4.

### `2111.14973` — bootstrap aggregation

> We specifically apply bootstrap aggregation (bagging) [19] to our predictor heads by training E
> such heads together. To encourage models learning complementary information, the weights of the E
> heads are initialized randomly, and an example is used to update the weights of each head with a
> 50% probability. — p.8, §4 Ensembling predictor heads via bootstrap aggregation

The 50% per-example draw is what makes this a bootstrap rather than plain ensembling. Classified
here as a genuine use of the bootstrap principle in its machine-learning form; the superseded
report classified it as a naming trap. Both readings are defensible — flagged rather than hidden.

---

## 4. Recommends or documents, without conducting one

- **`local:4087ccce4c01`** — *RAVE Checklist* (p.11): "For uncertainty in elements for which
  distributions are not known, sensitivity analysis and bootstrapping approaches can be useful."
  Methodological guidance.
- **`local:6b9ccd0431f6`** — *Comparison of Waymo Rider-Only Crash Rates by Crash Type… at 56.7
  Million Miles* (p.47, RAVE self-assessment): records that "the Nelson 1970 method produces wider
  (i.e., more conservative) confidence intervals compared to parametric bootstrapping (Kusano et al
  2024)" — documenting `2312.12675`'s decision as standing practice. Uses Nelson, not a bootstrap.

## 4b. Word present, bootstrap absent — 4 papers

| Paper | ID | Sense |
|---|---|---|
| Scalable Scene Flow from Point Clouds in the Real World | `2103.01306` | Colloquial — "bootstrap annotation labels" from tracked objects |
| LESS: Label-Efficient Semantic Segmentation for LiDAR Point Clouds | `2210.08064` | Colloquial — "bootstrapping the labeling from scratch" |
| Particle-Based Score Estimation for State Space Model Learning | `2212.06968` | The *bootstrap particle filter* — a named SMC algorithm, unrelated to Efron's bootstrap |
| Scaling Motion Forecasting Models with Ensemble Distillation | `2404.03843` | Bagging described in §II Related Work only |

---

## 5. Correction log

**One material false negative in the superseded report.** `2506.02215` was excluded there as a
naming trap on the grounds of "cross-entropy-method action resampling." That paper does use
cross-entropy-method resampling — and it *also* runs a nonparametric bootstrap with 10,000
resamples at p.27, which the exclusion missed.

**Root cause, worth carrying forward:** the scan ran with a low `--per-paper` cap. That paper's
three cross-entropy `resampl` hits filled its quota and crowded out the p.27 bootstrap evidence.
The tool printed `some evidence truncated` and neither pass acted on it. **The per-paper cap is a
display limit that can silently hide the one hit that decides a classification.** Raise it whenever
the output is a claim about what a paper does, and treat `some evidence truncated` as blocking.

**Count refinement.** An intermediate pass reported 7 papers using statistical bootstrap. Applying
the conduct-vs-recommend distinction properly gives **5** — `local:4087ccce4c01` recommends
bootstrapping and `local:6b9ccd0431f6` documents the Nelson-vs-bootstrap comparison, but neither
runs one. Same papers, tighter classification.

**Titles.** This re-run is the first to use repaired titles. 16 Waymo-corpus papers previously
carried a PDF filename as their title (e.g. `local:6b9ccd0431f6` was stored as "Safety Impact Crash
Type Manuscript"), which made classification passes materially harder to read.

---

## 6. Reproduction

```bash
# 1. exhaustive scan, high per-paper cap
python scripts/enumerate_corpus.py 'bootstrap' --author-org Waymo --per-paper 12

# 2. synonym sweep — bootstrap phrased without the word
python scripts/enumerate_corpus.py \
  'with replacement|resampl[a-z]* (the )?(data|dataset|sample)|percentile (interval|method)|jackknife' \
  --author-org Waymo --per-paper 2

# 3. per-paper deep dive (no cap pressure)
python scripts/enumerate_corpus.py 'bootstrap' --paper-id 2506.02215 --author-org '' \
  --per-paper 8 --context 600

# 4. semantic pass over a live MCP session, Waymo-only by default
python scripts/ask_waymo_corpus.py "why bootstrap for crash rate confidence intervals" --k 12

# 5. dependent-observations families (§8) -- run separately so hits stay attributable.
#    These are the exact patterns behind §8's match counts; abridging them changes the counts.
python scripts/enumerate_corpus.py --author-org Waymo --per-paper 3 \
  'cluster[a-z]*[ -]?(bootstrap|robust|standard error|variance|correlat)|block bootstrap|clustered (standard|se|data|observation)|by cluster'
python scripts/enumerate_corpus.py --author-org Waymo --per-paper 2 \
  'mixed[- ]effect|random effect|random intercept|multilevel|hierarchical (model|regression|bayes)|generalized estimating equation|\bGEE\b|exchangeable correlation|working correlation'
python scripts/enumerate_corpus.py --author-org Waymo --per-paper 2 \
  'survey design|complex sampl|primary sampling unit|\bPSU\b|design effect|design variable|variance estimate'
python scripts/enumerate_corpus.py --author-org Waymo --per-paper 2 \
  'autocorrelat|serial correlat|overdispers|over-dispers|negative binomial|independen(t|ce) (observation|assumption|sampl)|non-independen|correlated (observation|error|residual)|robust standard error|sandwich'
python scripts/enumerate_corpus.py --author-org Waymo --per-paper 3 \
  'intraclass|\bICC\b|spatial[- ]?temporal depend|spatio-?temporal depend|nested within|unit of analysis|correlated (observation|outcome|response|measure)|dependen(ce|cies) (between|among|across) (observation|event|crash|trip)'
```

## 7. Limitations

- Lexical scan plus one synonym sweep. A bootstrap described in wording neither pass anticipated
  would still be missed; the sweep found 0 additional, which bounds but does not eliminate this.
- Scope is the 153 curated Waymo-authored papers. A paper Waymo co-authored that is absent from
  their publication index is out of scope by construction.
- `2604.03827`'s mention-vs-use calls come from reading the text, not from `section_path` — that
  PDF parsed with no sections detected.
- `2111.14973`'s classification is a judgement call (§3), not a measurement.

---

## 8. Dependent observations — cluster bootstrap and alternatives

A separate axis from the bootstrap *variant*: when observations are not independent (repeated
measures on one participant, crashes clustered within a city or a survey's sampled hospitals), a
naive interval is too narrow. The standard remedies are cluster/block bootstrap, cluster-robust
("sandwich") standard errors, GEE, or a mixed-effects model.

**Scan scope for this section** (same 153 curated papers, five pattern families, run separately so
each could be attributed):

| Family | Pattern (abridged) | Papers matched | Relevant |
|---|---|---|---|
| A | `cluster*[ -](bootstrap\|robust\|standard error\|variance\|correlat)`, `block bootstrap`, `clustered (standard\|se\|data\|observation)` | 4 | **0** |
| B | `mixed[- ]effect`, `random effect/intercept`, `multilevel`, `hierarchical (model\|regression\|bayes)`, `GEE`, `exchangeable/working correlation` | 6 | 1 |
| C | `survey design`, `complex sampl`, `primary sampling unit`, `PSU`, `design effect`, `design variable`, `variance estimate` | 4 | 2 |
| D | `autocorrelat`, `serial correlat`, `overdispers`, `negative binomial`, `robust standard error`, `sandwich`, `correlated (observation\|error\|residual)` | 1 | 1 |
| E | `intraclass`, `ICC`, `spatio-temporal depend`, `nested within`, `unit of analysis`, `correlated (observation\|outcome\|response\|measure)` | 4 | 1 |

### 8.1 Cluster bootstrap: zero

**No cluster bootstrap, no block bootstrap, no cluster-robust/sandwich standard errors, and no GEE
appear anywhere in the 153 curated Waymo-authored papers.** Family A's 4 matches are all k-means or
point-cloud clustering (`2210.08061`, `2309.14491`, `2309.16889`, `local:2e47fb1e0308`) — the word
"cluster" in its machine-learning sense, not its statistical one; all four matched only on the
`by cluster` alternative ("by clustering"). Family D returned a single paper, and that hit was the
word "independent" in an unrelated sentence.

Family B's other five matches are architecture vocabulary, not statistics: "multilevel fusion"
(`2206.03666`), "hierarchical fusion" of attention modalities (`2207.05844`), hierarchical
imitation-learning models (`2210.09539`, `2309.14003`), and "multilevel splitting" as a rare-event
simulation technique (`2411.17826`). Family E's non-relevant matches are "spatiotemporal
dependencies" between tracked objects (`2008.07725`) and "intraclass" similarity in contrastive
learning (`2210.08064`, `2210.08375`).

### 8.2 What is used instead — three papers, three mechanisms

**Mixed-effects models — `local:03e2dfdfa816`** (*Kinematic Characterization of Micro-Mobility
Vehicles During Evasive Maneuvers*). The only random-effects model in the corpus, on a design that
requires one:

> This test track experiment used a mixed-factor design […] MMV Type was a **between-subjects**
> factor, whereas MMV Power was a **within-subject** factor. — p.2, §2 Method

> **Generalized linear mixed-effect models** were used to assess the significance of the MMV Type
> (eight different MMV types and the pedestrian) and MMV Power Source factors (Electric vs
> Traditional) on the relevant metrics calculated from the data (Table 3), controlling for
> participant sex and maneuver speed. — p.8, §2.4 Data Analysis

40 participants each performed repeated braking and swerving trials at two speeds — textbook
repeated measures. *Caveat:* the retrievable text names the model class but never states the
random-effect structure (grouping variable, random intercept vs. slope). A GLMM implies a random
effect by definition, but the specification is not in the text this scan can reach.

**Design-based survey variance — `2312.12675`** (*Comparison of Waymo RO Crash Data at 7.1 Million
Miles*). CRSS is a clustered, stratified survey, and the paper treats the design effect explicitly:

> Standard errors for counts that use the survey design variables are larger than standard errors
> calculated using conventional methods using just the weighted counts (Zhang and Diaz, 2020).
> — p.7, §Confidence Intervals

This is dependence handling: clustering inflates true variance, and using only weighted counts
understates it. The design-based SEs were then propagated into the parametric bootstrap of §3,
which produced narrower intervals than Nelson (1970) — and Nelson was kept as the more conservative
choice.

**Independence engineered at the design stage — `2604.03827`.** The most interesting treatment in
the corpus, because it names the problem and deliberately declines to solve it:

> Both Assumption 1 and 2 are reasonable when the run segments are properly defined so that true
> positive incidents are independent of each other. **How to properly design the run segments to
> minimize spatial-temporal dependencies is beyond the scope of the current paper** but may be
> discussed elsewhere. Intuitively, event rarity further helps make the independence assumption a
> good approximation. — p.5

Independence is obtained by how run segments are cut, not by a variance estimator that tolerates
correlation, with event rarity as a secondary argument. Explicit and honest about the limitation —
and the only paper in the corpus to raise the issue at all.

### 8.3 A distinction not to blur

`local:bc031ecd9224` uses **stratified** resampling — "Resampling was done within each grouping to
ensure fidelity of the bootstrap samples to the original data set" (p.4). This is **not** a cluster
bootstrap. A cluster bootstrap resamples *whole clusters* to absorb intra-cluster correlation;
stratified resampling resamples *within* groups to preserve composition. Different mechanism,
different purpose — it addresses representativeness, not dependence.

### 8.4 Gap worth flagging

`local:442bfd3211f4` (*Descriptive Analysis of Cyclist Dooring Events Using Data from NEISS*) draws
on NEISS, described in the paper itself as "a probability sample of 100 hospitals […] stratified
based on size of the emergency department and geographic location" (p.1). Hospitals are the primary
sampling units. The paper applies the inverse-probability weights for point estimates, then reports:

> helmeted cyclists had a 58% reduction in the odds of sustaining a head injury (odds ratio: 0.42,
> 95% confidence interval: 0.33-0.54) compared to unhelmeted riders. — p.5, §III Results

No design-based variance statement appears anywhere in the retrievable text. If that interval treats
the 644 cases as independent rather than clustered within hospitals, it is narrower than it should
be. Stated as what the text shows, not as a verdict — the analysis code is not observable here.

More broadly: the crash-rate benchmark papers compare ADS to human rates where crashes plausibly
correlate within city, deployment period, and vehicle. None uses cluster-robust methods.

### 8.5 Limitations of this section

Same lexical bounds as §7, plus one specific to dependence: a paper could handle clustering
implicitly — fitting a model in a package whose defaults are design-aware, or aggregating to a level
where dependence is absorbed — without any of the vocabulary above appearing in its text. The
`local:03e2dfdfa816` caveat is the visible instance of this: the method class is named, the
random-effect structure is not. Absence of the vocabulary bounds what is *stated*, not what was
*done*.
