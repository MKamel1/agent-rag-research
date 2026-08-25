# NB-X-P — deep-pool production tables: the standard dual-fixture table at K ∈ {10, 32, 64}

**Status: COMPLETE.** Ticket NB-X-P — X-series rank 1 per
[`docs/eval-reports/2026-08-25-nb-r0-fix-ranking.md`](2026-08-25-nb-r0-fix-ranking.md), Wave 2 of
the next-build programme (`docs/superpowers/plans/2026-08-24-next-build-programme.md` §4).
Branch `NB-X-P-deeppool-tables` (worktree off `main` @ `6b6f67f`). Measurement ticket: **no config
changes** — the Waymo corpus's shipped `hybrid_dense_weight=0.7`, `rerank_depth=32` (operator
decision A) and the shipped BGE reranker ran untouched; collection `waymo_av_safety` named
explicitly on every Qdrant-touching invocation; no reranker/model swaps; read-only on SQLite and
Qdrant; zero errored questions in all six runs. Sweep arms serialized end to end (one retrieval
process at a time).

## Question (one)

With the PRODUCTION retrieve→rerank pipeline (shipped BGE reranker, w=0.7 FROZEN), what are the
full standard retrieval numbers when the reranker draws from deeper pools? K ∈ {32, 64} plus the
shipped baseline (K=10-equivalent), BOTH fixtures separately, with the known-absent arm never
blended and the newcomer effect quantified against baseline.

## Answer in one paragraph

Depth is a **serving-side win and an ordering-side hazard, and the two fixtures split cleanly**.
GT-WMR's top-10 is *depth-invariant* — every top-10-restricted number is byte-identical across
K ∈ {10, 32, 64} because its hybrid pool was already 32 deep at baseline (`max(10, 32)`), so
deepening changes nothing until serving depth itself grows, where answerable R@K saturates at
**70/70 = 1.0000 by K=64**. verified-84 is where the newcomer hazard lives: at K=64 the pool
grows to 64 for the first time, and the reranker's reordering over it **pushes 11 previously
exposed gold blocks deeper (2 out of the top-10 entirely)** while promoting exactly one new gold
block to rank 1 — `Q-WAYB-031`, the same item NB-D1 saw reranked #1 from a 64-deep pool. Net:
block-P@1 *rises* 22→23/60 but restricted R@10 *falls* 65→64/68. Depth alone does not advance
verified-84 toward the ≥0.95 target; it trades paper-level top-10 stability for block-level rank-1
gains, which makes ordering quality (R0's X-O) the binding constraint, exactly as R0 predicted.

## Headline tables

### Serving-depth view — runner-native aggregates at each arm's own k

What an agent asking for k results gets. Rates are `app/retrieval_eval.build_report`'s published
aggregates via `nb_eval_runner.extract_row`, unchanged; denominators exact.

| fixture | K | answerable R@K | MRR@K | block-P@1 (VARM-1 text arm) | n_errors |
|---|---|---|---|---|---|
| gt_wmr | 10 | 68/70 = 0.9714 | 0.9393 | 48/65 = 0.7385 | 0 |
| gt_wmr | 32 | 69/70 = 0.9857 | 0.9402 | 48/65 = 0.7385 | 0 |
| gt_wmr | 64 | **70/70 = 1.0000** | 0.9410 | 48/65 = 0.7385 | 0 |
| waymo_gt_verified | 10 | 65/68 = 0.9559 | 0.8335 | 22/60 = 0.3667 | 0 |
| waymo_gt_verified | 32 | 66/68 = 0.9706 | 0.8348 | 22/60 = 0.3667 | 0 |
| waymo_gt_verified | 64 | 66/68 = 0.9706 | 0.8285 | **23/60 = 0.3833** | 0 |

* GT-WMR's two newly-hit papers arrive deep: `Q-WMR-062` (paper at 15 within the served 32;
  drifts to 29 at K=64) and `Q-WMR-028` (12 at K=64). Both are paper-level only.
* verified-84's MRR@K *drops* from 0.8348 (K=32) to 0.8285 (K=64): the deeper pool's reordering
  pushes gold papers down on net even while recall holds. The hazard is visible in the aggregate,
  not just per-item.
