# Standards baseline (`av_standards`): passage retrieval and the rerank-depth rule, first measurement, 2026-11-11

Protocol: `2026-11-10-standards-benchmark-protocol.md` (frozen; includes the EV-11 addendum of 2026-11-11 that added 3
alternatives to the fixture and changed its hash to `09b1061198c9`). Runbook step 1c. Counts and ratios, source
file named for each. Items are LLM-authored and same-family verified, and questions are about twice as long as logged queries.
Arms are reported separately and never averaged.

## 1. Run identity and validity

| item | value | source |
|---|---|---|
| code commit | `626fac3555a386076944d106254354ad66b2dfa7`, `code_tree_dirty = false` in all reports | `GIT_COMMIT`, `MANIFEST.txt`, each `*.json` |
| run directory | `docs/eval-reports/data/2026-11-10-standards-gt/runs/20261111T013215` (untracked; not committed) | |
| window | 2026-11-11 01:32:22 to 02:35:29 (-07:00), 63 min 7 s | `MANIFEST.txt` |
| collection / DB | `av_standards`; `/home/omar/ai-projects/research-system-rag-standards/data/papers.db` | `MANIFEST.txt` |
| configs | `config-shipped.yaml` equals `config-depth128.yaml` (`rerank_depth 128`); `config-depth64.yaml`, `config-depth32.yaml` differ only in `rerank_depth` (64, 32); weight 0.5 | `diff` of the four files |
| point-count guard | 36,031 points; DB 35,714 chunks, 119 papers; "plausible". 36,031 is 198 above chunks + summaries (0.55%), inside the 1% tolerance; not investigated | `scratchpad/baseline_standards.log` |
| errors, validity | in all 12 report files (6 authored arms incl. `depth128-fused-repeat`, 5 ablated): `n_errors = 0`, `run_valid = true`, `n_lock_timeouts = 0`, 0 unresolved chunk ids. One ablated report (`depth128-dense_only.ablated.json`) has `n_chunk_id_ambiguous_rows = 1` (a marker, not an error) | each `*.json` |
| fixture hash | `standards_gt.json` `09b1061198c9817b…` matches `data/2026-11-10-FIXTURE-HASHES.json`; every authored report carries GT hash `09b1061198c9`; ablated reports `af20df8212f2` (derived file, 86 items, omitted: 20 no document name, 22 not answerable); hashes file `7f2fa1fc352f…` as in `MANIFEST.txt`; run log `hash check OK (1 fixtures)`, `128 items, 0 failures`; today `check-hash` printed `hash check OK (10 fixtures)` | `MANIFEST.txt`, reports, `baseline_standards.log` |

Arms (file name prefix, `--sparse-mode`, depth, weight 0.5): `depth128-fused` (shipped), `depth128-fused-repeat`
(jitter), `depth64-fused`, `depth32-fused`, `depth128-dense_only`, `depth128-sparse_only`; each also `.ablated`
except the repeat. Strata: `strata.txt` / `strata.json` (authored), `strata.ablated.txt` / `.json`,
`strata-n-and-halfwidth.txt`.

## 2. Per-arm summary

Passage items are the 94 answerable items carrying a gold block; ablated runs use the 86 items that keep a document
name (the five shared dimensions). Member hit@10 is the metric of record (protocol 3.1). Paper R@10 is over the 106
answerable (authored) or 86 (ablated), a tripwire only.

