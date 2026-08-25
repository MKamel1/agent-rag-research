# NB-X-P — deep-pool production tables (R0 rank 1): the standard dual-fixture table at K ∈ {10, 32, 64}

**Status: IN PROGRESS — stub committed before any measurement (programme constraint 1).**
Ticket NB-X-P, Wave 2 X-series rank 1 per `docs/eval-reports/2026-08-25-nb-r0-fix-ranking.md`.
Branch `NB-X-P-deeppool-tables`. Config untouched: the Waymo corpus's shipped
`hybrid_dense_weight=0.7`, `rerank_depth=32` (operator decision A; nothing overridden);
collection `waymo_av_safety` named explicitly on every Qdrant-touching invocation.

## Question (one)

With the PRODUCTION retrieve→rerank pipeline (shipped BGE reranker, w=0.7 FROZEN), what are the
full standard retrieval numbers when the reranker draws from deeper pools? Run K ∈ {32, 64} plus
the shipped baseline (K=10-equivalent) for reference, BOTH fixtures separately
(`fixtures/eval/gt_wmr.json`, `fixtures/eval/waymo_gt_verified.json`), reporting per fixture:

* answerable-arm R@K / MRR / block-P@1 **with denominators**,
* top-10-restricted metrics computed on each arm's own ordering (the production-relevant reading:
  what does the served top-10 become when drawn from a deeper pool),
* known-absent arm separately (never blended),
* the newcomer effect quantified: how many previously-exposed gold blocks LOSE rank vs the
  K-baseline (and the counterpart gains).

## Pre-registered method (written before any run)

* **Reuse-first:** arms are driven through `scripts/nb_eval_runner.py`'s reuse seam —
  `python -m app.retrieval_eval --ground-truth <f> --config <abs waymo config> --collection
  waymo_av_safety --k <K> --sparse-mode fused --report-path <raw>` — one subprocess per fixture
  per arm, serialized (no concurrent retrieval processes; GPU modest-concurrency rule).
* **Why a thin wrapper exists at all** (`scripts/nb_xp_deeppool_tables.py`, scripts-level only):
  the D4 runner hardcodes one k per invocation and its nb-d4 output stem; X-P needs (a) three
  arms tied into one manifest, (b) X-P-namespaced outputs under
  `docs/eval-reports/data/2026-08-25-nb-xp/`, and (c) the cross-arm newcomer analysis, which no
  landed script computes (`nb_d1_pool_depth.py` tracks only PREC-1's C1/C2 population across
  pools, not full-table deltas vs baseline). The wrapper imports `fixture_argv`,
  `load_and_verify_report`, and `extract_row` from `nb_eval_runner` unchanged and invents no
  scoring logic of its own.
* **Pool mechanics being exercised** (verified in source, rag/retriever.py T-DOC24):
  `retrieve(q, None, K)` fetches `max(K, rerank_depth)` hybrid candidates, reranks the WHOLE
  pool, truncates to K. With `rerank_depth=32`: K=10 → 32-candidate pool (shipped shape);
  K=32 → same 32-candidate pool, untruncated ordering; K=64 → genuinely deeper 64-candidate
  pool where newcomers can first appear.
* **Determinism guard:** D1's probe showed zero jitter across repeated retrievals, so this
  ticket's K=32 arm must reproduce the baseline's top-10 exactly (same pool); any mismatch fails
  the wrapper loudly rather than shipping a phantom movement.
* **Baseline validity check:** the K=10 arm must reproduce the D4 SAMPLE headline numbers
  (gt_wmr R@10 68/70 = 0.9714; ver84 answerable R@10 65/68 = 0.9559) — same deterministic path.
* Both fixtures reported SEPARATELY with denominators; never averaged or compared across
  (PREC-1 §5 conditioning rule).

## Results

*(pending — filled by the numbered commits that follow)*

## Reproduction

*(pending — exact commands once the wrapper lands)*
