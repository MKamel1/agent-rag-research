# Ticket-set minimizer pass (advisory, "lazy designer")

Date 2026-11-10. Read-only challenge of `docs/superpowers/plans/2026-11-10-enhancement-programme.md` (51 tickets), its issue files and `docs/eval-reports/2026-11-10-system-review.md`. Advisory only; nothing here edits the plan.

## 0. Bottom line

- Only a handful of tickets are needed for a trustworthy first baseline. They are the eval-harness fixes (EV-7, EV-8, EV-9 shrunk, EV-10, EV-11 shrunk, EV-15) plus the three baseline runs (EV-16, EV-17, EV-18). Everything else is hygiene, speculation, or a downstream consumer of a number that does not exist yet.
- About 40% of wave 1 can wait (9 DEFER, 3 MERGE of 28) and nearly all of waves 3 and 4 is already gated; what the plan lacks is kill criteria that can be applied the moment the baseline lands (section 4).
- Guards against failures that actually happened (keep): SB-1 lock-timeout-scored-as-miss (EV-10), the run-script fixture rewrite and wrong checkout (already fixed by EV-5; EV-7 only closes the Python side), the usage-log id 327 empty result (MC-1), the 13% scorer under-count (EV-8), the 2026-07-30 backup (OP-4). Everything else guards a hypothetical or a "plausible story".
- Structural problem: many dependency edges are file-ownership or GPU-serial artefacts, not data dependencies (EV-9 -> EV-10, CQ-9 -> CQ-17, RQ-3 -> CQ-10, EV-20 -> EV-21). They inflate the critical path and the baseline gating. Cut them.
- Important observation: the eval harness reaches retrieval through `build_mcp_server`/`McpServer` (the plan says so for the `--collection` default). So MC-1/2/3, OP-2, OP-5 and MC-4 touch the code path the baseline measures, not only "the MCP surface".

## 1. Verdict table

Verdicts: KEEP / SHRINK / DEFER / MERGE / CUT. "Evidence" is harm measured or failure that happened vs a plausible story.

### Wave 1 (28)

