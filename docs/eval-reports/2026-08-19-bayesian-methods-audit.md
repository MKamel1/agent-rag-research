# Bayesian Methods Audit — Waymo-Authored Papers

**Question:** Which Waymo-authored papers actually *used* fully Bayesian or empirical-Bayes statistical methods, and why did they say they chose that approach?

**Scope:** 153 Waymo-authored papers only (of 1,738 total in the corpus). Every query below was run with the corpus tool's default scope filter (`--all-papers` was never passed), and every result printed `scope: WAYMO-AUTHORED ONLY`, confirmed on every run. Nothing from the broader 1,738-paper corpus appears below.

**Jargon note for this report, defined once:**
- **Fully Bayesian inference** — you write down a *prior* (a probability distribution expressing what you believed before seeing data), combine it with the data's likelihood, and compute a *posterior* distribution (updated belief). Answers come with a **credible interval** (e.g. "95% probability the true value is in this range").
- **Empirical Bayes** — a shortcut version of the above: instead of picking the prior's parameters (hyperparameters) by hand, you estimate them *from the same data* (often pooled across many groups). It typically shows up as **shrinkage**: individual noisy estimates get pulled toward a shared average, "borrowing strength" from the whole dataset to stabilize the estimate for any one group.
- **Frequentist confidence interval** — a different paradigm: no prior belief is stated; the interval is constructed so that, if you repeated the sampling process many times, X% of such intervals would contain the true value. Confidence intervals and credible intervals can look numerically identical in simple cases (e.g. Poisson-Gamma) without being the same thing philosophically — this is the single biggest trap in this corpus (see Section 4).

---

## 1. USED — FULLY BAYESIAN

| paper_id | title | what exactly was Bayesian | section | page |
|---|---|---|---|---|
| `2411.17826` | Rate-Informed Discovery via Bayesian Adaptive Multifidelity Sampling | A **Gaussian Process (GP) prior** placed directly on the unknown performance function θ(x) over embedded driving scenarios ("A Gaussian process (GP) imposes a prior belief on an unknown random function θ... through its mean function μ(x)... and covariance function k(x,x′)"), updated with observed simulation outcomes; the acquisition function that selects the next scenario to evaluate is driven by the posterior predictive variance of this GP. | "2 Background and related work" (GP prior definition) and "3 Bayesian adaptive multifidelity sampling" (their own method) | p.1, p.3 |

