# Session 2: launch sheet

Rules are in `PREREGISTRATION.md` (committed before any script existed). Nothing here has been run against a
service; the scripts were tested only with `bash -n`, fake baselines (they fail closed) and the offline unit
tests in `scripts/test_session2_ab_tools.py`. Run from this directory in the `agent-rag-research` env, from a
CLEAN tree (the scripts stamp `git rev-parse HEAD`). Baseline run directories are the `runs/<stamp>` of
`2026-11-10-papers-passage-gt/run_baseline_main.sh` (call it `$BM`) and
`2026-11-10-standards-gt/run_baseline.sh` (`$BS`).

```
cd /home/omar/ai-projects/research-system-rag/docs/eval-reports/data/2026-11-11-session2
conda activate agent-rag-research
```

## What may be modified

Only the clone `papers__ligrepair_20261111`, created and resparsed by `prepare_ligature_clone.sh`. Every other
script is read-only against corpus DBs, live collections and fixtures (no script writes or rewrites a fixture or a
hash). Outputs go to `runs/<step>-<stamp>/`.

## Order and commands (cheapest first; one GPU job at a time)

CPU only, any time the vector store is up (does not need the GPU):

| step | command | duration (estimate) |
|---|---|---|
| EV-14 dry run | `./run_filtered_search_check.sh 10` | minutes |
| EV-14 full | `./run_filtered_search_check.sh 100` | 20-60 min CPU |
| CQ-7 clone | `./prepare_ligature_clone.sh` (aborts under 20 GB free disk, expected clone 6-8 GB, and under 16 GB free RAM) | clone tens of minutes + resparse 7-20 min |

GPU, after the baselines finish and the queue releases the GPU (`python -m app.doctor` in the data dir first):

```
./run_session2.sh "$BM" "$BS"            # steps 1 -> 2 -> 3 (3 is skipped with a message if the clone is absent)
# or one at a time:
./run_depth_compare.sh "$BM"             # EV-20 shrunk, optional set args: papers books
./run_stub_ab.sh "$BM" "$BS"             # EV-21, optional set args: standards papers books
./run_ligature_ab.sh "$BM" papers__ligrepair_20261111 [--dense-control]   # EV-22
```

`run_session2.sh` prints the GPU estimate first, logs START/STOP per step, continues past a step that SKIPS by its
own rule (exit 0), and stops on a failure (non-zero).

| step | queries x arms | est. GPU (3.6 s/q @32; 10 s/q @128, an assumption) | runs only if |
|---|---|---|---|
| 1 depth | per set: 61 (papers) / 74 (books) x {32,128}; plus the ablated pair (about 61 / 69 x 2) only if 128 leads by >= 2 | 31 min; 60 worst | baseline member hit@10 leaves >= 6 items of headroom on that set, else `skipped: ceiling` |
| 2 stub | standards 128 x 2 (depth 128), papers 61 x 2, books 74 x 2 = 526 | up to 59 min | set ceiling C >= 2; whole step killed if stub-at-rank-1 < 3 on every set |
| 3 ligature | (61 + 74 + 210) x {live, clone} x {sparse_only, fused} = 1,380 (+690 dense control) | 83 min (+41) | clone exists, counts equal, 0 stale on clone, query-repair-check clean |
| EV-14 | 8 filters x 100 x 2 searches x 2 collections, CPU | no GPU | vector store up |

Worst-case total 202 min (3.4 h). The first run replaces every estimate: each `MANIFEST.txt` stamps start/finish.

## How to read each result

All verdicts print in `runs/<step>-<stamp>/RESULT.txt`; every `pair-*.txt` has per-metric wins/losses/net and the
strata table (gating strata, n >= 10, are marked). Metric of record = member-passage hit@10; the excerpt metric
and paper Recall@10 are in the same table. A `VALIDITY GATE FAILED` line means the re-run baseline arm differs
from the baseline run by more than 1 question: that step is NOT INTERPRETABLE, read nothing from it. n of 61-94
cannot show effects under about 6 net questions; the thresholds are materiality floors, not significance.

