# SB-3 — agentic loop prototype v0

Precision-95 programme. Measure-before-adopt experiment, branch `P95-SB3-agentic-loop`, offline
prototype under posture P0. Two independent arms, each with its own frozen falsification/routing
rule (committed *before* any label-bearing run, `app/exp_agentic_loop_v0.py`'s own module
docstring, commit 1: `983566d`) and its own verdict below. Neither arm touches the product
surface — `app/exp_agentic_loop_v0.py` is the only new source file; `git diff main --name-only`
shows only that file, its sibling test, this report, and the data under
`docs/eval-reports/data/2026-08-28-sb3/`.

Every number below is a field of a committed JSON/JSONL dump under
`docs/eval-reports/data/2026-08-28-sb3/` — none is typed by hand. File map at the end.

## 0. Serving posture P0 (asserted + logged on every real run)

```
SERVING POSTURE P0: model=qwen3-14b-16k:latest num_ctx=16384 think=False url=http://localhost:11434
```

Logged verbatim (`log_posture()`) at the start of every `crag-capture`/`route-capture`/
`wa4-capture` invocation; visible in `/tmp/sb3_*.log` from the real runs and reproducible from the
module directly. Every Qdrant-backed call goes through `app.assembly.build_mcp_server(config,
collection="waymo_av_safety")` — collection named explicitly on every invocation below, per
programme constraint 7.

**One deliberate deviation from the ticket's literal HTTP-client wording, stated up front, never
silently:** the module talks to the generation-LLM server over stdlib `urllib` rather than an
injected HTTP-client vendor SDK, and names no vendor (`Ollama`) anywhere in its own text. This
repo's `ci/checks/vendor_isolation.py` requires a same-PR allowlist entry for any new file that
imports `httpx` or writes the literal word `ollama` (`git log` shows every prior adapter —
`app/judge_llm.py`, `app/generation_capture.py`, `rag/summarizer.py`, … — added exactly such an
entry in its own landing commit), and `ci/` is one of this ticket's own foundation-gated paths.
Rather than touch it, this module follows two precedents already living in this repo:
`app/judge_llm.py`'s vendor-generic docstring convention (says "the generation LLM server", never
"Ollama") and `scripts/nb_c2_anchor_probe.py`'s own stdlib-`urllib`-over-vendor-client REST calls.
The request shape, `think:false`, and `num_ctx=16384` are otherwise byte-identical to what an
`httpx`-based adapter would send. This is flagged here so a reader auditing "did this ticket
follow posture P0" can see the one place its literal wording ("via Ollama") was deliberately not
repeated in code, and why.

## 1. Arm (a) — CRAG-style retrieval evaluator: **ADOPT on both fixtures**

**Frozen criterion (commit 1, before any run):** AUROC separating the answerable arm from the
known-absent arm, oriented "answerable scores higher", must be **≥ 0.75 on BOTH** `gt_wmr` and
`waymo_gt_verified` ("ver84") to ADOPT. Label = `absent` iff `Question.gold_paper_ids` is empty
after `app.retrieval_eval.load_questions`' own dedup (NB-C2/NB-D3 convention). No threshold,
prompt wording, or passage count changed after capture started.

**Mechanism:** one local generation-LLM call per question. Real `Retriever.retrieve()` (k=10,
`rerank_depth=32`, `hybrid_dense_weight=0.7` — the live `waymo_av_safety` config) supplies the
top-5 served passages (same `_SERVED_PASSAGES=5` convention as `app/generation_capture.py`'s
`_GENERATION_K`); the LLM is asked to judge sufficiency **pre-generation** — never shown a
generated answer — and return `{"sufficiency": float, "verdict": "sufficient"|"partial"|
"insufficient"}`. This is a genuinely new pre-generation signal, distinct from both NB-C2's
sparse-presence probe (DEAD, AUROC 0.48/0.36) and QW-2's MiniCheck-FT5 post-generation support
score (0.747 vs 0.579 means, heavy overlap) — QW-2's numbers are cited here for contrast only,
never presented as this ticket's own.

### Result (both fixtures reported separately, never averaged — programme constraint 10)

