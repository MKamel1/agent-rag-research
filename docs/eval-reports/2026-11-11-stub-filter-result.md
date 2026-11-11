# Stub-chunk filter A/B (EV-21, with the EV-12 addendum): result, 2026-11-11

**Verdict (pre-registered kill rule): KILLED before any arm ran.** Stub-at-rank-1 occurs on at most 1 answerable item on every set
(max 1, threshold 3); every set was also SKIPPED on the ceiling rule (ceiling 0 < minimum effect 2). The `--drop-stub-chunks`
default stays off. No GPU retrieval was spent.

Pre-registration: `docs/eval-reports/data/2026-11-11-session2/PREREGISTRATION.md` section 2 and the EV-12 addendum in
`docs/eval-reports/2026-11-10-cq3-stub-chunks.md`. Register: `EXPERIMENT-REGISTER.md`.

## 1. Question asked

Would dropping heading-only "stub" chunks (body < 40 characters, `rag.retriever._MIN_BODY_CHARS`) at query time raise member-passage
hit@10? The A/B was gated by a CPU ceiling computed from the baseline rows before any GPU use.

## 2. What was run

| item | value | source |
|---|---|---|
| script | `docs/eval-reports/data/2026-11-11-session2/run_stub_ab.sh`, started 11:59:18, exit 0 at 11:59:22 (4 s) | `gpu_queue3.status`, `CONSOLE.txt` |
| code | HEAD `03cfd18`; the script warned that `rag/ app/ contracts/` differ from the baseline commit `626fac3` (irrelevant here: only the CPU ceiling over existing rows ran) | `CONSOLE.txt` |
| baseline rows read | main-corpus run `docs/eval-reports/data/2026-11-10-papers-passage-gt/runs/20261111T004734` (papers, books) and standards run `.../2026-11-10-standards-gt/runs/20261111T013215` (`depth128-fused.json`); both untracked, in the PB worktree / data tree | `/tmp/.../scratchpad/gpu_queue3.sh` |
| fixtures + hash check | papers, books, standards; `hash check OK (3 fixtures)` | `CONSOLE.txt` |
| arms run | none | `ceiling-*.json` all `"run": false` |

Evidence committed: `docs/eval-reports/data/2026-11-11-session2/runs/stub-20261111T115918/` (`ceiling-{papers,books,standards}.{json,txt}`)
plus `CONSOLE.txt` (the console log filtered of HTTP lines, copied from the scratchpad `q3_stub.log` so the kill line is durable).

## 3. Results (source: `ceiling-<set>.json`)

| set | answerable n | stub at rank 1 (answerable) | stub top-k slots / all slots | slot share | answerable with a stub in top-10 | ceiling C (baseline misses that carry a stub) | run |
|---|---|---|---|---|---|---|---|
| standards | 106 | 1 | 5 / 1280 | 0.0039 | 4 | 0 | no |
| papers | 61 | 0 | 0 / 610 | 0.000 | 0 | 0 | no |
| books | 69 | 0 | 12 / 740 | 0.0162 | 3 | 0 | no |

For context (not an input to the rule): stub chunks are 9.1% of main-corpus chunks and 6.95% of standards chunks
(`PROJECT-STATUS.md` section 1.2), yet at baseline they occupy 0% to 1.6% of the returned top-10 slots.

## 4. Rules evaluated literally

| rule | evaluation |
|---|---|
| per-set skip: ceiling C < minimum effect 2 | C = 0 on standards, papers and books: all three SKIPPED ("skipped: ceiling" printed for each) |
| kill: stub-at-rank-1 on fewer than 3 answerable items on EVERY set | max over sets is 1 (standards): **KILLED**, printed "killed: ... (max 1); EV-21 trigger / minimizer s.4. No arm run." |
| ADOPT conditions (a) stub-at-rank-1 > 0 on a set, (b) net >= +2, (c) no gating stratum losing more than one | not evaluable (no arm); (a) holds only on standards with a count of 1 |

Verdict wording per PREREGISTRATION section 6 would be REJECT or SKIPPED per set; the kill rule is more specific and fired first.
Consequence stated in the CQ-14 ticket's kill criterion: "killed if ... stub-at-rank-1 occurs on fewer than 3 answerable standards
items" is met (1 < 3); this commit records that but does not close CQ-14.

## 5. Validity and caveats

- The ceiling is computed from the top-10 rows only; a stub deeper in the 32 or 128 rerank pool is invisible, so C understates
  second-order effects (PREREGISTRATION section 2, "cannot show"). A stub that never reaches the top-10 cannot cost a hit.
- Stubs are identified by chunk id (`retrieved_chunk_ids`) with the 40-character threshold; a rank counts as a stub only if every
  candidate chunk id at that rank is a stub (ambiguity resolves against calling it a stub).
- Rows come from curated fixtures (61 / 69 / 106 answerable); this says nothing about real queries that target short headings.
- Jitter between the baseline commit and HEAD did not matter: no arm was run.

## 6. Do not re-run unless

Re-running the ceiling is CPU-only and free; re-running the GPU A/B is pointless unless the ceiling changes. Re-evaluate only if:

1. Retrieval changed so stubs enter the top-10 more often (reranker, fusion weight, depth, a chunker change that emits more or
   different stubs, a new collection). Cheap check: `python scripts/session2_ab_tools.py stub-ceiling --report <new baseline report> --gt <fixture> --db <papers.db>`
   (how `run_stub_ab.sh` calls it); the A/B is justified only if stub-at-rank-1 >= 3 on some set AND ceiling C >= 2 there.
2. A new fixture with many heading/clause-title or short-section lookups (where stubs are plausible answers or competitors) and
   baseline rows that show stub-at-rank-1 on >= 3 answerable items.
3. The chunker is changed to fold or stop emitting stubs (CQ-14): then the question becomes a rechunk measurement, not this filter.
4. A threshold change (the 3-item kill or the 2-item minimum effect): dated addendum, then re-run the CPU ceiling on the stored rows.
