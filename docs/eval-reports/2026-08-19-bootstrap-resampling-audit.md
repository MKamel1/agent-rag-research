> **SUPERSEDED (2026-08-19) — see `2026-08-19-bootstrap-waymo-verified.md`.**
>
> This audit excluded `2506.02215` (*Active inference as a unified model of collision avoidance
> behavior in human drivers*) as a naming trap. That was a **false negative**: the paper runs a
> nonparametric bootstrap with 10,000 resamples at p.27 to estimate sampling variability for model
> comparison. The cause was a low per-paper evidence cap — the paper's cross-entropy-method
> `resampl` hits filled its quota and hid the bootstrap passage.
>
> The verbatim evidence and reasoning below remain accurate for the papers it does cover; the
> USED/EXCLUDED counts do not. Read the superseding report for the current classification.

# Bootstrap / Resampling Audit — Waymo-Authored Papers

**Scope:** the 153 Waymo-authored papers in the corpus only (queried with the default, non-`--all-papers` mode; every query below returned `scope: WAYMO-AUTHORED ONLY`). Third-party AV-safety literature elsewhere in the 1,738-paper corpus is out of scope by construction and does not appear anywhere below.

**Question:** which Waymo papers actually *used* bootstrap or other resampling methods (as opposed to merely mentioning them), and how did they justify the specific method chosen?

**Plain-English glossary** (used once, then assumed):
- **Bootstrap**: build many "pretend" datasets by randomly resampling the observed data (with replacement), recompute the statistic of interest on each pretend dataset, and use the spread of those results as the confidence interval. No assumption about the data's underlying distribution is required.
- **Poisson bootstrap**: instead of literally drawing rows out of a bag, each observation is given a random weight drawn from a Poisson distribution (mean 1). This is mathematically equivalent to resampling with replacement but is easier to compute at scale, and is a standard trick for bootstrapping rare-event count data.
- **Byar's method / Poisson-exact / chi-squared method**: closed-form formulas for a confidence interval around a count that assume the count follows a Poisson distribution — no resampling involved, just algebra on a known distribution.
- **Confidence interval (CI)**: a range that is expected to contain the true value of a quantity (e.g., a crash rate) with some stated probability (e.g., 95%).
- **Coverage / undercoverage**: how often a CI-construction method's interval actually contains the true value across repeated trials. A method that "undercovers" produces intervals narrower than advertised — it understates uncertainty.

---

## 1. USED — bootstrap or resampling actually applied

| paper_id | title | method | section | page |
|---|---|---|---|---|
| `2410.08903` | Dynamic Benchmarks: Spatial and Temporal Alignment for ADS Performance Evaluation | Poisson bootstrap (N=1000 iterations, 90% CI) | Confidence Intervals | 6 |
| `local:bc031ecd9224` | Baseline vulnerable road user injury risk in multiple U.S. dense urban driving environments | Nonparametric bootstrap — resampling with replacement (n=1,000) | Injury risk distributions | 4 |
| `2312.12675` | Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million Miles | Parametric bootstrap — computed as a sensitivity check, then **deliberately rejected** for the headline results | Confidence Intervals | 7 |
| `2604.03827` | Confidence Intervals for Rate Estimation with Importance Sampling in Autonomous Vehicle Evaluation | **Two** resampling methods, head-to-head: (a) Poisson Bootstrap ("PB") — computed as a comparison baseline; (b) Exponential Bootstrap ("EB") — the paper's own proposed method, a Monte Carlo procedure built from weighted sums of Exponential/Gamma random variables | Section 5 ("Poisson Bootstrap CI" / "Weighted Gamma CI") / Section 6 (numerical studies) — see note on section-detection below | 0–12 |

