# Decisions waiting on you — book-RAG programme, 2026-07-29

*Four decisions. Each states the question, the options, the trade-offs, why it matters, and a
recommendation. Nothing here has been actioned — all four need your call.*

**Reading the numbers:** every figure is chapter-routing or passage recall@10 on the same
40-question / 5-book eval set, measured on collection `exp1_ctrl_sizemerge_idf` (372,741 points,
identical to production except sparse IDF is on). **The measured noise floor is ~0.125 at N=40** —
deltas below that are suggestive, not established.

---

## Context in one paragraph

Five experiments tested ways to improve book chapter routing. **All five failed.** While
investigating why, three stacked ceilings turned up in the retrieval path — none of them in the
chapter units the experiments were tuning. Lifting them takes chapter routing from **0.425 to
0.900**. Two of the three lifts need your decision; the third is free and already shipping.

| cap | scope | chapter R@10 | |
|---|---|---|---|
| 3 | none | **0.425** | today |
| 3 | `doc_type="book"` | 0.650 | **+0.225** — free, Decision 0 |
| 50 | `doc_type="book"` | 0.725 | +0.075 — Decision 2 |
| **50** | **gold-book-scoped** | **0.900** | +0.175 — Decision 3 |

---

## Decision 0 — no decision needed, but you should know

**`filters={"doc_type":"book"}` is worth +0.225 and already ships.** `search_papers` accepts it and
its own docstring already recommends it for conceptual/background questions.

The eval harness never passed filters. So the 0.425 "baseline" this project has been quoting for
weeks describes *an agent that ignores existing guidance*, not a system limitation. Nothing to
approve — but the harness should measure both paths from now on, and the guidance deserves to be
harder to miss.

---

## Decision 1 — Run the IDF reindex on the production collection?

### The question
Production's sparse vectors have **no IDF weighting**. `app/reindex_idf.py` (OG-27) exists to fix
that. Do you want it run?

### Why it matters
Production `papers` was created before T-DOC27 landed, and `_ensure_collection()` only sets the
sparse IDF modifier at *creation* time — there is no in-place alter. So the fix has been in the code
for weeks while the live collection ran without it. Every freshly-created collection gets IDF
automatically, which is how this surfaced: it silently confounded Experiment 1 and nearly produced a
wrong verdict.

| surface | IDF off (today) | IDF on | Δ |
|---|---|---|---|
| paper recall@10 | 0.675 | 0.750 | **+0.075** |
| passage recall@10 | 0.625 | 0.700 | **+0.075** |
| chapter routing@10 | 0.450 | 0.425 | −0.025 |

Passage recall is the metric that carries actual answers, so net is clearly positive. This affects
**every query against the corpus**, not just books.

### Options

**A — Run it now.** One-time reindex. No re-embedding, no GPU. Three safety layers already built:
snapshot-first (verifies a real completed snapshot of that exact collection exists on disk — does
not merely trust a flag), a point-count invariant before/after that raises `ContractError` on
mismatch, and an IDF post-check that fails if the modifier didn't land. Idempotent.

**B — Validate on the paper eval set first, then run.** The +0.075 is measured on 40 *book*
questions. A 210-question paper eval set exists. Run it against an IDF-on clone before touching
production.

**C — Don't run it.** Accept the loss; avoid the risk entirely.

### Trade-offs
The real risk is the mechanism: `rebuild()` scrolls every point out, **drops the collection**,
recreates it with the modifier, and re-upserts. Between the drop and the re-upsert, the only copy of
372,741 points is in process memory. A crash, OOM, or power loss there loses the collection. It is
recoverable from a snapshot (5.73 GB, taken 2026-07-29 13:57) plus the source-of-truth SQLite, but
recovery is hours, not minutes.

Option B costs one extra eval run (~10 minutes, no GPU contention) and buys real information: if the
gain doesn't reproduce on papers, the case weakens considerably, since papers are 11,021 of 11,026
documents.

### Recommended: **B**
The gain is the largest single-lever improvement measured in this programme and it applies corpus-
wide. But it is measured on 40 book questions, and this session has already produced two confident
numbers that didn't survive checking. One 10-minute validation run against the 210-question paper set
before a destructive operation on the live corpus is proportionate.

---

## Decision 2 — Relax the per-paper cap for chapter routing?

### The question
`rag/retriever.py:59` `_MAX_HITS_PER_PAPER = 3` applies to `retrieve_papers()`. At most **3 chapters
per book** can appear in a chapter-routing response, regardless of `k`. Should that change?

