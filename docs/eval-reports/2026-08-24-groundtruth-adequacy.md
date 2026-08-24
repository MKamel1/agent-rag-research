# GTQ-1 — Is the ground-truth set actually deep, and does it test both error directions?

Assessment of the three Waymo ground-truth fixture sets for **adequacy** (depth, false-positive
coverage, false-negative coverage, redundancy/blind spots). Correctness was already established by
the GT-X verification tickets; nothing here re-checks it. Every number below carries the measurement
that produced it; where a claim rests on my reading rather than a count, it says so.

Inputs, all read-only: `fixtures/eval/waymo_gt_verified.json` (84 items = 68 answerable / 16
known-absent), `fixtures/eval/gt_wmr.json` (82 = 70 / 12), and their source sets
`waymo_gt_a.json` / `waymo_gt_b.json`. Corpus: `/home/omar/ai-projects/research-system-rag/waymo/data/papers.db`
(absolute path; 1,738 papers, 235,918 blocks, 46,155 chunks, 8,266 extracted tables, 24,708 figures),
opened `mode=ro`. No fixture, no DB row, and no product code was modified. The analysis scripts that
produced these numbers were throwaway tooling under `/tmp/opencode/GTQ-1/` (this ticket permits one
new report file only); each method is specified precisely enough below to re-derive every figure.

> **Posture.** All retriever numbers here come from deliberately trivial baselines (a keyword index
> and a toy TF-IDF), run offline against raw corpus text. They bound what a *trivial* system could
> do; they are not simulations of the production embedding pipeline, which was not run.

## Method summary

- **Inverted index**: every `blocks.text` lowercased, tokenized `[a-z0-9]+(\.[a-z0-9]+)?`
  (decimals like `7.14` kept whole), tokens len ≥ 3 → term → set of papers containing it.
- **Rarest-term grep test**: for each answerable item, take the question's content terms (after an
  English stoplist plus generic AV vocabulary), pick the one present in the fewest distinct papers,
  and ask whether the gold paper contains it. A hit means a naive keyword search already lands on
  the right paper — an upper bound on trivially-passable retrieval.
- **Toy TF-IDF baseline**: score each paper by Σ idf(term) · sqrt(tf) over question terms;
  report gold-paper rank. Same caveat as above.
- **Informative-term overlap**: fraction of the question's *rare* terms (document frequency < 200
  of 1,738 papers) that occur in the gold paper. Low overlap ⇒ paraphrase distance ⇒ a probe for
  lexical-match-free retrieval.
- **Near-duplicate scan**: Jaccard over content tokens across all four fixtures (deduped by ID),
  manually adjudicated — token Jaccard turned out to be a *weak* dupe detector here (below).
