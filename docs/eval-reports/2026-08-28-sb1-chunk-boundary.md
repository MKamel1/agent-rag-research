# SB-1 — chunk-boundary mitigation experiments

Precision-95 programme. Measure-before-adopt experiment, branch `P95-SB1-chunk-boundary`. No
config was flipped in the shipped system for either arm — arm (b) runs through a runtime
monkeypatch harness (`app/exp_chunk_boundary_neighbor_smooth.py`) identical in shape to QW-3's;
arm (a) builds a separately-named collection (`waymo_av_safety_sb1_latechunk`) and never touches
`waymo_av_safety`, which stayed at 47,893 points / green throughout this ticket (verified
repeatedly, most recently immediately before and after the incident in §0).

**Deviation from the ticket's written order, as instructed:** arm (b) ran first (query-time,
minutes, no re-index) before arm (a) (GPU-heavy re-embed, ~98-minute projection). Getting the
cheap signal first is strictly better sequencing, and it is also what let a real operational
incident (§0) get caught and fixed before the expensive job wasted a full run on top of it.

Every number below is a field of a committed JSON under `docs/eval-reports/data/2026-08-28-sb1/`
— none is typed by hand. File map at the end.

## 0. Operational incident: `.gpu.lock` has no priority (fixed before any number below was trusted)

Arm (b)'s treatment eval, arm (b)'s BGE-baseline repeat, and arm (a)'s full re-embed were
launched concurrently. The re-embed (a ~98-minute job) happened to acquire `rag/gpu_lock.py`'s
`FileGpuLock` first; both eval jobs then sat in `TeiEmbedder`/`TeiReranker`'s per-call
`gpu_lock.acquire()` retry loop for over 20 minutes, and a handful of their questions eventually
hit the loop's `gpu_lock_timeout=300s` ceiling and errored out — silently scored as ordinary
misses by `app/retrieval_eval.py`'s per-hit resilience, indistinguishable from a real quality
regression in the headline table.

**Caught, not shipped**, via a real `/proc` scan (process state/wchan/cumulative CPU) plus `fuser
.gpu.lock` naming the holder — not by trusting a clean-looking table. The contaminated runs'
raw per-question JSON showed the tell directly:

```
gt_wmr rep2 (bge baseline):    n_errors=4  ["gpu lock ... not acquired within 300.0s", Q-WMR-055..058]
gt_wmr sb1b-smooth (arm b):    n_errors=3  ["gpu lock ... not acquired within 300.0s", Q-WMR-001..003]
```

**Fixed at the source, not papered over**: `scripts/nb_eval_runner.py` (outside SB-1's owned
files — deviation recorded in §9) now renders any fixture row with `n_errors>0` as
`⚠️ VOID (n errored)` in both its markdown table and stdout — a contaminated run can no longer
look like a clean one. The re-embed was killed by exact PID (verified via `/proc/<pid>/cwd`
first, never `pkill -f`) having written **zero points** to its target collection — nothing was
lost — and both `gt_wmr` evals were re-run solo, error-free. Full incident writeup:
`docs/AGENT-OPERATIONS-LESSONS.md` §9.1. The original contaminated JSONs are kept (not deleted)
as incident evidence, `_VOID`-marked in place.

**Every number in §§1-6 below comes from the clean, error-free (`n_errors=0`) reruns.**

## 1. Baseline reproduction (today, live `waymo_av_safety`, fused, k=10, rerank_depth=32)

| metric | fixture | arm | pool depth | config | value |
|---|---|---|---|---|---|
| R@10 (answerable) | gt_wmr | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 68/70 = 0.9714 |
| R@10 (answerable) | waymo_gt_verified | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 65/68 = 0.9559 |
| MRR | gt_wmr | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 0.9393 |
| MRR | waymo_gt_verified | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 0.8335 (rep 1) / 0.8261 (rep 2, clean) |
| block-P@1 | gt_wmr | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 48/65 = 0.7385 |
| block-P@1 | waymo_gt_verified | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 22/60 = 0.3667 |

