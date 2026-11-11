# Missing Data in the Waymo Safety Papers

*What the corpus actually says about missing data, MCAR/MAR/MNAR, deletion and imputation.
Retrieved 2026-08-25 from the local `waymo_av_safety` corpus. Every claim carries the verbatim
passage it came from.*

Companion to [`WAYMO-SAMPLING-METHODS-REPORT.md`](WAYMO-SAMPLING-METHODS-REPORT.md).

---

## How this was searched, and over what

The corpus holds **157 papers tagged Waymo-authored by the curated tier** — an enumerated list built
from Waymo's own publication index, not a keyword guess (`fixtures/waymo/waymo_authored_ids.txt`).
Rather than rely on semantic retrieval alone for a question where *absence* is part of the answer, I
ran a literal full-text sweep over the stored markdown of all 157 papers, then confirmed with
semantic search that nothing else surfaced.

| Term | Papers containing it (of 157) |
|---|---|
| `MCAR` (abbreviation) | **0** |
| `MAR` / `missing at random` | **0** |
| `MNAR` / `missing not at random` | **0** |
| `missing completely at random` (spelled out) | **1** |
| `multiple imputation` | 2 |
| `imputation` | 5 |
| `imputed` | 6 |
| `missing data` | 8 |
| `missingness` | 4 |
| `complete case` | 3 |
| `chained equations` (MICE) | 2 |
| `Rubin` | 5 (only **1** for missing data — see false positives) |
| `listwise` | 1 (false positive) |
| `pairwise deletion`, `hot deck`, `last observation carried forward` | 0 |

**Headline finding.** The MCAR/MAR/MNAR taxonomy is essentially absent from this literature. The
phrase appears exactly once, spelled out, in one paper — and it appears there in order to be
*rejected*, as the justification for not using complete-case analysis. No paper in the corpus tests
for MCAR, names MAR as an assumption, or discusses MNAR sensitivity analysis (pattern-mixture or
selection models). Two papers run multiple imputation via MICE; several more use one-off weighting
imputation for a single field; several delete incomplete cases and say so in their limitations.

### False positives, stated up front

- `listwise` in **StarNet: Targeted Computation for Object Detection in Point Clouds** (arXiv
  1908.11069) is a bibliography entry for Cao et al., *"Learning to rank: from pairwise approach to
  listwise approach"* — ranking, not deletion.
- `Rubin` in **MultiPath++** (2111.14973) is Dempster, Laird & Rubin's EM paper cited for mixture-model
  training; in **Rate-Informed Discovery via Bayesian Adaptive Multifidelity Sampling** (2411.17826)
  and two active-inference papers it is *Rubinstein*, cited for the cross-entropy method.
- `imputed` in **Representative Pedestrian Collision Injury Risk Distributions for a Dense-Urban US
  ODD Using Naturalistic Dash Camera Data** refers to sensor-derived vehicle speed reconstruction
  (*"align the video with the imputed vehicle speed"*), not statistical imputation of missing
  records.
- `missing data` in **Kinematic Characterization of Micro-Mobility Vehicles During Evasive
  Maneuvers** describes a *prior* study's attrition (*"a substantial amount of missing data for the
  Segway (approximately 50%)"*), cited as a limitation of that work.

---

## 1. The one paper that engages the theory

**An omni-directional model of injury risk in planar crashes with application for autonomous
vehicles** — McMurry et al., 2021.

This is the only paper in the corpus that reasons about the missingness mechanism, quantifies it,
names the bias it produces, cites the standard reference, and runs both a deletion analysis and an
imputation analysis side by side.

### The full statement of the problem and the choice

> "Missing data is a persistent challenge in NASS-CDS/CISS. In the selected cohort, **26% of records
> (not survey weighted) are missing PDOF and 43% are missing delta-V.** In addition, delta-V is
> always missing for some objects contacted, such as heavy trucks. **Complete case analyses tend to
> produce biased results because data are not missing completely at random;** in our cohort, delta-V
> is 50% missing for occupants with MAIS 0, 57% for MAIS 6, and 38% for MAIS 1/2; a consequence is
> that a complete case analysis is unlikely to produce an unbiased estimates of the injury
> probabilities at each MAIS level because the underlying data are not representative of the
> population. **Statistical methods for handling missing data assume that the distribution of
> missing data can be modeled given other covariates (Little and Rubin 2002); this may not be
> possible if data are missing systematically, as with delta-V and object contacted.** For these
> reasons, we present both complete case analyses and analyses using multiple imputation to handle
> missing data. PDOF was imputed using random forests, which were more able to capture its nonlinear
> relationship with injury risk; we used the R mice package (v.3.12.0, van Buuren and
> Groothuis-Oudshoorn 2011)."
>
> — Methods

