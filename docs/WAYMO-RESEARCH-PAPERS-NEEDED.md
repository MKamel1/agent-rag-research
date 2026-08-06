# Waymo's own published research — enumerated, split by downloadability

*Compiled 2026-08-06 by fetching both of Waymo's public research index pages and classifying every
entry by whether this repo's pipeline can obtain the PDF without a human. Companion to
`docs/superpowers/plans/2026-08-06-waymo-av-safety-corpus-expansion-v2.md` (§5 routes each group).*

**Sources, as rendered on 2026-08-06:**

| page | entries enumerated |
|---|---|
| `https://waymo.com/research/` | **98** |
| `https://waymo.com/safety/research/` | **54** |
| total | **152** |

No entry appears on both pages (verified: the two arXiv-ID sets are disjoint, intersection empty).
Both counts are what the page rendered on the fetch date — if either page lazy-loads or paginates
beyond what a single fetch returns, the true count could be higher. Re-fetch before treating either
number as permanent.

## 1. Split summary

| group | count | how it gets into the corpus |
|---|---|---|
| **A — arXiv ID available** | **114** | `--paper-ids-file` (`fixtures/waymo/waymo_authored_ids.txt`), the normal arXiv path |
| **B — public direct PDF, not on arXiv** | **15** | download the listed URL into `waymo/data/drop_in/papers/`, then `python -m app.ingest_local` |
| **C — no direct PDF published on Waymo's page** | **23** | **operator-sourced.** §4 below is the actual to-do list |
| total | 152 | |

Group A + B = **129 of 152 (85%)** are obtainable without a human. Group C is the deliverable the
operator actually has to work.

### Update 2026-08-06 — the operator's manually-curated drop-in delivery

A 449-PDF library was placed at `drop_in/waymo downloaded research/` after this document was first
written. Measured against it (read-only; filenames + `manifest.json` + `app.ingest_local.detect_arxiv_id`
run over every file, nothing moved or ingested):

| group | before | after this delivery |
|---|---|---|
| A — arXiv ID available (114) | 0 held locally | **97 of 114 present as PDFs** (`detect_arxiv_id` resolves them to their real arXiv id, so they stage under that id, not a `local:` one) |
| B — public direct PDF (15) | 0 held locally | **11 of 15 present.** Missing: **B1**, **B2** (the two ESV26 "Building scientific consensus…" papers) and **B7**, **B8** (the two IWAI 2024 active-inference posters) |
| C — needs manual sourcing (23) | 23 outstanding | **14 sourced, 9 still outstanding** — see the `status` column in §4 |

Still outstanding overall: **9 Group-C papers** (C2, C8, C10, C17, C18, C20, C21, C22, C23) and
**4 Group-B PDFs** (B1, B2, B7, B8 — all still fetchable from the URLs in §3, no manual work
needed). Nothing else on Waymo's two index pages is blocked on a human.

The 449 files are far more than gap-filling for these 23 — see
`docs/superpowers/plans/2026-08-06-waymo-av-safety-corpus-expansion-v2.md` §8 for what the library
actually contains and how it gets ingested.

### The finding that matters most

**All 114 Group-A arXiv IDs are already inside `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §3's 173-ID
"already captured — exclude these before downloading" list** (verified by set intersection: 114 of
114). That list refers to PDFs in an *external* folder (`Waymo — Senior Data Scientist
2026-07-21/Research Papers/`) which does not exist anywhere on this machine (`find /home/omar
-maxdepth 3 -iname "*Waymo*Senior*"` returns nothing). The scout script honours that list as an
exclusion set, so:

- `fixtures/waymo/paper_ids.txt` (1,437 ids) contains **0** of these 114 (verified by intersection).
- `waymo/data/papers.db`'s `ingest_state` tracks **0** of these 114 (verified by read-only query).

The corpus built so far therefore contains **none of Waymo's own published papers** — the exact
tier `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §1 names as priority #1. Fixing this is Task 2 of the
v2 plan.

---

## 2. Group A — downloadable via arXiv (114)

These go straight into the ingest target list. `2412.12129` and `2411.17826` are listed on
`waymo.com/research/` with OpenReview PDF links only; their arXiv mirrors were confirmed by search
(cross-checked on author list + title), so they belong here rather than in Group B.

