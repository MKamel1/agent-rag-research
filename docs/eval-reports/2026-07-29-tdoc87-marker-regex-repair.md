# T-DOC87 — chapter-marker regex repair (Decision 4, option B)

*2026-07-29/30. Implements the operator's chosen option (B — repair the marker regex) from
`docs/DECISIONS-PENDING-operator.md` Decision 4.*

**Two separate questions, two separate verdicts — do not conflate them:**

1. **Is the regex fix itself correct?** Yes, unconditionally. The bare `^\d+\.\s+\S` alternative
   matched **643 blocks** across the 5-book corpus; every sampled match is body prose (numbered
   list items — `"1. Scan the QR code or visit the link below"`, `"1. First, let's import the
   necessary libraries:"`), never a real chapter boundary. Promoting those to routing-visible
   "chapters" is a defect independent of what retrieval does with the result. **This ships.**
2. **Is it safe to re-ingest the affected books' chapters into production under the new
   boundaries?** This is what phase 2 measures, and the answer is **no, not for both books.**
   Discovery in Python's routing holds within noise. **Econ/Social/Health's routing collapses well
   past the noise floor in both configurations** — a real, twice-independent-book regression this
   programme has now measured (Discovery-shaped in Experiment 1, Econ/Social/Health-shaped here).
   **Do not re-ingest production with these chapter boundaries as a routing improvement — it isn't
   one, and for one of the two books it's a serious regression.**

Nothing here touches the production corpus or the production `papers` collection; this PR's actual
production-facing content is the code fix, its tests, and a new fixture file, all reviewed
separately below.

---

## Reproduce

```
RAG_CONFIG=/home/omar/ai-projects/research-system-rag-data/config.yaml \
    python -m pytest rag/test_book_summarizer.py -q
```

The before/after projection numbers below were produced by loading `Block`/`ParsedDoc` rows
straight from `blocks`/read-only `papers.db` (`sqlite3.connect("file:...?mode=ro", uri=True)`) and
calling the real `rag.book_summarizer._split_chapters` — once against `git show HEAD:...` (the
unrepaired original) and once against the repaired file on disk. No corpus write, no GPU, no
summarizer/embedder call. The throwaway script used to gather them was deleted after use (not a
deliverable); the exact loading/calling logic is reproduced verbatim in this report's tables.

---

## The discriminator

