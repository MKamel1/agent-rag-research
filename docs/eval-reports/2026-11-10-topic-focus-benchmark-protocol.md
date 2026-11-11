# FROZEN benchmark protocol — topic focus on the main corpus (`papers`): does retrieval stay on focus?

Written 2026-11-10 **before any retrieval was run for focus questions and while the focus set
(`focus_gt.json`) is still being authored** (EP-EV4; item counts below are "filled in at freeze"). The
definitions, the comparators and the adoption rule for the future relevance-demotion arm are fixed here; the
measurement that follows is not free to move. A wrong or unmeasurable definition is fixed by a dated addendum
(§12), never silently. House standard: `2026-08-23-waymo-priority-benchmark-protocol.md`. Reviews answered:
`data/2026-11-10-system-review/RV-1-retrieval-ranking.md` (F-1.1, F-1.4), `RV-3-evaluation.md` (F-1.3, F-1.14).

## 1. Motivation and honesty constraint

The operator's question: about 37% of the main corpus is off-topic for causal methods (labels for all 12,385
labelled papers in `data/2026-11-10-topic-labels/`: 6,711 on / 1,044 borderline / 4,630 off; audited, weighted
kappa 0.90, `2026-11-10-topic-labels-audit.md`; audit-corrected off share 36.9%, 95% CI 35.2–38.3%). The operator
keeps those papers on purpose. **Does retrieval stay on focus anyway?** This is a measurement question first and a
lever question second; the lever (relevance-score demotion) exists only as a pre-registered FUTURE arm (§6).

1. The metric definitions, the comparators (§4) and the adoption rule (§6) are fixed before any focus number.
2. A focus lever may trade away legitimate off-topic retrieval: the corpus lawfully holds off-topic papers the
   operator may ask about. The adoption rule therefore carries guards for exactly that (§6) — a lever that makes
   them unfindable is rejected even if it cleans the top-10.
3. The first measurement is the baseline, published regardless of how unflattering it is.

## 2. Fixtures

| fixture | role | n | SHA-256 |
|---|---|---|---|
| `data/2026-11-10-focus-gt/focus_gt.json` | **primary**: dimensions `collision`, `offtopic-legit`, `focus-absent` | ~50: collision FILLED IN AT FREEZE, offtopic-legit FILLED IN AT FREEZE, focus-absent FILLED IN AT FREEZE (40 authored when this was written: 26 collision + 14 offtopic-legit) | **null in `data/2026-11-10-FIXTURE-HASHES.json` until authoring is finished**; the run script refuses to run `focus` while it is null |
| `data/2026-11-10-papers-passage-gt/papers_passage_gt.json`, `paper_topic = on` | secondary on-topic arm (strata report with labels) | 38 | `58cdbf47f08b00fa0ec289c8fd299dd07570a07a695e56c2526a931cd83faf81` |
| same file, `paper_topic = off` | secondary off-topic legit probe (member-passage / paper-level) | 17 | same |
| `data/2026-11-10-topic-labels/topic_labels.tsv` | labels | 12,385 | `c14cf1ebafc010f45e4e377f18d67994183b3d8696859b7c4ded55659956e8d1` |

Dimension definitions (from the authoring files; reconciled against the final set at freeze and corrected by
addendum if they differ):
- `collision`: the gold paper is `on`-topic; the question uses a word that also names an off-topic domain (for
  example "instrument": IV vs measurement instrument; item field `distractor_paper_ids`, each distractor verified to
  hold a colliding chunk). Gold is on-topic by construction — verified at freeze (`paper_topic = on` for every item).
- `offtopic-legit`: the gold paper is `off`-topic and a legitimate target; item field `causal_lookalike_paper_ids`
  names on-topic papers sharing a term. A lookalike that outranks the gold is the failure.
- `focus-absent`: question whose vocabulary sits in the focus area (or its collision zone) but whose answer is not
  in the corpus; `tests = absent`. Reported like every absent arm, never blended.