| id | title | verdict | reason | cut / defer-until |
|---|---|---|---|---|
| CQ-7 | Ligature-repaired clone (CPU) | DEFER | Only consumer is EV-22; effect on retrieval unmeasured (CQ-1 changes 0 of 1,217 stored queries; BM25 floor already 0.96-0.98 paper recall). Clone costs 6-8 GB on a 98%-full disk plus F2 (vector store up). | Until EV-16 strata show damaged-gold passage hit@10 at least 10 points below clean gold, or at least 5 damaged-gold misses (computable from EV-16 rows, no extra GPU). |
| CQ-8 | Rechunk reuse by text hash | DEFER | Sole consumer is CQ-15, which is gated on the EV-18 structure count. Optimisation for a job that may never run. | Until EV-18 structure gate count is 5 or more. |
| CQ-19 | 38 authority items | DEFER | n=4 stratum; no baseline yet says authority is a problem. 38 items under the two-author blind regime is the single biggest token spend in W1. | Until EV-18 shows authority-stratum hit@10 clearly below the other standards strata (at least 2 of 4 failing), see section 6. |
| CQ-20 | 38 edition items | MERGE | Into CQ-19 as one deferred authoring ticket; sequenced on the shared hash file only. | Same as CQ-19; author only the stratum that is weak. |
| EP-3 | Batch ledger, wave 1 | MERGE | Into each ticket's own PR (section 5); also removes a 27-edge fan-in gate. | Orchestrator appends ledger rows when it merges each ticket. |
| EP-6 | CORPORA.md + drift rows | SHRINK | CORPORA.md, no-ingest rule and Decision 1 closure are real (stale doc misleads agents). HANDOFF and precision-95 status-tick rows are archaeology. | Cut the HANDOFF-2026-08-24 and precision-95 plan tick rows. Not on the baseline path. |
| EP-7 | RUNBOOK sections | MERGE | Backup/restore commands belong in OP-3/OP-4's PR; GPU-contention in OP-5's; container pointer in OP-7's; the `gpu_lock_path` one-liner anywhere. A cold-agent acceptance drill for a runbook is gold plating. | Fold into OP-3, OP-5, OP-7 docs lines. |
| EV-7 | Require --collection, hash stamp, gold preflight | SHRINK | Failure is real but already mitigated: EV-5's run scripts pass `--collection` and check hash. Keep for `app/retrieval_eval.py` (it is the instrument) and the gold-id preflight. | Cut `escalation_eval.py` and `score_distribution_census.py` (not run anywhere in the programme). |
| EV-8 | Excerpt-containment metric | KEEP | Measured: 8/61 and 4/74 items under-counted; headline of every baseline. Prerequisite. | none |
| EV-9 | Chunk ids in eval rows | SHRINK | Only consumer is EV-21 stub matching. But rows from the 1-2 h standards run cannot be recollected cheaply, so add the additive field now. | Add `retrieved_chunk_ids` to rows only; cut the `list_stub_chunks.py --ab` rewiring (do it if EV-21 is commissioned). Decouple from EV-10 (ownership order only). |
| EV-10 | Invalid run on lock timeout | KEEP | Happened (SB-1: questions counted as misses behind a 20-minute GPU job). Wave 2 is the same scenario. | none |
| EV-11 | Alternatives, re-freeze hashes | SHRINK | Real: 3 note-only duplicates; hash re-freeze must precede any run. | Cut the `merge_gt` orphan-tolerance change (run scripts no longer call `merge_gt`; no orphan ever observed). |
| EV-12 | CQ-3 pre-registration addendum | DEFER | Pure prerequisite of EV-21. | Until EV-21 is commissioned (see EV-21). |
| EV-13 | rerank_scored + absence census tool | DEFER | New experiment code in `rag/reranker.py` for a signal the plan itself says cannot be wired (needs 60+ absent items; has 9-24 per set). | Until an abstention feature is commissioned and 60+ distinct absent items exist. |
| EV-14 | Filtered-search overlap | SHRINK | Reasonable cheap closer for CQ-9 (mechanical 0.99 falsifier) but inferred, not observed, harm. Needs no clone: search is read-only. | Run exact vs HNSW on the live collection read-only; drop clone, drop OP-4 and RQ-5 dependencies. CPU-only, run while GPU is busy. |
| EV-15 | BM25 floor script | KEEP | Protocols require a floor beside every number; scratch script not committed; stdlib only. | none |
| MC-1 | Unknown paper_id raises | KEEP | Happened (id 327 vs 337); an agent reads empty as "not covered". Small. | none |
| MC-2 | Self-describing MCP server | SHRINK | Evidence: `doc_type` used 0 of 1,198 calls, wrong-corpus calls ids 8, 21-24. Instructions string and filter legend are cheap. | Cut the new `documents` list in `corpus_stats` (the metadata-tag dependency). |
| MC-3 | Scan/get telemetry | SHRINK | 18% of calls have no pattern; cheap. But no MCP work is scheduled that consumes it. | Bind pattern/args and error message only; cut `--client-label`. Decouple from MC-2 and OP-2. |
| OP-2 | Lazy vector index | DEFER | No failure cited; the server not starting with the store down is an inconvenience, and eight tools being SQLite-only is a nicety. Touches `app/assembly.py`/`serve.py` (the baseline path) behind a 4-ticket chain. | Until the operator needs MCP with services down. |
| OP-3 | Snapshot quick_check + checksums | KEEP | A corrupt snapshot looks like a good one until restore; the backup is the one unrecoverable-downside finding. | none |
| OP-4 | Fresh main snapshot | KEEP | Backup is 2026-07-30 and 1,364 papers behind; disk 98% full. Run it today, outside the programme queue. | Do not wait for F1 (only the off-device copy and deletions need it); abort rule 20 GB free already in plan. |
| OP-5 | GPU lock holder, fast fail | SHRINK | Real, current (foreign process holds 18.6 GB). Holder file and doctor foreign-process listing are cheap and diagnostic. The 20 s query-path timeout is a behaviour change on the baseline path and a Config field the rider must add later. | Keep holder file + doctor listing; defer the 20 s timeout until a contended real session shows the 300 s wait. Remove OP-5 as a gate of EV-16. |
| OP-6 | Wrong-corpus guards | SHRINK | Failure shape is real but eval is already protected by run-script `check-points`. | Keep `require_existing_db` in snapshot/corpus_integrity and the doctor pairing check; cut the `status.py:830` fallback and `reindex_idf` (no-op tool per section 9). Fold in the doctor disk check against the data-dir device (unplaced F-A10). |
| OP-7 | Track container definitions | KEEP | Read-only inspection, S size, no deps; protects a 31 GB store from a `latest` re-pull; needed before any operator container restart. | none |
| RQ-1 | Three one-line retrieval defects | DEFER | No measured harm (payload "latency inferred", permutation failure never observed, cap-with-paper_id minor). It changes retrieval code before the baseline. Better ordering: baseline first, then RQ-1, verified byte-identical against real-index baseline rows (stronger than the fake-only check the ticket has). | Until EV-16 has landed; then it is the first post-baseline change. Cut as a gate of EV-16. |
| RQ-2 | Opt-in relevance demotion | DEFER | Speculative until EV-17 shows off-topic share above the F6 bar. The "keeps the first GPU day from being wasted" argument fails: RQ-3 is 15 min and EV-17 gates it. | Until EV-17 share exceeds the operator's F6 bar. Note: share and a first demotion estimate are computable offline from EV-17 rows plus `relevance_score`. |
| RQ-5 | Shared `sparse_tokens()` | DEFER | Refactor of the index sparse path to enable rider item 4 and CQ-17, neither of which is happening before baselines; a tokenizer-drift failure has not occurred. | Until CQ-17/CQ-18 is a go. Keep the one-line ligature-map checksum test if wanted, separately. |

