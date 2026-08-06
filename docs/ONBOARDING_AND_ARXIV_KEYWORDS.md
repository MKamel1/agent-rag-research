# Onboarding: Waymo AV-Safety Research Corpus — for `agent-rag-research`

> **Scope broadened 2026-08-06.** §1–§2 below describe the *original, narrow* Waymo-centric scope.
> The corpus this repo now builds covers 11 topic areas (AV safety, AV simulation, traffic modelling
> for AV simulation, Waymo tech stack, Waymo research, research *using* Waymo data,
> AV-safety-evaluation methodology, AV simulation assessment, simulation validation/realism,
> evaluation-framed motion forecasting, AV safety-case/standards literature). **§2b is the current
> query strategy; §2 is retained as its narrower ancestor, not as a competing spec.** §3's ID list
> has been **repurposed** — read §3's banner before using it as an exclusion set, because using it
> as one is what kept every Waymo-authored paper out of the corpus. Plan:
> `docs/superpowers/plans/2026-08-06-waymo-av-safety-corpus-expansion-v2.md`.

**Handoff document.** This is written so an agent with zero prior context on this project (e.g. the
`agent-rag-research` pipeline at github.com/MKamel1/agent-rag-research) can pick up arXiv harvesting for
this effort without re-deriving anything covered here. It has three parts: (1) why this exists and what
"done" looks like, (2) the keyword/query strategy to use on arXiv, (3) what's already captured so nothing
gets re-downloaded.

---

## 1. Why this exists — context for the agent

Mohamed Bayoumi Kamel is preparing for a **Senior Data Scientist technical screen at Waymo** (recruiter
screen already held 2026-08-13; the technical screen date is not yet confirmed, so prep started early).
The role's core, per the actual job description, is: developing statistical evaluation frameworks for
autonomous-vehicle performance and simulation quality, inventing statistical methods for rare-event
rate-estimation and combining real+synthetic data, and facilitating deployment-readiness decisions.

Earlier in this effort, a manually-curated set of **202 papers** was already researched and downloaded
(sourced from Waymo's own two public research pages — `waymo.com/research/` and
`waymo.com/safety/research/` — plus targeted web search for closely-adjacent external literature). That
set lives in this same `Waymo — Senior Data Scientist 2026-07-21/` folder:
- `Research Papers/` — top 52, highest priority
- `Research Papers (Extended - Lower Priority 53-200)/` — next 150

**This document exists because the next step — scaling coverage further via systematic arXiv search — is
better done by `agent-rag-research`, which already has a working arXiv download/parse/embed pipeline,
rather than duplicating that pipeline here.** The job for that project's agent is: run the queries below
against arXiv, skip anything matching the "already captured" ID list in §3, download+parse+embed the rest
into whatever store `agent-rag-research` normally uses, and — since the user also wants a plain PDF copy
of everything for direct reading — also save (or symlink/copy) the retrieved PDFs into:

```
Waymo — Senior Data Scientist 2026-07-21/Total Research Library/
```

(This is the shared destination folder for everything beyond the original 202 — this document lives in
it.)

### Goal, stated honestly

The original ask in this session was to scale the corpus toward **15,000 papers**. That number is not
realistic for this topic while staying genuinely relevant — arXiv's entire robotics category (cs.RO),
across every subject and all years, is only in the tens of thousands, and this is one narrow slice of it.
**The actual goal is: exhaustively harvest everything on arXiv that's genuinely relevant to this topic,
ranked most-relevant-first, and report the true yield — do not pad the count with tangential material
(generic object-detection papers, unrelated robotics papers, etc.) just to approach a target number.**
Realistic expectation: most-likely a few hundred to low thousands of genuinely new, non-duplicate papers,
once run across the full query list below. That is a *good* outcome, not a shortfall — a smaller, higher-
precision set is more useful for interview prep than a huge diluted one.

### Priority order (apply this when ranking/triaging results)

