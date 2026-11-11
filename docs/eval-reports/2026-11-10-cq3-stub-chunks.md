# CQ-3: heading-only "stub" chunks -- instrument + reversible retrieval-time filter

Status: PRE-REGISTRATION (written in the stub commit, before any measurement; no GPU was available).
Sections "Design" and "Where the filter sits" are filled in by the implementation commits.

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
