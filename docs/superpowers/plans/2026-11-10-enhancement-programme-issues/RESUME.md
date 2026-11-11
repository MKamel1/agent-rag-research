# EP-2 resume notes (checkpoint, paused)

DELETE this file and `_wip/` before the final commit.

## Finished
- Read all sources. Ticket DATA is complete in `_wip/t1.py`, `t2.py`, `t3.py` (49 non-done tickets, dict per ticket; all 11 fields). `_wip/gen.py` is HALF written: it has the renderers for issue files (`body`, `write_issues`, `write_index`) and the data tables (DONE with SHAs, INPROG, TRACE, LANE, UNPLACED, WNT, QS, EMBED, CONSTRAINTS_DECIDED). Nothing has been run yet, no output files generated.
- Worktree: branch EP-EP2-ticket-set (from EP-programme-20261110). Scripts were authored in the session scratchpad `.../scratchpad/ep2/`; copies are in `_wip/`.

## Remaining
1. In gen.py: write the plan renderer (sections: 0 Context, 1 Inputs table, 2 Honest framing, 3 Operator decisions + questions F1-F8 with blocks, 4 Execution model + 13 global constraints (rule 13 = batching exception for PROJECT-STATUS/BACKLOG via EP-3/4/5), 5 ID scheme, 6 Wave map ASCII + exhaustive edges incl. GPU-serial chain, 7 Done/in-progress (W0), 8 Tickets by wave using `body()`, 9 Will not do (WNT), 10 Traceability (TRACE, LANE, UNPLACED), 11 Self-review), the BACKLOG section writer (append only, "## Enhancement programme (2026-11-10)", rows for done/in-progress/EP-2 READY/49 tickets), then run it.
2. Consistency check (throwaway): deps exist, no cycles, same-wave unordered pairs share no Owns path, every ticket has issue file + BACKLOG row, grep issue files for absolute paths (`/home|/tmp|/mnt`) and emails, titles <= 80 chars, ① starts with "stub".
3. pytest, ruff (no py files changed), enforcement; fix typos; commit; final message (<300 words).

## Decisions to remember
- IDs: EP-3/4/5 status-batch tickets per wave (Haiku); EP-6 docs remainder + CORPORA.md; EP-7 RUNBOOK. OP-2 lazy vector index, OP-3 snapshot checks, OP-4 take snapshot, OP-5 lock holder/timeout, OP-6 wrong-corpus guards, OP-7 compose. MC-1..4, RQ-1..5 (RQ-5 shared sparse_tokens = prerequisite of rider item 4, no S-nn), EV-7..22 (EV-15 = BM25 floor "EV-5b"), CQ-7..18, RIDER-1. W1=26, W2=8, W3=12, W4=3.
- S-02 mostly already done by EV-5 -> residual EV-7. S-06 split OP-5 + EV-10. S-07 split OP-6 + OP-2. S-09 one ticket. S-13 split across EP-1(external), EP-3, EP-6, EP-7. S-23 -> CQ-10/11; S-24 -> CQ-12..16; S-25 -> CQ-17/18; S-17 -> CQ-7 + EV-22; S-21 -> RQ-2/RQ-3. Live-application tickets are on-ADOPT follow-ons, not ticketed.
- Ownership conflicts resolved by sequencing: retrieval_eval.py chain EV-7>8>9>10>RQ-2; vector_index.py RQ-1>RQ-5>EV-14, CQ-9>CQ-17; reranker.py RQ-1>EV-13; retriever.py RQ-1>RQ-2; serve.py MC-2>MC-3>OP-2; assembly/doctor/snapshot OP-3>OP-6>OP-5>OP-2; parser.py CQ-12>CQ-13. GPU-serial chain: EV-16>18>19>20>21>22>RQ-3>CQ-10>CQ-11>CQ-15>CQ-16>CQ-18 (EV-17 off-chain, depends on EV-4).
- Shared with in-progress EV-4: FIXTURE-HASHES.json (EV-11; key-disjoint, EV-4 merges first).
- Flagged discrepancy: review S-19 says reset defaults to 32/0.5 if no arm wins; runbook rule G-1 says defaults stay (EV-20 default = G-1).
- Unplaced lane findings listed in gen.py UNPLACED (report them to the lead).
- Issue files must use `$(mktemp)` not /tmp paths; no personal names/emails.
