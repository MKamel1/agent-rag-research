# Owner A — Harvester (M1) + IngestionOrchestrator (M9)

Read `AGENTS.md` (or `CLAUDE.md`, same content) first if you haven't. This file is self-contained for your role — you shouldn't need to
read any other doc cover-to-cover before starting, only the sections pointed at below.

## Modules you own

- **M1 · Harvester** — `harvest(focus_area, cap, ordering) -> Iterator[PaperRef]`. Pointer:
  ARCHITECTURE.md §M1.
- **M9 · IngestionOrchestrator** — `ingest(focus_area, cap)`, wires all stages. Pointer:
  ARCHITECTURE.md §M9.

## Your tickets (WORK-BREAKDOWN.md "M1b" section — full acceptance criteria there)

- **T-A1** — Harvester: arXiv `Source` adapter + `harvest()`.
- **T-A2** — IngestionOrchestrator: wires the stages, idempotency/resume, `relevance_score` computation
  (including the once-per-run `topic_query_vec` hoist — see DATA-CONTRACTS.md §M5's `relevance_score`
  comment, this is a known easy mistake to get wrong, don't compute it inside the per-paper loop).

## Prerequisites

`foundation-v0-frozen` tagged (Owner F). You are **not** blocked on any Phase-0 spike — you build against
the fakes from day one, same as everyone building on M0.

## Definition of Done

CONVENTIONS.md §11.

## Authoritative references (pointers)

- ARCHITECTURE.md §M1, §M9, and "Operational invariants" (the `ingest_state` stage machine, the
  `stored`-vs-`done` distinction for `VectorIndex.upsert` timing — read this closely, it's a real gap a
  naive implementation falls into).
- DATA-CONTRACTS.md §M1 (`PaperRef`), §M5 (`PaperRecord.relevance_score`, the `ingest_state`/`quarantine`
  SQL schema), §M9-adjacent relevance_score note, §IDs.
- TEST-STRATEGY.md "Harvester" and "Orchestrator" bullets under "What to test per module" — including the
  two resume-test cases (chunked→embedded window, and the `stored`→`done` window) and the `FakeEmbedder`
  call-count assertion (`N+1`, not `2N`) that catches the topic-query-vector hoist regressing.

## Vendor isolation

The arXiv API client is importable **only** inside your `Source` adapter (M1). `IngestionOrchestrator`
itself imports no vendor SDKs — it composes interfaces.

## Test-first, branch/PR procedure

GIT-WORKFLOW.md. Branches: `T-A1-tests` → `T-A1-harvester`; `T-A2-tests` → `T-A2-orchestrator`. Your M1a
(test) PRs can't merge until every other owner's M1a PRs are also up — it's a global milestone gate, not
per-ticket; see GIT-WORKFLOW.md.

## Scope fence

Nothing V1/V2/V3-shaped in your modules. Don't add a source-adapter plugin registry — M1's seam is
explicitly hypothetical in V0 (ARCHITECTURE.md principle 4), one adapter only.
