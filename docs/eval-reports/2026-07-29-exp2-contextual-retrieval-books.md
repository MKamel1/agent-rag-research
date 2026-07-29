# Experiment 2 — Contextual Retrieval, book-scoped (T-DOC41 revival) — 2026-07-29

`docs/PLAN-book-rag-experiments.md` §"Experiment 2". A/B re-embed of the 5 books' 1,939 chunks
with `app/reembed_experiment.py` (`--no-headers` vs `--with-headers`, into throwaway collections
`exp2_books_nohdr` / `exp2_books_hdr`), scored by `app/retrieval_eval.py` against the 40-question
`fixtures/eval/eval_book_questions.json` set from `origin/exp0-5book-eval-baseline`.

Full per-question detail: `2026-07-29-exp2-contextual-retrieval-books-nohdr.json`,
`2026-07-29-exp2-contextual-retrieval-books-hdr.json`. Combined summary + verification:
`2026-07-29-exp2-contextual-retrieval-books.json` (this report's machine-readable twin).

## Headline result

| arm | passage recall@10 | passage MRR | paper recall@10 | paper MRR | chapter recall@10 | chapter MRR | n_errors |
|---|---|---|---|---|---|---|---|
| baseline, no headers (`exp2_books_nohdr`) | **1.000** | 0.9375 | 1.000 | 0.9875 | 0.000 | 0.000 | 0 |
| headered (`exp2_books_hdr`) | **1.000** | 0.9375 | 1.000 | 0.9875 | 0.000 | 0.000 | 0 |
| **delta** | **0.000** | **0.000** | 0.000 | 0.000 | 0.000 (n/a, see below) | 0.000 (n/a) | — |

**The delta is an exact zero, not a small or noisy number.** A per-question diff of
`(paper_rank, passage_rank, chapter_rank)` across all 40 questions found **0 of 40 changed** —
this isn't an aggregate that happens to cancel out, every single question retrieved the identical
ranked results in both arms.

## Verdict against the pre-committed falsification criterion

Per the plan (restated, not softened): *"if headered passage recall is not measurably better than
baseline at N=40, treat this exactly as T-DOC41 already is — HOLD, not rejected, and do not spend
further GPU budget scaling it to the full corpus."*

Headered passage recall (1.000) is not measurably better than baseline (1.000) — the delta is
0.000. **Verdict: HOLD, not rejected**, same status T-DOC41's paper-scale result already carries.
This is **not** "trending positive" or inside a noise band that could go either way on a re-roll —
it is an exact null at the per-question level. Do not recommend spending further GPU budget
scaling contextual headers to the full corpus on the strength of this result.

## A caveat that weakens this as evidence, not just a footnote

**Both arms hit a 1.000 passage-recall ceiling.** The plan's own "number to beat" (0.625 recall /
0.596 MRR, `2026-07-29-book-retrieval-baseline-5book.md`) was measured against the **production**
`papers` collection — ~11,026 documents competing for every query's top-10. This experiment's two
throwaway collections, per the plan's own instruction to restrict `reembed_experiment.py` to the 5
book `paper_ids`, contain **only** the 1,939 chunks from those 5 books — nothing else competes.
That's a fundamentally easier retrieval task, and both arms saturate at recall=1.000 as a result.

**Consequence:** the 0.625 production number and this experiment's 1.000 numbers are not on the
same scale and must not be read as "headers took recall from 0.625 to 1.000" — that would be
comparing two different retrieval tasks. The only valid comparison this experiment supports is the
within-experiment nohdr-vs-hdr delta on the *same* restricted collection, which is 0.000.

**And that ceiling itself is a problem for the measurement, not just a scale mismatch:** with the
baseline arm already at 1.000, there is zero headroom for a real header effect to show up as a
recall improvement in this collection scope, regardless of whether contextual headers help
retrieval in principle. This run cannot distinguish "headers don't help" from "headers can't show
up because baseline is already saturated." A future book-only eval that wants to actually test this
should score against a harder candidate pool (e.g. the full production-scale collection, filtered
to book questions) rather than a books-only throwaway collection.

## Matched-set verification

The whole experiment depends on both arms embedding the *same* chunk ids — only the text handed to
the embedder should differ. Verified explicitly, not just by point count:

- `exp2_books_nohdr`: 1,939 points. `exp2_books_hdr`: 1,939 points.
- Full point-id sets pulled via Qdrant's `/points/scroll` (not just `points_count`) — **sets are
  exactly equal**: 0 ids in nohdr-not-hdr, 0 ids in hdr-not-nohdr.
