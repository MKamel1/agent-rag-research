# FROZEN benchmark protocol — standards corpus (`av_standards`): passage retrieval and the rerank-depth question

Written 2026-11-10 **before any retrieval was run against `standards_gt.json`** (retrieval services down,
GPU busy; no author or reviewer saw retrieval output for these items). This document is the target and
the decision rule; the measurement that follows it is not free to move. If a definition here turns out
to be wrong or unmeasurable, the fix is a dated addendum that says what changed and why — never a silent
redefinition after seeing numbers (§12). House standard:
`2026-08-23-waymo-priority-benchmark-protocol.md`. Independent review answered here:
`data/2026-11-10-system-review/RV-3-evaluation.md` (F-1.3–F-1.7), `RV-1-retrieval-ranking.md` (F-1.1, F-1.3, F-1.5).

## 1. Motivation and honesty constraint

No standards fixture has ever been measured. Two things are being decided from one set of items:
(a) how good passage retrieval on `av_standards` actually is, and (b) whether the standards-only setting
`rerank_depth: 128` (every other corpus uses 32; no recorded reason) should stay. The Waymo programme
lost 4 of 68 papers at pool 128 vs 32 (Recall@10 65 → 64 → 61 at pools 32/64/128, NB-X-O; 11 gold blocks
sank at 64, NB-X-P); GT-WMR was depth-invariant. Standards has the same confusable-neighbour structure
(editions, commentary documents), so 128 is an untested transplant, not a measured win. Therefore:

1. The decision rule for depth is fixed here (§5), before the first number.
2. The items are LLM-authored and same-family verified (RV-3 F-1.8), questions are ~2x longer than logged
   queries (19.7 vs 11.2 words) and 28% share a 3-gram with their excerpt (RV-3 F-1.6). Every number is
   labelled accordingly, and the title-ablated control (§7) runs beside every arm.
3. The first measurement is the baseline, published regardless of how unflattering it is. Improvements
   afterwards are new tickets judged against these numbers.

## 2. Ground-truth fixtures

| fixture | role | n | SHA-256 (frozen) |
|---|---|---|---|
| `docs/eval-reports/data/2026-11-10-standards-gt/standards_gt.json` | the only standards fixture | 128 = 106 answerable + 22 absent | `87b241af55d4a5c2a9d780c58bc533ce475a43a56058598fd4b9080dcf239bfb` |
| derived `standards_gt.title-ablated.json` (written into each run directory by `scripts/eval_protocol_tools.py ablate`; never committed over the fixture) | control (i) | 86 | recorded in the run's `MANIFEST.txt` |

All fixture hashes live in `data/2026-11-10-FIXTURE-HASHES.json`; `run_baseline.sh` fails if the file's
SHA-256 differs, and runs `gt_tools.py verify` **without** `--write` (the previous script ran `merge_gt.py`,
which rewrote the fixture at measurement time; that call is removed). Verification was run read-only on
2026-11-10 before freezing: `128 items, 0 failures`.

Strata (answerable items; `n_passage` = items carrying `gold_block_id`; hw = 95% Wilson half-width at the
worst case p = 0.5, from `scripts/eval_protocol_tools.py wilson`):

| dimension | n | n_passage | hw | role |
|---|---|---|---|---|
| book-passage | 26 | 26 | ±0.18 | gating stratum |
| clause-lookup | 18 | 18 | ±0.21 | gating |
| table-requirement | 16 | 16 | ±0.22 | gating |
| guidance-factual | 14 | 14 | ±0.23 | gating |
| definition-lookup | 12 | 12 | ±0.25 | gating |
| cross-document | 12 | 0 | n/a | paper-level only (§3 metric 6); no passage gold |
| **authority** | **4** | 4 | **±0.35** | **descriptive only — can never gate** |
| **edition** | **4** | 4 | **±0.35** | **descriptive only — can never gate** |
| answerable total | 106 | 94 | ±0.10 | headline pool |
| absent (9) / partial-absent (13) | 22 | 0 | ±0.26 / ±0.22 | reported separately, never blended; absent n=9 is descriptive |

