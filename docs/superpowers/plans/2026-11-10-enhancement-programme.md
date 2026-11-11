# The enhancement programme: instruments first, measurements second, gated changes last

Written 2026-11-10, before execution (house rule from the precision-95 and next-build programmes: the wave map exists so dependencies are decided before dispatch). Primary input: the adjudicated system review `docs/eval-reports/2026-11-10-system-review.md` and its six lane reports. **This document plans; it does not implement.** Every number is cited to its source report. Where something is unknown or not commissioned, it says so. It defines 51 tickets (plus the already-done work in section 7). The issue bodies, one file per ticket, are in `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/` with `INDEX.md`; nothing has been posted to GitHub.

---

## 0. Context

On 2026-11-10 the system was reviewed end to end (retrieval, parsing and chunking, evaluation, the MCP surface, harvest, operations) while the GPU was occupied by another process, so everything was read from code, stored data and logs. Along the way three new ground-truth sets, topic labels for every main-corpus paper, frozen benchmark protocols and several CPU-side tools were built. The review's finding, in plain words: the system is sound where it matters (every result is grounded in raw text and can be re-checked), but almost every question about retrieval *quality* on the new corpora is unmeasured, the measuring instruments had small defects that would have spoiled the first measurement, a few failures are silent (an unknown filter returns nothing instead of an error), and the main corpus has no recent backup. This plan turns the review's adjudicated findings into small tickets that subagents can run: fix and freeze the instruments now, measure once when the GPU is free, and make changes only where a pre-registered result says they pay.

## 1. Inputs this plan stands on

| fact | value | source |
|---|---|---|
| Main corpus topic split | 6,711 on-topic / 4,630 off-topic of 12,385 labelled papers (37.4% off); the operator keeps them | RV-1 F-1.4; `docs/eval-reports/data/2026-11-10-topic-labels/` |
| Label audit | weighted kappa 0.901; auditor is the same model family as the labeller, so it shows consistency, not correctness | `docs/eval-reports/2026-11-10-topic-labels-audit.md`; review section 2 |
| relevance_score vs labels | AUROC (on > off) 0.923; threshold 0.2745 keeps 95% of on-topic and 42% of off-topic; 0.33 keeps 86% / 18% | RV-1 F-1.4; EV-3 report |
| Score returned to callers | the fusion (RRF) score; the cross-encoder score is discarded; the earlier 'no floor' census measured rank arithmetic (per-arm means 0.0133-0.0154 = 1/(60+r)) | review item a (`rag/retriever.py:249`, `rag/reranker.py:231`) |
| CRAG evaluator | AUROC 0.9411 (gt_wmr, 70 answerable / 12 absent) and 0.8025 (ver84, 68 / 14, lower CI bound below the 0.75 bar); false abstention 20.6% on ver84 | RV-3 F-1.10 |
| Payload indexes | none on `papers`, `av_standards`, `waymo_av_safety` (8, 7, 8 segments); `full_scan_threshold` 10,000; vector store v1.18.2; recall loss inferred, not measured | review item b |
| Section-path defects | 1,678 furniture-root chunks in standards vs 150 in main; the tracker cannot create chapter levels for flat books (parser emits levels 1 and 2 only) | review item c; RV-2 F-2.1, F-2.5 |
| Re-chunk costs | full main re-chunk about 1.35M embeds and 13.8 GB of vectors vs 4.1 GB today, 91 GB free, about 700 fixture references; truncation-only fix about 177k-212k embeds, 48 GT items to re-ground | review item d; CQ-4 report |
| New ground-truth sets | standards 128 (106 answerable + 22 absent), causal books 74, papers 61; plain BM25 paper R@10 0.98 / 0.96 / 0.98, chunk@10 0.63 / 0.80 / 0.85; title-ablated paper R@10 0.87 / 0.83 / 0.82 | RV-3 F-1.3, F-1.7; review item e |
| Scorer | ignores `alternative_gold_chunk_ids` (papers 8/61, books 4/74: up to 13% under-count); gold is chunk identity | RV-3 F-1.5 |
| Run-time fixture rewrite / wrong checkout | `run_baseline.sh` re-ran `merge_gt.py` and pointed at another checkout; fixed by EV-5's run scripts (hash check, point-count guard) | review item e; EV-5 |
| Backups | newest main snapshot 2026-07-30 (manifest 11,026 papers; live 12,390); same device, 98% full, 91 GB free; no off-device copy | review item g |
| CQ-1 hazard | 0 of 1,217 stored query strings change under repair; 227 map keys, 0 in the system dictionary | review item h |
| Stub chunks | main 36,364 of 399,676; standards 2,483 of 35,714 (400 bare clause numbers) | `docs/eval-reports/2026-11-10-cq3-stub-chunks.md` |
| Shared anchors | standards: 35,714 chunks, 33,053 distinct anchors (7.5% share an anchor); main 0 | RV-1 F-1.3 |
| Ligature damage | 32.42% of main chunks (129,566); papers-set gold 35 of 61 damaged, books 27 of 69 | RV-2 F-2.9; RV-3 F-1.14 |
| GPU state | a foreign model server holds 18,609 of 24,576 MiB; the repo's own lock is free | `docs/eval-reports/2026-11-10-GPU-DAY-RUNBOOK.md` step 0 |
| Query-path lock wait | up to 300 s, no holder identity in the error | RV-1 F-1.9; review (S-06) |
| MCP usage | 1,198 logged calls; 213 scan calls with no pattern recorded; `doc_type` used 0 times; 57-58% of a standards response is envelope | RV-4 F-4.3, F-4.5, F-4.6 |
| Contamination | cohort published from 2026-06: n=3,440, 81.3% off-topic; ingest day 2026-07-31: 1,307 papers, 57% off | review item f |
| IDF | the on-disk config of all five live collections carries the IDF modifier (re-checked 2026-11-10 for the main, standards, Motional, Waabi and Waymo collections) | review item h / Decision 1; `.phase0-data` collection configs |
| Unpushed commits | 67 local commits at review time were never judged by CI | review F4 |

Only facts verified by the review (or re-checked on 2026-11-10, where stated) are used.

## 2. Honest framing: read before dispatching anything

1. **What is proven (by reading code and data, not by retrieval runs):** the reranker score is thrown away; no payload index exists; the section tracker causes the standards path defects; the main corpus has no recent backup; merged ligature repair changes none of 1,217 recorded queries; IDF is applied everywhere; the first GPU run, as the old scripts were written, would have rewritten its own fixture and measured another checkout (now fixed in the run scripts).
2. **What is unknown until the first GPU session (wave 2):** passage-level recall on the three new sets; whether stubs or ligature damage cost any answer; how often off-topic papers enter a top 10; whether the per-corpus depth and weight settings help; whether the cross-encoder score separates answerable from absent; whether filtered searches lose neighbours without payload indexes (that one needs only the vector store on CPU).
3. **What this programme does NOT promise:** no retrieval improvement has been measured for anything, and none is promised. No precision-0.95 or abstention claim (the P0-2 ratification is unsigned, F8). No deletion of the off-topic papers. No full re-chunk. No MCP wiring of any confidence signal (it would need at least 60 distinct real absent items). The ground-truth sets are LLM-authored, same-family verified, with questions about twice as long as real queries and title tokens carrying 11-16 points of paper recall; the authority and edition strata (n=4) are descriptive only until CQ-19/CQ-20 land.
4. **Statistical reality:** with 61-128 items per set, a net +3 items is the smallest effect any rule here can call, and many gated tickets will honestly end as REJECT, UNDERPOWERED or closed-by-gate. That counts as success: each costs a clone and a report, never a live change.
5. **Estimates:** every GPU duration and every size in this plan is an estimate (GPU-day runbook basis), not a measurement; the first run replaces them.

## 3. Operator decisions and open questions

**Already decided (constraints, not questions):**

- The roughly 37% off-topic papers STAY in the main corpus. The goal is to measure and improve whether retrieval stays on focus, never to delete them.
- No GPU for now. Everything in waves 1 is written and unit-tested without it; the first GPU session is wave 2 and is entered only after the operator answers F3.
- Protected paths (`contracts/`, `rag/config.py`, `config.example.yaml`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`) change only through the single sign-off rider, RIDER-1. No other ticket may touch them; a ticket that finds it needs to stops and reports.
- Tickets live in markdown and will be mirrored as GitHub issues only after the operator confirms the list (`INDEX.md` in the issues directory). Nothing has been posted.
- Subagents do the work. Each ticket names a model tier: Haiku for mechanical work, Sonnet for logic and authoring, Opus only for hard design adjudication with a one-line justification. No ticket in this set needs Opus; if a verdict is contested at review time, adjudication by Opus is justified by 'independent re-derivation of a pre-registered rule' and is the operator's call.

**Open questions (review group F), each with what it blocks:**

| # | question | blocks |
|---|---|---|
| F1 | Backups: is there any device or remote for an off-disk copy (the only other disk is the photo project's read-only source)? After a fresh verified snapshot, may the five July `.bak` files (6.4 GB), the 07-28 `.partial`, and two of the three July snapshots be deleted? | OP-4 (off-device copy and deletions only; the snapshot itself is not blocked), EP-7 (restore section's target) |
| F2 | May the vector store (CPU container only) be started for clone measurements? Each clone needs about 6-8 GB of the 91 GB free. | EV-14, CQ-7, CQ-9, CQ-10, CQ-15, CQ-18 |
| F3 | Who owns the wedged foreign model process holding 18.6 GB of VRAM, and may it be stopped? It is what blocks the GPU. | Every wave-2 ticket (EV-16 to EV-22) and every GPU ticket in wave 3 (RQ-3, CQ-10, CQ-11, CQ-15, CQ-16, CQ-18) |
| F4 | Push the local commits (67 at review time) so CI judges them: yes or no? | RIDER-1 (a CI verdict on the rider); every 'CI passes' claim in this plan is local until then |
| F5 | May the MCP wire be a projection of the frozen envelope (drop `bbox` and the duplicated `snippet`/`paper_id`)? | MC-4 |
| F6 | Focus lever: is 'demote, never drop, opt-in' the only acceptable form? What off-topic share in the top 10 counts as material? | RQ-3 (starts only above the bar), EV-17 (reports the number, does not set the bar), RIDER-1 item 1 |
| F7 | If the standards structure gate passes, may stored `Block.section_path` be rewritten for standards (and a 35k re-embed run), or must the corrected path live in a derived column? | CQ-15 (default is the derived column until answered), CQ-16, RIDER-1 conditional item 7 |
| F8 | P0-2 metric ratification: sign it, or retire it in favour of the EV-5 protocols and EV-7/EV-8 addenda? | Any headline quoted from wave-2 reports (they cite the EV-5 protocols, never P0-2, until answered); EP-4 records the answer |

Programme-embedded decisions that are NOT blocking questions (the operator decides them in PR review of the named ticket): the 20 s query-path lock timeout (OP-5), the Qdrant version pin (OP-7), the amended CQ-3 ADOPT rule (EV-12), the standards protocol addendum (EV-11), whether unsupported per-corpus defaults are reset to 32/0.5 as the review says or stay as frozen rule G-1 says (EV-20), the bare-clause-number folding rule (CQ-14), and applying any adopted index change to a live collection (follow-on tickets, written only on ADOPT).

## 4. Execution model and global constraints

One orchestrator plus dispatched subagents plus detached measurement processes (`docs/AGENT-OPERATIONS-LESSONS.md`). The orchestrator writes briefs from the ticket entries below, dispatches, verifies artifacts against git, merges lanes into the integration branch and owns integration. It never implements a ticket. Tier rule: Haiku for mechanical work (EP-3, EP-4, EP-5, OP-4), Sonnet for logic and authoring (everything else), Opus only for hard design adjudication with a one-line justification (none needed so far).

### Global constraints: encode into EVERY brief, verbatim-adapted

1. **Assume every dispatch dies.** Each ticket is a numbered commit list; commit ① is a stub committed before any real work (docstring stating the intended behaviour; for experiments, the pre-registered criterion). Commit after every green step. A dead dispatch must be resumable from committed state (LESSONS sections 3.3d, 4.5b).
2. **One ticket, one worktree, one live dispatch.** Branch `EP-<ID without hyphen>-<slug>` from the integration branch `EP-programme-20261110`; never edit the main checkout, another ticket's worktree or any default branch. Two items per brief at most; do item 1, commit, then item 2; do not read ahead (LESSONS 3.1b).
3. **File ownership partitions concurrency.** Each ticket lists `Owns`; two tickets that can run in parallel never share a file. Where a file is wanted by several tickets they are sequenced (section 6); hold a ticket rather than run it into a conflict (LESSONS 4.1).
4. **No attribution of any kind** in commits, PRs or issue text (no co-author trailers, no 'generated with' lines). Every brief that will lead to a commit says this explicitly. Single configured author.
5. **Never push to the default branch, never merge, never run `gh` in tickets before the operator confirms the issue list.** The operator merges.
6. **Protected paths** (`contracts/`, `rag/config.py`, `config.example.yaml`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`) change only in RIDER-1. A ticket that finds it needs one stops and reports what it would change and why (LESSONS 6.3).
7. **Explicit `--collection` on every index-touching command** (and `--db-path`, `--blob-dir` for evals). Omitting it silently queries the main collection.
8. **Clone first** for anything that writes an index: clone with `VectorIndex.clone_points_into`, apply only with the `--target-is-clone` guard, dry run before apply, delete the clone afterwards, abort if under 20 GB free. Corpus databases are opened read-only (`mode=ro`) except by the existing ingest tooling.
9. **Fixtures are never rewritten at run time and are checked by hash.** Every run script verifies the SHA-256 in `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`; a changed hash needs a dated addendum first. A report whose hash differs is discarded.
10. **Both fixtures / all sets are reported, never averaged.** One variable per run; a change is believed only if the held-out set does not move against it; the five-part qualifier `{metric, fixture, arm, pool depth, config}` accompanies every number.
11. **Ceiling-check before freezing any metric or rule** (LESSONS 7.2): the achievability bound (for example, that +3 is reachable on n items) is computed and written into commit ① before any run.
12. **Local CI gate before every push:** the full zero-GPU pytest and `ci.run_enforcement` (the synthesized push event, or `--local <base>`), read to their verdict line. A passing local suite says nothing about the gate (LESSONS 1.1-1.2). Until F4 is answered, no CI verdict exists for any of this work.
13. **Docs batching exception (declared, to be confirmed by the operator).** AGENT-PROCEDURES section B requires ledger entries in the same PR. Because PROJECT-STATUS.md and BACKLOG.md are the two most conflict-prone files, tickets here ship their own report or design note and name the section B triggers in 'Docs to update'; EP-3, EP-4 and EP-5 pay the ledger, entry-point and doc-map rows from the merged SHAs, once per wave. Doc supersession banners are still done in the superseding PR.
14. **Measurement runs are detached processes** (`setsid`, LESSONS 7.3, 8.1), one GPU job at a time, cheapest first (LESSONS 9.1); liveness is a `/proc` scan, never `$!`; a stuck holder is found with `fuser` on the lock and killed by exact pid after checking its working directory; never `pkill -f`. Confirm artifacts through git, not by listing someone else's tree.
15. **Brief hygiene** (LESSONS section 5): each brief states the rejected alternative and why, invites disagreement ('if you think this is wrong, say why and do not change it'), names the reuse target or demands the search that justifies new code, prefers one fix at a shared choke point, and gives the failure mode, not just the requirement. Baselines ('N passed') are re-read from the ticket's own merge base at dispatch time.

## 5. Ticket ID scheme

`EP-n` programme and housekeeping; `EV-n` evaluation instruments and measurements; `CQ-n` corpus and index quality; `RQ-n` retrieval quality and focus; `MC-n` MCP surface; `OP-n` operations; `RIDER-1` the single sign-off batch. Numbering continues after the IDs used on 2026-11-10 (EP-0..EP-2, EV-1..EV-6, CQ-1..CQ-6, OP-1); OP-2 is the lazy vector-index construction reserved by OP-1's notes. The review's `S-nn` id is kept in each ticket as 'Review cross-reference'. Waves: W1 do now without GPU (some tickets need the vector store on CPU), W2 first GPU session, W3 gated changes, W4 rider and what it unblocks. Branches: `EP-<ID without hyphen>-<slug>`, e.g. `EP-OP2-lazy-vector-index-construction`. Labels on issues come from a closed set (`wave:*`, `area:*`, `needs-gpu`, `needs-signoff`, `needs-services`, `size:S|M`). Sizes: S up to 2 h of agent work, M up to 1 day; nothing is larger (anything that was larger was split, section 11).

## 6. Wave map

```
W0  done / in progress (section 7)   EP-0 EV-1..3 EV-5 EV-6 CQ-1..6 OP-1 EP-1 RV-1..6 RV-S | EV-4 in progress

W1  no GPU                                                      (operator answers: F1, F2)
 docs   EP-6 --> EP-7 ------------------------------------------------------------------+
 ops    OP-4 (snapshot, first)      OP-3 -> OP-6 -> OP-5 -> OP-2 (needs MC-3)   OP-7 ---+
 mcp    MC-1 -> MC-2 -> MC-3 ------------------------------^                            |
 retr   RQ-1 -> RQ-5 -> EV-14*      RQ-1 -> RQ-2 (needs EV-10)                           |
 eval   EV-7 -> EV-8 -> EV-9 -> EV-10 -> RQ-2 ;  EV-8 -> EV-11(EV-4) -> EV-12 ;          |
        RQ-1 -> EV-13 ;  EV-15 ;  EV-11 -> CQ-19 -> CQ-20                                |
 corpus CQ-7* (clone, CPU)   CQ-8                                                         |
        (* = needs vector store up, F2; EV-14 and CQ-7 also need OP-4)                    v
                                                                         EP-3 (W1 ledger batch)
W2  first GPU session, measurements only, one job at a time, cheapest first (F3)
 EV-16 --> EV-18 --> EV-19 --> EV-20 --> EV-21 --> EV-22        EV-17 (focus; after EV-4's hash, off-chain)
 EP-4 (W2 ledger batch) after all of them

W3  gated changes (each starts only if its gate holds)
 EV-17,EV-16,RQ-2,F6 -> RQ-3 -> CQ-10 -> CQ-11 -> CQ-15 -> CQ-16 -> CQ-18
 EV-14 -> CQ-9 -> CQ-17 (needs EV-22) -> CQ-18            EV-18 gate -> CQ-12 -> CQ-13 -> CQ-15 ; EV-18 -> CQ-14 -> CQ-15
 MC-3 + F5 -> MC-4

W4  RIDER-1 (only adopted items) -> RQ-4 (needs EV-19 gate) ; EP-5 (final ledger batch)
```

Dependency edges, exhaustive (`A -> B` = B needs A; operator answers and in-progress inputs follow). GPU-serial edges only order jobs on the single card; they carry no data.

**W1 do now, no GPU** (edges whose target is in this wave):

- OP-3 -> EP-7; OP-4 -> EP-7; OP-5 -> EP-7; OP-7 -> EP-7; EP-6 -> EP-7; EP-6 -> EP-3; EP-7 -> EP-3; OP-2 -> EP-3; OP-3 -> EP-3; OP-4 -> EP-3; OP-5 -> EP-3; OP-6 -> EP-3; OP-7 -> EP-3; MC-1 -> EP-3; MC-2 -> EP-3; MC-3 -> EP-3; RQ-1 -> EP-3; RQ-2 -> EP-3; RQ-5 -> EP-3; EV-7 -> EP-3; EV-8 -> EP-3; EV-9 -> EP-3; EV-10 -> EP-3; EV-11 -> EP-3; EV-12 -> EP-3; EV-13 -> EP-3; EV-14 -> EP-3; EV-15 -> EP-3; CQ-7 -> EP-3; CQ-8 -> EP-3; CQ-19 -> EP-3; CQ-20 -> EP-3; OP-3 -> OP-6; OP-6 -> OP-5; OP-5 -> OP-2; OP-6 -> OP-2; MC-3 -> OP-2; MC-1 -> MC-2; MC-2 -> MC-3; RQ-1 -> RQ-5; RQ-1 -> RQ-2; EV-10 -> RQ-2; EV-7 -> EV-8; EV-8 -> EV-9; EV-9 -> EV-10; EV-8 -> EV-11; EV-9 -> EV-12; EV-11 -> EV-12; RQ-1 -> EV-13; RQ-5 -> EV-14; OP-4 -> EV-14; OP-4 -> CQ-7; EV-11 -> CQ-19; CQ-19 -> CQ-20

**W2 first GPU session, measurements only** (edges whose target is in this wave):

- EV-7 -> EV-16; EV-8 -> EV-16; EV-10 -> EV-16; EV-11 -> EV-16; EV-15 -> EV-16; RQ-1 -> EV-16; OP-5 -> EV-16; EV-16 -> EV-17; EV-16 -> EV-18; EV-11 -> EV-18; EV-15 -> EV-18; EV-13 -> EV-19; EV-16 -> EV-19; EV-18 -> EV-19; EV-16 -> EV-20; EV-18 -> EV-20; EV-19 -> EV-20 (GPU-serial order); EV-12 -> EV-21; EV-9 -> EV-21; EV-16 -> EV-21; EV-18 -> EV-21; EV-20 -> EV-21 (GPU-serial order); CQ-7 -> EV-22; EV-16 -> EV-22; EV-18 -> EV-22; EV-21 -> EV-22; EP-3 -> EP-4; EV-16 -> EP-4; EV-17 -> EP-4; EV-18 -> EP-4; EV-19 -> EP-4; EV-20 -> EP-4; EV-21 -> EP-4; EV-22 -> EP-4

**W3 gated changes after baselines** (edges whose target is in this wave):

