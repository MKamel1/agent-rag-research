# Book integration — closeout

*2026-07-30. What books do in this system, what shipped, what it measures, and every approach that
was tried and rejected with the test that rejected it.*

**All numbers below are recall@10 on the 115-question / 5-book eval set
(`fixtures/eval/eval_book_questions.json`), measured against the live production collection
(`papers`, 372,741 points, sparse IDF enabled) unless stated otherwise.**

**Measured noise floor: ~0.125 at N=40.** Established empirically from control drift, not assumed.
A delta below it is not a result. See "Measurement caveats" — several figures here are softer than
they look.

---

## 1. How book integration works

### Ingestion

A book enters as a PDF in `drop_in/`. Filename prefix `title--<Title>.pdf` sets the title
explicitly and **skips** metadata lookup entirely (T-DOC88); without it the system falls back to
arXiv lookup, then heuristics. Non-arXiv PDFs get a content-addressed id: `local:<sha256[:12]>`,
derived **only from bytes** — not filename, not `doc_type` — so re-dropping the same file is a
no-op rather than a duplicate.

Parsing produces `blocks` (text + `page` + `section_path`), the same shape papers use. `doc_type`
on `papers` is the only structural distinction between a book and a paper.

### Chapter splitting — the part that stayed hard

A paper fits one `summarize()` call; a book is 10–50× that, so it must be cut into units first.
`rag/book_summarizer.py` tries two strategies in order:

- **Strategy A — explicit markers.** Regex for `Chapter N` / `Part N` / `Appendix X` / `N. Title`.
- **Strategy B — size-merge (the working default).** Accumulate consecutive heading groups to
  ~5,000 words, then pick the unit's title by **structural scoring** of its ~12 candidate headings
  (T-DOC85), with an LLM-written title as fallback when no heading clears the floor.

Current split: 16 / 26 / 8 / 7 / 44 units across the five books, 101 total.

**Strategy A is known-defective and unrepaired.** Its `^\d+\.\s+\S` alternative matches numbered
list items in body prose — measured: **643 matching blocks across the five books, zero of them
real chapter markers**. Examples of resulting "chapters": `1. Scan the QR code or visit the link
below`, `2. Next, let's define the SCM`, `1. https://freakonometrics.hypotheses.org/52776`. A fix
exists and is measured but **does not ship** — see §4, T-DOC87.

### Summarization

Book-specific prompts (`book`, `book_overview`), separate from the paper prompt. This mattered:
asked for "effect size" and "sample size" of a textbook, the model **invented them** — a stored
summary once claimed a "novel hybrid method… 15–20% reduction in mean squared error… over 10
million observations from a financial services company," none of which existed in the book. The
book prompts carry explicit grounding constraints; verified on re-ingest.

### The two retrieval surfaces

| surface | MCP tool | searches | returns |
|---|---|---|---|
| **passage** | `semantic_search` | 361,614 chunk vectors | grounded spans with citations |
| **routing** | `search_papers` | ~11,100 summary vectors | paper/chapter summaries to choose from |

Both run hybrid dense+sparse with RRF fusion and a cross-encoder reranker
(BGE-reranker-v2-m3). The consumer is an **agent** that can issue multiple calls, not a
single-shot pipeline.

`search_papers` returns `PaperSearchResult.chapter` — the chapter summary's title. This is the
routing label an agent selects on, and it is scored by exact string match.

---

## 2. What shipped, and what each ships against

### Sparse IDF on the production collection

**What:** the vector store's sparse channel now uses BM25-style IDF weighting.

**Why it was missing:** `papers` was created before T-DOC27 landed, and `_ensure_collection()`
only sets the modifier at *creation* time — there is no in-place alter. Every freshly-created
collection got IDF automatically; production never did. It was found by accident, as a confound
that nearly invalidated Experiment 1.

**Measured, IDF off → on, three independent fixtures:**

| fixture | metric | off | on | Δ |
|---|---|---|---|---|
| 40q equation slice (papers) | passage R@10 | 0.8500 | 0.9250 | **+0.075** |
| 40q book set | paper R@10 | 0.6750 | 0.7500 | **+0.075** |
| 40q book set | passage R@10 | 0.6250 | 0.7000 | **+0.075** |
| 210q paper set | paper R@10 | 0.9762 | 0.9762 | 0.000 |
| 40q book set | chapter R@10 | 0.4500 | 0.4250 | −0.025 |

