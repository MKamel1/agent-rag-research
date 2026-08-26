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

**DEAD** — the candidate fails the pre-committed criterion on its first two components; family
closed permanently, per the stub-commit pre-registration.

Measured 2026-08-25 against `waymo_av_safety` (47,893 points, sparse field `sparse` with Qdrant's
native IDF modifier). Both fixtures' hit-rate AUROCs sit at-or-below coin flip in the
mechanism-predicted orientation (0.4824 ver84 / 0.3563 gt_wmr — gt_wmr actually *inverts*), and no
operating point comes near the FP/FN bar. The length-leakage guard PASSES (|ρ| ≤ 0.30) — the
feature is honestly not query-length in costume; what failed is the signal itself. This is the D3
§4 lesson running in reverse: a clean negative, measured once, under a criterion fixed before any
label-bearing run, with no tuning attempted.

---

## Pre-committed falsification criterion (unchanged from the stub commit)

Verbatim from the A-1 design doc §C2 + ticket brief:

1. Hit-rate AUROC ≥ 0.75 on **both** fixtures (D3's replication filter applied up front), AND
2. Best-cut FP ≤ 10/68 (ver84) **and** ≤ 10/70 (gt_wmr) at FN ≤ 25% (≤ 3/14 ver84 since
   4/14 = 28.6%; ≤ 3/12 gt_wmr), AND
3. Leakage guard: Spearman |ρ| between hit-rate and query length ≤ 0.8 reported alongside —
   if it exceeds, reject as authoring leakage regardless of AUROC.

Any single miss → candidate dead, recorded permanently. No extractor or threshold tuning is
permitted to rescue a failure (D3 §4's multiple-comparisons lesson).

## §2 Frozen measurement design (committed in the stub, before any label-bearing run)

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

Both fixtures reported separately throughout; nothing averaged across them (programme constraint
10). Denominators after the pre-committed zero-anchor exclusion: ver84 81 used (67 answerable /
14 absent; excluded `Q-GTA-022` — its text carries no digit, no acronym, no non-initial
capitalized token, and no ≥11-letter word); gt_wmr 81 used (69 / 12; excluded `Q-WMR-038` for the
same reason). FP counts are absolute, so the one-item denominator shrink cannot affect the ≤10
bar's outcome either way.

### Criterion component 1 — hit-rate AUROC (absent-lower orientation): **FAIL**

| fixture | AUROC (oriented) | raw direction P(absent higher) | mean rate absent | mean rate answerable |
|---|---|---|---|---|
| ver84 | 0.4824 | 0.5176 | 0.810 | 0.790 |
| gt_wmr | 0.3563 | 0.6437 | 0.875 | 0.760 |

ver84 is coin-flip territory; gt_wmr is *worse* than coin flip — absent questions there carry
MORE anchor coverage than answerable ones, the exact inversion of the mechanism's premise.
Bar was ≥0.75 on both. Missed by ~0.27 and ~0.39 respectively.

### Criterion component 2 — best-cut operating point: **FAIL**

| fixture | Youden cut (abstain < t) | FP | FN | TPR | FPR | J |
|---|---|---|---|---|---|---|
| ver84 | 0.60 | 12/67 | 10/14 (71.4%) | 0.2857 | 0.1791 | 0.1066 |
| gt_wmr | 0.00 (abstain never) | 0/69 | 12/12 (100%) | 0.0 | 0.0 | 0.0000 |

On gt_wmr the best-Youden cut is degenerate: with absent items covering MORE, every informative
cut loses more specificity than it gains detection, and the optimum collapses to "never abstain"
(J = 0). On ver84 the best non-degenerate trade still refuses 12 answerable questions while
missing 10 of 14 absent items. Bar was FP ≤10 at FN ≤25% on both. Missed on both.

### Criterion component 3 — length-leakage guard: **PASS** (reported alongside, as required)

| fixture | ρ(hit_rate, len_chars) | ρ(hit_rate, len_words) |
|---|---|---|
| ver84 | −0.1549 | −0.0923 |
| gt_wmr | −0.2966 | −0.1608 |

All |ρ| ≤ 0.30 ≪ 0.8. The failure above is genuine signal absence, not D3 §4 item 2's
authoring-leakage pattern recurring in costume.

### Where the signal actually lived (informational rule breakdown)

Per-rule presence rates by arm:

| rule | ver84 answerable | ver84 absent | gt_wmr answerable | gt_wmr absent |
|---|---|---|---|---|
| acronym | 28/31 = 0.90 | 2/2 = 1.00 | 35/37 = 0.95 | 3/3 = 1.00 |
| entity | 118/131 = 0.90 | 28/30 = 0.93 | 75/87 = 0.86 | 18/18 = 1.00 |
| numeric | 25/42 = 0.60 | 1/6 = 0.17 | 20/31 = 0.65 | 0/0 (none present) |
| rare_proxy | 100/137 = 0.73 | 11/15 = 0.73 | 71/104 = 0.68 | 3/7 = 0.43 |

Reading, which matches A-1 §C2's own failure-mode prediction almost line for line:

1. **Entity/acronym anchors hit everywhere in BOTH arms** (86–100%). "Waymo"-class anchors are
   corpus-universal, so they add a near-constant mass that compresses the aggregate rate toward
   saturation for every question.
2. **Numeric anchors ARE discriminative in the predicted direction** (ver84: absent 1/6 = 0.17
   vs answerable 25/42 = 0.60) — the one place the mechanism's premise holds — but they are too
   few per question (42 and 31 across each fixture's whole answerable arm) to move a
   per-anchor-normalized rate diluted by ~250 near-always-hit entity/rare anchors.
3. **gt_wmr's absent arm contains zero numeric anchors at all** — those twelve questions probe
   entities and long words only, which cover at 100%/43% — so on that fixture the only
   discriminative channel is structurally absent and the aggregate rate *inverts*.
4. Even among ANSWERABLE questions the rate bottoms out at 0.0 (`Q-GTA-027`) and 0.33 — C2 §C2's
   predicted lexical-mismatch false-refusal mode ("corpus contains the fact under a formatting
   variant") is visible on covered items, confirming the extractor-precision risk was real, not
   hypothetical.

### Implementation verification

- AUROC computed rank-based (Mann-Whitney U, average ranks for ties) and verified against
  brute-force pairwise counting on every call inside the script (`auroc_pos_higher` raises if
  the two disagree beyond 1e-12); same posture as D3 §2's implementation check.
- Presence semantics spot-checked before capture: `waymo` → score 220.9, `0.31` → 47.9,
  `VRU` → 114.3, `teleoperation` → 93.5, nonsense token → empty result.
- Capture ran 0 errors on both fixtures; ~0.1 s/fixture (no embedder, no reranker — pure index
  queries).

## §4 Method notes

- **Token-level anchors, not span-level.** A-1's sketch names number+unit *patterns*; the
  shipped index's tokenization is whitespace-granular (`_sparse_vector` hashes whole
  punctuation-included tokens), so a multi-token span has no native AND-semantics in a sparse
  query. Anchors were therefore defined at the index's own granularity — one token, one probe,
  one hash equality — rather than inventing an aggregation the retrieval layer itself doesn't
  perform. Consequence: number+unit spans contribute their unit word only when it independently
  satisfies a rule (it usually doesn't), i.e. the probe measures "does the fact-bearing TOKEN
  exist", which is the quantity A-1's why-null-doesn't-rule-out argument actually turns on.
- **Punctuation rides along, deliberately.** Neither side strips punctuation: a corpus chunk's
  `"waymo,"` hashes differently from a question's `"waymo"`. That lossiness belongs to the
  shipped sparse arm (D3's sparse features were computed over exactly this tokenization);
  stripping on the probe side would have made the probe *mismatch* the index rather than fix
  anything.
- **Zero-anchor policy** (pre-committed in the stub): excluded from all inferential stats rather
  than assigned a fabricated rate. One item per fixture affected; IDs listed in §3.
- **AUROC orientation was pre-stated** (absent-lower, per the mechanism) so the below-chance
  gt_wmr result could not be quietly re-oriented post hoc; the raw opposite-direction value is
  recorded next to it. Note that even taking the favorable-of-two orientations per fixture — a
  move the pre-commitment forbids — neither fixture approaches 0.75 (0.5176 / 0.6437).
- **No tuning occurred**: extraction rules, precedence, dedup, exclusion policy, cut rule, tie-
  breaks, and orientation were all fixed in commit 1 (`425d97e`) before any capture ran
  (commit 2, `f28801c`). The verdict is evaluated verbatim; nothing was iterated.
- **REFRESH scope:** narrower than D3's banner — ranking/fusion/reranker changes cannot move
  this feature (it never retrieves), but the collection's document-frequency statistics can:
  any re-index or corpus growth shifts IDF-weighted scores and presence. Re-run
  `python -m scripts.nb_c2_anchor_probe capture` before reusing these numbers against a changed
  collection.
- **Compliance:** fixtures reported separately; no foundation path touched; no pipeline file
  touched (`rag/vector_index.py` imported read-only via its public module surface — the ticket's
  own reuse mandate names `_sparse_vector`); no fixture writes; no mechanism built (the script
  decides nothing at serve time); GPU untouched (zero inference calls — the probe is
  lexical/index-level by construction).
- **Docs obligations (BACKLOG row, PROJECT-STATUS ledger)** ride with the merge orchestrator, not
  this lane — same posture as D3 §5: parallel lanes ship into those shared files, and constraint 6
  forbids two concurrent branches editing the same file.
- **Reproduction** (repo root, env `agent-rag-research`, Qdrant UP):

```bash
python -m scripts.nb_c2_anchor_probe capture   # -> docs/eval-reports/data/2026-08-25-nb-c2/{ver84,gt_wmr}_anchors.json
python -m scripts.nb_c2_anchor_probe analyze   # -> .../results.json + printed tables
```

All committed artifacts: `scripts/nb_c2_anchor_probe.py`,
`docs/eval-reports/data/2026-08-25-nb-c2/*.json`.
