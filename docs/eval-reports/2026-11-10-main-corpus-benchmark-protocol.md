# FROZEN benchmark protocol — main corpus (`papers`): passage retrieval baseline

Written 2026-11-10 **before any retrieval was run against the new main-corpus fixtures** (services down,
GPU busy; no author or reviewer saw retrieval output for these items). Target and reporting rules are fixed
here; the measurement that follows is not free to move. A wrong or unmeasurable definition is fixed by a dated
addendum (§12), never silently. House standard: `2026-08-23-waymo-priority-benchmark-protocol.md`.
Independent review answered: `data/2026-11-10-system-review/RV-3-evaluation.md` (F-1.3–F-1.7, F-1.12–F-1.14),
`RV-1-retrieval-ranking.md` (F-1.1, F-1.3).

## 1. Motivation and honesty constraint

**This is the first passage-level measurement of non-equation paper passages and of the 74-item books set on the
main corpus.** The only earlier passage-level numbers on `papers` are the 40-item equation slice (0.925, T-DOC41,
stock anchor rule) and a 40-item book subset (0.70) — small, equation- or outline-specific, and not from these
fixtures. Everything else ever measured on the main corpus is paper-level on the 210-question set, which is
saturated (205/210 = 0.9762, Wilson 0.945–0.990) and 81% of whose questions contain the paper title
(171/210, RV-3). So a "98% retrieval" statement today is a statement about title lookup. Therefore:

1. **Headline metrics are passage-level. Paper-level recall is reported and never a headline or a gate** on any
   fixture here; it is expected to saturate (plain BM25 over stored chunk text: 0.98 papers set, 0.96 books).
2. Every new-set number is labelled "LLM-authored, same-family verified"; questions are ~25 words vs 11.2 for
   logged queries (RV-3 F-1.6). The title-ablated control runs beside the baseline (§7).
3. The first measurement is the baseline, published regardless of how unflattering it is. It carries no absolute
   target: the operator set none, and inventing one now would be arbitrary. Later tickets (CQ-1 ligatures, CQ-3
   stubs, relevance demotion, re-chunk, depth/weight grid) are judged against these numbers by their own
   pre-registered rules; §4 freezes the regression guard they share.

## 2. Ground-truth fixtures

| fixture | role | n | SHA-256 (frozen; full list in `data/2026-11-10-FIXTURE-HASHES.json`) |
|---|---|---|---|
| `data/2026-11-10-papers-passage-gt/papers_passage_gt.json` | **primary**: paper passages (one deep passage per sampled paper) | 61 answerable | `58cdbf47f08b00fa0ec289c8fd299dd07570a07a695e56c2526a931cd83faf81` |
| `data/2026-11-10-causal-books-gt/causal_books_gt.json` | **primary**: books | 74 = 69 answerable + 5 partial-absent | `3c21d57bb6cb8949092a57cc0f4879f24f6f1f338993be24196e35a52195a0a8` |
| `fixtures/eval/eval_ground_truth.json` + `eval_questions_blind.json` | regression anchor ONLY (paper-level, no gold blocks) | 210 | `61e52db8957cde90267b46814164a9e4e47ca97809659b96e013abb14e8e50b6` (+ blind file `7813ac0efe3f40724b9883e8eee67661ae3f533a632df7a50b6642654b36a615`) |
| `fixtures/eval/eval_book_questions.json` | legacy books, stock report only | 115 | `747420e97d23b14a270825ea2bb4ce37dc5e816e74834ed35ffa062c02c64586` |
| `fixtures/eval/eval_equation_slice.json` | equation passages, stock report only | 40 | `d3fbe4ad94b9fbaafdabe264edebb077d804e411ea65124a1a4847e9935e82a8` |
| `fixtures/eval/eval_known_absent.json` | fabricated-entity absent arm | 24 | `8c80ee4095fbdddd952e3ac34bcbfd3fb0f50724f12e641fa00986777cf3002f` |
| `data/2026-11-10-topic-labels/topic_labels.tsv` | `on`/`borderline`/`off` for 12,385 of 12,390 papers (weighted kappa 0.90, `2026-11-10-topic-labels-audit.md`) | | `c14cf1ebafc010f45e4e377f18d67994183b3d8696859b7c4ded55659956e8d1` |

The run script (`run_baseline_main.sh`) fails if any needed fixture's SHA-256 differs from the frozen hash and
runs `gt_tools.py verify` WITHOUT `--write` on the two new sets (no `merge_gt.py`; the fixture is never rewritten).
Read-only verification on 2026-11-10: papers `61 items, 0 failures`, books `74 items, 0 failures`.

Strata (95% Wilson half-width at the worst case p = 0.5; `scripts/eval_protocol_tools.py wilson`):

