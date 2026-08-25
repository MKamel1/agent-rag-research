# NB-X-F — fusion-shape variants at fixed depth (R0 rank 2)

**Status: COMPLETE — measured 2026-08-25** on branch `NB-X-F-fusion-shape` (worktree of
`research-system-rag`). Commits: stub `16a02d8`, arms `8b858a9` / `2416611` / `60be47d` /
`0cb5e30`, analysis + this report `<this>`.

## Mandate

R0 rank 2 ([`2026-08-25-nb-r0-fix-ranking.md`](2026-08-25-nb-r0-fix-ranking.md)): measure
dense-only vs shipped-fused vs w∈{0.8, 1.0} full dual-fixture tables via the landed NB-D4
runner — pure config deltas, nothing flipped live. The finding under test is the eviction
result ([`2026-08-23-waymo-priority-baseline.md`](2026-08-23-waymo-priority-baseline.md) §2):
on the full verified corpus, dense-only beat fused on top-10 coverage (50/60 vs 43 at the
08-23 measurement), direction strictly one-way (5 questions dense-hit/fused-miss, 0 the other).

**Question (one): does fusion shape still matter once reranking draws from deeper pools?**

## Method notes

- **Config-delta mechanism — no config file was created, copied, or edited.** All four arms
  ran through `scripts/nb_eval_runner.py`, which forwards `--sparse-mode` / `--dense-weight`
  to `python -m app.retrieval_eval`; there `resolve_hybrid_weight` lands the override via
  `Config.model_copy(update={"hybrid_dense_weight": ...})` on the in-memory frozen Config.
  The live `/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml` (gitignored,
  outside this worktree) is opened read-only, so `_resolve_paths` anchors db/blob paths to its
  own directory and the brief's CONFIG-MECHANICS TRAP cannot bite — no variant config exists
  anywhere, so there is nothing to clean up. Verified before sweeping: one smoke query through
  the same seam returned Waymo-corpus results (`local:` ids, gold paper at rank 1,
  `hybrid_dense_weight=0.7` stamped in the scoring rule), zero errors.
- **Schema fact (pre-registered in the stub, now proven): `sparse_mode` is NOT a Config
  field.** It exists only as an eval CLI ablation whose mapping
  (`app/retrieval_eval.py::sparse_mode_weight`) pins `dense_only → hybrid_dense_weight = 1.0`.
  The Config schema exposes exactly one fusion knob: `hybrid_dense_weight`. Arms B and D are
  therefore the same configuration by construction, and the runs confirmed it: **all 164
  per-question rows (82 × 2 fixtures) have identical `paper_level`, `passage_level`, and
  `top_score` between B and D**; the only row-level differences are tail-ordering wobble in
  the recorded `retrieved_paper_ids`/`retrieved_block_ids` lists (7 rows), which feed no
  metric. They are reported as one result below, two labels.
- **Fixed depth:** every arm inherited shipped `top_k: 10` and `rerank_depth: 32`
  unchanged (`Retriever.retrieve` draws `max(k, 32)` fused-hybrid candidates, reranks the
  pool, truncates to 10). Depth variation is NB-X-P's variable (R0 rank 1), deliberately not
  touched here.
- **Determinism evidence (why every flip below is real, not noise):** arm A reproduced the
  stored NB-D4 SAMPLE run (same config, earlier today) with **zero** scoring-field diffs
  across all 164 rows — the pipeline is scoring-deterministic across processes. Only
  retrieved-id tail order wobbles between runs.
- **GPU serialization:** arms ran strictly sequentially, one runner invocation at a time;
  collection `waymo_av_safety` named explicitly on every command (programme constraint 8).
- **Fixtures reported separately throughout; nothing averaged** (constraint 10 /
  PREC-1 §5). Known-absent arm reported separately, never blended (BENCH-1). block-P@1 covers
  the VARM-1 text-answerable passage-scored arm (n=65 gt_wmr, n=60 ver84); vision-derived
  items keep their own denominator in the raw JSONs.

### Commands (exact, reproducible)

