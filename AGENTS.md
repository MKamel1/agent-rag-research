# AGENTS.md — project index

Whichever agent you are — Claude Code, a local LLM running under OpenCode, or another tool that reads
this file — **start here.** This file is deliberately an index, not a copy: nothing here restates
content that lives in a doc below; it tells you which doc to open. Read your `owners/OWNER-<X>.md` brief
next; it tells you exactly what your job is.

## What this project is

A personal AI Research Knowledge System: **V0 = a plain grounded RAG cache** over causal-methods arXiv
papers (causal ML, causal inference, causal discovery, treatment-effect estimation, causal
representation learning, causal LLM/agent setups — see CONTEXT.md). Ingest → parse → chunk → embed →
retrieve → return grounded passages + summaries + citations over MCP, at ~0 API cost (local models only).
No claims, no reconciliation, no evidence tiers beyond a pinned `"A"`, no Obsidian — those are V1–V3.

## Doc map (read in this order if you're new; each line notes what it's authoritative for)

| Doc | Authoritative for |
|---|---|
| **CONTEXT.md** | Vocabulary and V0–V3 phase definitions. **Wins any terminology dispute.** |
| **DATA-CONTRACTS.md** | Every frozen data shape, ID format, SQLite schema, `Config` fields. **Wins any shape conflict** with ARCHITECTURE.md or PRD.md — never fork a type, fix the other doc to match. |
| **PRD.md** | Vision + 18 ADRs (§12). The ADRs are settled decisions — don't re-litigate Qdrant, SQLite, Ollama→vLLM, etc. without a new fact from Phase 0. |
| **ARCHITECTURE.md** | The 9 modules (M1–M9), their interfaces/invariants, owners A–F, extensibility seams. |
| **CONVENTIONS.md** | Engineering guardrails. **Read §0 first — see below.** |
| **WORK-BREAKDOWN.md** | Milestones, ticket IDs (T-A1, T-F1, …), Definition of Done, dependency graph. |
| **TEST-STRATEGY.md** | Fakes, golden fixtures, contract tests, the retrieval eval set. |
| **PHASE0-RUNBOOK.md** | The de-risking spikes (S0 bring-up, Spike 1 parser, Spike 2 retrieval) that must run before certain tickets can start. |
| **GIT-WORKFLOW.md** | Branch naming, PR flow, CI gating, the foundation-freeze mechanism. **Read before your first commit.** |
| **EXECUTION-READINESS-REVIEW.md** | Historical principal design review; its fixes are already applied to the docs above. Reference only. |
| **owners/OWNER-\<X>.md** | **Your actual task brief. Start there, not here.** |

Two files at repo root are **background only, not authoritative** — don't build against them:
`research-kb-system-scope.md` (earliest raw scoping notes, superseded by PRD.md) and
`Technical Design & Annotated Survey...md` (literature survey that informed the ADRs; the ADRs
themselves in PRD.md §12 are the decision, this file is just the research behind them).

## The weak-communication thesis (CONVENTIONS.md §0 — read the full section, this is the 3-line version)

You are one session in a build team of AI agents and junior developers with **no memory across
sessions**. Nothing survives except what's written down. Guardrails in this repo are therefore
**mechanical (CI-enforced)**, not cultural — don't treat a prose rule as optional just because nothing
stops you from ignoring it; CI will. If a frozen contract (`contracts/`, `Config`, the SQLite schema, the
fakes) looks wrong to you, **stop and flag it — do not silently redefine a "close enough" local version**
and do not route around it in your own module. And: **no unsolicited scope expansion** — touch your
ticket's files and tests, nothing else, even if you notice something else that "should" be fixed.

This applies regardless of which tool you're running under — the guardrails live in CI and in these
docs, not in any one tool's memory or session state.

## Environment

Use the `agent-rag-research` conda env (`environment.yml` at repo root; `conda activate
agent-rag-research`) — not the machine's pre-existing `pytorch-env`. Downstream unit tests (everything
except the real adapters' own contract tests) run **zero-GPU, zero-network** — this is CI-enforced
(GIT-WORKFLOW.md / CONVENTIONS §12), not just a convention to remember.

## Owner → session mapping and sign-off authority

Filled in as each owner is actually dispatched — update this table when you start work as an owner so a
later session (or the human) can see who's doing what:

| Owner | Modules | Session/agent | Status |
|---|---|---|---|
| F | Shared foundation (T-F1…T-F7) | _unassigned_ | done — frozen at `foundation-v0-frozen` |
| A | Harvester, Orchestrator | _unassigned_ | not started |
| B | Parser | _unassigned_ | not started |
| C | Chunker, Summarizer, Embedder | _unassigned_ | not started |
| D | DocumentStore, VectorIndex | _unassigned_ | not started |
| E | Retriever, McpServer | _unassigned_ | not started |

**Foundation sign-off authority (T-F7, CONVENTIONS §0.2):** the human operator, GitHub `@MKamel1`. Any PR
touching `contracts/`, `config.py`, `config.yaml`, `migrations/`, or `rag/fakes/` requires their explicit
approval before merge — mechanized via `.github/CODEOWNERS` + branch protection, see GIT-WORKFLOW.md.

## If you're picking up work right now

1. Find your owner letter and read `owners/OWNER-<X>.md` — it names your modules, your ticket IDs, your
   prerequisites, and points you at the exact sections of the docs above that govern your work.
2. Read `GIT-WORKFLOW.md` before your first commit — including its commit-authorship convention.
3. Do not start a ticket whose prerequisites (foundation freeze, a Phase-0 spike lock) haven't landed —
   your owner brief states them explicitly.
