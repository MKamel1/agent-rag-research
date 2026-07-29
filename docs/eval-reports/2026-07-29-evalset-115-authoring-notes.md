# Evalset 115 authoring notes (T-DOC-BOOK-EVAL-115)

*2026-07-29. Companion to `fixtures/eval/eval_book_questions.json` (now 115 questions, 23/book x
5 books) and `docs/PLAN-book-rag-experiments.md` §1 (the power calculation and authoring method
this task executes). Read this alongside the fixture's own `_metadata` block, which carries the
same facts in machine-readable form.*

## What this is

`docs/PLAN-book-rag-experiments.md` §1 computed that resolving an 18-point chapter-routing swing
at α=0.05/power=0.80 needs ~114 questions; the existing 40-question set (8/book) could only prove
the harness worked, not adjudicate an experiment. This task adds 75 questions (15/book) to reach
115, using the same discipline as the original 40: every question was written and locked into the
fixture — question text, answer, `gold_chapter_title`/`gold_chapter_index`, `excerpt_block_id`,
`section_path`, `page`, `passage_excerpt` — **before any `search_papers`/`semantic_search` call was
made against the corpus for that question.** No exception, across any of the 5 books. The five
per-book commits on this branch (`evalset-115-questions`), each touching only
`fixtures/eval/eval_book_questions.json`, are the audit trail for that claim.

## Method, per book

1. Read the book's persisted `ChapterSummary.title` rows (`summaries` table, `papers.db`,
   `file:...?mode=ro`) to enumerate every chapter unit and flag any title shared with another
   unit of the same paper.
2. Call `rag/book_summarizer.py`'s `_split_chapters()` — imported, never modified — read-only
   against the live `blocks` table to recover each unit's actual content.
3. Read that content, find a concrete, quotable, checkable fact (a number, a named theorem, a
   specific worked example, a named method/paper) in a unit whose title is **not** shared with
   another unit of the same paper, and write the question from it.
4. Find the fact block's owning chunk in the live `chunks` table (matching the fact block's raw
   text as a substring of the chunk's stored text, not a recomputed `Chunker` run) and record that
   chunk's live `anchor_json.block_id` as `gold_block_id`/its `chunk_id` as `gold_chunk_id` — the
   same "anchor is the chunk's first block, not the fact block" convention the original 40 uses,
   for the same reason (scoring against the fact block directly is unwinnable by construction).

## Duplicate-title chapters skipped

Per-book chapter units that share a title with another unit of the *same* book (so a
chapter-routing hit check, which is title-string equality, cannot distinguish them):

| Book | Total units | Duplicate-titled units | Skipped for new Qs |
|---|---|---|---|
| `local:14b7e283bdcd` (Trustworthy OCE) | 16 | 0 | 0 |
| `local:f0929288d4f3` (CI in Python) | 26 | 0 | 0 |
| `local:f6c64e1e8c7d` (Elements of CI) | 8 | 0 | 0 |
| `local:dfe850b3281a` (CI & Discovery in Python) | 7 | **4** (`Part 2: Causal Inference` x2, `Part 3: Causal Discovery` x2) | 4 |
| `local:54d6ca71dda9` (CI & ML in Econ/Social/Health) | 44 | **12** | 12 |
| **Total** | **101** | **16** | **16** |

Matches the count stated in the task brief exactly (16 of 101). The original 40 already contains 5
questions drawn from 3 of these ambiguous units (QB-028/029 and QB-030/031 in `dfe850b3281a`'s
`Part 2`/`Part 3`, QB-034 in `54d6ca71dda9`'s `5. Recursive Partitioning...`) — those are
pre-existing, documented exceptions from the original authoring pass and were **left unchanged**
per this task's "keep all 40 existing questions unchanged" instruction. None of the 75 new
questions draw from any duplicate-titled unit; the invariants test now asserts this directly
(`KNOWN_DUPLICATE_CHAPTER_TITLES`, checked only for `QB-041`+).

### Structural finding: `dfe850b3281a` has only one usable unit

This book's 7 chapter units break down as: unit 0 is copyright/foreword/acknowledgments (no
checkable claim at all), unit 1 is a literal table-of-contents block dump (also no checkable
claim), units 2/3/5/6 are the 4 duplicate-titled units (off-limits), leaving **exactly one** unit
— unit 4, `"3. Finally, let's examine the results in Table 3.1:"` (pages 73–119) — with both a
non-ambiguous title and real content. All 15 of this book's new questions had to come from that
single unit. This is a hard ceiling imposed by the book's chapter split (the real Part 2/Part 3
technical content — most of the book — sits inside the ambiguous units), not a sampling choice;
flagging it here rather than letting it look like a spread violation. The 15 questions still
sample across that unit's own full page range (75–119, spread across 12 distinct pages) and its
existing 4 questions' pages (74/91/103/117) were avoided for distinct facts.

