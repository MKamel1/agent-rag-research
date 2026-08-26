# X-C member-block citation ADOPTION — design note (NB-QW1)

**Status: STUB — variant comparison table only; full recommendation, rollout order, and rider-PR
preview follow in commit ②** (house convention: the artifact is committed before the real content,
per precision95-programme constraint 1 "commit-as-you-go").

Ticket: **QW-1** of [the precision-0.95 + agentic-RAG programme](../superpowers/plans/2026-08-25-precision95-programme.md)
(§Wave-P1). Evidence being adopted: [NB-XC](../eval-reports/2026-08-25-nb-xc-citation.md) §2/§3.
This note selects between X-C §3's adoption variants and files the result for the ONE batched
foundation rider PR (programme constraint 9). **Design only — no implementation lives on this
branch; every caller-facing route below crosses a frozen path or a contract-reserved act, so
implementation is gated on T-F7 sign-off (`@MKamel1`) BEFORE any dispatch.**

## Measured effect sizes (X-C §2, quoted with fixtures/denominators)

All numbers from the stored 2026-08-23 Waymo-priority baseline records, answerable scored arm,
top-10 pool, gates G1–G4 passed (`app/exp_nb_xc_member_citation.py`; machine copy:
[`data/2026-08-23-waymo-priority/nb_xc_member_citation_results.json`](../eval-reports/data/2026-08-23-waymo-priority/nb_xc_member_citation_results.json)).
Fixtures never averaged (constraint 10). Qualifier per item: `{passage hit-rate under
member-widened citation semantics, fixture, answerable arm, top-10 stored pool, config}`.

| config | n_scored | baseline hits | member hits | Δ | conversions |
|---|---|---|---|---|---|
| ver84 × dense_only (headline) | 64 | 50/64 = 78.1% | 54/64 = 84.4% | +4 items (+6.3 pp) | Q-WAYB-027 (rank 1), Q-GTA-044 (r2), Q-GTA-043 (r3), Q-GTA-042 (r5) |
| GT-WMR × fused (headline) | 66 | 62/66 = 93.9% | 63/66 = 95.5% | +1 item (+1.5 pp) | Q-WMR-094 (rank 1); C2 bucket erased to zero |

Appendix arms (same instrument): ver84×fused 43→47 (same four items); gt_wmr×dense 61→62;
gt_wmr×sparse 36→37 (always Q-WMR-094); ver84×sparse converts nothing. Monotone-zero risk by
construction (every anchor is a member of its own chunk — no hit can become a miss). This is a
citation/metric-honesty fix, **not** a retrieval improvement.

## Variant comparison (X-C §3 variants; B shown for completeness)

| dimension | **A — populate reserved slot** | **C — refinement MCP tool** | B — explicit field (rejected by X-C §3) |
|---|---|---|---|
| mechanism | retriever derives members at query time into the existing forward-compat slot `GroundedResult.metadata["member_block_ids"]` | new pull tool `get_chunk_members(anchor: Anchor) -> list[Block]`, sibling of `get_section` | new required field `member_block_ids: list[str]` on `GroundedResult`, fed from a new optional `VectorPayload` key |
| frozen `.py` files edited | **none** (slot already exists in `contracts/retriever.py`; populating it is the act that is gated, not an edit) | **none** (verified against precedent: adding `get_section`/`get_figures`/`corpus_stats`, commit `9466ae1`, touched zero `contracts/` files) | `contracts/retriever.py` + `contracts/vector_index.py` (largest frozen diff) |
| contract-reserved acts triggered | populating the T-F7-reserved `metadata` slot (contracts/retriever.py docstring; DATA-CONTRACTS §M7 wording) + one §M7 prose paragraph defining the key | "new MCP tool enumeration" — named contract-reserved by programme constraint 9 itself | contracts shape change + payload migration/re-upsert |
| code touched (all unfrozen) | `rag/document_store.py` (~20-line derivation helper), `rag/retriever.py::retrieve()` (populate at construction), unit tests | same shared store helper, `rag/mcp_server.py::McpServer.get_chunk_members()`, `app/serve.py` wrapper, unit tests | retriever + vector index + re-index/re-upsert path |
| caller impact | automatic: every `GroundedResult` consumer gets members (MCP `semantic_search`, dashboard `/api/search`, offline harnesses via `Retriever.retrieve()`) | opt-in: callers must discover the tool and spend one round-trip per citation; default citations unchanged | automatic, but only after re-upsert makes it servable from the index path |
| measured effect materializes | by default, wherever results are consumed | only where callers adopt the call | by default (post-migration) |
| payload cost | k × ~5–15 short block-id strings atop already-served full chunk text — negligible | zero on search responses; +1 round-trip when used | grows every response AND every stored point payload |
| migration / re-index | none; retroactive over every stored corpus | none; retroactive | re-upsert of Qdrant points required |
| monotone-zero risk preserved | yes (no ranking change) | yes | yes |

*(Full touch-lists with line anchors, rollout order, rider-PR packaging, recommendation +
reasoning, and diff-preview sketches: commit ②.)*

## Verification stated in-ticket

`git diff origin/main --name-only` must show docs-only changes (this file alone). Effect sizes
carry fixtures/denominators (table above). No implementation commits exist on this branch.
