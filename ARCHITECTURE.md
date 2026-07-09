# ARCHITECTURE — V0 Deep-Module Design

**Scope:** V0 (the plain grounded RAG cache). Designed so V1–V3 slot in behind existing seams
without rewriting V0. Vocabulary follows `codebase-design` (module / interface / seam / adapter /
depth). Companion docs: [PRD.md](PRD.md), [CONTEXT.md](CONTEXT.md).

## Design principles (non-negotiable)

1. **Deep modules.** Small interface, lots of behaviour behind it. Callers/tests learn little, get a lot.
2. **Source-of-truth vs. derived.** `DocumentStore` (SQLite + blobs) is authoritative; `VectorIndex`
   is derived and **rebuildable** from it (ADR-04). This split is the backbone of replaceability.
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

### M2 · Parser  *(owner B)*
- **Interface:** `parse(raw: PdfBytes | LatexSource) -> ParsedDoc`
  `ParsedDoc` — authoritative shape in `DATA-CONTRACTS.md` §M2; do not re-derive its fields here.
  - *Invariants:* **every block carries a provenance anchor (bbox+page)**; equations preserved as LaTeX;
    reading order correct. (Anchor is block-level, not char-offset — validated, §6A.)
  - *Errors:* parse failure → typed error → paper **quarantined**, pipeline continues.
- **Hides (depth):** MinerU / Marker / Docling body parse + GROBID references + PDF-vs-LaTeX routing.
- **Seam:** `Parser` adapter — **REAL** (Spike 1 picks MinerU/Marker/Docling; may change).
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
- **V0 does NOT build contextual-header generation.** That is an LLM call *per chunk* (15,000-papers ×
  one call) and is explicitly **moved to V1** (PRD ADR-07) rather than gated by a Spike-2 toggle — it's
  a separate cost/benefit decision, not a rounding error on V0's scope. V0's only obligation is to
  **monitor**: the Spike-2 retrieval eval tags failures that look context-related (a chunk whose
  meaning depends on missing surrounding text), producing a real number for V1 to start from instead
  of a guess. **Do not implement the header-LLM pass in V0; do not add an `on|off` switch for it.**
- **Seam:** none needed for this in V0 (no LLM dependency injected here yet). V1 adds an internal seam
  for the header-LLM when it builds the feature — see extensibility table below.
- **Test:** `ParsedDoc` fixture → assert boundaries, parent links, anchors intact, prefix present,
  `contextual_header is None` for every chunk.

### M3B · Summarizer  *(owner C)*
- **Interface:** `summarize(ParsedDoc) -> str` (returns `summary_text`; `summary_id` is always the
  deterministic `f"{paper_id}:summary"`, per DATA-CONTRACTS §IDs — never invented by this module).
  - *Invariants:* non-empty output; **GPU-bound** — the local generation LLM (ADR-08, served per
    ADR-09) is subject to the single-GPU lock exactly like Embedder and the reranker (operational
    invariant §3 below) and never co-resides with them.
  - *Errors:* a `ParsedDoc` with no usable prose (e.g. figures-only after a bad parse) → `PermanentError`
    → quarantine, not a crash.
- **Hides (depth):** the summarization prompt, the model choice/serving stack, GPU-lock acquisition.
- **Seam:** *hypothetical* (one local model, no plugin registry — principle 4) — but its LLM client is
  still an **injected dependency** (principle 3, same as every module), so a deterministic
  `FakeSummarizer` powers zero-GPU downstream tests exactly as `FakeEmbedder` does.