```
conda activate agent-rag-research   # run from the worktree root

python scripts/nb_eval_runner.py --collection waymo_av_safety --k 10 \
  --date 2026-08-25 --tag nbxf-w070-ref --out-dir docs/eval-reports/data/2026-08-25-nb-xf
  # defaults: --config <live waymo config> --sparse-mode fused  => w=0.7 (arm A)

python scripts/nb_eval_runner.py --collection waymo_av_safety --k 10 \
  --sparse-mode dense_only --date 2026-08-25 --tag nbxf-dense-only \
  --out-dir docs/eval-reports/data/2026-08-25-nb-xf            # arm B (= w=1.0)

python scripts/nb_eval_runner.py --collection waymo_av_safety --k 10 \
  --sparse-mode fused --dense-weight 0.8 --date 2026-08-25 --tag nbxf-w080 \
  --out-dir docs/eval-reports/data/2026-08-25-nb-xf            # arm C

python scripts/nb_eval_runner.py --collection waymo_av_safety --k 10 \
  --sparse-mode fused --dense-weight 1.0 --date 2026-08-25 --tag nbxf-w100 \
  --out-dir docs/eval-reports/data/2026-08-25-nb-xf            # arm D (≡ B)

python scripts/nb_xf_flip_analysis.py   # every paired number below, from the committed JSONs
```

Raw artifacts (committed): `docs/eval-reports/data/2026-08-25-nb-xf/
2026-08-25-nb-d4-dual-fixture-{nbxf-w070-ref,nbxf-dense-only,nbxf-w080,nbxf-w100}/
{gt_wmr,waymo_gt_verified}.json` (verbatim `app/retrieval_eval` reports) + each tag's combined
`.json`/`.md`.

## Results

### Standard tables, both fixtures, all four arms (answerable arm with exact denominators)

| fixture | arm | effective w | R@10 (answerable) | MRR | block-P@1 |
|---|---|---|---|---|---|
| gt_wmr (70 ans.) | A reference | 0.7 (shipped) | **68/70 = 0.9714** | **0.9393** | **48/65 = 0.7385** |
| gt_wmr | C | 0.8 | 67/70 = 0.9571 | 0.9357 | 46/65 = 0.7077 |
| gt_wmr | B = D | 1.0 | 67/70 = 0.9571 | 0.9357 | 46/65 = 0.7077 |
| waymo_gt_verified (68 ans.) | A reference | 0.7 (shipped) | 65/68 = 0.9559 | 0.8335 | 22/60 = 0.3667 |
| waymo_gt_verified | C | 0.8 | 66/68 = 0.9706 | 0.8440 | 22/60 = 0.3667 |
| waymo_gt_verified | B = D | 1.0 | **66/68 = 0.9706** | **0.8476** | **24/60 = 0.4000** |

### Known-absent arm (reported separately — never blended)

All 26 absent queries (12 gt_wmr + 14 ver84) returned a full confident top result in every
arm. Top-score medians rise monotonically with the dense weight (scores are rank-1's own
fused/reranked score, so removing sparse dilution raises them):

| fixture | arm | n | with top result | median | range |
|---|---|---|---|---|---|
| gt_wmr | A w0.7 | 12 | 12 | 0.0104 | [0.0082, 0.0160] |
| gt_wmr | C w0.8 | 12 | 12 | 0.0124 | [0.0096, 0.0160] |
| gt_wmr | B=D w1.0 | 12 | 12 | 0.0144 | [0.0110, 0.0164] |
| ver84 | A w0.7 | 14 | 14 | 0.0097 | [0.0077, 0.0158] |
| ver84 | C w0.8 | 14 | 14 | 0.0117 | [0.0090, 0.0160] |
| ver84 | B=D w1.0 | 14 | 14 | 0.0129 | [0.0109, 0.0164] |

Consistent with D3's census: the distributions still overlap the answerable range in every
arm; no abstention signal appears or disappears with fusion shape.

### Paired flips, fused (w=0.7) vs dense-only (w=1.0) — the eviction arithmetic

**gt_wmr (priority set): dense-only is strictly worse.**
- Hits lost going dense-only: **1** — `Q-WMR-010` (Fact-Lookup, gold `local:0983968f9ec2`):
  rank **1** under fused, **absent from the top-10 entirely** under dense-only. A
  reverse-eviction case: fusion *rescues* this item; dropping sparse *evicts* it.
- Hits gained: 0. Net **−1** (68 → 67).
- Ordering among always-hit: `Q-WMR-052` rank 4 → 1 under dense-only (its gold block reaches
  the top-10 at rank 6 there, unseen at any rank under fused) — dense-only is not uniformly
  worse per-question, but its single loss is catastrophic (rank 1 → gone) where its gain is
  partial.