1. **Waymo-authored papers** — anything by Waymo's safety-statistics team (see author list in §2) or
   Waymo's ML-research team, not already in the "already captured" list.
2. **Rare-event / statistical AV-safety-evaluation methodology** — importance sampling, extreme value
   theory, Bayesian rare-event estimation, crash-rate benchmarking — this is the JD's actual center of
   gravity.
3. **Simulation validation / realism** — distributional-fidelity, sim-to-real gap, scenario generation.
4. **Motion forecasting / behavior prediction** — only where it's evaluation- or safety-framed, not pure
   architecture papers.
5. **Broader AV safety-case / standards literature** — UL 4600, RSS, Safety Force Field, SOTIF, PEGASUS-
   adjacent scenario-based-testing methodology.
6. **Perception / general robotics-ML** — lowest priority, include only as filler if the above tiers are
   exhausted and volume is still wanted.

---

## 2. arXiv keyword / query strategy

### Recommended arXiv categories
`cs.RO` (Robotics) — primary · `stat.AP`, `stat.ME` (Statistics) — for rare-event/risk-estimation methods
· `cs.LG` (Machine Learning) — general ML/monitoring methodology · `eess.SY` (Systems and Control) · `cs.CV`
(Computer Vision) — lowest priority, perception only.

### Author names worth a dedicated author-field search
Waymo's safety-statistics team publishes under these names (found during the manual research phase —
searching `au:` for each on arXiv is likely to surface papers not caught by the keyword queries below):
Kusano, Scanlon, Chen (Y.H./Yin-Hsiu), McMurry, Victor (Trent), Favaro, Fraade-Blanar, Engström, Schnelle,
Wichner, Campolettano, Schubert, Dinparastdjadid, Johnson (L.), Schumann (J.F.).

### Query set (arXiv API `search_query` field syntax — combine with `AND`/`OR`, quote phrases)

```
abs:"autonomous vehicle" AND abs:safety AND (abs:evaluation OR abs:assessment)
abs:"crash rate" AND (abs:"automated driving" OR abs:"autonomous vehicle")
(abs:"rare event" OR abs:"extreme value") AND (abs:"autonomous vehicle" OR abs:"automated driving" OR abs:traffic)
abs:"importance sampling" AND (abs:"autonomous vehicle" OR abs:"automated driving")
abs:"surrogate safety" OR abs:"time-to-collision" OR abs:"post-encroachment time"
abs:"scenario-based" AND (abs:testing OR abs:validation) AND (abs:"automated driving" OR abs:"autonomous vehicle")
abs:"safety case" AND (abs:"automated driving" OR abs:"autonomous vehicle" OR abs:"self-driving")
abs:simulation AND abs:realism AND (abs:driving OR abs:traffic)
cat:cs.RO AND abs:"trajectory prediction" AND (abs:driving OR abs:vehicle)
abs:"Waymo Open Dataset" OR abs:"Waymo Open Motion"
abs:"concept drift" AND (abs:monitoring OR abs:production)
abs:bayesian AND abs:"rare event" AND (abs:safety OR abs:risk)
abs:"responsibility sensitive safety" OR abs:"safety force field"
abs:"traffic conflict" AND (abs:risk OR abs:safety)
abs:"deployment readiness" AND (abs:"automated driving" OR abs:autonomous)
abs:"naturalistic driving" AND (abs:risk OR abs:crash)
abs:"vulnerable road user" AND (abs:injury OR abs:risk) AND abs:vehicle
abs:"operational design domain" AND (abs:safety OR abs:standard)
au:Kusano_K AND (abs:vehicle OR abs:driving OR abs:safety)
au:Scanlon_J AND (abs:vehicle OR abs:driving OR abs:safety)
au:Favaro_F AND (abs:vehicle OR abs:driving OR abs:safety)
au:Engström_J AND (abs:vehicle OR abs:driving OR abs:safety)
```

### Relevance-scoring keyword weights (for ranking results most-relevant-first)

