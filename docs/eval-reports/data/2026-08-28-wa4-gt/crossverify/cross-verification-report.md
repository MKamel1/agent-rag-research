# W-A4 cross-verification report (SB-2, Stage B/C/D)

Third-session, blind cross-verification of Author A (GT-A, 21 items / 19 papers) and Author B
(GT-B, `wa4_items_final.json`, 12 items / 5 papers). Independent checker written from scratch
(`scripts/wa4_crossverify.py`) — neither author's verify script was run or trusted.

## Stage B — independent mechanical checks

Ran against both real files. Full machine output: `crossverify/checker_A.json`,
`crossverify/checker_B.json`.

| Check | Set A (21 items) | Set B (12 items) |
|---|---|---|
| Excerpt verbatim substring (block and/or chunk) | 21/21 pass | 12/12 pass |
| `gold_block_id` resolves in `blocks` | 21/21 pass | 12/12 pass |
| `gold_chunk_id` resolves in `chunks` (where present) | n/a (A has no chunk_id field) | 12/12 pass |
| Absent sub-part carries ≥1 lexical probe w/ numeric denominator + scope, plus a semantic probe | 21/21 pass | 12/12 pass |
| Denominator arithmetic (corpus-wide 46,155; paper-scoped `count(*) from chunks where paper_id=?`) | 21/21 pass, 0 mismatches | 12/12 pass, 0 mismatches |
| `frozen_after_retrieval: true` | 21/21 pass | 12/12 pass |

**Zero mechanical failures in either set on first pass.** This alone is not a clean bill of
health — see the hit-count check added below and Stage C.

### Extra mechanical check added mid-review: probe hit-count re-verification

Stage B's denominator check only re-verifies the *denominator* half of a probe (e.g. "does this
paper really have 26 chunks"), not the *hits* half (e.g. "does the term really match 1 chunk").
After Stage C surfaced a falsified item whose root cause was an undercounted hit, I extended the
checker to re-run every lexical probe's own query against `chunks.text` (case-insensitive
substring, matching both authors' own LIKE convention) and diff it against the logged count.

Result: **4 of 12 Set-B items fail this check** (all four are the `2312.12675` items carried
forward unchanged from v3 — `FINAL-001` through `FINAL-004`); **0 of 21 Set-A items fail it.**

| Item | Query | Logged | Actual | Direction |
|---|---|---|---|---|
| FINAL-001 | "Los Angeles" | 1 | 6 | undercount — **hides the falsifying evidence, see below** |
| FINAL-001 | "significance" | 12 | 4 | overcount |
| FINAL-002 | "hour" | 0 | 1 | undercount, immaterial (unrelated prose) |
| FINAL-003 | "statistical test" | 0 | 1 | undercount, immaterial (generic phrase, no number) |
| FINAL-004 | "standard error" | 0 | 1 | undercount, immaterial (CRSS methodology passage, not LA-specific) |
| FINAL-004 | "variance" | 0 | 1 | undercount, immaterial (same passage) |
| FINAL-004 | "SE" | 0 | 19 | probe-design flaw — "SE" as a bare 2-letter substring matches inside ordinary words ("the**se**", "increa**se**"); not a real signal either direction |
| FINAL-004 | "uncertainty" | 1 | 2 | undercount, immaterial |

Only the **FINAL-001 "Los Angeles" undercount is load-bearing** — the two chunks it missed
(`c16`, `c23`) are exactly where the paper states the LA significance result the item calls
absent. The rest are minor logging drift with no effect on the verdict once the actual matched
text is read. All are logged as corrections rather than silently fixed (see Adjudication).

## Stage D — checker self-test (deliberate corruption)

Made a scratch copy of Set A and corrupted three items:
1. Changed one word in a supported excerpt ("incidents" → "events").
2. Pointed a `gold_block_id` at a real block in a different paper.
3. Inflated a corpus-wide denominator (46,155 → 99,999).

Result: **3/3 caught.** The checker dropped from 21/21 PASS to 18/21 PASS, correctly flagging
all three corrupted items and none of the other 18. Notably, corruption 2 (wrong-but-real block)
was caught by the *excerpt substring* check failing, not by `block_id_resolves` (which correctly
reports the block exists) — the combination of both checks is what makes this a real test rather
than a rubber stamp. Full transcript run inline during this session (not committed; ad hoc
scratch file, not part of the two owned data files).

