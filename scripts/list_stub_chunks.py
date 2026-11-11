"""List heading-only stub chunks of a corpus DB (read-only, no Qdrant, no GPU). STUB: see CQ-3 note.

Intended behaviour: for a papers.db, write `chunk_id<TAB>anchor_block_id<TAB>paper_id` for every chunk
whose body is shorter than `rag.retriever._MIN_BODY_CHARS` and print per-document stub counts. Input
for deleting stub points from a CLONED collection. `--report R.json` computes stub-at-rank-k shares
from an app.retrieval_eval report; `--ab BASE.json DROP.json` applies the pre-registered ADOPT rule
in docs/eval-reports/2026-11-10-cq3-stub-chunks.md.
"""
