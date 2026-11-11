# Main-corpus baseline (`papers`): passage retrieval, first measurement, 2026-11-11

Protocol: `2026-11-10-main-corpus-benchmark-protocol.md` (frozen; includes the EV-11 addendum of 2026-11-11).
Runbook step 1a: `2026-11-10-GPU-DAY-RUNBOOK.md`. This report states each number as counts and a ratio, names its
source file, and evaluates each pre-registered rule as written. Nothing here edits a fixture or reinterprets a rule.
All questions are LLM-authored and same-family verified; they run about 25 words against 11.2 for logged queries.

## 1. Run identity and validity

| item | value | source |
|---|---|---|
| code commit | `626fac3555a386076944d106254354ad66b2dfa7`, `code_tree_dirty = false` in every report | `GIT_COMMIT`, `MANIFEST.txt`, `papers.json` etc. |
| run directory | `docs/eval-reports/data/2026-11-10-papers-passage-gt/runs/20261111T004734` (untracked; not committed) | |
| window | 2026-11-11 00:47:37 to 01:29:19 (-07:00), 41 min 42 s | `MANIFEST.txt` |
| collection / DB | `papers`; `/home/omar/ai-projects/research-system-rag-data/papers.db` | `MANIFEST.txt` |
| config | shipped: `rerank_depth 32`, `hybrid_dense_weight 0.5`, fused; `drop_stub_chunks` not set | `config-shipped.yaml` |
| point-count guard | 412,167 points; DB 399,676 chunks + 12,390 papers; "plausible" (points exceed chunks + summaries by 101, inside the 1% tolerance; not investigated) | `scratchpad/baseline_main.log` |
| errors, validity | `n_errors = 0`, `run_valid = true`, `n_lock_timeouts = 0`, `n_chunk_id_ambiguous_rows = 0`, `n_chunk_id_unresolved_ranks = 0` in all 8 reports (papers, books, both ablated, 4 legacy) | `papers.json`, `books.json`, `*.ablated.json`, `legacy-*.json` |
| fixture hashes | all match `data/2026-11-10-FIXTURE-HASHES.json` (itself `7f2fa1fc352f…`, as recorded in `MANIFEST.txt`); re-checked today: `eval_protocol_tools.py check-hash` printed `hash check OK (10 fixtures)`; run log: `hash check OK (8 fixtures)`, `61 items, 0 failures`, `74 items, 0 failures` | `MANIFEST.txt`, `baseline_main.log` |
| report GT hashes (first 12 hex) | papers `58cdbf47f08b`, books `3c21d57bb6cb`, 210-set `61e52db8957c`, 115 books `747420e97d23`, equation `d3fbe4ad94b9`, known-absent `8c80ee4095fb`; ablated derived files papers `2fe52dd44df5`, books `dc43b3e43edc` | `ground_truth_sha256_12` in each report |

Metric of record: member-passage hit@10 (protocol 3.1) from `strata-papers.txt`, `strata-books.txt` and
`split-papers/*.txt`. Anchor hit (stock rule) is printed beside it. The excerpt metric (EV-8) is beside, gates nothing.
On `papers` there are 0 shared anchors, so member hit equals anchor hit plus alternatives.

## 2. Headline: member-passage hit@10 and P@1, authored questions

Pooled rows are labelled "pooled, not a headline" (protocol small-strata rule). Wilson half-width hw is at p = 0.5.

### 2.1 Papers set (61 answerable)

| stratum (role) | n | hw | member hit@10 | member P@1 | anchor hit@10 | anchor P@1 | paper R@10 | paper P@1 |
|---|---|---|---|---|---|---|---|---|
| `paper_topic = on` (headline) | 38 | 0.15 | 30/38 = 0.789 | 25/38 = 0.658 | 29/38 = 0.763 | 25/38 = 0.658 | 34/38 = 0.895 | 32/38 = 0.842 |
| `paper_topic = off` (separate) | 17 | 0.21 | 16/17 = 0.941 | 15/17 = 0.882 | 16/17 = 0.941 | 15/17 = 0.882 | 17/17 = 1.000 | 16/17 = 0.941 |
| `paper_topic = borderline` (descriptive only) | 6 | 0.31 | 6/6 = 1.000 | 5/6 = 0.833 | 6/6 = 1.000 | 4/6 = 0.667 | 6/6 = 1.000 | 6/6 = 1.000 |
| pooled, not a headline | 61 | 0.12 | 52/61 = 0.852 | 45/61 = 0.738 | 51/61 = 0.836 | 44/61 = 0.721 | 57/61 = 0.934 | 54/61 = 0.885 |