| Keyword | Weight | Keyword | Weight |
|---|---|---|---|
| waymo | 5 | traffic conflict | 3 |
| rare event | 4 | scenario-based | 2 |
| extreme value | 4 | concept drift | 2 |
| surrogate safety | 4 | responsibility sensitive safety | 3 |
| crash rate | 4 | safety force field | 3 |
| importance sampling | 4 | trajectory prediction | 1 |
| time-to-collision | 3 | motion forecasting | 1 |
| post-encroachment | 3 | naturalistic driving | 2 |
| safety case | 3 | collision avoidance | 2 |
| deployment readiness | 3 | risk estimation | 3 |
| bayesian | 2 | injury risk | 2 |
| simulation | 2 | vulnerable road user | 2 |
| autonomous vehicle | 2 | operational design domain | 2 |
| automated driving | 2 | benchmark | 1 |
| self-driving | 1 | | |

Drop anything scoring 0 (no keyword match at all) rather than keeping it as unranked filler.

---

## 2b. Broadened query strategy (2026-08-06) — the current spec

§2 above is the ancestor of this section, kept for provenance. Where the two disagree, **this
section wins**. It is written to be copied directly into `scripts/waymo_arxiv_scout.py`'s
`_TOPIC_QUERIES` / `_KEYWORD_WEIGHTS` / `_CATEGORY_FILTER` constants — one file, one source of
truth, which is why this lives here rather than in a second doc that would immediately fork.

### 2b.1 Category priority

Unchanged in membership from §2, now with explicit priority ordering:

| priority | category | role |
|---|---|---|
| 1 | `cs.RO` | primary — robotics/AV |
| 2 | `stat.AP`, `stat.ME` | rare-event and risk-estimation methodology |
| 3 | `cs.LG` | general ML / monitoring methodology |
| 4 | `eess.SY` | systems and control |
| 5 | `cs.CV` | **lowest — perception only, not general CV**; see the exclusion rule in 2b.4 |

Category filter string (AND-combined with every topic query; **not** with the author queries — an
author's own paper may sit outside these categories, and category-restricting an author search
defeats its purpose):

```
(cat:cs.RO OR cat:stat.AP OR cat:stat.ME OR cat:cs.LG OR cat:eess.SY OR cat:cs.CV)
```

### 2b.2 The 11 topic areas → query set

Every query below is arXiv-API `search_query` Lucene syntax. Queries 1–18 are §2's set, retained
verbatim (they already cover topics 1, 3, 7, 9 and 11); 19–36 are new coverage for the areas §2
did not reach. Coverage is tracked explicitly so a later reader can tell which topic a query serves.