| arm | member hit@10 (94) | member P@1 | anchor hit@10 | excerpt hit@10 | paper R@10 (106) | stub top-10 slots | ablated member hit@10 (86) | ablated member P@1 | ablated anchor | ablated paper R@10 (86) |
|---|---|---|---|---|---|---|---|---|---|---|
| `depth128-fused` (shipped) | **84/94 = 0.894** | 52/94 = 0.553 | 83/94 = 0.883 | 83/94 | 102/106 = 0.962 | 5/1280 = 0.004 | 68/86 = 0.791 | 47/86 = 0.547 | 67/86 | 78/86 = 0.907 |
| `depth128-fused-repeat` | 84/94 = 0.894 | 52/94 | 83/94 | 83/94 | 102/106 | 5/1280 | not run | not run | not run | not run |
| `depth64-fused` | 83/94 = 0.883 | 52/94 | 82/94 | 82/94 | 102/106 | 6/1280 | 69/86 = 0.802 | 47/86 | 68/86 | 80/86 |
| `depth32-fused` | 81/94 = 0.862 | 52/94 | 79/94 | 80/94 | 103/106 = 0.972 | 7/1280 | 65/86 = 0.756 | 49/86 | 64/86 | 80/86 |
| `depth128-dense_only` | 84/94 = 0.894 | 52/94 | 83/94 | 83/94 | 101/106 | 4/1280 | 68/86 = 0.791 | 46/86 | 67/86 | 76/86 |
| `depth128-sparse_only` | 65/94 = 0.691 | 47/94 | 64/94 | 64/94 | 99/106 | 1/1280 | 52/86 = 0.605 | 41/86 | 51/86 | 73/86 |
| BM25 floor (refrozen fixture) | 62/94 = 0.660 | 25/94 = 0.266 | 60/94 | n/a | 104/106 = 0.981 | 19/1280 | n/a (anchor 57/86 = 0.663) | n/a | 57/86 | 75/86 = 0.872 |

Sources: pooled member counts are the sum of the member columns in `strata.txt` / `strata.ablated.txt`, cross-checked
per question by `data/2026-11-11-baseline-analysis/standards_paired_arms.py` (output `standards_paired_arms.out.txt`:
H = 84, 84, 83, 81, 84, 65 and ablated 68, 69, 65, 68, 52). Anchor, excerpt and paper-level counts from each arm's
`passage_level`, `passage_excerpt_level`, `paper_level.by_gold_status.answerable`. BM25: see 5. The shipped arm and the
repeat are identical in every count above.

## 3. Shipped arm (`depth128-fused`), per stratum

Source `strata.txt`, first block. hw is Wilson at p = 0.5 (`strata-n-and-halfwidth.txt`).

| dimension (role) | n | hw | member hit@10 | member P@1 | anchor hit@10 | anchor P@1 | paper R@10 | paper P@1 |
|---|---|---|---|---|---|---|---|---|
| book-passage (gating) | 26 | 0.18 | 23/26 = 0.885 | 11/26 = 0.423 | 23/26 | 11/26 | 26/26 | 25/26 |
| clause-lookup (gating; instrument-saturated) | 18 | 0.21 | 18/18 = 1.000 | 16/18 = 0.889 | 18/18 | 16/18 | 18/18 | 17/18 |
| table-requirement (gating) | 16 | 0.22 | 16/16 = 1.000 | 7/16 = 0.438 | 15/16 | 6/16 | 16/16 | 13/16 |
| guidance-factual (gating; instrument-saturated) | 14 | 0.23 | 13/14 = 0.929 | 12/14 = 0.857 | 13/14 | 12/14 | 14/14 | 14/14 |
| definition-lookup (gating) | 12 | 0.25 | 8/12 = 0.667 | 1/12 = 0.083 | 8/12 | 1/12 | 10/12 | 5/12 |
| cross-document (paper level only) | 12 | n/a | no passage gold | | | | 12/12 | 7/12 |
| authority (descriptive only) | 4 | 0.35 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| edition (descriptive only) | 4 | 0.35 | 2/4 | 1/4 | 2/4 | 1/4 | 2/4 | 1/4 |
| pooled passage items, not a headline | 94 | 0.10 | 84/94 = 0.894 | 52/94 = 0.553 | 83/94 | 51/94 | | |

Pooled paper-level (answerable, 106): R@10 102/106 = 0.962, P@1 86/106 = 0.811 (sum of the paper columns).