| metric | fixture | arm | pool depth | config | value |
|---|---|---|---|---|---|
| AUROC (answerable > absent) | gt_wmr | CRAG evaluator (qwen3-14b-16k) | k=10, top-5 served | fused, waymo_av_safety | **0.9411** |
| AUROC (answerable > absent) | ver84 | CRAG evaluator (qwen3-14b-16k) | k=10, top-5 served | fused, waymo_av_safety | **0.8025** |
| mean sufficiency, answerable | gt_wmr | ″ | ″ | ″ | 0.951 (n=70) |
| mean sufficiency, absent | gt_wmr | ″ | ″ | ″ | 0.083 (n=12) |
| mean sufficiency, answerable | ver84 | ″ | ″ | ″ | 0.759 (n=68) |
| mean sufficiency, absent | ver84 | ″ | ″ | ″ | 0.200 (n=14) |
| n_errors | gt_wmr | ″ | ″ | ″ | **0/82** |
| n_errors | ver84 | ″ | ″ | ″ | **0/82** |

**Both clear the frozen 0.75 bar.** gt_wmr misses only 4 items into a wrong bucket at the
illustrative cut points (§1.1); ver84 is closer to the bar (0.8025) but still clears it cleanly.
Both captures are clean (`n_errors=0` on both — neither run is VOID). Denominators: gt_wmr 82
(70 answerable / 12 absent, matching NB-C2's own reported partition exactly); ver84 82 (68/14,
also matching NB-C2). Source: `docs/eval-reports/data/2026-08-28-sb3/crag_{gt_wmr,ver84}.jsonl`.

**This is a real, non-trivial finding relative to what came before it.** NB-C2 tried a different
pre-generation signal (lexical anchor coverage) for this exact separation and failed by a wide
margin (0.4824 ver84 / 0.3563 gt_wmr, gt_wmr *inverting*). Routing the same pre-generation
question through an LLM judgment call — rather than a hand-built lexical feature — recovers the
separation NB-C2 couldn't find. The mechanism difference is the likely explanation: an LLM
judging "do these 5 passages, read as prose, answer this question" has access to semantic content
NB-C2's token-presence probe structurally could not use.

### 1.1 Action mapping — illustrative, uncalibrated, reported honestly as such

`sufficiency >= 0.66` → `proceed`; `< 0.33` → `abstain`; otherwise `decompose`. These cut points
are arbitrary tertile splits fixed in commit 1 to exercise the {proceed, decompose, abstain} seam
end-to-end — **no threshold fit, no IN-2-style graded-anchor calibration backs them.** The scores
themselves are strongly bimodal (most land at or near 0.0 or 1.0), so the mapping's practical
effect is close to a step function regardless of exactly where the two cuts sit:

| fixture | answerable → proceed | answerable → decompose | answerable → abstain | absent → proceed | absent → abstain |
|---|---|---|---|---|---|
| gt_wmr (70/12) | 67 | 1 | 2 | 1 | 11 |
| ver84 (68/14) | 51 | 3 | 14 | 3 | 11 |

Two honest failure classes worth naming plainly, not just counting:

- **Answerable items scoring `abstain` are largely explained by retrieval, not evaluator
  failure.** Spot-checked against the same corpus's own retrieval (`route_ver84.jsonl`,
  independently captured for arm (b)): `Q-WAYB-003` has no gold block in the top-10 at all
  (`baseline_passage_rank: null`) — a genuine retrieval miss the evaluator correctly flags as
  insufficient. `Q-GTA-010`'s gold block ranks 7th — inside the retrieved top-10 but *outside*
  the top-5 actually served to the evaluator (`_SERVED_PASSAGES=5`, matching what a real
  generation call would see) — again a correct "insufficient" call given what it was actually
  shown, not a bug. This is evidence the evaluator responds to real context quality rather than
  rubber-stamping every answerable-labeled item.
- **`absent` items scoring `proceed` are the false-alarm mode that matters for an abstain
  action**: gt_wmr `Q-WMR-080` (sufficiency 1.0); ver84 `Q-WAYB-021`, `Q-WAYB-039`, `Q-GTA-035`
  (0.8, 1.0, 1.0). 4 of 26 absent items across both fixtures combined would wrongly proceed under
  this illustrative mapping — the AUROC bar is about ranking quality, not this specific cut's
  operating point, and no false-alarm-rate target was pre-committed for the illustrative mapping
  (only the AUROC bar was frozen). Flagged here rather than left implicit.

