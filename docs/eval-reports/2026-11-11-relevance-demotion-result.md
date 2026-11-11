# Relevance-demotion A/B (RQ-3, using the RQ-2 lever): result, 2026-11-11

**Verdict (pre-registered rule): REJECT for all three arms (tail@0.25, tail@0.30, penalty@0.30 p=5).** No arm passed; the lever
stays default-off. No arm reduced focus contamination@10 at all (every arm is at or above the baseline 0.100).

Pre-registration: `docs/eval-reports/2026-11-11-rq3-relevance-demotion-prereg.md`. Register: `EXPERIMENT-REGISTER.md`.

## 1. Question asked

Does demoting (never dropping) below-threshold `relevance_score` papers after reranking keep retrieval on the causal-methods
focus (lower off-topic share in the top-10) without hiding legitimate off-topic papers or damaging on-topic retrieval?

## 2. What was run

| item | value | source |
|---|---|---|
| code commit | `03cfd1854b7d37c8116d35545c3f54a309e6da40` (lever merged, default off) | `GIT_COMMIT` |
| window | 2026-11-11 11:15:52 to 11:59:18 (-07:00), 43 min 26 s (prereg estimate about 44 min) | `MANIFEST.txt` |
| collection / db | `papers`, `/home/omar/ai-projects/research-system-rag-data/papers.db`, shipped config | `MANIFEST.txt`, `config-shipped.yaml` |
| fixtures + hash check | `focus_gt.json` `c68210e0...` (49 items), `papers_passage_gt.json` `58cdbf47...` (61, split by `paper_topic`: on 38 / off 17 / borderline 6), `causal_books_gt.json` `3c21d57b...` (74), `topic_labels.tsv` `c14cf1eb...`, hashes file `7f2fa1fc...`; all in MANIFEST, checked before any service call | `MANIFEST.txt` |
| arms (back to back, one commit, baseline re-run) | baseline; `tail` tau 0.25; `tail` tau 0.30; `penalty` tau 0.30 p = 5. 184 queries per arm x 4 | `MANIFEST.txt` |
| errors | 0 in every arm; 10.00 results per question in every arm (no pool starvation) | `COMPARISON.md` columns `errors`, `results/q` |

Evidence committed in full (3.2 MB): `docs/eval-reports/data/2026-11-10-focus-gt/runs-rq3/20261111T111549/` (`COMPARISON.md`,
per-arm reports, strata, split files, config). Console log: `.../scratchpad/q3_demotion.log`.

## 3. Results (source: `COMPARISON.md`, the mechanical output of `scripts/relevance_demotion_ab_table.py`)

| arm | contam@10 focus (n 26) | off@rank1 focus | contam@10 papers (on-gold, n 38) | collision hit /26 | papers-on hit /38 | papers-off hit /17 | books hit /74 | legit recall /14 | dist>gold | lookalike>gold | errors |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 0.100 | 0 | 0.118 | 21 (0.808) | 30 (0.789) | 16 (0.941) | 54 (0.730) | 14 (1.000) | 0 | 0 | 0 |
| penalty-0.30-p5 | 0.112 | 0 | 0.126 | 21 | 30 | 16 | 54 | 14 | 0 | 0 | 0 |
| tail-0.25 | 0.112 | 0 | 0.116 | 20 | 30 | 12 | 54 | 8 | 0 | 0 | 0 |
| tail-0.30 | 0.154 | 1 | 0.142 | 19 | 29 | 8 | 54 | 8 | 0 | 0 | 0 |

Per-arm verdict column of `COMPARISON.md`: baseline (comparator), penalty REJECT, tail-0.25 REJECT, tail-0.30 REJECT.

## 4. Rules evaluated literally (protocol section 6 restated in the prereg, section 5)

Floor clause: baseline focus contamination@10 is 0.100, above 0.04, so the "nothing to fix" REJECT does not apply; the arms were
judged on the clauses. Clause 1 bar: focus contamination <= 0.5 x 0.100 = 0.050 AND papers contamination not above 0.118.

