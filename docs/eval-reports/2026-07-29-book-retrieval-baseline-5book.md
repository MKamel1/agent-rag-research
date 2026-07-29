# Book retrieval baseline — 5 books — 2026-07-29

Experiment 0 of `docs/PLAN-book-rag-experiments.md`: extends `fixtures/eval/eval_book_questions.json`
from 2 books (15 questions) to all 5 ingested books (40 questions, 8 per book), then re-runs
`app/retrieval_eval.py` against the **unmodified, current** chapter split (today's Strategy
A-marker/B-size-merge output) to produce the first baseline that covers the whole corpus's book
content. This is instrumentation, not a test — it produces the number Experiment 1 (outline-based
chapter split) will need to beat, extended from 2 books to 5.

Full per-question detail: `2026-07-29-book-retrieval-baseline-5book.json`
(`app/retrieval_eval.py --report-path`). Eval set: `fixtures/eval/eval_book_questions.json`
(40 questions, 8 per book, all fixture entries hand-authored and gold-label-verified against
`papers.db` read-only **before** this run — see the fixture's own `_metadata` for the full method).

## Run

```
python -m app.retrieval_eval \
  --ground-truth fixtures/eval/eval_book_questions.json \
  --config /home/omar/ai-projects/research-system-rag-data/config.yaml \
  --k 10 \
  --report-path docs/eval-reports/2026-07-29-book-retrieval-baseline-5book.json
```

Against the live 11,026-document corpus (read-only retrieval calls only — `semantic_search`/
`search_papers` never write). 40/40 questions scored, 0 retrieval errors.

## Headline numbers (k=10)

**Read the per-book column count before the per-book recall number** — 8 questions per book is
below the ~114-question power target §1 of `docs/PLAN-book-rag-experiments.md` computes for
detecting an 18-point chapter-routing swing; a single book's 0.625 here is one question away from
0.500 or 0.750. Treat every per-book number below as directional, not a precise estimate, and treat
the 40-question **overall** row the same way once Experiment 1 tries to move it by less than a
gross, unmistakable swing.

| book (paper_id) | n | paper recall@10 | paper MRR | passage recall@10 (`semantic_search`) | passage MRR | chapter recall@10 (`search_papers`) | chapter MRR |
|---|---|---|---|---|---|---|---|
| Trustworthy OCE, no outline (`local:14b7e283bdcd`) | 8 | 0.750 | 0.750 | 0.625 | 0.625 | 0.625 | 0.368 |
| CI in Python, 223-entry outline (`local:f0929288d4f3`) | 8 | 0.500 | 0.500 | 0.500 | 0.500 | 0.250 | 0.188 |
| Elements of Causal Inference (`local:f6c64e1e8c7d`) | 8 | 1.000 | 0.917 | 1.000 | 0.854 | 0.500 | 0.181 |
| Causal Inference and Discovery in Python (`local:dfe850b3281a`) | 8 | 0.625 | 0.625 | 0.625 | 0.625 | 0.375 | 0.263 |
| Causal Inference and ML in Econ/Social/Health (`local:54d6ca71dda9`) | 8 | 0.500 | 0.417 | 0.375 | 0.375 | 0.500 | 0.307 |
| **OVERALL** | **40** | **0.675** | **0.642** | **0.625** | **0.596** | **0.450** | **0.261** |

Every `n` above is a raw count of the questions drawn from that book, not a weighted sample —
each book contributes exactly 8/40 = 20% of the "overall" row regardless of the book's actual size
(the corpus's books range from 1,771 to 6,316 blocks), so "overall" is an unweighted mean across
books, not a corpus-representative average.

## Did the 2 previously-covered books move after the T-DOC95 retrofit?

**No — identical, exactly, both in aggregate and per question.** The 2-book baseline
(`docs/eval-reports/2026-07-28-book-retrieval-baseline.md`) was captured *before* T-DOC95's
retrofit rewrote 36 papers' chunk text (duplicate-heading stripping in `rag/chunker.py`'s
`_build_chunk`). To check whether that retrofit changed anything for these 2 books, this run's
per-question hit/rank for all 15 originally-covered questions (`QB-001`..`QB-015`) was diffed
against the old baseline's own per-question JSON, at rank granularity (not just recall/MRR, which
could hide a rank change that doesn't cross a hit/miss boundary):

- **0 of 15 questions' `(paper_rank, passage_rank, chapter_rank)` tuple changed.**
- Trustworthy OCE's per-book aggregate: paper 0.750/0.750, passage 0.625/0.625, chapter
  0.625/0.368 (recall/MRR) — identical to the old baseline's own per-book numbers, recomputed from
  its JSON the same way.
- CI in Python's original 7 questions (`QB-009`..`QB-015`, excluding this task's 8th new question
  `QB-040`): paper 0.571/0.571, passage 0.571/0.571, chapter 0.286/0.214 — identical to the old
  baseline's reported 0.571/0.571/0.286 (recall) for that book.

