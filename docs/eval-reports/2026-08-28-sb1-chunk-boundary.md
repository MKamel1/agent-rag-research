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

### 4.1 Mechanism and honesty corrections to the ticket's own framing

Each chunk's dense embedding text is the chunk's own text plus a bounded word window (100 words,
default) pulled from its position-adjacent siblings (same paper, chunk-id numeric suffix ±1) --
`app/exp_chunk_boundary_latechunk_embed.py::build_section_context_text`. `payload.text` (the
sparse/keyword channel) stays the chunk's own unmodified text throughout, isolating the dense-only
effect (`app/reembed_experiment.py`'s own established discipline, reused unchanged).

**Correction to the ticket brief**: the deployed embedding server's `max_input_length` is
**4096 tokens** (`GET /info` on the live TEI-style embed endpoint, measured directly), not the
32k the ticket text assumed. This did not block the experiment (4096 tokens comfortably covers a
~440-word median chunk plus two 100-word windows, with `auto_truncate` as the safety net for the
long tail), but the claimed headroom was 8x smaller than stated.

### 4.2 Dry-run cost projection vs. actual

Offline count (`price_corpus`, zero-GPU): **1,738 papers, 46,155 chunks, 1,452 multi-chunk
sections** (~3.1% of chunks belong to a section split across multiple chunks — the literal
`same_section`-eligible case). Arm-text word count **24,484,408 vs. baseline 16,959,863 — a
1.444x ratio** (most chunks gain two ~100-word windows; single-chunk-section papers with no
siblings are identical to baseline).

Real timed sample (6 median-sized papers, 126 chunks, real embed+upsert into a throwaway
collection `sb1_latechunk_dryrun_sample`): **16.05s, 0.1274 s/chunk**. Projected full-corpus time:
**46,155 × 0.1274s ≈ 5,878s ≈ 98.0 minutes**.

**Actual** (solo run, no concurrent GPU contention, `docs/AGENT-OPERATIONS-LESSONS.md` §9.1's
fix applied): started 11:02:45, finished 12:24:35 (log mtime; 1,443 `/embed` HTTP calls =
`ceil(46155/32)` exactly) — **81.8 minutes (4,910s), ~17% faster than projected**, plausibly
because the projection's small 126-chunk sample carried more fixed per-invocation overhead
(proportionally) than the full run, and/or the solo run had zero lock contention the sample run
also didn't have.

### 4.3 The confound this arm almost shipped with, and its fix

`app/reembed_experiment.py::reembed()` only ever embeds `kind="chunk"` points -- the freshly
built `waymo_av_safety_sb1_latechunk` collection therefore held **46,155 points, zero
`kind="summary"`** vectors after the re-embed, against the baseline's 46,155 chunk + **1,738**
summary (one per paper). Evaluating against that collection as-is would have changed two
variables at once (the intended chunk-embedding treatment, plus an unintended shrinkage of the
candidate pool for any summary-kind hybrid search) -- exactly the kind of silent confound this
ticket's own measurement discipline exists to catch, and structurally the same shape as the
`n_errors>0` case §0's VOID guard catches.

**Fixed by copying, not re-embedding**: `rag/vector_index.py::copy_kind_into(dest, kind)` (new,
§9) does a server-side-filtered scroll-then-upsert of only `kind="summary"` points, verbatim (no
re-embedding -- summaries are unaffected by this arm's chunk-text treatment, so copying is exact
and costs no GPU time). Real caller: `app/exp_chunk_boundary_latechunk_embed.py
--copy-summaries-into waymo_av_safety_sb1_latechunk` (§9) -- copied exactly 1,738 points.
**Verified both invariants before evaluating**: `waymo_av_safety` unchanged at 47,893/green
throughout (read-only scroll only, confirmed before and after); `waymo_av_safety_sb1_latechunk`
now totals 47,893 (46,155 chunk + 1,738 summary via a direct server-side count-by-kind), matching
the baseline collection's composition exactly.

### 4.4 Results — clean, error-free, both fixtures

| metric | fixture | arm | pool depth | config | before | after | delta |
|---|---|---|---|---|---|---|---|
| R@10 (answerable) | gt_wmr | section-context | rerank_depth=32, k=10 | fused, waymo_av_safety_sb1_latechunk | 68/70 = 0.9714 | 69/70 = 0.9857 | +1 item |
| R@10 (answerable) | waymo_gt_verified | section-context | rerank_depth=32, k=10 | fused, waymo_av_safety_sb1_latechunk | 65/68 = 0.9559 | 64/68 = 0.9412 | **−1 item** |
| MRR | gt_wmr | section-context | rerank_depth=32, k=10 | fused, waymo_av_safety_sb1_latechunk | 0.9393 | 0.9431 | +0.0038 |
| MRR | waymo_gt_verified | section-context | rerank_depth=32, k=10 | fused, waymo_av_safety_sb1_latechunk | 0.8335/0.8261 | 0.8354 | inside/at the edge of the 0.0074 noise band |
| block-P@1 | gt_wmr | section-context | rerank_depth=32, k=10 | fused, waymo_av_safety_sb1_latechunk | 48/65 = 0.7385 | 49/65 = 0.7538 | +1.54pp |
| block-P@1 | waymo_gt_verified | section-context | rerank_depth=32, k=10 | fused, waymo_av_safety_sb1_latechunk | 22/60 = 0.3667 | 24/60 = 0.4000 | +3.33pp |

`n_errors=0` on both fixtures (verified — not assumed).

### 4.5 D2 boundary-stratum bucket table, before/after, both fixtures

| fixture | bucket | before | after |
|---|---|---|---|
| gt_wmr | same_chunk | 1 | 1 |
| gt_wmr | adjacent_chunk | 2 | 2 |
| gt_wmr | same_doc_elsewhere | 9 | 9 |
| ver84 | same_chunk | 1 | 1 |
| ver84 | adjacent_chunk | 9 | 9 |
| ver84 | same_doc_elsewhere | 16 | 16 |

**Boundary-class bucket counts are byte-identical to baseline on both fixtures** — the same
result as arm (b), despite a completely different mechanism (embedding-text context vs.
score-level neighbour blending).

### 4.6 Where the metric movement actually came from (per-item trace, not asserted from the aggregate)

Traced every item whose PREC-1 joint-decomposition bucket (A/C1/C2/D/E) changed between the clean
baseline and arm (a) reports:

**ver84 — the two items that converted to hits**: `Q-GTA-012` (C1→A, block rank 2→1) and
`Q-WAYB-031` (C2→A, block rank absent→1). Checked directly against the "before" bucket analysis's
per-item records: **both are `same_doc_elsewhere`, chunk distances 13 and 20** — neither is a
`same_chunk`/`adjacent_chunk` (boundary-class) item. This is the same conclusion the frozen
bucket table already implies (§4.5's boundary counts are unchanged), now confirmed at the
individual-item level: **zero of arm (a)'s gains are boundary-class conversions.**

**ver84 — where the net R@10 loss came from**: `Q-GTA-011` entered the top-10 (paper rank
None→10, a genuine gain — the identical item that also entered under arm (b), suggesting a
corpus-level "most fragile" item near the R@10=10 threshold rather than anything specific to
either treatment); `Q-GTA-020` (rank 3→None) and `Q-GTA-022` (rank 8→None) both dropped OUT of
the top-10 entirely. Net: +1 −2 = **−1**, matching the observed 65→64.

**gt_wmr — the item that converted to a hit**: `Q-WMR-015` and `Q-WMR-020` both moved D→A (paper
rank 2→1, block rank 2→1 in both cases) — genuine paper-level re-ranking wins, not
within-paper boundary fixes (a D-bucket item, by definition, already had the right answer
retrievable somewhere in the pool; the fix here is which PAPER's chunk sits at rank 1, not where
within one paper's own chunk sequence the gold sits). One item (`Q-WMR-028`) entered the top-10
that hadn't been before (paper rank None→6), a genuine R@10 gain. **Two real costs on this
fixture, both worth naming even though neither flips the headline number as badly as it could
have**: `Q-WMR-035` **lost** a previously-perfect hit (paper rank 1→1 unchanged, but block rank
1→None — the gold passage is no longer found in the pool at all); `Q-WMR-048`'s correct paper
**collapsed from rank 1 to rank 10** (block rank 2→None) — it was already a near-miss before
(C1), so this doesn't move the binary block-P@1 count, but it is a real, large degradation a
binary metric hides.

### 4.7 The four persistently-unreachable ver84 items — checked again

Same check as §3.5, against arm (a)'s clean report. **None exposed** — all four
(`Q-GTA-042`, `Q-GTA-043`, `Q-GTA-044`, `Q-WAYB-027`) have `paper_level.rank == 1` and
`passage_level.rank == None` identically before and after. Expected, for the same reason as arm
(b): three are genuinely vision-only content and the fourth (`Q-GTA-044`) is missing from the
corpus's own extracted block/chunk text (a corpus-extraction defect, confirmed via substring
search — §3.5) — no change to how existing extracted text is embedded, by any mechanism, can
reach text that was never extracted in the first place. **The 57/60=0.95 trigger did not fire
under either arm.**

### 4.8 Verdict: arm (a)

**REJECT for this ticket's actual target (chunk-boundary near-miss mitigation), on both fixtures,
never averaged** — despite arm (a) being the one arm that moved a headline metric at all.

The distinction matters and is the whole point of §4.6's per-item trace: block-P@1 improved on
both fixtures (+1.54pp gt_wmr, +3.33pp ver84 — the latter clears arm (b)'s own pre-registered
+2pp bar), but **every single converted item is `same_doc_elsewhere` or a paper-level (D/E→A)
re-rank, and zero are boundary-class** (§4.5's bucket table is byte-identical to baseline; §4.6
names the two ver84 conversions explicitly and both check out as `same_doc_elsewhere`). A
metric improvement whose gains are provably not where the ticket is aimed is not evidence for
adopting this technique as a *boundary* mitigation, whatever its incidental value elsewhere might
be. This is the section-context analogue of "track anchor-exactness artifacts separately"
(measurement discipline) — the artifact here is "gains from paper-level re-ranking", not
re-anchoring, but the discipline is identical: verify the mechanism before crediting the metric.

Separately, and worth weighing on its own: this is **not a clean win even ignoring
target-alignment** — ver84's R@10 regressed by one item (a real, net change, not noise: two
paper-level exits against one entry), and gt_wmr lost one previously-perfect block-P@1 hit
(`Q-WMR-035`) while gaining two elsewhere. A treatment that reshuffles a broad swath of vectors
(the arm's own word-count ratio, 1.444x, touches most chunks' text, not only the ~3.1% in genuinely
split sections) plausibly produces exactly this shape of result: real but essentially undirected
churn, net-positive on one fixture and net-negative-on-one-metric on the other, with the actual
target (boundary near-misses) completely unmoved on either.

**Convergent finding across both arms, independently**: two structurally different mechanisms —
arm (b)'s score-level ±1-chunk blend and arm (a)'s ±100-word embedding-context window — both
leave the D2 boundary-class bucket counts byte-identical to baseline on both fixtures. Two
independent negative results on the same target, via unrelated mechanisms, is stronger evidence
than either alone that this corpus's `same_chunk`/`adjacent_chunk` near-misses (already a minority
of near-misses per D2's own framing — 25%/33%) are not reachable by a local, bounded-reach
intervention of either kind measured here.

## 9. Deviations from the owned-files list (recorded, not buried in a diff)

SB-1's owned files are `app/exp_chunk_boundary_*.py`, this report, its data directory, and
sibling tests. By the end of this ticket, **four shared, non-owned files were touched** — worth
naming as drift up front, even though each one is individually defensible: an experiment ticket
that ends up patching four pieces of shared infrastructure is a real cost, not a free action, and
a future reader should be able to see that at a glance rather than discover it file-by-file.

| file | change | why this ticket couldn't avoid it |
|---|---|---|
| `app/reembed_experiment.py` | `embed_text_fn` hook + `--section-context-window` flag | needed a real embedder/vector-store client; a new file doing that directly would trip `ci/checks/vendor_isolation.py`'s vendor-token allowlist, and `ci/` is foundation-gated |
| `scripts/nb_eval_runner.py` | `n_errors>0` → VOID row/stdout warning | a real incident (§0) showed a contaminated run rendering identically to a clean one; the fix belongs at the one place every fixture row is rendered |
| `rag/vector_index.py` | `copy_kind_into(dest, kind)` | `qdrant_client` is importable only in this one file (CONVENTIONS.md §1); no other file can copy vectors without it |
| `docs/AGENT-OPERATIONS-LESSONS.md` | appended §9.1 | orchestrator's explicit request; purely additive by that file's own convention |

Each is minimal, additive, and defaults to reproducing prior behavior byte-for-byte when unused.
Regression proof for every one, pasted below rather than only asserted:

1. **`app/reembed_experiment.py`** (T-DOC41's spike script) — added an optional `embed_text_fn`
   keyword parameter to `reembed()` (default `None`, mutually exclusive with `with_headers`,
   reproduces prior behavior byte-for-byte when omitted) and a `--section-context-window` CLI
   flag that deferred-imports arm (a)'s text-transform function only when used. Reason: arm (a)
   needs a real embedder/vector-store client to price and run its re-embed, and constructing one
   in a brand-new `app/` file would name a vendor HTTP-client token that
   `ci/checks/vendor_isolation.py` only allowlists in specific paths — `ci/` itself is a
   foundation-gated path this ticket must not touch to add an entry. Extending the one
   already-allowlisted composition root this shape belongs to was the smaller, correct move.

   **Naming fix applied on review**: the flag was originally `--sb1-section-context-window` —
   baking an ephemeral ticket ID into a shared, general-purpose CLI that predates this ticket and
   will outlive it. Renamed to `--section-context-window`; provenance now lives only in the
   docstring, where it belongs (same reasoning QW-3 hit naming `RrfBlendingReranker` — a
   ticket-scoped name on a piece of durable interface over-claims permanence).

   **Regression proof** (run directly for this report):

   ```
   $ python -m pytest app/test_reembed_experiment.py -v
   collected 17 items
   app/test_reembed_experiment.py .................                         [100%]
   ============================== 17 passed in 0.45s ==============================
   ```

   14 pre-existing tests unchanged + 3 new (`embed_text_fn` override applies while `payload.text`
   stays original; mutual-exclusion with `with_headers` raises `ReembedError`; `None`-default
   reproduces pre-SB-1 behavior byte-for-byte — this coverage was missing until this review pass).
   `app/test_exp1_outline_split.py` (the module's other real consumer) also still passes unchanged
   — 26 tests combined.

2. **`scripts/nb_eval_runner.py`** (NB-D4's dual-fixture runner, QW-3's own dependency) — §0's
   incident showed `extract_row()` already carried `n_errors` through but nothing surfaced it:
   a fixture whose run hit real failures (a `gpu_lock` timeout under concurrent GPU contention)
   produced a headline table indistinguishable from a clean one. `render_markdown()` now labels
   any row with `n_errors>0` as `⚠️ VOID (n errored)` plus a bold warning naming which fixture(s)
   and why; `main()` echoes the same warning to stdout. Zero behavior change for the `errors==0`
   path. **Regression proof** (run directly for this report):

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

3. **`rag/vector_index.py`** — added `copy_kind_into(dest_collection, kind)`: a server-side-
   filtered scroll-then-upsert (same shape as the existing `clone_points_into`, deliberately NOT
   built on top of it — cloning every point would overwrite the destination's own `kind="chunk"`
   points with the source's, destroying arm (a)'s treatment) that copies only points of one
   `kind`, verbatim, no re-embedding. Reason: §4.3's confound — arm (a)'s re-embed only touches
   `kind="chunk"` points, so its destination collection held zero `kind="summary"` vectors, an
   unintended second variable. `qdrant_client` is importable only in this one file
   (CONVENTIONS.md §1), so there is no way to copy the missing vectors without touching it.

   **Reproducibility fix applied on review**: the actual copy was first performed ad hoc from a
   shell one-liner — reproducible in principle (the method was tested) but not from anything
   committed. `app/exp_chunk_boundary_latechunk_embed.py` gained `copy_summary_vectors()` and a
   `--copy-summaries-into DEST_COLLECTION` CLI mode as `copy_kind_into`'s real, committed caller,
   so the confound-fix step is now part of the reproducible tool and anyone repeating arm (a)
   hits it as a documented step, not a trap.

   **Regression proof** (run directly for this report, including a new real-adapter test against
   a live vector-store service):

   ```
   $ python -m pytest rag/test_vector_index.py -q
   ........................................................................ [ 91%]
   .......                                                                  [100%]
   79 passed
   ```

   1 new test (`copy_kind_into` copies only the matching kind and never overwrites an existing
   point at the same id, verified against a live service) + all 78 pre-existing tests unchanged.
   `app/test_exp_chunk_boundary_latechunk_embed.py`'s own new test (`copy_summary_vectors` wiring,
   zero-network, `VectorIndex` faked) also passes — 11 tests in that file total.

4. **`docs/AGENT-OPERATIONS-LESSONS.md`** — appended §9.1, the `.gpu.lock`-has-no-priority
   incident writeup, at the orchestrator's explicit request. Purely additive (append-only file by
   its own stated convention).

## 10. Collections created and their final state

| collection | purpose | points | status | disposition |
|---|---|---|---|---|
| `waymo_av_safety` | live production (baseline for every comparison in this report) | 47,893 | green | **never written to** — read-only (search + one filtered scroll) throughout this ticket, verified before and after every risky step |
| `waymo_av_safety_sb1_latechunk` | arm (a)'s section-context re-embed | 47,893 (46,155 chunk + 1,738 summary) | green | complete, evaluated, kept |
| `sb1_latechunk_dryrun_sample` | arm (a)'s 6-paper timing sample (§4.2) | 126 | green | throwaway, kept (not cleaned up — harmless, small) |

## 11. Overall verdict

**REJECT, both arms, both fixtures, never averaged.** Neither arm converts a boundary-class
(`same_chunk`/`adjacent_chunk`) near-miss to a hit on either fixture — the D2 stratum bucket
counts are byte-identical to baseline in every case measured (§3.3, §4.5), across two
structurally unrelated mechanisms. This is the strongest form of null this ticket could have
produced: not "we didn't find an effect," but "we found real effects (arm (a) moved metrics on
both fixtures; arm (b) reordered 79-82/82 result lists) that are demonstrably not the effect this
ticket set out to find," traced to the individual item on both arms rather than inferred from an
aggregate. The 57/60=0.95 ver84 text-arm trigger did not fire under either arm — verified
directly, all four candidate items unchanged in both cases, and (§3.5) three of the four are
vision-only and the fourth is a corpus-extraction gap, not a retrieval-ranking problem either arm
could have reached regardless.