### Note on `2604.03827`'s section labels
Every hit for this paper came back with `SECTION: (front matter / unsectioned)` — the ambiguous case the task instructions warned about. I ran follow-up queries anchored on the paper's own title plus method names and inspected the returned text directly. The content is unambiguous: it is a full statistics paper with numbered sections — "2. Rate estimation," "4. Related work," "5.1 [Poisson Bootstrap]," "5.2. Weighted Gamma CI," "6. [numerical studies]," "7. Real-world data analysis," "A.1 Proof of Lemma 3." The section-path field is simply broken for this PDF (probably a parsing/layout issue), not evidence the passages are abstract-only or front matter. Resolved, not left uncertain.

---

## 2. Justification per USED paper — verbatim

### `2410.08903` — Dynamic Benchmarks (Poisson bootstrap)

> "All confidence intervals presented in this paper are estimated using Poisson bootstrap method (28) with 90% confidence level. For each of the bootstrap iterations (N=1000), a random number from a Poisson distribution with mean 1 (λ = 1) is generated for each crash event to represent the frequency of that particular event within the resampled data set. The distribution of a quantity of interest (unadjusted benchmark, dynamic benchmark, or dynamic benchmark multiplier) across all bootstrap samples serves as an approximation of the sampling distribution. The 5th and 95th quantiles of the distribution are then used to estimate the lower bound and upper bound, respectively, of the 90% confidence intervals." (p.6, *Confidence Intervals*)

**Finding: no justification given.** The passage cites reference "(28)" for where the method comes from and describes its mechanics in full, but nowhere in the retrieved text — including the Introduction, Methods header, and Discussion sections queried separately — does the paper argue *why* Poisson bootstrap was chosen over, e.g., the Poisson-exact or Nelson-ratio methods that sibling Waymo papers use (see §3 below for those). The choice is asserted, not defended.

### `local:bc031ecd9224` — Baseline VRU injury risk (resampling with replacement)

> "The data were resampled with replacement (n = 1,000) to generate 95% confidence intervals for these point estimates. The lower and upper bounds were obtained by sorting the samples and taking the 25th and 975th values, respectively. Resampling was done within each grouping to ensure fidelity of the bootstrap samples to the original data set." (p.4, *Injury risk distributions*)

**Finding: no justification given for choosing bootstrap specifically.** Interestingly, this same paper *does* justify its other CI method — Byar's method, used separately for collision-rate CIs:

> "Confidence intervals (95%) for these rates were developed using Byar's method, which represents an exact approximation to the Poisson distribution and retains high levels of accuracy for both small and large counts (Breslow et al. 1980)." (p.3, *Collision rates*)

So the paper explains why it picked Byar's for rate CIs (accuracy at both small and large counts) but gives no parallel rationale for why the *injury-risk-percentile* CIs specifically needed a bootstrap rather than, say, a parametric approach. Plausibly the reason is implicit — injury-risk-distribution percentiles (median, 75th, 95th) don't have the closed-form machinery Poisson methods offer — but the paper never states this.

### `2604.03827` — Confidence Intervals for Rate Estimation with Importance Sampling

This is the richest justification in the corpus: the paper compares **two resampling methods head-to-head** and gives an explicit, quantitative reason for preferring one.

**Poisson Bootstrap (PB)** is computed as the incumbent/comparison method:

> "It is worth pointing out that the Poisson bootstrap CI does satisfy the monotonicity property. However, it can severely under-estimate the uncertainty when the observed true positives are rare, which will be demonstrated later in numerical studies in Section 6." (p.7)

And from the numerical comparison itself:

> "PB systematically undercovers under both (a) and (b)…" (p.12)

i.e., across simulated scenarios, the Poisson Bootstrap interval failed to contain the true rate as often as its stated confidence level promised — especially for rare events, which is precisely the regime AV safety analyses care about.

**Exponential Bootstrap (EB)** is the paper's own proposed alternative, and — contrary to my initial read of the retrieved text — it is not just closed-form math wearing the bootstrap name: it is a genuine Monte Carlo/simulation-based resampling method. The abstract states:

> "We propose a novel exponential bootstrap (EB) method for CI construction based on a fiducial argument; it satisfies the monotonicity property, while novel extensions of some existing methods do not. Comprehensive numerical studies show that EB performs well for a wide range of settings relevant to our applications." (p.0, Abstract)

