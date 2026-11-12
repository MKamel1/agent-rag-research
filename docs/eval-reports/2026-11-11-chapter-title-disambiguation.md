# CQ-20: disambiguate duplicate chapter titles (Decision 4, option A)

Date 2026-11-11. Branch `CQ-20-chapter-title-disambiguation`. Nothing was applied to any database or collection; only dry runs were executed.

## What was built

| piece | where |
|---|---|
| Pure function `disambiguate_titles(titles) -> list[str]` | `rag/book_summarizer.py` (tests in `rag/test_book_summarizer.py`) |
| The one call, for new ingests | `summarize_book()`, right after the per-chapter loop and before the overview/"Contents:" list are built |
| Corpus backfill CLI `python -m app.disambiguate_chapter_titles` | `app/disambiguate_chapter_titles.py` (+ `app/test_disambiguate_chapter_titles.py`) |
| Dry-run listings and proposed GT edits | `docs/eval-reports/data/2026-11-11-chapter-title-disambiguation/` |

Flow traced: `summarize_book` sets `ChapterSummary.title` -> `IngestionOrchestrator._upsert_record` writes it to the chapter point's `section_path` payload and `DocumentStore.put` writes it to `summaries.title` -> `Retriever.retrieve_papers` returns `chapter` from the SQLite record (`rag/retriever.py`, `cs.title`) -> `rag/mcp_server.py` surfaces it -> `app/retrieval_eval.py` scores `r.chapter == gold_chapter_title`. `summarize_book` is the only producer of titles, so one call there covers every new ingest; the eval needed no change because it only compares strings.

## The scheme

Within one book, the first occurrence of a repeated title keeps it verbatim; the k-th occurrence (k >= 2) becomes `"<title> (k)"`, skipping to the next k if that string is already used by another title in the book. Empty titles are left alone. Only repeats change, so a gold title that points at a first occurrence never needs editing. Idempotent: unique titles come back unchanged (tested). Deterministic given the order of the units.

Side effect worth knowing: the windowed fallback for flat books (`_FALLBACK_WINDOW_BLOCKS`) used to label every window with the same section title; those windows now read `Only Section`, `Only Section (2)`, ... (one existing test updated for this).

## Is the title inside embedded text?

- Chapter point vectors (dense and sparse): no. They embed `ChapterSummary.text` only, so renaming a chapter leaves them exactly right.
- The whole-book summary (`<paper_id>:summary`) does: its text ends with a `Contents:` list of `n. <title>`, and its overview was written from `"<title>: <summary>"` lines. After applying, that vector and its stored text still carry the old duplicate labels (and the text is not edited either, so SQLite text and vector stay consistent with each other). The staleness is a few repeated label strings in one vector per affected book; not re-embedded, as instructed. New ingests get the unique labels in the Contents list.

## Backfill tool

Dry run by default: lists every (paper_id, chapter index, old title, new title), checks each chapter point exists in the collection (vector store scroll only; SQLite opened `mode=ro`), writes nothing. `--listing-out FILE` saves the TSV.

`--apply` requires the shared guard from `app.resparse.check_apply_guard` (also used by CQ-2 `set_payload_fields`): `--i-have-a-snapshot` (verified against a completed `app.snapshot` backup of that collection on disk, non-empty vector-store file) or `--target-is-clone --clone-of SRC` (point counts must match). Then it writes `section_path` per renamed point through `VectorIndex.set_payload(point_ids=...)` (merge; vectors and all other keys untouched), then updates `summaries.title` in one SQLite transaction (`WHERE summary_id=? AND title=old`). Checks: matched points == renames, SQLite rows changed == renames, a fresh plan is empty. Payload goes first so a crash leaves what users see (SQLite) unchanged, and re-running finishes the job. Idempotent: a corrected corpus plans zero renames.

## Dry-run results

| corpus | units | books | duplicate-title units renamed | points present |
|---|---|---|---|---|
| main (`research-system-rag-data/papers.db`, `papers`) | 101 | 5 | 8 renames = 16 units in 8 same-title pairs, 2 books | all present |
| standards (`research-system-rag-standards/data/papers.db`, `av_standards`) | 198 | 10 | 2 renames = 4 units, 2 books | all present |

