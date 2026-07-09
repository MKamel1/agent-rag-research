# PRD — AI Research Knowledge System ("Living Research Brain")

**Date:** 2026-07-04
**Status:** Draft v0.1 (for review)
**Owner:** Omar / Mohamed (mkamel1)
**Source:** Derived from `research-kb-system-scope.md` + scoping decisions (2026-07-04)

---

## 1. Vision

A **personal, always-on AI research knowledge system** that runs entirely on the local
workstation, continuously ingests AI/ML research from legal sources, and builds a
**living, claim-centric memory** that both Claude and local models can query cheaply
for grounded, cited answers.

Leave it running overnight or over a week → it accumulates an indexed, summarized,
cross-linked corpus. Any model then queries it instead of re-fetching and re-reading
PDFs — this is the token savings — and, over time, it does more: it answers hard
research questions with synthesis, and proactively surfaces what's new and important.

### The one-line differentiator
Most "chat with your PDFs" systems are a pile of embedded chunks. **This system's memory
is claim-centric and self-reconciling**: findings are extracted as atomic, verifiable
claims, bidirectionally linked to their source artifacts, and continuously reconciled so
new knowledge reshapes the existing knowledge (and vice versa). That is the "living
memory" requirement, and it is the hardest and most valuable part of the system.

---

## 2. Goals & Non-Goals

### Goals
- **G1 — Zero-token knowledge cache.** Models get grounded, cited answers from local
  memory without re-reading PDFs or burning API tokens.
- **G2 — Cited-answer research engine.** Answer hard, synthesis-level questions
  ("what's SOTA on X, and what are the open problems?") with citations to source claims.
- **G3 — Proactive research radar.** Surface what's new/important on a schedule
  ("3 papers this week challenge assumption Y").
- **G4 — Living memory.** New claims are reconciled against existing knowledge:
  duplicates merged, refinements linked, contradictions flagged, superseded results marked.
- **G5 — Verifiability.** Every finding is bidirectionally linked to its artifacts
  (paper, code, dataset, model) so any human or model can verify it.
- **G6 — Legal & local.** Only legal sources; all heavy compute runs on the local GPU
  at zero API cost.

### Non-Goals (v1, explicitly out of scope)
- Not a public/multi-user product. Single-user, single-machine.
- Not a general web crawler or paywall bypass. Legal sources only.
- Not full multimodal in v1 — **no figure/chart image understanding** (deferred).
  Content depth for v1 = **text + equations (LaTeX) + code**, per scoping decision.