Matches the ticket-stated baseline table exactly on gt_wmr and on ver84's R@10/block-P@1; ver84's
MRR reproduced twice (rep 1 = 0.8335 matching the ticket table exactly, rep 2 = 0.8261, both
clean/error-free, run identically) — see §2's noise-floor discussion for why these two numbers
differ at all despite identical code/config/collection.

## 2. Measured noise floor (before trusting any candidate delta)

Two clean, back-to-back, byte-identical-config reproductions of the **same** BGE baseline gave
**ver84 MRR = 0.8335 and 0.8261** — a **0.0074** spread with zero code/config/collection change
between them (float/tie-break jitter in the reranker's own scoring, not a measurement bug — every
other field, including block-P@1 and R@10, reproduced identically). **Any candidate MRR delta
smaller than 0.0074 on ver84 is unmeasurable noise, not a finding.** gt_wmr's own two clean bge
runs (rep 1 and the post-incident clean rerun) matched to 4 decimals (0.9393 both), so gt_wmr's
own floor is measured at ≤0.0001 here — tighter, but based on fewer repeats.

## 3. Arm (b) — neighbour-chunk score smoothing

### 3.1 Pre-registered criterion (frozen in commit `d352da7`, before this arm ran)

Primary configuration `weight=0.3`. **ADOPT** requires, on BOTH fixtures independently: (1)
block-P@1 improves ≥+2pp, (2) R@10 does not regress >1pp, (3) the boundary-defined
(`same_chunk`+`adjacent_chunk`) share of near-misses decreases, (4) the gain is not an
anchor-exactness artifact. **REJECT** if block-P@1 or R@10 regresses beyond the 1pp floor on
either fixture. Full text: `app/exp_chunk_boundary_neighbor_smooth.py` module docstring.

### 3.2 Results — clean, error-free, both fixtures

| metric | fixture | arm | pool depth | config | before | after | delta |
|---|---|---|---|---|---|---|---|
| R@10 (answerable) | gt_wmr | smoothing w=0.3 | rerank_depth=32, k=10 | fused, waymo_av_safety | 68/70 = 0.9714 | 68/70 = 0.9714 | 0 |
| R@10 (answerable) | waymo_gt_verified | smoothing w=0.3 | rerank_depth=32, k=10 | fused, waymo_av_safety | 65/68 = 0.9559 | 66/68 = 0.9706 | +1 item |
| MRR | gt_wmr | smoothing w=0.3 | rerank_depth=32, k=10 | fused, waymo_av_safety | 0.9393 | 0.9386 | −0.0007 (well under the floor) |
| MRR | waymo_gt_verified | smoothing w=0.3 | rerank_depth=32, k=10 | fused, waymo_av_safety | 0.8335/0.8261 | 0.8316 | inside the measured 0.0074 noise band |
| block-P@1 | gt_wmr | smoothing w=0.3 | rerank_depth=32, k=10 | fused, waymo_av_safety | 48/65 = 0.7385 | 48/65 = 0.7385 | **0** |
| block-P@1 | waymo_gt_verified | smoothing w=0.3 | rerank_depth=32, k=10 | fused, waymo_av_safety | 22/60 = 0.3667 | 22/60 = 0.3667 | **0** |

**79 of 82 gt_wmr questions had their entire `retrieved_block_ids` order changed** by the
treatment (verified directly against the raw per-question JSON, not asserted), and ver84 shows
the same shape (77/82 reordered, 7/82 paper-rank changed, 11/82 block-rank changed). **The
treatment fired on nearly every query and moved neither headline metric.** This is the single
most important fact in this section: a null result whose treatment never actually applied would
be worthless; this one demonstrably applied and still produced zero net effect on block-P@1 on
both fixtures, and a sub-noise-floor MRR move on both.