## Sampling requirements — how they were met

- **Full chapter-range spread** (not clustered at the start): achieved for 4 of 5 books (see the
  `dfe850b3281a` finding above for the one exception). E.g. book 1's new 15 span all 16 chapter
  units (pages 23–238); book 2's new 15 span 14 of 26 units (pages 63–369, previously-unused by
  the existing 8); book 3's new 15 revisit its only 8 units with distinct facts (pages 23–246,
  necessary since the book has just 8 units total); book 5's new 15 span 15 previously-unused
  units out of 32 non-ambiguous ones (pages 67–694).
- **At least 4 mid-content-section facts per book** (not section-opening claims): comfortably
  exceeded in every book — most of the 75 are several paragraphs/blocks into their section, not
  the opening sentence. Book 1 alone has ~10 of its 15 clearly mid-section (e.g. the RAND-corp
  bias example, the Simpson's-paradox Sure-Thing-Principle theorem, the SIDEBAR: Gameability
  examples).
- **Deliberate lexical-distance variation**: roughly half the 75 quote the source's own distinctive
  vocabulary closely (named theorems, exact formula components, exact percentages) and roughly
  half paraphrase the question away from the source excerpt's wording (e.g. QB-050's "human raters
  miss local context" instead of quoting "5/3"/"Fifth Third Bank" in the question itself; QB-077's
  "channel"/"signal" metaphor question instead of naming "front-door adjustment"; QB-096's "common
  cause" framing instead of quoting "llama"). Not tagged per-question in the fixture (the task
  didn't ask for a stored field for this), but every question's design notes above record the
  reasoning.

## Facet distribution (`QB-041`..`QB-115` only; not backfilled onto the original 40)

| facet | count |
|---|---|
| named-concept | 19 |
| definition | 16 |
| numeric-result | 15 |
| caveat-condition | 10 |
| method-procedure | 8 |
| comparison | 7 |
| **Total** | **75** |

Per book (all 6 facets appear in at least 3 of the 5 books; every book has at least 4 of the 6):

| Book | definition | numeric-result | named-concept | method-procedure | comparison | caveat-condition |
|---|---|---|---|---|---|---|
| `14b7e283bdcd` | 1 | 6 | 2 | 1 | 2 | 3 |
| `f0929288d4f3` | 3 | 5 | 3 | 1 | 1 | 2 |
| `f6c64e1e8c7d` | 3 | 1 | 9 | 2 | 0 | 0 |
| `dfe850b3281a` | 3 | 2 | 5 | 0 | 3 | 2 |
| `54d6ca71dda9` | 6 | 1 | 0 | 4 | 1 | 3 |

`f6c64e1e8c7d` (Elements of Causal Inference, a dense math monograph) skews heavily toward
named-concept (named theorems/principles/propositions) since that's almost all its content is;
`54d6ca71dda9` skews toward definition/method-procedure (formulas, DML/2SLS procedure steps).
This is a property of the books, not an authoring artifact — forcing an even split per book would
have meant writing weaker, less-representative questions.

## Validation — full pass against the live `papers.db`

