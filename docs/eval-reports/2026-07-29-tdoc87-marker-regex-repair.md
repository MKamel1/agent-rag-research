# T-DOC87 — chapter-marker regex repair (Decision 4, option B) — GATE: DO NOT SHIP

*2026-07-29. Implements the operator's chosen option (B — repair the marker regex) from
`docs/DECISIONS-PENDING-operator.md` Decision 4. Phase 1 (GPU-free) complete. **Phase 2 (GPU,
throwaway-collection routing measurement) was NOT run** — phase 1's own read-only projection
already trips the pre-committed stop condition ("if the repaired split still produces duplicate
titles or implausible units, stop and report — do not proceed to phase 2"), so no GPU budget was
spent. This is the cheap negative result the task's own gate anticipated.*

**Verdict: do not ship as-is.** Duplicates are eliminated (goal achieved), but that required a
second guard beyond the regex itself, and that guard reshapes Discovery in Python's chapter
boundaries 7 → 23 units — structurally the same kind of change Experiment 1 already measured
collapsing that book's routing recall to 0.000. Separately, Econ/Social/Health still produces
several implausible chapter titles after the repair (not duplicates, but not usable routing labels
either). Both are explicit phase-1 stop conditions. See "Verdict" at the end.

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

These are not duplicates (each string is unique), so they don't fail the duplicate check — but
they are exactly the "implausible units" the phase-1 gate calls out as an independent stop
condition. `_best_heading`'s title-quality logic is out of T-DOC87's stated scope (a Strategy-B
concern, not a marker-regex one) and was not touched here.

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

## Full suite / CI

```
RAG_CONFIG=.../config.yaml python -m pytest -v --color=no
# ===================== 1448 passed, 39 deselected in 49.51s =====================
```
(39 deselected = `real_adapter`-marked tests, excluded by `pyproject.toml`'s default `addopts`,
same as every other push.)

```
RAG_CONFIG=.../config.yaml GITHUB_EVENT_NAME=push python -m ci.run_enforcement
# enforcement: PASS -- no violations in checks (a)-(d), (f)-(h)
```

---

## Verdict against the gate

The task's phase-1 gate: *"If the repaired split still produces duplicate titles or implausible
units, stop and report — do not proceed to phase 2."*

- **Duplicate titles:** eliminated in the literal count (0/5 books have any after both guards).
  ✅ on that narrow reading.
- **Implausible units:** Econ/Social/Health still produces multiple non-representative chapter
  titles (list-item fragments, a printed numeric artifact) even with 0 duplicates. **Trips the
  gate on its own.**
- **Boundary reshaping risk (the task's separately pre-committed criterion):** the duplicate-title
  guard needed to actually clear Discovery in Python's duplicates forces that book from 7 units to
  23 — the same *shape* of change (small marker-based split → many size-merged units) that
  Experiment 1 already measured collapsing that exact book's chapter routing from 0.375 to 0.000
  while simultaneously producing "perfect" titles. Phase 1 cannot measure routing (no GPU, no
  embeddings) — but the task was explicit that this is not a coincidence to wave off: *"changing a
  book's chapter boundaries can wreck routing while improving labels... it is one of the two books
  you are touching."* This is exactly that book, exactly that shape of change.

**Both explicit stop conditions are met.** Per the task's own instructions ("do not proceed to
phase 2... this is the cheap negative result"), phase 2 (GPU re-summarization, throwaway
collection, fixture re-derivation, routing measurement) was **not run**. Spending the GPU budget
to *measure* a regression that the task's own prior experiment (Experiment 1) already demonstrated
for this exact book, on this exact shape of change, would not be new information — it would be
re-confirming a known failure mode at real cost.

**Recommendation back to the operator:** this regex-only repair does not clear the bar Decision 4B
was asking for. Two honest paths forward, neither of which this task's scope covers:
1. **Decision 4A** (disambiguate labels at summarization time, append an index/parent on a
   within-book title collision) does not require touching chapter boundaries at all, so it cannot
   reproduce Experiment 1's routing collapse — it was the doc's own original recommendation for
   exactly this reason, deprioritizing B as "later, if the mis-split shows up in routing quality."
   This projection suggests the mis-split does not repair cleanly without either accepting a
   reshaping risk (Discovery in Python) or leaving implausible titles in place
   (Econ/Social/Health) — i.e., the mis-split *has* now "shown up," but as a routing-shaped risk
   this task cannot resolve without phase 2, not as a clean win.
2. If B is still wanted, `_best_heading`/Strategy B's title-quality logic needs its own pass (it
   is what's producing Econ/Social/Health's remaining implausible titles) before a phase-2 GPU
   spend would even be evaluating a clean candidate.

**Ship status: do not ship.** Code stays on this branch behind a PR, not merged, per the task's
"never merge a PR" instruction and this verdict.