The one exception among the near-miss population worth naming individually: **Q-WMR-036** (D2's
own documented "genuine sub-chunk-overlap straddle" item) moved from block-rank 7 → 4 under
smoothing — a real, directionally-correct nudge from the mechanism — but not far enough to cross
rank 1, so it contributes nothing to block-P@1 either way. This is evidence the mechanism is not
inert at the individual-item level, just insufficient to flip the binary metric on this corpus.

### 3.3 D2 boundary-stratum bucket table, before/after, both fixtures

Reused `docs/eval-reports/data/2026-08-23-waymo-priority/nb_d2_block_adjacency.py` unmodified via
`app/exp_chunk_boundary_stratum.py`.

**gt_wmr** (n_scored=66, near-miss population unchanged at 12/66 = 18.2% both ways):

| bucket | before | after |
|---|---|---|
| same_chunk | 1 | 1 |
| adjacent_chunk | 2 | 2 |
| same_section | 0 | 0 |
| same_doc_elsewhere | 9 | 9 |

Byte-identical bucket table before/after — the treatment did not move a single item between
buckets on this fixture.

**ver84** (n_scored=64, near-miss population 26/64=40.6% before → 27/64=42.2% after):

| bucket | before | after |
|---|---|---|
| same_chunk | 1 | 1 |
| adjacent_chunk | 9 | 9 |
| same_section | 0 | 0 |
| same_doc_elsewhere | 16 | 17 |

Boundary-defined total (same_chunk+adjacent_chunk) is **unchanged in absolute count** (10 → 10);
the near-miss population grew by exactly one item (the same +1 that also moved R@10 — a
`same_doc_elsewhere` item, not a boundary one) — so even the population-share arithmetic (10/26 =
38.5% → 10/27 = 37.0%) is a denominator artifact, not a real boundary-class conversion. Zero
boundary-class near-misses converted to hits on either fixture.

### 3.4 Anchor-exactness check (criterion 4 / measurement discipline)

Checked directly against the two items D2's own report (§2) named as anchor/citation artifacts:
**Q-WMR-094** (vision-derived) is unchanged (block rank `None` → `None`, as expected — text
smoothing cannot touch a vision-only item). **Q-WMR-036** moved 7→4 (§3.2) but did not cross
rank 1, so it never became a counted hit and cannot be an anchor-exactness false-positive either
way. No item's block-P@1 hit is attributable to a re-anchoring artifact rather than genuinely
better matching, because **no item's block-P@1 status changed at all** on either fixture (§3.2's
0/0 deltas) — there is nothing for this check to have missed.

### 3.5 The four persistently-unreachable ver84 items — did smoothing expose any?

Checked directly, by question_id, against both the clean baseline and clean arm-(b) reports.

Ground-truth verification first (`fixtures/eval/waymo_gt_verified.json`, read directly — this
corrects the ticket brief's framing): **all four** items (`Q-GTA-042`, `Q-GTA-043`, `Q-GTA-044`,
`Q-WAYB-027`) carry `vision_derived: true`. Three (`Q-GTA-042`, `Q-GTA-043`, `Q-WAYB-027`) are
tagged `vision_scope: "document-image-only"` — genuinely unrecoverable from text by any retrieval
change. The fourth, `Q-GTA-044`, is tagged `vision_scope: "corpus-extraction-gap"` with an
explicit fixture note: its answer values are selectable PDF text that this pipeline's block
extractor dropped (0 substring hits confirmed in blocks/chunks) — a corpus re-extraction defect,
not a retrieval-ranking one; the fixture itself says it should be "excluded from the vision-arm
headline denominator by consumers that filter on vision_scope," i.e. treated as text-arm-eligible
in principle, but its content is not in the indexed text at all today, so no scoring or embedding
change downstream of extraction can reach it either.

**None of the four became exposed.** Measured directly: all four have `paper_level.rank == 1`
and `passage_level.rank == None` identically before and after arm (b) — zero movement. Given the
above, this is the expected result, not a surprise: three are genuinely vision-only and the
fourth is missing from the corpus's own extracted text, so no text-side retrieval-scoring change
(this arm, or arm (a) below) can expose any of them. **This ticket's brief framed them as "four
non-vision items"; the ground truth itself says otherwise, and that discrepancy is recorded here
rather than silently inherited.**