**Small-strata rule (frozen):** every stratum is reported with n and its Wilson half-width. A stratum with
n < 10 is descriptive only and is excluded from every gate, decision rule and stratum-loss count in this
document and in any later document that cites it. Authority and edition (n = 4 each) are anecdotes, not
measurements; they may be grown to ≥ 15 or merged into one "disambiguation" stratum only by a new fixture
version with a new hash.

## 3. Metric definitions (frozen)

All computed by `app/retrieval_eval.py` (per-question `retrieved_paper_ids` / `retrieved_block_ids` in
rank order) and `scripts/eval_strata_report.py` in their state at the commit of this file. k = 10 primary.
Denominators are ANSWERABLE items only; absent items are reported separately.

1. **Member-passage hit@10 — the passage metric of record (gate metric).** Per answerable item with a
   `gold_block_id`: the first rank r ≤ 10 at which the retrieved result's anchor block `a` satisfies any of
   (i) `a == gold_block_id`; (ii) `a` is the anchor block of an `alternative_gold_chunk_ids` chunk (or of
   `gold_chunk_id`) resolved in the corpus DB; (iii) `excerpt_block_id` is non-null and lies in the member set of
   `a`. Member set of an anchor = all blocks with `idx` in `[idx(a), idx(next anchor of the same paper))`, the last
   chunk running to the paper's last block (reused rule of `app/exp_nb_xc_member_citation.py`). Hit = a rank
   exists. Member **P@1** = rank 1 is such a hit. Strata are by `dimension`.
   Documented failure cases of the member rule (from `eval_strata_report.py`'s docstring; all err toward an
   OVER-count, except the last): several chunks sharing one anchor block (standards: 2,661 of 35,714 chunks,
   7.5%, a long block split over c3, c4, …) are indistinguishable at anchor level and a hit on any of them
   counts; chunks that stop before their span ends or tables re-rendered as rows (3.1% of chunks in a
   10,403-chunk sample have a member block missing from their text) can make a non-served block a "member";
   overlap text quoting the next block is not counted (under-count); blocks before the first anchor belong to
   no chunk.
2. **Anchor-passage hit@10 / P@1 (stock rule, reported beside, not the gate).** Hit iff a retrieved anchor
   block id == `gold_block_id`. This is the scorer's own `passage_level` rule and is kept byte-identical so
   the Waymo-era numbers stay comparable. It ignores `alternative_gold_chunk_ids` (1 standards item) and three
   same-document duplicates the cross-verifier left as notes (Q-STD-D-014 c210, D-027 c49, D-028 c58/c347; the
   fixture is frozen, so they stay unrecorded) — a UNDER-count of at most 4 items of 94 (4.3%) on both rules.
3. **Paper Recall@10 / P@1** (gold = `source_paper_id` ∪ `additional_gold_paper_ids` ∪ supporting) —
   **reported, never a headline, never a gate.** It is expected to saturate: a plain BM25 over stored chunk text
   reaches 0.98 on this set because every chunk's text begins with `title\nsection_path` and most questions
   name the document (RV-3 F-1.3, F-1.7). It is kept as a tripwire for gross breakage only.
4. **Authority / edition** — fraction of items where a `commentary_paper_ids` / `other_edition_paper_ids`
   document ranks strictly above every gold document (gold absent from top-10 = rank ∞). Descriptive (n = 4 each).
5. **Stub analysis** — share of rank-1 results and of all top-10 slots whose chunk body is < 40 chars.
   Descriptive; it is CQ-3's input (`2026-11-10-cq3-stub-chunks.md`).
6. **Cross-document** — fraction of the 12 items with ALL gold documents in the top-10 and with at least one.
   Descriptive (no passage gold).