## Stage C — adversarial falsification attempts

Every one of the 33 absent sub-parts (21 in A, 12 in B) was widened-lexical re-probed
corpus-wide and paper-scoped with vocabulary broader than the authors used (single terms and
2-word pairs, not the authors' own phrases). Beyond that:

- **All 21 of Set A's absent sub-parts** were checked by reading the actual paper's full block
  range around the cited section (not just the gold block), and for named-entity absences
  (ViSTA, DRS/"Fu et al", TerraZero, "Major Economic Loss", Delta-v+severe-injury+Waymo) by
  checking every other paper in the corpus that mentions the same term, to rule out a same-name
  collision or a cross-paper answer. **Result: 0 of 21 falsified.** Two are worth naming
  explicitly:
  - **Q-WA4-A-004** (VRU pedestrian/bicyclist/scooter split) — author A's own flagged doubt.
    Confirmed via full read of 2403.14648 (blocks 55–75): the paper never disaggregates its 11
    VRU crashes by type anywhere. The semantic near-miss (a different paper, `local:6b9ccd0431f6`,
    reporting a real per-type breakdown for its own 56.7M-mile dataset) is a genuine wrong-paper
    risk, but does not answer *this* item's question, which is tightly scoped to "those 145 SF
    crashes." **I agree with author A: item is correct as worded**, and the near-miss is exactly
    the kind of trap this eval set should contain, not a defect in it.
  - **Q-WA4-A-014** (WOMD additional scenarios) — see Adjudication; flagged, not falsified.
- **All 12 of Set B's absent sub-parts** were checked the same way. Two rejections came out of
  this pass (detailed below). One self-flagged doubt was re-probed and held:
  - **Q-WA4-B-FINAL-003** (p-value/test-statistic for LA significance) — author B's own flagged
    doubt (only all-zero-lexical-hits absent sub-part in the set). Widened lexical (p-value, p
    value, test statistic, chi-square, z-test, "statistical test") still ≤1 chunk, no numeric
    p-value anywhere. Ran a real semantic round trip via
    `python -m app.mcp_verify_client "p-value or test statistic for the statistical significance
    of the Los Angeles injury rate reduction in Waymo crash study" --k 10 --data-dir waymo/data`
    (resolves to collection `waymo_av_safety` via `waymo/data/config.yaml`). Top hit is a
    *different* paper (`local:6b9ccd0431f6`) that also only reports significance qualitatively via
    confidence intervals — no p-value anywhere in the corpus for this claim. **Confirmed absent,
    agree with author B.**

### Falsified: 2 of 33 absent sub-parts (6%)

**`Q-WA4-B-FINAL-001`** — REJECTED. The sub-part claims "statistical significance of the injury
rate reduction specifically in Los Angeles" is absent from 2312.12675. It is not: block
`2312.12675:b118` (chunk `c23`, section "A.2. Results for Los Angeles") states verbatim: *"The
result in Los Angeles was not statistically significant due to low mileage (confidence intervals
of [0, 21.3] for police-reported and [0, 32.8] for any-injury-reported)."* Block `2312.12675:b92`
(chunk `c16`, CONCLUSIONS) independently states: *"The comparison for Los Angeles was not
statistically significant for zero observed ADS events but few miles."* Root cause: the item's
own "Los Angeles" lexical probe logged 1/26 chunks; the actual count is 6/26 (see Stage B). The
two missed chunks are exactly where the falsifying text lives — a hit-count bug directly caused a
bad ground-truth label.

**`Q-WA4-B-FINAL-006`** — REJECTED. The sub-part claims "the specific required mileage for the
Blincoe-adjusted any-injury-reported severity level at 10% of benchmark" is absent from
2312.13228. It is not: block `2312.13228:b66` (part of chunk `c16` — a *different* chunk in the
same paper from this item's own gold_ref chunk `c19`) is Table 3's data row: `Blincoe-Adjusted
Any-Injury-Reported | 2.4 | 3.5 | 5.7 | 14.8 | 65.6 | 76.3 | 20.3` under column headers `1% | 10%
| 25% | Benchmark 50% | 75% | 125% | 150%`. The column mapping is independently cross-validated
against the paper's own prose: the Suspected-Serious-Injury+ row's 10%-column value (56.3)
exactly matches the paper's stated "approximately 56 million miles" at 10% of benchmark — the
item's own supported-half excerpt (`b74`). So the answer is **3.5 million miles**, sitting in a
retrievable chunk of the same paper. The item's own probes ("required mileage", "table 3")
matched only the prose paragraph and never found the adjacent table chunk.

Both rejections share a pattern: the author read the prose around the cited block carefully but
did not read a *different, nearby chunk in the same paper* that answers the question. This is
the same failure mode Author A's own protocol calls out in their authoring log ("a block-level
excerpt can look absent while the fuller chunk it lives inside is not") — but here it crossed
chunk boundaries within the paper, not just block-vs-chunk within one citation.

## Duplicates

Checked every (author-A block, author-B block) pair for overlap: **exactly one** shared block —
`2312.12675:b12`, cited by both `Q-WA4-A-001` and `Q-WA4-B-FINAL-001`, with near-identical
supported excerpts (both quote the same 0.6 vs 2.80 IPMM sentence). **Not marked as
`duplicate_of`**: the two items' *absent* sub-parts are different questions (A-001: nighttime
IPMM; FINAL-001: LA significance), and FINAL-001 is separately rejected above on its own defect.
Keep `Q-WA4-A-001`. No other block-level or semantic duplicates found between the two sets
(2604.03827 is used by both authors too — A-006 and B-FINAL-009/010 — but on entirely different
facts within the paper; not duplicates).

## Adjudication

Full merged file: `crossverify/wa4_adjudicated.json` (33 entries — every item from both sets,
including the 2 rejected, with adjudication status, notes, and evidence attached; nothing
silently dropped or edited).

| Status | Count | Composition |
|---|---|---|
| `accepted` | 28 | 21 from Set A (incl. 2 with disclosure notes, see below) + 7 from Set B |
| `accepted_with_correction` | 3 | Set B only — `FINAL-002`, `FINAL-003`, `FINAL-004` (probe hit-count logging fixes; verdict unchanged) |
| `rejected` | 2 | Set B only — `FINAL-001`, `FINAL-006` (absence claim falsified) |
| **Total adjudicated** | **33** | 21 + 12 |
| **Usable set (accepted + accepted_with_correction)** | **31** | |

**Paper distribution of the usable (31-item) set: 22 distinct papers.** 19 from Set A (one paper,
2403.14648, used 3×; all others 1×) plus 4 remaining from Set B after the 2 rejections dropped
one paper's item count by one each without dropping the paper itself (`2312.12675` still appears
via `FINAL-002/003/004`; `2312.13228` still appears via `FINAL-005`) — net distinct-paper overlap
between the sets is 2 papers (`2312.12675`, `2604.03827`), giving 19 + 5 − 2 = 22.