**The same +0.075 on three independent fixtures** — different documents, different authors,
different surfaces. That replication is what justified it; the magnitude alone (3 questions of 40)
would not have. The 210q null is consistent rather than contradictory: that fixture carries **no
gold blocks at all**, so it can only score paper-level, and at 0.9762 it is saturated.

**Post-restore verification against production:** paper 1.0000 / passage 0.9250 on the equation
slice — reproducing the IDF-on arm exactly.

### `filters={"doc_type": "book"}` on routing

**What:** restrict `search_papers` to book summaries, excluding ~11,021 paper summaries that can
never answer a book question.

**Measured:** chapter routing **0.487 → 0.713** (115q). Paper-level **0.774 → 1.000**.

**It was already built and already documented** — `search_papers` has always accepted
`SearchFilters`, and its own docstring already recommended `{"doc_type":"book"}` for
conceptual questions. **The eval harness never passed filters.** So every "baseline" this project
quoted for weeks described an agent ignoring existing guidance, not a system limit.

### Scoped per-paper cap

**What:** `_MAX_HITS_PER_PAPER = 3` (T-DOC82) still applies to unscoped corpus-wide search;
`_MAX_HITS_PER_PAPER_SCOPED = 50` applies once `filters` narrows the search.

**Why:** the cap stops one paper dominating a page of results drawn from 11,026 documents — sound
unscoped. But for routing *inside* a 26-chapter book, the correct chapter had to beat 23 siblings
for one of 3 slots. Sized from the corpus (books hold 8–44 units, `k`≈10), so 50 effectively
disables the cap when the caller has already asked for depth in one document.

**Measured:** scoped routing 0.650 → 0.725 (40q). **Load-bearing claim: unscoped behaviour did not
move** — unscoped chapter recall 0.425 → 0.425, and 210q paper recall 0.9762 → 0.9762. The +0.075
scoped gain is *below* the noise floor in isolation; its value appears only alongside `paper_id`.

`_is_scoped()` deliberately excludes `categories` and the published-date range — those are
corpus-wide filters where T-DOC82's diversity argument still holds.

### `paper_id` on `SearchFilters` *(PR #205, awaiting sign-off)*

**What:** exposes per-document scoping. `paper_id` already existed on `VectorPayload`; the filter
simply was not surfaced.

**Measured:** chapter routing **0.713 → 0.939** (+0.226, ~1.8× the noise floor). 4 of 5 books gain
+0.130 to +0.478; the 5th was already at 0.957 and is flat, not regressed.

**The trap it nearly fell into:** at cap 3, per-book scoping and `doc_type="book"` score
*identically* (0.650 both) because both bottom out on the same 3-slot ceiling. An earlier
measurement saw exactly that and concluded "a `paper_id` filter unlocks nothing." **Decisions 2
and 3 each hide the other's value in isolation** — measured alone, either looks worthless.

### Safety fixes from the 2026-07-29 outage *(merged)*

`app/reindex_idf.py` now documents that it **must run fully detached**. Its three safety layers —
snapshot-first, point-count invariant, IDF post-check — all assume the process survives; none
covers parent-process death. And `VectorIndex.migrate_via_clone_and_swap()` adds a
clone → verify → swap path so a retrofit never leaves the live collection empty. `rebuild()` is
unchanged and still reachable.

---

## 3. Current system state

**Production:** `papers`, 372,741 points, sparse IDF on, status green.

**Chapter routing, 115 questions, k=10:**

| book | units | unfiltered | `doc_type="book"` | `paper_id` |
|---|---|---|---|---|
| Trustworthy OCE | 16 | 0.522 | 0.739 | — |
| CI in Python | 26 | 0.435 | 0.652 | — |
| Elements of CI | 8 | 0.217 | 0.522 | — |
| Discovery in Python | 7 | 0.435 | 0.696 | — |
| Econ/Social/Health | 44 | 0.826 | 0.957 | — |
| **overall** | 101 | **0.487** | **0.713** | **0.939** |

**All three surfaces, unfiltered, 115 questions, k=10** (`app/retrieval_eval.py`, 0 errors):

