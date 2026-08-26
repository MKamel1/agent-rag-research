# NB-R2 — answer-confidence estimation + latest Qwen reasoning models, mapped to THIS system

> **COMPLETE** (supersedes the stub banner). Two cited survey sections (§§1–2), two ranked
> recommendations (§§3–4), sources index (§5). Every web claim carries a URL; anything not
> pinned to a primary source at write time is flagged inline (UNFETCHED / UNKNOWN / cluster
> incomplete) rather than guessed. No implementation, no pipeline change, no foundation path,
> no model download.

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

## Method note — what happened to the two research clusters, and what that cost this report

The stub's original method line promised "five parallel librarian passes … then synthesis". That
is not what produced this text. The honest account:

- **Both web-research clusters were lost.** The research parent session
  (`NB-R2: RAG confidence + Qwen research`, 2026-08-26 04:33 UTC) spawned five librarian lanes as
  background tasks (conformal; semantic-entropy/sampling/NLI; discrete-levels-in-production;
  Qwen lineup 2025–2026; Ollama-vs-vLLM serving), then ended its turn to await their completion
  and died there. Every lane's sub-session holds **only the dispatch prompt** — zero assistant
  output parts, `tokens_output = 0` in every state store on disk. Verified by direct SQLite
  harvest across all `/tmp/oc-state-*` stores: no lane findings exist anywhere; a WAL replay of
  the parent store added nothing; no orphaned headless-runner state dirs contain them. The write
  brief's two store paths were also stale (they hold unrelated NB-XC / NB-NUMCTX sessions).
- **What survived and was used instead:** the five dispatch prompts themselves (they enumerate
  exactly what the survey needed to pin); this repo's committed local evidence (table above);
  measured facts from sibling ticket branches (`NB-NUMCTX` context-window/thinking measurements,
  commits `5a74d7a`+`96dc650`; `NB-B0` benchmark audit on `main`); and already-verified primary
  sources from the sibling NB-R1 report ([`2026-08-25-agentic-rag-sota.md`](2026-08-25-agentic-rag-sota.md),
  merged) for mechanisms both tickets lean on (Self-RAG, CRAG).
- **Recovery path** = the one NB-R1's writer used under identical loss: first-party targeted
  verification of each load-bearing claim at write time (2026-08-25/26), with URL-per-claim.
  Live-verified this session: Quach et al., Farquhar et al. (Nature), Kuhn et al., Manakul et al.,
  Tang et al. (MiniCheck), Honovich et al. (TRUE), Tian et al., Xiong et al., Kumar et al.,
  Angelopoulos & Bates (+LTT/CRC), the unsloth/Qwen3.8 HF cards + guide, Ollama thinking docs and
  the thinking-budget issue/PR pair, vLLM reasoning-outputs docs, BFCL leaderboard mirrors.
- **Cluster status at write time: PARTIALLY RECOVERED.** Part 2 is well-pinned (the model lineup
  was re-derived from primary vendor pages and from the local artifacts themselves). Part 1's
  *production-bucketing survey* lane (vendor confidence-field documentation, RAG-truth-class
  benchmarks beyond what prior repo reports already cite) is **incomplete at write time** — that
  gap is marked where it bites (§1.6, §3). Nothing below rests on an unpinned claim.

## §1 Part 1 — answer-confidence mechanisms for RAG, implementable locally

Granularity tags per the scope: **[answer-level]** (measured on whole-answer correctness /
hallucination detection) vs **[passage/claim-level]** (support or factuality per span).

### 1.1 NLI / support-checking against grounding documents [passage/claim-level]

The family our MCP surface maps onto most directly: score each generated claim against the served
passages with an entailment model.

