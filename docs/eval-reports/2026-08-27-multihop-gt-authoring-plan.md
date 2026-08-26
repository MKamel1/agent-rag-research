# Multi-hop ground-truth AUTHORING PLAN (programme ticket P0-3)

> **Provenance.** Written 2026-08-26 by the programme orchestrator after the dispatched writer lane
> timed out twice on input-reading (4800 s budget consumed across B0 §3 + openevidence §3 +
> WORK-BREAKDOWN precedents; zero bytes drafted — lesson §4.6's fresh-narrow-brief rule applied
> inverted: the orchestrator held the context already). Docs only. **Authoring EXECUTION is Wave
> P2/SB-2 and sits behind the operator's GPU-freeze gate** — this document plans; nothing here runs.

Turns B0 §3's gap analysis into an executable specification for the five missing benchmark sets
(W-A1..W-A5). House rules binding throughout: fixtures never averaged; every number carries its
denominator; lessons §7.2 reachability notes precede any new-metric endorsement; the authoring
regime is openevidence-programme §3 verbatim.

---

## §1 Sets, shapes, floors (restated from B0 §3.2 — the contract this spec sizes)

| set | shape | system requirement | floor (B0) |
|---|---|---|---|
| W-A1 | decomposition-required | answer computable ONLY by combining ≥2 independently retrievable sub-results | n ≈ 30–40 |
| W-A2 | iterative-retrieval-required | hop-1 output necessarily reformulates hop-2 (entity resolution, citation chase, parameter lookup) | n ≈ 30–40 |
| W-A3 | cross-doc synthesis/conflict | ≥2 papers read; deliberate conflicting-figure items require reporting both with provenance | n ≥ 30 SCORED, spread across BOTH fixtures |
| W-A4 | partial-absent | multi-sub-part questions with ≥1 genuinely absent sub-part; correct behaviour answers supported parts, refuses absent | n ≈ 15–20 |
| W-A5 | trajectory/process GT | annotation LAYER over W-A1/W-A2: gold sub-goal graphs | cost multiplier ≈ 2–3× |

---

## §2 Sizing — shown arithmetic, not vibes

Method: paired same-item contrasts (each item scored under single-pass baseline AND agentic system),
normal approximation with assumed within-item outcome correlation ρ = 0.5:

```
minimum detectable swing (points) ≈ 2.8 × √( 2·p̄·q̄·(1−ρ) / n )
```

Sanity anchor against house precedent: the T-DOC-BOOK-EVAL-115 set (115 items) resolves an 18-point
swing at α = 0.05 / power = 0.80 — plugging n = 57-per-arm into the formula reproduces ≈19 points,
so the approximation tracks the precedent.

| set | planned n | assumed p̄ | MDE (paired, ρ=0.5) | verdict |
|---|---|---|---|---|
| W-A1 | **40** | 0.45 | ≈ 22 pts | sufficient IF the agentic delta on decomposition-required items is ≥ 25 pts (single-pass failure-by-construction supports this; confirmed at pilot before freeze) |
| W-A2 | **40** | 0.45 | ≈ 22 pts | same reasoning |
| W-A3 | **30** (≥15 per fixture) | 0.50 | ≈ 26 pts | fixes today's lopsidedness (5 scored, all ver84 — PREC-1 §5 symmetry violation) |
| W-A4 | **20** | 0.50 | ≈ 34 pts | acceptable: primary purpose is CALIBRATION ANCHORS (below), not hypothesis testing |
| W-A5 | subset: **20 fully-graphed** items first | — | — | extend only if trajectory metrics prove discriminating on the subset |

