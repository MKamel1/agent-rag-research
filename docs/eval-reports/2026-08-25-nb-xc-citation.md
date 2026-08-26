# NB-XC — citation refinement: exposing member blocks of served chunks (completes NB-D2 §2)

**Status: STUB — definitions frozen below before any measurement was run** (NB-C2/NB-C1
convention: the criterion is committed first, results only afterwards). Measurement instrument:
[`app/exp_nb_xc_member_citation.py`](../../../app/exp_nb_xc_member_citation.py); read-only over
the stored 2026-08-23 Waymo-priority baseline records
(`docs/eval-reports/data/2026-08-23-waymo-priority/*.json`) plus `papers.db` opened `mode=ro`.
No retrieval re-run, no config touch, no GPU, no network.

Evidence being acted on: [NB-D2](2026-08-25-nb-d2-block-adjacency.md) §2 — two headline items
(Q-WAYB-027, Q-WMR-094) had gold text **physically inside the rank-1 served chunk** under a
sibling anchor; callers/callers' users cite only the anchor (`GroundedResult.anchor.block_id`),
so those items are honestly servable today but are cited as misses. Ticket question: exactly
which stored-run items convert if citation granularity is the served chunk's **member blocks**
rather than its anchor alone — and what would it take to expose members to callers without
touching frozen shapes.

## 0. The seam as it exists (investigated before design)

* **Chunker** (`rag/chunker.py::_group_blocks`/`_split_oversized`/`_build_chunk`): groups
  *consecutive same-`section_path`* blocks into one `Chunk`; anchor/`parent_id` pin the group's
  **first** block (DATA-CONTRACTS "Multi-block anchoring rule"). Oversized groups split before
  prose blocks; every sub-chunk after the first prepends the previous sub-chunk's last block as
  an **overlap that changes `text` only** — the overlap block never becomes a member's anchor and,
  per contract wording, is not a member either.
* **Serve payload** (`contracts/vector_index.py::VectorPayload`, `contracts/mcp_server.py`):
  `VectorPayload` carries `paper_id/kind/section_path/text/categories/published/
  embedding_version/doc_type/author_orgs/curated_author_orgs` — **no member-block ids**.
  `GroundedResult` serves `passage_text` (= full `Chunk.text`) + one `Anchor`. DATA-CONTRACTS
  explicitly defers per-member provenance: *"storing one bbox per constituent block is out of
  scope for V0 … do not build a multi-bbox `Anchor` in V0."*
* **Read path already exposes everything needed to *compute* membership**:
  `rag/document_store.py` has `get_blocks(paper_id)` / `get_block(block_id)` /
  `get_chunk(chunk_id)` / `get_span(anchor)`; chunks carry `anchor_json`. Membership is derived,
  never stored: within a paper, sorting chunks by their anchor block's `blocks.idx` partitions
  block-index space — block *x* ∈ chunk *i* iff `anchor_idx[i] ≤ x < anchor_idx[i+1]`
  (NB-D2 §0, mechanically verified there for every paper touched).

## 1. Frozen definitions (pre-committed, before measurement)

**Population:** all scored answerable items (`passage_level.scored`) of each fixture×mode config
of the stored 2026-08-23 baseline. Headline configs = PREC-1 §1's pair (verified-84 × dense_only,
GT-WMR × fused); remaining arms computed by the same code as appendix context. Fixtures never
averaged.

**Baseline hit (eval semantics, unchanged):** `gold_block_id ∈ retrieved_block_ids` (exact string
match over the top-k anchors), rank = first matching position.

