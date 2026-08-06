# Project Status — single source of truth

*Written 2026-08-05. Every claim below was re-derived against live source/git on that date — see the
citation next to each one (commit SHA, `file:line`, or report path). This doc supersedes any status
claim in `AGENTS.md`'s old owner table or any doc listed §7 as HISTORICAL. If this doc and another doc
disagree on a *fact* (not a frozen shape — `DATA-CONTRACTS.md` still wins those), this one wins; fix
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

A second, experimental corpus now also exists: **Waymo AV-safety**, a from-scratch causal-inference-
style corpus scoped to autonomous-vehicle safety research, built with the same pipeline pointed at a
separate data directory. It is much smaller and mid-build, not production-grade — see
`docs/WAYMO-CORPUS-STATUS.md` for the detailed state (a parallel workstream owns that doc; if the link
404s, it hasn't been written yet as of this doc's writing).

**Live main-corpus numbers** (measured 2026-08-05 via read-only SQLite against
`/home/omar/ai-projects/research-system-rag-data/papers.db`, path read from that dir's
`config.yaml`, and a `GET /collections/papers` call to the local Qdrant on `localhost:6333`):

| metric | value | how measured |
|---|---|---|
| papers at `ingest_state.stage='done'` | **12,390** | `select stage, count(*) from ingest_state group by stage` — all 12,390 rows are `done`, no other stage present |
| `papers.doc_type` breakdown | **12,385 paper / 5 book** | `select doc_type, count(*) from papers group by doc_type` |
| `chunks` rows | **399,676** | `select count(*) from chunks` |
| `blocks` rows | **2,720,572** | `select count(*) from blocks` |
| `summaries` rows | **12,491** | `select count(*) from summaries` (12,385 one-per-paper + 106 book chapter/overview summaries across the 5 books) |
| `quarantine` rows | **80** | `select count(*) from quarantine` |
| Qdrant `papers` collection | **412,167 points**, 823,956 indexed vectors (dense 2560-dim + sparse IDF), 8 segments, status `green` | `curl localhost:6333/collections/papers` |

**Waymo corpus** (`waymo/data/config.yaml`, `db_path: waymo/data/papers.db`, collection
`waymo_av_safety` — this directory is gitignored, `.gitignore:19`, but present on disk):

| metric | value |
|---|---|
| `papers` rows | 17, all `doc_type='paper'` |
| `ingest_state` stages | `done`=17, `chunked`=810 (mid-build, Pass-2 not yet run on those) |
| `chunks` rows | 388 |
| Qdrant `waymo_av_safety` collection | 405 points / 405 indexed vectors |

The Waymo `config.yaml` also carries a 700+-entry `ingest_paper_ids` allowlist (T-EVAL-style scoped
harvest, `contracts/config.py:88` `ingest_paper_ids`) — it is not query-driven like the main corpus.

## 2. How to actually run it

Every flag below traces to an actual `add_argument`/argv line — no flag is inferred.

| Module | Key flags | Purpose |
|---|---|---|
| `app.build_corpus` | `--target N` (required), `--parse-workers`, `--events-path`, `--batch-size`, `--telemetry-poll-interval`, `--run-id` | Supervisor loop: repeatedly invokes `app.ingest` until `ingest_state` has `N` papers at `stage='done'` (`app/build_corpus.py:712-741`) |
| `app.ingest` | `--parse-workers`, `--limit`, `--scratch`, `--paper-ids-file`, `--no-preflight`, `--force`, `--events-path`, `--telemetry-poll-interval` | One harvest→parse→chunk→embed→store pass (`app/ingest.py:404-433`) |
| `app.parse_phase` | `--shard-index`, `--shard-count` | Runs Pass-1 parsing for one shard of a sharded run (`app/parse_phase.py:76-78`) |
| `app.prefetch_pdfs` | `--max-idle N`, `--log-every N` | Standalone PDF-backlog downloader, runs forever unless `--max-idle` bounds it (`app/prefetch_pdfs.py:344-364`) |
| `app.ingest_local` | `--stage-only`, `--drop-dir PATH`, `--dry-run` | Stages `drop_in/` PDFs into `pdf_cache` + a manifest, then normally invokes `app.ingest` (`app/ingest_local.py:340-354`) |
| `app.serve` | `--data-dir` (optional) | MCP server (`semantic_search`, `search_papers`, `get_paper`, `get_span`) (`app/serve.py:47-58`) |
| `app.doctor` | `--no-auto-start`, `--check-mcp` | Readiness check for TEI/vector-store/GROBID, auto-starts stopped containers by default (`app/doctor.py:311-318`) |
| `app.init_config` | `--data-dir` (required), `--force`, `--link` | Scaffolds a new corpus's `config.yaml` from `config.example.yaml` (`app/init_config.py:46-61`) |
| `app.rechunk` | `--config`, `--paper-ids`, `--paper-ids-file`, `--dry-run` | Re-chunks-from-blocks for already-ingested papers without a full re-ingest (`app/rechunk.py:262-275`) |
| `app.reindex_idf` | `--collection` (required), `--config`, `--dry-run`, `--i-have-a-snapshot`, `--backup-root`, `--keep N`, `--use-clone-swap`, `--vector-store-host/-port` | Adds the sparse IDF modifier to an existing collection (`app/reindex_idf.py:204-238`) |
| `app.delete_docs` | `PAPER_ID [PAPER_ID ...]` (positional), `--yes` (required to actually delete) | Cascade-deletes papers (chunks/blocks/summaries/vectors) (`app/delete_docs.py:54-58`) |
| `app.snapshot` | `--config`, `--backup-root`, `--keep N`, `--vector-store-host/-port` | Takes/prunes Qdrant collection snapshots (`app/snapshot.py:222-235`) |
| `app.obsidian_export` | `--config`, `--out-dir`, `--limit N` | Exports papers as an Obsidian vault (`app/obsidian_export.py:187-195`) |
| `app.corpus_integrity` | none (module-level `main()`, reads `Config` directly) | Standing check: every `done` paper has ≥1 chunk and ≥1 block row (`app/corpus_integrity.py`) |
| `app.dashboard.server` | `--port` (default 8700), `--data-dir` (required), `--token`, `--host` (default `0.0.0.0`) | Corpus dashboard web server (`app/dashboard/server.py:671-684`) |
| `app.dashboard.verify_numbers` | `--data-dir` (required), `--host`, `--port` | Independent cross-check of the dashboard's own numbers against ground truth (`app/dashboard/verify_numbers.py:580-583`) |
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
of the 4 tools that support it (trap (b)). The Waymo corpus (§1) is exactly this pattern — see
`waymo/data/config.yaml`.

