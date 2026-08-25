# NB-X-O — ordering quality at depth: can cheap reranker-side levers recover the deep-pool losses?

**Status: COMPLETE.** Ticket NB-X-O (X-series rank 3 per
[`docs/eval-reports/2026-08-25-nb-r0-fix-ranking.md`](2026-08-25-nb-r0-fix-ranking.md)), unblocked by
NB-X-P's data ([`2026-08-25-nb-xp-deeppool-tables.md`](2026-08-25-nb-xp-deeppool-tables.md)). Branch
`NB-X-O-ordering-quality` (worktree off `main` @ `c139f9c`). Measurement ticket: **no model/vendor
swap, no config flip to any live file, no foundation path touched** (`rag/config.py`,
`contracts/`, `fixtures/`, `ci/` untouched; `git diff --stat` against the merge-base shows only
`scripts/nb_xo_*` and this report's data dir). Collection `waymo_av_safety` named explicitly on
every Qdrant-touching invocation; read-only on SQLite/Qdrant; **zero errored questions in all 12
fixture-arm runs** (enforced by a hard gate, not observed in passing). All arms serialized — one
retrieval process alive at a time.

## Question (one)

Can cheap reranker-side levers recover ordering losses at the deep-pool operating point (pool 64,
serve 10 — where X-P realized verified-84's newcomer hazard) WITHOUT a model swap? Tested what the
shipped stack supports, measurement-first: (a) rerank-depth vs serve-depth splits, (b) rank-
agreement blending (reciprocal-rank style), (c) other knobs `rag/reranker.py` / the runner seam
exposes cheaply.

## Answer in one paragraph

**No.** Every cheap lever either fails the cross-fixture held-out rule or moves verified-84's
text-arm block-P@1 by less than the bar, and the levers trade exactly against each other: the only
arm that clears ≥+2 points on verified-84 (pool 16, 24/60 = 0.4000, +3.3 pts) does so by
*truncating* the candidate pool — which drops 8 gold blocks out of the served top-10 entirely,
costs −3 answerable papers of R@10, and costs GT-WMR −3 gold blocks at rank 1 (45/65) — while every
rank-agreement blend α<1 is monotonically *worse* than pure BGE ordering on BOTH fixtures' block-P@1
(the shipped cross-encoder owns block-level ordering: turning it fully off collapses verified-84 to
10/60 = 0.1667). Deeper pools keep degrading verified-84's paper-level top-10 stability
(R@10 65→64→61 across pools 32/64/128). No lever is adopt-candidate; per the pre-registered verdict
rule, **the residual lives upstream (X-H strata / chunk-boundary long tail), not in reranker-side
knobs** — consistent with R0's ceiling statement that even perfect ordering caps verified-84's
text arm at ~0.9333, far above anything these knobs reach but reachable only by upstream work.

## Headline tables — top-10-restricted view (all arms serve k=10)

block-P@1 is the VARM-1 text-arm rate (rank exactly 1); denominators exact; fixtures never averaged
(PREC-1 §5). Because every arm serves k=10, the serving-depth view and the restricted view coincide;
the single reading below is the production operating point. Baseline and the rerank-64 arm are
REUSED NB-X-P committed raw reports (see Method notes — re-running them would measure the same
computation twice).

### waymo_gt_verified (n=82; answerable 68; block-scored text arm n=60; absent arm n=14)

| arm | pool | serve | R@10 | MRR@10 | block-P@1 (text arm) | n_errors |
|---|---|---|---|---|---|---|
| baseline_pool32 *(reused)* | 32 | 10 | 65/68 = 0.9559 | 0.8335 | 22/60 = 0.3667 | 0 |
| r64s10_rerank64 *(reused)* | 64 | 10 | 64/68 = 0.9412 | 0.8268 | 23/60 = 0.3833 | 0 |
| p16 | **16** | 10 | 62/68 = 0.9118 | 0.8487 | **24/60 = 0.4000** | 0 |
| p128 | **128** | 10 | 61/68 = 0.8971 | 0.8095 | 23/60 = 0.3833 | 0 |
| b0.0_at_64 (control: pure hybrid order) | 64 | 10 | 62/68 = 0.9118 | 0.7630 | 10/60 = 0.1667 | 0 |
| b0.3_at_64 | 64 | 10 | 62/68 = 0.9118 | 0.8044 | 15/60 = 0.2500 | 0 |
| b0.5_at_64 | 64 | 10 | 63/68 = 0.9265 | 0.8135 | 16/60 = 0.2667 | 0 |
| b0.7_at_64 | 64 | 10 | 65/68 = 0.9559 | 0.8526 | 23/60 = 0.3833 | 0 |

### gt_wmr (n=82; answerable 70; block-scored text arm n=65; absent arm n=12)

| arm | pool | serve | R@10 | MRR@10 | block-P@1 (text arm) | n_errors |
|---|---|---|---|---|---|---|
| baseline_pool32 *(reused)* | 32 | 10 | 68/70 = 0.9714 | 0.9393 | 48/65 = 0.7385 | 0 |
| r64s10_rerank64 *(reused)* | 64 | 10 | 68/70 = 0.9714 | 0.9393 | 48/65 = 0.7385 | 0 |
| p16 | **16** | 10 | 67/70 = 0.9571 | 0.9214 | **45/65 = 0.6923** | 0 |
| p128 | **128** | 10 | 69/70 = 0.9857 | 0.9421 | 48/65 = 0.7385 | 0 |
| b0.0_at_64 (control) | 64 | 10 | 67/70 = 0.9571 | 0.8444 | 25/65 = 0.3846 | 0 |
| b0.3_at_64 | 64 | 10 | 67/70 = 0.9571 | 0.8580 | 26/65 = 0.4000 | 0 |
| b0.5_at_64 | 64 | 10 | 68/70 = 0.9714 | 0.8940 | 33/65 = 0.5077 | 0 |
| b0.7_at_64 | 64 | 10 | 68/70 = 0.9714 | 0.9060 | 42/65 = 0.6462 | 0 |

The α-response is monotone on both fixtures (verified-84: 10→15→16→23→[23 at α=1]; GT-WMR:
25→26→33→42→[48]); five points span both controls (α=0 run fresh, α=1 identical to the reused
rerank-64 arm by construction and asserted in unit tests). Intermediate α values cannot leave the
convex hull of measured points, so no further α was spent.

## Newcomer effect vs baseline — identities (gold-block first-hit ranks)

Every count below is computed by `scripts/nb_xp_deeppool_tables.newcomer_effect` over stored
per-question rows; full identities (including gold-paper level) travel in
`docs/eval-reports/data/2026-08-25-nb-xo/nb-xo-ordering-sweep.json`. All movement classes are
1–2 orders of magnitude beyond the inherited cross-process jitter envelope (≤~4% adjacent
permutations, membership never changes — X-P's duplicate probe), so none of the following is noise.

### waymo_gt_verified

| arm | lost rank | fell out of top-10 | gained into top-10 | improved |
|---|---|---|---|---|
| r64s10_rerank64 *(reused)* | 11 | 2: Q-GTA-010, Q-GTA-022 | 2: **Q-WAYB-031 → rank 1**, Q-GTA-006 → 5 | 0 |
| p16 | 0 | **8**: Q-GTA-005, -009, -010, -022, -027, Q-WAYB-002, -033, -038 | 1: Q-GTA-011 → 8 | 7, incl. **Q-GTA-012 2→1, Q-GTA-016 2→1, Q-GTA-021 3→1** (all three block-P@1 gains) |
| p128 | 10 | 4: Q-GTA-007, -010, -022, Q-WAYB-002 | 2: Q-WAYB-031 → **still rank 1**, Q-GTA-006 → 7 | 0 |
| b0.7_at_64 | 12 | 3: Q-GTA-010, -022, Q-WAYB-033 | 3: Q-GTA-006 → 7, Q-GTA-011 → 9, **Q-WAYB-031 → only rank 10** | 9 |

Two mechanisms visible by identity, not just aggregate:

* **Pool truncation (p16)** manufactures precision by amputation: the three promoted-to-rank-1 gold
  blocks are real, but eight previously-served gold blocks lose their slot outright — the pool no
  longer contains them (paper R@10 pays −3). The same amputation on GT-WMR drops Q-WMR-010/-059 out
  of its top-10 (−3 block-P@1). This is a recall-for-precision dial, not an ordering improvement.
* **Rank-blending (α<1) demotes the newcomer as designed — and gets nothing back**: at α=0.7 the
  hybrid prior pushes Q-WAYB-031 (pure-BGE rank 1) down to rank 10, exactly the "protect exposed
  gold against newcomers" behavior the ticket hoped for. But the freed slot is filled by another
  non-gold block, net verified-84 block-P@1 is unchanged at 23/60, and on GT-WMR the same prior
  demotes NINE BGE-correct rank-1 gold blocks off rank 1 (Q-WMR-004, -008, -010, -044, -049, -056,
  -058, -059, -077 — each to ranks 2–4; three other items gain rank 1, netting −6). A reciprocal-
  rank prior protects *hybrid-favored* candidates, which correlates with gold only weakly at block
  granularity.

### gt_wmr

| arm | lost rank | fell out of top-10 | gained into top-10 | improved |
|---|---|---|---|---|
| p16 | 1 | 2: Q-WMR-010, Q-WMR-059 | 1: Q-WMR-052 → 6 | 1 |
| p128 | 0 | 0 | 1: Q-WMR-028 → 7 | 0 |
| b0.0_at_64 | 32 | 4 | 1 | 6 |
| b0.3_at_64 | 32 | 2 | 1 | 7 |
| b0.5_at_64 | 26 | 0 | 1 | 7 |
| b0.7_at_64 | 11 | 0 | 1 | 6 |

GT-WMR's depth-invariance (r64/p128 ≡ baseline at block level) reproduces X-P's finding and doubles
as this sweep's negative control: arms that only deepen the pool cannot move GT-WMR's top-10, so its
block-P@1 deltas under p16/blends are attributable to the lever alone.

## Known-absent arm (reported separately — never blended)

Both fixtures' absent arms return a top result on every question in every arm; top-score medians sit
at 0.0074–0.0133 across all arms with distributions still overlapping the answerable arm — consistent
with D3's no-separation verdict, nothing new claimed. Medians per arm are fields of the committed
JSON (`row.known_absent`).

## Method notes

* **Reuse-first — what was reused, named.** The measurement path is the D4 runner's reuse seam
  verbatim: `python -m app.retrieval_eval` subprocesses built by `nb_eval_runner.fixture_argv`,
  guarded by `load_and_verify_report`, row-derived by `extract_row`; cross-arm arithmetic
  (`top10_restricted`, `newcomer_effect`, `ordering_divergence`) imported unchanged from
  `scripts/nb_xp_deeppool_tables.py`. Pool arms change exactly one variable via a generated config
  COPY (`configs/config.rerank{16,128}.yaml`, committed beside the data; the live corpus config is
  never edited — store paths in it are absolute, so copies resolve identically). Blend arms run
  `scripts/nb_xo_blend_arm.py`, which calls `app.retrieval_eval`'s `load_questions`/`run`/
  `build_report` UNMODIFIED behind the Retriever's injected-reranker seam (ARCHITECTURE §M7): the
  shipped TeiReranker still scores every candidate; only the final ordering is merged.
* **"Rerank 64 → serve 10" was reused, not re-spent, and the identity is structural, not assumed.**
  `Retriever.retrieve(q, None, k)` draws `max(k, rerank_depth)` candidates, reranks them all, then
  truncates to k (rag/retriever.py T-DOC24). Any configuration with pool 64 and serve 10 executes
  the identical computation as X-P's K=64 arm truncated to its first 10 — same candidates, same
  scorer, truncation-only difference — so X-P's committed K=64 raw reports ARE that arm. Its
  committed rows reproduce under this sweep's analysis code exactly (65→64/68 R@10, 23/60
  block-P@1, the 11-lost/2-out/2-gained newcomer table), confirmed before any new GPU was spent.
* **Why the blend is rank-scale, not score-scale.** `TeiReranker.rerank()` returns reordered
  candidate objects and discards numeric scores (its frozen contract, DATA-CONTRACTS.md
  "Reranker"); the public seam exposes the cross-encoder as an ORDERING only. The implemented blend
  is reciprocal-rank over the two orderings, `score = α/(rrf_k+bge_rank) + (1−α)/(rrf_k+
  hybrid_rank)`, ties toward hybrid rank — the ticket's own suggested fallback shape. Score-scale
  alternatives need contract/vendor changes: follow-ups, not this ticket.
* **Validity gates ran before publication.** Every fresh report passed `load_and_verify_report`
  PLUS a zero-error gate (an errored question is a missing observation, not a miss) and blend arms
  additionally a provenance gate (`xo_provenance.alpha` must match the arm). Unit tests cover the
  blend math zero-GPU, including both controls (α=1 reproduces pure BGE order; α=0 pure hybrid
  order) and no-fabrication/length-preservation.
* **Jitter accounting.** All comparisons are across processes, so they inherit X-P's measured
  duplicate-run envelope rather than re-measuring it (same services, same day, same pipeline);
  per-arm divergence classification vs the baseline travels in the JSON. Every conclusion above
  involves 8–32-item movements — far outside an envelope whose worst case was ±1 adjacent position
  on ~4% of questions.
* **Disagreement register:** none with the briefed method. Two scope decisions taken unilaterally,
  both conservative: (i) no additional α points between 0.7 and 1.0 — the five-point curve plus
  both-controls argument above makes them unable to change the verdict; (ii) no re-run of the two
  reused arms — the computation-identity argument makes re-spending them a duplicate measurement,
  and their committed rows verify under this sweep's own analysis code.

## Follow-ups (NOT implemented — each fails the ticket's cheapness rule)

1. **Score-scale blending** (min-max/z-scored cross-encoder logits mixed with a rank prior):
   requires widening the frozen `Reranker` contract to return scores (foundation path, T-F7) or
   duplicating vendor HTTP code outside the adapter. Given the rank-scale result (monotone-worse),
   only worth revisiting with a genuinely independent second signal, not the hybrid rank the
   cross-encoder already beats.
2. **Model/vendor swaps** (larger/listwise/LLM reranker): out of scope per ticket; nothing here
   suggests ordering headroom is small — D1's ceiling says up to ~53–55/64 is achievable at these
   depths vs 49/64 today, so a *better ordering model over the same pool* remains the one
   reranker-side direction this ticket could not test cheaply.
3. **Query-side work for the hard/negation strata** → X-H lane (R0 rank 5), untouched here.
4. **Upstream re-chunking** for the boundary long tail (D2: 63–75% of near-misses are
   same_doc_elsewhere) — where R0's ceiling statement says the verified-84 residual actually lives.
5. **Anchor-exactness citation refinement** (R0's X-C): orthogonal to ordering; would convert the
   right-words-served-under-wrong-anchor misses honestly.

## Verdict for the programme

**No cheap lever clears the bar → X-H/upstream is where the residual lives.** Explicitly against
the pre-registered adoption rule: pool 16 moves verified-84 text-arm block-P@1 by +3.3 points
(≥+2 ✓) but is NOT held-out-stable (GT-WMR −4.6 points, verified-84 paper-R@10 −3 papers); every
blend α<1 is worse than the shipped configuration on both fixtures' block-P@1; deeper pools
monotonically degrade verified-84's paper-level top-10 without block-level progress. The shipped
configuration (pool 32, w=0.7, pure BGE ordering) survives as the best known cheap operating point;
verified-84's gap to target is upstream (chunk boundaries, vision slice, query difficulty), exactly
where R0's honest-ceiling statement placed it.

## Reproduction

```bash
cd <worktree root> && export PYTHONPATH=$PWD
CFG=/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml   # gitignored, absolute
conda run -n agent-rag-research python scripts/nb_xo_ordering_sweep.py --reuse-raw
# writes docs/eval-reports/data/2026-08-25-nb-xo/{raw/<fixture>.<arm>.json,
#          configs/config.rerank{16,128}.yaml, nb-xo-ordering-sweep.json, nb-xo-ordering-sweep.md}
conda run -n agent-rag-research python -m pytest scripts/test_nb_xo_ordering.py -q
```

Arms serialize internally; `--reuse-raw` reuses any raw report that verifies (this is how the sweep
was committed arm-by-arm and how it resumes after a dead dispatch at zero loss); `--arms <names>`
runs a subset. Full re-spend from scratch: drop `--reuse-raw`. Services were up throughout; wall
clock ~75 min for the twelve serialized fixture-arm runs.

Files touched by this ticket: this report, `docs/eval-reports/data/2026-08-25-nb-xo/**`, and
`scripts/{nb_xo_blend_arm,nb_xo_ordering_sweep,test_nb_xo_ordering}.py`. BACKLOG row +
PROJECT-STATUS ledger entry ride the landing PR per AGENT-PROCEDURES §B (kept out of this branch to
keep concurrent lanes conflict-free, programme constraint 6).
