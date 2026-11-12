# CQ-4 — targeted re-chunk of embed-truncated chunks: plan and cost (not run)

Prepared 2026-11-10 without GPU or services. Nothing was written to any database or index.
Background: `../2026-11-10-embed-truncation/report.md` (the embedding server truncates at 4,096 tokens).

## Result

| | main | waymo |
|---|---|---|
| Truncated chunks (exact list: `truncated_chunk_ids_*.txt`) | 3,136 | 126 |
| Affected papers (`targets_*.txt`) | 1,490 | 72 |
| Chunks those papers hold today (all would be replaced) | 60,888 | 3,882 |
| Estimated new embeddings, low to high | 170,397 to 202,839 | 6,656 to 8,929 |

Total: about 177k to 212k embeddings, against 64,770 chunks today.

The embedding estimate is text length divided by 1,200 characters. `app.rechunk --dry-run` was **not**
run: `main()` constructs `DocumentStore` (which runs `migrate()`, a write) and `VectorIndex` (which
contacts the vector store and may create the collection) before it reaches the dry-run check.

## Correction to the earlier truncation report

That report estimated "a few minutes of GPU" for re-embedding only the oversized chunks. No tool does
that: `app/rechunk.py` re-chunks and re-embeds every chunk of a changed paper. The real cost is the
table above.

## Concentration

192 main papers hold 50% of the truncated characters; 978 hold 90%. The problem is broad, not a
handful of documents. Top 20: `summary.json`.

## Consequences before applying

- Chunk ids are positional (`{paper_id}:c{index}`): an id survives but points at different text.
- 48 ground-truth items sit in affected papers and must be re-grounded (`gt_affected.tsv`): 12 of 61 in
  `papers_passage_gt.json`, 13 of 69 answerable in `causal_books_gt.json`, 23 of 115 in
  `fixtures/eval/eval_book_questions.json` (the two book sets: all in one book). None of the 48 gold
  chunks is itself truncated.
- Affected papers would use the 220-word chunker while the rest of the corpus keeps the 1,500-word
  one: mixed granularity inside one index.
- Alternative named by the truncation report and not assessed here: raising the embedding server's
  `--max-batch-tokens`.

## Open

- This count (3,136 main) differs by 2 from the earlier measurement (3,138). Unexplained; check before
  applying.
  2026-11-11: explained, 3,138 is right; the SQL `length()` filter used here stops at NUL and missed 2 chunks (`2510.16669:c33`, `2602.23602:c18`). See `docs/eval-reports/2026-11-11-loose-ends-point-counts-and-truncation.md`.

## Commands for later — needs GPU, not run

Snapshot first (`python -m app.snapshot`), then `python -m app.rechunk --paper-ids-file <targets> --dry-run`
from inside the corpus data directory, review, re-run without `--dry-run`, verify counts, re-ground the
48 ground-truth items with each set's `merge_gt.py`. See `docs/PROJECT-STATUS.md` §2 for the flags.
