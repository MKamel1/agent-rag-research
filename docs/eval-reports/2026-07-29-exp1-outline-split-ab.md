# Outline-based chapter split vs. size-merge — Experiment 1 A/B — 2026-07-29

Experiment 1 of `docs/PLAN-book-rag-experiments.md`: builds an outline-based chapter splitter
(`rag/book_summarizer.py`'s `_split_chapters_outline`/`pick_outline_level`, new, alongside the
existing size-merge `_split_chapters`) and A/B's it against today's size-merge split on
chapter-routing recall, for the 4 books whose PDF ships a usable outline. The gate step
(`docs/eval-reports/2026-07-29-outline-join-feasibility.md`) already proved the outline→block page
join is a constant, zero-offset join for all 4 books; this run spends the GPU budget the gate
cleared: re-summarizing ~97 chapters, embedding them into a throwaway collection, and re-scoring.

**Headline: the falsification criterion triggers. Outline-based chapters do not beat size-merge on
chapter-routing recall for any of the 4 outline-bearing books — 2 tied, 2 declined, one severely.
Per the pre-committed criterion, A1's structural correctness is aesthetic here and A2 (size-merge)
wins.** This is not being restated more favourably than the numbers support. It is also not a
"close call, underpowered" situation — see the per-book table and its magnitudes below; the
direction is unambiguous even under this experiment's own acknowledged small-N limits.

