# Owner D — DocumentStore (M5) + VectorIndex (M6)

Read `CLAUDE.md` first if you haven't. This file is self-contained for your role — you shouldn't need to
read any other doc cover-to-cover before starting, only the sections pointed at below.

## Modules you own

- **M5 · DocumentStore** — the source of truth (SQLite + blobs). Pointer: ARCHITECTURE.md §M5.
- **M6 · VectorIndex** — derived, rebuildable (Qdrant). Pointer: ARCHITECTURE.md §M6.

## Your tickets (WORK-BREAKDOWN.md "M1b" section — full acceptance criteria there)

- **T-D1** — DocumentStore: SQLite + blob filesystem, all seven methods
  (`put/get/get_blocks/get_block/get_chunk/get_summary/get_span/iter_papers`), atomicity + idempotency
  tests.
- **T-D2** — VectorIndex: Qdrant adapter, hybrid dense+sparse via the shared `rrf_fuse` (never a local
  reimplementation), `rebuild()`, typed `SearchFilters`.

## Prerequisites

`foundation-v0-frozen` tagged (Owner F) for both. **T-D1** is otherwise unblocked. **T-D2** additionally
needs Spike 2 to verify Qdrant's hybrid/RRF/payload-filtering behavior (PHASE0-RUNBOOK.md "Vector store
note" — Qdrant itself is already locked, ADR-01; Spike 2 verifies the fusion formula, doesn't re-decide
the DB).

## Definition of Done

CONVENTIONS.md §11. Note T-D1's atomicity test specifically requires a fresh-connection check after an
injected mid-`put()` failure — "no exception propagated" alone doesn't prove atomicity.

## Authoritative references (pointers)

- ARCHITECTURE.md §M5, §M6.
- DATA-CONTRACTS.md §M5 (`PaperRecord`, the seven-method interface, `ingest_state`'s `stored`-vs-`done`
  pinning — `VectorIndex.upsert()` is YOUR method that this pin governs the timing of), §M6 (`Hit`,
  `SearchFilters`, the frozen RRF fusion formula + `contracts/fusion.py`), §SQLite schema, §IDs.
- TEST-STRATEGY.md "DocumentStore" and "VectorIndex" bullets + the `rrf_fuse`/cross-adapter contract-test
  section ("Contract tests" — read why the cross-adapter test is deliberately weaker than exact-ordering
  equality before you write it).

## Vendor isolation

`sqlite3` → **only** DocumentStore. `qdrant_client` → **only** VectorIndex. If you ever type
`import qdrant` anywhere else, stop — you're dissolving the swap seam.

## Test-first, branch/PR procedure

GIT-WORKFLOW.md. Branches: `T-D1-tests`→`T-D1-documentstore`, `T-D2-tests`→`T-D2-vectorindex`. M1a PRs
are part of the global milestone gate.

## Scope fence

Don't create V1 schema (`claims`, `claim_relations`, `citation_edges`) — DATA-CONTRACTS.md's SQLite
section names them "DO NOT CREATE IN V0," additive-only when V1 arrives. Don't build multi-bbox `Anchor`
storage — out of scope for V0, a documented V1+ enhancement.
