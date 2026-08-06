# Books and chunk quality — the problem, what we tried, what's queued

> **HISTORICAL** — superseded by docs/BOOK-INTEGRATION-CLOSEOUT.md. Current state: [PROJECT-STATUS.md](PROJECT-STATUS.md).

*Living document, started 2026-07-28. A methods log, not a plan — the plan is
`DESIGN-book-chapters-and-hierarchy.md`. This records what was attempted, what it cost, what it
produced, and what was rejected and why, so approaches aren't silently re-tried.*

---

## The problem we are actually trying to solve

The system is a grounded RAG cache over causal-methods literature. Papers work. **Books were added
and are not finished.** Three distinct problems, often conflated:

**P1 — A book is too large to summarize in one pass.** A paper fits one `summarize()` call; a book
is 10-50× that. So a book must be cut into units, each summarized, then combined. *What the unit
should be* is the open question.

**P2 — Those units are also the routing surface.** `search_papers` returns chapter summaries so an
agent can choose where to read. The unit therefore has to be a *useful thing to be offered*, not
just a size that fits in a context window. A 5,000-word slice can satisfy P1 perfectly and still be
useless for P2.

**P3 — A book has structure a paper doesn't.** Part → Chapter → Section. Nothing in the system
represents this. `summaries` has no parent and no level, so a book is a flat list of 8 or 44 peers.

Underneath all three sits a quieter problem:

**P0 — We could not tell whether any of it worked.** Until 2026-07-28 there was no measurement of
book retrieval at all. Every judgement was eyeballing chapter titles.

---

## What we tried

### M1 — Split by parser heading hierarchy *(shipped, then found inadequate)*

Group blocks by top-level `section_path`, on the assumption the parser emits a real heading tree.

**Outcome: failed on contact with real books.** Measured: an arXiv paper had 113 blocks containing
`" > "`; a 2,520-block book had **zero**. So `_top_level` was an identity function and every heading
became its own "chapter" — 530 chapters against 535 chunks, with titles like `Contributors`,
`About the author`, `Italic`.

Parser hierarchy is wildly inconsistent across books: `" > "`-bearing blocks range from **0** (CI in
Python, Trustworthy OCE) to **4,242 of 6,316** (Econ/Social/Health). It cannot be relied on.

### M2 — Explicit chapter markers, regex *(shipped, partly harmful)*

Match `Chapter N` / `Part N` / `Appendix X` / `N. Title`, with plausibility guards (3-60 units, no
unit >50% of words).

**Outcome: works when a book uses those conventions; actively mis-splits when it doesn't.** The
`^\d+\.\s+\S` alternative matches ordinary numbered *list items* in body text. Measured: one book
produced 43 marker matches including `1. https://freakonometrics.hypotheses.org/52776`,
`2. DiD%20Resources`, `4. Verify GPU availability:`. Another produced 7 units for a whole book with
**duplicate titles** — `Part 2: Causal Inference` labelling two different units.

The plausibility guards don't catch it: 43 units sits comfortably inside the 3-60 band. They were
designed to catch the opposite failure (one stray marker producing two lopsided units).

Filed as T-DOC87. **Not repaired** — see M5.

### M3 — Size-merge at ~5,000 words *(shipped, current default)*

Accumulate consecutive heading groups until a word target, independent of heading text.

**Outcome: the reliable general path, and the honest limit is worth stating.** It produces
plausible unit counts (16 / 26 / 8 on three books) and, with M4, good labels. But a word count is
not a chapter boundary. **Good titles on arbitrary slices** is the accurate description.

### M4 — Score headings instead of taking the first *(shipped)*

Rank all ~12 headings merged into a unit by a structural score; take the best.

**Outcome: worked.** Replaced `Assign`, `See Also`, `F`, `\* and : Operators` with real section
names. Deliberately structural — no word blocklist, because heading names vary per publisher and
such a list is endless.

Residual limit: where *every* heading in a window is mid-content, the title is too
(`{probabilistically/interventionally/counterfactually} equivalent`).

### M5 — LLM-written title fallback *(shipped)*

When no heading in a unit scores above the floor, have the model write one from the chapter's own
already-grounded summary.

**Outcome: works, and fires rarely** — on the measured books, only on the front-matter unit.
Constrained to extractive wording and fed a summary rather than raw text, because the summary was
already produced under an anti-fabrication prompt.

### M6 — Book-specific summarization prompts *(shipped)*

The paper prompt asked for "effect size" and "dataset or sample size". Asked those of a textbook,
the model **invented them** — a stored summary claimed *"a novel hybrid method… 15-20% reduction in
mean squared error… over 10 million observations from a financial services company"*, none of which
existed in the book.

**Outcome: fixed.** Separate `book` and `book_overview` prompts with explicit grounding constraints.
Verified on re-ingest: summaries now describe the actual books, no invented numbers.

### M7 — Chunk-text quality *(shipped; two bugs, both found late)*

Not book-specific, but it feeds every embedding and therefore every measurement.

Stored chunk text is `title\nsection_path\n\n<body>`, and the body's first block was usually that
same heading — duplicated, wasting embedded tokens. Fixed in the chunker; **58.49% → 0.01%**.

The 0.01% residue took two attempts and produced the session's main methodological lesson:

- **Mechanism A (9 of 36 papers):** a heading-only sub-group becomes the *next* sub-chunk's borrowed
  `overlap` and opens `body` unchecked. Fixed as T-DOC93.
