# Waymo eval: dimension-taxonomy fix + the vision arm's first-ever retrieval measurement

Two independent jobs against the Waymo AV-safety ground-truth set. Job 1 fixes a data defect
that was silently corrupting any per-dimension breakdown of `fixtures/eval/waymo_gt_verified.json`.
Job 2 runs the one evaluation arm that had never been run: whether retrieval can even find the
right page for a question whose answer was never extracted as text in the first place.

Branch: `EVAL-VISION-ARM`. Corpus: `waymo/data/papers.db` (read-only), collection
`waymo_av_safety`.

## Job 1 — dimension taxonomy: nine labels, six real dimensions

`waymo_gt_verified.json` is the cross-verified union of two independently-authored ground-truth
sets, GT-A (44 items, `waymo_gt_a.json`) and GT-B (40 items, `waymo_gt_b.json`). The two authors
used different wording for three of the six evaluation dimensions:

| GT-A form (short) | GT-B form (noun) | Merged count |
|---|---|---|
| `numeric/quantitative` (14) | `numeric/quantitative claims` (10) | **24** |
| `methodological` (12) | `methodological questions` (7) | **19** |
| `temporal/versioned` (3) | `temporal/versioned claims` (4) | **7** |
| `single-passage factual lookup` (18, one spelling only) | | 18 |
| `negation and scope` (10, one spelling only) | | 10 |
| `multi-paper synthesis` (6, one spelling only) | | 6 |

Any `Counter(item["dimension"] for item in ground_truth)` — exactly the kind of ad hoc grouping a
report would do — silently produced nine buckets instead of six, understating three real
dimensions by roughly half each.

**Normalization decision:** kept GT-A's short form for all three split pairs (`numeric/quantitative`,
`methodological`, `temporal/versioned`), dropping GT-B's noun forms (`... claims`, `... questions`).
Reason: the short form was *already* the unmodified spelling for the other three dimensions
(`single-passage factual lookup`, `negation and scope`, `multi-paper synthesis` — GT-B used those
verbatim, no variant existed), so picking it everywhere gives one consistent naming convention
instead of a mix, rather than introducing a new style neither author used for those three.

Applied to all three named fixtures (`waymo_gt_verified.json`, `waymo_gt_a.json`,
`waymo_gt_b.json`). `waymo_gt_a.json` needed **zero changes** — it never used the noun-form
spelling for any item, only `waymo_gt_verified.json` and `waymo_gt_b.json` (git diff confirms:
`waymo_gt_a.json` has no diff on this branch).

### Before/after proof, restricted to the changed key

A verification script (loaded via `git show HEAD~1:<path>` vs. the working tree, per-item,
per-field) confirms: **42 `dimension` value changes** (21 items × 2 files that needed it:
`waymo_gt_verified.json` and `waymo_gt_b.json`), and **zero changes to any other field or to item
order** across all 168 items checked (84 in `waymo_gt_verified.json` + 44 in `waymo_gt_a.json` +
40 in `waymo_gt_b.json`). The 21 changed items and their before → after:

```
Q-WAYB-014..022, Q-WAYB-040   'numeric/quantitative claims'  -> 'numeric/quantitative'   (10 items)
Q-WAYB-023..029               'methodological questions'     -> 'methodological'          (7 items)
Q-WAYB-036, Q-WAYB-037,
Q-WAYB-039                    'temporal/versioned claims'    -> 'temporal/versioned'       (3 items)
Q-WAYB-038                    'temporal/versioned claims'    -> 'temporal/versioned'       (1 item)
```
(Each of the 21 lines above appears once in `waymo_gt_b.json` and once in `waymo_gt_verified.json`
— 42 total value changes.) Post-normalization counts, read directly from the file: `numeric/
quantitative` 24, `methodological` 19, `single-passage factual lookup` 18, `negation and scope`
10, `temporal/versioned` 7, `multi-paper synthesis` 6 — 84 total. Matches the ticket's predicted
merge exactly.

Also updated (not part of the byte-identical-field guarantee, since these are metadata/prose, not
ground-truth item fields, and they document the very thing being changed): `waymo_gt_b.json`'s
`_metadata.dimensions` / `_metadata.dimension_counts`, and `waymo_gt_verified.json`'s
`_metadata.dimension_labels_note` (previously said labels were deliberately preserved verbatim —
now says they were normalized, and why).

