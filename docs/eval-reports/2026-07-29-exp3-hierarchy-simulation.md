# Hierarchy-as-routing simulation — Experiment 3 — 2026-07-29

Experiment 3 of `docs/PLAN-book-rag-experiments.md`: decides whether a Part → Chapter hierarchy
(H1: `parent_summary_id` + `level` on `summaries`) is worth building, **without building it**.
Simulates a two-step Part-then-Chapter routing strategy in memory, entirely read-only, against
Experiment 1's already-embedded chapter vectors in the throwaway `exp1_outline_chapters` Qdrant
collection. Persists nothing: no `summaries` writes, no migration, no `contracts/` change, no new
collection.

**Headline: H1 should not be built.** The one book this experiment could actually test hierarchy on
shows the simulated two-step routing tying flat routing on recall (0.250 either way) and losing to
size-merge (0.425 corpus-wide). The 3 other outline-bearing books structurally cannot participate at
all — their PDF outlines have no level coarser than the one Experiment 1 already used as "chapter",
so there is no Part to route through. Both pre-committed falsification bars are missed, and the
delta is nowhere near the ~0.125 noise floor this branch of experiments has already established.

Throwaway analysis script: `app/exp3_hierarchy_sim.py` (module docstring marks it as throwaway,
same convention `app/exp1_outline_split.py` uses for itself). Pure-logic test file:
`app/test_exp3_hierarchy_sim.py`. Full machine-readable output:
`2026-07-29-exp3-hierarchy-simulation.json`.

## Collection + IDF verification (per the task's own required check)

```
VectorIndex('localhost', 6333, 'exp1_outline_chapters', 2560).point_count()        -> 372753
VectorIndex('localhost', 6333, 'exp1_outline_chapters', 2560).has_idf_modifier()    -> True
```

Matches the brief exactly: 372,753 points, sparse IDF modifier on. Both arms of this experiment
score against this one collection — no comparison ever crosses a collection boundary.

## Which books could actually be simulated

Verified from real `pypdfium2.get_toc()` output (`app.exp3_hierarchy_sim.survey_books`), not
assumed from the earlier gate/Experiment-1 docs' prose:

| book (paper_id) | outline level histogram | chapter level (Exp 1's pick) | parent (Part) level | usable? |
|---|---|---|---|---|
| Causal Inference in Python (`f0929288d4f3`) | {0:12, 1:19, 2:95, 3:97} | 1 | **0** | **yes** |
| Elements of Causal Inference (`f6c64e1e8c7d`) | {0:18, 1:66} | 0 | none | no |
| Causal Inference and Discovery in Python (`dfe850b3281a`) | {0:29, 1:102, 2:219} | 0 | none | no |
| Causal Inference and ML in Econ/Social/Health (`54d6ca71dda9`) | {0:42, 1:156, 2:180} | 0 | none | no |

**Only 1 of the 4 outline-bearing books has a usable multi-level outline for this experiment.**
Level 0 is `pypdfium2.get_toc()`'s own outermost level (confirmed in the Experiment 1 gate doc, Q1)
— for the other 3 books, Experiment 1's own `pick_outline_level` rule already picked level 0 as
"chapter" (the level with the most `Chapter`/`Part`/`Appendix`-marker titles, or level 0 as
fallback), which means their own PDF outline has **nothing coarser to route through**. This is a
structural property of those 3 books' outlines, not a judgment call or a tuning choice: Discovery's
outline mixes "Chapter N" and "Part N" divider entries at the *same* level, and Elements/Econ-Social-
Health never nest a chapter under anything at all. Hierarchy, as this experiment defines it (Part
one level up from Chapter), literally cannot be constructed for these 3 books from their own outline
data. Only **Causal Inference in Python** (11 unique Part boundaries at level 0, 17 chapter units at
level 1) has the two-level structure the plan's mechanism requires.

This alone is a data point worth weighing in the H1 decision: even in the best case, a Part/level
schema migration would only ever activate its second level for 1 of 5 books in the current corpus
(the same "helps only some books" caveat the gate doc raised about the outline splitter itself).

## Arm (a) — flat: self-check against Experiment 1's own number

Reused `app.retrieval_eval.load_questions`/`run`/`build_report` **unmodified**, via the real
`Retriever.retrieve_papers()` pipeline (hybrid search → rerank → per-paper cap=3 → top-k), against
`exp1_outline_chapters` and a **read-only copy** of Experiment 1's own throwaway `papers.db`/`blobs`
(`/home/omar/ai-projects/rag-exp1/.exp1-work/` — Experiment 1's own scratch artifacts, git-ignored
and worktree-local; copied, never written to, the same "read a sibling worktree/checkout's files,
never write them" pattern `app/exp1_outline_split.py`'s own `PDF_DIR` already establishes for the
corpus PDFs). This was the script's own hard self-check, per the task: it raises and stops before
touching arm (b) if the number doesn't match.

**Result: chapter-routing recall@10 = 0.325, exactly matching Experiment 1's reported number.**
Per-book breakdown, recomputed from the run's own `questions[]` array grouped by `gold_paper_ids`
(not retyped by hand), also matches Experiment 1's own table digit for digit:

| book | n | recall@10 | MRR |
|---|---|---|---|
| Causal Inference in Python | 8 | 0.250 | 0.1375 |
| Elements of Causal Inference | 8 | 0.375 | 0.2812 |
| Causal Inference and Discovery in Python | 8 | 0.000 | 0.0000 |
| Causal Inference and ML in Econ/Social/Health | 8 | 0.500 | 0.3929 |
| Trustworthy OCE (control, no outline) | 8 | 0.500 | 0.3542 |
| **OVERALL** | **40** | **0.325** | **0.2332** |

The pipeline reproduced exactly — the rest of this run's numbers are trustworthy.

## Arm (b) — simulated hierarchical, for the one eligible book

Mechanism (Causal Inference in Python, `local:f0929288d4f3`, its 8 fixture questions only):

1. **Part-title embeddings, computed ad hoc, never persisted.** The 11 level-0 outline entries
   (`Cover`, `Copyright`, `Table of Contents`, `Preface`, `Part I. Fundamentals` … `Part V.
   Alternative Experimental Designs`, `Index`, `About the Author`) embedded once via `TeiEmbedder`
   — the plan's own "computed but never persisted" instruction; nothing is ever upserted into any
   Qdrant collection. `TeiEmbedder.embed()` acquires the shared `FileGpuLock` internally per call,
   which is what satisfied the task's "take the GPU lock for the handful of Part embeddings"
   instruction — no separate manual acquire was added or needed.
2. **Route to the single best-matching Part** by cosine similarity (`TeiEmbedder.embed()` vectors
   are L2-normalized, so a plain dot product is cosine similarity) between the question's own
   embedding and the 11 Part-title embeddings. A hard top-1 decision, per the plan's own wording
   ("route to THE top-level Part").
3. **Chapter-level score restricted to the routed Part's children only** — `VectorIndex.
   hybrid_search(qvec, qtext, kind="summary", k=5000)` against `exp1_outline_chapters` (the *same*
   persisted chapter vectors arm (a) scored against), filtered post-hoc to only the ids belonging to
   the routed Part, in their existing fused-score order, truncated to k=10. No cross-encoder rerank
   in this step — the plan's own cost estimate scopes this experiment to "a handful of additional
   embedding calls," not a second reranker pass, and each Part has only 1–4 children here, so a
   rerank pass is unlikely to change which one comes first.

Also computed, as a diagnostic control isolating *which* part of the mechanism does the work:
**book-scoped-flat** — the same raw `hybrid_search` + no-rerank scoring, but with *no* Part
restriction at all (all 17 of the book's own chapters are candidates). This isolates "removing
corpus-wide competition and the per-paper cap by scoping to one book" from "further scoping to one
Part within that book" — two different effects the plan's two-step design bundles together.

### Results (n=8, Causal Inference in Python only)

| arm | recall@10 | MRR@10 |
|---|---|---|
| arm (a) flat, corpus-wide, this book's 8 questions | 0.250 | 0.1375 |
| **arm (b) simulated hierarchical (Part → Chapter)** | **0.250** | **0.250** |
| book-scoped-flat control (no Part step, book-only) | **1.000** | 0.7812 |

**Part-routing accuracy: 2/8 (0.250, MRR 0.250) — the entire hierarchical-arm result.** Every
question that routed to the correct Part then hit its chapter at rank 1 (both Parts had only 2–3
children, trivially within k=10); every question that routed to the wrong Part missed entirely,
because the correct chapter was never even a candidate after the Part filter. With this book's
granularity (11 Parts, 1–4 children each), **hierarchical chapter-level recall reduces almost
exactly to Part-routing accuracy** — the second step contributes essentially nothing beyond "did
step 1 pick right," which is the opposite of what a routing hierarchy is supposed to buy (a
second, finer decision that recovers cases the first, coarser one gets wrong).

4 of the 6 misses routed to the same wrong Part (`Part III. Effect Heterogeneity and
Personalization`) regardless of which chapter the question was actually about — a naive
title-only Part embedding does not obviously disambiguate five methodologically similar "Part"
labels from eleven candidates (5 of which — Cover/Copyright/TOC/Index/About the Author — are
front/back matter with zero content chapters at all, permanently un-routable to but still
competing as targets).

**The book-scoped-flat control is the real result worth noting, but it is not evidence for
hierarchy.** Restricting search to just this book's own 17 chapters (removing the corpus-wide
per-paper cap of 3 and cross-book competition — *without* any Part-routing step) gets every
question right. That means the bottleneck arm (a) actually measures is **corpus-wide competition**,
not "chapters need a coarser index to route through." Note this control is oracle-conditioned on
already knowing the right book — arm (a)'s own paper-level (book-identification) recall for this
book is only 4/8, so "just scope to the right book" is not free in production either; it is a
different, already-existing problem (`_MAX_HITS_PER_PAPER` / corpus-wide paper-level routing),
not the one H1 would address.

## Comparison against both pre-committed bars

**1. vs. flat outline routing (0.325, the plan's originally stated criterion).** The only
apples-to-apples comparison available is same-book, same-8-questions: arm (a) flat = 0.250,
arm (b) hierarchical = 0.250. **Delta: 0.000.** Nowhere close to beating flat by more than the
~0.125 noise floor established across this branch of experiments (Experiment 1's own OCE-control
finding). **Criterion not met.**

**2. vs. size-merge (0.425, the actual shipping incumbent).** Size-merge's own number for this same
book (Experiment 1's table) is also 0.250. Hierarchical arm (b) ties it too: **delta 0.000.**
**Criterion not met, by a wider margin than criterion 1 in absolute terms (0.425 vs 0.250 corpus-
wide, though the book-level comparison is the fairer one here).**

**Corpus-wide effect, for completeness:** Causal Inference in Python contributes exactly 2 of its 8
chapter-level hits in *both* arm (a) and arm (b) — different specific questions, same count. Since
this is the only book hierarchy could apply to, substituting the hierarchical routing outcome for
this one book into the full 40-question set leaves the **overall** number bit-for-bit **0.325**,
identical to arm (a) and still 0.100 below size-merge's 0.425. Simulated hierarchy changes nothing
measurable at the corpus level, because it only had one book to act on and tied that book's own
result.

**Neither delta clears the pre-committed ~0.125 noise floor.** Both are 0.000.

## The granularity-correlation hypothesis — examined, not concluded

The task asked whether finer splits hurting routing (Experiment 1's clearest signal: Discovery in
Python's 7→24 unit jump collapsing its recall to 0.000) predicts where hierarchy — a *coarsening*
strategy — should help most. **This cannot be tested as a correlation here**: only 1 of the 4
outline-bearing books has a usable hierarchy at all, so there is exactly one (unit_count,
hierarchy_delta) data point (Causal Inference in Python: 17 units, Experiment 1 delta = +0.000,
hierarchical-vs-flat delta = +0.000). A correlation needs at least a handful of independent points
to mean anything; one point is not evidence for or against the hypothesis, only a single anecdote
that happens to be flat on both axes. The hypothesis remains genuinely untested by this experiment,
not refuted — reported as such, not stretched into a conclusion the data can't support.

## Verdict against the pre-committed falsification criterion

**Falsification criterion (task, restated verbatim):** *"if simulated hierarchical routing does not
beat flat outline routing by more than the ~0.125 noise floor, do not build H1 — no
`parent_summary_id`, no `level`, no migration, no `ChapterSummary` contract change. And if it beats
flat outline but not size-merge (0.425), H1 still does not ship."*

**Triggered, on the first and more permissive bar alone.** Simulated hierarchical routing did not
beat flat outline routing at all (0.000 delta, both recall and against a 0.125 floor) for the one
book it could be tested on; the question of whether it separately beats size-merge is moot, since
it did not even clear the first, easier bar. It also does not beat size-merge (0.250 vs 0.250 on
this book, 0.325 vs 0.425 corpus-wide) — so even a more permissive reading that let the first bar
slide would still fail on the second, harder bar. This is not a "close call, underpowered" result
in the sense the task warns against over-reading a marginal number: the delta isn't small-and-
ambiguous, it's exactly zero, on a book where the ALTERNATIVE (book-scoped-flat, no hierarchy)
control scored a perfect 1.0 — hierarchy is not merely "not proven," the data available here
actively points at something *other* than hierarchy (corpus-wide competition scope) being the real
lever.

**Should H1 ever be built? No — not on this evidence.** No `migrations/` change, no `contracts/`
`ChapterSummary` change, no `parent_summary_id`/`level` field. Beyond the falsification criterion
itself: even in the best case this experiment could construct, H1's second level would only ever
activate for 1 of the corpus's 5 books (structural, not incidental — see the level-structure
survey), and the mechanism that actually recovered a real signal here (book-scoped-flat's 1.0) is
"remove corpus-wide competition when the target book is already known" — a *retrieval-scoping*
question, not a *schema* question, and not what H1 was proposed to fix.

## On power (per the task's own instruction, not glossed over)

N=8 for the one book hierarchy could apply to (N=40/4 books per the plan's original design; N=8/1
book once 3 of 4 turned out ineligible) cannot resolve small effects — even less power than the
plan's own N=40/4-book estimate assumed. The measured delta here (0.000) is not a "small effect
lost in noise" story, though: it's an exact tie on the primary metric across every one of this
book's 8 questions considered as a set, not a marginal single-question swing. Low power widens the
plausible range around a genuinely small true effect; it does not manufacture a tie out of what
would otherwise be a real difference — same reasoning Experiment 1's own report applied when 0 of 4
books improved.

## Artifacts

- Throwaway script: `app/exp3_hierarchy_sim.py` (module docstring marks it as throwaway).
- Pure-logic tests: `app/test_exp3_hierarchy_sim.py` (12 tests, zero GPU/corpus/network).
- Full machine-readable output: `2026-07-29-exp3-hierarchy-simulation.json`.
- Nothing persisted: `exp1_outline_chapters` collection unchanged (still 372,753 points), no
  `summaries` writes, no migration, no `contracts/` change, no new collection. The only new
  artifact on disk is this worktree's own `.exp3-work/` scratch copy of Experiment 1's throwaway
  `papers.db`/`blobs` (git-ignored, not part of this diff).
