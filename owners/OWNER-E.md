# Owner E — Retriever (M7) + McpServer (M8)

Read `AGENTS.md` (or `CLAUDE.md`, same content) first if you haven't. This file is self-contained for your role — you shouldn't need to
read any other doc cover-to-cover before starting, only the sections pointed at below.

## Modules you own

- **M7 · Retriever** — the crown-jewel deep module; **two** methods, `retrieve()` (passage-level) and
  `retrieve_papers()` (whole-paper/summary-level, additive). Pointer: ARCHITECTURE.md §M7.
- **M8 · McpServer** — the protocol edge (acceptably thin). Pointer: ARCHITECTURE.md §M8.

## Your tickets (WORK-BREAKDOWN.md "M1b" section — full acceptance criteria there)

- **T-E1** — Retriever: both methods, shared pipeline (embed→hybrid→RRF→rerank→resolve), injected
  `Reranker`. Runs the Spike-2 eval set.
- **T-E2** — McpServer: `search_papers`/`semantic_search`/`get_paper`/`get_span`. `search_papers` calls
  `retrieve_papers()`; `semantic_search` calls `retrieve()` — **do not** reimplement any part of the
  embed/hybrid/RRF/rerank pipeline inside McpServer, that's the whole reason `retrieve_papers()` exists
  on Retriever instead of being composed ad hoc in M8 (module-design "hide the secret" — see
  ARCHITECTURE.md §M7 for the reasoning if you're tempted to shortcut this).

## Prerequisites

`foundation-v0-frozen` tagged (Owner F) for both, **plus** Spike 2 locking the reranker choice (ADR-10)
and the retrieval config (top-k, hybrid weights, rerank depth) before `retrieve()`'s real pipeline can be
finalized — you build against fakes in the meantime, same as everyone else.

## Definition of Done

CONVENTIONS.md §11. Both `retrieve()` and `retrieve_papers()` need their own rerank-wiring assertions —
don't assume testing one covers the other.

## Authoritative references (pointers)

- ARCHITECTURE.md §M7 (read closely: the passage_text-is-not-a-get_span-fetch fix, and the
  `retrieve()`/`retrieve_papers()` split with its `kind="chunk"`/`kind="summary"` internal restriction),
  §M8.
- DATA-CONTRACTS.md §M7 (`GroundedResult`, `Citation`, the Reranker sub-section — `RerankCandidate` and
  why the fake must be non-identity), §M8 (`PaperSummaryView`, `Coverage`, `SearchResponse`,
  `PaperSearchResult`, `PaperSearchResponse`), §Provenance & structure (why `passage_text` = the full
  matched `Chunk.text`, not a `get_span(anchor)` fetch — this is a real bug a naive implementation falls
  into, read the "What this means for `GroundedResult.passage_text`" note there).
- TEST-STRATEGY.md "Retriever" and "McpServer" bullets — including the multi-block-chunk regression test
  and the spy asserting McpServer never touches Embedder/VectorStore/Reranker directly.

## Vendor isolation

The cross-encoder reranker client → **only** the `Reranker` adapter (used by M7, not a top-level module
of its own).

## Test-first, branch/PR procedure

GIT-WORKFLOW.md. Branches: `T-E1-tests`→`T-E1-retriever`, `T-E2-tests`→`T-E2-mcpserver`. M1a PRs are
part of the global milestone gate.

## Scope fence

`evidence_tier` stays pinned `"A"` on every `GroundedResult` — no B/C/D. `metadata` stays `{}` — populating
it later is a `contracts/` foundation-change (T-F7), not a free write from inside M7/M8. No
`synthesize`/`get_citations`/SymPy tools — those are V2. No `describe_capabilities`/`corpus_stats` — V1.
