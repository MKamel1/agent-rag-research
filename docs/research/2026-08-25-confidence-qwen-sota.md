# NB-R2 — answer-confidence estimation + latest Qwen reasoning models, mapped to THIS system

> **STUB.** Web-research ticket (`docs/BACKLOG.md` NB-series). Deliverable is this one cited
> report; no implementation, no pipeline change, no foundation path, no model download.
> Sections fill in as the research lands; every web claim carries a URL, and anything
> unfetchable/paywalled is flagged per-claim rather than guessed.

## Scope

Two questions, one report:

1. **Part 1 — answer confidence for RAG, implementable locally.** Conformal prediction for
   retrieval/QA; semantic entropy / discrete semantics (Farquhar et al. lineage);
   self-consistency (sample-and-agree) and verbalized confidence; NLI/support-checking;
   and how production systems honestly bucket continuous confidence into discrete levels —
   here, the operator's target of **5 confidence levels on MCP answers**. Each mechanism is
   marked **[answer-level]** vs **[passage/claim-level]** per where its results were measured.
2. **Part 2 — latest Qwen reasoning models for an agentic loop.** The current lineup
   (Qwen3 family through any 2025–2026 releases, incl. pinning down exactly what the local
   `qwen38:160k` and `unsloth/Qwen3.8-27B-GGUF` UD-Q4_K_S/M artifacts are), thinking vs
   non-thinking modes, thinking-token-budget control, context windows, function-calling
   reliability, VRAM at quants that fit a 24 GB card **shared with the TEI pair**, and Ollama
   vs vLLM (vs llama.cpp direct) for reasoning-mode/budget control on this stack.

Deliverable ends with two ranked lists:

- **(a)** top-3 confidence mechanisms for the 5-level MCP surface — each with its
  calibration-data requirement and honest per-level semantics;
- **(b)** recommended model + serving posture for the agentic loop, with VRAM arithmetic
  against our card.

## Local ground truth this report builds on (verified, not researched)

| Fact | Source |
|---|---|
| Retrieval-side thresholdable abstention signals: ALL NULL (17 features × 2 fixtures; scores are RRF rank-scale by construction — rank-1 dense max = 1/61 exactly on both fixtures) | [`2026-08-25-nb-d3-abstention-census.md`](../eval-reports/2026-08-25-nb-d3-abstention-census.md); D3 census data `docs/eval-reports/data/2026-08-25-nb-d3/census_full.json` |
| Refusal-affordance detector C1 stage-1: DROPPED — ver84 failed BOTH halves of the pre-committed disjunctive bar; stage-2 sample-consistency died with it (gate was stage 1 clearing). A/B evidence remains strong (wrong-side 6/16 → 1/16 at one clean answerable regression) but is not a detector | [`2026-08-25-nb-c1-refusal-detector.md`](../eval-reports/2026-08-25-nb-c1-refusal-detector.md); ledger commit `d62fb87` |
| Anchor-coverage probe C2: DEAD per pre-committed criterion — AUROC 0.4824/0.3563 (ver84/gt_wmr, gt_wmr inverts) vs ≥0.75 both | [`2026-08-25-nb-c2-anchor-probe.md`](../eval-reports/2026-08-25-nb-c2-anchor-probe.md) (merge `7dc46fa`) |
| Remaining live candidates from A-series design doc: C3 perturbation stability, C4 judge sufficiency screening, C5 embedding relative-density (expected death) | [`2026-08-25-nb-a1-abstention-signal-design.md`](../eval-reports/2026-08-25-nb-a1-abstention-signal-design.md) §1, §3 |
| Generation layer never measured as signal source; affordance arm = only observed item-level separation (14/16 absent-refused vs 3/68 false) | NB-A1 §0 item 1 |
| **Ollama v0.31.2 silent truncation**: past `num_ctx=8192`, keeps only FINAL ~4,098 tokens, no error/warning; rubric-first prompts lost the rubric on 46/84 judge items | [`2026-08-25-nb-judge-rerun.md`](../eval-reports/2026-08-25-nb-judge-rerun.md) §3 |
| **ADR-09 thinking-budget limitation**: Ollama v1 serving stack shares ONE token budget between reasoning and answer; no protected `thinking_token_budget`; hence `think: False` in judge/summarizer/header adapters | `app/judge_llm.py` module docstring; `rag/summarizer.py` `_NUM_CTX_CEILING` comment |
| GPU: RTX 3090 24 GB (24576 MiB total, 11094 MiB used / 13000 MiB free at ticket time) with TEI embedder+reranker pair resident | `nvidia-smi`, 2026-08-25 |
| Local generation models: `qwen3:14b`/`qwen3-14b-16k:latest` (9.3 GB), `qwen38:160k` (16 GB), `hf.co/unsloth/Qwen3.8-27B-GGUF` UD-Q4_K_S (16 GB) + UD-Q4_K_M (17 GB); plus qwen2.5vl:7b, embedding models | `ollama list`, 2026-08-25 |

## Report structure (to be filled)

- §1 Part 1 — confidence mechanisms survey (conformal · semantic entropy · self-consistency ·
  verbalized · NLI support-checking · discrete-level production mapping)
- §2 Part 2 — Qwen reasoning lineup + serving postures (Ollama vs vLLM vs llama.cpp) +
  VRAM arithmetic against the shared 3090
- §3 Recommendation (a): top-3 mechanisms for the 5-level MCP confidence surface,
  each with calibration-data requirement + honest per-level semantics
- §4 Recommendation (b): model + serving posture with VRAM arithmetic
- §5 Sources index; per-claim UNFETCHABLE flags live inline, not here

## Method note

Web research via five parallel librarian passes (one per lane above), then synthesis into
§§1–2 with URL-per-claim discipline; key load-bearing URLs spot-verified by direct fetch
before they carry a recommendation. Local facts in the table above were verified directly
(`ollama list`, `nvidia-smi`, repo docs/git) on 2026-08-25 and need no citation.

## Status

- [x] Stub committed (this commit)
- [ ] §1 Part 1 written
- [ ] §2 Part 2 written
- [ ] §§3–4 recommendations written
- [ ] Sources index complete; report final
