# Project Status — single source of truth

*Written 2026-08-05; partially re-verified 2026-11-10 (ticket EP-1). **Re-derived on 2026-11-10 against
live read-only SQLite, git and the on-disk state:** the §1 corpus registry and known-state tables (every
corpus count, config lever and chunker attribution), the entry-point rows in §2 for `app.serve`,
`app.doctor`, `app.resparse`, `app.set_payload_fields`, the Precision-95 lane statuses in §3b, the new
2026-11-10 ledger in §3, §6 (open items and pending operator decisions) and the §7 doc map. **Not
re-verified since 2026-08-05 and may be stale:** the rest of §2 (flag table rows other than those named),
§3 entries dated before 2026-08-28, §4, §5 and §8's branch index (§8's trailing sub-sections are ledger
entries, now headed §3b). Where a section carries its own date or query, that date governs. Every claim
carries its evidence (commit SHA, `file:line`, report path, or the query used). This doc supersedes any
status claim in `AGENTS.md`'s old owner table or any doc listed §7 as HISTORICAL. If this doc and another
doc disagree on a *fact* (not a frozen shape — `DATA-CONTRACTS.md` still wins those), this one wins; fix
the other doc.*

---

## 1. What the system is and what runs today

**V0** is a plain grounded RAG cache over causal-methods arXiv papers (causal inference, causal ML,
causal discovery, treatment-effect estimation, causal representation learning, causal LLM/agent
setups): ingest → parse → chunk → embed → retrieve → return grounded passages + summaries + citations
over MCP, at ~0 API cost (local models only). It has since grown two things V0's original design
didn't have: **books** (PDF, chapter-summarized, chapter-routable — `contracts/document_store.py`
`doc_type: Literal["paper","book"]`, T-DOC80) alongside arXiv papers in the same corpus, and a
**drop-in folder** (`drop_in/`) for ingesting PDFs that didn't come from arXiv at all.

### 1.1 Corpus registry — five corpora (re-measured 2026-11-10)

The same pipeline is pointed at five data directories, each with its own `config.yaml`, SQLite
`papers.db` and vector collection (§2 "Second corpus = second directory"). Before this pass this
section described two; the other three had no top-level doc footprint at all (RV-6 B.1 row 12,
`docs/eval-reports/data/2026-11-10-system-review/RV-6-ops-docs.md`).

**How every number below was measured (2026-11-10).** SQLite only, opened read-only
(`sqlite3.connect("file:<db>?mode=ro", uri=True)`): `select doc_type, count(*) from papers group by 1`;
`select stage, count(*) from ingest_state group by 1`; `select count(*) from chunks | blocks |
summaries | quarantine`. Config levers read from each `config.yaml` (`rerank_depth`,
`hybrid_dense_weight`, `collection`). The three corpora outside the repo are sibling directories of the
checkout (`/home/omar/ai-projects/research-system-rag-standards`, `-motional`, `-waabi`, each with a
`data/` subdirectory); main is `/home/omar/ai-projects/research-system-rag-data`; Waymo is `waymo/data`
inside the main checkout (gitignored, `.gitignore:19` — a git worktree does not contain it).

| corpus | data directory | vector collection | documents (`papers.doc_type`) | `ingest_state` stages | chunks | blocks | summaries | quarantine |
|---|---|---|---|---|---|---|---|---|
| **main** (causal methods) | `research-system-rag-data/` | `papers` | 12,390 = 12,385 paper + 5 book | `done` 12,390 | 399,676 | 2,720,572 | 12,491 | 80 |
| **Waymo AV safety** | `research-system-rag/waymo/data/` | `waymo_av_safety` | 1,861 paper | `done` 1,861; `chunked` 2 (`1203.5986`, `1009.1191`, both stranded since 2026-08-06) | 47,771 | 245,045 | 1,861 | 1 (`2601.05653`, PDF 404) |
| **AV standards** | `research-system-rag-standards/data/` | `av_standards` | 119 = 109 paper + 10 book | `done` 119 | 35,714 | 107,521 | 317 | 0 |
| **Motional** | `research-system-rag-motional/data/` | `motional_av` | 65 paper | `done` 65 | 2,013 | 9,478 | 65 | 0 |
| **Waabi** | `research-system-rag-waabi/data/` | `waabi_safety` | 29 paper | `done` 29 | 566 | 3,129 | 29 | 0 |

The main-corpus row is unchanged from the 2026-08-05 measurement (12,390 / 12,385+5 / 399,676 /
2,720,572 / 12,491 / 80): nothing has been ingested into main since 2026-08-01 (`select max(updated_at)
from ingest_state` = `2026-08-01T17:40:07+00:00`). Waymo grew: 123 `ingest_state` rows carry an
`updated_at` after 2026-08-28 (the Oct 31 – Nov 3 drop-in batches; `select count(*) from ingest_state
where updated_at > '2026-08-29'`); the earlier "mid-build, 221 papers, 4,745 chunks" snapshot
(2026-08-07) is superseded. Standards, Motional and Waabi were built 2026-10-27 .. 2026-11-03 (their
`ingest_state` ranges).

**Vector-store point counts cannot be measured today** — `rag-qdrant` is stopped (§1.3), so the
`GET /collections/<name>` numbers from the earlier version of this section were not re-read and are
not restated as current. For reference only, the last recorded values were: `papers` 412,167 points on
2026-08-05 (equals chunks + summaries, 399,676 + 12,491, so it was consistent with SQLite then) and
`waymo_av_safety` 47,893 points on 2026-08-28 (`docs/eval-reports/2026-08-28-sb1-chunk-boundary.md`
header; SQLite then held fewer papers than now). **Index-vs-SQLite agreement is therefore unverified for
all five corpora** until Qdrant is up. What IS verified, from the Qdrant storage on disk
(`.phase0-data/qdrant/collections/<name>/config.json`): all five collections exist and carry
`sparse_vectors.sparse.modifier = "idf"` — the IDF reindex (the old "Decision 1") is applied on all five
(see §6); the store is 31 GB (`du -sh`) and holds 39 collection directories, most of them throwaway
experiment/scratch collections.

#### Per-corpus levers, chunker generation, provenance and evaluation

| corpus | `rerank_depth` | `hybrid_dense_weight` | chunker that produced the stored chunks | how built (evidence in the data directory) | evaluation status |
|---|---|---|---|---|---|
| main | 32 | 0.5 | **legacy** (pre-`8301342`): 299 of 300 sampled papers reproduce byte-for-byte under the old chunker, 0 under the new | arXiv harvest by `focus_area_queries` + drop-in PDFs, driven by `app.build_corpus`; run logs `ingest_run-*.log` 2026-07-14 .. 08-01, `config_run-*.yaml`, `run_manifest.json`, `rechunk_run.log` (2026-07-28 rechunk of `rechunk_targets.txt`). Reproducible from tracked code + `config.example.yaml` in principle, not from tracked files. | legacy fixtures only: `eval_ground_truth.json` (210, paper-level), `eval_book_questions.json` (115), `eval_known_absent.json` (24), `eval_equation_slice.json`; two new passage sets (61 papers, 74 causal books) **authored, never run**; protocol frozen (`docs/eval-reports/2026-11-10-main-corpus-benchmark-protocol.md`) |
| Waymo | 32 | **0.7** (operator decision 2026-08-24, §3b) | **legacy**: 299 of 300 sampled papers reproduce under the old chunker (1 matches both), 0 under the new | v2 plan harvest + drop-in batches; `waymo/data/{run_batches.sh,run_phases.sh,chain_phases.sh,run_b2_topup.sh,run_manifest.json,*.log}`; later `drop_in_risk_20261030`, `drop_in_mindmap_20261101`, `drop_in_20261102`, `drop_in_20261102b`; 370 of 1,861 ids are `local:` (non-arXiv). `fixtures/waymo/` (tracked) preserves the candidate list and id lists. | best evaluated: `gt_wmr.json` (82) and `waymo_gt_verified.json` (84), `scripts/nb_eval_runner.py`, many reports in `docs/eval-reports/` 2026-08-22 .. 08-28 |
| standards | **128** (only corpus not at 32; no recorded reason) | 0.5 | **new** (bounded, post-`8301342`): 119 of 119 reproduce under the new chunker, 0 under the old | `_tools/build_standards.sh` (pinned `all_ids.txt`, 33 ids, → `app.ingest`) then batch scripts `ingest_mindmap_20261101*.sh`, `ingest_completion_20261102{,c,d}.sh`, `ingest_blog_20261102.sh`, `ingest_completion_20261103e.sh` (each backs up `papers.db` to `backups/` and runs `app.snapshot` then `app.ingest_local`); 114 of 119 ids are `local:`; `rag_fix_ids.txt` lists the pre-fix documents re-chunked after `8301342` (RV-2 F-2.2) | `standards_gt.json` (128 items) **authored, never run**; protocol frozen incl. the depth-128-vs-32 decision rule (`docs/eval-reports/2026-11-10-standards-benchmark-protocol.md`) |
| Motional | 32 | 0.5 | **legacy**: 65 of 65 reproduce under the old chunker | `_tools/fetch_motional.py` (reads `catalog.json`, downloads PDFs, keeps OpenAlex-only arXiv hits only if page 1 names Motional/nuTonomy/Aptiv, else `held_back/`), `manifest.tsv`, `status.json`, `_tools/build_motional.sh` (→ `app.ingest --paper-ids-file all_ids.txt`, 65 ids; 20 are `local:`) | **none of record.** Ad-hoc question files `_tools/questions.json`, `qa.json`, `q2..q4.json` + `query_batch.py` exist; no fixture in the repo, no report |
| Waabi | 32 | 0.5 | **legacy**: 29 of 29 reproduce under the old chunker | `_tools/build_waabi.sh` only (→ `app.ingest --paper-ids-file all_ids.txt`, 29 ids; 18 are `local:`); **no acquisition script survives** — how the PDFs/ids were gathered is not recorded | **none of record** |

**Chunker attribution method (re-run 2026-11-10).** Read-only: for 300 random papers per corpus (all
papers for standards, Motional, Waabi), rebuild each paper's `Block` list from the `blocks` table,
run the pre-`8301342` chunker (`git show 8301342^:rag/chunker.py`) and the current `rag/chunker.py`,
and compare the chunk texts with the stored `chunks.text`. This reproduces RV-2 F-2.2's main and
standards results and extends it to Waymo, Motional and Waabi
(`docs/eval-reports/data/2026-11-10-system-review/RV-2-parse-chunk.md` F-2.2). **Consequence:** the
chunker has no version stamp anywhere (`grep -rn chunker_version` finds nothing), `chunk_id` is
positional (`{paper_id}:c{n}`, `rag/chunker.py:386`), so any main/Waymo-vs-standards comparison
confounds corpus with chunker (on a 400-paper main sample the new chunker gives 3.4× the chunks and a p95 chunk length of 1,405 vs 6,635 characters, RV-2 F-2.2), and any ingest into a live
collection from this branch would mix chunker generations. The new chunker's commits (`8301342`,
`5eadd35`, 2026-11-01) are on `EP-programme-20261110`, **not on `main`**
(`git branch --contains 8301342` lists only EP branches).