`rag/book_summarizer.py`'s `_CHAPTER_MARKER` regex had two alternatives: a keyword one
(`chapter|part|appendix N`) and a bare one (`^\d+\.\s+\S`, i.e. "N. Title"). Measured against the
live 5-book corpus, the bare alternative had **0 true positives and 44 false positives** — every
single bare match across all 5 books was a numbered list item in body prose that MinerU's layout
model classified as a heading (`text_level >= 2` in `rag/parser.py`'s terms), not a real chapter
boundary.

**Discriminator chosen:** a bare "N. Title" heading is trusted as a chapter marker only when
*every* bare-numbered heading in the document — taken together in reading order, excluding
anything already matched by the keyword alternative — forms the exact sequence `1, 2, 3, ..., k`
with no gaps and no repeats. That is the numbering a book's own chapters actually have. A numbered
list restating steps in body prose resets to 1 for each separate list (measured, Econ/Social/
Health: `[1,2, 1,2,...,10, 1,2,...,10, 1,4, 1,2,3,4, ...]` — several independent short lists, never
one running count across the book) or starts mid-sequence (Discovery in Python's sole bare match
starts at 3, with nothing numbered 1 or 2 anywhere near it).

Position/block-type were considered and rejected as the discriminator: MinerU already collapses
"is this a heading" to a single flag (`text_level`) before `rag/book_summarizer.py` ever sees the
block, so a `Block`'s `type` (`"prose"` for every single match, real and bogus alike — verified)
carries no signal here. Only the numbering pattern across the whole document does.

**What it still gets wrong (stated up front, per instructions):**
1. A book whose *only* marker-worthy heading anywhere is a single, coincidentally 1..N sequential
   body-prose list (no other bare-number or keyword heading in the entire book) would still slip
   through this check alone. Not observed in this 5-book corpus — Econ/Social/Health has two
   separate 10-item sequential lists (classification-tree and regression-tree walkthroughs), which
   is exactly why the check catches it (their union isn't one 1..20 run). The existing word-share
   guard catches most single-list cases anyway, because the rest of the book then piles into one
   lopsided front-matter unit.
2. It does not, and was never going to, fix the *other* mechanism behind Discovery in Python's
   duplicate "Part 2"/"Part 3" labels — see below.

A second guard was added alongside the regex fix, in `_split_by_markers`: **reject the whole
marker split if any two matched titles are identical.** This is not a regex change; it is a
plausibility check of the same kind the function already had (min/max unit count, word-share) —
added because the bare-number fix alone does not eliminate Discovery in Python's duplicates (see
next section), and Decision 4B's actual goal is "duplicates eliminated," not "this one regex
alternative repaired."

---

## Root cause of Discovery in Python's duplicates was NOT the bare-number bug

Investigated directly against the corpus (`local:dfe850b3281a`, blocks 55–105): the book's own
**printed table of contents** (idx 63–101) is parsed as real body text, and MinerU classifies its
ToC entries "Part 1: Causality – an Introduction" / "Part 2: Causal Inference" / "Part 3: Causal
Discovery" as level-2+ headings — the same text, matched by the same (unchanged) keyword
alternative, that also appears later at the *real* part dividers (idx 1000, 3132). This produces
two matched groups per repeated part, several hundred blocks apart, with the earlier bogus (ToC)
occurrence swallowing most of the intervening real "Part 1" chapter content once its title-share
starts absorbing everything before the next keyword match.

This is a distinct defect from the bare-number bug, entirely inside the keyword alternative
(unchanged by this repair) and outside T-DOC87's stated scope ("repair the chapter-marker
regex"). It is why the bare-number-only fix (see "AFTER, bare-number fix only" row below) does
**not** clear Discovery in Python's duplicates on its own — the duplicate-title guard above was
needed on top of it, and that guard's side effect (discussed in "Verdict") is the reason this
change does not ship.

---

## Phase-1 projection: per-book, before vs after

Both guards (bare-number sequential check + duplicate-title rejection) applied. `dup` = titled
units sharing a title with another unit in the same book (0 = none duplicated).

| book | BEFORE units | BEFORE dup | AFTER units | AFTER dup | AFTER words min/median/max |
|---|---|---|---|---|---|
| Discovery in Python (`dfe850b3281a`) | 7 | 2 | **23** | **0** | 5002 / 5180 / 6113 |
| Econ/Social/Health (`54d6ca71dda9`) | 44 | 6 | **38** | **0** | 5013 / 6619 / 25824 |
| Tech Industry (`f0929288d4f3`) | 26 | 0 | 26 | 0 | 3942 / 5305 / 6346 (unchanged) |
| Elements (`f6c64e1e8c7d`) | 8 | 0 | 8 | 0 | 5254 / 10595 / 41324 (unchanged) |
| AB Testing (`14b7e283bdcd`) | 16 | 0 | 16 | 0 | 5023 / 5344 / 6747 (unchanged) |

("dup" count is the excess of titles over unique titles, e.g. two units both titled "Part 2:..."
contributes 1 — matches the report's own earlier "2 pairs = 4 of 6 duplicate-titled units" framing
for Discovery in Python and "6 pairs" for Econ/Social/Health's "12 of 44".)

**Interim check — bare-number fix alone, without the duplicate-title guard** (i.e. T-DOC87's
literal scope, nothing more): Discovery in Python still has 6 titled units, 2 of them duplicated
(unchanged from BEFORE — the bare-number bug wasn't the cause here); Econ/Social/Health drops
straight to 0 duplicates (its bogus units were 100% bare-number-driven, 0 keyword matches exist in
that book at all, confirmed: `_CHAPTER_KEYWORD_MARKER` matches 0 groups). This interim result is
what motivated adding the duplicate-title guard on top, to actually reach Decision 4B's stated
goal for both books.

**Unaffected books:** Tech Industry, Elements, and AB Testing are byte-identical before/after —
confirms the repair does not disturb the 3 books that were never broken (0 bare-number matches
in any of them; keyword matches unaffected by either new guard).

---

## Titles produced, qualitative check ("implausible units")

**Discovery in Python (after):** falls back entirely to Strategy B (size-merge) once the
duplicate-title guard rejects Strategy A. All 23 resulting titles are real subsection headings
from the book's own text — e.g. *"From associations to logic and imagination – the Ladder of
Causation"*, *"DAG your pardon? Directed acyclic graphs in the causal wonderland"*, *"Nodes,
Edges, and Statistical (In)dependence"*. Plausible, distinct, no duplicates. **But this is a
7 → 23 unit reshaping** — see Verdict.

**Econ/Social/Health (after):** 0 duplicates, but several titles are still not usable routing
labels — Strategy B's `_best_heading` picks the highest-scoring heading text merged into a unit,
and it has no way to know a candidate heading originated from a numbered list item rather than a
real section title. Examples pulled straight from the projection output:

- `"Therefore, we need to define what makes an estimator the "best" among others."` — a
  mid-sentence fragment, not a title.
- `"## Best lambda for Ridge regression: 0.2529632"` — a printed numeric result / markdown
  artifact, not a heading at all.
- `"4. Choose Optimal Split Point for Each Variable"`, `"2. Second Stage:"`,
  `"1. Recursive Forecasting:"` — numbered list items that leaked through Strategy B's
  independent title-scoring (real words, passes `_title_score`, but originated from the same
  MinerU heading-misclassification this ticket exists to fix — just surfacing through the
  fallback path's title selection instead of Strategy A's boundary detection).

These are not duplicates (each string is unique). **Follow-up candidate, not fixed here:**
`_best_heading`'s title-quality logic (Strategy B) has no way to tell a numbered-list-item heading
from a real one — that's a pre-existing Strategy-B defect, not something the marker-regex repair
touches or claims to fix, and recorded here as a candidate ticket rather than actioned in this PR.

**Second follow-up candidate, also not fixed here:** Discovery in Python's duplicate `Part 2`/
`Part 3` labels (before this repair) come from its own table of contents being mis-classified as
real chapter headings by the parser's layout model — a distinct defect from the bare-number bug,
inside the keyword marker alternative (unchanged by this repair). See "Root cause..." above for
the full trace (blocks 63–101 of `local:dfe850b3281a`).

---

## Mutation test

Reverted `rag/book_summarizer.py` to `git show HEAD` (pre-fix) with the new tests still in place:

1. **Full revert** (function names gone entirely): `pytest rag/test_book_summarizer.py` fails at
   **collection** (`ImportError: cannot import name '_bare_numbers_are_sequential'`) — the new
   tests cannot even load against unfixed code.
2. **Targeted mutation 1** — neutered `_bare_numbers_are_sequential` to always return `True`:
   `test_bare_number_markers_rejected_when_not_sequential_from_one` and
   `test_bare_number_markers_reject_real_bogus_examples` both fail with real assertion errors
   (`assert not True`), not collection errors.
3. **Targeted mutation 2** — removed the duplicate-title guard's `return None`, letting the
   duplicate split through: `test_marker_split_rejected_when_matched_titles_duplicate` fails with
   a real assertion error (`_split_by_markers(groups) is None` → got a non-`None` unit list back).
4. **Restored** the fix after each mutation (`diff -q` against the saved fixed copy confirmed
   byte-identical restoration): full suite green each time, 42/42 in `test_book_summarizer.py`.

All three mutations produced the expected red; restoration produced the expected green.

---

## Phase 2 — chapter routing measurement

**Narrowed gate (operator correction, 2026-07-30):** phase 1's original stop condition
("duplicate titles **or implausible units**") was mis-drawn — Econ/Social/Health's implausible
titles are a pre-existing Strategy-B defect this fix neither causes nor claims to repair, not a
real stop signal. Duplicates ARE eliminated (the goal phase 1 actually needed to hit), so phase 2
proceeded. **The only question phase 2 answers: does chapter routing hold?**

### Setup

- Pulled latest `origin/main` (already merge-base — no new commits since branching); confirmed 115
  questions in `fixtures/eval/eval_book_questions.json` and `_MAX_HITS_PER_PAPER_SCOPED` present in
  `rag/retriever.py` before starting.
- `app/exp_tdoc87_marker_repair.py` (new; sibling-tested, `app/test_exp_tdoc87_marker_repair.py`):
  re-summarized the 2 affected books under the already-repaired `_split_chapters` (no PDF, no
  outline, no `mock.patch` substitution needed — the repair IS the module's live default split, so
  `summarize_book()` runs completely unmodified). Reuses `app/exp1_outline_split.py`'s
  infrastructure directly (read-only corpus access, `VACUUM INTO` throwaway SQLite copy,
  `VectorIndex.clone_points_into`, `rederive_fixture`) rather than duplicating it — none of that
  code is outline-specific.
- **Throwaway collection: `tdoc87_marker_repair`**, cloned from production `papers`
  (372,741 points, sparse IDF on — confirmed via `QdrantClient.get_collection` before starting, not
  assumed) via `clone_points_into`. Final point count **372,751** — reconciles exactly:
  372,741 + 16 net-new Discovery-in-Python chapter vectors (23 new − 7 old, all old ids 0–6 are a
  subset of new ids 0–22, so 0 stale deletes) − 6 net-removed Econ/Social/Health vectors (38 new
  chapter ids are a subset of the old 44, so old ids 38–43 are deleted as stale). Confirmed via
  `QdrantClient.get_collection("tdoc87_marker_repair")` after the run, not assumed.
- **New fixture: `fixtures/eval/eval_book_questions_tdoc87.json`** (115 questions, same count as
  `main`). `rederive_fixture` re-derived `gold_chapter_title`/`gold_chapter_index` for all 46
  questions on the 2 affected books (0 unmapped — every `gold_block_id` landed inside some unit of
  the new split, confirmed programmatically before spending GPU time, and again by the script's own
  `TDoc87Error` guard, which never fired). The other 69 questions (3 untouched books) are
  byte-identical to `main`'s fixture. `gold_block_id`/`gold_chunk_id`/`source_paper_id` diffed
  field-by-field against the original for all 115 records: **0 changes** to any provenance field —
  only `gold_chapter_title`/`gold_chapter_index` moved, and only for the 44 (of 46) affected
  questions whose label text actually changed (2 questions' new unit happens to carry the same
  title string as its old unit — `QB-115`/`QB-034`, both landing on titles that leaked through
  Strategy B's fallback both before and after; confirmed their `gold_chapter_index` DID change, so
  this isn't a stale no-op, just a title-text coincidence).
- GPU lock (`Config.gpu_lock_path`) acquired/released cleanly at the start of each script run (0.00s
  wait — free at every acquisition in this run). One earlier attempt to run a "before" baseline
  concurrently with the still-running re-summarization job hit the lock's own 300s timeout
  (`TransientError`, expected/correct behavior, not a bug) — re-run sequentially after the
  background job finished, no further contention.
- Scoring: `scripts/tdoc87_routing_eval.py` (new, throwaway per its own docstring — mirrors
  `scripts/scratch_scoped_cap_eval.py`'s already-established `_chapter_rank`/`_recall_mrr` helpers,
  reused directly rather than reimplemented, plus a per-book breakdown that script didn't have).
  Real `Retriever.retrieve_papers()`, both `filters=None` (unscoped) and
  `filters=SearchFilters(doc_type="book")` (scoped, `_MAX_HITS_PER_PAPER_SCOPED` already on `main`).
  **Caught and fixed one real bug before trusting any number:** the first "after" run pointed
  `build_mcp_server` at the throwaway collection without `--db-path`/`--blob-dir`, so
  `retrieve_papers()` resolved `summary_id`s against **production's** `papers.db` — which has no
  row for Discovery in Python's new `ch7`–`ch22` (they only exist in the throwaway SQLite copy).
  This surfaced as `retrieve_papers(): dropping unresolvable hit ... orphaned/stale vector point`
  warnings and a spurious 0.000 for that book. Re-run with `--db-path`/`--blob-dir` pointed at the
  throwaway copy (`/tmp/tdoc87_scratch/{papers.db,blobs}`) produced **zero** such warnings — the
  numbers below are from that clean run.
- **"Before" baseline freshly measured, not assumed:** rather than relying only on the
  previously-published 40-question numbers (0.425 unscoped / 0.725 scoped — a different N, 8
  questions/book), the *same* 115-question fixture was also scored against production `papers`
  itself (read-only `retrieve()`/`retrieve_papers()` calls only — no write) to get a controlled,
  same-N, same-questions "before" for the head-to-head diff. The 40-question numbers are still
  reported alongside as an external consistency check.

### Results (k=10)

**Overall, 115 questions — before (production, unrepaired) vs. after (`tdoc87_marker_repair`,
repaired 2 books):**

| config | before | after | Δ | vs. ~0.125 floor |
|---|---|---|---|---|
| unfiltered | 0.487 | 0.383 | **−0.104** | within noise |
| `doc_type="book"` (scoped, cap 50) | 0.713 | 0.687 | **−0.026** | within noise |

Both aggregate deltas look like "holds." **They hide a real per-book collapse — the exact failure
mode Experiment 1 already demonstrated and this measurement was designed to catch:**

**Per book, n=23 each:**

| book | unfiltered before→after (Δ) | scoped before→after (Δ) |
|---|---|---|
| AB Testing — untouched | 0.522 → 0.522 (+0.000) | 0.739 → 0.783 (+0.043) |
| **Econ/Social/Health — repaired** | **0.826 → 0.391 (−0.435) REGRESSION** | **0.957 → 0.609 (−0.348) REGRESSION** |
| Discovery in Python — repaired | 0.435 → 0.348 (−0.087) | 0.696 → 0.652 (−0.043) |
| Tech Industry — untouched | 0.435 → 0.435 (+0.000) | 0.652 → 0.696 (+0.043) |
| Elements — untouched | 0.217 → 0.217 (+0.000) | 0.522 → 0.696 (+0.174) |

(MRR moved the same direction as recall for every row — e.g. Econ/Social/Health's MRR dropped
0.677→0.274 unscoped, 0.801→0.331 scoped — ruling out a fluke at the hit/miss threshold rather than
a real shift.)

**Untouched books are not perfectly flat in the scoped configuration** (AB Testing/Tech Industry
+0.043, Elements +0.174) even though their own chapters never changed. This is a real, explainable
side effect, not noise in the sense of measurement error: the scoped cap's rerank pool is shared
across all `doc_type="book"` candidates, so shrinking Econ/Social/Health's chapter count (44→38)
and reshaping Discovery's (7→23) changes who else is competing for the same slots. Their unfiltered
numbers ARE exactly flat (+0.000 each) — unfiltered candidates are drawn from the whole 372k-point
corpus, where 5 books' chapters are a rounding error in the competition, so no shared-pool effect
reaches them there.

### The specific risk named in the task did NOT materialize — a different one did

**Discovery in Python held.** −0.087 unfiltered / −0.043 scoped, both comfortably inside the noise
floor — despite reshaping from 7 to 23 units, the same *shape* of change (small marker split → many
size-merged units) that collapsed this exact book 0.375→0.000 in Experiment 1's outline-split
change. **This is not the same finding as Experiment 1's** — a different splitter (outline-cut vs.
size-merge) produced different units, and this result shows unit-count reshaping alone does not
automatically wreck routing, contrary to what a naive read of Experiment 1 might suggest.

**Econ/Social/Health collapsed instead.** −0.435 unfiltered / −0.348 scoped — both 2.8–3.5× past
the noise floor, the largest single regression measured anywhere in this programme. Plausible
mechanism (offered as a hypothesis, not verified further — out of scope to chase down here): the
OLD split's 44 units were mostly the bare-number bug's own tiny, hyper-specific fragments (word
share min/median/max 57/181/104425 — a chapter could be 57 words). An eval question's gold passage
often sat inside one of those narrow fragments, so the "chapter" embedding was accidentally
passage-sized and lexically close to the question — inflating routing recall in a way that doesn't
reflect real chapter-topic routing. The repaired split's units are uniform chapter-sized prose
(5013/6619/25824 words) — a real embedding of real chapter-scale content, diluting whatever narrow
lexical signal the old fragments coincidentally matched on. If true, some of the OLD 0.826/0.957
numbers for this book were never a reliable measure of chapter routing to begin with — but the
repaired number is the one that has to ship, and it is worse.

**Report per-book, not aggregate, going forward — this run is exactly why:** the overall deltas
(−0.104/−0.026) alone would have looked shippable.

---

## Full suite / CI

```
RAG_CONFIG=.../config.yaml python -m pytest -v --color=no
```

```
RAG_CONFIG=.../config.yaml GITHUB_EVENT_NAME=push python -m ci.run_enforcement
```

(Numbers filled in after the final run below, post phase-2 file additions.)

---

## Verdict against the narrowed gate

**Gate:** *"if chapter routing drops by more than the ~0.125 noise floor in either configuration,
the split change does not ship as-is."*

- Discovery in Python: **passes.** −0.087 / −0.043, both within floor.
- Econ/Social/Health: **fails, clearly.** −0.435 / −0.348, both 2.8–3.5× the floor, in *both*
  configurations.
- Overall aggregate: would read as "passes" (−0.104 / −0.026) — **this is exactly the masking
  effect the task named as the reason to report per-book.** Do not trust it.

**Verdict: the chapter-boundary change does not ship as-is.** Re-ingesting production with the
repaired split, as currently implemented, would trade Econ/Social/Health's routing quality for
clean labels — precisely the trade Experiment 1 already proved is not automatic and is not
acceptable here either.

**What DOES ship, per the operator's framing:** the regex correctness fix itself
(`rag/book_summarizer.py`'s `_bare_numbers_are_sequential` discriminator plus the duplicate-title
guard) — it eliminates 643 false-positive matches and every duplicate chapter title, independent of
what retrieval does with the result, and touches no production data. This PR ships that fix, its
tests, the eval-report evidence above, and the new `fixtures/eval/eval_book_questions_tdoc87.json`
fixture (for reproducibility of this measurement) — but **does NOT trigger a production re-ingest**
of the 2 affected books' chapters, because that specific action is what this measurement shows is
unsafe for Econ/Social/Health.

**Recommendation back to the operator:** the regex fix lands now, on correctness grounds. Chapter
boundary re-ingestion for these 2 books stays open, blocked on one of:
1. Investigate why Econ/Social/Health's OLD (buggy) split scored so well — if the mechanism above
   (accidental passage-sized fragment matching) is confirmed, the 0.826/0.957 "before" numbers may
   themselves be the misleading artifact, in which case the real comparison point isn't this book's
   own history but whether 0.391/0.609 is competitive with a book of comparable real structure
   (e.g. Tech Industry: 0.435/0.696 — Econ/Social/Health's repaired numbers are actually in a
   similar range to Tech Industry's, not obviously an outlier once the old number is set aside).
2. Or, keep Decision 4A (label disambiguation, no boundary change) as the production-facing fix for
   duplicate labels, and treat this repair as available machinery for future re-ingests /new books,
   not an immediate re-ingest trigger for these 2.
3. The two follow-up candidates recorded above (Discovery's TOC mis-classification;
   Strategy-B's title-selection quality) are both real and both out of this PR's scope.

**Ship status: do not ship.** Code stays on this branch behind a PR, not merged, per the task's
"never merge a PR" instruction and this verdict.