**Why they used it.** The reasoning is a three-step argument, all of it in that one paragraph:

1. *Reject MCAR empirically.* They do not assert MCAR or test it formally — they exhibit
   **differential missingness by outcome level** (50% / 57% / 38% missing delta-V at MAIS 0 / 6 /
   1-2). Missingness that varies with the outcome is the definition of a mechanism that breaks
   complete-case analysis for absolute risk.
2. *Name the failure mode of deletion.* Complete-case is "unlikely to produce an unbiased estimates
   of the injury probabilities at each MAIS level because the underlying data are not representative
   of the population" — i.e. deletion changes the injury distribution the model is fit to.
3. *Refuse to fully trust imputation either.* The Little & Rubin sentence concedes that imputation's
   own assumption ("the distribution of missing data can be modeled given other covariates" — MAR in
   all but name) "may not be possible if data are missing systematically, as with delta-V and object
   contacted." Delta-V is structurally missing for heavy-truck impacts — an MNAR pattern they do not
   claim to fix.

That is why they publish **both** analyses instead of picking one: neither method's assumption holds
cleanly, so the pair of results bounds the answer.

### The comparison they report

> "Models showed strong in-sample ability to discriminate between injured and uninjured occupants.
> Evaluated on occupants with complete data, the MAIS3 models had survey weighted areas under the
> receiver operating characteristic curve (AUCs) of **0.91 (imputed) and 0.92 (complete case)**,
> while both MAIS5 models had AUCs of 0.96."
>
> — Results, Model formulation

> "Table 3 AUCs comparing predictions between the general and direction specific models, between
> models fit to complete case and imputed datasets, and tested on both complete and imputed data
> sets."
>
> — Discussion

Note what that table does: it crosses *fit on* × *tested on* for both datasets — a 2×2 design that
exposes whether the imputation is doing work or just reproducing the complete cases.

### Where they concede the limits of both

> "Missing data is a limitation. This is not unique to our study; it is oft-cited, especially at
> higher injury severity levels (e.g., Sunnevang et al. 2009). **The imputed models assume we can
> adequately model distributions for PDOF and delta-V given other covariates. PDOF is a particular
> challenge because it is periodic, while delta-V is systematically missing for some collision
> partners. The complete case models are limited because the underlying MAIS injury distribution
> does not reflect the distribution seen across all planar crashes. This limits their ability to
> correctly estimate absolute risk, although they might still correctly rank different potential
> crashes.**"
>
> — Limitations

That last clause is the operationally important one, and it explains the rest of the corpus: a
complete-case model is disqualified for *absolute* risk but may still be adequate for *relative*
comparison — which is exactly the use most downstream Waymo papers make of it.

> "It may be possible to improve agreement by improving the algorithm used to impute PDOF."
>
> — Discussion

---

## 2. The one paper that runs imputation as a declared sensitivity analysis

**Passenger and heavy vehicle collisions with pedestrians: Assessment of injury mechanisms and
risk** — Schubert et al., 2023 (GIDAS data).

Here multiple imputation is not the primary analysis; it lives in a section literally titled
*Sensitivity analysis*, alongside re-weighting.

### The method

> "We analyzed the influence of missing data on the regression through **multiple imputation using
> the R mice package; we used classification and regression trees (cart) (van Buuren &
> Groothuis-Oudshoorn, 2011) for all variables; and we created ten imputed datasets, each using ten
> iterations.** For imputation, we augmented the dataset with additional variables from the GIDAS
> dataset, which were expected to provide auxiliary information. For example, to impute pedestrian
> height, weight is useful in addition to sex and age. **Logistic regression models were created for
> the ten imputed datasets, and the ten estimates for each independent variable were pooled to
> produce an overall estimate.** The models of the original and the imputed master dataset were
> compared by looking at the regression curves."
>
> — §2.3 Model evaluation

**Why they used it.** Two reasons are given explicitly. First, the stated study objective includes
missing data as a thing to be *quantified*, not merely handled:

