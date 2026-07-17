# Design — V1 Claim Layer (T-V1-CLAIM-SCHEMA + downstream)

*Design proposal, 2026-07-17. Grounded in ADR-12, DATA-CONTRACTS.md §6, and Spike 3
(`reviews/SPIKE3-CLAIM-EXTRACTION.md`). **Foundation change — needs sign-off before build.***

Applies the deep-module lens: a small interface (what a caller must know about a claim) over the
capability of "grounded, reconcilable knowledge." The claim layer is four modules with distinct
secrets, mapped to the already-ticketed waves.

---

## What Spike 3 changed about the pre-named schema

DATA-CONTRACTS.md §6 stubbed `claims(claim_id, paper_id, method, dataset, metric, value,
conditions_json, anchor_json, ...)` as rigid columns. Spike 3 measured reality on this corpus:

- The structured fields are **sparse**: method 80%, dataset 68%, metric 54%, **value 46%**.
- `value` is **heterogeneous text**, not a number: `"0.94–0.99"`, `"3.991 (3.69,4.29)"`, `"reduces
  bias"`, `""`. A float column would fight the data.
- `conditions` is the **load-bearing** field — it correctly flags cross-paper claims as
  non-comparable (the ADR-12 thesis working). It must stay rich free-text, first-class.
- Reconciliation is **flag-only** — no auto-supersession (that's v2's judge). Edges are surfaced
  hypotheses, never applied.

**Design consequence:** a claim is fundamentally a *grounded assertion* (`claim_text` + `anchor` +
`type`); the structured facets (`method/dataset/metric/value/conditions`) are *optional enrichment*
present when extraction found them. This is the common case (Ch 4–5): storing, retrieving, and
citing a claim must be trivial and must not require the structured fields — most claims are
half-populated. Reconciliation, which needs the facets, is a separate optional module.

---

## Module 1 — `Claim` contract (`contracts/claim.py`) [T-V1-CLAIM-SCHEMA, foundation]

The secret it hides: *what constitutes an atomic, verifiable claim.*

```python
class Claim(FrozenModel):
    claim_id: str          # "{paper_id}:cl{n}" — same id convention as chunks
    paper_id: str
    claim_text: str        # the atomic assertion (REQUIRED, non-empty)
    claim_type: Literal["result", "method", "comparison", "limitation", "assumption"]
    anchor: Anchor         # provenance — REQUIRED. "no anchor -> invalid" (DATA-CONTRACTS §6A).
                           # pins to a source block_id (structural), snippet = the quotable evidence.
    # --- optional structured facets (present when extraction found them) ---
    method: str | None = None
    dataset: str | None = None       # task_or_dataset
    metric: str | None = None
    value: str | None = None         # str, NOT float — heterogeneous ("0.94–0.99", ranges, CIs)
    conditions: str | None = None    # the load-bearing disambiguator — rich free-text
    confidence: Literal["high", "medium", "low"] = "medium"
    artifact_links: list[str] = []   # bidirectional Claim<->Artifact ids (code/dataset/model/figure)
```

**Contract (design-by-contract):**
- *Invariant:* `claim_text` non-empty AND `anchor` valid (its own contract: block_id + page +
  snippet). A claim with no grounding is invalid by construction — the verifiability guarantee (G5).
- *The facets are optional by design* — a claim is valid as a grounded assertion alone. No caller
  is forced to handle the structured surface (avoids Overexposure).
- **No `embedding` field** — the vector is derived and lives in the vector store (kind="claim"),
  exactly as `Chunk` doesn't carry its own vector.

**Spike-3-driven decisions baked in:** `value` is `str|None` (heterogeneous); every facet is
nullable (sparse extraction); `conditions` is first-class free-text (load-bearing); `anchor` pins
structurally to a block (NOT a verbatim-span match — Spike 3 showed spans are paraphrased, so the
extractor fuzzy-maps each claim to its best source block and anchors there).

## Module 2 — `ClaimRelation` contract (edges) [T-V1-DEDUP / T-V1-TIERS]

The secret: *how two claims relate, as a surfaced hypothesis.*

```python
class ClaimRelation(FrozenModel):
    claim_id_a: str
    claim_id_b: str
    relation: Literal["duplicate", "refines", "supports", "contradicts"]  # NOT "supersedes" in V1
    basis: str          # WHY — e.g. "same method+metric+dataset, values differ" — for human/agent review
    confidence: Literal["high", "medium", "low"] = "low"
```

**Flag-only, by contract:** V1 emits `supersedes` **never** — supersession is v2's judge (ADR-12
"v2 turns on the judge"). Edges are candidates surfaced to the consuming agent, never applied to
rewrite belief. This is the schema-level encoding of Spike 3's flag-only verdict (mirrors how V0's
`evidence_tier` is pinned to "A").

## Module 3 — `ClaimExtractor` seam (`rag/claim_extractor.py`) [T-V1-CLAIM-EXTRACT]

The secret: *how claims are extracted from a paper* (prompt + LLM + JSON-repair + anchor mapping).
Interface mirrors `Summarizer` (deep: one method, lots behind it):

```python
def extract(self, parsed: ParsedDoc, summary: str) -> list[Claim]: ...
```