### Wave 2 (8)

| id | title | verdict | reason | cut / defer-until |
|---|---|---|---|---|
| EP-4 | Ledger batch wave 2 | MERGE | W2 is GPU-serial, so there is no concurrency conflict to batch around; each run ticket writes its own ledger row. | Fold into each EV ticket's PR. |
| EV-16 | Main baselines | KEEP | The first measurement; includes TEI `/info` truncation check. | Remove OP-5 and RQ-1 from its dependencies. |
| EV-17 | Focus baseline | KEEP | Answers the operator's focus question; 2-5 min; needs EV-4 hash freeze. | none |
| EV-18 | Standards baseline + structure gate | KEEP | The standards baseline and the gate-count for CQ-12/13/14/16. | Ensure per-question rows carry chunk ids (EV-9) and that the count is printed with qualifying questions. |
| EV-19 | Rerank-score census run | DEFER | Companion to EV-13; with n=9-24 absent items the CI will almost surely include 0.5, closing the gate it exists to open. No wiring is planned. | With EV-13. |
| EV-20 | Depth x weight grid | SHRINK | 1,200 queries / 40-90 min GPU against weak, sign-flipping prior evidence, with a net +3 bar on n=61-128. Standards depth is already decided by D-1 from EV-18's depth arms. | Drop standards and Waymo; run depth 32 vs 128 only (weight 0.5) on papers and books, and only if that set's passage hit@10 leaves at least 6 items of headroom. Weight arms wait. |
| EV-21 | Stub A/B | DEFER | Stubs are 7-10% of chunks but never shown to cost an answer; ceiling is the stub-at-rank-1 share. | Until baseline rows (with chunk ids) show stubs at rank 1 on at least 3 answerable items on some set, see section 4. Needs EV-12. |
| EV-22 | Ligature A/B | DEFER | Needs CQ-7 clone; effect unmeasured. | Until the damaged-gold stratum shows a gap (see CQ-7). |

