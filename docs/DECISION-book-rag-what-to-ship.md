# What to ship from the book-RAG experiment programme

> **HISTORICAL** — superseded by docs/BOOK-INTEGRATION-CLOSEOUT.md + eval-reports. Current state: [PROJECT-STATUS.md](PROJECT-STATUS.md).

*2026-07-29. Decision document for the operator. Every number below was measured on the same
40-question / 5-book fixture at k=10, on collection `exp1_ctrl_sizemerge_idf` (372,741 points,
identical to production except sparse IDF is ON) unless stated otherwise.*

**Established noise floor: ~0.125 (12.5 points) at N=40**, measured empirically from control drift.
Deltas below it are not results. ~114 questions would be needed to resolve an 18-point swing.

---

## The headline

**Every planned experiment failed. The findings worth shipping were discovered while investigating
why.**

The programme spent four experiments tuning *chapter units* — re-cutting boundaries, re-embedding
their text, re-ranking them by section, adding hierarchy. Experiment 3 showed the units were never
the defect: chapter routing **scoped to the correct book scores 1.000** against 0.250 globally, on
the same vectors and the same questions. The right units were never reaching the candidate set.

This also explains the puzzle from the first baseline — passage recall (0.700) beating chapter
routing (0.425). Passage search draws on 361,614 chunks where the target book contributes hundreds;
chapter search draws on ~11,100 summaries where a book contributes 8–44.

### Three stacked ceilings, each hiding the next

Measured on `exp1_ctrl_sizemerge_idf`, 40 questions, k=10:

| cap | scope | chapter R@10 |
|---|---|---|
| 3 | none | **0.425** ← today |
| 10 | none | 0.450 |
| 3 | `doc_type="book"` | 0.650 |
| 50 | `doc_type="book"` | 0.725 |
| 3 | gold-book-scoped | 0.650 |
| **50** | **gold-book-scoped** | **0.900** |

| # | ceiling | mechanism | lifting it |
|---|---|---|---|
| 1 | global competition | ~11,021 paper summaries compete for 10 slots | **+0.225** |
| 2 | per-paper cap | `_MAX_HITS_PER_PAPER = 3` (T-DOC82) on `retrieve_papers()` | **+0.075** more |
| 3 | no per-book scoping | `SearchFilters` has no `paper_id` | **+0.175** more |
| — | reranker batch | `rag/reranker.py` `_MAX_BATCH_SIZE = 32`, silently truncates | unmeasured |

**Each ceiling hides the one below it.** At cap 3, `doc_type="book"` and gold-book scoping score
*identically* (0.650) — both bottom out on the same 3-slot limit. Only after raising the cap does
per-book scoping show its +0.175. An earlier partial reading of Experiment 5 concluded "a `paper_id`
filter unlocks nothing"; that was this artifact, and it is **wrong**. Measuring any one of these in
isolation understates it.

The 0.900 figure is itself a **lower bound**: the reranker truncated a 106-candidate batch to 32.

---

## Ship

### 1. `filters={"doc_type": "book"}` on chapter routing — **+0.225, zero cost**

| | chapter R@10 |
|---|---|
| no filter | 0.425 |
| `doc_type="book"` | **0.650** |

All 5 books improved, no regressions. 1.8× the noise floor.

**Already built and already documented.** `search_papers` accepts `SearchFilters`, and its own
docstring instructs callers to prefer `{"doc_type":"book"}` for conceptual/background questions.

**The uncomfortable corollary:** the eval harness has never passed filters. So the 0.425 baseline
measures an agent that ignores existing guidance, not the system's capability. This is a
usage/measurement gap, not a missing feature.

**Action:** make the harness measure both paths; strengthen the guidance so the filter is reliably
used. No code change required to get the gain.

### 2. Per-paper cap on the summary surface — **+0.075 further (below floor alone)**

`rag/retriever.py:59` `_MAX_HITS_PER_PAPER = 3` (T-DOC82) applies to `retrieve_papers()`. A book
can contribute at most 3 chapters to a 10-result response, so in a 26-chapter book the correct
chapter must beat 23 siblings for one of 3 slots.

| cap | filter | chapter R@10 |
|---|---|---|
| 3 | none | 0.425 |
| 10 | none | 0.450 |
| 3 | book | 0.650 |
| **10** | **book** | **0.725** |

Combined with the filter: **0.425 → 0.725 (+0.300)**, 2.4× the floor.

**Honest caveat:** the cap raise alone is +0.075, *below* the noise floor — suggestive, not proven
at N=40. Only the combined effect is established.

**Risk to weigh:** T-DOC82 added this cap deliberately, to stop one paper dominating a search across
11,026 documents. Raising it globally may degrade cross-document paper search. The defensible change
is to relax the cap **only when results are already scoped** (a `doc_type` or per-paper filter is
active), not unconditionally. That needs design, not a constant edit.