> "This study builds on previous work by i) including the most recent data and vehicles; […] and v)
> **conducting sensitivity analyses to understand the effects of missing data and of reweighting
> towards the entire population of German crashes.**"
>
> — §1 Introduction

Second, the auxiliary-variable move ("to impute pedestrian height, weight is useful in addition to
sex and age") is the practical expression of the MAR-style assumption the McMurry paper names: it
only works if the missingness is explainable by observed covariates, so they deliberately widen the
covariate set beyond the analysis model.

### The results, including where deletion had been quietly biasing things

> "Not all cases within GIDAS have complete entries for all fields. We imputed unknown values of the
> independent variables of **sex (0.2% missing), vehicle deceleration (7% missing), and height
> relative to the bumper (imputed by separately imputing pedestrian height (21% missing) and vehicle
> bumper height (12% missing)).** After 10 iterations, diagnostic plots indicated convergence of the
> imputation models. […] The signs of the estimated coefficients are unchanged from the complete
> case analysis."
>
> — §3.4.1 Multiple imputation

> "A comparison between the imputed and complete case injury risk of MAIS3+ for different ages is
> given in Fig. 3.10. **The risk curves are very similar except for smaller children, where a larger
> number of unknowns existed for pedestrian height and those cases were excluded in the original
> dataset.** In general, children (AGE = 5 years) were at higher risk of injury compared to young
> adults (AGE = 20 years) due to their age and smaller stature relative to the bumper. **After
> imputation, this risk is even higher than for the original dataset.**"
>
> — §3.4.1 Multiple imputation

This is the clearest demonstration of the deletion failure mode anywhere in the corpus: dropping
incomplete records systematically removed small children, and doing so had been *understating* child
injury risk.

> "**Our sensitivity analyses suggest that effects on this analysis of missing data in GIDAS are
> minimal**, but that re-weighting towards German national data significantly reduces estimated
> injury risk."
>
> — §4 Discussion

---

## 3. The doctrine: imputation as a named alignment tool

**RAVE Checklist: Recommendations for Overcoming Challenges in Retrospective Safety Studies of
Automated Driving Systems** — Scanlon et al., 2024.

The field's own checklist lists imputation as one of four sanctioned data-alignment methods, with a
one-line rationale:

> Table 5, *Methods for aligning ADS and benchmark data* — "**Imputation** | Filling in missing data
> | **Incomplete data is commonplace in crash data, where only partial evidence is recorded
> following an event. These missing data elements can be approximated using a variety of approaches
> (e.g., Herbert, 2019).**"
>
> — Ensure data alignment in ADS and benchmark data

The cited reference is NHTSA's own methodology: *Herbert, G. C. (2019). Crash Report Sampling System:
Imputation (Report No. DOT HS 812 795)*. That matters — the imputation being endorsed here is
largely **NHTSA's pre-existing imputation of federal crash files**, not something the analyst is
expected to build.

Note what the checklist does *not* do: it names no missingness mechanism, requires no MAR
justification, and gives no guidance on when imputation is inadmissible.

---

## 4. Weighting imputation in the benchmarking papers

**Benchmarks for Retrospective Automated Driving System Crash Rate Analysis Using Police-Reported
Crash Data** (arXiv 2312.13228) has a section titled *Handling Data Missingness*:

> "Crash data is also subject to a certain degree of missingness in the data that is compiled for a
> given crash. **Factors like missing records or a vehicle driving away from the scene of a crash
> result in certain crash variables not being coded, such as the type of vehicle, injury status, or
> damage extent.** Researchers should consider various strategies for handling missingness, such as
> relying on imputed data, when handling police-reported data, and **should be aware of how that
> missingness may introduce bias in the results (McMurry et al., 2021).** Given that vehicle type
> was occasionally not specified with enough detail, this study relied on a form of imputation for
> estimating the passenger vehicle crash counts."
>
> — Handling Data Missingness

The citation is the chain that ties this literature together: the benchmarking paper's warning about
bias points back to the omni-directional injury-risk paper in §1 above.

### The actual procedure — proportional weighting, not model-based imputation

> "A proportion of the crashed vehicles had enough information to identify the actor as a vehicle,
> but not enough information to indicate whether or not the vehicle was a passenger vehicle. **For
> these vehicles not further specified (NFS), we imputed vehicle type by applying a weighting factor
> that represented the total proportion of known vehicles that were passenger vehicles.** The
> computed weighting factors applied to NFS vehicles for national, Maricopa county, San Francisco
> county, and Los Angeles county were 0.94, 0.90, 0.89, and 0.93, respectively."
>
> — 2312.13228, Appendix

The same procedure recurs in the two later benchmarking papers:

> "For a small proportion of vehicles, the specific vehicle type could not be determined (e.g., when
> a party left the scene of a crash before police could determine the vehicle type). **These unknown
> vehicle types were imputed using the distribution of known vehicle types at the geographic level**
> (reflecting likelihood of that vehicle being a passenger vehicle)."
>
> — *From Stoplights to On-Ramps* (arXiv 2508.19425), Methods