* Known-absent arm (never blended into anything above): GT-WMR n=12, all with a top result,
  top-score median 0.0104 / 0.0104 / 0.0088 across K=10/32/64; verified-84 n=14, all with a top
  result, median 0.0097 / 0.0097 / 0.0092. Medians dip slightly at K=64; distributions still do
  not separate from the answerable arm — consistent with D3's verdict, nothing new claimed here.

### Top-10-restricted view — the production top-10 drawn from each pool depth

The production-relevant reading: each arm's own ordering truncated to its first 10, scored under
the standard rules. This isolates what happens to the served top-10 when it is drawn from a
deeper pool.

| fixture | K | R@10 (answerable) | MRR@10 | block-P@1 (text arm) |
|---|---|---|---|---|
| gt_wmr | 10 | 68/70 = 0.9714 | 0.9393 | 48/65 = 0.7385 |
| gt_wmr | 32 | 68/70 = 0.9714 | 0.9393 | 48/65 = 0.7385 |
| gt_wmr | 64 | 68/70 = 0.9714 | 0.9393 | 48/65 = 0.7385 |
| waymo_gt_verified | 10 | 65/68 = 0.9559 | 0.8335 | 22/60 = 0.3667 |
| waymo_gt_verified | 32 | 65/68 = 0.9559 | 0.8335 | 22/60 = 0.3667 |
| waymo_gt_verified | 64 | **64/68 = 0.9412** | 0.8268 | **23/60 = 0.3833** |

GT-WMR: identical rows are the expected result, not a null measurement — see Pool mechanics.
verified-84 at K=64: −1 answerable paper inside the top-10 (`Q-GTA-022`: 8 → 20), MRR@10 down,
block-P@1 up one. block-P@1 is rank-exactly-1 and therefore identical under either reading; the
+1 comes from the same single event in both tables.

## Newcomer effect vs baseline (the ticket's core question)

All movement below is measured against the same-run K=10 baseline (first arm of the sweep), per
question, on first-hit ranks. Identities travel in
`docs/eval-reports/data/2026-08-25-nb-xp/nb-xp-deeppool-tables.json` (`newcomer.gold_block` /
`newcomer.gold_paper` per arm); counts here are computed by
`scripts/nb_xp_deeppool_tables.py`, so report == script output by construction.

### verified-84 at K=64 — the hazard is real and asymmetric

| direction | count | items (baseline rank → K=64 rank) |
|---|---|---|
| gold blocks LOST rank | **11** | Q-GTA-007 4→10 · Q-GTA-009 3→4 · Q-GTA-010 7→14 · Q-GTA-013 7→8 · Q-GTA-021 3→4 · Q-GTA-022 8→20 · Q-GTA-024 2→3 · Q-GTA-027 2→4 · Q-GTA-030 3→4 · Q-GTA-032 5→6 · Q-WAYB-002 8→10 |
| …of which fell OUT of the top-10 | **2** | Q-GTA-010, Q-GTA-022 |
| gold blocks GAINED into top-10 | **2** | **Q-WAYB-031 → rank 1**, Q-GTA-006 → 5 |
| gold blocks improved (still found, shallower) | 0 | — |

* The single block-P@1 gain is `Q-WAYB-031`'s promotion to rank 1 — non-vision, and precisely
  the item NB-D1 flagged as "absent from the 32-deep pool yet reranked #1 from 64" (D1's
  promotion proof). X-P confirms that mechanism survives the full production scoring path.
* No item that held rank 1 lost it at block level (else block-P@1 could not rise); the losses
  concentrate in ranks 2–8 sliding to 3–20.
* Paper-level movement is a DIFFERENT population from block-level: 8 gold papers lose rank
  (`Q-WAYB-026` 1→2 and `Q-GTA-042` 1→2 among them) while 3 improve (`Q-GTA-006` 6→1,
  `Q-GTA-021` 2→1, `Q-GTA-010` 7→5). A paper can rise to rank 1 while its gold block sinks
  (Q-GTA-021: paper 2→1, block 3→4) or fall in the top-10 while its block leaves it entirely
  (Q-GTA-010: paper 7→5, block 7→14). Any X-O work that optimizes one level must report the
  other as a control.
* Jitter context (below): cross-process noise moves ≤~4% of questions by ±1 adjacent position
  and moved exactly one gold paper rank by ±1 in the duplicate probe. The 11-item, up-to-12-position
  losses above are 1–2 orders of magnitude beyond that envelope — real pool-depth effects, not noise.