- **Manual classification passes**: all 27 answerable-hard items read and labeled by hardness
  source; all 14 unique absent facts read (with the authors' own `absence_search` trails) and typed.

## Verdict summary

| Axis | Verdict in one line |
|---|---|
| Depth | Real but front-loaded: verified set resists trivial retrieval on 47% of items and its hard labels are ~89% honest; gt_wmr is much shallower and its hard tier is entirely keyword-findable |
| False-positive coverage | The set's strength: 13 of 14 unique absent facts have genuine adjacent near-misses — but the specific fabrication mode the system actually failed with is probed by exactly 1 unique fact |
| False-negative coverage | Under-tested by construction: half the set is rarest-keyword reachable; genuine probes exist (9 zero-informative-overlap items) but tables/arithmetic are nearly absent |
| Redundancy & blind spots | Material issues: 3 unflagged true duplicates across sets, 3 paraphrase families double-counting facts inside the verified set, 30 distinct gold papers carrying 64 items, and whole corpus themes untouched |

---

## Axis 1 — Depth

### 1.1 The quoted difficulty split includes non-answerable labels

The 15 easy / 34 medium / 35 hard headline counts cover all 84 items. Among the 68 answerable items
the split is **13 easy / 28 medium / 27 hard**; absent items carry difficulty labels too, which no
retrieval run can ever confirm (they are refusals, not lookups). Depth claims below use
answerable-only counts.

### 1.2 Rarest-keyword upper bound (the "grep would answer it" test)

> **Reviewer note, added on merge — the ratio replicates, the absolute rates do not.** An
> independent reimplementation of this test (rarest term by distinct-paper document frequency,
> tokens of 4+ characters, substring match over `chunks.text`) produced **19/64 = 0.297** for
> verified-84 and **38/66 = 0.576** for GT-WMR, against the 0.531 / 0.818 below. The absolute
> numbers are clearly sensitive to tokenisation and to how "rarest" is defined, so **they should not
> be quoted as a stable property of either fixture.** What survives both implementations is the
> comparison this section actually rests on: GT-WMR is roughly 1.5–2x more keyword-findable than
> verified-84. Read the ratio, not the rates.



For the 64 answerable items that anchor to a single gold paper (4 multi-paper-synthesis items and
the vision-derived items are excluded by construction):

| Set | rarest-keyword hits gold paper | toy TF-IDF top-1 | top-3 | MRR |
|---|---|---|---|---|
| waymo_gt_verified (n=64) | **34/64 = 53.1%** | 16/64 = 25.0% | 30/64 = 46.9% | 0.408 |
| gt_wmr (n=66) | **54/66 = 81.8%** | 25/66 = 37.9% | 44/66 = 66.7% | 0.551 |

Verified-set breakdown:

- By difficulty: easy 11/13 (85%), medium 15/27 (56%), hard 8/24 (33%). The labels correlate with
  grep-resistance, so they are not noise — but a third of the hard tier is still reachable by one
  lucky keyword at paper level.
- By dimension: single-passage factual lookup 8/13 (62%), numeric/quantitative 12/20 (60%), negation
  and scope 5/7 (71%), methodological 7/16 (44%), temporal/versioned 2/6 (33%), multi-paper 0/2.
  Negation/scope being highly findable is expected — its trap lives in the answer stage, not
  retrieval.
- gt_wmr's hard tier: **12/12 rarest-keyword reachable.** Its "hard" label measures nothing on the
  retrieval side. (Its numeric/quantitative dominance — 42/82 items vs 24/84 in the verified set —
  pushes the same way.)

Two readings matter. First, hitting the gold *paper* is not answering the *question*: most of these
items demand extracting a specific number or CI from the found paper, so 53% is an upper bound on
trivial passage, not a pass rate. Second, the honest conclusion is asymmetric: the verified set has
a genuinely resistant majority (47% unreachable by their own rarest keyword; worst toy-TF-IDF ranks
636, 340, 233 — for Q-GTA-007, Q-GTA-020, Q-GTA-029), while **gt_wmr would surrender to a
grep-based system on five of every six questions**, including every question it calls hard.

### 1.3 What makes the 27 answerable "hard" items hard

I read all 27. Classification by hardness source:

| Hardness source | n | Items |
|---|---|---|
| Cross-document synthesis (two+ papers, or corpus-vs-external-literature contrast) | 9 | GTA-005, 008, 015, 021, 031, 033, WAYB-010, 011, 012 |
| Multi-part enumeration inside one section (taxonomy + thresholds + distribution) | 8 | GTA-002, 007, 023, 025, 026, 028, 029, WAYB-025 |
| Figure/table-layout extraction (vision-derived) | 4 | WAYB-027, GTA-042, 043, 044 |
| Statistical fine-distinction or scope-flip | 3 | GTA-004, 006, 009 |
| Deliberately oblique phrasing (model's own terms banned from the question) | 1 | WAYB-006 |
| Numeric extraction inflated to hard | 2 | WAYB-019, WAYB-036 |

Notes on the interesting ones:

- **Genuinely hard and correctly labeled**: Q-GTA-009 (which severity outcome flips significance
  under dynamic benchmark adjustment — a scope-flip requiring both conclusions), Q-WAYB-010 (the
  set's only cross-paper arithmetic: PV-RCNN++'s own 69.91 mAPH + SWFormer's claimed +0.42 =
  ≈70.33), Q-GTA-033 (EMMA text-vs-MotionLM-quantization disagreement with rationale), Q-WAYB-006
  (MultiPath intent/control uncertainty described without using either term — the set's best
  designed vocabulary-mismatch item).
- **Label inflation exists but is modest**: Q-WAYB-019 asks for three CIs out of one sentence —
  extraction, not synthesis; Q-WAYB-036 dresses two numbers from one section ("Comparisons to Prior
  Studies" of the 56.7M paper) as temporal synthesis. Q-GTA-002 is borderline (multi-constraint but
  single-section).
- So **~24–25 of 27 hard labels are defensible (~89–93%)**. The verified set's depth reputation is
  earned; it is just concentrated (see 1.2) and, per axis 4, partially duplicated.

### 1.4 Depth verdict

The verified set is deeper than a lookup set but shallower than its labels suggest at the margins:
53% rarest-keyword reachable, hard-tier honesty ~90%, and the deepest instruments (cross-paper
synthesis 6 items, arithmetic 1 item, table-grounded extraction 1 item) are exactly the thinnest
slices. gt_wmr fails the same test outright (81.8% reachable; hard tier 12/12 trivial).

---

## Axis 2 — False-positive coverage

### 2.1 The 16 known-absent items are 14 unique facts

Two flagged duplicate pairs (`Q-GTA-036`≈`Q-WAYB-034`, `Q-GTA-037`≈`Q-WAYB-009`) mean 16 items
cover 14 distinct absences. Typology with near-miss strength (my judgment after reading each fact
plus the author-recorded search trail):

| Absence (unique fact) | Items | Near-miss strength | What sits adjacent in the corpus |
|---|---|---|---|
| Waymo LiDAR wavelength | WAYB-009 + GTA-037 | strong | 35 wavelength chunks / 20 papers: 1550 nm FMCW assumption + Innovusion Falcon, 905 nm laser-diode tutorial |
| Zoox crash rate vs humans | WAYB-034 + GTA-036 | strong | Zoox appears as a filter row in 2403.14648 while Waymo/Cruise CPMM are computed beside it; old 1-per-1900-mi disengagement claim |
| Tesla FSD crash rate vs human | GTA-035 | very strong | Tesla's self-reported 0.31 cpmm quoted — then bias-analyzed — in the crash-database comparability paper |
| Waymo-run RCT | GTA-034 | strong | Corpus argues RCTs in traffic are unethical/infeasible and equates RCT logic with sim domain randomization |
| WOMD collision fraction | GTA-041 | very strong | 106–130 chunks pair WOMD×collision — all simulated-rollout outcome metrics, never dataset composition |
| Who underwrites Waymo + premium discount | GTA-040 | strong | "Underwriter(s)" collides with Underwriters Laboratories/UL 4600; Swiss Re collaboration described in detail |
| Cruise vs Blincoe-adjusted benchmark | WAYB-035 | strong | A Cruise crash rate exists — computed under a different methodology (raw DMV/CPUC vs Uber TNC) |
| 100M-mile rider-only crash study | WAYB-039 | strong | The 100M-mileage milestone itself exists (2507.17943, July 2025) — as mileage, not a crash-rate study |
| Gen-5-specific disengagement rate | WAYB-022 | moderate | Aggregate disengagement reporting exists; no hardware-generation breakdown |
| Waymo-attributed fatalities by victim category | WAYB-021 | moderate | Human-benchmark fatality rates and severity tiers exist; no Waymo-attributed counts |
| Cumulative ridership total | GTA-038 | moderate | Two weekly-rate snapshots (early 2020; 250k rides/week 2025) — neither cumulative |
| RAVE checklist self-validation study | WAYB-028 | moderate | Statistical-power discussion inside the very paper asked about |
| Blinding procedure in fatigue framework | WAYB-029 | moderate | Survey-assessment framing invites it; "blind" 0-hit in that paper |
| Waymo One ride price | GTA-039 | weak | 'Fare' appears only definitionally (CPUC permit taxonomy) — the closest thing to a free absence |

Census: **13 of 14 unique absences have genuine adjacent content a retriever will plausibly
surface; 1 is weak-adjacent; none is content-free.** The ticket hypothesized absences might be
"close to free" — measured, they nearly never are. This half of the set discriminates.

### 2.2 How many items probe the demonstrated fabrication mode?

The fabrication run's failure mode was generic-statement-to-specific-subject attribution ("905 nm"
taken from a laser tutorial that never mentions Waymo). Counting depends on how strictly the mode is
defined, so here are all three tiers:

- **Tier A — exact mechanism**: a fact stated generically in an unrelated source, bindable to the
  subject. **1 unique fact / 2 items** (wavelength). The ticket guessed "if the answer is one" — at
  strict definition, the answer is one.
- **Tier B — wrong-granularity/wrong-subject binding of corpus-native numbers** (self-report taken
  as independent measurement, aggregate taken as specific, weekly taken as cumulative, mileage
  milestone taken as safety study): Zoox ×2, Tesla ×1, Gen-5 ×1, fatalities ×1, ridership ×1,
  100M-mile ×1, Cruise-benchmark ×1 = **8 items / 7 unique facts**.
- **Tier C — refuse-despite-plausible-document content** (capability attributed to a document that
  discusses the concept without doing the thing): RAVE ×1, blinding ×1, RCT ×1, WOMD ×1,
  underwriter ×1 = **5 items / 5 unique facts**.

So refusal-under-plausible-evidence broadly construed covers ~15/16 items — but the *specific*
mechanism caught in the fabrication run is tested once. The set is thick where the system is
merely weak-adjacent and thin exactly where it demonstrably broke.

### 2.3 FP verdict

Strong discrimination breadth, narrow penetration of the known failure mode. Also worth noting:
absent-item documentation is inconsistent — `expected_behavior` is recorded for 8/16 verified-absent
items (vs 12/12 in gt_wmr), so half the verified absent items don't state what a correct refusal
looks like.

---

## Axis 3 — False-negative coverage

An FN in the operator's sense includes missing something the corpus does contain. Measurements:

- **Zero lexical anchor is impossible on this set**: 0/64 items lack *any* question-term overlap
  with their gold paper. But restricting to *informative* terms (df < 200), **16 items fall below
  0.34 overlap and 9 share no informative term at all**: Q-GTA-004 (question says "resampling,"
  paper says "parametric bootstrap"), Q-GTA-007 ("hit from behind" vs "F2R Struck"), Q-GTA-013,
  017, 020, 021, 022, 027, 028. These are real paraphrase-distance probes.
- **Retrieval-hostile tail**: 5 items land beyond rank 50 for the toy TF-IDF (worst 636). Half the
  set (34/64) is nonetheless rarest-keyword reachable — those items cannot detect an FN failure on
  the retrieval side at all; they only test reading/extraction.
- **Buried answers are nearly untested relative to what the corpus offers**: gold anchors are
  63 prose blocks and **1 table block**, even though the DB holds 8,266 extracted tables and
  60 of the 68 answerable items' gold papers contain at least one extracted table. Four items
  (vision-derived: WAYB-027, GTA-042, 043, 044) require figure/table-*layout* reading — good, but
  they test visual layout more than buried-tabular-data retrieval.
- **Arithmetic**: 1 item (Q-WAYB-010). No derived rates, deltas, or multiples anywhere else.

### FN verdict

Plainly: **the set under-tests false negatives for any system with decent lexical recall.**
Roughly half of it is winnable by substring luck, the buried-data dimension is 1/68 against a
corpus where tables are ubiquitous, and derivation is 1/84. The nine zero-informative-overlap
items are the honest core of FN testing and deserve to grow.

---

## Axis 4 — Redundancy and blind spots

### 4.1 Duplicates

Token-Jaccard turns out to be nearly useless here: the two *flagged* duplicates sit at J = 0.19 and
0.23 because they are paraphrases. Manual adjudication of the ≥0.30 candidates and of topic families
found:

**Unflagged true duplicates across sets** (same gold paper, same requested numbers — they collide
if the sets are ever evaluated together):
- `Q-WMR-029` ≈ `Q-WAYB-015` (25.3M-mile PD/BI claim counts vs benchmark)
- `Q-WMR-012` ≈ `Q-WAYB-016` (airbag-deployment freeway-rate geographic range)
- `Q-WMR-053` ≈ `Q-WAYB-001` (actual-vs-simulated contact events, 2011.00038)

**Paraphrase families inside the verified set itself** (double-counted facts within one eval):
- `Q-GTA-005` ≈ `Q-WAYB-036`: both ask how the police-reported/any-injury reductions and CIs changed
  between the 7.1M and 56.7M studies (55%→65%, 80%→79%).
- `Q-GTA-004` ≈ `Q-WAYB-025`: both ask about Nelson(1970) rate-ratio CIs in 2312.12675 (different
  angles — why-preferred vs implementation-validation).
- `Q-GTA-008` ≈ `Q-WAYB-011`: both ask whether insurance-claims and crash-rate methodologies give
  similar magnitudes and which is larger.

### 4.2 Concentration

64 paper-anchored answerables spread over only **30 distinct gold papers**; the top six papers
carry **34/64 (53%)** (56.7M study ×10, 7.1M study ×6, Stoplights-to-On-Ramps ×6, WOMD ×5, 2011
safety report ×4, scaling laws ×3). Verified ∪ wmr covers 73 distinct papers of 1,738. Retrieval
evaluations on this set therefore measure navigation of roughly a dozen documents far more than
they measure corpus-scale retrieval.

### 4.3 Blind spots (corpus themes with zero or near-zero items)

From title censuses over `papers`: adversarial/attack/security ≈ **51 papers, 0 items**;
simulation ≈ 151 titles, ~4 items (WOSAC/Waymax); human-factors-ish ≈ 161 titles, 3 items
(fatigue ×2, teleoperation ×1). Also absent as question shapes: derived quantities (1 item),
table-grounded lookup (1), cross-paper contradiction beyond Q-GTA-033 (1), arXiv-version/metadata
provenance (0 — the temporal dimension's 7 items are all content milestones, e.g. mileage
mileposts, not publication/version drift), and answerable questions about non-Waymo subjects
(Q-WAYB-018's Cruise direction is the only one).

### 4.4 Schema inconsistencies noticed while measuring (reported, not fixed)

- `question_type` is null on all 19 GT-B-sourced items (GT-A populated it).
- `expected_behavior` present on 8/16 verified absent items vs 12/12 gt_wmr absent items.
- `duplicate_of` flags cover only 2 pairs; the families above are unflagged.

---

## Ranked list: what to add (most valuable first)

1. **4–6 Tier-A attribution traps** — questions asking for a specific-subject technical spec whose
   generic form exists in an adjacent-domain paper (sensor specs, compute modules, battery/chemistry
   figures, regulatory limits). Shape: "What X does [subject]'s [component] use?" with a real X
   sitting in an unrelated corpus paper. *Closes*: the demonstrated fabrication mode, currently
   probed by 1 unique fact (Axis 2.2).
2. **Dedupe adjudication before any next merge** — resolve the three intra-verified families
   (keep one of each or differentiate sharply) and mark the three cross-set pairs if verified+wmr
   are ever combined. Pure curation, no new authoring. *Closes*: double-counted facts inflating
   apparent coverage (Axis 4.1).
3. **6–10 table-anchored numeric items** — gold anchor in a `type='table'` block or the `tables`
   store; ask for the cell value / row comparison. *Closes*: buried-data FN gap (currently 1/68
   against 8,266 extracted tables).
4. **4–6 derived-quantity items** — compute a rate, delta, multiple, or percentage from two numbers
   in one or two passages (the Q-WAYB-010 shape generalized). *Closes*: arithmetic dimension
   (currently 1/84).
5. **3–5 cross-paper tension items** — where two corpus papers' numbers/benchmarks/method choices
   disagree or don't compose; require naming both sides. *Closes*: synthesis depth beyond 6 items
   and adds a second contradiction probe besides Q-GTA-033.
6. **Rebalance gt_wmr's hard tier** — relabel honestly (its 12 hard answerables are all
   rarest-keyword findable) or re-author them under the verified regime; otherwise any
   verified+wmr aggregate inherits free passes. *Closes*: label inflation measurable at 12/12
   (Axis 1.2).
7. **3–5 adversarial/security-theme items** — the corpus has ~51 candidate papers; answerable
   attack/adversary-effect questions plus one or two calibrated absences. *Closes*: a whole
   uncovered theme.
8. **2–4 provenance/version-drift items** — publication/update dates, arXiv-version behavior,
   who-authored-what; the temporal dimension currently tests content milestones only. *Closes*:
   metadata dimension at 0.
9. **Optional: 2–4 human-factors items** beyond the fatigue/teleop trio (~161 candidate-title
   papers). *Closes*: theme thinness, lower priority than 1–8.

Explicitly *not* recommended by this assessment: more single-passage factual lookups (already
18 items, 62% grep-reachable), more Waymo-milestone numerics (top-6 concentration), or more
gt_wmr-style rate-extraction items.

## What I could NOT assess, and why

- **Production-retriever behavior** — no embeddings model or MCP pipeline was run (offline,
  zero-network constraint; also out of scope). Every "reachable/unreachable" number above is a
  property of trivial baselines, i.e., bounds, not performance predictions.
- **Whether the near-misses actually fool the system** — that requires running the generator on
  the absent set; I assessed affordance (does plausible bait exist), not realized failure.
- **Correctness of any item** — established by prior tickets; re-verification was out of scope.
- **Difficulty labels on absent items** — untestable without execution; I report that they exist
  and are unverifiable, not that they are wrong.
- **waymo_gt_a/gt_b independently** — the verified union supersedes them; their only independent
  signal is provenance metadata.
- **Figure-image content** — captions/markdown only; the four vision-derived items were classified
  from their text fields.

## Adjudication notes

No objection to any ticket decision. One hypothesis correction, stated plainly because it reverses
an expectation in the brief: the absent set is *not* mostly free wins — 13/14 unique absences carry
genuine adjacent bait, several of them excellent (Tesla self-report, WOMD×collision, UL-4600
collision). The scarcity is narrower than "FP coverage": it is Tier-A-mode penetration specifically
(1 unique fact), plus the FN-side gaps (tables, arithmetic, lexical-anchor-free reachability) and
the redundancy cleanups listed above.