Added `test_dimension_vocabulary_is_closed` to both `fixtures/eval/test_waymo_gt_b_invariants.py`
and `fixtures/eval/test_waymo_gt_verified_invariants.py`, following the existing suites' pattern:
narrowed each `VALID_DIMENSIONS` set from the 9-label union down to the 6 canonical labels, and
added an explicit `RETIRED_DIMENSION_VARIANTS` check so a future author reintroducing one of the
three retired spellings fails loudly rather than silently passing under a "be safe" superset.

### `question_type`: null on 40 of 84 items — backfilled 21, left 19 honestly null

GT-B never populated `question_type` at all (the key is absent, not merely `null`, in
`waymo_gt_b.json` itself) — a wholesale per-source gap, not a per-item omission. `build_report`
coerces the missing value to `"Unlabeled"`, so its type breakdown covered 44/84 items before this
fix.

**Method:** read every null item's own `question_text` and matched it against the classification
pattern already established by GT-A's 44 labeled items (`Result-Comprehension` = asks about a
reported number/finding; `Method-Comprehension` = asks what method/procedure/criterion the authors
used; `Assumption-Comprehension` / `Contribution-Comprehension` = narrower categories with too few
labeled examples to pattern-match reliably). Two dimensions turned out to have a **100%-consistent**
existing pattern (`numeric/quantitative`: 14/14 labeled items are `Result-Comprehension`;
`temporal/versioned`: 3/3 are `Result-Comprehension`), and the WAYB items in those dimensions ask
the same shape of question ("how many/what rate/how much"). `methodological` was 11/12
`Method-Comprehension` with one demonstrated exception (`Q-GTA-023`, phrased as "why can't X" —
a reasoning-about-limitation question, not "what method did they use"); all 7 WAYB methodological
items are phrased as "what method/procedure/criterion/axes did the authors use," matching the
majority pattern's shape and not the one exception's.

Backfilled 21 items:

- **10** `numeric/quantitative` items (`Q-WAYB-014..022`, `Q-WAYB-040`) → `Result-Comprehension`
- **3** `temporal/versioned` items (`Q-WAYB-036`, `Q-WAYB-037`, `Q-WAYB-039`) → `Result-Comprehension`
  (comparing a reported figure across time)
- **1** `temporal/versioned` item (`Q-WAYB-038`) → `Method-Comprehension` — its own text says
  "describe its own **methodological scope**," not a figure; this deliberately breaks from the
  naive same-dimension correlation because the item's actual content doesn't match it
- **7** `methodological` items (`Q-WAYB-023..029`) → `Method-Comprehension`

Left the other **19 items explicitly `null`** (added the key with an explicit `null` rather than
leaving it absent, so the gap is visible in the data, not silently missing) because the labeled
reference data itself proves dimension does not reliably predict `question_type` there:

- **`negation and scope`** (6 items): the 4 already-labeled items in this exact dimension split
  3 `Result-Comprehension` / 1 `Assumption-Comprehension` (`Q-GTA-041`, "what fraction of
  scenarios involve a collision" — phrased identically to several `Result-Comprehension` items
  elsewhere, yet labeled `Assumption-Comprehension`). No content-level feature distinguishes the
  exception from the majority — the classification hinges on authorial judgment not recoverable
  from the question text.
- **`multi-paper synthesis`** (4 items): only 2 labeled examples exist, split 1 `Result-
  Comprehension` / 1 `Method-Comprehension` — a 50/50 split carries no signal at all.
- **`single-passage factual lookup`** (9 items): the most mixed category — 9 labeled examples
  span 4 different `question_type`s (`Result` 4, `Method` 3, `Contribution` 1, `Assumption` 1),
  no majority.

A wrong label would be worse than an honest gap; these 19 stay null.

### Verification

```
fixtures/eval/ pytest: 17 passed (includes the live-DB cross-check tier against papers.db)
ci.run_enforcement --local main: PASS
```

Committed as `d35b0ae` before starting Job 2.

## Job 2 — the vision arm's first retrieval measurement

Vision was used to *construct* 4 ground-truth items (`vision_derived: true`): `Q-WAYB-027`,
`Q-GTA-042`, `Q-GTA-043`, `Q-GTA-044`. Their answers are, by construction, not present in this
corpus's extracted block/chunk text — only readable from the rendered PDF page. No prior run had
ever measured whether retrieval can even surface the right material for these questions.
**n=4 — this is a very small arm; every rate below is a direction, not a confident estimate.**