**From `waymo.com/research/` (98):**

```
1812.03079 1908.11069 1910.05449 1910.06528 1912.04838 2004.00831 2005.01864 2005.03844
2005.04255 2005.04259 2005.04298 2005.07289 2005.09927 2008.06120 2008.07725 2008.08294
2010.06808 2010.16404 2103.01306 2103.02093 2103.05073 2103.16054 2104.09959 2104.10133
2105.07014 2106.08417 2106.13365 2106.13381 2106.14880 2108.06709 2109.01066 2111.14973
2112.07787 2112.12141 2201.05938 2202.05263 2203.03875 2203.12683 2204.12511 2205.03195
2205.04624 2205.05703 2206.00991 2206.01738 2206.03666 2206.03970 2206.04176 2206.04831
2206.07704 2206.07705 2207.03586 2207.05844 2208.06062 2210.05018 2210.07372 2210.08061
2210.08064 2210.08113 2210.08375 2210.09267 2210.09539 2210.13428 2210.13488 2212.01375
2212.03267 2212.06968 2212.07729 2212.08710 2212.11419 2304.02163 2304.03834 2305.12032
2306.01075 2306.03083 2306.03206 2306.04745 2309.14003 2309.14491 2309.16534 2309.16870
2309.16889 2310.08710 2401.02402 2404.03843 2404.19531 2405.00236 2405.02811 2405.03807
2409.18343 2410.23262 2411.17826 2412.12129 2505.24139 2506.08228 2506.19488 2506.21976
2510.06209 2605.22809
```

**From `waymo.com/safety/research/` (16):**

```
2011.00038 2011.00054 2208.12833 2212.08148 2303.15201 2305.07733 2306.17682 2410.08903
2502.08121 2505.14842 2506.02215 2506.09929 2507.17943 2508.19425 2604.19838 2604.27168
```

Note on the safety-page 16: several are the author-accepted arXiv version of a paywalled
journal/SAE article (e.g. `2212.08148` = SAE 2026-01-0519; `2508.19425` = SAE Int. J. Transp.
Safety 14(2); `2502.08121` = Springer chapter; `2410.08903` = Transportation Research Record).
Waymo publishes the arXiv link itself alongside the paywalled DOI — the arXiv copy is the one to
ingest, and these are **not** Group C.

---

## 3. Group B — public direct PDF, not on arXiv (15)

**Status 2026-08-06:** 11 of these 15 already arrived in the operator's drop-in delivery —
B3, B4, B5, B6, B9, B10, B11, B12, B13, B14, B15 are all in
`drop_in/waymo downloaded research/Research Papers/01_Safety_Statistics_Evaluation/`. Only **B1,
B2, B7, B8** still need fetching from the URLs below.

Downloadable without a login, but not through the arXiv path. Route: fetch the URL into
`waymo/data/drop_in/papers/`, then run `python -m app.ingest_local` from `waymo/data/`
(`app/ingest_local.py` mints a content-addressed `local:<sha256>` id for a PDF arXiv doesn't have —
see its module docstring, path 2). None of these were downloaded while writing this document.