Freeze-time conditions (checked before the hash is written, recorded in the hashes file note): every
`offtopic-legit` item has a non-empty `causal_lookalike_paper_ids` (an empty list scores "not outranked" and
silently dilutes the rate — §3 failure case); every `collision` item has non-empty `distractor_paper_ids`; every
gold paper has a label; `gt_tools.py verify` passes read-only.

Strata, n and Wilson half-width are printed by `scripts/eval_protocol_tools.py wilson` into each run directory and
quoted in the report. **Small-strata rule (frozen):** any stratum with n < 10 is descriptive only and can never
gate. Orientation (worst-case p = 0.5): n = 26 → ±0.18; n = 14 → ±0.25; n = 38 → ±0.15; n = 17 → ±0.21. One
item = 3.8 pts at n = 26, 7.1 pts at n = 14, 2.6 pts at n = 38. Contamination is a MEAN over questions (no
interval is produced by the stock script), so it is only ever compared paired and by counts.

## 3. Metric definitions (frozen — taken from `scripts/eval_strata_report.py`, focus section)

Labels come from `topic_labels.tsv` (`on` / `borderline` / `off`). A paper with no label (5 of 12,390 main papers)
and a `borderline` paper both count as "not off". k = 10. All computed over the ordered `retrieved_paper_ids`
(one entry per returned CHUNK/passage, so a paper can occupy several slots; the top-10 spans ~3.9 distinct papers
on average, 2026-08-19 report).

1. **On-gold answerable set.** Answerable items whose gold papers (report gold ∪ `additional_gold_paper_ids`) are
   ALL labelled `on`. Everything in 2–4 is computed on this set (and by `dimension` inside it).
2. **Off-topic contamination@10** = mean over the set of (top-10 slots whose paper is labelled `off`) / (slots
   returned). Printed as "mean off share of top-k". Floor 0.
3. **Off-at-rank-1 rate** = fraction of the set whose first result's paper is labelled `off`. Floor 0.
4. **Distractor-outranks-gold rate** (`collision`) = among on-gold items with a non-empty `distractor_paper_ids`:
   fraction whose best-ranked distractor has a strictly smaller rank than the best-ranked gold paper; a paper
   missing from the top-10 has rank ∞. Failure cases: gold missing AND a distractor present counts as outranked
   (1); both missing counts as not outranked (0) — a retriever that returns neither scores 0, so this rate must be
   read next to the item's Recall; it is a ranking statistic, not a quality score.
5. **Lookalike-outranks-gold rate** (`offtopic-legit`) = among ALL answerable `offtopic-legit` items: fraction whose
   best-ranked `causal_lookalike_paper_ids` paper ranks strictly above the gold paper (∞ for missing). Failure case:
   an item with an empty lookalike list is in the denominator and can only score 0 (hence the freeze-time condition).
6. **Companion rates (reported, same tables):** on-topic member-passage hit@10 (`collision` row of the strata
   report; and the papers set split by `paper_topic`), `offtopic-legit` paper Recall@10 and member-passage hit@10, the
   absent arm for `focus-absent` (n, top-score min/median/max — the RRF fusion score, ceiling 0.0164, not
   informative; nearest distractor at rank 1). The member-passage metric is defined exactly as in the standards
   protocol §3.1 (anchor == gold, or an alternative chunk's anchor, or `excerpt_block_id` in the retrieved anchor's
   member span); on `papers` there are 0 shared anchors, so it is essentially exact.
7. **Chance baseline printed by the script:** `chance_baseline_off_share` = labelled-off papers / labelled papers =
   4,630 / 12,385 = **0.374**. Frozen second reference, chunk-weighted: labelled-off papers hold 129,251 of 399,676
   chunks = **0.323** (on 0.580, borderline 0.092, unlabelled 0.005; measured read-only from the main DB). The
   slot-level contamination is over chunks, so 0.323 is its topic-blind reference; 0.374 is the paper-level one.
   Audit-corrected sensitivity: 0.369.

## 4. Comparators, ceiling and floor arithmetic (every frozen metric)