### 3. IDF reindex — **+0.075 paper AND passage recall — NEEDS OPERATOR APPROVAL**

Production `papers` has **no sparse IDF modifier** (`sparse: {}`); it was created before T-DOC27 and
`_ensure_collection` only sets the modifier at creation time. Every freshly-created collection gets
it automatically — which is how this was discovered (it silently confounded Experiment 1).

| surface | IDF off | IDF on | Δ |
|---|---|---|---|
| paper / passage recall | 0.675 / 0.625 | 0.750 / 0.700 | **+0.075** |
| chapter routing | 0.450 | 0.425 | −0.025 |

Net strongly positive: passage recall is the metric that carries answers.

`app/reindex_idf.py` (OG-27) exists for exactly this. Idempotent; snapshot-first (verifies a real
snapshot of that collection is on disk), point-count invariant, IDF post-check. No re-embed, no GPU.

**Why it is not done:** it drops and recreates the collection, holding every point in memory
between. A crash mid-run loses the collection. That is a destructive in-place operation on the live
corpus and needs explicit operator sign-off.

**Before running it:** validate the gain on the 210-question paper eval set against an IDF-enabled
clone. The +0.075 is measured on 40 book questions only.

---

## Do not ship

| intervention | result | verdict |
|---|---|---|
| **Outline chapter boundaries (E1, Q1/Q2)** | −0.100 matched; **0 of 4 books improved**; Discovery in Python collapsed 0.375 → 0.000 | Falsification criterion triggered. Size-merge (M3+M4) wins on measurement. |
| **Contextual-retrieval headers (E2, T-DOC41)** | −0.20 passage recall at full scale | Headers are book-level boilerplate (median 46 words), making a book's chunks mutually indistinguishable. T-DOC41 stays HOLD. |
| **Section-aware boost (E4, T-DOC64)** | Not built — premise invalid | 86% of book `section_path` values are **unique strings**, not types. Books use free-text headings, not IMRaD. May still hold for papers — separate question, different data. |
| **Hierarchy / H1 (E3, Q3)** | 0.250 vs 0.250 flat — exact tie | Fails both bars. And usable in **1 of 4** books: the other three have chapters *at* outline level 0, nothing coarser above. No migration, no `ChapterSummary` change. |
| **Marker-regex repair (T-DOC87, A3)** | Settled without running | Only justified if the outline split landed. It didn't. Close as superseded. |

---

## Open decisions for the operator

1. **Approve or decline the IDF reindex.** Destructive-in-place on the live collection; snapshot-
   first, point-count invariant, IDF post-check. Needs sign-off. Validate on the 210-question paper
   eval set first — the +0.075 is measured on 40 book questions only.
2. **Relax the per-paper cap when results are already scoped.** Design work, not a constant edit:
   T-DOC82 added the cap to stop one paper dominating a corpus-wide search, and that reason still
   holds unscoped. The defensible change is to relax it only when a `doc_type` or per-paper filter
   is active.
3. **Add `paper_id` to `SearchFilters`** — foundation-frozen contract change (`contracts/`,
   CODEOWNERS). **Worth +0.175 over `doc_type="book"`, but only once the cap is raised.** A real
   filter would push scoping into the vector store rather than post-hoc, so 0.900 is a lower bound
   on what it delivers. Decisions 2 and 3 should be taken together; either alone hides the other's
   value.
4. **The reranker truncates at 32 candidates** (`rag/reranker.py` `_MAX_BATCH_SIZE`, a TEI vendor
   limit). Every number above was measured through that truncation. Worth investigating whether
   batching multiple rerank calls beats truncating — not tested here.
5. **Eval-set size.** 40 questions cannot settle close calls; ~114 needed for an 18-point swing.
   The findings above clear the 0.125 floor comfortably; nothing else in the programme did.

## A known defect, unfixed

**16 of 101 chapter units carry a duplicate title** — 4 of 7 in Discovery in Python, 12 of 44 in
Econ/Social/Health, 0 elsewhere. An agent selecting by label cannot distinguish them, and the
harness would score a hit even when routing to the wrong unit. The outline split eliminated all 16
and **still lost on recall**, so it is not the remedy. Worth a targeted fix; cheaper than anything
tested here.

## Method note worth keeping

Two experiments produced confident results that did not survive checking, and in both cases the tell
was **a number that could not legitimately have moved**: E2 showed 1.000 in both arms (saturated
ceiling — the throwaway collection had 192× less competition than production); E1 showed paper and
passage recall shifting when only `summaries` changed (the IDF confound). Neither would have been
caught from the headline metric alone. Any clone-based A/B in this repo silently upgrades the
collection schema to current code — check `has_idf_modifier()` and point count on both arms before
trusting any delta.