**Per D2's own honest ceiling, stated at the top of this ticket**: boundary classes were always
only 25% (gt_wmr) / 33% (ver84) of near-misses, with `same_doc_elsewhere` dominating at 75%/63%
at a median distance of 7.5-32.5 chunks/blocks — an order of magnitude beyond either arm's
reach (arm (b)'s explicit ±1-chunk blend; arm (a)'s ±100-word embedding context). **A null result
here was the expected outcome stated in the ticket itself, not a surprise, and this report's job
was to measure it honestly rather than to manufacture a win.** Three real operational incidents
were caught and fixed in the process (§0's `.gpu.lock` starvation, §4.3's missing-summary-vector
confound, and the `n_errors` silent-miscount pattern common to both) — each is now a guarded,
tested, documented case a future ticket in this repo will not need to rediscover.

## File map (every number above traces here)

- `docs/eval-reports/data/2026-08-28-sb1/2026-08-27-nb-d4-dual-fixture-bge-baseline*` — baseline rep 1
- `docs/eval-reports/data/2026-08-28-sb1/2026-08-28-nb-d4-dual-fixture-bge-baseline-rep2*` — baseline rep 2 (gt_wmr VOID, ver84 clean)
- `docs/eval-reports/data/2026-08-28-sb1/2026-08-28-nb-d4-dual-fixture-bge-baseline-rep2-gtwmr-clean/` — clean gt_wmr rerun (baseline)
- `docs/eval-reports/data/2026-08-28-sb1/2026-08-28-nb-d4-dual-fixture-sb1b-smooth*` — arm (b) (gt_wmr VOID, ver84 clean)
- `docs/eval-reports/data/2026-08-28-sb1/2026-08-28-nb-d4-dual-fixture-sb1b-smooth-gtwmr-clean/` — clean gt_wmr rerun (arm b)
- `docs/eval-reports/data/2026-08-28-sb1/2026-08-28-nb-d4-dual-fixture-sb1a-latechunk*` — arm (a), both fixtures, clean
- `docs/eval-reports/data/2026-08-28-sb1/stratum/` — D2 bucket tables, before/after, both arms, both fixtures
- `docs/eval-reports/data/2026-08-28-sb1/all_paper_ids.txt` — full corpus paper-id list driving arm (a)
- `app/exp_chunk_boundary_stratum.py`, `app/test_exp_chunk_boundary_stratum.py` — D2-reuse harness
- `app/exp_chunk_boundary_neighbor_smooth.py`, `app/test_exp_chunk_boundary_neighbor_smooth.py` — arm (b)
- `app/exp_chunk_boundary_latechunk_embed.py`, `app/test_exp_chunk_boundary_latechunk_embed.py` — arm (a)
- `docs/AGENT-OPERATIONS-LESSONS.md` §9.1 — the `.gpu.lock` incident
