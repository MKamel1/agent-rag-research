# RQ-3 pre-registration: does relevance demotion keep retrieval on focus without hiding legitimate off-topic papers?

Written 2026-11-11, before the RQ-2 lever was ever run and before any arm. Governing documents (binding, not
amended here): `2026-11-10-topic-focus-benchmark-protocol.md` section 4-6 and its 2026-11-11 addendum;
`2026-11-10-topic-labels-audit.md` (relevance_score vs label AUROC 0.923; a hard floor at 0.30 would remove 8.3% of
on-topic papers, so the lever only DEMOTES, never drops); RV-1 F-1.4; tickets `parked/RQ-2-*.md`, `parked/RQ-3-*.md`.
Nothing here switches anything on by default; the outcome is a recommendation for operator sign-off.

## 1. The lever (RQ-2, merged on this branch, default OFF)

`Retriever(relevance_demotion=None|"tail"|"penalty", relevance_tau, relevance_penalty)`, threaded through
`build_mcp_server` and the `app/retrieval_eval.py` flags `--relevance-demotion {tail,penalty} --relevance-tau T
--relevance-penalty P`. Applied after reranking and before the per-paper cap and the top-k cut. A below-tau result is
never dropped, and a paper with a NULL `relevance_score` is never demoted. `tail`: every at-or-above-tau result precedes
every below-tau one (stable). `penalty`: every below-tau result moves down P rank positions (stable). The score is
read from the `PaperRecord` the retriever already loads per result (no extra query, no payload change, no
re-embedding). `retrieve_papers()` is untouched.

## 2. Arms (four; no sweep)

| arm | flags | why |
|---|---|---|
| baseline | none | re-run inside the same script, at the same commit, so arms are comparable |
| tail@0.25 | `--relevance-demotion tail --relevance-tau 0.25` | the audit's conservative point: 2.8% of on, 15.8% of borderline, 47.1% of off papers below |
| tail@0.30 | `--relevance-demotion tail --relevance-tau 0.30` | the balanced point: 8.3% / 36.9% / 69.3% below |
| penalty@0.30, p = 5 | `--relevance-demotion penalty --relevance-tau 0.30 --relevance-penalty 5` | the softer mode, same tau as tail@0.30 so the only difference is the move rule |

No other tau (protocol section 5) and no other p. **Why p = 5.** The top-10 is 10 chunks over about 3.9 distinct papers,
and the rerank pool is 32. With p = 10 a below-tau result at any top-10 rank is pushed to rank 11 or lower whenever
enough in-floor results follow it, so for the top-10 the mode is nearly the same as tail and the comparison would
waste an arm. p = 5 (half of k) keeps a below-tau result that ranks 1-5 inside the top-10 (it is shown lower, not
hidden) while still pushing any rank 6-10 off-topic result out; it is the one setting that can differ from tail on
the legitimate-off-topic guards. Cost per arm is a GPU run, so exactly one p.

## 3. Offline what-if (no retrieval; relevance_score + labels + fixtures only)