| # | topic area | `search_query` |
|---|---|---|
| 1 | AV safety | `abs:"autonomous vehicle" AND abs:safety AND (abs:evaluation OR abs:assessment)` |
| 2 | safety-eval methodology | `abs:"crash rate" AND (abs:"automated driving" OR abs:"autonomous vehicle")` |
| 3 | safety-eval methodology | `(abs:"rare event" OR abs:"extreme value") AND (abs:"autonomous vehicle" OR abs:"automated driving" OR abs:traffic)` |
| 4 | safety-eval methodology | `abs:"importance sampling" AND (abs:"autonomous vehicle" OR abs:"automated driving")` |
| 5 | safety-eval methodology | `abs:"surrogate safety" OR abs:"time-to-collision" OR abs:"post-encroachment time"` |
| 6 | standards / scenario testing | `abs:"scenario-based" AND (abs:testing OR abs:validation) AND (abs:"automated driving" OR abs:"autonomous vehicle")` |
| 7 | safety case / standards | `abs:"safety case" AND (abs:"automated driving" OR abs:"autonomous vehicle" OR abs:"self-driving")` |
| 8 | simulation validation / realism | `abs:simulation AND abs:realism AND (abs:driving OR abs:traffic)` |
| 9 | motion forecasting (see 2b.4) | `cat:cs.RO AND abs:"trajectory prediction" AND (abs:driving OR abs:vehicle)` |
| 10 | research using Waymo data | `abs:"Waymo Open Dataset" OR abs:"Waymo Open Motion"` |
| 11 | monitoring methodology | `abs:"concept drift" AND (abs:monitoring OR abs:production)` |
| 12 | safety-eval methodology | `abs:bayesian AND abs:"rare event" AND (abs:safety OR abs:risk)` |
| 13 | standards (RSS / SFF) | `abs:"responsibility sensitive safety" OR abs:"safety force field"` |
| 14 | AV safety | `abs:"traffic conflict" AND (abs:risk OR abs:safety)` |
| 15 | AV safety | `abs:"deployment readiness" AND (abs:"automated driving" OR abs:autonomous)` |
| 16 | AV safety | `abs:"naturalistic driving" AND (abs:risk OR abs:crash)` |
| 17 | AV safety | `abs:"vulnerable road user" AND (abs:injury OR abs:risk) AND abs:vehicle` |
| 18 | standards (ODD) | `abs:"operational design domain" AND (abs:safety OR abs:standard)` |
| 19 | **AV simulation** | `(abs:"driving simulation" OR abs:"driving simulator" OR abs:"autonomous driving simulator") AND (abs:evaluation OR abs:validation OR abs:fidelity OR abs:realism)` |
| 20 | **AV simulation** | `abs:"closed-loop simulation" AND (abs:driving OR abs:"autonomous vehicle" OR abs:traffic)` |
| 21 | **AV simulation assessment** | `(abs:"sim agents" OR abs:"simulation agents") AND (abs:driving OR abs:traffic OR abs:realism)` |
| 22 | **AV simulation assessment** | `abs:"simulation-based testing" AND (abs:"autonomous vehicle" OR abs:"automated driving" OR abs:"cyber-physical")` |
| 23 | **traffic modelling for simulation** | `(abs:"traffic simulation" OR abs:"microscopic traffic" OR abs:"car-following model" OR abs:"lane change model") AND (abs:calibration OR abs:validation OR abs:realism OR abs:safety)` |
| 24 | **traffic modelling for simulation** | `abs:"driver behavior model" AND (abs:simulation OR abs:calibration OR abs:validation)` |
| 25 | **sim-to-real / distributional fidelity** | `(abs:"sim-to-real" OR abs:"sim2real" OR abs:"reality gap" OR abs:"distributional realism" OR abs:"distribution shift") AND (abs:driving OR abs:"autonomous vehicle" OR abs:traffic)` |
| 26 | **scenario generation** | `(abs:"scenario generation" OR abs:"critical scenario" OR abs:"adversarial scenario" OR abs:"safety-critical scenario") AND (abs:"autonomous vehicle" OR abs:"automated driving" OR abs:simulation)` |
| 27 | **evaluation-framed forecasting** | `(abs:"motion forecasting" OR abs:"behavior prediction" OR abs:"trajectory prediction") AND (abs:calibration OR abs:"uncertainty quantification" OR abs:"failure mode" OR abs:robustness OR abs:"safety impact" OR abs:"evaluation metric")` |
| 28 | **evaluation-framed forecasting** | `abs:"prediction" AND abs:"planner" AND (abs:"safety" OR abs:"downstream") AND (abs:driving OR abs:"autonomous vehicle")` |
| 29 | **standards — UL 4600** | `abs:"UL 4600" OR (abs:"safety case" AND abs:"autonomous" AND abs:standard)` |
| 30 | **standards — SOTIF** | `abs:SOTIF OR abs:"safety of the intended functionality" OR abs:"ISO 21448"` |
| 31 | **standards — PEGASUS-adjacent** | `abs:PEGASUS OR (abs:"scenario database" AND abs:"automated driving") OR abs:"logical scenario"` |
| 32 | **standards — general** | `(abs:"ISO 26262" OR abs:"functional safety") AND (abs:"automated driving" OR abs:"autonomous vehicle")` |
| 33 | **Waymo tech stack** | `abs:Waymo` |
| 34 | **Waymo tech stack / simulation** | `abs:Waymax OR abs:"Waymo Open Sim Agents" OR abs:"WOMD"` |
| 35 | **AV safety — assurance/runtime** | `(abs:"runtime monitoring" OR abs:"safety envelope" OR abs:"reachability analysis") AND (abs:"autonomous vehicle" OR abs:"automated driving")` |
| 36 | **safety-eval methodology** | `(abs:"miles per intervention" OR abs:disengagement OR abs:"safety benchmark") AND (abs:"autonomous vehicle" OR abs:"automated driving")` |