### verified-84 at K=32 and GT-WMR everywhere — zero movement

Newcomer table at K=32: **0 lost / 0 gained / 0 improved on both fixtures**; GT-WMR at K=64:
likewise all zeros. Same-pool arms cannot admit newcomers (see Pool mechanics), and GT-WMR's
pool never grows within K ≤ 64 — both confirmed empirically, not assumed.

## Cross-process jitter probe (what "same result" is allowed to mean)

The sweep runs separate processes per arm, so before trusting any cross-K delta the sweep
measured its own process-to-process noise: the K=32 arm was run twice fresh (`jitter/*.runA.json`
vs `raw/*.k32.json`) at identical parameters and compared top-10 orderings via
`scripts/nb_xp_deeppool_tables.py --compare`:

| fixture pair | identical | permutation (same ids, swapped) | structural (id set differs) | gold-rank effect |
|---|---|---|---|---|
| gt_wmr runA↔runB | 79/82 | 3 | **0** | none |
| ver84 runA↔runB | 78/82 | 4 | **0** | one gold PAPER rank 2↔1 (`Q-WAYB-026`); blocks unmoved |

Reading: GPU float-level tie jitter produces adjacent permutations on ~4% of questions and never
changes top-10 membership between duplicates; worst observed metric impact is one question's
paper-MRR term flipping between 1 and ½. Two consequences, both encoded rather than narrated:

1. The sweep's validity gate (`assert_within_jitter`) fails loudly if a same-pool pair diverges
   beyond this envelope (>5% structural or >15% total divergence — mutation scale), so a store
   change mid-sweep cannot silently publish. Every committed arm passed it.
2. Single-position movements in the K=64 tables carry that ±1 caveat; everything concluded above
   involves movements far outside it. One truncation-boundary artifact (`Q-WMR-006`, position-10
   neighbor swap between baseline and one K=32 run) sits inside the same envelope.

## Method notes

