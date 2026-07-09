---
title: "Principal Design Review — Execution Readiness (V0)"
date: "2026-07-08"
verdict: "NEEDS REVISION (one contract hole to close before M0 freeze) — then ready to build"
status: "Findings 1-6 applied directly to ARCHITECTURE.md / DATA-CONTRACTS.md / PRD.md / WORK-BREAKDOWN.md / TEST-STRATEGY.md / CONVENTIONS.md on 2026-07-08. The Execution Readiness Gap List below (missing files/artifacts, missing info, tacit knowledge) is NOT yet actioned — it's the remaining pre-execution punch list."
---

# Principal Design Review — AI Research Knowledge System V0
## Execution-readiness pass, ahead of handing off to a weak-communication build team (AI agents + junior devs)

> **Update (2026-07-08):** Findings 1–6 below have been applied directly to the design docs (see the
> `status` field above and the per-finding notes). This file is kept as the historical review record —
> the docs themselves are now authoritative. The **Execution Readiness Gap List** section is still an
> open punch list; nothing there has been built yet.

This supersedes / resolves `rag_v0_design_review.md` (2026-07-06). See "Re-adjudication of the prior review" below —
each of its 6 findings was independently re-checked against the current files rather than accepted or dismissed wholesale.

---

## Verdict: needs revision

This is one of the strongest pre-build design suites reviewed. The mechanical-guardrail thesis (CONVENTIONS §0),
source-of-truth/derived split, seam discipline (real seams only where behavior varies), single ownership, the frozen
`contracts/` package, cross-process `GpuLock`, and the M1a-before-M1b test-first gate are all correct and unusually
well-executed for a weak-communication build team. **Scope discipline held — no premature V1–V3 machinery found in V0.**
Every forward-compat hook is a single-field/single-mechanism seam justified by a stated V0 need.

Not yet execution-ready for one substantive reason (a real hole in a *frozen* contract — must close before the M0
freeze because 5 owners code against it in parallel) plus five cheap clarifications, plus the artifacts in the Gap
List below that simply don't exist on disk yet.

---

## Findings

### 1. [Root cause] `Anchor`/`GroundedResult` assumes a single-block retrieval unit — two V0 paths violate it
- **Summary surface**: `search_papers` can return summary-level `GroundedResult`s, but a summary has no block/page/bbox
  to anchor to (DATA-CONTRACTS §M7 L338–352, §M8 L463, §M6 L265, §M5 L250). Every option a builder might invent
  (nullable anchor / dummy bbox / anchor-to-abstract) breaks either the grounding invariant or the re-grounding check.
- **Passage surface**: Chunker groups multiple blocks (b0+b1+b2) into one Chunk to keep an equation with its prose
  (ARCHITECTURE L69–73), but pins `anchor`/`parent_id` to the *first* block only. `get_span` then returns just b0
  (§M5 L252) — so a chunk that matched on b1's equation cites only b0, silently, with no failing test. This also
  **inverts** the documented small-to-big pattern (CONTEXT L52–54: return the *enclosing* parent — here the "parent"
  is smaller than the searched child).
- **Why it matters**: frozen shared type, 5 owners build against it from M0. Getting it wrong here is exactly the
  late-integration drift CONVENTIONS §0 exists to prevent, and it undermines the grounding invariant that *is* the product.
- **Fix (decide and write down before freeze)**: Passage path — `passage_text` = full matched chunk span (bbox
  pinned to first block as an accepted precision loss); fix the `get_span`/small-to-big wording so it can't be read
  as "return only the first block." Summary path — do NOT force summary results through anchored `GroundedResult`;
  return a non-anchored shape (extend `PaperSummaryView` + `score`); keep `Retriever.retrieve()` passage-only.
  **Placement choice to make deliberately**: either an additive `Retriever` method for summary/paper search (keeps
  logic in the deep module) or compose it in `McpServer` from `hybrid_search(kind="summary")` + `get_summary`/`get`
  (keeps M7 untouched, thickens M8 slightly). Also state whether the summary path is reranked in V0. Pick one, write it down.

