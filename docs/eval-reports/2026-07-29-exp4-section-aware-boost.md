# Experiment 4 — section-aware boost/filter by `section_path` (T-DOC64) — 2026-07-29

Experiment 4 of `docs/PLAN-book-rag-experiments.md`: boost/filter `semantic_search` results by
`section_path` type (favoring Method/Results-shaped sections over Introduction-shaped ones),
scored against the 40-question 5-book eval fixture (`fixtures/eval/eval_book_questions.json`).

**Verdict: stopped before implementation.** `section_path` is present on almost every chunk in
the book corpus this experiment targets, but it does not carry the kind of stable, reliable
Method/Results/Introduction-style label the T-DOC64 hypothesis needs. No boost was built, no
toggle was added, no A/B eval was run. Full measured distribution below; raw numbers also in
`2026-07-29-exp4-section-aware-boost.json`.

## Why this is the right stopping point, not a shortcut

The experiment brief pre-authorizes exactly this outcome: *"If the field is too sparse or too
inconsistent to support a boost, that is a legitimate and valuable finding — report it and stop
rather than building a boost over unusable data."* The measurement below shows the second half of
that sentence, not the first — `section_path` is not sparse (99.6% of the 5 books' 1,939 chunks
carry a non-empty value). It is inconsistent in the specific way that matters: it does not
distinguish "Method" from "Results" from "Introduction" from anything else in any way a scoring
function could exploit, for this corpus.

## What `section_path` looks like, measured

Three populations, all read-only against `papers.db` (`file:...?mode=ro`), no writes:

### 1. Corpus-wide (11,026 papers, 361,614 chunks — mostly arXiv research papers)

| | value |
|---|---|
| non-empty `section_path` | 96.8% |
| distinct non-empty values | 218,714 |
| classified `method` | 13.8% |
| classified `results` | 13.0% |
| classified `introduction` | 4.0% |
| classified `other` (unclassifiable) | 44.3% |

Research papers follow IMRaD-ish conventions closely enough that a deliberately loose keyword
classifier (`"method"`/`"methodology"`/`"approach"`/… → `method`, `"result"`/`"evaluation"`/
`"experiment"`/… → `results`, etc., after stripping numeric/roman-numeral/letter prefixes) resolves
55.7% of non-empty values into a canonical category — method+results alone is 26.8% of all
non-empty chunks. **If this population were what Experiment 4 is scored against, the field would
plausibly support a boost.** It is not: the 40-question fixture this experiment must be measured
against is 100% `doc_type="book"`.

### 2. The 5-book eval corpus (1,939 chunks — the actual population any boost would act on)

| | value |
|---|---|
| non-empty `section_path` | 99.6% |
| distinct non-empty values | 1,673 of 1,932 (**86.6% unique**) |
| classified `method` | 12.5% |
| classified `results` | 3.8% |
| classified `introduction` | 0.5% |
| classified `other` (unclassifiable) | **80.4%** |

Per book, method+results share ranges from 6.4% (*Causal Inference and Discovery in Python*) to
33.8% (*Elements of Causal Inference*) — too variable to calibrate one boost weight across the
fixture's own 5 books, let alone the wider book collection.

The reason is structural, not a classifier weakness: book `section_path` values are free-text
subsection headings, not IMRaD section labels — worked examples (`"Example: OEC for E-mail at
Amazon"`), nested notes (`"Notes > 5.1 Bias–Variance Trade-of"`), single-letter appendix markers
(`"A"` through `"W"`), and in a few cases OCR/parse artifacts standing in for headers (`"## Best
lambda for Ridge regression: 0.2529632"`, `"betahat\_OLS > 31.6 Factor Analysis"`). There is no
enumerable "type" here to boost by; each is closer to a unique caption than a category.

### 3. The eval fixture's own 40 gold answers

Applying the same classifier to the 40 questions' own `section_path` field (the fact-bearing
block's actual section — what a working boost would need to promote):

| category | count |
|---|---|
| `other` (unclassifiable) | **28 / 40 (70%)** |
| `method` | 8 / 40 |
| `results` | 3 / 40 |
| `appendix` | 1 / 40 |

70% of the eval set's own gold answers sit in a section the boost's taxonomy cannot recognize as
anything special — a boost built on Method/Results/Introduction detection would have zero
mechanical effect on 7 of every 10 questions in this fixture, and could only help the remaining 3
in 10 if it never mis-classifies a boundary case among that minority.

Separately: **`question_type` is uniform** — all 40 questions carry `"Book-Chapter-Recall"`. The
design plan's own text assumed a Method/Results-seeking subset could be isolated via the harness's
existing `by_question_type` breakdown (`"an aggregate-only comparison would dilute a real effect
on a minority of questions into noise"`) — that assumption does not hold for the fixture as
actually authored. There is no tagged subset to point a targeted boost at without retroactively
relabeling questions by their content, which is exactly the kind of after-the-fact,
retrieval-informed relabeling the fixture's own write-before-retrieval discipline exists to rule
out (`_metadata.authoring_method`: *"no question in this file... was written by looking at what
search_papers/semantic_search returns"*).

## Collection that would have been used, had the data supported a boost

Per the experiment brief's confound warning, both arms of any A/B must share one collection.
`exp1_ctrl_sizemerge_idf` was the intended choice (identical to production except IDF on — the
configuration this project is likely to ship), and was verified, read-only, before this
investigation concluded there was nothing to A/B:

- `exp1_ctrl_sizemerge_idf`: `point_count()` = 372,741, `has_idf_modifier()` = `True`
- `papers` (production, for contrast): `point_count()` = 372,741, `has_idf_modifier()` = `False`

Neither collection was written to. No eval run was executed against either, because there is no
boosted arm to compare against a no-boost arm — building that comparison over data that cannot
distinguish "Method" from "Introduction" would produce a number, but not a meaningful one.

## Against the falsification criterion

The pre-committed criterion (*"if section-aware boosting does not improve passage recall by more
than the ~0.125 noise floor, it does not ship"*) presupposes a boosted arm to measure. None was
built, so the criterion is not reached — this is a **data-quality stop**, one step upstream of
where the criterion would apply, not a sub-floor result being reported as inconclusive. **"No
measurable effect at N=40" is also not the honest summary here — the honest summary is "no
mechanism was built to measure," because the input the mechanism needs does not exist in usable
form for this eval's population.**

## What ships from this experiment

Nothing behind a toggle in `rag/retriever.py` — there is nothing to toggle. T-DOC64 remains a
documented idea without measured support, same status as `docs/METHODS-books-and-chunk-quality.md`
already records it — this run's contribution is the read-only `section_path` distribution above as
the *reason*, not a new open question. If a future revision of `T-DOC64` wants to revisit this, the
concrete blocker to solve first is upstream of retrieval: `section_path` would need a normalization
or classification pass at ingest/chunk time (turning "Notes > 5.1 Bias–Variance Trade-of" into a
`{method, results, introduction, other}`-style field) before any retrieval-time boost has usable
signal to act on for books — that is a chunker/parser-side change, not a `Retriever.retrieve()`
change, and is out of this experiment's scope.