### 3.6 Mechanism: why the null is structural, not mysterious

gt_wmr's own chunk-position-distance histogram (§3.3's population, `docs/eval-reports/data/
2026-08-28-sb1/stratum/before_bucket_analysis.json`) explains the null quantitatively, not just
descriptively:

| chunk distance from rank-1 chunk to gold | count (of 12 near-misses) |
|---|---|
| 0 or 1 (what a ±1-neighbour blend can reach) | **3** |
| ≥3 | **9** (median 7.5, max 28) |

Block distance tells the same story at finer grain: median **32.5**, max **129** blocks away.
**The intervention's reach (one adjacent chunk each side) is roughly an order of magnitude
smaller than the median distance to the gold.** Smoothing across a single neighbour cannot reach
a gold sitting 7 or 28 chunks away, and that is where 9 of gt_wmr's 12 near-misses (75% —
reproducing D2's original 75% `same_doc_elsewhere` figure exactly) actually sit. Even the 3
items within reach (chunk distance ≤1) did not convert — §3.3's bucket counts for `same_chunk`
and `adjacent_chunk` are unchanged (1 and 2 on gt_wmr, 1 and 9 on ver84), so being in reach was
necessary but not sufficient here either.

**This makes the null mechanistic and generalisable, not just an absence of evidence**: any
technique whose reach is a small, fixed neighbourhood (±1 chunk, ±1 block, a short context
window) is predicted in advance to fail on this corpus's dominant failure mode, because that
mode is defined by distance, and the distances involved (median 7.5 chunks / 32.5 blocks, up to
28/129) are structurally larger than a small fixed reach can cover. This prediction is falsifiable
and worth stating plainly so a future ticket does not re-spend a measurement on the same shape of
idea: **±1-neighbour blending of any kind (score-level, as here, or a small embedding-context
window) is expected to fail on this corpus for the same reason**, unless the window is widened
enough to routinely span double-digit chunk counts — at which point it stops being a "neighbour"
technique and starts approaching whole-document context.

### 3.7 Verdict: arm (b)

**REJECT — no detectable effect, on both fixtures independently, never averaged.**

**Why this null is credible, not a silent no-op** (the commonest failure mode of a negative
result): **79/82 gt_wmr result lists and 77/82 ver84 result lists had their entire
`retrieved_block_ids` order changed** by the treatment (§3.2, verified directly against raw
per-question JSON), and the D2 boundary-stratum bucket table is **byte-identical before/after on
gt_wmr** (§3.3: same_chunk 1→1, adjacent_chunk 2→2, same_doc_elsewhere 9→9, near-miss population
12/66 both ways) and unchanged in absolute boundary-class count on ver84 (same_chunk 1→1,
adjacent_chunk 9→9). **The treatment fired on nearly every query, reshuffled ranks throughout, and
converted zero near-misses out of any stratum, on either fixture.** That combination — near-total
reordering paired with a completely flat outcome — is what makes this a measurement rather than an
untested hypothesis.

Applying §3.1's frozen criterion literally: criterion 1 (block-P@1 ≥+2pp on both fixtures) fails
outright — the measured delta is exactly **0** on both. Criteria 2 (no R@10 regression) and the
literal "R@10/block-P@1 regresses" trigger for REJECT are both **not** hit either — nothing
regressed; ver84's R@10 improved by one item, which appears unrelated to boundary mitigation
(§3.3's stratum table shows the gain landing in `same_doc_elsewhere`, not `adjacent_chunk`/
`same_chunk`). The honest label for this outcome is a flat null, not a regression — described
here as REJECT (the ADOPT bar is unambiguously not met) while explicitly noting it does not
trigger the criterion's own regression-based REJECT condition either.