### 2. M9 re-embeds a static string 15,000 times
ARCHITECTURE §M9 (L177–179) / DATA-CONTRACTS §M5 (L238–241): `relevance_score` embeds the topic-query string inside
the per-paper loop. It's identical every paper. Fix: state explicitly it's computed once per run and passed into scoring.

### 3. "Zero-GPU / zero-network" tests are asserted but not mechanized
TEST-STRATEGY's golden rule depends on it; none of T-F6's 8 checks enforce it at runtime (all static/grep). An agent
debugging a red test will reach for a live Qdrant/HF download; if the CI runner has network, it passes silently. Fix:
add `pytest-socket --disable-socket` + `CUDA_VISIBLE_DEVICES=""` to T-F6 for non-adapter suites (~2 lines). (The CUDA
var also catches accidental real-GPU use on local dev machines.)

### 4. `ingest_state` never pins where `VectorIndex.upsert` happens in the sequence
Stage enum is `harvested|parsed|chunked|summarized|embedded|stored|done`; ordering invariant says "source-of-truth
before derived index" but not which named stage `upsert` runs at. Wrong placement + a crash there = paper silently
absent from the vector index forever, and the resume test doesn't cover this window. Fix: one sentence pinning it.

### 5. PRD §8.5 is stale against the authoritative contracts
§8.5 (L396–397) stages "tiers A–C + coverage" as "v1" and its response envelope (L371–373) is a flat field set — both
predate the V0/V1/V2/V3 renaming and contradict DATA-CONTRACTS (tier pinned `"A"`, `Coverage` built in V0). Fix:
reconcile wording + add a one-line precedence rule (DATA-CONTRACTS wins on shapes over PRD, mirroring ARCHITECTURE L5).

### 6. (light) `GroundedResult.metadata: dict` is an untyped escape hatch
Fine empty in V0 (typing it now would import V1/V2 field defs that don't exist — the premature-machinery the owner
is right to avoid). Cheap governance fix instead: one line noting that populating `metadata` is a T-F7
foundation-change, not a free write.

---

## Re-adjudication of the prior review (`rag_v0_design_review.md`, 2026-07-06)

Independently re-checked against current files — not accepted or dismissed wholesale:

| # | Prior finding | Verdict |
|---|---|---|
| 1 | Static query re-embedded per-paper | **Valid, worth doing** — matches Finding 2 above. |
| 2 | Non-`str` ID wrapper dataclasses | **Overkill for V0.** T-F6(h) already grep-bans id string-slicing outside `DocumentStore`, and type-discriminating id prefixes already make `get_chunk`/`get_block`/`get_summary` raise `ContractError` on a wrong-kind id — a second guardrail already covers this. Wrapper types would churn every contract shape, SQLite adapter, and JSON path for a benefit already had. This is the gold-plating you were right to worry about. |
| 3 | Mandatory transaction/rollback + cross-store 2PC | **Stale / already addressed.** `DocumentStore.put` is already specified atomic with an explicit atomicity test (T-D1). Cross-store consistency is handled by source-vs-derived + idempotent upsert + ordering + `rebuild()`; 2PC would over-engineer what the rebuildable design deliberately avoids. |
| 4 | Ban literal `==` on envelopes in tests | **Valid but low priority, partly a testing-mechanics call.** V0 `metadata` is empty and tier is pinned, so `==` tests stay green until V1 actually changes them (a V1 task that touches tests anyway). Downgraded to a one-line TEST-STRATEGY preference, not a binding rule. |
| 5 | Mechanical zero-GPU/zero-net CI | **Valid, worth doing** — matches Finding 3 above. |
| 6 | Summary retrieval anchor breakdown | **Valid, worth doing** — real contract hole, folded into Finding 1. Fix can be lighter than the prior review's two-method prescription — see the placement choice under Finding 1. |