1. Depth (`verdict-<set>.json`): `rule_ge2_prefers` is "32" unless 128 gains >= 2 with no gating stratum losing
   more than one. A default change is recommended only if `recommend_default_change` is true (that also needs rule
   G-1: net >= +3, wins:losses >= 3:1, same sign on the title-ablated arm). Otherwise defaults stay.
   `skipped: ceiling` means the set had under 6 items of headroom: closed by the gate.
2. Stub (`verdict stub`): ADOPT only if a set with stub-at-rank-1 > 0 improved by >= 2 AND no gating stratum on any
   run set lost more than 1; else REJECT. `ceiling-<set>.txt` is the pre-run bound (misses that carry a stub in the
   top 10). ADOPT still needs the sign-off rider; nothing is switched on.
3. Ligature (`verdict ligature`): the CQ-2 rule. `a_...` = sparse_only paper Recall@10 on the passage set strictly
   higher on the clone; `b_...` = fused paper Recall@10 and member hit@10 no worse than -1 on papers and books.
   REJECT is final; the best outcome is `ADOPT-PENDING-STANDARDS` (no `av_standards` clone tonight). Read the damaged
   vs clean strata in `pair-<set>.<mode>.txt` (`ligature=damaged` / `ligature=clean`, expected 35/26 and 27/42).
   Legacy 210 is an anchor only (paper Recall@10 and stock metrics), named by no clause.
4. EV-14 (`runs/filtered-*/papers.json`, field `verdict`): `CLOSE CQ-9` if mean overlap@10 >= 0.99 on F1, F3, F4, F6
   (binding); `CQ-9 TRIGGER MET` otherwise. Other filters and `av_standards` are informational. `n_short_lists` is the
   count of queries returning fewer than k.

## What each ligature arm measures (read this before quoting the A/B)

`rag/vector_index.py::_sparse_vector` repairs tokens with `repair_ligatures(text.lower())` on BOTH `upsert` and
`hybrid_search`, unconditionally. So: arm A (live `papers`) = repaired query vs UNREPAIRED index; arm B (clone)
= repaired query vs repaired index (and repaired IDF statistics). A-vs-B isolates the index-side repair only. A
clean pre-CQ-1 vs post-CQ-1 comparison would need rows from the pre-CQ-1 code; they do not exist (CQ-1 is in the
baseline commit) and are not reconstructed. `run_ligature_ab.sh` first proves the query-side repair changes no
question string in the three fixtures (verified offline 2026-11-11: 0 of 61, 74 and 210 changed), which makes arm
A behave as pre-CQ-1 on these questions. The only other difference between the collections is the separately
built HNSW graph (`--dense-control` measures that).

## EV-14 request bodies (REST; the only calls made)

```
GET  /collections/<c>
POST /collections/<c>/points/scroll
  {"filter":{"must":[<population conditions>]},"limit":1,"with_payload":["paper_id","kind","doc_type","categories"],
   "with_vector":["dense"],"offset":"<uuid from random.Random(20261111)>"}
POST /collections/<c>/points/query
  {"query":<stored dense vector>,"using":"dense","filter":{"must":[<kind eq>, ...]},"limit":11,
   "params":{"exact":false|true},"with_payload":false}
```
Condition shapes (mirroring `_qdrant_filter`): `{"key":"kind","match":{"value":"summary"}}`,
`{"key":"doc_type","match":{"value":"book"}}`, `{"key":"paper_id","match":{"value":"<own>"}}`,
`{"key":"categories","match":{"any":[...]}}`, and for `doc_type=paper`
`{"should":[{"key":"doc_type","match":{"value":"paper"}},{"is_empty":{"key":"doc_type"}}]}`. The script rejects
any endpoint other than `points/scroll` and `points/query`. The vendor-isolation CI check scans only `rag/`,
`contracts/` and `app/` (`ci/checks/model.py::PIPELINE_SCOPE_PREFIXES`), so `docs/` is outside it.

## After the A/B

Delete the clone (printed by `prepare_ligature_clone.sh`, not executed by any script):
`curl -fsS -X DELETE http://localhost:6333/collections/papers__ligrepair_20261111`.