- Qdrant point ids are `uuid5(fixed_namespace, chunk_id)` (`rag/vector_index.py`'s `_point_id`) —
  deterministic, so id-set equality implies chunk_id-set equality, not just a coincidental count
  match.
- **Verdict: PASS.** The matched-set property holds; the delta above (0.000) is a valid measurement,
  not an artifact of a corpus-size mismatch between arms.

## Chapter-routing tripwire

Per the plan: Experiment 2 doesn't touch `ChapterSummary`, so chapter-routing numbers must not move
between arms. Observed: **0.000/0.000 recall/MRR in both arms, identically** — 0 questions'
`chapter_rank` differ between arms (already covered by the per-question diff above). The tripwire
is **clear** in the sense that matters (no differential movement), but the *absolute* 0.000 in both
arms needs its own explanation so it isn't mistaken for a chapter-routing regression:
`app/reembed_experiment.py` only upserts `kind="chunk"` points; it never writes chapter-summary
vectors (`{paper_id}:summary:ch{n}` ids), which `rag/retriever.py`'s `retrieve_papers()` requires to
score a chapter hit at all. The throwaway collections structurally cannot support chapter routing —
this is a property of the experiment's scope (only chunk vectors were re-embedded, as the plan
specifies), not something the header technique broke. Chapter routing was not exercised, in either
direction, by this experiment.

## Headers generated

1,939 of 1,939 chunks got a generated header (0 skipped, 0 `PermanentError` failures) —
`ContextualHeaderGenerator` via `qwen3:14b`, `think=false`. Sample (`local:14b7e283bdcd:c0`):
*"This book offers a comprehensive guide to conducting reliable online controlled experiments,
particularly A/B testing, drawing on extensive industry experience. This passage introduces the
book, outli[ne...]"* — headers written to a local scratch path (`/tmp/exp2_headers_out.json`, not
committed — a generated artifact, not a deliverable), referenced here for provenance only.

## Runtime — actual vs. estimated

| stage | actual wall clock |
|---|---|
| Worktree setup + read-only paper-id verification | ~2 min |
| Baseline re-embed (`--no-headers`, 1,939 chunks, embed-only) | ~2–3 min |
| Headered re-embed (`--with-headers`, 1,939 sequential `qwen3:14b` calls + one batched embed) | **37m39s** (01:59:04–02:36:43 PDT) |
| Eval scoring, each arm (40 queries) | ~1–2 min |
| **Total GPU-heavy wall clock** | **~45 minutes** |

The task's operator-revised estimate was **6–18 GPU-hours**. Actual was **~45 minutes** — roughly
10–20x faster than even the low end. The gap: header calls ran at ~1.1s/chunk (`think=false` plus a
tight `num_predict` cap keeps each call short), not the multi-second-per-call the estimate
implicitly assumed. Reported honestly in both directions — this is not a scope reduction, it's the
real measured rate.

## Infrastructure incident (reported, not hidden)

Mid-run, the concurrently-working sibling agent's activity in the main checkout triggered a
graceful shutdown (`docker`, exit code 0, clean signal — not a crash) of the **system-wide**
`rag-tei-embed`/`rag-tei-reranker` containers, which are not scoped to any one worktree. This
happened while the headered re-embed was still generating headers via Ollama (a separate service,
unaffected throughout). Caught via a failed `/health` check; both containers were restarted before
the deferred `embed()` call at the end of the headered run needed them. No data loss — the nohdr
collection was independently confirmed to still hold 1939/1939 points throughout.

Separately: a first attempt at scoring the nohdr arm was started while the headered re-embed was
still mid-flight (contending for the same `FileGpuLock`) and came back with **4/40 questions
GPU-lock-timeout errors** (`gpu lock ... not acquired within 300.0s`). That report was **discarded,
not reported as a result** — both arms were rescored cleanly (0 errors each) once the GPU was idle.
The headline numbers above are from the clean, 0-error rescore.

## Corpus and production safety

- `papers.db`: 0 writes (`DocumentStore.get()`/`iter_papers()` only, verified by inspection of
  `app/reembed_experiment.py`, unmodified).
- Production `papers` Qdrant collection: never targeted — `--collection` was `exp2_books_nohdr` /
  `exp2_books_hdr` throughout; `reembed_experiment.py`'s own production-collection guard was never
  weakened.
- Throwaway collections **left in place** (not deleted) for later re-verification: `exp2_books_nohdr`,
  `exp2_books_hdr`.
- GPU lock: `rag.gpu_lock.FileGpuLock` at `/home/omar/ai-projects/research-system-rag/.gpu.lock`
  (shared absolute path across worktrees), used by both re-embed arms and both eval-scoring runs.

## Recommendation

Do not spend further GPU budget scaling contextual headers to the full corpus based on this result
— the falsification criterion is triggered (HOLD, not rejected). If Experiment 2 is revisited, fix
the ceiling-effect scope problem first: score against a candidate pool that isn't already saturated
for the baseline arm (e.g., the production-scale collection filtered to book questions, or a harder
question set) before drawing any conclusion about whether contextual headers help retrieval.
