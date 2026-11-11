# Topic-focus baseline (`papers`): does retrieval stay on focus? First measurement, 2026-11-11

Protocol: `2026-11-10-topic-focus-benchmark-protocol.md` (frozen; includes the EV-11 addendum of 2026-11-11 that
froze the focus hash and fixed the set at 49 items). Runbook step 1b. Numbers are counts and ratios with the
source file named. The focus set is LLM-authored and same-family verified; 3 of 26 collision traps are strong,
20 moderate, 3 weak (addendum), so a low contamination here is weak evidence of topic robustness.

## 1. Run identity and validity

| item | value | source |
|---|---|---|
| code commit | `626fac3555a386076944d106254354ad66b2dfa7`, `code_tree_dirty = false` | `GIT_COMMIT`, `focus.json` |
| run directory | `docs/eval-reports/data/2026-11-10-papers-passage-gt/runs/20261111T012931` (untracked; not committed) | |
| window | 2026-11-11 01:29:31 to 01:32:14 (-07:00), 2 min 43 s | `MANIFEST.txt` |
| collection / config | `papers`, shipped config (`rerank_depth 32`, `hybrid_dense_weight 0.5`, fused) | `MANIFEST.txt`, `config-shipped.yaml` |
| point-count guard | 412,167 points; DB 399,676 chunks, 12,390 papers; plausible | `scratchpad/baseline_focus.log` |
| errors, validity | `n_questions 49`, `n_errors 0`, `run_valid true`, `n_lock_timeouts 0`, 0 ambiguous or unresolved chunk-id rows | `focus.json` |
| fixture hashes | `focus_gt.json` `c68210e06a9f5c9a…` and `topic_labels.tsv` `c14cf1ebafc010f4…` match `data/2026-11-10-FIXTURE-HASHES.json`; report GT hash `c68210e06a9f`; hashes file `7f2fa1fc352f…`; run log `hash check OK (2 fixtures)`; today `check-hash` printed `hash check OK (10 fixtures)` | `MANIFEST.txt`, `focus.json` |

The focus set is 49 items: collision 26, offtopic-legit 14 (answerable 40), focus-absent 9. Wilson hw at p = 0.5
(`eval_protocol_tools.py wilson`): collision 0.18, offtopic-legit 0.23; absent n = 9 is below 10 and descriptive only.

## 2. Frozen metrics (protocol 3), shipped config

Source: `strata-focus.txt` and `strata-focus.json`.

| metric | stratum | n | value | count and ratio |
|---|---|---|---|---|
| off-topic contamination@10 (mean off share of top-10 slots) | focus, on-gold answerable (= the 26 `collision` items) | 26 | **0.100** | mean of per-question shares |
| off-at-rank-1 rate | same | 26 | 0.000 | 0/26 |
| distractor-outranks-gold rate | `collision` | 26 | 0.000 | 0/26 |
| lookalike-outranks-gold rate | `offtopic-legit` | 14 | 0.000 | 0/14 |
| on-topic member hit@10 | `collision` | 26 | 0.808 | 21/26 |
| on-topic member P@1 | `collision` | 26 | 0.615 | 16/26 |
| `offtopic-legit` member hit@10 | `offtopic-legit` | 14 | 0.929 | 13/14 |
| `offtopic-legit` member P@1 | | 14 | 0.571 | 8/14 |
| paper Recall@10 | `collision` / `offtopic-legit` | 26 / 14 | 0.923 / 1.000 | 24/26 / 14/14 |
| paper P@1 | `collision` / `offtopic-legit` | 26 / 14 | 0.808 / 1.000 | 21/26 / 14/14 |
| anchor hit@10 (stock) | `collision` / `offtopic-legit` | 26 / 14 | 0.808 / 0.929 | 21/26 / 13/14 |
| stub share | rank-1 / top-10 slots | 49 / 490 | 0.000 / 0.004 | 0/49 / 2/490 |

Chance references printed by the script: corpus off share 4,630 / 12,385 = 0.374 (paper level); chunk-weighted 0.323
(protocol 3.7). Contamination is a mean with no interval, so it is compared by counts only. Member misses (6 of 40
answerable): Q-FOC-007, -010, -011, -014, -020, -035 (computed by `data/2026-11-11-baseline-analysis/focus_paired_misses.py`,
output `focus_paired_misses.out.txt`). Paper-level misses (2): Q-FOC-011, Q-FOC-020. The distractor rule counts "both
missing" as not outranked, so the 0/26 sits beside a recall of 24/26: in those two items no distractor was in the top 10 either.