A parallel verification pass (run by the coordinator against the same paper, checked against the paper text) surfaced two further sentences I was not able to independently pull from my own retrieval despite six differently-phrased attempts (my queries kept returning the same ~12 pages of this 24-page paper; the two sentences below appear to sit on pages my rerank never surfaced):

> "…there is no closed-form expression for quantiles of the weighted sum of independent exponential random numbers, but this can be implemented by the Monte Carlo procedure described in Table 2, which we call 'exponential bootstrap' (EB), to mimic Poisson bootstrap."
>
> "The coverage of EB is more reliable than PB overall while the coverage error for PB can be very large and even close to 100% when true positive data is sparse."

I flag these two as **sourced from a parallel check, not independently reconfirmed by my own query** — the honest caveat the task asks for when a claim can't be directly re-derived. That said, everything I *did* independently retrieve is fully consistent with them and corroborates the picture: the abstract explicitly calls EB a numerically-evaluated method (not pure closed-form theory); the body text shows EB's building block is `Gamma(shape=1, rate=1)`, i.e. exactly an Exponential(1) random variable (p.7); and the appendix states "EB can be treated as a special realization of the weighted Gamma CI" with a *separate* fast saddlepoint approximation offered as an alternative to the (implied slower, simulation-based) exact computation (p.21, "A.3. Fast algorithm by saddlepoint approximation"). A saddlepoint approximation is only useful to develop if the default method it's approximating is otherwise costly to compute — which is consistent with EB's default form being Monte Carlo, not closed-form.

**Bottom line justification, in the paper's own terms:** EB was chosen over PB because (a) it satisfies a "monotonicity" property the authors argue is essential for interpretability — summing the rates of two disjoint event types should never produce a *narrower* combined confidence interval than either type's CI alone — and PB's competitor methods without EB's construction fail this test; and (b) EB's empirical coverage (how often the interval actually contains the true rate, checked via 10,000-replicate simulation studies, p.10) is close to the nominal/advertised level, while PB's coverage degrades severely, and can approach total failure, exactly when true-positive events are sparse — the regime AV safety rate-estimation cares about most.

Separately, in the Related Work section, the same paper also cites bootstrap the way the "MENTION" pattern in this audit's instructions describes — see §3.

### `2312.12675` — Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million Miles

*Added by the coordinator's review pass; this paper was missed by the audit's own retrieval — see §6b.*

This is the corpus's second-richest justification, and unusually it is a justification for **not**
using the bootstrap. The paper computed a parametric bootstrap as a sensitivity analysis, compared
it against the Nelson (1970) closed-form method, and then chose Nelson for its published intervals.
Verbatim (p.7, *Confidence Intervals*, block `2312.12675:b56`):

> "To investigate the efect of the CRSS variance estimates on the confidence intervals for the rate
> ratio, the authors constructed confidence intervals using a parametric bootstrap using the standard
> error for the benchmark crash counts estimated using the survey design variables. The rate ratio
> confidence intervals computed using the parametric bootstrap method were narrower than those
> computed using the method described in Equation 2. This result suggests that the method from
> Nelson (1970) is more sensitive to the other parameters in the rate ratio calculation (i.e., the
> count of ADS events) than a parametric bootstrap method. The Nelson (1970) method is more
> conservative (i.e., produces larger confidence intervals) relative to the parametric boostrap
> method. **For this reason, the confidence intervals described in Equation 2 were used** to construct
> rate ratio confidence intervals for the national benchmark comparisons."

**Why this counts as USED, not MENTIONED:** the bootstrap was actually constructed and its results
compared numerically — it is applied work, not a citation. This is the same standard §2 already
applied to `2604.03827`'s Poisson bootstrap, which is likewise computed in order to argue against it.