### Why it matters
For a 26-chapter book, the correct chapter must beat 23 siblings for one of 3 slots. This is a
structural ceiling nobody had measured against — and it **masks the value of everything below it**.

It also re-explains Experiment 1's most confusing result. Discovery in Python collapsed from 0.375 to
0.000 when re-split from 7 to 24 chapters. The obvious reading was "units became too small." The
better reading is the cap: 24 chapters competing for 3 slots is far harder than 7 competing for 3.

| cap | filter | chapter R@10 |
|---|---|---|
| 3 | none | 0.425 |
| 10 | none | 0.450 |
| 3 | book | 0.650 |
| **10** | **book** | **0.725** |

Note the interaction: the cap barely matters *unfiltered* (+0.025) because global competition already
excludes book chapters. Once the filter clears the field, the cap becomes binding (+0.075).

### Options

**A — Raise `_MAX_HITS_PER_PAPER` globally.** One constant. Simplest possible change.

**B — Relax only when results are already scoped** — when a `doc_type` or per-paper filter is
active, allow more hits per paper; keep 3 for unscoped corpus-wide search.

**C — Make it a `Config` field.** Operator-tunable, no code change to adjust later.

**D — Leave it.** The +0.075 is below the noise floor; wait for a bigger eval set.

### Trade-offs
**T-DOC82 added this cap deliberately**, to stop one paper dominating a search across 11,026
documents. That reason still holds for unscoped search — option A would likely degrade cross-document
paper retrieval, which is the system's primary use. No measurement exists of A's effect on the
210-question paper set, and this decision should not be taken without one.

B is the design-correct answer: the cap exists to preserve diversity across a large candidate pool,
and that rationale evaporates once the caller has already narrowed to one doc type or one document.
It is more code than A — the cap function needs to know the active filter — but it is a small,
testable change.

C is tempting and I'd argue against it: a tuning knob nobody knows how to set is a deferred decision,
not a solved one, and it adds a `Config` field (foundation-frozen) for a value with one correct
answer per calling context.

### Recommended: **B**, and take it together with Decision 3
Not A — it risks the corpus-wide paper search that is the system's main job, unmeasured. Not D — the
+0.075 understates it, because the cap's real value only appears alongside Decision 3 (+0.175 more).
Measure A's effect on the paper eval set as part of the work, so the "does this hurt paper search"
question gets an answer rather than an assumption.

---

## Decision 3 — Add `paper_id` to `SearchFilters`? (foundation-frozen)

### The question
`SearchFilters` (`contracts/vector_index.py`) has `categories`, `published_after`,
`published_before`, `kind`, `doc_type` — but **no `paper_id`**. So a caller cannot say "search only
within this document." Should that be added?

### Why it matters
This is the largest single remaining gain: **+0.175 over `doc_type="book"`**, taking chapter routing
to **0.900**.

It is also the decision most easily gotten wrong. Experiment 5 initially measured gold-book scoping
as *identical* to `doc_type="book"` (0.650 both) and concluded a `paper_id` filter would unlock
nothing. That was an artifact: with the cap at 3, both arms bottom out on the same 3-slot ceiling, so
scoping can only reorder the same ≤3 candidates — visible as MRR rising 0.344→0.442 while recall
stayed flat. At a relaxed cap the gap opens to +0.175. **Decisions 2 and 3 each hide the other's
value in isolation.**

The measured 0.900 is a **lower bound**: it was produced by over-fetching and filtering post-hoc, so
the candidate set was still drawn globally. A real filter pushes scoping into the vector store, so
the candidate pool would come from the target document to begin with.

### Options

**A — Add `paper_id: str | None` to `SearchFilters`.** Foundation-frozen: `contracts/` is CODEOWNERS-
protected and needs the `foundation-change` label plus your sign-off. Also needs the payload filter
plumbed through `rag/vector_index.py`.

**B — Two-stage retrieval instead**, no contract change: call `search_papers` to find the book, then
a second scoped call. But there is no way to scope the second call without `paper_id`, so this
reduces to A with extra steps.

**C — Expose it only at the MCP layer**, not in `SearchFilters`. Avoids touching the frozen contract
by filtering results after retrieval — which is exactly the post-hoc approach that produced the
0.900 lower bound, and it wastes candidate slots on documents that will be discarded.

**D — Defer** until the eval set is large enough to confirm +0.175 above the noise floor.

