# CORPORA — the registry of the five corpora

Written 2026-11-10. Purpose: a cold agent can find a corpus, select it with the right tool, and not
confuse it with another. **Numbers (documents, chunks, per-corpus levers' effects, census figures)
live in `docs/PROJECT-STATUS.md` section 1.1 and 1.2 and are deliberately not repeated here**; this
file holds the stable facts. Every statement below was checked on 2026-11-10 against each corpus's
`config.yaml` and read-only SQLite (`sqlite3 "file:<db>?mode=ro"`); the counts in PROJECT-STATUS 1.1
were re-run the same day and matched (main 12,390 docs / 399,676 chunks; Waymo 1,861 / 47,771;
standards 119 / 35,714; Motional 65 / 2,013; Waabi 29 / 566).

## Rules

1. **No ingest into a live collection from the `EP-programme-20261110` branch** (or any branch) until
   the verdicts of the sparse-recompute (EV-22) and bounded re-chunk (CQ-11) experiments are in. The
   stored chunks come from two chunker generations (below); an ingest would mix chunkers and sparse
   versions in one collection and silently confound every comparison (`docs/PROJECT-STATUS.md` 1.1).
2. **No ingest, re-chunk, resparse or re-embed on a corpus while a benchmark against it is running or
   its frozen protocol is open.** A benchmark compares against a fixed index; a changed index
   invalidates the run. Benchmarks are frozen by `docs/eval-reports/2026-11-10-*-benchmark-protocol.md`.
3. SQLite (`papers.db`) is the source of truth; the Qdrant collection is a projection of it that can be
   rebuilt only by re-embedding on the GPU. The IDF reindex question ("Decision 1") is **closed**:
   all five collections already carry `sparse.modifier = "idf"` (on-disk `collections/<name>/config.json`;
   `docs/DECISIONS-PENDING-operator.md`).

## Registry

Locations outside the repo are given relative to the parent directory of the checkout (the one that
contains `research-system-rag/`). The three sibling directories are **not git repositories**.

| corpus | scope | data directory | collection | chunker generation |
|---|---|---|---|---|
| **main** | Causal inference / causal ML / econometrics / causal-LLM papers (arXiv harvest) plus 5 books and drop-in PDFs; 37% of papers are off-topic by label, kept by operator decision | sibling `research-system-rag-data/` | `papers` | legacy |
| **Waymo** | Autonomous-vehicle safety, simulation, scenario testing (arXiv from 2015 plus non-arXiv drop-ins, 370 `local:` ids) | `waymo/data/` inside the main checkout (gitignored; a git worktree does **not** contain it) | `waymo_av_safety` | legacy |
| **AV standards** | AV safety standards, regulation, guidance and commentary documents (mostly non-arXiv: 114 of 119 ids `local:`; 10 books) | sibling `research-system-rag-standards/data/` | `av_standards` | **new (bounded)** |
| **Motional** | Papers by or about Motional/nuTonomy/Aptiv (65, curated) | sibling `research-system-rag-motional/data/` | `motional_av` | legacy |
| **Waabi** | Papers by or about Waabi (29, curated) | sibling `research-system-rag-waabi/data/` | `waabi_safety` | legacy |

**Chunker generations.** "Legacy" = chunker before commit `8301342`; "new (bounded)" = after it (commits
`8301342`, `5eadd35`, 2026-11-01, on `EP-programme-20261110`, not on `main`). Attributed by re-chunking
stored blocks and comparing with stored chunks (method and results: `docs/PROJECT-STATUS.md` 1.1; RV-2
F-2.2, `docs/eval-reports/data/2026-11-10-system-review/RV-2-parse-chunk.md`). The chunker has no version
stamp in the database; this table is the only record.

## Selecting a corpus (the cwd trap)

- **Most ingest-side tools take no `--data-dir`** (`app.ingest`, `app.build_corpus`, `app.parse_phase`,
  `app.prefetch_pdfs`, ...): they use the **current working directory as the data dir**. Run
  `cd <data dir> && python -m app.ingest ...`. Run from the wrong directory and you ingest into, or
  read, the wrong corpus (or create an empty `papers.db` at the repo root).
- **Four tools take `--data-dir`** and need no `cd`: `app.serve`, `app.dashboard.server`,
  `app.dashboard.verify_numbers`, `app.init_config`. (`app.mcp_verify_client` also accepts it.) Many
  `scripts/` analysis tools take `--data-dir` too; several default to `waymo/data`, so always pass it.
- **MCP: one server process serves exactly one corpus.** `app.serve` with no `--data-dir` discovers
  `config.yaml` from `RAG_CONFIG`, then cwd, then walking up parents. To reach more than one corpus
  register one MCP server entry per corpus with `--data-dir`. Call `corpus_stats()` first: its `serving`
  key names the collection and db. Details: `docs/RUNBOOK.md` "Which corpus is this MCP connection serving?"
  and "Running a second corpus".
- All five configs share one `gpu_lock_path` (the repo's `.gpu.lock`); keep it shared so two corpora
  cannot hold the GPU at once. `app.init_config` writes a private lock path that must be edited.

## Config levers that differ

All five: `top_k` 10, `child_parent_expansion` true, `relevance_filter` off, `ingestion_mode` one_shot_seed,
same `gpu_lock_path`. The levers that differ (values as of 2026-11-10; read each `config.yaml`):

| corpus | `rerank_depth` | `hybrid_dense_weight` | status of the choice |
|---|---|---|---|
| main | 32 | 0.5 | default; not tuned for this corpus |
| Waymo | 32 | **0.7** | **measured, operator decision 2026-08-24** (`docs/PROJECT-STATUS.md` "Operator tuning decision, 2026-08-24"; reports in `docs/eval-reports/` 2026-08-22..28). Config backup `config.yaml.bak-w0.5-*` holds the 0.5 state |
| standards | **128** | 0.5 | **unexplained** (no recorded reason). Waymo evidence points the other way (pool 32/64/128 gave Recall@10 65/64/61 of 68, NB-X-O). Frozen decision rule in `docs/eval-reports/2026-11-10-standards-benchmark-protocol.md`; not yet run |
| Motional | 32 | 0.5 | default |
| Waabi | 32 | 0.5 | default |

Other per-corpus config: main `corpus_cap` 30,000, `ordering: freshest_first`, 33 harvest queries; Waymo
`ordering: relevance`, 20 queries, arXiv categories cs.RO/stat.AP/stat.ME/cs.LG/eess.SY/cs.CV;
standards/Motional/Waabi are pinned id lists (`ingest_paper_ids`), `prefetch_target` 1.

## Ground truth and benchmark history

| corpus | fixtures | benchmarked? |
|---|---|---|
| main | legacy, tracked: `fixtures/eval/eval_ground_truth.json` (paper-level), `eval_book_questions.json`, `eval_known_absent.json`, `eval_equation_slice.json`. New, under `docs/eval-reports/data/`: `2026-11-10-papers-passage-gt/`, `2026-11-10-causal-books-gt/`, `2026-11-10-focus-gt/` | Yes, on the legacy fixtures (2026-07/08 reports). The new passage sets are authored and **never run**; protocol frozen: `docs/eval-reports/2026-11-10-main-corpus-benchmark-protocol.md`, `...-topic-focus-benchmark-protocol.md` |
| Waymo | `fixtures/eval/gt_wmr.json`, `waymo_gt_verified.json`, `waymo_gt_a/b.json`, `eval_ground_truth_waymo.json`, `waymo_safety_research_55*.json`; `docs/eval-reports/data/2026-08-28-wa4-gt/`; id lists in `fixtures/waymo/` | **Best evaluated corpus** (many reports 2026-08-22..28) |
| standards | `docs/eval-reports/data/2026-11-10-standards-gt/standards_gt.json` (128 items) | **Never** (authored, protocol frozen, services down) |
| Motional | none in the repo; ad-hoc question files in `_tools/` of its data dir | **Never** |
| Waabi | none | **Never** |

## How each was built, and reproducibility

**None of the five can be rebuilt from tracked files.** Build scripts, id lists, logs and backups live in
the data directories, which are outside git (Waymo's is gitignored; the siblings are not repositories).
The sequence, as far as the evidence in each directory shows:

- **main:** arXiv harvest by `focus_area_queries` and drop-in PDFs through `app.build_corpus`;
  `ingest_run-*.log` and `config_run-*.yaml` 2026-07-14..08-01; a 2026-07-28 re-chunk from stored blocks
  (`rechunk_run.log`). Nothing ingested since 2026-08-01.
- **Waymo:** v2 plan harvest (`run_batches.sh`, `run_phases.sh`, `chain_phases.sh`, `run_manifest.json`),
  then drop-in batches (`drop_in_risk_20261030`, `drop_in_mindmap_20261101`, `drop_in_20261102`, `drop_in_20261102b`).
- **standards:** `_tools/build_standards.sh` (33 pinned ids) then batch scripts `ingest_mindmap_20261101*`,
  `ingest_completion_20261102*`, `ingest_blog_20261102`, each backing up `papers.db` first;
  re-chunked after `8301342` for the ids in `rag_fix_ids.txt`.
- **Motional:** `_tools/fetch_motional.py` then `_tools/build_motional.sh` (65 ids).
- **Waabi:** `_tools/build_waabi.sh` only; **how the PDFs/ids were acquired is not recorded.**

## Known defects (all corpora unless stated)

Link, do not restate: `docs/PROJECT-STATUS.md` 1.2 (off-topic share of main, ligature-broken words,
heading-only stub chunks, chunks cut at the 4,096-token embedding limit, book section paths, duplicates,
missing `figures`/`tables` rows in main) and section 6; audits: `docs/eval-reports/2026-11-10-system-review.md`
(adjudicated review), `docs/eval-reports/2026-11-10-topic-labels-audit.md`,
`docs/eval-reports/data/2026-11-10-embed-truncation/report.md`,
`docs/eval-reports/data/2026-11-10-ligature-census/`, `docs/eval-reports/data/2026-11-10-dup-ref-census/`,
`docs/eval-reports/data/2026-11-10-system-review/RV-2-parse-chunk.md`.
Index-vs-SQLite agreement of the Qdrant point counts is unverified while `rag-qdrant` is down.
The services are recorded in `ops/README.md`.
