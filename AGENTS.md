# AGENTS.md — project index

Whichever agent you are — Claude Code, a local LLM running under OpenCode, or another tool that reads
this file — **start here.** This file is deliberately an index, not a copy: nothing here restates
content that lives in a doc below; it tells you which doc to open. Read `docs/PROJECT-STATUS.md` next
for what's actually shipped and open today; see "How work is tracked now" below for how work is
assigned.

## What this project is

A personal AI Research Knowledge System: **V0 = a plain grounded RAG cache** over causal-methods arXiv
papers (causal ML, causal inference, causal discovery, treatment-effect estimation, causal
representation learning, causal LLM/agent setups — see CONTEXT.md). Ingest → parse → chunk → embed →
retrieve → return grounded passages + summaries + citations over MCP, at ~0 API cost (local models only).
No claims, no reconciliation, no evidence tiers beyond a pinned `"A"`, no Obsidian — those are V1–V3.

## Doc map (read in this order if you're new; each line notes what it's authoritative for)

| Doc | Authoritative for |
|---|---|
| **docs/PROJECT-STATUS.md** | Current system state: what shipped (with commit SHAs/PR#s), what was tried and rejected, what's open. Every numeric/status claim is re-derived against live source/git, not copied — start here for "what actually exists today." |
| **docs/BACKLOG.md** | The live work queue (D/T/B/O ticket series) — what's open right now, updated as items land. |
| **CONTEXT.md** | Vocabulary and V0–V3 phase definitions. **Wins any terminology dispute.** |
| **DATA-CONTRACTS.md** | Every frozen data shape, ID format, SQLite schema, `Config` fields. **Wins any shape conflict** with ARCHITECTURE.md or PRD.md — never fork a type, fix the other doc to match. |
| **PRD.md** | Vision + 18 ADRs (§12). The ADRs are settled decisions — don't re-litigate Qdrant, SQLite, Ollama→vLLM, etc. without a new fact from Phase 0. |
| **ARCHITECTURE.md** | The 9 modules (M1–M9), their interfaces/invariants, owners A–F, extensibility seams. |
| **CONVENTIONS.md** | Engineering guardrails. **Read §0 first — see below.** |
| **WORK-BREAKDOWN.md** | Milestones, ticket IDs (T-A1, T-F1, …), Definition of Done, dependency graph. |
| **TEST-STRATEGY.md** | Fakes, golden fixtures, contract tests, the retrieval eval set. |
| **PHASE0-RUNBOOK.md** | The de-risking spikes (S0 bring-up, Spike 1 parser, Spike 2 retrieval) that must run before certain tickets can start. |
| **docs/RUNBOOK.md** | Operator bring-up after a reboot: `nvidia-smi` → `python -m app.doctor` → `scripts/dashboard.sh start`, where the dashboard token lives, reaching it over Tailscale. Not to be confused with PHASE0-RUNBOOK.md above (Phase-0 spikes, a different thing). |
| **GIT-WORKFLOW.md** | Branch naming, PR flow, CI gating, the foundation-freeze mechanism. **Read before your first commit.** |
| **EXECUTION-READINESS-REVIEW.md** | Historical principal design review; its fixes are already applied to the docs above. Reference only. |
| **owners/OWNER-\<X>.md** | Frozen build briefs from the original V0 owner-track (module boundaries, invariants) — background, not a live task assignment. See "How work is tracked now" below for what is. |

Two files at repo root are **background only, not authoritative** — don't build against them:
`research-kb-system-scope.md` (earliest raw scoping notes, superseded by PRD.md) and
`Technical Design & Annotated Survey...md` (literature survey that informed the ADRs; the ADRs
themselves in PRD.md §12 are the decision, this file is just the research behind them).

## Codebase map for navigation (dev tooling — optional, not product scope)

A **Graphify** knowledge graph of this repo's source + design docs lives in `graphify-out/graph.json`
(local artifact, git-ignored; the `.graphifyignore` corpus filter is tracked). It is a navigation aid,
**not** part of the V0–V3 product — unrelated to the paper-corpus Obsidian view on the roadmap. To
locate code or trace dependencies, prefer it over blind grep: `graphify query "<question>"`,
`graphify path "A" "B"`, `graphify explain "<node>"` (or `/graphify` in Claude Code). Rebuilt for free
by the post-commit hook; if `graphify-out/` is absent, run `graphify extract . --code-only` (no API key).
A human-browsable Obsidian vault + `graph.html` are generated from the same graph. **Full setup, rebuild,
and usage: `docs/GRAPHIFY.md`.**

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

## How work is tracked now

The six-owner (A-F) build-out is long done — all six tracks landed on `main`, then went through a
hardening phase tracked as `T-DOC<n>` tickets (`WORK-BREAKDOWN.md`'s T-DOC series, now up to
T-DOC95), and the project has since grown well past V0's original scope (books, drop-in, the
dashboard, MCP telemetry, author-org tagging). There is no live owner→session assignment table
anymore — work today is tracked in `docs/BACKLOG.md`'s `D-<n>`/`T-<n>`/`B-<n>`/`O-<n>` series (D =
dashboard/telemetry, T = ad hoc test/tooling, B = book-programme carryover, O = operational/infra),
which is the queue of what's *open*. For what has already shipped — grouped by programme, each item
with its commit SHA(s)/PR#(s) — see `docs/PROJECT-STATUS.md` §3 (shipped-work ledger). The record of
closed PRs runs well past the original #31-#46 range this table used to cite — `docs/BACKLOG.md`
alone references PRs through #227, and the live PR list (`gh pr list --state all`) tops out at #235
as of 2026-08-05; treat any PR-number ceiling as a snapshot, not a fact to hardcode.

**Foundation sign-off authority (T-F7, CONVENTIONS §0.2):** the human operator, GitHub `@MKamel1`. Any PR
touching a foundation-protected path (`.github/CODEOWNERS` — currently `contracts/`, `rag/config.py`,
`config.example.yaml`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`) requires their explicit
approval before merge — mechanized via `.github/CODEOWNERS` + branch protection, see GIT-WORKFLOW.md.

## A second corpus is just a second directory

The pipeline is not hardwired to one corpus. `python -m app.init_config --data-dir <dir>` scaffolds a
new corpus's own `config.yaml` under `<dir>`; select it either by running an ingest-side tool (no
`--data-dir` flag — cwd is the data dir) from inside `<dir>`, or by passing `--data-dir <dir>` to one
of the 4 tools that support it (`app.init_config`, `app.serve`, `app.dashboard.server`,
`app.dashboard.verify_numbers`) — see `docs/PROJECT-STATUS.md` §2 for the full flag table and traps.
The Waymo AV-safety corpus (`docs/PROJECT-STATUS.md` §1) is exactly this pattern, live today.

## If you're picking up work right now

1. Read `docs/PROJECT-STATUS.md` §3 for what's already shipped and §6 for what's open, then pick an
   item from `docs/BACKLOG.md`. The `owners/OWNER-<X>.md` briefs still exist and describe each
   module's original design intent (M1-M9 boundaries, invariants) — useful background, but frozen:
   they are not live ticket assignments.
2. Read `GIT-WORKFLOW.md` before your first commit — including its commit-authorship convention.
3. Do not start a ticket whose prerequisites (foundation freeze, a Phase-0 spike lock) haven't landed —
   `docs/BACKLOG.md`'s item states them explicitly when they matter.