| clause | penalty-0.30-p5 | tail-0.25 | tail-0.30 |
|---|---|---|---|
| 1 focus contamination <= 0.050 | 0.112 FAIL | 0.112 FAIL | 0.154 FAIL |
| 1 papers contamination does not rise (0.118) | 0.126 FAIL | 0.116 pass | 0.142 FAIL |
| 2 collision hit drop <= 1 (of 26) | 0 pass | -1 pass | -2 FAIL |
| 2 papers-on hit drop <= 1 (of 38) | 0 pass | 0 pass | -1 pass |
| 2 books hit drop <= 1 (of 74) | 0 pass | 0 pass | 0 pass |
| 3 offtopic-legit paper recall drop <= 1 (of 14) | 0 pass | -6 FAIL | -6 FAIL |
| 3 papers-off hit drop <= 1 (of 17) | 0 pass | -4 FAIL | -8 FAIL |
| 4 distractor-outranks-gold and lookalike-outranks-gold rise <= 1 | 0, 0 pass | 0, 0 pass | 0, 0 pass |
| 5 validity (errors 0, hashes, point-count guard, back to back) | pass | pass | pass |
| **result** | **REJECT (clause 1)** | **REJECT (clauses 1, 3)** | **REJECT (clauses 1, 2, 3)** |

The failing-clause lists match the `COMPARISON.md` footer lines exactly. "Among passing arms prefer the smaller tau" does not
apply (no arm passed). Prereg section 3 predicted that tail arms would breach the legitimate-off-topic guard (9 to 11 of 14
`offtopic-legit` gold below tau); the observed recall drops (14 -> 8) are within that prior. The prereg had no prediction that
contamination would not fall.

## 5. Validity and caveats

- Errors 0, 10.00 results per question, hashes and point counts matched. No separate jitter arm: the baseline arm was re-run in the
  same script at the same commit, so arm differences are paired on identical questions.
- Contamination is a mean over 26 (focus) and 38 (papers) questions with no interval from the stock script; a question's share moves
  in steps of 0.1 to 0.25. The differences 0.100 vs 0.112 are one or two question-level share steps.
- Only 3 of 26 collision traps are strong, 20 moderate, 3 weak (addendum): baseline contamination is already low, so "REJECT" here
  means this lever did not help on this fixture, not that the corpus mix is harmless for real queries (prereg section 7).
- The mechanism by which contamination failed to fall although offline 51.8% (tau 0.25) and 72.3% (tau 0.30) of collision
  distractor papers lie below tau (prereg section 3) was not investigated here.
- Demotion acts only inside the 32-result rerank pool; a payload-index / full-corpus filter route is a different, unmeasured arm.
- `focus-absent` (n 9) and `borderline` (n 6) are descriptive only and never gate.

## 6. Do not re-run unless

An identical re-run reproduces `COMPARISON.md` (44 GPU minutes). Re-run only if:

1. `relevance_score` or the topic labels were recomputed, or the lever's semantics changed (different score, different demotion
   rule, demotion before the cap). Check: `sha256sum docs/eval-reports/data/2026-11-10-topic-labels/topic_labels.tsv` against
   `c14cf1ebafc010f4...`; `git diff 03cfd18 -- rag/retriever.py`.
2. A new focus fixture exists with a baseline focus contamination clearly above 0.100 (strong traps, more than 26 collision items)
   so that "<= 0.5 x baseline" is measurable. Cheap check, CPU only: run the baseline arm rows against the new fixture, or
   `scripts/relevance_demotion_whatif.py`; if baseline contamination <= 0.04 the floor clause says nothing to fix.
3. Different arms are wanted (another tau, another p, a different mode). The prereg fixes four arms and forbids a sweep; new arms
   need a new pre-registration with its own addendum first.
4. The reranker, rerank pool depth (32), embedder or corpus composition changed so that the top-10 off-topic share is different.
   Check: re-measure the baseline contamination (topic-focus baseline report) first; if unchanged, the arms are unlikely to differ.
5. The operator's F6 off-topic bar or the adoption thresholds change (dated addendum), in which case the existing per-arm rows can be
   re-scored on CPU without a new run.