* **Reuse-first.** Arms run the D4 runner's reuse seam verbatim: `python -m app.retrieval_eval
  --ground-truth <fixture> --config <abs waymo config> --collection waymo_av_safety --k <K>
  --sparse-mode fused --report-path <raw>`, orchestrated by `scripts/nb_xp_deeppool_tables.py`,
  which imports `fixture_argv`, `load_and_verify_report`, and `extract_row` from
  `scripts/nb_eval_runner.py` unchanged. Nothing new scores anything: every rate above is
  `build_report`'s published aggregate; the wrapper only orchestrates, derives top-10-restricted
  counts from stored per-question rows, classifies newcomer movement, and renders tables. The
  thin wrapper exists because no landed script does multi-arm orchestration with cross-arm
  deltas (NB-D4 pins one k and an nb-d4 output stem; NB-D1 tracks only PREC-1's C1/C2 population
  membership, not per-item rank deltas against a same-run baseline). Unit tests cover the pure
  functions zero-GPU (`scripts/test_nb_xp_deeppool_tables.py`).
* **Pool mechanics (why K=32 must equal K=10).** `Retriever.retrieve(q, None, K)` fetches
  `max(K, rerank_depth)` hybrid candidates, reranks the WHOLE pool, then truncates to K
  (rag/retriever.py T-DOC24). With frozen `rerank_depth=32`: K=10 and K=32 both draw a
  32-candidate pool — identical candidate sets through a deterministic scorer — so their
  orderings differ only by jitter, and only K=64 genuinely deepens the pool. The measured
  zero-movement rows confirm the mechanics.
* **Two readings reported deliberately.** "Standard numbers at depth" is ambiguous between what
  a depth-K served list contains (serving-depth view) and what the production top-10 becomes
  when drawn deeper (restricted view). They answer different questions and can move in opposite
  directions — verified-84's K=64 row does exactly that (+1 block-P@1, −1 R@10) — so both travel
  in every artifact rather than choosing one silently.
* **Honest account of the validity gate's development.** v1 compared per-question ranks across
  arms and fired immediately — wrongly: ranks are truncation-relative, so `None→12` transitions
  ARE the depth effect under measurement (it fired on exactly NB-D1's documented exposure items).
  v2 compared id-sequence prefixes exactly and fired again — legitimately this time, on real
  jitter whose signature (adjacent swaps, preserved membership) the raw diffs exposed. Rather
  than weaken silently, the sweep then MEASURED jitter with the duplicate probe above and v3
  encodes that measured envelope as the tolerance. Both firings are visible in branch history;
  no run's data was published while the gate disagreed with itself.
* **Baseline validity check passed.** The K=10 arm reproduces the committed D4 SAMPLE headlines
  exactly (GT-WMR R@10 68/70 = 0.9714; verified-84 answerable 65/68 = 0.9559) and NB-D1's A-bucket
  counts on VARM-1 denominators (48/65, 22/60) — the deterministic-path prediction, confirmed.
* **Fixture conditioning respected** (PREC-1 §5): separate invocations, separate JSONs, separate
  tables, denominators beside every count; nothing averaged or compared across fixtures. The
  known-absent arm is reported through size/top-result/score-distribution only (BENCH-1), never
  blended into recall.
* **Disagreement register:** none with the briefed method. Two additions beyond its letter, both
  forced by data: the duplicate-run jitter probe (the naive determinism assumption broke on first
  contact with cross-process reality) and the paper-level newcomer breakdown (block-level losses
  alone would have misdescribed what depth does — three papers IMPROVE to rank 1 in the same arm
  where 11 blocks sink).

## Verdict for the programme

* **X-P's decision question:** depth buys served-recall headroom (GT-WMR saturates at 1.0000;
  ver84 +1 paper by K=32) but NOT passage-target progress on verified-84 — its text-arm
  block-P@1 moves 0.3667 → 0.3833 against a 0.95 target, and its top-10 gets *less* stable
  (R@10 0.9559 → 0.9412). Depth alone cannot be adopted as a config flip on this evidence.
* **X-O is now unblocked with its brief:** the binding constraint on verified-84 is reranker
  ordering over larger pools — 11 sinking blocks vs 2 entering ones is a net ordering loss the
  ceiling tables said was available (D1: 53–55/64 achievable at these depths vs 49/64 today).
  Any X-O arm must report BOTH granularities' newcomer tables as controls.
* **Serving-side note for MCP consumers:** asking for k=64 results is recall-monotone at paper
  level on both fixtures (GT-WMR reaches 100%, MRR slightly up; ver84 holds its K=32 gain) — the
  only serving-view cost anywhere is ver84's MRR@K dipping 0.8348 → 0.8285 across K=32 → 64.
  Relevant to `semantic_search` default-k discussions, distinct from any pipeline config change.

## Reproduction

```bash
cd <worktree root> && export PYTHONPATH=$PWD
CFG=/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml   # gitignored, absolute
conda run -n agent-rag-research python scripts/nb_xp_deeppool_tables.py \
  --ks 10 32 64 --reuse-raw
# writes docs/eval-reports/data/2026-08-25-nb-xp/{raw/<fixture>.k<K>.json,
#          nb-xp-deeppool-tables.json,nb-xp-deeppool-tables.md}
```

Arms serialize internally; `--reuse-raw` reuses any raw report that verifies (this is how the
sweep was committed arm-by-arm and how it resumes after a dead dispatch at zero loss). Full
re-spend from scratch: drop `--reuse-raw`. Jitter classification between any two raw reports:

```bash
conda run -n agent-rag-research python scripts/nb_xp_deeppool_tables.py --compare \
  docs/eval-reports/data/2026-08-25-nb-xp/jitter/gt_wmr.k32.runA.json \
  docs/eval-reports/data/2026-08-25-nb-xp/raw/gt_wmr.k32.json
```

Every number in this report is a field of the committed
`docs/eval-reports/data/2026-08-25-nb-xp/nb-xp-deeppool-tables.json` or is printed by the script's
summary. Services were up throughout (~35 min wall clock for all six fixture-arm runs, serialized).

## Blockers

None. No config touched, no foundation paths touched, no re-ingest, no infra improvisation.
Files touched: this report, `docs/eval-reports/data/2026-08-25-nb-xp/**`, and the two scripts-level
files named above. BACKLOG row + PROJECT-STATUS ledger entry ride the landing PR per
AGENT-PROCEDURES §B (kept out of this branch to keep concurrent X-lanes conflict-free, programme
constraint 6).