### Trade-offs
A is the clean design: `SearchFilters` is explicitly "every field maps to a `VectorPayload` field of
the same name," and `paper_id` **is** a `VectorPayload` field. The shape is already there; the filter
just isn't exposed. Adding it is arguably completing the contract rather than extending it.

The cost is governance, not engineering: foundation-frozen means design review and your sign-off, and
that friction exists on purpose.

D's caution has real force — +0.175 is above the 0.125 floor but not by a wide margin at N=40, and
it depends on Decision 2 landing first. The eval-set expansion now in progress (115 questions) would
settle it.

### Recommended: **A, sequenced after Decision 2 and after the 115-question eval set lands**
The gain is real and the design is clean. But it is the one item here touching a frozen contract, and
its measured value depends on a cap change that hasn't been made yet. Order: expand the eval set →
Decision 2 → re-measure → then A with a number you trust. Nothing is lost by that sequence, and it
avoids a contract change justified by a 40-question measurement whose own confound we discovered
mid-session.

---

## Decision 4 — What to do about duplicate chapter titles

### The question
**16 of 101 chapter units share a title with another unit in the same book** — 4 of 7 in Discovery in
Python, 12 of 44 in Econ/Social/Health, 0 in the other three. An agent selecting a chapter by label
cannot distinguish them.

### Why it matters
This is a live defect in production, not a hypothetical. It also silently corrupts measurement: the
harness scores a hit when the returned `chapter` string equals the gold title, so routing to the
*wrong* unit with the same name counts as success. Both the defect and its measurement error are
real today.

Cause: the M2 marker-regex path (`^\d+\.\s+\S`) matches numbered list items in body text, producing
"chapters" like `1. https://freakonometrics...` and labelling two different units `Part 2: Causal
Inference`.

### Options
**A — Disambiguate at summarization time.** Append an index or parent when a title repeats within a
book. Cheap; makes labels unique without changing boundaries.
**B — Repair the marker regex (T-DOC87).** Fixes the cause for these two books.
**C — Use the outline split for these two books only.** It produced **zero** duplicates on all four
outline-bearing books — but lost on recall, and Discovery in Python was its worst case (0.000).
**D — Leave it.** 16 of 101 units, in 2 of 5 books.

### Trade-offs
C is the one to avoid: it fixes labels by adopting a splitter that measurably worsens the metric
those labels serve. Experiment 1 established that clean labels and good routing are separate
properties — Discovery in Python got perfect titles and 0.000 recall in the same change.

A is a few lines and cannot make routing worse, since boundaries don't move. It does not fix the
underlying mis-split — those two books still have units derived from numbered list items — but it
makes every unit addressable and removes the false-positive scoring.

B is the real fix and more work, and the plan already deprioritised it as "superseded if the outline
lands." The outline didn't land, so B is back on the table on its own merits rather than as a
fallback.

### Recommended: **A now, B later if the mis-split shows up in routing quality**
A removes the measurement error and the addressability defect immediately and safely. Keep T-DOC87
open — reclassify from "superseded" to "deferred, cause still present."

---

## Summary

| # | decision | recommendation | blocked on |
|---|---|---|---|
| 0 | `doc_type` filter | use it; measure both paths | nothing — already ships |
| 1 | IDF reindex | **B** — validate on paper eval set, then run | your approval |
| 2 | per-paper cap | **B** — relax only when scoped | your approval + paper-eval check |
| 3 | `paper_id` filter | **A** — after #2 and the 115-question set | your sign-off (foundation) |
| 4 | duplicate titles | **A** now, keep T-DOC87 open | your approval |

**Also worth knowing:** 40 questions cannot settle close calls. An expansion to **115 questions** is
in progress — that is the scaffolding that makes Decisions 2 and 3 measurable rather than arguable.

## What did NOT work, so you don't have to wonder

| intervention | result |
|---|---|
| Outline chapter boundaries (E1) | −0.100; **0 of 4 books improved**; one collapsed 0.375 → 0.000 |
| Contextual-retrieval headers (E2) | −0.20 passage recall; headers were book-level boilerplate |
| Section-aware boost (E4) | premise invalid — 86% of book `section_path` values are unique strings |
| Hierarchy / H1 (E3) | exact tie; usable in **1 of 4** books |
| Self-Route escalation (E5) | 0.575 vs 0.650 always-filtering — loses, and costs a second call |

**Size-merge chapter splitting stays** — it won on measurement, not by default.
