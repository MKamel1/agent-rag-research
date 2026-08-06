# T-DOC82 — book chapter detection + book-appropriate summarization

*2026-07-26. Both defects found by the first live drop-in ingest against the real corpus
(T-DOC80's feature). Status: awaiting user review of this spec.*

## The two defects

Both were invisible to the unit suite: its fixtures are synthetic 3-block `ParsedDoc`s with a
real `" > "` hierarchy, summarized by `FakeSummarizer` (a truncation stub that cannot fabricate).
Only a real book through real MinerU and the real local LLM exposes them.

### D1 — chapter splitting degenerates to ~1 chapter per chunk

`rag/book_summarizer.py::_split_chapters` groups blocks by `_top_level(section_path)`, i.e.
`section_path.split(" > ", 1)[0]`.

**Measured on the real corpus:** an arXiv paper (`0705.1270`) has 113 blocks whose `section_path`
contains `" > "` — MinerU builds a real heading stack there, because the headings are numbered
(`2. History-Restricted MSM > 2.1. Data structure`). A real book
(`local:f0929288d4f3`, *Causal Inference in Python*, 2,520 blocks, ~144k words) has **zero**
blocks containing `" > "` and **306 distinct flat `section_path` values**.

So on books `_top_level` is an identity function, and every heading becomes its own "chapter":
530 chapter summaries against 535 chunks for one book. Observed titles include `Contributors`,
`About the author`, `Italic`, `Constant width`. Median group is 2-5 blocks.

Consequences: ~530 LLM summarize calls per book instead of ~15-30 (the dominant cost of the
76-minute run); chapter-level routing hits polluted with front-matter and typographic-convention
"chapters".

### D2 — the whole-book summary is fabricated

`rag/summarizer.py`'s `_SUMMARY_PROMPT` is hard-coded for academic papers: *"Summarize this
academic paper's contribution... (b) the main quantitative result or effect size... (d) dataset
or sample size used"*. `book_summarizer.py` calls that same `summarize()` for every chapter AND
for the reduce step.

Asked for an effect size that doesn't exist, the model invents one. Real stored output for
*Causal Inference and Discovery in Python* (a Python textbook):

> "The paper introduces a novel hybrid method that combines structural equation modeling with
> machine learning... an improvement in causal effect estimation by approximately **15%**...
> as measured by **mean squared error** on benchmark datasets."

No such method, number, or benchmark exists in that book. This is a grounding failure — the
specific thing this system exists to prevent — and it is what `get_paper` returns for every book.

## Fix 1 — chapter detection (`rag/book_summarizer.py`)

`_split_chapters` tries two strategies in order, then the existing structureless fallback.

**Strategy A — explicit chapter markers.** A heading is a chapter marker if it matches
(case-insensitive, on the heading text):

- `^(chapter|part|appendix)\s+(\d+|[ivxlc]+|one|two|three|four|five|six|seven|eight|nine|ten)\b`
- `^\d+\.\s+\S` (numbered chapter headings)

Blocks between consecutive markers belong to the preceding marker; blocks before the first
marker become a leading unit titled `""` (front matter).

**Accepted only if the result is plausible**, else fall through to B:
- `3 <= len(units) <= 60`, and
- no single unit holds more than 50% of the document's words.

The guard is the point: a book that merely *mentions* "Chapter 3" in one heading must not produce
2 units, one holding 95% of the text.

**Strategy B — size-based merge (fallback, and the expected path for most books).** Walk the
flat heading-groups in reading order, accumulating into a unit until it reaches
`_TARGET_CHAPTER_WORDS = 5000`, then close it. Title = the first heading in the group. Trailing
remainder merges into the previous unit if it is under half the target (avoids a stub tail unit).

On the measured book (144k words) this yields ~29 units — real-chapter scale, and independent of
heading text entirely.

**Existing structureless fallback unchanged:** when there is ≤1 distinct heading, the current
`_FALLBACK_WINDOW_BLOCKS = 150` windowing still applies.

`_summarize_text`'s existing depth-2 windowing still covers a unit exceeding
`_MAX_CHAPTER_WORDS`, so an oversized real chapter needs no new handling.

**Front matter needs no special-casing.** Under B it merges into the first unit; under A it is
the leading `""` unit. Explicitly *not* building a front-matter blocklist — heading names vary
per publisher and a blocklist would be endless.

## Fix 2 — book-appropriate prompt (`rag/summarizer.py`)

`OllamaSummarizer.summarize` gains one optional keyword-only argument:

```python
def summarize(self, parsed: ParsedDoc, *, kind: str = "paper") -> str:
```

`kind="paper"` (the default) keeps `_SUMMARY_PROMPT` and today's behavior **byte-identical** — the
11k-paper corpus is not re-summarized and no existing paper path changes.

`kind="book"` selects a new `_BOOK_SUMMARY_PROMPT`, which drops every paper-shaped field and adds
an explicit grounding constraint:

> Summarize what this book section actually covers, in 4-6 sentences: its main topics, the
> concepts or methods it explains, and how it fits into the book's subject matter. State only
> what the text says. Do not invent numbers, results, effect sizes, datasets, or findings — if
> the text does not contain them, omit them entirely.

A third prompt covers the reduce step (`kind="book_overview"`), which is where the fabrication
above actually originated:

> These are section summaries from a single book. Describe what the book as a whole covers in
> 4-6 sentences: its subject, scope, and the main topics it treats. State only what these
> summaries say. Do not invent numbers, results, or findings.

`book_summarizer.py` passes `kind="book"` for the map step and `kind="book_overview"` for the
reduce step. Unknown `kind` raises `ValueError` (a caller bug, not a data problem).

`FakeSummarizer.summarize` accepts and ignores `**kwargs`/`kind`, so every existing zero-GPU test
keeps working unchanged.

## Testing

Unit (zero-GPU, zero-network, per TEST-STRATEGY):

- **Strategy A:** headings `["Chapter 1 Intro", ...]` split at markers; `Part II` / `Appendix A`
  / `3. Estimation` variants; blocks before the first marker become the `""` leading unit.
- **A's plausibility guard:** a doc with one stray `Chapter 3` heading and 95% of words in one
  unit must REJECT A and fall through to B — asserted by the resulting unit count/titles.
- **Strategy B:** a flat 306-heading, 144k-word shaped fixture yields a unit count in the
  expected band (~20-40), not ~300; each unit's word count is near the target; the title of each
  is its first heading; a small trailing remainder merges rather than forming a stub.
- **Structureless:** ≤1 distinct heading still takes the existing 150-block windowing path.
- **Regression pin for D1:** the exact failure shape — N distinct flat headings with no `" > "` —
  must NOT produce N units. This is the test that would have caught the bug.
- **Prompt selection:** a fake HTTP client captures the request body; assert `kind="paper"`
  sends `_SUMMARY_PROMPT` unchanged, `kind="book"`/`"book_overview"` send their own prompts, and
  an unknown kind raises `ValueError`.
- **Wiring:** `summarize_book` passes `kind="book"` per chapter and `kind="book_overview"` once
  for the reduce — asserted via a recording fake summarizer.

Not unit-testable (operator verification, below): whether the new prompts actually stop the
fabrication. That requires the real model.

## Rollout — verify on one book before re-ingesting the rest

The 5 books now in the corpus carry fabricated summaries and ~1,380 junk chapter summaries.

1. Land the fix.
2. Delete ONE book (`DocumentStore.delete` + `VectorIndex.delete` — T-DOC80 Task 2 made that
   return every chapter summary id, so both stores stay in sync) and re-ingest it from
   `drop_in/done/`.
3. **Inspect before proceeding:** unit count is ~15-30 not ~300; chapter titles look like real
   sections, not `Italic`/`Contributors`; and the whole-book summary contains no invented
   numbers/benchmarks and actually describes that book.
4. Only if that passes, delete + re-ingest the remaining 4.

Re-ingest also re-exercises the cross-store delete path on real book data, which has never run
outside unit tests.

## Out of scope

- Re-summarizing the 11k arXiv papers (paper path is unchanged by design).
- A front-matter blocklist (see above).
- Making MinerU emit real heading hierarchy for books — upstream parser behavior; this spec adapts
  to what it actually produces.
- The migration-mechanism gap (T-DOC81, separate).

## Risks

- **The plausibility guard's thresholds (3/60/50%) are judgment calls**, tuned against one
  measured book. If a future book lands outside them it silently takes strategy B — acceptable,
  since B is the safe general path, but worth revisiting if a book with genuine `Chapter N`
  headings gets B-split anyway.
- **The anti-fabrication instruction is a prompt constraint, not a guarantee.** It reduces the
  failure mode; it cannot prove absence. Step 3 above is a human read of real output, deliberately
  not an automated assertion.