### Wave 3 (12)

| id | title | verdict | reason | cut / defer-until |
|---|---|---|---|---|
| CQ-9 | Payload indexes on a clone | DEFER | Dies if EV-14 overlap is 0.99 or more. | EV-14 below 0.99 on any filter. |
| CQ-10 | Raise embedder token limit | CUT | Own ceiling says gain on current fixtures is 0 by construction (no GT item has a truncated gold chunk; 0 truncated in standards; 0.79% of main chunks). Needs operator container restart and VRAM/OOM risk. No harm measured. | Reopen if any EV-16 miss has its gold or top-10 chunk in `truncated_chunk_ids_main.txt`. |
| CQ-11 | Truncation decision note | CUT | Derived mechanically from CQ-10; one line in BACKLOG covers it. | With CQ-10. |
| CQ-12 | Section tracker golden tests | DEFER | Already self-gated at 5+ structure-attributable misses. | EV-18 count 5 or more. |
| CQ-13 | Furniture pre-pass + table sup/sub | SHRINK | Two unrelated changes in one ticket; furniture affects 4.7% standards chunks and may be fixed by CQ-12 rules. | Keep furniture pre-pass only if CQ-12 leaves furniture roots; cut table sup/sub/span handling (no miss attributed to tables). |
| CQ-14 | Stub folding + regex guard | DEFER | Third patch on the stub population (review rule (d)(4)); the regex guard fixes 23 blocks and only matters after a re-chunk. | After EV-21 verdict; cut the regex guard unless CQ-15/16 proceed. |
| CQ-15 | Standards re-derive + clone rechunk | MERGE | Into CQ-16 (one ticket: rebuild clone and measure). | Same gate as CQ-12. |
| CQ-16 | Standards rechunk verdict | DEFER | Ceiling is the EV-18 structure-attributable miss count; net +3 needed. | EV-18 count 5 or more. |
| CQ-17 | BM25 saturation flag | MERGE | Into CQ-18 (one ticket: flag plus clone A/B). Cut the CQ-9 dependency (file ownership artefact). | With CQ-18. |
| CQ-18 | BM25 A/B | DEFER | Unmeasured; needs clone and EV-22 repaired base. | Until the sparse arm is shown to matter, see section 4. |
| MC-4 | Slim MCP wire | DEFER | Cost is tokens only; agents already lower k; needs F5. | F5 = yes and telemetry shows k lowered. |
| RQ-3 | Demotion A/B | DEFER | Gated on EV-17 above the F6 bar. | EV-17 share above bar. |

### Wave 4 (3)

| id | title | verdict | reason | cut / defer-until |
|---|---|---|---|---|
| EP-5 | Final ledger batch | MERGE | Same as EP-3/EP-4. | Fold into each ticket. |
| RIDER-1 | Foundation rider | SHRINK | Items 3 (rerank_score note) and 4 (fake imports `sparse_tokens`) die with RQ-4 and RQ-5. Items 1/7 conditional on adoption. | Keep 5 (promote GT sets to `fixtures/eval/` with invariants test, the drift guard), 2 (reject dead `relevance_filter`) and 6 (ruff step, after F4). Add adopted items only. |
| RQ-4 | Expose rerank score | DEFER | Contract change for a signal with no consumer. | Until abstention is commissioned and EV-19 gate (which needs 60 items) can open. |

Counts: KEEP 10, SHRINK 12, DEFER 20, MERGE 7, CUT 2 (total 51).

## 2. Sequencing

### Smallest set for trustworthy first baselines (three corpora plus focus)

Not tickets: finish EV-4 (focus fixture 40 of ~50) and freeze its hash; answer F3 (the GPU). OP-4 is urgent but independent of the baseline; run it first and today.