Topic rows: `split-papers/papers.paper_topic-{on,off,borderline}.txt` summed over their dimension rows; pooled row:
`strata-papers.txt` summed over dimensions, and `papers.json` (`paper_level.overall.recall_at_k = 0.9344`,
`passage_level.overall.recall_at_k = 0.8361 = 51/61`, `passage_excerpt_level.overall.recall_at_k = 0.8525 = 52/61`).
The on/off/borderline sums were recomputed by `data/2026-11-11-baseline-analysis/main_ablation_topic_split.py`
(output `main_ablation_topic_split.out.txt`) and agree.

By dimension (`strata-papers.txt`):

| dimension | n | hw | member hit@10 | member P@1 | anchor hit@10 | paper R@10 |
|---|---|---|---|---|---|---|
| equation-context | 11 | 0.25 | 9/11 = 0.818 | 6/11 = 0.545 | 9/11 = 0.818 | 10/11 = 0.909 |
| method-detail | 20 | 0.20 | 17/20 = 0.850 | 16/20 = 0.800 | 17/20 = 0.850 | 18/20 = 0.900 |
| numeric-result | 16 | 0.22 | 16/16 = 1.000 | 15/16 = 0.938 | 16/16 = 1.000 | 16/16 = 1.000 |
| paper-passage | 14 | 0.23 | 10/14 = 0.714 | 8/14 = 0.571 | 9/14 = 0.643 | 13/14 = 0.929 |

`paper_topic` inside `on` (`split-papers/papers.paper_topic-on.txt`): equation-context 4/6, method-detail 10/13,
numeric-result 8/8, paper-passage 8/11 member hit@10. Inside `off`: 3/3, 6/6, 5/5, 2/3. Inside `borderline`:
2/2, 1/1, 3/3 (n < 10 everywhere below the topic level is descriptive).

### 2.2 Books set (69 answerable + 5 partial-absent)

| stratum (role) | n | hw | member hit@10 | member P@1 | anchor hit@10 | anchor P@1 | paper R@10 | paper P@1 |
|---|---|---|---|---|---|---|---|---|
| book-passage (headline) | 52 | 0.13 | 41/52 = 0.788 | 34/52 = 0.654 | 41/52 = 0.788 | 34/52 = 0.654 | 45/52 = 0.865 | 36/52 = 0.692 |
| equation-context (loss guard only) | 12 | 0.25 | 10/12 = 0.833 | 7/12 = 0.583 | 10/12 = 0.833 | 7/12 = 0.583 | 11/12 = 0.917 | 9/12 = 0.750 |
| table-requirement (descriptive only) | 5 | 0.33 | 3/5 = 0.600 | 2/5 = 0.400 | 3/5 = 0.600 | 2/5 = 0.400 | 4/5 = 0.800 | 2/5 = 0.400 |
| pooled, not a headline | 69 | 0.11 | 54/69 = 0.783 | 43/69 = 0.623 | 54/69 = 0.783 | 43/69 = 0.623 | 60/69 = 0.870 | 47/69 = 0.681 |

Source: `strata-books.txt`; pooled passage and excerpt rate in `books.json` (`passage_level` 0.7826 = 54/69,
`passage_excerpt_level` 0.7826, 7 items on the anchor fallback). `books.json` `paper_level.by_gold_status.answerable`
paper R@10 0.8696 = 60/69.

### 2.3 Other metrics the protocol requires

- **Stub share (3.6).** Papers: rank-1 0/61 = 0.000, top-10 slots 0/610 = 0.000. Books: rank-1 0/74 = 0.000, slots
  12/740 = 0.016 (`strata-papers.txt`, `strata-books.txt`). Background share of stub chunks in the corpus is 36,364 of 399,676.
- **Absent arm (3.5), RRF fusion score (ceiling 0.0164; not an abstention test).**
  - known-absent (24, `legacy-eval_known_absent.json`): top score min 0.00674 / median 0.00874 / max 0.01626.
    Same measure on the papers answerable arm (n = 61): 0.00658 / 0.00906 / 0.01577.
  - books partial-absent (5, `strata-books.txt`): 0.00702 / 0.00767 / 0.00840 against the 69 answerable
    0.00658 / 0.00836 / 0.01601. Nearest distractor at rank 1: 0/5.
  - The absent range lies inside the answerable range in both. This display cannot separate them (protocol 3.5, 7 iii).
