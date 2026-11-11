# Survival analysis & time-to-event in Waymo-authored content — a corpus review

*2026-08-23. Question: does any Waymo-authored paper in the `waymo_av_safety` corpus publish
survival analysis or time-to-event analysis — what exact methods do they use instead, and why?*

**Method.** Engaged the Waymo-corpus MCP server (`app.serve --data-dir waymo/data`; identity
confirmed via `corpus_stats().serving` → `collection=waymo_av_safety`). Two exhaustive lexical
scans with `author_org="Waymo"` (curated tier only — third-party papers excluded by construction):
a survival/time-to-event vocabulary (`surviv|kaplan|meier|proportional hazards|hazard ratio|
weibull|log-normal|extreme value|censor|time-to-event|failure time|…`) returning **35 matches in
19 papers**, and an estimation-method vocabulary (`risk curve/function|maximum likelihood|logistic
regression|ordered logit|monotonic|…`) returning **125 matches in 38 papers**. Every substantive
match was then pulled verbatim by block id from the same store the MCP serves. All quotes below
are verbatim and citable via `get_span` (paper_id + block_id given).

---

## 1. Headline answer

**No Waymo-authored paper in the corpus publishes survival analysis (Kaplan-Meier, Cox, Weibull
time-to-event) as an applied method.** The survival vocabulary appears in Waymo content in exactly
three registers:

1. **A named alternative they consciously did not use** — TARGET-setting names *survival analysis*
   explicitly as a candidate model family for injury-risk curves.
2. **The core statistical argument for why their data would need it** — five Waymo papers discuss
   **censoring** (left/right/double) in their injury-risk and crash-rate data, which is precisely
   the problem survival analysis exists to solve.
3. **Coincidental vocabulary** — citations of *Kaplan* et al. (2020) scaling laws, stochastic-depth
   "survival probability", safety-case document "survivability", and a severity class labeled
   "survival probable". None are survival analysis.

What Waymo actually publishes, consistently across every injury-risk paper, is **binary logistic
regression** on MAIS-thresholded outcomes.

## 2. The exact methods Waymo uses (per paper)

| paper | corpus id | method | outcome / detail |
|---|---|---|---|
| An omni-directional model of injury risk in planar crashes (C22) | `local:071d15c56158` | **logistic regression**, NASS-CDS/CISS survey-design weighted | MAIS3+/MAIS5+ risk; direction of force as a **second-order Fourier series** interacted with delta-V; "fatalities were treated as injured regardless of coded MAIS"; prediction = 21-term log-odds dot product → inverse logit |
| Bridging the gap: mechanistic cyclist injury risk curves (C17) | `local:7b943f45c1da` | **binary logistic regression** | "injury outcome represented as a binary variable based on the MAIS level or a recorded fatality"; curves at MAIS2+F/3+F/4+F/5+F |
| Mechanistic omnidirectional motorcyclist injury risk (C2) | `local:bb74867d2259` | **binary logistic regression** | "In alignment with ISO 26262 safety standards… MAIS2+F, 3+F, 4+F and 5+F levels"; friction factor estimated by "manual maximum likelihood approximation" varying friction 0→1 in 0.05 steps |
| Representative pedestrian collision injury risk distributions (B10) | `local:aa069e80dac9` | **logistic regression** | MAIS-threshold risk vs impact speed; plus a knock-down model: "10% risk of knockdown was observed to occur at 2.8 mph" |
| Passenger & heavy vehicle collisions with pedestrians (C18) | `local:c92c18fe2ac2` | **logistic regression** + natural cubic spline | age splined "in the log odds space with a knot at age 20" (R `ns()`); evaluated by AROC/APRC given class imbalance |
| Comparison of RO crash rates at 56.7M miles / Safety Performance at 1M miles (B14) | `local:6b9ccd0431f6`, `local:4c3912bd5507` | published external risk curves (**McMurry et al. 2021 logistic models**) applied | p(MAIS2+) per contact event, population-average predictors |

## 3. Why logistic regression — and where survival analysis is pointed to instead

### 3.1 TARGET-setting names survival analysis as the un-taken alternative

> *"An additional source of potential bias is that logistic regression is the most commonly used
> model form for these injury risk functions, and it predicts non-zero injury risk at zero speed.
> Efforts to mathematically and biomechanically align these risk curves to limit the overestimation
> of low-end risk through use of different models (e.g., weibull or log-normal models, **survival
> analysis**) may be warranted depending on the research objectives (Kent & Funk, 2004;
> Yoganandan et al., 2016). Further, techniques aimed at re-weighting the sample to avoid
> undersampling non-injury and/or non-tow-away crashes may also be useful…"*
> — `local:f2811feacd35:b84`, p10, §4.3

This is the single most explicit statement in the curated set: survival-analysis-family models
(Weibull/log-normal) are identified as the fix for logistic regression's known artifact
(non-zero risk at zero speed), but framed as optional ("depending on the research objectives"),
alongside sample re-weighting as the competing remedy.