Protocol 3 descriptive metrics, shipped arm (`strata.txt`):
- **Authority / edition.** Commentary document outranks gold: 0/4. Other edition outranks gold: 2/4. Descriptive (n = 4).
- **Stub analysis.** Rank-1 stub 1/128 = 0.008; top-10 slots 5/1280 = 0.004.
- **Cross-document** (items with more than one gold paper: 15, the script's count, against the protocol's 12): all gold
  in top 10: 8/15 = 0.533; at least one: 15/15 = 1.000.
- **Chapter level** (heading-string match; never a gate): 1/14 = 0.071 (`depth128-fused.json` `chapter_level`).

### 3.1 Absent arm (RRF fusion score, ceiling 0.0164; protocol 3.7)

Not an abstention test. The 9 absent and the 13 partial-absent items are reported apart (`dimension` field of the
fixture, computed from each arm's rows; the stock `strata.txt` prints their union of 22). Top-1 score min / median / max.

| arm | absent (9) | nearest distractor at rank 1 | partial-absent (13) | nearest distractor at rank 1 | answerable (106) |
|---|---|---|---|---|---|
| `depth128-fused` | 0.00662 / 0.00904 / 0.01495 | 3/9 | 0.00755 / 0.01129 / 0.01528 | 6/13 | 0.00434 / 0.01320 / 0.01639 |
| `depth64-fused` | 0.00662 / 0.00904 / 0.01495 | 3/9 | 0.00755 / 0.01129 / 0.01528 | 6/13 | 0.00730 / 0.01344 / 0.01639 |
| `depth32-fused` | 0.00753 / 0.00904 / 0.01495 | 3/9 | 0.00755 / 0.01208 / 0.01528 | 6/13 | 0.00756 / 0.01412 / 0.01639 |
| `depth128-dense_only` | 0.00543 / 0.01538 / 0.01639 | 3/9 | 0.01190 / 0.01493 / 0.01639 | 6/13 | 0.00654 / 0.01613 / 0.01639 |
| `depth128-sparse_only` | 0.00613 / 0.01266 / 0.01639 | 4/9 | 0.00549 / 0.01064 / 0.01563 | 5/13 | 0.00575 / 0.01333 / 0.01639 |

The absent ranges lie inside the answerable ranges in every arm. The absent n = 9 is below 10 (descriptive).

## 4. Pre-registered decision rules

### 4.1 D-1 (keep `rerank_depth` 128 only if all four hold)

H(d) = member hit@10 count over the 94 passage-scored answerable items, authored questions. Gating strata (n >= 10):
book-passage, clause-lookup, table-requirement, guidance-factual, definition-lookup. Authority and edition (n = 4)
cannot gate.

Authored member hit@10 per stratum (counts of n):

| stratum (n) | 128 | 64 | 32 | 128 minus 32 |
|---|---|---|---|---|
| book-passage (26) | 23 | 23 | 21 | +2 |
| clause-lookup (18) | 18 | 18 | 18 | 0 |
| table-requirement (16) | 16 | 15 | 15 | +1 |
| guidance-factual (14) | 13 | 13 | 13 | 0 |
| definition-lookup (12) | 8 | 8 | 8 | 0 |
| authority (4), descriptive | 4 | 4 | 4 | 0 |
| edition (4), descriptive | 2 | 2 | 2 | 0 |
| H over 94 | **84** | 83 | **81** | **+3** |

Ablated member hit@10 per stratum (86 items; `strata.ablated.txt`): book-passage 15 / 15 / 16 for 128 / 64 / 32,
clause-lookup 16 / 16 / 16, definition-lookup 9 / 10 / 8, guidance-factual 12 / 12 / 11, table-requirement 16 / 16 / 14;
H_abl 68 / 69 / 65.

| # | condition | measured | verdict |
|---|---|---|---|
| 1 | H(128) - H(32) >= 2 | 84 - 81 = **+3** | **holds** |
| 2 | no gating stratum has H_s(32) - H_s(128) >= 2 | worst per-stratum difference is 0 (book-passage and table-requirement favour 128: +2, +1) | **holds** |
| 3 | on ablated questions, H_abl(128) - H_abl(32) >= -1 | 68 - 65 = **+3** | **holds** |
| 4 | validity: both arms `n_errors = 0`, point-count check passed, fixture hash matched, repeat of `depth128-fused` differs on <= 1 question of H | all arms `n_errors = 0`; guard passed (36,031 points); hash matched; repeat differs on **0** questions of H (7 of 128 questions have different top-10 block lists in the repeat; none changes a hit) | **holds** |

**D-1 verdict: all four hold, so `rerank_depth` stays at 128. No default changes.** Ties would have gone to 32; this is
not a tie. Depth 64 (H = 83, H_abl = 69) is reported and is not an eligible outcome under the rule.

Paired flips, 128 versus 32 (`standards_paired_arms.out.txt`): authored, 4 items only 128 hits (Q-STD-A-014, B-022,
D-020, D-022) and 1 only 32 hits (A-021); ablated, 4 only 128 (A-013, A-014, A-020, B-017) and 1 only 32 (D-011). The
protocol states the 2-question rule is a burden-of-proof rule and not a significance test; a 4:1 split is not
significant by a sign test and was not claimed to be. P@1 is level (52/94 in both). Anchor-rule hit@10 is 83 against 79
(+4); the excerpt metric 83 against 80 (+3).

### 4.2 S-1 (sparse-arm falsifier: `dense_only` against `fused`, both at depth 128)

| | authored (94) | ablated (86) |
|---|---|---|
| H(`dense_only`) | 84 | 68 |
| H(`fused`) | 84 | 68 |
| net | 0 | 0 |

"Not replicated" needs `dense_only` to lose >= 5 net on authored AND ablated: not met (0, 0). "Replicated" needs
`dense_only` >= `fused` + 2 on both: not met (0, 0). **S-1 verdict: unresolved. No weight change follows from it.**
Flips: authored, 1 only `dense_only` (Q-STD-C-017), 1 only `fused` (A-022); ablated, 4 and 4. Descriptive: `sparse_only`
is 19 below `fused` authored (65 against 84; 20 only-fused, 1 only-sparse) and 16 below ablated (52 against 68).

### 4.3 Other protocol rules

- **Ablated reporting rule (7 i).** Pooled over the five shared dimensions, `depth128-fused` authored member hit is
  78/86 = 0.907 against ablated 68/86 = 0.791 (difference 0.116 > 0.10). **The headline is the lower arm, 0.791**; both are quoted.
- **"Retrieval is semantic, not title lookup" claim (7 i).** Needs ablated paper-level R@10 within 0.05 of authored on the
  same items: authored 84/86 = 0.977 against ablated 78/86 = 0.907 (difference 0.070). **Not met.** The claim may not be made.
- **Instrument-informative criterion (7 ii; floor chunk@10 <= 0.80 on the stratum a claim is about).** BM25 on this fixture,
  member hit (exact-chunk in brackets where it differs): book-passage 9/26 = 0.346 (informative), definition-lookup 6/12 = 0.500
  (informative), table-requirement 14/16 = 0.875 [12/16 = 0.750 exact chunk] (informative on the exact-chunk definition,
  above the bar on member hit), clause-lookup 16/18 = 0.889 and guidance-factual 13/14 = 0.929 (**instrument-saturated**: they
  can show a loss, never a gain), edition 0/4 (n = 4, descriptive). The protocol names the exact-chunk definition for the floor.
- **Small-strata rule.** Authority and edition (4 each), absent (9) and cross-document (no passage gold) are excluded from
  D-1 and S-1; they appear above as descriptive.

## 5. Comparison with the BM25 floor

BM25 source: `docs/eval-reports/data/2026-11-10-bm25-floor/` (EV-15, `2026-11-10-bm25-floor.md`). The committed
`standards-standard.strata.txt` reports member hit 61/94 (table-requirement 13/16). It was run before the EV-11 refreeze
reached that branch: the retrieved lists are identical (0 of 128 questions differ) and a re-run on today's fixture gives
62/94 (table-requirement 14/16), the only change being the 3 alternatives EV-11 added. I re-ran `scripts/bm25_floor.py`
and `eval_strata_report.py` on today's fixture (CPU, DB read-only) into `standards-standard-refrozen-fixture.report.json`
and `.strata.txt` / `.json` in the same folder; the table below uses that file. Reason for the choice stated here, not
hidden: the system numbers are on the refrozen fixture, so the floor must be too. The ablated BM25 row is the committed
anchor-rule number (57/86), unaffected by alternatives.

| stratum | n | system member hit@10 (`depth128-fused`) | BM25 member hit@10 | system member P@1 | BM25 member P@1 |
|---|---|---|---|---|---|
| book-passage | 26 | 23/26 = 0.885 | 9/26 = 0.346 | 11/26 | 2/26 |
| clause-lookup | 18 | 18/18 = 1.000 | 16/18 = 0.889 | 16/18 | 9/18 |
| table-requirement | 16 | 16/16 = 1.000 | 14/16 = 0.875 | 7/16 | 4/16 |
| guidance-factual | 14 | 13/14 = 0.929 | 13/14 = 0.929 | 12/14 | 8/14 |
| definition-lookup | 12 | 8/12 = 0.667 | 6/12 = 0.500 | 1/12 | 1/12 |
| authority (4) / edition (4) | | 4/4 / 2/4 | 4/4 / 0/4 | 4/4 / 1/4 | 1/4 / 0/4 |
| pooled, 94 | 94 | 84/94 = 0.894 | 62/94 = 0.660 | 52/94 = 0.553 | 25/94 = 0.266 |

Per question (member hit@10, 94 items; `standards_paired_arms.out.txt`, fused vs the BM25 report scored with today's
fixture): 22 items only the system hits, 0 items only BM25 hits, 62 both, 10 neither. Every BM25 hit is also a system hit.
Paper R@10: system 102/106 = 0.962, BM25 104/106 = 0.981. Ablated: system anchor 67/86 = 0.779 against BM25 57/86 = 0.663;
paper R@10 78/86 = 0.907 against 75/86 = 0.872.

## 6. Caveats

- D-1 conditions 1 and 3 pass with +3 against a threshold of +2 and rest on 4:1 pairings: one more lost question would
  still have passed (+2), two would have failed. The rule was pre-registered and is applied as written.
- Interpretation points in D-1 the protocol does not spell out, resolved here by the most literal reading and stated:
  (a) condition 3's H_abl is pooled over the 86 ablated items; (b) condition 2 uses authored per-stratum counts (ablated
  per-stratum counts are shown and also show no loss of 2 at 128); (c) condition 4's "differs on <= 1 question of H"
  is read as flips in the hit indicator, which is 0, while 7 of 128 questions retrieved different top-10 block lists.
- Over-count (shared anchors, protocol 3.1) and under-count (unrecorded duplicates) bound the member metric within about
  4 questions; the anchor-rule counts (83 against 79, +4) point the same way as the member counts for 128 against 32.
- The member-rule count of cross-document items is 15 in the script (items with more than one gold paper), not 12.
- Authority and edition are n = 4; the edition-outranks figure (2/4 at 128, 64 and dense-only, 0/4 at 32 and sparse-only) is anecdote.
- The three dimension strata with BM25 above 0.80 cannot support a gain; the two gating strata with real headroom are
  book-passage and definition-lookup (definition member P@1 is 1/12).
- 198 points beyond chunks + summaries in the collection are unexplained here.
- Not in this report: the EV-18 structure-gate count (qualifying misses for the CQ-12 trigger, from per-row chunk ids and
  chunk-quality rules) and the CQ-19 authority trigger judgement. The per-row data they need are in the run directory.
- Items are LLM-authored, same family verified; ablation over-ablates. No answer quality, no abstention (fusion-score
  display only), no groundedness.
- The run directory is untracked; analysis files are in `docs/eval-reports/data/2026-11-11-baseline-analysis/`.
