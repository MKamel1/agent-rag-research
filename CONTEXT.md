# CONTEXT — Ubiquitous Language

Canonical vocabulary for the AI Research Knowledge System. Glossary only — no implementation
detail. When a term here conflicts with usage elsewhere, this file wins (or gets updated).

## Phases / product stages
- **V0** — the MVP that ships first: a *plain grounded RAG cache*. Ingest → parse → chunk → embed →
  retrieve → return grounded passages + summaries + **citations** over MCP. **No claims, no
  reconciliation, no evidence tiers, no Obsidian.** Success = an agent answers with a verifiable
  citation at ~0 API cost, and it gets used.
- **V1** — claim enrichment layer on top of V0 (extracted claims + Obsidian + evidence-tier envelope).
  **Gated** behind V0 working and the reconciliation/consumption spikes passing.
- **V2** — cited-answer engine: citation graph + synthesis. Contradiction/benchmark comparison is
  **optional, nice-to-have**, surfaced as agent hints only.
- **V3** — proactive radar: scheduled digests, "what's new." *(Note: PRD.md §9 separately defines a
  "V3+ (experimental)" bucket for broader cross-paper inference — a different roadmap item under a
  similar label; a future doc pass should reconcile the naming.)*

## Core domain terms
- **Paper** — a canonical source document (arXiv id / DOI).
- **Artifact** — a verifiable object linked to findings: `paper_pdf`, `code_repo`, `dataset`,
  `model`, `figure`, `table`.
- **Chunk** — a retrieval-sized passage of a Paper's full text (equations/code preserved).
- **Summary** — the per-paper structured summary; also the token-saving payload an agent reads
  instead of the PDF.
- **Claim / Finding** — an atomic assertion extracted from a Paper, stored *with its conditions*
  `(method, task/dataset, metric, value, conditions)`. A claim without conditions is invalid.
  (V1+ only.)
- **Provenance anchor** — what grounds a Chunk/Claim to its source: **quotable snippet + block/line
  bounding box + page**. (Char offsets do *not* survive PDF→markdown; they exist only on the
  arXiv-LaTeX path, anchored to `.tex`.) No anchor → the item is invalid.
- **Reconciliation** — relating a new Claim to existing ones (duplicate / refines / supports /
  contradicts / supersedes). Output is an **untrusted, tier-labeled, source-attached hint**, never a
  system verdict. (V1+/optional.)
- **Living memory** — the aspiration that new knowledge reshapes old. Realized as a **read-time
  computed view over evidence**, consumed and judged by the querying agent — *never* an autonomously
  mutated store.

## Configuration
- **Lever** — a scope-defining parameter held in one visible config, never a buried constant, so
  re-targeting is a setting change + re-run (ADR-18). Registry: `focus_area`, `corpus_cap`,
  `ordering`, `ingestion_mode`, `sources`, `relevance_filter` (+ retrieval knobs).
- **`relevance_filter`** — rejects off-topic harvest false positives. **V0 = off**, but a relevance
  score is *precomputed* per paper so switching to `embedding` later is a free threshold flip.
- **`focus_area`** — the topic definition (a set of arXiv *search queries*, not just categories)
  that selects what to ingest. **V0 = causal methods** (causal ML, causal inference, causal
  discovery, treatment-effect estimation, causal representation learning, causal LLM/agent setups)
  across `cs.LG`, `cs.AI`, `stat.ML`, `stat.ME`, `cs.CL`, `econ.EM`.
- **`corpus_cap`** — max papers to ingest. **V0 = 2,000**, freshest-first, one-shot seed.

## Retrieval terms
- **Multi-granularity** — the three *zoom levels* of a paper used for **routing**: summary (which
  paper) → chunk (which passage) → claim (which finding).
- **Parent-child / small-to-big** — *distinct* from multi-granularity: a fix inside the chunk layer.
  **Search on small child chunks (precise match), return the enclosing parent block (context)** to the
  agent. `on` in V0.

## Access / trust terms
- **Evidence tier** — the grounded-vs-inferred label on every returned item:
  **A** quoted source · **B** extracted claim · **C** summary/paraphrase · **D** system inference.
  A/B are what a Paper says; D is what the *system* inferred and must never be presented as fact.
- **Agent-as-reasoner** — the consuming LLM (esp. Claude) does the reasoning over surfaced evidence.
  **No human-in-the-loop** (rejected as impractical) and **no autonomous truth arbitration** by the
  system. The memory stays *dumb-but-grounded*; intelligence lives in the agent.
- **Source of truth vs. derived** — SQLite + filesystem are authoritative; vectors and Obsidian are
  disposable, rebuildable projections.

## Rejected / non-goals (so they don't creep back)
- **Human approval queue** — rejected; impractical for a solo operator.
- **Autonomous belief rewriting** — rejected; research shows ~70% precision ceiling, every attempt
  failed or retreated to curation. Reconciliation is a hint, not an action.
- **Char-offset grounding** — not achievable through PDF→markdown; block-bbox+snippet is the contract.
