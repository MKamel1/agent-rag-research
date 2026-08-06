# Design — Dashboard Control Panel (OG-43): full tunable-parameter inventory

> **HISTORICAL** — superseded by the tag-pool design. Current state: [PROJECT-STATUS.md](PROJECT-STATUS.md).

*Owner-approved direction 2026-07-18. The dashboard becomes a full control panel: start/pause/resume
(exists) + edit keyword tags + edit all SAFE tuning parameters, grouped by what they affect. Keyword
edits AUGMENT the one library (owner decision). Storage-identity params (db/collection/blob) are NOT
exposed — switching those is a deliberate "new corpus" action, not a slider. Built AFTER the dashboard
bug-fix PR (OG-42/OG-44) lands. This doc is the parameter inventory; present before building.*

## Group 1 — COLLECT (what enters the library — drives the downloader `app.prefetch_pdfs`)
| Parameter | Current | Default | Recommended | Status / build cost |
|---|---|---|---|---|
| **keyword tags** (`focus_area_queries`) | 33 causal queries | — | edit = **augment** (add topics) | Exists as config; editing per-run needs run-scoped override plumbing. Feeds the downloader now (cache-first). |
| **arXiv subject / category** (e.g. `stat.ME`, `econ.EM`, `cs.LG`, `stat.ML`) | none (keyword-only) | none | pick a few relevant | **NEW feature.** Harvester builds only `all:"term"` today — no `cat:` filter. Needs: new `Config` field (**foundation** — contracts/config.py) + `ArxivSource` query-builder change (rag/harvester.py) + run-scoped override + UI. |
| **date range** (`submittedDate:[…]`) | none | none | optional (e.g. 2015→now) | **NEW feature.** Same shape as category: new `Config` field (**foundation**) + query-builder + UI. |
| **target** (paper count) | per run | 30000 cap | set per run | Exists (`--target`/`--limit`). |
| **relevance_filter** | off | off | off | Dead code (OG-36) — prerequisite only if we add noisy sources; not wired. |

## Group 2 — BUILD (how papers get processed — the GPU pipeline)
| Parameter | Current | Default | Recommended | Status / build cost |
|---|---|---|---|---|
| **parse_workers** | 3 | 1 | 3 | Exists (`--parse-workers`). +63% Pass-1 throughput (T-DOC51). |
| **parse_batch_size** | 4 | 4 | 4 | Exists. Papers per MinerU batch. |
| **build batch-size** (`build_corpus`) | whole cache/iter | (whole set) | whole set | Exists (`app.build_corpus --batch-size`). Cap per iteration. |
| **telemetry_poll_interval** | 5s | 5s | 5s | Exists. GPU sampling cadence. |
| **MINERU_VIRTUAL_VRAM_SIZE** (advanced) | auto | auto (24GB→ratio 8) | auto | Advanced; leave auto unless tuning. |

## Group 3 — SEARCH (how the AI queries the FINISHED library — query-time, doesn't change the corpus)
| Parameter | Current | Default | Recommended | Status / build cost |
|---|---|---|---|---|
| **number of results (top-k)** | 10 | 10 | 10 (tune 5–20) | Exists per-query (`app/serve.py` `semantic_search`/`search_papers` `k=10`). Expose a configurable DEFAULT. |
| **rerank pool size** (`_RERANK_POOL_SIZE`) | fixed constant | — | — | Candidates reranked before top-k (rag/retriever.py). Advanced knob; expose read-only first, editable later. |
| **search filters: subject / date** | data present | — | — | Every paper already stores `categories` + `published`/`updated` (contracts/harvester.py PaperRef), so query-time filtering by subject/date is feasible. Confirm `SearchFilters` supports them; wire into the MCP/search if not. |

## Build notes / sequencing
- **Cheap, no-foundation, do first:** expose + edit Group 2 params, target, keyword tags (run-scoped
  override), and top-k default. These reuse existing CLI/args + the override-config mechanism
  (`app/ingest.py::_write_override_config_dir`).
- **Bigger lift, FOUNDATION (flag for human sign-off):** arXiv subject/category + date-range download
  filters need new `Config` fields (`contracts/config.py`, `config.yaml`) + `ArxivSource` query
  construction + run-scoped overrides. This is the one genuinely new backend capability here — worth
  its own ticket (proposed **OG-45**), separate from the UI wiring.
- **Safety boundary:** never expose db_path / collection / blob_dir as edit fields (corpus
  fragmentation). "New corpus" is a distinct, deliberate action.
- All control-plane edits go through the existing token-gated `POST /api/control` (Tailscale boundary
  + `hmac.compare_digest`); changing keywords/params = restart/relaunch the build with the override.
- Fold in the OG-42/OG-44 accuracy fixes + the deferred completeness gaps (mode indicator, prefetch
  status, Pass 1/2 labels, VRAM row) so the panel is correct AND complete in one pass.

## Exhaustive knob catalog (code sweep, 2026-07-18) — synthesis

Two read-only sweeps catalogued **every** Config field, CLI flag, and tunable constant in the codebase
(full tables in the sweep task outputs; the load-bearing conclusions are here). ~60 knobs total; most
are internal safety/vendor constants that should NOT be dials. Curated recommendation below.