7. **Absent arm (reported, never blended)** — for the 9 absent and the 13 partial-absent items: n, top-score
   min/median/max beside the answerable arm's, and how often `nearest_distractor_paper_id` is rank 1.
   **The `top_score` returned today is the RRF fusion score (rank arithmetic, ceiling (0.5+0.5)/61 = 0.0164),
   not the reranker's** (RV-1 F-1.1); this display therefore cannot separate absent from answerable by
   construction and is not a test of abstention. The test is control (iii), §7.
8. **Not frozen on purpose: passage P@10.** With one gold chunk per item and ~3.9 distinct papers per top-10,
   `|top-10 ∩ gold| / 10` is capped near 0.10 — the Waymo gate-B/D flaw (`2026-08-23-waymo-priority-baseline.md` §1).
   No metric of that shape is frozen here.

## 4. Ceiling and floor arithmetic (every frozen metric)

| metric | ceiling | floor / reference at freeze | headroom and bias |
|---|---|---|---|
| member hit@10 (94 items) | 1.00 (the gold chunk can be in the top 10) | BM25 exact-gold-chunk hit@10 = 0.63 (RV-3, one run, not part of the instrument) | over-count ≤ 5/119 gold anchors shared with a sibling chunk (4.2%, RV-3); under-count ≤ 4/94 from unrecorded duplicates (§3.2); net bias within ±4 questions |
| member P@1 | 1.00 | BM25 chunk@1 = 0.23 | same bias band |
| anchor hit@10 | 1.00 | as above | strict: under-counts alternatives only |
| paper Recall@10 (94) | 1.00 | BM25 0.98 (hw ±0.03) | headroom ≤ 0.02 = 2 items → cannot separate any two configs; tripwire only |
| edition / authority outranks | 0.0 is best | n = 4 each | one item = 0.25; descriptive |
| per-stratum floors (BM25 chunk@10, RV-3) | | book-passage 0.38 (26), definition 0.42 (12), table 0.75 (16), clause 0.89 (18), guidance 0.93 (14), edition 0.00 (4) | strata whose floor is > 0.80 (clause-lookup, guidance-factual) are **instrument-saturated**: they can show a LOSS but can never support a claim of gain |
| detectable difference, paired | one item = 1/94 = 1.06 pts | a sign test with 0 losses needs ≥ 5 wins for two-sided p < 0.10 (5-0: 0.0625; 4-0: 0.125) | a 2-question rule (§5) is a burden-of-proof rule, NOT a significance test |

## 5. Pre-registered decision rule for the depth question (D-1) and the sparse-arm falsifier (S-1)

**Arms.** Shipped: depth 128, dense weight 0.5 (`fused`). Candidates: depth 64, depth 32 (same weight);
ablations `dense_only` and `sparse_only` at depth 128. Plus a repeat of the shipped arm (jitter envelope).
Every arm also runs on the title-ablated questions.

**Evidence the rule is built on.** Waymo ver84 Recall@10 fell 65 → 64 → 61 of 68 across pools 32 / 64 / 128
and 11 gold blocks sank at 64, while GT-WMR was invariant; a deeper pool gave the reranker more confusable
neighbours and never produced a measured gain on any corpus. Main-corpus 210-set: pool 32 → 50 moved
0.976 → 0.967 (2 lost, 0 gained). The prior therefore favours 32; 128 carries the burden of proof, and the
asymmetry is also a cost one (rerank work grows with pool).

**D-1 (frozen).** Let H(d) = member-passage hit@10 count over the 94 passage-scored answerable items at
depth d, on the AUTHORED questions. Keep 128 **only if all** hold:

1. H(128) − H(32) ≥ 2 (exceeds by MORE than one question);
2. no gating stratum (n ≥ 10, §2) has H_s(32) − H_s(128) ≥ 2 (no stratum loses more than one question at 128);
3. on the ABLATED questions, H_abl(128) − H_abl(32) ≥ −1 (the title-ablated arm may not contradict by 2+);
4. validity: both arms `n_errors = 0`; the collection point-count check passed; the fixture hash matched; the
   run-to-run repeat of depth128-fused differs from depth128-fused on ≤ 1 question of H (if it differs on 2+,
   the comparison is declared undecidable, the shipped value stays, and the run is repeated once — no tuning).