- RQ-2 -> RQ-3; EV-16 -> RQ-3; EV-17 -> RQ-3; EV-22 -> RQ-3; EV-14 -> CQ-9; RQ-5 -> CQ-9; RQ-1 -> CQ-9; EV-16 -> CQ-10; RQ-3 -> CQ-10 (GPU-serial order); CQ-10 -> CQ-11; EV-18 -> CQ-12; CQ-12 -> CQ-13; EV-18 -> CQ-13; EV-18 -> CQ-14; CQ-12 -> CQ-15; CQ-13 -> CQ-15; CQ-14 -> CQ-15; CQ-8 -> CQ-15; CQ-11 -> CQ-15; CQ-15 -> CQ-16; EV-18 -> CQ-16; EV-22 -> CQ-17; CQ-9 -> CQ-17; RQ-5 -> CQ-17; CQ-17 -> CQ-18; EV-22 -> CQ-18; EV-16 -> CQ-18; EV-18 -> CQ-18; CQ-16 -> CQ-18 (GPU-serial order); MC-3 -> MC-4

**W4 rider and what it unblocks** (edges whose target is in this wave):

- EV-11 -> RIDER-1; EV-18 -> RIDER-1; EV-19 -> RIDER-1; EV-20 -> RIDER-1; EV-21 -> RIDER-1; RQ-3 -> RIDER-1; RQ-5 -> RIDER-1; OP-5 -> RIDER-1; CQ-18 -> RIDER-1; RIDER-1 -> RQ-4; EV-19 -> RQ-4; RQ-1 -> RQ-4; EP-4 -> EP-5; RQ-3 -> EP-5; CQ-9 -> EP-5; CQ-11 -> EP-5; CQ-16 -> EP-5; CQ-17 -> EP-5; CQ-18 -> EP-5; MC-4 -> EP-5; RIDER-1 -> EP-5; RQ-4 -> EP-5

**External inputs and operator answers:** OP-4 <- F1; EV-11 <- EV-4; EV-14 <- F2; CQ-7 <- F2; EV-16 <- F3; EV-17 <- EV-4, F3; EV-18 <- F3; EV-19 <- F3; EV-20 <- F3; EV-21 <- F3; EV-22 <- F3; RQ-3 <- F3, F6; CQ-9 <- F2; CQ-10 <- F3; CQ-15 <- F2, F3, F7; CQ-16 <- F3; CQ-18 <- F2, F3; MC-4 <- F5; RIDER-1 <- F4, F7.

Notes: EP-3, EP-4, EP-5 depend on every ticket of their wave (they batch ledger rows); the W2 chain is also the order of the GPU-day runbook steps 1c, 2, 3, 4, 5, with EV-16 as step 1a and EV-17 as step 1b run in the slot after EV-16 when its fixture hash is frozen, otherwise skipped. W3 gated tickets begin only when the named gate holds; if it does not, the ticket is closed by its gate with the report that shows it.

## 7. Already done, or in progress on other branches (W0)

Not re-ticketed. SHAs are on the integration branch `EP-programme-20261110`.

| ticket | what | status | where |
|---|---|---|---|
| EP-0 | Programme branch; three ground-truth sets (standards 128 items, causal books 74, paper passages 61); chunk-quality census; corpus audits (off-topic, ligature, embed truncation) | DONE `0021de1` | commits `173fe4e` (standards GT), `f119f30` (books GT), `0c9483e` (papers GT), `09cb847` (audits), `368ce55` (census), `17b48ec`, `0021de1` |
| EV-1 | Topic labels for all 12,385 main-corpus papers | DONE `5f54fb4` | `docs/eval-reports/data/2026-11-10-topic-labels/` |
| EV-2 | Label audit (weighted kappa 0.90, same model family as the labeller) | DONE `eb4d993` | `docs/eval-reports/2026-11-10-topic-labels-audit.md` |
| EV-3 | relevance_score against labels (AUROC 0.923) | DONE `eb4d993` | same merge as EV-2; report above |
| EV-5 | Three frozen protocols, run scripts that verify fixture hashes, fixture hashes, GPU-day runbook | DONE `b9be4c8` | `docs/eval-reports/2026-11-10-*-benchmark-protocol.md`, `2026-11-10-GPU-DAY-RUNBOOK.md`, `data/2026-11-10-FIXTURE-HASHES.json` |
| EV-6 | Per-stratum evaluation report script | DONE `c06b411` | `scripts/eval_strata_report.py` |
| CQ-1 | Ligature repair in the sparse arm (merged, applied to no index) | DONE `56d24d0` | `docs/eval-reports/data/2026-11-10-ligature-census/repair-map-report.md` |
| CQ-2 | `VectorIndex.resparse` / `set_payload` and their CLIs | DONE `655b384` | `docs/eval-reports/2026-11-10-cq2-index-maintenance.md` |
| CQ-3 | Stub filter (default off) and pre-registered A/B | DONE `720f77d` | `docs/eval-reports/2026-11-10-cq3-stub-chunks.md` |
| CQ-6 | Duplicate-document and reference-list census | DONE `23fc2d2` | `docs/eval-reports/data/2026-11-10-dup-ref-census/` |
| CQ-4 | Truncation re-chunk plan: about 177k-212k embeddings, 48 ground-truth items to re-ground; names a server token-limit change as the unassessed alternative | DONE `bb6520a` | `docs/eval-reports/data/2026-11-10-truncation-rechunk/report.md` |
| CQ-5 | Standards metadata: reviewed table, validator/tag emitter, acquisitions list; specifies the authority/edition follow-up authoring (CQ-19, CQ-20) | DONE `3df5c8b` | `docs/eval-reports/2026-11-10-cq5-standards-metadata.md` |
| EP-1 | Documentation drift pass over PROJECT-STATUS, README, AGENTS, RUNBOOK | DONE `dc70a73` | commits `2f25a68`..`dc70a73` on the integration branch |
| OP-1 | `doctor --cpu-only` and fail-fast degraded mode | DONE `564582a` | `app/doctor.py` |
| RV-1..RV-6 | Six review lanes | DONE `b4c2b43`, `e796cc9` | `docs/eval-reports/data/2026-11-10-system-review/` |
| RV-S | Adjudicated system review (the primary input of this plan) | DONE `364aa13` | `docs/eval-reports/2026-11-10-system-review.md` |
| EV-4 | Topic-focus ground truth (40 of about 50 items authored) | IN PROGRESS | branch `EP-EV4-focus-gt`; its content is not described here |
| EP-2 | This plan, the issue files and the BACKLOG section | READY | branch `EP-EP2-ticket-set` |

## 8. The tickets

Every entry has the same fields; the standard gate (full zero-GPU pytest, enforcement, ruff on owned files) is spelled out in each. The same text is the issue body in the issues directory.

### W1 do now, no GPU

#### CQ-7: Build a ligature-repaired clone of the main collection on CPU

Labels: wave:1-no-gpu, area:corpus, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-7-ligature-resparse-clone-cpu.md`.

**Review cross-reference:** S-17. **Wave:** W1 do now, no GPU.

**Why.** CQ-1 repairs ligature damage in the sparse arm but is deliberately not applied to any index, and CQ-2 added `app.resparse` to recompute sparse vectors without re-embedding. The A/B (EV-22) needs a repaired clone to exist, and the whole preparation is CPU-only, so it can run while the GPU is held by another process (GPU-day runbook step 5.1). About 35% of main-corpus chunks change; resparse time is unmeasured.

**Scope.**
- In:
  - Clone the main collection with `VectorIndex.clone_points_into` into a new scratch collection, then `app.resparse --collection <scratch> --target-is-clone --clone-of <live> --apply` after a dry run, following `docs/eval-reports/2026-11-10-cq2-index-maintenance.md`. Record measured resparse time and the sparse-staleness sample before and after.
- Out (explicitly):
  - Touching the live collection (read-only source only). The A/B (EV-22). Any BM25 weighting (CQ-17). Deleting the clone: EV-22 does that when done.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<run-date>-ligature-clone/`

**Commits** (① is a stub, committed before any real work):
① stub: record skeleton with the dry-run and apply checklists and the abort rule (under 20 GB free)
② dry run output saved
③ apply on the clone; times and counts recorded; staleness sample before/after
④ handover note for EV-22 (collection name, git revision of the resparse code)

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `df -h /` before the clone
- `conda run -n agent-rag-research python -m app.resparse --help` shows `--collection` required and `--target-is-clone`
- Post-apply sparse-staleness sample reports the stale share near zero on the clone and unchanged on the live collection

**Acceptance / falsification criterion.** Scratch collection holds the same point count as the live one; resparse applied only to the scratch collection; staleness sample on the scratch shows the repaired vectors, on the live shows unchanged. Falsified if the live collection's point count or sampled sparse vectors changed at all.

**Gates / depends on.** Depends on: OP-4. Operator answers: F2. Gates: EP-3, EV-22.

**Needs.** GPU: n · services up: vector store (CPU container) up; no GPU services · operator sign-off: n (no protected path is touched); operator answers: F2 · re-embed: n. Also: vector store start approved (F2); 6-8 GB free for the clone.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Applying resparse to the live collection by mistake (the documented CQ-1 deployment hazard). Mitigation: `--target-is-clone` guard, explicit `--collection` on every command, live collection read-only. Rollback: delete the scratch collection.

**Docs to update in the same PR.** CQ-2 operating note is the reference; record is the doc; PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### CQ-8: Make rechunk re-embed only chunks whose text changed

Labels: wave:1-no-gpu, area:corpus, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-8-rechunk-reuse-vectors-by-text-hash.md`.

**Review cross-reference:** S-14. **Wave:** W1 do now, no GPU.

**Why.** `app/rechunk.py:189` re-embeds every chunk of a re-chunked paper, including unchanged text, which multiplies the cost of every re-chunk the later tickets want (RV-2 F-2.3 step 1; review S-14). Chunk ids are positional, so reuse must key on a text hash, not on the id.

**Scope.**
- In:
  - Look up stored vectors for identical chunk text (hash of the embedded text) in the same collection, reuse them, and embed only new text. Guard: reuse only from the same collection and embedder model name.
- Out (explicitly):
  - Content-addressed chunk ids (explicitly rejected: 'Will not do' table). Changing the chunker. Applying to any live index.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/rechunk.py`
- `app/test_rechunk.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the reuse rule and its guards
② failing test: a text-only change to one chunk of a 10-chunk paper re-embeds exactly one chunk (fake embedder call count)
③ implementation to green
④ dry-run report line 'reused N, embedded M'

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/rechunk.py app/test_rechunk.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_rechunk.py -o addopts="--disable-socket"`
- Mutation proof: disable the reuse path and the call-count test fails

**Acceptance / falsification criterion.** Dry run on a fixture of 10 papers with a text-only change: re-embedded count equals changed-text count and reused count equals the rest; a changed embedder model name disables reuse. Falsified if the call-count test passes with reuse disabled.

**Gates / depends on.** Depends on: none. Gates: EP-3, CQ-15.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A wrongly reused vector silently pairs old text with a new position. Mitigation: vectors depend only on the embedded text (which includes title and section path prefix), guarded by model name. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### CQ-19: Author 38 more standards authority-stratum ground-truth items

Labels: wave:1-no-gpu, area:eval, area:corpus, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-19-standards-authority-items.md`.

**Review cross-reference:** CQ-5 follow-up. **Wave:** W1 do now, no GPU.

**Why.** The authority stratum has 4 items (Q-STD-C-019..022), so any filter or tag effect is description only: with n=4 the best possible exact McNemar p is 0.125 and can never reach 0.05. CQ-5's pre-registered measurement (`docs/eval-reports/2026-11-10-cq5-standards-metadata.md` section 5) computes 42 items per stratum for a 30-point difference at alpha 0.05, power 80%, planning disagreement 0.5, so 38 more are needed.

**Scope.**
- In:
  - Author 38 new authority-stratum items from many different documents (the current four rest on four), phrased as a user would without hinting the tag, under the existing blind two-author plus cross-verification regime and `gt_tools.py verify`; recorded as a separate extension file with its own hash entry, dated addendum first.
  - If frozen before EV-18 launches, EV-18 may run them as a descriptive stratum; otherwise they wait for a later run.
- Out (explicitly):
  - Running retrieval on them. Any change to the 128 existing items. The tag filters (CQ-5, done).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<date>-standards-gt-authority-extension/`
- `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`

**Commits** (① is a stub, committed before any real work):
① stub: addendum and authoring protocol copy (strata definition, no-hint rule, hash procedure), before any item is written
② author A and author B draft files, blind to each other
③ cross-verification report with kills and fixes counted
④ adjudicated extension file, `verify` transcript and hash entry

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research python docs/eval-reports/data/2026-11-10-standards-gt/gt_tools.py verify <extension file>` passes (read-only against the standards database)
- Count of distinct source documents printed (target: at least 20)

**Acceptance / falsification criterion.** 38 items pass verbatim-excerpt verification, 0 reuse a 6-word run of the excerpt, come from at least 20 distinct documents, are cross-verified by a reader other than the authors, and their SHA-256 is in the hash file before any run reads them. Falsified if any item fails `verify` or an excerpt is not verbatim in the stored chunk.

**Gates / depends on.** Depends on: EV-11. Gates: EP-3, CQ-20.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Same-model-family authors and verifiers (0 kills on standards so far): residual defects are possible; the stratum stays labelled LLM-authored. Rollback: drop the extension file and its hash entry.

**Docs to update in the same PR.** Addendum and extension file are the docs; PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### CQ-20: Author 38 more standards edition-stratum ground-truth items

Labels: wave:1-no-gpu, area:eval, area:corpus, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-20-standards-edition-items.md`.

**Review cross-reference:** CQ-5 follow-up. **Wave:** W1 do now, no GPU.

**Why.** The edition stratum also has 4 items (Q-STD-A-021/022, B-021/022); same arithmetic as CQ-19: 42 per stratum needed, 38 to add (`docs/eval-reports/2026-11-10-cq5-standards-metadata.md` section 5). Edition questions are where BM25 scores 0.00 chunk@10 on n=4 (RV-3), so the stratum is the one that would show whether the standards metadata tags help.

**Scope.**
- In:
  - Author 38 edition-stratum items (some naming an edition, some not, from many documents with superseded and current editions), same regime and extension-file procedure as CQ-19.
- Out (explicitly):
  - Running retrieval. Changing existing items. Using `status:current` as a filter in the design (excluded by CQ-5 because the gold documents may be superseded).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<date>-standards-gt-edition-extension/`
- `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`

**Commits** (① is a stub, committed before any real work):
① stub: addendum with the stratum definition and the named/unnamed edition quota
② author A and author B draft files
③ cross-verification report
④ adjudicated extension file, `verify` transcript and hash entry

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research python docs/eval-reports/data/2026-11-10-standards-gt/gt_tools.py verify <extension file>` passes
- Count of distinct source documents printed (target: at least 20)

**Acceptance / falsification criterion.** Same as CQ-19: 38 verified, cross-verified, hashed items from at least 20 documents, hash recorded before any run reads them. Falsified if any item fails `verify`.

**Gates / depends on.** Depends on: CQ-19. Gates: EP-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** As CQ-19; the hash file is shared with CQ-19, hence the sequencing. Rollback: drop the extension file and hash entry.

**Docs to update in the same PR.** PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EP-3: Batch BACKLOG and PROJECT-STATUS updates for wave 1

Labels: wave:1-no-gpu, area:docs, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EP-3-status-batch-wave-1.md`.

**Review cross-reference:** S-13. **Wave:** W1 do now, no GPU.

**Why.** The common brief for this programme forbids parallel tickets from editing `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` (they are the two most conflict-prone files), so AGENT-PROCEDURES section B's ledger obligations are paid here, once per wave, from each ticket's 'Docs to update' list. The BACKLOG drift rows of RV-6 B.1 (SB-1, SB-3, P0-2/T-F7, FD-1, B-4, B-5) were corrected by EP-2 itself.

**Scope.**
- In:
  - For every wave-1 ticket merged: flip its row in the 'Enhancement programme (2026-11-10)' BACKLOG section to `DONE -- <sha>`; add one PROJECT-STATUS section 3 ledger entry; add section 2 entry-point rows and section 7 doc-map rows exactly where the ticket's docs line says a trigger fired.
  - Any further BACKLOG drift row found while flipping rows, each with its git evidence.
  - Record operator answers received so far (F1-F8) in PROJECT-STATUS section 6 as open or closed.
- Out (explicitly):
  - Any claim about retrieval quality (none exists until wave 2). Rewriting PROJECT-STATUS sections EP-1 already corrected on 2026-11-10; this ticket only appends ledger entries.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/PROJECT-STATUS.md`
- `docs/BACKLOG.md`

**Commits** (① is a stub, committed before any real work):
① stub: checklist of the wave-1 tickets with their merge SHAs, empty status cells
② BACKLOG row flips + punch rows 1,5,6,17,18
③ PROJECT-STATUS ledger, entry-point and doc-map rows
④ open-question status lines

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `grep -c 'IN PROGRESS' docs/BACKLOG.md` no longer lists SB-1
- Each ledger SHA exists: `git cat-file -e <sha>^{commit}` for every SHA written
- `git diff --stat` touches only the two owned files

**Acceptance / falsification criterion.** Every merged wave-1 ticket has a DONE row with a SHA that resolves and a ledger entry; no row says DONE for an unmerged ticket (checked by `git branch --contains <sha>` against the integration branch). Falsified if any SHA does not resolve.

**Gates / depends on.** Depends on: EP-6, EP-7, OP-2, OP-3, OP-4, OP-5, OP-6, OP-7, MC-1, MC-2, MC-3, RQ-1, RQ-2, RQ-5, EV-7, EV-8, EV-9, EV-10, EV-11, EV-12, EV-13, EV-14, EV-15, CQ-7, CQ-8, CQ-19, CQ-20. Gates: EP-4.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Haiku; S (up to 2 h of agent work). Mechanical work, no judgement calls.

**Risk and rollback.** Low. A wrong SHA is the failure; mitigation is the `git cat-file` check. Rollback: revert.

**Docs to update in the same PR.** This ticket is the docs obligation for wave 1.

#### EP-6: Add CORPORA.md and fix drift rows outside EP-1's files

Labels: wave:1-no-gpu, area:docs, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EP-6-docs-corpora-and-drift-remainder.md`.

**Review cross-reference:** S-13. **Wave:** W1 do now, no GPU.

**Why.** Agents follow stale docs exactly (CONVENTIONS section 0.6). The review's 23-row drift punch list (RV-6 B.1) splits by file: PROJECT-STATUS, README and AGENTS belong to EP-1 (in progress); the rest has no owner. Which chunker built each corpus is written nowhere (RV-2 F-2.2), the IDF question in DECISIONS-PENDING Decision 1 is stale (the on-disk config of all five collections already carries the IDF modifier; review item 1 'Decision 1'), and the review's rule 'no ingest into a live collection from this branch' has no home.

**Scope.**
- In:
  - New `docs/CORPORA.md`: one row per corpus (five), data-dir role, collection name, document/chunk counts re-derived read-only, and which chunker built it (standards: bounded chunker; main and Waymo: legacy chunker), reusing the five-corpus registry EP-1 added to PROJECT-STATUS instead of restating it differently.
  - State the rule: no ingest into a live collection from this branch until the verdicts of EV-22 (sparse recompute) and CQ-11 (bounded re-chunk) are in, because it would mix chunkers and sparse versions (review S-13; item h residual risk 1).
  - Close Decision 1 in `docs/DECISIONS-PENDING-operator.md` with the evidence (IDF modifier present in the on-disk config of all five collections); punch-list rows 8 and 16 (that file and `docs/HANDOFF-2026-08-24.md`); tick the status of each ticket in `docs/superpowers/plans/2026-08-25-precision95-programme.md` per RV-6 B.2 (row 7).
  - HISTORICAL banner, in this PR, on any doc this PR supersedes (AGENT-PROCEDURES section B).
- Out (explicitly):
  - PROJECT-STATUS.md, README.md, AGENTS.md (EP-1). BACKLOG.md rows (EP-3). RUNBOOK.md (EP-7).
  - Any code change; any measurement that needs a service (counts are read-only SQLite).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/CORPORA.md`
- `docs/DECISIONS-PENDING-operator.md`
- `docs/HANDOFF-2026-08-24.md`
- `docs/superpowers/plans/2026-08-25-precision95-programme.md`

**Commits** (① is a stub, committed before any real work):
① stub: `docs/CORPORA.md` skeleton with the five rows and column headings, empty cells marked TODO
② corpora table filled from read-only queries; counts stamped with the query date
③ no-ingest rule + chunker provenance column
④ Decision 1 closure + HANDOFF + precision-95 plan status rows (each row cites the git evidence)

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `grep -c 'IN PROGRESS' docs/BACKLOG.md` is NOT this ticket's check (EP-3). Instead: `grep -n 'Decision 1' docs/DECISIONS-PENDING-operator.md` shows the closure with the config evidence
- Every count in CORPORA.md reproduces with the read-only query printed under the table (`sqlite3 "file:<db>?mode=ro" 'select count(*) from chunks'`)

**Acceptance / falsification criterion.** `docs/CORPORA.md` lists five corpora with path role, collection, counts and chunker; each count was re-derived on the day and the query is shown; the no-ingest rule is present; Decision 1 reads 'closed' with evidence; someone who did not write it can re-run every shown query and match. Falsified if any count differs from a fresh read-only query by more than the ingest drift stated in the doc.

**Gates / depends on.** Depends on: none. Gates: EP-7, EP-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. Docs only. A wrong count misleads an agent; mitigation is the printed query beside each number. Rollback: revert the commit.