| stratum | n | hw | role |
|---|---|---|---|
| papers set, `paper_topic = on` | 38 | ±0.15 | **headline for papers** (dimensions inside: method-detail 13, paper-passage 11, numeric-result 8, equation-context 6) |
| papers set, `paper_topic = off` | 17 | ±0.21 | reported separately; not blended; it is the "legitimate off-topic question" probe |
| papers set, `paper_topic = borderline` | 6 | ±0.31 | **descriptive only — can never gate** |
| books, book-passage | 52 | ±0.13 | **headline for books** |
| books, equation-context | 12 | ±0.25 | gating-eligible only as a loss guard (n ≥ 10) |
| books, table-requirement | 5 | ±0.33 | **descriptive only** |
| books, partial-absent | 5 | ±0.33 | **descriptive only**, absent arm |
| 115 legacy books | 115 | ±0.09 | stock report; chapter-level never a gate (§3.7) |
| equation slice | 40 | ±0.15 | stock report |
| known-absent | 24 | ±0.19 | absent arm, easy class (invented surnames) |

**Small-strata rule (frozen):** every stratum is reported with n and its half-width; n < 10 is descriptive only
and is excluded from every gate, decision rule and stratum-loss count. The three `paper_topic` groups are NEVER
blended into one rate, in any table or sentence; the all-61 pooled row may appear only labelled "pooled, not a
headline". Known exclusions in the papers sample (RV-3 F-1.14): 2506.23374 (parser corruption, 55 of 70 chunks
with per-character `<sub>` damage), and 2303.10544, 2204.01169 skipped for dimension quotas (dense array math);
the sample therefore tilts away from the worst-parsed papers and toward unique-fact passages (the headline can
understate how often an abstract/intro chunk also answers, and overstate robustness to unreadable papers).

## 3. Metric definitions (frozen)

Computed by `app/retrieval_eval.py` (per-question `retrieved_paper_ids` / `retrieved_block_ids`, rank order) and
`scripts/eval_strata_report.py`, in their state at this commit. k = 10 primary, denominators ANSWERABLE items only.