**Absent arm (focus-absent, n = 9, descriptive).** RRF fusion score, top-1: min 0.00671 / median 0.00771 / max 0.01430
against the answerable arm (n = 40) 0.00701 / 0.00884 / 0.01613. Nearest distractor at rank 1: 0/9. The score cannot
separate absent from answerable (protocol 3.6; reranker-score census not run).

### 2.1 Secondary check: the papers set (same run family, run `20261111T004734`)

Source `strata-papers.txt` (authored) and `strata-papers.ablated.txt`. Never averaged with the focus-set numbers.

| set | n (on-gold answerable) | mean off share of top-10 | off at rank 1 |
|---|---|---|---|
| papers, authored | 38 | 0.118 | 0/38 = 0.000 |
| papers, title-ablated | 38 | 0.161 | 3/38 = 0.079 |

By dimension, papers authored: equation-context 5 items 0.060, method-detail 13 items 0.138, numeric-result 10 items
0.110, paper-passage 10 items 0.130; off at rank 1 is 0 in each. Ablated: 0.220 / 0.146 / 0.180 / 0.130 with off at
rank 1 in 1/5, 1/13, 0/10, 1/10. The papers `paper_topic = off` stratum is reported in the main-corpus baseline
(`2026-11-11-main-corpus-baseline.md`: member hit@10 16/17).

## 3. Verdict bands (protocol 4, descriptive, pre-committed)

| band | test | focus set (n = 26) | papers set (n = 38) |
|---|---|---|---|
| "Retrieval stays on focus" | contamination@10 <= 0.162 AND off-at-rank-1 <= 0.187 | 0.100 <= 0.162 and 0.000 <= 0.187: **met** | 0.118 <= 0.162 and 0.000 <= 0.187: **met** |
| "partly" | between those and the references | not applicable | not applicable |
| "no" | at or above a reference (0.323 chunk-weighted for contamination, 0.374 for rank 1) | not reached | not reached |

By the pre-committed language, "retrieval stays on focus" may be written for the baseline. These are descriptive
bands, not gates. The protocol's stated prior for good retrieval was contamination of about 0.00 to 0.05 on ordinary
on-gold items; the measured values (0.100 focus, 0.118 papers) are above that prior and the protocol asked that a
surprising baseline be recognised as such. The ablated papers run is higher still (0.161, off at rank 1 3/38), which
is at the edge of the 0.162 band for contamination (0.161 <= 0.162) and passes the rank-1 band (0.079 <= 0.187).
The ablated numbers are a control, not the verdict.

## 4. Comparison with the BM25 floor (post-hoc extension of EV-15)

EV-15 did not run `focus_gt.json` (it was under repair then). The protocol (7 ii) says the BM25 floor for focus
must also output the off share of its top 10. I ran the committed `scripts/bm25_floor.py` on the frozen
`focus_gt.json` (fixture hash checked first, DB read-only, CPU, 23 s) and `scripts/eval_strata_report.py` with the topic
labels. Outputs, new and committed in `docs/eval-reports/data/2026-11-10-bm25-floor/`: `focus-standard.report.json`,
`focus-standard.strata.txt` / `.json`, and `papers-standard.strata-with-topic-labels.txt` (the existing papers BM25 report
re-scored with labels for the papers-set row). Reproduce with the commands in 7.

| metric | system | BM25 floor |
|---|---|---|
| contamination@10, focus on-gold (n = 26) | **0.100** | **0.023** |
| off at rank 1 | 0/26 | 0/26 |
| contamination@10, papers on-gold (n = 38) | 0.118 | 0.042 (`papers-standard.strata-with-topic-labels.txt`) |
| distractor outranks gold (`collision`, 26) | 0/26 | 0/26 |
| lookalike outranks gold (`offtopic-legit`, 14) | 0/14 | 0/14 |
| `collision` member hit@10 / P@1 | 21/26 = 0.808 / 16/26 = 0.615 | 20/26 = 0.769 / 10/26 = 0.385 |
| `offtopic-legit` member hit@10 / P@1 | 13/14 = 0.929 / 8/14 = 0.571 | 12/14 = 0.857 / 4/14 = 0.286 |
| paper R@10 `collision` / `offtopic-legit` | 24/26 / 14/14 | 24/26 / 14/14 |
| stub share, top-10 slots | 2/490 = 0.004 | 11/490 = 0.022 |