- **Mechanism B (27 of 36 papers):** two adjacent blocks both byte-equal to the `section_path`; the
  first is stripped, the second is in `group[1:]` and never checked. Fixed as T-DOC95.

Mechanism B was **proposed first and wrongly dismissed** — tested against a paper that happened to
exhibit mechanism A, found absent, declared disproved. A counter-example disproves a *universal*
claim, not a partial one. This is why `CONVENTIONS.md §14` exists.

### M8 — Measurement *(shipped 2026-07-28, first ever)*

Extended `app/retrieval_eval.py` for `doc_type`; built a 15-question seed eval set across one
outline-bearing and one outline-less book, with questions written from book content **before** any
retrieval was run.

**Baseline, k=10:**

| metric | overall | Trustworthy OCE *(no outline)* | CI in Python *(223-entry outline)* |
|---|---|---|---|
| paper recall@10 | 0.667 | 0.750 | 0.571 |
| passage recall@10 | 0.600 | 0.625 | 0.571 |
| **chapter routing recall@10** | **0.467** | 0.625 | **0.286** |

Two findings already: **chapter routing is the weakest metric** — the thing 101 chapter summaries
exist to serve performs worst; and **passage recall exceeds chapter routing** (0.600 vs 0.467),
meaning the raw chunk index finds the right content more often than chapter summaries find the
right chapter. That gap would have been invisible had the two been collapsed into one number.

---

## What's queued

### Q1 — PDF outline as the chapter boundary *(next)*

Four of five books ship a publisher-authored outline: 84-378 entries, 2-4 levels. `CI in Python`'s
top level is literally `Part I. Fundamentals` / `Part II. Adjusting for Bias`. `pypdfium2` already
reads it via `pdf.get_toc()`.

Exact ground truth for **both** P1/P2 boundaries and P3 hierarchy, with no heuristic and no model.
The one book *without* an outline is the one M3+M4 handle best, so outline-first with heuristic
fallback covers all five.

**Unproven and must be proven first:** outline entries carry page indices; our blocks carry page
anchors. That join has never been exercised. Prove it on one book before committing.

### Q2 — A/B Q1 against M3 on the M8 harness

Same eval set, same corpus, only the splitter differs. **The number to beat: chapter routing
0.467 overall, 0.286 on the outline-bearing book.**

Stated in advance so it can't be rationalised later: **if outline-based chapters don't beat
size-merge on routing accuracy, their correctness is aesthetic and M3 wins.** A semantically correct
boundary is not automatically a better retrieval unit.

### Q3 — Hierarchy (P3), gated on Q2

`parent_summary_id` + `level` on `summaries`. Needs a migration against the populated corpus
(possible now — T-DOC81) and a `ChapterSummary` contract change (foundation-frozen).

**Simulate it in the eval harness before building it.** Building a schema change for an unmeasured
benefit is how this codebase accumulated most of what the last week was spent fixing.

### Q4 — Section-aware retrieval (T-DOC64)

Boost/filter by `section_path` type — favour Method/Results over Introduction. Marked highest-value
for the owner's actual use. **Should ride along with Q2**, since it needs the same harness.

---

## Rejected, with reasons

| approach | why not |
|---|---|
| **Repair M2's marker regex** (T-DOC87) | If Q1 lands, M2's job is covered by a better mechanism. Repairing a heuristic we're about to demote is wasted work. Close as superseded, not abandoned. |
| **LLM-proposed chapter boundaries** | We have deterministic ground truth in 4 of 5 cases, and it reintroduces exactly the fabrication risk M6 removed. |
| **Front-matter blocklist** | Heading names vary per publisher; the list is endless. Structural scoring (M4) instead. |
| **Hierarchy encoded in the title string** (`"Part I > Chapter 3"`) | Makes the routing label do double duty as a data structure, right after M4 was spent making those labels clean. |
| **Full-corpus re-embed to fix M7** | Measured: only 809 of 11,026 papers were affected, and their blocks survived — re-chunk from blocks, ~14× cheaper. Only justified if something else forces a full re-embed. |

---

## Open questions

- Does chapter-level routing earn its cost at all? M8 says it currently underperforms passage
  retrieval. If Q1 doesn't move it, the honest question is whether chapter summaries should remain a
  routing surface or become navigation-only metadata.
- The eval set is hand-built (~15 questions, expanding to 40-60) over five books we chose. It can
  encode our assumptions. Mitigation so far: questions written from book content before seeing any
  retrieval output.
- Front matter (`Cover`, `Copyright`, `Dedication` all at outline level 0) needs deliberate handling
  under Q1; M4 currently handles it by accident.

---

## External research

2026-07-28: `docs/RESEARCH-book-rag-established-methods.md` surveys established research and
shipped RAG systems (RAPTOR, GraphRAG, contextual retrieval, late chunking, propositional
chunking, multi-view indexing, agentic-retrieval literature, and more) against P0–P3 above, with
a ranked verdict per method and full verified citations. `docs/PLAN-book-rag-experiments.md` turns
the recommended methods into a concrete, falsifiable experiment plan across all five books,
building on Q1–Q4 and reusing the existing `app/retrieval_eval.py` harness. Two findings worth
surfacing here: hybrid search + reranking (an obvious "try this" from most RAG literature) are
already active in `rag/retriever.py` and already reflected in the M8 baseline, and the closest
prior art to "prepend context before embedding" isn't external — it's this repo's own T-DOC41
spike (HOLD, inconclusive at paper scale, but cheap to re-test at book scale).