**Net: 4 of 6 were real, 2 were overkill/stale.** Your instinct not to blindly implement the old review was correct in those two cases; the ID-wrapper-classes one in particular was exactly the kind of speculative-generality you were right to be wary of.

---

## Execution Readiness Gap List
### The literal pre-execution punch list — everything an owner/agent with access to *only this directory* needs and currently cannot find.

### 1. Missing files / artifacts (referenced or assumed, absent on disk)

The directory currently contains **only docs** — every buildable artifact the docs presuppose is missing:

| # | Missing | Why it blocks weak-comm execution | Fix |
|---|---|---|---|
| 1 | `contracts/` package (§M1–M8 types + `errors.py` + `fusion.py` + `GpuLock`) | Every owner imports it; without it, nothing compiles and each agent invents local shapes | Owner F builds T-F1 first; tag `foundation-v0-frozen` |
| 2 | `config.yaml` + `Config` loader with real values | `focus_area_queries` exact strings, locked `EmbedderInfo.dim`, `gpu_lock_path` undefined | Create `config.yaml` with the concrete causal-methods arXiv query set + locked knobs (T-F2) |
| 3 | SQLite schema/migration script (T-F3) | DDL exists only as prose | Ship the migration script as code |
| 4 | The six fakes (T-F4) | M1a test-first gate can't start without them | Owner F builds them day 1 |
| 5 | CI harness + T-F6 enforcement job + deliberately-broken fixture diffs | The mechanical-guardrail thesis is inert until this runs | Build T-F5/T-F6; commit one failing fixture per check (a)–(h) |
| 6 | `pyproject.toml` / lockfile + Python interpreter pin | Env is ambiguous (system 3.13 vs `pytorch-env` 3.12+torch2.6+cu124) — not referenced anywhere in the build docs | Pin Python 3.12 + deps matching `pytorch-env` |
| 7 | Repo scaffold / directory layout | T-F6(g) "sibling test file" check presumes a layout never specified | One-paragraph "repo layout" section |
| 8 | `phase0-results.md` | Baselines/regression gates the whole build cites don't exist until Phase 0 runs | Produced by Phase 0; hard M0-exit gate |
| 9 | Golden fixture PDFs + expected `ParsedDoc` assertions (~8–12) | Parser (M2), the one un-fakeable module, has nothing to test against | Output of Spike 1; commit the scored PDFs |
| 10 | ~50-question retrieval eval set (content + labels) | Blocks the Spike-2 gate and T-EVAL — the headline quality bar | **RESOLVED (2026-07-08):** no human labeler — agent-generated teacher-student pattern, ~200 questions. See TEST-STRATEGY.md "Retrieval eval set" + PHASE0-RUNBOOK.md Spike 2 + PRD §11 Q6. The actual `eval_set.jsonl` content is still Spike 2's output, not produced by this scaffolding pass. |
| 11 | Locked adapter choices (parser/embedder/reranker; ADR-06/02/10) | Modules wrap adapters not yet chosen | Resolved by Spikes 1 & 2 before M2 |
| 12 | License note for the chosen parser | MinerU is AGPL-3.0; fine for personal/local/non-shared use, but that caveat isn't written anywhere | Add one line to PRD §11B: acceptable only under personal/local/non-shared assumption; revisit on any share/host decision |
| 13 | Owner A–F → real person/agent mapping | Plan assumes 5 parallel owners; unstated whether these are concurrent agent sessions or one solo operator sequentially. T-F7 sign-off presumes a specific human identity | **RESOLVED (2026-07-08):** `owners/OWNER-A.md`…`OWNER-F.md` + the Owner→session table in `CLAUDE.md` (filled in as each owner is dispatched); sign-off identity named as Omar/`MKamel1`. |

### 2. Missing information inside existing files (a weak-comm builder would have to guess)