Author-field queries (no category filter), extended from §2's four to cover the full author roster
in §2 "Author names worth a dedicated author-field search":

```
au:Kusano_K AND (abs:vehicle OR abs:driving OR abs:safety)
au:Scanlon_J AND (abs:vehicle OR abs:driving OR abs:safety)
au:Favaro_F AND (abs:vehicle OR abs:driving OR abs:safety)
au:Engström_J AND (abs:vehicle OR abs:driving OR abs:safety)
au:McMurry_T AND (abs:vehicle OR abs:driving OR abs:safety)
au:Victor_T AND (abs:vehicle OR abs:driving OR abs:safety)
au:Fraade-Blanar_L AND (abs:vehicle OR abs:driving OR abs:safety)
au:Schnelle_S AND (abs:vehicle OR abs:driving OR abs:safety)
au:Campolettano_E AND (abs:vehicle OR abs:driving OR abs:safety)
au:Dinparastdjadid_A AND (abs:vehicle OR abs:driving OR abs:safety)
au:Schumann_J AND (abs:vehicle OR abs:driving OR abs:safety)
au:Anguelov_D AND (abs:driving OR abs:vehicle)
au:Sapp_B AND (abs:driving OR abs:vehicle)
```

`au:Chen_Y`, `au:Johnson_L`, `au:Schubert_A` and `au:Wichner_D` from §2's roster are **deliberately
omitted** — they are high-collision surnames on arXiv and their `abs:` guard is too weak to hold
precision. Waymo's own papers by those authors are already captured exactly by
`docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §2, which is ground truth rather than a search heuristic.

### 2b.3 Extended relevance-scoring keyword weights

§2's table, plus the new areas. Additive, no existing weight changed — the ranking stays comparable
to the earlier run's output.

| Keyword | Weight | Keyword | Weight |
|---|---|---|---|
| waymo | 5 | scenario generation | 4 |
| rare event | 4 | safety-critical scenario | 4 |
| extreme value | 4 | sim-to-real | 3 |
| surrogate safety | 4 | sim2real | 3 |
| crash rate | 4 | distributional realism | 4 |
| importance sampling | 4 | traffic simulation | 3 |
| time-to-collision | 3 | car-following | 2 |
| post-encroachment | 3 | driving simulator | 2 |
| safety case | 3 | closed-loop simulation | 3 |
| deployment readiness | 3 | sim agents | 4 |
| bayesian | 2 | waymax | 5 |
| simulation | 2 | waymo open | 5 |
| autonomous vehicle | 2 | sotif | 4 |
| automated driving | 2 | ul 4600 | 4 |
| self-driving | 1 | iso 21448 | 4 |
| traffic conflict | 3 | iso 26262 | 3 |
| scenario-based | 2 | pegasus | 3 |
| concept drift | 2 | functional safety | 2 |
| responsibility sensitive safety | 3 | reachability analysis | 3 |
| safety force field | 3 | runtime monitoring | 3 |
| trajectory prediction | 1 | uncertainty quantification | 2 |
| motion forecasting | 1 | calibration | 2 |
| naturalistic driving | 2 | failure mode | 2 |
| collision avoidance | 2 | disengagement | 2 |
| operational design domain | 2 | safety benchmark | 3 |
| benchmark | 1 | scenario database | 2 |
| risk estimation | 3 | logical scenario | 2 |
| injury risk | 2 | | |
| vulnerable road user | 2 | | |

Unchanged rule: **drop anything scoring 0.**

### 2b.4 Exclusions — what must NOT enter the corpus

These are the scope's negative space. Stated as rules a reviewer can apply to a candidate list, not
as query syntax (arXiv's `ANDNOT` is too blunt for judgement calls like these):

1. **Pure motion-forecasting/behavior-prediction architecture papers are OUT.** A paper proposing a
   new forecasting model architecture, with no safety or evaluation angle, does not belong here
   however good it is. A paper *evaluating* forecasting models — their safety implications,
   calibration, uncertainty, failure modes, or downstream effect on a planner — is IN. Operational
   test: if the contribution is "a better number on a forecasting leaderboard," it's out; if the
   contribution is "here is what those numbers do or don't tell you about safety," it's in.
   Query 27/28 encode this by requiring an evaluation term alongside the forecasting term; query 9
   (inherited from §2) does **not**, so its hits need the manual pass at the review checkpoint.
2. **`cs.CV` is perception-only.** A `cs.CV` hit is in scope only if it is about AV perception. A
   general computer-vision paper that merely benchmarks on an AV dataset is out.
3. **Generic robotics/ML** with no AV-safety framing is out — §1's original "do not pad the count"
   rule, unchanged.
4. **Waymo-authored papers are never excluded**, even when they land in an out-of-scope-looking
   area (e.g. a pure 3D-detection paper). Author affiliation outranks topic here: the corpus needs
   to be able to answer "what has Waymo published," which requires the whole body of work.
   `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` is the authoritative list of what that means.

### 2b.5 Waymo-authored vs. Waymo-adjacent

Both are in scope; the corpus must be able to tell them apart. The mechanism chosen (see the v2
plan §4) is **not** an ingest-time affiliation extractor — it is the exact, enumerated ID list in
`docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §2, mirrored to `fixtures/waymo/waymo_authored_ids.txt`.
Membership in that file means "authored by Waymo"; everything else in the corpus that matches
Waymo-related queries is "about or using Waymo," and needs no extraction step to be classified.