Main confirms the expected 16 of 101 in two books (8 pairs; the first of each pair keeps its title).

| paper_id | chapter index | old title | new title |
|---|---|---|---|
| local:54d6ca71dda9 | 13 | 1. Setup: Define the Problem and Data | 1. Setup: Define the Problem and Data (2) |
| local:54d6ca71dda9 | 16 | 4. Choose Optimal Split Point for Each Variable | ... (2) |
| local:54d6ca71dda9 | 17 | 5. Recursive Partitioning: Split Left and Right Nodes | ... (2) |
| local:54d6ca71dda9 | 19 | 7. Pruning the Tree Using Cost-Complexity | ... (2) |
| local:54d6ca71dda9 | 20 | 8. Cross-Validation to Select Optimal Tree Size | ... (2) |
| local:54d6ca71dda9 | 22 | 10. Final Prediction for New Observations | ... (2) |
| local:dfe850b3281a | 5 | Part 2: Causal Inference | Part 2: Causal Inference (2) |
| local:dfe850b3281a | 6 | Part 3: Causal Discovery | Part 3: Causal Discovery (2) |

Standards: `local:5d92cd1f17dd` ch12 `COLUMBIA ACCIDENT INVESTIGATION BOARD` -> `... (2)`; `local:e94916e8eba9` ch17 `References` -> `References (2)`. Full TSVs: `.../main.tsv`, `.../standards.tsv`.

## Ground-truth impact

Gold chapter titles were checked in `fixtures/eval/eval_book_questions.json` (115), `docs/eval-reports/data/2026-11-10-causal-books-gt/causal_books_gt.json` (5 chapter-titled of 74: `Introduction`, `The Most Dangerous Equation`, `Preface`, `Time Series`: none renamed), and the two alternate-split fixtures. The standards GT has no chapter gold.

Which duplicate a gold passage sits in was decided from block positions: chapter units are contiguous block ranges, and the gold block index falls between the two repeated heading starts (for local:dfe850b3281a the second "Part 2" run starts at block 1000 and the second "Part 3" at block 3132; for local:54d6ca71dda9 the gold block 2328 is inside the first "5. Recursive Partitioning" run, which starts there). This agrees with each item's `gold_chapter_index`. The current code cannot rebuild the stored units (it now includes the T-DOC87 marker repair, 38 vs 44 units), so the stored heading runs were used, not a re-split.

| file | question | paper | gold block | unit it sits in | old gold title | new gold title |
|---|---|---|---|---|---|---|
| eval_book_questions.json | QB-028 | local:dfe850b3281a | b1527 | ch5 (second Part 2) | Part 2: Causal Inference | Part 2: Causal Inference (2) |
| eval_book_questions.json | QB-029 | local:dfe850b3281a | b2587 | ch5 | Part 2: Causal Inference | Part 2: Causal Inference (2) |
| eval_book_questions.json | QB-030 | local:dfe850b3281a | b3596 | ch6 (second Part 3) | Part 3: Causal Discovery | Part 3: Causal Discovery (2) |
| eval_book_questions.json | QB-031 | local:dfe850b3281a | b4097 | ch6 | Part 3: Causal Discovery | Part 3: Causal Discovery (2) |
| eval_book_questions.json | QB-034 | local:54d6ca71dda9 | b2328 | ch7 (first "5. Recursive Partitioning", index 7) | unchanged | unchanged (first occurrence keeps its title; but see false hits below) |

`eval_book_questions_tdoc87.json` (QB-034, QB-102..106) and `eval_book_questions_outline_split.json` describe other splits (gold indices 13/14, a "do not ship" boundary change) and are not the live corpus; no edit is proposed. Machine-readable edits: `.../proposed_gt_changes.tsv`. `fixtures/` and the frozen GT were not touched; the four edits need operator sign-off and go in through a rider.

## Measurement error today