**Verdict: ADOPT.** The pre-committed criterion passes on both fixtures with margin. This is a
genuinely usable pre-generation sufficiency signal; the illustrative action mapping is not
calibrated and should not ship as-is (IN-2's graded-anchor gate applies here exactly as it does to
QW-2's score family).

## 2. Arm (b) — IRCoT/Self-Ask decomposition: **REJECT (routed AND global), on both fixtures**

**Frozen routing rule (commit 1):** route to decomposition iff, on the question's own fixture
record, `difficulty == "hard"` OR `dimension in {"multi-paper synthesis", "negation and scope"}`.

**Mechanism:** one local generation-LLM call per (routed, for the "routed" policy; every item,
for measuring "global") question, producing up to 3 self-ask sub-questions; each sub-question
retrieved independently (k=10) and merged (`merge_hits`: union deduped by block id, max score,
truncated to k=10) into one comparable hit list, scored via `app.retrieval_eval.score_question`
identically to the baseline (undecomposed) call.

### 2.1 Routed-vs-global recall/MRR, gt_wmr and ver84 (answerable items only, both n_errors=0)

Three whole-fixture policies over the identical item set — never-decompose, routed (decompose iff
routed, baseline otherwise), global (decompose everyone):

| metric | fixture | arm | pool depth | config | value |
|---|---|---|---|---|---|
| recall@10 | gt_wmr | never-decompose | k=10 | fused, waymo_av_safety | 62/66 = 0.9394 |
| recall@10 | gt_wmr | routed policy | k=10 | fused, waymo_av_safety | 61/66 = 0.9242 |
| recall@10 | gt_wmr | global-decompose | k=10 | fused, waymo_av_safety | 57/66 = 0.8636 |
| MRR | gt_wmr | never-decompose | k=10 | fused, waymo_av_safety | 0.8229 |
| MRR | gt_wmr | routed policy | k=10 | fused, waymo_av_safety | 0.7730 |
| MRR | gt_wmr | global-decompose | k=10 | fused, waymo_av_safety | 0.4575 |
| recall@10 | ver84 | never-decompose | k=10 | fused, waymo_av_safety | 49/64 = 0.7656 |
| recall@10 | ver84 | routed policy | k=10 | fused, waymo_av_safety | 44/64 = 0.6875 |
| recall@10 | ver84 | global-decompose | k=10 | fused, waymo_av_safety | 38/64 = 0.5938 |
| MRR | ver84 | never-decompose | k=10 | fused, waymo_av_safety | 0.4896 |
| MRR | ver84 | routed policy | k=10 | fused, waymo_av_safety | 0.4406 |
| MRR | ver84 | global-decompose | k=10 | fused, waymo_av_safety | 0.2623 |

**Note on denominators:** this is passage-level recall@10/MRR over the answerable items that had
a `gold_block_id` to score against (66/70 gt_wmr, 64/68 ver84) — a different measurement from the
ticket's cited block-P@1 baselines (which use a different denominator convention and metric
definition entirely). The three policies above are paired over the *same* item set, so the
ordering between them is the load-bearing comparison, not the absolute recall level.

**The ordering is consistent and unambiguous on both fixtures: never-decompose > routed >
global.** Decomposition never wins, at any routing granularity, on either fixture, on either
metric. The MRR damage is severe even where recall@10 holds up better — decomposition frequently
still retrieves the gold block somewhere in its merged top-10, just pushed to a worse rank
(`merge_hits`' max-score-per-block union spreads several sub-questions' independently-scored
top-10s together, and the gold block's best sub-question doesn't always rank it near 1).

### 2.2 The routing decision itself — does it at least reduce the damage on the routed stratum?

| stratum | fixture | n | baseline recall@10 | decomposed recall@10 | baseline MRR | decomposed MRR |
|---|---|---|---|---|---|---|
| routed (hard/multi-hop/negation) | gt_wmr | 12 | 11/12 = 0.9167 | 10/12 = 0.8333 | 0.7619 | 0.4876 |
| unrouted | gt_wmr | 54 | 51/54 = 0.9444 | 47/54 = 0.8704 | 0.8364 | 0.4508 |
| routed (hard/multi-hop/negation) | ver84 | 29 | 17/29 = 0.5862 | 12/29 = 0.4138 | 0.3081 | 0.1998 |
| unrouted | ver84 | 35 | 32/35 = 0.9143 | 26/35 = 0.7429 | 0.6401 | 0.3142 |

**Routing does NOT rescue decomposition even on the population it was designed for.** R1 §2.4's
finding was "negative passage-level evidence for decomposition on non-multi-hop data" — the
prediction this ticket's routing rule was built against. What was measured here is a *stronger*
null: decomposition also hurts on the routed (multi-hop/hard/negation) stratum itself, on both
fixtures, on both metrics. The routed policy is less damaging than the global policy only because
it decomposes fewer items (12/66 gt_wmr, 29/64 ver84) — it is a smaller dose of a treatment that
doesn't help the population it targets either, not a treatment that works where routed and
merely over-applies where global. This is worth stating precisely because it changes the
practical recommendation: routing here does not rescue the mechanism, it only limits the
blast radius of a mechanism that doesn't work on this retriever.

