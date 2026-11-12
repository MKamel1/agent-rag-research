# Loose ends: point-count surplus and the 3,136 vs 3,138 truncated-chunk count (2026-11-11)

Read-only. Qdrant only via `points/scroll` (payload-only, limit 1,000); SQLite only via `mode=ro`; CPU only
(tokenizer file is local). Scripts: `data/2026-11-11-loose-ends/` (`point_diff.py`, `trunc_diff.py`, `nul_check.py`).

## 1. Points above chunks + summaries

Command: `python3 -I data/2026-11-11-loose-ends/point_diff.py <collection> <papers.db>`. It scrolls every point,
keys it by payload `_ext_id`, and diffs against `chunks.chunk_id` and `summaries.summary_id`.

| | `papers` (main) | `av_standards` |
|---|---|---|
| points | 412,167 | 36,031 |
| distinct `_ext_id` / duplicate ids | 412,167 / 0 | 36,031 / 0 |
| payload `kind` | chunk 399,676; summary 12,491 (no other kinds) | chunk 35,714; summary 317 |
| DB `chunks` / `summaries` rows | 399,676 / 12,491 | 35,714 / 317 |
| chunk points absent from DB, DB chunks without a point | 0 / 0 | 0 / 0 |
| summary points absent from DB, DB summaries without a point | 0 / 0 | 0 / 0 |
| points whose `paper_id` is not in `papers` | 0 | 0 |
| `summaries` rows with id `<paper_id>:summary:ch<n>` (chapter summaries) | 101, in 5 books | 198, in 10 books |
| per-document summaries (`<paper_id>:summary`) | 12,390 (= 12,385 papers + 5 books) | 119 |

Cause: the baselines compared points with chunks + one summary per paper. Books also write one `kind="summary"` point per
chapter (`rag/orchestrator.py::_upsert_record`, ids `<paper_id>:summary:ch<n>`, `section_path` = chapter title; stored in the
same `summaries` table by `rag/book_summarizer.py`). 101 chapter summaries in main and 198 in standards are exactly the surplus.
The point set and the DB are identical id for id: no orphans, no duplicates.

Retrievable: yes, deliberately. They are `kind="summary"` points, so `retrieve_papers()` / `search_papers` can return an
individual chapter as a routing hit. They never appear in passage (`kind="chunk"`) retrieval.

Conclusion: expected by design; no action. The baseline guard should compare against `COUNT(*)` of `chunks` plus `summaries`, not chunks plus papers.

## 2. 3,136 vs 3,138 truncated main chunks

Both runs use the same rule (Qwen3-Embedding-4B tokenizer, no special tokens, truncated when tokens > 4,096; no `>=` effect:
no chunk is exactly 4,096 tokens) and the same chunk count (399,676). The difference is the pre-filter:

- `2026-11-10-embed-truncation/measure.py` selects candidates with Python `len(text) > 3500` (128,975 chunks tokenised, total
  characters 1,080,386,685).
- `2026-11-10-truncation-rechunk/exact_truncated_ids.py` selects with SQL `length(text) > 3500` (128,761 tokenised).
  SQLite `length()` on TEXT stops at the first NUL character.

`nul_check.py` finds the 2 chunks that contain a NUL early, so SQL length is under 3,500 while the full text is over 4,096 tokens:
`2510.16669:c33` (9,165 chars, NUL at offset 551) and `2602.23602:c18` (13,781 chars, NUL at 2,476).
`trunc_diff.py` reproduces the stored list exactly: 3,136 ids, 0 differences, the list equals what the SQL filter yields. 3,136 + these 2 = 3,138
(also reconciles the 214-chunk and 1,109,567-character gap between the two scans).

Right number: 3,138 (0.79%). The tokenizer sees the whole stored text including text after the NUL; the 3,136-id list
(`truncated_chunk_ids_main.txt`) is missing those 2 ids, so the CQ-4 re-chunk target set understates by 2 chunks (about 0.06%).
Waymo and standards were not re-checked for NUL chunks (Waymo 126 comes from the Python-length run; the id list used SQL length).

Conclusion: explained, a method artefact, not a data change. No code action; if the re-chunk is ever re-opened, regenerate the id
list with Python `len`, not SQL `length()`.

## Standing decision (truncation re-chunk)

The targeted re-chunk (about 177-212k new embeddings for 0.79% of chunks) was costed and deliberately not scheduled. Re-open only if a
measured retrieval loss is traced to truncated chunks.
