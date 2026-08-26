# X-C member-block citation ADOPTION — design note (NB-QW1)

**Status: ADOPTION DESIGN — recommends Variant A; filed for the ONE batched foundation rider PR.
No implementation lives on this branch.** T-F7 sign-off (`@MKamel1`) is required BEFORE any
implementation dispatch (programme constraint 9; plan §6: "implementation gets its own dispatched
tickets with the sign-off hash in the brief").

Ticket: **QW-1** of [the precision-0.95 + agentic-RAG programme](../superpowers/plans/2026-08-25-precision95-programme.md)
(§Wave-P1). Evidence being adopted: [NB-XC](../eval-reports/2026-08-25-nb-xc-citation.md) §2/§3.
This note selects between X-C §3's adoption variants and packages the result for the batched rider
PR. **Design only** — every caller-facing route crosses a frozen path or a contract-reserved act,
so this ticket stops here by instruction.

---

## 1. Method notes (including two corrections to the framing we were handed)

1. **"Variant C touches `contracts/mcp_server.py`'s tool enumeration" — verified FALSE against
   live `main`.** `contracts/mcp_server.py` holds response envelopes only; its module docstring
   (lines 4–6) explicitly says the tool interface "`is not reproduced here`". The actual MCP tool
   enumeration lives in `app/serve.py`'s `@mcp.tool()` FastMCP wrappers (instance at :92) plus the
   typed methods on `rag/mcp_server.py::McpServer` (:40). Decisive precedent: adding three MCP
   tools (`get_figures`/`get_section`/`corpus_stats`, commit `9466ae1`) touched `app/serve.py`
   (+32), `rag/document_store.py` (+55), `rag/mcp_server.py` (+39), tests, and a BACKLOG row —
   **zero `contracts/` files, zero CODEOWNERS paths**. The sounder thing done here: enumerate each
   variant's real touch-list from live code (§4–§5), while keeping the *act-level* gate —
   constraint 9's own wording reserves "new MCP tool enumeration" regardless of which file carries
   it — so Variant C still rides the batched rider PR even though its material diff is
   foundation-clean.
2. **Both diff commands coincide.** This worktree branched off fresh `main`; verified
   `git rev-parse origin/main HEAD $(git merge-base HEAD origin/main)` = `e1c3e91` for all three,
   so the plan's `git diff main --name-only` and the brief's `git diff origin/main --name-only`
   are the same check here.
3. Variant B (explicit `GroundedResult` field) is carried in §3's table only for completeness; it
   was already rejected by X-C §3 (largest frozen diff; requires payload re-upsert to serve from
   the index path) and nothing measured since changes that.
4. Denominator discipline: every number below carries `{metric, fixture, arm, pool depth, config}`;
   fixtures are never averaged or compared (constraint 10).

## 2. Measured effect sizes

All numbers from the stored 2026-08-23 Waymo-priority baseline records, answerable scored arm
(`passage_level.scored`), top-10 stored pool, gates G1–G4 passed
(`app/exp_nb_xc_member_citation.py`; machine copy:
[`data/2026-08-23-waymo-priority/nb_xc_member_citation_results.json`](../eval-reports/data/2026-08-23-waymo-priority/nb_xc_member_citation_results.json)).
Fixtures never averaged (constraint 10). Qualifier per row: `{passage hit-rate under
member-widened citation semantics, fixture, answerable arm, top-10 stored pool, config}`.

| config | n_scored | baseline hits | member hits | Δ | conversions |
|---|---|---|---|---|---|
| ver84 × dense_only (headline) | 64 | 50/64 = 78.1% | 54/64 = 84.4% | +4 items (+6.3 pp) | Q-WAYB-027 (rank 1), Q-GTA-044 (r2), Q-GTA-043 (r3), Q-GTA-042 (r5) |
| GT-WMR × fused (headline) | 66 | 62/66 = 93.9% | 63/66 = 95.5% | +1 item (+1.5 pp) | Q-WMR-094 (rank 1); C2 bucket erased to zero |

Appendix arms (same instrument, same gates): ver84×fused 43→47 (same four items);
gt_wmr×dense 61→62; gt_wmr×sparse 36→37 (always Q-WMR-094); ver84×sparse converts nothing (the
carrier chunks never surface under sparse retrieval — no inflation there). Bucket decomposition:
on ver84 dense the C2 bucket ("gold absent from top-10") drops 9 → 5; on GT-WMR fused it drops
1 → 0 — the entire remaining bucket was a citation artifact. Honesty checks held: both NB-D2 §2
sibling-anchor items reproduce as rank-1 conversions; Q-WMR-036 does NOT convert (overlap
presence is not membership, per contract). Risk posture: **monotone-zero by construction** (G4 —
every anchor is a member of its own chunk, so no baseline hit can become a miss under member-
widened citation; pure metric/citation honesty, zero ranking change). **This is a citation/
metric-honesty fix, not a retrieval improvement, and must never be presented as one.**

## 3. Variant comparison (X-C §3 variants; B shown for completeness)

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

## 4. The seam as verified on `main` (`e1c3e91`) — what each variant actually touches

Shared prerequisite, identical in both variants: a read-time membership derivation in the store —
chunks persist `anchor_json`, and membership is derivable via the anchor-partition rule
(NB-D2 §0, mechanically verified there for every paper touched; X-C's committed, gated instrument
demonstrates it end-to-end). Nothing about membership is stored; no migration or re-index either
way. The dual-id conservative rule and the overlap-block exclusion (an overlap block changes
`text` only and is NOT a member — the contract's own carve-out, honored by Q-WMR-036's non-
conversion) must be encoded once, server-side, in this shared helper.

### Variant A — populate `GroundedResult.metadata["member_block_ids"]`

Exact touch list (rider PR contents; no CODEOWNERS path is edited — the gate here is the
reserved ACT):

- **Contract-reserved act:** populating `metadata` — the slot's own docstring
  (`contracts/retriever.py:43–46`) and DATA-CONTRACTS.md §M7 (lines 565–567) reserve population
  for the T-F7 foundation-change protocol verbatim: *"Populating this field is a `contracts/`
  shape change, not a free write by a downstream module."* No byte of `contracts/*.py` changes —
  `metadata: dict = Field(default_factory=dict)` already exists and `SearchResponse` is unchanged.
- **Prose (contract document):** DATA-CONTRACTS.md §M7 gains ONE paragraph defining the key
  (sketch in §7a).
- **Code:** `rag/document_store.py` — derivation helper `get_chunk_members(...)` (~20 lines,
  partition rule, G3-style geometry checks ported from the exp instrument); 
  `rag/retriever.py::retrieve()` — populate the slot at the existing `GroundedResult(...)`
  construction site (:271 area). Critically, `Retriever.__init__` ALREADY injects
  `document_store` (rag/retriever.py:194–198), so Variant A adds **zero new collaborators and
  zero cross-module seams**.
- **Tests:** `rag/test_document_store.py` (helper: partition rule, overlap exclusion, dual-id,
  unresolvable anchor), `rag/test_retriever.py` (slot populated, anchor-first ordering).
- **Docs obligations (ride with the PR, constraint 12):** `docs/BACKLOG.md` row +
  `docs/PROJECT-STATUS.md` ledger entry.

Caller impact: automatic everywhere `GroundedResult` flows — MCP `semantic_search`
(`SearchResponse.results[*].metadata`), the dashboard `/api/search` (routes through
`McpServer.semantic_search`, `app/dashboard/server.py:528`), and offline harnesses that call
`Retriever.retrieve()` directly (e.g. `app/retrieval_eval.py` via the `server.retriever`
property) — meaning IN-1's dual-fixture runs can compute the member-hit metric straight from
served results with no reimplementation. Old clients ignoring unknown dict keys are unaffected;
V1/V2's planned keys (status/conditions/confidence, §M7) do not collide. Payload cost is k ×
~5–15 short block-id strings per response, negligible against `passage_text`, which already
ships the full chunk body on every result.

### Variant C — refinement tool `get_chunk_members`

Exact touch list (also rider PR contents; also zero frozen-file edits):

- **Contract-reserved act:** constraint 9 names "new MCP tool enumeration" as requiring the
  batched rider PR regardless of which file carries the enumeration.
- **Code:** `rag/document_store.py` — the SAME shared helper as Variant A;
  `rag/mcp_server.py::McpServer.get_chunk_members()` — new method beside `get_section` (:292),
  same error posture (`ContractError` on unresolvable anchor, `_serving_suffix()` included);
  `app/serve.py` — `@mcp.tool()` + `@record_usage(source="mcp", tool="get_chunk_members")`
  wrapper beside `get_section`'s (:221–228). Return type is the already-frozen `Block`
  (`contracts/provenance.py`), exactly like `get_section` returns bare `list[Block]` — records,
  never bare text (PRD §8.5) — so no envelope work in `contracts/mcp_server.py`.
- **Tests:** `app/test_serve.py`, `rag/test_mcp_server.py`, `rag/test_document_store.py`.
- **Prose:** DATA-CONTRACTS.md §M5/§M8 mention; `ARCHITECTURE.md` M8 interface list (:252) —
  noting that line is ALREADY stale (it still says four tools; `scan_corpus`/`scan_methods`/
  `get_section`/`get_figures`/`corpus_stats` exist today), so the rider updates it rather than
  newly breaking it. `app/usage_log.py`'s "four tools" docstring has the same pre-existing
  staleness.

Caller impact: opt-in pull. Existing callers keep citing anchors-only BY DEFAULT — so the
measured conversions materialize only where each calling agent discovers the tool AND spends one
extra round-trip per citation. Zero widening of search responses; zero cost for callers who don't
care. ARCHITECTURE.md M8 explicitly blesses this seam shape ("tools are **additive** … No
existing tool changes", :266–267).

## 5. Rollout order

Identical shape for either variant; only step r③'s wiring differs:

- **r① Contract prose FIRST:** DATA-CONTRACTS §M7 paragraph (Variant A) or §M5/§M8 mention
  (Variant C) lands as the rider PR's first commit — semantics frozen before code, the house
  convention X-C/NB-C2 used to freeze definitions before measurement.
- **r② Store-side derivation helper + unit tests** (shared core; pure read-side; partition rule +
  overlap exclusion + dual-id conservatism + geometry checks ported from the exp instrument).
- **r③ Wiring + tests:** Variant A — retriever slot population; Variant C — `McpServer` method +
  `app/serve.py` wrapper. Zero-GPU, zero-network pytest locally, then
  `GITHUB_EVENT_PATH=/tmp/fake_push_event.json GITHUB_EVENT_NAME=push python -m
  ci.run_enforcement` (constraint 13).
- **r④ Docs obligations:** BACKLOG row + PROJECT-STATUS ledger entry (constraint 12), plus the
  ARCHITECTURE.md M8 interface line if Variant C.

Sequence around the gate: THIS note → operator reviews it → T-F7 sign-off recorded (hash) → a
SEPARATE implementation ticket is dispatched with the sign-off hash in its brief → the ONE
batched rider PR carries r①–r④. Implementation never rides silently inside another lane's branch.

## 6. Recommendation — Variant A

**Adopt Variant A** (populate `GroundedResult.metadata["member_block_ids"]` + the §M7 paragraph),
with Variant C as the recorded fallback if the operator declines to open the reserved slot.

1. **Effect realization is the entire point.** The measured benefit is a *citation-metric* shift;
   it counts only when citations actually carry members without anyone opting in. Variant A
   delivers it to every consumer by default; Variant C converts the programme's cheapest win into
   a caller-diligence bet — every agent must learn the tool exists AND pay a round-trip per
   citation, forever, to realize +6.3/+1.5 pp that are already measured and carry zero regression
   risk.
2. **One source of truth for a fragile rule.** Membership semantics encode contract subtleties
   (anchor-partition, overlap exclusion, dual-id conservatism). Variant A encodes them once,
   server-side. Variant C invites N independent client reconstructions — and X-C §3's own
   zero-code workaround paragraph demonstrates exactly how fragile reconstruction is (duplicate
   block texts, split sections spanning chunks).
3. **Zero structural cost.** `Retriever` already holds `document_store` (no new collaborator, no
   seam change); no migration; no re-index; retroactive over every stored corpus including the
   Waymo corpus; monotone-zero risk preserved because ranking is untouched.
4. **The slot exists for precisely this.** §M7's design intent is forward-compat by filling:
   *"those land as filled fields, not a changed type — no V0 consumer breaks."* Populating it via
   the rider PR is not bypassing the foundation protocol — it IS the protocol operating as
   designed.
5. **IN-1 consumes the effect server-side.** The integration ticket scores the adopted stack
   directly off `retrieve()` output; under Variant A the honesty shift shows up in those runs
   automatically. Coordination note (operator item, not scope expansion): IN-1 may count member
   hits only under ratified metric definitions — flag to P0-2 so the ratified definition names
   member-widened citation semantics explicitly.

Honest counter-case for C, recorded because the operator signs, not us: C keeps the search
response semantically minimal, sits on an explicitly blessed additive seam, and has the cleanest
precedent on record (`9466ae1` — zero frozen diffs), which may make the sign-off conversation
shorter. Decision rule: if default-effect realization weighs heaviest → A; if surface minimalism
does → C. We weigh realization heaviest because the programme's gate (IN-1 scored under ratified
metrics) consumes the effect mechanically, not through caller cooperation.

## 7. Rider-PR diff-preview sketches (SKETCH ONLY — not appliable hunks)

Real diffs belong to the post-sign-off implementation ticket. These previews exist so the
operator signs against something concrete.

**(a) Variant A — `DATA-CONTRACTS.md` §M7, one paragraph appended after the `metadata` field
comment (lines ~565–567):**

```text
    metadata["member_block_ids"] (populated starting NB-QW1-rider): ordered block ids of the
    matched Chunk's constituent blocks — anchor first, then reading order; OVERLAP BLOCKS ARE
    EXCLUDED (the multi-block anchoring rule's carve-out: an overlap block changes text only and
    is not a member). Ids are emitted in the chunk's own ingest identity (dual-id rule:
    membership is asserted within one paper-prefix only). Derivation is read-time (anchor-
    partition rule, NB-D2 §0), so the slot populates retroactively over every stored corpus with
    no migration and no re-index.
```

**(b) Variant A — `rag/document_store.py` helper + `rag/retriever.py` construction-site change:**

```diff
 # rag/document_store.py — beside get_block()/get_chunk()/get_span()
+   def get_chunk_members(self, anchor: Anchor) -> list[Block]:
+       """Member blocks of the chunk anchored at `anchor` — anchor first, reading order,
+       overlap blocks excluded (contract carve-out). Raises on unresolvable anchor."""
+       ...  # anchor-partition rule, ~20 lines; geometry checks per NB-D2 §0

 # rag/retriever.py::retrieve() — at the GroundedResult(...) build site (~:271)
-        GroundedResult(passage_text=..., anchor=..., score=..., citation=...)
+        GroundedResult(passage_text=..., anchor=..., score=..., citation=...,
+                       metadata={"member_block_ids":
+                                 [b.block_id for b in
+                                  self._document_store.get_chunk_members(anchor)]})
```

**(c) Variant C — fallback shape, `rag/mcp_server.py` + `app/serve.py`:**

```diff
 # rag/mcp_server.py::McpServer — beside get_section() (:292)
+   def get_chunk_members(self, anchor: Anchor) -> list[Block]:
+       """Member blocks of the chunk anchored at `anchor`, anchor first, overlap excluded.
+       Precondition: anchor resolves to a stored block; else ContractError."""
+       return self._document_store.get_chunk_members(anchor)

 # app/serve.py — beside get_section()'s wrapper (:221)
+   @mcp.tool()
+   @record_usage(_get_usage_log, source="mcp", tool="get_chunk_members")
+   def get_chunk_members(anchor: Anchor) -> list:
+       return _server.get_chunk_members(anchor)
```

## 8. Explicitly out of scope (all variants)

No ranking/pipeline change (monotone-zero is the safety property being preserved); no handling of
`adjacent_chunk`/`same_doc_elsewhere` near-misses (NB-D2 §3's long tail — SB-1's territory); no
V1 tier/confidence/status semantics written into `metadata` alongside the new key; no dashboard
UI change required; no claim-language upgrades — GT-WMR's 95.5% stays labeled a citation-honesty
bound, never a retrieval improvement. This ticket itself touches NO path outside
`docs/design-notes/`.

## 9. Verification stated and performed in-ticket

- `git diff origin/main --name-only` → `docs/design-notes/2026-08-28-xc-member-citation-adoption.md`
  only (docs-only). Branch base == `origin/main` == `e1c3e91`, verified by `git rev-parse`
  triple-equality before writing.
- Effect sizes carry fixtures/denominators (§2 table; five-part qualifiers stated; fixtures never
  averaged).
- No implementation commits exist on this branch: both commits touch this file alone; no
  `contracts/`, `migrations/`, `fixtures/`, `rag/config.py`, `ci/`, `.github/`, or
  `pyproject.toml` diff; no MCP change implemented.