**Anchor-budget consequence (closes B0 §4's ~4× gap):** W-A4's per-sub-part absence logs plus
W-A1/W-A3 gold references yield **130 items / ≈300+ graded claim-evidence pairs**, crossing the
≥100-graded-anchor threshold R2 §3.4 set for five-threshold semantics. This is the quietest but
most consequential line in the document.

Attrition policy: +10% spare items per set (the regime discloses drift; verification kills items);
spares enter scoring only after the killed items are logged with cause.

---

## §3 Per-item shape specifications

Common mandatory fields (every set): `question`, `gold_paper_ids`, `gold_block_ids` (substring-
fidelity machine-checked against served chunk text — difflib rule, never retyped), `author_id`
(GT-A/GT-B), `_metadata.corrections[]`, `duplicate_of` where applicable, `frozen_after_retrieval:
true` (protocol §5.8 no-edit-after-retrieval).

- **W-A1**: `sub_goal_graph` = `{sub_queries: [], sub_results: [{ref: block id}], composition:
  "numeric-composition" | "conjunction"}`; validity requires NO single passage contains all inputs
  (machine-checked at authoring time by probing the index per sub-result).
- **W-A2**: `hop_chain` = `[{query, evidence_ref}] × ≥2` + `hop_trigger` field naming what in hop-1
  output forces hop-2 (entity id, citation, parameter). Grading records `hops_to_answer`.
- **W-A3**: `paper_set` (≥2), `conflict_class: complementary | conflicting`; conflicting items carry
  BOTH gold positions and the expected behaviour (`report-both-with-provenance`) stated in the item.
- **W-A4**: `sub_parts[]` each `{text, status: supported|absent, gold_ref | absence_probe_log}`;
  every `absent` status carries its probe denominator (hit-count queries logged, second-pass
  adversarial probes logged).
- **W-A5 overlay** (on the 20-item subset): `expected_sub_queries[]`,
  `intermediate_evidence[block ids]`, `stop_condition`.

---

## §4 Authoring regime checklist (openevidence §3, enumerated for dispatch briefs)

- [ ] Stage A — two blind authors, alternating set ownership (GT-A/GT-B pattern: neither sees the
      other's items)
- [ ] Stage B — third session cross-verifies read-only against the corpus; mechanical checks
      re-run independently, counts logged
- [ ] Stage C — adversarial second pass over the riskiest classes (absence logs, numeric
      compositions, conflicting figures) over stated probe denominators
- [ ] Stage D — fourth agent spot-checks the checker
- [ ] Stage E — drift disclosed (never smoothed); duplicates kept under `duplicate_of`;
      corrections only via `_metadata.corrections`
- [ ] Stage F — freeze: `frozen_after_retrieval` set; protocol §5.8 applies thereafter

---

## §5 New-metric reachability notes (lessons §7.2 — before endorsement)

- **hops-to-answer**: defined ONLY when the W-A5 trajectory layer exists for the scored item;
  achievability bound = 1..max_iterations configured. Frozen metric deferred until the 20-graph
  subset lands.
- **decomposition coverage**: matched-required-subgoals / total-required-subgoals. Ceiling < 100%
  by design when graphs contain optional branches — denominator is REQUIRED nodes only, or the
  metric lies.
- **partial-support rate** (W-A4): bounded by each item's sub-part count distribution; every
  absence verdict carries its probe denominator or the rate is void.

---

## §6 Cost estimate and sequencing

- Volume: 130 authored items × 2 blind authors = ~260 authoring units + cross-verification passes
  + 20 trajectory graphs. Scale reference: GT-WMR (82 items, full regime) cost roughly one focused
  session per stage; expect ≈ 1.6× that, i.e. **~5–6 dispatched sessions** (2 author + 1
  cross-verify + 1 adversarial + 1 checker-check + contingency).
- **Sequencing recommendation:** W-A4 first (smallest; doubles as the confidence-surface anchors
  IN-2 needs), then W-A1/W-A2 cores, then W-A3 extension, W-A5 subset last.
- All execution is Wave P2/SB-2, **behind the GPU-freeze gate** (authors are local models).

---

## §7 Self-review

- Fixtures never averaged: enforced per-set and per-fixture spreads (W-A3 explicitly ≥15/fixture).
- No new metric endorsed without a reachability note: §5 covers all three candidates.
- Power arithmetic shown and anchored to the 115 precedent: §2 reproduces it.
- The plan does not author, does not run models, does not touch fixtures/ or foundation paths.
- Known risk stated: if the agentic pilot shows < 20-pt deltas, W-A1/A2 need extension before any
  conclusion is frozen — cheaper to learn that at pilot than post-freeze.
