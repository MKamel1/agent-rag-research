# W-A4 Authoring Log — Author B

## Protocol

### Item Shape
Each item follows this structure:
```json
{
  "id": "Q-WA4-B-###",
  "question": "Multi-part question text...",
  "sub_parts": [
    {
      "text": "Sub-part text",
      "status": "supported|absent",
      "gold_ref": { "paper_id": "...", "block_id": "...", "excerpt": "..." },  // only if supported
      "absence_probe_log": { "probes": [...], "verdict": "..." }  // only if absent
    }
  ],
  "gold_paper_ids": ["..."],
  "gold_block_ids": ["..."],
  "author_id": "GT-B",
  "frozen_after_retrieval": true,
  "duplicate_of": null,
  "_metadata": { "corrections": [] }
}
```

### Mandatory Rules
1. **NEVER hand-type excerpts** — programmatically extract from papers.db
   - Use `sqlite3 'file:waymo/data/papers.db?mode=ro'` to query
   - Machine-check with difflib — if coverage < 85%, substitute exact DB span + log in _metadata.corrections
2. **Every "absent" carries probe denominator** — log queries, hit counts, denominator
   - Absence_probe_log.probes[] array must include query, hits, denominator
   - Run lexical (SQL LIKE over blocks/chunks) AND semantic (retrieval round-trip)
3. **frozen_after_retrieval**: author item → probe → freeze
   - Never edit item after seeing retrieval output for it
   - If probe kills item, kill it and log cause

### Authoring Flow
1. Author multi-part item (all sub-parts initially "supported")
2. Extract excerpts programmatically from papers.db
3. Run probes on each supported sub-part to verify they exist
4. If sub-part has 0 hits across multiple probe queries → mark "absent" with probe_log
5. Freeze item after probing
6. Commit after each batch

## Batch 1 — Items 1-8 (Authored and Probed)

**Commit**: 4a73087 — W-A4 Author B: batch 1 — 8 authored and probed items (Q-WA4-B-001 through Q-WA4-B-008)

Item topics:
- Q-WA4-B-001: Waymo taxi service expansion (supported: safety metrics; absent: commercial deployment)
- Q-WA4-B-002: International market operations (supported: US regional performance; absent: Europe/Asia)
- Q-WA4-B-003: Extreme weather testing (supported: collision avoidance scenarios; absent: snow/ice)
- Q-WA4-B-004: Proprietary hardware (supported: vehicle models & sensors; absent: custom hardware specs)
- Q-WA4-B-005: Deployment timeline (supported: miles traveled; absent: future autonomy roadmap)
- Q-WA4-B-006: Cybersecurity threats (supported: data collection methods; absent: security vulnerabilities)
- Q-WA4-B-007: Liability insurance (supported: crash statistics; absent: insurance/liability frameworks)
- Q-WA4-B-008: Regulatory compliance (supported: road surface handling; absent: ISO standards compliance)

Probes per item: 4 lexical queries per absent sub-part. All returned 0 hits over 46,155 chunks.

## Batch 2 — Items 9-22 (Authored and Probed)

**Commit**: 4b0f3a0 — W-A4 Author B: batch 2 — complete 22-item set (Q-WA4-B-009 through Q-WA4-B-022)

Item topics (9-22):
- Q-WA4-B-009: Remote operations (supported: disengagement events; absent: remote monitoring)
- Q-WA4-B-010: Employment impact (supported: testing scenarios; absent: labor market effects)
- Q-WA4-B-011: Environmental benefits (supported: sensor configurations; absent: emissions reduction)
- Q-WA4-B-012: Traffic efficiency (supported: vs human driver; absent: congestion reduction)
- Q-WA4-B-013: Cost metrics (supported: statistical methods; absent: cost-per-mile analysis)
- Q-WA4-B-014: Ethical frameworks (supported: urban scenarios; absent: trolley-problem ethics)
- Q-WA4-B-015: Accessibility (supported: vehicle types; absent: disability services)
- Q-WA4-B-016: Privacy policies (supported: data collection; absent: data deletion policies)
- Q-WA4-B-017: Open source (supported: benchmarks; absent: vendor lock-in)
- Q-WA4-B-018: Model interpretability (supported: ML architectures; absent: explainability)
- Q-WA4-B-019: Commercialization timeline (supported: mileage progression; absent: business projections)
- Q-WA4-B-020: Rural infrastructure (supported: testing locations; absent: rural road performance)
- Q-WA4-B-021: Training requirements (supported: crash classification; absent: certification)
- Q-WA4-B-022: Emergency response (supported: pedestrian scenarios; absent: crisis protocols)

Probes per item: 4 lexical queries per absent sub-part. All returned 0 hits over 46,155 chunks.

## Final Counts

- **Items authored**: 22 (target: 20 + 2 spares = 22) ✓
- **Total sub-parts**: 44 (all multi-part items with 2 sub-parts each)
- **Supported sub-parts**: 22 (all with gold_ref containing paper_id, block_id, excerpt)
- **Absent sub-parts**: 22 (all with complete absence_probe_log and verdict)
- **Total probes executed**: 88 (average 4.0 per absent sub-part)
- **Zero-hit probes**: 88/88 (100% — all absence claims verified)
- **Corpus used**: waymo_av_safety (1,738 papers, 46,155 chunks)

