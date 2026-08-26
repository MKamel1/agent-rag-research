# NB-C2 — pre-retrieval lexical anchor-coverage probe — measured 2026-08-25

> **REFRESH-POST-RERANK (inherited from D3, scoped):** this probe bypasses ranking entirely
> (sparse-only presence queries at the index level), so fusion weight / reranker changes do not
> move its feature — but the collection's document-frequency statistics DO move it (any re-index
> or corpus change shifts IDF and presence). Numbers below describe `waymo_av_safety` as indexed
> when measured (47,893 points).

Ticket NB-C2; candidate C2 of [`2026-08-25-nb-a1-abstention-signal-design.md`](2026-08-25-nb-a1-abstention-signal-design.md)
§C2. Question: does per-anchor-normalized anchor coverage (hits/#anchors) under sparse-only
presence queries separate known-absent items from answerable ones well enough to carry an
abstention threshold? This ticket only measures; it builds no mechanism.

---

## Verdict

**PENDING — measurement not yet run** (stub commit; results land in commit 3).

---

## §1 Pre-committed falsification criterion (fixed before any run — committed in this stub)

Verbatim from the A-1 design doc §C2 + ticket brief:

1. Hit-rate AUROC ≥ 0.75 on **both** fixtures (D3's replication filter applied up front), AND
2. Best-cut FP ≤ 10/68 (ver84) **and** ≤ 10/70 (gt_wmr) at FN ≤ 25% (≤ 3/14 ver84 since
   4/14 = 28.6%; ≤ 3/12 gt_wmr), AND
3. Leakage guard: Spearman |ρ| between hit-rate and query length ≤ 0.8 reported alongside —
   if it exceeds, reject as authoring leakage regardless of AUROC.

Any single miss → candidate dead, recorded permanently. No extractor or threshold tuning is
permitted to rescue a failure (D3 §4's multiple-comparisons lesson).

## §2 Frozen measurement design (committed in this stub, before any label-bearing run)

- **Questions:** both fixtures via `app.retrieval_eval.load_questions` unmodified → same
  dedup/partition D3 used: ver84 n=82 (68 answerable / 14 absent), gt_wmr n=82 (70 / 12).
  Labels joined only in `analyze`, never seen by extraction.
- **Anchor extraction (token-level, deterministic, frozen):** each whitespace token of the
  question gets ONE rule by first match, probed lowercased VERBATIM (punctuation included —
  exactly `_sparse_vector`'s own tokenization):
  - R1 numeric: token contains any digit (`0.31`, `24`, `85%`, `1,000`);
  - R2 acronym: all-caps with ≥2 letters anywhere (`VRU`, `AV`);
  - R3 entity: capitalized token NOT at sentence start (sentence starts tracked after `.!?`
    token boundaries);
  - R4 rare-term proxy: ≥11 alphabetic characters (no corpus-df table exists client-side; a
    length proxy is the only leak-free pre-retrieval option — stated as a known precision
    limitation, not tuned around).
  Deduped per question (set of probe forms). No stoplist — any authoring-curated exclusion
  list would be extractor tuning.
- **Presence check:** one Qdrant REST `points/query` per distinct probe form (cached within a
  fixture run), sparse vector built by importing `rag.vector_index._sparse_vector` itself;
  `using="sparse"`, `limit=1`, hit ⇔ a point with score > 0 is returned. Read-only; no dense
  arm, no embedder, no GPU call. Collection named explicitly (`waymo_av_safety`,
  programme constraint 8). Vendor isolation kept: this script never imports `qdrant_client`.
- **Feature:** hit_rate = (#anchor tokens with ≥1 hit)/(#anchors). Zero-anchor questions are
  excluded from all inferential stats (count reported); assigning them a fabricated rate would
  be an unstated mechanism choice.
- **AUROC orientation (pre-stated):** the mechanism predicts absent items score LOWER (fewer
  anchors covered). AUROC is reported as P(answerable > absent) + ½·P(equal); the raw opposite
  direction is also recorded. The criterion applies to the pre-stated orientation.
- **Best cut:** Youden-J over every observed hit-rate value per fixture, abstain if rate < cut
  (D3's convention); FP = answerable below cut, FN = absent at-or-above cut.
- **Leakage guard:** Spearman ρ of hit-rate vs len_chars AND vs len_words per fixture (D3 used
  both length forms); guard fails if EITHER |ρ| > 0.8.

## §3 Results

TODO (commit 3).

## §4 Method notes

TODO (commit 3).