| surface | recall@10 | MRR@10 |
|---|---|---|
| paper-level | 0.7739 | 0.7192 |
| **passage-level** | **0.7304** | 0.6518 |
| chapter routing | 0.4870 | 0.3492 |

With `doc_type="book"`, paper-level reaches **1.000** — **the right book is always found.** Every
remaining miss is chapter selection *inside* a correctly-identified book, which is why
candidate-set fixes worked and unit-quality fixes did not.

**Passage recall (0.7304) still exceeds chapter routing (0.4870) by 0.243 at N=115** — the same
gap first seen at N=15 on 2 books, now confirmed at 115 questions across 5. Unfiltered, the raw
chunk index finds the right content far more often than chapter summaries find the right chapter.
`paper_id` scoping closes that gap (0.939 > 0.730) — but only once the caller already knows which
document to search, which is a different question from routing to one.

---

## 4. Every approach tried, and the test it failed

Each was measured against a criterion written **before** the result was known.

| # | approach | criterion it had to clear | measured | outcome |
|---|---|---|---|---|
| 1 | **Parser heading hierarchy** (M1) | produce a usable chapter tree | `" > "`-bearing blocks range **0** (2 books) to **4,242 of 6,316** (1 book); 530 "chapters" vs 535 chunks on one book | **abandoned** — parser hierarchy is unusable |
| 2 | **Explicit marker regex** (M2 / Strategy A) | split correctly where books use the convention | 43 marker matches on one book including `1. https://freakonometrics…`, `2. DiD%20Resources`; duplicate labels on two different units | **partly harmful, still shipped as fallback** |
| 3 | **PDF outline boundaries** (E1, Q1/Q2) | beat size-merge on chapter routing | **0.325 vs 0.425** matched; **0 of 4 books improved**; Discovery in Python 0.375 → **0.000** | **failed** — structural correctness was aesthetic |
| 4 | **Contextual-retrieval headers** (E2, T-DOC41) | beat passage recall 0.625 at N=40 | **−0.20 at full scale**; 6 questions went rank-1 → absent. Headers were book-level boilerplate (median 46 words), making a book's chunks mutually indistinguishable | **failed** — HOLD, not rejected |
| 5 | **Section-aware boost** (E4, T-DOC64) | `section_path` must support a type-based boost | **86% of book `section_path` values are unique strings**, not categories; 3.8% match IMRaD terms. Books use free-text headings | **premise invalid** — stopped before implementation |
| 6 | **Part→Chapter hierarchy** (E3, Q3/H1) | beat flat routing (0.325), and beat size-merge (0.425) | **0.250 vs 0.250 — exact tie.** And usable in **1 of 4** books: the other three have chapters *at* outline level 0, nothing coarser above | **failed twice over** — no migration, no contract change |
| 7 | **Self-Route agent escalation** (E5) | beat the best single-shot config already available | **0.575 vs 0.650** always-filtering, while costing a second retrieval call on 60% of questions | **failed** — always-filter wins |
| 8 | **Marker-regex repair** (4B, T-DOC87) | eliminate duplicate titles **without** regressing routing past the floor | duplicates **eliminated** (2→0, 6→0). But Econ/Social/Health **0.826 → 0.391 unfiltered / 0.957 → 0.609 scoped** — 2.8–3.5× past the floor | **boundary change does not ship**; the regex fix ships on correctness grounds (PR #204) |

### Rejected without being built, with reasons

| approach | why not |
|---|---|
| **RAPTOR** (recursive clustering + tree summarization) | Solves "no ground-truth structure exists." Four of five books ship a publisher outline. Expensive: an LLM call per cluster per tree level. |
| **GraphRAG** | Built for corpus-wide sensemaking, not targeted fact lookup. Every eval question here is a targeted lookup. LLM-heavy at index time. |
| **Late chunking** | Needs the embedder to expose pre-pool token embeddings, which TEI's standard `/embed` may not. Duplicates what contextual retrieval addresses more cheaply. |
| **Propositional / Dense-X chunking** | Targets passage recall — already the *stronger* surface (0.700 vs 0.425). Finer granularity does nothing for chapter routing. |
| **Docling / GROBID parser swap** | Parser is ADR-locked. Out of scope. |
| **Hierarchy in the title string** (`"Part I > Chapter 3"`) | Makes the routing label do double duty as a data structure, immediately after T-DOC85 was spent making those labels clean. |
| **Full-corpus re-embed** | Only 809 of 11,026 papers were affected by the chunk-quality bug and their blocks survived — re-chunk from blocks was ~14× cheaper. |

### The pattern

**Seven interventions tried to improve chapter routing by improving the chapter units. Every one
failed or regressed.** Every gain that did materialise came from the **candidate set** instead:

```
0.487  unfiltered
0.713  + doc_type filter        (+0.226)  ← exclude 11,021 irrelevant summaries
0.939  + paper_id scoping       (+0.226)  ← exclude other books
```

Experiment 3 stated it outright as an incidental measurement: routing **scoped to the correct book
scored 1.000 versus 0.250 globally**, on identical vectors and identical chapters. The chapters
were never the defect. The right units simply never reached the candidate set.

This also resolves the puzzle from the very first baseline — passage recall beating chapter
routing. Passage search draws on 361,614 chunks where a target book contributes hundreds; chapter
search draws on ~11,100 summaries where a book contributes 8 to 44. The chapter surface is thinner
against identical noise.

---

## 5. Measurement caveats — read before trusting any number above

**Econ/Social/Health's 0.826 / 0.957 is probably inflated, and it is 1 of 5 books in every
aggregate here.** Its 44 units include fragments as small as **57 words** (word-share
min/median/max 57 / 181 / 104,425). A gold passage often sits *inside* one, so the "chapter"
embedding is accidentally passage-sized and lexically close to the question. Repairing the split
to real chapter-scale units (median 6,619 words) dropped it to 0.391 / 0.609 — which is likely the
honest figure. **If so, the overall 0.487 / 0.713 are inflated too**, and a corpus with correct
splits everywhere would score lower.

**Five of the original 40 questions have ambiguous gold chapter titles** (QB-028/029/030/031/034)
— titles appearing twice in the same book. Scoring is title-string equality, so routing to the
*wrong* unit counts as a hit. Three of the five scored rank-1 hits. That puts a **±7.5-point band**
on the 40-question chapter figures. The 115-question set now guards against this mechanically:
`KNOWN_DUPLICATE_CHAPTER_TITLES` in `test_eval_book_questions_invariants.py` blocks new questions
from using ambiguous titles, and a cross-record check catches a title used at two different
chapter indexes.

**Discovery in Python contributes ~3 independent routing targets, not 23.** Nineteen of its 23
questions resolve to a single unit — itself a marker-regex artifact. That book is close to
unmeasurable for routing until its split is repaired, and repairing it regresses a different book
(§4 #8).

**The 210-question paper eval set cannot measure passage-level retrieval at all** — it carries
zero gold blocks. Every passage-level figure in this project comes from a 40-question fixture.

**N=115 was chosen from a power calculation**, not convenience: distinguishing an 18-point
chapter-routing swing at α=0.05 / power=0.80 needs ~114 questions. The prior 40 could catch a gross
regression or an obvious win, and could not adjudicate a close call — which is why several results
in §4 are stated as "within noise" rather than resolved.

---

## 6. Open follow-ups

| item | note |
|---|---|
| **Table of contents mis-classified as headings** | Discovery in Python's duplicate `Part 2`/`Part 3` labels trace to its own TOC being read as real headings — a distinct root cause from the marker-regex bug. Not fixed. |
| **Strategy-B title selection** | Produces junk titles like `"## Best lambda for Ridge regression: 0.2529632"` on Econ/Social/Health. Outside T-DOC87's scope. |
| **T-DOC87 boundary re-ingest** | Regex fix ships; the boundary change does not. Re-ingesting production with repaired boundaries would regress one book past the noise floor. |
| **Remove the unused outline splitter** | Reviewed 2026-08-29 — delete if still unused. Kept for now as documented negative-result code alongside its report. |
| **`reindex_idf` default** | `--use-clone-swap` is opt-in; the default remains `rebuild()`, which is the path that emptied production. Consider flipping. |
| **Chapter routing as a surface** | With `paper_id`, routing reaches 0.939 — but passage retrieval was always the stronger surface. Whether chapter summaries should remain a *routing* surface or become navigation-only metadata is still open. |