1. EV-7 (retrieval_eval only: required `--collection`, hash stamp, gold preflight).
2. EV-8 (excerpt metric).
3. EV-9 shrunk (chunk ids in rows only). Combine 1-3 and EV-10 into one PR with four commits: they all own `app/retrieval_eval.py` and serialise anyway.
4. EV-10 (invalid run on lock timeout).
5. EV-11 shrunk (addendum, 3 alternatives, hash re-freeze). In parallel with 1-4 after EV-8 lands; hash file is shared with EV-4, keys disjoint.
6. EV-15 (BM25 floor), no deps, parallel anywhere.
7. Freeze a baseline commit (integration head) and record it in the run manifests.
8. EV-16, then EV-17 (needs EV-4 hash), then EV-18.

### What is missing from the critical path

- The strata report script (`scripts/eval_strata_report.py`, EV-6) is the reporting instrument for every headline and was never reviewed by any lane (plan section 10). Add a dry run of it on a fake-backed rows file before EV-16 and fold into EV-8's acceptance, no new ticket. Otherwise the first baseline's tables are an unreviewed instrument.
- An explicit "baseline commit" freeze (item 7). Today each baseline "runs on whatever is merged", and the plan relies on manifests to detect drift. Cheaper: freeze, land other code after.
- Nothing else. `doctor --cpu-only` (OP-1) and TEI `/info` (in EV-16) already exist. The three small corpora (Motional, Waabi, Waymo) get no baseline in this plan; say so explicitly rather than leaving it implicit.

### W1 tickets done "while waiting" without need

Not baseline prerequisites: OP-3, OP-5, OP-6, OP-7, MC-1, MC-2, MC-3, EP-6, EV-14 (hygiene, fine to run in parallel agent capacity, but they must not gate EV-16 and each should be reviewed for the merge risk it adds). Not needed at all yet: CQ-7, CQ-8, CQ-19/20, EV-12, EV-13, OP-2, RQ-1, RQ-2, RQ-5 (the "about half of wave 1 can wait" list, 9 DEFER + 3 MERGE).

## 3. Pre-baseline changes to retrieval or index behaviour

| ticket | what changes | defensible before baseline? |
|---|---|---|
| RQ-1 | payload fields on both arms, permutation raise (new failure mode), cap skip when `paper_id` set | No. Perf/hardening with no observed harm; better verified against baseline rows afterwards. Move after EV-16. |
| RQ-2 | `Retriever` kwargs and an eval flag (default off, byte-identical) | Defensible technically, unjustified: speculative before EV-17. Defer. |
| RQ-5 | index sparse path refactored through a new module | Defer; the "byte-identical on 200 chunks" check is fine but protects nothing now. |
| EV-13 | new `rerank_scored()` in `rag/reranker.py` | Defer with EV-19. |
| OP-5 | 20 s query-path timeout, holder file in `rag/gpu_lock.py` | Holder file yes. Timeout no: it changes failure behaviour under contention, which is precisely what wave 2 is. |
| OP-2 | lazy construction of the vector index in `assembly` | No, defer; startup path of the measured stack. |
| MC-1, MC-2, MC-3 | MCP-layer (`semantic_search` raising, instructions, logging) | Defensible: not ranking changes, and the eval harness gets the same results. But note they are on the baseline path via `McpServer`, so they must be merged before the frozen baseline commit, not during. |
| EV-14 | maybe one read-only `VectorIndex` method | Defensible (read-only). |
| CQ-7/8/9/17 | clone or rechunk tooling | No live effect; not a retrieval change. Deferred for cost, not risk. |

Principle: the baseline is the reference for everything. Only instrument fixes and read-only/diagnostic changes may precede it; any behaviour-touching change lands after, verified against the real baseline rows.

## 4. W3 kill criteria (apply the moment the baseline numbers arrive)