- **Chapter level (books).** `books.json` `chapter_level`: 0/5 on the 5 items where it is scored. Heading-string match;
  never a gate (protocol 3.7).

### 2.4 Legacy sets (stock report only)

| set | n | metric | count and ratio | source |
|---|---|---|---|---|
| 210-question set (regression anchor) | 210 | paper R@10 | 207/210 = 0.9857 (MRR 0.9264; misses Q-164, Q-170, Q-205) | `legacy-eval_ground_truth.json` |
| | | paper P@1 | 187/210 = 0.890 | same |
| | | title verbatim in question / not | 161 questions with the gold title verbatim: 161/161 hit; 49 without: 46/49 = 0.939 | `title_leak` flag per question; the verbatim predicate (161) differs from RV-3's 171/39 split |
| 115 legacy books | 115 | paper R@10 | 89/115 = 0.774 | `legacy-eval_book_questions.json` |
| | | passage (anchor) hit@10 / P@1 | 83/115 = 0.722 / 69/115 = 0.600 | same |
| | | chapter level | 55/115 = 0.478 (heading-string match; never a gate) | same |
| equation slice | 40 | passage (anchor) hit@10 / P@1 | 37/40 = 0.925 / 28/40 = 0.700 | `legacy-eval_equation_slice.json` |
| | | paper R@10 | 40/40 = 1.000 | same |

The equation slice reproduces the earlier 0.925 (T-DOC41). The 210-set count is 207, against the historical 205.
Protocol 4 freezes today's baseline count as the reference for the shared regression guard (see 5, rule R4).

## 3. Title-ablated control (protocol 7 i)

Ablation by `scripts/eval_protocol_tools.py ablate`: papers 61 items (none omitted), books 69 (5 not answerable
omitted); log lines in `papers.strata-n-and-halfwidth.txt`. Sources: `strata-papers.ablated.txt`,
`strata-books.ablated.txt`, `papers.ablated.json`, `books.ablated.json`. On-topic / off-topic / borderline splits of
the ablated papers run were computed by `main_ablation_topic_split.py` (no committed split file exists for the ablated run).

| stratum | n | authored member hit@10 | ablated member hit@10 | difference | rule (diff > 0.10: headline is the lower) |
|---|---|---|---|---|---|
| papers `on` | 38 | 30/38 = 0.789 | 25/38 = 0.658 | 0.132 | headline **0.658** |
| papers `off` | 17 | 16/17 = 0.941 | 12/17 = 0.706 | 0.235 | headline **0.706** |
| papers `borderline` | 6 | 6/6 | 4/6 | descriptive | n < 10 |
| papers pooled, not a headline | 61 | 52/61 = 0.852 | 41/61 = 0.672 | 0.180 | lower: 0.672 |
| books book-passage | 52 | 41/52 = 0.788 | 33/52 = 0.635 | 0.154 | headline **0.635** |
| books equation-context | 12 | 10/12 = 0.833 | 12/12 = 1.000 | ablated is higher | authored stands |
| books table-requirement | 5 | 3/5 | 2/5 | descriptive | n < 10 |
| books pooled, not a headline | 69 | 54/69 = 0.783 | 47/69 = 0.681 | 0.101 (7/69 = 0.1014) | lower: 0.681 |

Ablated by dimension, papers: equation-context 4/11, method-detail 12/20, numeric-result 15/16, paper-passage 10/14.
Ablated member P@1: papers pooled 35/61 = 0.574, books pooled 34/69 = 0.493.

Paper-level recall, authored vs ablated: papers 57/61 = 0.934 vs 47/61 = 0.770 (difference 0.164); books 60/69 = 0.870
vs 51/69 = 0.739 (difference 0.130).

Ablated focus numbers (papers `on`-gold, n = 38, `strata-papers.ablated.txt`): mean off share 0.161, off at rank 1
3/38 = 0.079 (authored: 0.118 and 0/38).

## 4. Comparison with the plain BM25 floor (EV-15)

BM25 numbers are read from `docs/eval-reports/data/2026-11-10-bm25-floor/{papers,books}-standard.report.json` and
`*.strata.txt` (report `2026-11-10-bm25-floor.md`; k1 1.2, b 0.75, question as written, title header in the index, no
ligature repair). The two papers/books fixtures were unchanged by the EV-11 refreeze, so those floor runs are on the
same hashes. BM25 is not the system; no fixture was changed in response to either result.