### Items flagged for operator judgment (not rejected)

- **`Q-WA4-A-014`** — the "absent" sub-part ("number of additional scenarios added in WOMD's
  most recent version") is directly answerable as **zero**, stated explicitly in the same gold
  block already cited for the supported half ("...subsequent versions only add new modalities...
  without introducing new driving episodes"). A system that answers "zero, per the paper" would
  be fully grounded, not fabricating — arguably not the same failure mode as a true refuse-to-
  answer case. Author A's own verdict acknowledges this. Left as `accepted` but flagged; an
  operator should decide whether "a stated zero" belongs in this eval's absent bucket at all.
- **`Q-WA4-A-004`** and **`Q-WA4-B-FINAL-003`** — both authors' own self-flagged doubts,
  independently re-probed in Stage C and confirmed correct as worded (see above). Not uncertain
  anymore; recorded here because the ticket asked for them by name.

## Bottom line

33 items checked (21 + 12). Zero mechanical (Stage B) failures on the original five checks in
either set. Adding a hit-count re-verification (not in the original five, added after Stage C
found the need for it) surfaced stale probe logging in 4 of Set B's 12 items. Stage C's adversarial
re-probing — full-paper reads for every absent sub-part in both sets, cross-paper term checks for
named-entity absences, and targeted semantic round trips for the two self-flagged items — falsified
**2 of 33 absence claims (6%), both in Set B, both on papers the item's own gold-ref chunk did not
fully cover**. Stage D confirmed the checker itself is not a rubber stamp (3/3 injected corruptions
caught). Final usable set: **31 items across 22 papers** (28 accepted, 3 accepted with a logged,
verdict-unchanged correction), plus 2 rejected items preserved in the adjudicated file with their
falsifying evidence for the record.