- block-P@1 48/65 → 46/65: the two rank-1 gold blocks lost are exactly `Q-WMR-010` and
  `Q-WMR-059` (both fall out of the top-10 at block level).

**waymo_gt_verified (full corpus): dense-only is slightly better.**
- Hits gained going dense-only: **1** — `Q-GTA-011` (Method-Comprehension, gold `2508.19425`):
  miss under fused → rank 8 under dense-only. Hits lost: 0. Net **+1** (65 → 66).
- Rank improvements among always-hit: 8 of them (`Q-GTA-001` 2→1, `-006` 6→3, `-007` 4→3,
  `-010` 7→6, `-015` 2→1, `-022` 8→6, `Q-WAYB-002` 8→7) against one regression
  (`Q-WAYB-011` 1→2). Dense ordering is broadly tighter on this fixture.
- block-P@1 22/60 → 24/60 (+2: `Q-GTA-001`, `Q-GTA-019` move to block rank 1; `Q-GTA-005`,
  `Q-GTA-009` lose their blocks out of the top-10 — the churn nets positive here).

**The five historically one-way evicted questions** (baseline §2, all in ver84): four of the
five are top-10 hits under BOTH arms today (`Q-GTA-010` 7→6, `Q-GTA-020` 3→3, `Q-GTA-022`
8→6, `Q-WAYB-002` 8→7); only **`Q-GTA-011`** still needs dense-only to surface (fused miss →
dense rank 8). The mass one-way event did not survive to today's corpus state; a one-item
residue did.

## Verdict

**Does eviction survive depth? Mostly no — and what survives cuts both ways.**

1. **The headline eviction effect is gone at fixed production depth.** At the 08-23
   measurement dense-only led the full corpus by ~7 hits, one-way. Today, same pipeline, same
   fixed depth (pool 32 → rerank → top-10): the gap is **net +1** (66/68 vs 65/68), with 4 of
   the 5 historical evictees now hit under both arms. Whatever combination of corpus changes
   (dedupe, backfills), the w=0.5→0.7 decision, and the deeper-than-naive rerank pool is
   responsible, the specific finding R0 ranked X-F to test no longer holds at magnitude.
2. **Fusion shape still matters at the margin — and not only in dense-only's favor.** The
   priority set shows the first measured *reverse* eviction: `Q-WMR-010` goes from rank 1 to
   completely absent when fusion is dropped, costing gt_wmr a hit AND a block-rank-1. Dense-
   only's gains elsewhere (ver84 +1 recall, +2 block-P@1, better MRR) do not transfer to
   gt_wmr (−1 recall, −2 block-P@1, −0.0036 MRR). Per constraint 10 the fixtures are read
   separately: **no arm dominates both**, which alone settles Decision A's question for now —
   the shipped w=0.7 config stays.
3. **The reranker does not neutralize shape effects at this depth** — ordering metrics move
   measurably between arms — so the shape question must be re-asked IF NB-X-P changes the
   pool depth it draws from (handoff to X-P: re-run arm A vs B at whatever K wins, before
   treating "depth subsumes eviction" as settled).
4. **Schema note for all future tickets:** "sparse_mode" is not a config lever; dense-only ≡
   `hybrid_dense_weight = 1.0` exactly (proven at scoring-field level on all 164 rows). Any
   future mode work is weight work; there is no physically-removed-sparse-arm seam
   (`rrf_fuse` fuses the union — disabled-arm candidates can still occupy slots at score 0,
   `app/retrieval_eval.py` docstring).

### Cross-time caveat (honesty note)

Baseline §2's absolute numbers were measured 2026-08-23 under the then-live w=0.5 config and
a pre-dedupe/backfill corpus state; they are quoted here only as the finding under test, not
as an arm. Every comparison drawn in this report is within-ticket: same day, same corpus
snapshot, same depth, one variable per run.

## Scope boundaries & obligations

- No live config, foundation path, reranker, model, NB-X-P, or NB-A1 file was touched; no
  temp config files exist (CLI-delta method), so there is nothing to clean up. Working tree
  carries only this report, the analysis script, and the arm artifacts under
  `docs/eval-reports/data/2026-08-25-nb-xf/`.
- Owed at PR-landing time (AGENT-PROCEDURES §B, deliberately left to the orchestrator because
  sibling X-tickets own those files concurrently): BACKLOG.md row for NB-X-F and a
  PROJECT-STATUS §3 ledger entry citing these commits.