Command: `python scripts/relevance_demotion_whatif.py --db <main papers.db> --labels topic_labels.tsv --gt
focus=... --gt papers=... --gt books=...` (read-only; values below are that script's output, 2026-11-11). Cells are
papers below tau (share of the row). A paper with a NULL score counts as not below.

Corpus, by topic label (12,385 labelled papers):

| label | n | < 0.20 | < 0.25 | < 0.30 | < 0.35 |
|---|---|---|---|---|---|
| off | 4,630 | 29.5% | 47.1% | 69.3% | 88.8% |
| borderline | 1,044 | 4.1% | 15.8% | 36.9% | 59.5% |
| on | 6,711 | 0.6% | 2.8% | 8.3% | 20.0% |

The lever's ceiling on contamination, on a topic-blind sample, is the off row: at tau 0.25 about half of off papers,
at 0.30 about 69%. It cannot exceed that and cannot remove an off paper that is the only candidate.

Focus set (`focus_gt.json`, gold papers of answerable items; one gold paper per item here):

| group | n | < 0.20 | < 0.25 | < 0.30 | < 0.35 |
|---|---|---|---|---|---|
| `collision` gold (on; must stay findable) | 26 | 0 | 1 (3.8%) | 3 (11.5%) | 6 (23.1%) |
| `collision` distractor papers (off; what the lever must reach) | 83 | 31 (37.3%) | 43 (51.8%) | 60 (72.3%) | 73 (88.0%) |
| `offtopic-legit` gold (off; the items the lever HURTS) | 14 | 7 (50.0%) | 9 (64.3%) | 11 (78.6%) | 12 (85.7%) |
| `offtopic-legit` causal-lookalike papers (on; what outranks them after demotion) | 14 | 0 | 1 (7.1%) | 2 (14.3%) | 3 (21.4%) |

Main-corpus passages set (`papers_passage_gt.json`, 61 items), gold below tau by `paper_topic`: `on` (38 items): 1 at
0.25, 2 at 0.30 (paper-passage 1, numeric-result 1); `off` (17 items, the damage check): 5 at 0.25, 9 at 0.30; `borderline`
(6 items): 2 at 0.25, 4 at 0.30. Causal books (74 items; the fixture's 69 gold papers by item): 0 below 0.30 at every
tau up to 0.30 (11 + 2 + 1 of 69 below 0.35), so the books are not exposed at the pre-registered taus.

What these numbers bound before any GPU run:
- **Gain.** A distractor can be demoted only if it is below tau: 51.8% (0.25) or 72.3% (0.30) of the 83 collision
  distractors. At most that share of the distractor-driven contamination can go, and only when an in-floor result is
  available to take the slot (the pool is 32). The protocol's adoption bar (contamination <= 0.5 x baseline) is
  therefore reachable at 0.30 and borderline at 0.25.
- **Cost.** On `offtopic-legit`, 9 of 14 gold papers (0.25) and 11 of 14 (0.30) sit below tau, against a guard of
  "at most one question lost". The lever cannot be free here: under `tail`, a demoted gold is shown behind every
  in-floor result in the pool, so unless the pool has fewer than 10 in-floor results it leaves the top-10. The
  honest prior is that tail@0.30 and probably tail@0.25 breach the guard (expected loss up to 9-11 of 14 minus items
  whose in-floor competition is thin), and penalty@0.30 p = 5 is the arm most likely to survive it. The same
  arithmetic on the papers-set `off` gold: up to 5 of 17 (0.25), 9 of 17 (0.30).
- **On-topic collateral.** 1 of 26 collision gold (0.25), 3 of 26 (0.30); 1 and 2 of 38 papers-set on-topic gold.
  The one-question tolerance is consumed by the first of these, so tail@0.30 can also fail guard 2.
- A tau of 0.20 or 0.35 appears above for orientation only and is not an arm.

## 4. Fixtures (each reported separately, never averaged)

| fixture | role | n |
|---|---|---|
| `focus_gt.json` | primary: `collision` 26, `offtopic-legit` 14, `focus-absent` 9 (descriptive, n < 10) | 49 |
| `papers_passage_gt.json` split by `paper_topic` | `on` 38 (on-topic guard), `off` 17 (damage check), `borderline` 6 (descriptive) | 61 |
| `causal_books_gt.json` | held-out control: books are not off-topic, so any loss is lever damage | 74 |

Metric of record: member-passage hit@10 from `scripts/eval_strata_report.py` (stock excerpt metric from
`app/retrieval_eval.py` is in each arm's report beside it). Contamination@10, off-at-rank-1, distractor-outranks-gold
and lookalike-outranks-gold are the protocol section 3 definitions via `--topic-labels`. Mean results per question
is also tabulated as a pool-starvation check. Hashes are verified by the run script before any service call.

## 5. Adoption rule (the protocol's section 6, plus the books guard; numbers restated)

ADOPT a mode (a recommendation to ship it behind a visible opt-in flag, never a default change) only if ALL hold,
each compared with the baseline arm re-run in the same script:
1. **Contamination falls materially:** focus-set contamination@10 on on-gold items <= 0.5 x baseline (the protocol's
   bar, stricter than "falls"; the table also prints the raw values) AND papers-set on-gold contamination@10 does not
   rise. Floor clause: if baseline focus contamination@10 <= 0.04, REJECT (nothing to fix).
2. **On-topic retrieval is not damaged:** member-passage hit@10 drops by at most one question on the `collision`
   items (of 26), on papers-set `paper_topic = on` (of 38) and on the causal books (of 74).
3. **Legitimate off-topic retrieval is not damaged:** `offtopic-legit` paper Recall@10 (of 14) and papers-set
   `paper_topic = off` member-passage hit@10 (of 17) each drop by at most one question.
4. **No ranking regression:** distractor-outranks-gold and lookalike-outranks-gold each rise by at most one question.
5. **Validity:** `n_errors = 0`, hashes match, point-count guard passed, all arms ran back to back at one commit.

A mode that passes 1 but fails 3 is reported as "cleans the top-10 at the cost of legitimate off-topic
findability" and is not adopted. Among passing arms prefer the smaller tau (less collateral). If no arm passes: REJECT
and the default stays off. `focus-absent` (n = 9) and `borderline` (n = 6) are descriptive only and never gate.
Mechanical application: `scripts/relevance_demotion_ab_table.py` prints each arm's pass/fail per check
(`COMPARISON.md`); no human judgement moves a threshold after the run.

## 6. Minimum detectable effect (stated honestly)

Wilson 95% half-widths at worst case p = 0.5, and what one question is worth: focus 49 items (answerable 40):
+-0.135, one item = 2.0 pts; `collision` 26: +-0.18, 3.8 pts; `offtopic-legit` 14: +-0.23, 7.1 pts; papers `on` 38:
+-0.15, 2.6 pts; papers `off` 17: +-0.21, 5.9 pts; books 74: +-0.11, 1.4 pts. The tolerance of "one question" is
therefore 3.8 pts on collision and 7.1 pts on offtopic-legit: a real loss of up to a 3.8 / 7.1 point recall drop is
invisible to the guard, and a real gain smaller than about +-0.18 in any rate on 26 items cannot be told from noise.
Contamination is a mean over questions with no interval from the stock script, so it is compared paired and by
counts; a question's share moves in steps of about 0.1-0.25. Arms are paired on identical questions, which helps with
between-question variance but not with the item counts above.

## 7. What this cannot show

- Only 3 of 26 collision traps are strong, 20 are moderate and 3 are weak (addendum 2026-11-11). On moderate traps the
  retriever already reads the causal context, so baseline contamination is expected to be low. A null or small
  effect on this set does NOT prove the corpus mix is harmless, and a lever that matches the baseline here has not
  been shown unnecessary; the floor clause (baseline <= 0.04, REJECT) means "nothing to fix on this fixture", not
  "no off-topic risk for real queries".
- The items are LLM-authored with one same-family verification; none is a real operator query. Not answer quality, not
  abstention, not borderline-paper behaviour beyond a descriptive 6 items.
- Demotion acts inside the 32-result rerank pool; a pool starved of in-floor results is visible only in the
  results-per-question column, and a payload-index route (full-corpus filtering) is a different, unmeasured arm.
- relevance_score is a single topic vector (AUROC 0.923): it demotes legitimate off-topic papers by construction, which
  is exactly what guard 3 exists to measure.

## 8. Cost and procedure

`docs/eval-reports/data/2026-11-10-focus-gt/run_relevance_demotion_ab.sh`: 184 queries per arm (49 + 61 + 74) x 4
arms x about 3.6 s = about 2,650 s, about 44 min GPU (the script prints the estimate first), plus about a minute of
CPU post-processing. It refuses a dirty tracked tree, stamps `git rev-parse HEAD`, checks fixture hashes, requires
`app.doctor --no-auto-start` and the point-count guard, names `--collection papers --db-path ... --blob-dir ...` on
every call, and writes only `runs-rq3/<stamp>/<arm>/`. Launch only after the baseline queue (main, focus, standards)
has finished, from the committed branch `EP-RQ2-relevance-demotion`.

Integrity: any change to an arm, threshold or fixture after this commit is a dated addendum appended below, never an edit above.