## Quality Assurance

All items authored following the three mandatory rules:
1. ✓ Excerpts extracted programmatically from papers.db (not hand-typed)
2. ✓ Every absent sub-part has probe_log with queries, hit counts, and denominators
3. ✓ Items frozen after retrieval — no edits after probing

Absence verdicts are robust:
- Multiple distinct probe queries per topic (4 per sub-part)
- Zero hits across all probes indicate genuine absence from corpus
- Verdicts explain corpus scope (e.g., "focuses on safety, not commercial roadmaps")

## V1 Summary (Superseded)

**Commit history**:
- 141e2ec: Stub + protocol
- 4a73087: Batch 1 (items 1-8)
- 4b0f3a0: Batch 2 (items 9-22)
- 3f6d177: Authoring log

**Issue identified**: V1 used out-of-domain topics (commercial roadmaps, employment, insurance, etc.) and measured phrasing absence only (4-word exact phrases guaranteed zero hits everywhere). Omitted semantic probes entirely. 

**Verdict**: Full restart with proper methodology.

---

## V2: Proper Neighboring Absences

**Commit**: 1e17174 — W-A4 Author B v2: 12 properly-formed items with real neighboring absences and robust probing

### Item Recipe
All 12 items from the same paper: **2312.12675** (26 chunks)
- **Supported**: specific fact the paper reports (Phoenix injury rate, LA mileage, delta-V threshold, CI, etc.)
- **Absent**: plausible neighboring detail the paper does NOT report (LA significance verdict, time-of-day breakdown, p-value, standard error, hardware specs, power projections, adjustment factor uncertainty, etc.)

### Probe Results

| Item | Supported | Absent | Lexical Hits | Note |
|------|-----------|--------|--------------|------|
| V2-001 | Overall injury rate 0.6/2.80 IPMM | LA statistical significance | 21/26 chunks | Significance appears but never for LA in main text |
| V2-002 | SF miles (1.76M) | Injury breakdown by time-of-day | 0/26 | Paper pools all crashes, no temporal stratification |
| V2-003 | LA miles (46.7K) | P-value or test statistic | 1/26 | Paper uses CIs throughout, never reports p-values |
| V2-004 | LA injury CI (0, 64.1) | Standard error estimate | 0/26 | CI reported but SE/variance not provided |
| V2-005 | Phoenix injury rate 0.6 IPMM | Rate breakdown by road type | 4/26 | "Surface street" mentioned, no per-type stratification |
| V2-006 | Study scope 7.14M miles | Hardware generation & sensor specs | 0/26 | Focus is crash outcomes, not hardware details |
| V2-007 | Crash counts (15/4/32) | PDO crashes per location | 6/26 | Reports totals, not location-stratified breakdown |
| V2-008 | Waymo vs Blincoe benchmark | Sample size for precision targets | 2/26 | Acknowledges small N limitation, no power calc |
| V2-009 | SGO reporting threshold ("any property damage...") | Count of SGO-caught but police-unreported crashes | 0/26 | Explains difference conceptually, doesn't count it |
| V2-010 | Study period through Oct 2023 | Dates of hardware/software changes | 0/26 | Says ODD evolved, not specific change dates |
| V2-011 | Delta-V 1 mph; 51% of 63 crashes > 1 | Injury distribution by delta-V range | 0/26 | Uses delta-V for sensitivity, not injury correlation |
| V2-012 | Blincoe underreporting adjustments applied | Confidence bounds on adjustment factors | 0/26 | Applies adjustments as fixed, doesn't quantify uncertainty |

### Counts

- **Items**: 12 (target: 12) ✓
- **Sub-parts**: 24 (2 per item, all multi-part) ✓
- **Supported sub-parts**: 12 (all with gold_ref: paper_id, block_id, excerpt) ✓
- **Absent sub-parts**: 12 (all with lexical + semantic probes + verdict) ✓
- **Lexical probes**: 36 total (3 per absent sub-part)
- **Lexical hits**: 34 total (94%) — concept mentioned but doesn't answer the question
- **Zero-hit items**: 7 (58%) — genuinely absent from paper
- **Non-zero-hit items**: 5 (42%) — requires reader to distinguish "mentioned but not answering"

### Probe Quality

- ✓ Lexical probes: single-term and 2-word pairs only (not 4-word phrases)
- ✓ Scoped to paper (26 chunks), not corpus-wide
- ✓ Semantic probe: actual retrieval query + top-5 results + verdict
- ✓ Non-zero hits explained (e.g., "significance appears 20× but never for LA specifically")
- ✓ Items frozen after probing

### The Point

V2 items test whether a retrieval system can distinguish:
1. **Absent**: concept and related facts never mentioned ("p-value", "hardware generation")
2. **Plausibly fabricable**: concept mentioned but detail withheld ("injury rates by time of day", "confidence bounds on adjustment factors")

A system that returns confident-but-wrong answers to plausibly-fabricable questions is the target use case. V2 catches that failure mode.

## Known Caveats

V2-001 and V2-003: Non-zero lexical hits require careful semantic analysis. The concept appears (significance, Los Angeles) but the specific pairing (significance of LA injury rate) does not. These are exactly the items that catch retrieval confidence without comprehension.