### 2.3 Decomposition coverage on W-A4 (the primary, sub-goal-bearing fixture)

31 usable items (28 accepted + 3 accepted_with_correction, 2 rejected excluded per
`adjudication_status`), 31 required sub-goals total (each item's own `supported` sub-parts only —
never the `absent` ones, which have no gold evidence to retrieve by construction). `n_errors=0`.

| metric | fixture | arm | pool depth | config | value |
|---|---|---|---|---|---|
| decomposition_coverage | wa4 (31 items) | baseline (undecomposed top-level question) | k=10 | fused, waymo_av_safety | **0/31 = 0.0** |
| decomposition_coverage | wa4 (31 items) | decomposed (self-ask, merged) | k=10 | fused, waymo_av_safety | **0/31 = 0.0** |

**Verified this is a real measurement, not a bug** (hand-checked two items against the live
retriever directly, `Q-WA4-A-001` and `Q-WA4-A-005`): both times, the correct PAPER is retrieved
at multiple ranks in the top-10 — the retriever is not lost — but the exact required BLOCK is
missed by one or a few adjacent chunks (`Q-WA4-A-005`: required `local:6b9ccd0431f6:b10`, closest
retrieved was `b9`). This is a block-level near-miss consistent with SB-1's own established
chunk-boundary finding (`docs/eval-reports/2026-08-28-sb1-chunk-boundary.md`), not a labelling or
ID-format error, and not specific to decomposition — the SAME near-miss pattern defeats both the
baseline and the decomposed condition identically. Self-ask decomposition does not fix it: the
generated sub-questions retrieve the same neighborhood, not the missing exact block.

**This is the mechanism-level explanation for why W-A4 coverage is flat at 0.0 in both
conditions, not evidence that decomposition is uniquely bad here** — it is evidence that this
retriever's block-level precision on W-A4's compound, mixed-answerable/absent question phrasing
is the binding constraint, and decomposition (at least this Self-Ask implementation) does not
relieve it.

### 2.4 Process metrics, with reachability notes (house rule, lessons §7.2)

- **hops_to_answer** — reachable only for items that actually issued a decomposition
  trajectory (every item in arm (b)-1's capture went through the decomposer, to enable the
  routed/global comparison; W-A4's arm (b)-2 capture likewise decomposed every item). Mean
  sub-questions issued, bounded by `_MAX_SUBQUESTIONS=3`:

  | fixture | mean hops_to_answer | n |
  |---|---|---|
  | gt_wmr | 2.955 | 66 |
  | ver84 | 2.984 | 64 |
  | wa4 | 2.806 | 31 |

  Consistently near the 3-sub-question ceiling on all three — the decomposer almost always uses
  its full budget, which is itself worth noting: a decomposer that always maxes out its allowed
  hop count regardless of question complexity is a plausible contributor to §2.1-2.3's null (more
  independently-scored, independently-noisy sub-question retrievals to merge, not fewer).
- **decomposition_coverage** — defined and reachable only on W-A4 (§2.3); `gt_wmr`/`ver84` carry
  no sub-part structure, so this metric is not computed against them, only the routed-vs-global
  recall comparison is (§2.1-2.2) — exactly the split the module docstring committed to in
  commit 1, before any run.

**Verdict: REJECT, both the routed and the global policy, on both control fixtures AND on the
primary W-A4 fixture.** Decomposition (this Self-Ask implementation, merged by max-score dedup)
does not improve retrieval quality anywhere it was measured, including the multi-hop/hard/
negation stratum it was hypothesized to help. Routing limits the damage relative to a global
policy but does not turn the mechanism positive on the routed population. This corroborates and
sharpens R1 §2.4's prior finding rather than merely repeating it.

## 3. Compliance

- Foundation-gated paths untouched: `contracts/`, `rag/config.py`, `config.example.yaml`,
  `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/` — none edited (§0 explains the one
  deliberate design choice, stdlib `urllib` + vendor-generic prose, made specifically to avoid
  needing a `ci/checks/vendor_isolation.py` edit).
- `git diff main --name-only`: `app/exp_agentic_loop_v0.py`, `app/test_exp_agentic_loop_v0.py`,
  `docs/eval-reports/2026-08-28-sb3-agentic-loop.md`, and the six files under
  `docs/eval-reports/data/2026-08-28-sb3/` — no MCP tool, no `app/assembly.py`/`app/serve.py` edit.
