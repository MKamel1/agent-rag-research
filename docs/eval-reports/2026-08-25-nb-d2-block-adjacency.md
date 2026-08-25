# NB-D2 — block adjacency / chunking-artifact analysis (completes PREC-1 §3)

**Read-only analysis.** No retrieval was re-run, no config touched, no GPU, no network. Measured
2026-08-25 on branch `NB-D2-block-adjacency` over the stored per-question records of the frozen
2026-08-23 Waymo-priority baseline (`data/2026-08-23-waymo-priority/*.json`) plus `papers.db`
(opened `file:…?mode=ro`). Ticket: `docs/superpowers/plans/2026-08-24-next-build-programme.md` §4
D2. Script: [`nb_d2_block_adjacency.py`](data/2026-08-23-waymo-priority/nb_d2_block_adjacency.py)
in this directory; every number below reproduces via

```bash
python docs/eval-reports/data/2026-08-23-waymo-priority/nb_d2_block_adjacency.py
```

## 0. Definitions (frozen before use)

**Population ("near-miss"), per fixture:** scored answerable items where the **rank-1 paper is
correct** (`retrieved_paper_ids[0] ∈ gold_paper_ids`) but the **gold block is not at rank 1**
(`passage_level.rank ≠ 1`) — exactly PREC-1 §1's buckets **C1 ∪ C2**. Denominators stated per
fixture; fixtures never averaged (programme constraint 10).

**Reference point:** `B1` = `retrieved_block_ids[0]`, i.e. the **anchor block of the chunk the
retriever returned at rank 1** (eval records store returned chunks' `anchor.block_id`s —
`app/retrieval_eval.py`; `GroundedResult.passage_text` serves that chunk's full text,
DATA-CONTRACTS §M7). `G` = `gold_block_id`.

**Chunk↔block membership:** the Chunker groups *consecutive same-`section_path`* blocks into one
chunk and anchors it at the group's **first** block (DATA-CONTRACTS "Multi-block anchoring rule";
oversized groups split before prose blocks). Therefore, within a paper, sorting chunks by their
anchor's `blocks.idx` partitions the block-index space: block *x* ∈ chunk *i* iff
`anchor_idx[i] ≤ x < anchor_idx[i+1]`. Verified mechanically for every paper touched: anchor
uniqueness, consecutive chunk-id suffixes, member-section consistency (zero violations found), and
raw-SQL spot-checks of every `same_chunk`/`adjacent_chunk` claim quoted below.

**Buckets (mutually exclusive, first match wins):**

| bucket | definition |
|---|---|
| `cross_gold_paper` | doc(G) ≠ doc(B1) — possible only for multi-paper gold sets |
| `same_chunk` | G lies **inside the very chunk returned at rank 1** |
| `adjacent_chunk` | chunk-position distance between chunk(G) and chunk(B1) is exactly 1 |
| `same_section` | same document, equal `blocks.section_path`, neither of the above |
| `same_doc_elsewhere` | same document, everything else |

Block-level adjacency is reported as the raw distribution of `|blocks.idx(G) − blocks.idx(B1)|`
alongside (≤1 never occurs in this population; see §3).

## 1. Results — headline fixtures (PREC-1 §1 configs)

Sanity gate passed first: the script independently recomputes PREC-1 §1's joint decomposition
(A/C1/C2/D/E) from raw records and matches its published counts exactly on all three tabulated
configs (verified-84 dense 24/18/9/11/2, verified-84 fused 23/16/11/7/7, GT-WMR fused
48/11/1/5/1).

### verified-84 × dense_only — n_scored = 64, near-misses = 27 (42.2%)

| bucket | n (/27) | share | gold in top-10 (C1) | gold absent (C2) |
|---|---|---|---|---|
| `cross_gold_paper` | 1 | 3.7% | 0 | 1 |
| `same_chunk` | 1 | 3.7% | 0 | 1 |
| `adjacent_chunk` | 8 | 29.6% | 6 | 2 |
| `same_section` | 0 | 0% | 0 | 0 |
| `same_doc_elsewhere` | **17** | **63.0%** | 12 | 5 |

Boundary-defined misses (`same_chunk` + `adjacent_chunk`): **9/27 = 33.3% of near-misses =
9/64 = 14.1% of all scored items.**

### GT-WMR × fused — n_scored = 66, near-misses = 12 (18.2%)

| bucket | n (/12) | share | gold in top-10 (C1) | gold absent (C2) |
|---|---|---|---|---|
| `cross_gold_paper` | 0 | 0% | 0 | 0 |
| `same_chunk` | 1 | 8.3% | 0 | 1 |
| `adjacent_chunk` | 2 | 16.7% | 2 | 0 |
| `same_section` | 0 | 0% | 0 | 0 |
| `same_doc_elsewhere` | **9** | **75.0%** | 9 | 0 |

Boundary-defined misses: **3/12 = 25.0% of near-misses = 3/66 = 4.5% of all scored items.**

## 2. The sharpest finding: gold content served at rank 1, cited elsewhere

The eval's passage-level hit requires a returned chunk's **anchor to equal `gold_block_id`
exactly**, while the agent receives the **full chunk text**. Two near-misses sit inside that gap —
the retriever served the right words at rank 1 and the metric called them misses:

* **Q-WAYB-027** (verified-84 dense): gold block `2208.12833:b188` is a member of the rank-1
  chunk anchored at `…:b186` (group span 186–190, same section "OVERVIEW AND MAPPING"). Scored
  C2 — "gold absent from top-10" — though its text was physically in the rank-1 passage.
* **Q-WMR-094** (GT-WMR fused): gold block `2312.12675:b66` is the **last block** of the rank-1
  chunk anchored at `…:b63` (span 63–66, section "Table 6"). Same pattern.

A third item (**Q-WMR-036**, GT-WMR) is a genuine sub-chunk-overlap straddle: its gold text
appears verbatim inside the rank-1 chunk's body via the Chunker's documented one-block overlap
while true membership is the preceding (adjacent) chunk — whose own anchor also appears in the
top-10 at rank 7.

These are **anchor/citation artifacts, not retrieval failures**: no reranker can improve them,
and any "cite every block in the served chunk" or block-level scoring change converts them to
hits for free (~1–2 items per fixture here).

## 3. How far away, in raw distance?

| fixture | block dist `\|idx(G)−idx(B1)\|` median (max) | dist ≤ 4 | chunk-position dist median (max) | dist ≤ 1 (chunk) |
|---|---|---|---|---|
| verified-84 dense | 26 (184) | 7/27 | 8.5 (29) | 9/27 incl. same-chunk |
| GT-WMR fused | 32.5 (129) | 1/12 | 7.5 (28) | 4/12 incl. same-chunk |

Full histograms are in
[`nb_d2_block_adjacency_results.json`](data/2026-08-23-waymo-priority/nb_d2_block_adjacency_results.json).
Both fixtures agree on the shape: a small tight cluster within ±1 chunk, then a long tail spread
across the whole document (up to 16–29 chunks away). Block-level adjacency (|Δidx| ≤ 1) never
occurs — when two blocks from different chunks straddle a boundary they still differ by ≥2 in
block index in this population.

`same_section` beyond adjacency is structurally rare by construction: chunks are runs of
consecutive same-section blocks, so same-section neighbours are usually *the same or the adjacent*
chunk (already captured by higher-priority buckets). It measured zero in both populations.

## 4. Appendix — remaining arms (context only; headline configs above govern)

Same code, same definitions:

| arm | scored | near-miss | same_chunk | adjacent_chunk | same_section | elsewhere | cross-gold-paper |
|---|---|---|---|---|---|---|---|
| ver84 × fused | 64 | 27 | 1 | 9 | 0 | 17 | 0 |
| ver84 × sparse_only | 64 | 23 | 0 | 5 | 0 | 18 | 0 |
| gt_wmr × dense_only | 66 | 14 | 1 | 2 | 0 | 11 | 0 |
| gt_wmr × sparse_only | 66 | 14 | 1 | 1 | 0 | 12 | 0 |

Direction is stable across arms: elsewhere-in-document dominates everywhere; boundary classes
stay in the 7–33%-of-near-misses band.

## 5. Method notes

1. **Title-header containment trap.** A first pass flagged three extra "gold text inside the
   rank-1 chunk" items on verified-84. All three were false positives: `_build_chunk` prepends
   `{title}\n{section_path}` to every chunk, so questions whose gold block *is* the paper-title
   block substring-match every chunk of that paper. The containment check now strips the header
   and tests the body only; the three reverted to ordinary `adjacent_chunk`/
   `same_doc_elsewhere` classifications (their bucket assignments were anchor-based and never
   depended on containment).
2. **Membership rule, not text matching,** decides buckets (anchor-partition, §0); text
   containment is evidence only. Every `same_chunk`/`adjacent_chunk` case quoted above was
   re-derived by hand against raw `chunks.anchor_json` rows.
3. **Gate G1** ties this analysis to PREC-1 §1: the script refuses to emit results if its own
   recomputation of the published A/C1/C2/D/E decomposition disagrees. It agreed everywhere.
4. **PREC-1 §1 prose vs table on GT-WMR:** §1's narrative table (n=18) counts all non-rank-1
   items; the joint decomposition's C1+C2 (=12) is the rank-1-paper-correct population this
   ticket asks about. The two reconcile via §1's own footnote (5×D + 1×E). This report uses the
   C1∪C2 definition throughout, as briefed.
5. **Doc obligations:** no `docs/BACKLOG.md` row exists for NB-\* tickets (that queue lives in
   the programme plan's own §4 checkboxes), so closure is recorded there plus a PROJECT-STATUS
   §3 ledger entry, per AGENT-PROCEDURES §B's actual trigger table.

## Verdict

**Boundary effects are a real but secondary failure class — same-chunk-or-adjacent explains
9/27 (33%) of verified-84's near-misses but only 3/12 (25%) of GT-WMR's (≈14% vs ≈5% of all
scored items), elsewhere-in-document dominates both fixtures, so chunk-boundary artifacts are
noise next to ordering/pool-depth failures; their one actionable slice is the 2 items per
headline pair where the gold content was already served under a sibling anchor, which is an
anchoring/citation policy fix, not a ranking one.**

TICKET COMPLETE: NB-D2