- *Precondition:* `parsed.markdown` has usable prose (else `[]`).
- *Postcondition:* every returned `Claim` has a valid anchor into `parsed`'s blocks.
- **The deep/hard part — anchor mapping [RESOLVED by design-it-twice, 2026-07-17].** Two arms were
  prototyped and MEASURED against the real Spike-3 data (`scratchpad/anchor-A`, `anchor-B`):
  post-hoc lexical mapping (map after extraction) vs. in-loop (LLM cites the `block_id` during
  extraction). **They tied at 11/15 (73%) hand-audit precision and BOTH failed the same way — the
  paper's Abstract block is a universal false-attractor** (lexical similarity drifts to it;
  in-loop falls back to it when the true block is windowed out of context on long papers). So the
  winner is neither mechanism alone but a **precision-GATED hybrid — "cite, verify, repair, else
  drop":**
    1. **Cite (in-loop):** the LLM emits `source_block_id` during extraction (grounds provenance at
       the source; `Anchor`'s page/bbox/section come free from the block row; 0% id-hallucination
       after a one-line `[[block: id]]`-unwrap fix).
    2. **Verify (grounding gate — the real quality control both arms demanded):** confirm the cited
       block actually contains the claim's numeric `value` / key terms. Cheap CPU (Arm A's scorer).
       An Abstract-fallback fails this gate because the abstract lacks the specific result.
    3. **Repair (post-hoc lexical, Arm A):** if the gate fails, re-map over ALL blocks (Arm A has no
       context limit) with the Abstract penalized as a known attractor; re-run the gate.
    4. **Else drop:** if no block passes the gate, the claim can't be verifiably grounded → it is
       NOT stored (or stored flagged-unverified), per G5 "no valid anchor → invalid." Better to drop
       an ungroundable claim than cite it wrongly (a wrong anchor is false confidence).
  This makes provenance **verified, not hoped**: every stored claim's anchor has passed an objective
  support check — the ~27% that would have been wrong anchors become "dropped/flagged," never
  "silently wrong." Windowing on long papers (Arm B's scaling risk at 30k) is absorbed because the
  repair step (Arm A) sees the full block set regardless of what extraction could fit in context.
- **Spike-3 fixes fold in here** (not the schema): verbatim-span prompting, results/tables-section
  preservation for numeric `value`, and **JSON-repair/retry** (2/20 papers failed raw-JSON parse —
  would silently drop papers at 30k).

## Module 4 — persistence (`migrations/0004_claims.sql` + `DocumentStore` methods) [T-V1-CLAIM-SCHEMA]

Additive migration (never alters V0 tables). Store seam mirrors chunks:
`put_claims(paper_id, list[Claim])`, `get_claims(paper_id)`, `put_claim_relations(...)`,
`get_claim_relations(claim_id)`.

**Schema (the columns-vs-facets decision — see "Decisions needing sign-off"):**
```sql
CREATE TABLE claims (
  claim_id   TEXT PRIMARY KEY,
  paper_id   TEXT NOT NULL REFERENCES papers(paper_id),
  claim_text TEXT NOT NULL,
  claim_type TEXT NOT NULL,
  anchor_json TEXT NOT NULL,          -- provenance, required
  method     TEXT, dataset TEXT, metric TEXT,   -- indexed: the reconciliation candidate-grouping keys
  value      TEXT,                    -- heterogeneous, nullable (Spike 3)
  conditions TEXT,                    -- load-bearing free-text
  confidence TEXT NOT NULL,
  artifact_links_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX idx_claims_recon ON claims(metric, dataset, method);  -- candidate grouping
CREATE TABLE claim_relations (
  claim_id_a TEXT NOT NULL, claim_id_b TEXT NOT NULL,
  relation TEXT NOT NULL, basis TEXT NOT NULL, confidence TEXT NOT NULL
);
```
`citation_edges` (the S2/OpenAlex citation *graph*, ADR-15) is **v2, NOT part of the claim layer** —
excluded here to keep the seam honest (Separate general from special).

## Pipeline integration

- New orchestrator stage after `summarized`: `ClaimExtractor.extract` → `put_claims` → embed claims
  into the vector store (`kind="claim"` payload alongside chunks). Reuses the existing GPU-lock +
  `before_embed` unload discipline.
- `CheckpointArtifacts.claims: list[Claim] | None` — **already stubbed** (contracts/ingest_state.py),
  so resume needs no new checkpoint migration.
- New stage token in `_STAGES` (e.g. `claims_extracted` between `summarized` and `embedded`).

## Wave mapping (already ticketed)

- **T-V1-CLAIM-SCHEMA** = Modules 1, 2, 4 (contract + migration + store seam). Foundation → this
  design's sign-off. Update DATA-CONTRACTS.md §6 first (source of truth), then the migration.
- **T-V1-CLAIM-EXTRACT** = Module 3 + pipeline stage. Gated on schema. Carries the Spike-3 fixes.
- **T-V1-DEDUP** = ClaimRelation *generation* (candidate grouping on the indexed keys → flag edges).
- **T-V1-TIERS** = activate evidence-tier B/C/D using claims (currently pinned to "A").

## Decisions needing your sign-off (foundation)

1. **[CONFIRMED 2026-07-17] Hybrid schema.** `method/dataset/metric` as indexed columns (candidate
   grouping for reconciliation); `value/conditions` as nullable text. Matches Spike 3's sparse/
   heterogeneous reality while keeping the reconciliation candidate-query indexable.
2. **`value` as `str`, not `float`** — Spike 3 says heterogeneous. Recommend `str|None`. (A future
   numeric-comparison layer can parse it; forcing a float now loses ranges/CIs.)
3. **[CONFIRMED 2026-07-17] Flag-only in the schema** — `ClaimRelation.relation` excludes
   `supersedes` in V1; supersession deferred to v2's judge. Matches Spike 3 + PRD default.

**[RESOLVED 2026-07-17] Anchor-mapping** — measured design-it-twice (both arms tied at 73%, both
failed via the Abstract-attractor) → the precision-gated "cite, verify, repair, else drop" hybrid in
Module 3. Provenance is verified per-claim, not hoped. Schema is now ready for build sign-off.