| # | title | authors | venue / year | direct PDF |
|---|---|---|---|---|
| B1 | Building scientific consensus on the crash safety performance of automated driving systems (ESV26-294) | Campolettano, E.; Scanlon, J. M.; Kusano, K. D. | 28th ESV, Toronto, 2026 | `https://static.nhtsa.gov/esv/pdf/ESV/Proceedings/28/ESV26-294.pdf` |
| B2 | Building scientific consensus on the crash safety performance of automated driving systems (ESV26-252) | Scanlon, J. M.; Kusano, K. D.; McMurry, T. L.; Gode, T.; Victor, T. | 28th ESV, Toronto, 2026 | `https://static.nhtsa.gov/esv/pdf/ESV/Proceedings/28/ESV26-252.pdf` |
| B3 | Collision avoidance effectiveness of an automated driving system using a human driver behavior reference model in reconstructed fatal collisions | Scanlon, J. M.; Kusano, K. D.; Engström, J.; Victor, T. | SAE 2026-01-0520 | `https://storage.googleapis.com/waymo-uploads/files/documents/safety/Collision%20Avoidance%20Effectiveness%20of%20an%20Automated%20Driving%20System%20Using%20a%20Human%20Driver%20Behavior%20Reference%20Model%20in%20Reconstructed%20Fatal%20Collisions.pdf` |
| B4 | Ride-hailing in the Safe System: Increased Seat Belt Compliance and Late Model Year Vehicles (IRC-25-67) | Campolettano, E. T.; Scanlon, J. M.; McMurry, T. L.; Kusano, K. D. | IRCOBI 2025, Vilnius | `https://www.ircobi.org/wordpress/downloads/irc25/pdf-files/2567.pdf` |
| B5 | Do Autonomous Vehicles Outperform Latest-Generation Human-Driven Vehicles? A Comparison to Waymo's Auto Liability Insurance Claims at 25 Million Miles | Di Lillo, L.; Gode, T.; Zhou, X.; Scanlon, J. M.; Chen, R.; Victor, T. | Waymo white paper, 2024 | `https://storage.googleapis.com/waymo-uploads/files/documents/safety/Comparison%20of%20Waymo%20and%20Human-Driven%20Vehicles%20at%2025M%20miles.pdf` |
| B6 | Characterising vulnerable road user evasive manoeuvring in real-world crashes: Injury risk implications (IRC-24-117) | Campolettano, E. T.; Scanlon, J. M.; Kusano, K. D. | IRCOBI 2024 | `https://www.ircobi.org/wordpress/downloads/irc24/pdf-files/24117.pdf` |
| B7 | Active inference-based modeling of human driver collision avoidance behavior (poster) | Schumann, J. F.; Engström, J.; O'Kelly, M.; Kober, J.; Zgonnikov, A. | 5th Int. Workshop on Active Inference, 2024 | `https://storage.googleapis.com/waymo-uploads/files/documents/safety/IWAI_poster_Schumann%20et%20al.pdf` |
| B8 | Active inference as a general framework for modeling human driving behavior (poster) | Engström, J.; O'Kelly, M.; Johnson, L.; Dinparastdjadid, A.; Liu, S-Y.; Messias, J. | 5th Int. Workshop on Active Inference, 2024 | `https://storage.googleapis.com/waymo-uploads/files/documents/safety/IWAI%20poster%2C%20Engstrom%20et%20al.%20final.pdf` |
| B9 | Descriptive analysis of cyclist dooring events using data from the National Electronic Injury Surveillance System (IRC-23-112) | Campolettano, E. T.; Scanlon, J. M.; Victor, T. | IRCOBI 2023, Cambridge | `https://www.ircobi.org/wordpress/downloads/irc23/pdf-files/23112.pdf` |
| B10 | Representative pedestrian collision injury risk distributions for a dense-urban US ODD using naturalistic dash camera data (23-0075) | Campolettano, E.; Scanlon, J. M.; Victor, T. | 27th ESV, Yokohama, 2023 | `https://static.nhtsa.gov/esv/pdf/ESV/Proceedings/27/27ESV-000075.pdf` |
| B11 | Interpreting safety outcomes: Waymo's performance evaluation in the context of a broader determination of safety readiness | Favaro, F. M.; Victor, T.; Hohnhold, H.; Schnelle, S. | ISTDM2023, Ispra | `https://storage.googleapis.com/waymo-prod-cdn/uploads/ecc0033d86be3edaaccadaf8c6879cb4-Interpreting_Safety_Outcomes-_Waymo___s_Performance_Evaluation_in_the_Context_of_a_Broader_Determination_of_Safety_Readiness.pdf` |
| B12 | Framework for a conflict typology including contributing factors for use in ADS safety evaluation (23-0328-O) | Kusano, K.; Scanlon, J.; Brännström, M.; Engström, J.; Victor, T. | 27th ESV, Yokohama, 2023 | `https://static.nhtsa.gov/esv/pdf/ESV/Proceedings/27/27ESV-000328.pdf` |
| B13 | Challenges for the evaluation of automated driving systems using current ADAS and active safety test track protocols (23-0329-O) | Schnelle, S.; Kusano, K.; Favaro, F.; Sier, G.; Victor, T. | 27th ESV, Yokohama, 2023 | `https://static.nhtsa.gov/esv/pdf/ESV/Proceedings/27/27ESV-000329.pdf` |
| B14 | Safety performance of the Waymo rider-only automated driving system at one million miles | Victor, T.; Kusano, K.; Gode, T.; Chen, R.; Schwall, M. | Waymo white paper, 2023 | `https://storage.googleapis.com/waymo-uploads/files/documents/safety/Safety%20Performance%20of%20Waymo%20RO%20at%201M%20miles.pdf` |
| B15 | Waymo safety report | Waymo | Waymo, 2021 | `https://storage.googleapis.com/waymo-prod-cdn/uploads/d1623d42ed7aaea46993c22ea7e50612-Waymo_Safety_Report_02-2021.pdf` |