---

## 3. Already captured — **repurposed 2026-08-06, no longer an exclusion list**

> **Read this before using the list below.** These 173 IDs describe PDFs sitting in an *external*
> folder (`Waymo — Senior Data Scientist 2026-07-21/Research Papers/`) that does **not exist on the
> machine running this repo** (checked 2026-08-06). Treating them as "already captured" and
> excluding them from harvest is what kept **every one of Waymo's own 114 arXiv-published papers
> out of this repo's corpus** — verified: all 114 IDs enumerated in
> `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §2 are inside this list, and **0** of them appear in
> `fixtures/waymo/paper_ids.txt` (1,437 ids) or in `waymo/data/papers.db`'s `ingest_state`.
>
> **Correct use from now on:** this is a *seed/priority* list, not an exclusion list. The scout's
> `ALREADY_CAPTURED_IDS` constant must be emptied (the pipeline's own `ingest_state` is the real
> "already have it" authority — `app/build_corpus.py::cached_not_done` already subtracts
> `stage='done'` ids every iteration, so a second hand-maintained exclusion list is both redundant
> and, as shown, dangerous).

**173 arXiv IDs** originally downloaded and present in `Research Papers/` or
`Research Papers (Extended - Lower Priority 53-200)/` in this folder's parent. Skip any of these on
arXiv-side search (parse the ID out of the search result's arXiv URL and check membership in this list):

```
1605.04965, 1607.02687, 1708.06374, 1812.03057, 1812.03079, 1904.02697, 1905.09018, 1908.11069,
1910.05449, 1910.06528, 1911.01207, 1912.04838, 2002.00386, 2003.00790, 2004.00831, 2004.06531,
2005.01864, 2005.03844, 2005.04045, 2005.04255, 2005.04259, 2005.04298, 2005.07289, 2005.09417,
2005.09927, 2008.06120, 2008.07725, 2008.08294, 2010.04719, 2010.06808, 2010.16404, 2011.00038,
2011.00054, 2102.03483, 2102.04241, 2103.01306, 2103.02093, 2103.05073, 2103.16054, 2104.09097,
2104.09959, 2104.10133, 2105.07014, 2106.08417, 2106.13365, 2106.13381, 2106.14880, 2107.14412,
2108.06709, 2109.01066, 2111.14973, 2112.07787, 2112.12141, 2201.05938, 2202.05263, 2203.03875,
2203.12683, 2203.14355, 2204.02351, 2204.07619, 2204.12511, 2205.03195, 2205.04624, 2205.05703,
2206.00991, 2206.01738, 2206.03666, 2206.03970, 2206.04176, 2206.04831, 2206.05961, 2206.07704,
2206.07705, 2207.03586, 2207.05844, 2208.06062, 2208.12833, 2209.09879, 2210.02761, 2210.05018,
2210.07372, 2210.08061, 2210.08064, 2210.08113, 2210.08375, 2210.09267, 2210.09539, 2210.13428,
2210.13488, 2211.10237, 2212.01375, 2212.03267, 2212.06968, 2212.07729, 2212.08148, 2212.08710,
2212.11419, 2301.03941, 2302.00437, 2303.15201, 2304.02163, 2304.03834, 2305.07733, 2305.12032,
2306.01075, 2306.01917, 2306.03083, 2306.03206, 2306.04745, 2306.17682, 2307.01058, 2309.12474,
2309.14003, 2309.14491, 2309.16534, 2309.16870, 2309.16889, 2310.08710, 2312.07019, 2312.12675,
2312.13228, 2312.14717, 2401.02402, 2401.11993, 2404.03843, 2404.05444, 2404.15635, 2404.18573,
2404.19531, 2405.00236, 2405.02811, 2405.03807, 2406.17813, 2407.16832, 2408.07758, 2408.09769,
2408.15538, 2409.18343, 2410.08903, 2410.09190, 2410.12538, 2410.23262, 2411.01683, 2411.06010,
2411.17826, 2412.12129, 2502.08121, 2503.00815, 2504.08316, 2505.01446, 2505.01515, 2505.09880,
2505.13556, 2505.14842, 2505.21743, 2505.24139, 2506.02215, 2506.08228, 2506.09929, 2506.19488,
2506.21976, 2507.17943, 2508.19425, 2510.06209, 2511.00659, 2512.07874, 2602.00903, 2603.14841,
2604.15740, 2604.19838, 2604.27168, 2605.22809, 2606.07789
```

**Also already captured, but NOT on arXiv** (primary-source PDFs from Waymo, NHTSA, RAND, NVIDIA,
Mobileye, and open conference proceedings — irrelevant to an arXiv-only pipeline, listed here only so
nobody wonders why they're missing from the ID list above): Waymo's own safety-data-hub release notes and
2021 safety report; the RAND "Driving to Safety" report; NHTSA's ADS policy documents (2016 Federal
Automated Vehicles Policy through 2025 Report to Congress); Mobileye's RSS architecture documents; NVIDIA's
original Safety Force Field paper; the UL 4600 voting draft; the PEGASUS method overview; and several
IRCOBI/ESV open conference-proceedings papers. Full list and sourcing notes in
`../Research Papers (Extended - Lower Priority 53-200)/README.md`.

---

## 4. Reporting back

When a run completes, the useful summary for this session to receive back is: total new papers found,
how many were genuinely relevant (score > 0) vs. discarded as noise, top 10-20 by relevance score, and
where the PDFs/embeddings ended up. Honest yield numbers are more valuable here than hitting any particular
target count.