| ticket | kill it if |
|---|---|
| CQ-9 | EV-14 overlap at least 0.99 on all three filters (already pre-registered), or no baseline query returned fewer than k hits. |
| CQ-10 | None of the baseline's missed-gold chunks or top-10 chunks is in `truncated_chunk_ids_main.txt` (expected, since 0 of 48 GT items have a truncated gold chunk). |
| CQ-11 | CQ-10 killed. |
| CQ-12 | EV-18 structure-attributable misses fewer than 5 (own gate), or standards passage hit@10 leaves under 5 items of headroom. |
| CQ-13 | After CQ-12's in-memory re-derive, zero furniture roots remain among the qualifying-miss questions; table half: none of the qualifying misses has a table chunk as gold. |
| CQ-14 | EV-21 is REJECT, or stub-at-rank-1 occurs on fewer than 3 answerable standards items, or fewer than 3 qualifying misses have a stub in the top 10. |
| CQ-15 | CQ-12/13/14 all killed; or F7 says keep stored paths and the operator will not pay the 35k re-embed (derived-column paths never reach the embedder). |
| CQ-16 | EV-18 structure-attributable miss count is below 5 (net +3 is unreachable) or the CQ-15 clone shows fewer than 3 flipped questions. |
| CQ-17 | On every set, fused minus dense-only passage hit@10 is 2 items or fewer (the sparse arm contributes nothing detectable), or sparse-only passage hit@10 is within 3 items of the plain-BM25 floor on every set (the weighting approximates BM25, which is already there). |
| CQ-18 | Same as CQ-17, or EV-22 shows ligature repair itself already changed the sparse arm materially so that attribution is muddied and no gain remains. |
| MC-4 | F5 = no; or MC-3 telemetry shows default-k calls are not being lowered by agents; or a standards k=10 response (about 4.2k tokens) is acceptable to the operator. |
| RQ-3 | EV-17 off-topic top-10 share is below the F6 bar; or an offline demotion on EV-17 rows (using `relevance_score`) removes under 50% of off-topic top-10 slots or drops any gold on papers-passage or books. |

