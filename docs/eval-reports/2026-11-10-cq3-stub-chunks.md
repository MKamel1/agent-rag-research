# CQ-3: heading-only "stub" chunks -- instrument + reversible retrieval-time filter

Status: the A/B section below was PRE-REGISTERED in the stub commit (de520e4), before any measurement;
no GPU was available. Everything after it describes the implementation and was added later.

## Problem

7-10% of chunks in every corpus are heading-only: text is `title\nsection_path\n\n` with an empty
or near-empty body (main 36,364 / 399,676; standards 2,483 / 35,714, of which 400 are bare clause
numbers such as "3.159"; see `scripts/chunk_quality_census.py`). They are embedded and indexed and so
can occupy result slots while carrying no content. Whether they actually do is UNMEASURED.

## Pre-registered A/B

Arms: baseline (`drop_stub_chunks=False`) vs `drop_stub_chunks=True`. Same config, same collection,
same `k`, same `rerank_depth` otherwise. Fixtures of record: standards GT (standards corpus);
main-corpus passage GT (`fixtures/eval/eval_ground_truth.json`) and books GT
(`fixtures/eval/eval_book_questions.json`).

Definitions (fixed now):
- stub chunk: `len(body_of(text)) < _MIN_BODY_CHARS` (40), the single definition in `rag/retriever.py`.
- stub-at-rank-1 share: fraction of non-errored questions of a fixture whose baseline rank-1
  `retrieved_block_ids[0]` is the anchor block of a stub chunk (anchors from `scripts/list_stub_chunks.py`).
- strata: the report's `by_doc_type` and `by_question_type` groups.

ADOPT (turn the filter on by default, via the sign-off rider) only if ALL hold:
1. stub-at-rank-1 share at baseline > 0 on at least one fixture; AND
2. no stratum's paper Recall@10 or member-passage hit@10 drops by more than one question; AND
3. at least one of passage P@1 / hit@10 improves on at least one fixture.
Otherwise REJECT and leave the default off. No post-hoc metric or threshold changes.

Ceiling arithmetic. Removing a stub from a ranked list can only move every real chunk below it up
one place. So per question: P@1 can gain only if a stub is at rank 1 (gain <= s1 = stub-at-rank-1
share); hit@10 can gain only if gold sits at ranks 11..10+j where j = stubs in the baseline top 10
(gain <= q10 = share of questions with >= 1 stub in the top 10, and only for the subset whose gold
is within j places of the cut). Net of rerank effects the filter also hands the reranker a pool
with up to ~stub-share fewer wasted slots, refilled from deeper hybrid hits, so small
second-order movement is possible; that is why criterion 2 caps regressions rather than demanding
zero.  `list_stub_chunks.py --report` prints s1, the top-k stub share, and q10.

## Alternatives considered and rejected for now
- Fix the chunker to fold a heading into its first child. Correct at the root, but it changes chunk
  boundaries, renumbers chunk ids, forces a full GPU re-embed, and several `rag/test_chunker.py`
  tests deliberately pin heading-only chunks.
- Delete stub points from the live index. Irreversible without a snapshot. The index-side A/B is
  instead done on a CLONED collection from `list_stub_chunks.py`'s id list (later ticket).

## Design: where chunk text is loaded, where a stub is dropped

