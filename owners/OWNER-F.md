# Owner F — Shared Foundation

Read `CLAUDE.md` first if you haven't. This file is self-contained for your role — you shouldn't need to
read any other doc cover-to-cover before starting, only the sections pointed at below.

## Role

You build the **shared foundation** every other owner (A–E) codes against in parallel. Per
WORK-BREAKDOWN.md: "the single highest-blast-radius artifact in the build... if it drifts after the
fan-out, every module drifts with it and the failure surfaces late, at integration." You go **first**,
alone, then freeze and tag what you built so A–E can start.

## Modules you own

None of M1–M9 — your output is the substrate they're all built on: the `contracts/` package, `Config`,
the SQLite schema, the six fakes, and the CI enforcement job.

## Your tickets (WORK-BREAKDOWN.md "M0 — Shared foundation" — full acceptance criteria there, not repeated here)

- **T-F1** — `contracts/` package: every dataclass/TypedDict in DATA-CONTRACTS.md, `GpuLock` protocol,
  `contracts/errors.py`, `contracts/fusion.py` (`rrf_fuse`).
- **T-F2** — `Config` loader reading `config.yaml` (already filled in at repo root with real V0 values,
  including `focus_area_queries` — you build the loader, the values are already decided).
- **T-F3** — SQLite schema/migration script (DATA-CONTRACTS.md "SQLite schema" section is the DDL source).
- **T-F4** — The six fakes: `FakeEmbedder`, `FakeVectorStore`, `FakeSource`, `FakeSummarizer`,
  `FakeReranker` (non-identity!), `FakeGpuLock`.
- **T-F5** — CI harness (unit+fake+golden on every push, nightly slot for real-adapter+eval).
- **T-F6** — The CI enforcement job itself: mechanize checks (a)–(i) listed in CONVENTIONS.md §12 and
  WORK-BREAKDOWN.md's T-F6 entry, including the zero-GPU/zero-net check
  (`pytest-socket --disable-socket` + `CUDA_VISIBLE_DEVICES=""`). A CI skeleton already exists at
  `.github/workflows/ci.yml` with a placeholder marking where (a)–(i) go — fill it in for real.
- **T-F7** — the foundation-freeze protocol itself (tag `foundation-v0-frozen`, confirm
  `.github/CODEOWNERS` + branch protection are active — they were set up during repo bootstrap; verify,
  don't re-create).

## Prerequisites

None — you start immediately.

## Definition of Done

CONVENTIONS.md §11, applied to each of T-F1–T-F6 individually.

## Authoritative references (pointers — the content lives there, not here)

- DATA-CONTRACTS.md — every section (this is what you're translating into code).
- CONVENTIONS.md §0 (why the guardrails must be mechanical), §12 (the exact PR checklist T-F6 mechanizes).
- TEST-STRATEGY.md "Fakes" section (exact behavior each fake must have — the `FakeReranker` must NOT be
  an identity reorder, this is the single most common mistake here).
- WORK-BREAKDOWN.md "M0" section (ticket-by-ticket Done criteria).

## Vendor isolation

None — you own no adapters. You DO own enforcing that everyone else's adapters stay isolated (T-F6a).

## Test-first, branch/PR procedure

GIT-WORKFLOW.md — your tickets are the exception to the M1a/M1b split (there's no "implementation" to
gate behind tests here in the usual sense; T-F1/T-F4 largely *are* their own tests). Branch per ticket:
`T-F1-contracts`, `T-F2-config`, etc.

## Scope fence

Don't create V1 schema (claims/claim_relations/citation_edges tables) — DATA-CONTRACTS.md's SQLite
section names them explicitly as "DO NOT CREATE IN V0." Don't build anything for B/C/D/E's adapters —
those stay as directories only until each owner starts (Phase-0-gated ones may still be empty when you
freeze; that's expected, not a gap in your ticket).

## After you're done

Tag `foundation-v0-frozen` on `main`. Update the Owner→session table in `CLAUDE.md` to mark yourself
done. A–E can now start (subject to their own Phase-0 prerequisites, in their owner briefs).