**Docs to update in the same PR.** New doc: PROJECT-STATUS section 7 (doc map) row is carried by EP-3. Superseded-doc banners are done in this PR. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EP-7: Add backup, container and GPU-contention sections to RUNBOOK

Labels: wave:1-no-gpu, area:docs, area:ops, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EP-7-runbook-backup-containers-gpu-contention.md`.

**Review cross-reference:** S-13, S-01, S-06, S-12. **Wave:** W1 do now, no GPU.

**Why.** `docs/RUNBOOK.md` has no backup or restore section, no container definitions and no GPU-contention section (RV-6 punch row 22), yet the system has no backup newer than 2026-07-30 and a foreign process holds the GPU today (review items g, S-06). A second-corpus recipe also omits that `app.init_config` writes a private `gpu_lock_path` that must be edited to the shared lock.

**Scope.**
- In:
  - Three sections: (1) backup and restore (what `app.snapshot` writes, how to verify with `quick_check` and the manifest checksums, restore drill, retention, the off-device gap), (2) containers (point to `ops/docker-compose.yml`, the pinned Qdrant version, the rule that nothing is restarted without a snapshot), (3) GPU contention (holder file, doctor's foreign-process listing, the 20 s query-path timeout, cheapest-first ordering rule from LESSONS section 9.1).
  - Punch row 22: the shared-lock note in 'Running a second corpus'. Add a pointer to `docs/CORPORA.md` and the no-ingest rule.
- Out (explicitly):
  - Writing the code those sections describe (OP-3, OP-5, OP-7 own it). Deleting any backup (operator question F1).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/RUNBOOK.md`

**Commits** (① is a stub, committed before any real work):
① stub: three empty section headings with one-line intent each
② backup/restore section, commands copied from the merged OP-3/OP-4 output, not guessed
③ container + GPU-contention sections, commands verified against merged OP-5/OP-7
④ punch row 22 + CORPORA pointer

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command in the new sections was run (or `--help`-checked) in the worktree and the output is quoted in the PR description
- `grep -n 'gpu_lock_path' docs/RUNBOOK.md` shows the second-corpus warning

**Acceptance / falsification criterion.** A cold agent can, from RUNBOOK alone, (a) take and verify a snapshot, (b) name who holds the GPU, (c) recreate the four containers from the tracked compose file. Checked by a reviewer who did not write it following each section once on a read-only or dry-run basis. Falsified if any quoted command fails or prints different flags.

**Gates / depends on.** Depends on: OP-3, OP-4, OP-5, OP-7, EP-6. Gates: EP-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. A documented command that has since changed misleads; mitigation: commands verified at merge time. Rollback: revert.

**Docs to update in the same PR.** RUNBOOK is itself the doc; PROJECT-STATUS doc-map row carried by EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EV-7: Require --collection, stamp the fixture hash, preflight gold ids

Labels: wave:1-no-gpu, area:eval, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-7-eval-entrypoints-explicit-collection.md`.

**Review cross-reference:** S-02. **Wave:** W1 do now, no GPU.

**Why.** `--collection` still defaults to None in `app/retrieval_eval.py:780`, `app/escalation_eval.py:153` and `app/score_distribution_census.py:209`, which `build_mcp_server` turns into the main `papers` collection, so a mispointed run yields a plausible low number with `n_errors = 0` (RV-3 F-1.2). Reports stamp no hash of the ground-truth file (contrast `judge_eval`'s `rubric_sha256_12`). EV-5 already fixed the run scripts (fixture hash check, point-count guard, no fixture rewrite, run from the worktree under test); the Python entry points themselves were not touched.

**Scope.**
- In:
  - `--collection` `required=True` in the three entry points (precedent: `app/generation_capture.py`).
  - `ground_truth_sha256_12` in `build_report`, same pattern as `judge_eval`.
  - Preflight before scoring: every `gold_paper_id` of the loaded questions resolves in the document store, else exit 2 naming the unresolved ids.
- Out (explicitly):
  - The run scripts, protocols and addenda (EV-5, done). The collection point-count check (stays in the run scripts' `check-points`). Lock-timeout validity (EV-10). Excerpt metric (EV-8).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`
- `app/escalation_eval.py`
- `app/test_escalation_eval.py`
- `app/score_distribution_census.py`
- `app/test_score_distribution_census.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings stating the three behaviours (required flag, hash stamp, preflight exit 2)
② failing tests for each
③ implementation to green
④ docstring/`--help` text updated

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py app/escalation_eval.py app/test_escalation_eval.py app/score_distribution_census.py app/test_score_distribution_census.py`
- `conda run -n agent-rag-research python -m app.retrieval_eval --help` shows `--collection` as required
- Unit test: report hash equals `sha256sum` of the fixture file (first 12 hex)

**Acceptance / falsification criterion.** Running any of the three without `--collection` exits non-zero; the report's `ground_truth_sha256_12` equals the first 12 hex of `sha256sum` of the file; a fixture with an unresolvable gold paper id exits 2 naming it. Falsified if a run without `--collection` still starts.

**Gates / depends on.** Depends on: none. Gates: EP-3, EV-8, EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Existing wrapper scripts that relied on the default break loudly. Mitigation: that is the point; EV-5's run scripts already pass `--collection`. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (flag now required) via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EV-8: Add an excerpt-containment passage metric that honours alternative gold chunks

Labels: wave:1-no-gpu, area:eval, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-8-passage-excerpt-hit-metric.md`.

**Review cross-reference:** S-03. **Wave:** W1 do now, no GPU.

**Why.** `load_questions` never reads `alternative_gold_chunk_ids`, so passage hit is under-counted by up to 13% of items (papers 8 of 61, books 4 of 74) and scoring by chunk identity makes the sets incomparable across any re-chunk (RV-3 F-1.5, review S-03). Anchor-equality also credits any fragment of the gold block (5 of 119 gold anchors are shared by a sibling chunk: about 4% lenient false hits; RV-1 F-1.3).

**Scope.**
- In:
  - Additive metric `passage_excerpt_hit`: a returned `passage_text` contains the normalised gold excerpt or an alternative's excerpt (reuse `retrieval_eval._normalized`; alternatives resolved through the document store the harness already holds). Items with a null `excerpt_block_id` (excerpt spans blocks) fall back to the anchor rule and are listed separately.
  - The anchor rule stays byte-identical and the report stamps `scoring_rule` for both. State in the docstring how this relates to EV-6's member-passage metric (`scripts/eval_strata_report.py`) and the frozen protocols; if the names collide, add an addendum rather than redefining.
- Out (explicitly):
  - Editing any ground-truth file (EV-11). Chunk ids in reports (EV-9). Changing the Waymo frozen scoring rule.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring defining `passage_excerpt_hit`, its null-excerpt fallback and the ceiling arithmetic (an item can only be a hit if the excerpt is in some chunk the pool can contain)
② failing test: FakeRetriever returning an alternative chunk is a hit under the excerpt rule and a miss under the anchor rule
③ implementation to green; `scoring_rule` stamp
④ report fields and by-stratum split added

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_retrieval_eval.py -o addopts="--disable-socket"`
- Existing Waymo-fixture scoring tests unchanged and green (anchor rule untouched)

**Acceptance / falsification criterion.** A FakeRetriever test returning an alternative chunk is a hit under the excerpt rule and a miss under the anchor rule; Waymo anchor-rule results are byte-identical on the existing test fixtures. This is an instrument, not a retrieval change: its ceiling check is that on the gold chunk itself the excerpt metric equals 1 for every non-null-excerpt item. Falsified if the gold chunk fails its own excerpt check on any fixture item.

**Gates / depends on.** Depends on: EV-7. Gates: EP-3, EV-9, EV-11, EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Two metrics diverge in meaning from EV-6's member-passage metric and confuse later reports. Mitigation: the docstring reconciliation and one stamped `scoring_rule`. Rollback: revert; additive.

**Docs to update in the same PR.** PROJECT-STATUS section 2 via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EV-9: Record retrieved chunk ids in eval rows; match stubs by chunk id

Labels: wave:1-no-gpu, area:eval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-9-chunk-ids-in-eval-rows.md`.

**Review cross-reference:** S-05. **Wave:** W1 do now, no GPU.

**Why.** Report rows carry only `retrieved_block_ids` (`app/retrieval_eval.py:229,371,551`), and `scripts/list_stub_chunks.py` identifies a stub by its anchor block, which is ambiguous for the 7.5% of standards chunks that share an anchor (35,714 chunks, 33,053 distinct anchors; RV-1 F-1.3, review section 2 on CQ-3). The CQ-3 addendum (EV-12) needs per-chunk identity.

**Scope.**
- In:
  - Add `retrieved_chunk_ids` to the per-question row. `GroundedResult` has no chunk id, so recover it from (paper id, anchor block id, passage text) through the document store the harness already holds; where two chunks match, record both and mark the row ambiguous.
  - `scripts/list_stub_chunks.py --ab` matches stubs by chunk id.
- Out (explicitly):
  - Any `contracts/` change. If chunk ids cannot be recovered without one, STOP and report: that is a RIDER-1 candidate, not an edit.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`
- `scripts/list_stub_chunks.py`
- `scripts/test_list_stub_chunks.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring of the recovery rule and the ambiguity marker
② failing tests: unique recovery; duplicate-text ambiguity marked; stub-at-rank-1 share computed by chunk id equals anchor-based share where anchors are unique, and differs on a shared-anchor fixture
③ implementation to green
④ list_stub_chunks wired

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py scripts/list_stub_chunks.py scripts/test_list_stub_chunks.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_retrieval_eval.py scripts/test_list_stub_chunks.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** On a fixture with two chunks sharing one anchor, the stub-at-rank-1 share is computed per chunk and the anchor-based figure is shown to differ; ambiguous rows are counted, not hidden. Falsified if recovery silently picks one of two matching chunks.

**Gates / depends on.** Depends on: EV-8. Gates: EP-3, EV-10, EV-12, EV-21.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Recovery by text may be slow on 30,000-chunk papers. Mitigation: per-paper lookup, cached. Rollback: revert; additive field.

**Docs to update in the same PR.** PROJECT-STATUS section 2 via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EV-10: Mark an eval run invalid when any error is a GPU lock timeout

Labels: wave:1-no-gpu, area:eval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-10-invalid-run-on-lock-timeout.md`.

**Review cross-reference:** S-06. **Wave:** W1 do now, no GPU.

**Why.** Lock-timeout errors are scored as ordinary misses by `app/retrieval_eval.py`'s per-hit resilience: in SB-1 two eval jobs sat more than 20 minutes behind a long GPU job and some questions timed out and were counted as misses (RV-6 F-A8, `docs/eval-reports/2026-08-28-sb1-chunk-boundary.md`). Wave 2 is exactly the concurrent-GPU scenario.

**Scope.**
- In:
  - Count questions whose error is a lock timeout; if any, write `run_valid: false` and the count in the report header and exit non-zero instead of scoring them as misses.
- Out (explicitly):
  - The lock holder identity (OP-5). Retrying timed-out questions.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the invalid-run rule
② failing test: a stubbed lock-timeout error yields `run_valid: false` and a non-zero exit
③ implementation to green
④ report header field documented

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_retrieval_eval.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** A stubbed lock timeout on one question makes the whole report invalid and the process exit non-zero; a run with no timeouts is unchanged. Falsified if the timeout question is still counted as a miss.

**Gates / depends on.** Depends on: EV-9. Gates: EP-3, RQ-2, EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A transient timeout on one question invalidates a long run. Mitigation: intended (a partially starved run is not a baseline); the run is repeatable. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EV-11: Record note-only duplicates as alternatives and re-freeze fixture hashes

Labels: wave:1-no-gpu, area:eval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-11-record-alternatives-refreeze-hashes.md`.

**Review cross-reference:** S-03. **Wave:** W1 do now, no GPU.

**Why.** Cross-verification found three same-document duplicates recorded only as 'survive' notes (Q-STD-D-014, D-027, D-028) that are not in `alternative_gold_chunk_ids`, so a correct answer from the duplicate scores a miss (RV-3 F-1.5, review S-03). Fixing it changes a frozen fixture, so it must happen before any run and under a dated addendum, because the frozen protocols record each fixture's SHA-256.

**Scope.**
- In:
  - Dated addendum to the standards protocol first (commit 1), then record the duplicates as alternatives in the standards ground-truth file, make `merge_gt` tolerate per-item orphans (report them, write the rest, fail only above a stated percentage), and update the standards, books and papers entries in `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`.
- Out (explicitly):
  - Rewriting any question or gold excerpt. Collapsing the three `gt_tools.py` copies. The focus-set hash entry (EV-4). Promotion into `fixtures/eval/` (RIDER-1).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/2026-11-10-standards-gt/`
- `docs/eval-reports/data/2026-11-10-causal-books-gt/`
- `docs/eval-reports/data/2026-11-10-papers-passage-gt/gt_tools.py`
- `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`
- `docs/eval-reports/2026-11-10-standards-benchmark-protocol.md`

**Commits** (① is a stub, committed before any real work):
① stub: addendum text (what changes, why it is pre-run, the new hash procedure) appended to the standards protocol BEFORE any fixture edit
② three duplicates recorded as alternatives; per-item orphan tolerance in `merge_gt` with tests or a dry-run transcript
③ new hashes written to FIXTURE-HASHES.json for the files that changed
④ `scripts/eval_protocol_tools.py check-hash` transcript quoted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check docs/eval-reports/data/2026-11-10-papers-passage-gt/gt_tools.py`
- `conda run -n agent-rag-research python scripts/eval_protocol_tools.py check-hash docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json <fixture-relative-path>` passes for each fixture
- `git log --format=%H -- docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json` shows the addendum commit precedes the hash change

**Acceptance / falsification criterion.** Addendum commit precedes the fixture edit; the three duplicates appear as alternatives; hashes in the file equal `sha256sum` of each fixture; no question text or excerpt changed (diff shows only alternatives and the hash file). Falsified if `git diff` shows any other change in a fixture.

**Gates / depends on.** Depends on: EV-8. In-progress tickets on other branches (merge order or inputs): EV-4. Gates: EP-3, EV-12, CQ-19, EV-16, EV-18, RIDER-1.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A hash edit after a run would void that run. Mitigation: ordered before wave 2 by dependency. The hash file is shared with in-progress EV-4 (focus entry): edits are key-disjoint and EV-4 merges first. Rollback: revert the fixture and hash commits together.

**Docs to update in the same PR.** Standards protocol addendum is the doc; PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EV-12: Amend the CQ-3 stub A/B pre-registration (fixtures, minimum effect)

Labels: wave:1-no-gpu, area:eval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-12-cq3-preregistration-addendum.md`.

**Review cross-reference:** S-05. **Wave:** W1 do now, no GPU.

**Why.** CQ-3's pre-registration names the wrong fixtures (the 210-question set and the legacy books set, which have no passage gold), has no minimum effect so one noise flip would ADOPT, and identifies stubs by anchor (ambiguous for 7.5% of standards chunks); the stub length threshold also differs across three tools (40, 60 and 80 characters; review section 2).

**Scope.**
- In:
  - Dated addendum appended to `docs/eval-reports/2026-11-10-cq3-stub-chunks.md`: fixtures are the standards, causal-books and papers-passage sets (post-EV-11 hashes); ADOPT needs net +3 items on at least one set and no stratum losing more than 1; stubs identified by chunk id (EV-9); the single binding stub definition for this A/B is the retriever's (40 characters) with the other two tools' thresholds stated as non-binding.
- Out (explicitly):
  - Changing any threshold in code (the three tools stay as they are). Running the A/B (EV-21). Editing the original pre-registration text: append only.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/2026-11-10-cq3-stub-chunks.md`

**Commits** (① is a stub, committed before any real work):
① stub: addendum heading with date and the four amendments as a list, committed before any stub A/B report exists
② addendum text with ceiling arithmetic for the new minimum effect (n of each set vs +3)
③ cross-check that every number cited resolves to a file

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `git log --diff-filter=A --format='%H %cI' -- <any stub A/B report>` shows no such file older than this addendum's commit

**Acceptance / falsification criterion.** Addendum is committed before any stub A/B report exists and states fixtures, ADOPT rule (net +3 on one set, no stratum worse by more than 1), chunk-id matching and the binding threshold; the ceiling note shows +3 is reachable on each set (n=94, 69, 61 answerable). Falsified if a stub A/B report predates the addendum.

**Gates / depends on.** Depends on: EV-9, EV-11. Gates: EP-3, EV-21.

**Needs.** GPU: n · services up: none · operator sign-off: n (not a protected path); the amended rule is a decision for the operator in PR review. · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. An addendum cannot undo a result already seen; ordering is enforced by dependency. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EV-13: Capture cross-encoder scores and build the absence census tool

Labels: wave:1-no-gpu, area:eval, area:retrieval, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-13-rerank-score-capture-and-census.md`.

**Review cross-reference:** S-04. **Wave:** W1 do now, no GPU.

**Why.** Callers get the fusion (RRF) score and the reranker's score is discarded (`rag/retriever.py:249`, `rag/reranker.py:231`), so the earlier 'no score floor' verdict tested rank arithmetic only; the cross-encoder score is the one cheap absence signal nobody has censused (review item a; RV-1 F-1.1, RV-4 F-4.1). A CRAG instrument (AUROC 0.94 and 0.80) and MiniCheck are independent of this and stay as they are.

**Scope.**
- In:
  - Experiment-only `rerank_scored()` on `TeiReranker` returning `(candidate, score)` pairs, no contract change, `rerank()` untouched.
  - `app/exp_rerank_score_census.py`: answerable top-1 reranker score versus the absent arms (standards absent 9 and partial-absent 13 reported separately; main known-absent 24; books partial-absent 5; Waymo 12 and 14), AUROC with Hanley-McNeil interval, reusing `auroc_pos_higher` from `exp_agentic_loop_v0` and `_iqr_separates` from the score census; explicit `--collection`, `--db-path`, `--blob-dir`. Definition frozen in the standards protocol section 7 (iii).
- Out (explicitly):
  - Exposing the score to callers (RQ-4, gated). Running it (EV-19, GPU). Any threshold or wiring decision (needs 60 or more distinct absent items; RV-3 F-1.10).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/reranker.py`
- `rag/test_reranker.py`
- `app/exp_rerank_score_census.py`
- `app/test_exp_rerank_score_census.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings of `rerank_scored` and the census CLI; the frozen definition cited by section number
② failing tests: scores returned are monotone in the order `rerank()` returns; census on a fake reranker computes the expected AUROC and CI
③ implementation to green
④ census CLI with required collection flags

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/reranker.py rag/test_reranker.py app/exp_rerank_score_census.py app/test_exp_rerank_score_census.py`
- `conda run -n agent-rag-research python -m pytest -q rag/test_reranker.py app/test_exp_rerank_score_census.py -o addopts="--disable-socket"`
- Reuse stated: `auroc_pos_higher`, `_iqr_separates`, Hanley-McNeil helper (no new statistics code)

**Acceptance / falsification criterion.** Unit test: `rerank_scored` scores are monotone with `rerank()` order; the census reproduces a hand-computed AUROC on a fixture of 6 items. Falsified if `rerank()` output changes by even one id on the existing reranker tests.

**Gates / depends on.** Depends on: RQ-1. Gates: EP-3, EV-19.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Adding a method to a real adapter widens its surface. Mitigation: documented experiment-only; fakes are untouched (protected). Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (new `app/` entry point) via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EV-14: Measure filtered-search overlap with exact search on a clone

Labels: wave:1-no-gpu, area:eval, area:retrieval, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-14-payload-index-overlap-measurement.md`.

**Review cross-reference:** S-15. **Wave:** W1 do now, no GPU.

