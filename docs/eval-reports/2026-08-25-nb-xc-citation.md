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

*(pending — this section is filled only after the instrument runs; numbers are not written by hand)*

## 3. Design note: how callers could receive member blocks

*(pending — proposed contract diff, design-note-only; implementation stops at this section
because the minimal designs cross foundation-protected paths)*

## Verdict

*(pending)*

TICKET COMPLETE: NB-XC