---

## 4. Group C — needs manual sourcing (23)

**This section is the operator-facing to-do list.** Every entry below is published on
`https://waymo.com/safety/research/` with a DOI or publisher link only — no arXiv mirror and no
direct PDF on Waymo's own page. `access` distinguishes two very different amounts of work:

- `paywalled` — a subscription/purchase is required (Taylor & Francis, Elsevier, SAE, Springer).
- `open-access, no direct link` — the journal is (or appears to be) free to read, but Waymo's page
  publishes only the DOI, so no PDF URL was captured here. Verified as "no direct PDF link on the
  source page", **not** verified as "unreachable" — these are the cheap ones to fetch first.

Once a PDF is obtained, drop it into `waymo/data/drop_in/papers/` and run
`python -m app.ingest_local` from `waymo/data/` — same route as Group B, no new mechanism.

| # | title | authors | venue / year | access | link | status (2026-08-06 drop-in delivery) |
|---|---|---|---|---|---|---|
| C1 | Building a credible case for safety: Waymo's approach for the determination of absence of unreasonable risk | Favaro, F.; Fraade-Blanar, L.; Schnelle, S.; Victor, T.; Peña, M.; Engström, J.; Scanlon, J.; Kusano, K.; Smith, D. | Journal of Safety Research, 96 (2026) | paywalled (Elsevier) | `https://doi.org/10.1016/j.jsr.2025.10.019` | **SOURCED*** — `058_Favaro_BuildingCredibleCaseForSafety_2023.pdf` (2023 whitepaper version of the same title, not the JSR-96 journal text) |
| C2 | A mechanistic approach to modeling omnidirectional motorcyclist injury risk | Schubert, A.; Campolettano, E. T.; Scanlon, J. M.; McMurry, T. L.; Unger, T. | Traffic Injury Prevention, 26(sup1) (2025) | paywalled (Taylor & Francis) | `https://doi.org/10.1080/15389588.2025.2570829` | **STILL NEEDED** |
| C3 | Potential Safety Benefits Associated with Speed Limit Compliance in San Francisco and Phoenix | Campolettano, E. T.; Kusano, K. D.; Victor, T. | Traffic Injury Prevention (2025) | paywalled (Taylor & Francis) | `https://doi.org/10.1080/15389588.2025.2538726` | **SOURCED** — `053_Campolettano_SpeedLimitCompliance_SF_Phoenix_2025.pdf` |
| C4 | TARGET setting for high severity collisions: tolerance-based assessment of risk for generalized event thresholds | Campolettano, E. T.; Scanlon, J. M.; McMurry, T. L.; Kusano, K. D.; Victor, T. | Traffic Safety Research, 9 (2025) | open-access, no direct link | `https://doi.org/10.55329/wxoa2712` | **SOURCED** — `054_Campolettano_TARGETSetting_HighSeverityCollisions_2025.pdf` |
| C5 | Determining Absence of Unreasonable Risk: Approval Guidelines for an Automated Driving System Deployment | Favaro, F.; Schnelle, S.; Fraade-Blanar, L.; Victor, T.; Peña, M.; Webb, N.; Smith, D. | SAE Int. J. Connected and Automated Vehicles, 9(4) (2026) | paywalled (SAE) | `https://doi.org/10.4271/12-09-04-0026` | **SOURCED** — `Favaro_DeterminingAbsenceUnreasonableRisk_2025.pdf` |
| C6 | Comparison of Waymo Rider-Only Crash Rates by Crash Type to Human Benchmarks at 56.7 Million Miles | Kusano, K. D.; Scanlon, J. M.; Chen, Y.; McMurry, T. L.; Gode, T.; Victor, T. | Traffic Injury Prevention, 26(sup1) (2025) | paywalled (Taylor & Francis) | `https://doi.org/10.1080/15389588.2025.2499887` | **SOURCED** — `Kusano_CrashRates56.7MillionMiles_2025.pdf` |
| C7 | Developing a Safety Management System for the Automated Vehicle Industry | Wichner, D.; Wishart, J.; Sergent, J.; Swaminathan, S. | SAE Technical Paper 2025-01-8673 (2025) | paywalled (SAE) | `https://doi.org/10.4271/2025-01-8673` | **SOURCED** — `055_Wichner_SafetyManagementSystem_AVIndustry_2025.pdf` |
| C8 | Baseline vulnerable road user injury risk in multiple U.S. dense-urban driving environments | Campolettano, E. T.; Scanlon, J. M.; Kadar, I.; Lavy, L. L.; Moura, D.; Kusano, K. D. | Traffic Injury Prevention (2024) | paywalled (Taylor & Francis) | `https://doi.org/10.1080/15389588.2024.2364050` | **STILL NEEDED** |
| C9 | Kinematic characterization of micro-mobility vehicles during evasive maneuvers | Terranova, P.; Liu, S. Y.; Jain, S.; Engström, J.; Perez, M. A. | Journal of Safety Research, 91 (2024) | paywalled (Elsevier) | `https://doi.org/10.1016/j.jsr.2024.09.020` | **SOURCED** — `056_Terranova_KinematicCharacterization_MicroMobility_2024.pdf` |
| C10 | Representative cyclist collision injury risk distributions for a dense-urban US ODD using naturalistic dash camera data | Campolettano, E. T.; Scanlon, J. M.; Kusano, K. D. | SAE Technical Paper 2024-01-2645 (2024) | paywalled (SAE) | `https://doi.org/10.4271/2024-01-2645` | **STILL NEEDED** |
| C11 | Comparative safety performance of autonomous and human drivers: A real-world case study of the Waymo One service | Di Lillo, L.; Gode, T.; Zhou, X.; Atzei, M.; Chen, R.; Victor, T. | Heliyon, 10(14) (2024) | open-access, no direct link | `https://doi.org/10.1016/j.heliyon.2024.e34379` | **SOURCED** — `DiLillo_ComparativeSafetyPerformance_Heliyon_2024.pdf` |
| C12 | Modeling road user response timing in naturalistic traffic conflicts: A surprise-based framework | Engström, J.; Liu, S. Y.; Dinparastdjadid, A.; Simoiu, C. | Accident Analysis & Prevention, 198 (2024) | paywalled (Elsevier) | `https://doi.org/10.1016/j.aap.2024.107460` | **SOURCED** — `Engstrom_ModelingRoadUserResponseTiming_SurpriseFramework_2024.pdf` |
| C13 | Resolving uncertainty on the fly: modeling adaptive driving behavior as active inference | Engström, J.; Wei, R.; McDonald, A. D.; Garcia, A.; O'Kelly, M.; Johnson, L. | Frontiers in Neurorobotics, 18 (2024) | open-access, no direct link | `https://doi.org/10.3389/fnbot.2024.1341750` | **SOURCED** — `Engstrom_ResolvingUncertaintyOnTheFly_ActiveInference_2024.pdf` |
| C14 | Comparison of Waymo rider-only crash data to human benchmarks at 7.1 million miles | Kusano, K. D.; Scanlon, J. M.; Chen, Y. H.; McMurry, T. L.; Chen, R.; Gode, T.; Victor, T. | Traffic Injury Prevention, 25(sup1) (2024) | paywalled (Taylor & Francis) | `https://doi.org/10.1080/15389588.2024.2380786` | **SOURCED** — `Kusano_Comparison7.1MillionMiles_2024.pdf` |
| C15 | Benchmarks for retrospective automated driving system crash rate analysis using police-reported crash data | Scanlon, J. M.; Kusano, K. D.; Fraade-Blanar, L. A.; McMurry, T. L.; Chen, Y. H.; Victor, T. | Traffic Injury Prevention, 25(sup1) (2024) | paywalled (Taylor & Francis) | `https://doi.org/10.1080/15389588.2024.2380522` | **SOURCED** — `Scanlon_BenchmarksRetrospectiveCrashRateAnalysis_2024.pdf` |
| C16 | RAVE checklist: Recommendations for overcoming challenges in retrospective studies of Automated Driving Systems | Scanlon, J. M.; Teoh, E. R.; Kidd, D. G.; Kusano, K. D.; Bärgman, J.; Chi-Johnston, G.; Di Lillo, L.; Favaro, F.; Flannagan, C.; Liers, H.; Lin, B.; Lindman, M.; McLaughlin, S.; Perez, M.; Victor, T. | Traffic Injury Prevention (2024) | paywalled (Taylor & Francis) | `https://doi.org/10.1080/15389588.2024.2435620` | **SOURCED** — `Scanlon_RAVEChecklist_2024.pdf` |
| C17 | Bridging the gap: Mechanistic-based cyclist injury risk curves using two decades of crash data | Schubert, A.; Campolettano, E. T.; Scanlon, J. M.; McMurry, T. L.; Unger, T. | Traffic Injury Prevention, 25(sup1) (2024) | paywalled (Taylor & Francis) | `https://doi.org/10.1080/15389588.2024.2400276` | **STILL NEEDED** |
| C18 | Passenger and heavy vehicle collisions with pedestrians: Assessment of injury mechanisms and risk | Schubert, A.; Babisch, S.; Scanlon, J. M.; Campolettano, E. T.; Roessler, R.; Unger, T.; McMurry, T. L. | Accident Analysis & Prevention, 190 (2023) | paywalled (Elsevier) | `https://doi.org/10.1016/j.aap.2023.107139` | **STILL NEEDED** |
| C19 | World model learning from demonstrations with active inference: Application to driving behavior | Wei, R.; Garcia, A.; McDonald, A.; Markkula, G.; Engström, J.; Supeene, I.; O'Kelly, M. | IWAI 2022, CCIS vol. 1721, Springer (2023) | paywalled (Springer) | `https://doi.org/10.1007/978-3-031-28719-0_9` | **SOURCED** — `057_Wei_WorldModelLearning_ActiveInference_2023.pdf` |
| C20 | Determination of functional scenarios for intersection collisions | Bangert, L. G.; Lubash, T.; Scanlon, J. M.; Kusano, K. D.; Riexinger, L. E. | Accident Analysis & Prevention, 193 (2023) | paywalled (Elsevier) | `https://doi.org/10.1016/j.aap.2023.107326` | **STILL NEEDED** |
| C21 | Methodology for determining maximum injury potential for automated driving system evaluation | Kusano, K.; Victor, T. | Traffic Injury Prevention, 23(sup1) (2022) | paywalled (Taylor & Francis) | `https://doi.org/10.1080/15389588.2022.2125231` | **STILL NEEDED** |
| C22 | An omni-directional model of injury risk in planar crashes with application for autonomous vehicles | McMurry, T. L.; Cormier, J. M.; Daniel, T.; Scanlon, J. M.; Crandall, J. R. | Traffic Injury Prevention, 22(sup1) (2021) | paywalled (Taylor & Francis) | `https://doi.org/10.1080/15389588.2021.1955108` | **STILL NEEDED** |
| C23 | Waymo simulated driving behavior in reconstructed fatal crashes within an autonomous vehicle operating domain | Scanlon, J. M.; Kusano, K. D.; Daniel, T.; Alderson, C.; Ogle, A.; Victor, T. | Accident Analysis & Prevention, 163 (2021) | paywalled (Elsevier) | `https://doi.org/10.1016/j.aap.2021.106454` | **STILL NEEDED** |

### Suggested order of work for the operator

**Revised 2026-08-06** — the original ordering (C4/C11/C13 first, then C6/C14/C15/C16) is now moot:
all seven of those are in the drop-in delivery. What is left:

1. **C8, C10, C17, C18, C22** — the injury-risk/VRU cluster (Campolettano, Schubert, McMurry). Five
   papers, all Taylor & Francis / Elsevier / SAE paywalled.
2. **C2** — Schubert motorcyclist injury risk (Taylor & Francis).
3. **C20, C21, C23** — Bangert functional scenarios, Kusano maximum injury potential, Scanlon
   reconstructed fatal crashes (Elsevier / Taylor & Francis).
4. Nothing in the v2 plan blocks on Group C: it is additive, and `app.ingest_local` is idempotent
   by content hash (`mint_local_ref`), so PDFs can be dropped in at any point during or after the
   main build.
