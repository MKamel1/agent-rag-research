# Books: chapter boundaries, hierarchy, and how we'll actually know it works

> **HISTORICAL** — superseded by docs/BOOK-INTEGRATION-CLOSEOUT.md. Current state: [PROJECT-STATUS.md](PROJECT-STATUS.md).

*2026-07-28. A plan for comparing approaches and for measuring them. Written after the five-book
re-ingest, which is the first real evidence we have.*

---

## Part 1 — where we actually are

### Chapter extraction: partly working, on weak foundations

Two heuristics in `rag/book_summarizer.py`, tried in order:

- **Strategy A** — a regex for `Chapter N` / `Part N` / `Appendix X` / `N. Title`.
- **Strategy B** — size-merge: accumulate flat heading groups until ~5,000 words.

Measured on the five books, 2026-07-28:

| book | units | strategy | verdict |
|---|---|---|---|
| Trustworthy OCE | 16 | B | **excellent** — every title a real section |
| CI in Python | 26 | B | good |
| Elements of CI | 8 | B | **partial** — several mid-content titles |
| Discovery in Python | 7 | **A** | **broken** — duplicate labels, far too coarse |
| Econ/Social/Health | 44 | **A** | **broken** — titles are numbered list items |

Two things this table hides:

1. **Strategy A actively mis-splits** (T-DOC87). Its `^\d+\.\s+\S` alternative matches ordinary
   numbered list items in body text, producing "chapters" like `1. https://freakonometrics…`,
   `2. DiD%20Resources`, `4. Verify GPU availability:`. And it produced **duplicate titles** —
   `Part 2: Causal Inference` labels two different units in the same book, so an agent selecting by
   label cannot tell them apart.
2. **Even Strategy B's good results are good labels on arbitrary slices.** A 5,000-word cut is not a
   chapter boundary. Trustworthy OCE's 16 titles are excellent; its 16 *boundaries* are word counts.

### Hierarchy: zero

```
summaries columns: summary_id, paper_id, text, title
```

No parent, no level, no ordering beyond the `ch<N>` suffix. A book is 8 or 44 peers — never
Part → Chapter → Section. And the parser's own hierarchy is unusable anyway; `" > "`-bearing blocks
range from **0** (CI in Python, Trustworthy OCE) to **4,242 of 6,316** (Econ/Social/Health).
`book_summarizer` discards what does exist, calling `_top_level()` to strip everything after the
first `" > "`.

### The thing we've been ignoring

Four of five books ship a **publisher-authored outline** inside the PDF:

| book | outline entries | levels |
|---|---|---|
| Econ/Social/Health | 378 | 3 |
| Discovery in Python | 350 | 3 |
| CI in Python | 223 | **4** |
| Elements of CI | 84 | 2 |
| Trustworthy OCE | **0** | — |

`CI in Python`'s top level is literally `Part I. Fundamentals`, `Part II. Adjusting for Bias`.
`Elements of CI`'s top level is its real chapter list. This is exact ground truth for **both**
boundaries and hierarchy — deterministic, no regex, no model — and `pypdfium2`, already a
dependency, reads it via `pdf.get_toc()`.

The complementarity is almost too convenient: **the one book with no outline is the one the
heuristics handle best.**

### Measurement: nothing

`app/retrieval_eval.py` contains no `doc_type` at all. **No one has ever measured whether book
chapter routing improves retrieval.** Every quality judgement so far — including every one in this
document above — is eyeballing titles.

---

## Part 2 — the approaches to compare

### For chapter boundaries

**A1 — PDF outline (primary).** Use `pdf.get_toc()` entries as boundaries and as the hierarchy.
Deterministic and exact where present. Open questions the test must answer: how to map outline
entries (which carry page indices) onto our `blocks`; how to handle front matter, since `Cover`,
`Copyright`, `Dedication` all appear at level 0; and which level to treat as "chapter" when a book
has 4 levels and another has 2.

**A2 — heuristic fallback (existing).** Strategy B's size-merge, for the outline-less case. Already
built and working; the change is that it stops being the primary path.

**A3 — repair Strategy A.** Fix the marker regex per T-DOC87. **My position: don't.** If A1 lands,
Strategy A's whole job is covered by a better mechanism, and repairing a heuristic we're about to
demote is wasted work. Worth stating explicitly so the ticket can be closed as superseded rather
than silently abandoned.