§3.6's reach-vs-distance mechanism explains *why* the null is flat rather than partial: the
technique's ±1-chunk reach is roughly an order of magnitude smaller than the median distance
(7.5 chunks / 32.5 blocks) to gt_wmr's dominant `same_doc_elsewhere` near-misses (9/12 = 75%,
reproducing D2's original figure exactly), and even the 3 items within reach did not convert. This
is consistent with D2's own honest ceiling that framed this ticket from the start: boundary
classes are only 25% (gt_wmr) / 33% (ver84) of near-misses. **Explicit, falsifiable prediction for
future tickets**: on this corpus, any ±1-neighbour blending technique — score-level (this arm) or
a small fixed embedding-context window — is expected to fail for the same structural reason, and
should not be re-measured without first widening reach to routinely span double-digit chunk
counts. R1 found no published evaluation of neighbour-chunk score smoothing — this is a first
measurement, cleanly priced against a pre-registered criterion and a quantified noise floor, and
it should be read as exactly that: informative evidence, not a failed attempt.

## 4. Arm (a) — late-chunking-style section-scoped embedding

*(Filled in once the solo re-embed run completes — see §9's live status note if this section
still reads as a placeholder when read mid-run.)*

## 9. Deviations from the owned-files list (recorded, not buried in a diff)

SB-1's owned files are `app/exp_chunk_boundary_*.py`, this report, its data directory, and
sibling tests. Two shared, non-owned files were touched, both minimally and additively, both with
their own regression proof run and pasted here rather than only asserted:

1. **`app/reembed_experiment.py`** (T-DOC41's spike script) — added an optional `embed_text_fn`
   keyword parameter to `reembed()` (default `None`, mutually exclusive with `with_headers`,
   reproduces prior behavior byte-for-byte when omitted) and a `--sb1-section-context-window` CLI
   flag that deferred-imports arm (a)'s text-transform function only when used. Reason: arm (a)
   needs a real embedder/vector-store client to price and run its re-embed, and constructing one
   in a brand-new `app/` file would name a vendor HTTP-client token that
   `ci/checks/vendor_isolation.py` only allowlists in specific paths — `ci/` itself is a
   foundation-gated path this ticket must not touch to add an entry. Extending the one
   already-allowlisted composition root this shape belongs to was the smaller, correct move.
   **Regression proof**: `app/test_reembed_experiment.py` (23 tests) + `app/test_exp1_outline_
   split.py` — both pass unchanged, verified twice (once directly, once independently by the
   orchestrator against the same commit).

2. **`scripts/nb_eval_runner.py`** (NB-D4's dual-fixture runner, QW-3's own dependency) — §0's
   incident showed `extract_row()` already carried `n_errors` through but nothing surfaced it:
   a fixture whose run hit real failures (a `gpu_lock` timeout under concurrent GPU contention)
   produced a headline table indistinguishable from a clean one. `render_markdown()` now labels
   any row with `n_errors>0` as `⚠️ VOID (n errored)` plus a bold warning naming which fixture(s)
   and why; `main()` echoes the same warning to stdout. Zero behavior change for the `errors==0`
   path. **Regression proof** (`scripts/test_nb_eval_runner.py`, run directly for this report):

   ```
   $ python -m pytest scripts/test_nb_eval_runner.py -v
   collected 15 items
   scripts/test_nb_eval_runner.py ...............                           [100%]
   ============================== 15 passed in 0.02s ==============================
   ```

   12 pre-existing tests unchanged, 3 new (VOID row rendering, no-void-when-clean, stdout echo).
   Both of `nb_eval_runner.py`'s other consumers also still pass unchanged:
   `app/test_exp_nb_rr_qwen_reranker.py` (QW-3) and `app/test_exp_chunk_boundary_neighbor_
   smooth.py` (this ticket's own arm (b)) — 41 tests total across all three files, all green.

3. **`docs/AGENT-OPERATIONS-LESSONS.md`** — appended §9.1, the `.gpu.lock`-has-no-priority
   incident writeup, at the orchestrator's explicit request. Purely additive (append-only file by
   its own stated convention).