(Also: RQ-4 dies if the EV-19 census, when run, has a CI containing 0.5 on two of three sets, which is the plan's own rule and, with 9-24 absent items, the likely outcome.)

## 5. Documentation batching (EP-3/EP-4/EP-5)

Fold docs into each ticket; drop the three batch tickets. Reasons: (1) AGENT-PROCEDURES §B says ledger entries are same-PR and not deferrable ("deferring exactly that is what produced the 2026-08-05/06 backlog this doc exists to prevent recurring"); the plan's declared exception recreates that failure on purpose. (2) The conflict argument is weak: W2 and most of W3 are GPU-serial, so there is no concurrency; in W1 the ledger and BACKLOG rows are append/flip operations that conflict trivially, and the orchestrator already merges into one integration branch. (3) EP-3 fans in 27 dependencies, EP-4 re-quotes verdicts from reports (a second place to get a verdict wrong), EP-5 depends on every W3/W4 outcome including closed-by-gate tickets. (4) With 12 W1 tickets removed there is less to batch anyway. If the operator still wants one conflict-free pass for W1 only, make it a non-gating sweep done by the orchestrator, not a ticket on the dependency graph.

## 6. Standards authority/edition authoring (CQ-19, CQ-20)

Premature. n=4 per stratum is a limit of description, not evidence of a problem; the plan itself says the tag filters (CQ-5) are done and nothing consumes the strata. The baseline's descriptive stratum numbers will say whether authority/edition questions fail at all. Authoring 76 items under the two-author blind plus cross-verification regime, with 0 kills seen on standards so far (same model family), is the largest token and review spend in wave 1. Merge into one ticket, run only after EV-18, and author only for the stratum that is visibly weak (for example, 2 or more of the 4 current items missing at hit@10 while other strata are strong). Also note the EV-18 "may run them as a descriptive stratum if frozen before launch" clause adds a hash-file dependency to the baseline path; remove it.

## 7. The 14 unplaced lane findings (plan section 10)

1. RV-3 F-1.1 one-command regression gate: DROP now; revisit after EV-16/18 manifests exist (a diff script over stored baselines).
2. RV-3 F-1.6 question-style realism controls: DROP (needs operator time; title-ablated arm already reported; the "questions twice as long as real queries" caveat is already in section 2).
3. RV-3 F-1.12 chapter-level is a heading-string match: FOLD one caveat sentence into EV-11's addendum.
4. RV-2 F-2.7 front/back-matter role classifier: DROP; reopen if EV-9 chunk ids show reference/TOC chunks in top-10 slots.
5. RV-2 F-2.11 books outline join: DROP; reopen only if EV-16 shows flat-book chapter-level misses.
6. RV-2 F-2.13 3,500-char metric: DROP.
7. RV-4 F-4.7 `get_section` clause prefix / `section_pattern`: DROP; reopen on MC-3 telemetry (4 clause references in 242 queries).
8. RV-4 F-4.9 error path text, nearest-id hints, async wrappers: DROP.
9. RV-4 F-4.10 reorder BACKLOG MCP-E rows: DROP (already recorded in section 9).
10. RV-6 F-A7 migration snapshot guard, `busy_timeout` (quick_check carried): DROP (no migrations planned; `migrations/` protected).
11. RV-6 F-A9 canary slice, usage-log top-score columns: DROP (the canary is item 1 again).
12. RV-6 F-A10 dashboard bind, doctor disk check cwd-only, `.phase0-data` naming: FOLD the doctor disk check (device of the data dir, matters at 98% full) into OP-6; DROP the rest.
13. RV-5 F-5.7, F-5.11, F-5.12 (supply, rebuildability, seed reproducibility): DROP (no harvest scheduled).
14. RV-1 F-1.12 per-paper diversity default: DROP (lane recommends no change).

## 8. "Will not do" table: missing entries

Add, so they are not re-proposed:
- MCP confidence/abstention wiring and score floors (stated only in section 2 and 10 scope notes, not in the table).
- Focus lever options C (blending) and D (collection split); hard drop or filter of off-topic papers (stated only below the table as an operator decision).
- Writing `relevance_score` into the vector payload (RQ-3 follow-on) unless pool starvation is observed.
- GPU-lock priority scheduler and reranker-failure fallback to fused order (rejected in OP-5's Out section).
- Restart policy on containers; auto-restart of the foreign model server.
- CQ-10/CQ-11 truncation route (if CUT as above), reopen on a truncated gold chunk.
- Edge-punctuation tokenizer change (named in CQ-17 Out).
- Baselines for the Motional, Waabi and Waymo corpora (currently implied by omission).
- Resetting per-corpus defaults to 32/0.5 (the plan notes the conflict with G-1; record which wins).
- Any off-device backup tooling until F1 yields a target.

## 9. Recommended ticket counts per wave

| wave | plan | recommended | note |
|---|---|---|---|
| W1 do now | 28 | 16 | OP-4 (now), 6 baseline-critical eval tickets (EV-7, 8, 9s, 10, 11s, 15, ideally one PR for 7-10), 9 hygiene (OP-3, OP-5s, OP-6s, OP-7, MC-1, MC-2s, MC-3s, EP-6s, EV-14s) that must not gate the baseline |
| W2 first GPU session | 8 | 3 firm + 1 conditional | EV-16, EV-17, EV-18; EV-20 shrunk, only if headroom |
| W3 gated | 12 | 8 conditional (CQ-9, CQ-12, CQ-13s, CQ-14, CQ-16 merged, CQ-18 merged, MC-4, RQ-3) | plus 2 CUT (CQ-10, CQ-11) and 2 MERGE; parked W1/W2 items (CQ-7, 8, 19+20, EV-12, 13, 19, 21, 22, OP-2, RQ-1, 2, 5, RQ-4) wake only on their named measurement |
| W4 | 3 | 1 | RIDER-1 shrunk to items 5, 2, 6 plus whatever is adopted |

Total: 51 -> 42 rows (7 merged away, 2 cut), of which about 20 are active, about 21 are parked behind a named measurement, 1 is the final rider.