The BM25 top-10 holds about a quarter (focus 0.023 against 0.100) to a third (papers 0.042 against 0.118) of the
off-topic share the system's top-10 holds. BM25 sits inside the protocol prior (0.00 to 0.05); the system is above it.
Both are far under the topic-blind references (0.323, 0.374).

### 4.1 Per-question overlap of member misses (post-hoc, descriptive, 40 answerable items)

| | system | BM25 | both | system only | BM25 only |
|---|---|---|---|---|---|
| misses | 6 | 8 | 3 | 3 | 5 |

Both: Q-FOC-007, -011, -014. System only: Q-FOC-010, -020, -035. BM25 only: Q-FOC-012, -017, -024, -037, -039.
Source `focus_paired_misses.out.txt`.

## 5. Pre-registered rules evaluated

| id | rule | verdict |
|---|---|---|
| F1 | Verdict language: "stays on focus" only if contamination@10 <= 0.162 and off-at-rank-1 <= 0.187 (protocol 4) | Met on focus set (0.100, 0/26) and papers set (0.118, 0/38). |
| F2 | Floor clause: baseline focus contamination <= 0.04 means REJECT for a lever (protocol 4, 6.1) | Not triggered: baseline is 0.100. No lever was run; the clause concerns R-demote only. |
| F3 | R-demote adoption rule, conditions 1 to 5 (protocol 6) | **Not evaluated.** No R-demote arm exists in this run. RQ-2 (opt-in demotion code) has merged but RQ-3 (the A/B) has not run. The baseline counts that RQ-3 will be judged against are in 2 and in `2026-11-11-main-corpus-baseline.md` (papers `on` member hit@10 30/38, `off` 16/17). |
| F4 | n < 10 strata descriptive only (protocol 2) | focus-absent (n = 9) is descriptive; excluded from every rule. |
| F5 | Never blend focus-set and papers-set numbers (protocol 5) | Respected; 2 and 2.1 are separate tables. |

One ambiguity: the F2 floor clause says "baseline focus-set contamination@10 is <= 0.04 the answer is REJECT (nothing to
fix)". The protocol does not say what to do when the baseline is above 0.04 but already "stays on focus" by the band in
section 4. F3's conditions and the adoption rule are written without a lower bound beyond the 0.04 floor. I did not
choose a reading; the question belongs to the RQ-3 pre-registration.

## 6. Caveats

- n = 26 and 14; one item moves a rate by 3.8 and 7.1 points. Contamination is slot-based: one off-topic paper
  can occupy several slots, so the mean is inflated by repeated papers. Distinct-paper contamination is not computed.
- Trap strength: 3 strong / 20 moderate / 3 weak. A retriever that reads causal context is hardly tempted by moderate
  traps, so 0/26 distractor-outranks-gold shows no gross failure and little more.
- The system's off share is higher than BM25's although the system's recall and P@1 are higher. This is not
  explained here; the likely reading (the semantic dense arm and reranker pull in semantically near but off-topic
  chunks, while BM25 needs the shared words) is a hypothesis, not tested.
- Labels: weighted kappa 0.90 by the same model family that labelled; 5 of 12,390 papers unlabelled count as "not off".
- BM25 here has no ligature repair and its row for focus was run after the system baseline (post-hoc extension, not
  frozen in the protocol beyond the 7 ii requirement); no fixture was changed in response to either result.
- The run directory is untracked; analysis files are in `docs/eval-reports/data/2026-11-11-baseline-analysis/`.

## 7. Reproduce the BM25 focus row

```
D=docs/eval-reports/data
python scripts/bm25_floor.py --ground-truth $D/2026-11-10-focus-gt/focus_gt.json \
  --db /home/omar/ai-projects/research-system-rag-data/papers.db --k 10 --variant standard \
  --report-path $D/2026-11-10-bm25-floor/focus-standard.report.json
python scripts/eval_strata_report.py --ground-truth $D/2026-11-10-focus-gt/focus_gt.json \
  --db /home/omar/ai-projects/research-system-rag-data/papers.db \
  --topic-labels $D/2026-11-10-topic-labels/topic_labels.tsv --k 10 \
  $D/2026-11-10-bm25-floor/focus-standard.report.json
```