Otherwise **revert `rerank_depth` to 32** (the value measured on the other corpora). Ties go to 32. Depth 64
is reported but is not an eligible outcome: it is an interpolation point, not a pre-registered candidate.
Rule D-1 is a change-control rule: it moves a default only on a clear, non-regressing gain.

**S-1 (frozen falsifier; Waymo's "sparse hurts" is a one-question effect with the sign flipping between
fixtures, RV-1 F-1.5).** The finding is **not replicated** on standards if `dense_only` loses ≥ 5 net items
vs `fused` (H_dense ≤ H_fused − 5) on the authored AND ablated questions; it is **replicated** only if
`dense_only` ≥ `fused` + 2 on BOTH; anything else is **unresolved** and no weight change follows from it.
The ablated arm is required because LLM-authored questions with shared rare tokens flatter the sparse arm
(RV-3 F-1.6). Nothing in this protocol changes `hybrid_dense_weight`; the weight axis is run only in the
GPU-day grid, which has its own rule (runbook §3).

## 6. No dev/test split (declined, stated)

RV-3 proposed a dev/test split by document. Declined: it would halve n (94 → ~47 per half; per-stratum n
below 10 almost everywhere). The overfitting risk is instead bounded by pre-registration: one shipped
baseline, three pre-named candidates, one rule (D-1), one falsifier (S-1), the ablated veto, the jitter
validity gate; any other arm is labelled EXPLORATORY and cannot move a default.

## 7. Controls (specified now, run with the baseline)

(i) **Title-ablated questions — available at first run.** `scripts/eval_protocol_tools.py ablate` writes a
derived copy: for each answerable item with `source_paper_title`, every whitespace-delimited word whose
alphanumeric tokens ALL occur in the gold document's title (and that is not a stopword) is dropped; ids and all
other fields are unchanged. Omitted and counted in `_metadata`: cross-document (12, no single title), `edition`
and `authority` (8; the document identity IS the question), non-answerable (22). 86 items remain. Deterministic,
no model, no hand editing. It over-ablates (topical words shared with the title go too), so it is a lower-bound
style control: RV-3's crude version moved paper R@10 0.98 → 0.87 on this set. Reporting rule: member hit@10 is
compared per dimension (strata are shared) and pooled over the five shared dimensions; **if the ablated pooled
value is more than 0.10 below the authored value on the same items, the headline is the lower arm** and both are
quoted; a claim that "retrieval is semantic rather than title lookup" requires the ablated paper-level value
within 0.05.

(ii) **Plain BM25 floor — NOT available at first run.** No script is committed (RV-3's `bm25.py` is scratch
and needs numpy/scipy/sklearn). Specified for a follow-up script ticket (EV-5b): BM25 k1 = 1.2, b = 0.75, tokens
`[A-Za-z0-9]+` lowercased, the stopword list of `eval_protocol_tools.STOP`, idf = ln(1 + (N − df + 0.5)/(df + 0.5)),
over ALL chunk texts of the corpus as stored (they begin `title\nsection_path`), query = `question_text` as
written; outputs chunk@1/@10 and paper@10 per stratum, authored and ablated. Instrument-informative criterion:
floor chunk@10 ≤ 0.80 on the stratum a claim is about. Until it exists, the reference floors in §4 are RV-3's
single scratch run and are labelled as such.

(iii) **Reranker-score census on the absent arm — NOT available at first run.** RV-1 F-1.1: the score returned
is the fusion score; the cross-encoder score was never tested for abstention, so RI-M7's "no floor" rested on a
signal that cannot separate. It needs an experiment-only recording subclass of `TeiReranker` that keeps
`(id, score)` — not committed. Frozen definition for when it exists: record the reranker score of the rank-1
result for every question; AUROC (answerable vs absent, Hanley–McNeil CI) and the RI-M7 IQR-separation rule
(`app/score_distribution_census.py::_iqr_separates`). Floor viable only if AUROC ≥ 0.85 (RV-1); ≈ 0.5 closes the
question. Here n_absent = 9 (+13 partial-absent, a different failure class, never pooled): the CI is ±0.2 or
wider, so **no wiring decision is made from standards alone**; it contributes to the ≥ 60-item pooled set RV-3
F-1.10 requires.