Full per-question detail: `2026-07-29-exp1-outline-split-ab.json` (`app/retrieval_eval.py
--report-path`, run against the throwaway collection below). Splitter + tooling:
`rag/book_summarizer.py` (`_split_chapters_outline`, `pick_outline_level`,
`rag/test_book_summarizer.py`), `rag/vector_index.py` (`VectorIndex.clone_points_into`,
`rag/test_vector_index.py`), `app/exp1_outline_split.py` (orchestration, no tests of its own —
same "spike script, no unit-test file" convention as `app/reembed_experiment.py`/`app/rechunk.py`,
its logic is exercised end-to-end by this run and by `rag/book_summarizer.py`'s own unit tests).

## Run

GPU-free half (splitter + tests) committed separately; GPU half:

```
RAG_CONFIG=/home/omar/ai-projects/research-system-rag-data/config.yaml \
    python -m app.exp1_outline_split \
    --dest-collection exp1_outline_chapters \
    --work-dir .exp1-work \
    --fixture-out fixtures/eval/eval_book_questions_outline_split.json \
    --report-out .exp1-work/split-report.json
```

This: (1) clones the full production `papers` collection (372,741 points) into the throwaway
`exp1_outline_chapters` collection via `VectorIndex.clone_points_into` — no re-embedding, so the
other 4,997 papers' and OCE's own vectors are byte-identical to production; (2) for each of the 4
outline-bearing books, runs the **unmodified** `summarize_book()` against the new outline split
(`rag.book_summarizer._split_chapters` substituted for the duration of one call via
`unittest.mock.patch` — see `app/exp1_outline_split.py`'s module docstring for why editing
`summarize_book()` itself was rejected); (3) writes the new chapter/overview summaries into a
throwaway SQLite copy of `papers.db` (`DocumentStore.get`/`.put` against the copy only, never the
corpus) and swaps the corresponding vectors in the throwaway collection (stale old chapter ids
deleted, new ones upserted); (4) re-derives `gold_chapter_title`/`gold_chapter_index` for the 32
questions on the 4 touched books against the new split (`fixtures/eval/
eval_book_questions_outline_split.json`) — the 8 OCE questions are carried over byte-for-byte.

Scoring (separate, already-existing tool, per the task):

```
python -m app.retrieval_eval \
    --ground-truth fixtures/eval/eval_book_questions_outline_split.json \
    --config /home/omar/ai-projects/research-system-rag-data/config.yaml \
    --db-path .exp1-work/papers.db --blob-dir .exp1-work/blobs \
    --collection exp1_outline_chapters --k 10 \
    --report-path docs/eval-reports/2026-07-29-exp1-outline-split-ab.json
```

40/40 questions scored, 0 retrieval errors, both runs.

**A note on a bug found and fixed along the way, not part of the experiment's own logic:**
`VectorIndex.clone_points_into`'s first version sent a whole `_SCROLL_PAGE_SIZE` (100,000-point)
page in one `upsert` call; against the real 372,741-point collection that serialized to a
multi-gigabyte request body, and Qdrant's REST API rejects any single request over a fixed 32MB
regardless of client timeout. Fixed by re-batching the upsert side independently
(`_CLONE_UPSERT_BATCH_SIZE = 400`, `rag/vector_index.py`) — read and write sides now have
independent sizes. Caught by the first real run (RC=1), not by the unit test that shipped with the
GPU-free half (2 points was never going to hit a 32MB ceiling) — a second live test
(`test_clone_points_into_batches_the_upsert_side`) now monkeypatches the batch size down to 2 so 5
points genuinely exercise multiple batches without needing thousands of real points in CI.

## GPU lock wait

The coordinator's resume message reported Experiment 2's re-embed jobs had already finished and
the GPU was idle (9.8GB resident, 0% util) before this run started, with only a brief, cheap
scoring job (40 query embeddings) possibly contending. No explicit wait-time instrumentation was
added to `FileGpuLock` for this run (it blocks silently, no log line on wait), and no
`TransientError`/lock-timeout was raised at any point. Total wall clock for the full GPU-bound run
(clone + 4 books' map-reduce summarization, ~97 chapter map-calls + 4 reduce-calls + embed calls,
all through `qwen3:14b`) was **~37 minutes** (07:14:10–07:51:25 UTC by file timestamps), a plausible
order of magnitude for that workload on its own. **Honest statement, not a stronger claim than the
evidence supports:** nothing observed indicates a significant stall, but the total isn't decomposed
into "waiting" vs. "computing," so a wait of a few minutes hidden inside that total cannot be ruled
out. No workaround was used — every real call went through the shared `FileGpuLock` at
`/home/omar/ai-projects/research-system-rag/.gpu.lock`.

## Chapter-routing recall@10 — the metric of record

| book (paper_id) | N | baseline (today's size-merge) | outline split | Δ |
|---|---|---|---|---|
| CI in Python (`f0929288d4f3`) | 8 | 0.250 | 0.250 | +0.000 |
| Elements of CI (`f6c64e1e8c7d`) | 8 | 0.500 | 0.375 | −0.125 |
| CI and Discovery in Python (`dfe850b3281a`) | 8 | 0.375 | **0.000** | **−0.375** |
| CI and ML in Econ/Social/Health (`54d6ca71dda9`) | 8 | 0.500 | 0.500 | +0.000 |
| Trustworthy OCE, no outline, **control** (`14b7e283bdcd`) | 8 | 0.625 | 0.500 | −0.125 |
| **OVERALL** | **40** | **0.450** | **0.325** | **−0.125** |

Baseline column reproduced from `docs/eval-reports/2026-07-29-book-retrieval-baseline-5book.json`
(recomputed from its `questions[]` array grouped by `gold_paper_ids`, not retyped by hand — script
discarded after use, same discipline the baseline doc itself used against the prior one).

**Zero of the 4 outline-bearing books improved.** Two are exactly tied (CI in Python, Econ/Social/
Health — same hit count, same 8 questions), one declined by one question (Elements), one collapsed
from 3/8 hits to 0/8 (CI and Discovery in Python). Per the task's own pre-committed guidance ("a
clear per-book reversal is meaningful; a 1-question difference is not"): CI-Discovery's swing is a
clear reversal, not noise; Elements' one-question decline is exactly at the noise threshold the
task itself names as inconclusive on its own — but see the OCE control below, which independently
establishes what a one-question move looks like on this harness even with **zero** change to the
book in question.

## The OCE control moved — investigated, not hand-waved

**The control's number moved: 0.625 → 0.500, and per the task's own instruction that is a red flag
requiring an explanation before the other books' deltas can be trusted.** OCE
(`local:14b7e283bdcd`) has no PDF outline and was never touched by this experiment — its
`ChapterSummary` rows, its chunk/summary vectors, are byte-identical between the production
`papers` collection and the throwaway `exp1_outline_chapters` clone.

**Root-caused, not assumed.** Two candidate explanations were checked, not just one asserted:

1. **Non-determinism in the serving stack** (embedder/reranker giving slightly different scores
   run to run, e.g. from floating-point batching effects) — **ruled out**. The 8 OCE questions
   were re-run, right now, straight against the unmodified, live production `papers` collection
   (`.exp1-work/oce_only.json`, same fixture questions, same gold labels): paper 0.750, passage
   0.625, chapter 0.625 (MRR 0.368) — an **exact** reproduction of the original baseline row,
   digit for digit, run as a completely separate process at a different point in time, with
   Experiment 2 having been active on the same GPU in between. The pipeline is deterministic.
2. **Collection composition** — **confirmed**. The only variable between that reproduction (0.625,
   against `papers`) and this experiment's own run (0.500, against `exp1_outline_chapters`) is
   which collection was queried. `retrieve_papers()` (`rag/retriever.py`) is a **global** hybrid
   search + RRF-fusion + fixed-size rerank pool over every `kind="summary"` point in the
   collection, for a given query — not scoped per book. Swapping ~97 of 372,741 points' text (the
   4 re-split books' chapter + overview summaries) shifts each of: Qdrant's collection-wide,
   live-computed sparse IDF statistics (`_sparse_vector_params()`, `rag/vector_index.py`'s own
   docstring: "computed by Qdrant itself from this collection's own live document-frequency
   stats"), and the relative dense/RRF ranking of everything else that competes for the same
   fixed-size candidate pool (`rerank_depth`) before truncation to `k`. Both are corpus-relative,
   not per-book-isolated, computations — so touching any subset of the collection's summary-kind
   text can, in principle, nudge a borderline candidate from an **untouched** book in or out of the
   top-`k`, purely through changed competition, without that book's own vectors changing at all.
   This is not a broken join, not data loss, not a vendor bug — it is a real, deterministic
   property of scoring an A/B arm inside one shared collection.

**What this means for the rest of the table:** the OCE control's one-question move (12.5 points)
is the measured noise floor this specific methodology (clone-whole-collection-then-swap-a-subset)
introduces, on top of the already-acknowledged small-N noise from 8 questions/book. Paper- and
passage-level numbers (never touched by this experiment's write path at all — only chunk-kind
retrieval) also moved for 2 of 5 books (OCE paper 0.750→1.000, passage 0.625→0.875; Econ/Social/
Health paper 0.500→0.625, passage 0.375→0.500), moving in **both directions** across books, which
is consistent with a shared-ranking perturbation and not with a directional bug that would only
ever help or only ever hurt. Elements' −0.125 chapter-level move is the same magnitude as this
confirmed noise floor and should not be read as a splitter-quality finding on its own. CI and
Discovery in Python's −0.375 move is roughly **3× the confirmed noise floor** and cannot be
explained by this mechanism alone — see below.

## Why CI and Discovery in Python collapsed to 0/8, checked for a bug first

A book going from 3/8 hits to 0/8 is the kind of result that gets reported as a bug unless it's
been checked. It was checked, not assumed real:

- **Titles match exactly, character for character**, between the re-derived fixture's
  `gold_chapter_title` and the throwaway DB's persisted `summaries.title` (spot-checked
  `local:dfe850b3281a:summary:ch7` = `"Chapter 3: Regression, Observations,  and Interventions"`
  — double space preserved — against QB-024's gold label).
- **Content is real, not degenerate**: every one of this book's 24 new chapter rows has
  substantial persisted text (603–2,849 characters), not an empty/failed summarization.
- **A live `retrieve_papers()` trace for one of the book's questions** shows the book's chapters
  genuinely competing in the pool (two of its own points appear in the top 10 for one query — one
  correctly resolving to `chapter="Index"`, one to the whole-book overview, `chapter=None`, by
  design) — the resolution mechanism itself works; the *specific* right chapter simply didn't
  outrank its own 23 siblings and everything else in the corpus for these 8 queries.

**The most plausible real explanation, not a bug:** this book went from **7 units (baseline) to 24
units (outline split)** — the largest relative granularity increase of the 4 books (the gate doc's
own "shift in granularity is real and book-specific" warning, quoted in the task brief, called this
out in advance). More, thinner candidate chapters from the *same* book compete against each other
for the same query, and each individual chapter's summary now covers noticeably less content
(spanning fewer of the book's own distinguishing terms), diluting the signal that used to make one
of 7 broad units win handily. This is a real, structural cost of finer granularity that the
duplicate-title elimination (next section) does not offset for this book's chapter-routing number.

## Duplicate chapter titles — outline split eliminates them, a separate finding

The baseline carried 16 of 101 chapter units with a title duplicated elsewhere in the same book (4
of 7 in Discovery, 12 of 44 in Econ/Social/Health, 0 in the other three) — an A2 defect
`search_papers`' title-equality scoring cannot see around. Reported here as its own finding, not as
a substitute for the recall result above:

| book | baseline duplicate units | outline-split duplicate units |
|---|---|---|
| CI in Python | 0 / 26 | 0 / 17 |
| Elements of CI | 0 / 8 | 0 / 18 |
| CI and Discovery in Python | **4 / 7** | **0 / 24** |
| CI and ML in Econ/Social/Health | **12 / 44** | **0 / 38** |

**Every duplicate title is eliminated.** A real book's own PDF outline essentially never repeats a
literal title string across chapters, unlike the size-merge marker strategy, which can legitimately
produce two units both titled e.g. `"Part 2: Causal Inference"` (a Part divider heading reused as
the whole unit's label). This is a genuine structural improvement — it just isn't the one this
experiment's pre-committed criterion is gated on, and it does not rescue Discovery's recall number:
Discovery went from a split with duplicates (title-ambiguous, but higher recall) to a split with no
duplicates (title-clean, but recall collapsed) — clean labels and correct routing moved in opposite
directions for this book.

## Structural sanity (front matter, unit counts, no implausible unit)

No candidate unit swallowed an implausible share of any book (max word share 26.2%, Elements —
unchanged from the gate doc's own Q4 finding, since word shares are computed from the same
`blocks`, only the reporting script differs). Front matter handling (leading Cover/Copyright/
Dedication-type units under `_FRONT_MATTER_MAX_WORDS=500`, merged structurally by word count, no
label blocklist — `rag/book_summarizer.py`) produced the expected two shapes: CI in Python and
Elements absorb their true front matter into the first real outline entry (that entry's own page
range already starts at page 0, so no separate `""` bucket is needed); CI-Discovery and
Econ/Social/Health each produce one leading `""` unit (which `summarize_book()`'s own unmodified
LLM-title fallback then names, e.g. `"Causal Inference and Discovery in Python Book Section"` for
Discovery's unit 0) before their first named entry.

| book | outline level picked | unit count | word share min / median / max |
|---|---|---|---|
| CI in Python | 1 (Chapter) | 17 | 0.001 / 0.070 / 0.124 |
| Elements of CI | 0 | 18 | 0.001 / 0.042 / 0.262 |
| CI and Discovery in Python | 0 | 24 | 0.001 / 0.038 / 0.136 |
| CI and ML in Econ/Social/Health | 0 | 38 | 0.000 / 0.023 / 0.080 |

(Unit counts here are lower than the gate doc's raw boundary counts — 17/18/29/42 there vs.
17/18/24/38 here — entirely explained by this splitter's front-matter merge collapsing several
leading small units into one, plus dropping any boundary page with zero blocks; the gate doc's own
`units_at_level` did neither, since it was answering a different question, "are the boundaries
plausible," not producing a real split.)

## Verdict against the pre-committed falsification criterion

**Falsification criterion (task, restated verbatim, not more favourably):** *"if outline-based
chapters do not beat size-merge on chapter-routing recall for the outline-bearing books, A1's
structural correctness is aesthetic and size-merge (A2) wins."*

**Triggered.** 0 of 4 outline-bearing books improved. 2 tied exactly, 1 declined by an amount
indistinguishable from this methodology's own confirmed noise floor, 1 collapsed by roughly 3× that
floor for an identified, plausible, book-specific structural reason (a 7→24 granularity jump).
Overall chapter-routing recall fell from 0.450 to 0.325.

**This is not a close call.** The task's own guidance is to say "close call, underpowered" only
when the result is genuinely ambiguous near the noise floor with no clear direction — that would
describe Elements' single-book −0.125 in isolation, but not the set of 4 books together, where not
one book moved in the improving direction and one moved sharply against it. A result with zero wins
across 4 independent books is a directionally unambiguous outcome even at N=8/book; low power
widens the plausible range around each point estimate, it does not manufacture a win out of four
losses/ties.

**A1 (outline-based split) does not clear the bar. A2 (size-merge) wins on the metric this
experiment was gated on.** Per the task's own stated logic, this also settles **A3** (repairing the
marker regex, T-DOC87) as not worth building: A1 was already the higher-ceiling structural fix
A3 was to be superseded by, and a losing A1 makes investing in repairing the thing A1 was meant to
replace less justified, not more.

**What should still ship, separately from the recall verdict:** the duplicate-title elimination is
real and worth keeping in mind for a *future* attempt at combining an outline-derived front-matter/
title source with size-merge's granularity — that recombination was not built or tested here and is
future work, not a claim this report makes.

## Artifacts left in place

- Throwaway Qdrant collection: **`exp1_outline_chapters`** (372,753 points — production's 372,741
  plus a net +12 from the 4 books' unit-count change, 97 new chapter/overview units replacing 85
  old ones). Left running, not deleted, per the task.
- Throwaway SQLite copy + blobs: `.exp1-work/papers.db`, `.exp1-work/blobs/` (git-ignored,
  worktree-local scratch — not part of the diff).
- New fixture: `fixtures/eval/eval_book_questions_outline_split.json` (committed;
  `eval_book_questions.json` itself was never mutated).
- Full per-question report: `2026-07-29-exp1-outline-split-ab.json` (this directory).