What was compared: `docs/eval-reports/2026-07-28-book-retrieval-baseline.json`'s
`questions[]` array (keyed by `question_id`) against this run's own `questions[]` array for the
same 15 ids — a straight tuple-equality diff, script discarded after use (the comparison, not the
conclusion, is what's load-bearing; the conclusion is stated here). This is consistent with
T-DOC95's own description of the change (duplicate-heading-block stripping only touches chunk
*text* the parser had already mis-duplicated within a chunk, not which block anchors a chunk or
which chapter a block falls under) — a finding, not an assumption: the fact that literally every
rank is unchanged, not just the aggregate recall, is what rules out a change that happened to
cancel out in the mean.

## Gold-label verification

Every one of the 25 new questions' `gold_chapter_title`, `gold_chapter_index`, `gold_chunk_id`,
`gold_block_id`, `excerpt_block_id`, `section_path`, `page`, and `passage_excerpt` was checked
**programmatically** against `papers.db` (`file:...?mode=ro`, read-only) before any retrieval call:
excerpt block's real `page`/`section_path` from `blocks`; chapter membership and title from
`rag/book_summarizer.py`'s own (unmodified) `_split_chapters()` called against the live `blocks`
table, cross-checked against the persisted `ChapterSummary.title`; the excerpt block's owning
chunk's real anchor from `rag/chunker.py`'s own (unmodified) `Chunker` class, cross-checked against
the live `chunks.anchor_json`. All 15 pre-existing questions were re-run through the same
programmatic check as a regression guard on this task's own edits.

**Checked: 40/40 questions, all fields, both new and pre-existing.**
**Corrected: 0 `gold_chunk_id`/`gold_block_id`/`gold_chapter_title`/`section_path`/`page` labels** —
every one matched the live DB on the first pass; the final automated check
(`gold label vs. live DB` script, run once fixture-complete) reported 0 mismatches across all 40
records. **9 `passage_excerpt` fields were corrected** during authoring, before being locked into
the fixture commit: an early pass hand-cleaned LaTeX/OCR artifacts out of 9 quotes for readability
(e.g. writing "sufficiency" for the source's OCR-dropped-ligature "suficiency"), which silently
broke the field's own documented invariant — `passage_excerpt` must be a literal substring of the
source block's text, the way every pre-existing entry in this file already is (e.g. `QB-013`'s
"Diference-in-Diferences"). All 9 were reverted to the verbatim OCR text before the fixture was
written to disk; the invariants test does not check this substring property mechanically (it
predates papers.db access in CI), so this was caught by the same one-off verification script noted
above, not by `test_eval_book_questions_invariants.py`.