Only one Waymo-authored paper in the corpus clears the bar for genuinely *doing* fully Bayesian statistics on its own data (as opposed to modeling someone else's cognition as Bayesian, or using Bayesian-looking machinery for a non-statistical task). Authors: Aman Sinha, Payam Nikdel, Supratik Paul, Shimon Whiteson — Waymo, LLC.

Verbatim, from the Background section (p.1, "2 Background and related work"):
> "A Gaussian process (GP) [42] imposes a prior belief on an unknown random function θ : X ⊆ R^d → R through its mean function μ(x) (for convenience usually set to zero) and covariance function k(x,x′)."

And the method section itself is literally titled "3 Bayesian adaptive multifidelity sampling" (p.3), which is where the GP prior is fit to the empirical distribution of logged driving run-segments and used to drive an active-sampling acquisition function.

## 2. USED — EMPIRICAL BAYES

**Null result — see §6c for an important qualification of this claim.** No Waymo-authored paper in the corpus was found to use empirical Bayes (hyperparameters of a prior estimated from the pooled data, typically producing shrinkage toward a group mean) as its statistical method of analysis.

Queries run in direct pursuit of this (all returned no qualifying hits): "empirical Bayes shrinkage estimator", "hierarchical model shrinkage toward global mean borrowing strength across sites", "zero counts rare events handling small sample stabilize estimate shrinkage", plus general coverage from the "Bayesian inference" and "conjugate prior" queries below. The one candidate that surfaced — an "EB" abbreviation inside `2604.03827` — was **resolved after this audit and is not empirical Bayes**: EB stands for *exponential bootstrap*, the authors' own proposed method. See Section 6. **This null result therefore carries no residual doubt.**

## 3. Justification, per USED paper

### `2411.17826` — Rate-Informed Discovery via Bayesian Adaptive Multifidelity Sampling

Verbatim, from the Abstract (p.0):
> "Ensuring the safety of autonomous vehicles (AVs) requires both accurate estimation of their performance and eficient discovery of potential failure cases. This paper introduces Bayesian adaptive multifidelity sampling (BAMS), which leverages the power of adaptive Bayesian sampling to achieve eficient discovery while simultaneously estimating the rate of adverse events. BAMS prioritizes exploration of regions with potentially low performance, leading to the identification of novel and critical scenarios that traditional methods might miss."

And from the Introduction (p.0), the underlying pain point being addressed:
> "Evaluating the long tail of safety issues is particularly dificult: as the AV's performance improves, safety-related issues become rarer and more dificult to discover. In turn, this makes improving the planner increasingly challenging, as identifying failure cases is the first step towards addressi[ng them]"

**Reading of the justification:** the stated reason for going Bayesian is *sample efficiency under rarity* — as failures get rarer, a method that can use its posterior uncertainty to actively choose which of a huge number of run-segments to spend expensive simulation/evaluation budget on (rather than sampling passively/uniformly) finds more of the rare failure modes per unit of compute. This matches the operator's expected "small-sample / rare-event" justification category cleanly.

## 4. BAYESIAN-SOUNDING BUT NOT BAYESIAN STATISTICS

This corpus is genuinely full of these traps, and separating them out is itself the main finding of this audit. Three distinct traps showed up.

### 4a. Active inference / free-energy models of *human driver cognition* (8 papers)

| paper_id | title | section | page |
|---|---|---|---|
| `2303.15201` | Learning An Active Inference Model of Driver Perception and Control | I. Introduction / II. POMDP Model / IV. Active Inference Specification | p.0–8 |
| `2305.07733` | Measuring Surprise in the Wild | 1 Introduction / 2 Results / 4 Methods | p.1, p.4, p.14 |
| `2604.19838` | Resolving space-sharing conflicts in road user interactions through uncertainty reduction | Minimizing Variational Free Energy / Minimizing Expected Free Energy | p.18 |
| `2208.08651` | Modeling road user response timing in naturalistic settings: a surprise-based framework | 2.2 A framework for modeling response timing / 5. A computational implementation | p.2, p.10 |
| `2311.06417` | Resolving uncertainty on the fly: Modeling adaptive driving behavior as active inference | Active Inference and Expected Free Energy / Particle-Based Algorithm | p.3, p.5 |
| `2506.02215` | Active inference as a unified model of collision avoidance behavior in human drivers | Perception / Model principles | p.22–23 |
| `local:5b903ab148a7` | World Model Learning from Demonstrations with Active Inference | 2.2 A POMDP Formulation of Active Inference | p.2 |
| `local:b3dd74970ec8` | IWAI poster, Engstrom et al. final | (poster, front matter) | p.0 |

**Plain-English distinction:** these papers use genuinely Bayesian mathematics — priors, posteriors, belief updates (one, `2506.02215`, even says outright: "we use standard Bayesian updating: q(s_t) ∝ p(o_t|s_t)q(s_t−1)", p.23) — but the thing being modeled as "Bayesian" is a *simulated human driver's brain*, not the authors' own statistical analysis of their study's results. The claim these papers make is "human drivers behave *as if* they run Bayesian belief updating" (the "Bayesian brain hypothesis," cited explicitly in `2303.15201` p.0: "The Bayesian brain hypothesis posits that the human brain uses the information provided by sensory data to update a representation of the world..."). That is a scientific hypothesis about cognition, tested by fitting the model's outputs to observed driving behavior — it is not the authors placing a prior on an unknown parameter of their own dataset and reporting a posterior/credible interval for it. Per the operator's framing, this is "a Bayesian model of human cognition, not the authors doing Bayesian statistical inference on their own data," and I classify it accordingly — none of these 8 papers appear in Sections 1 or 2 above.

### 4b. Particle filters — recursive Bayesian *state estimation*, not Bayesian *data analysis*

| paper_id | title | section | page |
|---|---|---|---|
| `2212.06968` | Particle-Based Score Estimation for State Space Model Learning in Autonomous Driving | 3.2 Particle Filtering / 4 Score Estimation using Particle Methods | p.2–5 |

**Plain-English distinction:** a particle filter tracks a moving, hidden quantity (here, the position/pose of another road user the AV can only partially observe) by repeatedly updating a probability distribution over "where is it now" as new sensor readings arrive — mathematically this recursive update *is* Bayes' rule applied at every timestep. But it is being used as an engineering tool inside the AV's perception stack to estimate *where a car is right now*, not as a method for the paper's authors to draw statistical conclusions from a dataset (no prior is placed on a study parameter, no posterior distribution over an effect size is reported). `2311.06417` (already listed in 4a) also uses a particle-based belief representation for the same reason — belief tracking of a simulated agent's internal state, not statistical inference on the authors' own data.

### 4c. The Poisson–Gamma "exact interval" trap — looks like a Bayesian conjugate update, is actually frequentist

Several Waymo crash-rate papers construct confidence intervals for event *rates* (crashes per million miles) using the **Gamma distribution's quantile function**. This is worth flagging explicitly because the math is *identical in form* to Bayesian conjugate updating (a Gamma prior combined with a Poisson likelihood yields a Gamma posterior) — but every one of these papers frames it as an **exact frequentist confidence interval**, derived from the mathematical relationship between the Poisson and Gamma/chi-squared distributions, not from any stated prior belief. None of the passages below contain the words "prior," "posterior," or "Bayesian."

| paper_id | title | method named | section | page |
|---|---|---|---|---|
| `2312.12675` | Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million Miles | "Poisson exact model" via Gamma quantile function | Confidence Intervals | p.6 |
| `local:6b9ccd0431f6` | Safety Impact Crash Type Manuscript (56.7M miles) | Clopper–Pearson limits on ratio of two Poisson rates | Statistical Testing | p.9 |
| `local:79c782071ad2` | High-resolution urban fatal crash rate benchmarks | Poisson–chi-squared relationship | Confidence intervals | p.4 |
| `local:bc031ecd9224` | Baseline vulnerable road user injury risk in multiple U.S. dense urban driving environments | Byar's method (exact Poisson approximation) | Collision rates | p.3 |
| `2410.08903` | Dynamic Benchmarks: Spatial and Temporal Alignment for ADS Performance Evaluation | Poisson bootstrap | Confidence Intervals | p.6 |
| `2604.03827` | Confidence Intervals for Rate Estimation with Importance Sampling in AV Evaluation | "Weighted Gamma CI," explicitly derived "in the spirit of the fiducial argument" (Fisher 1935) | §5.2 Weighted Gamma CI | p.7 |

`2604.03827` deserves a specific callout: it is the corpus's most statistically sophisticated confidence-interval paper (by Aiyou Chen, Ruixuan Rachel Zhou, Joseph J. Lee, Nicholas Chamandy, Henning Hohnhold — Waymo LLC), and it explicitly grounds its main proposed method in Fisher's **fiducial argument**, not in Bayesian priors. Fiducial inference is a distinct, historically contested inferential paradigm that Fisher proposed as an *alternative* to Bayesian inference precisely because it avoids specifying a prior — so despite the superficial resemblance (Gamma distributions, quantile-based interval construction), this paper's own words place it outside Bayesian statistics. It does, however, contain an unresolved wrinkle — see Section 6.

## 5. MENTIONED ONLY

**Near-null result.** I did not find a clean example of a Waymo-authored paper that name-drops "Bayesian"/"prior"/"posterior" in a Related Work or Introduction section while doing something entirely non-Bayesian in its own Methods — the pattern the operator specifically warned about (e.g. the `2212.06968` two-face example). What I found instead is that essentially every Bayesian-flavored retrieval hit belongs to one of three buckets already covered above: the one genuinely-Bayesian paper (§1), the active-inference/particle-filter papers where the Bayesian framing runs through the *entire* paper rather than being confined to a "prior work" aside (§4), or the frequentist crash-rate papers that never use Bayesian language at all (§4c).

The closest thing to a "mention" is the citation of the **Bayesian brain hypothesis** in `2303.15201`'s Introduction (p.0): "The Bayesian brain hypothesis [3], [4] posits that the human brain uses the information provided by sensory data to update a representation of the world..." — but this is the paper's foundational premise, developed and used throughout the rest of the paper (see §4a), not a passing citation that gets dropped. I have therefore left it in §4a rather than padding this table with it.

| paper_id | title | section | why classified "mention, not use" |
|---|---|---|---|
| *(none)* | — | — | — |

## 6. RESOLVED — the "EB" abbreviation in `2604.03827`

*This section was headed UNCERTAIN when the audit closed. It was resolved immediately afterwards by
reading the paper's full stored text directly, rather than through retrieval. The original reasoning
is kept below the answer, because the way retrieval failed here is worth knowing.*

**EB = "exponential bootstrap". It is NOT empirical Bayes.** It is the authors' own proposed method,
and it is a *resampling* technique, so it belongs to the bootstrap/resampling audit rather than this
one. Verbatim from the paper:

> "We propose a novel **exponential bootstrap (EB)** method for CI construction based on a fiducial
> argument; it satisfies the monotonicity property, while novel extensions of some existing methods
> do not."

> "...there is no closed-form expression for quantiles of the weighted sum of independent exponential
> random numbers, but this can be implemented by the Monte Carlo procedure described in Table 2,
> which we call **'exponential bootstrap' (EB), to mimic Poisson bootstrap**."

So the companion abbreviations are **PB = Poisson bootstrap**, **EB = exponential bootstrap**, and
**GP/GO = Gamma-based reference methods**. Every one is frequentist. Section 2's null result stands
with no caveat, and this paper stays out of Sections 1 and 2.

**Why retrieval could not close this, which is the transferable lesson.** Six targeted queries
across a 24-page paper never returned the two sentences that define the term, even though both sit
in the abstract and the methods section. Chunk-level semantic search retrieves passages that are
*about* a query's topic; a definitional aside ("...which we call 'exponential bootstrap' (EB)...")
is topically dominated by the surrounding mathematics, so it ranks below richer passages every time.
The audit's inference from partial evidence was sound — it correctly reasoned from
"EB is a special case of the paper's own fiducial Weighted Gamma CI" that EB was probably not
Bayesian — and it correctly refused to convert that into a claim. **Resolving an abbreviation is a
full-text lookup problem, not a retrieval problem**, and the fix is one query against the stored
text rather than more attempts through the search interface.

The original uncertain-state reasoning, preserved:

> | paper_id | title | what I tried |
> |---|---|---|
> | `2604.03827` | Confidence Intervals for Rate Estimation with Importance Sampling in Autonomous Vehicle Evaluation | See below. |
> 
> `2604.03827` compares several confidence-interval construction methods under abbreviations **PB**, **GP/GP2m**, **GO2m**, and **EB/EB2/EB2m** (e.g. p.12: "The results show that EB2m and GO2m exhibit similar performance... EB2 and PB are nearly identical... PB systematically undercovers... EB2 and GP2m is very close to the nominal level..."). "EB" is exactly the abbreviation one would expect for "Empirical Bayes," which is a real, published family of confidence-interval methods for rare-event/small-area rate estimation.
> 
> I ran four separate follow-up queries specifically to find the sentence that defines "EB" (`"empirical Bayes EB confidence interval Gamma Poisson rate estimation"`, `"EB weighted Gamma confidence interval definition abbreviation method"`, `"Section 6 numerical studies method abbreviations PB GP EB GO comparison table"`, `"we compare the following CI construction methods PB GP EB GO Poisson bootstrap"`) and retrieved roughly 15 distinct chunks from this 24-page paper, but never the passage that spells out what EB stands for. The one substantive clue (p.21, Appendix A.1): "Since EB can be treated as a special realization of the weighted Gamma CI where each weight appears at least once..." tells us EB is a *special case* of the paper's own Weighted Gamma CI method — which the paper itself grounds in Fisher's fiducial argument, not in a stated prior (see §4c). That points toward EB **not** being Empirical Bayes in the classical sense, but I cannot rule out that it is a Bayesian benchmark method drawn from the cited literature (Fay & Feuer 1997; Fay & Kim 2017; Ng, Filardo & Zheng 2008; etc.) rather than the authors' own proposed method.
> 
> Because the paper's own method is explicitly non-Bayesian (fiducial) and the word "Bayesian" never appears in any retrieved passage from this paper, I am **not** including it in Section 1 or 2. But because I could not positively rule out an Empirical Bayes reading of "EB," I am not filing it under Section 4 either. Flagging it here as unresolved rather than guessing.

## 6b. Review pass — exhaustive recall check

*Added by the coordinator after the audit closed.* Same check as the companion bootstrap audit: every
block of all 153 Waymo-authored papers was regex-scanned for
`empirical bayes|posterior distribution|prior distribution|credible interval|MCMC|markov chain monte
carlo|variational inference|conjugate prior|shrinkage`.

**14 papers contain at least one such term; the audit accounted for 11.** The 3–6 not surfaced were
inspected individually and are all machine-learning uses of Bayesian vocabulary, not Bayesian data
analysis:

| paper | term | what it actually is |
|---|---|---|
| `2304.02163` GINA-3D | "approximates the posterior Pr(z\|x)" | a variational autoencoder's latent posterior — ML architecture |
| `2004.00831` Progressive Population Based Augmentation | "search space shrinkage" | shrinking a hyperparameter search space; unrelated to statistical shrinkage |
| `2008.08294` TNT | "estimated a Bayesian posterior distribution of destinations" | **Related Work**, attributed to reference [28] — a MENTION, and arguably belongs in §5 |
| `2309.14003`, `1910.05449`, `2212.03267` | scattered | ML-model posteriors / probabilistic heads |

**No finding is overturned.** Fully Bayesian remains 1 (`2411.17826`), empirical Bayes remains **0**,
and the resolved EB abbreviation (§6) removes the only route by which that zero could have been
wrong. The one substantive addition is that §5's "essentially null" MENTIONED-ONLY result understates
things slightly: `2008.08294` is a clean mention-in-related-work example of exactly the pattern the
audit was asked to separate.

**The `shrinkage` keyword is worth a caution for anyone re-running this.** It is the standard search
term for empirical Bayes, but in an ML-heavy corpus it matches "search space shrinkage" and similar
far more often than it matches statistical shrinkage. A keyword-only audit would report a false
empirical-Bayes hit here; the section-plus-context discipline is what prevents that.

## 6c. Deep verification — the "empirical Bayes = 0" claim, qualified

*Added by the coordinator's second, deeper review pass, which deliberately searched for methods
under vocabulary NEITHER this audit nor the first review used — because a keyword list can only find
what its author already thought of. Six families were swept across all 16,801 blocks: resampling-core,
resampling-adjacent (cross-validation, BCa), **EB-disguised** (random/mixed effects, partial pooling,
BLUP, multilevel, borrowing strength, James-Stein), bayes-core, bayes-compute (MCMC/Gibbs/HMC/Stan/
PyMC/JAGS), and EB-explicit (hyperprior, type-II ML, marginal likelihood).*

**The headline survives, with one qualification that should be stated rather than buried.**

### What held

- **No paper anywhere in the 153 contains the literal phrase "empirical Bayes."** All three
  `EB-explicit` matches are "marginal likelihood" in unrelated senses (`2212.06968` state-space
  likelihood, `2104.09959` query likelihood, `local:5b903ab148a7` an agent preference model).
- **MCMC/Gibbs/HMC/Stan/PyMC/JAGS appear in exactly one paper — `2411.17826`**, already the
  identified fully-Bayesian entry. No hidden Bayesian computation anywhere else.
- **`2411.17826` is not a false positive.** The sharpest risk was that it is Bayesian *optimisation*
  machinery (like the particle filters excluded in §4b) rather than Bayesian data analysis. It is
  not: "Our formalism begins by first considering a **Bayesian estimator for the rate of adverse
  events**... we **impose a GP prior** over it" (p.3), and "The marginal p̂γ(θn) is **an estimator of
  the rate of adverse events**" (p.3). The posterior yields the study's own reported estimand. The
  §4b boundary — machinery whose output feeds downstream vs. inference that produces the reported
  quantity — is coherent and correctly applied.

### The qualification — `local:03e2dfdfa816` uses mixed-effects models, and this audit never saw it

`local:03e2dfdfa816` (Terranova et al., *Kinematic characterization of micro-mobility vehicles during
evasive maneuvers*) applies GLMMs in its methods section. Verbatim (p.8, §*2.Method > 2.4. Data
Analysis*):

> "**Generalized linear mixed-effect models** were used to assess the significance of the MMV Type
> (eight different MMV types and the pedestrian) and MMV Power Source factors (Electric vs
> Traditional) on the relevant metrics calculated from the data (Table 3), controlling for
> participant sex and maneuver speed."

Why this bears on the claim: **a mixed model's predicted random effects (BLUPs) are formally
empirical-Bayes estimators.** They shrink each group's estimate toward the population mean by an
amount determined by variance components estimated *from the data itself* — which is precisely the
empirical-Bayes construction, and precisely what the "borrowing strength" and "shrinkage" queries
were meant to catch. This paper's title extracted as "1", so it is also invisible to any
title-based search.

**The verdict, stated precisely rather than as a bare zero:**

| claim | verdict |
|---|---|
| No Waymo paper *adopts empirical Bayes as its stated method* | **TRUE** — no paper names it, frames its analysis that way, or discusses a prior |
| No Waymo paper uses machinery that is *formally* empirical Bayes | **FALSE** — `local:03e2dfdfa816`'s GLMM random effects are EB shrinkage estimators |

The authors use the GLMM for frequentist significance testing (Tukey HSD post-hoc, α = 0.05), not to
produce shrunken group estimates, and no statistician reading the paper would describe it as an
empirical-Bayes analysis. So §2's null result is defensible — but it should read "no paper adopts
empirical Bayes," not "no paper does anything empirical-Bayes-adjacent," and this paper should have
been surfaced and adjudicated rather than never considered.

### One further MENTION this audit missed

`local:79c782071ad2` (*High-resolution urban fatal crash rate benchmarks*), p.9, §*Potential for
model-based benchmarking*: "Furthermore, parametric modeling provides valuable smoothing benefits for
highly granular data slices. By **'borrowing strength'** across the entire dataset, a model can
stabilize estimates in data-poor strata where empirical counts might otherwise be highly volatile."

This is the canonical empirical-Bayes phrase, and it is a textbook MENTION: the section is explicitly
hypothetical ("**may** become the better option", "**If** future researchers pursue this model-based
approach"), and the paper states it used stratification instead, which "avoids the parametric
assumptions required by unified risk models." A keyword audit would have scored this as a hit. The
used-vs-mentioned discipline is exactly what prevents that — but only if the passage is retrieved at
all, and this one never was.

## 7. Method and limitations

**Queries run (11 total, each confirmed `scope: WAYMO-AUTHORED ONLY`):**
1. "Bayesian inference posterior distribution"
2. "empirical Bayes shrinkage estimator"
3. "empirical Bayes EB confidence interval Gamma Poisson rate estimation"
4. "EB weighted Gamma confidence interval definition abbreviation method"
5. "Section 6 numerical studies method abbreviations PB GP EB GO comparison table"
6. "we compare the following CI construction methods PB GP EB GO Poisson bootstrap"
7. "hierarchical model shrinkage toward global mean borrowing strength across sites"
8. "Markov chain Monte Carlo MCMC posterior sampling credible interval"
9. "why we chose a Bayesian approach motivation rare events sample efficiency prior knowledge"
10. "particle filter recursive Bayesian state estimation posterior update"
11. "Bayes factor Bayesian model comparison naive Bayes classifier Bayesian network"
12. "variational inference approximate posterior ELBO evidence lower bound"
13. "conjugate prior sensitivity analysis uninformative prior choice of prior distribution parameter"
14. "zero counts rare events handling small sample stabilize estimate shrinkage"
15. "Confidence Intervals Rate Estimation Importance Sampling Bayesian frequentist coverage abstract objective"
16. "Dinparastdjadid O'Kelly Schumann active inference free energy driver belief"
17. "credible interval 95% Bayesian credible region highest posterior density"

(17 queries were actually run — I kept going past the initial minimum list once the "EB" ambiguity in `2604.03827` surfaced, to try to resolve it before falling back to Uncertain.)

**Coverage achieved against the requested phrase list:** Bayesian inference ✓, empirical Bayes ✓, prior distribution ✓, posterior distribution ✓, credible interval ✓ (explicit null result — no Waymo paper uses this term), Markov chain Monte Carlo/MCMC ✓ (explicit null result), hierarchical model shrinkage ✓ (null result), borrowing strength across groups ✓ (null result), conjugate prior Gamma Poisson ✓ (found, but classified as frequentist fiducial/exact-interval, not Bayesian — §4c), Bayes factor ✓ (null result), variational inference ✓ (found only inside active-inference "variational free energy," §4a), uninformative prior / sensitivity analysis ✓ (the one "sensitivity analysis" hit found, in the Safety Impact Crash Type Manuscript, was about underreporting-correction sensitivity, unrelated to priors), shrinkage estimator toward global mean ✓ (null result).

**What could be missed:**
- **Retrieval, not exhaustive search.** This is a semantic-similarity retrieval system over `--k 30` per query; a paper using unusual terminology for a Bayesian method (e.g., calling a posterior mean an "updated estimate" without ever using the word "Bayesian," "prior," or "posterior") could in principle be missed by every query phrasing tried here.
- **Chunking cuts off mid-sentence.** Several passages, especially in `2604.03827`, were truncated at roughly 600 characters, which is precisely why the "EB" definition could not be pinned down — the defining sentence may simply not have been surfaced as a discrete, complete chunk by any of the six queries targeted at it.
- **`(front matter / unsectioned)` sections.** `2604.03827`'s entire main text returned with SECTION `(front matter / unsectioned)` rather than named subsections (its Methods subsections like "5.2 Weighted Gamma CI" only appeared correctly labeled in a few chunks) — this is a section-detection failure on a PDF with heavy inline math, not a signal about the paper's content, and it is the reason the paper needed several follow-up queries rather than being resolved by SECTION labeling alone, per the audit's own ambiguous-section protocol.
- **Scope is Waymo-authored papers only, by construction.** The 1,738-paper corpus contains substantial third-party AV-safety and traffic-safety literature (including, plausibly, genuine empirical-Bayes crash-rate work from the broader road-safety statistics field, e.g., Empirical Bayes methods are a textbook approach in highway safety "black-spot" analysis). None of that is in scope here, and its absence from this report says nothing about whether empirical Bayes is used *anywhere* in AV safety research — only that it was not found among the 153 papers Waymo itself authored.

---

## Summary

| Category | Count |
|---|---|
| USED — Fully Bayesian | 1 (`2411.17826`) |
| USED — Empirical Bayes | 0 as an adopted method — **qualified, see §6c** |
| Bayesian-sounding, not Bayesian statistics — active inference (human cognition modeling) | 8 |
| Bayesian-sounding, not Bayesian statistics — particle filter (state estimation) | 1 |
| Bayesian-sounding, not Bayesian statistics — Poisson/Gamma frequentist "exact interval" trap | 6 |
| Mentioned only | 2 added by review (`local:79c782071ad2`, `2008.08294`); §5 originally near-null |
| Uncertain | **0** — `2604.03827`'s "EB" resolved as *exponential bootstrap* (§6) |

**Most interesting finding:** out of 153 Waymo-authored papers and 17 differently-phrased queries chasing every flavor of Bayesian language, exactly **one** paper does fully Bayesian statistics in the classical sense (`2411.17826`, a Gaussian-process-based active-sampling method for finding rare AV failure cases), **zero** do empirical Bayes, and the single largest cluster of "Bayesian" hits (8 papers) is entirely about modeling *human drivers'* brains as Bayesian reasoners — a completely different use of the word from what the question was asking about. The corpus's most statistically dense paper on confidence intervals for rare-event rates (`2604.03827`) explicitly rejects the Bayesian framing in favor of Fisher's fiducial argument, which is a genuinely surprising choice for a 2026 paper given how thoroughly Bayesian methods have displaced fiducial inference elsewhere in applied statistics. The "EB" abbreviation in that paper is now resolved (§6): it means *exponential bootstrap*, not empirical Bayes, so the zero above stands on the adopted-method reading.

**What made me doubt my own classification:** the unresolved "EB" abbreviation in `2604.03827` is the one place I could not close the loop — retrieval kept surfacing the same ~15 chunks regardless of query phrasing, suggesting the defining sentence either sits in a table/caption that didn't get chunked as retrievable text, or was cut off by the ~600-character truncation right at the point it mattered. I chose to report this honestly as Uncertain rather than either padding the Empirical Bayes table or confidently declaring it frequentist — a reader with access to the original PDF (page 9–10, Section 6, or the abbreviation glossary if one exists) could resolve this in under a minute.