**Reproducibility (review finding).** None of the five corpora can be rebuilt from tracked files. The
three sibling directories are **not git repositories at all** (`git rev-parse` fails in
`research-system-rag-waabi/data`'s parents); their `_tools/*.sh` build scripts, id lists, config files
and backups exist only on this disk; Waymo's `data/` is gitignored; main's is outside the repo.
Qdrant itself is not reproducible from tracked files either: unpinned `qdrant:latest`, container
arguments and ports only visible via `docker inspect`, collections in the gitignored `.phase0-data/`
(RV-6 F-A2). SQLite is the source of truth; the vector index is a projection that can be rebuilt from
it, but only by re-embedding on the GPU.

### 1.2 Known state of the data (measured 2026-11-10; every number has its source)

| fact | value | source |
|---|---|---|
| main-corpus papers off-topic for causal methods | **37.4%** = 4,630 of 12,385 labelled (`off` 4,630 / `borderline` 1,044 / `on` 6,711). All 12,385 papers labelled (Haiku, title + abstract, `RUBRIC.md`); the 300-paper audit passes (Cohen's kappa 0.901, binary agreement 0.975), but the auditor is the same model family, so it shows consistency, not correctness. **Operator decision: KEEP the off-topic papers and measure whether retrieval stays on focus** (do not filter). `papers.relevance_score` separates on/off at AUROC 0.923 (thresholds proposed, none applied) | `cut -f2 docs/eval-reports/data/2026-11-10-topic-labels/topic_labels.tsv \| sort \| uniq -c`; `docs/eval-reports/2026-11-10-topic-labels-audit.md` §5; the earlier 400-paper sample estimate was 38.5% (`docs/eval-reports/data/2026-11-10-offtopic-census/report.md`) |
| chunks containing ligature-broken words ("efect", "diference") | main **32.42%** (129,566 of 399,676; 52.9% of papers); Waymo 9.97%; standards 2.79%; Motional 5.02%; Waabi 7.07%. CQ-1 repairs the sparse arm (227-entry map) but no collection has been resparsed; the dense arm is not repaired | `docs/eval-reports/data/2026-11-10-ligature-census/results.json` (`corpora.<name>.affected_chunks_pct`); `docs/eval-reports/data/2026-11-10-ligature-census/repair-map-report.md` |
| heading-only "stub" chunks (body < 40 chars) | main **9.1%** (36,364), Waymo 9.87% (4,717), standards 6.95% (2,483; 400 bare-number), Motional 9.99% (201), Waabi 10.25% (58) — 7-10% in every corpus. The chunker emits them (RV-2 F-2.6); CQ-3's `drop_stub_chunks` filter hides them at query time (default off, A/B not run) | `python scripts/chunk_quality_census.py <db>` per corpus, re-run 2026-11-10 |
| chunks cut at the 4,096-token embedding limit | main **3,138** = 0.79% of chunks (1.51% of characters); Waymo 126 (0.26%); standards 0. TEI truncates every input silently at `--max-batch-tokens 4096`; the client sends no truncate flag. Motional and Waabi not censused (oversized chunks 22 and 6 by the census above) | `docs/eval-reports/data/2026-11-10-embed-truncation/report.md` (exposure table; container flags read from `docker inspect`/logs, not a live request) |
| book section paths without chapter hierarchy | the 15 books (5 main, 10 standards) carry ≈12,500 chunks whose `section_path` is not a chapter (every `Chapter N` heading becomes a depth-1 root); standards also has running headers and stale clause numbers in paths (UL 4600, 1,384 chunks, has a wrong path for most clauses; 1,678 standards chunks, 4.7%, have a running-furniture string as their path root) | RV-2 F-2.1, F-2.5, F-2.11 (`docs/eval-reports/data/2026-11-10-system-review/RV-2-parse-chunk.md`) |
| duplicate documents / reference lists indexed as content | candidate duplicate groups: main 8, Waymo 8, standards 1 confirmed; reference-section text is ≈0.9-1.0% of characters in main and Waymo (0.33% standards) | `docs/eval-reports/data/2026-11-10-dup-ref-census/report.md` (A3, Part B) |
| raw parser structure not persisted for main | `figures` and `tables` tables hold 0 rows in main (Waymo 26,087 / 8,390; standards 3,544 / 2,189; Motional 775 / 278; Waabi 433 / 139): main was parsed before RI-18 (`f92bd8f`) persisted them | `select count(*) from figures`, `from tables` per corpus, 2026-11-10 |

### 1.3 Backups, disk and services (checked 2026-11-10, read-only)

- **Disk:** `/dev/nvme0n1p2` 3.6T, 3.4T used, **90G free, 98% full** (`df -h /home/omar`). Every backup
  sits on this same disk; nothing is off-disk (RV-6 F-A1).
- **Main-corpus backups:** the newest is **`backups/snapshot-20260730T021052Z`** (manifest + `papers.db`
  + Qdrant `papers.snapshot`; dated 2026-07-29/30 local). The live `papers.db` was last modified
  2026-09-07 (3.55 GB). Also in `backups/`: `papers-pre-0004-20260726T054148Z.db`, snapshot
  directories named 20260717, 20260729, two 20260730 and a `.partial` 20260728 (UTC stamps), and five July `papers.db.bak-*` in the data root
  (~1.28 GB each). No scheduler, retention rule or restore procedure exists (RV-6 F-A1). Waymo and
  standards have recent snapshots (`snapshot-20261103T0318xxZ`, standards `…T0540xxZ`, plus per-batch
  `papers.db.pre-batch*` copies); Motional and Waabi have **no backup directory**.
- **Services (all down):** `rag-qdrant`, `rag-tei-reranker` and `rag-grobid` exited 255 together at
  2026-11-08T17:08:06Z (`docker inspect`: not OOM-killed; the common cause is not recorded in any
  log read). `rag-tei-embed` exited 1 at 2026-11-09T09:50Z — its last log lines end `Could not start
  backend: Could not start a suitable backend` — and cannot restart while an **Ollama
  `qwen3.8:27b-mtp-q4_K_M` runner (18,586 MiB of the 24,576 MiB card, state "Stopping…") holds the
  GPU** (`nvidia-smi --query-compute-apps`, `ollama ps`). Ownership of that process is an open
  operator question (§6). Nothing in this pass started or stopped any service.
- **What works without them:** SQLite-only reads and the CPU-only mode (`python -m app.doctor
  --cpu-only`, `docs/RUNBOOK.md` "GPU busy / CPU-only operation", OP-1). Anything needing the embedder,
  reranker or a live index (every retrieval benchmark, resparse/set-payload `--apply`, CQ-3's A/B) is
  blocked until the GPU is free.

### 1.4 Earlier Waymo build notes (2026-08-05..08, history)

Config changes from the v1 state, all applied by plan Task 3: `ingest_paper_ids` cleared (it held a
hand-pasted 1,437-id allowlist, duplicating what `--paper-ids-file` already does), `prefetch_target`
restored to 30000 from v1's neutering value of 1, `focus_area_queries` replaced with the 20-term
broadened-scope list, and `arxiv_date_from: '2015-01-01'` for the operator's cutoff.

The sidecar count is worth watching: it was **0** for the whole v1 era, because sidecars are written
by the downloader and v1 had neutered it. Every missing sidecar costs an arXiv metadata re-fetch at
ingest time, which is what produced the multi-minute per-batch stalls observed on 2026-08-07 before
`49b966a` got the downloader working again. (The 2026-08-07 `pdf_cache` and drop-in-tray counts that
used to sit here — 1,097 PDFs / 37 sidecars / 449 staged — were not re-measured and are not current.)

## 2. How to actually run it

Every flag below traces to an actual `add_argument`/argv line — no flag is inferred.

| Module | Key flags | Purpose |
|---|---|---|
| `app.build_corpus` | `--target N` (required), `--parse-workers`, `--events-path`, `--batch-size`, `--telemetry-poll-interval`, `--run-id` | Supervisor loop: repeatedly invokes `app.ingest` until `ingest_state` has `N` papers at `stage='done'` (`app/build_corpus.py:712-741`) |
| `app.ingest` | `--parse-workers`, `--limit`, `--scratch`, `--paper-ids-file`, `--no-preflight`, `--force`, `--events-path`, `--telemetry-poll-interval` | One harvest→parse→chunk→embed→store pass (`app/ingest.py:404-433`) |
| `app.parse_phase` | `--shard-index`, `--shard-count` | Runs Pass-1 parsing for one shard of a sharded run (`app/parse_phase.py:76-78`) |
| `app.prefetch_pdfs` | `--max-idle N`, `--log-every N` | Standalone PDF-backlog downloader, runs forever unless `--max-idle` bounds it (`app/prefetch_pdfs.py:344-364`) |
| `app.ingest_local` | `--stage-only`, `--drop-dir PATH`, `--dry-run` | Stages `drop_in/` PDFs into `pdf_cache` + a manifest, then normally invokes `app.ingest` (`app/ingest_local.py:340-354`) |
| `app.serve` | `--data-dir` (optional) | MCP server, **ten tools** registered by the `@mcp.tool()` decorators at `app/serve.py:127-263`: `semantic_search`, `scan_corpus`, `search_papers`, `scan_methods`, `list_methods`, `get_figures`, `get_section`, `corpus_stats`, `get_paper`, `get_span` (argparse `app/serve.py:52-64`). One process serves exactly one corpus; `--data-dir` is the only guard against serving the wrong one and it is the only tool path that refuses a missing DB (system review S-07) |
| `app.doctor` | `--no-auto-start`, `--check-mcp`, `--cpu-only` (OP-1) | Readiness check for TEI/vector-store/GROBID, auto-starts stopped containers by default; `--cpu-only` checks only the vector store and reference service and skips TEI, GPU headroom and the `.gpu.lock` check (`app/doctor.py:336-358`). It does not detect a foreign process holding the GPU (system review S-06) |
| `app.init_config` | `--data-dir` (required), `--force`, `--link` | Scaffolds a new corpus's `config.yaml` from `config.example.yaml` (`app/init_config.py:46-61`) |
| `app.rechunk` | `--config`, `--paper-ids`, `--paper-ids-file`, `--dry-run` | Re-chunks-from-blocks for already-ingested papers without a full re-ingest (`app/rechunk.py:262-275`) |
| `app.reindex_idf` | `--collection` (required), `--config`, `--dry-run`, `--i-have-a-snapshot`, `--backup-root`, `--keep N`, `--use-clone-swap`, `--vector-store-host/-port` | Adds the sparse IDF modifier to an existing collection (`app/reindex_idf.py:204-238`) |
| `app.resparse` (CQ-2) | `--collection` (required, no default), `--config`, `--dry-run` (default) / `--apply`, `--i-have-a-snapshot`, `--target-is-clone` + `--clone-of`, `--verify-sample N`, `--batch-size`, `--backup-root`, `--vector-store-host/-port` | Recomputes the sparse vector of every point in place from stored chunk text, without re-embedding; needed after CQ-1's ligature repair. Never run against a live index (`app/resparse.py:184-199`; runbook `docs/eval-reports/2026-11-10-cq2-index-maintenance.md`) |
| `app.set_payload_fields` (CQ-2) | `--collection` and `--only-fields` (required), `--build relevance_score\|topic_label` or `--mapping-file`, `--db`, `--labels`, `--dry-run` (default) / `--apply`, `--i-have-a-snapshot`, `--target-is-clone`, `--clone-of`, `--config`, `--backup-root`, `--vector-store-host/-port` | Writes allow-listed payload keys on existing points without re-embedding (`app/set_payload_fields.py:193-210`). Never run against a live index |
| `app.delete_docs` | `PAPER_ID [PAPER_ID ...]` (positional), `--yes` (required to actually delete) | Cascade-deletes papers (chunks/blocks/summaries/vectors) (`app/delete_docs.py:54-58`) |
| `app.snapshot` | `--config`, `--backup-root`, `--keep N`, `--vector-store-host/-port` | Takes/prunes Qdrant collection snapshots (`app/snapshot.py:222-235`) |
| `app.obsidian_export` | `--config`, `--out-dir`, `--limit N` | Exports papers as an Obsidian vault (`app/obsidian_export.py:187-195`) |
| `app.corpus_integrity` | none (module-level `main()`, reads `Config` directly) | Standing check: every `done` paper has ≥1 chunk and ≥1 block row (`app/corpus_integrity.py`) |
| `app.dashboard.server` | `--port` (default 8700), `--data-dir` (required), `--token`, `--host` (default `0.0.0.0`) | Corpus dashboard web server (`app/dashboard/server.py:671-684`) |
| `app.dashboard.verify_numbers` | `--data-dir` (required), `--host`, `--port` | Independent cross-check of the dashboard's own numbers against ground truth (`app/dashboard/verify_numbers.py:580-583`) |
| `app.mcp_verify_client` | `QUERY` (positional, optional), `--k`, `--data-dir` (optional — corpus dir for the spawned server) | Full query→citation MCP round trip over real stdio (`app/mcp_verify_client.py`); `--data-dir waymo/data` targets a non-default corpus |
| `migrations/migrate.py` | `python migrations/migrate.py <path/to/db.sqlite>` (positional, no argparse) | Applies every unapplied `000N_*.sql` file to a DB, idempotently |

### Traps

- **(a) No `--data-dir` on ingest-side tools.** `app.build_corpus`, `app.ingest`, `app.parse_phase`,
  `app.prefetch_pdfs`, `app.ingest_local`, `app.rechunk`, `app.reindex_idf`, `app.delete_docs`,
  `app.snapshot`, `app.obsidian_export`, `app.corpus_integrity` have no such flag — **your shell's
  cwd IS the data dir** (`rag/config.py`'s discovery precedence starts at cwd). Run them from inside
  the corpus's data directory, or set `RAG_CONFIG`.
- **(b) Exactly 4 tools DO take `--data-dir`**: `app.init_config` (required — it's creating the dir),
  `app.serve` (optional, falls back to plain `load_config()`), `app.dashboard.server` (required),
  `app.dashboard.verify_numbers` (required).
- **(c) `config.yaml`'s path fields resolve against the config file's own directory, not cwd**
  (T-DOC89 §1, `rag/config.py:9-12,44-62`). `db_path: "papers.db"` in a config always means "next to
  that config file," wherever it's loaded from — loading the same file from two different cwds
  yields identical absolute paths.
- **(d) Dashboard auth is split by route** (`app/dashboard/server.py:412-438`): `GET /` is open (no
  corpus content, just the static frontend). `GET /api/status`, `GET /api/search`, and
  `POST /api/control` all require a valid `X-Dashboard-Token` header, checked with
  `hmac.compare_digest` (constant-time). The token lives at `<data-dir>/.dashboard_token` (mode
  `0600`, auto-generated on first run if absent, T-DOC78) unless `--token` overrides it.

### Second corpus = second directory

A second corpus is nothing more than a second directory holding its own `config.yaml`. Create one
with `python -m app.init_config --data-dir <dir>`, then select it either by `cd`-ing into it before
running an ingest-side tool (cwd-is-data-dir, trap (a) above) or by passing `--data-dir <dir>` to one
of the 4 tools that support it (trap (b)). All five corpora in §1.1 follow this pattern — see each directory's
`config.yaml`. Two things `app.init_config` does not do for you: it writes a private `gpu_lock_path`
(`config.example.yaml:108` default `.gpu.lock`, resolved under the new directory), which must be edited to
the shared `/home/omar/ai-projects/research-system-rag/.gpu.lock` that all five existing configs use, and
it leaves `collection` at the template value, which must be made distinct (`docs/RUNBOOK.md` "Running a
second corpus").

## 3. Shipped-work ledger

### Next-build programme — NB series (2026-08-…)

- **NB-D4** (2026-08-25, branch `NB-D4-eval-runner`): the dual-fixture evaluation ruler —
  `scripts/nb_eval_runner.py` runs BOTH Waymo ground-truth fixtures (`gt_wmr.json`,
  `waymo_gt_verified.json`) against the live config in one command by subprocess-orchestrating
  `app/retrieval_eval` per fixture (the reuse seam; no evaluation logic rewritten), with a
  silent-death artifact guard and a never-blend split of the answerable arm
  (R@10/MRR/block-P@1 with denominators) from the known-absent arm. Unit tests:
  `scripts/test_nb_eval_runner.py` (synthetic reports, zero-GPU/network). First committed run
  (`docs/eval-reports/data/2026-08-25-nb-d4-dual-fixture-SAMPLE.*`, tag SAMPLE): gt_wmr 68/70 =
  0.9714 R@10 / 0.9393 MRR / 48/65 = 0.7385 block-P@1; ver84 65/68 = 0.9559 / 0.8335 / 22/60 =
  0.3667; absent arms 12 and 14, all with confident top results. The two R@10 figures reproduce
  handoff §0's live-w=0.7 headline numbers exactly. block-P@1 denominators are VARM-1's
  text_answerable arm (65/60), so they are NOT directly comparable to PREC-1's pre-VARM-1
  66/64-denominator figures.

### V0 core — M1-M9, owners A-F

All six owner tracks landed on `main` during the original build. Ticket-by-ticket detail (PR
numbers per module) lived in `AGENTS.md`'s old owner table; see §5's note below on why that table is
gone. Summary: Harvester/Orchestrator (owner A), Parser (owner B, MinerU locked at Spike 1,
`phase0-results.md`), Chunker/Summarizer/Embedder (owner C), DocumentStore/VectorIndex (owner D),
Retriever/McpServer (owner E), shared foundation `contracts/`+`rag/config.py`+migrations (owner F).
`ARCHITECTURE.md`'s M1-M9 section still accurately describes this module boundary — verified against
current `contracts/` and `rag/` layout 2026-08-05.

### T-DOC1-95 — hardening tickets

93 `T-DOC<n>` fix commits appear in `WORK-BREAKDOWN.md`, numbered up to **T-DOC95** (`grep -oE
"T-DOC[0-9]+" WORK-BREAKDOWN.md | sort -u | tail -1`). 224 commits on `main` reference a `T-DOC1[5-9]`
or `T-DOC[2-9][0-9]` ticket ID (`git log --oneline main | grep -cE 'T-DOC1[5-9]|T-DOC[2-9][0-9]'`).
See §4 for the specific war stories this doc covers in detail.

### Book integration

Books enter via `drop_in/`, get chapter-split, chapter-summarized, and chapter-embedded
(`doc_type="book"`, T-DOC80/82). Full closeout, including every approach tried and rejected:
`docs/BOOK-INTEGRATION-CLOSEOUT.md`. Current corpus: 5 books (§1 table).

### Drop-in folder

`app/ingest_local.py` scans `drop_in_dir` (default `drop_in/`, `contracts/config.py:76`) for
`papers/` and `books/` subfolders, stages matching PDFs into `pdf_cache`, writes a manifest, then
invokes `app.ingest` — same idempotency spine as the arXiv path. Shipped as a first-class dashboard
run type in D-1 (PR #208).

### Dashboard + telemetry — D-0 through D-12

Full live ledger: `docs/BACKLOG.md` lines 11-30. D-0 through D-10 are **DONE** (PRs #206-#227,
committed to specific SHAs in §4 for the ones this doc covers as war stories). D-11 and D-12 are
listed `OPEN` in `docs/BACKLOG.md` as of 2026-08-05, **but both fixes are already on `main`**:
D-11 via `4e07eb4` ("D-11: archive run logs on the failed transition, not only on done") and D-12 via
`f351a27` ("D-12: match the downloader by argv, not substring; make the cross-check independent") —
verified `git log --oneline main --grep="D-11"` / `--grep="D-12"` both return hits. `BACKLOG.md`'s
status column for these two items has not been updated to reflect the merge; this doc reports what
git actually shows, per this workstream's brief (not editing `BACKLOG.md`).

### MCP usage telemetry

`app/usage_log.py`: every `semantic_search`/`search_papers`/`get_paper`/`get_span` call (from both
the MCP server and the dashboard's `/api/search`) is recorded into a **separate** SQLite database,
`<data_dir>/mcp_usage.db` — deliberately not a table in `papers.db`, so it needs no migration or
foundation sign-off (`app/usage_log.py:1-15`). Shipped D-2a (PR #207, store + `app/serve.py`
instrumentation) and D-2b (PR #209, dashboard `usage` panel).

### Author-org tagging (NEW, undocumented elsewhere — shipped 2026-08-05)

Design: `docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md`. Motivated by the
Waymo corpus expansion — answers "which papers were actually written by org X's own team, vs.
researchers merely using their public datasets." Two-step pipeline, deliberately decoupled so a new
org can be added later with zero re-parsing:

1. **Extraction** (`raw_affiliations: list[str]`) — candidate text is every page-0 `Block` that is
   either front matter (`section_path==""`) or contains `@` (`rag/author_org_tagger.py`
   `_is_candidate_affiliation_block`). Two extraction methods exist, both shipped for comparison:
   - Rule-based (regex, `rag/author_org_tagger.py::extract_affiliations_rule_based`) — no vendor
     dependency.
   - LLM-based (`rag/summarizer.py::OllamaSummarizer.extract_affiliations`, commit `de89902`) —
     hardened (`46f50c2`) after paper `2201.12003` broke `json.loads` on a literal backslash the
     model echoed from a LaTeX-style institution name; also wraps untrusted page text in
     BEGIN/END markers against prompt injection.
2. **Matching** (`rag/author_org_tagger.py::match_known_orgs`) — cheap, re-runnable string matching
   against `contracts/author_orgs.py`'s `KNOWN_ORGS` roster (currently one entry: Waymo, matched by
   `email_domains=["waymo.com"]` and `keywords=["waymo"]`).

Validation harness: `app/exp_author_org_tagging.py` (throwaway `app/exp_*` script, measures
precision/recall for both extraction methods against a real positive set and a sampled negative set
from the existing corpus). Not yet backfilled onto the existing 12,390-paper corpus by design (§3
"Non-goals" in the spec doc) — the mechanism doesn't require backfill to ship.

### Waymo second-corpus attempt

**v1 (2026-08-05) stalled at 17 done / 810 stranded** — post-mortem in `docs/WAYMO-CORPUS-STATUS.md`.

**v2 (2026-08-06/07) — plan merged, setup shipped, build executing.** Plan:
`docs/superpowers/plans/2026-08-06-waymo-av-safety-corpus-expansion-v2.md`. Landed in PR #238
(`cfae593` and below): the arXiv scout brought onto `main` and extended from the narrow v1 scope to
the operator's 11 topic areas (`scripts/waymo_arxiv_scout.py`, 12 tests);
`fixtures/waymo/waymo_authored_ids.txt`, the 114 Waymo-authored arXiv ids enumerated off Waymo's own
two research index pages (re-fetch-verified current 2026-08-07, `54df0dc`); and `waymo/data/config.yaml`
reconfigured off v1's hand-edits. Live numbers in §1.

Three real defects were found by *running* it, each fixed with a regression test — see §4.

### Corpus-build fixes found in execution (2026-08-07)

| fix | commit | what it was |
|---|---|---|
| Harvester emitted a wildcard arXiv rejects | `49b966a` | A one-sided `arxiv_date_from` produced `submittedDate:[<from> TO *]`; arXiv answers that with HTTP 500. Since 500 is retryable, harvests burned their retries and reported `0 distinct paper(s)`, which the downloader logged as "0 new available" before sleeping an hour — so an ordinary 2015 cutoff **silently disabled the downloader** while looking like supply exhaustion. Both open ends now emit concrete bounds. After the fix the same harvest found **596 candidates / 306 to download** where it had found 0. |
| Dashboard consistency panel read the wrong corpus | `4cc164f` | `read_consistency` fell back to the hardcoded `"papers"` collection whenever no run was in the manifest, so an idle Waymo dashboard reported the **main** corpus's 412,167 points beside its own `sqlite_done: 17` and called it `consistent: true` — a false pass on the OG-16/T-DOC35 check. Now falls back to the data dir's own configured collection. |
| Scout's 12 tests never ran in CI | `c3765c9` | `scripts/` was absent from `pyproject.toml` `testpaths`. |

### Affiliation retrieval — measured, and it does not work (2026-08-07)

Report: `docs/eval-reports/2026-08-07-affiliation-retrieval-first-batch.md`. Run over the first 134
done Waymo papers, the authorship signal flagged 36 as Waymo-authored and **none of them are**
(precision 0.000); 35 of the 36 also fire the topical `mentions_orgs`. Root cause:
`_is_candidate_affiliation_block` accepts any page-0 front-matter block, which includes the
**abstract** — so any paper benchmarking on a Waymo dataset keyword-matches. This is why the v2 plan
sources the Waymo-vs-other split from the enumerated id list rather than the tagger, and why
`T-ORG1` (wiring tagging into ingest) is now **blocked by `T-ORG2`**: persisting a 0.000-precision
tag would bake a wrong answer into the schema. It does **not** affect the corpus build, which never
calls the tagger.

### T-ORG2 fixed, T-ORG1 wired into ingest (2026-08-08)

**T-ORG2 (commit `d3e79c3`):** the abstract-as-affiliation bug above is fixed — candidate blocks are
now capped at 40 words, with an email-address override so a genuine affiliation merged into a longer
block by the parser isn't dropped (front-matter blocks containing "waymo" run a median of 6 words in
genuinely Waymo-authored papers vs. 166 in the rest). Measured live over the 1,741 done papers against
the 114 enumerated Waymo-authored ids: **precision 0.569, recall 0.763** (pre-fix, correctly measured
against the same 114 ids: 0.311/0.851 — the 0.000/0.043 numbers reported on 2026-08-07 above were
measured before those 114 known-positive papers were ingested, so they undercounted true positives the
sample hadn't seen yet, not a different bug). Email-domain-only matching scores precision 0.700 but
recall only 0.123 (81% of extracted affiliation regions carry no email at all).

**T-ORG1 (`migrations/0005_author_orgs.sql`):** wires the tagger into the ingest pipeline, but
deliberately does NOT persist a bare "authored by org X" boolean — at 0.569 precision, close to half of
keyword-derived tags are wrong, so baking that straight into a boolean would bake the errors in too.
`papers.raw_affiliations`/`papers.author_orgs` (both nullable JSON — no sensible default for a row the
tagger has never run against) carry the evidence and, per match, which signal fired:
`rag/author_org_tagger.py::match_known_orgs_with_method` returns `AuthorOrgMatch(name, method)` with
`method` one of `"email_domain"`/`"keyword"` (`email_domain` wins when both fire for the same org, since
it's the higher-precision one) — `contracts/author_orgs.py`. `rag/orchestrator.py::_finish` computes both
fields during ingest (pure, no new I/O — a regex scan over already-parsed blocks plus a substring check).
`contracts/vector_index.py` adds `SearchFilters.author_org`/`VectorPayload.author_orgs` (names only) so
"papers by org X" is queryable via `semantic_search`/`search_papers`; both tool docstrings now state the
measured precision/recall plainly. `match_known_orgs` (existing `list[str]`-returning callers, e.g.
`app/exp_author_org_tagging.py`) is now a thin wrapper over `match_known_orgs_with_method` — one matching
implementation, not two that can drift.

**Not authoritative — this is a derived, imperfect signal, not ground truth.** The enumerated id list
(`fixtures/waymo/waymo_authored_ids.txt`) remains the exact, free source for the Waymo-authored-vs-
adjacent split used elsewhere in this corpus build; `author_orgs`/the `author_org` filter are for
open-ended "find papers plausibly authored by org X" queries where an enumerated list doesn't exist,
not for anything where a wrong tag is costly.

### T-ORG3: the curated tier — wiring the enumerated list in as a first-class method (2026-08-08)

The section above already names the fix for a wrong tag being costly: the enumerated id list. T-ORG3
(commit `0498e82`) wires that list into the tagging pipeline itself, as a third `AuthorOrgMatch.method`
value, `"curated"` (`contracts/author_orgs.py`) — rather than the operator having to know to reach for
`fixtures/waymo/waymo_authored_ids.txt` separately every time. The trigger: T-ORG1's heuristic measures
precision 0.706 / recall 0.783 at the corrected 138-id ground truth (`docs/eval-reports/2026-08-07-
affiliation-retrieval-first-batch.md`'s 2026-08-08 addendum — the 0.569/0.763 numbers in the T-ORG2
writeup above are now stale relative to this; the ground truth grew 114 → 138 with zero classifier
change, see that addendum for the correction). That's fine for open-ended discovery, but the operator's
actual use case — understanding Waymo's technical stack from Waymo's own papers — needs zero false
positives, and the dominant false-positive shape ("1st Place Solution for Waymo Open Dataset Challenge"
-type papers, another team competing on Waymo's public benchmark) is one a keyword matcher will never
get to zero on. The curated list, built from Waymo's own two research-index pages, gives 0 FP / 0 FN by
construction over the 138 ids — an enumerated fact from the org itself, not a measured approximation.

**Design:** `AuthorOrgTag.curated_ids_path` (`contracts/author_orgs.py`) is an optional path, resolved
relative to the repo root, defaulting to `None` — an org that doesn't opt in gets no curated matches and
no behavior change. Waymo's `KNOWN_ORGS` entry points it at the existing fixture file; this keeps
`rag/` free of any Waymo-specific path (the seam works for any corpus/org). `rag/author_org_tagger.py::
curated_orgs_for(paper_id)` is a pure id lookup against the org's list, independent of
`extract_affiliations_rule_based`/`match_known_orgs_with_method` by design — a curated match must not
depend on (or be defeated by) whatever the heuristic scan does or doesn't find in a paper's parsed text.
The file is read once per run and cached in a module-level dict keyed by path — ingest calls this once
per paper (`rag/orchestrator.py::_finish`), so a naive re-read would hit the 138-line file 1,741 times
for nothing. `rag/orchestrator.py::_finish` merges `curated_orgs_for()` with the existing heuristic
result (`_merge_author_orgs`), `curated` winning over `email_domain`/`keyword` for the same org name.

**Making the correctness path queryable, not just stored:** `contracts/vector_index.py` adds
`SearchFilters.author_org_curated_only: bool` (only takes effect combined with `author_org`; a no-op on
its own, same as every other filter field meaning "don't filter on this") and
`VectorPayload.curated_author_orgs: list[str]` (the `method=="curated"` subset of `author_orgs`,
populated in `rag/orchestrator.py`'s `_upsert_record`). `rag/vector_index.py`/`rag/fakes/fake_vector_store.py`
switch the filtered payload key to `curated_author_orgs` when the flag is set — same `.get([])`-default
legacy-point handling as every other list-valued filter field here. `rag/mcp_server.py`'s
`semantic_search`/`search_papers` docstrings now state plainly that `curated` is exact and the heuristic
tiers are ~0.71 precision, and that a caller asking "what does Waymo's own research say" should set
`author_org_curated_only=True`.

**No migration.** `papers.author_orgs` was already a JSON `TEXT` column (`migrations/0005_author_orgs.sql`)
— `"curated"` is a `Literal`-only widening of the same JSON shape, confirmed by a committed round-trip
test rather than assumed.

**Verified, read-only, against the live corpus:** all 138 curated ids resolve via `curated_orgs_for`
(no `waymo/data/` writes, no ingest run) — and the real challenge-paper false positive `2006.15505`
("1st Place Solution"-style, not Waymo-authored) correctly gets no curated match.

### Enhancement programme — 2026-11-10 (branch `EP-programme-20261110`, `git log --oneline main..HEAD`)

All of this exists as committed code, data and reports on the integration branch `EP-programme-20261110`
(not on `main`; nothing pushed). **No retrieval benchmark, index change or GPU job from this programme has
been run** — the embedder, reranker and Qdrant are down and the GPU is held (§1.3) — so every "not yet
applied/measured" below is literally true on 2026-11-10. Orientation: `docs/eval-reports/2026-11-10-system-review.md`
(adjudicated review, below) ranks the follow-up work; `docs/eval-reports/2026-11-10-GPU-DAY-RUNBOOK.md`
sequences the first GPU session. The programme plan is `docs/superpowers/plans/2026-11-10-enhancement-programme.md`
(being written in parallel with this pass; referenced by path only).

| item | what exists (SHA) | NOT yet applied / measured |
|---|---|---|
| **Ground-truth sets** (EP-0) | Three LLM-authored, blind-authored, cross-verified passage-level sets: standards 128 items (`173fe4e`, with `AUTHORING-PROTOCOL.md`), causal books 74 (`f119f30`), main-paper passages 61 (`0c9483e`), under `docs/eval-reports/data/2026-11-10-{standards,causal-books,papers-passage}-gt/`. SHA-256 of every fixture of record frozen before any run (`9236e7a`, `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`; `focus_gt.json` still `null`) | Never run against retrieval. Not instruments of record yet: the scorer ignores `alternative_gold_chunk_ids` (up to 13% under-count), gold is chunk identity bound to one chunker, authors and verifiers share a model family, questions are ~2× longer than logged queries (system review §2). Not promoted to `fixtures/eval/` (foundation-protected) |
| **Topic labels + audit** (EV-1/2/3) | on/borderline/off label for all 12,385 main papers (`5f54fb4`, `docs/eval-reports/data/2026-11-10-topic-labels/topic_labels.tsv`); blind 300-paper audit, kappa 0.901, binary agreement 0.975, ACCEPTED; `relevance_score` AUROC 0.923 on on-vs-off (`9a2c6fb`, `4766c8c`, `1975b81`, merge `eb4d993`; `docs/eval-reports/2026-11-10-topic-labels-audit.md`) | Labels are not in the vector payload and nothing filters or demotes on them (operator keeps the off-topic papers). Proposed `relevance_score` thresholds 0.25/0.30 not applied. Auditor is the same model family: consistency, not truth |
| **Benchmark protocols + GPU-day runbook** (EV-5) | Frozen protocols for standards (`7782a0f`; includes the rerank-depth 128 vs 32 decision rule), main (`2a017de`), topic focus (`ba78d4a`), `scripts/eval_protocol_tools.py` (hash check, point-count guard, title ablation, split, Wilson; `6d4526d`, `0728e16`), cheapest-first runbook (`882a086`); merge `b9be4c8` | Nothing in them has been run. The relevance-demotion adoption rule is pre-registered, not applied. System review S-02/S-03/S-05 amend them before the first run |
| **Ligature repair** (CQ-1) | `rag/ligatures.py` + `rag/ligature_map.json` (227 mappings) + builder `scripts/build_ligature_map.py` (`ca65f68`), applied inside `_sparse_vector` (index and query side) and `scan_blocks` (`05b34ee`), review runs (`5906f2e`); merge `56d24d0`. Measured: changes none of 1,217 recorded queries, improves `scan_corpus` (system review §4) | No collection has been resparsed, so query-side repair against unrepaired stored sparse vectors is a deployment hazard until `app.resparse` runs (`docs/eval-reports/2026-11-10-cq2-index-maintenance.md` §1). Dense side not repaired. Retrieval gain unmeasured |
| **Index-maintenance methods** (CQ-2) | `VectorIndex.resparse`, `set_payload` and read-only sampling helpers (`79d44d3`), `relevance_score` added to the shared vector payload (`79d29a0`, new ingests only), CLIs `app.resparse` / `app.set_payload_fields` with apply guards (`586095a`), runbook (`9ce36dc`); merge `655b384` | Mocked-client unit tests only; never run against a live index; time and size figures are estimates |
| **Stub-chunk filter** (CQ-3) | `scripts/list_stub_chunks.py`, `drop_stub_chunks` flag on `Retriever` and `--drop-stub-chunks` on `app.retrieval_eval`, default off, reversible (`e984fb9`, `d39a094`, pre-registration `de520e4`; merge `720f77d`; `docs/eval-reports/2026-11-10-cq3-stub-chunks.md`) | A/B not run; stubs still sit in every index (7-10% of chunks). System review S-05 tightens the pre-registration (no minimum effect size; three different stub thresholds) |
| **CPU-only mode** (OP-1) | `python -m app.doctor --cpu-only` and fail-fast on TEI/Qdrant down (`2e51b4f`, `8de3ad3`; merge `564582a`); runbook section "GPU busy / CPU-only operation" | Covers "TEI down" only; does not detect a foreign GPU holder or a held lock (300 s wait) — system review S-06 |
| **Censuses** (EP-0, CQ-6) | Chunk-quality census instrument (`368ce55`, `scripts/chunk_quality_census.py`); off-topic, ligature and embed-truncation censuses (`09cb847`); duplicate-document and reference-content census (`4a8feae`, merge `23fc2d2`); per-stratum report script `scripts/eval_strata_report.py` (EV-6, `e4f2fed`, merge `c06b411`) | Figures are in §1.2. EV-6's script has tests but no recorded run on real retrieval output. Embed truncation is not fixed (needs `--max-batch-tokens` change and re-embed); no duplicate has been removed |
| **Chunker repair on standards** (T-RAG) | `8301342`, `5eadd35` (2026-11-01): extraction joins, definition boundaries, oversized-table bounding; the whole standards corpus (119 docs) was built with it | On `EP-programme-20261110` only, not `main`; main, Waymo, Motional and Waabi still hold legacy-chunker chunks (§1.1) |
| **System review** (RV-1..6 + adjudication) | Lane findings `b4c2b43`, `e796cc9`; adjudicated findings and ranked work list `364aa13` (`docs/eval-reports/2026-11-10-system-review.md`) | Its groups (A)-(F) are recommendations; none is implemented. Group (F) operator questions are in §6 |
| **This pass** (EP-1) | Drift correction of this file, README, AGENTS.md, RUNBOOK corpus facts (branch `EP-EP1-docs-drift`) | Plan checkboxes in `docs/superpowers/plans/2026-08-25-precision95-programme.md`, `docs/DECISIONS-PENDING-operator.md`'s contradictory line and the stale `docs/BACKLOG.md` rows were out of this ticket's ownership — see the hand-over list in its report |

**In progress on other branches (mentioned only; not verified here):** EV-4 focus ground truth
(`EP-EV4-focus-gt`), CQ-5 standards metadata (`EP-CQ5-standards-metadata`), CQ-4 truncation re-chunk plan
(`EP-CQ4-truncation-rechunk-plan`), EP-2 ticket set (`EP-EP2-ticket-set`).

## 4. Problems faced → solution landed

**MinerU VRAM peak measurement correction (T-DOC15).** `ARCHITECTURE.md`/`CONVENTIONS.md` originally
claimed a flat ~6.6GB MinerU footprint, "fits comfortably" alongside Embedder+Reranker (~9.4GB) on a
24GB card. Real measurement (commit `ae9340d`/`7437246`, same content on two branches) found MinerU's
pipeline backend loads layout-detection/OCR/table/formula sub-models sequentially per paper, so its
footprint is **not flat** — it peaks around ~13GB routinely, observed as high as ~23.7GB/24GB (96.4%
of the card) during real Pass-1 runs. Real safety margin: ~1GB, not "comfortable." Flagged as an open
risk, not fixed in that commit.

**The GPU lock design (`rag/gpu_lock.py`, `rag/embedder.py:151`).** `FileGpuLock` wraps
`filelock.FileLock` so `IngestionOrchestrator` and `McpServer` — built from the same
`Config.gpu_lock_path` — serialize GPU access against each other. Critically, in
`rag/embedder.py::_post_batch_with_retry`, the lock (`self._gpu_lock.acquire("embed", ...)`) is
acquired **only around the single HTTP attempt** (one `with` block wrapping one `self._client.post`
call), not across the retry loop — confirmed at `rag/embedder.py:151`: the `with` block exits (lock
released) before any `except` clause runs, so `self._retry_sleep(self._backoff(attempt))` always
sleeps with the lock already free. This is deliberate (OG-48#3, per the docstring at
`rag/embedder.py:143`): holding the lock across a multi-second exponential backoff would starve every
other GPU consumer for no benefit — the retry sleep needs no GPU.

**TEI eviction / self-healing (T-DOC78).** Largest single ticket family — 48+ commits (`git log
--oneline --all --grep="T-DOC78" -i`). Landed: on-demand GPU free/reload (`controller.free_gpu()` /
`load_for_mcp()`), a self-healing query path (`ensure_tei_running` health-check-first reload wired
into `TeiEmbedder`/`TeiReranker` via an optional `ensure_ready` hook), dashboard Free-GPU/Load-for-MCP
buttons with live TEI status, and a download-only run mode.

**GROBID 500s — three progressively-discovered root causes.** All three commits fix the *same*
symptom (GROBID 500ing an entire reference batch) at progressively deeper root causes:
1. `e4a4191` — blank/whitespace-only citations. MinerU sometimes emits an empty reference string;
   one blank in a batch 500s the whole batch (reproduced against GROBID 0.8.0: `3 good + 1 empty` →
   500, `3 good` alone → 200). Fix: drop blanks, count them.
2. `25543f1` — non-alphanumeric junk citations (e.g. `"."`, `"[]"`) that survive the blank filter.
   Fix: drop any citation with no alphanumeric character (a superset of the blank filter).
3. `fa70acd` — **the real root cause**: a raw C0 control byte (0x00-0x1F, excluding tab/LF/CR)
   leaking into otherwise-normal, alphanumeric-rich citation text where MinerU's PDF text layer
   failed to decode a glyph (typically an fi/ffi ligature, hyphen, or epsilon). The two prior filters
   were no-ops against this — the actual failing strings pass both. Fix: sanitize (strip C0 bytes),
   never drop a reference. Validated against all 7 sampled real failing batches: every one flips from
   500 to 200 with zero references lost. Tracked as O-2a in `docs/BACKLOG.md` (PR #221).

**Duplicate chunk headers (T-DOC62, `app/rechunk.py`).** Chunker was re-emitting a chunk's own
leading section heading inside the chunk body text (fix: `4b27ad3`, "de-dupe leading section heading
in chunk text"). Because the bug had already produced bad chunks in the live DB, a general
re-chunk-from-blocks retrofit tool, `app/rechunk.py`, was built (`4654fde`) to fix already-ingested
papers without a full re-ingest. A residue of the same class of bug was found later and fixed
separately under T-DOC93 (`863b6bc`, "heading-dedup residue -- overlap can carry a bare section
heading").

**The empty-papers.db fallback bug that faked Recall@10=0.000 (T-DOC56).** `build_mcp_server`
ignored `config.db_path`/`blob_dir` and silently fell back to an empty local `papers.db`, so any
retrieval eval run against it scored a fake 0.000 recall — not a real retrieval failure. Fix:
`ab1b663`, "build_mcp_server honors config.db_path/blob_dir". A related cleanup, `d550bf8`
(T-DOC67/OG-33), removed committed `pdf_cache` blobs and gitignored data cruft that had been
polluting the repo.

**Orphan-downloader false-positive fix (D-12, commit `f351a27`).** `status._live_prefetch_pids`
matched any `/proc/*/cmdline` containing the *substring* `app.prefetch_pdfs` — so a diagnostic
`pgrep -af "app.prefetch_pdfs"` or a `grep` naming the pattern counted itself as a live downloader,
tripping a spurious `orphan=True`. Fix follows the precedent `scripts/dashboard.sh` already set for
its own PID lookup: require `-m` immediately adjacent to `app.prefetch_pdfs` in argv
(`_is_prefetch_argv`), exclude the scanning process and its ancestors, and — critically — make
`verify_numbers.py`'s cross-check compute the ground truth via an **independently implemented**
predicate (`_has_prefetch_module_flag`, not shared code with `status.py`), so a shared bug in the two
readers can no longer launder itself past the cross-check as agreement.

**Supply-exhaustion reconciliation (O-1, commits `70940dc`, `f8a7f69`, `013f7cf`).** A run that
drained arXiv's supply for its configured queries (not a real failure) used to wait the full 60-
minute processing-stall guard, then log "giving up — check parse_workers/parse_batch_size aren't
misconfigured," blaming config for a supply fact, and reconcile as `failed`. Three-commit fix: (1)
`70940dc` — wait only 15 minutes and record `run_outcome_<run_id>.json` distinguishing
supply-exhaustion from a real processing stall; (2) `f8a7f69` — `controller._crashed_before_target`
reads that file and reconciles such a run `done`, not `failed`; (3) `013f7cf` — surface it in
`/api/status`/the run panel as "Completed -- arXiv exhausted for the current queries (N of M)," with
`verify_numbers.py` cross-checking `run.outcome` against the file read independently from disk.

## 5. Tried and failed / deliberately not shipped

All five book-RAG experiments below share one fixture (`fixtures/eval/eval_book_questions.json`) and
one pre-committed falsification criterion per experiment (`docs/PLAN-book-rag-experiments.md`). Full
reports: `docs/eval-reports/2026-07-29-exp{1..5}-*.md`.

- **Exp 1 — outline-based chapter split.** *Falsified.* Outline-based chapters do not beat the
  existing size-merge split on chapter-routing recall for any of the 4 outline-bearing books tested
  (2 tied, 2 declined, one severely) — size-merge wins per the pre-committed criterion.
- **Exp 2 — contextual retrieval (headered chunks), book-scoped.** *HOLD, not rejected* — same status
  T-DOC41's earlier paper-scale result already carried. A/B of headered vs. non-headered chunks over
  1,939 book chunks found an **exact zero delta**: 0 of 40 questions changed rank in either arm.
- **Exp 3 — hierarchy-as-routing simulation (Part→Chapter, H1).** *H1 should not be built.* Simulated
  two-step routing ties flat routing (0.250 recall either way) on the one book it could test, loses
  to size-merge (0.425) corpus-wide; the other 3 outline-bearing books have no coarser level to route
  through at all.
- **Exp 4 — section-aware boost/filter by `section_path`.** *Stopped before implementation.*
  `section_path` is present on 99.6% of the 5-book corpus's chunks (not sparse) but does not reliably
  distinguish Method/Results/Introduction-shaped content — the pre-authorized "report and stop rather
  than build over unusable data" outcome.
- **Exp 5 — scoping ceiling + Self-Route-style escalation.** *Fails to ship.* Neither the scoping
  ceiling measurement nor the escalation arm clears its falsification bar; two-stage "pick a book,
  then route within it" is not adopted.
- **T-DOC87 — chapter-marker regex repair.** Two separate verdicts, not to be conflated: the regex
  *correctness* fix (bare `^\d+\.\s+\S` alternative was matching 643 body-prose blocks, e.g. numbered
  list items, as false chapter boundaries) **shipped** (PR #204). The resulting **boundary change is
  explicitly NOT shipped to production** — re-ingesting under the new boundaries regressed one book's
  (Econ/Social/Health) chapter routing 2.8-3.5× past the noise floor. Tracked as `docs/BACKLOG.md`
  item B-3 ("OPEN / will not ship as-is").
- **MinerU-replacement ADR.** `reviews/PARSER-ALTERNATIVES-EVAL.md` (gitignored, still readable on
  disk) recommends **against** switching parsers — every credible alternative (Marker, Docling,
  external VLM parsers) regresses on scientific-equation fidelity, which this corpus is full of. The
  one option judged worth a Spike-1-style validation, MinerU's own `vlm` backend (MinerU2.5), was
  never adjudicated by the human CODEOWNER — status is "Recommendation, not yet a decision" as of
  its 2026-07-16 date, unchanged as of this doc's writing.

## 6. Open and known-broken

*Re-derived 2026-11-10 (ticket EP-1) from `docs/BACKLOG.md`, git, and the adjudicated system review
`docs/eval-reports/2026-11-10-system-review.md` (cited below as "review"); where the review and its lane
reports (RV-1..6) disagree, the review wins. `docs/BACKLOG.md` was not edited by this pass.*

### 6.1 Known-broken or unmeasured (the system's open problems)

Measured facts live in §1.2; this list is what is broken or unknown *because of* them, ranked by the review
(§3 groups (A)-(C), item ids S-nn).

- **No current, off-disk backup of the source-of-truth SQLite.** Newest main snapshot 2026-07-30; disk 98%
  full; no scheduler/retention/restore procedure (§1.3; review S-01, RV-6 F-A1). The only finding whose
  downside is unrecoverable.
- **The first GPU run would not yet be a baseline.** The eval harness rewrites its own fixture, measures
  whichever checkout is current, records no hash, defaults `--collection` to `papers`
  (`app/retrieval_eval.py:780`), and the scorer ignores `alternative_gold_chunk_ids` (review S-02, S-03).
  Fixtures were hashed (`9236e7a`) but the harness does not yet enforce it.
- **Every quality question on the new sets is unmeasured:** passage-level recall, whether stubs or
  ligatures cost results, whether off-topic papers enter answers, whether per-corpus depth/weight settings
  help (standards `rerank_depth` 128 vs 32 is an untested transplant), whether the cross-encoder score
  separates answerable from absent (the earlier "no floor" verdict tested rank arithmetic only; the reranker
  score is discarded at `rag/reranker.py:231`), and whether filtered searches lose results with no payload
  indexes (review §1 a, b; S-04, S-15, S-16).
- **Silent wrong answers:** an unknown `filters.paper_id` returns an empty result (review S-08); wrong-corpus
  guards cover only `app.serve --data-dir` (S-07); a held GPU lock looks like "service down" and a query
  waits up to 300 s (S-06).
- **Structure:** broken section paths for the standards and the 15 books, 7-10% stub chunks, 32% ligature
  damage in main, 0.79% truncated embeddings in main (§1.2). All have designed fixes (S-17, S-18, S-23,
  S-24); none is applied, and several need a GPU re-embed.
- **Chunker mix:** main, Waymo, Motional, Waabi hold legacy-chunker chunks, standards holds new-chunker
  chunks, with no version stamp. **Standing rule (review S-13): do not ingest into any live collection from
  this branch until S-17 and S-23 have decided** — it would mix chunker generations and sparse versions.
- **Containers cannot be recreated from tracked files**; Qdrant is unpinned `latest` over a 31 GB store
  (review S-12, RV-6 F-A2). The nightly real-adapter workflow has no runner (review §3 D(6), RV-6 F-A5).

Older queue items, from `docs/BACKLOG.md`, re-checked against git:

- **D-8** — bound retries for repeatedly-failing quarantined papers (OPEN, lower priority since O-2's fix).
- **D-9** — land the orphaned unexpected-exception safety net (`T-SEED-combined-fixes`, §8) — real
  unmerged work, but no longer "the only genuinely unmerged branch" (`docs/BACKLOG.md:222` already says so;
  `worktree-waymo-corpus-expansion` also has unmerged commits). `main` has no catch-all for an unforeseen
  exception.
- **D-11 / D-12** — **DONE**, and `docs/BACKLOG.md:224-225` already says so (`4e07eb4`, `f351a27`, both
  ancestors of the integration branch). The previous version of this section called BACKLOG's rows stale;
  that was itself stale and is withdrawn.
- **B-1, B-2** — TOC pages as headings; junk chapter titles (OPEN).
- **B-3** — T-DOC87 boundary change will not ship as-is (§5).
- **B-4** — remove the unused outline splitter: review date 2026-08-29 is **73 days overdue**; operator to
  remove or extend.
- **B-5** — `reindex_idf` default flip: the underlying need is moot (sparse IDF is on all five collections,
  §1.1; review §3 E marks the tool historical).
- **O-2b** — GROBID "unparseable TEI" (6 papers); **O-3** — a stale `git stash` entry of unknown provenance.
- **FD-1 (figure images lost)** — resolved *going forward*: RI-18 (`f92bd8f`, `migrations/0006_figures_tables.sql`)
  persists figures/tables, and Waymo, standards, Motional and Waabi hold them (§1.2). **Not resolved for
  main**: its `figures`/`tables` tables hold 0 rows and the 12,390-paper parse's images are gone; only a
  re-parse (GPU) recovers them.

### 6.2 Pending operator decisions (not agent work)

| # | decision | recorded in | what it blocks |
|---|---|---|---|
| 1 | **Ratify (sign) the metric ratification, P0-2 — or retire it** in favour of the review's S-02 addenda (review F8). Unsigned `Signed: ___` | `docs/eval-reports/2026-08-26-precision95-metric-ratification.md:3-9`; BACKLOG P0-2 row; §3b | IN-1; any headline "0.95" claim |
| 2 | **T-F7: approve the member-block citation rider PR** (Variant A; touches `contracts/` and DATA-CONTRACTS §M7, foundation-protected). Review §3 D batches it with the other foundation changes into one rider after the S-16 baselines | `docs/design-notes/2026-08-28-xc-member-citation-adoption.md`; BACKLOG T-F7 row | QW-1 implementation (gt_wmr passage hit 93.9% → 95.5%, measured); IN-1 |
| 3 | **Claim-layer design sign-off** — `docs/DESIGN-claim-layer-v1.md` is headed "Foundation change — needs sign-off before build"; no sign-off is recorded anywhere | `docs/DESIGN-claim-layer-v1.md:3`; `PRD.md` ADR-12 | every V1 claim-layer ticket (nothing is built) |
| 4 | **MinerU `vlm` backend spike** (the one parser option judged worth a Spike-1-style validation) never adjudicated — "Recommendation, not yet a decision" since 2026-07-16 | `reviews/PARSER-ALTERNATIVES-EVAL.md` (gitignored, on disk); §5 | any parser swap; also the OCR/ligature damage that the parser, not the chunker, causes |
| 5 | Backups: is there any device or remote for an off-disk copy? After a fresh verified snapshot, may the five July `.bak` files (6.4 GB), the 07-28 `.partial` and two of the three July snapshots be deleted? (review F1) | review §3 F1; §1.3 | S-01; any re-embed on a 98%-full disk |
| 6 | May Qdrant (CPU only) be started for clone measurements (S-15, S-17)? ~6-8 GB per clone of the 90 GB free (review F2) | review F2 | Wave 1 of the review's wave map |
| 7 | Who owns the Ollama `qwen3.8:27b-mtp-q4_K_M` process (18.6 GB, wedged "Stopping…")? May it be stopped? It is what blocks the GPU and `rag-tei-embed` (review F3) | review F3; §1.3 | every GPU job (S-16 and everything after) |
| 8 | Push the local commits so CI judges them: yes or no? (review F4) | review F4 | CI evidence for the whole programme |
| 9 | May the MCP wire be a projection of the frozen envelope (drop `bbox`, duplicate `snippet`/`paper_id`)? (review F5) | review F5, S-26 | envelope slimming |
| 10 | Focus lever: is "demote, never drop, opt-in" the only acceptable form, and what off-topic share in the top 10 counts as material? (review F6) | review F6; `docs/eval-reports/2026-11-10-topic-focus-benchmark-protocol.md` | S-21 |
| 11 | If S-24's gate passes, may stored `Block.section_path` be rewritten for standards (and a ~35k re-embed run), or must the corrected path live in a derived column? (review F7) | review F7; RV-2 open question 1 | S-24 |
| 12 | Decision 4 — duplicate chapter titles: option A (disambiguate) was never built; marker regex repair shipped but its boundary change does not (B-3) | `docs/DECISIONS-PENDING-operator.md` banner + §Decision 4 | addressability of 16 of 101 chapter units |
| 13 | Operator rulings still open from the 2026-08-22 review series: self-hosted CI runner, corpus-target conflict (15k/30k/12.4k), reviewer findings R4/R5, RI-2 empty-token policy | `docs/superpowers/plans/2026-08-22-review-implementation.md:246-252` | closing the RI series |

**Closed — do not re-ask (verified 2026-11-10; two lane claims withdrawn):**
- **IDF reindex ("Decision 1" of `docs/DECISIONS-PENDING-operator.md`) is closed:** every collection's
  `config.json` carries `sparse.modifier = "idf"` (§1.1), and the review adjudicates it as already applied on
  all five. RV-6 B.3 row 3 listing it as pending is wrong, as is §7's earlier "Decision 1 still genuinely
  open". What `DECISIONS-PENDING` still lacks is the recorded evidence; this paragraph is it.
- `hybrid_dense_weight` on Waymo: **decided 0.7** by the operator on 2026-08-24 (§3b "Operator tuning
  decision"), "until another corpus is benchmarked". RV-6 B.3 row 5 / punch-list row 16(a) call it still
  undecided; it is decided, and the other four corpora deliberately stay at 0.5.
- Fabrication/groundedness rubric: groundedness rubric **SIGNED OFF 2026-08-24**
  (`docs/eval-rubrics/groundedness-rubric.md:3`); fabrication rubric **SIGNED OFF 2026-08-25 with
  amendments F-A1..F-A3** (`docs/eval-rubrics/fabrication-audit-rubric.md:12`, `6d0b32b`). RV-6 B.3 row 6 is
  wrong on both counts. OpenEvidence head-to-head: operator decision D "out of scope this programme" (§3b).
- Off-topic papers: **kept**, labelled (§1.2).

## 7. Doc map

Every markdown file at repo root (`find . -maxdepth 2 -name '*.md'`) and under `docs/`
(`find docs -name '*.md'`), classified AUTHORITATIVE / REFERENCE / HISTORICAL:

### Repo root

| Doc | Class | Notes |
|---|---|---|
| `AGENTS.md` | AUTHORITATIVE | Entry-point index — start here. |
| `CLAUDE.md` | AUTHORITATIVE | A five-line pointer to `AGENTS.md` (no second copy of the content), so Claude Code's auto-load finds the index. |
| `CONTEXT.md` | AUTHORITATIVE | Vocabulary and V0-V3 phase definitions; wins any terminology dispute. |
| `DATA-CONTRACTS.md` | AUTHORITATIVE | Frozen data shapes/schema/`Config` fields; wins any shape conflict. Current with T-DOC80/82 book fields as of 2026-08-05; does not yet describe `mcp_usage.db` or `contracts/author_orgs.py` (those aren't frozen contracts). |
| `PRD.md` | AUTHORITATIVE | Vision + 18 settled ADRs. |
| `ARCHITECTURE.md` | AUTHORITATIVE | The 9 modules (M1-M9), interfaces/invariants, owners A-F — verified current against `contracts/`/`rag/` layout 2026-08-05. |
| `CONVENTIONS.md` | AUTHORITATIVE | Engineering guardrails, CI-enforced. |
| `WORK-BREAKDOWN.md` | AUTHORITATIVE | Milestones, ticket IDs, T-DOC series (now up to T-DOC95). |
| `TEST-STRATEGY.md` | AUTHORITATIVE | Fakes, golden fixtures, contract tests, the retrieval eval set. |
| `PHASE0-RUNBOOK.md` | HISTORICAL | Phase-0 de-risking spikes — concluded, results in `phase0-results.md`. Kept for the method, not live status. |
| `phase0-results.md` | HISTORICAL | Phase-0 spike results (MinerU/embedder/retrieval-config locks) — decisions already absorbed into `ARCHITECTURE.md`/`WORK-BREAKDOWN.md`. |
| `GIT-WORKFLOW.md` | AUTHORITATIVE | Branch naming, PR flow, CI gating, foundation-freeze mechanism. |
| `EXECUTION-READINESS-REVIEW.md` | HISTORICAL | Principal design review; fixes already applied to the docs above. |
| `rag_v0_design_review.md` | HISTORICAL | An earlier/duplicate principal design review artifact, same era as the above. |
| `LESSONS-LEARNED.md` | REFERENCE | Append-only notebook, explicitly "not authoritative, not a spec." |
| `SCHEDULE.md` | REFERENCE | A *view* over `WORK-BREAKDOWN.md`/`PHASE0-RUNBOOK.md`; those win on conflict, by its own header. |
| `README.md` | AUTHORITATIVE | Top-level pointer to `AGENTS.md` (see §Task 3 of this workstream). |
| `research-kb-system-scope.md` | HISTORICAL | Earliest raw scoping notes, superseded by `PRD.md` (per `AGENTS.md`). |
| `Technical Design & Annotated Survey...md` | HISTORICAL | Literature survey behind the ADRs; the ADRs themselves (`PRD.md` §12) are the decision. |
| `docs/PROJECT-STATUS.md` (this file) | AUTHORITATIVE | Current system state, what shipped, what's open. |

`owners/OWNER-A.md` through `OWNER-F.md` exist, are tracked in git, and are treated as **frozen**
build briefs from the original V0 owner-track build — not live task assignments (see §Task2 of this
workstream on why the owner table is gone from `AGENTS.md`). `reviews/*.md` exist on disk but are
**gitignored** (`.gitignore:4`) — ADR/spike-style analysis docs, not part of the tracked doc set;
`reviews/PARSER-ALTERNATIVES-EVAL.md` is referenced by §5 above as one still-live example.
`graphify-out/GRAPH_REPORT.md` and `.pytest_cache/README.md` are tool-generated artifacts, not
authored project docs — excluded from classification.

### `docs/`

| Doc | Class | Notes |
|---|---|---|
| `docs/BACKLOG.md` | AUTHORITATIVE | The live work queue (D/T/B/O series) — see §6. |
| `docs/AGENT-PROCEDURES.md` | AUTHORITATIVE | Onboarding checklist, per-PR/per-trigger doc obligations, periodic drift-correction procedure — read this, and this file, before your first commit. |
| `docs/WAYMO-CORPUS-STATUS.md` | AUTHORITATIVE | Post-mortem + recovery runbook for the stalled v1 Waymo corpus attempt (17/1437 done, 810 stranded at `chunked`). Superseded as the forward-looking plan by `docs/superpowers/plans/2026-08-06-waymo-av-safety-corpus-expansion-v2.md`, but still the authoritative record of what actually happened and why. |
| `docs/RUNBOOK.md` | AUTHORITATIVE | Operator bring-up after a reboot; GPU-busy / CPU-only operation (OP-1); dashboard token location; Tailscale access; MCP client wiring; running a second corpus (the five registered corpora are tabulated in §1.1 of this file). |
| `docs/GRAPHIFY-ROADMAP.md` | AUTHORITATIVE | T-G agent-tooling plan + outcome ledger; refresh procedure for the enriched graph. New. |
| `docs/GRAPHIFY-SCIP-SPIKE.md` | REFERENCE | T-G13 spike verdict (SCIP precision upgrade feasibility). New. |
| `docs/GRAPHIFY.md` | AUTHORITATIVE | Knowledge-graph dev-tooling setup/usage (not product scope). |
| `docs/BOOK-INTEGRATION-CLOSEOUT.md` | AUTHORITATIVE | Book integration closeout — how it works, what shipped, every rejected approach with its falsifying test. |
| `docs/TEST-AUDIT-2026-07-31.md` | REFERENCE | Point-in-time test-suite audit; findings T-1..T-3 shipped (PR #212), T-4..T-8 tracked live in `docs/BACKLOG.md`. |
| `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` | AUTHORITATIVE | Waymo corpus harvesting handoff/keyword strategy. §2b (added 2026-08-06) is the current broadened-scope query strategy and wins over §2; §3's ID list is a seed/priority list, **not** an exclusion list. |
| `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` | AUTHORITATIVE | Every paper on Waymo's two public research index pages (152 as fetched 2026-08-06), split into arXiv-downloadable (114), public-direct-PDF (15), and needs-manual-sourcing (23). Reconciled 2026-08-06 against the operator's 449-PDF drop-in delivery (`drop_in/waymo downloaded research/`): 97/114, 11/15 and 14/23 respectively are now held locally, leaving **4 Group-B URLs and 9 Group-C papers** outstanding — the live operator-facing to-do list. |
| `docs/CORPUS-EXPANSION-RESEARCH.md` | REFERENCE | Non-arXiv source options investigated, so they aren't re-studied. |
| `docs/ROADMAP-AND-PRIORITIES-PLAIN-ENGLISH.md` | HISTORICAL | 2026-07-17 plain-English roadmap/reprioritization opinion piece; superseded as a status source by this doc. |
| `docs/THE-DECISION-plain-english.md` | HISTORICAL | A single 2026-07-17 decision clarification, resolved. |
| `docs/YOUR-USE-CASES-can-the-system-do-this.md` | HISTORICAL | 2026-07-17 capability Q&A snapshot; capabilities have moved on since. |
| `docs/DECISIONS-PENDING-operator.md` | REFERENCE | 4 book-RAG decisions from 2026-07-29. Decisions 2 and 3 shipped; Decision 4 only partly (marker-regex repair shipped, title disambiguation never built — §6.2 #12); Decision 1 (IDF reindex) is **closed**: every collection already carries the IDF modifier (§1.1, §6.2). Its body line "Nothing here has been actioned" is stale. |
| `docs/DECISION-book-rag-what-to-ship.md` | HISTORICAL | Book-RAG shipping decision, absorbed into `docs/BOOK-INTEGRATION-CLOSEOUT.md`. |
| `docs/DECISION-t-doc62-duplicate-chunk-headers.md` | HISTORICAL | Decision record for the T-DOC62 fix (§4); superseded by the shipped fix. |
| `docs/DESIGN-book-chapters-and-hierarchy.md` | HISTORICAL | Original book-hierarchy design; pressure-tested and partly falsified by Exp 1/3 (§5). |
| `docs/DESIGN-claim-layer-v1.md` | REFERENCE | V1+ design, not built in V0 — forward-looking, not current-state. |
| `docs/DESIGN-continuous-cache-first-build.md` | REFERENCE | Design proposal; check `docs/BACKLOG.md`/git before assuming shipped-as-written. |
| `docs/DESIGN-corpus-dashboard.md` | HISTORICAL | Original dashboard design proposal; the dashboard has since shipped and evolved past it (D-0..D-12, §3). |
| `docs/DESIGN-dashboard-control-panel.md` | HISTORICAL | Control-panel design proposal (OG-43); largely shipped, see §3. |
| `docs/DESIGN-download-only-and-quarantine-fixes.md` | HISTORICAL | Design doc absorbed into the shipped T-DOC78 download-only mode + quarantine fixes. |
| `docs/DESIGN-gpu-free-and-self-healing-tei.md` | HISTORICAL | Design doc for T-DOC78's GPU-free/self-healing TEI work — shipped, see §4. |
| `docs/PLAN-book-rag-experiments.md` | HISTORICAL | The experiment plan Exp 1-5 executed against (§5) — plan, now executed. |
| `docs/RESEARCH-book-rag-established-methods.md` | REFERENCE | External literature pressure-testing the book design; background evidence. |
| `docs/METHODS-books-and-chunk-quality.md` | REFERENCE | Living methods log for book/chunk-quality work; largely folded into `BOOK-INTEGRATION-CLOSEOUT.md`. |
| `docs/eval-reports/*.md` | AUTHORITATIVE | Primary source for every book-RAG experiment verdict (§5) and measurement claim (§1). Specific 2026-11-10 reports are listed individually below. |
| `docs/research/2026-08-25-agentic-rag-sota.md` | REFERENCE | Web-research SOTA survey (URLs cited): agentic/iterative RAG families + retrieval levers, ranked top-5 adoptable mapped to measured failure buckets F1–F7 (precision-95 programme R1). |
| `docs/research/2026-08-25-confidence-qwen-sota.md` | REFERENCE | Web-research SOTA survey: answer-confidence mechanisms (top-3 ranked for a 5-level MCP surface; verbalized confidence rejected) + Qwen reasoning-model lineup and serving posture P0 (precision-95 programme R2). |
| `docs/design-notes/2026-08-28-xc-member-citation-adoption.md` | REFERENCE | Adoption design note for member-block citation (Variant A recommended); rider-PR diff sketch awaiting T-F7 sign-off — no implementation dispatched (precision-95 programme QW-1). |
| `docs/eval-reports/2026-08-26-precision95-metric-ratification.md` | DRAFT (awaiting operator sign-off) | Frozen metric definitions for the 0.95 push, quoted from B0 §2 verbatim; five-part qualifier rule; retired gates; two-arm statement. Unsigned = not a ratified gate (precision-95 programme P0-2). |
| `docs/eval-reports/2026-08-27-multihop-gt-authoring-plan.md` | AUTHORITATIVE (plan) | Multi-hop GT authoring spec: W-A1..A5 sized by shown power arithmetic (~130 items, MDE ≈22–26 pts paired); regime checklist; ~300 graded pairs close B0 §4 anchor gap; execution = SB-2 behind GPU-freeze gate (P0-3). |
| `docs/HANDOFF-2026-08-24.md` | HISTORICAL | OpenEvidence-programme handoff written at `main` `8e63cec`; its operator decisions were since made (§6.2 "Closed"). Banner added 2026-11-10. |
| `docs/AGENT-OPERATIONS-LESSONS.md` | REFERENCE | Append-only log of what went wrong running agents on this repo (incident-first entries). Read before orchestrating multi-agent work. |
| `docs/BOOTSTRAP-VARIANTS-CHEATSHEET.md`, `docs/RATE-INTERVALS-AND-PVALUES-TOOLKIT.md`, `docs/NELSON-RATE-RATIO-IMPLEMENTATION.md`, `docs/EVT-CONFLICT-CRASH-ESTIMATION-REPORT.md` | REFERENCE | Statistics learning references written for the Waymo safety-benchmarking material (2026-08-31 onward); tracked by `17b48ec`. Not system status. |
| `docs/WAYMO-MISSING-DATA-METHODS-REPORT.md`, `docs/WAYMO-SAMPLING-METHODS-REPORT.md`, `docs/WAYMO-UNCERTAINTY-METHODS-REPORT.md`, `docs/WAYMO-SURVIVAL-ANALYSIS-REVIEW.md`, `docs/WAYMO-SAFETY-STACK-REPORT.md`, `docs/WAYMO-SAFETY-METHODS-INTERVIEW-BRIEF.md`, `docs/WAYMO-RESEARCH-MISSING.md` | REFERENCE | Corpus-grounded Waymo method reports and interview-preparation briefs, each citing verbatim passages from `waymo_av_safety` as of its own date; not re-verified against today's corpus. `WAYMO-RESEARCH-MISSING.md` is the 2026-08-23 audit of papers absent from the corpus. |
| `docs/eval-rubrics/groundedness-rubric.md`, `docs/eval-rubrics/fabrication-audit-rubric.md` | AUTHORITATIVE | The signed-off baseline definitions of "grounded" (2026-08-24) and "fabricated" (2026-08-25, amended). The `*-rubric-review.md` files beside them are REFERENCE. |
| `docs/eval-reports/2026-11-10-system-review.md` | AUTHORITATIVE | Adjudicated system review (RV-1..6): ranked work list S-01..S-26, wave map, operator questions F1-F8. Wins over its lane reports where they disagree. |
| `docs/eval-reports/data/2026-11-10-system-review/RV-{1..6}-*.md` | REFERENCE | The six lane reports the review adjudicates; RV-6 carries the doc-drift punch list this pass applied. Some lane claims are corrected in §6.2 "Closed". |
| `docs/eval-reports/2026-11-10-{standards,main-corpus,topic-focus}-benchmark-protocol.md` | AUTHORITATIVE | FROZEN pre-registered benchmark protocols (EV-5); changes only by dated addendum. Nothing run against them yet. |
| `docs/eval-reports/2026-11-10-GPU-DAY-RUNBOOK.md` | AUTHORITATIVE | The first GPU session, jobs serialized cheapest-first with prerequisites and index effects (EV-5). |
| `docs/eval-reports/2026-11-10-cq2-index-maintenance.md` | AUTHORITATIVE | Runbook for `app.resparse` / `app.set_payload_fields` and the CQ-1 deployment hazard; unrun, estimates only. |
| `docs/eval-reports/2026-11-10-cq3-stub-chunks.md` | AUTHORITATIVE | Stub-chunk filter design and its pre-registered A/B (unrun; amend per review S-05). |
| `docs/eval-reports/2026-11-10-topic-labels-audit.md` | AUTHORITATIVE | EV-2/EV-3: label audit (kappa 0.901) and `relevance_score` as a focus signal (AUROC 0.923). |
| `docs/eval-reports/data/2026-11-10-*/` (`standards-gt`, `causal-books-gt`, `papers-passage-gt`, `topic-labels`, `offtopic-census`, `ligature-census`, `embed-truncation`, `dup-ref-census`, `FIXTURE-HASHES.json`) | REFERENCE | The ground-truth sets, labels and censuses with their scripts; `standards-gt/AUTHORING-PROTOCOL.md` is AUTHORITATIVE for how GT items are authored. Figures from them are restated in §1.2. |
| `docs/superpowers/plans/2026-11-10-enhancement-programme.md` | REFERENCE (plan) | The forward plan for this programme; being written in parallel with EP-1 and **not present on this branch when this row was added** — check it exists before citing it. |
| `docs/superpowers/plans/*.md`, `docs/superpowers/specs/*.md` | REFERENCE | Per-feature design/implementation plans (superpowers workflow artifacts); the newest, `2026-08-05-paper-author-org-tagging-design.md` and `2026-08-06-waymo-av-safety-corpus-expansion-v2.md`, are the only source for those two efforts' design (§3). The original `2026-08-05-waymo-corpus-expansion.md` is superseded by the v2 plan — kept for its own historical record of what v1 intended, per `docs/WAYMO-CORPUS-STATUS.md`. |

## 8. Preserved-but-unmerged work index

Verified 2026-08-05 with `git branch -r --no-merged main` and `git log main..origin/<branch>` — this
supersedes any earlier count, the repo has moved since any prior analysis.

- **`origin/T-SEED-combined-fixes`** — 3 commits ahead of `main` and genuinely unmerged (confirmed via
  `git log --oneline main..origin/T-SEED-combined-fixes`, which also shows 5 older commits already on
  `main` under different SHAs — only the top 3 are new): `e4e15aa` (per-paper unexpected-exception
  safety net with a circuit breaker), `885dd1a` (exclude `ContractError` from that safety net —
  contract violations must surface loudly, not be swallowed), `fe450f0` (document the `UNEXPECTED:`
  quarantine-reason prefix in `DATA-CONTRACTS.md`). This is D-9 (§6) — the branch is ~3 weeks stale,
  expect a real rebase against current `rag/orchestrator.py`, not a fast-forward.
- **`worktree-waymo-corpus-expansion`** (worktree at
  `.claude/worktrees/waymo-corpus-expansion`) — 7 commits ahead of `main`, unmerged: the Waymo arXiv
  scout script and its iterations (`679f7be` add, `ad761b9`/`8f700d6` timeout/backoff fixes,
  `4430cf5` rewrite to reuse `ArxivSource`/`Harvester`'s machinery, `acf97e2` field-name/rate-limit
  fix), plus `636eeb0` (gitignore `waymo/`) and `9f11bde` (the Waymo expansion plan doc). An 8th
  commit reachable from this branch, `8da1817`, is the same D-11 content already on `main` under
  `4e07eb4` — a base-branch artifact, not part of this branch's own unique work.
- **`d10-plan`** and **`o1-plan`** — each a single-commit plan doc (`4e92d98` "Plan: D-10 dashboard
  number accuracy" and `f76bbca` "Plan: O-1 finish as completed when arXiv is exhausted"
  respectively), never merged. Their **implementations did land on `main`**, under different
  branches/PRs: D-10 shipped as PR #227 (§3/§6), O-1 shipped as commits `70940dc`/`f8a7f69`/`013f7cf`
  (§4). The plan docs themselves are stranded, superseded by the shipped code.
- Not requested by this workstream's brief but found during verification, worth flagging as **stale,
  not live unmerged work**: `origin/archive-failed-run-logs` and `origin/fix-observer-effect-pid-scan`
  each carry a single commit that duplicates content already on `main` (the D-11 and D-12 fixes
  respectively, under different SHAs — a rebase-merge rewrite artifact, same pattern `docs/BACKLOG.md`
  describes for the 147 already-deleted stale branches). `origin/worktree-paper-author-org-tagging`
  similarly duplicates all 12 author-org-tagging commits (§3) already on `main` under different SHAs.
  None of these three branches carry work that isn't already on `main`.

## 3b. Shipped-work ledger, continued (2026-08-23 onward)

*These sub-sections were appended after §8 without a heading of their own; they are §3 ledger
entries and are headed here so the section numbering matches `docs/AGENT-PROCEDURES.md` §B. Entries below
that predate 2026-11-10 are history and were not re-derived, except where a correction is stated inline.*

### Waymo-priority benchmark programme (shipped 2026-08-23)

Operator goal: recall and precision ≥ 95% on the Waymo corpus, with waymo.com/safety/research
papers as top priority; **target frozen before any implementation work**. All merged on `main`:

- **Protocol (frozen first, commit `4e14d7b`)** — `docs/eval-reports/2026-08-23-waymo-priority-benchmark-protocol.md`:
  metric definitions (paper-level Recall@10 / Precision@10 over answerable items, absent arm
  reported separately per RI-M7's no-separable-floor finding), gates A–D, item-authoring rules,
  and the no-post-hoc-editing constraint.
- **Priority list** — `fixtures/eval/waymo_safety_research_55.json` (the full 55-paper page,
  transcribed verbatim) and its resolution `waymo_safety_research_55_resolution.json`: 53/55
  ingested, 2 documented missing. Invariants: `test_waymo_safety_research_resolution.py`.
- **GT-WMR ground truth** — `fixtures/eval/gt_wmr.json`: 82 items (70 answerable / 12 absent),
  52/53 priority papers grounded; every excerpt machine-verified verbatim against its gold chunk
  (9 re-groundings logged in `_metadata.corrections`); absence items carry live-run search logs;
  4 multi-paper synthesis items; 1 leak-checked vision item. Invariants:
  `test_gt_wmr_invariants.py`.
- **Verified-set v2 (pass 2)** — `waymo_gt_verified.json` grew 73 → 84 items: Q-GTA-034..044
  survived independent re-verification (`docs/eval-reports/2026-08-22-waymo-groundtruth-second-pass.md`,
  11/11 survive; coordinating session reproduced the decisive counts). Q-GTA-036/037 carry
  `duplicate_of` pointers; `load_questions` excludes secondaries by default so a rediscovered
  fact cannot move an aggregate denominator twice.
- **Figures backfill (RI-32) completed** — full 1,738-paper run finished 2026-08-22 23:46
  (9298.8s, 5.4 s/paper observed — both earlier ETAs wrong): figures 24,708 rows / 1,724 papers,
  tables 8,266 / 1,586. `blocks`, `chunks` and `summaries` verified byte-identical by content
  hash against the pre-run backup (`waymo/data/backups/pre-RI32-backfill-20260822T204114Z/`).
  `papers` did move, by 4 rows in `author_orgs` only (NULL -> the curated Waymo value) — **not**
  the backfill, whose connection authorizer denies any write to `papers`, but
  `scripts/backfill_curated_author_orgs.py` running concurrently: those 4 papers carry
  `author_orgs`/`curated_author_orgs` in Qdrant too, which is that script's signature (it writes
  both stores) and which the figures backfill never touches. Row counts alone would have missed
  this — 1738 before and after — so the gate's content hashes are what caught it.

Baseline numbers, gates, and the honest verdict: `docs/eval-reports/2026-08-23-waymo-priority-baseline.md`.

### MCP method-synonym layer (shipped 2026-08-23)

`scan_methods(method, paper_id, author_org, max_matches_per_paper, context)` and
`list_methods()` on the MCP server (`rag/mcp_server.py`, wired in `app/serve.py`), backed by a
curated alias map (`rag/method_aliases.py`, 50 families across the Waymo AV-safety and
causal-methods corpora). `scan_methods` resolves a method to its family's surface forms —
acronyms, long forms, inflection stems (`\brerank` → reranking/reranked; `\bmais` → MAIS3+) —
and compiles them into one alternation scanned exactly like `scan_corpus` (recall 1.0 for the
alias group; lexical false positives rejected by reading; `author_org` = curated tier only).
Unknown methods scan literally; ambiguous inputs raise rather than guess. Scope boundary kept
explicit in the docstrings: this is lexical enumeration in `scan_corpus`'s mold — the semantic
tools stay un-rewritten (PRD §11A). Envelope shapes unchanged (`ScanResponse` reused — no
contracts/ diff, no T-F7). Review plan with the fuller design fork (method taxonomy, argument
layer): `docs/superpowers/plans/2026-08-23-mcp-review-plan.md`. Live-verified against the Waymo
corpus: 8/8 method queries surface their known gold papers (NIEON → the CAT pair; GIDAS → the
GIDAS trio; active inference → all four active-inference papers; …).

### Operator tuning decision, 2026-08-24 — `hybrid_dense_weight` 0.5 → 0.7

`waymo/data/config.yaml` is gitignored, so this change lives only on disk. Recorded here because an
untracked operational change with no record is how a measured decision quietly becomes folklore.

**Decision (operator):** optimise for the Waymo **safety/research priority corpus** (`gt_wmr.json`,
the waymo.com/safety/research papers) until another corpus is benchmarked.

**Basis** — FUSE-1's sweep, raw runs under `docs/eval-reports/2026-08-24-fuse1-sweep-*.json`:

| w | GT-WMR R@10 | GT-WMR block-P@1 | verified-84 R@10 |
|---|---|---|---|
| 0.5 (was) | not swept | not swept | 0.8971 ✗ below bar |
| **0.7 (now)** | **0.9714** | **0.7273** | 0.9559 ✓ |
| 0.8 | 0.9571 | 0.6970 | 0.9706 ✓ |
| 1.0 | 0.9571 | 0.6970 | 0.9706 ✓ |

0.7 is the best measured value for the priority corpus on **both** metrics, and still clears the
≥0.95 recall bar on the full Waymo corpus. Verified live after the change: paper-level
Recall@10 = 0.971, MRR = 0.939 (n=70), with the run's own scoring line confirming
`hybrid_dense_weight=0.7`.

**Caveat resolved 2026-08-24, and it overturns the reason given above.** The lower half was swept
(FUSE-2). The optimum on the priority set is **not** 0.7 — it is **0.5**, the value that was already
shipped:

| w | GT-WMR R@10 | GT-WMR block-P@1 | verified-84 R@10 |
|---|---|---|---|
| 0.3 | 0.9000 | 0.6364 | 0.7353 |
| 0.4 | 0.9286 | 0.6212 | 0.8235 |
| **0.5** | **0.9857** | **0.7273** | 0.8971 ✗ below bar |
| 0.6 | 0.9714 | 0.7273 | 0.9265 ✗ below bar |
| **0.7 (live)** | 0.9714 | 0.7273 | **0.9559 ✓** |
| 0.8–1.0 | 0.9571 | 0.6970 | 0.9706 ✓ |

**The stated justification for 0.7 was wrong; the choice survives on a different one.** "Best on the
priority set" is false — 0.5 beats it by 1.4 pp of recall at identical block precision. What is true
is that **0.7 is the lowest weight that clears ≥0.95 on the full Waymo corpus** while staying within
1.4 pp of the priority peak. 0.5 and 0.6 both fail the full-corpus bar (0.8971, 0.9265).

**If the priority corpus is the only thing that matters, 0.5 is strictly better and should be
restored.** 0.7 is the right choice only if the full corpus must also clear the bar. That is an
operator call; 0.7 stays live until it is made.

**Rollback:** `waymo/data/config.yaml.bak-w0.5-20260824T122256`.

**Resolved 2026-08-25 (operator): 0.7 stays.** The condition above holds — the full Waymo corpus
must also clear the bar, which 0.5 fails outright (0.8971 < 0.95) and 0.7 clears. The +1.4 pp
priority advantage of restoring 0.5 does not buy back a failed full-corpus gate. Re-evaluation is
deferred until the next-build programme's rerank/pool-depth work lands and then measured against
both fixtures (`docs/superpowers/plans/2026-08-24-next-build-programme.md` §1, decision A) — not
before, since changing weight mid-programme would invalidate comparability with every baseline
number collected at 0.7.

### Next-build D2 — block adjacency / chunking-artifact analysis (2026-08-25)

Completes PREC-1 §3, read-only (no retrieval re-run): stored 2026-08-23 per-question records +
`waymo/data/papers.db` opened `mode=ro`. Among near-misses whose rank-1 **paper** is correct but
gold **block** not at rank 1 (PREC-1 §1 C1∪C2: verified-84 dense 27/64 scored; GT-WMR fused
12/66), the gold block is elsewhere-in-document in 17/27 and 9/12 respectively; same-chunk 1+1,
adjacent-chunk 8+2, cross-gold-paper 1+0. Boundary classes are real but secondary (33%/25% of
near-misses; ≈14%/≈5% of scored items). Two items (one per headline fixture) had the gold text
physically served inside the rank-1 chunk under a sibling anchor — an anchoring/citation artifact
no reranker reaches. Report: `docs/eval-reports/2026-08-25-nb-d2-block-adjacency.md`; script:
`docs/eval-reports/data/2026-08-23-waymo-priority/nb_d2_block_adjacency.py` (commits `87bfa51`,
`d89fa15`, report commit on branch `NB-D2-block-adjacency`). Gates R0.

### Next-build programme — Wave 0–2 ledger (2026-08-25)

Orchestrator-run programme per `docs/superpowers/plans/2026-08-24-next-build-programme.md`; every
lane verified against artifacts by the orchestrator before merge. Consolidated here because the
lane agents deferred their rows (sibling files owned concurrently).

| ticket | verdict / deliverable | evidence |
|---|---|---|
| C1 | closed as already-satisfied — FUSE sweep JSONs + PREC-1 diagnosis were on `main` byte-identical to `FUSE-2-lower-sweep`; plan's "stranded" premise was a stale-working-tree misread | merge `a956272` |
| D1 pool depth | all 23/23 non-vision right-paper-wrong-block items on ver84 exposed by K=64; GT-WMR ≥0.95 by K=32; bottomless ceilings 0.8750 all-arm / 0.9333 text-arm @K=128; vision-only items absent everywhere | `docs/eval-reports/2026-08-25-nb-d1-pool-depth.md`, merge `e95825d` |
| D2 block adjacency | boundary misses 33%/25% of near-misses; anchor/citation artifacts Q-WAYB-027/Q-WMR-094 | section above; merge `93071cb` |
| D3 abstention census | **no separation found** (17 features × 2 fixtures); distinct_papers_fused died held-out (0.866→0.574); query-length = authoring leakage | `docs/eval-reports/2026-08-25-nb-d3-abstention-census.md`, merge `0b93c72`, fix `de4b32f` |
| D4 eval runner | dual-fixture standard-table runner over `app/retrieval_eval.py`; SAMPLE reproduces headline numbers exactly | `scripts/nb_eval_runner.py`, merge `e8e46d3` |
| R0 fix ranking | ranked 1) X-P depth 2) X-F fusion shape 3) X-O gated on X-P 4) X-C citation refinement 5) X-H last; achievability bound stated up front; independent review REVISE → five corrections applied | `docs/eval-reports/2026-08-25-nb-r0-fix-ranking.md`, `6b6f67f`→`ceca9c3` |
| A-1 abstention design | five candidate signal sources with pre-committed falsifiers; recommendation: falsify C1 refusal-affordance detector first (operating point already dominates census), C5 expected to die | `docs/eval-reports/2026-08-25-nb-a1-abstention-signal-design.md`, merge `f465971` |
| X-F fusion shape | eviction does NOT survive production depth (net +1, 66/68 vs 65/68); dense_only ≡ w=1.0 bit-identical (schema fact); config stays w=0.7 | `docs/eval-reports/2026-08-25-nb-xf-fusion-shape.md`, merge `f465971` |
| X-P deep-pool tables | depth = serving win (GT-WMR saturates 70/70) but ordering hazard realized on ver84 (11 gold blocks lose rank at K=64; block-P@1 0.3667→0.3833 vs 0.95 target); **X-O unblocked as binding constraint** | `docs/eval-reports/2026-08-25-nb-xp-deeppool-tables.md`, merge `c139f9c` |
| NB-C1 refusal detector (A-series C1 stage 1) | **DROPPED** per pre-committed criterion: frozen blind rule v1.0 committed before classification; ver84 fails both halves (10/16 absent covered, bar ≥12; 7/68 false refusals, bar ≤5) — gt_wmr passed clean (11/12, 0/70) but the criterion is disjunctive; finding = refusal signal not mechanically extractable by a fixed lead-region rule; unconditional-affordance fallback is where A-1 §3 points | `docs/eval-reports/2026-08-25-nb-c1-refusal-detector.md`, branch `NB-C1-refusal-detector` |

Operator decisions recorded this programme: **A** keep `hybrid_dense_weight`=0.7 (section above);
**B** fabrication-rubric amendments F-A1..F-A3 applied after verification + SIGNED OFF header
(`6d0b32b`); **C** VLM conditional on unique-information yield (NB-6 scoping dispatched);
**D** OpenEvidence head-to-head out of scope this programme.

### Successor queue executed (2026-08-25, same day)

| item | outcome |
|---|---|
| A-series C1 refusal-affordance detector | **DROPPED** per pre-committed disjunctive criterion — ver84 fails both halves (10/16 absent covered < 12; 7/68 false refusals > 5); gt_wmr passes clean (11/12, 0 FP). Stage 2 dead with it. No rubric iteration performed or permitted. `docs/eval-reports/2026-08-25-nb-c1-refusal-detector.md`, merge `ba05c85` |
| Fabrication re-run under amended rubric | **Adverse + qualified**: headline rates are a 38/46 mixture of full-delivery vs NUM_CTX-truncated items (non-comparable by hash AND delivery); F-A2 did NOT surface Q-GTA-037 (wording ≠ compliance, now measured); Q-WAYB-035 lost its old unsupported catch; F-A3 delta sits on a truncated item. Follow-up ticket **NB-JUDGE-CTX** filed (fix harness context window, correct stale comment, re-run owed). `docs/eval-reports/2026-08-25-nb-judge-rerun.md`, merge `5784fa5` |
| NB-JUDGE-CTX / NB-NUMCTX harness fix + clean-delivery re-run | **SHIPPED, outcome adverse**: `_NUM_CTX` raised 8192 → the served artifact's declared 40,960 (interim 16384 was itself caught silently truncating Q-WAYB-010, true count 17,452 tok — caught live by the new per-call `prompt_eval_count` telemetry), loud pre-send estimate-vs-window guard added at the single choke point in `app/judge_llm.py`, stale "max 228 words" comment corrected; zero-GPU tests pin window/estimator/refusal. Clean-delivery re-run verified 84/84 full delivery from the run transcript. Adverse: amended-rubric unsupported collapsed (absent arm 0.286→0.000; answerable 0.208→0.053), F-A2 surfaced neither Q-GTA-037 nor Q-GTA-040 on clean tests, and full-vs-full item flips show single-pass judge sampling variance dominates — seeded/repeated sampling owed before any trend claim. `docs/eval-reports/2026-08-25-nb-numctx-clean-delivery.md`, branch `NB-NUMCTX-fix` (through commit `96dc650`) |
| NB-6 bounded VLM pilot | **PROJECT CLOSED** per pre-committed protocol — Stage 0 all PASS (G0.1 posture-A 5.65GB free ≥2GB; G0.2 max 14.4s/page ≤30s; G0.3 4/5 true-vision survivors), Stage 1 FAIL 50.0% (4/8) vs ≥80% bar; misses hand-verified genuine (dense chart/table numerics dropped or paraphrased; sparse figure-text survives). qwen2.5vl:7b acquired for the pilot. `docs/eval-reports/2026-08-25-nb-vlm-pilot.md`, merge `2f401f5` |
| X-H (hard/negation strata) | Gate fired (residual is stratum-shaped per X-P/X-O) but **execution deferred**: no pre-committed falsifier exists (R0 deferred its definition), honest-ceiling bounds already cap ordering-side work below target, and cost/certainty profile is worst-of-rank. First candidate of any future retrieval-quality programme; evidence cited (ver84 hard 0.167, negation-and-scope 1/7, PREC-1 §4) |
| A-series C2 anchor-coverage probe | Dispatched same day (next in A-1 ordering after C1's drop; fully pre-committed criteria incl. length-leakage guard) — outcome recorded on landing |
| A-series C2 anchor-coverage probe | **DEAD** per pre-committed criterion — hit-rate AUROC 0.4824 (ver84) / 0.3563 (gt_wmr) vs ≥0.75 both; entity anchors diluted by per-anchor normalization, gt_wmr absent arm contains zero numeric anchors so coverage inverts. Length-leakage guard not reached. `docs/eval-reports/2026-08-25-nb-c2-anchor-probe.md`, merge `7dc46fa`. **A-series state: C1 DROPPED, C2 DEAD; C3/C4/C5 remain specified-but-unrun in the A-1 doc (criteria pre-committed there), and NB-JUDGE-CTX is the open harness fix** |
| X-C citation refinement | member-block citation measured from stored runs: ver84 dense 78.1%→84.4% passage hits (4 conversions — Q-WAYB-027 rank-1 plus 3 more C2 items riding inside non-rank-1 served chunks), GT-WMR fused 93.9%→95.5% (Q-WMR-094 rank-1; its C2 bucket erased outright); monotone so zero regression risk; it is a citation/metric-honesty fix, not retrieval. Every caller-facing exposure route crosses a frozen path or the contract-reserved `metadata` slot → proposed diffs are design-note-only in §3, pending T-F7 sign-off. Gated instrument: `app/exp_nb_xc_member_citation.py`. `docs/eval-reports/2026-08-25-nb-xc-citation.md`, branch `NB-XC-citation` |

### NUMCTX truncation fix landed (2026-08-25/26)

Merge `cc6a0c3` (branch `NB-NUMCTX-fix`): Ollama serving-stack silent front-truncation made structurally loud — window raised 8192 → the served artifact's declared 40,960 (`/api/show`, honored empirically after 16384 still clipped one real prompt, Q-WAYB-010 at 17,452 tok); loud pre-send estimate-vs-window guard; per-call `prompt_eval_count` delivery telemetry; stale comments corrected; 4 zero-GPU tests pin behavior. Clean-delivery fabrication re-run under the amended rubric: absent arm **29/29 supported**, answerable 0.935/0.053/0.011. Adverse findings recorded honestly: unsupported-flagging collapsed to 0.000 on the absent arm; F-A2 surfaced neither Q-GTA-037 nor Q-GTA-040 even at full delivery; single-pass judge sampling variance dominates flips between runs — seeded/repeated sampling owed before any trend claim. Closes NB-JUDGE-CTX's original scope; judge-variance follow-up remains open.

### GPU freeze gate (operator, 2026-08-26)

Operator directive: no GPU work until lifted. Held at freeze: QW-2 confidence v0 (stub committed, pre-download), QW-3 reranker-seat A/B (blocked entirely), Wave P2/P3 execution, GT authoring execution. Proceeding docs-only: P0-1 ledger (this entry), P0-2 ratification draft (sign-off header deferred to operator), P0-3 multi-hop authoring PLAN, QW-1 design note (landed `cff3b53`, recommends Variant A; rider PR awaits T-F7 sign-off).

### GPU freeze lifted (operator, 2026-08-27)

**Freeze lifted on 2026-08-27.** GPU available in full. Measured GPU state at lift: NVIDIA RTX 3090, 24,576 MiB total, 11,100 MiB resident (the TEI pair — `text-embeddings-router` ×2, containers `rag-tei-embed` and `rag-tei-reranker`), leaving ~13.4 GB free, 0% utilization.

**Lanes dispatched on lift:**
- **QW-3** (reranker-seat A/B, branch `P95-QW3-reranker-seat`) — BGE cross-encoder versus Qwen3-Reranker-0.6B measured on both fixtures against pre-committed ceilings, targeting F1 (near-misses at rank 2: 7/18 on ver84, 8/12 on gt_wmr).
- **QW-2** (confidence surface v0, branch `NB-QW2-confidence-v0`) — branch carries stub with scorer-absent plumbing (commit ①), rebased onto main @ `8dc336e` before dispatch.
- **SB-2 first slice = W-A4** (partial-absent GT, two blind authors on branches `P95-SB2-WA4-authorA` / `P95-SB2-WA4-authorB`) — multi-hop ground-truth authoring.

**Lanes deliberately NOT dispatched and why:**
- **SB-1** (chunk-boundary mitigation) held because it requires a full re-embed/reindex that should not race QW-3 for the card. *(Outcome, verified 2026-11-10: dispatched 2026-08-28, verdict REJECT on both arms, merge `7b679f7`, `docs/eval-reports/2026-08-28-sb1-chunk-boundary.md` §3.7 — see the lane-outcomes table below.)*
- **SB-3** (agentic loop) gated on SB-2's first adjudicated batch; proceeding docs-only until SB-2 delivers. *(Outcome, verified 2026-11-10: landed 2026-08-28 — arm (a) CRAG-style evaluator ADOPT-as-candidate, arm (b) decomposition REJECT; commits `8d7c478`..`901a108` on `main`; see the lane-outcomes table below. The 2026-08-28 ledger did not record it.)*
- **SB-4** (Qwen3.8-27B pilot) needs a declared stop-TEI maintenance window since 15.4 GB of weights cannot co-reside with TEI; execution deferred to a dedicated card-off window. *(Verified 2026-11-10: no SB-4 commit or report exists — `git log --all --grep=SB-4` finds only ledger commits `54e1141`, `d8b95d7`, and `ls docs/eval-reports \| grep qwen38` is empty. A `qwen3.8:27b-mtp-q4_K_M` Ollama process is currently resident on the GPU (§1.3); whether it is this pilot is unknown.)*

**Two items remain blocked on the operator, not on the GPU:**
- P0-2 metric-ratification sign-off header (`docs/eval-reports/2026-08-26-precision95-metric-ratification.md` is still an unsigned DRAFT, so no headline 0.95 claim is ratifiable).
- T-F7 sign-off on the batched rider PR that QW-1 recommends (member-block citation adoption, `docs/design-notes/2026-08-28-xc-member-citation-adoption.md`).

**Repo state:** `main` fast-forwarded from `20d2882` to `8dc336e` (the `LEDGER-precision95` tip), so all new lanes branch from current main.

### Precision-95 programme precursors (2026-08-25/26)

Benchmark-first groundwork for the 0.95 push, executed under the operator GPU-freeze gate
(docs-only). Consolidated ledger; every lane verified by the orchestrator before merge.

| item | outcome | evidence |
|---|---|---|
| NB-B0 benchmark audit | instrument inventory with achievability ceilings shown as arithmetic; P@10 retired (~1/k wall); agentic-GT deficit enumerated (W-A1..W-A5, none authored); confidence-anchor deficit (~4×) quantified | `docs/eval-reports/2026-08-25-nb-b0-benchmark-audit.md`, merge `0646ff0` |
| NB-R1 agentic SOTA research | top-5 adoptable ranked to failure buckets F1–F7: reranker-seat upgrade (Qwen3-Reranker-0.6B), depth-first reranking, contextual chunk enrichment, CRAG-pattern evaluator, stratum routing | `docs/research/2026-08-25-agentic-rag-sota.md`, merge `5ede2e7` |
| NB-R2 confidence+Qwen research | confidence top-3: MiniCheck-class support-checking, conformal/LTT (gated on anchors), semantic entropy; verbalized rejected. Posture P0: qwen3-14b @16384 co-resident; Qwen3.8-27B UD-Q4_K_S pilot in stop-TEI windows (vLLM thinking_token_budget) | `docs/research/2026-08-25-confidence-qwen-sota.md`, merge `a8e2181` |
| NB-P02 metric ratification | DRAFT addendum (definitions quoted verbatim from B0 §2; qualifier rule; retired gates; two-arm statement) — **operator sign-off header unsigned** | `docs/eval-reports/2026-08-26-precision95-metric-ratification.md`, merge `ee11e85` |
| NB-P03 multi-hop GT authoring plan | W-A1..A5 sized via shown power arithmetic (~130 items; MDE ≈22–26 pts paired); ~300 graded pairs close B0 §4 gap; regime checklist enumerated; execution = SB-2 behind GPU gate | `docs/eval-reports/2026-08-27-multihop-gt-authoring-plan.md`, merge `15f678d`; orchestrator-direct after two dispatch timeouts on input-reading |
| NB-QW1 citation adoption note | Variant A recommended (GroundedResult.metadata slot + DATA-CONTRACTS §M7 paragraph); rider-PR sketch filed for T-F7 batch | `docs/design-notes/2026-08-28-xc-member-citation-adoption.md`, merge `cff3b53` |

### Precision-95 programme lane outcomes (2026-08-28)

Lanes dispatched on freeze lift (2026-08-27) landed their primary work by 2026-08-28. *Corrected 2026-11-10 (this sentence used to say "SB-1 remains in-flight"): SB-1 landed as REJECT (`7b679f7`) and SB-3 landed (arm (a) ADOPT-as-candidate, arm (b) REJECT, `901a108`); two operator-gated items remain blocked and are still unsigned as of 2026-11-10.*

| lane | outcome | notes |
|---|---|---|
| **QW-2** — MiniCheck-FT5 confidence surface v0 | **LANDED** — support score is real separator, ~500× wider margin than retrieval score, but heavily overlapping distributions block threshold fitting | Per-arm answer-aggregate means (never blended): primary-prompt answerable n=68 mean 0.747 median 0.822 range [0.044, 0.988]; primary-prompt absent n=16 mean 0.579 median 0.682 range [0.027, 0.956]; affordance-prompt answerable n=68 mean 0.794 median 0.884 range [0.315, 0.988]; affordance-prompt absent n=16 mean 0.667 median 0.737 range [0.027, 0.951]. Separation confirmed real but 15/16 absent items fall inside the answerable arm's range. Retrieval score gap only 0.00026 (verified against `docs/eval-reports/2026-08-25-nb-d3-abstention-census.md`'s ver84-fused row), so support score's gap is roughly 500× wider. `Q-GTA-037` ("905 nm" misattribution) scored lowest of all 16 absent items at 0.0268, contradicting prior expectation; ablation stripping "Waymo" raised score to ~0.98, showing sensitivity to subject substitution — same failure mode appears in `Q-GTA-040` (invented "Swiss Re underwrites Waymo" scores 0.9388 against passage discussing both entities separately). Affordance arm's absent mean rose (0.579→0.667) while producing more correct refusals — refusal sentences are themselves scored. **Viable as one candidate signal for IN-2, not alone; conformal fit should use sentence-level scores rather than per-answer means.** Branch `NB-QW2-confidence-v0`, merge `fd05dbf`; report `docs/eval-reports/2026-08-28-confidence-v0.md` |
| **QW-3** — reranker-seat A/B | **VERDICT: REJECT** Qwen3-Reranker-0.6B on block-P@1 | BGE baseline reproduced committed NB-D4 SAMPLE exactly to four decimals. Both fixtures, k=10, sparse-mode fused, collection `waymo_av_safety`: block-P@1 collapses 24.0× on gt_wmr (48/65 → 2/65 = 0.7385 → 0.0308) and 11.0× on ver84 (22/60 → 2/60 = 0.3667 → 0.0333). Ver84's 0.0333 sits below no-rerank floor of 0.1667 — adopting would regress against disabling reranking. Full metrics table in report. R@10 MRR block-P@1 comparison: gt_wmr: BGE 0.9714/0.9393/0.7385 vs Qwen 0.9429/0.5968/0.0308; ver84: BGE 0.9559/0.8335/0.3667 vs Qwen 0.8971/0.5429/0.0333. Three hypotheses tested before measurement trusted — dtype fp16→bf16 (ruled out), wrong prompt template (falsified by token inspection), abstract/summary-block preference (~12% same-paper-and-summary against 61–64% promoting a different paper). Hosting: in-process via `transformers` in bfloat16, structurally incompatible with TEI classification-head route; swap via monkeypatch in harness. R1 survey's vendor +8.8 MTEB-R claim did not reproduce on this corpus domain. Not attempted: Qwen3-Reranker 4B/8B, corpus-tuned task instruction, PyLate/GTE-ModernColBERT. Branch `P95-QW3-reranker-seat`, merge `825c57b`; report `docs/eval-reports/2026-08-28-qw3-reranker-seat.md` |
| **SB-2 / W-A4** — partial-absent ground truth authoring | **LANDED** — 31 usable items across 22 distinct papers, max 4 per paper | Two blind authors (Author A: 21 items/19 papers, 1 killed on probe; Author B: 12 items/5 papers) → third-session cross-verification (Stages B/C/D). Adjudicated: 33 entries → 28 accepted, 3 accepted_with_correction, 2 rejected. Cross-verifier added sixth mechanical check (re-running lexical probes and diffing logged hit counts) — found **4 of 12 Set-B items carrying stale counts**. Main falsification: `Q-WA4-B-FINAL-001` claimed Los Angeles statistical-significance verdict absent, but `2312.12675:b118` states verbatim "The result in Los Angeles was not statistically significant due to low mileage"; probe logged 1 hit when true count is 6 of paper's 26 chunks. Second rejection: `Q-WA4-B-FINAL-006`, where `2312.13228:b66`'s power-analysis table supplies required-mileage value (3.5M miles) item claimed absent. Stage D self-test: three deliberate corruptions (word-swapped excerpt, wrong-but-real block_id, inflated denominator) — checker caught 3/3. Both authors' self-flagged doubts re-probed hard and confirmed. One item (`Q-WA4-A-014`) accepted with disclosure note for operator judgement — "absent" claim is arguably directly-stated zero in same gold block. **Incidental finding:** 12 of 12 Author B's cited passages sat 1–5 blocks downstream of anchor block, never in anchor itself — independent supporting evidence for X-C member-block citation's Variant A recommendation. Branches `P95-SB2-WA4-authorA` (merge `7191f8e`), `P95-SB2-WA4-authorB` (merge `336d78c`), `P95-SB2-WA4-crossverify` (merge `259b007`); data `docs/eval-reports/data/2026-08-28-wa4-gt/`; report `docs/eval-reports/data/2026-08-28-wa4-gt/crossverify/cross-verification-report.md`; checker `scripts/wa4_crossverify.py` |
| **SB-1** — chunk-boundary mitigation | **VERDICT: REJECT (both arms)** — merge `7b679f7` (2026-08-28) | Neighbour smoothing is a flat null (reach vs distance mismatch); section-context embedding trades fixtures with zero boundary-class conversions; "no detectable effect, on both fixtures independently, never averaged." The ver84 MRR tie-break noise floor (~0.0074, below) is the instrument finding that survives. Report `docs/eval-reports/2026-08-28-sb1-chunk-boundary.md` §3.7 |
| **SB-3** — agentic loop | **LANDED: arm (a) CRAG-style pre-generation evaluator ADOPT-as-candidate, never wired; arm (b) IRCoT/Self-Ask decomposition REJECT** — commits `8d7c478`..`901a108` on `main` (fast-forwarded, no merge commit) | (a) AUROC answerable-vs-absent 0.9411 on gt_wmr (95% CI [0.890, 0.992], n 70/12, 2.9% false abstention) and 0.8025 on ver84 (CI [0.696, 0.909], n 68/14, 20.6% false abstention): both clear the frozen 0.75 bar as point estimates; gt_wmr is established, ver84 is directional and not established. The evaluator exists only as the experiment `app/exp_agentic_loop_v0.py` — it is not in `app/serve.py`, `rag/retriever.py` or any serving path (grep, 2026-11-10) — and is not ready to ship uncalibrated. (b) Decomposition lowers recall@10/MRR on every measured slice on both fixtures, including the routed hard/multi-hop/negation stratum it targets, and adds zero coverage on the W-A4 fixture. Report `docs/eval-reports/2026-08-28-sb3-agentic-loop.md` §1, §2, §5 |

### Precision-95 plan ticket status (`docs/superpowers/plans/2026-08-25-precision95-programme.md`, verified 2026-11-10)

The plan's 12 checkboxes are all still unchecked; actual status, each merge SHA confirmed an ancestor of
the integration branch with `git merge-base --is-ancestor`:

| ticket | actual status | evidence |
|---|---|---|
| P0-1 NUMCTX merge | DONE | `cc6a0c3` |
| P0-2 metric ratification | DRAFT, operator signature blank | `ee11e85`; `docs/eval-reports/2026-08-26-precision95-metric-ratification.md:3-9` |
| P0-3 multi-hop GT plan | DONE | `15f678d` |
| QW-1 citation adoption note | note DONE; adoption BLOCKED on T-F7 | `cff3b53` |
| QW-2 confidence v0 | LANDED (real separator, heavy overlap, no threshold) | `fd05dbf` |
| QW-3 reranker seat | REJECT | `825c57b` |
| SB-1 chunk boundary | REJECT both arms | `7b679f7` |
| SB-2 multi-hop GT | first slice W-A4 LANDED (31 items / 22 papers); W-A1, W-A2, W-A3, W-A5 not authored | `7191f8e`, `336d78c`, `259b007`; plan `docs/eval-reports/2026-08-27-multihop-gt-authoring-plan.md` (~130 items) |
| SB-3 agentic loop | LANDED: arm (a) ADOPT-as-candidate (not wired), arm (b) REJECT | `8d7c478`..`901a108`; report §5 |
| SB-4 Qwen3.8-27B pilot | NOT STARTED as a recorded ticket (no commit, no report) | `git log --all --grep=SB-4` finds only ledger commits |
| IN-1 integration | NOT STARTED; gated on P0-2 signature | no implementation commit (`git log --all --grep=IN-1` hits only SB-3 and ledger commits) |
| IN-2 calibration | NOT STARTED; gated on anchors | same |

### In-progress and blocked (2026-08-28; re-checked 2026-11-10)

*SB-1 was listed here as IN PROGRESS; it is merged as REJECT (row moved to the lane-outcomes table). Its instrument finding, kept for every future ticket: **ver84 MRR carries a tie-break noise floor of ~0.0074** — two identical-configuration BGE baseline runs differed on exactly one item of 82 (`Q-WAYB-026`, two near-equal papers swapped ranks 1 and 2, 0.5/68 = 0.00735 MRR); R@10 and block-P@1 were bit-identical, so a ver84 MRR movement below ~0.0074 is indistinguishable from one tied pair flipping. Both operator-gated rows below are still unsigned on 2026-11-10.*

| lane / item | status | notes |
|---|---|---|
| **P0-2** — metric-ratification sign-off | **BLOCKED** — on operator signature (still unsigned 2026-11-10: `Signed: ___` at `docs/eval-reports/2026-08-26-precision95-metric-ratification.md:3-9`) | `docs/eval-reports/2026-08-26-precision95-metric-ratification.md` remains DRAFT; no headline 0.95 claim is ratifiable until signed. Gates IN-1. |
| **T-F7** — X-C member-block citation adoption | **BLOCKED** — on operator sign-off (still pending 2026-11-10; foundation-protected paths: `contracts/`, DATA-CONTRACTS §M7) | Batched rider PR for Variant A wiring. Measured effect: gt_wmr passage hit-rate 93.9%→95.5%, monotone, zero-risk by construction. Now additionally supported by the 12/12 anchor-offset finding from SB-2/W-A4 above. Design note: `docs/design-notes/2026-08-28-xc-member-citation-adoption.md`. |

