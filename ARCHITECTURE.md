# ARCHITECTURE — V0 Deep-Module Design

**Scope:** V0 (the plain grounded RAG cache). Designed so V1–V3 slot in behind existing seams
without rewriting V0. Vocabulary follows `codebase-design` (module / interface / seam / adapter /
depth). Companion docs: [PRD.md](PRD.md), [CONTEXT.md](CONTEXT.md).

## Design principles (non-negotiable)

1. **Deep modules.** Small interface, lots of behaviour behind it. Callers/tests learn little, get a lot.
2. **Source-of-truth vs. derived.** `DocumentStore` (SQLite + blobs) is authoritative; `VectorIndex`
   is derived from it (ADR-04) — its own `rebuild()` is a same-model Qdrant reindex (scrolls and
   re-upserts its own existing points, no re-embedding); recovering it from `DocumentStore` after an
   embedding-model swap needs a separate, not-yet-built orchestrator pass. This split is still the
   backbone of replaceability.
3. **Accept dependencies, return results.** Every module takes its collaborators as arguments and
   returns data (no hidden singletons, no ambient side effects) → each is testable in isolation.
4. **Build a seam only where behaviour actually varies.** *Two adapters = real seam; one = hypothetical.*
   Real V0 seams (build them): `Parser`, `Embedder`, `VectorStore`. Everything else: concrete but
   cleanly shaped so a second adapter is *possible*, not pre-built.
5. **The interface is the test surface.** Callers and tests cross the same seam. If a test needs to
   reach *past* the interface, the module is the wrong shape.

## Module map

```
IngestionOrchestrator ──drives──▶ Harvester → Parser → {Chunker, Summarizer} → Embedder → DocumentStore + VectorIndex
                                                                                                      │
Query path:  McpServer ──▶ Retriever ──(reads)──▶ VectorIndex + DocumentStore ◀──────────────────────┘
                              │
                              └──uses (injected, GPU-bound)──▶ Reranker

Real seams (⇄ = swappable adapter):  Parser⇄   Embedder⇄   VectorStore⇄
```

`Chunker` and `Summarizer` both consume `ParsedDoc` independently (neither depends on the other's
output) and both must finish before `Embedder`, which embeds chunk text **and** summary text.

Ten modules, each independently ownable (owners A–F) and testable through its interface.

---

## Modules (interface = the full contract: signature + invariants + errors + config)

### M1 · Harvester  *(owner A)*
- **Interface:** `harvest(focus_area, cap, ordering) -> Iterator[PaperRef]`
  `PaperRef` — authoritative shape in `DATA-CONTRACTS.md` §M1; do not re-derive its fields here.
  - *Invariants:* deduped by **base paper_id (latest version)**; respects arXiv rate limits;
    **idempotent/resumable** — re-running skips already-seen ids.
  - *Errors:* transient API → retried; hard failure → surfaced, not swallowed.
  - *Config (levers):* `focus_area` queries, `corpus_cap`, `ordering`, `relevance_filter` (records the
    precomputed relevance score but filters nothing in V0). Levers arrive as one injected `Config`
    object (see `DATA-CONTRACTS.md` §Config) — never read from `os.environ` inside a module.
- **Hides (depth):** arXiv API paging, query expansion across categories, dedup, rate-limiting, resume cursor.
- **Seam:** `Source` (arXiv adapter). *Hypothetical for V0* (one source) — keep the interface
  source-agnostic; **do not** build a plugin registry. V3 adds RSS/OpenAlex/Unpaywall adapters here.
- **Test:** fake `Source` yielding fixture `PaperRef`s; assert dedup + resume.
- **Real `ArxivSource.fetch()` issues one sequential request per `focus_area_queries` term, not one
  combined query.** A single `" OR "`-joined query across all ~33 configured terms reliably got
  `HTTP 429`/timeout from arXiv and returned zero papers across three attempts; splitting into
  per-term requests (each still spaced by the existing rate-limit delay) fixed it.
