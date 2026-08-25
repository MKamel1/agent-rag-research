# NB-X-F — fusion-shape variants at fixed depth (R0 rank 2)

**Status: IN PROGRESS — stub committed before any measurement (programme constraint 1:
numbered commits, stub first, commit every green step).**

## Mandate

R0 rank 2 ([`2026-08-25-nb-r0-fix-ranking.md`](2026-08-25-nb-r0-fix-ranking.md)): measure
dense-only vs shipped-fused vs w∈{0.8, 1.0} full dual-fixture tables via the landed NB-D4
runner — pure config deltas, nothing flipped live. The finding under test is the eviction
result ([`2026-08-23-waymo-priority-baseline.md`](2026-08-23-waymo-priority-baseline.md) §2):
on the full verified corpus, fused top-10 hits 43/60 vs dense-only 50/60, direction strictly
one-way (5 questions dense-hit/fused-miss, 0 the other way).

**Question (one): does fusion shape still matter once reranking draws from deeper pools?**

## Arms (one variable per run; fixtures reported separately; never averaged)

| arm | effective `hybrid_dense_weight` | mechanism |
|---|---|---|
| A — reference | config's own value (= 0.7, Decision A) | `--sparse-mode fused`, no weight override |
| B — dense-only | 1.0 | `--sparse-mode dense_only` |
| C — w=0.8 | 0.8 | `--dense-weight 0.8` |
| D — w=1.0 | 1.0 | `--dense-weight 1.0` |

Pre-registered schema fact (from reading `rag/config.py` / `contracts/config.py` /
`app/retrieval_eval.py`, read-only): **`sparse_mode` is not a Config field.** It exists only as
an eval CLI ablation whose mapping (`app/retrieval_eval.py::sparse_mode_weight`) pins
`dense_only → hybrid_dense_weight = 1.0`. Arms B and D are therefore the *same effective
configuration by construction*; both are measured anyway as an identity cross-check — if they
disagree beyond run-to-run noise, that is itself a finding about nondeterminism in the path.
The Config schema exposes exactly one fusion knob: `hybrid_dense_weight`.

## Fixed depth

Every arm inherits the shipped depth unchanged: `top_k: 10`, `rerank_depth: 32`
(`Retriever.retrieve` draws `max(k, rerank_pool_size)` = 32 fused-hybrid candidates, reranks
the pool, truncates to 10). Depth variation is NB-X-P's variable (R0 rank 1), deliberately not
touched here. This ticket measures fusion *shape* at that fixed depth.

## Method notes

- All four arms run through `scripts/nb_eval_runner.py` (NB-D4 ruler), which subprocesses
  `python -m app.retrieval_eval` per fixture against `fixtures/eval/gt_wmr.json` +
  `fixtures/eval/waymo_gt_verified.json`, collection `waymo_av_safety` named explicitly
  (programme constraint 8).
- **Config-delta mechanism — no config file is created, copied, or edited.** The runner
  forwards `--sparse-mode` / `--dense-weight`; `app/retrieval_eval.py::main` resolves them via
  `resolve_hybrid_weight` and lands the override with `config.model_copy(update={...})` on the
  in-memory frozen pydantic Config. The live
  `/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml` (gitignored, outside this
  worktree) is opened read-only, so its relative-path resolution (`rag/config.py::
  _resolve_paths`) stays anchored to its own directory — the CONFIG-MECHANICS TRAP in the
  brief cannot bite because no variant config file exists anywhere. Zero temp files to clean up.
- GPU serialization: arms run strictly sequentially (runner runs its two fixture subprocesses
  sequentially per arm).
- Verification before sweeping: one smoke query through the same seam must return
  Waymo-corpus results (non-empty hits against gold ids), not an empty/wrong DB.
- Reproducibility: every number comes from committed JSONs under
  [`data/2026-08-25-nb-xf/`](data/2026-08-25-nb-xf/) produced by the committed runner command
  lines recorded below.

### Commands (filled in as arms complete)

```
# A — pending
# B — pending
# C — pending
# D — pending
```

## Results

Pending — standard dual-fixture tables per arm (answerable R@10/MRR/block-P@1 with exact
denominators; known-absent arm reported separately, never blended).

## Verdict

Pending — does the eviction finding survive at fixed depth? Compared on (i) pool coverage
(answerable paper-level hits, fused vs dense-only, including the five known one-way flip
questions Q-GTA-010/-011/-020/-022/Q-WAYB-002) and (ii) post-rerank tables (MRR, block-P@1).
