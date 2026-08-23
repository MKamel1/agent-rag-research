# Waymo ground-truth cross-verification (GT-X)

*2026-08-22 · branch `GT-X-cross-verification` · verifier: an independent session that authored
neither set*

Two evaluation sets were built independently from the Waymo AV-safety corpus by two different
models, neither seeing the other's work:

| set | author | fixture | branch | items |
|---|---|---|---|---|
| GT-A | oxalpha | `fixtures/eval/waymo_gt_a.json` | `GT-A-oxalpha-waymo-groundtruth` (`050c011`, `de28cbd`) | 33 |
| GT-B | claude | `fixtures/eval/waymo_gt_b.json` (+ its invariants suite) | `GT-B-claude-waymo-groundtruth` (`d78102e`, `9d28e76`) | 40 |

Both were built against the same frozen corpus DB (`waymo/data/papers.db`, mtime 2026-08-19,
1,738 papers / 46,155 chunks / 235,918 blocks — larger than the 221-paper snapshot in
`docs/PROJECT-STATUS.md` §1; both fixtures' own logs reference the current size).

**Headline: every item survived verification — 73/73 (100%).** The disagreements between the
sets turned out to live in *process* (search-log bookkeeping, one incomplete search log, one
near-miss absence that needed adjudication against the other set) rather than in any item being
wrong. Details below, caveats included; the survival rate should be read together with §5 and §7,
not instead of them.

---

## 1. What was checked, per item

1. **Excerpt fidelity (mechanical):** paper exists in `papers`; recorded title equals the
   corpus's own title; `gold_chunk_id` resolves and belongs to the cited paper; the chunk's
   `anchor_json.block_id` equals `gold_block_id`; each `passage_excerpt` is a whitespace-
   normalized substring of the cited chunk's stored `text`. Applied to primaries **and** to
   every `supporting_passages` entry (GT-B) / `supporting_sources` entry (GT-A).
2. **Section-path agreement:** recorded `section_path` equals the cited chunk's stored
   `section_path` (0 mismatches across 73 path-bearing claims).
3. **Absence claims (GT-B only; GT-A defines none):** every search re-run independently over
   full `chunks.text`/`blocks.text`, plus adversarial probes the original log did not try.
4. **Answerability:** every answerable item read individually — does the cited material answer
   the question as asked, or merely mention it?
5. **Numeric grounding audit:** every numeral in every `answer_text` checked for presence in
   (or derivability from) the cited paper's text — catches hallucinated specifics.
6. **Vision items:** only what is checkable without re-rendering a page — paper/title/block-id/
   page agreement. The visual claim itself is stated as unverified.

## 2. GT-A results — 33/33 verified

- Mechanical fidelity: **152/152 checks pass** (33 primaries + 5 supporting sources + titles).
- Section paths: 38/38 match the DB.
- Answerability: all 33 read and judged answerable as asked. Two items carry a *citation-scope*
  nit (answer detail grounded in a sibling chunk of the same paper, not the cited one):
  - **Q-GTA-024** — "5 s of future trajectory" lives at `2510.26125:c2`, cited chunk is `c1`.
  - **Q-GTA-031** — the "~50× larger than an optimal LLM" comparison lives at `2506.08228:c4`
    and `:c14`, cited chunk is `c1`.
  Both details are real and correctly quoted; only the citation points one chunk short. Kept,
  with a note in the merged fixture's `verification.notes`.

**Process findings on GT-A (not item failures):**

- **The branch ships no invariants suite.** The GT-X brief described "waymo_gt_a.json (+ its
  invariants suite)" but `git ls-tree` shows both GT-A commits touch only the JSON. GT-B's
  equivalent suite exists and passes; GT-A's has nothing guarding it. This merge's suite now
  covers the surviving GT-A items mechanically.
- `_metadata.description` advertises "plus verified-absence probes", and `structure` says the
  same, but **the set contains zero absent items** (all 33 are `tests: "answerable"`), and
  `total_items` is 33 where the description says "40+ items". The metadata overstates what the
  data contains.

## 3. GT-B results — 40/40 verified

- Mechanical fidelity: **143/143 checks pass** (32 answerable incl. all supporting passages;
  the vision item's paper/title/block/page resolve; the block's stored page equals the cited
  page).
- Its own invariants suite passes as shipped (structural + live-DB tiers).
- Answerability: all 32 answerable items read and judged answerable as asked, including the
  arithmetic synthesis item Q-WAYB-010 (PV-RCNN++ 69.91 vehicle L2 mAPH confirmed inside the
  run-together table cell `"68.9869.91"` in `2102.00463:c13`).
- Numeric audit: clean (Q-WAYB-027's numerals come from a rendered figure and are covered by the
  vision caveat below).

### Absence re-verification — 8/8 hold, with three logs flagged

Every absence was re-established by my own searches, including probes the original log did not
run. Verdicts:

| item | claim | verdict | evidence / caveat |
|---|---|---|---|
| Q-WAYB-009 | no Waymo LiDAR wavelength anywhere | **holds** | 35 `wavelength` hits reviewed; adversarial `1550`/`1550 nm`/`lidar wavelength` probes find only camera-resolution tables and unrelated FMCW physics. **Log count drifts:** recorded "10 hits", actual 35 chunks / 20 papers. |
| Q-WAYB-021 | no Waymo-attributed fatality counts by victim category | **holds** | 430 `fatalit*` chunk hits corpus-wide; the 29 whose text co-occurs with `waymo` reviewed individually (benchmarks, severity-tier discussion, mission statements); `death/died/killed/deaths` probes add nothing. |
| Q-WAYB-022 | no Gen-5-specific disengagement rate | **holds** | No hit gives any operator's hardware-generation-specific rate. **Log count drifts:** recorded "10 hits", actual 168 chunks / 75 papers. |
| Q-WAYB-028 | RAVE checklist reports no power analysis validating itself | **holds** | 0 `power analysis` hits in-paper; the 2 `statistical power` hits (`c20`, `c22`) are advice to other researchers, matching the original log exactly. |
| Q-WAYB-029 | no blinding procedure in the fatigue-framework paper | **holds** | 0 `blind*` hits under either id of the paper (`2208.12833` and its duplicate row `local:94bdd3d09df1`). |
| Q-WAYB-034 | no dedicated Zoox safety-performance study | **holds** | 0 title hits; 11 chunk mentions across 10 papers (count reproduces exactly), all passing mentions; nearest misses are a historical disengagement-rate remark (`1912.03618:c11`) and a Zoox-*authored* validation-methodology paper (`2411.03328`) that reports no Zoox crash-rate figures. |
| Q-WAYB-035 | no Cruise reduction computed against the Blincoe-adjusted benchmark | **holds — near miss** | See §6.2. |
| Q-WAYB-039 | no rider-only crash-rate study at a 100M-mile milestone | **holds — log incomplete** | Series caps at 56.7M miles. But the recorded search log misses the corpus's strongest 100M-mile hit, `2507.17943:c2` ("quickly reached 100 million miles in July 2025") — which GT-A uses for Q-GTA-015. Adjudicated in §6.1; the absence still stands under its precise wording. |