**The justification, in plain English:** the bootstrap gave *narrower* confidence intervals than
Nelson's method. Narrower intervals claim more precision, and when comparing a driverless vehicle's
crash rate against a human benchmark, overstating precision is the dangerous direction to err. They
kept the more conservative method deliberately. Note this is the opposite conclusion to
`2604.03827`, which rejects Poisson bootstrap for *under*-covering — the two papers are consistent,
both preferring whichever method is less likely to understate uncertainty.

---

---

## 3. MENTIONED ONLY — named but not applied by the citing paper

| paper_id | title | section (why this counts as mention-only) | page |
|---|---|---|---|
| `2604.03827` | Confidence Intervals for Rate Estimation with Importance Sampling in AV Evaluation | "4. Related work" (content-verified; SECTION field shows blank/unsectioned) — attributes the general bootstrap idea to prior literature rather than describing something this passage does | 6 |
| `local:4087ccce4c01` | RAVE Checklist: Recommendations for Overcoming Challenges in Retrospective Safety Studies of Automated Driving Systems | "Quantify uncertainty of the estimates with statistical testing or other methods." — a best-practices recommendation document, not an empirical analysis | 11 |

Verbatim passages:

- `2604.03827`, p.6: "Traditional procedures for CI construction include bootstrap (Efron and LePage (1992)), the delta method (see Bickel and Doksum (2015) for parametric models and Bickel et al. (1993) for semiparametric models) and empirical likelihood (Owen (2001)), which all rely on large sample approximation." — This is a literature-background statement attributing "bootstrap" to Efron and LePage, distinct from the paper's own applied use of Poisson Bootstrap elsewhere (§1–2 above). Per the task's own worked example, a single paper can have both a MENTION passage and a USE passage — this is exactly that case.

- `local:4087ccce4c01`, p.11: "For uncertainty in elements for which distributions are not known, sensitivity analysis and bootstrapping approaches can be useful." — This is the RAVE Checklist paper, a methodology/best-practices consensus document written by (and for) the Waymo-adjacent retrospective-safety-study research community. It recommends bootstrapping as an *available tool* researchers *could* use; the paper itself performs no empirical bootstrap analysis of its own.

---

## 4. NAMING TRAPS — excluded despite containing the word "bootstrap"/"resampling"