- **Note — this module was missing from earlier drafts of this doc** even though `PaperRecord`
  (DATA-CONTRACTS §M5) already required `summary_text`/`summary_id` as non-nullable fields. Summaries
  are in V0 scope (CONTEXT.md's V0 definition names them explicitly) — do not defer this to V1 by
  analogy with contextual headers; it's a different decision.
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
  - `retrieve(query:str, filters: SearchFilters?, k) -> [GroundedResult]` — **passage-level.** Internally
    restricts the underlying `hybrid_search` to `kind="chunk"` regardless of what the caller passed for
    `filters.kind` (categories/date filters from the caller are preserved; `kind` is fixed by which
    method you called, not a caller choice — this is what keeps "which granularity am I searching"
    unambiguous without a runtime error path). Never returns a summary/whole-paper match — a summary has
    no block to anchor to, so it cannot satisfy `GroundedResult` (see DATA-CONTRACTS §M7).
  - `retrieve_papers(query:str, filters: SearchFilters?, k) -> [PaperSearchResult]` — **whole-paper/
    summary-level**, **additive** to `retrieve()` (does not change its signature). Internally restricts
    `hybrid_search` to `kind="summary"`. Closes the summary-retrieval gap: forcing summary results
    through the anchored `GroundedResult` envelope has no valid anchor to offer (DATA-CONTRACTS §M7).
    Placed on `Retriever`, not composed ad hoc inside `McpServer`, because the retrieval algorithm
    (embed-query → hybrid → RRF → rerank) is this module's secret — building it a second time in M8
    would leak that secret into the "acceptably thin" protocol edge (module-design "hide the secret").

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
  grounded passages and `retrieve_papers()` returns expected unanchored paper results; the ~50-question
  **Spike-2 eval set** runs against `retrieve()` (Recall@10 / MRR).

### M8 · McpServer  *(owner E)* — protocol edge (acceptably thin)
- **Interface (MCP tools):** `search_papers` · `semantic_search` · `get_paper` · `get_span` — all return
  **cited** results. `search_papers` calls `Retriever.retrieve_papers()` and returns the typed
  `PaperSearchResponse` envelope (`results` + `Coverage`); `semantic_search` calls `Retriever.retrieve()`
  and returns the typed `SearchResponse` envelope (`results` + `Coverage`) — both in DATA-CONTRACTS §M8;
  `get_paper` returns `PaperSummaryView`; the `filters?` param on the search tools is `SearchFilters`,
  §M6 — never a raw dict.
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
    the derived index (ordering invariant, §6A); **single-GPU backpressure** so stages don't thrash VRAM
    (Embedder, Summarizer, and the reranker never co-reside — Operational invariants §3 below, `GpuLock`
    per DATA-CONTRACTS.md).
  - *`relevance_score` (DATA-CONTRACTS §M5):* after Summarizer produces `summary_text` and before
    `DocumentStore.put`, the Orchestrator computes `cosine(embedder.embed([summary_text])[0],
    topic_query_vec)` using the **same injected `Embedder`** (no new dependency) and sets it on the
    `PaperRecord` it constructs. **`topic_query_vec` is computed exactly once per run** — at the start of
    `ingest()`, before the per-paper loop begins: `topic_query_vec = embedder.embed([" ".join(
    cfg.focus_area_queries)])[0]` — and passed into the per-paper scoring step, never recomputed per
    paper. The query string is identical for every paper in a run; embedding it inside the per-paper loop
    (an easy mistake — it reads naturally as "compute both vectors, then score") means calling `embed()`
    on a constant value `corpus_cap` times (15,000 at V0's cap), each acquiring `GpuLock` for no reason.
    This was previously named only in `PaperRef`/the SQL schema with no module actually assigned to
    compute it — the Orchestrator is the owner now; `PaperRef.relevance_score` itself stays `None` (it
    can't be computed before a summary exists).
- **Hides (depth):** staging, checkpoints, resume, dedup, GPU queueing, relevance-score computation.
- **Seam:** composes the stage modules. **V1 adds a `ClaimExtractor` stage** — the orchestrator gains a
  stage; no other module changes.
- **Test:** run end-to-end with all fakes; assert idempotency (re-run = no dupes) and resume-after-crash.

---

## Operational invariants (the three things juniors get wrong — specify, don't assume)

These back the invariants asserted above. They are **not optional** and each has a concrete mechanism.
Full patterns + code-shape in `CONVENTIONS.md`; schemas in `DATA-CONTRACTS.md`.

1. **Idempotency & resume = an `ingest_state` table, not cleverness.** One row per `paper_id` with a
   per-stage status (`harvested/parsed/chunked/summarized/embedded/stored/done` + `failed`). Every stage **checks the
   row before doing work and upserts after** — so a re-run skips completed work and a crash resumes mid-corpus.
   All writes are **upserts keyed by stable id** (never blind `INSERT`), so re-running never duplicates.
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
3. **Single GPU = one GPU-bound stage at a time (a hard serialization rule).** The embedder, reranker, and
   any summarizer **cannot co-reside** at working precision on 24 GB. This is **not** just an
   in-process rule: `IngestionOrchestrator` (M9) and `McpServer` (M8) are the system's two composition
   roots and V0 explicitly allows them to run concurrently as separate processes (a multi-day ingest next
   to an always-on query server) — so the serialization has to hold *across* processes, not just within
   one. The mechanism is a typed, injected **`GpuLock`** (DATA-CONTRACTS.md "GpuLock" section): the real
   `Embedder`/`Summarizer`/`Reranker` adapters each take a `GpuLock` in their constructor and acquire it
   themselves around their own inference call, backed by a cross-process file lock keyed off
   `Config.gpu_lock_path` — so both composition roots contend for the same lock by construction, not by an
   agent remembering to wrap every call site. "Backpressure" = a bounded queue so CPU stages (harvest,
   parse, DB writes) don't run arbitrarily far ahead of the GPU. Never assume two models fit, and never
   write a GPU-bound adapter that skips acquiring the lock "because this call is quick."

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
| Embedding-model swap | new `Embedder` adapter + `VectorIndex.rebuild()` | none |

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
- **Retrieval eval set** (Spike 2, ~50 causal-domain questions) runs against `Retriever.retrieve()` as the
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