- GPU lock: acquired only around each individual generation-LLM call
  (`gpu_lock.acquire("crag-eval")` / `.acquire("self-ask")`), never across a capture loop; three
  capture processes (arm (b)'s two route-captures + wa4-capture) ran concurrently without
  contention beyond ordinary per-call queueing (verified via `nvidia-smi` showing 99% GPU
  utilization during the concurrent window, and zero timeout errors in any of the three captures).
- Every Qdrant-backed call names `--collection waymo_av_safety` explicitly (CLI flag, default
  value, spelled out on every invocation below).
- `n_errors` reported per run throughout this document; every one of the five real captures
  (`crag_gt_wmr`, `crag_ver84`, `route_gt_wmr`, `route_ver84`, `wa4`) is `n_errors=0` — none is
  VOID.
- `pytest app/test_exp_agentic_loop_v0.py` — 43 tests, zero-GPU, zero-network (fake `post`
  injection for both LLM adapters, `FakeGpuLock`, in-memory fixture JSON).
- `GITHUB_EVENT_PATH=/tmp/fake_push_event.json GITHUB_EVENT_NAME=push python -m
  ci.run_enforcement` → **PASS** (checks (a)-(d), (f)-(h), testpaths; check (e) skipped, no PR
  context on a push event) — verified after every commit in this ticket, most recently after the
  arm (b) data commit.

## 4. Reproduction

```bash
# commit 1: plumbing only, zero GPU/LLM
python -m app.exp_agentic_loop_v0 plumbing

# arm (a): CRAG-style evaluator, both fixtures
python -m app.exp_agentic_loop_v0 crag-capture --fixture gt_wmr \
    --config <waymo data-dir>/config.yaml --collection waymo_av_safety \
    --out-dir docs/eval-reports/data/2026-08-28-sb3
python -m app.exp_agentic_loop_v0 crag-capture --fixture ver84 \
    --config <waymo data-dir>/config.yaml --collection waymo_av_safety \
    --out-dir docs/eval-reports/data/2026-08-28-sb3
python -m app.exp_agentic_loop_v0 crag-analyze --fixture gt_wmr
python -m app.exp_agentic_loop_v0 crag-analyze --fixture ver84

# arm (b)-1: routed-vs-global decomposition, both fixtures
python -m app.exp_agentic_loop_v0 route-capture --fixture gt_wmr \
    --config <waymo data-dir>/config.yaml --collection waymo_av_safety \
    --out-dir docs/eval-reports/data/2026-08-28-sb3
python -m app.exp_agentic_loop_v0 route-capture --fixture ver84 \
    --config <waymo data-dir>/config.yaml --collection waymo_av_safety \
    --out-dir docs/eval-reports/data/2026-08-28-sb3
python -m app.exp_agentic_loop_v0 route-analyze --fixture gt_wmr
python -m app.exp_agentic_loop_v0 route-analyze --fixture ver84

# arm (b)-2: decomposition coverage, W-A4
python -m app.exp_agentic_loop_v0 wa4-capture \
    --config <waymo data-dir>/config.yaml --collection waymo_av_safety \
    --out-dir docs/eval-reports/data/2026-08-28-sb3
python -m app.exp_agentic_loop_v0 wa4-analyze
```

All committed artifacts: `app/exp_agentic_loop_v0.py`, `app/test_exp_agentic_loop_v0.py`, this
report, and `docs/eval-reports/data/2026-08-28-sb3/{crag_gt_wmr,crag_ver84,route_gt_wmr,
route_ver84,wa4}.jsonl`.

## 5. Summary verdicts

| arm | mechanism | verdict |
|---|---|---|
| (a) CRAG-style pre-generation evaluator | LLM sufficiency judgment over top-5 served passages | **ADOPT** — AUROC 0.9411 (gt_wmr) / 0.8025 (ver84), both ≥ the frozen 0.75 bar, both clean (n_errors=0). Action-mapping thresholds are illustrative only and are NOT ready to ship uncalibrated. |
| (b) Self-Ask/IRCoT decomposition, routed | LLM sub-question generation + merged retrieval | **REJECT** (both routed and global policy) — decomposition reduces recall@10/MRR on every measured slice on both control fixtures, INCLUDING the routed (hard/multi-hop/negation) stratum it targets, and produces zero coverage improvement on the primary W-A4 fixture (0.0 in both baseline and decomposed conditions, a genuine block-level near-miss, not a bug). Routing limits damage relative to a global policy; it does not make the mechanism positive. |