Ran read-only against `papers.db` (`file:...?mode=ro, uri=True`) for all 115 questions (not just
the 75 new ones, so the original 40's provenance is re-confirmed too):

| Check | Checked | Failed | Corrected |
|---|---|---|---|
| `gold_block_id`/`gold_chunk_id`/`excerpt_block_id` exist, belong to `source_paper_id` | 115 | 0 | 0 |
| `gold_chunk_id`'s live anchor block == `gold_block_id` | 115 | 0 | 0 |
| `gold_chapter_title` matches a real `summaries.title` for that paper | 115 | 0 | 0 |
| `gold_chapter_title` unique within its paper | 115 | **5** | 0 (see below) |
| `passage_excerpt` is a verbatim substring of `excerpt_block_id`'s text | 115 | 0 (at final check) | 1 during authoring |
| `page` matches the excerpt block's real page | 115 | 0 (at final check) | 5 during authoring |

**Title-uniqueness failures (5):** all 5 are `QB-028`/`QB-029`/`QB-030`/`QB-031`/`QB-034` —
pre-existing, documented exceptions in the *original* 40 (see "Duplicate-title chapters skipped"
above). Zero of the 75 new questions fail this check; the extended invariants test enforces that
going forward (`KNOWN_DUPLICATE_CHAPTER_TITLES`, gated to `QB-041`+).

**Corrections made during authoring** (before these commits landed, all caught by the validation
script and fixed against the live block data — never guessed):
- `QB-056`, `QB-059`, `QB-060`, `QB-066`, `QB-067` (book 2): `page` was mistranscribed by 1 while
  copying from a `grep` dump (e.g. `63` recorded instead of the block's actual `64`). Fixed to the
  block's real page.
- `QB-104` (book 5): `excerpt_block_id` pointed at the wrong adjacent block (the permutation-
  importance sentence is one block later than where I'd recorded it). Fixed to the correct block
  and its real page.
- `QB-098` (book 4): the source block contains a genuine OCR artifact — a literal U+FFFD
  replacement character in `"...is Markov equivalent if and only if all DAGs in <U+FFFD> have..."`.
  Per the "preserve OCR artifacts literally, don't clean up" rule this had to stay verbatim, but
  the character didn't reliably round-trip through this session's tool-call text encoding, so the
  `passage_excerpt` was narrowed to a clean prefix of the same block (`"Let's introduce the
  concept of the Markov equivalence class (MEC)."`) built by slicing the live block text directly
  (not retyped), guaranteeing an exact substring match rather than risking a silent mismatch.

## Self-review pass

Before committing the final book, re-read all 75 questions against the three checks the task
specifies. One revision:

- **`QB-088` (book 4) replaced.** Original: *"How does the book distinguish directed graphs from
  undirected graphs?"* → *"Directed graphs are graphs with directed edges, while undirected graphs
  have undirected edges."* This is circular by construction — the words *directed* and *undirected*
  already answer the question, so it tests nothing about retrieval or the book specifically; any
  model would produce this without ever seeing the text. Replaced with a fact from the same
  section (page 82, same chunk) that isn't self-answering: *"Per the book, what tool does it say
  you can use to represent a graph where you know all the edges but are unsure about the direction
  of some of them?"* → *"Complete partially directed acyclic graphs (CPDAGs)."* Re-validated clean.

**Questions flagged as doubtful but kept** (reviewed against "could this be answered from general
causal-inference knowledge without the book," judged defensible enough to keep, but worth a reader
knowing the call was close):
- `QB-071`/`QB-072` (book 3, Reichenbach's common cause principle / initial-state-and-dynamical-law
  principle): both are well-known, field-standard statements that appear in multiple causal
  inference texts, not unique to this book. Kept because the *entire* original 8-question set for
  this book is the same genre (exact numbered Theorem/Proposition statements from a dense math
  monograph) — excluding these would be inconsistent with the established convention for this
  specific book, and the exact-numbering/exact-wording match is still real retrieval-relevant
  provenance, not something reproducible from memory alone with confidence.
- `QB-069` (book 2, inverse propensity weighting definition): standard technique documented broadly
  in the causal inference literature, not unique to this book's phrasing. Kept for the same
  consistency reason — the original 40 already includes an almost-identical-genre question
  (`QB-012`, the stabilized-propensity-weights pseudo-population fact) for this same book.
- `QB-089` (book 4, connected/fully-connected/disconnected graph definitions): standard graph-
  theory vocabulary. Weaker than the replaced `QB-088` but not circular — "fully-connected = edges
  between *all* pairs" is a specific enough claim to be wrong if guessed carelessly. Kept rather
  than spending more of book 4's single usable chapter's limited fact budget (see the structural
  finding above) chasing a marginally better replacement.
- `QB-113`/`QB-114` (book 5, IV independence/relevance assumptions in plain English): the
  substance (exclusion restriction, relevance/first-stage) is standard econometrics; the specific
  phrasing tested is book-tied but a strong causal-inference background could answer these without
  retrieval. Kept because they're paired with the book's own specific step-numbering
  (`1. Independence of the Instrument:` / `2. First-Stage (Relevance):`) which the chapter-routing
  half of the score depends on regardless of answer-content difficulty.

No question was found to have more than one defensible gold chapter — every fact was sourced from
a `_split_chapters()`-recomputed unit's own block dump, so the chapter-index assignment is fixed by
construction, and the duplicate-title skip (above) removes the one real source of that ambiguity
this corpus has.

## Deliverables checklist

- `fixtures/eval/eval_book_questions.json`: 115 questions (23/book x 5 books), `_metadata`
  extended with `authoring_method_115`, `facet_vocabulary`, `per_book_counts_115`,
  `no_retrieval_statement`, `created_115`.
- `fixtures/eval/test_eval_book_questions_invariants.py`: extended for 115 total, 23/book, the
  closed facet vocabulary (checked on `QB-041`+ only), and duplicate-chapter-title avoidance
  (checked on `QB-041`+ only, both against the hardcoded known-duplicate set and via internal
  self-consistency across all 115 records).
- Five commits, one per book, `fixtures/eval/eval_book_questions.json` only.
- This notes doc + the invariants-test commit.