### CORRECTIONS to the summary tables earlier in this doc (sweeps caught these)
- **`MINERU_VIRTUAL_VRAM_SIZE` is NOT currently controllable.** No repo code reads or forwards it — the
  vendored `mineru` package reads it from the *shell env* before Python starts, and nothing plumbs it
  into the `app.parse_phase` subprocess. Listing it as a tunable "auto (24GB→ratio8)" was wrong.
  Exposing it needs new plumbing (pass `env=` into the parse subprocess). Real tested numbers exist
  (ratio8/24GB @ 3 workers = 280.7 pages/min best; ratio16/32GB OOMs) — keep as a documented default,
  not a live slider, until plumbed.
- **`Config.top_k` (=10) and `Config.rerank_depth` (=50) are DEAD fields** — declared but never read. The
  real top-k is the per-query `k` (default 10, `app/serve.py`); the real rerank pool is hardcoded
  `_RERANK_POOL_SIZE=32`, itself capped by the reranker's `_MAX_BATCH_SIZE=32`. A slider on
  `Config.rerank_depth` would control nothing. Fix wiring (foundation) or expose the real knobs.
- **`parse_batch_size` (=4) is only the FLOOR.** Once `AdaptiveBatchSizer` is active, the real Pass-1
  batch size is decided by an AIMD grower whose knobs (min/max/safety_margin/growth) are all hardcoded
  in `app/assembly.py`'s constructor call — invisible to config.yaml and CLI. Biggest "tunable but
  unexposed" gap.

### TRAPS to honor when exposing these (don't create foot-guns)
- **`prefetch_target` (30000) vs `build_corpus --target`:** if target > prefetch_target the build stops
  short (downloader never fills past prefetch_target). Expose them together / keep in sync.
- **Two different PDF-download delays:** `prefetch_pdfs` = 15s (arXiv robots.txt Crawl-delay), pipeline
  = 1.5s (assembly). Different code paths, different reasons — never merge into one slider, never lower.
- **arXiv rate limit 3.0s / crawl-delay 15s / metadata retry policy** = ToS-derived "don't get banned"
  floors — display maybe, never expose as lowerable.
- **`relevance_filter: "embedding"`** is selectable in the type but dead code (OG-36) — do not expose as
  a live toggle (silent no-op).
- Storage-identity (`db_path`/`blob_dir`/`collection`/`pdf_cache_dir`, embedder model/dim,
  `_OLLAMA_MODEL`) = "new corpus" actions, never dials.

### CURATED SET to actually expose (the rest stay advanced/internal/hidden)
**Collect:** focus_area_queries (keywords) · corpus_cap/`--limit`/`--target` (one unified "how many",
synced with prefetch_target) · arXiv subject + date filters (OG-45, new) · `--max-idle` (optional).
**Build:** `--parse-workers` (⭐ measured +63% @ 3) · parse_batch_size (label it "floor; adaptive sizer
grows it") · `build_corpus --batch-size` · telemetry_poll_interval · **AdaptiveBatchSizer max/safety
margin** (advanced — the real batch driver) · MINERU VRAM tier (advanced, needs plumbing first).
**Search:** top-k (per-query default) · hybrid_dense_weight (⭐ the one genuinely-wired quality dial,
0.5, [0,1]) · subject/date search filters (⭐ already wired end-to-end — UI only) · rerank pool
(advanced; wire real `_RERANK_POOL_SIZE`, not the dead Config field).
**Advanced/reliability worth a readout (not a slider):** IngestionOrchestrator.max_retries (=2,
hardcoded) · chunk `_MAX_CHUNK_WORDS`/`_OVERLAP_MAX_WORDS` (self-documented retrieval-quality knobs,
range 150-300 for overlap) · preflight disk/VRAM floors (author flagged promotable) · query-path
reranker/embedder have NO retry (reliability gap) · GpuLock has no timeout (a wedged holder hangs all
queries — surface "waiting on GPU lock" on the dashboard).

Full per-knob tables (file:line, current/default, foundation?, overridable?, safe?) live in the two
sweep reports; port them verbatim into an appendix here when building.

## Resolved decisions (owner, 2026-07-18)
1. **Inventory:** not final — an EXHAUSTIVE code sweep (2 parallel agents: Collect+Build side, Search+
   Reliability side) is cataloguing EVERY knob/constant/config field/CLI arg in the codebase. Their
   merged tables replace/extend the inventory above. Owner: "be exhaustive — we were collecting these
   variables along the way."
2. **arXiv subject/date download filters: BUILD NOW** (OG-45), including the foundation change (new
   `Config` fields in contracts/config.py + config.yaml) — human sign-off required on the protected
   files. Not deferred.
3. **Query-time search filters (subject/date at search time): INCLUDE NOW** — wire subject/date
   filtering into the retrieval/MCP path so queries can be scoped (e.g. "econometrics, 2018+"). Confirm
   `SearchFilters`' real fields first (sweep agent B is checking) and wire whatever's missing.

Build order once the sweep lands: finalize the full inventory → present → then build (cheap UI-exposed
params + top-k first; arXiv download filters + query-time search filters as the foundation-touching
pieces with sign-off; fold in OG-42/OG-44 accuracy fixes + completeness gaps).