- Not a paper-writing tool (that's what the ARS pipeline already does; this feeds it).
- Not real-time — batch/background processing is fine and expected.

---

## 3. Success Metrics (per phase)

| Phase | North star | "It works" means |
|---|---|---|
| v1 — Cache | Token savings | A model answers a factual question about an ingested paper with a correct citation, at ~0 API cost. Retrieval hit-rate on a hand-labeled question set ≥ target. |
| v2 — Engine | Answer quality | A synthesis question ("compare methods A/B/C on benchmark Z") returns a correct, cited, contradiction-aware answer. Claim-reconciliation precision measured on a labeled set. |
| v3 — Radar | Proactive value | A weekly digest correctly identifies the genuinely notable new papers and flags contradictions with prior knowledge, judged useful by you. |

Concrete v1 acceptance measures (to be finalized in Phase 0):
- **Retrieval quality:** Recall@10 and MRR on a ~50-question hand-labeled eval set.
- **Ingestion throughput:** papers/hour end-to-end on the 3090 (target set after spike).
- **Answer groundedness:** % of answers whose citations actually support the claim
  (spot-checked).

---

## 4. Users & Use Cases

**Primary user:** you (Omar), via two surfaces:
1. **Claude / Claude Code** calling the system's **MCP tools** (the agentic path).
2. **Obsidian vault** for hand-browsing, graph view, serendipitous discovery.

**Core use cases:**
- *"What does the memory know about <topic>?"* → semantic + keyword search, cited.
- *"Summarize this specific paper / its method / its results."* → per-paper retrieval.
- *"What's the current SOTA on <benchmark>, and what's contested?"* → synthesis + contradictions (v2).
- *"Show me the citation neighborhood of <paper>."* → citation graph (v2).
- *"What's new and notable this week?"* → digest/radar (v3).
- *"Where did this claim come from?"* → claim → artifact provenance, always.
- * "What claims does this paper make?" → claim extraction, always.
- * "what is the practical way to implement <method>?" → claim + artifact retrieval, always.
- * "what are the gaps in the literature on <topic>?" → claim graph traversal, v2/v3.
---

## 5. System Architecture

Five layers (the four from the scope doc **plus a Knowledge layer** that makes the
memory "living"):

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1. INGESTION (collectors)                                              │
│    arXiv · Semantic Scholar / OpenAlex · Unpaywall · Lab RSS · user    │
│    → raw PDFs + metadata + citation edges, deduped, queued             │
└───────────────┬──────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. PROCESSING (brain-builder, local GPU)                              │
│    PDF → structured markdown (text + LaTeX equations + code + tables)  │
│         + figure/table capture (PNG+caption+bbox, VLM hook)            │
│    → structure-aware chunking (contextual headers: V1, ADR-07)          │
│    → embeddings (local)                                                 │
│    → per-paper structured summary (local LLM)                          │
│    → ATOMIC CLAIM EXTRACTION (local LLM)  ← enables living memory       │
└───────────────┬──────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 3. KNOWLEDGE (living memory)  ← the novel core (see §8 feasibility)    │
│    Aggregate & SURFACE evidence — not arbitrate truth:                  │
│    dup / related / condition-gated contradiction → flag for review.     │
│    Structured compare on shared benchmark = mechanical supersession.    │
│    Belief = COMPUTED view over evidence (append-only, never rewritten). │
│    Bidirectional links: claim ↔ artifact (paper/code/dataset/model).   │
└───────────────┬──────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 4. STORAGE (the substrate)  ← layout/lifecycle/sizing in §6A          │
│    Filesystem = blobs+full text (truth) · SQLite = metadata/chunks/    │
│    summaries/claims/edges (truth) · Qdrant = vectors (derived) ·       │
│    Obsidian = one note/paper (derived view). Truth vs derived split.   │
└───────────────┬──────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 5. ACCESS (query layer)  ← result contract §8.5 · orchestration §8.6  │
│    Self-describing MCP server (instructions + describe_capabilities +   │
│    corpus_stats + resources + workflow prompts + next-step hints).      │
│    Tools: search_papers · semantic_search · get_paper · get_span ·      │
│    get_citations · find_contradictions · synthesize · compare_on_bench  │
│    · whats_new. Returns evidence + epistemic metadata (tier A–D,        │
│    provenance, conditions, confidence, status) — never bare text.       │
│    Pipeline: hybrid (dense+BM25) → RRF → rerank → synthesize (cited)    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 6. Data Model

The claim-centric model is what enables living memory. Core entities:

- **Paper** — canonical record: arXiv id / DOI, title, authors, abstract, dates,
  venue, source, ingest status, file paths. (SQLite)
- **Artifact** — a verifiable object: `paper_pdf`, `code_repo`, `dataset`, `model`,
  **`figure`**, **`table`**. Each has a type, URI/location, and hash. Figures/tables also
  store the extracted **image (PNG), caption, section context, bounding box**, and a
  nullable **`vlm_description`** (filled later when the VLM lands — see §7 "Figure/table
  capture"). (SQLite + filesystem for blobs)
- **Chunk** — a retrieval unit: text + section context + LaTeX/code preserved, plus its
  embedding **and its provenance anchor** — the **quotable snippet + block/line bounding box +
  page index** (validated: char offsets do *not* survive PDF→markdown; block-bbox+snippet is the
  real contract, char offsets best-effort on the arXiv-LaTeX path only — see ADR-06/§6A). This is
  the **deep, full-text** layer — retrieval lands on the actual passage (equations/code intact),
  not a paraphrase. (Qdrant payload references back to Paper + section.)
- **Summary** — the per-paper structured summary written by the local LLM. Stored as a
  first-class object **with its own embedding**, and serves two jobs: (1) **coarse routing** —
  cheap paper-level retrieval ("which papers are even about this?") that feeds the drill-down
  into chunks; (2) it *is* the **token-saving payload** a model reads instead of the PDF (G1).
  (SQLite text + Qdrant vector.)
- **Claim / Finding** — an atomic, extracted assertion. Stored **with its structured
  conditions** — `(method, task/dataset, metric, value, conditions)` — not as a bare
  sentence; a claim stripped of conditions is misleading, so conditions are mandatory (see
  §8.3 R2/R3). Also has: text, type (result/method/definition/hypothesis/limitation),
  confidence, embedding, **a provenance anchor** (quotable snippet + block/line bbox + page →
  the evidencing passage), and **bidirectional links to Artifact(s)** it is evidenced by.
  A claim with no traceable anchor is invalid by construction (grounding — §6A). (SQLite + Qdrant)
- **Claim relation** — edge between two claims: `duplicate`, `refines`, `supports`,
  `contradicts`, `supersedes`. Carries confidence + provenance (who/what asserted it). (SQLite)
- **Citation edge** — Paper→Paper (cites/cited-by) from Semantic Scholar / OpenAlex. (SQLite)
- **Obsidian note** — one markdown file per Paper, wikilinked to related/cited papers
  and to the claims it originates.

**Bidirectional linking (G5):** `claim ↔ artifact` and `claim ↔ claim` are stored as
explicit edges so provenance is queryable in both directions ("what does this paper
claim?" and "what evidence backs this claim?").

**What gets embedded (multi-granularity, one model per ADR-02).** The memory stores
**three vector granularities** so it can be both broad and deep:
- **Summary vectors** → coarse *which-papers* routing.
- **Chunk vectors** → deep *which-passage* retrieval (equations/code intact).
- **Claim vectors** → finding-level retrieval + living-memory reconciliation.

The **raw full text** is kept as durable source-of-truth (SQLite/filesystem) but is **not
itself a vector** — all three vector layers are derived and rebuildable from it (ADR-04).
Retrieval is therefore **hierarchical**: summary-level to find candidate papers → chunk-level
to go deep within them → rerank (see §7 retrieval pipeline / ADR-11).

### 6A. Storage layout, lifecycle, sizing & grounding

**Governing principle: source-of-truth vs. derived.** SQLite + filesystem are authoritative;
Qdrant and Obsidian are **disposable projections** that can be deleted and rebuilt from the
authoritative stores. This one rule is what makes the embedding model replaceable (ADR-04) *and*
keeps everything grounded.

**Where each object lives:**

| Object | Store | Role |
|---|---|---|
| Raw PDF · extracted markdown (full text) · figure/table PNGs | **Filesystem** | source of truth (blobs / text) |
| Paper metadata · Chunk text · Summary text · Claim records (w/ conditions + source span) | **SQLite** | source of truth |
| Claim-relation edges · citation edges · artifact links · ingest state · embedding version stamps | **SQLite** | source of truth |
| Chunk / Summary / Claim **vectors** (+ filter payload → SQLite ids) | **Qdrant** | **derived** (rebuildable) |
| One note per paper, wikilinked | **Obsidian** | **derived projection** (regenerated) |

**The ID spine.** Everything keys off a stable `paper_id` (arXiv id/DOI) → `chunk_id` /
`summary_id` / `claim_id`. Every vector payload and every Obsidian note references a SQLite row,
which references a filesystem span — a provenance chain: `vector → SQLite row → source span in
the paper`. Nothing floats free.

**Write path (per paper), each stage checkpointed → idempotent, resumable, dedup-safe:**
`ingest → parse → chunk → summarize/extract-claims → embed → reconcile → project(Obsidian)`.
**Ordering invariant:** write source-of-truth (SQLite/filesystem) *before* the derived index
(Qdrant/Obsidian) — a crash then never leaves a vector without its authoritative row.

**Updates are append-only.** New knowledge **appends** claims + relation edges; it never
overwrites. A claim's standing (superseded/contested) lives in edges + a *computed* view (§8),
not in mutation. Re-embed (model swap) = rebuild Qdrant from SQLite into a new collection →
atomic cutover (ADR-04). Obsidian regenerates anytime.

**Sizing (order-of-magnitude; validate in Spike 0).** ~4 MB blobs/paper (PDF+figures+markdown)
dominate; vectors ≈ 0.14 MB int8 / 0.57 MB fp32/paper; SQLite ≈ 0.1 MB/paper.

| Corpus | Disk (all kept) | Qdrant RAM (int8) | On this box |
|---|---|---|---|
| 10K | ~50 GB | ~1.5 GB | trivial |
| 100K | ~0.45 TB | ~14 GB | comfortable |
| ~500K | **~2.3 TB (disk ceiling)** | ~70 GB int8 / ~9 GB binary | disk-bound |

- **Disk is the first limit** (raw PDFs+figures) → ~2.3 TB ≈ ~500K papers. Beyond that, **stop
  storing raw PDFs** (keep markdown, re-fetch on demand) to ~halve per-paper cost.
- **RAM (96 GB)** is ample to hundreds of thousands of papers *with* Qdrant quantization +
  on-disk payload (ADR-01). RAM is not the bottleneck; disk is.
- **GPU (24 GB)** is the real constraint: embedder + reranker + generation LLM can't co-reside at
  full precision → stages run **sequentially with queueing** (backpressure). Bounds throughput, not storage.

**Grounding invariants (structural, not hope-based):**
1. **Mandatory provenance** — every chunk/claim/summary stores a provenance anchor (quotable
   snippet + block/line **bbox** + page + `paper_id`/section) → deep-links to the evidencing
   passage at **block granularity**. No anchor → invalid. (Char offsets don't survive PDF→markdown;
   they're best-effort only on the arXiv-LaTeX ingest path, which anchors to `.tex`, not the PDF.)
2. **Derived layers are regenerable** — grounding can't be *lost*; vectors/notes rebuild from authoritative text.
3. **Claims carry conditions + artifact citations** (G5) — no free-floating assertions.
4. **Retrieval & synthesis always cite** ids that resolve to a source span; groundedness spot-checked (§3).
5. **Append-only + audit trail** — every reconciliation edge records who/what/when/confidence.
6. **Belief is computed, not stored** (§8) — no hidden mutated state to drift.
7. **Integrity checks** — artifact hashes detect blob corruption; optional periodic re-grounding
   verifies a claim's cited span still supports it (guards extraction drift after re-embed/model change).

---

## 7. Technical Decisions (resolving your open questions)

These resolve the "Open decisions" section of the scope doc. Each is a **recommendation
with rationale**; the ones still genuinely open are in §11. This table is the *summary*;
the **full reasoning, alternatives considered, and revisit triggers live in §12 (Decision
Records)** — every decision here is reasoned there, not just stated.

| Decision | Recommendation (v1) | Why / upgrade path |
|---|---|---|
| **PDF → structured content** | **MinerU** (or **Marker**) for body → markdown with LaTeX equations, tables, code + reading order; **GROBID** for clean metadata + reference extraction. | Both handle scientific math/code far better than plain `pdfminer`. GROBID's reference parsing seeds the citation graph. Pick one of MinerU/Marker in the Phase-0 spike by quality on your papers. |
| **Chunking** | **V0:** structure-aware (by section), each chunk prefixed with paper title + section path (free). **V1:** add **contextual-retrieval** headers (short local-LLM-generated context per chunk) — gated on V0's monitoring signal, not built in V0 (ADR-07). | Section-aware chunks + the free prefix measurably lift retrieval precision at zero cost. Equations and code kept as first-class blocks, not flattened. The LLM-per-chunk header cost is deliberately a separate, evidence-gated V1 decision. |
| **Embedding model** | **Lean Qwen3-Embedding-4B for quality** (dense-only, top of MTEB, strong on code, 32K ctx, flexible dims); **BGE-M3** as the convenience baseline (emits dense **+** sparse **+** multi-vector → hybrid for free). **Decide in Spike 2 on eval numbers.** | Qwen3-4B has the higher quality ceiling and is stronger on our code-heavy corpus, but is dense-only → pair with a separate sparse method (Qdrant BM25/SPLADE) for hybrid. BGE-M3 trades some quality for one-model hybrid convenience + built-in RRF. Both fit on 24 GB. Caveat: neither *understands* equations — they tokenize LaTeX; deep math semantics is a later concern. |
| **Vector DB** | **Qdrant** (Docker, persistent). | Chosen over **Chroma** for: native **sparse+dense hybrid**, stronger **metadata filtering at scale**, and **quantization** in an always-on container. Chroma is fine for a prototype but thinner on hybrid/filtering for a long-lived, filter-heavy KB. LanceDB is the zero-ops embedded fallback (and is multimodal-friendly if we ever colocate figure blobs). (Your doc's "Quadrand" = Qdrant.) |
| **Figure/table capture** | **Extract + store figures/tables as artifacts during the initial parse** (PNG + caption + section + bbox + `vlm_description=null`); index captions in v1. | Re-parsing the backlog later is the expensive, lossy path; MinerU/Marker already emit figures during the parse we're paying for anyway. This turns the future VLM from a full re-ingestion into a bolt-on ("run VLM over stored figures"), and captions add retrieval value **immediately**, pre-VLM. |
| **Math / equation handling** | **v1:** keep inline LaTeX, normalize macros, index the explaining prose. **v2:** local LLM emits a plain-English description of each key equation → embed it alongside the LaTeX (rides the claim-extraction pass). **Later/optional:** LaTeX→MathML/SymPy for structural equation search, and/or rendered-equation-as-image via the VLM phase. | Embedders tokenize LaTeX, they don't *understand* it — so retrieval by *meaning* comes from the prose + the LLM-generated description, reusing infra we already run. No dedicated math model needed for the common case; structural/VLM options held in reserve. |
| **Graph RAG** | **Yes — graph-aware retrieval over the citation + claim graphs (v2). No generic entity-graph engine.** | The living-memory design already yields two *meaningful, verifiable* graphs (paper→paper citations; claim→claim supports/contradicts/supersedes). Retrieval seeds via hybrid vector search, then traverses those edges for lineage/contradiction context. Microsoft-style GraphRAG (LLM-extracted entity graph + community summaries) is skipped: costly, hallucination-prone, and its global-sensemaking payoff overlaps the v3 radar. Revisit community summaries only if v3 needs cross-field theme detection. |
| **Relational store** | **SQLite** (WAL mode) for metadata, claims, claim relations, citation edges, artifact links. | Handles this scale easily; recursive CTEs cover citation-graph queries. DuckDB if analytics get heavy. |
| **Summarization / claim-extraction LLM** | **Qwen3-14B** (4-bit) as workhorse; **Qwen2.5/Qwen3-32B** (4-bit, ~20 GB) for synthesis. | Strong on math + code + structured extraction, fits the 3090. Use the small model for high-volume extraction, the 32B for v2 synthesis. |
| **Reranker** | **BGE-reranker-v2-m3** (or Qwen3-Reranker) cross-encoder over top-k. | Large quality win for little cost; pairs with BGE-M3. |
| **Embedding *serving*** | **TEI (Text Embeddings Inference) — or vLLM** — with native HF weights for the bulk embedding job; **not** GGUF/Ollama. | Embedding the backlog is a throughput job; benchmarks put **TEI fastest** (Ollama ~9× slower); *validated: TEI ≥ Infinity, so don't default to Infinity, and vLLM now serves embeddings first-class*. Ollama is the slowest and degrades at batch ≥16 → keep it for interactive only. Just run the embedder at **fp16/Q8 (skip GGUF quantization — a 4B embedder barely costs VRAM)**; the old "never Q4" was prudence, not a proven cliff. |
| **Serving stack (LLM)** | **Ollama** for v1 (summarization/claim LLM); **vLLM** later. | Ollama = simplest for the single-GPU generation workload where its convenience wins and throughput matters less. Move to vLLM when overnight throughput becomes the bottleneck. |
| **Embedding-model replaceability** | **Design for swap now:** text is source of truth; vectors are a disposable, **version-stamped** (`model+dim+version`) derived index in per-model Qdrant collections; embedding hidden behind one `embed()` interface; re-embed is a first-class idempotent/resumable job. | A model swap **invalidates the whole vector index** (no cross-model comparability, often different dims) → a full re-embed is unavoidable and is the system's most expensive migration. These cheap measures make it a config-change + background re-index + atomic cutover, not a rewrite. Qwen3's **MRL** dims also allow query-time truncation without re-embedding. |
| **RAG?** | **Yes.** | Grounding + citations + token savings are the whole point. |
| **Retrieval pipeline** | query → (optional) **summary-level routing** to candidate papers → **hybrid** (dense + BM25/sparse) chunk retrieval → **RRF** fusion → **rerank** → (v2) LLM synthesis with inline citations. | Hierarchical: coarse summary vectors find relevant papers, deep chunk vectors go into the text. This is the RRF/indexing/retrieval sequence your doc asked about, made concrete. |
| **Knowledge representation** | **Claim-centric** (see §6) on top of chunks. | The only way to deliver "living memory" (G4) + verifiability (G5). |

---

## 8. Living Memory Design — Feasibility & Grounded Design

> **Reality check.** Stated as "the system reconciles claims and maintains a belief state,"
> this reads as a dream. It isn't one thing — it's a stack of sub-problems ranging from
> trivial to research-grade. This section separates them honestly and grounds the ambition in
> what is actually buildable.

### 8.1 What's feasible vs. what's a dream

| Sub-capability | Verdict | Note |
|---|---|---|
| Claim ↔ artifact bidirectional links | **Grounded / trivial** | A join table. This is the verifiability win (G5), essentially free. |
| Claim extraction (with conditions) | **Feasible, noisy** | ~70–85% precision; quality bounds everything downstream. A claim without its **conditions** is misleading — conditions are mandatory (§8.3). |
| Claim embedding + nearest-neighbor | **Grounded** | Standard; it's a *candidate generator*, not a decision. |
| Duplicate detection | **Feasible** | Embedding + light LLM check. |
| Contradiction/related **flagging** | **Feasible with guardrails** | Surfaces candidates; naive version is mostly false positives (§8.2). |
| support / refine / contradict **classification** | **Partially feasible, unreliable** | Scientific-claim NLI needs domain + condition awareness LLMs do unreliably. |
| **supersede** + auto belief-state rewriting | **Research-grade / not reliably automatable today** | The "dream" part. Never auto-fires without a precision gate + human/model confirmation. |

### 8.2 Why the hard parts are hard (the three traps)
1. **Most "contradictions" are condition mismatches, not disagreements.** "X beats Y" and
   "Y beats X" are usually *both true* on different datasets/scales/hardware. A condition-blind
   judge floods you with false contradictions — the single biggest failure mode.
2. **Supersession is a value judgment.** "B supersedes A" means same task, more rigorous, more
   recent, better — something human reviewers disagree on. Automating it encodes taste.
3. **A self-mutating belief state corrupts silently.** Rewriting beliefs from an ~80%-precise
   judge compounds errors invisibly and destroys trust in the whole KB.

### 8.3 The grounding reframes (dream → engineering)
- **R1 — Aggregate & surface, don't arbitrate truth.** The system organizes evidence and
  *shows* agreements/tensions/lineage to the human or Claude, who judges. "Belief state" is a
  **computed view over evidence, recomputed on read — never a mutated store.**
- **R2 — Claims carry structured conditions or they aren't stored.** Extract as
  `(method, task/dataset, metric, value, conditions)`, not a bare sentence. Directly kills the
  false-contradiction trap by only ever comparing like-with-like.
- **R3 — Reduce fuzzy reasoning to structured comparison on shared axes (the key unlock).**
  Anchor claims to a shared benchmark/dataset/task and compare the **numbers**, not the prose.
  "Accuracy on ImageNet" becomes a **leaderboard-style view** where supersession/contradiction
  are *mechanical* (94% > 92%, same conditions, newer → supersedes; different conditions →
  not a contradiction, just a different setting). The LLM's job shrinks to *extraction*; the
  comparison becomes *deterministic*. This is what makes "living" real instead of magical.
- **R4 — Append-only + the *consuming agent* is the reasoner (no human loop, no auto-mutation).**
  Reconciliation only *adds* tier-labeled, source-attached, low-confidence signals — never deletes,
  never rewrites belief. **Decision (owner, validated by research):** we do **not** build a
  human-approval queue (impractical) and we do **not** let the system autonomously arbitrate truth.
  Instead the memory stays *dumb-but-grounded* and the **querying LLM reasons over the surfaced
  evidence at read time** (§8.5). The intelligence lives in the agent, not the store. This is the
  honest response to the ~70%-precision ceiling: nothing downstream ever *trusts* reconciliation —
  it's a labeled hint the agent may use and must verify against the attached source.

### 8.4 Staging (mapped to the reframes)
- **V0 (ship first — no claims at all):** plain grounded RAG. Agent reasons directly over retrieved
  **source passages + summaries + citations** (tier A/B) — zero extraction noise, most grounded input.
- **V1 (grounded enrichment):** structured claim extraction *with conditions* (R2) + claim↔artifact
  links + duplicate detection. Claims are a **queryable convenience, always tier-labeled +
  source-attached**; the agent verifies. **No automated truth judgments.**
- **V2 (nice-to-have, low priority):** structured benchmark comparison / leaderboard views (R3) and
  **optional** contradiction *surfacing* (owner: "at best nice-to-have — won't use much"). Presented
  as tier-D signals for the agent to weigh, never as system verdicts.
- **V3+ (experimental):** broader cross-paper inference — always surfaced + labeled, never trusted.

> ⚠️ **Non-negotiable guardrails:** never delete; append-only + source-attached; the reconciled
> "belief" view is *computed at read time*, not stored; **the system never auto-mutates belief and
> never blocks on a human.** Reconciliation output is always a tier-D, source-linked hint — the
> consuming agent (esp. Claude) does the reasoning and can re-verify against the evidence.
> *Research reality (cited in session): autonomous contradiction flagging tops out ~70% precision and
> tuple-value extraction ~70 F1 (worst on novel methods); every autonomous reconciling KB failed or
> retreated to curation — so we deliberately keep reconciliation as an untrusted, agent-consumed hint.*

### 8.5 Exposing this to the LLM — the query-layer contract

> **Precedence note:** this section predates DATA-CONTRACTS.md and states the *design intent* across
> all phases (V0–V2). Where it names a concrete field/shape and DATA-CONTRACTS.md disagrees,
> **DATA-CONTRACTS.md is authoritative — fix this section to match, never the other way** (same rule
> DATA-CONTRACTS.md already states for ARCHITECTURE.md, §DATA-CONTRACTS.md L4-5). Concretely for V0:
> the envelope shipped is `GroundedResult`/`PaperSearchResult` + `SearchResponse`/`PaperSearchResponse`
> (`Coverage` included) — DATA-CONTRACTS §M7/§M8 — not the flat field list below, which is the V1/V2
> target shape this section was originally scoped against.

All the upstream grounding (source spans, conditions, confidence, contradiction/supersession
status) is wasted if the query layer hands the LLM a flat wall of text — it will then treat a
system-*inferred* supersession like a verbatim quote, or report a superseded result as current
SOTA. **The access layer therefore never returns bare text; it returns evidence + epistemic
metadata, in a contract shaped so the LLM can't miss the caveats.** (Decision: ADR-16.)

**Evidence tiers (the "grounded vs. inferred" axis, made explicit).** Every returned item is tagged:

| Tier | What it is | LLM must treat it as |
|---|---|---|
| **A — Quoted source span** | Verbatim paper text (via snippet + block bbox) | Highest trust; quotable ("the paper states…"). |
| **B — Extracted claim** | Structured claim + conditions, linked to its span | Grounded but LLM-extracted → verifiable; report *with* conditions. |
| **C — Paper summary** | LLM paraphrase | Gist, **not** verbatim; don't quote as the paper's words. |
| **D — System inference** | Reconciliation / synthesis / contradiction / supersession | **System judgment, not any paper's statement** — label "inferred", never assert as fact. |

**Response envelope (uniform across all tools).** Each item is a record, not a string. **V0 ships**
`GroundedResult` (passage_text, anchor, paper_id, score, citation, evidence_tier pinned `"A"`, empty
`metadata`) and `PaperSearchResult` (a wrapped `PaperSummaryView` + score) — DATA-CONTRACTS §M7/§M8 are
authoritative. The **V1/V2 target shape** this section describes conceptually —
`conditions:{dataset, metric, value, setup}`, `confidence`, `support_count`,
`status:current|superseded_by(id)|contested`, `as_of` — lands as **filled fields on the same
`metadata`/`evidence_tier` envelope**, not a new type (that's the whole point of shipping the envelope
in V0 already, ARCHITECTURE §M7 "Forward-compat"). The LLM cannot render "X is SOTA" without seeing
`status: superseded_by(…)` and `conditions` next to it — **once V1/V2 populate them**; V0 has neither.

**Tools surface, don't collapse (mirrors §8.3-R1).**
- **`find_contradictions`** returns both sides + their conditions as a **tier-D flagged candidate**;
  it does not assert disagreement. Condition mismatches come back as "different settings," not contradictions.
- **`synthesize`** must **structurally separate** "what sources say" (A/B, cited) from "what the
  system infers across them" (D) — no blending stated facts with cross-paper inference.

**Anti-*miss* mechanisms (missing findings ≠ misreading them).**
- **`compare_on_benchmark`** (structured/faceted) returns *all* claims on a dataset/metric — the
  §8.3-R3 leaderboard view — so a relevant result that didn't embed near the query still surfaces.
  Pure semantic top-k silently drops these.
- **Coverage signal** in every response ("top K of N candidates, filtered by …") so the LLM knows
  when it's seeing a sample, not the whole picture.

**LLM-facing guardrails.**
- **Mandatory citations** — answers cite `source_span_id`s that resolve to the paper; interpretation
  rules live in the MCP tool *descriptions* (the model reads them).
- **Absence is first-class** — "no grounded claim found for X" is a real response, so the LLM reports
  the gap instead of hallucinating.
- **`get_span`** — fetch the exact evidencing text on demand so any claim is checkable against source.

**Staging (V0–V3 naming, CONTEXT.md).** **V0** ships the envelope + tier `"A"` pinned (mandatory
citations, `Coverage`, absence-as-first-class, `get_span`) — all built now, not deferred; see the
precedence note at the top of this section. **V1** activates tiers B–C for real (claims, summaries
distinguished as claim-derived vs. paraphrase) + `conditions`/provenance depth. **V2** adds tier D
(`synthesize` / `find_contradictions` / `compare_on_benchmark`) once reconciliation lands.

### 8.6 Making the system legible & orchestratable to the LLM

§8.5 makes each *result* interpretable; this makes the *whole system* usable. A well-labeled bag
of tools is still under-leveraged if the consuming model doesn't know what exists, what the memory
contains, or how to compose calls — the common failure is one `semantic_search` then stop. So the
MCP server is **self-describing and orchestratable**, using all four MCP primitives, not just tools.
(Decision: ADR-17.)

- **Server `instructions`** — an operating manual injected into context: what the system is, the
  evidence-tier legend (§8.5), the tool map, orchestration recipes, and disciplines (always cite,
  respect `status`, check coverage before claiming completeness).
- **Discovery tool `describe_capabilities`** — returns the capability map (tool catalog + when to
  use each + recommended workflows) so the model forms an accurate mental model on first contact.
- **Corpus self-knowledge `corpus_stats` / `whats_covered`** — counts, categories, date range,
  freshness. Tells the model **what the memory does and doesn't hold**, so it defers / flags gaps /
  triggers ingestion instead of overclaiming. A memory that can't describe its own boundaries gets misused.
- **Resources** (MCP readable refs) — **benchmark registry** (real dataset/metric names for faceted
  `compare_on_benchmark`), **claim-type + evidence-tier taxonomy**, **schema**. The model pulls these
  to form correct queries instead of guessing field values.
- **Prompts** (MCP workflow templates) — packaged multi-step recipes: *SOTA question*
  (`compare_on_benchmark → get_span → synthesize`), *gap analysis*, *verify a claim*, *lit-review*.
  This is what lets a **weaker local model** drive the full system — orchestration handed to it, not reinvented.
- **Next-step hints in responses** — results carry affordances (`contradictions_available: 3`,
  `has_citation_neighborhood: true`) that pull the model deeper (→ `find_contradictions`,
  `get_citations`) instead of stopping early. Turns passive tools into an orchestration trail.
- **Tiered scaffolding by consumer** — Claude needs the concise manual; small local models lean on
  the workflow prompts + stronger hints. Same tools, richer scaffolding for the weaker consumer.

**Staging.** v1: server `instructions` + `describe_capabilities` + `corpus_stats` + self-describing
tools + next-step hints. v2: workflow **prompts** + **resources** (benchmark registry, taxonomy) as
reconciliation/graph land. v3: `whats_new` and digest workflows join the same manual.

---

## 9. Phased Roadmap

### Phase 0 — Foundation & De-risking (must clear the unknowns first)

Phase 0 exists because several load-bearing claims in this PRD are **asserted, not proven**. Each
spike answers **one at-risk assumption** with a **measurable gate**, and unblocks a specific
decision/ADR. Several also produce **reusable labeled eval sets** that become permanent regression
gates. A spike that cannot fail isn't a spike.

**S0 — Bring-up (prerequisite).** Fix the `nvidia-smi` NVML driver/library mismatch (reboot/reload);
verify torch sees the 3090. Stand up Ollama + Qdrant (Docker) + TEI/Infinity. Assemble a ~30–50
paper **representative set** (math-heavy, code-heavy, tables, multi-column). *Exit: pipeline runs
end-to-end on one paper.*

| Spike | Assumption at risk | Method | Gate (pass/fail) | Unblocks |
|---|---|---|---|---|
| **1 — Parse + provenance fidelity** | Parser recovers eqns/code/tables **and** the snippet+block-bbox anchors back to the source (grounding, §6A). *Validated: char offsets don't survive PDF→markdown → contract is block-bbox+snippet.* | Run MinerU (math/layout) + Marker (throughput) on the set; rubric-score extraction; test **snippet→block-bbox round-trip** (highlight the evidencing block); trial the arXiv-LaTeX ingest path | Pick MinerU/Marker (+ Docling if tables load-bearing); **block-anchor round-trip ≥ ~95%**; GROBID refs sane | ADR-06; §8.5 grounding |
| **2 — Retrieval quality** | Qwen3-4B ≥ BGE-M3 on our corpus; hybrid+RRF+rerank > dense | ~50-question labeled set (known-relevant chunks); sweep embedders × {dense, hybrid, hybrid+rerank}; serve via TEI/Infinity | Lock embedder+reranker+config; **Recall@10 ≥ ~0.85**; hybrid must earn its complexity | ADR-02/-03/-10/-11 |
| **3 — Claim extraction + reconciliation** *(long pole, make-or-break)* | Claims extractable *with conditions*; condition-gated judge separates dup/contradict/supersede reliably | (a) hand-label gold claims+conditions on ~20 papers → extraction P/R + condition capture; (b) labeled **claim-pair** set → judge precision per relation, esp. **false-contradiction rate** on condition-mismatch pairs | **Sets the precision bar that gates any auto-supersession** (e.g. ≥0.95 same-benchmark); likely outcome **v1 = flag-only** | §8 feasibility; ADR-12; the auto-mutation guardrail |
| **4 — Throughput + sizing** | Sequential-GPU staging gives acceptable papers/hour; §6A sizing holds | Full pipeline on ~100 papers; measure per-stage GPU mem+time, papers/hour, MB/paper, Qdrant RAM under quantization | Real papers/hour → realistic backfill plan; validate/correct §6A estimates | §11 ingestion-breadth decision |
| **5 — LLM-consumption behavior** | Result contract + orchestration scaffolding actually change model behavior | Scenario suite (cite grounded / label inferred / report gaps / use `compare_on_benchmark` / catch supersession); Claude + local model, with vs without contract+hints | Scaffolding measurably improves citation, tier-respect, false-completeness, tool-composition | ADR-16/-17; whether prompts/hints earn their cost |

**Dependency order:** S0 → **Spike 1** (parsing feeds all) → **Spikes 2 & 3 in parallel** (both need
parsed text) → **Spike 4** (needs 1+2+3 wired) → **Spike 5** (needs data from 2, ideally 3). Spike 3
is the long pole and highest-risk.

**Phase 0 exit criteria.** Env fixed + plumbing up + end-to-end on ~100 papers; parser/embedder/
reranker **locked with numbers**; offset-grounding proven or fallback chosen; **reconciliation
precision measured → automation bar set → v1 flag-only confirmed**; throughput+sizing baselined →
ingestion breadth decided; LLM-consumption behavior validated; **reusable eval sets (retrieval,
reconciliation, consumption) exist as regression gates.**

> **Scope note (revised).** V0 (below) needs only a **lighter Phase 0** — Spike 1 (parse) + Spike 2
> (retrieval). Spike 3 (reconciliation) + Spike 5 (consumption) gate **V1+**, not V0. Labeling the
> eval sets still needs *your* domain judgment (§11 Q6) — the real effort — but V0's set is just the
> ~50-question retrieval set, not the claim-pair set.

### Configuration Levers (explicit, not buried — ADR-18)

Scope-defining knobs live in **one visible config**, so re-targeting is a *setting change + re-run*,
not a rewrite. V0 values:

| Lever | Meaning | V0 value |
|---|---|---|
| `focus_area` | topic definition — arXiv **search queries** (not just categories) that select what to ingest | **Causal methods**: causal ML, causal inference, causal discovery, treatment-effect estimation, causal representation learning, causal LLM/agent setups. Queried across `cs.LG`, `cs.AI`, `stat.ML`, `stat.ME`, `cs.CL`, `econ.EM` |
| `corpus_cap` | max papers to ingest | **15,000** |
| `ordering` | harvest order | **freshest-first** |
| `ingestion_mode` | one-shot seed vs forward-only vs backfill | **one-shot seed** (V0); forward-only later |
| `sources` | where papers come from | **arXiv** (V0) |
| `relevance_filter` | reject off-topic harvest false positives | **off** (V0) — but the score is *precomputed* (below) so flipping to `embedding` later is free |

Change `focus_area` + re-run → a different-domain KB on the same system. (Retrieval knobs — top-k,
hybrid weights, rerank depth, chunk size — are also levers, tuned in Spike 2.)

**Instrumenting the `off` choice (compute-signal-now, act-later).** V0 runs no filter, but *monitors*
whether it's needed so the A→B decision is data-driven: (1) **precompute a relevance score** per paper
— cosine similarity of its summary to a "causal methods" seed vector, stored as metadata, used by
nobody in V0 → flipping `relevance_filter` to `embedding` later is just a threshold, no re-embed;
(2) **harvest-precision spot-check** — periodically hand-label a random ~50 causal/not; (3) **query
attribution** — log which query term pulled each paper (prune noisy queries before adding a filter);
(4) **retrieval precision** — the metric that actually matters: sample real top-k results for junk.
**Trigger:** set the bar after smoke-test data; if retrieval/harvest precision drops below it, flip
`relevance_filter → embedding` (free — the score is already stored).

### Phase V0 — Plain Grounded RAG Cache (ship first, use in weeks → G1)  ⟵ the MVP
*Levers above. Process: **smoke-test the pipeline on ~200 papers first** (fail fast), then run the
full 15K overnight/over a few days — parse time is the one unmeasured variable (Spike 1/4).*
`arXiv → parse (text+eq+code, block-bbox+snippet anchors) → structure-aware chunk (no contextual
headers — V1, ADR-07) → embed (one model) → Qdrant + SQLite → hybrid+RRF+rerank+parent-block
expansion → MCP search/get_paper (cited)`
- **No claims, no reconciliation, no evidence tiers, no self-describing MCP scaffolding, no Obsidian.**
- Store: **Qdrant** (persistent Docker service, ADR-01) + SQLite (metadata, chunk/summary text, provenance anchors).
- Access: MCP `search_papers`, `semantic_search`, `get_paper`, `get_span` — returns grounded passages +
  summaries + **citations**. The **consuming agent reasons** over the passages (no human loop, §8.3-R4).
- **Ship criterion:** an agent answers a factual question about an ingested paper with a correct,
  verifiable citation, at ~0 API cost — and you actually use it.

### Phase 1 — V1: Claim Enrichment + KB (gated behind V0 + Spikes 3/5)
`(V0) + claim extraction → SQLite + Obsidian → richer MCP`
- Knowledge: extract claims *with conditions* + artifact links; **tier-labeled + source-attached**
  (agent verifies); duplicate detection. **No auto truth judgments, no human queue.**
- Store: + one Obsidian note/paper (wikilinked) — the human-browsable view.
- Access: + evidence-tier envelope (§8.5), `describe_capabilities`/`corpus_stats` (§8.6).
- **Only build the claim schema after Spike 3 clears its bar** — else V1 stays passage-level (V0+Obsidian).

### Phase 2 — V2: Cited-Answer Engine + optional reconciliation (→ G2)
- Citation graph from Semantic Scholar / OpenAlex; Unpaywall OA fallback.
- Synthesis with inline citations (tier-separated, §8.5).
- **Optional / nice-to-have (low priority):** benchmark-comparison + contradiction *surfacing* as
  tier-D agent hints — never system verdicts (owner: "won't use much").
- MCP tools: `get_citations`, `synthesize`, (optional) `compare_on_benchmark`/`find_contradictions`.

### Phase 3 — v3: Proactive Research Radar (→ G3)
- Lab RSS feeds + user-provided sources for breadth/coverage of non-arXiv items.
- Scheduled ingestion + **weekly digest**: novelty/trend detection, "what changed vs prior belief."
- MCP tool: `whats_new`; optional push/notification.

---

## 10. Cross-Cutting Concerns
- **Scheduling:** background jobs (systemd timers / cron) for ingest + processing; idempotent, resumable, dedup-safe.
- **Idempotency & resume:** every stage checkpointed; re-runs never duplicate papers/claims.
- **Observability:** counts per stage, failures queue, throughput dashboard (even a simple log/table).
- **Backpressure:** single-GPU queueing so embedding + summarization + judge don't thrash VRAM.
- **Data safety:** append-only *knowledge edges*; audit trail; nightly SQLite + vector-store snapshot to the 2.3 TB free space.
- **Document updates (arXiv versioning — deferred post-V3):** papers can be revised (v2 supersedes v1), but revisions are rare enough to ignore for now. The only guard we keep (free): **dedup by arXiv id at harvest** so we never hold v1 *and* v2. A full CRUD/update path (delete old chunks, re-embed) is **possible post-V3 adoption**, not a V1 requirement. See §11A.
- **Legal hygiene:** source allowlist; respect API rate limits & ToS (arXiv, S2, OpenAlex, Unpaywall).

---

## 11. Open Questions / Decisions Still Needed
1. ~~**Ingestion breadth for v1**~~ **RESOLVED for V0** (see Levers): `focus_area` = causal methods,
   `corpus_cap` = 15,000, freshest-first, one-shot arXiv seed. Full/other-domain backfill deferred
   until Spike 4 gives a papers/hour number. **Relevance filter: RESOLVED → `off` for V0, but
   instrumented** (precomputed relevance score + precision spot-checks) so A→B is a data-driven,
   free flip later (see Levers).
2. **MinerU vs Marker:** decide in Spike 1 (quality on *your* papers).
3. **BGE-M3 vs Qwen3-Embedding-4B:** decide in Spike 2 (eval numbers).
4. **Auto-supersession bar:** what judge precision is high enough to let it rewrite belief state (vs. flag-only forever)?
5. **Obsidian as source-of-truth vs. rendered view:** are notes generated/regenerated from SQLite, or hand-editable? (Recommend: generated view, SQLite is truth.)
6. ~~**Eval set ownership**~~ **RESOLVED for V0:** no human labeler. The retrieval eval set is
   **agent-generated** — a teacher-student pattern: a generation pass samples chunks and writes a
   question each chunk answers (gold label = that chunk's `chunk_id`, so Recall@10/MRR need no human
   labeling), a judge pass filters degenerate questions. ~200 questions, up from the original ~50 now
   that generation is cheap. Full mechanism: TEST-STRATEGY.md "Retrieval eval set"; procedure:
   PHASE0-RUNBOOK.md Spike 2. This is a **build-time QA** choice, distinct from CONTEXT.md's *runtime*
   "no human in the loop" principle (agent-as-reasoner, no approval queue) — not a contradiction, a
   separate decision made the same way. The **reconciliation set** (V1+, claim contradiction/duplicate
   labeling) stays open/deferred — it's gated behind V1 anyway (CONTEXT.md phase defs).

---

## 11A. Smart-RAG Technique Coverage & Deliberate Omissions

Audit of standard "smart RAG" features against this design (to catch unknown-unknowns). Have/planned
vs. deliberately-not, with phase:

- **Hybrid search** (ADR-11) — ✅ V0. **Cross-encoder rerank** (ADR-10) — ✅ V0. **GraphRAG** (ADR-15,
  citation+claim graphs) — ✅ V2. **Query transformation/routing** — ✅ by design, *delegated to the
  agent-as-reasoner* (multiple MCP tools incl. structured SQLite queries); no server-side auto-rewrite.
- **Parent-child / small-to-big retrieval** — ✅ **ADOPTED, `on` in V0.** **Distinct from our
  multi-granularity** (summary→chunk→claim = zoom levels for *routing*): parent-child is a fix
  *inside the chunk layer* for the size dilemma — **search on small child chunks (precise), but return
  the enclosing parent block (context)** to the agent. Nearly free (we already store full text + chunk
  positions). Lever: `child_parent_expansion = on`.
- **arXiv versioning / CDC updates** — ⏸️ **Deferred post-V3 (rare).** Only free guard kept: dedup by
  arXiv id at harvest. Full CRUD/update path is possible-later, not required.
- **Memory consolidation (episodic→semantic)** — ⚠️ Partial. Per-paper summary+claims+dedup = our
  consolidation (V1). A *periodic background re-synthesis* job over the KB = candidate V2. Interaction
  memory = out of scope (single-user).
- **HyDE** — ❌ Not planned; optional V1+ retrieval mode (the agent can already self-generate a
  hypothetical and search — marginal value uncertain with strong embedder+rerank).
- **Time-weighted decay** — ❌ **Deliberately NOT adopted.** Blanket recency-decay *degrades* a research
  KB (foundational old papers must not be penalized). Recency handled via **explicit date filters +
  supersession `status` + the V3 radar**, never a global decay. *Documented so it isn't "fixed" later.*

---

## 11B. External Survey Triage — Parked Ideas & New Constraints

From an advanced-RAG survey of the causal/EconML domain. **Most of the survey targets a billions-scale
commercial product — deliberately not our regime.** Captured here so good ideas aren't lost *and*
scope-creep is contained. Nothing here enters V0.

**Pulled into spikes (cheap wins):** promote **Docling** to a first-class Spike-1 parser candidate
(Apache-2.0, ~2× faster than MinerU); add a **faithfulness≠correctness / retrieval-failure-rate**
dimension to the Spike-2 eval (§3). *(Chroma-hybrid question RESOLVED — verified Chroma OSS has no
native hybrid → V0 reverted to Qdrant, ADR-01.)*

**Parked for later phases (do NOT build in V0):**
- **V1:** credibility metadata via OpenAlex (venue, citation count, **retraction flag**); MinHash/
  **SemDeDup** near-duplicate dedup (beyond exact arXiv-id); SymPy symbolic math layer's priority is
  **higher for this math-heavy domain** than ADR-14's generic framing (still V2).
- **V2:** RAPTOR summary tree + HippoRAG multi-hop (synthesis/reasoning); **semantic caching** +
  **LLMLingua** context compression (token-savers, serve G1); SPECTER2/SciNCL **dual embeddings** for
  paper-similarity routing (Spike-2 may A/B it); **HyDE** as an optional retrieval mode.
- **V2+ / VLM phase:** ColBERT/**ColPali** late-interaction for figure/equation pages.
- **Explicitly skipped (scale-out infra, not our regime):** Milvus/DiskANN/IVF-PQ/**MUVERA**, Ray/Spark
  distributed ingestion, **Mathpix** (commercial — violates local/zero-cost; MinerU-VLM covers math),
  multi-tenancy/governance.

**New constraints/risks logged (were missing):**
- **Security — indirect prompt injection / corpus poisoning** (PoisonedRAG): retrieved paper text could
  carry adversarial instructions that hijack the *consuming agent* (which reasons over that text).
  Low risk for personal arXiv use, but real → treat retrieved text as untrusted; revisit if sources
  broaden beyond arXiv.
- **Licensing:** arXiv full text is **non-exclusive — not redistributable**. **Personal, local,
  non-shared use = fine.** If this is ever shared/hosted, switch to ODC-By corpora (S2ORC/peS2o) or
  link back to arXiv rather than serving full text.

---

## 12. Decision Records (ADRs)

> The §7 table states decisions; this section reasons them. Format per record: **Context →
> Options considered → Decision → Rationale → Risks/limitations → Phase & scaling link →
> Revisit if**. The *Phase & scaling link* ties each decision to what it enables/blocks across
> the v1→v2→v3 roadmap (§9) and how it holds as the corpus grows from thousands to hundreds of
> thousands of papers. New decisions are added here, not just asserted in the table.

> **Weighing rubric — how we evaluate any alternative** (esp. techniques from external research).
> Score on these dimensions, *not* on generic benchmark wins: **(1) Value to our use case** (single-user
> causal-domain KB, not a leaderboard) · **(2) Build effort** · **(3) Operational burden** (services,
> extra models) · **(4) GPU/VRAM cost** (our hard bottleneck) · **(5) Token economics** (helps/hurts G1)
> · **(6) Reversibility** (derived+rebuildable = safe to defer) · **(7) Maturity/risk** (proven vs
> frontier) · **(8) Architectural fit** (agent-as-reasoner, local/zero-cost, source-vs-derived) ·
> **(9) Scale-appropriateness** (do we reach the regime where it pays off?). A technique that only wins
> on dimension 9 (scale) is *dismissed* — it's solving a problem we don't have.

### ADR-01 — Vector database: Qdrant
**Context.** Always-on, single-machine KB ingesting up to tens of thousands of papers →
millions of chunks + claims. Retrieval must be hybrid (dense + lexical → RRF), heavily
metadata-filtered (category, date, source, claim type, "cited-by X"), and survive as a
long-lived persistent service.

**Options considered.**
- **Chroma** — nicest DX, Python-native, embedded. *Update (validated): as of Nov 2025 Chroma has
  a Rust core (~4× faster) and **first-class BM25+SPLADE sparse search** — so "bolt-on hybrid" is no
  longer fair.* Remaining gap is scale/production-grade payload filtering, where teams still migrate off it.
- **LanceDB** — embedded, zero-ops, columnar, disk-based, **multimodal/blob-friendly**
  (could colocate figure images). Great fallback; hybrid is improving but less mature than Qdrant.
- **Qdrant** — server (Docker), production-grade: **native sparse+dense hybrid**, strong
  payload filtering, named/multi-vectors, quantization.

**Decision (re-revised — Chroma OSS lacks native hybrid; VERIFIED).** **V0: Qdrant** (persistent
Docker container) — proven native dense+sparse hybrid + RRF *locally*. **Chroma OSS dropped for V0:**
confirmed (trychroma.com docs) that its unified hybrid/RRF Search API is **Chroma Cloud-only**;
self-hosted OSS requires hand-rolling BM25+fusion at the app layer — and hybrid is core to our
retrieval. **LanceDB** is the embedded, no-server alternative (native FTS+vector hybrid) — evaluate in
Spike 2 *only if* avoiding a Docker service matters; else Qdrant. The **GPU-bottleneck point still
holds** (DB doesn't affect ingest throughput), so this is decided on **hybrid correctness**, not speed.
*(History: original Qdrant → briefly Chroma for embedded simplicity → back to Qdrant once Chroma's
local hybrid gap was verified. The flip is fact-driven, and cheap anyway — vectors are rebuildable, ADR-04.)*

**Rationale.** *(Rejustified per validation: Qdrant wins on **scale + payload filtering + quantization**,
not on hybrid being "bolted on" in Chroma — that gap closed in late 2025.)* (1) Our retrieval is hybrid — Qdrant treats sparse vectors (BM25/SPLADE) as
first-class beside dense, so hybrid + RRF is built in; Chroma needs a bolt-on. (2) We filter
heavily and at scale — Qdrant's payload filtering stays fast as the corpus grows. (3) It runs
as an always-on quantized container, matching "leave it running." Blobs (figure PNGs) live on
the filesystem + SQLite, keeping a clean split rather than pushing Qdrant toward multimodal.

**Risks/limitations.** Requires running a service (Docker) vs. Chroma/LanceDB embedded
simplicity. For a pure prototype, Chroma would be *fine* — this is a soft call driven by the
hybrid + filtering + longevity requirements, not a hard technical necessity.

**Phase & scaling link.** v1 uses dense + payload filtering; **v2's hybrid + claim-graph
retrieval leans on native sparse and multi-vector support — chosen now to avoid a v2 store
migration.** Scaling to hundreds of thousands of papers → millions of vectors: enable
**scalar/binary quantization + on-disk payload** to stay inside 96 GB RAM; Qdrant
collections/sharding give headroom without re-architecting.

**Revisit if.** We decide to colocate figure/image vectors with blobs (→ LanceDB's multimodal
model becomes attractive), or the Docker service becomes an operational burden with no
hybrid/filtering payoff.

### ADR-02 — Embedding model: lean Qwen3-Embedding-4B (BGE-M3 as baseline)
**Context.** Corpus is code- and math-heavy technical text. Retrieval quality is the v1
north-star (token-saving cache). We also need hybrid (a sparse signal alongside dense).

**Options considered.**
| | BGE-M3 (2024, ~568M) | Qwen3-Embedding-4B (2025) | Qwen3-Embedding-8B (GGUF) |
|---|---|---|---|
| Retrieval quality | Good, not top-tier | **Top of MTEB at release** | Marginally > 4B (few pts) |
| Code/technical text | Solid | **Stronger** | Stronger |
| Hybrid | **dense+sparse+multi-vector in one model** | dense-only (pair w/ separate sparse) | dense-only |
| Context / dims | 8K / 1024 | 32K / **MRL flexible** | 32K / MRL |
| Cost / throughput | Light, fast | Heavier | ~2× 4B; slower for bulk |

**Decision.** **Lean Qwen3-Embedding-4B for quality; keep BGE-M3 as the convenience
baseline. Final pick in Spike 2 on our own labeled eval set.** Include 8B (Q8/bf16) as a
Spike-2 candidate.

**Rationale.** Qwen3-4B has the higher quality ceiling and is stronger on code (which we have
a lot of). Its dense-only limitation is cheap to close — Qdrant can generate BM25/SPLADE sparse
vectors independently of the dense model, so we still get hybrid. BGE-M3's one-model
dense+sparse convenience is real but trades away quality. 8B's few-point MTEB gain doesn't
justify ~2× per-chunk compute for a large backlog; VRAM (fits at Q8 ≈ 8.5 GB / bf16 ≈ 16 GB on
24 GB) is *not* the deciding factor — throughput is.

**Risks/limitations.** No general embedder *understands* equations — they tokenize LaTeX (see
ADR-05 / §7 math row). Quality claims are leaderboard-based; our eval set is the real arbiter.
GGUF-8B specifically: prefer **fp16/Q8 and skip GGUF quantization** (a 4B embedder barely costs
VRAM). *Correction: the earlier "never Q4 for embeddings" is prudence, not a benchmarked cliff —
no hard study shows a Q4 embedding-retrieval collapse; the risk/reward just doesn't favor it.*

**Phase & scaling link.** v1 embeds chunks; **v2 reuses the identical model + interface to
embed atomic claims** for the living-memory nearest-neighbor step (ADR-12) — one model serves
both, so no second embedding stack. Scaling: 4B's throughput advantage compounds over a growing
backlog; MRL lets us **drop query-time dimensions** to trade recall for speed/RAM without
re-embedding.

**Revisit if.** Spike-2 eval shows 8B clearly better *and* ingest throughput is acceptable; or
a materially stronger open embedder ships (re-run the eval — see ADR-04 for swap cost).

### ADR-03 — Embedding *serving*: TEI/Infinity, not GGUF/Ollama
**Context.** Embedding the backlog is a bulk throughput job (millions of chunks + claims),
distinct from the interactive LLM generation workload.

**Decision.** Serve the embedding model via a **batching-optimized server (TEI or Infinity)
using native HF weights** for the bulk job. Reserve **Ollama for the summarization/claim LLM**.

**Rationale.** Ollama/llama.cpp is optimized for single-stream generation and batches embedding
requests poorly; TEI/Infinity are several× faster on bulk embedding. GGUF format is oriented at
generation, not high-throughput embedding, so it actively works against the backlog use case.

**Risks/limitations.** One more service to run alongside Ollama + Qdrant. Acceptable given the
throughput payoff on ingest.

**Phase & scaling link.** v1's backlog ingest is throughput-bound → this is where TEI/Infinity
pays off most. As v2 adds claim embeddings and v3 adds continuous ingest, sustained throughput
matters more, not less; this is also the natural point to **converge embedding + generation onto
vLLM** (ADR-09) when we move off Ollama.

**Revisit if.** Corpus is small enough that ingest time is a non-issue, or we consolidate onto
vLLM (which can serve both generation and embeddings with batching).

### ADR-04 — Design the embedding model as replaceable
**Context.** Embedders improve fast; we will likely want to swap models over the system's life.

**Decision.** Treat vectors as a **disposable, version-stamped derived index**, never the
source of truth: (1) chunk/claim **text** is durable in SQLite/filesystem; (2) every vector /
Qdrant collection is stamped `embedding_model + dim + version`, named per model+version;
(3) embedding is hidden behind one `embed()` interface; (4) "re-embed the corpus" is a
first-class idempotent, resumable maintenance job; migration = build new collection alongside →
atomic query-layer cutover.

**Rationale.** A model swap **invalidates the entire vector index** — vectors from model A are
meaningless to model B, dims often differ, and there is no cross-model comparability or
incremental migration. So a full re-embed (hours–days of GPU) is unavoidable; these cheap
measures reduce it to a config change + background rebuild + cutover instead of a rewrite.
Qwen3's **MRL** dims further allow query-time truncation without re-embedding.

**Risks/limitations.** Re-embed remains the single most expensive maintenance operation; RRF
weights / rerank thresholds / similarity cutoffs need re-tuning after a swap; answers may drift
(reproducibility) — hence the version stamping.

**Phase & scaling link.** The versioned-collection + `embed()` abstraction is what makes a
mid-life model upgrade (very likely between v1 and v3) a background re-index rather than a
rewrite. At scale the re-embed cost grows linearly with the corpus, so **the durable text store
(ADR-05) is the asset; vectors are always rebuildable** — this is the invariant that keeps
every future embedding/quantization/dimension change tractable.

**Revisit if.** Never expected to change the model (then some of the abstraction is overhead) —
unlikely given the pace of embedder releases.

### ADR-05 — Relational store: SQLite
**Context.** Need metadata, claims, claim-relation edges, citation edges, and artifact links.

**Decision.** **SQLite (WAL mode)** as the relational backbone + source of truth for text.

**Rationale.** Handles this scale trivially; recursive CTEs cover citation- and claim-graph
traversal without a dedicated graph DB (see §7 "Graph RAG" — the edges are the graph). Zero-ops,
single-file, easy to snapshot to the 2.3 TB disk.

**Risks/limitations.** Not built for heavy analytical aggregation or high write concurrency — if
analytics grow, **DuckDB** alongside is the escape hatch. Single-writer model is fine for the
background-job pipeline with proper queueing.

**Phase & scaling link.** SQLite is the **source-of-truth backbone every phase writes to** —
v1 papers/chunks/artifacts, v2 claim + claim-relation + citation edges, v3 digest state. Because
it holds the durable text, it underpins ADR-04's replaceability. Scaling: citation/claim graphs
in the low-millions of edges stay well within SQLite + CTEs; the DuckDB (analytics) or graph-DB
(deep traversal) escape hatches are additive, not migrations.

**Revisit if.** Graph traversals get multi-hop-heavy enough to justify a real graph DB, or
analytics workloads outgrow SQLite.

### ADR-06 — PDF → structured content: MinerU/Marker + GROBID
**Context.** Content depth for v1 is **text + LaTeX equations + code** (not figure *understanding*
yet). The parser must recover reading order, equations, tables, and code from scientific PDFs, and
we separately need clean structured metadata + references to seed the citation graph.

**Options considered.**
- **pdfminer/PyMuPDF raw text** — fast but flattens math/tables/columns; loses equations and reading order. Rejected.
- **Nougat** (Meta) — *validated obsolete: ~1 min/page, ~1-in-500 pages loops/hallucinates, and fully generative → **zero bboxes** (fatal for grounding). Dropped.*
- **Marker** — fast PDF→markdown, clean LaTeX-fenced output + code blocks; block-level polygons.
- **MinerU** (now VLM v2.5) — best formula recognition + multi-column scientific layout; Markdown **and** structured JSON with block/line/span bboxes.
- **Docling (TableFormer)** — *add if nested tables are load-bearing; beats both on complex tables.*
- **arXiv LaTeX source** — *>90% of arXiv ships `.tex`; near-perfect equations/sections/citations, no OCR — preferred ingest path for arXiv, but grounds to `.tex` spans, a separate coordinate basis from PDF.*
- **GROBID** — best-in-class *metadata + reference* parsing (emits PDF coords); watch multi-page/ACL ref-list failures.

**Decision.** **MinerU (math/layout) *or* Marker (throughput)** for the body (pick in Spike 1) **+
GROBID for metadata/references**; **prefer the arXiv-LaTeX path for arXiv papers**; add Docling if
tables matter. Body parser also **emits figure/table images + captions + bboxes** (ADR-13).
*Grounding contract is block-bbox+snippet, not char offsets (validated — see §6A).*

**Rationale.** Body extraction and reference extraction are different problems; using the tool
that's best at each beats one mediocre pass. GROBID's structured references are what make the
citation graph (v2) cheap and accurate. MinerU vs Marker is a quality call best settled on real
inputs, not benchmarks — hence the spike.

**Risks/limitations.** Parsers err on dense multi-column math and exotic layouts; equation LaTeX
is imperfect. Parsing is CPU/GPU-heavy — a throughput factor for the backlog. Mitigation: parse
is idempotent + resumable + cached, so re-runs are cheap.

**Phase & scaling link.** The parse is the **one-time, most expensive pass over each PDF** — so
it captures figures/tables *now* (ADR-13) even though the VLM lands in v3, avoiding a full
re-parse of the backlog later. GROBID references feed **v2's citation graph**. Scaling: parsing
parallelizes across the 16-core CPU; it's the likely ingest bottleneck, so throughput here sets
the papers/hour ceiling measured in Spike 0.

**Revisit if.** Spike-1 quality is inadequate on math-heavy papers (lean harder on MinerU-VLM /
the arXiv-LaTeX path), or a materially better scientific parser ships.

### ADR-07 — Chunking: structure-aware (V0); contextual headers moved to V1
**Context.** Retrieval quality (v1 north-star) is highly sensitive to chunking. Chunks must keep
equations/code intact and carry enough context to be independently meaningful.

**Options considered.**
- **Fixed-size/token windows** — simple, but split equations/code and lose section context.
- **Structure-aware (by section/heading)** — respects document structure; variable size. Free —
  no extra model pass.
- **+ Contextual Retrieval** (prepend a short LLM-generated context to each chunk) — an LLM call
  **per chunk**, i.e. per-chunk cost × 15,000 papers.

**Decision (revised — cleanly split by phase, not Spike-2-gated).** **V0 ships structure-aware
chunking only**: by section, equations/code as first-class blocks, each chunk **prefixed with
paper title + section path** (free, string concatenation). **Contextual-retrieval headers (the
LLM pass) are explicitly a V1 feature, not a V0 toggle.** V0 does not build the header-generation
path at all; it only **records a monitoring signal** — the rate of "context-poor" chunks in the
Spike-2 eval (chunks whose retrieval failures plausibly trace to missing surrounding context,
tagged during eval labeling) — so V1 starts with data instead of a guess about whether headers are
worth their cost.

**Rationale.** Section-aware chunks + the free title/section prefix already capture most of the
"which ablation is this?" disambiguation win at zero ingest cost. The *remaining* gap — cases the
prefix doesn't cover — is exactly what an LLM-generated context header would close, but that's a
15,000× LLM-call cost that deserves its own gated decision with real evidence, not a Spike-2 A/B
squeezed into V0's timeline. Splitting it out avoids blocking V0 ship on a cost/benefit call that
isn't V0's to make.

**Risks/limitations.** If V0's monitoring signal shows context-poor chunks are common, V1 should
prioritize contextual headers early; if rare, V1 can deprioritize them. Either way the call is
evidence-based, not deferred by default. Variable chunk sizes still need care with embedder
context limits (Qwen3/BGE-M3's long context covers this) — that part *is* V0's concern.

**Phase & scaling link.** Chunk granularity feeds **v2 claim extraction** (claims are distilled
from well-scoped chunks) and the prose that makes **equations retrievable by meaning** (ADR-14).
**V1 handoff:** the `Chunk.contextual_header` field already exists (nullable) in V0's schema
(DATA-CONTRACTS.md) so V1 fills it in-place — no migration. Scaling: if V1 adopts headers, the
per-chunk LLM pass is a real cost at hundreds of thousands of papers — tier it (cheap small model
for headers, reserve 14B/32B for summaries/claims).

**Revisit if.** V0's monitoring signal shows context-poor chunks are rare enough that V1 can skip
headers entirely, or claim-centric retrieval (ADR-12) reduces reliance on raw-chunk quality.

### ADR-08 — Summarization / claim-extraction LLM: Qwen (14B workhorse, 32B synthesis)
**Context.** Local LLM must write per-paper structured summaries (v1), extract atomic claims (v1
capture / v2 reasoning), and judge claim relations (v2) — all on a single 24 GB GPU, at zero API cost.

**Options considered.**
- **Llama-3.3-70B** — strong, but ~40 GB at 4-bit → doesn't fit the 3090 well.
- **Qwen3-14B (4-bit)** — strong on code/math/structured output; fast; fits comfortably.
- **Qwen3-32B (4-bit, ~19 GB weights)** — *validated caveat: it fits, but leaves only ~4–6 GB for KV cache → usable context collapses to ~8–16K if the embedder/reranker are co-resident. Use it **offline only** (models not co-resident), optionally with KV-cache quant.*
- **Small models (Qwen3-4B/8B)** — for high-volume, low-complexity passes (e.g., context headers).

**Decision.** **Tiered Qwen:** 4B/8B for high-volume extraction/context, **14B as the workhorse**
(full context, room to co-reside with embedder+reranker), **32B (4-bit) for *offline* synthesis /
reconciliation-judge passes only** — not co-resident with the retrieval stack.

**Rationale.** Qwen leads open models on code + math + structured extraction and fits 24 GB at
useful quant. Tiering matches model cost to task difficulty, protecting ingest throughput while
keeping a high-quality option for the hard reasoning in v2.

**Risks/limitations.** 4-bit quant costs some reasoning fidelity — acceptable for summaries,
watch it for the judge (validated in the Phase-0 reconciliation spike). 32B is slow on one GPU →
use it selectively, not on every paper.

**Phase & scaling link.** **This is the model behind the "full-ambition" living memory** — v2's
relation judge (ADR-12) is the highest-stakes use, gated by the Phase-0 precision spike before it
may mutate belief state. v3 digests reuse the same tier. Scaling: generation is throughput-bound
on one GPU → this is the primary driver for the **vLLM move (ADR-09)** and, eventually, a second GPU.

**Revisit if.** A better-fitting open model ships, the judge's precision is insufficient at 4-bit
(try higher quant / 32B), or throughput forces model-size cuts.

### ADR-09 — LLM serving stack: Ollama for v1 → vLLM later
**Context.** Serve the generation models (summaries, claims, judge) locally; v1 favors simplicity,
later phases favor throughput.

**Decision.** **Ollama for v1**; **migrate generation (and possibly embeddings) to vLLM** when
overnight throughput becomes the bottleneck.

**Rationale.** Ollama is the least-friction way to pull/run quantized models on one GPU for
batch/background work. vLLM's continuous batching + PagedAttention give far higher throughput but
cost operational complexity we don't need on day one. Defer that cost until data says otherwise.

**Risks/limitations.** Ollama's throughput ceiling is lower; a late migration means re-validating
prompts/outputs on vLLM. Kept low-risk by hiding model calls behind a thin client interface.

**Phase & scaling link.** Directly tied to ADR-03 and ADR-08: as v2/v3 add claim-judging and
continuous ingest, generation load rises → **vLLM becomes the convergence point for both
generation and embedding serving.** Scaling past one GPU (tensor/pipeline parallel, or a second
3090/bigger card) is a vLLM-era concern, not a v1 one.

**Revisit if.** Overnight jobs miss their window on Ollama, or we need to serve generation +
embeddings from one batched stack.

### ADR-10 — Reranker: BGE-reranker-v2-m3 (cross-encoder)
**Context.** First-stage hybrid retrieval optimizes recall; a second-stage reranker optimizes
precision@k, which is what the LLM/user actually consumes.

**Options considered.** No reranker (cheaper, worse precision) · **BGE-reranker-v2-m3** · **Qwen3-Reranker**.

**Decision.** **Cross-encoder reranker (BGE-reranker-v2-m3, or Qwen3-Reranker) over top-k**;
final choice in Spike 2 alongside the embedder.

**Rationale.** Cross-encoders jointly attend to query+passage and reliably deliver a large
precision lift for modest cost on a small candidate set (top 50–100 → top 5–10). Pairs naturally
with BGE-M3; Qwen3-Reranker pairs with Qwen3 embeddings. Cheap, high-leverage.

**Risks/limitations.** Adds latency per query and a model to serve; benefit depends on candidate-set
size (tune k). Negligible for our query volumes.

**Phase & scaling link.** v1 quality gate depends on it; **v2 synthesis quality depends on feeding
the LLM only high-precision context** (bad context → bad cited answers), so the reranker matters
*more* as answers get more synthesis-heavy. Scaling: rerank cost is per-query, not per-corpus, so
it's insensitive to corpus growth — a durable choice.

**Revisit if.** Latency budget tightens, or embedder+hybrid alone hit the precision target in Spike 2.

### ADR-11 — RAG + retrieval pipeline: hybrid → RRF → rerank → synthesize
**Context.** The whole point is grounded, cited answers at ~0 API cost — i.e., RAG. The pipeline
shape determines answer quality and token savings.

**Decision.** **Use RAG**, **hierarchical/multi-granularity** (§6). Pipeline: query →
**(optional) summary-level routing** → **hybrid (dense + BM25/sparse) chunk retrieval** →
**RRF fusion** → **cross-encoder rerank** → **resolve to the matched chunk's full text**
(`Config.child_parent_expansion`, `on` in V0, controls chunk-*build*-time grouping of an equation/table
block with its defining prose block into one `Chunk` — not a query-time fetch; DATA-CONTRACTS
§Provenance & structure and ARCHITECTURE §M7 are authoritative on this, superseding the "return its
enclosing parent block" framing this ADR originally used) → **(v2) LLM synthesis with inline citations**.

**Rationale.** Multi-granularity is the key: **summary vectors give breadth** ("which papers
matter"), **chunk vectors give depth** ("the exact passage/equation/code"), **claim vectors give
findings** — one embedding model over all three (ADR-02). Hybrid catches both semantic and
exact-term matches (crucial for method names, symbols, benchmark IDs that pure-dense misses); RRF
is a robust, tuning-light fuser; rerank fixes precision; synthesis is deferred to v2 so v1 can ship
as pure retrieval. This is the concrete answer to the scope doc's "indexing / retrieval / RRF" question.

**Risks/limitations.** More stages = more to tune (RRF weights, k, thresholds) and more calibrated
to the chosen embedder (couples to ADR-04). Synthesis can hallucinate if context is weak — mitigated
by rerank + mandatory citations back to claims/artifacts.

**Phase & scaling link.** **v1 = retrieval only** (search_papers/semantic_search/get_paper);
**v2 = + synthesis + graph-aware expansion** (ADR-15) over the claim/citation graphs;
**v3 = the radar consumes the same pipeline** for digest generation. Scaling: retrieval stays
sub-second with quantization + filtering (ADR-01); cost scales with queries, not corpus.

**Revisit if.** RRF underperforms a learned fuser, or synthesis groundedness misses the §3 bar.

### ADR-12 — Knowledge representation: claim-centric (atomic findings)
**Context.** "Living memory" (G4) + verifiability (G5) are impossible over an undifferentiated pile
of chunks. We need objects that can be compared, reconciled, and cited.

**Options considered.**
- **Chunks only** — simplest; can't reconcile knowledge or attribute claims. Rejected as the core model.
- **Full ontology/knowledge graph** — maximal structure, but brittle + expensive extraction.
- **Atomic claims layered on chunks** — extract per-paper assertions, each linked to evidencing artifacts.

**Decision.** **Claim-centric model** (§6): atomic Claims **carrying structured conditions**
`(method, task/dataset, metric, value, conditions)` + type + confidence + embedding,
**bidirectionally linked to Artifacts**, and Claim-relation edges (`duplicate/refines/supports/
contradicts/supersedes`) — layered on top of retrieval chunks, not replacing them.

**Rationale.** Claims are the unit that reconciliation operates on, the unit citations point to
(provenance in both directions), and the unit that lets new knowledge reshape old. The
**structured conditions are load-bearing**: they turn fuzzy "does A contradict B?" reasoning into
mechanical, like-with-like comparison on shared benchmarks (§8.3 R3) — which is what makes the
living memory feasible rather than aspirational. This keeps extraction tractable (vs a full
ontology) while enabling the aggregate-and-surface model of §8 (the system organizes evidence; it
does not autonomously arbitrate truth).

**Risks/limitations.** Claim extraction quality bounds everything downstream; bad claims → bad
reconciliation. LLM extraction is imperfect and adds ingest cost. Mitigation: claims always link
back to source artifacts so any claim is verifiable/falsifiable by human or model (G5).

**Phase & scaling link.** **The pivot of the whole roadmap:** v1 *captures + stores* claims and
links (lightweight — dedup + cross-link + flag); **v2 turns on the judge** (ADR-08) for
supersession/confidence — where full ambition lands (§8); v3 trend detection reads the evolving
claim graph. Scaling: claim volume grows faster than paper volume, so claim embeddings dominate the
vector store at scale — reinforcing ADR-01's quantization and ADR-02's throughput choices.

**Revisit if.** Claim extraction can't reach usable precision (fall back to chunk-only retrieval +
manual curation), or a lighter representation delivers the same reconciliation value.

### ADR-13 — Capture figures/tables as artifacts during the initial parse
**Context.** v1 excludes figure *understanding*, but the VLM is planned for v3. Re-parsing the whole
backlog later to recover figures would be the expensive, lossy path.

**Decision.** During the one-time parse, **extract and store figures/tables as first-class
Artifacts** — PNG + caption + section context + bbox + stable `figure_id` + **nullable
`vlm_description`** — and index captions in v1.

**Rationale.** The parser already emits these (ADR-06), so marginal cost now is ~zero; captions add
retrieval value *immediately*; and this converts the future VLM from a re-ingestion project into a
bolt-on ("run VLM over stored figures, fill `vlm_description`"). Figures fit the claim↔artifact model
(a claim "Table 2 shows X" links to the artifact).

**Risks/limitations.** Extra storage (trivial vs 2.3 TB) and schema surface carried before it's used.
Extraction accuracy bounded by the parser.

**Phase & scaling link.** **Deliberate cross-phase forward-compatibility:** cost paid in v1's parse,
value realized in **v3's VLM** with no backlog re-parse. Scaling: figure blobs live on the filesystem
(not Qdrant), keeping the vector store lean (ties to ADR-01's clean split).

**Revisit if.** We commit to *never* adding a VLM (then skip extraction), or storage/parse cost proves
non-trivial at scale.

### ADR-14 — Math/equation handling: prose + LLM-described equations, staged
**Context.** Embedders tokenize LaTeX; they don't understand equations. We still want equations
retrievable by *meaning*.

**Decision.** **v1:** keep inline LaTeX, normalize macros, index explaining prose. **v2:** local LLM
emits a plain-English description of each key equation → **embed it alongside the LaTeX** (rides the
claim-extraction pass); **model equations as first-class typed nodes** (LaTeX + context + gloss +
optional SymPy form), like figure/table artifacts (ADR-13). **v2 — SymPy as an agent-callable
derivation-check tool** (from external survey): expose a CAS tool over MCP so the **consuming agent
verifies math** (equivalence / a derivation step) via SymPy rather than trusting embeddings or token
prediction — fits agent-as-reasoner and is high-value for the causal/EconML math-heavy domain.
**Parked (frontier):** structural formula embeddings (operator trees / MathBERT) — the survey itself
calls math-embedding equivalence *unsolved*; rendered-equation-as-image via the VLM (v3+).

**Rationale.** Most of an equation's queryable meaning lives in surrounding prose + a natural-language
gloss, both from infra we already run — no dedicated math model for the common case. The insight from
the survey + our agent-as-reasoner stance: **don't make the memory understand math; give the agent a
SymPy tool to *check* it.** That turns "unsolved math retrieval" into a tractable verification tool.

**Risks/limitations.** LLM equation descriptions can be wrong/generic; normalization is imperfect.
Deep symbolic/structural search genuinely needs the later MathML/SymPy path.

**Phase & scaling link.** **Reuses the v2 claim-extraction LLM pass** (ADR-08/-12) — the equation
gloss is produced in the same call, so v2 gets math-by-meaning "for free." The structural (MathML/
SymPy) and image (VLM, ADR-13) options attach to **v3+**. Scaling: description-embedding is just more
claim-like vectors — no new subsystem.

**Revisit if.** A real need for exact structural equation search emerges, or a strong math-native
embedder ships.

### ADR-15 — Graph RAG: graph-aware retrieval over citation + claim graphs (no generic entity graph)
**Context.** "Do we want graph RAG?" The living-memory design already yields two real graphs
(paper→paper citations; claim→claim relations).

**Options considered.**
- **No graph** — miss multi-hop lineage/contradiction reasoning.
- **Generic (Microsoft-style) GraphRAG** — LLM-extract an entity graph + community summaries.
- **Graph-aware retrieval over our existing citation + claim edges.**

**Decision.** **Yes to graph RAG as graph-aware retrieval (v2):** hybrid vector search seeds nodes,
then traverse citation/claim edges for lineage + contradiction context. **No generic entity-graph
engine.**

**Rationale.** Our edges are already *meaningful and verifiable* (real citations, judged claim
relations) — extracting a synthetic entity graph would be costly, hallucination-prone, and largely
redundant. Its main payoff (global "themes across the field" sensemaking) overlaps the v3 radar
anyway. So we get graph RAG's value from structure we're building regardless.

**Risks/limitations.** Traversal quality depends on citation completeness (Semantic Scholar/OpenAlex
coverage) and claim-relation precision (ADR-12). Deep multi-hop traversal could pressure SQLite
(ADR-05's graph-DB escape hatch).

**Phase & scaling link.** **Emerges in v2** once the citation + claim graphs are populated; **v3's
radar** may add community-summary-style global queries *only if* cross-field theme detection needs
it. Scaling: traversal is over SQLite edges (CTEs) — fine into low-millions of edges; a graph DB is
the additive escape hatch, not a rewrite.

**Revisit if.** v3 needs corpus-wide thematic sensemaking that edge-traversal can't provide, or
traversal depth outgrows SQLite.

### ADR-16 — Query-layer result contract: evidence tiers + epistemic envelope
**Context.** The consuming model (Claude or local) only sees what the access layer hands it. If
that's flat text, upstream grounding (spans, conditions, confidence, contradiction/supersession) is
invisible → the model over-trusts inferences, over-generalizes past conditions, and reports
superseded results as current. The query layer must make reliability legible.

**Options considered.**
- **Bare text / passages** — simplest; loses all epistemic signal. Rejected.
- **Text + citations only** — grounds *where* but not *how reliable* or *stated-vs-inferred*.
- **Structured envelope with evidence tiers + provenance + conditions + status** — full epistemic contract.

**Decision.** **Every tool returns records, not strings**, each carrying an **evidence tier (A
quoted / B extracted / C summary / D system-inferred)** + provenance (`source_span_id`) +
conditions + confidence + `status(current|superseded|contested)` + `as_of`/`embedding_version`.
Tools **surface, don't collapse** (find_contradictions/synthesize separate A/B from D); add
**`compare_on_benchmark`** (anti-miss faceted view), **coverage signals**, **first-class absence**,
and **`get_span`** for verification. Interpretation rules live in the MCP tool descriptions. (§8.5.)

**Rationale.** The tiers operationalize the user's "grounded truth vs inferred" concern directly:
the model is structurally prevented from blending a verbatim quote (A) with a cross-paper inference
(D). Conditions + status stop over-generalization and stale-SOTA errors; coverage + absence stop
false-completeness and hallucination; mandatory `source_span_id` citations keep answers verifiable.
This is the payoff that makes all upstream grounding *usable*.

**Risks/limitations.** Richer envelope costs tokens per result (mitigate: compact fields, return
spans on demand via `get_span` rather than inline). Models can still ignore metadata → reinforce via
tool-description instructions + a synthesis system prompt that mandates tier/citation discipline.
Tier tagging is only as good as upstream provenance (couples to §6A, ADR-12).

**Phase & scaling link.** **v1** ships the envelope + tiers A–C + provenance + citations + coverage
+ absence + `get_span` (retrieval-only). **v2** adds tier D + `synthesize`/`find_contradictions`/
`compare_on_benchmark` as reconciliation lands (§8.4). **v3** `whats_new` digests reuse the same
contract so proactively-surfaced items carry the same reliability labels. Scaling: contract is
per-result, independent of corpus size.

**Revisit if.** Token overhead of the envelope hurts, or evals show models ignore tiers despite
prompt discipline (→ stronger structural separation, e.g., separate tool calls per tier).

### ADR-17 — MCP server is self-describing & orchestratable (not just a bag of tools)
**Context.** ADR-16 makes each result interpretable, but the consuming model still under-leverages
the system if it doesn't know what exists, what the memory holds, or how to compose calls. The
dominant failure is one `semantic_search` then stop — missing the graph, benchmark, and
contradiction capabilities entirely.

**Options considered.**
- **Tools only, thin descriptions** — relies on the model to infer usage. Under-uses the system.
- **Tools + rich descriptions** — better, but no corpus self-knowledge, no composition guidance.
- **Full self-description via all four MCP primitives** (tools + `instructions` + resources + prompts)
  \+ corpus introspection + next-step hints.

**Decision.** Use **all four MCP primitives**: server **`instructions`** (operating manual),
self-describing **tools** + `describe_capabilities`, **`corpus_stats`/`whats_covered`** boundary
introspection, **resources** (benchmark registry, claim-type/tier taxonomy, schema), and **prompts**
(packaged multi-step workflows). Responses carry **next-step hints**; scaffolding is **tiered** by
consumer strength. (§8.6.)

**Rationale.** Legibility (know what it is + what it holds) + orchestratability (know how to compose)
are what turn a tool bag into a system the model *drives*. Corpus self-knowledge specifically
prevents overclaiming and enables honest deferral/ingestion. Workflow prompts + hints let even a weak
local model exploit the full capability, protecting the "both Claude and local models" goal (G1).

**Risks/limitations.** More surface to build and keep in sync with the tools (stale instructions
mislead). Mitigate: generate `describe_capabilities`/`corpus_stats` from the live schema/DB, not
hand-maintained prose. Token cost of injected instructions — keep the manual concise, push detail
into on-demand resources.

**Phase & scaling link.** **v1** ships `instructions` + `describe_capabilities` + `corpus_stats` +
self-describing tools + hints. **v2** adds workflow **prompts** + **resources** as reconciliation/graph
land. **v3** digest/radar workflows join the manual. Scaling: corpus introspection stays accurate by
being computed from the DB; the manual is O(1) regardless of corpus size.

**Revisit if.** MCP primitives evolve, or evals show the workflow prompts/hints aren't improving
tool-composition behavior (→ rethink scaffolding).

### ADR-18 — Scope parameters are explicit named levers, not buried constants
**Context.** Focus area, corpus size, ordering, sources define the *product's scope*. Hardcoded as
magic numbers they get buried, and re-scoping means code surgery — the system becomes single-purpose.

**Decision.** A single visible **config registry** holds the scope levers (`focus_area`,
`corpus_cap`, `ordering`, `ingestion_mode`, `sources`, plus retrieval knobs). V0 values recorded
(causal methods, 15K, freshest-first, one-shot, arXiv). Owner requirement: these must not be buried.

**Rationale.** Makes the system **re-targetable** (swap `focus_area` → a new-domain KB with no code
change), keeps scope decisions auditable, and separates "what we're building a memory *of*" from
"how the memory works." `focus_area` is a topic *query set*, not a category list (causal work spans
`cs.LG/stat.ML/stat.ME/…`).

**Risks/limitations.** Lever sprawl — restrict the registry to genuinely scope-defining knobs, not
every internal tunable. A too-broad `focus_area` query pulls false positives ("mentions causal" ≠
"causal methods") — may need a light relevance filter.

**Phase & scaling link.** V0 seeds the registry; each phase adds its own levers (forward-only
schedule, source list, reconciliation on/off). Changing `focus_area` + re-running is how the *same*
codebase serves any research domain — the main reuse lever.

**Revisit if.** The config surface grows unwieldy, or levers need per-source overrides.

---

## 13. Appendix — Environment (confirmed)
- **GPU:** RTX 3090 24 GB (driver 580.95.05). ⚠️ NVML driver/library mismatch → reboot/reload before GPU work.
- **CPU:** Ryzen 9950X (16C/32T) · **RAM:** 96 GB · **Disk:** ~2.3 TB free.
- **Python:** 3.13 system; `pytorch-env` = 3.12 + torch 2.6.0+cu124 + transformers 4.57.
- **Ollama:** installed (`/usr/local/bin/ollama`), server not running.
- **Obsidian:** none yet — new dedicated vault.
