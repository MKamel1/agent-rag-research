# Rerank depth 32 vs 128 (EV-20, shrunk): result, 2026-11-11

**Verdict (pre-registered rule, per set, not pooled):**
**papers: PREFER 128 (provisional) by the >= 2 rule, but G-1 NOT met, so NO default change recommended.
books: PREFER 128 (provisional) by the >= 2 rule AND G-1 met, so a default change to 128 is RECOMMENDED by the rule.**
The two sets give different recommendations. Whether to change the main-corpus `rerank_depth` (one value serves both
sets) is an OPEN OPERATOR DECISION; this report does not choose. Nothing was changed.

Pre-registration: `docs/eval-reports/data/2026-11-11-session2/PREREGISTRATION.md` section 1 (rule) and section 0 (gates,
minimum detectable effect). Register: `EXPERIMENT-REGISTER.md`.

## 1. Question asked

At the shipped hybrid weight 0.5 and fused mode, does reranking a pool of 128 candidates instead of 32 raise passage
retrieval on the main corpus (`papers` collection) for the papers set and the books set? Standards depth is decided by
the standards baseline (rule D-1: keep 128) and was not run here. Waymo, and the 0.7 / 1.0 weight arms, were not run.

## 2. What was run

| item | value | source |
|---|---|---|
| code commit | `03cfd1854b7d37c8116d35545c3f54a309e6da40` (merge of RQ-2; the baseline ran at `626fac3`) | `GIT_COMMIT`, `MANIFEST.txt` |
| window | 2026-11-11 09:54:16 to 10:41:13 (-07:00), 46 min 57 s | `MANIFEST.txt` |
| collection | `papers` (412,167 points), fused, dense weight 0.5, shipped config otherwise; arms differ only in `rerank_depth` | `config-depth32.yaml`, `config-depth128.yaml` |
| fixtures | papers 61 questions (61 answerable, 61 scored); books 74 (69 answerable and scored) | `MANIFEST.txt`, PREREGISTRATION section 0 |
| fixture hash check | `papers_passage_gt.json` `58cdbf47f08b00fa...`, `causal_books_gt.json` `3c21d57bb6cb8949...`, hashes file `7f2fa1fc352f...`; match `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json` (script runs `check-hash` before any service call) | `MANIFEST.txt` |
| arms | original fixture: `depth32` and `depth128` per set (depth32 is a fresh re-run of the baseline arm and is the validity gate); title-ablated arms (`ablated.depth32`, `ablated.depth128`) run because 128 led by >= 2 on the original fixture | `depth_compare.log` lines "128 leads by the >=2 rule -> spending the title-ablated arms" |
| errors | 0 errored questions in every pair | `pair-*.txt` (`errored base/arm=0/0`) |
| wall-clock per arm (start-to-start gaps in the console log, includes scoring) | papers depth32 3 min 35 s (09:54:16 to 09:57:51); papers depth128 6 min 56 s (09:57:51 to 10:04:47); books depth32 4 min 32 s (10:15:29 to 10:20:01); books depth128 8 min 46 s (10:20:01 to 10:28:47). Depth 128 took about 1.9x the wall-clock of depth 32 | `/tmp/.../scratchpad/depth_compare.log` (timestamp lines) |

Console log (not committed, large): `/tmp/claude-1000/-home-omar-ai-projects/3426f8b7-1c1a-4487-ad8c-3b6a5cbe5792/scratchpad/depth_compare.log`.
Evidence committed: `docs/eval-reports/data/2026-11-11-session2/runs/depth-20261111T095413/` in full (2.7 MB: per-arm reports,
logs, pair files, strata, verdict JSON, RESULT.txt).

## 3. Results (metric of record: member-passage hit@10, 128 minus 32; every pair file is `pair-<set>[.ablated|.jitter].txt`)

Ceiling precondition (headroom = scored answerable - baseline hits, must be >= 6): papers 61 - 52 = 9; books 69 - 54 = 15. Both
pass; computed from the `base=` counts in `pair-papers.jitter.txt` and `pair-books.jitter.txt`.

| set | arm pair | n | depth32 hits | depth128 hits | ratio 32 -> 128 | wins:losses | net | source |
|---|---|---|---|---|---|---|---|---|
| papers | original | 61 | 52 | 54 | 0.852 -> 0.885 | 2:0 | +2 | `pair-papers.txt` |
| papers | title-ablated | 61 | 41 | 46 | 0.672 -> 0.754 | 6:1 | +5 | `pair-papers.ablated.txt` |
| books | original | 69 | 54 | 57 | 0.783 -> 0.826 | 4:1 | +3 | `pair-books.txt` |
| books | title-ablated | 69 | 47 | 50 | 0.681 -> 0.725 | 4:1 | +3 | `pair-books.ablated.txt` |

Beside the metric of record (same pair files, never deciding):

| set | arm | paper Recall@10 (32 -> 128, net) | excerpt hit (32 -> 128, net) | anchor hit (32 -> 128, net) |
|---|---|---|---|---|
| papers | original | 57 -> 58 (+1; 2:1) | 52 -> 54 (+2) | 51 -> 54 (+3) |
| papers | ablated | 47 -> 49 (+2; 4:2) | 41 -> 46 (+5) | 41 -> 46 (+5) |
| books | original | 60 -> 63 (+3; 4:1) | 54 -> 57 (+3) | 54 -> 57 (+3) |
| books | ablated | 51 -> 53 (+2; 5:3) | 47 -> 50 (+3) | 47 -> 50 (+3) |