`Retriever.retrieve()` (`rag/retriever.py`): `_hybrid_hits(query, filters, pool, kind="chunk")` returns
`Hit`s carrying only id + score (no text). The text is first loaded in the per-hit loop
`self._document_store.get_chunk(hit.id)` (with the OG-48#2 orphan skip), after which
`RerankCandidate(id, text=chunk.text)` objects are built and passed to `reranker.rerank`. The T-DOC38
parent-paper orphan skip happens after reranking.

The stub is dropped in that per-hit loop, right after `get_chunk` and before the `RerankCandidate` is
built: (a) it therefore never reaches the reranker and costs no pool slot; (b) the pool is refilled
because, with the flag on, `retrieve()` fetches `pool * 5 // 4` hybrid hits (`_STUB_OVERFETCH_*`) and
stops the loop once `pool` real chunks are collected, so the reranker still gets `rerank_pool_size`
real chunks wherever the extra 25% of hits contain enough of them (stubs are 7-10% of chunks). With
the flag off the fetch size and the loop are exactly as before.

Edge cases (all tested in `rag/test_retriever.py`): every candidate a stub -> `([], coverage)`,
reranker not called; a paper whose only chunk is a stub simply does not appear on the passage path;
`retrieve_papers()` never consults the flag (summary points are not chunks); `k` larger than the
surviving pool returns all survivors; bare numbers ("3.159") and empty bodies are stubs; the 51-char
definition "computer program used in the development of an item" is kept (threshold 40).

One definition of "stub": `body_of` and `_MIN_BODY_CHARS` now live in `rag/retriever.py`;
`scripts/chunk_quality_census.py` (behaviour identical: 2,483 standards stubs reproduced) and
`scripts/list_stub_chunks.py` import them -- scripts importing from `rag/` is the right layering.

`coverage.candidate_count` is `len(hits)` as before, which with the flag on counts the overfetched
hits (up to 25% more than baseline) -- a diagnostic only.

## How it is switched on

- Library: `Retriever(..., drop_stub_chunks=True)`; default False.
- `app.assembly.build_mcp_server(config, ..., drop_stub_chunks=False)` threads it through (unprotected).
- CLI for the A/B: `python -m app.retrieval_eval ... --drop-stub-chunks` (unprotected hook, tested).
- PRODUCTION: `app.assembly.build_mcp_server` callers do not pass it, so production stays off. Turning
  it on in production would need either a call-site change in the MCP entrypoint or a new
  `Config` field (`rag/config.py`, PROTECTED) plus `config.example.yaml`. NOT done; left for the
  sign-off rider, and only after an ADOPT verdict.

## Commands to run once the GPU is free

Standards (`$STD_GT` = the standards ground-truth fixture of record; not in this repo tree):
```
cfg=/home/omar/ai-projects/research-system-rag-standards/data/config.yaml
db=/home/omar/ai-projects/research-system-rag-standards/data/papers.db
python -m app.retrieval_eval --config $cfg --ground-truth $STD_GT --collection av_standards --db-path $db --k 10 --report-path std_base.json
python -m app.retrieval_eval --config $cfg --ground-truth $STD_GT --collection av_standards --db-path $db --k 10 --drop-stub-chunks --report-path std_drop.json
python scripts/list_stub_chunks.py $db --report std_base.json
python scripts/list_stub_chunks.py $db --ab std_base.json std_drop.json
```
Main corpus: same with `--config config.yaml` (db `/home/omar/ai-projects/research-system-rag-data/papers.db`)
and `--ground-truth fixtures/eval/eval_ground_truth.json`, then `fixtures/eval/eval_book_questions.json`.
Both arms of a pair must run back-to-back against the same collection. `--ab` prints the per-fixture
numbers for criteria 1-3 (`stub_at_rank1_share`, worst net per-stratum change, P@1 / hit@k change);
the ADOPT conjunction across fixtures is applied by the reader. Per-question rows are required (do
not pass `--no-per-question`). Note: `retrieved_block_ids` identifies stubs by anchor block, which
is exact as long as no heading block anchors both a stub and a non-stub chunk (verify with the
`--out` file if in doubt).

## Addendum 2026-11-11 (EV-12): fixtures, minimum effect, ceiling, stub identity

Appended before any stub A/B report exists (no `2026-11-1*-stub-filter-ab*` file or run directory is
older than this addendum's commit). The text above is unchanged. The review's criticism it answers: the
original pre-registration named fixtures with no passage gold, had no minimum effect (one noise flip would
ADOPT), identified stubs by anchor (ambiguous for 7.5% of standards chunks) and left three tools with
different stub thresholds. Full context and the other session-2 pre-registrations:
`docs/eval-reports/data/2026-11-11-session2/PREREGISTRATION.md` section 2.

1. Fixtures of record (hashes in `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`):
   `docs/eval-reports/data/2026-11-10-standards-gt/standards_gt.json` (collection `av_standards`, shipped
   config, rerank depth 128; 128 questions, 94 scored answerable),
   `docs/eval-reports/data/2026-11-10-papers-passage-gt/papers_passage_gt.json` (collection `papers`; 61 / 61),
   `docs/eval-reports/data/2026-11-10-causal-books-gt/causal_books_gt.json` (collection `papers`; 74 questions,
   69 scored answerable). These replace `fixtures/eval/eval_ground_truth.json` and `eval_book_questions.json`
   named above, which have no passage gold. Sets are decided separately, never averaged.
2. Metric of record: member-passage hit@10 (`scripts/eval_strata_report.py`), with the excerpt metric
   (`passage_excerpt_level`, `app.retrieval_eval`) reported beside it. Arms: baseline vs `--drop-stub-chunks`,
   run back to back at one commit, baseline re-run (not reused).
3. Stub identity: by chunk id (`retrieved_chunk_ids`, EV-9). The single binding definition is the
   retriever's, `len(body_of(text)) < _MIN_BODY_CHARS` = 40 characters. A rank is a stub only if every
   candidate chunk id at that rank is a stub. The 60- and 80-character thresholds in other tools are
   non-binding. No threshold is changed in code.
4. Minimum effect and ADOPT rule (replaces criteria 1-3 above for the A/B run tonight): ADOPT only if ALL
   hold: (a) stub-at-rank-1 at baseline is > 0 on a set S; (b) member-passage hit@10 improves by at least 2
   questions (net, paired) on that set S; (c) no stratum with n >= 10 on any of the three sets loses more than
   one question (net <= -2) in member-passage hit@10. Otherwise REJECT; the default stays off. Adoption
   itself still needs the sign-off rider.
5. Ceiling and kill criterion: first-order, a question can gain only if it misses member-passage hit@10 at
   baseline AND has at least one stub in its baseline top 10. Ceiling C per set = the count of such questions,
   computed from the baseline rows (they now carry `retrieved_chunk_ids`) before any GPU use, printed with the
   stub-at-rank-1 count and the stub share of top-10 slots. A set with C < 2 is skipped (the minimum effect is
   unreachable); if stub-at-rank-1 occurs on fewer than 3 answerable items on every set the whole A/B is
   killed (minimizer section 4; EV-21 parked-until). Second-order movement (the filter hands the reranker a
   refilled pool) is not bounded by C because rows carry only the top 10; the report says so.
6. Minimum detectable effect: a net +2 is a materiality floor, not a significance claim; the smallest paired
   result with exact two-sided p < 0.05 is 6 wins to 0 losses (or 8 to 1) on a set.
