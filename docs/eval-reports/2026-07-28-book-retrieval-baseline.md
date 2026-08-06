# Book retrieval baseline — 2026-07-28

> **HISTORICAL** — superseded by the 5-book baseline (2026-07-29-book-retrieval-baseline-5book.md). Current state: [../PROJECT-STATUS.md](../PROJECT-STATUS.md).

Part 3 Step 1 of `docs/DESIGN-book-chapters-and-hierarchy.md`: the first-ever measurement of
whether book chapter routing/retrieval works at all, against today's chapter split (before any
outline-based re-split — that's Step 2).

Full per-question detail: `2026-07-28-book-retrieval-baseline.json` (`app/retrieval_eval.py
--report-path`). Eval set: `fixtures/eval/eval_book_questions.json` (15 questions, seed set).

## Run

```
python -m app.retrieval_eval \
  --ground-truth fixtures/eval/eval_book_questions.json \
  --config /home/omar/ai-projects/research-system-rag-data/config.yaml \
  --k 10 \
  --report-path docs/eval-reports/2026-07-28-book-retrieval-baseline.json
```

Against the live 11,026-document corpus (read-only retrieval calls only — `semantic_search`/
`search_papers` never write). 0 retrieval errors across all 15 questions.

## Headline numbers (k=10)

| metric | overall (n=15) | Trustworthy OCE, no outline (n=8) | CI in Python, 223-entry outline (n=7) |
|---|---|---|---|
| paper-level recall@10   | 0.667 | 0.750 | 0.571 |
| passage-level recall@10 (`semantic_search`) | 0.600 | 0.625 | 0.571 |
| chapter-level recall@10 (`search_papers`)   | 0.467 | 0.625 | 0.286 |

(MRR: paper 0.667, passage 0.600, chapter 0.296 overall — see the JSON for MRR broken out by
book and the full per-question hit/rank detail.)

## What these numbers mean

- **Chapter routing works some of the time, not reliably** (46.7% overall). `search_papers`
  finds the chapter containing the answer for fewer than half these questions — this is what
  `ChapterSummary`/`book_summarizer.py`'s map-step summaries exist for, and today it's
  meaningfully worse than a coin flip would need to beat only because the corpus has thousands of
  competing chapters/papers, not because the questions are contrived (see the eval set's
  `authoring_method` — questions were written from chapter content, then routed here for the
  first time).
- **Passage recall is higher than chapter routing** (60.0% vs. 46.7% overall) — `semantic_search`
  finds the right specific chunk more often than `search_papers` finds the right chapter for the
  same underlying fact. That gap is itself a finding: chapter-level routing and passage-level
  retrieval are not moving together, which is exactly why the design doc insists on measuring them
  as two separate metrics rather than one.
- **The two outline regimes look different, on 15 questions.** CI in Python (which DOES have a
  223-entry/4-level PDF outline the splitter doesn't use yet) scores lower on chapter routing
  (28.6%) than Trustworthy OCE (which has NO outline, 62.5%) under today's heuristic split. This is
  suggestive, not conclusive at n=7/n=8 — it's the number Step 2's A1-outline-vs-A2-heuristic A/B
  needs to beat for CI in Python specifically, not a verdict on whether an outline would help.

## What Step 2 compares against

Re-run this exact command (same `--ground-truth`, same `--k`) against a re-split corpus (A1
outline-based or a repaired A2), and diff the three recall/MRR numbers above, overall and per
book, against this file. `app/reembed_experiment.py` is the existing precedent for a matched
before/after run against a throwaway collection.