Not adopted from RV-3: the 30-item human logged-query-style slice (operator time, none promised), the
different-family second read (not available today), the logged-queries realism check (needs an unlabelled run
path no instrument provides). Without them, every number from this set is labelled "LLM-authored, same-family
verified".

## 8. Known facts at freeze (context, not excuses)

BM25 floor (RV-3, scratch): paper R@10 0.98 / chunk@10 0.63 / chunk@1 0.23. Standards `rerank_depth: 128` has no
recorded reason. 2,483 of 35,714 chunks (7%) are heading-only stubs. 7.5% of chunks share an anchor with another
chunk. The vector store holds the 35,714 chunks plus at most one summary point per paper (119); the run script
asserts 0.98·35,714 ≤ points ≤ 35,714 + 119 + 1% before measuring. All three bounds were set before any run.

## 9. Item rules (fixed)

No item may be added, edited or dropped after retrieval output for it has been seen. Corrections for
verifiable factual errors are allowed only as a new fixture version with a new frozen hash and a dated addendum
here; the baseline is then re-run, not patched. Ground-truth files, `gt_tools.py` and `merge_gt.py` are not
touched by measurement; `run_baseline.sh` never calls `merge_gt.py`.

## 10. Measurement procedure

One run, after services are up (`GPU-DAY-RUNBOOK.md` steps 0–1). Everything is in one script; it checks the
hash, verifies the fixture read-only, requires `app.doctor --no-auto-start` to pass, asserts the point count,
names `--collection av_standards --db-path … --blob-dir …` explicitly on every call, and writes one directory
`docs/eval-reports/data/2026-11-10-standards-gt/runs/<stamp>/` holding `MANIFEST.txt` (git rev, hashes,
start/finish), the config copies, one report JSON + log per arm (authored and `.ablated`), the
`depth128-fused-repeat` report, and `strata*.txt/json` from `eval_strata_report.py`:

```
conda activate agent-rag-research
cd /home/omar/ai-projects/research-system-rag/docs/eval-reports/data/2026-11-10-standards-gt
./run_baseline.sh
```

Each arm is `python -m app.retrieval_eval --ground-truth GT --config <config copy> --collection av_standards
--db-path …/research-system-rag-standards/data/papers.db --blob-dir …/blobs --k 10 --sparse-mode
{fused|dense_only|sparse_only}`; the report of record is `strata.txt` (authored) with `strata.ablated.txt`
as control. Results land in `docs/eval-reports/2026-11-10-standards-baseline.md`, committed unmodified, with D-1
and S-1 stated pass/fail with counts.

## 11. What this result does NOT show

- Not retrieval quality on real user queries: items are LLM-authored, longer than logged queries, same-family
  verified; the ablated control bounds but does not remove the style bias.
- Not that 128 (or 32) is right for standards in general: it decides between two pre-named values on 94 items,
  at one weight; a 2-question rule is not statistical significance (§4).
- Not anything about authority or edition handling (n = 4 each), cross-document synthesis beyond 12 paper-level
  items, or answer quality / groundedness (no generation, no judge was run).
- Not abstention: the absent-arm display is the fusion score; abstention is untested until control (iii) runs.
- Paper-level recall near 0.98 does not mean the right passage is served; that is why it is not a headline.
- Member-passage hit can over-count by ≤ 4% (shared anchors) and under-count by ≤ 4% (unrecorded duplicates).

## 12. Integrity clause

Gates stand as measured. Any change to a definition, a threshold or a fixture — including "the check was
wrong" — is a dated addendum appended below this line stating what changed and why; the measured gates above it
are not edited, and a re-run after a fixture change is a new baseline, not a replacement.
