# Onboarding: Waymo AV-Safety Research Corpus — for `agent-rag-research`

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

## 3. Already captured — exclude these before downloading

**173 arXiv IDs** already downloaded and present in `Research Papers/` or
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