**Chance is the wrong comparator for a semantic retriever.** 0.374 / 0.323 is what a topic-BLIND retriever returns
(random papers/chunks). Any retriever that matches a question to text — even plain BM25 — lands far below it,
because an on-topic question shares almost no vocabulary with "nucleon form factors". Beating chance therefore
shows only that the system is not random; it cannot show that focus is good. The informative comparators are the
floor 0, the system's paired change under a lever, and (when it exists) the BM25 floor of control (ii).

| metric | floor (best) | topic-blind reference | expected under good retrieval (prior, unmeasured, NOT a gate) | resolution |
|---|---|---|---|---|
| contamination@10 (slots) | 0 | 0.323 (chunk-weighted); 0.374 (paper share) | ≈ 0.00–0.05 for ordinary on-gold items (off papers are semantically distant); above that only on `collision` items, which are built to be hard | per-question value moves in steps of ~0.1; one off paper occupies ~2.5 slots on average, so a question's share jumps ~0.25 at a time |
| off-at-rank-1 | 0 | 0.374 | ≈ 0.00–0.05 | one item = 1/n; Wilson hw at p = 0.1, n = 38: ±0.10; n = 26: ±0.12 |
| distractor-outranks-gold | 0 | 0.5 (a coin flip when both are retrieved; > 0.5 if gold is missing) | ≪ 0.5 | n ≈ 26: one item = 3.8 pts, hw ±0.12 at p = 0.1 |
| lookalike-outranks-gold | 0 | 0.5 | ≪ 0.5 | n ≈ 14: one item = 7.1 pts, hw ±0.16 at p = 0.1 |
| on-topic member hit@10 | ceiling 1.00 | | BM25 exact-chunk reference on the papers set: 0.82 on-topic (RV-3, scratch) | one item = 2.6 pts (n = 38) |
| `offtopic-legit` paper R@10 | ceiling 1.00 | | BM25 reference 0.88 off-topic (n = 17) | one item = 7.1 pts (n = 14) |

Verdict language for the baseline (descriptive, pre-committed so it is not chosen after seeing numbers): quote
contamination@10 and off-at-rank-1 with n, beside both references. "Retrieval stays on focus" may be written only
if contamination@10 ≤ 0.162 (half the chunk-weighted reference, the "falls ≥ 50%" scale of RV-1 F-1.4) AND
off-at-rank-1 ≤ 0.187 (half of 0.374); between those and the references: "partly"; at or above a reference:
"no". These are descriptive bands, not gates, and the prior in the table is stated so a surprising baseline is
recognised as surprising. Ceiling note: where the baseline contamination is already ≤ 0.04 there is at most 0.04
of headroom (≈ 1 slot in 25 questions) and no lever can be justified (§6 floor clause).

Why demotion cannot reach the floor (bounds used in §6): relevance_score separates on from off at AUROC 0.923;
demoting papers below τ moves them behind in-floor results but cannot remove an off paper that is the only
candidate. Best-case residual contamination ≈ baseline × (1 − fraction of off papers below τ): τ = 0.25 → ×0.53
(47.1% of off papers below), τ = 0.30 → ×0.31 (69.3%). Collateral: on-topic papers below τ: 2.8% (0.25) / 8.3% (0.30),
borderline 15.8% / 36.9%; hence an expected loss of ≈ 1 of 38 / ≈ 3 of 38 `on` items if their gold is demoted out of
the top-10, and on `offtopic-legit` (gold is off) the exposure is the 47% / 69% of off papers below τ — expected to
breach the guard at τ = 0.30 and possibly at 0.25. The rule is built so that this can end in REJECT.

## 5. Arms

- **Baseline** (the only arm at first run): shipped main config (rerank_depth 32, dense weight 0.5, no stub filter),
  collection `papers`, run by `run_baseline_main.sh focus` and `… papers`. The focus section is also read from the
  papers set (on-gold n = 38) as a secondary check; focus-set numbers are never averaged with papers-set numbers.