The excerpt metric agrees in sign with the metric of record on every row.

Gating strata (n >= 10), member hit@10 net, original fixture: papers equation-context 9 -> 9 (+0), method-detail 17 -> 17 (+0),
numeric-result 16 -> 16 (+0), paper-passage 10 -> 12 (+2); worst +0. Books book-passage 41 -> 42 (+1), equation-context 10 -> 11 (+1);
worst +1 (table-requirement n = 5, not gating, 3 -> 4). The whole papers net comes from the paper-passage stratum
(`pair-papers.txt`). Ablated: papers strata nets +2, +2, +1, +0 (worst +0); books book-passage +3, equation-context +0.

## 4. Rules evaluated literally

| rule | papers | books | source |
|---|---|---|---|
| validity gate: depth32 re-run vs baseline run, \|net\| <= 1 | net 0 (0:0), PASS | net 0 (0:0), PASS | `pair-papers.jitter.txt`, `pair-books.jitter.txt`, RESULT.txt "validity gate passed" |
| precondition headroom >= 6 | 9, PASS | 15, PASS | section 3 |
| ">= 2 rule": 128 gains >= 2 net with no gating stratum losing more than one (net <= -2) | net +2, worst stratum +0: **prefer 128 (provisional)** | net +3, worst +1: **prefer 128 (provisional)** | `verdict-*.json` `rule_ge2_prefers` |
| G-1 net >= +3 | +2: FAIL | +3: pass | `verdict-*.json` `G1_core` |
| G-1 wins:losses >= 3:1 (zero losses passes) | 2:0 pass | 4:1 pass | same |
| G-1 no gating stratum losing more than one | pass | pass | same |
| G-1 same sign on the title-ablated arm | +5, pass | +3, pass | `G1_ablated_same_sign` |
| G-1 overall (`G1_core`) | **false** | **true** | `verdict-*.json` |
| default change recommended only if BOTH the >= 2 rule and G-1 hold | **no** (`recommend_default_change: false`) | **yes** (`recommend_default_change: true`) | `verdict-*.json`, `RESULT.txt` |

Precedence between the two rules is stated in PREREGISTRATION section 7 item 1: the >= 2 rule only decides whether the ablated
arms are spent and which way the "prefer" line leans; G-1 alone decides a default change. The review fallback ("otherwise reset
everything to 32/0.5") was not applied. `verdict-*.preliminary.json` are the pre-ablation verdict files written mid-run; the
final ones are `verdict-papers.json` and `verdict-books.json`.

## 5. Validity and noise

Jitter gate passed on both sets with net 0 and no discordant pairs (retrieval and rerank were deterministic across the re-run of
the baseline arm at a different commit). Errors 0. Statistical power (PREREGISTRATION section 0): reaching two-sided p < 0.05 on a
paired sign test needs 6:0 or 8:1. Post-hoc arithmetic, not part of any rule: the exact two-sided sign-test p-values for the
observed discordant counts are 0.50 (papers 2:0), 0.375 (books 4:1), 0.125 (papers ablated 6:1), 0.375 (books ablated 4:1). No
arm comparison here is significant; these are materiality-floor verdicts.

## 6. Caveats

- Curated sets of 61 and 69 questions; effects below about 6 net questions are undetectable. The books recommendation rests on 5
  discordant questions.
- `rerank_depth` is a property of the main corpus config and serves both sets. Books say change (G-1 met), papers say G-1 not met
  while leaning 128 by the weaker rule; nothing in the pre-registration says how to combine them.
- The cost side is real: depth 128 took about 1.9x wall-clock per query batch in this run (section 2). No latency or GPU-memory
  measurement beyond that was taken, and the effect on production traffic is not measured.
- Weight (0.7 / 1.0), standards and Waymo depth were not tested here.
- The title-ablated fixture is derived from the same questions, so it is not an independent replication.

## 7. Do not re-run unless

Retrieval is deterministic for a fixed index, code and config (jitter gate: 0 discordant). An identical re-run reproduces this
table and costs about 47 GPU minutes. Re-run only if one of these has changed:

1. The `papers` collection was re-chunked, re-embedded, re-sparsed or had its point count changed from 412,167 (e.g. the
   ligature clone `papers__ligrepair_20261111` is promoted, a stub filter or re-chunk is adopted). Check: point count in
   `app.doctor`, and `git log -- rag/chunker* scripts/rechunk*`.
2. The embedder or reranker model or its serving flags changed, or the shipped `hybrid_dense_weight` is no longer 0.5. Check:
   `docker inspect` of the TEI containers; diff the data-dir `config.yaml` against `config-depth32.yaml` in the run directory.
3. A new passage fixture exists with more headroom (papers 9 and books 15 misses at baseline is small) or more questions: the
   sign-test needs 6:0 or 8:1, so a fixture with about 150+ answerable questions and 20+ baseline misses. Check: fixture hashes
   differ from `data/2026-11-10-FIXTURE-HASHES.json`.
4. The operator changes a threshold (the +2 or +3 floor) or decides how to combine the two sets; that needs a dated addendum to
   PREREGISTRATION and re-reading these rows, not necessarily a new run (the per-question rows are in the run directory).
5. The operator asks for the weight grid at depth 128 (0.7, 1.0): a different, un-run experiment, not a re-run of this one.

Cheap pre-check: compare `git rev-parse HEAD:rag/` between the run commit `03cfd18` and now (`git diff --stat 03cfd18 -- rag app`);
if empty and the fixture hashes and collection point count match, the answer is already here.