**Why.** No payload index exists on any live collection (every segment's `payload_index/config.json` is `{"indexed_fields":{}}`; 8, 7 and 8 segments), yet every query is filtered. The recall loss is inferred from the vector store's documented design, not measured; the real risk band is mid-selectivity filters (`kind=summary` is 3% of points and is the whole `search_papers` path; `doc_type=book`) (review item b; RV-1 F-1.2).

**Scope.**
- In:
  - On a clone made with `VectorIndex.clone_points_into` (never the live collection): use 100 stored summary vectors as queries and compare exact search with the default HNSW search for `kind=summary`, `doc_type=book` and a single `paper_id`; report overlap@k per filter. Reuse CQ-2's read-only sampling helpers; if an exact-search method is missing from `VectorIndex`, add one small read-only method there (vendor SDK calls stay inside that adapter).
  - Pre-registered falsifier (commit 1): HNSW overlap with exact is at least 0.99 on all three filters, then payload-index work (CQ-9) is closed.
- Out (explicitly):
  - Creating payload indexes (CQ-9). Touching the live collection. Any GPU use: stored vectors are the queries, nothing is embedded.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `scripts/payload_index_overlap.py`
- `scripts/test_payload_index_overlap.py`
- `docs/eval-reports/data/<run-date>-payload-index-overlap/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the pre-registered 0.99 falsifier and the three filters, committed before the clone is made
② exact-search read-only method and the script, unit-tested against mocked clients
③ clone created; dry run on 10 queries; free space recorded
④ full run; report with the overlap table and the verdict

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py scripts/payload_index_overlap.py scripts/test_payload_index_overlap.py`
- `df -h /` before cloning (needs 6-8 GB free per clone, review F2)
- `conda run -n agent-rag-research python scripts/payload_index_overlap.py --help` shows required `--collection` and a `--target-is-clone` guard
- Report table has one row per filter with overlap@10 and the count of queries returning fewer than k

**Acceptance / falsification criterion.** Report states overlap of HNSW versus exact for each of the three filters. Verdict is mechanical: all three at least 0.99 closes the finding; any below 0.99 opens CQ-9. Falsified (finding closed) if all three are 0.99 or more. The clone is deleted afterwards and its deletion is recorded.

**Gates / depends on.** Depends on: RQ-5, OP-4. Operator answers: F2. Gates: EP-3, CQ-9.

**Needs.** GPU: n · services up: vector store (CPU container) up; no embedder, no reranker · operator sign-off: n (no protected path is touched); operator answers: F2 · re-embed: n. Also: vector store start approved (operator question F2) and 6-8 GB free for one clone.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Cloning on a 98%-full disk. Mitigation: OP-4 first, free-space check, one clone at a time, deleted after. The live collection is only read. Rollback: delete the clone.

**Docs to update in the same PR.** Report is the doc; PROJECT-STATUS section 5/6 via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### EV-15: Add the plain BM25 floor script named EV-5b in the protocols

Labels: wave:1-no-gpu, area:eval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-15-bm25-floor-script.md`.

**Review cross-reference:** S-02. **Wave:** W1 do now, no GPU.

**Why.** The frozen protocols require a BM25 'instrument floor' printed beside every run, but their own text says it is not available at first run: the lane's script was scratch (needs numpy, scipy and sklearn) and nothing is committed. They name it 'EV-5b', a follow-up script ticket (standards protocol section 7 (ii); topic-focus protocol section 7 (ii); RV-3 F-1.3 (b)). Without it every run reports a number with no floor.

**Scope.**
- In:
  - `scripts/bm25_floor.py`: plain BM25 (k1 = 1.2, b = 0.75, tokens as specified in the standards protocol) over the stored chunk text of a corpus database opened read-only, scoring a ground-truth file at paper and passage level; no new dependency (standard library only).
- Out (explicitly):
  - Any claim that BM25 predicts the system's score. Wiring it into run scripts (EV-16 runs it as a separate step). Using the system's sparse arm.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `scripts/bm25_floor.py`
- `scripts/test_bm25_floor.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the frozen definition and that the database is opened `mode=ro`
② failing tests on a 20-chunk toy corpus with known BM25 scores
③ implementation to green
④ reproduction check against the review's figures on the standards database

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check scripts/bm25_floor.py scripts/test_bm25_floor.py`
- `conda run -n agent-rag-research python scripts/bm25_floor.py --db <standards.db> --ground-truth docs/eval-reports/data/2026-11-10-standards-gt/standards_gt.json` prints paper R@10 near 0.98 and chunk@10 near 0.63 (the review's re-run values, tolerance stated)

**Acceptance / falsification criterion.** Standards floor reproduces the review's re-run within the tolerance stated in the protocol (paper R@10 0.98, chunk@10 0.63, chunk@1 0.23 on the 94 answerable items). Falsified if the script cannot reproduce those figures from the same stored text.

**Gates / depends on.** Depends on: none. Gates: EP-3, EV-16, EV-18.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A tokenisation difference makes the floor differ from the one the protocols quote. Mitigation: the reproduction check and the stated tolerance. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### MC-1: Raise an error for an unknown paper_id filter instead of returning empty

Labels: wave:1-no-gpu, area:mcp, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/MC-1-unknown-paper-id-raises.md`.

**Review cross-reference:** S-08. **Wave:** W1 do now, no GPU.

**Why.** `filters.paper_id` with an unknown or wrongly formed id returns an empty result with no error, while `get_paper` raises for the same id. In the standards usage log one call with an `arxiv:`-prefixed id (row 327) returned empty and the next with the bare stored id (row 337) succeeded (RV-4 F-4.2, confirmed by the review). An agent reads the empty result as 'this standard does not discuss X'.

**Scope.**
- In:
  - In `McpServer.semantic_search` and `search_papers`: when `filters.paper_id` is set, resolve it against the document store; on a miss raise `ContractError` with the same wording style as `get_paper` plus a hint when the id starts with `arxiv:` (the stored form has no prefix).
  - Reuse the existing `get_paper` resolution and error construction; no new lookup path.
- Out (explicitly):
  - Dropping the absolute database path from error text and other error rewording (RV-4 F-4.9, not carried by the review). Fuzzy nearest-id suggestions. Any contract change.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/mcp_server.py`
- `rag/test_mcp_server.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring lines stating the new precondition and error
② failing tests: unknown id raises; `arxiv:`-prefixed id raises with the stripped hint; known id still returns results
③ implementation to green
④ docstring updated

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/mcp_server.py rag/test_mcp_server.py`
- `conda run -n agent-rag-research python -m pytest -q rag/test_mcp_server.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Unit tests: an unknown id raises `ContractError`; the `arxiv:`-prefixed form produces the hint; a valid id is unchanged. Mutation proof: remove the resolve call and the unknown-id test fails. Falsified if the unknown-id test passes with the resolve call removed.

**Gates / depends on.** Depends on: none. Gates: EP-3, MC-2.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A valid-but-unindexed paper id now errors where it used to return empty. That is intended; it is also the same behaviour `get_paper` already has. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS ledger via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### MC-2: Make the MCP server describe its corpus, filters and limits

Labels: wave:1-no-gpu, area:mcp, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/MC-2-self-describing-mcp-server.md`.

**Review cross-reference:** S-10. **Wave:** W1 do now, no GPU.

**Why.** A cold agent sees no server instructions, zero field descriptions in the `SearchFilters` schema, and docstring guidance that FastMCP never exposes; `doc_type` was used 0 times in 1,198 logged calls, and wrong-corpus queries appear in the main log (ids 8, 21-24) (RV-4 F-4.3, F-4.4; review S-10). Hard-coded counts and a stale 32-ceiling paragraph in docstrings can disagree with the corpus.

**Scope.**
- In:
  - Pass `instructions=` to `FastMCP`, generated at startup from `corpus_stats()` (what the corpus is, counts, date range, document kinds, which filters are meaningful, a five-line tool map), under 250 tokens.
  - A compact filter legend in the `semantic_search` tool docstring (the field schema is protected). Delete hard-coded counts and the 32-ceiling paragraph.
  - `corpus_stats` gains a compact `documents` list (id, title, kind, year, status) when the corpus has 500 documents or fewer; kind and status are read from the standards metadata tags if present (CQ-5), omitted otherwise (no hard dependency).
- Out (explicitly):
  - Field descriptions on `SearchFilters` (contracts edit, RIDER-1 territory). A per-corpus card file or Config key. Federation across corpora. Response slimming (MC-4).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/serve.py`
- `app/test_serve.py`
- `rag/mcp_server.py`
- `rag/test_mcp_server.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the instructions contract (generated, under 250 tokens, no literal counts)
② failing tests: `instructions` present and under budget; every filter named in the legend; no number in any description absent from `corpus_stats`; `documents` present only at 500 documents or fewer
③ implementation to green
④ docstring cleanup commit

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/serve.py app/test_serve.py rag/mcp_server.py rag/test_mcp_server.py`
- `list_tools` and `initialize().instructions` dump built on fakes (no GPU, no store); output quoted in the PR
- `conda run -n agent-rag-research python -m pytest -q app/test_serve.py rag/test_mcp_server.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Instructions exist and stay under 250 tokens on a standards-sized and a main-sized fake; every filter appears in the legend; no description contains a literal count that disagrees with `corpus_stats`. Falsified if a description number is not derived from `corpus_stats`.

**Gates / depends on.** Depends on: MC-1. Gates: EP-3, MC-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Generated text that is wrong for a corpus misleads every cold session. Mitigation: the text is derived from `corpus_stats` only; a test pins that. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (what the server advertises) via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### MC-3: Record arguments and errors for scan and get tools in the usage log

Labels: wave:1-no-gpu, area:mcp, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/MC-3-scan-tool-telemetry.md`.

**Review cross-reference:** S-11. **Wave:** W1 do now, no GPU.

**Why.** 213 scan calls (18% of all 1,198 logged calls) have no pattern recorded, `get_section`, `get_span` and `get_paper` rows carry no arguments, errors store only the exception class name, and `source` is constant, so harness replays look like agent sessions (RV-4 F-4.5; review S-11). The usage log is the only evidence base for any future MCP work, and it is blind exactly where agents behave most like brute force.

**Scope.**
- In:
  - Bind pattern, method or section path into the existing `query` column, the argument `paper_id`, `result_count` from the result length, `str(e)[:200]` into `error`, and a `--client-label` flag (argparse, not environment) into `source`. No schema change; existing rows stay valid.
- Out (explicitly):
  - New columns (top score, returned ids: RV-6 F-A9, not carried by the review). Dashboard changes. Any retrieval change.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/usage_log.py`
- `app/test_usage_log.py`
- `app/serve.py`
- `app/test_serve.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the per-tool binding table
② failing tests per tool (scan_corpus, scan_methods, get_section, get_span, get_paper, errors)
③ implementation to green
④ `--client-label` flag + test

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/usage_log.py app/test_usage_log.py app/serve.py app/test_serve.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_usage_log.py app/test_serve.py -o addopts="--disable-socket"`
- On a scratch usage database: one mixed fake session then `select tool, query from requests where tool like 'scan%'` shows no NULL query

**Acceptance / falsification criterion.** After one scripted mixed session on fakes, no scan row has a NULL `query` and every get_* row has its `paper_id`; error rows carry the message prefix. Falsified if any tool still writes a NULL where its argument exists.

**Gates / depends on.** Depends on: MC-2. Gates: EP-3, OP-2, MC-4.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Logging full regex patterns could store sensitive text. Mitigation: the log is local and already stores queries; length is capped. Rollback: revert; rows written stay valid.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (`--client-label`) via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### OP-2: Construct the vector index lazily so the server starts without it

Labels: wave:1-no-gpu, area:ops, area:mcp, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-2-lazy-vector-index-construction.md`.

**Review cross-reference:** S-07. **Wave:** W1 do now, no GPU.

**Why.** OP-1 made a down vector store exit with an actionable message, but the server still cannot start without it: `build_mcp_server` constructs the vector index eagerly and that constructor makes a network call. `app/serve.py` carries the note 'SQLite-only tools could run without it if the vector index were constructed lazily (follow-up ticket)'. Eight of the ten MCP tools need only SQLite.

**Scope.**
- In:
  - Construct the vector index on first use (or through a lazy proxy) so `get_paper`, `get_span`, `get_section`, `scan_corpus`, `scan_methods`, `list_methods`, `get_figures` and `corpus_stats` work with the vector store down; `semantic_search` and `search_papers` raise the existing actionable transient error.
  - Call `require_existing_db()` (OP-6) in both `app/serve.py` branches (the serve part of review S-07).
  - Replace the OP-1 'follow-up ticket' comment.
- Out (explicitly):
  - Changing how TEI or the GPU lock are handled (OP-1, OP-5). Any tool signature or contract change. Health-checking the store at startup beyond what doctor does.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/assembly.py`
- `app/test_assembly.py`
- `app/serve.py`
- `app/test_serve.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating which tools work with the store down and which raise
② failing tests: factory that raises TransientError at construction -> server builds, a SQLite tool answers, a search tool raises the actionable error, `list_tools` still lists ten tools
③ implementation to green
④ serve.py: exists-check call sites and comment replaced

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/assembly.py app/test_assembly.py app/serve.py app/test_serve.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_assembly.py app/test_serve.py -o addopts="--disable-socket"`
- `list_tools` dump (no GPU) shows ten tools

**Acceptance / falsification criterion.** With the vector store construction failing, the server builds and the eight SQLite tools answer on fakes; the two search tools raise the actionable error naming `python -m app.doctor --cpu-only`; the tool list is unchanged. Falsified if any SQLite tool touches the vector index or if a search tool returns an empty result instead of raising.

**Gates / depends on.** Depends on: OP-5, OP-6, MC-3. Gates: EP-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Misconfiguration (wrong collection) surfaces on first search instead of at startup. Mitigation: doctor still checks the pairing (OP-6); the first-use error names the collection. Rollback: revert; behaviour returns to eager construction.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (serve behaviour) via EP-3; RUNBOOK mention via EP-7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### OP-3: Add integrity check and checksums to snapshot manifests

Labels: wave:1-no-gpu, area:ops, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-3-snapshot-integrity-and-checksums.md`.

**Review cross-reference:** S-01. **Wave:** W1 do now, no GPU.

**Why.** `app/snapshot.py::backup_sqlite` is correct (read-only source plus VACUUM INTO) but never runs an integrity check and the manifest records no checksum per artifact (RV-6 F-A1, F-A7; review S-01), so a corrupt snapshot looks identical to a good one until the day it is restored.

**Scope.**
- In:
  - Run `PRAGMA quick_check` on the produced SQLite copy and fail the snapshot (non-zero exit, snapshot marked incomplete) if it is not `ok`.
  - Write sha256 per artifact into the manifest; add a verify mode (or reuse an existing one) that recomputes them and compares `count(*)` with the manifest.
- Out (explicitly):
  - The guard against a nonexistent data dir (OP-6). Taking a snapshot (OP-4). Off-device copy (F1).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/snapshot.py`
- `app/test_snapshot.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the manifest fields (`quick_check`, `sha256` per artifact) and the failure rule
② failing tests: corrupt copy fails; manifest has sha256; verify detects a flipped byte
③ implementation to green
④ docstring and `--help` text brought up to date

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/snapshot.py app/test_snapshot.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_snapshot.py -o addopts="--disable-socket"`
- Mutation proof (CONVENTIONS section 14): revert the quick_check call and watch the corruption test fail

**Acceptance / falsification criterion.** A deliberately corrupted SQLite copy makes the snapshot exit non-zero and not write a complete manifest; a flipped byte in an artifact fails verify; existing snapshot tests stay green. Falsified if either test passes with the check removed.

**Gates / depends on.** Depends on: none. Gates: EP-7, EP-3, OP-6.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A verify mode changes the manifest shape: old manifests lack checksums. Mitigation: verify treats a missing checksum as 'unverifiable', not 'ok'. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 entry-point row for any new flag (via EP-3); RUNBOOK via EP-7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### OP-4: Take and verify a fresh main-corpus snapshot

Labels: wave:1-no-gpu, area:ops, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-4-take-verify-main-snapshot.md`.

**Review cross-reference:** S-01. **Wave:** W1 do now, no GPU.

**Why.** The newest main snapshot is from 2026-07-30 (manifest records 11,026 papers; the live database has 12,390) and every backup sits on the same device as the live data, which is 98% full with 91 GB free (review item g, `df -h`). The next write, re-embed or bad migration on that device has no recent restore point. This is the only finding whose downside is unrecoverable.

**Scope.**
- In:
  - Run the existing `python -m app.snapshot` for the main corpus from its data directory, once.
  - Verify the new snapshot read-only: `PRAGMA quick_check` on the snapshot copy opened with `mode=ro`, and `count(*)` of papers and chunks equal to the manifest. Record sizes, timings and `df` before/after in a dated record under `docs/eval-reports/data/`.
- Out (explicitly):
  - Deleting any old snapshot, `.bak` or `.partial` file, and copying to another device (operator question F1; no target exists).
  - Any code change (OP-3 adds the checks to the tool). Any write to `papers.db`.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<run-date>-main-snapshot-record/`

**Commits** (① is a stub, committed before any real work):
① stub: record file with the four acceptance checks as an unchecked list and the abort rule (stop if under 20 GB free)
② snapshot taken; manifest copied into the record
③ verification results: quick_check, counts vs manifest, age
④ free-space and next-step notes (off-device copy is F1)

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `sqlite3 "file:<snapshot-db>?mode=ro" "PRAGMA quick_check"` prints `ok`
- `sqlite3 "file:<snapshot-db>?mode=ro" "select count(*) from papers"` equals the manifest `papers`
- `df -h /` before and after is quoted

**Acceptance / falsification criterion.** Newest main snapshot is under 24 hours old at verification time, quick_check is ok, restored paper count equals the manifest, and free space after is still at least 20 GB. Falsified if any of the four fails; then the snapshot is deleted and the failure reported (nothing else is touched).

**Gates / depends on.** Depends on: none. Operator answers: F1. Gates: EP-7, EP-3, EV-14, CQ-7.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched); operator answers: F1 · re-embed: n. Also: operator go-ahead to write about 9 GB (estimate, RV-6) into the main data dir's backups folder on a 98%-full device.

**Model tier and size.** Haiku; S (up to 2 h of agent work). Mechanical work, no judgement calls.

**Risk and rollback.** Disk fills mid-write on a 98%-full device. Mitigation: abort rule before starting; the tool reads the source read-only and writes only the new snapshot. Rollback: delete the new snapshot directory.

**Docs to update in the same PR.** BACKLOG and PROJECT-STATUS rows via EP-3; the restore procedure itself is documented by EP-7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### OP-5: Name the GPU lock holder and fail fast on the query path

Labels: wave:1-no-gpu, area:ops, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-5-gpu-lock-holder-and-fast-fail.md`.

**Review cross-reference:** S-06. **Wave:** W1 do now, no GPU.

**Why.** A query waits up to 300 s for the GPU lock before erroring (`app/assembly.py:630-640` passes no `gpu_lock_timeout`, default 300 s in the embedder and reranker), the timeout message does not name the holder (`rag/gpu_lock.py:38-41`), and doctor reports only 'unreachable' when a foreign process holds the GPU (OP-1 handles 'TEI down', not 'GPU held'; RV-1 F-1.9, RV-6 F-A3 and F-A8; review S-06). A foreign model server holds 18,609 of 24,576 MiB today.

**Scope.**
- In:
  - `FileGpuLock` writes pid, stage and UTC time to a `<lock>.holder` file on acquire (best effort, removed on release) and the timeout error reads it back.
  - Query path only: pass a short `gpu_lock_timeout` (proposed 20 s, a named constant; ingest keeps 300 s) with an actionable message.
  - `app.doctor`: list foreign GPU compute processes via `nvidia-smi --query-compute-apps` and read the TEI container exit code and OOM log line, so 'GPU held by a foreign process' is distinct from 'TEI crashed' (nvidia-smi and docker calls injected so tests need neither).
- Out (explicitly):
  - Marking eval runs invalid on lock timeouts (EV-10). A priority scheduler for the lock (not needed; the holder file is the smallest step). Reranker-failure fallback to fused order (changes behaviour, needs a Coverage flag: foundation).
  - The Config field for the timeout (RIDER-1 item 1).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/gpu_lock.py`
- `rag/test_gpu_lock.py`
- `app/doctor.py`
- `app/test_doctor.py`
- `app/assembly.py`
- `app/test_assembly.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings stating the holder-file format and the 20 s query-path timeout
② failing tests: second lock with timeout 0.1 raises with the first's stage label; query-path construction passes the short timeout; doctor names a foreign pid from a canned nvidia-smi output
③ implementation to green
④ doctor TEI exit-code and OOM-line reading with injected docker output

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/gpu_lock.py rag/test_gpu_lock.py app/doctor.py app/test_doctor.py app/assembly.py app/test_assembly.py`
- Two `FileGpuLock` objects on one path in a unit test (no GPU)
- Live check only when the operator frees the GPU: hold the lock from a second process, `semantic_search` returns the named error in under 22 s

**Acceptance / falsification criterion.** Holding the lock from a second process makes the query path fail in under 22 s with the holder named; doctor output against a canned foreign-holder state names the pid and says 'GPU held by a foreign process', not 'TEI unreachable'. Falsified if the error still waits the full default or omits the holder.

**Gates / depends on.** Depends on: OP-6. Gates: EP-7, EP-3, OP-2, EV-16, RIDER-1.

**Needs.** GPU: n · services up: none · operator sign-off: n for the code; the 20 s value is a decision in PR review. Moving it into Config rides RIDER-1 item 1. · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A 20 s ceiling will fail queries that today would have waited out a long GPU job. That is the intended behaviour but changes what an agent sees. Mitigation: ingest is unaffected; the value is one constant. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (doctor flags) via EP-3; RUNBOOK GPU-contention section via EP-7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### OP-6: Guard every corpus tool against a missing or mismatched database

Labels: wave:1-no-gpu, area:ops, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-6-wrong-corpus-guards.md`.

**Review cross-reference:** S-07. **Wave:** W1 do now, no GPU.

**Why.** Only `app.serve --data-dir` refuses a nonexistent database (`app/serve.py:80-82` has no exists check on the default branch). `app/corpus_integrity.py` opens the live database read-write, and the collection-versus-database pairing is checked nowhere, so a mispointed tool returns a confident empty or wrong corpus (the T-DOC56 shape; RV-6 F-A4, RV-3 F-1.2; review S-07). `app/dashboard/status.py:830` falls back to the literal collection name `papers`.

**Scope.**
- In:
  - One shared `require_existing_db()` (search for an existing helper first, e.g. the T-DOC56 `_resolve_store_paths`; add a module only if none fits) used by `corpus_integrity` (also opened `mode=ro`), `snapshot`, `reindex_idf`.
  - `app.doctor`: collection point count must match the database within 1% (stated tolerance), reported with both numbers.
  - Remove the `papers` fallback at `app/dashboard/status.py:830`.
- Out (explicitly):
  - The two `app/serve.py` branches (folded into OP-2, which owns that file's startup). Changing `migrate()` (protected).
  - Auto-snapshot before migration (RV-6 F-A7, not carried by the review).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/corpus_paths.py`
- `app/test_corpus_paths.py`
- `app/corpus_integrity.py`
- `app/test_corpus_integrity.py`
- `app/snapshot.py`
- `app/test_snapshot.py`
- `app/reindex_idf.py`
- `app/test_reindex_idf.py`
- `app/doctor.py`
- `app/test_doctor.py`
- `app/dashboard/status.py`
- `app/dashboard/test_status.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring of `require_existing_db()` stating precondition and error message; list of the five call sites
② failing tests per call site (nonexistent path exits non-zero, names the path)
③ helper + call sites to green; `corpus_integrity` opens `mode=ro` (test asserts a write attempt fails)
④ doctor point-count-vs-database check with injected counts; status fallback removed

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/corpus_paths.py app/test_corpus_paths.py app/corpus_integrity.py app/test_corpus_integrity.py app/snapshot.py app/test_snapshot.py app/reindex_idf.py app/test_reindex_idf.py app/doctor.py app/test_doctor.py app/dashboard/status.py app/dashboard/test_status.py`
- `conda run -n agent-rag-research python -m app.corpus_integrity --help` still works; each tool against a nonexistent data dir exits non-zero (shown in the PR)
- `conda run -n agent-rag-research python -m app.doctor --cpu-only` from each data dir still passes where services are up (needs services: run only when the vector store is up)

**Acceptance / falsification criterion.** Every named tool exits non-zero against a nonexistent path with a message that names the path; `corpus_integrity` cannot write; doctor run from each of the five data dirs passes its pairing check on the current corpora. Falsified if any tool still prints a result for a nonexistent path or if the doctor check fails on a correctly paired corpus.

**Gates / depends on.** Depends on: OP-3. Gates: EP-3, OP-5, OP-2.

**Needs.** GPU: n · services up: vector store (CPU container) only for the doctor smoke run; unit tests use fakes · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A false positive in the 1% tolerance blocks a healthy doctor run. Mitigation: tolerance is a named constant, the message prints both counts. Rollback: revert; the guards are additive.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (doctor behaviour) via EP-3; RUNBOOK via EP-7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### OP-7: Track the four container definitions in ops/docker-compose.yml

Labels: wave:1-no-gpu, area:ops, needs-services, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-7-tracked-container-definitions.md`.

**Review cross-reference:** S-12. **Wave:** W1 do now, no GPU.

**Why.** The four containers (embedder, reranker, vector store, reference-resolution service) cannot be recreated from tracked files: the vector-store image tag is the moving `latest`, arguments, ports and volumes exist only in `docker inspect`, and a re-pull could jump the storage version over a 31 GB store (RV-6 F-A2; review S-12). Not re-run by the review beyond the lane's own inspect.

**Scope.**
- In:
  - A compose file with the four services exactly as inspected today (image, command, binds, ports, GPU reservation), the vector store pinned to v1.18.2 by digest, and no restart policy (a restart on a contended GPU is how the foreign-holder situation arises).
  - Read-only inspection only: `docker inspect`, `docker image inspect`, `docker compose config`.
- Out (explicitly):
  - Starting, stopping or recreating any container (this ticket never applies the file). Moving the vector store's data. Adding a restart policy.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `ops/docker-compose.yml`

**Commits** (① is a stub, committed before any real work):
① stub: compose file with the four service names and a header comment stating 'mirrors inspected state of <date>; never applied by this ticket'
② services transcribed from `docker inspect` output, one commit per service pair
③ digest pin and `docker compose config` output compared line by line with the inspected values

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `docker compose -f ops/docker-compose.yml config` succeeds and matches image, command, binds and GPU reservation of each running container (differences listed in the PR)

**Acceptance / falsification criterion.** `docker compose config` reproduces image digest, command, binds, ports and GPU reservation of all four running containers; the vector-store image is pinned by digest to v1.18.2; the PR lists any field that could not be reproduced. Falsified if a running container's inspected setting is absent from the file.

**Gates / depends on.** Depends on: none. Gates: EP-7, EP-3.

**Needs.** GPU: n · services up: docker daemon read-only inspection (no container is started or restarted) · operator sign-off: n (not a protected path). The version pin is a decision for the operator in PR review. · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** The file drifts from reality or is applied by a later agent with different GPU settings. Mitigation: header states it is a mirror; EP-7 documents 'verify with config diff before any recreate'. Rollback: delete the file.

**Docs to update in the same PR.** RUNBOOK containers section via EP-7; PROJECT-STATUS doc-map/entry via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### RQ-1: Fix three one-line retrieval defects (payload, partial rerank, cap)

Labels: wave:1-no-gpu, area:retrieval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/RQ-1-three-retrieval-one-liners.md`.

**Review cross-reference:** S-09. **Wave:** W1 do now, no GPU.

**Why.** (1) `hybrid_search` requests the full payload (including chunk text) for up to 10,000 hits per arm but uses two fields (`rag/vector_index.py:286,296`; about 50 MB per main query, latency inferred). (2) A malformed partial reranker reply silently drops candidates: nothing checks the scored indices form a permutation before `rag/reranker.py:231`. (3) `max_hits_per_paper` applied together with `paper_id` returns fewer than `k` (RV-1 F-1.7, F-1.8 #7, RV-4 F-4.11; review S-09).

**Scope.**
- In:
  - `with_payload=[_EXT_ID_KEY, "kind"]` on both arms, after a grep proving no other payload field is read downstream (CONVENTIONS section 14: carry the check).
  - Raise `PermanentError` when the returned index set is not a permutation of the sent indices.
  - Skip the per-paper cap when `paper_id` is set.
- Out (explicitly):
  - Retry around vector-store calls, fusion depth changes, a reranker-failure fallback (all behaviour changes). Any ranking change: this ticket must leave `Hit` lists identical for queries without a `paper_id` filter.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `rag/reranker.py`
- `rag/test_reranker.py`
- `rag/retriever.py`
- `rag/test_retriever.py`

**Commits** (① is a stub, committed before any real work):
① stub: three docstring lines, one per defect, with the intended behaviour
② failing tests: identical `Hit` lists before and after on the fake; a stub client returning 31 of 32 indices raises; `paper_id` plus cap returns `k`
③ three fixes, one commit each, each green
④ grep evidence for 'payload fields read downstream' recorded in the commit body

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py rag/reranker.py rag/test_reranker.py rag/retriever.py rag/test_retriever.py`
- `conda run -n agent-rag-research python -m pytest -q rag/test_vector_index.py rag/test_reranker.py rag/test_retriever.py -o addopts="--disable-socket"`
- Sibling-path check: state in the PR what happens with `paper_id` set and no cap, and with a cap and no `paper_id`

**Acceptance / falsification criterion.** Not a ranking change, so no A/B: the falsifier is that `Hit` id and score lists are identical before and after on the fake for any query without a `paper_id`+cap combination; the 31-of-32 stub raises; the `paper_id`+cap test returns `k`. The EV-16 baselines run on this code, so any real-index difference would show as an unexplained delta against the pre-change commit recorded in each run manifest. Falsified if the identical-hits test fails.

**Gates / depends on.** Depends on: none. Gates: EP-3, RQ-5, RQ-2, EV-13, EV-16, CQ-9, RQ-4.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Narrowing the payload could break a reader that silently used another field. Mitigation: the grep and the identical-hits test. Rollback: revert (three independent commits).

**Docs to update in the same PR.** PROJECT-STATUS ledger via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### RQ-2: Add an opt-in, default-off relevance demotion to the Retriever

Labels: wave:1-no-gpu, area:retrieval, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/RQ-2-opt-in-relevance-demotion.md`.

**Review cross-reference:** S-21. **Wave:** W1 do now, no GPU.

**Why.** 37.4% of main-corpus papers (4,630 of 12,385) are off-topic against the audited labels and nothing in the pipeline can keep them out of an answer; `papers.relevance_score` separates on from off topic at AUROC 0.923 (RV-1 F-1.4, `docs/eval-reports/2026-11-10-topic-labels-audit.md`), the Retriever already loads the paper record for every reranked hit, and `Config.relevance_filter` is dead. The operator keeps the off-topic papers; the lever is measurement first, demotion only.

**Scope.**
- In:
  - `Retriever` keyword arguments (floor value, demote mode) that, when set, move results whose paper `relevance_score` is below the floor after those at or above it, preserving relative order and never removing any result; default off so output is byte-identical to today.
  - A `--demote-relevance <floor>` flag in `app/retrieval_eval.py`, the same pattern CQ-3 used for `--drop-stub-chunks`, so the arm can be run.
- Out (explicitly):
  - A hard drop or a filter (excluded by the frozen topic-focus protocol, section 6). A `Config` field or `SearchFilters.min_relevance` (RIDER-1 item 1 if adopted). The payload-index route (only if RQ-3 observes pool starvation). Choosing the floor: RQ-3's pre-registered arms.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/retriever.py`
- `rag/test_retriever.py`
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating demote semantics, the default-off identity guarantee, and the flag name that RQ-3's addendum will cite
② failing tests: below-floor results follow in-floor ones in original relative order; none removed; `Coverage` unchanged; default off equals baseline on the fake
③ implementation to green
④ `--demote-relevance` flag wired and tested

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/retriever.py rag/test_retriever.py app/retrieval_eval.py app/test_retrieval_eval.py`
- `conda run -n agent-rag-research python -m pytest -q rag/test_retriever.py app/test_retrieval_eval.py -o addopts="--disable-socket"`
- Identity check: with the flag absent, the per-question rows of a fake-backed run are equal before and after

**Acceptance / falsification criterion.** Default-off output is identical to the pre-change commit on the fake (byte-equal result lists); with a floor set, no result is removed and order within each side of the floor is preserved. The retrieval-quality ADOPT/REJECT rule is not applied here: it is frozen in the topic-focus protocol section 6 and applied by RQ-3. Falsified if the default-off identity test fails.

**Gates / depends on.** Depends on: RQ-1, EV-10. Gates: EP-3, RQ-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Demotion acts on the already-truncated pool and can starve it (a pool 40% off-topic still leaves about 19 of 32; RV-1 F-1.4). Mitigation: default off; RQ-3 reports `Coverage` pool sizes. Rollback: revert; nothing depends on it until RIDER-1.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (flag) via EP-3; no contract or Config change here. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

#### RQ-5: Extract one shared sparse_tokens() used by the index

Labels: wave:1-no-gpu, area:retrieval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/RQ-5-shared-sparse-tokens.md`.

**Review cross-reference:** none: RV-1 F-1.10, prerequisite of RIDER-1 item 4. **Wave:** W1 do now, no GPU.

**Why.** The fake vector store keeps its own `lower().split()` (`rag/fakes/fake_vector_store.py:131`) while the real index tokenizes and repairs ligatures in `_sparse_vector`, so a tokenizer change cannot fail any fake-backed test (review item h residual risk 2; RV-1 F-1.10). RIDER-1 item 4 makes the fake import a shared function, but that function must exist first and it is not a protected path.

**Scope.**
- In:
  - A small pure module (no vendor import, so vendor isolation holds) exposing `sparse_tokens(text)`, containing exactly today's behaviour including CQ-1's ligature repair, imported by `VectorIndex._sparse_vector`.
  - A test that pins the checksum of `rag/ligature_map.json` so the map cannot drift silently (review section 2, CQ-1: no test pins it).
- Out (explicitly):
  - Any tokenizer behaviour change (edge-punctuation stripping and BM25 weighting are CQ-17). Editing the fake (RIDER-1). A filter-parity test against an in-memory vector store (RV-1 F-1.10 part 2, not carried by the review).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/sparse_tokens.py`
- `rag/test_sparse_tokens.py`
- `rag/vector_index.py`
- `rag/test_vector_index.py`

**Commits** (① is a stub, committed before any real work):
① stub: module docstring stating 'behaviour-preserving extraction of the tokenizer in `_sparse_vector`'
② characterisation tests pinning today's tokens on a sample including damaged ligatures, and the ligature-map checksum
③ extraction to green; `_sparse_vector` calls it
④ mutation proof recorded: changing the shared function fails the vector-index tests

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/sparse_tokens.py rag/test_sparse_tokens.py rag/vector_index.py rag/test_vector_index.py`
- Identical sparse vectors before and after on 200 stored main chunks, read-only (script output quoted; no index touched)
- `conda run -n agent-rag-research python -m pytest -q rag/test_sparse_tokens.py rag/test_vector_index.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Sparse vectors for a fixed sample of chunk texts are byte-identical before and after the extraction; mutating the shared function fails the vector-index tests. Falsified if any sampled vector differs.

**Gates / depends on.** Depends on: RQ-1. Gates: EP-3, EV-14, CQ-9, CQ-17, RIDER-1.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Extraction subtly changes tokens, which would silently desynchronise stored sparse vectors from query tokens. Mitigation: the identical-vectors check. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (new `rag/` module) and the ARCHITECTURE.md module list; the ARCHITECTURE line is in this PR, the ledger via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.

### W2 first GPU session, measurements only

#### EP-4: Batch BACKLOG and PROJECT-STATUS updates for wave 2

Labels: wave:2-gpu-measure, area:docs, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EP-4-status-batch-wave-2.md`.

**Review cross-reference:** S-13. **Wave:** W2 first GPU session, measurements only.

**Why.** Wave 2 produces the first measured numbers for the new sets; they must land in the shipped-work ledger and the open-questions section in one pass, not from seven concurrent branches editing the same two files (same reason as EP-3).

**Scope.**
- In:
  - BACKLOG rows for EV-16 to EV-22 flipped with SHAs; PROJECT-STATUS section 3 ledger entries quoting each verdict and its report; section 5 (tried and failed) for any REJECT; section 6 for open questions (F3 answered or not, F6 bar, F8).
- Out (explicitly):
  - Interpreting results beyond what each report states. Editing reports.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/PROJECT-STATUS.md`
- `docs/BACKLOG.md`

**Commits** (① is a stub, committed before any real work):
① stub: checklist of wave-2 tickets with report paths, empty verdict cells
② BACKLOG rows + SHAs
③ PROJECT-STATUS ledger and section 5/6 entries
④ open-question status lines

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `git cat-file -e <sha>^{commit}` for every SHA written
- Every verdict quoted equals the verdict line in its report (grep)

**Acceptance / falsification criterion.** Each wave-2 ticket has a row and a ledger entry whose verdict text is copied from its report and whose SHA resolves. Falsified if any quoted verdict differs from the report.

**Gates / depends on.** Depends on: EP-3, EV-16, EV-17, EV-18, EV-19, EV-20, EV-21, EV-22. Gates: EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Haiku; S (up to 2 h of agent work). Mechanical work, no judgement calls.

**Risk and rollback.** Low. Rollback: revert.

**Docs to update in the same PR.** This ticket is the docs obligation for wave 2.

#### EV-16: Run the frozen main-corpus baselines (papers, books, legacy)

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-16-baseline-main-corpus.md`.

**Review cross-reference:** S-16. **Wave:** W2 first GPU session, measurements only.

**Why.** No baseline exists for the new papers-passage and causal-books sets, and every later A/B needs a measured reference on the same code and index; the first run is also the only moment the TEI truncation limit can be confirmed with one `/info` request (review S-16). Plain BM25 already reaches 0.96-0.98 paper recall on these sets, so only passage level and the title-ablated arm can show headroom (RV-3 F-1.3).

**Scope.**
- In:
  - Run `run_baseline_main.sh papers books legacy` exactly as the GPU-day runbook step 1a specifies (about 654 queries, estimated 20-40 min), as a detached process (LESSONS section 7.3); then the BM25 floor (EV-15) beside it, the title-ablated arm and the strata report (EV-6).
  - One `/info` request to the embedder to confirm its truncation limit; record the value.
  - Report unmodified as a dated baseline document: passage-level headline (member-passage hit@10 and P@1, plus `passage_excerpt_hit`), paper recall as tripwire only, per-stratum Wilson intervals, `authority`/`edition`-style small strata labelled descriptive.
- Out (explicitly):
  - Any A/B or config change (later tickets). The focus set (EV-17) and standards (EV-18). Re-grounding or editing a fixture. Quoting a precision-95 headline number (operator question F8).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-main-baseline.md`
- `docs/eval-reports/data/<run-date>-main-baseline/`
- `docs/eval-reports/data/2026-11-10-papers-passage-gt/runs/ (own stamp only)`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton citing the frozen main-corpus protocol and the stop conditions; hash file revision and git revision of the code under test recorded
② detached run launched; MANIFEST committed when it starts (start time, collection, db, git revision, fixture hashes)
③ raw reports copied into the data dir with `n_errors` and `run_valid` shown
④ BM25 floor and title-ablated arm
⑤ report written; every number carries {metric, fixture, arm, pool depth, config}

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research python -m app.doctor --no-auto-start` exits 0 before and after
- Run scripts print `check-hash` and `check-points` passes; the report's `ground_truth_sha256_12` equals the hash file's entry
- `n_errors` is 0 and `run_valid` is true in every report (else the arm is invalid and is not read)

**Acceptance / falsification criterion.** Per set (never averaged): passage-level hit@10 and P@1 with Wilson intervals, the BM25 floor beside it, the title-ablated paper recall, and stratum tables; the report hash equals the frozen hash; zero errors. The ceiling for each metric is printed with it (member hit@10 ceiling 1.00; paper recall tripwire headroom at most 2 items on the legacy 210-set). Falsified (run discarded) if a hash or point-count check fails or any error is a lock timeout.

**Gates / depends on.** Depends on: EV-7, EV-8, EV-10, EV-11, EV-15, RQ-1, OP-5. Operator answers: F3. Gates: EV-17, EV-18, EV-19, EV-20, EV-21, EV-22, EP-4, RQ-3, CQ-10, CQ-18.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free of the foreign model process (operator question F3); about 20-40 min GPU (estimate, not measured).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A foreign GPU holder or a held lock starves the run. Mitigation: OP-5 names the holder; EV-10 invalidates a starved run; one GPU job at a time. The run only reads. Rollback: discard the run directory.

**Docs to update in the same PR.** Dated baseline report is the doc; PROJECT-STATUS section 3/6 via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.

#### EV-17: Run the frozen topic-focus baseline

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-17-baseline-topic-focus.md`.

**Review cross-reference:** S-16. **Wave:** W2 first GPU session, measurements only.

**Why.** Whether off-topic papers enter the top ten for realistic questions is unmeasured: 37.4% of main-corpus papers are off-topic (labels audited at weighted kappa 0.90) and nothing has ever measured how often they surface in answers (review section 4 'Unknown'). The frozen topic-focus protocol defines the instrument; its fixture hash is null until authoring ends.

**Scope.**
- In:
  - Run the `focus` mode of the main baseline script (about 50 queries, estimated 2-5 min) once EV-4 has frozen the focus fixture hash in the hash file; report off-topic share in the top 10 with its interval, `offtopic-legit` paper recall, and the control arms, per the frozen protocol.
- Out (explicitly):
  - Choosing the materiality bar (operator question F6: the report states the number, the operator sets the bar). Any demotion arm (RQ-3).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-focus-baseline.md`
- `docs/eval-reports/data/<run-date>-focus-baseline/`
- `docs/eval-reports/data/2026-11-10-papers-passage-gt/runs/ (own stamp only)`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton, the frozen metrics and the refusal rule (the script refuses while the hash is null)
② MANIFEST committed at launch
③ raw report copied; errors and validity shown
④ report with off-topic share, interval and the bar left blank for the operator

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `sha256sum` of the focus fixture equals the hash file entry (the script checks it)
- `n_errors` 0, `run_valid` true

**Acceptance / falsification criterion.** Report states off-topic share in the top 10 on the focus set with a Wilson interval, per question dimension, never averaged with the other sets, with the control arms' values beside it; its fixture hash matches. The ceiling and floor arithmetic of the protocol are printed with each metric. Falsified (not read) if the hash was null at launch or any error occurred.

**Gates / depends on.** Depends on: EV-16. In-progress tickets on other branches (merge order or inputs): EV-4. Operator answers: F3. Gates: EP-4, RQ-3.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); focus fixture authoring finished and hash frozen (EV-4).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Fixture hash still null: the script refuses to run, which is the intended guard. Rollback: discard run directory.

**Docs to update in the same PR.** Report via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.

#### EV-18: Run the frozen standards baseline and evaluate the structure gate

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-18-baseline-standards.md`.

**Review cross-reference:** S-16, S-24 gate. **Wave:** W2 first GPU session, measurements only.

**Why.** The standards corpus (119 documents, 35,714 chunks, built with the new bounded chunker) has never been measured by any fixture; the standards protocol freezes a depth decision rule (D-1) and a falsifier (S-1) to be evaluated from this one run, and the review gates the whole standards structure bundle (CQ-12 to CQ-16) on a count taken from it (review S-24).

**Scope.**
- In:
  - Run `run_baseline.sh` exactly as GPU-day runbook step 1c specifies (about 1,198 queries across depth 128/32/64 and fused/dense/sparse arms plus ablations and controls; estimated 1-2 h), detached; BM25 floor and per-stratum tables beside it; evaluate D-1 and S-1 as written.
  - Gate evaluation for CQ-12: count answerable misses whose gold chunk or top-10 chunk has a furniture, numeric or NOTE root, or a split table (mechanical rules from `scripts/chunk_quality_census.py` and RV-2 F-2.5), and state whether the count reaches 5.
- Out (explicitly):
  - Changing the standards depth default (that is rule D-1's verdict, a sign-off, not an edit here). Any structure fix (CQ-12 to CQ-16).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-standards-baseline.md`
- `docs/eval-reports/data/<run-date>-standards-baseline/`
- `docs/eval-reports/data/2026-11-10-standards-gt/runs/ (own stamp only)`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with rules D-1 and S-1 quoted verbatim and the gate definition for CQ-12
② MANIFEST committed at launch
③ raw reports + validity (the `depth128-fused-repeat` arm is the validity gate)
④ D-1 / S-1 verdicts and the structure-gate count
⑤ report

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Run script prints `check-hash` and `check-points` passes
- `depth128-fused-repeat` agrees with `depth128-fused` within the protocol's jitter envelope
- `n_errors` 0, `run_valid` true

**Acceptance / falsification criterion.** Verdicts for D-1 and S-1 are mechanical and quoted from the protocol; the structure-gate count is a number with the list of qualifying questions; per-stratum intervals shown with edition/authority marked descriptive; no fixture averaged. Falsified (run not read) if the repeat arm disagrees beyond the envelope or any error occurs.

**Gates / depends on.** Depends on: EV-16, EV-11, EV-15. Operator answers: F3. Gates: EV-19, EV-20, EV-21, EV-22, EP-4, CQ-12, CQ-13, CQ-14, CQ-16, CQ-18, RIDER-1.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 1-2 h GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Longest read-only job of the session; a mid-run foreign GPU grab invalidates it. Mitigation: detached, validity arm, `run_valid`. Rollback: discard.

**Docs to update in the same PR.** Report via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.

#### EV-19: Run the reranker-score census on the absent arms

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-19-rerank-score-absence-census.md`.

**Review cross-reference:** S-16, S-04. **Wave:** W2 first GPU session, measurements only.

**Why.** Whether the cross-encoder score can tell 'answerable' from 'absent' was never tested; the earlier 'no floor' verdict measured RRF rank arithmetic (review item a). This is the cheapest read-only job after the baselines and decides whether exposing the score (RQ-4) is worth a contract change.

**Scope.**
- In:
  - Run the EV-13 census tool on: standards absent 9 and partial-absent 13 (separately), main known-absent 24, books partial-absent 5, and the Waymo absent items, each against the answerable top-1 score, about 500 queries (estimate 15-30 min); AUROC with Hanley-McNeil interval and the IQR separation test; explicit `--collection`, `--db-path`, `--blob-dir` for every corpus.
- Out (explicitly):
  - Any threshold or wiring decision (needs 60 or more distinct real absent items; RV-3 F-1.10). Exposing the score (RQ-4).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-rerank-score-census.md`
- `docs/eval-reports/data/<run-date>-rerank-score-census/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the rule written before the run: gate OPEN for RQ-4 only if the lower CI bound exceeds 0.65 on at least two of three sets; question CLOSED if the interval includes 0.5 on two of three; a floor is 'viable' only at AUROC 0.85 or more
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ raw census output saved
④ report with per-set AUROC, CI and the verdict

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every census command names `--collection` explicitly (a missing flag fails after EV-7)
- Counts of items per arm printed beside each AUROC

**Acceptance / falsification criterion.** Verdict is the pre-registered rule applied mechanically on per-set (not pooled) results, with each set's n printed; partial-absent is reported as its own class. Ceiling note: with 9-24 absent items per set the interval half-width is about 0.1 or more, so 'open' needs a clearly separated signal. Falsified (gate closed) if the interval includes 0.5 on two of the three sets.

**Gates / depends on.** Depends on: EV-13, EV-16, EV-18. Operator answers: F3. Gates: EV-20, EP-4, RIDER-1, RQ-4.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 15-30 min GPU (estimate).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Small n yields an inconclusive verdict. Mitigation: the rule treats inconclusive as 'gate closed, no change'. Rollback: n/a (read-only).

**Docs to update in the same PR.** Report via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.

#### EV-20: Run the per-corpus depth and dense-weight grid

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-20-depth-weight-grid.md`.

**Review cross-reference:** S-19. **Wave:** W2 first GPU session, measurements only.

**Why.** Rerank depth and dense weight differ per corpus (standards depth 128; Waymo weight 0.7; others 32 and 0.5) with no recorded reason, and the existing measurements are single-question effects with the sign flipping between fixtures (RV-1 F-1.5, review S-19). The evidence that the settings matter is weak; the evidence that they differ for a reason is absent.

**Scope.**
- In:
  - The GPU-day runbook step 3 grid: depth {32, 128} by dense weight {0.5, 0.7, 1.0} per corpus on its own fixtures, arms already measured in the baselines not repeated (about 1,200 queries, estimate 40-90 min), paired flips via `scripts/nb_xp_deeppool_tables.py` with its jitter envelope.
  - Rule G-1 as already frozen in the runbook: a candidate arm is believed only with net member-passage hit@10 of at least +3 on that corpus's own fixture(s), wins:losses at least 3:1, no gating stratum (n at least 10) losing more than 1, and the same sign on the title-ablated arm. The standards depth question is already decided by D-1 and is not reopened.
- Out (explicitly):
  - Changing any default (a verdict here is a recommendation; a default change needs sign-off and goes through RIDER-1 or a config edit the operator approves). The review's fallback 'otherwise set everything to 32/0.5' is NOT part of G-1: see risk.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-depth-weight-grid.md`
- `docs/eval-reports/data/<run-date>-depth-weight-grid/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton quoting rule G-1 and stating the unresolved difference with the review (see risk)
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ arms run one at a time (cheapest first); MANIFEST per arm
④ flip tables per corpus with the jitter envelope
⑤ report: verdict per corpus

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Each arm names `--collection`, `--db-path`, `--blob-dir` explicitly
- Both fixtures (or all of a corpus's fixtures) are reported separately, never averaged

**Acceptance / falsification criterion.** Per corpus: the flip table and the G-1 verdict; no default changes unless G-1 holds; the ceiling for 'net +3' is shown per fixture (n answerable). Falsified if the baseline arm repeated here differs from the EV-16/EV-18 arm beyond the jitter envelope (then the grid is not interpretable).

**Gates / depends on.** Depends on: EV-16, EV-18, EV-19. Operator answers: F3. Gates: EV-21, EP-4, RIDER-1.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 40-90 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** The review (S-19) says that if no arm wins, reset all corpora to 32/0.5; the runbook's frozen rule G-1 says defaults stay. The EV-20 stub commit must state which applies; default is G-1 as frozen, because resetting is a config change needing sign-off and a frozen rule changes only by dated addendum. Rollback: n/a (read-only).

**Docs to update in the same PR.** Report via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.

#### EV-21: Run the amended CQ-3 stub-filter A/B

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-21-stub-filter-ab.md`.

**Review cross-reference:** S-18. **Wave:** W2 first GPU session, measurements only.

**Why.** 7-10% of chunks in every corpus are heading-only stubs (main 36,364 of 399,676; standards 2,483 of 35,714) and whether they cost any results is unmeasured; CQ-3 shipped a reversible default-off filter and a pre-registered A/B, amended by EV-12 (review S-18, `docs/eval-reports/2026-11-10-cq3-stub-chunks.md`).

**Scope.**
- In:
  - GPU-day runbook step 4 as amended by EV-12: baseline and `--drop-stub-chunks` back to back per fixture (standards, causal-books, papers-passage), baseline re-run rather than reused, per-question rows kept, stubs matched by chunk id (about 588 queries x 2 arms, estimate 40-80 min); `scripts/list_stub_chunks.py --ab`.
- Out (explicitly):
  - Turning the filter on (adoption rides RIDER-1 item 1). Changing the pre-registration.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-stub-filter-ab.md`
- `docs/eval-reports/data/<run-date>-stub-filter-ab/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton quoting the EV-12 addendum rule verbatim
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ baseline and drop arms with MANIFEST per arm
④ paired flip table by fixture and stratum
⑤ report: ADOPT or REJECT

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Per-question rows present (no `--no-per-question`)
- Both arms ran on the same collection and code revision (manifest lines compared)

**Acceptance / falsification criterion.** ADOPT only if the EV-12 rule holds (net +3 items on at least one set, no stratum losing more than 1, stub-at-rank-1 share above 0 at baseline); otherwise REJECT and the default stays off. Both sets' tables are shown; none averaged. Ceiling: a gain is bounded by the stub-at-rank-1 and top-10 stub shares printed from `--report`. Falsified if the baseline arm differs from EV-16/EV-18's beyond the jitter envelope.

**Gates / depends on.** Depends on: EV-12, EV-9, EV-16, EV-18, EV-20. Operator answers: F3. Gates: EV-22, EP-4, RIDER-1.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 40-80 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A noise flip adopting a filter: prevented by the amended minimum effect. Rollback: n/a (flag only).

**Docs to update in the same PR.** Report via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.

#### EV-22: Run the ligature-repair A/B on the repaired clone

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-22-ligature-resparse-ab.md`.

**Review cross-reference:** S-17. **Wave:** W2 first GPU session, measurements only.

**Why.** CQ-1's sparse-arm ligature repair is merged but unmeasured: 32.42% of main chunks (129,566) carry damaged ligatures and 57% of the papers-set gold chunks (35 of 61) and 39% of books (27 of 69) are damaged, so the effect can be stratified (RV-3 F-1.14, review S-17). Review item h shows the merged query-side repair changes none of 1,217 stored queries.

**Scope.**
- In:
  - Runbook step 5: arm A is the live collection at the baseline revision; arm B is the repaired clone from CQ-7 (about 345 queries, estimate 12-25 min GPU); stratify every set by damaged versus clean gold (census regexes in `docs/eval-reports/data/2026-11-10-ligature-census/results.json`); delete the clone afterwards.
  - First, on CPU, recheck item h for the three new sets' questions: if repair changes any of their query strings, arm A must instead run from the pre-CQ-1 checkout.
- Out (explicitly):
  - Dense-side repair and any 129k re-embed (explicitly not doing; reopened only if this A/B shows a sparse gain and dense-only misses on damaged gold). Applying resparse to the live collection.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-ligature-ab.md`
- `docs/eval-reports/data/<run-date>-ligature-ab/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the rule: net gain on damaged-gold items and no loss of more than 1 on any set, both strata reported
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ CPU recheck of query-string changes; arm choice recorded
④ arms A and B run; MANIFEST per arm
⑤ stratified flip tables and verdict; clone deleted and recorded

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command names `--collection` (live for arm A, clone for arm B)
- Point counts of live and clone are equal before the run

**Acceptance / falsification criterion.** Verdict applies the pre-registered rule per set, with damaged and clean strata separate (35/26 on papers, 27/42 on books); the ceiling is stated (a gain can only occur on damaged-gold items; with about 60 damaged items only an effect of about 10 net items is detectable per RV-3). Falsified if arm A differs from the EV-16 run beyond the jitter envelope.

**Gates / depends on.** Depends on: CQ-7, EV-16, EV-18, EV-21. Operator answers: F3. Gates: EP-4, RQ-3, CQ-17, CQ-18.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); the repaired clone exists (CQ-7); about 12-25 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Serving from the clone with the wrong code revision. Mitigation: manifest records revisions; arm B uses the CQ-1 code by design. Rollback: delete the clone.

**Docs to update in the same PR.** Report via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.

### W3 gated changes after baselines

#### CQ-9: Add idempotent payload indexes and verify them on a clone

Labels: wave:3-gated-change, area:corpus, area:retrieval, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-9-payload-indexes-on-clone.md`.

**Review cross-reference:** S-22. **Wave:** W3 gated changes after baselines.

**Why.** If EV-14 shows filtered HNSW search loses neighbours against exact search, payload indexes are the repair; they rebuild HNSW links, a CPU and disk cost, so they must be proven on a clone first (review S-22; RV-1 F-1.2). If EV-14 shows overlap of at least 0.99, this ticket is closed unstarted.

**Scope.**
- In:
  - `ensure_payload_indexes()` in `VectorIndex` (idempotent; keyword indexes for `kind`, `doc_type`, `paper_id`, `author_orgs`, `curated_author_orgs`, `categories`; datetime for `published`) and a call from `_ensure_collection` for new collections only.
  - On a clone: build the indexes, re-run the EV-14 script, report overlap with and without the index and the count of queries returning fewer than k.
- Out (explicitly):
  - Applying to any live collection (follow-on ticket, written only on ADOPT, with explicit operator approval, because it changes candidate sets slightly everywhere). Any GPU use.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `docs/eval-reports/<run-date>-payload-index-clone.md`
- `docs/eval-reports/data/<run-date>-payload-index-clone/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the rule written before the clone is touched: ADOPT if overlap with the index is at least 0.99 and strictly greater than without, and queries returning fewer than k fall to 0
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ `ensure_payload_indexes` with tests on mocked clients
④ clone: build indexes, time and size recorded
⑤ re-run of the EV-14 script on the indexed clone; verdict; clone deleted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py`
- `df -h /` before the clone; abort under 20 GB free
- Unit test: calling `ensure_payload_indexes()` twice changes nothing

**Acceptance / falsification criterion.** Verdict applies the stated rule to the three filters separately; build time, added disk and p50 query latency before and after are reported. Falsified if overlap with the index is not strictly greater than without it.

**Gates / depends on.** Depends on: EV-14, RQ-5, RQ-1. Operator answers: F2. Gates: CQ-17, EP-5.

**Needs.** GPU: n · services up: vector store (CPU container) up; no GPU services · operator sign-off: n (no protected path is touched); operator answers: F2 · re-embed: n. Also: vector store start approved (F2); 6-8 GB free for one clone.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Index build on a large clone could fill the disk or slow other work. Mitigation: free-space abort rule, one clone, deleted after. Rollback: delete the clone; revert the code (no live collection touched).

**Docs to update in the same PR.** Report; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### CQ-10: Assess raising the embedding server's token limit for truncated chunks

Labels: wave:3-gated-change, area:corpus, area:ops, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-10-assess-raising-embedder-token-limit.md`.

**Review cross-reference:** S-23. **Wave:** W3 gated changes after baselines.

**Why.** 3,138 main chunks exceed the embedder's 4,096-token limit and are silently truncated (0.79% of main chunks; 0 in standards). CQ-4's plan (`docs/eval-reports/data/2026-11-10-truncation-rechunk/report.md`) shows the re-chunk fix costs about 177k-212k embeddings (against 64,770 chunks held today by the affected papers), re-grounding of 48 ground-truth items, and mixed chunk granularity inside one index; it names raising the embedding server's `--max-batch-tokens` as the alternative it did not assess. The review's rule (d)(2) permits a targeted re-chunk only for information destroyed at embed time, and CQ-4 shows the targeted form is not cheap, so the cheap alternative is assessed first (review S-23, re-scoped).

**Scope.**
- In:
  - Feasibility measurement on a scratch embedder setting, after the operator restarts the embedder container with a higher limit (agents never restart containers): VRAM use, out-of-memory events and p50/p95 latency at the larger limit; then embed the exact truncated chunk list (`truncated_chunk_ids_main.txt`, about 3,136 chunks, minutes of GPU) and report the cosine between each full-length embedding and its stored truncated embedding. Nothing is written to any index.
  - Ceiling statement: none of the 48 affected ground-truth items has a truncated gold chunk (CQ-4), so a retrieval gain on the current fixtures is bounded at 0 by construction; the verdict is feasibility and vector shift, not retrieval quality.
- Out (explicitly):
  - Any re-chunk (see CQ-11: only inside a planned full re-chunk). Writing or replacing vectors in any collection. Restarting containers (operator action).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-embedder-token-limit.md`
- `docs/eval-reports/data/<run-date>-embedder-token-limit/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the feasibility rule written before any run: FEASIBLE if no out-of-memory event and p95 embedding latency for normal chunks stays within 1.5x of today's; INFEASIBLE otherwise
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ limit change requested from the operator; baseline latency and VRAM recorded first
④ truncated-chunk embeddings and cosine table
⑤ report and verdict

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Each embedding call is wrapped by the existing GPU lock; no collection name appears in any write command
- Count of chunks embedded equals the length of the truncated-id list

**Acceptance / falsification criterion.** Report states, for the larger limit: out-of-memory events (0 or not), latency ratio against baseline, and the distribution of cosine shift on the truncated chunks; verdict FEASIBLE or INFEASIBLE by the pre-stated rule. Falsified (INFEASIBLE) if any out-of-memory event occurs or latency exceeds 1.5x.

**Gates / depends on.** Depends on: EV-16, RQ-3. Operator answers: F3. Gates: CQ-11.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: operator restarts the embedder with a higher limit and restores it afterwards; GPU free (F3); minutes of GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A larger batch-token limit can exhaust VRAM next to the reranker and starve other work. Mitigation: operator-run restart, restore step in the record, one job at a time. Rollback: restore the previous container setting.

**Docs to update in the same PR.** Report; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### CQ-11: Decide the truncation fix: limit change or only inside a planned full re-chunk

Labels: wave:3-gated-change, area:corpus, area:eval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-11-truncation-fix-decision.md`.

**Review cross-reference:** S-23. **Wave:** W3 gated changes after baselines.

**Why.** With CQ-4's costs on record, a re-chunk of only the truncated chunks is not justified on its own (about 177k-212k embeddings, 48 ground-truth items to re-ground, mixed granularity). The only remaining routes are a server limit change (CQ-10) or folding the truncation fix into a full re-chunk that passes the review's paired chunker test, rule (d)(3) (66 papers, two scratch collections, about 45k embeds, at least +5 net excerpt hits, flips at least 3:1, 2x disk headroom).

**Scope.**
- In:
  - A short decision note: if CQ-10 is FEASIBLE, recommend the limit change to the operator and list which stored vectors would be recomputed (only the truncated chunks, about 3,136 for main; a bounded job, specified but not run); if INFEASIBLE, record that the truncation defect waits for a full re-chunk decision and is not re-proposed separately. No GPU.
- Out (explicitly):
  - Running any re-chunk or re-embed. Re-grounding fixtures. A full re-chunk test (not part of this programme).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-truncation-fix-decision.md`

**Commits** (① is a stub, committed before any real work):
① stub: note skeleton with the two branches and the facts each cites (CQ-4 report, CQ-10 verdict)
② decision text
③ cross-check that every cited number resolves to a file

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every number in the note appears in CQ-4's report or CQ-10's report (grep list in the PR)

**Acceptance / falsification criterion.** Note states one recommendation, derived mechanically from CQ-10's verdict, with costs from CQ-4 quoted exactly; someone who did not write it can trace each figure. Falsified if a quoted figure is absent from its source report.

**Gates / depends on.** Depends on: CQ-10. Gates: CQ-15, EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. Docs only. Rollback: revert.

**Docs to update in the same PR.** Note is the doc; PROJECT-STATUS section 5/6 via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### CQ-12: Add golden tests and rules to the section tracker (standards)

Labels: wave:3-gated-change, area:corpus, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-12-section-tracker-rules-and-golden-tests.md`.

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Why.** `_heading_depth` and `_SectionTracker` (`rag/parser.py:457-494`, fed by the unfiltered `text_level >= 2` test at `:539`) are the root cause of stale clause numbers, furniture roots and NOTE/output-line roots in section paths; neither has a unit test. Reproduced today: a path such as `'FOR UL INTERNAL REFERENCE > 6.4.1.2 Risk'`. It is a standards and books problem (1,678 furniture-root chunks in standards against 150 in main), high for standards and low for main (review item c). It cannot fix flat books: the parser emits only levels 1 and 2.

**Scope.**
- In:
  - Golden tests first, pinning the reproduced defects, then rules that reject or renest headings whose text equals the last path component, drop stale numeric markers, and refuse NOTE/output lines as roots; expose the tracker as a pure function over stored blocks so it can be re-run on CPU.
  - Starts only if EV-18's gate count is 5 or more.
- Out (explicitly):
  - Books' chapter structure (needs the PDF outline join; not carried by the review). Rewriting stored `Block.section_path` (operator question F7). Re-embedding (CQ-15/CQ-16).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/parser.py`
- `rag/test_parser.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring and a skipped golden-test file listing the reproduced sequences
② golden tests pinning current behaviour on the reproduced examples (green)
③ rules change the golden expectations; tests updated in the same commit with the reason
④ pure function over stored blocks; CPU diff over the standards documents (read-only), counts and a 30-diff manual sample recorded in the commit body

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/parser.py rag/test_parser.py`
- `conda run -n agent-rag-research python -m pytest -q rag/test_parser.py -o addopts="--disable-socket"`
- `python scripts/chunk_quality_census.py <standards.db>` before/after counts on the in-memory re-derivation

**Acceptance / falsification criterion.** The three reproduced paths no longer occur; the in-memory re-derivation over standards blocks changes only paths with a stale numeric, furniture or NOTE root (every changed path listed, 30 sampled by hand with zero wrong); main sample unchanged within stated tolerance. Falsified if a sampled changed path is wrong.

**Gates / depends on.** Depends on: EV-18. Gates: CQ-13, CQ-15.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A tracker change affects every future parse. Mitigation: no live data is re-parsed here; golden tests pin the rest. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS via EP-5; DATA-CONTRACTS wording is RIDER-1 conditional item 7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### CQ-13: Add the running-furniture pre-pass and table sup/sub and span handling

Labels: wave:3-gated-change, area:corpus, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-13-furniture-prepass-and-table-spans.md`.

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Why.** Running headers promoted to headings are a standards problem and are detectable positionally: 20 of 119 standards documents, 947 blocks, 1,678 chunks (4.7%) have a furniture string as their path root (RV-2 F-2.5); table conversion drops superscripts and rowspan content (`<10-8 h-1` instead of `<10^-8 h^-1`; 2,189 standards tables) (RV-2 F-2.10).

**Scope.**
- In:
  - Pre-pass in `_build_blocks`: key `(text with digits collapsed, 12-point y bucket)` per page; a text item recurring on at least 4 pages is furniture and skipped before the tracker; also runnable on stored blocks.
  - `markdownify` `sup_symbol`/`sub_symbol`, and rowspan/colspan expansion before conversion (fallback: `col: value` lines for irregular spans).
- Out (explicitly):
  - Main-corpus table HTML (not stored, needs a re-parse: not carried by the review). Re-embedding. Persisting `content_list` (explicitly not doing).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/parser.py`
- `rag/test_parser.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings for both changes and the 70% / 4-page criteria
② golden tests: the PMHF row and a severity table (`10^-8`, equal cell counts); a furniture case and a real repeating template heading that must survive
③ pre-pass implementation to green
④ table fix to green; CPU probe re-run on standards blocks

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/parser.py rag/test_parser.py`
- Positional probe re-run on stored standards blocks reports 0 furniture roots; template headings that repeat at different y survive (RV-2 F-2.5 check)
- `conda run -n agent-rag-research python -m pytest -q rag/test_parser.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Probe finds 0 furniture roots in standards; the real template heading survives; golden table tests pass with equal cell counts per row. Falsified if the 70% threshold removes a real template heading.

**Gates / depends on.** Depends on: CQ-12, EV-18. Gates: CQ-15.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** False positives delete real headings. Mitigation: y-clustering criterion and the survival test. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### CQ-14: Fold heading-only chunks into the next group and guard normalisation regexes

Labels: wave:3-gated-change, area:corpus, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-14-stub-folding-and-regex-guard.md`.

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Why.** Heading-only groups become stub chunks (standards 2,825 by the lane's count, 400 of them bare clause numbers; main 37,770); the chunker emits them by design (`rag/chunker.py:169-173`, `:261-266`). The two generic normalisation regexes also damage identifiers such as `a<sub>max,brake</sub>` and `2016a,b` (RV-2 F-2.6, F-2.8).

**Scope.**
- In:
  - Do not emit a group that is only its own heading text: carry it as prefix of the following group's body, or drop it when nothing follows; prepend a bare clause number to the next term group's first block (the operator decision in RV-2 open question 4 is recorded in the PR).
  - Add `<sub>/<sup>` spans and `\d[a-z],[a-z]` citation patterns to the normalisation `protected` regex.
- Out (explicitly):
  - Per-corpus normalisation tables, glued-word repair, a dictionary segmenter (new dependency). Re-embedding.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/chunker.py`
- `rag/test_chunker.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the folding rule and the bare-number rule
② failing tests (the existing `test_complete_definition_retains_its_term_path_after_a_stale_numeric_marker` expectation changes with a recorded reason)
③ implementation to green
④ regex guard + diff of derived text over standards blocks (changes limited to the intended classes)

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/chunker.py rag/test_chunker.py`
- `python scripts/chunk_quality_census.py <standards.db>` on an in-memory re-chunk: stub rate under 2% and `bare_number` 0 (targets from RV-2 F-2.6)
- Derived-text diff over standards blocks shows no change inside `<sub>` spans

**Acceptance / falsification criterion.** On a re-chunk of the standards blocks (read-only, in memory) the stub rate is under 2% and bare-number stubs are 0; ten definitions sampled from the vocabulary part carry their numbers in the term chunk; no change inside `<sub>/<sup>` spans. Falsified if any sampled definition loses its number or term.

**Gates / depends on.** Depends on: EV-18. Gates: CQ-15.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Folding changes chunk boundaries for every new ingest and invalidates gold chunk ids of re-chunked corpora (scoring uses the excerpt metric). Mitigation: nothing is re-chunked live here. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### CQ-15: Re-derive standards paths from stored blocks and re-chunk on a clone

Labels: wave:3-gated-change, area:corpus, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-15-standards-rederive-and-rechunk-clone.md`.

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Why.** The structure fixes (CQ-12 to CQ-14) change section paths and chunk boundaries, so they take effect on the existing corpus only through a re-chunk of the standards corpus (about 35k embeds; 477 MB collection); whether stored block paths may be rewritten at all is operator question F7.

**Scope.**
- In:
  - A CPU tool that re-derives section paths from stored standards blocks with the CQ-12/13 functions into a derived column or copy (the default, until F7 is answered), then `app.rechunk` on a database copy and a clone of the standards collection, with CQ-8 reuse, GPU embed of the changed chunks only.
- Out (explicitly):
  - Rewriting stored `Block.section_path` in place (needs F7 = rewrite). Live application. Books' outline paths. Measurement (CQ-16).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/restructure_blocks.py`
- `app/test_restructure_blocks.py`
- `docs/eval-reports/data/<run-date>-standards-rechunk-clone/`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating derived-column route, read-only source, clone-only apply
② tool with tests on fixtures (idempotent, never writes the source database)
③ database copy + clone; dry run: counts of changed paths and chunks
④ apply on the clone; GPU embed time and counts recorded

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/restructure_blocks.py app/test_restructure_blocks.py`
- The tool opens the source `mode=ro` (a write attempt fails in the test)
- `--collection` explicit on every command; the first apply is `--dry-run`

**Acceptance / falsification criterion.** Clone holds re-chunked standards with chunk count and changed-text count equal to the dry run; the live collection and database are byte-unchanged (point count, sampled vectors, file hash of the live database). Falsified if the live database hash changes.

**Gates / depends on.** Depends on: CQ-12, CQ-13, CQ-14, CQ-8, CQ-11. Operator answers: F2, F3, F7. Gates: CQ-16.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) (embedder for the clone) · operator sign-off: n (no protected path is touched); operator answers: F2, F3, F7 · re-embed: y (about 35k, standards whole corpus, estimate). Also: GPU free (F3); vector store (F2); operator answer F7 on the section-path route; about 5-15 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Mixing the derived column with the stored path in later tooling. Mitigation: derived route documented in the record; nothing live changes. Rollback: delete the clone and the database copy.

**Docs to update in the same PR.** Record; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### CQ-16: Measure the standards re-chunk against baseline and decide

Labels: wave:3-gated-change, area:corpus, area:eval, needs-gpu, needs-services, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-16-standards-rechunk-verdict.md`.

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Why.** Structure fixes are only worth a live re-embed if answers improve: the gate (EV-18) is a count of structure-attributable misses, and the standards fixture is scored by the chunker-independent excerpt metric so old and new chunkers are comparable (review S-24).

**Scope.**
- In:
  - Run the standards GT on live and on the CPU-rebuilt clone, same code, excerpt metric, paired flips by stratum; plus the structural checks (furniture roots 0, stub rate under 2%, bare-number stubs 0).
- Out (explicitly):
  - Applying to the live collection (follow-on ticket on ADOPT only; needs F7).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-standards-rechunk-verdict.md`
- `docs/eval-reports/data/<run-date>-standards-rechunk-verdict/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton; rule: ADOPT only if net +3 excerpt hits on the standards set, flips at least 3:1, no stratum losing more than 1, and the structural checks pass
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ live and clone arms; MANIFEST
④ report

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command names `--collection` (live and clone separately)
- Gold chunk ids of re-chunked documents are not used for scoring

**Acceptance / falsification criterion.** Verdict applies the stated rule; edition and authority strata (n=4 each) are shown as descriptive only. Ceiling: gain bounded by the EV-18 structure-attributable miss count. Falsified if the live arm differs from EV-18's beyond the jitter envelope.

**Gates / depends on.** Depends on: CQ-15, EV-18. Operator answers: F3. Gates: CQ-18, EP-5.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 20-30 min GPU (estimate).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Gain unobservable at n=94. Mitigation: UNDERPOWERED is a verdict. Rollback: delete the clone.

**Docs to update in the same PR.** Report; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### CQ-17: Add BM25 saturation and length normalisation to the sparse arm behind a flag

Labels: wave:3-gated-change, area:corpus, area:retrieval, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-17-bm25-weighting-in-sparse-arm.md`.

**Review cross-reference:** S-25. **Wave:** W3 gated changes after baselines.

**Why.** The sparse arm is raw term frequency times IDF with no saturation or length normalisation although its docstring says 'BM25-style' (`rag/vector_index.py:112`); legacy main chunks are unbounded (8,487 chunks over 8,000 characters), so long chunks can dominate (RV-1 F-1.6). A sparse recompute is CPU-only, so bundling it with ligature repair 'to save cost' is wrong and would confound attribution (review S-25).

**Scope.**
- In:
  - Index-time weight `tf*(k1+1)/(tf + k1*(1-b+b*len/avglen))` behind an explicit option, `avglen` measured once per corpus from stored chunks (CPU) and recorded; applies only when (re)computing sparse vectors (`app.resparse` on a clone); default off.
  - Starts only after EV-22 (S-17 done).
- Out (explicitly):
  - Edge-punctuation stripping in the tokenizer (measured effect on 12-26% of tokens, but it changes tokens; include only if the operator wants it in this A/B: stated as a separate flag, never bundled). Applying to any live collection. The A/B (CQ-18).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `rag/sparse_tokens.py`
- `rag/test_sparse_tokens.py`
- `app/resparse.py`
- `app/test_resparse.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring with the formula, parameters (k1, b, avglen), the default-off guarantee and the one-recompute-per-arm rule
② failing tests: option off leaves vectors byte-identical; option on gives the expected weights on a toy corpus
③ implementation to green
④ avglen measurement helper and recorded constants per corpus

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py rag/sparse_tokens.py rag/test_sparse_tokens.py app/resparse.py app/test_resparse.py`
- Identical sparse vectors with the option off on 200 stored chunks (RQ-5 check reused)
- `conda run -n agent-rag-research python -m pytest -q rag/test_vector_index.py rag/test_sparse_tokens.py app/test_resparse.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Option off: byte-identical vectors; option on: weights match a hand-computed toy example; avglen constants recorded with the command that produced them. Falsified if default behaviour changes by one byte.

**Gates / depends on.** Depends on: EV-22, CQ-9, RQ-5. Gates: CQ-18, EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Query-side tokens stay binary while index weights change, which a later reader might misread as a bug. Mitigation: documented in the docstring. Rollback: revert; no index depends on it.

**Docs to update in the same PR.** PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### CQ-18: Run the BM25-weighting A/B on a repaired clone

Labels: wave:3-gated-change, area:corpus, area:eval, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/CQ-18-bm25-weighting-ab.md`.

**Review cross-reference:** S-25. **Wave:** W3 gated changes after baselines.

**Why.** Whether length normalisation and saturation help the sparse arm is unmeasured; a separate A/B keeps attribution clean after the ligature A/B (review S-25).

**Scope.**
- In:
  - On a fresh clone: resparse with the option on (CPU), run the standards, causal-books and papers-passage sets and the lexical strata (standards clause lookups, books terminology) against the live baseline, paired flips.
- Out (explicitly):
  - Live application (follow-on on ADOPT only). Combining with any other change.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-bm25-weighting-ab.md`
- `docs/eval-reports/data/<run-date>-bm25-weighting-ab/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton; rule: ADOPT only if net +3 items on at least one set, no set losing more than 1, and a gain on the lexical strata, else REJECT
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ clone built and resparsed; counts recorded
④ arms run; MANIFEST
⑤ report; clone deleted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command names `--collection`; the live collection is never an apply target

**Acceptance / falsification criterion.** Verdict applies the stated rule per set (never averaged); the ceiling is stated per stratum (BM25 floor from EV-15 shows where lexical headroom exists). Falsified if the baseline arm differs from EV-16/EV-18 beyond the jitter envelope.

**Gates / depends on.** Depends on: CQ-17, EV-22, EV-16, EV-18, CQ-16. Operator answers: F2, F3. Gates: RIDER-1, EP-5.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F2, F3 · re-embed: n. Also: GPU free (F3); vector store (F2); 6-8 GB for a clone.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Disk or contention; mitigations as CQ-7. Rollback: delete the clone.

**Docs to update in the same PR.** Report; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### MC-4: Slim the MCP wire by projecting duplicated envelope fields away

Labels: wave:3-gated-change, area:mcp, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/MC-4-mcp-wire-projection.md`.

**Review cross-reference:** S-26. **Wave:** W3 gated changes after baselines.

**Why.** 57-58% of a standards `semantic_search` response is envelope rather than passage (k=10 is about 4.2k tokens; a Waymo call averages about 10.8k): `bbox`, a `snippet` that lies inside `passage_text` for 94-100% of results, and repeated `paper_id`/`block_id`. Agents already lower `k` to cope (RV-4 F-4.6; review S-26).

**Scope.**
- In:
  - In `app/serve.py`, project the response with `model_dump(exclude=...)` for `bbox`, the duplicated `anchor.snippet` and the repeated `anchor.paper_id`/`citation.paper_id`; the contract objects are untouched.
  - Starts only if the operator answers F5 yes (the wire may be a projection of the frozen envelope).
- Out (explicitly):
  - Snippet-only passages by default (the logs show search-then-`get_span` verification habits). Changing `search_papers` section paths (`PaperSummaryView`, a contract change). `get_span` behaviour.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/serve.py`
- `app/test_serve.py`
- `scripts/mcp_wire_tokens.py`
- `scripts/test_mcp_wire_tokens.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the projection list and the invariant that `passage_text`, `citation` and `get_span(anchor)` round-trip are unchanged
② failing tests: projected JSON lacks the four fields; `passage_text` and `citation` equal the unprojected values; `get_span` on a projected anchor still resolves
③ implementation to green
④ token-count script (skips cleanly if the tokenizer package is absent) and measurement on standards- and Waymo-sized fixtures

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/serve.py app/test_serve.py scripts/mcp_wire_tokens.py scripts/test_mcp_wire_tokens.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_serve.py scripts/test_mcp_wire_tokens.py -o addopts="--disable-socket"`
- Token count before/after on a realistic response fixture quoted in the PR

**Acceptance / falsification criterion.** Token count of a standards k=10 response falls by at least 25% with identical `passage_text` and citation content; `get_span` still round-trips. Falsified if `passage_text` differs anywhere or the drop is under 25%.

**Gates / depends on.** Depends on: MC-3. Operator answers: F5. Gates: EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched); operator answers: F5 · re-embed: n. Also: operator answer F5 (wire as a projection of the frozen envelope).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A client that read a dropped field breaks. Mitigation: only fields no LLM can use are dropped; the dropped list is documented in the server instructions. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### RQ-3: Run the relevance-demotion arms on the focus and passage sets

Labels: wave:3-gated-change, area:retrieval, area:eval, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/RQ-3-focus-lever-ab.md`.

**Review cross-reference:** S-21. **Wave:** W3 gated changes after baselines.

**Why.** Off-topic papers cannot be kept out of an answer today. RQ-2 built a default-off demotion lever; the frozen topic-focus protocol (section 6) pre-registers its adoption rule. Whether the lever is needed at all depends on how material the baseline off-topic share is (operator question F6) (review S-21).

**Scope.**
- In:
  - Runbook step 6 (document-store route, no index change; the payload route only if pool starvation is observed): arms baseline, demote at 0.25, demote at 0.30 on the focus set and the papers-passage set, back to back (about 111 queries x 3, estimate 15 min). Record the exact flag in a dated addendum to the focus protocol before reading any number.
  - Starts only if EV-17's off-topic share exceeds the bar the operator sets (F6); if it does not, close as 'not material'.
- Out (explicitly):
  - A hard drop or filter (never, per protocol). A Config field or SearchFilters field (RIDER-1 item 1 if adopted). Writing `relevance_score` into the vector payload (follow-on only if starvation is observed).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-focus-lever-ab.md`
- `docs/eval-reports/data/<run-date>-focus-lever-ab/`
- `docs/eval-reports/2026-11-10-topic-focus-benchmark-protocol.md`

**Commits** (① is a stub, committed before any real work):
① stub: dated addendum to the focus protocol naming the exact flag and arms, committed before any arm runs
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ three arms run; MANIFEST per arm; `Coverage` pool sizes recorded
④ paired tables: off-topic share in top 10 and gold losses per set
⑤ report: ADOPT or REJECT against protocol section 6

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Both the focus set and the papers-passage set are reported separately; causal-books is the held-out control
- Every command names `--collection`, `--db-path`, `--blob-dir`

**Acceptance / falsification criterion.** ADOPT only if the protocol's rule holds: at least 50% relative drop in off-topic top-10 share with zero gold losses on papers-passage and causal-books and the legitimate-off-topic guards intact; otherwise REJECT. Ceiling: the achievable drop is bounded by the share of off-topic papers whose `relevance_score` falls below the floor (printed from the 0.923-AUROC operating points). Falsified if the baseline arm differs from EV-16/EV-17 beyond the jitter envelope.

**Gates / depends on.** Depends on: RQ-2, EV-16, EV-17, EV-22. Operator answers: F3, F6. Gates: CQ-10, RIDER-1, EP-5.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3, F6 · re-embed: n. Also: GPU free (F3); operator-set materiality bar (F6); about 15 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Demotion starves a pool that is already 40% off-topic. Mitigation: pool sizes are recorded and a starved pool is a REJECT reason. Rollback: n/a (flag only).

**Docs to update in the same PR.** Report and protocol addendum; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

### W4 rider and what it unblocks

#### EP-5: Batch BACKLOG and PROJECT-STATUS updates for waves 3 and 4

Labels: wave:4-rider, area:docs, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EP-5-status-batch-final.md`.

**Review cross-reference:** S-13. **Wave:** W4 rider and what it unblocks.

**Why.** Same reason as EP-3 and EP-4: the gated tickets land verdicts (ADOPT, REJECT, UNDERPOWERED, closed-by-gate) that belong in the ledger and in PROJECT-STATUS section 5 (tried and failed) in one pass.

**Scope.**
- In:
  - BACKLOG rows flipped with SHAs, including tickets closed by their gate ('CLOSED -- gate not met: <report>'); ledger entries; section 5 entries for each REJECT; the list of on-ADOPT follow-on tickets the operator should now commission.
- Out (explicitly):
  - Writing the follow-on tickets themselves.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/PROJECT-STATUS.md`
- `docs/BACKLOG.md`

**Commits** (① is a stub, committed before any real work):
① stub: checklist of W3/W4 tickets and their gate outcomes
② BACKLOG rows + SHAs
③ PROJECT-STATUS ledger and section 5 entries
④ follow-on list

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `git cat-file -e <sha>^{commit}` for every SHA written
- Every verdict quoted equals its report's verdict line

**Acceptance / falsification criterion.** Every W3/W4 ticket has a row stating DONE, CLOSED-by-gate or BLOCKED with its reason; no verdict text differs from its report. Falsified if any SHA fails to resolve.

**Gates / depends on.** Depends on: EP-4, RQ-3, CQ-9, CQ-11, CQ-16, CQ-17, CQ-18, MC-4, RIDER-1, RQ-4. Gates: nothing further (programme close).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Haiku; S (up to 2 h of agent work). Mechanical work, no judgement calls.

**Risk and rollback.** Low. Rollback: revert.

**Docs to update in the same PR.** This ticket is the docs obligation for waves 3 and 4.

#### RIDER-1: Raise the single foundation rider PR with only the adopted items

Labels: wave:4-rider, area:ops, area:eval, area:retrieval, needs-signoff, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/RIDER-1-foundation-signoff-rider.md`.

**Review cross-reference:** review (D), RV-5 F-5.6, RV-3 F-1.11, RV-6 F-A5, RV-1 F-1.10. **Wave:** W4 rider and what it unblocks.

**Why.** Several adopted changes can only land on protected paths (`contracts/`, `rag/config.py`, `config.example.yaml`, `rag/fakes/`, `fixtures/`, `.github/`), and every unrelated protected-path PR pays the same sign-off toll; batching them into one PR pays it once (`docs/AGENT-OPERATIONS-LESSONS.md` section 6.3). It is raised only after the wave-2 verdicts so only adopted items ride.

**Scope.**
- In:
  - (1) `Config` fields (in `contracts/config.py`, loader/defaults in `rag/config.py`, `config.example.yaml`) for whichever of `drop_stub_chunks` (EV-21), the focus lever (RQ-3) and the query-path `gpu_lock_timeout` (OP-5) were ADOPTED; none if none were.
  - (2) `relevance_filter="embedding"` fails validation until a gate exists (dead lever, RV-5 F-5.6).
  - (3) Only if EV-19's gate opened: the `rerank_score` metadata note in `contracts/retriever.py` and its DATA-CONTRACTS section M7 paragraph.
  - (4) `rag/fakes/fake_vector_store.py` imports the shared `sparse_tokens()` (RQ-5).
  - (5) Promote the three ground-truth sets to `fixtures/eval/` with one parametrised invariants test (unique ids, strata vocabulary, no gold on absent items, 6-word rule, excerpt verbatim in the live database with a skip when absent) and the SHA-256 in each set's metadata (RV-3 F-1.11), after the hash lock.
  - (6) `.github/`: a `ruff` step in CI and the nightly real-adapter workflow labelled manual-only (RV-6 F-A5).
  - Conditional item 7, present only if F7 = rewrite: DATA-CONTRACTS wording for `Block.section_path` (review S-24 sign-off need).
- Out (explicitly):
  - The `chunker_id` migration (explicitly not doing). Any logic change beyond the listed edits. Pushing to the default branch or merging (human only). Items whose verdict was REJECT or UNDERPOWERED: they drop out, the rider shrinks.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `contracts/config.py`
- `contracts/retriever.py`
- `rag/config.py`
- `config.example.yaml`
- `rag/fakes/fake_vector_store.py`
- `rag/fakes/test_fake_vector_store.py`
- `fixtures/eval/`
- `DATA-CONTRACTS.md`
- `.github/workflows/ci.yml`
- `.github/workflows/nightly-real-adapters.yml`

**Commits** (① is a stub, committed before any real work):
① stub: PR description draft listing each item, its source verdict and the operator decision it needs; empty diff
② items (4) and (5) (no verdict dependency)
③ items (1)-(3) for the adopted set only, each citing its verdict report
④ item (6) and conditional item 7
⑤ local enforcement transcript with the `foundation-change` label noted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check contracts/config.py contracts/retriever.py rag/config.py rag/fakes/fake_vector_store.py rag/fakes/test_fake_vector_store.py`
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (includes the new invariants test)
- `EV=$(mktemp) && printf '{"pull_request":{"number":0,"labels":["foundation-change"],"base":{"sha":"%s"},"head":{"sha":"%s"}}}' "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV" && GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement`
- Mutation proof for the invariants test: edit one question in a copy and watch it fail

**Acceptance / falsification criterion.** One PR only; every protected-path edit is traceable to a listed item with an ADOPT verdict or an operator decision; the invariants test passes on the three promoted sets and fails when one question is altered; the PR carries the `foundation-change` label and waits for the operator's merge. Falsified if the PR touches any protected path not listed.

**Gates / depends on.** Depends on: EV-11, EV-18, EV-19, EV-20, EV-21, RQ-3, RQ-5, OP-5, CQ-18. Operator answers: F4, F7. Gates: RQ-4, EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: y: this ticket IS the sign-off request; the operator merges (never an agent); operator answers: F4, F7 · re-embed: n. Also: operator sign-off and merge; push of the local commits so CI can judge them (F4).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A broad rider is slow to review. Mitigation: items with no adopted verdict are omitted, so it can be small. A wrong Config default could change serving: all new fields default to current behaviour. Rollback: revert the merge (single PR).

**Docs to update in the same PR.** DATA-CONTRACTS section M7 paragraph for item (3) (in this PR); PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

#### RQ-4: Expose the cross-encoder score in result metadata

Labels: wave:4-rider, area:retrieval, area:mcp, needs-signoff, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/RQ-4-expose-rerank-score-metadata.md`.

**Review cross-reference:** S-20. **Wave:** W4 rider and what it unblocks.

**Why.** Only if the census (EV-19) shows the reranker score separates answerable from absent: callers today get the fusion score, which carries no absolute relevance, so no abstention or focus signal can be built on it (review item a; RV-4 F-4.1). `GroundedResult.metadata` is the contract-reserved slot, so populating it is the rider's act.

**Scope.**
- In:
  - After the rider note merges: populate `metadata["rerank_score"]` from the experiment-only `rerank_scored()` path (promoted to the normal rerank path), keep `score` exactly as it is.
- Out (explicitly):
  - Changing `score` semantics. Building a floor or abstention from it (needs 60 or more distinct absent items and a pre-registered falsifier; RV-3 F-1.10).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/retriever.py`
- `rag/test_retriever.py`
- `rag/reranker.py`
- `rag/test_reranker.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating `metadata['rerank_score']` and that `score` is unchanged
② failing tests: metadata present and equal to the reranker score; `score` and order unchanged on the fake
③ implementation to green
④ docs line for DATA-CONTRACTS section M7 cross-checked against the rider's wording

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/retriever.py rag/test_retriever.py rag/reranker.py rag/test_reranker.py`
- Existing retriever and reranker tests unchanged and green
- Identity check: result order and `score` byte-equal to the pre-change commit on the fake

**Acceptance / falsification criterion.** Metadata carries the reranker score; `score`, order and `passage_text` are byte-identical to before on the fake; the EV-16 rows reproduced on a small live sample match order exactly. Falsified if any order or `score` differs.

**Gates / depends on.** Depends on: RIDER-1, EV-19, RQ-1. Gates: EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: y: blocked by RIDER-1 item 3 (contract note) merging · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A caller treating the new field as calibrated confidence. Mitigation: the contract note says 'uncalibrated rank-order score'. Rollback: revert.

**Docs to update in the same PR.** DATA-CONTRACTS section M7 via the rider; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.

## 9. Will not do, and why

So nobody re-proposes these without the stated condition.

| proposal (source) | reason | would be reopened by |
|---|---|---|
| Full main-corpus re-chunk (RV-2 F-2.3 option) | About 1.35M embeds, about 13.8 GB of vectors against 4.1 GB today on a disk with 91 GB free, and about 700 fixture references broken. | Only the paired old-vs-new chunker test of the review's rule (d)(3) (66 papers, two scratch collections, about 45k embeds, at least +5 net excerpt hits, flips at least 3:1, 2x disk headroom) can justify it. |
| Content-addressed chunk ids (RV-2 F-2.3 step 2) | Touches the frozen IDs spine and rewrites fixtures. The excerpt metric (EV-8) removes the main reason. | A re-chunk that must preserve ids across chunkers. |
| `chunker_id` payload stamp and migration (RV-2 F-2.2) | No ingest is planned. `docs/CORPORA.md` plus the no-ingest rule (EP-6) carry the same fact at zero schema cost. | Before the next ingest into a mixed collection. |
| Dense-side ligature repair and a 129k re-embed (RV-2 F-2.9) | No evidence the dense arm suffers (subword tokenizer); repaired excerpts would diverge from `get_span`. | EV-22 shows a sparse gain and dense-only misses on damaged gold. |
| Harvest lexical gate, attribution table, stop-loss, `paper_topic` migration (RV-5 F-5.2, F-5.3, F-5.5) | Supply is exhausted (BACKLOG O-1), no harvest is scheduled, the operator keeps the mix, labels are in git. | Build the gate together with the next harvest. |
| arXiv contamination curl (RV-5 F-5.1) | Settles a cause that matters only to a future harvest. | A harvest is scheduled. |
| `relevance_score` max-cos recompute, version refresh, quarantine cleanup, duplicates (RV-5 F-5.4, F-5.8, F-5.9, F-5.10) | Low decision value; only a stratifier reads these and the labels already serve it. | None stated. |
| `reindex_idf` default flip and snapshot checks (RV-6 F-A6) | IDF is already applied on all five collections, so the tool is a no-op everywhere. Mark the tool historical. | A new collection built without the IDF modifier. |
| Judge determinism and repeats (RV-3 F-1.9); different-family GT read (F-1.8) | No answer-level claim is on the table; the retrieval work does not depend on them. | Before any groundedness number is quoted. |
| Persist `content_list` and table HTML; GROBID persist/remove (RV-2 F-2.4, F-2.12) | No parse is planned. | In the same ticket as the next parse. |
| MCP-E1 find-similar, MCP-E4 taxonomy, federation (RV-4 F-4.10, F-4.4) | Zero log evidence (2 `scan_methods` calls in 1,198). | MC-3 telemetry shows more than 30% of hand-written scan patterns are alias-style alternations of one method (E4), or find-similar demand appears (E1). |
| Self-hosted CI runner (RV-6 F-A5) | An always-on cost on a GPU workstation; manual-only and documented is enough (RIDER-1 item 6). | None stated. |
| `_normalize_text` per-corpus table (RV-2 F-2.8) | 23 blocks affected; only the regex guard is worth doing and it is folded into CQ-14. | None stated. |

Also not done, by operator decision: removing the off-topic papers; any GPU work before F3; any protected-path edit outside RIDER-1.

## 10. Traceability

Every review item maps to a ticket, to 'folded into', or to 'not doing'.

| review item | claim | ticket(s) / disposition |
|---|---|---|
| S-01 | No backup since 07-30, none off-device | OP-4 (snapshot now), OP-3 (quick_check + checksums). Off-device copy and deletions: no ticket until a target exists (F1) |
| S-02 | Eval inputs not frozen | Folded into EV-5 (done: run scripts verify hashes, no run-time fixture rewrite, run from the worktree under test, point-count guard, protocols and addenda, title-ablation tool); residual EV-7 (required `--collection`, hash in report, gold-id preflight); EV-15 (BM25 floor, the 'EV-5b' of the protocols) |
| CQ-5 follow-up | 38 more authority and 38 more edition items (CQ-5 report section 5) | CQ-19, CQ-20 |
| S-03 | Chunk-identity scoring ignores alternatives | EV-8 (excerpt metric), EV-11 (alternatives recorded, hashes re-frozen) |
| S-04 | Cross-encoder score never captured | EV-13 (capture + census tool), EV-19 (the run) |
| S-05 | CQ-3 pre-registration wrong fixtures, no minimum effect | EV-12 (addendum); EV-9 (chunk ids in rows, enabler) |
| S-06 | GPU contention unnamed and slow to fail | OP-5 (holder file, 20 s query path, doctor), EV-10 (eval invalid on lock timeout) |
| S-07 | Wrong-corpus guards cover one path | OP-6 (helper, tools, doctor, status fallback), OP-2 (the two serve call sites) |
| S-08 | Unknown paper_id returns empty | MC-1 |
| S-09 | Three one-line retrieval defects | RQ-1 |
| S-10 | Cold agent cannot see filters/corpus | MC-2 |
| S-11 | Telemetry blind on scan/get tools | MC-3 |
| S-12 | Containers not reproducible | OP-7 |
| S-13 | Docs drift, chunker provenance, Decision 1 | EP-1 (done: PROJECT-STATUS, README, AGENTS rows); EP-2 itself (BACKLOG rows 1, 5, 6, 17, 18, B-5 corrections, as allowed by the coordinator); EP-6 (CORPORA.md, DECISIONS-PENDING, HANDOFF, precision-95 plan rows, no-ingest rule); EP-7 (RUNBOOK sections, row 22) |
| S-14 | rechunk re-embeds unchanged text | CQ-8 |
| S-15 | Filtered dense search without payload indexes | EV-14 |
| S-16 | No baselines, reranker score untested | EV-16 (main), EV-17 (focus), EV-18 (standards), EV-19 (census); TEI `/info` check folded into EV-16 |
| S-17 | Ligature repair in sparse arm | CQ-7 (CPU clone), EV-22 (A/B, stratified by damaged vs clean gold) |
| S-18 | Stub filter | EV-21 |
| S-19 | Depth and weight per corpus | EV-20 |
| S-20 | Expose cross-encoder score | RQ-4 (after RIDER-1 item 3), gate = EV-19 |
| S-21 | Focus lever: post-rerank demotion | RQ-2 (build, default off), RQ-3 (A/B and verdict), RIDER-1 item 1 |
| S-22 | Payload indexes on live collections | CQ-9 (clone and verdict; live application is an on-ADOPT follow-on), gate = EV-14 |
| S-23 | Bounded re-chunk of oversized main papers | Re-scoped after CQ-4 (done): CQ-10 (assess raising the embedder token limit), CQ-11 (decision: limit change, or truncation fix only inside a planned full re-chunk). The targeted re-chunk tickets were dropped because CQ-4 priced it at about 177k-212k embeddings |
| S-24 | Standards structure bundle | CQ-12 (tracker + golden tests), CQ-13 (furniture pre-pass, table sup/sub/spans), CQ-14 (stub folding, regex guard), CQ-15 (re-derive + clone re-chunk), CQ-16 (verdict); gate counted in EV-18; F7 |
| S-25 | BM25 saturation and length normalisation | CQ-17 (flag-gated implementation), CQ-18 (A/B) |
| S-26 | Envelope slimming on the MCP wire | MC-4 (gate F5) |
| (D) | Single foundation rider | RIDER-1 (items 1 to 6; conditional item 7 for F7) |
| (E) | Not worth doing | Section 9 'Will not do' table; no ticket |
| (F) | Open operator questions | Section 3, each linked to the tickets it blocks |

Lane findings and review adjudications kept by the synthesis:

| finding | disposition |
|---|---|
| Review 1a (score discarded, RV-1 F-1.1, RV-4 F-4.1) | EV-13, EV-19, RQ-4 (=S-04, S-20) |
| Review 1b (no payload index, RV-1 F-1.2) | EV-14, CQ-9 (=S-15, S-22) |
| Review 1c (`_SectionTracker`, RV-2 F-2.1) | CQ-12 to CQ-16 (=S-24); flat books (D5) not fixable by the tracker and not ticketed (needs the PDF outline join, RV-2 F-2.11, not carried) |
| Review 1d (patches vs re-chunk rule, RV-2 F-2.2/F-2.3) | Rule applied in CQ-10/CQ-11 (after CQ-4) and CQ-8 (text-hash reuse); full re-chunk and `chunker_id` in section 9; no-ingest rule in EP-6 |
| Review 1e (saturation, run-time fixture rewrite, wrong checkout; RV-3 F-1.3, F-1.4) | EV-5 (done), EV-7, EV-15, EV-8, EV-11; passage-level headline and title-ablated arm are in the frozen protocols (EV-5) |
| Review 1f (contamination cause, RV-5 F-5.1) | Section 9 (arXiv curl); the lexical gate is built with the next harvest |
| Review 1g (backups, RV-6 F-A1) | OP-4, OP-3 |
| Review 1h (CQ-1 hazard refuted as regression) | No ticket for the refuted part. Residual risk 1 (ingest into a live collection mixes chunkers/sparse versions): EP-6 no-ingest rule. Residual risk 2 (fake tokenizer): RQ-5 and RIDER-1 item 4 |
| Review 'other claims': RV-4 F-4.2 | MC-1 |
| RV-1 F-1.3 shared anchors (confirmed) | Folded into EV-8 (excerpt metric removes the anchor-equality blind spot) and EV-9 (chunk ids). The member-block (QW-1 Variant A) helper must treat fragments; QW-1 remains parked on T-F7 and is not part of this programme |
| RV-1 F-1.9 300 s lock wait, RV-6 F-A3, F-A8 | OP-5, EV-10 |
| RV-3 F-1.2 `--collection` default | EV-7 |
| RV-1 F-1.11 critique of CQ-3 (refuted) | No action. CQ-3 overfetches and stops once the pool is full |
| RV-6 F-A6 / Decision 1 (refuted as open) | EP-6 closes Decision 1 with the config evidence; `reindex_idf` default flip in section 9 |
| RV-5 foundation-protection notes; F-5.5 (refuted) | RIDER-1 item 2 carries the real protected change (`relevance_filter`); labels are in git, so no ticket |
| RV-5 F-5.6 inert config | RIDER-1 item 2 |
| RV-3 F-1.11 promotion of the three sets | RIDER-1 item 5 |
| RV-6 F-A5 CI (ruff step, nightly manual-only, push) | RIDER-1 item 6; push is operator question F4. Self-hosted runner: section 9 |
| RV-3 F-1.14 ligature stratification | EV-22 |
| RV-3 F-1.10 abstention minimum data | EV-19 (census only); no MCP wiring is proposed anywhere in this programme |
| RV-2 F-2.5 / F-2.6 / F-2.8 (a) / F-2.10 | CQ-13, CQ-14 (regex guard), CQ-13 (table sup/sub/spans), CQ-14 (stub folding) |
| RV-4 F-4.3, F-4.4 | MC-2 |
| RV-4 F-4.5 | MC-3 |
| RV-4 F-4.6 | MC-4 |
| RV-4 F-4.11 | RQ-1 |
| RV-1 F-1.4 (focus lever options) | RQ-2, RQ-3 (option A only); option B payload route only if RQ-3 sees starvation; C blending and D collection split rejected by the review's reasoning and the operator decision |
| RV-1 F-1.5 (depth/weight) | EV-20 |
| RV-1 F-1.6 (BM25 weighting) | CQ-17, CQ-18 |
| RV-1 F-1.7, F-1.8 #7 | RQ-1 |
| RV-1 F-1.10 shared tokenizer | RQ-5, RIDER-1 item 4 |
| RV-6 F-A2 | OP-7 |
| RV-6 B.1 punch list rows 1-23 | EP-1 (PROJECT-STATUS, README, AGENTS rows, done), EP-2 (BACKLOG rows), EP-6 (HANDOFF, DECISIONS-PENDING, precision-95 plan), EP-7 (RUNBOOK) |
| Review section 2: CQ-1 'no test pins the map checksum' | RQ-5 (checksum test) |
| Review section 2: OP-1 covers only 'TEI down' | OP-5 |
| Review section 2: EV-6 'not reviewed by any lane' | Not ticketed; its first exercise is EV-16, where every strata number is cross-checked against the raw report (stated in EV-16's acceptance via the validity checks) |

Lane findings the synthesis neither ranked nor rejected. They are NOT silently dropped: they are listed here as unplaced, with no ticket, and reported to the operator as a decision (a second review pass or explicit rejection):

| finding | note |
|---|---|
| RV-3 F-1.1 one-command regression gate (manifest + `--baseline`) | Not carried by the synthesis. Candidate after the first baselines exist (the stored baselines from EV-16/18 are its input). |
| RV-3 F-1.6 question-style realism controls (logged-query comparison, human 30-item slice, keywordised arm) | Not carried. The protocols already report the title-ablated arm; the realism slice needs operator time. |
| RV-3 F-1.12 chapter-level is a heading-string match (caveat) | Not carried; one-line docs caveat, can ride EV-11 if the operator asks. |
| RV-2 F-2.7 front/back-matter role classifier and payload tag | Not carried. Revisit if EV-21 shows reference/TOC chunks occupying top-10 slots. |
| RV-2 F-2.11 books outline join for chapter paths | Not carried (12.5k chunks, GPU re-embed). Needed to fix flat books; CQ-12 explicitly does not. |
| RV-2 F-2.13 chunks over 3,500 characters metric in `scripts/truncation_census.py` | Not carried (low). |
| RV-4 F-4.7 `get_section` clause-prefix match, `scan_corpus` `section_pattern` | Not carried; the logs show 4 clause references in 242 queries. Reopen on MC-3 telemetry. |
| RV-4 F-4.9 error text without absolute path, nearest-id hints, async tool wrappers | Not carried (low). |
| RV-4 F-4.10 reorder BACKLOG MCP-E rows | Not carried as a ticket; the evidence ranking is recorded in section 9 (MCP-E1, E4 not doing). |
| RV-6 F-A7 pre-migration snapshot guard, `busy_timeout`, `quick_check` on snapshot | Only the `quick_check` part is carried (OP-3). The migration guard and `busy_timeout` are not. |
| RV-6 F-A9 canary eval slice and usage-log top-score columns | Not carried. |
| RV-6 F-A10 dashboard bind default, doctor disk check on cwd only, `.phase0-data` naming | Not carried (low). |
| RV-5 F-5.7 on-topic supply understated; F-5.11 other corpora not rebuildable from tracked files; F-5.12 first-seed runs not reproducible | Not carried. |
| RV-1 F-1.12 per-paper diversity default | Not carried (no change recommended by the lane). |

## 11. Self-review

- **Counts.** 51 tickets: W1 28, W2 8, W3 12, W4 3.
- **File-ownership conflicts checked** by a throwaway script over every pair of tickets in the same wave without a dependency path between them: none share an `Owns` path. Conflicts found and resolved by sequencing: `app/retrieval_eval.py` (EV-7, EV-8, EV-9, EV-10, RQ-2 chain); `rag/vector_index.py` (RQ-1, RQ-5, EV-14; CQ-9, CQ-17); `rag/reranker.py` (RQ-1, EV-13); `rag/retriever.py` (RQ-1, RQ-2); `app/serve.py` (MC-2, MC-3, OP-2); `app/assembly.py`, `app/doctor.py`, `app/snapshot.py` (OP-3, OP-6, OP-5, OP-2); `rag/parser.py` (CQ-12, CQ-13); the fixture hash file (EV-11, CQ-19, CQ-20; also shared with in-progress EV-4: key-disjoint edits, EV-4 merges first). Review items that touched the same file were split to make this possible (S-06 into OP-5 and EV-10; S-07 into OP-6 and OP-2).
- **Every ticket has a falsifier**: each acceptance line contains an explicit 'Falsified if' clause (checked mechanically).
- **What would falsify this plan's structure.** (a) If the baselines show the new sets saturated even at passage level with the title-ablated arm high, every gated change auto-REJECTs and the programme's value is the instruments: the structure absorbs it because each change is a per-ticket verdict. (b) If a W1 chain produces merge conflicts anyway, the ownership partition is wrong and the shared-file list must be re-cut. (c) If the first run shows `run_valid: false` from lock contention, the cheapest-first serialization is not enough and a scheduler (rejected here) comes back. (d) If EV-14 finds overlap of at least 0.99, CQ-9 and CQ-17's dependency on it vanish cleanly.
- **Deviations to confirm.** (1) Docs batching (rule 13) departs from AGENT-PROCEDURES section B's same-PR ledger rule. (2) Review S-19 says reset unsupported per-corpus defaults to 32/0.5; the frozen runbook rule G-1 says defaults stay; EV-20 follows G-1 unless the operator says otherwise. (3) After CQ-4 the review's S-23 targeted re-chunk was re-scoped to a token-limit assessment (CQ-10) and a decision note (CQ-11). (4) RQ-5 has no S-nn: it is the prerequisite for rider item 4. (5) RQ-2 builds the default-off demotion in wave 1, although the review lists S-21 as gated: only its adoption is gated; the build is reversible and keeps the first GPU day from being wasted. (6) Wording: 'sign-off' for non-protected paths means a decision in PR review, not RIDER-1.
- **Three weakest points, stated honestly.** (1) *One GPU session carries the value.* Every quality question sits behind a single serialized session that is blocked by a process this programme does not control (F3); if it slips, W2 and W3 do nothing and only the instruments and fixes land. (2) *Statistical power.* With n of 61-128 and strata of 4-26, even a clean win is hard to call; the plan deals with that by pre-registered minimum effects and an UNDERPOWERED verdict, but it cannot create power. The authority and edition strata stay descriptive until CQ-19/CQ-20 land. (3) *Serial chains and untested estimates.* W1 is chain-bound on `retrieval_eval.py`, `serve.py` and `assembly.py`, so wall time is longer than the ticket count suggests; GPU durations and sizes are estimates; and the docs batching exception adds a dependency on three Haiku tickets that could fall behind.
- **Scope discipline.** No MCP confidence wiring, no corpus deletion, no full re-chunk, no harvest changes, no schema migration. Review items outside the ranked groups are listed as unplaced in section 10, not smuggled in.
- **Dispatch survival encoded:** stub-first commits in every ticket including docs tickets; detached runs with MANIFEST committed at launch; death verified through git; one worktree per dispatch; no `pkill -f`.