- **Future arm R-demote(τ), τ ∈ {0.25, 0.30}** — GATED on tickets that are written but not yet applied (CQ-2
  payload backfill of `relevance_score`; the retriever change that reads it). Semantics frozen now: after reranking,
  stable-partition the pool into results whose paper `relevance_score ≥ τ` followed by those `< τ`, each group keeping
  its reranker order; **never a hard drop** (the audit: a hard floor at 0.30 removes 8.3% of on-topic papers and
  37% of borderline). Papers with NULL score are treated as in-floor. The two thresholds are the audit's
  conservative and balanced operating points; no other τ is eligible. The exact flag/CLI is recorded in a dated
  addendum when the ticket is applied; the payload route (clone only) and the document-store route give the same
  ordering and are one arm.
- Ablations, depth/weight grid and other levers: out of scope here (runbook).

## 6. Pre-registered adoption rule for R-demote (frozen)

Let a "question" be one item. All counts are on the authored questions of the named fixture, per fixture, never
pooled across fixtures. **ADOPT** a threshold τ only if ALL hold; **REJECT** otherwise:

1. **Contamination falls materially:** focus-set contamination@10 under R-demote(τ) is ≤ 0.5 × the baseline value
   (RV-1 F-1.4's "≥ 50% relative" criterion), and the papers-set on-gold contamination@10 does not rise.
   **Floor clause:** if the baseline focus-set contamination@10 is ≤ 0.04 the answer is REJECT (nothing to fix).
2. **On-topic retrieval is not damaged:** member-passage hit@10 on the focus `collision` items (on-gold) AND on the
   papers set `paper_topic = on` each drops by at most one question vs baseline.
3. **Legitimate off-topic retrieval is not damaged (the operator's guard):** `offtopic-legit` paper Recall@10 on
   the focus set drops by at most one question, AND the papers set `paper_topic = off` member-passage hit@10 drops by
   at most one question. The corpus holds off-topic papers the operator may ask about; a focus lever must not make
   them unfindable.
4. **No ranking regression:** distractor-outranks-gold does not rise by more than one question; lookalike-outranks-gold
   does not rise by more than one question.
5. **Validity:** `n_errors = 0`; hashes match; point-count guard passed; the arm ran against the same collection or
   its verified clone back-to-back with the baseline.

If both thresholds pass, adopt the smaller τ (less collateral). Adoption means "propose the lever behind a
visible opt-in flag for operator sign-off" — never a silent default change (`SearchFilters`/`Config` are
foundation-protected). Any n < 10 stratum is descriptive and excluded from 1–4. A threshold that fails only on
condition 3 is REPORTED as "cleans the top-10 at the cost of legitimate off-topic findability" and is not adopted.

## 7. Controls (specified now, run with the baseline)

(i) **Title-ablated questions:** available for the papers set (`run_baseline_main.sh papers`, derived file
`papers_passage_gt.title-ablated`; see the main-corpus protocol §7 (i)). NOT applied to the focus set: its
questions are built around a colliding term, and removing document-name words would not test that. The focus
set's own style bias (LLM-authored, same-family verified) is stated, not controlled.
(ii) **Plain BM25 floor — NOT available at first run.** Follow-up script ticket (EV-5b; definition in the standards
protocol §7 (ii)); for focus it must also output the off-share of its top-10 so the topic-blind-to-semantic range is
measured instead of assumed (§4 prior).
(iii) **Reranker-score census — NOT available at first run** (needs the experiment-only `TeiReranker` recording
subclass; RV-1 F-1.1). It also gives the first reading of whether a CROSS-ENCODER score is on-topic-sensitive;
`focus-absent` is its absent arm. No decision is taken from it alone.

## 8. Known facts at freeze

Labels: weighted kappa 0.90 (0.850–0.947 for Cohen's); relevance_score AUROC (on vs off) 0.9227, medians 0.417 on /
0.328 borderline / 0.256 off; threshold table in `data/2026-11-10-topic-labels/relevance_score_output.txt`. Main
collection: 399,676 chunks + ≤ 12,390 summary points; the run script asserts the point count is plausible before
measuring. The sparse arm's ligature damage and the stub chunks are unrelated levers with their own A/Bs.

## 9. Item rules (fixed)

No item may be authored, edited or dropped after retrieval output for it has been seen. The focus set's hash is
frozen only when authoring is complete and its freeze-time conditions (§2) hold; after that, corrections are a new
fixture version with a new hash and an addendum here, and the baseline is re-run.

## 10. Measurement procedure

After `focus_gt.json`'s hash is frozen and services are up (`GPU-DAY-RUNBOOK.md` steps 0–1). Same script as the
main corpus; it checks hashes (and stops while the focus hash is null), requires `app.doctor --no-auto-start`,
asserts the collection point count, names `--collection papers --db-path … --blob-dir …` on every call, and runs
`eval_strata_report.py --topic-labels …` so the focus section is printed:

```
conda activate agent-rag-research
cd /home/omar/ai-projects/research-system-rag/docs/eval-reports/data/2026-11-10-papers-passage-gt
./run_baseline_main.sh focus papers     # focus set + papers set, one run directory
```

Report of record: `strata-focus.txt` (the `focus (chance baseline …)` block) and `strata-papers.txt`, plus
`split-papers/*`. Results land in `docs/eval-reports/2026-11-10-topic-focus-baseline.md`, committed unmodified. The
R-demote A/B is the runbook's step 6, after the tickets apply.

## 11. What this result does NOT show

- Not that the user's real queries stay on focus: items are LLM-authored, collision-built or lookalike-built, and
  n ≈ 26 / 14; one item moves a rate by 3.8 / 7.1 points.
- Not "focus" in the corpus-hygiene sense: it measures what the top-10 contains for questions whose gold is
  `on` (or the ranking against named distractors), not how many off-topic papers sit in the corpus (the corpus
  is deliberately 37% off).
- Not borderline behaviour (1,044 papers; counted as "not off") and not label error: kappa 0.90 means ~10% of
  disagreement can still move a few items; the audit-corrected off share 0.369 is a sensitivity, not a rerun.
- Contamination is slot-based: a single off-topic paper filling several slots inflates the mean; distinct-paper
  contamination is not computed by the stock script.
- Not the effect of any lever until R-demote runs; the baseline has no interval on its mean contamination.
- Nothing about abstention or answer quality.

## 12. Integrity clause

Gates stand as measured. Any change to a definition, comparator, threshold or fixture — including freezing the
focus hash, reconciling dimension definitions, or recording the R-demote flag — is a dated addendum appended below
this line stating what changed and why; the text above it is not edited, and a re-run after a fixture change is a
new baseline, not a replacement.

---

## ADDENDUM 2026-11-11 (EV-11)

**What changed (focus set).** `focus_gt.json` was repaired after cross-verification (EV-4b: 4 items replaced, most
collision questions reworded so the collision term is in the question text) and has not had a retrieval run. EV-11
did a focused independent second read of every changed item (gold excerpt inside the gold chunk, collision term in
the question, distractor chunks read for a genuine non-causal use of the term, alternative chunks read, replaced
absent items re-scanned corpus-wide with ligature-tolerant patterns in one batched pass). Result:

- Passed unchanged: all 26 collision items (term present in the question in 26/26; every distractor chunk is a
  genuine non-causal use, e.g. measurement instruments, keyword matching, MHD and contact discontinuities, nova
  shocks, backdoor attacks, particle colliders; the excerpt sits in the gold chunk for every item; alternatives
  Q-FOC-001 c16, -020 c2, -021 c2, -023 c2 read and support the answer), the 14 offtopic-legit items (untouched by the repair) and the
  absent items Q-FOC-042, -047, -048, -049, -050 (tolerant patterns for the Blanchard-Quah long-run output restriction, regression kink
  with galaxies, Hirshleifer-Shumway sunshine returns, sunspot-stock links, lunar-birth/crime links: 0 true hits;
  the few hits are citations, an astronomy "kink in the M-sigma relation", "lunar new year").
- **Q-FOC-046 dropped.** Its absence was falsified: `2606.12596:c7` (Prais-Winsten extension to AR(k) panels) writes the
  quasi-differenced transformation y~ = y - rho*y(t-1) (the Cochrane-Orcutt transformation for AR(1)); the earlier scan
  missed it because the corpus spells it "quasi-diferenced" (lost ligature). The item cannot be made sound by
  rewording, so it is removed rather than replaced.
- **Q-FOC-016: alternative `2506.01191:c6` removed.** It names the category (conditioning on colliders) but not the
  second half of the answer (the spurious association), so it is not an independent full answer.

Final composition: 49 items = collision 26 / offtopic-legit 14 / focus-absent 9 (answerable 40, absent 9;
paper_topic on 26 / off 14 / absent 9). Alternatives: 4 items (Q-FOC-001, -020, -021, -023). Trap strength over the 26
collision items, re-counted from the items: 3 strong (Q-019, Q-021, Q-026) / 20 moderate / 3 weak (Q-011, Q-012, Q-024),
matching the repair's report. The protocol's "filled in at freeze" counts are therefore: collision 26, offtopic-legit 14,
focus-absent 9 (the 10 expected before this re-check; n = 49 replaces "~50"). Freeze-time conditions re-checked:
every offtopic-legit item has non-empty `causal_lookalike_paper_ids`, every collision item non-empty
`distractor_paper_ids`, every gold paper is labelled, collision gold is `on` for 26/26, `verify` reports 0 failures.
The hash is no longer null; the run script's `focus` set can run once services are up. The focus-absent stratum now has
n = 9 < 10, so under the frozen small-strata rule (section 7) it is descriptive only and cannot gate.

**What the focus set can and cannot detect (stated honestly).** Only 3 of 26 collision traps are strong; 20 are moderate
(the term is prominent but the rest of the question is clearly causal) and 3 are weak (Q-011/-012 use "discontinuity" only
inside "regression discontinuity"; Q-024 "synthetic control" is not confusable with control theory). A retriever that
reads the causal context of a moderate question is hardly tempted by the off-topic distractor, so a low
contamination rate on this set is weak evidence of topic robustness, and a lever that merely reduces contamination
on moderate items will be hard to distinguish from noise (n = 26 gives +-0.19 at p = 0.5, one item = 3.8 points).
What the set can show is a gross failure: contamination from the strong items, the offtopic-legit items being
pushed down by a topic-based demotion (the main harm R-demote could do, n = 14, +-0.26 at p = 0.5), and whether absent
questions are answered from near-vocabulary chunks (descriptive, n = 9). It cannot show that topic-demotion helps in
general, that gold-paper recall is unaffected beyond these 40 answerable items, or anything about answer quality.
All distractor and label judgements are textual; none has been checked against a retrieval run.

**No retrieval output of any kind existed when these changes were made** (no embedder, reranker or vector store has
run against these sets), so every edit below sits inside the freeze rule: it was made blind to retrieval results.
Nothing was changed after seeing a score; a fixture edit after a run would void that run and be a new baseline.

Hash procedure: every fixture of record was re-hashed with SHA-256 (`scripts/eval_protocol_tools.py`
`sha256_of`), the file was rewritten in one commit (`b4f5a09`, after the fixture commit `82bffac`), and
`scripts/eval_protocol_tools.py check-hash data/2026-11-10-FIXTURE-HASHES.json <10 fixtures>` passes
(`hash check OK (10 fixtures)`). Both run scripts were exercised up to their service check: the hash check and the
read-only `gt_tools.py verify` (standards 128 items, papers 61, books 74; 0 failures) pass, then each stops at
`app.doctor` because the services are down, as expected. The merged files were regenerated with each set's own
`merge_gt.py` (no FAIL line) and load with `app.retrieval_eval.load_questions` (128 / 74 / 61 / 49).

| fixture | SHA-256 (first 12 hex; full values in `data/2026-11-10-FIXTURE-HASHES.json`) | changed? |
|---|---|---|
| `standards_gt.json` | `09b1061198c9` (was `87b241af55d4`) | yes, 3 alternatives added |
| `causal_books_gt.json` | `3c21d57bb6cb` | no |
| `papers_passage_gt.json` | `58cdbf47f08b` | no |
| `focus_gt.json` | `c68210e06a9f` (was `null`) | first freeze; repaired set, 49 items |