**Pattern worth naming:** the qualitative absence conclusions are all sound, but several recorded
hit counts do not reproduce under plain SQLite `LIKE` on the frozen DB (009: 10→35; 022: 10→168;
Zoox's count is the one that reproduces exactly). Whatever produced those logs was not plain
reproducible queries pasted verbatim. For future absence items: record query + count as program
output, or drop the counts and keep only the method description.

## 4. Vision item (Q-WAYB-027)

Machine-checkable facts verified: paper resolves, title matches, `gold_block_id` resolves in
`blocks`, and the block's stored `page` equals the cited page 35. **The visual claim itself —
which pillar/lifecycle-phase grid cell Figure 19 assigns to practice #9 "Human drowsiness
rating" — could not be re-rendered or re-read by this verification and remains unverified**,
carried forward on the authoring model's reading alone. It survives into the merged fixture
flagged accordingly (its `verification.notes` say so verbatim), per the brief's instruction not
to pretend JSON-side checking covers it.

## 5. Set-vs-set comparison

### 5.1 Overlap: a narrow shared core, different exploration beyond it

- Papers cited: GT-A 20, GT-B 21, **shared 8** — the Waymo self-study cluster (`2312.12675`,
  `local:6b9ccd0431f6`, `local:f6f1461f2c9a`, `2011.00038`), the dataset cluster (`2104.10133`,
  `2210.07372`, `2508.19425`), and WOSAC (`2305.12032`). Each set also explored a distinct
  region the other didn't touch: GT-A went deep into perception/forecasting/scaling model papers
  (12 papers exclusive); GT-B into methodology/frameworks/SOTIF/teleoperation (13 exclusive).
- Chunks cited: GT-A 35, GT-B 30, **shared 6** — almost all in the self-study cluster.
- **Near-verbatim duplicate questions: zero** (best cross-set token-Jaccard < 0.35 even at the
  tightest fact level). The two authors converged on the same corpus facts from independent
  angles — e.g. both cite `local:6b9ccd0431f6:c37` for the 7.1M-vs-56.7M reduction tightening,
  but GT-A asks about the police-reported headline estimate and its uncertainty (Q-GTA-005)
  while GT-B asks for both outcome categories' percentages and CIs (Q-WAYB-036).

Reading: the corpus has a **narrow, strongly-convergent answerable core** (the Waymo crash-rate
self-studies plus the open-dataset family) that any competent explorer finds, ringed by a wide
diverse frontier where independent exploration diverges. Both halves of that finding are useful
for retrieval eval: the core gives high-signal items likely to be re-derived by anyone; the
frontier measures breadth.

### 5.2 Contradictions adjudicated

No item-level contradiction survived scrutiny — the two apparent ones resolved as follows:

1. **Q-WAYB-039 (absent) vs Q-GTA-015 (answerable)** — the closest thing to a real
   disagreement in the exercise. GT-A's timeline item cites "quickly reached 100 million miles
   in July 2025" from `2507.17943:c2`; GT-B declares "no 100-million-mile report" absent.
   Ruling: **both correct under their own wording.** GT-A asserts a *mileage-milestone mention*
   (one paper citing Waymo's announcement); GT-B's absence is about a *rider-only crash-rate
   study at 100M miles reporting reduction figures*, which indeed does not exist here. GT-B's
   search log should have surfaced the `2507.17943` hit and explained why it doesn't defeat the
   absence — that explanation is now in the merged fixture's notes.
2. **Q-WAYB-035 near-miss** — the corpus *does* contain a Cruise-specific reduction figure
   (Zhang 2023 via `2312.12675:c11`: −65% any-property-damage-or-injury over Cruise's first 1M
   RO miles), so a sloppier version of this question would have been falsifiable. It does **not**
   defeat the absence as asked, because Zhang computed it against the Flannagan et al. (2023)
   ride-hailing NDS benchmark, whereas the question names the Blincoe-adjusted police-reported
   benchmark specifically — a benchmark nobody in the corpus applies to Cruise. The question's
   precision is what keeps it valid; noted in the fixture because a retrieval system returning
   `2312.12675:c11` would look superficially responsive to it.

### 5.3 Coverage gaps (both sets)

- **Absence testing: entirely missing from GT-A** (0/33 vs GT-B's 8/40). An eval set with no
  known-absent items cannot measure false-positive retrieval behavior at all.
- **Multi-paper synthesis is thin in both** (GT-A 2, GT-B 4 of 73 total).
- **Vision coverage: 1 item in 73**, and its central claim is unverifiable post hoc by design.
  Either invest in a render-and-check harness or stop counting vision_derived items as verified.
- **Dimension vocabularies diverge** for 3 of 6 dimensions (`numeric/quantitative` vs
  `numeric/quantitative claims`, etc.). Preserved verbatim in the merge (normalizing would
  silently rewrite author intent); consumers needing one bucketing can strip the "
  claims"/"questions"/" s" suffixes — but the right fix is agreeing one vocabulary upstream.

## 6. Merged deliverable

`fixtures/eval/waymo_gt_verified.json` — 73 items (GT-A 33, GT-B 40), each carrying:

- its original fields verbatim (including original `question_id`);
- a `verification` block: `source_set` (GT-A/GT-B), `source_fixture`, `verified_at`, the list of
  checks that passed, and — where verification found something non-routine — explicit `notes`
  (both citation-scope nits, all eight absence re-verifications with their evidence and caveats,
  and the vision item's unverified-claim statement);
- metadata recording per-set survival, source branches/commits, method, and the known caveats.

Its suite, `fixtures/eval/test_waymo_gt_verified_invariants.py`, follows the directory's
two-tier pattern: structural invariants (counts per source set, cross-set id uniqueness, shape
rules per item type, mandatory verification provenance, absence-evidence presence, vision-note
presence) plus a live-DB tier re-resolving every excerpt/id/section-path/page claim (auto-skips
without the gitignored DB, like its siblings). One deliberate relaxation vs the sibling suites:
`section_path` may be empty when the cited chunk itself is front-matter (`section_path==""`),
three GT-A items do exactly that, and the DB tier asserts equality with the stored value —
stronger than demanding non-empty.

## 7. Honest bottom line

**Survival rate: 73/73 (100%)** — GT-A 33/33, GT-B 40/40. Nothing mechanical failed; no excerpt
was unfaithful; no absence collapsed; no answer was unanswerable-as-asked; no hallucinated
numerals. That is a strong result for two independently-built sets and it says the builder
processes (programmatic excerpt extraction for GT-A, careful manual work for GT-B) produce
trustworthy grounding.

It should not be read as "nothing was found". The verification caught, and the fixture now
records: two citation-scope nits, three unreliable absence-log hit counts, one incomplete
absence search log that missed the single most relevant counterexample-candidate in the corpus,
one near-miss absence kept alive only by the question's own precision, one vision item whose
central claim no downstream consumer can verify from the repo, a source set whose metadata
misdescribes its own contents, and a source branch shipping without the suite its sibling has.
The disagreements-between-sets signal the brief expected mostly wasn't item-level disagreement —
it was disagreement about *how the work was documented*, which is exactly what a third-party
check is for.

## 8. Scope discipline — found but deliberately not fixed

Per the no-scope-expansion rule, these were observed and reported only:

- The GT-A branch itself still lacks an invariants suite (fixing their branch is not this
  ticket; the merged fixture is now guarded here).
- GT-A's `_metadata` inaccuracies (described above) are preserved as-authored in the source
  fixture; the merged fixture's own metadata is accurate.
- The fatigue-framework paper exists under two paper_ids (`2208.12833` arXiv-native and
  `local:94bdd3d09df1`), i.e. an apparent duplicate ingest row pair in the corpus. Not touched;
  flagging for the corpus owners.
- `docs/PROJECT-STATUS.md` §1's Waymo snapshot (221 papers) is far behind the live DB
  (1,738 papers) and its `waymo_authored_ids.txt` reference count (138) is behind the file on
  `main` (153). Both stale-doc issues belong to the parallel Waymo workstream that owns that
  doc.