- **Anchor/GroundedResult hole** — DATA-CONTRACTS §M7 L341, §M8 L463, §M6 L265, §M5 L252, §Provenance L78–85 → resolve per Finding 1.
- **M9 static-query hoist** — ARCHITECTURE L177–179, DATA-CONTRACTS §M5 L238–241 → state "computed once per run."
- **`VectorIndex.upsert` stage placement** — DATA-CONTRACTS L550–554 vs ARCHITECTURE L173 → one sentence.
- **PRD §8.5 stale scope** — L371–373, L396–397 → reconcile + precedence line.
- **Concrete `Config` values** — **RESOLVED (2026-07-08)** for `focus_area_queries`: filled into `config.yaml` at repo root, organized by CONTEXT.md's 6 V0 sub-topics + econ/library coverage. `EmbedderInfo.dim = 2560` remains a placeholder until Spike 2 locks the embedder.
- **Summary-path rerank decision** — implicit, needs to be stated.
- **PRD §11 Q6 (eval-labeling ownership)** — **RESOLVED (2026-07-08):** agent-generated, no human labeler; see gap-list item #10 above.

### 3. Tacit knowledge you have but haven't written into the authoritative build docs

- **Python/env target** — only in PRD §13 + scope notes, not in CONVENTIONS/WORK-BREAKDOWN. A context-free agent won't know to build/test in `pytorch-env` (3.12 + torch 2.6.0+cu124) vs system 3.13. → state target interpreter/env in CONVENTIONS.
- **Model provisioning** — exact Ollama tag for the summarizer ("Qwen 14B workhorse" — which tag), HF repo/revision for Qwen3-Embedding-4B and BGE-reranker-v2-m3, GROBID/MinerU weight sources. None captured. → add a "model sources & tags" appendix to PHASE0-RUNBOOK.
- **Per-model VRAM budget** — the 24GB single-GPU rule assumes specific model sizes/precisions fit; the quantization each model needs is tacit. → one table of per-model precision + VRAM in PHASE0-RUNBOOK S0.
- **Ollama bring-up** — "installed, not running" (PRD §13); S0 says stand it up but start command/port/preload steps aren't captured. → add concrete commands to S0.
- **arXiv API specifics** — Harvester invariants say "respects rate limits" with no numbers/endpoint/client. → pin client, rate limit, resume-cursor mechanics in T-A1.
- **GPU driver NVML mismatch** — already carried into S0. No further action.

---

## Challenges resolved (red-team pass)

- **review-skeptic** flagged that parent-block expansion drops matched content in multi-block chunks (High) —
  accepted and folded into Finding 1 as the second surface of the same root cause; it raised the finding's priority.
  Also flagged the `metadata: dict` escape hatch and the PRD §8.5 staleness — both accepted, the former only as the
  cheap governance note (typing it now would be the same over-engineering trap), the latter as Finding 5.
- **change-minimizer** flagged that Finding 1's fix understates its footprint if summary results flow through
  `Retriever.retrieve()` — accepted, and the placement choice (additive M7 method vs M8 composition) is now
  explicit in Finding 1 rather than papered over. It confirmed a "nullable anchor + doc rule" alternative would
  launder the ambiguity rather than close it.
- No challenge overturned the verdict. The only remaining open call is *where* the summary-path fix lives (M7 vs
  M8) — a deliberate implementation choice, not a design gap.

---

## Bottom line

1. Close Finding 1 (Anchor/GroundedResult single-block hole) before the M0 freeze — it's the only item that would
   actually cause parallel-build integration failure.
2. Apply Findings 2–6 — all one-line-to-one-paragraph doc edits.
3. Work the Execution Readiness Gap List §1–3 as the actual pre-execution task list — most of it is "build the
   artifact the docs already describe," not new design work.
4. Two of the six prior-review findings (ID wrapper types, transaction/2PC mandate) were correctly left unactioned —
   don't revisit them; the current mechanisms already cover their concerns without the added machinery.
