# Owner C — Chunker (M3) + Summarizer (M3B) + Embedder (M4)

Read `AGENTS.md` (or `CLAUDE.md`, same content) first if you haven't. This file is self-contained for your role — you shouldn't need to
read any other doc cover-to-cover before starting, only the sections pointed at below.

## Modules you own

- **M3 · Chunker** — `chunk(ParsedDoc) -> [Chunk]`. Pointer: ARCHITECTURE.md §M3.
- **M3B · Summarizer** — `summarize(ParsedDoc) -> str`. Pointer: ARCHITECTURE.md §M3B.
- **M4 · Embedder** — `embed(texts) -> [Vector]`, the replaceability seam. Pointer: ARCHITECTURE.md §M4.

## Your tickets (WORK-BREAKDOWN.md "M1b" section — full acceptance criteria there)

- **T-C1** — Chunker: section-aware, parent-child links, multi-block anchoring rule, title+section prefix.
  **Do NOT implement contextual-header generation** — V1 (ADR-07), not a V0 toggle.
- **T-C2** — Summarizer: real adapter over the local generation LLM, GPU-locked.
- **T-C3** — Embedder: real adapter (TEI/vLLM), GPU-locked, the contract test against the fake.

## Prerequisites

`foundation-v0-frozen` tagged (Owner F) for all three. **T-C1** (Chunker) is otherwise unblocked — build
against fakes. **T-C2** (Summarizer) additionally needs PHASE0-RUNBOOK.md S0's local LLM service up.
**T-C3** (Embedder) additionally needs Spike 2 to lock the embedder choice (ADR-02: Qwen3-Embedding-4B vs
BGE-M3) — you may be the one running that spike's embedding sweep.

## Definition of Done

CONVENTIONS.md §11, applied per-ticket. Note T-C2's non-degeneracy requirement specifically (a bare
non-empty check isn't enough — see TEST-STRATEGY.md "Summarizer" bullet).

## Authoritative references (pointers)

- ARCHITECTURE.md §M3, §M3B, §M4.
- DATA-CONTRACTS.md §M3 (`Chunk`, `contextual_header` stays `None`), §M3B, §M4 (`EmbedderInfo`, `Vector`),
  §Provenance & structure (the multi-block anchoring rule you implement in Chunker, and what it means for
  `passage_text` downstream — read this even though `passage_text` itself is Retriever's/Owner E's field,
  because Chunker is where the grouping decision actually happens via `Config.child_parent_expansion`).
- TEST-STRATEGY.md "Chunker," "Summarizer," "Embedder" bullets + `FakeSummarizer`/`FakeGpuLock` in "Fakes."
- CONVENTIONS.md §10 "Cost landmines" (contextual headers = 15,000 LLM calls, explicitly NOT V0).

## Vendor isolation

Local generation-LLM client → **only** Summarizer's adapter. Embedding client (TEI/vLLM) → **only**
Embedder's adapter. Never import either in Chunker.

## Test-first, branch/PR procedure

GIT-WORKFLOW.md. Branches: `T-C1-tests`→`T-C1-chunker`, `T-C2-tests`→`T-C2-summarizer`,
`T-C3-tests`→`T-C3-embedder`. M1a PRs are part of the global milestone gate.

## Scope fence

`Chunk.contextual_header` stays `None` in V0 — no `Config.contextual_header` toggle exists, don't add
one. V0's only obligation re: contextual headers is monitoring (tag context-poor retrieval failures
during Spike 2), not building the feature.