The 2026-11-11 baseline run rows (`.../runs/20261111T004734/legacy-eval_book_questions.json`, `books.json`) record only `chapter_level.{scored,hit,rank}` and the retrieved paper/block/chunk ids, not the returned chapter string or chapter summary id. So whether a chapter hit was to the right or the wrong same-named unit cannot be told from the rows. Missing: the returned `chapter` (or `summary_id`) per rank. Re-running retrieval needs the embedder/GPU, which this ticket may not use.

What the rows do bound: of the five affected questions, QB-028 and QB-029 scored chapter hits (rank 1) and QB-034 scored a hit (rank 1); QB-030 and QB-031 were misses (a miss cannot be a false hit). So at most 3 of 115 legacy chapter-scored questions (2.6 percent) were possibly false hits; the causal-books set has 0 questions on a duplicated title. The true count is between 0 and 3. QB-028/029 are the live risk (the gold title matched the first "Part 2" unit's label too). QB-034 would turn from possible-false-hit to a strict miss after apply if the system returned the second unit. Net: the error is small on this set, so re-measurement is a correctness step, not a large shift.

## Apply procedure (not run)

1. Stop writers to the corpus (no ingest running).
2. Snapshot: `python -m app.snapshot` for the corpus and collection (`papers`).
3. Dry run, save and review: `python -m app.disambiguate_chapter_titles --db /home/omar/ai-projects/research-system-rag-data/papers.db --collection papers --listing-out <file>` and compare with `data/.../main.tsv` (expect 8 renames).
4. Apply: same command plus `--apply --i-have-a-snapshot` (or `--target-is-clone --clone-of papers` on a clone first).
5. Verify: the command asserts matched points and updated rows equal 8 and that a re-plan is empty; re-run the dry run and expect "0 chapter title(s)". Optionally call `search_papers` for a Part 2 query and see both `Part 2: Causal Inference` and `... (2)`.
6. Update GT through a rider (operator sign-off, the four QB-028..031 edits above), then re-measure chapter-routing for the books baseline. Standards: same command with `--db .../research-system-rag-standards/data/papers.db --collection av_standards` if wanted (2 renames, no GT impact).

## What applying changes

For users: only labels. 8 chapter labels in two books (2 in the standards corpus) gain a ` (k)` suffix. Chunk boundaries, ranking, scores, chunk and chapter vectors, sparse vectors and point counts are unchanged. For the frozen baselines: passage-level and paper-level numbers are unaffected. Chapter-routing numbers must be re-measured after apply, after the GT rider, since gold titles for QB-028..031 stop matching the old label and a wrong-unit hit stops counting. Baselines taken before apply remain valid for the pre-apply corpus only. The underlying mis-split (numbered list items as chapters, B-3) is untouched.

## Applied 2026-11-11, and measured before and after

Applied to both corpora after a fresh verified snapshot of each (main `snapshot-20261112T012540Z`, standards
`snapshot-20261112T012604Z`): 8 renames in `papers`, 2 in `av_standards`; payload and SQLite agree and a re-plan is
empty on both. The four gold titles (QB-028..031) were updated in `fixtures/eval/eval_book_questions.json` and its
hash re-frozen (operator instruction "apply for both").

Paired measurement on the 115 book questions, main corpus, same config both sides (`runs/config-shipped.yaml`,
`rerank_depth` 128), 0 errors in either run (`runs/before.json`, `runs/after.json`):

| level | before | after |
|---|---|---|
| paper Recall@10 | 0.817 | 0.817 |
| passage Recall@10 | 0.765 | 0.765 |
| chapter Recall@10 | 0.452 (52/115) | 0.452 (52/115) |

No question changed its chapter-level outcome. So the number of false chapter hits caused by duplicate titles was
0 of 115 (the earlier bound was 0 to 3): QB-028, QB-029 and QB-034 were hits on the correct unit. The change makes
every chapter unit addressable and removes the possibility of a false hit; it does not move any retrieval score.
Do not re-run unless chapter boundaries or titles change again.

Note: these runs are at `rerank_depth` 128; the frozen 2026-11-11 baseline for this set (paper 0.774, passage 0.722,
chapter 0.478) was at depth 32, so the two are not a paired comparison of depth.