**A4 — LLM-proposed boundaries.** Ask a model where chapters begin. Listed for completeness and
rejected: we have deterministic ground truth in 4 of 5 cases, and this reintroduces exactly the
fabrication risk T-DOC82 removed.

### For hierarchy

**H1 — parent/level columns on `summaries`.** `parent_summary_id TEXT NULL`, `level INTEGER`. A
migration against the populated corpus — which is precisely what T-DOC81 just made possible, and
this is its first real consumer. Requires a `ChapterSummary` contract change (foundation-frozen).

**H2 — a separate `chapter_tree` table.** Keeps `summaries` untouched. More joins, more surface;
no obvious benefit over H1 given a chapter has exactly one parent.

**H3 — encode hierarchy in the title string** (`"Part I > Chapter 3"`). Zero schema change. Rejected:
it makes the routing label do double duty as a data structure, and we just spent T-DOC85 making
those labels clean.

**Recommendation: H1.** But note it is only worth doing *if* retrieval measurement shows hierarchy
helps — see Part 3. Building a schema change for an unmeasured benefit is how this codebase
accumulated the problems the last week was spent fixing.

---

## Part 3 — the testing plan

**This is the part that gates everything else.** Without it we would choose between A1 and A2 on
aesthetics.

### Step 1 — build the measurement instrument first

Extend `app/retrieval_eval.py` to handle `doc_type`, and build a **book eval set**: questions whose
answers live in known chapters of the five books, with the correct chapter recorded. Target ~40-60
questions spread across all five books, deliberately including both outline-bearing and
outline-less books.

Two metrics, measuring different things:

- **Chapter routing accuracy** — given a question, does `search_papers` return the chapter that
  actually contains the answer? This is what chapter summaries exist for.
- **Passage recall** — does `semantic_search` return the right span? This tells us whether chapter
  work affects retrieval at all, or only navigation.

**Baseline before changing anything.** Measure today's 7/44/26/16/8 split. Without a baseline, any
subsequent number is unfalsifiable.

### Step 2 — A/B the splitters on the same eval set

Re-split the five books under A1 (outline) and A2 (heuristic), holding everything else constant, and
measure both. `app/reembed_experiment.py` is the precedent for a matched A/B of this shape.

**What would make A1 the wrong choice**, stated up front so we can't rationalise afterwards: if
outline-based chapters score *no better* than size-merge on routing accuracy, then the outline's
correctness is aesthetic and A2 is simpler. That is a real possible outcome — a semantically correct
boundary is not automatically a better retrieval unit.

### Step 3 — measure hierarchy separately, and only then build it

Hierarchy (H1) should be evaluated as its own question: does a Part → Chapter structure improve
routing over a flat list of the same chapters? Test it by *simulating* the hierarchy in the eval
harness before committing to a migration and a contract change.

### Step 4 — the human gate stays

Automated metrics won't catch a fabricated summary or a nonsense label. The eyeball check from the
T-DOC82 rollout stays: chapter counts plausible, titles readable, summaries free of invented
numbers.

---

## Part 4 — sequencing

1. **Measurement instrument + baseline** (Step 1). Nothing else is decidable without it.
2. **A1 outline extraction**, behind the existing splitter interface so A/B is a config switch.
3. **A/B and decide** (Step 2). Close T-DOC87 as superseded if A1 wins.
4. **Hierarchy simulation** (Step 3); build H1 only if it earns it.
5. **Re-ingest the five books once**, under whatever won.

Sequencing note: T-DOC64 (section-aware retrieval — boost by `section_path` type) should ride along
with Step 1. It needs the same eval harness, and building the harness twice would be silly.

## Risks

- **The eval set is the whole game and it is hand-built.** ~50 questions written by us, over five
  books we chose. It can encode our assumptions. Mitigation: write the questions from the books'
  own contents before looking at any retrieval output.
- **Outline page indices → block mapping is unproven.** `get_toc()` gives page numbers; our blocks
  carry page anchors. The join should work but has never been exercised. Prove it on one book before
  committing to A1.
- **A1 helps 4 of 5 books.** The outline-less one still depends on heuristics, so A2 can't be
  deleted, and we carry two paths permanently.
- **Front matter at level 0** (`Cover`, `Copyright`, `Dedication`) needs handling that T-DOC85's
  scorer currently does by accident.

## Out of scope

- Re-summarizing the 11k papers. The paper path is unaffected.
- The contextual-header A/B (T-DOC41), except to note it would subsume any full re-embed.