| stratum | n | system member hit@10 | BM25 member hit@10 | system member P@1 | BM25 member P@1 |
|---|---|---|---|---|---|
| papers `on` | 38 | 30/38 = 0.789 | 31/38 = 0.816 | 25/38 = 0.658 | 20/38 = 0.526 |
| papers `off` | 17 | 16/17 = 0.941 | 15/17 = 0.882 | 15/17 = 0.882 | 12/17 = 0.706 |
| papers `borderline` | 6 | 6/6 | 6/6 | 5/6 | 2/6 |
| papers pooled | 61 | 52/61 = 0.852 | 52/61 = 0.852 | 45/61 = 0.738 | 34/61 = 0.557 |
| papers equation-context | 11 | 9/11 | 7/11 | 6/11 | 4/11 |
| papers method-detail | 20 | 17/20 | 17/20 | 16/20 | 10/20 |
| papers numeric-result | 16 | 16/16 | 16/16 | 15/16 | 10/16 |
| papers paper-passage | 14 | 10/14 | 12/14 | 8/14 | 10/14 |
| books book-passage | 52 | 41/52 = 0.788 | 39/52 = 0.750 | 34/52 = 0.654 | 22/52 = 0.423 |
| books equation-context | 12 | 10/12 | 11/12 | 7/12 | 5/12 |
| books table-requirement | 5 | 3/5 | 4/5 | 2/5 | 1/5 |
| books pooled | 69 | 54/69 = 0.783 | 54/69 = 0.783 | 43/69 = 0.623 | 28/69 = 0.406 |
| paper R@10, papers / books | 61 / 69 | 57/61 = 0.934 / 60/69 = 0.870 | 60/61 = 0.984 / 64/69 = 0.928 | | |

Topic rows for BM25 and the ablated BM25 arms were computed by `main_ablation_topic_split.py`.
Ablated (anchor rule, BM25 title-ablated report; no member column exists for it): papers BM25 48/61 = 0.787 against
system 41/61 = 0.672; books BM25 50/69 = 0.725 against system 47/69 = 0.681. The system's ablated pooled hit is below
the BM25 floor on both sets. Paper-level R@10 under ablation: papers system 47/61 = 0.770 vs BM25 53/61 = 0.869;
books system 51/69 = 0.739 vs BM25 56/69 = 0.812.

Pooled member hit@10 is identical between system and BM25 on both sets (52/61 and 54/69). The system is ahead at
rank 1 (45 vs 34, 43 vs 28). On the papers `on` stratum and on paper-level recall (both sets) it is at or below BM25.

### 4.1 Per-question overlap of misses (post-hoc, descriptive; not a protocol gate)

Both sides scored with the same member rule (`eval_strata_report.passage_ranks`, current fixtures), member hit@10 over
answerable items with a gold block. Script `data/2026-11-11-baseline-analysis/main_paired_misses.py`, output
`main_paired_misses.out.txt`. Per-dimension member counts from it match the strata files for both sides.
The system rows come from `papers.json` / `books.json`; BM25 rows from `*-standard.report.json`.

| set | n | misses, system | misses, BM25 | both | system only | BM25 only |
|---|---|---|---|---|---|---|
| paper passages | 61 | 9 | 9 | 5 | 4 | 4 |
| causal books (answerable) | 69 | 15 | 15 | 5 | 10 | 10 |

- Papers, both miss: Q-PAPG-009, Q-PAPG-016, Q-PF-F-004, Q-PF-F-015, Q-PF-F-022.
  System only: Q-PAPG-006, Q-PAPG-023, Q-PF-F-016, Q-PF-F-030. BM25 only: Q-PAPG-005, Q-PAPG-024, Q-PF-F-023, Q-PF-F-025.
- Books, both miss: Q-CB-H-001, Q-CB-H-007, Q-CB-H-025, Q-CB-J-007, Q-CB-J-009.
  System only: Q-CB-H-005, Q-CB-H-023, Q-CB-H-024, Q-CB-H-029, Q-CB-I-006, Q-CB-I-010, Q-CB-I-014, Q-CB-I-016,
  Q-CB-I-020, Q-CB-I-027. BM25 only: Q-CB-H-011, Q-CB-H-028, Q-CB-I-021, Q-CB-I-022, Q-CB-I-024, Q-CB-J-001,
  Q-CB-J-003, Q-CB-J-005, Q-CB-J-006, Q-CB-J-014.