### 3.2 The censoring argument — stated three times, three ways

TARGET §4.3:

> *"It is also important to recognize that injury data from field collision data (as well as a
> large portion of the specific body region injury tolerance data from biomechanical research)
> represents censored data. For injured persons (left-censored data), there is no way of telling
> how much less severe the collision could have been and still resulted in the same injury
> severity. Similarly, for uninjured persons (right-censored data), there is no way to know how
> much more severe the collision could have been and still resulted in no injuries."*
> — `local:f2811feacd35:b85`, p10

Baseline VRU risk (C8):

> *"The data used to generate injury risk curves generally represent observational samples of
> injury outcomes that are necessarily censored. … This double censoring is also reflective of
> biomechanical variance. Additionally, it can be difficult to differentiate between injuries
> directly caused by contact with the motor vehicle and those caused by potential subsequent
> contacts, such as those associated with a fall to the ground."*
> — `local:bc031ecd9224:b103`, p9, §Injury risk model considerations

Note the direction of the argument: censoring is acknowledged as intrinsic to the data, then
**absolved** — "manifests itself in the form of variance in the injury risk models, and does not
necessarily bias the model outputs … toward under- or over-estimation of injury risk"
(`local:f2811feacd35:b85`). That absolution is the implicit justification for staying with
logistic regression.

### 3.3 Sampling-induced censoring acknowledged in Limitations, four more times

| paper | quote | anchor |
|---|---|---|
| Baseline VRU (C8), Limitations | "only cases with at least a suspected VRU injury were sampled, resulting in **data censoring and low-end risk offsets**" | `local:bc031ecd9224` p9 |
| Pedestrian ESV-27 (B10), Limitations | "collisions without an injury are not considered, resulting in **data censoring and low-end risk offsets**" | `local:aa069e80dac9:b56`, p9 |
| Pedestrian AAP (C18) | "there is a bias toward collisions of higher severity … and a **censoring of collisions without injuries**. This is exemplified by the injury risk curves having relatively large offsets from 0% risk at impact speeds of 0 kph" | `local:c92c18fe2ac2:b97`, p10 |
| 1M-miles RO report (B14) | "Because some contact events go unreported to police … this **data censoring creates the opportunity for overestimation of p(MAIS2+) risk** on the very low injury severity end" | `local:4c3912bd5507:b86`, p20 |
| Cyclist dooring / NEISS (B9) | "the odds ratio presented in this study is affected by this dataset being **censored** in that it only considers those cyclists who sought treatment at an emergency department" | `local:442bfd3211f4:b121`, p6 |

C8 also points to extreme value theory as the long-tail remedy rather than survival models:
"One option would be leveraging **extreme value theory** to fit a distribution to the underlying
NDS data to estimate the frequency and severity of the long-tail collision events" (p9,
Potential applications).

## 4. Time-to-event framing

No Waymo-authored paper frames any outcome as time-to-event. TTE appears in Waymo content only
incidentally — e.g., the dooring survey reports trajectory error "according to the time to event
(TTE)" when citing tracking-algorithm metrics (`local:053bb8386d5f:b121`, p12). The genuine
time-to-event *applications* found in the corpus (pedestrian waiting-time Cox model `1903.11812`;
Cox-adjusted dynamic risk `2501.16480`; EVT-survival conflict detection `2407.10959`; continuous
survival-based risk measures `2303.08007`) are all third-party work — see companion audit note.

Also excluded as false positives after reading each match: *Kaplan* et al. 2020 scaling-law
citations (`2506.08228`, `2605.20390`), *Kaplan and Prado* evasive-maneuver citations
(`2505.14842`, `2507.17943`/`local:ac6107f22da9`), stochastic-depth "survival probability 0.6"
(`2210.07372`), safety-case document "survivability" (`2506.09929` ×3, `local:e402895b56ca`,
`2011.00054`), the AIS severity class "**survival** probable" (`local:f2811feacd35` §1.2.2 table),
and an active-inference paper's "to survive over time" (`2506.02215`).

## 5. Synthesis

Waymo's injury-severity methodology treats injury as a **binary state at a given collision
intensity** (delta-V or impact speed → P(MAIS≥k)), not as a time-to-event process — so the
survival toolkit's *time dimension* has no role, while its *censoring machinery* is exactly what
their severity-space data problem calls for. They name that connection once (TARGET §4.3:
Weibull/log-normal/survival analysis as low-end-risk refinement candidates, citing Kent & Funk
2004 and Yoganandan et al. 2016), document the censoring honestly in six papers' methods/
limitations sections, quantify its symptom (non-zero risk offsets at zero speed), and then proceed
with ISO-26262-aligned logistic regression plus re-weighting/EVT as the alternative remedies. The
research objective stated — comparing relative risk across populations rather than estimating
absolute low-severity risk — is the reason given for the choice being acceptable.