- **TRUE** (Honovich et al., NAACL 2022 findings lineage, arXiv 2204.04991,
  <https://arxiv.org/abs/2204.04991>): standardized meta-benchmark over 11 factual-consistency
  datasets; large-scale **NLI** and question-generation-and-answering metrics are the strongest
  families (best NLI systems avg AUC ≈ 81.5 across datasets), and they are complementary in
  ensemble. Establishes that support-checking quality is measurable example-level, not just
  system-level.
- **MiniCheck** (Tang, Laban, Durrett, EMNLP 2024, arXiv 2404.10774,
  <https://arxiv.org/abs/2404.10774>; models <https://github.com/Liyan06/MiniCheck>,
  leaderboard <https://llm-aggrefact.github.io>): sentence-level fact-checkers trained on
  synthetic GPT-4-generated error instances; **MiniCheck-FT5 (770M params) reaches GPT-4-level
  accuracy on LLM-AggreFact at >400× lower cost**, without a separate claim-decomposition step
  (decomposition multiplies inference cost 2–4× with no consistent accuracy gain — same paper).
  Small downloadable models; runs comfortably on our card even beside other workloads.
- What it guarantees / costs / breaks it: no statistical guarantee — it is a trained score whose
  direction ("supported" vs "unsupported") is supervised by construction; cost is one small-model
  forward pass per claim; breaks when the grounding passage itself is irrelevant to the question
  (it measures faithfulness-to-context, NOT answer correctness — a confidently wrong answer
  supported by a wrong retrieved passage still scores high). This is why it pairs with an
  abstention/absence signal rather than replacing one.

### 1.2 Semantic entropy lineage [answer-level; factoid-level variant for long-form]

- **Semantic uncertainty / semantic entropy** (Kuhn, Gal, Farquhar, ICLR 2023, arXiv 2302.09664,
  <https://arxiv.org/abs/2302.09664>; code <https://github.com/lorenzkuhn/semantic_uncertainty>):
  sample k answers, cluster them by **bidirectional NLI entailment** (meaning-level, not lexical),
  compute entropy over cluster probabilities. Unsupervised, single model, out-of-the-box;
  outperforms sequence-probability entropy, lexical similarity and p(True) baselines on TriviaQA
  and CoQA AUROC.
- **Nature 2024 follow-up** (Farquhar, Kossen, Kuhn, Gal, Nature 630:625–630, 19 Jun 2024,
  <https://www.nature.com/articles/s41586-024-07421-0>, doi 10.1038/s41586-024-07421-0): detects
  "**confabulations**" — arbitrary, incorrect generations sensitive to random seed. Evaluated via
  AUROC (error prediction) and AURAC (selective-refusal accuracy) across TriviaQA, SQuAD, BioASQ,
  NQ-Open, SVAMP, FactualBio. Two load-bearing details for us: (a) the **discrete variant needs no
  token probabilities at all** — cluster counts suffice — so it works through serving stacks that
  don't expose logprobs (ours); (b) the authors' own scope statement: it detects only
  seed-arbitrary wrongness — "**it does not guarantee factuality because it does not help when
  LLM outputs are systematically bad**" (same source). Long-form mode decomposes passages into
  factoids and scores each — i.e., it degrades gracefully toward claim granularity.
- Cost: k samples (paper uses 5–10) + k² pairwise NLI calls per answer — cheap locally except for
  the k× generation latency multiplier.

### 1.3 Self-consistency / sample-and-agree [sentence/passage-level detection]

- **SelfCheckGPT** (Manakul, Liusie, Gales, EMNLP 2023,
  <https://aclanthology.org/2023.emnlp-main.557/>; arXiv 2303.08896): if the model knows a fact,
  stochastic samples tend to agree; hallucinated facts diverge. Variants: BERTScore, QA-based,
  and **NLI-based** cross-sample checking; detects non-factual sentences and unsupported claims at
  sentence level (WikiBio-passage evaluation). Same k-sample cost shape as §1.2; conceptually its
  ancestor without the meaning-clustering step. Agreement is a *detection signal*, not a
  calibrated probability — mapping agreement rates to error probabilities is exactly the
  calibration problem §§1.5–1.6 address.

### 1.4 Verbalized confidence [answer-level]

- **Just Ask for Calibration** (Tian et al., EMNLP 2023, arXiv 2305.14975,
  <https://arxiv.org/abs/2305.14975>; PDF <https://aclanthology.org/2023.emnlp-main.330.pdf>):
  for RLHF-tuned models, **verbalized confidences are typically better-calibrated than the
  models' conditional token probabilities** on TriviaQA/SciQ/TruthfulQA — often halving expected
  calibration error (ECE) relative to sampled-probability estimates; asking for several candidate
  answers before the confidence number improves calibration further; chain-of-thought does not;
  combining with temperature scaling (Guo et al. 2017, §1.5) helps.
- **Can LLMs Express Their Uncertainty?** (Xiong et al., arXiv 2306.13063,
  <https://arxiv.org/abs/2306.13063>): systematic framework (prompting × sampling × aggregation)
  over five task types and five LLMs; headline caveats: verbalizing models are **prone to
  overconfidence** (imitating human idiom), multi-sample consistency and better aggregation
  mitigate but nothing dominates, white-box methods beat black-box ones only narrowly (~0.52 →
  ~0.61 AUROC in their comparison), and all methods degrade on professional-knowledge tasks.
- Verdict for us: cheapest signal to add (one prompt field), but the least honest *primary*
  driver of published levels — documented overconfidence plus prompt sensitivity means its raw
  output must itself be calibrated before it earns a level label.

### 1.5 Conformal prediction family [answer-level sets; claim-level extensions exist]

What split conformal actually guarantees: given a held-out calibration set, exchangeability with
the test point is the ONLY assumption; the resulting prediction sets carry a **finite-sample
marginal coverage guarantee** (≥ 1−α, up to a 1/(n+1) correction) regardless of model correctness
— canonical reference Angelopoulos & Bates, *Conformal Prediction: A Gentle Introduction*,
Foundations & Trends in ML 16(4), arXiv 2107.07511 (<https://arxiv.org/abs/2107.07511>, doi
10.1561/2200000101). The guarantee is explicitly **marginal, not conditional** (their §3.1
discusses the impossibility result) — a caveat that matters if we ever want per-question-type
level semantics.

LLM-specific instantiations:

- **Conformal Language Modeling** (Quach et al., ICLR 2024, arXiv 2306.10193,
  <https://arxiv.org/abs/2306.10193>): calibrates a sampling **stopping rule** (keep drawing
  candidates until the set provably contains ≥1 acceptable response w.p. ≥ desired coverage) plus
  a rejection rule, via Learn-then-Test; also identifies independently-correct *subsets* of
  phrases/sentences within responses with guarantees — the closest published thing to
  guaranteed claim-level flags. Works with any sampling API.
- **Multi-choice QA conformal** (Kumar et al., arXiv 2305.18404,
  <https://arxiv.org/abs/2305.18404>): softmax-score conformal sets tightly track accuracy and
  enable selective classification; **and demonstrates the failure mode that matters for us** —
  calibrating on one MMLU subject and testing on another drops coverage to ~83% against a 90%
  target: exchangeability breaks across distribution shift, so guarantees do NOT survive corpus
  or model changes unrefreshed.
- Threshold-selection machinery with error control: **Learn-then-Test** (Angelopoulos, Bates,
  Candès, Jordan, Lei; arXiv 2110.01052, <https://arxiv.org/abs/2110.01052>; journal version
  AOAS 2025, doi 10.1214/24-aoas1998) reframes risk control as multiple hypothesis testing — pick
  thresholds satisfying a risk bound w.p. ≥ 1−δ; **Conformal Risk Control** (Angelopoulos, Bates,
  Fisch, Lei, Schuster, arXiv 2208.02814, <https://arxiv.org/abs/2208.02814>) extends to any
  monotone loss (e.g., bound expected FNR of abstention).
- Compute cost locally: negligible at inference — quantile/threshold arithmetic once calibrated;
  no extra model. The entire cost is the calibration data (§3.2).

### 1.6 Honest mapping of continuous scores → discrete levels

- Calibration fundamentals: reliability diagrams / ECE and temperature scaling as the trivial
  post-hoc calibrator — Guo, Pleiss, Sun, Weinberger, *On Calibration of Modern Neural Networks*,
  ICML 2017 (<https://arxiv.org/abs/1706.04599>); temperature scaling transfers poorly to
  open-ended generation, which is why §1.4's verbalization-plus-calibration literature exists for
  LLM answers specifically.
- The honest-binning principle the statistics side converges on: a binned level may only claim
  the **empirical error rate measured for that bin on held-out data**, refreshed under drift
  (Guo et al. for the diagram practice; LTT §1.5 for choosing the cut-points with controlled
  risk). Publishing levels without per-bin measured error rates is decoration, not calibration.
- **Production-bucketing survey (who ships bucketed confidence fields, and whether per-level
  error rates are published): INCOMPLETE AT WRITE TIME** — this was the lost third lane's core
  deliverable and was not reconstructed beyond noting that the general expectation in vendor docs
  is score-without-per-level-guarantees; treat any specific vendor claim as UNFETCHED here.
- Local sizing fact that governs everything: NB-B0 instrument #7 — total scored Waymo absence GT
  is **26 items** (gt_wmr 12 + ver84 14 scored after dedup), judged "**INSUFFICIENT alone for
  confidence-surface work**", with §4 stating n=26 cannot fit 5-level calibration
  ([`../eval-reports/2026-08-25-nb-b0-benchmark-audit.md`](../eval-reports/2026-08-25-nb-b0-benchmark-audit.md),
  merge `0646ff0`). B0's own sizing language: **≥100 graded anchors needed for 5-level fitting**
  — i.e., roughly **4× more graded anchors than exist today** before five thresholds can carry
  any measured semantics. Generation-layer anchors are scarcer still: zero multi-sample captures
  and zero support-graded answer–claim pairs exist (NB-B0 §4; D3 census NULL-result context in
  the table above).

## §2 Part 2 — Qwen reasoning lineup through mid-2026 + serving postures on the shared 3090

### 2.1 Lineup census (verified against vendor pages at write time)

| Release | What it is | Key specs | Source |
|---|---|---|---|
| Qwen3 (Apr 2025) | dense 0.6B–32B + MoE 30B-A3B / 235B-A22B, hybrid think/no-think chat-template switch | basis of our local `qwen3:14b` | vLLM parser note + Qwen deploy docs (below) |
| Qwen3-2507 refreshes | split into dedicated **-Instruct** and **-Thinking** weights; older hybrid template retained only pre-2507 | template change is visible in vLLM's qwen3 parser compatibility note | <https://docs.vllm.ai/en/v0.22.1/api/vllm/reasoning/qwen3_reasoning_parser/> |
| Qwen3.5 series (2026) | 397B-A17B, 122B-A10B, 35B-A3B, 27B, 9B, 4B, 2B, 0.8B | Qwen3.5-27B appears on BFCL-V4 mirrors at 0.685 with 262K ctx | <https://llm-stats.com/benchmarks/bfcl-v4>; unsloth guide ("Following the widespread community adoption of the Qwen3.5 and Qwen3.6 series") |
| Qwen3.6 (2026) | intermediate release referenced by unsloth; NVFP4 dynamic quants introduced alongside | not independently pinned beyond unsloth mentions | <https://unsloth.ai/docs/models/qwen3.8> |
| **Qwen3.8** (Aug 2026) | current flagship generation: **Qwen3.8-27B dense VLM**, Qwen3.8-2.4T-A95B MoE, Qwen3.8-Max | see card row below | <https://huggingface.co/unsloth/Qwen3.8-27B-GGUF>; <https://unsloth.ai/docs/models/qwen3.8> |

**Qwen3.8-27B card** (base model `Qwen/Qwen3.8-27B`, Apache-2.0, per unsloth GGUF card metadata):
dense 27B **native vision-language** model; hidden 5120; 64 layers arranged 16×(3×(Gated
DeltaNet→FFN)→1×(Gated Attention→FFN)) — a hybrid linear-attention (Gated DeltaNet, 48 V-heads /
16 QK-heads) + gated-attention stack (24 query / 4 KV heads, head-dim 256); vocab 248,320 padded;
trained with multi-token prediction; **context 262,144 native, YaRN-extensible to 1M**; thinking
ON by default, disable per-request, reasoning depth tunable via `reasoning_effort`, history
reasoning retained via `preserve_thinking`; tool-calling parsing improvements called out for
agentic use (<https://huggingface.co/unsloth/Qwen3.8-27B-GGUF>;
<https://huggingface.co/unsloth/Qwen3.8-27B>). Release timing "Aug 15 2026" and "near-Opus-class
agentic coding" characterizations come from third-party coverage — plausible but **[V] vendor /
secondary-sourced**, not independently verified
(<https://explainx.ai/blog/unsloth-qwen3-8-27b-dynamic-v3-ggufs-august-2026>).

Unsloth GGUF quants (Dynamic V3.0; ">10% better top-1% accuracy at matched size" is a
**self-reported** number, <https://unsloth.ai/docs/basics/dynamic-3.0-ggufs>): file sizes from
the HF card table — **UD-Q4_K_S 15.4 GB, UD-Q4_K_M 16.5 GB**, UD-IQ4_XS 14.3 GB, UD-Q3_K_XL
13.1 GB; unsloth's own hardware table puts 4-bit at "16–19 GB total memory"
(<https://unsloth.ai/docs/models/qwen3.8>).

**Local artifact identity — resolved from the artifacts themselves** (no URL; `ollama show`
on this host, 2026-08-25):

- `hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_S` (16 GB on disk ≈ 15.4 GB card figure) and
  `:UD-Q4_K_M` (17 GB ≈ 16.5 GB) — exactly the card's Dynamic-V3.0 files pulled into Ollama.
- `qwen38:160k` (16 GB) = a Qwen3.8-27B GGUF blob wrapped in a local Modelfile with
  **`num_ctx 163840`** (the "160k" tag) and a template that **pre-fills an empty `<think></think>`
  block** (thinking disabled by default) plus a "Reasoning effort is set to xhigh" system line —
  i.e., the same 27B weights in a non-thinking-default, long-window wrapper.

### 2.2 Thinking-mode and thinking-budget control per serving stack

| Capability | Ollama (ours: v0.31.2) | Ollama (current upstream) | vLLM | llama.cpp |
|---|---|---|---|---|
| Separate reasoning field | ✗ pre-thinking-docs builds return mixed text | ✓ `message.thinking` vs `content` (<https://docs.ollama.com/capabilities/thinking>) | ✓ `--reasoning-parser qwen3` splits `reasoning_content` (<https://docs.vllm.ai/en/latest/features/reasoning_outputs/>) | ✓ `--reasoning-format` |
| Mode toggle per request | `think: true/false` (our ADR-09 usage) | ✓ booleans + `low/medium/high/max` levels (same docs page) | ✓ `chat_template_kwargs {"enable_thinking": false}` per request or server-wide default (<https://docs.vllm.ai/en/latest/features/reasoning_outputs/>; Qwen guide: <https://qwen.readthedocs.io/en/latest/deployment/vllm.html>) | ✓ template kwarg / `--reasoning-budget 0` disables |
| **Thinking-token budget** | **✗ none** — ADR-09's shared-budget limitation stands for our stack | **✗ still absent from releases**: budget is an OPEN proposal (issue [#17561](https://github.com/ollama/ollama/issues/17561)) implemented in PR [#17566](https://github.com/ollama/ollama/pull/17566) (`think: N`, effort levels as fractions, `PARAMETER think_budget`), enforced via llama.cpp's sampler; PR testing references ollama 0.32.6 and states the bundled runtime at 0.32.5 does not honor it — **not shipped at write time** | **✓ today**: `thinking_token_budget` sampling parameter + `--reasoning-config` boundary strings; token count starts at `reasoning_start_str`, forces the end string at budget (same vLLM docs page) | ✓ upstream `--reasoning-budget` exists (that is the sampler Ollama's PR drives — same source) |

Two operational hazards worth carrying forward from those primary sources: Ollama's KV-cache
quantization to q4_0 produced heavy repetition in the PR author's tests while f16/q8_0 stayed
clean (PR #17566 discussion) — relevant if we quantize KV to fit windows; and vLLM's
`enable_thinking` passthrough is documented as not OpenAI-API-compatible (Qwen deployment guide),
so client code must use `chat_template_kwargs`.

### 2.3 Function-calling evidence for an agentic loop

- Official board: BFCL V4, <https://gorilla.cs.berkeley.edu/leaderboard.html> (last updated
  2026-04-12 per the page).
- Mirror rows (third-party aggregators — treated as indicative, not authoritative):
  Qwen3.5-27B scores **0.685** on BFCL-V4 (262K-ctx row),
  <https://llm-stats.com/benchmarks/bfcl-v4>; older-generation Qwen3-14B sits at **34.75%**
  multi-turn FC on BFCL-v3 mirrors (<https://benchmarklist.com/benchmarks/bfcl_v3_multiturn/>).
  **Qwen3.8 does not yet appear on any board we could fetch — UNKNOWN at write time.**
- Reading: 27B-class Qwen shows a large generational jump in public function-calling scores over
  14B-class Qwen3. For THIS system the local model is judge/summarizer/header, not the loop
  driver — the MCP client drives tools — so this matters for the operator's broader
  host-the-loop ambition, not for the served product path.

### 2.4 VRAM arithmetic against OUR card (RTX 3090 24 GB, TEI pair resident)

Ground rules: TEI embedder+reranker pair ≈ 11.1 GB resident → **~13.0 GB free** (stub table,
`nvidia-smi` 2026-08-25). Measured facts from NB-NUMCTX (branch `NB-NUMCTX-fix`, commits
`5a74d7a`, `96dc650`): `qwen3:14b`'s served artifact declares `context_length 40960`;
`num_ctx=16384` was honored to 15,417 true tokens end-to-end through two full audit arms; past
the window Ollama silently left-truncates keeping a window/2 tail (4,098 tokens @8192; 8,194
@16384); real prompt density floor 3.51 chars/token with one pathological 2.12 chars/token
outlier (17,452 true tokens); the whole-window 40960 setting was exercised once within 24 GB
during that run.

KV-cache arithmetic is **estimate-only** (rule-of-thumb bytes/token ≈ 2 × layers × KV-heads ×
head_dim × 2 B; ≈ 320 KB/token fp16 class for a 40-layer/8-KV-head 14B) — flagged because
Ollama empirically served more window than naive fp16-KV headroom suggests, i.e. its allocation/
offload behavior is not fully captured by the rule of thumb. Do not treat the KV column as a
guarantee.

| Posture | Weights | Fits beside TEI (~13 GB free)? | Window reality | Verdict |
|---|---|---|---|---|
| `qwen3-14b-16k` co-resident | 9.3 GB | **yes** (≈3.7 GB slack) | 16384 proven end-to-end incl. truncation guard; 40960 declared but naive-KV-infeasible beside TEI | **adopt** for judge/summarizer/header |
| Qwen3.8-27B UD-Q4_K_S co-resident | 15.4 GB | **no** — 15.4 > 13.0 before any KV | n/a | impossible without stopping TEI |
| Qwen3.8-27B serialized (TEI stopped) | 15.4 GB | n/a (whole card ≈24 GB minus CUDA contexts) | ≈8–9 GB slack → tens-of-k tokens class at fp16 KV; more with q8_0 KV (q4_0 KV has the documented repetition hazard, PR #17566) | pilot in maintenance windows only |
| `qwen38:160k` interactive | 16 GB | **no** | num_ctx 163840 wants ~50 GB fp16 KV by the rule of thumb — massive CPU spill regardless of residency | reject for interactive use |

Serving-stack corollary: vLLM's `gpu_memory_utilization` claims a fraction of TOTAL VRAM, so a
vLLM server cannot share the card gracefully with the TEI pair either — the vLLM thinking-budget
capability (§2.2) is therefore available inside the same stop-TEI maintenance windows, not
alongside retrieval.

## Status

- [x] Stub committed (this commit)
- [ ] §1 Part 1 written
- [ ] §2 Part 2 written
- [ ] §§3–4 recommendations written
- [ ] Sources index complete; report final