## 3. Shipped-work ledger

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

Scout script (`worktree-waymo-corpus-expansion` branch, 7 commits, unmerged — see §8) plus the corpus
itself (§1's live numbers, 17 done / 810 mid-build). Full detail, including whatever verdict a
parallel workstream reaches on its viability: `docs/WAYMO-CORPUS-STATUS.md`.

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

Live queue, as of 2026-08-05, from `docs/BACKLOG.md` — not edited by this workstream, reflected as
found (a parallel workstream may be correcting some of these concurrently):

- **D-8** — bound retries for repeatedly-failing quarantined papers (OPEN, lower priority since O-2's
  fix removed the main cause).
- **D-9** — land the orphaned unexpected-exception safety net. The only genuinely unmerged branch in
  the repo per `docs/BACKLOG.md`'s own audit (`T-SEED-combined-fixes`, see §8) — `main` has no
  catch-all for an unforeseen exception today.
- **D-11 / D-12** — listed OPEN in `docs/BACKLOG.md`, but both fixes are already on `main` (§3/§4
  above document the actual landed commits: `4e07eb4` and `f351a27`). `BACKLOG.md`'s status for these
  two rows appears stale relative to `main`.
- **B-1** — TOC pages mis-classified as headings (inflates book chapter-unit counts).
- **B-2** — Strategy-B junk chapter titles (some titles are page furniture, not real headings).
- **B-3** — T-DOC87 boundary change will not ship as-is (§5 above).
- **B-4** — unused outline splitter not yet removed (review date 2026-08-29 per the operator).
- **B-5** — `reindex_idf`'s non-destructive `--use-clone-swap` path exists (PR #203) but is not yet
  the default; the destructive rebuild path still is.
- **O-2b** — GROBID "unparseable TEI" (6 papers, a *different* failure from the 500s in §4) — open,
  worth checking whether it shares the same deterministic-but-labelled-transient pattern.
- **O-3** — a stale `git stash` entry of unknown provenance; do not touch without the owner.

## 7. Doc map

Every markdown file at repo root (`find . -maxdepth 2 -name '*.md'`) and under `docs/`
(`find docs -name '*.md'`), classified AUTHORITATIVE / REFERENCE / HISTORICAL:

### Repo root

| Doc | Class | Notes |
|---|---|---|
| `AGENTS.md` | AUTHORITATIVE | Entry-point index — start here. |
| `CLAUDE.md` | AUTHORITATIVE | Same content as `AGENTS.md`, for Claude Code's auto-load. |
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
| `docs/RUNBOOK.md` | AUTHORITATIVE | Operator bring-up after a reboot; dashboard token location; Tailscale access. |
| `docs/GRAPHIFY.md` | AUTHORITATIVE | Knowledge-graph dev-tooling setup/usage (not product scope). |
| `docs/BOOK-INTEGRATION-CLOSEOUT.md` | AUTHORITATIVE | Book integration closeout — how it works, what shipped, every rejected approach with its falsifying test. |
| `docs/TEST-AUDIT-2026-07-31.md` | REFERENCE | Point-in-time test-suite audit; findings T-1..T-3 shipped (PR #212), T-4..T-8 tracked live in `docs/BACKLOG.md`. |
| `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` | AUTHORITATIVE | Waymo corpus harvesting handoff/keyword strategy. |
| `docs/CORPUS-EXPANSION-RESEARCH.md` | REFERENCE | Non-arXiv source options investigated, so they aren't re-studied. |
| `docs/ROADMAP-AND-PRIORITIES-PLAIN-ENGLISH.md` | HISTORICAL | 2026-07-17 plain-English roadmap/reprioritization opinion piece; superseded as a status source by this doc. |
| `docs/THE-DECISION-plain-english.md` | HISTORICAL | A single 2026-07-17 decision clarification, resolved. |
| `docs/YOUR-USE-CASES-can-the-system-do-this.md` | HISTORICAL | 2026-07-17 capability Q&A snapshot; capabilities have moved on since. |
| `docs/DECISIONS-PENDING-operator.md` | HISTORICAL | 4 book-RAG decisions from 2026-07-29; resolved by the Exp 1-5 verdicts (§5) and `DECISION-book-rag-what-to-ship.md`. |
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
| `docs/eval-reports/*.md` | AUTHORITATIVE | Primary source for every book-RAG experiment verdict (§5) and several measurement claims (§1). |
| `docs/superpowers/plans/*.md`, `docs/superpowers/specs/*.md` | REFERENCE | Per-feature design/implementation plans (superpowers workflow artifacts); the newest, `2026-08-05-paper-author-org-tagging-design.md` and `2026-08-05-waymo-corpus-expansion.md`, are the only source for those two efforts' design (§3). |

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