**Two data-quality findings surfaced during authoring, not corrected because they reflect real
production state** (documented in the fixture's `_metadata.sampling_note`, repeated here since
they affect how to read this book's chapter-level numbers):

- `local:dfe850b3281a` has two pairs of chapter units sharing an identical persisted title
  ("Part 2: Causal Inference" for both units 2 and 5; "Part 3: Causal Discovery" for both units 3
  and 6) — `search_papers`' chapter-routing hit check is title-string equality against
  `PaperSearchResult.chapter`, which cannot in general distinguish two same-titled chapters of the
  same paper. This task's 8 questions for that book were deliberately drawn only from units 4-6
  (never unit 2 or 3), so none of them are individually scored against an ambiguous title — but a
  future reader of this book's chapter-routing number should know the ambiguity exists in the
  underlying split, independent of this eval set.
- `local:54d6ca71dda9` over-splits into 44 chapter units (vs. 7-26 for the other 4 books) because
  a numbered algorithm-step list (e.g. `"2. Define Gini Index for a Node t"`) false-positive-matches
  `book_summarizer.py`'s chapter-marker regex; many units are 2-13 blocks long. One of this book's
  8 questions (`QB-034`) deliberately draws from one such small fragment-unit, both because its
  content was independently checkable and because it documents this book's over-split behavior
  rather than hiding it — directly relevant to Experiment 1's chapter-routing comparison.

## What these numbers mean

- **Chapter routing is still the weak link, now confirmed at 5x the book count**: 45.0% overall
  (vs. 46.7% on the 2-book/15-question set) — close enough at this sample size that "chapter
  routing works less than half the time" reads the same at n=15 and n=40, which is itself a useful
  (if unexciting) confirmation that the 2-book number wasn't a fluke of which 2 books got picked
  first.
- **Passage recall remains higher than chapter routing** (62.5% vs. 45.0% overall, vs. 60.0%/46.7%
  on the 2-book set) — the same qualitative gap the 2-book baseline found, holding up on 3
  additional books.
- **Per-book spread is wide and the sample is too small to explain why.** Elements of Causal
  Inference scores 1.000/1.000 on paper/passage recall (8/8, every one of its dense-math
  theorem/proposition quotes was retrieved) but only 0.500 on chapter routing — the same
  passage-vs-chapter gap as every other book, just at a higher passage baseline. Causal Inference
  and ML in Econ/Social/Health, the most fragmented book (44 chapter units, many 2-13 blocks), does
  **not** score obviously worse on chapter routing (0.500, in the middle of the 5-book range) —
  which is itself worth flagging as a non-finding: over-splitting into many small chapters was a
  plausible hypothesis for hurting chapter-routing recall, and this run doesn't support it, but 8
  questions on one book cannot rule it out either.
- **The honest power limitation, restated from the plan rather than left implicit:** §1 of
  `docs/PLAN-book-rag-experiments.md` computes that resolving an 18-point chapter-routing swing
  (the rough size of the M3-vs-M4 title-quality jump the plan's own qualitative reference point)
  needs roughly n≈114 questions at conventional significance, even before accounting for the
  paired-design efficiency gain a same-question A/B would get. This 40-question set (like the
  15-question set before it) can catch a **gross** regression or an unmistakable qualitative win —
  it cannot adjudicate a close call, and no number in the table above should be read as
  distinguishing, say, 0.450 from 0.500 chapter-routing recall with any confidence. This is the
  number Experiment 1 is explicitly told to check against a larger (synthetic-supplemented) set
  before concluding anything from a small movement.

## What Experiment 1 compares against

Re-run this exact command (same `--ground-truth`, same `--k`) against a re-split corpus (A1
outline-based or a repaired A2), **re-deriving `gold_chapter_title`/chapter-membership fields
against the new split first** (this fixture's own `chapter_split_note` — block-level provenance
carries over, chapter labels do not), and diff the recall/MRR numbers above, overall and per book,
against this file. `app/reembed_experiment.py` is the existing precedent for a matched before/after
run against a throwaway collection.