1. **Member-passage hit@10 — the passage metric of record, and the only gate metric.** Per answerable item with
   `gold_block_id`: first rank r ≤ 10 at which the retrieved anchor block `a` satisfies `a == gold_block_id`, or `a`
   anchors an `alternative_gold_chunk_ids` / `gold_chunk_id` chunk (resolved in the DB), or `excerpt_block_id` is
   non-null and lies in the member set of `a` (blocks with `idx` in `[idx(a), idx(next anchor))`, last chunk to the
   paper's end; rule reused from `app/exp_nb_xc_member_citation.py`). Member **P@1**: rank 1 is such a hit. It exists
   because the stock rule misses a correct answer served from an alternative chunk: 8 of 61 papers items (13%) and
   4 of 69 books items carry `alternative_gold_chunk_ids`, and `excerpt_block_id ≠ gold_block_id` for 58/61 papers
   items and 62/69 books items. Documented failure cases (`eval_strata_report.py` docstring): chunks sharing one
   anchor are merged and a hit on any counts (main corpus: **0** shared anchors, 399,676 chunks = 399,676 distinct
   anchors, so this does not arise on `papers`); chunks that stop before their span ends can make a non-served block a
   "member" (main DB: 1,284/1,284 sampled chunks had every member block inside the chunk text); overlap text quoting
   the next block is not counted; blocks before the first anchor belong to no chunk. On the main corpus the rule is
   therefore essentially exact: member hit = anchor hit + alternatives.
2. **Anchor-passage hit@10 / P@1 (stock rule) — reported beside, not the gate.** `retrieved anchor == gold_block_id`
   (the scorer's `passage_level`); continuity with the 0.925 / 0.70 numbers above. Under-counts alternatives.
3. **Paper Recall@10 / P@1** — reported, **never a headline, never a gate** (§1).
4. **Per-`paper_topic` reporting (papers set)** — `eval_protocol_tools.py split --field paper_topic` writes one
   sub-report each for on / borderline / off; `eval_strata_report.py` is run on each. Never blended.
5. **Absent arm** (24 known-absent, 5 books partial-absent), reported separately: n, top-score min/median/max beside
   the answerable arm's. The score returned is the RRF fusion score (ceiling (0.5+0.5)/61 = 0.0164; RV-1 F-1.1), so
   this display cannot separate absent from answerable by construction and is not an abstention test (§7 iii).
6. **Stub share** — rank-1 and top-10-slot share of chunks with body < 40 chars (main: 36,364 of 399,676). Descriptive.
7. **Legacy sets (stock report only).** 210-set: paper R@10, P@1, MRR, and the title-present/absent split
   (171/39 per RV-3) printed beside — regression anchor only. 115 books: the stock report includes a chapter-level
   rate; it is `gold_chapter_title == retrieved chapter`, a flat heading-string match (RV-3 F-1.12: 27 of 30 sampled
   "chapters" in two books are subsection headings) — **a claim about heading strings, never a gate**; its
   passage-level (anchor) rate is reported. Equation slice and known-absent: stock report.
8. **Not frozen on purpose: passage P@10.** One gold chunk per item and ~3.9 distinct papers per top-10 cap it near
   0.10 (the Waymo gate-B/D flaw, `2026-08-23-waymo-priority-baseline.md` §1).

## 4. Ceiling and floor arithmetic (every frozen metric)

| metric | ceiling | floor / reference at freeze | headroom and bias |
|---|---|---|---|
| member hit@10, papers `on` (38) | 1.00 | BM25 exact-gold-chunk hit@10: 0.82 on-topic, 0.88 off-topic, 0.85 all 61 (RV-3, one scratch run); @1 0.52 | headroom ≤ 0.18 = 7 items on `on`; one item = 2.6 pts |
| member hit@10, books book-passage (52) | 1.00 | BM25 chunk@10 0.77 book-passage, 0.80 all books (@1 0.39) | headroom ≤ 0.23 = 12 items; one item = 1.9 pts |
| member P@1 | 1.00 | BM25 chunk@1 0.52 papers / 0.39 books | same |
| paper Recall@10 | 1.00 | BM25 0.98 papers / 0.96 books; 210-set 0.9762 | headroom ≤ 1–4 items; **no decision can rest on it**; a change moves it by 0–1 items (the 210-set did not move for 5 independent changes) |
| 210-set R@10 (regression anchor) | 1.00 | 205/210 = 0.9762, hw ±0.022; one question = 0.0048 | detects regressions of ≥ 3 questions only |
| equation slice | 1.00 | 0.925 = 37/40 (T-DOC41) | one item = 2.5 pts |
| known-absent displays | n/a | fusion score ceiling 0.0164 | not informative until §7 (iii) |
| ligature-damaged gold (affects sparse arm) | | 57% of papers-set gold chunks (35/61), 39% of books (27/69) contain ligature-damaged words (main base rate 32%) | stratify CQ-1 by this flag; with ~60 items only a ≥ 10 net-item effect is detectable |
| detectable difference, paired | one item ≈ 1.6–2.6 pts | sign test, 0 losses: ≥ 5 wins for two-sided p < 0.10 | a 2-question rule is burden-of-proof, not significance |

**Regression guard shared by later tickets (frozen now):** a change is a regression if the 210-set R@10 falls
below (baseline count − 1) (the historical 205/210 is the reference, the run of record is today's baseline), or if
any stratum with n ≥ 10 loses more than one question of member-passage hit@10 on the authored questions. No
absolute pass level is frozen. (RV-3 F-1.13 phrased the 210-set tripwire as "R@10 ≥ 0.96, i.e. at most one extra
miss"; 0.96 allows three extra misses, 204/210 = 0.971 allows one — the question-count form is frozen instead.)

## 5. Arms

One arm: shipped config (rerank_depth 32, `hybrid_dense_weight` 0.5, `drop_stub_chunks` off, `fused`), plus the
title-ablated variant of each new set. The depth/weight grid, the stub filter, ligature resparse, relevance
demotion and re-chunk are separate A/Bs in `2026-11-10-GPU-DAY-RUNBOOK.md`, each with its own pre-registered rule
(CQ-3's is in `2026-11-10-cq3-stub-chunks.md`; the standards depth rule is in the standards protocol §5). The
run-to-run jitter of this baseline is not measured here (no repeat arm; the standards protocol carries it).

## 6. No dev/test split, no tuning

The 61 + 74 items are a baseline instrument, not a tuning set. No default is changed from this run alone; any
later arm beyond those named above is EXPLORATORY and cannot move a default.

## 7. Controls (specified now, run with the baseline)

(i) **Title-ablated questions — available at first run.** `scripts/eval_protocol_tools.py ablate` (deterministic;
drops every question word whose alphanumeric tokens all occur in the gold document's title and which is not a
stopword; ids unchanged; derived file written into the run directory, fixture untouched). Papers: all 61 items
ablatable; books: the 69 answerable items; the 5 partial-absent are omitted. It over-ablates (topical words shared
with the title go too), so it is a lower-bound-style control: RV-3's crude version moved paper R@10 0.98 → 0.82
(papers; on-topic 0.97 → 0.79) and 0.96 → 0.83 (books). Reporting rule: the headline is the **lower** of authored vs
ablated member hit@10 when they differ by more than 0.10 on the same items, and both are quoted; "paper-level
retrieval is semantic" needs the ablated paper-level value within 0.05 of the authored one. The legacy sets are not
ablated (no title field on the 210/115 sets that the script reads); that gap is stated, not hidden.

(ii) **Plain BM25 floor — NOT available at first run.** No script is committed; follow-up script ticket (EV-5b),
definition as in the standards protocol §7 (ii) (BM25 k1 = 1.2, b = 0.75, `[A-Za-z0-9]+` tokens, over all 399,676
stored chunk texts, question as written; chunk@1/@10 and paper@10 per stratum). Instrument-informative criterion:
floor chunk@10 ≤ 0.80 on the claimed stratum; on the papers `on` stratum the RV-3 reference is 0.82, i.e.
**already above the bar** — claims on that stratum must say the instrument is near its lexical floor.

(iii) **Reranker-score census on the absent arm — NOT available at first run.** RV-1 F-1.1: the cross-encoder
score is discarded; the RI-M7 census measured the RRF score. Needs the experiment-only `TeiReranker` recording
subclass (not committed). Frozen definition: rank-1 reranker score for every answerable and absent question; AUROC
with Hanley–McNeil CI plus the `_iqr_separates` rule; a floor is viable only if AUROC ≥ 0.85. Absent items here:
24 fabricated-entity (easy class) + 5 partial-absent books; no wiring decision from these alone (RV-3 F-1.10 needs
≥ 60 real absent items across ≥ 2 corpora).

Not adopted from RV-3: dev/test split (§6), human 30-item slice, different-family second read, logged-query
realism check (no instrument), promotion of the sets into `fixtures/eval/` (CODEOWNERS sign-off; out of scope).

## 8. Known facts at freeze

BM25 floors as in §4. Main `papers` collection: 399,676 chunks + at most one summary point per paper (12,390);
the run script asserts 0.98·399,676 ≤ points ≤ 399,676 + 12,390 + 1% before measuring. 5 of 12,390 papers have no
topic label (0.5% of chunks) and count as "not off" in the focus metrics.

## 9. Item rules (fixed)

No item may be added, edited or dropped after retrieval output for it has been seen. Corrections for verifiable
errors are a new fixture version with a new hash and a dated addendum here; the baseline is re-run, not patched.
The measurement never calls `merge_gt.py` and never writes a fixture.

## 10. Measurement procedure

After services are up (`GPU-DAY-RUNBOOK.md` steps 0–1). The script checks hashes, verifies the new sets read-only,
requires `app.doctor --no-auto-start`, asserts the point count, names `--collection papers --db-path … --blob-dir …`
on every call, and writes `docs/eval-reports/data/2026-11-10-papers-passage-gt/runs/<stamp>/` (MANIFEST with git
rev + hashes + timing, config copy, one report + log per fixture, authored and `.ablated`, `strata-*.txt/json`, and
`split-papers/` with one strata report per `paper_topic`):

```
conda activate agent-rag-research
cd /home/omar/ai-projects/research-system-rag/docs/eval-reports/data/2026-11-10-papers-passage-gt
./run_baseline_main.sh papers books legacy      # default sets
```

Report of record: `strata-papers.txt` and the three `split-papers/*.txt` files (member-passage first, stock anchor
beside), `strata-books.txt`; the ablated files as control. Results land in
`docs/eval-reports/2026-11-10-main-corpus-baseline.md`, committed unmodified. (`focus` is a separate protocol.)

## 11. What this result does NOT show

- Not quality on real user queries (LLM-authored, same-family verified, longer than real queries; ablation bounds
  the style bias, it does not remove it).
- Not on-topic vs off-topic retrieval ability in general: `off` has n = 17 (±0.21), `borderline` n = 6.
- Not chapter routing (§3.7), not equation or table handling beyond n = 11–12 / 5, not abstention (fusion score
  display; control iii pending), not answer quality or groundedness (no generation, no judge).
- Not that the 210-set's 0.976 means anything beyond title lookup (81% title-present).
- Member-passage hit on `papers` is near-exact, but a hit means the right passage was returned, not that it was
  ranked first or that the answer can be read from it (P@1 is reported separately).

## 12. Integrity clause

Gates stand as measured. Any change to a definition, threshold or fixture is a dated addendum below this line
stating what changed and why; the measured results above it are not edited, and a re-run after a fixture change
is a new baseline, not a replacement.

---

## ADDENDUM 2026-11-11 (EV-11)

**What changed.** No main-corpus fixture changed in content: `papers_passage_gt.json` and `causal_books_gt.json`
keep every recorded alternative (papers 8 items, books 4 items) and gain none; the sweep of both sets' cross-verification
reports found every suggested alternative already recorded (the one unmatched verdict, Q-CB-H-022, is an item that was
killed as a duplicate of QB-037). The hashes were re-verified, not changed.

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

Metric note (EV-8): `app/retrieval_eval.py` now emits one additional metric, `passage_excerpt_level`, reported
BESIDE the member-passage metric of record defined in section 3. It gates nothing and replaces nothing; the
gates and decision rules above are unchanged.
