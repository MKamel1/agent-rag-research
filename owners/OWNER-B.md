# Owner B — Parser (M2)

Read `CLAUDE.md` first if you haven't. This file is self-contained for your role — you shouldn't need to
read any other doc cover-to-cover before starting, only the sections pointed at below.

## Modules you own

- **M2 · Parser** — `parse(raw: PdfBytes | LatexSource) -> ParsedDoc`. Pointer: ARCHITECTURE.md §M2.

## Your tickets (WORK-BREAKDOWN.md "M1b" section — full acceptance criteria there)

- **T-B1** — the Phase-0-chosen adapter behind the `Parser` interface + PDF/LaTeX routing + GROBID
  references.

## Prerequisites

`foundation-v0-frozen` tagged (Owner F) **and** PHASE0-RUNBOOK.md Spike 1 has locked the parser choice
(ADR-06: MinerU vs Marker vs Docling — "may change" until that spike runs). You are also the module on
the **critical path** for Spike 1 itself — you may be the one running it, not just waiting on it; check
with whoever is coordinating Phase 0 before assuming someone else is running Spike 1.

## Definition of Done

CONVENTIONS.md §11 **plus**: this is the one module correctness can't be faked for (TEST-STRATEGY.md
"Golden fixtures" section) — your tests run against real, hand-checked PDFs, not just a fake.

## Authoritative references (pointers)

- ARCHITECTURE.md §M2.
- DATA-CONTRACTS.md §M2 (`ParsedDoc`, `Figure`, `TableItem`, `Reference`), §Provenance & structure
  (`Block`, `Anchor`, the multi-block anchoring rule your output feeds into downstream).
- TEST-STRATEGY.md "Golden fixtures" section (~8–12 real PDFs: math-heavy, code-heavy, multi-column,
  table-heavy, one deliberately broken/scanned) and the "Parser" bullet under "What to test per module."
- PHASE0-RUNBOOK.md "Spike 1 — Parse + provenance fidelity."

## Vendor isolation

MinerU/Marker/Docling/GROBID are importable **only** inside your `Parser` adapter(s). No other module may
import any of them (CONVENTIONS.md §1).

## Test-first, branch/PR procedure

GIT-WORKFLOW.md. Branch: `T-B1-tests` → `T-B1-parser`. Your M1a PR is part of the same global
milestone gate as every other owner's.

## Scope fence

VLM figure descriptions (`Figure.vlm_description`) stay `None` — that's V3 (ARCHITECTURE.md §M2 "V3
extension" note). Every `Block` must have a valid `page`+`bbox` or it's a `ContractError` — never emit a
fake `bbox=(0,0,0,0)`.