> "Some vehicle types were not specified with enough specificity to determine whether the actor was
> a passenger vehicle or some other actor type (e.g., a heavy vehicle). **For these uncertain
> vehicles, the vehicle type was imputed by applying a weighting factor representative of how likely
> that actor was to be a passenger vehicle.** This weight was calculated using the proportion of the
> known vehicles that were a passenger vehicle for each specific geographic region. The weighting
> factors applied to the unspecified vehicles were 0.93, 0.89, 0.89, and 0.94 for Los Angeles, San
> Francisco, Maricopa County, and Austin, respectively."
>
> — *…at 56.7 Million Miles*, Appendix

**Why this method.** The stated reason is mechanistic — the missingness has a known cause ("a party
left the scene of a crash before police could determine the vehicle type") — and the quantity being
recovered is a *count*, not a per-record covariate. A fractional weight applied to the unknown
stratum preserves the expected total. It is single, deterministic, mean-style imputation: it carries
no uncertainty forward into the confidence intervals, which none of these papers mentions as a
limitation.

### Inherited imputation from the federal file

> "For the national crashes identified within CRSS, we relied upon the **"MAXSEV_IM" variable, which
> uses the KABCO reported level but incorporates imputation in the event of unknown or missing
> data.** In addition, CRSS crashes with "Injured, Severity Unknown" (MAXSEV_IM equal to 5) were
> included."
>
> — 2312.13228, Appendix

The `_IM` suffix is NHTSA's imputed-variable convention. Waymo's analysts adopt the federal
imputation wholesale rather than re-deriving it — consistent with the RAVE checklist's pointer to
Herbert (2019).

---

## 5. Deletion in practice, and the justifications given for it

Two papers delete incomplete records. Both justify it, and the justifications are different.

### 5a. Deletion justified by "we only need relative differences"

**Ride-hailing in the Safe System: Increased Seat Belt Compliance and Late Model Year Vehicles** —
Campolettano, Scanlon, McMurry & Kusano.

> "**Only cases with a known resultant vehicle delta-v and defined principal direction of force
> (PDOF) were included** as these were the principal factors defining the severity distribution for
> this analysis. […] Vehicle delta-v is not reported for cases involving rollover, side swipes,
> non-horizontal forces, over/under ride, multiple, or overlapping impacts, among others. **After
> applying the above exclusion criteria, delta-v missingness was observed for 38% of vehicles in the
> dataset.** The resulting dataset, which excluded these cases of unknown delta-v, represented a
> known estimate for the current human planar crash severity distribution **with the caveat that it
> does not capture collisions with all object types.**"
>
> — Data Source

> "**As noted in the methods, CISS is associated with systematic data missingness for specific
> collision configurations.** […] Still, this study leveraged a subset of CISS for which all
> relevant case information was known. […] That being said, **all comparisons in this study were
> made using the same underlying dataset and injury risk model, so reported results are of relative
> differences.**"
>
> — Limitations

**Why deletion was acceptable here, by their own argument.** They acknowledge the missingness is
*systematic* (structurally tied to collision configuration — an MNAR pattern in everything but
name), then argue the bias cancels because every arm of the comparison is drawn from the same
deleted dataset. That is precisely the escape hatch McMurry et al. left open: complete-case models
lose absolute risk but "might still correctly rank different potential crashes."

Note the same paper builds on the complete-case parameters directly:

> "The injury risk model for vehicle occupants leverages **the complete case parameters presented in
> McMurry et al., 2021.**"
>
> — *TARGET Setting for High Severity Collisions: Tolerance-Based Assessment of Risk for Generalized
> Event Thresholds*, Appendix

So the complete-case variant of the injury model — not the imputed one — is what got reused
downstream.

### 5b. Deletion justified by matching the benchmark's own exclusions

**Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million Miles** (arXiv
2312.12675). This is the most interesting justification in the corpus, because the reason for
dropping ADS records is a property of the *comparison*, not of the records:

> "In addition, there was one crash (30270-6149) with "Unknown" maximum severity. The written SGO
> case narrative for this case states there were reported injuries and a person involved in the
> crash "was transported from the scene to a hospital for medical treatment." This crash with
> "Unknown" severity was considered an any-injury-reported crash in this study […]. **Other crashes
> with "Unknown" maximum severity due to missing information (e.g., due to another party leaving the
> scene without exchanging information) were excluded from the any-injury-reported outcome, as these
> types of missing data are also excluded from the human crash databases used to derive the
> benchmarks used in this study (Scanlon et al., 2023).**"
>
> — A.1 Selection of SGO Events

**Why.** Deleting an incomplete ADS record is normally the biasing move. Here the argument is that
*keeping* it would bias the comparison, because the human benchmark has already dropped its
equivalent records. Symmetric deletion preserves comparability even though neither arm is unbiased
on its own. Note also the direction of the one judgment call they did make: the "Unknown"-severity
crash with narrative evidence of injury was counted **against** Waymo.

---

## 6. Missingness as grounds for rejecting a data source outright

**Comparison of Waymo Rider-Only Crash Rates by Crash Type to Human Benchmarks at 56.7 Million
Miles** uses unquantifiable missingness to disqualify a competing benchmark:

> "One of the primary challenges with using CPUC TNC crash data, that is also a limitation noted by
> Chen and Shladover (2024), is the lack of any documented reporting thresholds. […] **Without clear
> guidance on the protocol for documenting each event, it is impossible to know the amount of
> potential missingness present in the data.** Chen and Shladover (2024) reported that **there was
> high missingness of reported fields in newer data, which required the authors to use only data
> from Uber from calendar year 2020.** […] Minor collisions, which make up the majority of
> collisions, may not be reported […]. **Drivers may have an incentive to not report minor
> collisions**, as they may suspect that reported collisions may impact their driver rating or their
> ability to meet the requirements to remain as a driver on the TNC network. […] **Therefore,
> without further study into the reporting practices and underreporting amount in the TNC crash
> data, it does not seem appropriate to compare ADS crash rates from the NHTSA SGO to the CPUC TNC
> crash data.**"
>
> — Comparisons to Prior Studies

That is an MNAR argument stated in plain language — missingness driven by the reporter's incentive,
correlated with the outcome being measured — without the vocabulary. The remedy chosen is not
imputation but exclusion of the entire data source.

A related structural argument appears in **Refinements in Benchmarking for Vulnerable Road User
Collisions by Comparing Naturalistic Driving and Police-Report Data**:

> "For higher severity crashes, those involving serious injury or fatality, most events are reported
> to police and included in the databases; however, **there is fundamental missingness associated
> with lower severity events (non-injury or minor injury), particularly for VRUs.** There exists a
> well-documented underreporting of VRU collisions in police-reported data […] estimates from around
> the world have observed reporting rates ranging from **44-75% among pedestrians, 7-46% among
> cyclists, and less than 20% among motorcyclists**."
>
> — Introduction

> "Additionally, **collision scenarios may only be present in the police report data due to the
> observed outcome, while events with equivalent risk may be absent** (e.g., two pedestrians struck
> by a vehicle traveling at 8 mph, one falls to the ground and sustains an injury while the other is
> able to maintain their balance and avoid a ground-induced injury). In this example scenario, the
> underlying crash configuration is the same, but the true incidence would not be captured because
> of the lack of an injury outcome for the second pedestrian."
>
> — Introduction

**Why this matters methodologically.** That worked example is textbook **outcome-dependent
missingness** — inclusion in the dataset is conditional on the outcome value. Their remedy is a
different data source (naturalistic driving data) rather than a statistical correction.

---

## 7. What the corpus does not do

Stated as observations from the sweep above, not as a claim about Waymo's internal practice:

- **No use of the MCAR/MAR/MNAR vocabulary**, beyond the single spelled-out MCAR rejection in
  McMurry et al. 2021. No paper labels its assumption as MAR, and no paper runs an MNAR sensitivity
  analysis (pattern-mixture models, selection models, tipping-point analysis).
- **No formal missingness diagnostics.** No Little's MCAR test, no missingness-pattern plots, no
  comparison of complete vs incomplete cases on observed covariates — except McMurry et al.'s
  missingness-by-MAIS-level breakdown, which serves that purpose informally.
- **Single/deterministic imputation goes unqualified.** The proportional-weighting imputation of
  vehicle type in the three benchmarking papers is single imputation; the resulting uncertainty is
  not propagated into the reported confidence intervals, and this is not listed as a limitation.
  (The two MICE papers do pool across ten imputations, which is the correct treatment.)
- **Rubin's rules are never named**, though the pooling procedure in the GIDAS paper is Rubin's rules
  in substance ("the ten estimates for each independent variable were pooled to produce an overall
  estimate"), and Little & Rubin (2002) is cited once.
- **The RAVE checklist does not require any of this.** Imputation appears as an available alignment
  method with no accompanying assumption to discharge.

---

## Summary table

| Paper | Missing data situation | Method chosen | Stated reason |
|---|---|---|---|
| An omni-directional model of injury risk in planar crashes (McMurry et al., 2021) | 26% PDOF, 43% delta-V missing; differential by MAIS level | Complete case **and** MICE (random forests for PDOF), reported side by side | Data "are not missing completely at random", so complete case is biased for absolute risk; but imputation's own modelling assumption may fail for systematically missing delta-V |
| Passenger and heavy vehicle collisions with pedestrians (Schubert et al., 2023) | 0.2%–21% missing across sex, deceleration, heights | MICE with CART, 10 datasets × 10 iterations, estimates pooled | Declared sensitivity analysis "to understand the effects of missing data"; auxiliary GIDAS variables added to support the imputation |
| RAVE Checklist (Scanlon et al., 2024) | — (guidance document) | Lists imputation as one of four alignment methods | "Incomplete data is commonplace in crash data, where only partial evidence is recorded following an event" |
| Benchmarks for Retrospective ADS Crash Rate Analysis (2312.13228) | Vehicle type "not further specified"; unknown injury severity | Proportional weighting imputation; adopts CRSS `MAXSEV_IM` | Missingness has a known mechanism (party left the scene); researchers "should be aware of how that missingness may introduce bias (McMurry et al., 2021)" |
| From Stoplights to On-Ramps (2508.19425); …at 56.7 Million Miles | Same vehicle-type problem | Same proportional weighting | Same |
| Ride-hailing in the Safe System (Campolettano et al.) | 38% of vehicles missing delta-v, systematically by collision configuration | Complete-case deletion | Comparisons all use the same dataset and model, "so reported results are of relative differences" |
| …at 7.1 Million Miles (2312.12675) | ADS crashes with "Unknown" maximum severity | Deletion — with one judgment-call inclusion | "these types of missing data are also excluded from the human crash databases used to derive the benchmarks" |
| …at 56.7 Million Miles | CPUC TNC data with undocumented reporting thresholds | Reject the data source | "impossible to know the amount of potential missingness present in the data" |
| Refinements in Benchmarking for VRU Collisions | Police-report reporting rates of 44–75% (pedestrians) down to <20% (motorcyclists) | Substitute naturalistic driving data | Outcome-dependent capture: "events with equivalent risk may be absent" |

---

## Provenance and caveats

**Provenance.** Term counts come from a literal case-insensitive full-text search over the stored
markdown of all 157 papers tagged `author_org=Waymo` at the curated tier in the local
`waymo_av_safety` corpus (`waymo/data/blobs/*.md`, paths resolved from `papers.markdown_path`).
Quotations were then read from those same files and cross-checked with semantic retrieval via
`scripts/ask_waymo_corpus.py`, which returned no additional papers on this topic. Quotations
reproduce the stored text; ellipses and bracketed completions are marked; **bold** within quotations
is mine, for emphasis.

**Caveats.** The sweep covers the 157 curated Waymo-authored papers present in this corpus, which is
a superset of the safety-methods subset but is not guaranteed to be Waymo's complete publication
record — a paper not ingested cannot be found. Term counts are per-paper (a paper is counted once
however many times a term appears) and match substrings, which is why the false positives in §0 are
listed explicitly. Section labels come from the parsed markdown headings; a few local journal PDFs
have imperfect heading extraction, so a small number of citations name the section by its visible
heading text rather than a numbered path. Passages of my own analysis are marked with *"why"* framing
and are inference from the quoted text, not source claims.