The equal totals hide different miss sets: on both sets the systems agree on only 5 of the 9 (papers) and 5 of the 15
(books) misses. Paper-level misses (gold document absent from the top 10): system on books Q-CB-H-005, H-007, H-023,
H-024, H-029, I-006, I-016, I-027, J-009 (9 of 69); BM25 on books H-007, I-021, J-003, J-005, J-006 (5). System on
papers Q-PAPG-009, Q-PF-F-015, -016, -022 (4 of 61); BM25 Q-PF-F-025 (1). Seven of the ten books items the system
alone misses at passage level are paper-level misses (the gold book is not retrieved at all). Four of the ten BM25-only books misses are
also paper-level misses for BM25 (I-021, J-003, J-005, J-006). With 4:4 and 10:10 splits the comparison has no direction.

## 5. Pre-registered rules, each evaluated as written

| id | rule (source) | evidence | verdict |
|---|---|---|---|
| R1 | Headline is the lower of authored and ablated member hit@10 when they differ by more than 0.10 on the same items (7 i) | table in 3 | Applies to papers `on` (0.132), papers `off` (0.235), books book-passage (0.154). Headlines are the ablated values 0.658, 0.706, 0.635. Books pooled differs by 0.1014, just over 0.10; pooled rows are not headlines. |
| R2 | "Paper-level retrieval is semantic" needs the ablated paper-level value within 0.05 of authored (7 i) | papers 0.934 vs 0.770; books 0.870 vs 0.739 | **Not met** on either set. The claim may not be made. |
| R3 | Instrument-informative: BM25 chunk@10 <= 0.80 on the claimed stratum (7 ii) | papers `on` 31/38 = 0.816; books book-passage 39/52 = 0.750 | papers `on`: **above the bar**, claims there must say the instrument is near its lexical floor. books book-passage: **below the bar**, informative. |
| R4 | Regression guard for later tickets: 210-set R@10 falls below baseline count - 1; any stratum with n >= 10 loses more than one member-passage hit@10 question (4) | reference counts: 210-set 207/210; papers `on` 30, `off` 16; papers dimensions 9 / 17 / 16 / 10; books book-passage 41, equation-context 10 | Reference only. No arm to compare against, so no pass/fail. Strata with n < 10 are excluded by rule. |
| R5 | No absolute target (1.3, 4) | none | Nothing to evaluate; no gate exists on this baseline. |
| R6 | Paper R@10 is never a headline or gate (1.1, 3.3) | reported in 2.1, 2.2 | Satisfied; quoted as a tripwire only. |
| R7 | Absent arm cannot separate absent from answerable by construction (3.5, 7 iii) | 2.3 | Confirmed: ranges overlap. Not an abstention result. |

The protocol contains no pass/fail gate for this baseline; "gates" here are the reporting rules above.

## 6. Caveats

- `papers` set: system member hit@10 on `on` (30/38) is one item below BM25 (31/38); the protocol's own note (7 ii)
  said this stratum was already near its lexical floor. One item is 2.6 points (hw 0.15), so the two are not separable.
- Paper-level R@10 of the system (0.934 papers, 0.870 books) is below plain BM25 (0.984, 0.928). Protocol 1.1 expected
  paper-level recall to saturate. The cause is not examined here. The five books items with the gold book missing
  from the top 10 for the system alone and the ablation drop (0.935 -> 0.770 papers) say title words carry much of it.
- Ablation over-ablates (topical words shared with the title are removed too), so ablated values are lower bounds.
- Books pooled ablation difference is 0.1014, by 1 hundredth of a point over the 0.10 line; the headline rule applies to
  book-passage (0.154) regardless.
- Members: the member rule can over- or under-count only where chunks share anchors or stop early; on `papers` there
  are 0 shared anchors. Books items fall back to the anchor rule in 7 cases (`fallback_question_ids` in `books.json`),
  papers 1 (Q-PF-F-003).
- No repeat arm: jitter of this baseline is not measured here (protocol 5). Standards carries a repeat (0 hit flips,
  7 of 128 top-10 block lists differed).
- The 161/49 title split uses the report's verbatim predicate, not RV-3's 171/39; both are stated, neither altered.
- Limits as in protocol 11: LLM-authored items, not real queries; no answer quality; no abstention test; chapter routing
  not measured.
- The run directory is untracked and stays so; this report and the analysis folder carry the numbers. Analysis scripts
  and outputs: `docs/eval-reports/data/2026-11-11-baseline-analysis/`.