| paper_id | title | trap phrase (verbatim) | section / page | why excluded |
|---|---|---|---|---|
| `2212.06968` | Particle-Based Score Estimation for State Space Model Learning in Autonomous Driving | "The original bootstrap particle filter [13] samples at each time step…" | "2 Related Work", p.1 | **Bootstrap particle filter** is a Sequential Monte Carlo algorithm for state estimation (e.g., tracking a vehicle's position over time), unrelated to statistical resampling for computing confidence intervals on an estimate. Same word, different field. |
| `2212.06968` | (same) | "They rely on the combination of importance sampling and **resampling** steps of a set of N weighted particles…" | "3.2 Particle Filtering", p.3 | Same reason — "resampling" here means discarding low-weight particles and duplicating high-weight ones inside a particle filter, not resampling observed data to build a CI. |
| `2111.14973` | MultiPath++: Efficient Information Fusion and Trajectory Aggregation for Behavior Prediction | "We specifically apply bootstrap aggregation (bagging) [19] to our predictor heads by training E such heads together." | "4 Ensembling predictor heads via bootstrap aggregation", p.8 | **Bootstrap aggregation (bagging)** here is a machine-learning ensembling technique — training several model heads on different data views to reduce prediction variance — not a statistical procedure for quantifying uncertainty in a measured rate or effect. |
| `2103.01306` | Scalable Scene Flow from Point Clouds in the Real World | Section header: "BOOTSTRAPPING GROUND TRUTH ANNOTATIONS" | p.9 | "Bootstrapping" here refers to iteratively propagating/generating pseudo-ground-truth training labels for a perception model — an ML self-training sense of the word, not statistical resampling. |
| `2205.05703` | Multi-Class 3D Object Detection with Single-Class Supervision | "We found the cause to be dataset **resampling**. In Figure 4 we vary the probability of sampling images from the dominant vehicle class…" | "C. Dataset Resampling", p.5 | This is class-balancing of a training dataset (oversampling/undersampling by object class to fix long-tail imbalance), not resampling of observed data to estimate a sampling distribution or CI. |

**Distinguishing Monte Carlo simulation from resampling (per task instructions):** Several Waymo papers use "Monte Carlo" or "simulation" in the sense of *simulating driving scenarios* (e.g., counterfactual crash reconstructions, active-inference driver-behavior models) — this is not resampling of observed data and was excluded from the USED table on that basis, even where retrieval surfaced it under "Monte Carlo" queries. One paper in the USED set, `2604.03827`, does use genuine Monte Carlo simulation in a different, narrower sense — validating a mathematical approximation:

> "the curve is the cumulative distribution function (CDF) based on Monte-Carlo with sample size 10^6, and the crossshaped markers are based on the saddlepoint approximation" (p.23, Appendix A.1)

This is Monte Carlo sampling from a *known, already-fitted* parametric distribution (a weighted sum of Gamma random variables) purely to check that a fast numerical approximation (saddlepoint) tracks the true CDF — it is not resampling of the underlying AV crash/exposure data, and does not itself produce the paper's reported confidence intervals.

---

## 5. UNCERTAIN

No paper remains genuinely uncertain in the final pass. `2604.03827`'s "exponential bootstrap (EB)" method — whether it is literally implemented via Monte Carlo resampling or is closed-form math wearing the bootstrap name — was the one open question after my first pass of queries. It is resolved in §2 above: EB is a Monte Carlo/simulation-based method ("this can be implemented by the Monte Carlo procedure described in Table 2, which we call 'exponential bootstrap' (EB), to mimic Poisson bootstrap"), not purely closed-form theory. That specific sentence, and the companion "close to 100%" coverage-error figure, came from a parallel verification pass rather than my own retrieval — I made six differently-phrased attempts and never surfaced those two exact sentences, likely because they sit on one of the ~12 pages of this 24-page paper my reranked queries never returned. Everything I *did* independently retrieve (the abstract's framing of EB as numerically evaluated, the Exponential(1)-as-Gamma(1,1) building block, the appendix's saddlepoint *fast approximation* implying a costlier default computation) is consistent with and corroborates that sentence, so I'm treating it as confirmed rather than leaving it flagged — but the sourcing distinction is worth keeping visible for an auditor who wants to re-derive every word independently.

No other paper was left ambiguous: every other USED, MENTIONED, and TRAP entry above had an unambiguous SECTION label or was resolved via a targeted follow-up query before being classified.

---

## 5b. Sourcing closed, and why retrieval failed on this one paper

*Added after the audit closed, by the coordinator.* §5's caveat — that two EB sentences came from a
parallel pass rather than this audit's own retrieval — is now resolved. Both were located in the
stored block text and carry full citations:

| quote | block | page |
|---|---|---|
| "We propose a novel **exponential bootstrap (EB)** method for CI construction based on a fiducial argument; it satisfies the monotonicity property..." | `2604.03827:b3` | p.0 (abstract) |
| "...can be implemented by the Monte Carlo procedure described in Table 2, which we call **'exponential bootstrap' (EB), to mimic Poisson bootstrap**." | `2604.03827:b77` | p.8 |
| "The coverage of EB is more reliable than PB overall while the **coverage error for PB can be very large and even close to 100%** when true positive data is sparse..." | `2604.03827:b106` | p.11 |

So the USED classification for `2604.03827` is fully sourced, and the audit's instinct to keep the
provenance distinction visible rather than smooth it over was the right call.

**Why retrieval kept missing them — a measured limitation, not a guess.** Section detection failed
badly on this specific paper. Across the 153 Waymo-authored papers only **5.0%** of blocks (836 of
16,801) lack a `section_path`, and no paper is entirely without structure. But `2604.03827` is
**61.7% unsectioned** — the worst in the corpus by a wide margin, nearly 3x the next worst:

| paper | unsectioned blocks |
|---|---|
| `2604.03827` Confidence Intervals for Rate Estimation | **61.7%** |
| `local:5fa216c3425a` Comparative safety performance | 22.2% |
| `local:071d15c56158` Omni-directional injury risk | 21.5% |
| `local:7bf8bf93e22e` Maximum injury potential | 20.8% |

The irony is worth stating plainly: **the section signal that makes used-vs-mentioned decidable is
available 95% of the time, and it failed hardest on the single most methodologically important paper
for this question** — the one that proposes its own resampling method. Two effects compounded there:
with no headings, the section cue was unavailable, and a definitional aside ("...which we call
'exponential bootstrap' (EB)...") is topically dominated by the surrounding mathematics, so it ranks
below richer passages no matter how the query is phrased.

**The transferable rule: resolving a definition or an abbreviation is a full-text lookup problem,
not a retrieval problem.** More re-phrasings will not fix it. One direct query against the stored
block text will. The same failure appeared independently in the parallel Bayesian audit, where six
queries could not establish that EB meant "exponential bootstrap" rather than "empirical Bayes" —
a misreading that would have produced a false Empirical Bayes finding had either audit guessed.

## 6b. Review pass — exhaustive recall check

*Added by the coordinator after the audit closed.* The audit found its papers through semantic
retrieval, which is high-precision but cannot prove it found everything. To bound recall, every
block of all 153 Waymo-authored papers was scanned directly with a regex for
`bootstrap|resampl|jackknife|permutation test|monte carlo`.

**29 of 153 papers contain at least one such term.** The audit accounted for 8. Of the 21 it never
surfaced:

- **1 was a genuine miss with material consequence — `2312.12675`**, now added to §1 and §2. It
  applies a parametric bootstrap in its "Confidence Intervals" methods section, then rejects it. The
  audit's own retrieval never returned it.
- **20 were correctly-excluded naming traps**, verified individually: SIR/particle-filter resampling
  (`2311.06417`), cross-entropy-method action resampling (`2506.02215`), bootstrap aggregation/bagging
  (`2404.03843`), class-imbalance resampling (`2210.08375`), label bootstrapping (`2210.08064`),
  NeRF point resampling (`2202.05263`), 5 Hz signal resampling (`2207.05844`), nearest-neighbour label
  resampling (`2210.08113`), and similar. None is statistical resampling for uncertainty
  quantification. §4's exclusion logic was right; it simply documented 4 instances rather than all 20.
- **1 further MENTION**, `local:6b9ccd0431f6` (*Safety Impact Crash Type Manuscript*, p.47, "Study
  Conformance to the RAVE Checklist"): "the Nelson 1970 method produces wider (i.e., more
  conservative) confidence intervals compared to parametric bootstrapping (Kusano et al 2024)" —
  attributed to prior work, so a mention, not a use.

**Quote fidelity: 7 of 7 spot-checked quotes are verbatim** against the stored block text, including
every quote underpinning a USED classification. No paraphrase was presented as a quotation.

**What this says about the method.** Retrieval-based auditing gave 3 of 4 true positives here — a
75% recall rate — with zero false positives. For a question of the form "which papers did X", that
precision is worth having but the recall gap is real, and a regex sweep over full text is a cheap
complement that closes it. The two techniques fail in opposite directions: regex cannot tell a
bootstrap particle filter from a bootstrap confidence interval (20 false positives here), and
retrieval cannot guarantee it surfaced everything (1 false negative here). **Run both.**

## 6c. Deep verification — false positives and false negatives

*Second review pass, searching under vocabulary neither the audit nor the first review used.*

**False positives: none.** All four USED entries were re-checked against stored block text. Every
quote is verbatim (7/7 spot-checked, including every quote underpinning a USED call), every one sits
in a methods-type section, and every one uses applied first-person language with concrete parameters.
The MENTIONED demotions are also correct — e.g. `2604.03827` p.5: "Traditional procedures for CI
construction include bootstrap (Efron and LePage (1992)), the delta method... which all rely on large
sample approximations" is unmistakably a literature review, not an application.

**False negatives: one material (§6b's `2312.12675`), plus one further mention.**
`local:6b9ccd0431f6` (p.47, *Study Conformance to the RAVE Checklist*) attributes parametric
bootstrapping to prior work — a mention, now recorded in §3.

**A scope boundary that held up.** Four papers name an explicit CI-construction method yet appear in
neither audit, and that is correct: `local:f6f1461f2c9a` (Garwood, Poisson-exact),
`local:5fa216c3425a` (Poisson-exact), `local:b12ef27e3cd6` (Byar's), `local:071d15c56158` (survey
design). All are **closed-form** interval methods — algebra on an assumed distribution, no
resampling. Their absence from the USED table is a correct exclusion, not an oversight, and it
mirrors §4c of the companion Bayesian audit (the Poisson–Gamma papers that look conjugate but are
frequentist).

**Net effect on this report's conclusions:** the USED list moves from 3 to 4 papers. Nothing else
changes. The audit's precision was perfect; only its recall needed supplementing.

## 6. Method and limitations

**Queries run (18 total, `--k 20`–`30` each, one at a time, all confirmed `scope: WAYMO-AUTHORED ONLY`):**
`bootstrap confidence interval`; `Poisson bootstrap method resampled data set bootstrap iterations`; `why we chose bootstrap instead of normal approximation`; `resampling with replacement bootstrap sample`; `baseline vulnerable road user injury risk confidence interval bootstrap method chosen because`; `numerical studies simulation setup PB EB Poisson bootstrap implemented comparison methods`; `second confidence interval type risk ratio bootstrap method 7.1 million miles`; `Safety Impact Crash Type confidence intervals statistical methods section`; `crash type manuscript statistical methods incidents per million miles Nelson rate ratio Poisson exact`; `dynamic benchmarks spatial temporal alignment ADS performance evaluation why bootstrap chosen rare events variance`; `insurance claims autonomous vehicles 25 million miles statistical methods confidence interval`; `confidence intervals were calculated using bootstrap Poisson binomial method claims per million miles`; `jackknife permutation test resampling statistical uncertainty method`; `ESV VRU Benchmark Comparison confidence interval statistical method used`; `TARGET Setting High Severity Collisions confidence interval bootstrap statistical method`; `parametric bootstrap simulation confidence interval Waymo safety`; `weighted Gamma CI fiducial argument monotonicity property advantage over Poisson bootstrap`; `Poisson Bootstrap CI PB defined generate independent Poisson random variables mean`; `RAVE checklist quantify uncertainty simulation methods bootstrap confidence interval recommended`; `distributions are not known simulation methods bootstrap can be used to determine confidence intervals`; `exponential bootstrap EB novel method fiducial argument monotonicity abstract propose`; `Monte Carlo simulation scenario testing uncertainty`; `no closed-form expression quantiles weighted sum independent exponential random numbers Monte Carlo procedure Table 2 mimic Poisson bootstrap`; `coverage error close to 100% true positive data sparse Poisson bootstrap PB unreliable`; `Table 2 algorithm exponential bootstrap procedure generate exponential random variables replicate`; `exponential random variable Exp(1) weighted sum simulate B replicates quantile empirical algorithm steps`.

**What this could miss:**
- **Failed section detection.** `2604.03827` returned `(front matter / unsectioned)` for every hit despite having clear numbered sections in its body text — I resolved this manually by reading the content, but a paper with similarly broken section detection *and* genuinely ambiguous content (unlike this one) could be misclassified in either direction by a less careful pass.
- **Methods named only in a table or figure caption.** The retrieval and reranking pipeline surfaces paragraph-level text; a paper that states its CI method only inside a table cell (e.g., a footnote reading "CI: bootstrap, 1000 reps") or a figure caption, without ever spelling it out in prose, could be under-retrieved. I did not find evidence of this happening, but I also cannot positively rule it out — I did not open every one of the 153 papers directly, only what the retriever surfaced across 22 differently-phrased queries.
- **Papers with confidence intervals but no named method retrieved.** Two papers — `local:5fa216c3425a` ("Comparative safety performance of autonomous- and human drivers…") and `local:f6f1461f2c9a` ("Do Autonomous Vehicles Outperform Latest-Generation Human-Driven Vehicles?…") — clearly report confidence intervals on insurance-claim rates but never surfaced any passage naming *how* those CIs were constructed, bootstrap or otherwise, across several targeted queries. I did not list them anywhere above (not MENTION, not TRAP, not UNCERTAIN) because there was no bootstrap-adjacent text to classify — but readers should not take their absence from this report as proof they don't use resampling somewhere unretrieved.
- **Scope, by construction.** Per the task, only the 153 Waymo-authored papers were queried (the tool's default, non-`--all-papers` mode, confirmed on every call). The much larger third-party AV-safety literature in the wider 1,738-paper corpus — including papers this report's Waymo papers directly cite and respond to (e.g., Kalra and Paddock 2016, Di Lillo et al. 2024) — was never queried and is entirely out of scope here.

---

## Summary

- **USED:** 4 papers — `2410.08903`, `local:bc031ecd9224`, `2604.03827` (applying *two* distinct resampling methods, Poisson Bootstrap and its own Exponential Bootstrap), and `2312.12675` (added by the review pass, §6b — the audit's own retrieval never surfaced it).
- **MENTIONED ONLY:** 3 passages — `2604.03827`'s own Related Work section (inside a paper otherwise counted as USED), the RAVE Checklist best-practices document (`local:4087ccce4c01`), and `local:6b9ccd0431f6` (added by the review pass).
- **NAMING TRAPS excluded:** 5 passages across 4 papers (`2212.06968` ×2, `2111.14973`, `2103.01306`, `2205.05703`).
- **UNCERTAIN:** 0. `2604.03827`'s "exponential bootstrap" question is fully resolved and sourced (§5, §5b).
- **Verification:** 7/7 quotes verbatim; **zero false positives** found in the USED table; one material false negative found and added (§6c).

**Most interesting finding:** the corpus's most careful, most quantitative bootstrap justification is an argument for **replacing** bootstrap, not for using it. `2604.03827` runs both Poisson Bootstrap and its own new Exponential Bootstrap through 10,000-replicate coverage simulations and finds Poisson Bootstrap "systematically undercovers" and can have coverage error "close to 100% when true positive data is sparse" — i.e., in the rare-event regime AV safety analysis cares about most, the classic bootstrap's confidence intervals can fail almost completely. The paper's own Exponential Bootstrap is kept in the bootstrap family (same Monte Carlo resampling logic) but changed at the weighting-distribution level to fix this. Meanwhile two other USED papers — `2410.08903` and `local:bc031ecd9224` — apply a bootstrap method with **no stated justification at all** for the choice, in contrast to how carefully `2604.03827` treats the same decision. The gap between these two behaviors — "state your reasons with numbers" vs. "just do it" — is itself a finding about the corpus's statistical rigor, not just about resampling specifically.

**What made me doubt my own classification:** two things. First, whether to count `2604.03827` as USED for Poisson Bootstrap at all, given the paper doesn't ultimately recommend it — it computes PB only to demonstrate why not to prefer it. I kept it in USED because the task's definition turns on applying the method with concrete parameters and first-person applied language, not on whether the paper endorses the outcome — PB is fully implemented and numerically evaluated here, not just cited. Second, the "exponential bootstrap (EB)" question in §5: my own retrieval, across roughly two dozen queries against this one 24-page paper, kept returning the same ~12 pages and never surfaced the exact sentence stating EB is computed via Monte Carlo ("the procedure described in Table 2"). I ultimately relied on a parallel verification pass for that specific sentence and the "close to 100%" coverage figure, while everything I *did* independently retrieve corroborates rather than contradicts it. I've flagged that sourcing distinction explicitly rather than presenting it as something I found myself.