**Member hit:** ∃ position *j* with anchor A = `retrieved_block_ids[j]` such that
`paper(A) == paper(G)` (**string prefix identity** — see dual-id rule below) and G's
`blocks.idx` lies in A's chunk span `[anchor_idx(A), next_anchor_idx(A))` in that paper's
anchor-partition (last chunk's span closes at `max(blocks.idx)`).

**Dual-id rule (conservative):** the stored records interleave each physical chunk under two
ingest identities (e.g. `2208.12833:b186` canonical and `local:94bdd3d09df1:b186` drop-in twin).
Membership is asserted **only within one paper-prefix**: a gold block under `2208.12833` is never
claimed as a member of a chunk anchored under `local:…`, or vice versa — cross-identity text
equality is assumed nowhere. Serving position reported is the first qualifying *j*.

**Converts :=** `scored ∧ ¬baseline_hit ∧ member_hit`. Monotonicity makes this safe: every
anchor is a member of its own chunk, so the hit set can only grow — no previously-hitting item
can convert into a miss under a member-citation metric.

**Reported slices:** (a) conversions with G ∈ members(**rank-1** chunk) — the NB-D2 §2 claim;
(b) all conversions (G ∈ members(anywhere in top-k)); old vs new passage hit-rate per config;
explicit status lines for Q-WAYB-027, Q-WMR-094, and the overlap-straddle item Q-WMR-036 (whose
rank-1 overlap presence must NOT count: the contract says the overlap block is not a member —
its own chunk's anchor sits in the top-10 anyway, so it stays a C1 hit under both criteria).

**Sanity gates (instrument refuses to emit if any fail):**
* **G1 record fidelity:** recomputing baseline hit/rank from raw `retrieved_block_ids` strings
  reproduces stored `passage_level.hit/rank` for every scored item.
* **G2 resolvability:** every referenced block id resolves in `papers.db`; every referenced
  chunk anchor resolves.
* **G3 geometry validity:** per paper — unique anchors, consecutive chunk-id suffixes,
  member-section consistency checked and reported (same posture as NB-D2: violations are printed,
  not silently swallowed).
* **G4 monotonicity:** baseline hit ⇒ member hit, for every scored item.

## 2. Results

Instrument: `python -m app.exp_nb_xc_member_citation` — all gates G1–G4 passed on every arm
(no output suppressed); machine copy:
[nb_xc_member_citation_results.json](data/2026-08-23-waymo-priority/nb_xc_member_citation_results.json).
Serving positions below are 1-based ranks into the stored top-10.

### Headline configs

**verified-84 × dense_only — n_scored=64: baseline hits 50 (78.1%) → member hits 54 (84.4%). Four conversions, one of them at rank 1:**

| item | bucket | gold block | inside served chunk | rank | chunk span |
|---|---|---|---|---|---|
| Q-WAYB-027 | C2 | `2208.12833:b188` | anchored `…:b186` | **1** | 186–190 |
| Q-GTA-044 | C2 | `2104.10133:b66` | anchored `…:b64` | 2 | 64–66 |
| Q-GTA-043 | C2 | `2506.08228:b75` | anchored `…:b74` | 3 | 74–79 |
| Q-GTA-042 | C2 | `2508.19425:b88` | anchored `…:b85` | 5 | 85–88 |

**GT-WMR × fused — n_scored=66: baseline hits 62 (93.9%) → member hits 63 (95.5%). One conversion, at rank 1:** Q-WMR-094 [C2], gold `2312.12675:b66`, last block of the rank-1 chunk anchored `…:b63` (span 63–66).

Watch-item honesty checks (pre-committed in §1): both NB-D2 §2 items reproduce as rank-1
conversions; **Q-WMR-036 does NOT convert** — its overlap-block presence inside the rank-1 text
is not membership (contract), and it remains a C1 hit at rank 7 through its own chunk's anchor.

### What NB-D2 could not see

NB-D2 measured membership against B1 (rank-1) only; its "~1–2 per fixture" claim holds exactly
for that slice (1 + 1). Widening to any served chunk in the top-10 surfaces three more ver84
conversions (Q-GTA-042/043/044) — all C2 items whose gold block rode inside a *non-rank-1*
served chunk as a non-anchor member. Consequence for PREC-1 §1's decomposition: on ver84 dense,
C2 ("gold absent from top-10") drops 9 → 5 — nearly half that bucket was gold-served-but-
anchor-cited; on GT-WMR fused, C2 goes 1 → 0, i.e. **the entire bucket was a citation artifact**.
Appendix arms: ver84×fused 43→47 (same four items, Q-GTA-042 decomposing D there);
gt_wmr×dense 61→62 and gt_wmr×sparse 36→37 (always Q-WMR-094); ver84×sparse converts nothing
(the chunks carrying those golds never surface under sparse retrieval — no inflation there).

Every quoted case was re-derived by raw SQL against `chunks.anchor_json` (membership span +
member-section match, all five OK), mirroring NB-D2 §5's method note 2. G3 found zero
member-section violations across all papers touched. The dual-id rule never had to be relaxed:
every conversion qualified within one identity (`local:` twins vouched for nothing).

### What member-block citation does NOT do

Monotone by construction (G4): no baseline hit can become a miss, so this is pure metric/citation
honesty — zero ranking change. It does not touch `adjacent_chunk`/`same_doc_elsewhere` items
(NB-D2 §3's long tail), and it cannot help arms where the carrier chunk isn't retrieved at all.

## 3. Design note: how callers could receive member blocks

*(design-note-only per ticket instruction — every caller-facing route crosses foundation-
protected paths or a contract-reserved act; implementation stops here)*

**What exists today.** The store side already has everything: chunks persist `anchor_json`
(`rag/document_store.py::get_chunk/get_blocks/get_span`), membership is derivable via the
anchor-partition rule, and `get_section(paper_id, section_path)` already returns `list[Block]`
over MCP. Nothing is *stored* about membership — by contract design (DATA-CONTRACTS: multi-bbox
anchors explicitly out of scope for V0). The gap is purely at the serve surface:
`VectorPayload` carries no member ids, `GroundedResult` carries one `Anchor`, and the MCP tool
enumeration has no refinement call.

**Variant A — derive at query time into `GroundedResult.metadata` (recommended if members should ride along).**
Retriever computes `members(anchor.block_id)` from the DocumentStore (partition rule, ~20 lines)
and populates the existing forward-compat slot: `metadata={"member_block_ids": [...]}`.
Touches: `rag/retriever.py` (not protected) + DATA-CONTRACTS §M7 prose. No migration, no
re-index, works retroactively over every stored corpus. **Why still sign-off-gated:** not a
`contracts/*.py` edit, but `GroundedResult.metadata`'s own contract docstring reserves populating
it for the T-F7 foundation protocol ("a contracts/ shape change, not a free write") — so this is
a contract-reserved act, and per ticket instruction we stop here.
Diff sketch: DATA-CONTRACTS §M7 gains one paragraph defining `metadata["member_block_ids"]`
(ordered block ids of the matched chunk, anchor first; overlap blocks excluded).

**Variant B — explicit field.** `member_block_ids: list[str] = []` on `GroundedResult`
(`contracts/retriever.py`) fed from an optional new `VectorPayload` key with the legacy-key
convention. Most discoverable, largest frozen diff, and requires re-upserting points (payload
change) to serve from the index path rather than deriving read-only — rejected as less minimal.

**Variant C — refinement call (recommended if the operator prefers zero semantic widening).**
New MCP tool `get_chunk_members(anchor: Anchor) -> list[Block]`, a sibling of the existing
`get_section`: resolves the chunk anchored at `anchor.block_id`, returns its member blocks as
the already-frozen `Block` shape. Touches only `contracts/mcp_server.py`'s tool enumeration +
DATA-CONTRACTS §M5 mention. Zero duplication, zero migration, caller pulls only when precision
matters; cost is one extra round-trip per citation.

**Zero-code workaround available today** (documented for completeness, not recommended):
a caller holding a served result already has `anchor.section_path`; `get_paper`/`get_section`
returns that section's blocks, and membership can be reconstructed by matching block texts
against `passage_text`'s body (strip the `{title}\n{section_path}` header; remember the
documented one-block overlap rides in the body without being a member). Fragile under duplicate
block texts and split sections spanning multiple chunks — which is precisely why the derived
variants above exist.

**Recommendation to the operator:** Variant C if minimalism wins (new tool, old shapes),
Variant A if callers should get members without a second call (contract-reserved metadata slot).
Either way the measurement above is the expected effect size: +6.3 pp passage hit-rate on
ver84 dense (78.1→84.4%), +1.6 pp on GT-WMR fused (93.9→95.5%), concentrated entirely in the
C2 bucket, with zero regression risk.

## Verdict

**Member-block citation converts real items honestly — but fewer than the metric framing alone
suggests and exactly where NB-D2 pointed: the two known sibling-anchor artifacts reproduce as
rank-1 conversions, and widening to the full top-10 finds three more ver84 C2 items riding
inside non-rank-1 served chunks, taking ver84 dense from 78.1%→84.4% and erasing GT-WMR's C2
bucket outright (93.9%→95.5%) with monotone-zero risk. It is a citation/metric-honesty fix, not
a retrieval fix. Every caller-facing exposure route (payload field, GroundedResult field,
refinement MCP tool, even populating the reserved metadata slot) crosses a frozen path or a
contract-reserved act — the proposed diffs are in §3 and stop there pending T-F7 sign-off;
the store-side derivation they would share is demonstrated end-to-end by the committed,
gated instrument (`app/exp_nb_xc_member_citation.py`).**

TICKET COMPLETE: NB-XC