One caveat carried over from the fixture's own metadata: `Q-GTA-044` is tagged
`vision_scope: corpus-extraction-gap` — its numbers *are* selectable PDF text, just dropped by
this pipeline's block extractor, not truly image-only like the other three
(`vision_scope: document-image-only` for `Q-GTA-042`/`Q-GTA-043`; `Q-WAYB-027` carries no
`vision_scope` tag but is, by content, the same document-image-only kind — Figure 19's grid
mapping is not restated anywhere in the paper's prose). The fixture's own metadata says
consumers who want "vision capability specifically" should filter it out of the headline
denominator. Reported below with all 4 (as the ticket names them) and flagged inline wherever
`Q-GTA-044`'s different nature matters.

### Command run

```
cd /home/omar/ai-projects/research-system-rag && \
/home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.retrieval_eval \
  --ground-truth fixtures/eval/waymo_gt_verified.json \
  --config /home/omar/ai-projects/research-system-rag/waymo/data/config.yaml \
  --collection waymo_av_safety \
  --report-path docs/eval-reports/data/2026-08-23-vision-arm/waymo_gt_verified_full.json
```

**Collection spot-check** (the ticket's stated trap: `build_mcp_server`'s default collection is a
*different*, causal-inference corpus): the config file at `waymo/data/config.yaml` already pins
`collection: waymo_av_safety` and `db_path` to the absolute Waymo DB path, and `--collection
waymo_av_safety` was passed explicitly regardless. Verified post hoc — every one of the 4 vision
items' `source_paper_id`s resolves in `papers.db` under its correct title (e.g. `2506.08228` →
"Scaling Laws of Motion Forecasting and Planning"), and every paper id returned in the top-10 for
these 4 questions (`2210.15449`, `2303.04116`, `2304.03834`, `2210.16144`, `2312.04316`,
`2312.12675`, `2312.13228`, plus several `local:` drop-in ids) resolves to an AV-safety/motion-
forecasting title (e.g. "Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1
Million Miles"), not a causal-inference one. Correct corpus confirmed.

Full run: 82 questions scored (84 minus 2 duplicate-of items excluded by default), 0 errors.
Report: `docs/eval-reports/data/2026-08-23-vision-arm/waymo_gt_verified_full.json`.

### 1. Paper-level recall: vision arm vs. the answerable arm

| Arm | Recall@10 | n |
|---|---|---|
| **Vision arm** (all 4: `Q-WAYB-027`, `Q-GTA-042`, `Q-GTA-043`, `Q-GTA-044`) | **4/4 = 1.000** | 4 |
| Vision arm, excluding `Q-GTA-044` (extraction-gap, not vision-only) | 3/3 = 1.000 | 3 |
| Text-answerable arm, **excluding the 4 vision items** (same run, same k) | 57/64 = 0.891 | 64 |
| Text-answerable arm, as the runner's own built-in partition (includes the 4 vision items) | 61/68 = 0.897 | 68 |

**n=4 (or n=3): a single miss would have swung the vision-arm rate from 1.00 to 0.75/0.67. Do not
read "1.000" as "retrieval is fine for vision questions" — read it as "retrieval found the right
paper in all 4 cases measured, worth confirming at n=20+."**

Every one of the 4 vision questions returned its gold paper somewhere in the top 10 (ranks 1, 1,
1, 2 — see the report JSON's `paper_level.rank` per question). That is *not* obviously guaranteed:
these questions' answer text is absent from the indexed chunks by construction, so a hit here
means the question's own *surrounding textual context* (what the question is about, not what its
answer is) was enough to identify the right paper via semantic + sparse retrieval. At this small
n, paper-level recall for the vision arm is at least as good as — not worse than — the
text-answerable reference arm.

Passage-level (exact `gold_block_id` match) was 0/4 for the vision arm — expected and not a
useful signal here: `gold_block_id` on a vision item anchors to a *nearby* prose block for
navigation, not the block containing the visual content itself (block text there is often mangled
or absent — see `Q-GTA-042`'s note on its own block's garbled table extraction). This is why
measurement 2 below (page proximity) is the metric that actually answers the ticket's question,
not passage-level recall.

### 2. Page/block proximity: when the right paper comes back, is a returned chunk near the answer's page?

For each vision item, every retrieved chunk (of the top-10) belonging to the gold paper was
resolved to its page via `blocks.page` (the `anchor.block_id`/`gold_block_id` convention this
corpus uses throughout), then compared to the gold `page` field carried on the ground-truth item
itself (independently cross-checked against `blocks.page` for `gold_block_id` in the fixture's own
invariants test — they agree).

| Question | Gold page | Best (min) \|Δpage\| among returned chunks | Rank of that chunk | Chunks returned from gold paper (of 10) |
|---|---|---|---|---|
| `Q-WAYB-027` | 35 | **1** | 1 | 5 |
| `Q-GTA-042` | 13 | **1** | 7 | 7 |
| `Q-GTA-043` | 9 | **0** (exact) | 3 | 10 |
| `Q-GTA-044` | 7 | **0** (exact) | 2 | 3 |

- **All 4/4 vision items** had at least one returned chunk within **1 page** of the gold page —
  the closest chunk landed either exactly on the gold page (`Q-GTA-043`, `Q-GTA-044`: 2/4) or one
  page off (`Q-WAYB-027`, `Q-GTA-042`: 2/4).
- Full |Δpage| distribution across all 25 same-paper chunks returned in the top-10 across the 4
  questions: `[0, 0, 1, 1, 2, 2, 3, 3, 6, 7, 7, 7, 8, 8, 9, 9, 10, 11, 11, 13, 18, 20, 24, 32, 35]`
  — bimodal: a handful of chunks land tight (0-3 pages), the rest scatter across the rest of the
  paper (the retriever pulls in other relevant-but-distant sections of the same long paper, as
  expected from paper-level semantic retrieval that isn't page-aware).
- `Q-WAYB-027`'s best hit is its own *rank-1* result — the single highest-scoring retrieved chunk
  in the entire top-10 is one page before the gold page.

**n=4: four data points is not enough to claim a rate ("X% of vision questions land within 1
page") — but the *direction* is unambiguous and consistent: every single item measured had a
near-page or exact-page hit, none missed by a wide margin only.

### 3. What this says about a VLM-augmented pipeline

Per the ticket's framing: if retrieval reliably lands on the right page, a VLM re-reading that
page could answer these questions; if it doesn't, page-level retrieval — not VLM capability — is
the blocker.

**On these 4 items, page-level retrieval is not the blocker.** Every question's gold paper was
recovered (4/4), and every question had a returned chunk within 1 page of the answer's actual
location (4/4, 2 of them exact). A pipeline that (a) ran today's retrieval, (b) took the top-k
*pages* of returned chunks belonging to the top-ranked paper (not just the chunks' text), and (c)
handed those page images to a VLM would have had the correct page in front of the VLM for all 4
measured items — `Q-WAYB-027` on the very first retrieved chunk. The open question this small
sample cannot answer is whether that holds at scale (n=4 says "worth building," not "will work
reliably") — and whether "top-k pages of the top-ranked paper" is the right selection rule
generally, since here it worked because the gold paper was always rank-1 or rank-2 at the paper
level.

### Do the `figures`/`tables` backfill rows let retrieval target a figure directly? (finding only — not built)

The corpus now has `figures` (24,708 rows) and `tables` (8,266 rows) populated with `page` and
`bbox_json` per row (confirmed by direct query), plus a `caption` column (populated for some rows,
empty string for others — e.g. `Q-GTA-042`'s Table 5 on page 13 of `2508.19425` has an empty
caption) and a `vlm_description` column that exists in the schema but is **entirely unpopulated:
0/24,708 rows**. Every figure/table implicated in the 4 vision items above does exist in these
tables at (or one page from) the correct gold page — e.g. `2208.12833`'s Figure 19 is `figure_id`
5515 at page 35, exactly the vision item's gold page.

So: these rows already give **location** metadata that page-proximity retrieval (measurement 2)
converges on independently — they would let a downstream step *jump straight to* the right
figure/table once the right page is known, without needing text-block proximity as a proxy. They
do **not** yet give **content** that could be a retrieval *target* in the sense of semantic
similarity search: with `vlm_description` empty, there is no indexed text describing what any
figure/table actually shows, so a query embedding can't match against figure/table content
directly today — only against surrounding prose (which, for these 4 items, doesn't state the
visual fact) or a caption (present for some, blank for others). Populating and indexing
`vlm_description` is the natural next step if figure-level (not just page-level) retrieval
becomes a goal — a roadmap item, not built here per the ticket.