- **Harvest-level failures are quarantined too, not silently dropped.** `Harvester` is constructed
  with a real `QuarantineSink` (`app/assembly.py`'s `_sqlite_harvest_quarantine_sink`) that writes to
  the same `quarantine` table `IngestionOrchestrator` uses for parse/summarize failures, under stage
  `"harvested"` (a fixed `"<unknown>"` paper_id sentinel for page-level failures with no paper
  identity yet). Previously no sink was wired, so an exhausted-retry-budget harvest failure left no DB
  row and no log line anywhere.

### M2 · Parser  *(owner B)*
- **Interface:** `parse(raw: PdfBytes | LatexSource) -> ParsedDoc`
  `ParsedDoc` — authoritative shape in `DATA-CONTRACTS.md` §M2; do not re-derive its fields here.
  - *Invariants:* **every block carries a provenance anchor (bbox+page)**; equations preserved as LaTeX;
    reading order correct. (Anchor is block-level, not char-offset — validated, §6A.)
  - *Errors:* parse failure → typed error → paper **quarantined**, pipeline continues.
- **Hides (depth):** MinerU body parse + GROBID references + PDF-vs-LaTeX routing.
- **Seam:** `Parser` adapter — **REAL** (Spike 1 locked MinerU as the sole V0 parser, PR #41;
  Marker and Docling were benchmarked and dropped — `phase0-results.md`).
- **Test:** golden fixtures — PDFs with expected `ParsedDoc`; every adapter runs the *same* golden set.
- **V3 extension:** VLM fills `figures[].vlm_description` — enrichment behind `ParsedDoc`, callers unchanged.

### M3 · Chunker  *(owner C)*
- **Interface:** `chunk(ParsedDoc) -> [Chunk]`
  `Chunk` — authoritative shape in `DATA-CONTRACTS.md` §M3; do not re-derive its fields here.
  - *Invariants:* equations/code **never split** from defining context; child chunks link to a
    `parent_id` **block_id** — never a chunk_id (parent-child, `on` in V0; multi-block anchoring rule
    in DATA-CONTRACTS §Provenance & structure pins which block when several are grouped into one
    chunk); anchors preserved end-to-end; each chunk's text is prefixed with paper title + section path
    (free, string-level — not an LLM call).
  - *Config:* `child_parent_expansion on|off` (lever). **No `contextual_header` config exists in V0** —
    there is nothing to toggle.
- **Hides (depth):** section-aware splitting, parent linkage, atomicity rules, the title/section prefix.
- **V0 does NOT build contextual-header generation** — deferred to V1, full rationale + V0's
  monitoring-only obligation: PRD ADR-07. Do not implement the header-LLM pass in V0.
- **Seam:** none needed for this in V0 (no LLM dependency injected here yet). V1 adds an internal seam
  for the header-LLM when it builds the feature — see extensibility table below.
- **Test:** `ParsedDoc` fixture → assert boundaries, parent links, anchors intact, prefix present,
  `contextual_header is None` for every chunk.

### M3B · Summarizer  *(owner C)*
- **Interface:** `summarize(ParsedDoc) -> str` (returns `summary_text`; `summary_id` is always the
  deterministic `f"{paper_id}:summary"`, per DATA-CONTRACTS §IDs — never invented by this module).
  - *Invariants:* non-empty output; **GPU-bound** — the local generation LLM (ADR-08, served per
    ADR-09) acquires the shared `GpuLock` around its inference call exactly like Embedder and the
    reranker (Operational invariants §3 below). Unlike Embedder/Reranker, it is **not** expected to
    stay resident for the whole ingest process — §3's measured VRAM budget means it's evicted before
    the parse phase and reloaded for the finish phase (`unload()`, `before_parse_phase` hook).
  - *Errors:* a `ParsedDoc` with no usable prose (e.g. figures-only after a bad parse) → `PermanentError`
    → quarantine, not a crash.
- **Hides (depth):** the summarization prompt, the model choice/serving stack, GPU-lock acquisition.
- **Seam:** *hypothetical* (one local model, no plugin registry — principle 4) — but its LLM client is
  still an **injected dependency** (principle 3, same as every module), so a deterministic
  `FakeSummarizer` powers zero-GPU downstream tests exactly as `FakeEmbedder` does.
- **Note:** `PaperRecord` (DATA-CONTRACTS §M5) requires `summary_text`/`summary_id` as non-nullable
  fields. Summaries are in V0 scope (CONTEXT.md's V0 definition names them explicitly) — do not defer
  this to V1 by analogy with contextual headers; it's a different decision.
- **Test:** `ParsedDoc` fixture → non-empty `summary_text`; the GPU-lock test asserts Summarizer and
  Embedder never hold the lock simultaneously (shared test with Embedder/Orchestrator).

### M4 · Embedder  *(owner C)* — the replaceability seam
- **Interface:** `embed(texts:[str]) -> [Vector]`; property `{model_id, dim, version}`
  - *Invariants:* deterministic per (text, model, version); batched; L2-normalized.
- **Hides (depth):** the model, TEI/vLLM serving, batching, MRL truncation.
- **Seam:** `Embedder` adapter — **REAL.** Model swap is *planned* (ADR-02/04); V1 dual-embeddings adds a
  second instance. This seam is what makes vectors disposable/rebuildable.
- **Test:** a **deterministic fake** (hash→vector) is the default dependency for *all* downstream tests;
  the real embedder is tested only in isolation.

### M5 · DocumentStore  *(owner D)* — source of truth
- **Interface:** `put(PaperRecord)` · `get(paper_id)` · `get_blocks(paper_id)` · `get_block(block_id)` ·
  `get_chunk(chunk_id)` · `get_summary(summary_id)` · `get_span(anchor) -> text`
  - *Invariants:* **authoritative**; holds all text so `VectorIndex` is rebuildable; anchors resolve to
    text. `get_block`/`get_chunk`/`get_summary` exist specifically so `Retriever` (M7) never has to parse
    a `chunk_id`/`block_id`/`summary_id` string itself to expand a `Hit` into a grounded passage — that
    knowledge stays inside DocumentStore (full shapes/behavior in `DATA-CONTRACTS.md` §M5).
- **Hides (depth):** SQLite schema, filesystem blob storage, provenance resolution, the ID-format
  conventions in DATA-CONTRACTS §IDs.
- **Seam:** `MetadataStore` (SQLite) — one adapter; **extended by schema** for claims (V1), citation edges (V2).
- **Test:** temp SQLite + temp blob dir.

### M6 · VectorIndex  *(owner D)* — derived, rebuildable
- **Interface:** `upsert(id, vector, payload)` · `hybrid_search(qvec, qtext, filters: SearchFilters?, k) -> [Hit]` · `rebuild()`
  (`Hit`/`SearchFilters` shapes: `DATA-CONTRACTS.md` §M6 — `filters` is a typed `SearchFilters`, never a
  raw `dict`; `Hit` carries `kind` so callers don't parse the id string).
  - *Invariants:* derived from `DocumentStore`; **versioned per embedding model**; hybrid = dense + sparse
    fused by the **frozen weighted-RRF formula** in DATA-CONTRACTS §M6 (both the fake and real adapter
    must implement the identical formula, or the contract test doesn't prove anything).
- **Hides (depth):** Qdrant hybrid + RRF + quantization + versioned collections.
- **Seam:** `VectorStore` adapter — **REAL** (Qdrant now; LanceDB candidate; the DB choice lives *here*,
  callers never import Qdrant). This is where the whole Chroma/Qdrant/LanceDB question is contained.
- **Test:** an in-memory fake `VectorStore` (brute-force cosine + BM25) powers `Retriever` tests; real
  Qdrant gets an isolated **contract test** (same assertions as the fake).

### M7 · Retriever  *(owner E)* — the crown-jewel deep module
- **Interface:** two methods, sharing one internal pipeline, differing only in which `kind` they search
  and how they resolve a `Hit`:
  - `retrieve(query:str, filters: SearchFilters?, k) -> ([GroundedResult], RetrievalCoverage)` —
    **passage-level.** Internally restricts the underlying `hybrid_search` to `kind="chunk"` regardless
    of what the caller passed for `filters.kind` (categories/date filters from the caller are preserved;
    `kind` is fixed by which method you called, not a caller choice — this is what keeps "which
    granularity am I searching" unambiguous without a runtime error path). Never returns a summary/
    whole-paper match — a summary has no block to anchor to, so it cannot satisfy `GroundedResult` (see
    DATA-CONTRACTS §M7).
  - `retrieve_papers(query:str, filters: SearchFilters?, k) -> ([PaperSearchResult], RetrievalCoverage)`
    — **whole-paper/summary-level**, **additive** to `retrieve()` (does not change its signature).
    Internally restricts `hybrid_search` to `kind="summary"`. Closes the summary-retrieval gap: forcing
    summary results through the anchored `GroundedResult` envelope has no valid anchor to offer
    (DATA-CONTRACTS §M7). Placed on `Retriever`, not composed ad hoc inside `McpServer`, because the
    retrieval algorithm (embed-query → hybrid → RRF → rerank) is this module's secret — building it a
    second time in M8 would leak that secret into the "acceptably thin" protocol edge (module-design
    "hide the secret").
  - **`RetrievalCoverage` (T-DOC28):** both methods return their results list paired with a
    `RetrievalCoverage` carrying `candidate_count` — the true pre-rerank/pre-top_k `hybrid_search` pool
    size (`len(Hit list)`), which `list[GroundedResult]`/`list[PaperSearchResult]` alone can't carry once
    truncated to `k`. `McpServer` uses it to build the real `Coverage.candidates` (§M8) instead of the
    `len(results)` stand-in it used before this fix. `RetrievalCoverage` itself is never part of an MCP
    tool's response — DATA-CONTRACTS §M7.

  `GroundedResult`/`PaperSearchResult`/`SearchFilters` — authoritative shapes in `DATA-CONTRACTS.md`
  §M7/§M8/§M6; do not re-derive fields here. **Forward-compat:** `GroundedResult` is a *record with an
  envelope* from V0 — `evidence_tier` is pinned to `"A"` and `metadata` is empty in V0, so V1/V2 (tiers
  B–D, `status`, `conditions`) **fill fields rather than changing the type** (PRD §8.5). Never return
  bare strings.
  - *Invariants:* **every `retrieve()` result is grounded** (has anchor + resolvable citation).
    `retrieve_papers()` results are explicitly *not* anchored — that's the whole reason they're a
    different type. Shared pipeline behind both methods: embed-query → hybrid(dense+sparse) → RRF →
    cross-encoder rerank → resolve each `Hit` — `retrieve()` via `DocumentStore.get_chunk`/`get_block`
    into a `GroundedResult` whose `passage_text` is the resolved `Chunk`'s own text (**not** a
    `get_span`/parent-block fetch — DATA-CONTRACTS §Provenance & structure has the full reasoning);
    `retrieve_papers()` via `DocumentStore.get_summary`/`get` into a `PaperSearchResult` → attach
    provenance/citation.
- **Hides (depth):** the entire retrieval pipeline behind two method calls.
- **Dependencies (constructor-injected, per principle 3):** `Embedder`, `VectorStore`, `DocumentStore`,
  and **`Reranker`** — the reranker is a real injected dependency, not merely an "internal seam"; it is
  GPU-bound (single-GPU lock, same as Embedder/Summarizer) and needs a `FakeReranker` for Retriever's
  tests to actually be zero-GPU (DATA-CONTRACTS §M7 "Reranker"; TEST-STRATEGY fakes). Both `retrieve()`
  and `retrieve_papers()` rerank their candidates through the same injected `Reranker` — summary text is
  a valid `RerankCandidate.text` exactly as chunk text is (DATA-CONTRACTS §M7 "Reranker" already
  anticipates this: `RerankCandidate.id` is documented as "chunk_id or summary_id").
- **Seam:** *internal* seams for (V2) HyDE / graph-expansion. **External interface is stable across V1–V3**
  (V1–V3 only add fields to `GroundedResult`/`PaperSearchResult` or new methods, per Extensibility below).
- **Test:** seed stores (incl. `FakeReranker`) with fixtures → assert `retrieve()` returns expected
  grounded passages and `retrieve_papers()` returns expected unanchored paper results; the ~200-question
  **Spike-2 eval set** runs against `retrieve()` (Recall@10 / MRR).

### M8 · McpServer  *(owner E)* — protocol edge (acceptably thin)
- **Interface (MCP tools):** `search_papers` · `semantic_search` · `get_paper` · `get_span` — all return
  **cited** results. `search_papers` calls `Retriever.retrieve_papers()` and returns the typed
  `PaperSearchResponse` envelope (`results` + `Coverage`); `semantic_search` calls `Retriever.retrieve()`
  and returns the typed `SearchResponse` envelope (`results` + `Coverage`) — both in DATA-CONTRACTS §M8;
  `get_paper` returns `PaperSummaryView`; the `filters?` param on the search tools is `SearchFilters`,
  §M6 — never a raw dict. **Routing (T-DOC34):** summary-level routing (§6 "coarse routing," ADR-11) is
  surfaced only as tool-description guidance on `search_papers`/`semantic_search` (`rag/mcp_server.py`
  docstrings) telling the calling agent to call `search_papers` first for paper-scoped queries — there is
  no server-side auto-narrowing and no paper-id field on `SearchFilters`, consistent with the
  agent-as-reasoner decision (CONTEXT.md, PRD.md §11A).
- **Hides:** composes `Retriever` + `DocumentStore`, formats citations. (Thin by nature — it's the
  protocol adapter; it calls `Retriever`'s two methods and wraps their output, it does not reimplement
  any part of the embed/hybrid/RRF/rerank pipeline itself — that stays inside M7.)
- **Seam:** tools are **additive** — V1 adds `describe_capabilities`/`corpus_stats` + the evidence-tier
  envelope; V2 adds `synthesize`/`get_citations`/SymPy tool. No existing tool changes.
- **Test:** drive each tool against a seeded system; assert citation resolves via `get_span`.

### M9 · IngestionOrchestrator  *(owner A)*
- **Interface:** `ingest(focus_area, cap)` — runs harvest→parse→{chunk, summarize}→embed→**compute
  relevance_score**→store.
  - *Invariants:* **idempotent, resumable, checkpointed per stage**; writes source-of-truth *before*
    the derived index (ordering invariant, §6A); **single-GPU compute serialization** via `GpuLock`
    (Operational invariants §3 below, DATA-CONTRACTS.md) so two GPU-bound calls never execute at the
    same instant — **only Embedder and the reranker are expected to co-reside** in VRAM for the life of
    the process; the Summarizer is proactively evicted (real, verified mechanism, not just a lock) both
    before Pass 1 and before each paper's embed step within Pass 2 — §3 below has the full mechanism and
    why.
  - *Two-pass structure:* the Orchestrator runs `parse_phase()` (every paper to `chunked`, Pass 1) then
    `finish_phase()` (every paper from wherever it sits to `done`, Pass 2) — **not** per-paper CPU/GPU
    pipelining across stages, which would require MinerU and the Summarizer to co-reside (§3 has the
    real CUDA OOM this reproduced). Within each pass, CPU-bound and GPU-bound work still overlap
    normally paper-to-paper; the two-pass split is what keeps MinerU and the Summarizer apart.
  - *`relevance_score` (DATA-CONTRACTS §M5):* after Summarizer produces `summary_text` and before
    `DocumentStore.put`, the Orchestrator computes `cosine(embedder.embed([summary_text])[0],
    topic_query_vec)` using the **same injected `Embedder`** (no new dependency) and sets it on the
    `PaperRecord` it constructs. **`topic_query_vec` is computed exactly once per run** — at the start of
    `ingest()`, before the per-paper loop begins: `topic_query_vec = embedder.embed([" ".join(
    cfg.focus_area_queries)])[0]` — and passed into the per-paper scoring step, never recomputed per
    paper. The query string is identical for every paper in a run; embedding it inside the per-paper loop
    (an easy mistake — it reads naturally as "compute both vectors, then score") means calling `embed()`
    on a constant value `corpus_cap` times (30,000 at V0's cap), each acquiring `GpuLock` for no reason.
    The Orchestrator owns computing it; `PaperRef.relevance_score` itself stays `None` (it can't be
    computed before a summary exists).
- **Hides (depth):** staging, checkpoints, resume, dedup, GPU queueing, relevance-score computation.
- **Seam:** composes the stage modules. **V1 adds a `ClaimExtractor` stage** — the orchestrator gains a
  stage; no other module changes.
- **Test:** run end-to-end with all fakes; assert idempotency (re-run = no dupes) and resume-after-crash.

---

## Operational invariants (the three things juniors get wrong — specify, don't assume)

These back the invariants asserted above. They are **not optional** and each has a concrete mechanism.
Full patterns + code-shape in `CONVENTIONS.md`; schemas in `DATA-CONTRACTS.md`.

1. **Idempotency & resume = an `ingest_state` table, not cleverness.** One row per `paper_id` with a
   per-stage status (`harvested/parsed/chunked/summarized/embedded/stored/done`). Every stage **checks the
   row before doing work and upserts after** — so a re-run skips completed work and a crash resumes mid-corpus.
   All writes are **upserts keyed by stable id** (never blind `INSERT`), so re-running never duplicates.
   `failed` is **not** part of this vocabulary — a bad paper never sits at `ingest_state.stage="failed"`; it
   moves to `quarantine` instead (invariant 2 below), whose row removal is what "this paper is bad" durably
   means. (An earlier version of this doc listed `+ failed` here; that wording was stale — the schema,
   `rag/orchestrator.py`'s `_STAGES`, and every `state` fake/adapter have always agreed on the six values
   above, T-A2 checkpoint-durability fix.)
   **`stored` vs. `done`, pinned exactly (closes the one gap the six-stage list leaves open):** `stored` is
   set immediately after `DocumentStore.put()` succeeds (source-of-truth written). `VectorIndex.upsert()`
   runs **after** that — it is not part of the `put()` call — and only once it succeeds does the Orchestrator
   set `done`. So a paper found at `stored` on resume has **not** necessarily reached the vector index yet;
   resume must re-run `upsert()` for it (idempotent — keyed by `chunk_id`/`summary_id`, safe to repeat) before
   advancing it to `done`. This is what "source-of-truth before derived index" (above) means operationally,
   and it's why `upsert` failing never orphans a paper: it just stays at `stored`, retried on the next run.
2. **One bad paper must not kill the run = a dead-letter table.** A parse/permanent failure moves the paper
   to `quarantine(paper_id, stage, error, ts)` and the pipeline **continues**. Quarantine is visible and
   re-runnable; it is *never* a silent `except: pass`. Transient errors retry with backoff; contract
   violations crash early (they are bugs, not data problems).
3. **Single GPU, four real consumers, measured VRAM (corrected — this section previously asserted
   an unmeasured, flat budget that turned out wrong).** A real end-to-end ingestion run reproduced a
   genuine CUDA OOM. Measured footprints on this project's 24GB card: MinerU (parser) is **not** a flat
   footprint — its pipeline backend loads layout-detection, OCR, table-recognition, and
   formula-recognition sub-models sequentially per paper (`rag/parser.py`'s `_run_mineru_pipeline`) and
   **peaks around ~13GB routinely, observed as high as ~23.7GB/24GB (96.4% of the card) during real
   production Pass 1 runs**; Embedder (TEI Qwen3-Embedding-4B) **~8.2GB**, Reranker (TEI
   BGE-reranker-v2-m3) **~1.4GB**, Summarizer (Ollama qwen3:14b) **~11.8GB** — higher than the original
   ~7-8GB estimate. With Embedder+Reranker resident (**~9.4GB**) — as they were for every measurement
   quoted above, all taken before the Pass-1 eviction exception described below existed — Pass 1's real
   safety margin against MinerU's typical peak was thin — **roughly ~1GB**, not the "fits comfortably"
   this section previously claimed — and the worst observed spike left almost none. The combination
   that still doesn't fit at all is **MinerU + Summarizer at the same time** (with Embedder+Reranker
   also resident, ~28GB+). **Embedder+Reranker are resident during Pass 2 (summarize+embed+store) and
   during live serving, where they serve `McpServer` queries continuously — but are evicted for the
   entire duration of Pass 1** (mechanism below); MinerU and the Summarizer remain the two that must
   never be loaded together.
   - **TEI (Embedder+Reranker) eviction during Pass 1 — a scoped exception, not a reversal of
     always-resident.** Frees the ~9.4GB above as MinerU headroom for exactly the phase that needs it.
     New module `app/tei_lifecycle.py` (`stop_tei_containers()`/`start_tei_containers()`, best-effort
     `docker stop`/`docker start` over the two TEI containers) is wired to the same phase-boundary hook
     mechanism the Summarizer eviction below already uses — `before_parse_phase` (composed alongside
     `summarizer.unload`) stops both TEI containers before Pass 1's MinerU loads, and `before_finish_phase`
     starts them again, polling their health endpoint until ready, before Pass 2's first summarize/embed
     call. **This is safe only because the user has explicitly confirmed that ingestion and live querying
     never overlap in practice for this deployment** — it is not a general claim that Embedder+Reranker
     co-residency is unnecessary, and it must be reconsidered or reverted if concurrent live serving ever
     becomes a real requirement. **The downtime window this creates is materially bigger than the
     Summarizer's eviction below**: the Summarizer's unload/reload is brief (~2.5s) because Ollama exposes
     a `keep_alive`/reload primitive; TEI has no equivalent per-call unload API, so the only lever is
     stopping/starting its Docker containers — Embedder+Reranker are unavailable for the **entire Pass 1
     duration**, potentially hours on a full corpus run, not a brief pause. Any live MCP query attempted
     during Pass 1 would fail outright for the whole phase, not be briefly delayed.
   - **Open risk, not yet decided: Pass 1's ~1GB margin is thin enough that it needs a human call on
     footprint reduction or a guard** (WORK-BREAKDOWN.md's T-DOC series has the tracking note; this doc
     only flags it, it doesn't prescribe the fix).
   - **Fix: two-pass ingestion, not per-paper pipelining.** `IngestionOrchestrator.ingest()` (M9) runs
     `parse_phase()` (every paper to `chunked`, MinerU) then `finish_phase()` (every paper from wherever
     it sits to `done`, Summarizer+Embedder) — not the per-paper CPU/GPU pipelining this section
     previously described. That pipelining was correctness-neutral but memory-unsafe: it required
     MinerU and the Summarizer to co-reside during the overlap window. The two-pass split reuses the
     existing `ingest_state` stage/checkpoint machinery to resume — nothing new was invented for
     persistence, only the entry point changed (`rag/orchestrator.py`'s module docstring has the detail).
   - **MinerU eviction is a subprocess, not an in-process unload.** Tried first, measured insufficient:
     clearing MinerU's process-lifetime model caches (`ModelSingleton`/`AtomModelSingleton`) plus
     `torch.cuda.empty_cache()` only released 57% of what one parse call had allocated — some
     PaddlePaddle-backed OCR/table sub-models don't free through PyTorch's cache-clearing, and this
     residue would accumulate paper after paper across a long run. `app/parse_phase.py` runs Pass 1 as
     its own subprocess; its exit is what actually guarantees full VRAM release, regardless of what
     MinerU's internal caches do. `app/ingest.py` runs that subprocess, then runs `finish_phase()` in
     its own process once it exits.
   - **Summarizer eviction is a real, verified mechanism — fired at two points, not one.**
     `OllamaSummarizer.unload()` sends Ollama's documented no-generation `keep_alive: 0` request, then
     **polls Ollama's `/api/ps` (currently-loaded-models) endpoint every 0.25s, up to a 6s timeout,
     until this model no longer appears there**, before returning. `IngestionOrchestrator`'s
     constructor takes optional `before_parse_phase`/`before_finish_phase`/**`before_embed`** hooks
     (no-op by default); the composition root wires `before_parse_phase = summarizer.unload` (evicts
     any resident Summarizer before Pass 1's MinerU loads) **and `before_embed = summarizer.unload`**
     (evicts it again immediately before *each paper's* embed call within Pass 2 — see below for why).
     Best-effort end to end: if the poll times out or the server is unreachable, `unload()` logs a
     warning and returns anyway rather than blocking the caller's phase transition.
   - **Why the poll, not just the `keep_alive: 0` response: a real scheduled-but-not-complete race.**
     Ollama's `keep_alive: 0` request only *schedules* the unload on its own internal model scheduler —
     the HTTP response can return before the model's VRAM is actually released. A live `nvidia-smi`
     trace caught the Summarizer and Embedder GPU-resident **simultaneously in 5 of 36 samples**
     despite the eviction hook firing every time, i.e. trusting the POST response alone was
     silently unreliable. Polling `/api/ps` until the model is confirmed gone (rather than assuming
     eviction from the request alone) closes that race (PR #63/#64).
   - **Why `before_embed` exists as a second hook, not just `before_parse_phase`.** Found necessary
     2026-07-13: within Pass 2, nothing evicted the Summarizer between a paper's own summarize and
     embed steps — it stayed fully GPU-resident (real measured ~11.5GB for a long paper) for the whole
     time the Embedder was working, though nothing needed it loaded then. On a real long paper this
     left too little headroom and the Embedder hit a real CUDA OOM (batch size and individual chunk
     length were ruled out first via direct measurement). `before_embed` fires before each of
     `_finish`'s two `embedder.embed()` calls; real reload cost for the next paper's summarize call is
     ~2.5s — negligible against a ~15-20s real summarize call.
   - **Runtime residency — Pass 1's margin is thin, not comfortable; Pass 2's real numbers are also
     tighter than first measured, and the fix now has real-scale evidence behind it.** Pass 1 (parse)
     was originally estimated from two real end-to-end test runs (`rag/test_composition_e2e.py`) at
     MinerU 6.6 + Embedder 8.2 + Reranker 1.4 = 16.2GB with no OOM — but that used MinerU's flat
     ~6.6GB figure. MinerU's real production peak (see §3 above) runs much higher, ~13GB typical and up
     to ~23.7GB observed, so Pass 1's real safety margin against the always-resident Embedder+Reranker
     is thin (**~1GB**), not the comfortable one the original 16.2GB figure implied. Pass 2 (finish) was
     originally estimated at
     Summarizer 11.8 + Embedder 8.2 + Reranker 1.4 = 21.4GB from small isolated test calls — but a
     **real full-length paper** measured higher on both: Summarizer ~13.5GB (longer context → bigger
     KV cache than a short test prompt) and Embedder ~9-10GB during its actual batch call (many real
     chunks, not 1-2 test strings), which first reproduced a real `CUDA_ERROR_OUT_OF_MEMORY` in the TEI
     embed container. The `before_embed` fix above (plus the `/api/ps` poll closing the eviction race)
     targets exactly that gap, and a real **250-paper end-to-end ingest run**
     (`.phase0-data/100-paper-run-stats.md`) has since completed with **zero OOM-caused quarantines** —
     all 43 quarantines were unrelated arXiv 404s on PDF download (freshest-first metadata-vs-PDF-
     availability lag), concentrated in the first ~120 papers, with zero recurrence after. This is real
     evidence the fix resolves the practical risk at real-ingest scale — it is **not** a formal
     guarantee against every pathological case: a single earlier worst-case paper was observed hitting
     a CUDA OOM inside the TEI embed container even with total tracked usage well under the card's
     capacity (candidate cause: CUDA allocator fragmentation inside that process, not a total-VRAM-
     budget overrun), and that specific hypothesis was never independently re-tested after the 250-paper
     run. See `.phase0-data/known-issue-pass2-oom.md` for the full trail.
   - **`GpuLock` — cross-process compute serializer only, unchanged by this fix.** `IngestionOrchestrator`
     (M9) and `McpServer` (M8) are the system's two composition roots and V0 explicitly allows them to
     run concurrently as separate processes (a multi-day ingest next to an always-on query server) — the
     typed, injected **`GpuLock`** (DATA-CONTRACTS.md "GpuLock" section) serializes *inference calls*
     across that process boundary so two GPU-bound calls never execute at the same instant, backed by a
     cross-process file lock keyed off `Config.gpu_lock_path`. It does not manage residency or eviction —
     that's the job of the phase-boundary hooks above, a separate concern. In V0, a query simply queues
     behind an in-flight ingest call: no priority, no timeout — accepted V0 simplification, unchanged.
     `McpServer` never references either eviction hook and is unaffected by an ingest run.
   - **If external GPU pressure means eviction still isn't enough** (something other than this system is
     also on the GPU): no scheduler, no retry loop for V0 — a failure surfaces loud (`PermanentError`
     from a parse OOM quarantines that paper; `TransientError` from a summarize OOM retries/stops the
     run) and a re-run resumes from checkpoints. `# ponytail:` marks this ceiling at the phase-boundary
     call sites — a poll-and-backoff `_ensure_vram` upgrade is a real option if this ever proves to be a
     real problem, not built now.
   - "Backpressure" = a bounded queue so CPU stages (harvest, parse, DB writes) don't run arbitrarily far
     ahead of the GPU. Never write a GPU-bound adapter that skips acquiring `GpuLock` "because this call is
     quick" — the lock is what keeps two GPU-bound calls from executing at the same instant.

**Dependency-direction rule (prevents the leak juniors always cause).** Vendor SDKs live **only** inside their
adapter: `qdrant_client` is imported **only** by the `VectorStore` adapter (M6); the embedding client only by
the `Embedder` adapter (M4); MinerU/Marker/Docling only by `Parser` adapters (M2); the cross-encoder client
only by the `Reranker` adapter (used by M7); the local generation-LLM client only by the `Summarizer` adapter
(M3B). Modules depend on the **interface**, never the vendor. `Retriever` must never `import qdrant` or the
cross-encoder client directly. This is what keeps the swap seams real.

## Extensibility: how V1–V3 slot in behind existing seams

Every future feature is a **new adapter, new module, or new stage** behind a stable interface — no V0 rewrite.

| Future feature | Slots in as… | V0 modules touched |
|---|---|---|
| V1 contextual-header generation | header-LLM call fills the existing `Chunk.contextual_header` field, using V0's monitoring signal to decide priority (ADR-07) | Chunker (M3) internal only — field already exists |
| V1 claim extraction | new `ClaimExtractor` **stage** (M9) + `ClaimStore` schema (M5) + claim retrieval (M7) + tools (M8) | none rewritten |
| V1 credibility metadata (OpenAlex) | new `Enricher` stage + `MetadataStore` schema (M5) | none |
| V1 Obsidian view | new `Projector` module reading M5 | none |
| V2 citation graph / GraphRAG | new `CitationGraph` module + graph-expand *inside* M7 | M7 internal only |
| V2 synthesis + evidence tiers | extend `GroundedResult` type + M8 envelope | additive |
| V2 SymPy derivation-check | new M8 tool | none |
| V2 dual embeddings (SPECTER2) | second `Embedder` **adapter** (M4) | none |
| V3 new sources (RSS/OpenAlex) | new `Source` **adapters** (M1) | none |
| V3 VLM figure understanding | enricher filling `ParsedDoc.figures[].vlm_description` (M2 output) | none |
| V3 radar / whats_new | new scheduled orchestrator + M8 tool | none |
| Vector DB swap (Qdrant↔LanceDB) | new `VectorStore` **adapter** (M6) | none — callers unaffected |
| Embedding-model swap | new `Embedder` adapter + orchestrator-level re-embed+reupsert pass (not yet built) | none |

## Test strategy (summary — full doc: TEST-STRATEGY.md)

- **Fakes at every real seam:** deterministic fake `Embedder` (hash→vector), in-memory fake
  `VectorStore` (brute-force + BM25), fake `Source`, fake `Summarizer` (deterministic truncation), fake
  `Reranker` (deterministic **non-identity** reorder + call recording — an identity fake would leave the
  rerank stage untested, TEST-STRATEGY.md), fake `GpuLock` (no-op, call recording). These let M3/M3B/M7/M9
  be tested with **zero GPU / zero network**.
- **Golden fixtures** for `Parser`: a small PDF set with hand-checked `ParsedDoc` — the one place
  correctness can't be faked.
- **Contract tests at swap seams:** the same assertion suite runs against the fake *and* the real
  adapter (fake `VectorStore` vs Qdrant; fake vs real `Embedder`), so swaps are safe.
- **Retrieval eval set** (Spike 2, ~200 causal-domain questions) runs against `Retriever.retrieve()` as the
  headline quality gate (Recall@10, MRR) and the regression gate for any future model/DB swap.

## Ownership & parallelization

| Owner | Modules | Can build against |
|---|---|---|
| A | Harvester, Orchestrator | fakes for all stages |
| B | Parser | golden fixtures |
| C | Chunker, Summarizer, Embedder | fake LLM/embedder |
| D | DocumentStore, VectorIndex | temp SQLite / fake VectorStore |
| E | Retriever, McpServer | seeded stores + fake embedder + fake reranker |
| F | **Shared foundation** (owned first, day 1): `DATA-CONTRACTS.md` types, `Config`, `ingest_state` + `quarantine` schema, the fakes, CI/test harness | — everyone depends on this |

Each module has exactly **one** owner (no co-ownership notation like "B/C") — a module with two owners
is precisely the coordination hazard the seam-based split exists to eliminate in a weak-communication
team.

**Owner F builds the shared foundation before the parallel tracks fan out.** The data types, `Config`,
the state/quarantine schema, and the fakes are the contract every other owner codes against; if they drift,
integration breaks. Freeze them first (a few days), then A–E proceed in parallel. Because every module accepts
its dependencies and is tested through a fake at each seam, **all five tracks then run in parallel** and
integrate at the interfaces. The other hard prerequisite is **Phase 0 (Spikes 1 & 2)** — they pick the
`Parser` and `Embedder`/`VectorStore` adapters the modules will wrap (see `PHASE0-RUNBOOK.md`).

**Companion handoff docs:** `DATA-CONTRACTS.md` (authoritative types/schemas), `CONVENTIONS.md`
(engineering guardrails), `TEST-STRATEGY.md` (fakes/golden/contract tests), `PHASE0-RUNBOOK.md`
(env + Spikes 1&2), `WORK-BREAKDOWN.md` (tickets, sequence, acceptance criteria).
