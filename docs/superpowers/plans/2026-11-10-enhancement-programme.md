# The enhancement programme: instruments first, measurements second, gated changes last

Written 2026-11-10, before execution (house rule from the precision-95 and next-build programmes: the wave map exists so dependencies are decided before dispatch). Primary input: the adjudicated system review `docs/eval-reports/2026-11-10-system-review.md` and its six lane reports. **This document plans; it does not implement.** Every number is cited to its source report. Where something is unknown or not commissioned, it says so.

**Revision 2026-11-11 (EP-2b).** The operator approved in full the minimizer verdicts in `docs/eval-reports/2026-11-10-ticket-set-minimizer.md`. The original 51 tickets are now **22 active and 21 parked** (KEEP 10, SHRINK 12, DEFER 20, MERGE 7, CUT 2; plus one new ticket, EV-6b; one SHRINK, CQ-13, is placed in the parked section because it hard-depends on a parked ticket, see section 11). ACTIVE tickets are the list proposed for posting as GitHub issues; PARKED tickets stay in the plan behind a checkable trigger and are not to be started or posted unless the operator asks. The issue bodies, one file per ticket (parked ones in `parked/`), are in `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/` with `INDEX.md`; nothing has been posted to GitHub.

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
3. **What this programme does NOT promise:** no retrieval improvement has been measured for anything, and none is promised. No precision-0.95 or abstention claim (the P0-2 ratification is unsigned, F8). No deletion of the off-topic papers. No full re-chunk. No MCP wiring of any confidence signal (it would need at least 60 distinct real absent items). The ground-truth sets are LLM-authored, same-family verified, with questions about twice as long as real queries and title tokens carrying 11-16 points of paper recall; the authority and edition strata (n=4) stay descriptive: the 38-item extensions are parked (CQ-19) behind a baseline result.
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
| F1 | Backups: is there any device or remote for an off-disk copy (the only other disk is the photo project's read-only source)? After a fresh verified snapshot, may the five July `.bak` files (6.4 GB), the 07-28 `.partial`, and two of the three July snapshots be deleted? | the off-device copy and the deletions only (no ticket exists for them: no off-device tooling until a target exists, section 9); the snapshot itself is not blocked and OP-4 is in progress |
| F2 | May the vector store (CPU container only) be started for clone measurements? Each clone needs about 6-8 GB of the 91 GB free. | EV-14 (active); parked CQ-7, CQ-9, CQ-16, CQ-18 |
| F3 | Who owns the wedged foreign model process holding 18.6 GB of VRAM, and may it be stopped? It is what blocks the GPU. | EV-16, EV-17, EV-18 and EV-20, and every parked GPU ticket (EV-19, EV-21, EV-22, RQ-3, CQ-16, CQ-18) |
| F4 | Push the local commits (67 at review time) so CI judges them: yes or no? | RIDER-1 (a CI verdict on the rider, and its ruff step); every 'CI passes' claim in this plan is local until then |
| F5 | May the MCP wire be a projection of the frozen envelope (drop `bbox` and the duplicated `snippet`/`paper_id`)? | MC-4 (parked) |
| F6 | Focus lever: is 'demote, never drop, opt-in' the only acceptable form? What off-topic share in the top 10 counts as material? | parked RQ-2 and RQ-3 (start only above the bar), EV-17 (reports the number, does not set the bar) |
| F7 | If the standards structure gate passes, may stored `Block.section_path` be rewritten for standards (and a 35k re-embed run), or must the corrected path live in a derived column? | parked CQ-16 (default is the derived column until answered) |
| F8 | P0-2 metric ratification: sign it, or retire it in favour of the EV-5 protocols and EV-7/EV-8 addenda? | Any headline quoted from wave-2 reports (they cite the EV-5 protocols, never P0-2, until answered); the answer is recorded in EV-16's ledger entry |

Programme-embedded decisions that are NOT blocking questions (the operator decides them in PR review of the named ticket): the Qdrant version pin (OP-7), the standards protocol addendum (EV-11), whether unsupported per-corpus defaults are reset to 32/0.5 as the review says or stay as frozen rule G-1 says (EV-20; G-1 wins, section 9), and, for parked tickets, the amended CQ-3 ADOPT rule (EV-12), the bare-clause-number folding rule (CQ-14), the 20 s query-path lock timeout (deferred out of OP-5, section 9) and applying any adopted index change to a live collection (follow-on tickets, written only on ADOPT).

## 4. Execution model and global constraints

One orchestrator plus dispatched subagents plus detached measurement processes (`docs/AGENT-OPERATIONS-LESSONS.md`). The orchestrator writes briefs from the ticket entries below, dispatches, verifies artifacts against git, merges lanes into the integration branch and owns integration. It never implements a ticket. Tier rule: Haiku for mechanical work (OP-4), Sonnet for logic and authoring (everything else), Opus only for hard design adjudication with a one-line justification (none needed so far).

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
13. **Documentation is paid in the same PR (no batch tickets).** `docs/AGENT-PROCEDURES.md` section B makes the BACKLOG row flip, the PROJECT-STATUS section 3 ledger entry and the section 7 doc-map row (and the section 2 entry-point row for a new flag) same-PR, non-deferrable obligations. The earlier batching exception (tickets EP-3, EP-4, EP-5) is withdrawn on the minimizer's reasons: it recreated the failure section B exists to prevent, W2 is GPU-serial so there is nothing to batch around, and the batch tickets fanned in 27 dependencies. Every active ticket therefore lists these obligations in its 'Docs to update in the same PR' field. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files and are deliberately NOT in any ticket's `Owns`; the orchestrator resolves append conflicts when it merges each ticket into the integration branch. Doc supersession banners are done in the superseding PR.
14. **Measurement runs are detached processes** (`setsid`, LESSONS 7.3, 8.1), one GPU job at a time, cheapest first (LESSONS 9.1); liveness is a `/proc` scan, never `$!`; a stuck holder is found with `fuser` on the lock and killed by exact pid after checking its working directory; never `pkill -f`. Confirm artifacts through git, not by listing someone else's tree.
15. **Brief hygiene** (LESSONS section 5): each brief states the rejected alternative and why, invites disagreement ('if you think this is wrong, say why and do not change it'), names the reuse target or demands the search that justifies new code, prefers one fix at a shared choke point, and gives the failure mode, not just the requirement. Baselines ('N passed') are re-read from the ticket's own merge base at dispatch time.
16. **Pre-baseline rule.** No ticket may change retrieval, ranking, index or server start-up behaviour (even default-off) before the baseline commit is frozen, unless this plan lists it as a baseline-path exception with its reason. The baseline is the reference for everything: only instrument fixes and read-only or diagnostic changes may precede it; any behaviour-touching change lands after the last baseline (EV-18 merged) and is verified against the real baseline rows. The exception list and the check of the active set are in section 6.4. At the freeze, any listed exception not yet merged is held, not merged, until the EV-18 report is merged. The parked behaviour-touching tickets (RQ-1, RQ-2, RQ-5, EV-13, OP-2, CQ-9, CQ-18, MC-4) are barred by their triggers anyway; RQ-1 is explicitly the first post-baseline change.
17. **Baseline commit freeze.** EV-16's first commit records the integration-branch head as `baseline_commit`; EV-16, EV-17 and EV-18 run from a worktree checked out at exactly that SHA and write it into every MANIFEST and every run's output; a report whose recorded SHA differs from the code that ran is discarded. This is a step of the baseline tickets, not a separate ticket.

## 5. Ticket ID scheme

`EP-n` programme and housekeeping (the EP-3/EP-4/EP-5 batch tickets are dropped; EP-2b applied the minimizer verdicts); in-progress repair tickets carry a letter suffix (`EV-4b`, the repair of the merged focus ground truth; `EV-6b`, the review of the strata report script); `EV-n` evaluation instruments and measurements; `CQ-n` corpus and index quality; `RQ-n` retrieval quality and focus; `MC-n` MCP surface; `OP-n` operations; `RIDER-1` the single sign-off batch. Numbering continues after the IDs used on 2026-11-10 (EP-0..EP-2, EV-1..EV-6, CQ-1..CQ-6, OP-1); OP-2 is the lazy vector-index construction reserved by OP-1's notes. The review's `S-nn` id is kept in each ticket as 'Review cross-reference'. Waves: W1 do now without GPU (some tickets need the vector store on CPU), W2 first GPU session, W3 gated changes, W4 rider and what it unblocks. Branches: `EP-<ID without hyphen>-<slug>`, e.g. `EP-OP2-lazy-vector-index-construction`. Labels on issues come from a closed set (`wave:*`, `area:*`, `needs-gpu`, `needs-signoff`, `needs-services`, `size:S|M`, and `parked`, used on parked issue files only). Sizes: S up to 2 h of agent work, M up to 1 day; nothing is larger (anything that was larger was split, section 11).

## 6. Wave map and critical path

### 6.1 Minimal critical path to a trustworthy first baseline (the minimizer's order, numbered)

Not tickets, and first: (a) EV-4b (in progress) repairs the merged focus ground truth and re-freezes its hash, so EV-17 has a valid fixture; (b) the operator answers F3 (the GPU). OP-4 (a fresh main-corpus snapshot) is urgent but independent of the baseline: the orchestrator is running it now, outside the programme queue, and it is not waited for.

1. **EV-7** Require `--collection`, stamp the fixture hash, preflight gold ids (`app/retrieval_eval.py` only).
2. **EV-8** Excerpt-containment passage metric.
3. **EV-9** Chunk ids in eval rows (shrunk to the additive row field).
4. **EV-10** Mark an eval run invalid on a GPU lock timeout.
5. **EV-11** Record the three alternatives, re-freeze the fixture hashes (in parallel with 1-4 once EV-8 has landed; the hash file is shared with EV-4b, keys disjoint).
6. **EV-15** BM25 floor script (no dependencies; parallel anywhere).
7. **EV-6b** Dry-run and independently review `scripts/eval_strata_report.py` against a hand-computed example (inserted by the operator's instruction: the minimizer found the script unreviewed although every headline number passes through it and proposed folding the dry run into EV-8; a separate ticket gives an independent reviewer and runs after EV-9 has made the row format final).
8. **Freeze the baseline commit** (a step inside EV-16's commit 1, not a separate ticket): record the integration head SHA as `baseline_commit` and write it into every run's output.
9. **EV-16** Main-corpus baselines (papers, books, legacy), including the one TEI `/info` truncation check.
10. **EV-17** Focus baseline (needs EV-4b's re-frozen hash and EV-16's slot).
11. **EV-18** Standards baseline and the structure-gate count.

**Combination decision for items 1-4.** EV-7, EV-8, EV-9 and EV-10 all own `app/retrieval_eval.py` and `app/test_retrieval_eval.py`, so they serialise whatever is done. They stay **four tickets explicitly chained** (EV-7 -> EV-8 -> EV-9 -> EV-10) but are delivered as **one branch and one PR** (`EP-EV7-eval-entrypoint-bundle`), with a commit group per ticket, dispatched as two sequential briefs of two tickets each (EV-7 + EV-8, then EV-9 + EV-10, which respects global rule 2, two items per brief). Why chained tickets and not one ticket: each keeps its own acceptance criterion, falsifier and traceability row and the operator can strike one; why one PR: four separate branches over the same file would merge-conflict in sequence and the instrument changes belong to one review. The EV-9 -> EV-10 edge is an ordering edge only, not a data dependency.

Tickets that are not on this path and must not gate EV-16: OP-3, OP-5, OP-6, OP-7, MC-1, MC-2, MC-3, EP-6, EV-14 (hygiene; fine to run in parallel agent capacity, but under rule 16 any that touch the baseline path are merged before the freeze or held until EV-18 is merged). EV-20 runs after EV-18 and only if its headroom gate holds.

### 6.2 Wave map (active set only)

```
W0  done / in progress (section 7)   EP-0 EV-1..3 EV-5 EV-6 CQ-1..6 OP-1 EP-1 RV-1..6 RV-S | EV-4 merged, needs repair: EV-4b IN PROGRESS | OP-4 IN PROGRESS (orchestrator)

W1  no GPU                                                       (operator answer: F2 for EV-14; F1 only for off-device copy)
 eval bundle   EV-7 -> EV-8 -> EV-9 -> EV-10          one branch, one PR (section 6.1)
 eval          EV-8 -> EV-11 (EV-4b merge order)      EV-15 (no deps)       EV-9 -> EV-6b
 retr (RO)     EV-14* (read-only, live collection)
 ops           OP-4 (now)      OP-3 -> OP-6 -> OP-5 -> OP-7 (RUNBOOK commit last; ordering edges)
 mcp           MC-1 -> MC-2 -> MC-3                   (hygiene, not a gate of EV-16)
 docs          EP-6
               (* = needs the vector store up on CPU, F2)

               [ freeze baseline_commit: step of EV-16 ]
W2  first GPU session, measurements only, one job at a time, cheapest first (F3)
 EV-7,8,9,10,11,15,6b --> EV-16 --> EV-18 --> EV-20 (only if headroom)        EV-17 (focus; after EV-16's slot, needs EV-4b)

W3  gated changes: nothing active. Every W3 ticket is parked (section 8A).

W4  EV-11, EV-18 --> RIDER-1 (items 5, 2, 6 only; F4)
```

### 6.3 Dependency edges, exhaustive for the ACTIVE set

`A -> B` means B needs A. '(ordering)' edges exist only because both tickets own the same file; they carry no data. GPU-serial edges only order jobs on the single card. No active ticket depends on a parked ticket (checked mechanically, section 11).

**W1 do now, no GPU** (edges whose target is in this wave): OP-3 -> OP-6 (ordering); OP-6 -> OP-5 (ordering); OP-5 -> OP-7 (ordering); MC-1 -> MC-2 (ordering); MC-2 -> MC-3 (ordering); EV-7 -> EV-8 (ordering); EV-8 -> EV-9 (ordering); EV-9 -> EV-10 (ordering); EV-8 -> EV-11; EV-9 -> EV-6b

**W2 first GPU session** (edges whose target is in this wave): EV-7 -> EV-16; EV-8 -> EV-16; EV-9 -> EV-16; EV-10 -> EV-16; EV-11 -> EV-16; EV-15 -> EV-16; EV-6b -> EV-16; EV-16 -> EV-17 (GPU-serial order and shared baseline commit); EV-16 -> EV-18 (GPU-serial order and shared baseline commit); EV-9 -> EV-18; EV-11 -> EV-18; EV-15 -> EV-18; EV-16 -> EV-20; EV-18 -> EV-20

**W3**: no active tickets.

**W4 rider**: EV-11 -> RIDER-1; EV-18 -> RIDER-1

**External inputs and operator answers:** EV-14 <- F2; EV-11 <- EV-4b; EV-16 <- F3; EV-17 <- EV-4b; EV-17 <- F3; EV-18 <- F3; EV-20 <- F3; RIDER-1 <- F4. OP-4 has no operator dependency (F1 only blocks the off-device copy and deletions, which have no ticket).

Parked tickets' own edges are listed inside each parked ticket (section 8A). If an active ticket is later found to need a parked one, that is reported, not wired silently.

### 6.4 Pre-baseline rule: check of the active set (rule 16)

| ticket | what it touches | verdict |
|---|---|---|
| EV-7, EV-8, EV-9, EV-10 | the eval harness `app/retrieval_eval.py` (instrument) | allowed: instrument fixes; baseline prerequisites (EV-7 gold preflight, EV-8 metric, EV-9 chunk ids needed by EV-18's gate count, EV-10 validity) |
| EV-11, EV-15, EV-6b | fixtures hash file, BM25 script, strata script | allowed: instrument; baseline prerequisites |
| OP-3, OP-4, OP-7, EP-6 | snapshot tool, a snapshot record, a compose file, docs | allowed: not retrieval, ranking, index or serve start-up |
| OP-6 | doctor, snapshot, integrity tool guards | allowed: none is on the retrieval path or in `app/serve.py` start-up |
| MC-1 | `McpServer.semantic_search` raises on an unknown `paper_id` | **listed exception**: new failure mode on the path the harness measures through `build_mcp_server`; results for valid ids are unchanged and EV-7's preflight guarantees every fixture gold id resolves. Merged before the freeze or held until EV-18 |
| MC-2 | server instructions generated at start-up from `corpus_stats()` | **listed exception**: changes start-up output only, no retrieval path; same hold rule |
| MC-3 | usage-log bindings for scan and get tools | **listed exception**: logging only; same hold rule |
| OP-5 | `FileGpuLock` writes a holder file on acquire (also on the eval path), doctor listing | **listed exception**: best effort, removed on release, no result changes; the 20 s timeout that would have changed behaviour is cut; same hold rule |
| EV-14 | maybe one read-only `VectorIndex` method; searches the live collection read-only | **listed exception**: read-only by construction, not called by retrieval; same hold rule |
| RIDER-1 | config validation (item 2), fixtures promotion (item 5), CI (item 6) | **violates the rule unless sequenced**: item 2 changes config validation (start-up); resolved by the explicit dependency RIDER-1 <- EV-18, so it merges after the last baseline |
| EV-16, EV-17, EV-18, EV-20 | measurements | n/a |

Outcome: no active ticket violates the rule as sequenced; five (MC-1, MC-2, MC-3, OP-5, EV-14) are baseline-path exceptions listed with their reason, none a baseline prerequisite (the minimizer's ruling: defensible, not gating), and RIDER-1 is the one ticket that would violate it if it were not held behind EV-18.

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
| EV-4 | Topic-focus ground truth | MERGED, needs repair | branch `EP-EV4-focus-gt`; independent cross-verification found 18 of 26 collision questions did not contain their collision term and 6 of 10 absent items weak. Anything that depended on the focus set's frozen hash now depends on EV-4b |
| EV-4b | Repair of the focus ground truth (collision questions, weak absent items) and re-freeze of its hash | IN PROGRESS | branch `EP-EV4b-focus-fixes` |
| EP-2 | This plan, the issue files and the BACKLOG section (first version) | READY | branch `EP-EP2-ticket-set` |
| EP-2b | Application of the operator-approved minimizer verdicts (this revision) | READY | branch `EP-EP2b-apply-minimizer` |
| OP-4 | Fresh main-corpus snapshot, executed by the orchestrator outside the queue (it is also an active ticket, section 8) | IN PROGRESS | consistent SQLite backup into the corpus's `backups/` directory with integrity check, row-count comparison and SHA-256; the vector store's on-disk data was NOT copied (service stopped, about 31 GB, operator decision pending); not DONE |

## 8. The tickets (ACTIVE)

Every entry has the same fields; the standard gate (full zero-GPU pytest, enforcement, ruff on owned files) is spelled out in each. The same text is the issue body in the issues directory. Order is the minimal critical path first within each wave. Active tickets with a 'Cut by minimizer' line were shrunk; 'Absorbs' names merged sources.

### W1 do now, no GPU

#### OP-4: Take and verify a fresh main-corpus snapshot

Labels: wave:1-no-gpu, area:ops, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-4-take-verify-main-snapshot.md`.

**Review cross-reference:** S-01. **Wave:** W1 do now, no GPU.

**Status (2026-11-10): IN PROGRESS**, executed by the orchestrator outside the programme queue (do not wait for F1; only the off-device copy and deletions need it). It is a consistent SQLite backup of the main corpus database into that corpus's `backups/` directory with an integrity check, a row-count comparison against the manifest and a SHA-256. **The vector store's on-disk data was NOT copied** (service stopped; about 31 GB; operator decision pending). Do not mark this ticket DONE until the operator has decided that copy.

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

**Gates / depends on.** Depends on: none. Gates: CQ-7 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched); operator answers: F1 · re-embed: n. Also: operator go-ahead to write about 9 GB (estimate, RV-6) into the main data dir's backups folder on a 98%-full device.

**Model tier and size.** Haiku; S (up to 2 h of agent work). Mechanical work, no judgement calls.

**Risk and rollback.** Disk fills mid-write on a 98%-full device. Mitigation: abort rule before starting; the tool reads the source read-only and writes only the new snapshot. Rollback: delete the new snapshot directory.

**Docs to update in the same PR.** The dated snapshot record is the doc (section 7 doc-map row if a new `docs/*.md` is added); ledger entry only after the operator decides the vector-store data copy. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### OP-3: Add integrity check and checksums to snapshot manifests

Labels: wave:1-no-gpu, area:ops, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-3-snapshot-integrity-and-checksums.md`.

**Review cross-reference:** S-01. **Wave:** W1 do now, no GPU.

**Absorbs EP-7** (part: the backup and restore RUNBOOK section). EP-7's GPU-contention section goes to OP-5 and its containers pointer to OP-7.

**Why.** `app/snapshot.py::backup_sqlite` is correct (read-only source plus VACUUM INTO) but never runs an integrity check and the manifest records no checksum per artifact (RV-6 F-A1, F-A7; review S-01), so a corrupt snapshot looks identical to a good one until the day it is restored.

**Scope.**
- In:
  - Run `PRAGMA quick_check` on the produced SQLite copy and fail the snapshot (non-zero exit, snapshot marked incomplete) if it is not `ok`.
  - Write sha256 per artifact into the manifest; add a verify mode (or reuse an existing one) that recomputes them and compares `count(*)` with the manifest.
  - `docs/RUNBOOK.md`: backup and restore section (what `app.snapshot` writes, how to verify with `quick_check` and the manifest checksums, a restore drill on a scratch copy, retention, the off-device gap named as open question F1). Commands run or `--help`-checked and quoted, not guessed.
- Out (explicitly):
  - The guard against a nonexistent data dir (OP-6). Taking a snapshot (OP-4). Off-device copy (F1).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/snapshot.py`
- `app/test_snapshot.py`
- `docs/RUNBOOK.md`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the manifest fields (`quick_check`, `sha256` per artifact) and the failure rule
② failing tests: corrupt copy fails; manifest has sha256; verify detects a flipped byte
③ implementation to green
④ docstring and `--help` text brought up to date
⑤ RUNBOOK backup and restore section

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/snapshot.py app/test_snapshot.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_snapshot.py -o addopts="--disable-socket"`
- Mutation proof (CONVENTIONS section 14): revert the quick_check call and watch the corruption test fail
- `grep -n 'quick_check' docs/RUNBOOK.md` shows the verification step; every command in the section was run or `--help`-checked and quoted in the PR

**Acceptance / falsification criterion.** A deliberately corrupted SQLite copy makes the snapshot exit non-zero and not write a complete manifest; a flipped byte in an artifact fails verify; existing snapshot tests stay green. Falsified if either test passes with the check removed.

**Gates / depends on.** Depends on: none. Gates: OP-6.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A verify mode changes the manifest shape: old manifests lack checksums. Mitigation: verify treats a missing checksum as 'unverifiable', not 'ok'. Rollback: revert.

**Docs to update in the same PR.** Section 2: entry-point row for any new snapshot flag; `docs/RUNBOOK.md` backup and restore section is part of this PR. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### OP-6: Guard every corpus tool against a missing or mismatched database

Labels: wave:1-no-gpu, area:ops, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-6-wrong-corpus-guards.md`.

**Review cross-reference:** S-07. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** the `app/dashboard/status.py:830` fallback and `reindex_idf` are cut (`reindex_idf` is a no-op tool per plan section 9; eval is already protected by the run scripts' `check-points`). Folded in from the unplaced lane findings: the doctor disk-space check against the device of the data directory, not the cwd (RV-6 F-A10; matters at 98% full).

**Why.** Only `app.serve --data-dir` refuses a nonexistent database (`app/serve.py:80-82` has no exists check on the default branch). `app/corpus_integrity.py` opens the live database read-write, and the collection-versus-database pairing is checked nowhere, so a mispointed tool returns a confident empty or wrong corpus (the T-DOC56 shape; RV-6 F-A4, RV-3 F-1.2; review S-07). `app/dashboard/status.py:830` falls back to the literal collection name `papers`.

**Scope.**
- In:
  - One shared `require_existing_db()` (search for an existing helper first, e.g. the T-DOC56 `_resolve_store_paths`; add a module only if none fits) used by `corpus_integrity` (also opened `mode=ro`) and `snapshot`.
  - `app.doctor`: collection point count must match the database within 1% (stated tolerance), reported with both numbers.
  - `app.doctor`: free-space check measured on the device that holds the data directory (not the current working directory), reported with the path.
- Out (explicitly):
  - `app/dashboard/status.py` fallback and `app/reindex_idf.py` (cut). The two `app/serve.py` branches (parked OP-2). Changing `migrate()` (protected).
  - Auto-snapshot before migration (RV-6 F-A7, dropped).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/corpus_paths.py`
- `app/test_corpus_paths.py`
- `app/corpus_integrity.py`
- `app/test_corpus_integrity.py`
- `app/snapshot.py`
- `app/test_snapshot.py`
- `app/doctor.py`
- `app/test_doctor.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring of `require_existing_db()` stating precondition and error message; list of the two call sites
② failing tests per call site (nonexistent path exits non-zero, names the path)
③ helper + call sites to green; `corpus_integrity` opens `mode=ro` (test asserts a write attempt fails)
④ doctor point-count-vs-database check with injected counts
⑤ doctor disk-space check on the data-dir device with an injected `statvfs`

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/corpus_paths.py app/test_corpus_paths.py app/corpus_integrity.py app/test_corpus_integrity.py app/snapshot.py app/test_snapshot.py app/doctor.py app/test_doctor.py`
- `conda run -n agent-rag-research python -m app.corpus_integrity --help` still works; each tool against a nonexistent data dir exits non-zero (shown in the PR)
- `conda run -n agent-rag-research python -m app.doctor --cpu-only` from each data dir still passes where services are up (needs services: run only when the vector store is up)

**Acceptance / falsification criterion.** `snapshot` and `corpus_integrity` exit non-zero against a nonexistent path with a message that names the path; `corpus_integrity` cannot write; doctor run from each of the five data dirs passes its pairing check on the current corpora and reports free space for the data-dir device. Falsified if either tool still prints a result for a nonexistent path or if the doctor check fails on a correctly paired corpus.

**Gates / depends on.** Depends on: OP-3 (ordering only: same file, not a data dependency). Gates: OP-5, OP-2 (parked).

**Needs.** GPU: n · services up: vector store (CPU container) only for the doctor smoke run; unit tests use fakes · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A false positive in the 1% tolerance blocks a healthy doctor run. Mitigation: tolerance is a named constant, the message prints both counts. Doctor, snapshot and integrity are not on the retrieval path (pre-baseline rule, plan section 4). Rollback: revert; the guards are additive.

**Docs to update in the same PR.** Section 2: doctor behaviour (pairing and disk-space checks). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### OP-5: Name the GPU lock holder and list foreign GPU processes in doctor

Labels: wave:1-no-gpu, area:ops, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-5-gpu-lock-holder-and-fast-fail.md`.

**Review cross-reference:** S-06. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** the 20 s query-path timeout is deferred (a behaviour change on the baseline path, and a Config field the rider would have to add) until a contended real session shows the 300 s wait; `app/assembly.py` leaves Owns. Holder file and doctor foreign-process listing stay (the foreign holder of 18.6 GB is real and current). OP-5 is no longer a dependency of EV-16. Absorbs the GPU-contention section of EP-7 (see Absorbs).

**Absorbs EP-7** (part: the GPU-contention RUNBOOK section and the `gpu_lock_path` second-corpus warning, RV-6 punch row 22). EP-7's other sections go to OP-3 (backup and restore) and OP-7 (containers).

**Why.** A query waits up to 300 s (the wait itself is left as is here) for the GPU lock before erroring (`app/assembly.py:630-640` passes no `gpu_lock_timeout`, default 300 s in the embedder and reranker), the timeout message does not name the holder (`rag/gpu_lock.py:38-41`), and doctor reports only 'unreachable' when a foreign process holds the GPU (OP-1 handles 'TEI down', not 'GPU held'; RV-1 F-1.9, RV-6 F-A3 and F-A8; review S-06). A foreign model server holds 18,609 of 24,576 MiB today.

**Scope.**
- In:
  - `FileGpuLock` writes pid, stage and UTC time to a `<lock>.holder` file on acquire (best effort, removed on release) and the timeout error reads it back.
  - `app.doctor`: list foreign GPU compute processes via `nvidia-smi --query-compute-apps` and read the TEI container exit code and OOM log line, so 'GPU held by a foreign process' is distinct from 'TEI crashed' (nvidia-smi and docker calls injected so tests need neither).
  - `docs/RUNBOOK.md`: GPU-contention section (holder file, doctor's foreign-process listing, cheapest-first ordering rule from LESSONS section 9.1) and, in 'Running a second corpus', the warning that `app.init_config` writes a private `gpu_lock_path` that must be edited to the shared lock (punch row 22). Commands quoted from a run, not guessed.
- Out (explicitly):
  - The 20 s query-path timeout and its Config field (deferred until a contended real session; RIDER-1 would carry the field). Any change to `app/assembly.py` or to the lock wait time.
  - Marking eval runs invalid on lock timeouts (EV-10). A priority scheduler for the lock. Reranker-failure fallback to fused order (changes behaviour, needs a Coverage flag: foundation).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/gpu_lock.py`
- `rag/test_gpu_lock.py`
- `app/doctor.py`
- `app/test_doctor.py`
- `docs/RUNBOOK.md`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings stating the holder-file format and the doctor listing
② failing tests: second lock with timeout 0.1 raises naming the first's pid and stage; doctor names a foreign pid from a canned nvidia-smi output
③ implementation to green
④ doctor TEI exit-code and OOM-line reading with injected docker output
⑤ RUNBOOK GPU-contention section and the `gpu_lock_path` warning; every command run or `--help`-checked

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/gpu_lock.py rag/test_gpu_lock.py app/doctor.py app/test_doctor.py`
- Two `FileGpuLock` objects on one path in a unit test (no GPU)
- `grep -n 'gpu_lock_path' docs/RUNBOOK.md` shows the second-corpus warning
- Live check only when the operator frees the GPU: hold the lock from a second process; the timeout error names the holder

**Acceptance / falsification criterion.** Holding the lock from a second process (test timeout 0.1 s) makes the second acquirer's error name the holder's pid and stage; doctor output against a canned foreign-holder state names the pid and says 'GPU held by a foreign process', not 'TEI unreachable'; the default query-path wait is unchanged (no `app/assembly.py` diff). Falsified if the error omits the holder or the diff changes a timeout.

**Gates / depends on.** Depends on: OP-6 (ordering only: same file, not a data dependency). Gates: OP-7, OP-2 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** The holder file is written on every lock acquire, including on the eval path: best effort and removed on release, so no result changes (listed in the pre-baseline rule, plan section 4). A stale holder file could name a dead pid: the message states the write time. Rollback: revert.

**Docs to update in the same PR.** Section 2: doctor flags; `docs/RUNBOOK.md` GPU-contention section is part of this PR. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### OP-7: Track the four container definitions in ops/docker-compose.yml

Labels: wave:1-no-gpu, area:ops, needs-services, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-7-tracked-container-definitions.md`.

**Review cross-reference:** S-12. **Wave:** W1 do now, no GPU.

**Absorbs EP-7** (part: the containers RUNBOOK pointer). Its RUNBOOK commit is ordered after OP-5 (shared file `docs/RUNBOOK.md`); the compose-file commits have no dependency.

**Why.** The four containers (embedder, reranker, vector store, reference-resolution service) cannot be recreated from tracked files: the vector-store image tag is the moving `latest`, arguments, ports and volumes exist only in `docker inspect`, and a re-pull could jump the storage version over a 31 GB store (RV-6 F-A2; review S-12). Not re-run by the review beyond the lane's own inspect.

**Scope.**
- In:
  - A compose file with the four services exactly as inspected today (image, command, binds, ports, GPU reservation), the vector store pinned to v1.18.2 by digest, and no restart policy (a restart on a contended GPU is how the foreign-holder situation arises).
  - Read-only inspection only: `docker inspect`, `docker image inspect`, `docker compose config`.
  - `docs/RUNBOOK.md`: a short containers section pointing to `ops/docker-compose.yml`, the pinned vector-store version and the rule that nothing is restarted without a verified snapshot and a `docker compose config` diff.
- Out (explicitly):
  - Starting, stopping or recreating any container (this ticket never applies the file). Moving the vector store's data. Adding a restart policy.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `ops/docker-compose.yml`
- `docs/RUNBOOK.md`

**Commits** (① is a stub, committed before any real work):
① stub: compose file with the four service names and a header comment stating 'mirrors inspected state of <date>; never applied by this ticket'
② services transcribed from `docker inspect` output, one commit per service pair
③ digest pin and `docker compose config` output compared line by line with the inspected values
④ RUNBOOK containers section (after OP-5 has merged)

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `docker compose -f ops/docker-compose.yml config` succeeds and matches image, command, binds and GPU reservation of each running container (differences listed in the PR)

**Acceptance / falsification criterion.** `docker compose config` reproduces image digest, command, binds, ports and GPU reservation of all four running containers; the vector-store image is pinned by digest to v1.18.2; the PR lists any field that could not be reproduced. Falsified if a running container's inspected setting is absent from the file.

**Gates / depends on.** Depends on: OP-5 (ordering only: shared `docs/RUNBOOK.md`; only its RUNBOOK commit waits). Gates: none.

**Needs.** GPU: n · services up: docker daemon read-only inspection (no container is started or restarted) · operator sign-off: n (not a protected path). The version pin is a decision for the operator in PR review. · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** The file drifts from reality or is applied by a later agent with different GPU settings. Mitigation: header states it is a mirror; the RUNBOOK containers section (this ticket) says 'verify with config diff before any recreate'. Rollback: delete the file.

**Docs to update in the same PR.** `ops/docker-compose.yml` is the doc; `docs/RUNBOOK.md` containers section is part of this PR; section 7 doc-map row for the compose file if the map lists ops files. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EP-6: Add CORPORA.md and fix drift rows outside EP-1's files

Labels: wave:1-no-gpu, area:docs, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EP-6-docs-corpora-and-drift-remainder.md`.

**Review cross-reference:** S-13. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** the HANDOFF-2026-08-24 and precision-95 plan status-tick rows are archaeology and are cut; CORPORA.md, the no-ingest rule and the closure of Decision 1 stay (a stale doc misleads agents). Not on the baseline path.

**Why.** Agents follow stale docs exactly (CONVENTIONS section 0.6). The review's 23-row drift punch list (RV-6 B.1) splits by file: PROJECT-STATUS, README and AGENTS belong to EP-1 (in progress); the rest has no owner. Which chunker built each corpus is written nowhere (RV-2 F-2.2), the IDF question in DECISIONS-PENDING Decision 1 is stale (the on-disk config of all five collections already carries the IDF modifier; review item 1 'Decision 1'), and the review's rule 'no ingest into a live collection from this branch' has no home.

**Scope.**
- In:
  - New `docs/CORPORA.md`: one row per corpus (five), data-dir role, collection name, document/chunk counts re-derived read-only, and which chunker built it (standards: bounded chunker; main and Waymo: legacy chunker), reusing the five-corpus registry EP-1 added to PROJECT-STATUS instead of restating it differently. State that only the main, standards-GT and focus sets have baselines in this programme; the Motional, Waabi and Waymo corpora get none (plan section 9).
  - State the rule: no ingest into a live collection from this branch until the operator has decided the parked sparse-recompute (CQ-7/EV-22) and re-chunk (CQ-16) questions, because it would mix chunkers and sparse versions (review S-13; item h residual risk 1).
  - Close Decision 1 in `docs/DECISIONS-PENDING-operator.md` with the evidence (IDF modifier present in the on-disk config of all five collections).
  - HISTORICAL banner, in this PR, on any doc this PR supersedes (AGENT-PROCEDURES section B).
- Out (explicitly):
  - `docs/HANDOFF-2026-08-24.md` and the precision-95 plan tick rows (cut).
  - PROJECT-STATUS section rows other than this ticket's own ledger and doc-map entries, README.md, AGENTS.md (EP-1, done). RUNBOOK.md (OP-3, OP-5, OP-7). Any code change; any measurement that needs a service (counts are read-only SQLite).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/CORPORA.md`
- `docs/DECISIONS-PENDING-operator.md`

**Commits** (① is a stub, committed before any real work):
① stub: `docs/CORPORA.md` skeleton with the five rows and column headings, empty cells marked TODO
② corpora table filled from read-only queries; counts stamped with the query date
③ no-ingest rule + chunker provenance column
④ Decision 1 closure with the git evidence

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `grep -n 'Decision 1' docs/DECISIONS-PENDING-operator.md` shows the closure with the config evidence
- Every count in CORPORA.md reproduces with the read-only query printed under the table (`sqlite3 "file:<db>?mode=ro" 'select count(*) from chunks'`)

**Acceptance / falsification criterion.** `docs/CORPORA.md` lists five corpora with path role, collection, counts and chunker; each count was re-derived on the day and the query is shown; the no-ingest rule is present; Decision 1 reads 'closed' with evidence; someone who did not write it can re-run every shown query and match. Falsified if any count differs from a fresh read-only query by more than the ingest drift stated in the doc.

**Gates / depends on.** Depends on: none. Gates: none.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. Docs only. A wrong count misleads an agent; mitigation is the printed query beside each number. Rollback: revert the commit.

**Docs to update in the same PR.** New `docs/CORPORA.md` gets a section 7 doc-map row (AUTHORITATIVE) and a ledger entry. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

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

**Gates / depends on.** Depends on: none. Gates: MC-2.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A valid-but-unindexed paper id now errors where it used to return empty. That is intended; it is also the same behaviour `get_paper` already has. Rollback: revert.

**Docs to update in the same PR.** Section 2: the unknown-`paper_id` error. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### MC-2: Make the MCP server describe its corpus, filters and limits

Labels: wave:1-no-gpu, area:mcp, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/MC-2-self-describing-mcp-server.md`.

**Review cross-reference:** S-10. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** the new `documents` list in `corpus_stats` (and with it the metadata-tag dependency) is cut. Instructions string and filter legend stay (evidence: `doc_type` used 0 of 1,198 calls; wrong-corpus calls ids 8, 21-24). The MC-1 -> MC-2 edge is file ownership (`rag/mcp_server.py`), not data.

**Why.** A cold agent sees no server instructions, zero field descriptions in the `SearchFilters` schema, and docstring guidance that FastMCP never exposes; `doc_type` was used 0 times in 1,198 logged calls, and wrong-corpus queries appear in the main log (ids 8, 21-24) (RV-4 F-4.3, F-4.4; review S-10). Hard-coded counts and a stale 32-ceiling paragraph in docstrings can disagree with the corpus.

**Scope.**
- In:
  - Pass `instructions=` to `FastMCP`, generated at startup from `corpus_stats()` (what the corpus is, counts, date range, document kinds, which filters are meaningful, a five-line tool map), under 250 tokens.
  - A compact filter legend in the `semantic_search` tool docstring (the field schema is protected). Delete hard-coded counts and the 32-ceiling paragraph.
- Out (explicitly):
  - A `documents` list in `corpus_stats` (cut by the minimizer). Field descriptions on `SearchFilters` (contracts edit, RIDER-1 territory). A per-corpus card file or Config key. Federation across corpora. Response slimming (parked MC-4).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/serve.py`
- `app/test_serve.py`
- `rag/mcp_server.py`
- `rag/test_mcp_server.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the instructions contract (generated, under 250 tokens, no literal counts)
② failing tests: `instructions` present and under budget; every filter named in the legend; no number in any description absent from `corpus_stats`
③ implementation to green
④ docstring cleanup commit

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/serve.py app/test_serve.py rag/mcp_server.py rag/test_mcp_server.py`
- `list_tools` and `initialize().instructions` dump built on fakes (no GPU, no store); output quoted in the PR
- `conda run -n agent-rag-research python -m pytest -q app/test_serve.py rag/test_mcp_server.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Instructions exist and stay under 250 tokens on a standards-sized and a main-sized fake; every filter appears in the legend; no description contains a literal count that disagrees with `corpus_stats`. Falsified if a description number is not derived from `corpus_stats`.

**Gates / depends on.** Depends on: MC-1 (ordering only: same file, not a data dependency). Gates: MC-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Generated text that is wrong for a corpus misleads every cold session. Mitigation: the text is derived from `corpus_stats` only; a test pins that. Rollback: revert.

**Docs to update in the same PR.** Section 2: what the server advertises. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### MC-3: Record arguments and errors for scan and get tools in the usage log

Labels: wave:1-no-gpu, area:mcp, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/MC-3-scan-tool-telemetry.md`.

**Review cross-reference:** S-11. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** bind pattern/args and the error message only; the `--client-label` flag is cut (no MCP work is scheduled that consumes it). Decoupled from OP-2 (parked). The MC-2 -> MC-3 edge is an ownership order only (both own `app/serve.py`), not a data dependency.

**Why.** 213 scan calls (18% of all 1,198 logged calls) have no pattern recorded, `get_section`, `get_span` and `get_paper` rows carry no arguments, errors store only the exception class name, and `source` is constant, so harness replays look like agent sessions (RV-4 F-4.5; review S-11). The usage log is the only evidence base for any future MCP work, and it is blind exactly where agents behave most like brute force.

**Scope.**
- In:
  - Bind pattern, method or section path into the existing `query` column, the argument `paper_id`, `result_count` from the result length and `str(e)[:200]` into `error`. No schema change; existing rows stay valid.
- Out (explicitly):
  - A `--client-label` flag and any change to `source` (cut by the minimizer). New columns (top score, returned ids: RV-6 F-A9, dropped). Dashboard changes. Any retrieval change.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/usage_log.py`
- `app/test_usage_log.py`
- `app/serve.py`
- `app/test_serve.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the per-tool binding table
② failing tests per tool (scan_corpus, scan_methods, get_section, get_span, get_paper, errors)
③ implementation to green

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/usage_log.py app/test_usage_log.py app/serve.py app/test_serve.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_usage_log.py app/test_serve.py -o addopts="--disable-socket"`
- On a scratch usage database: one mixed fake session then `select tool, query from requests where tool like 'scan%'` shows no NULL query

**Acceptance / falsification criterion.** After one scripted mixed session on fakes, no scan row has a NULL `query` and every get_* row has its `paper_id`; error rows carry the message prefix. Falsified if any tool still writes a NULL where its argument exists.

**Gates / depends on.** Depends on: MC-2 (ordering only: same file, not a data dependency). Gates: OP-2 (parked), MC-4 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Logging full regex patterns could store sensitive text. Mitigation: the log is local and already stores queries; length is capped. Rollback: revert; rows written stay valid.

**Docs to update in the same PR.** Section 2: what the usage log now records for scan and get tools. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-14: Measure filtered-search overlap with exact search on the live collection (read-only)

Labels: wave:1-no-gpu, area:eval, area:retrieval, needs-services, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-14-payload-index-overlap-measurement.md`.

**Review cross-reference:** S-15. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** no clone is made: search is read-only, so exact versus HNSW runs on the live collection; the OP-4 and RQ-5 dependencies are dropped. CPU-only (the vector store container, no embedder, no reranker), so it can run while the GPU is busy.

**Why.** No payload index exists on any live collection (every segment's `payload_index/config.json` is `{"indexed_fields":{}}`; 8, 7 and 8 segments), yet every query is filtered. The recall loss is inferred from the vector store's documented design, not measured (the minimizer notes the harm is inferred, not observed; this is the cheap closer); the real risk band is mid-selectivity filters (`kind=summary` is 3% of points and is the whole `search_papers` path; `doc_type=book`) (review item b; RV-1 F-1.2).

**Scope.**
- In:
  - Read-only on the live collection (never a write, never an index change): use 100 stored summary vectors as queries and compare exact search with the default HNSW search for `kind=summary`, `doc_type=book` and a single `paper_id`; report overlap@k per filter. Reuse CQ-2's read-only sampling helpers; if an exact-search method is missing from `VectorIndex`, add one small read-only method there (vendor SDK calls stay inside that adapter).
  - Pre-registered falsifier (commit 1): HNSW overlap with exact is at least 0.99 on all three filters, then payload-index work (parked CQ-9) is closed.
- Out (explicitly):
  - Cloning the collection. Creating payload indexes (parked CQ-9). Any write to the collection. Any GPU use: stored vectors are the queries, nothing is embedded.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `scripts/payload_index_overlap.py`
- `scripts/test_payload_index_overlap.py`
- `docs/eval-reports/data/<run-date>-payload-index-overlap/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the pre-registered 0.99 falsifier and the three filters, committed before any query is sent
② exact-search read-only method (only if missing) and the script, unit-tested against mocked clients
③ dry run on 10 queries against the live collection
④ full run; report with the overlap table and the verdict

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py scripts/payload_index_overlap.py scripts/test_payload_index_overlap.py`
- `conda run -n agent-rag-research python scripts/payload_index_overlap.py --help` shows required `--collection`; the script issues no write call (a unit test asserts the client double records none)
- Report table has one row per filter with overlap@10 and the count of queries returning fewer than k

**Acceptance / falsification criterion.** Report states overlap of HNSW versus exact for each of the three filters on the live collection. Verdict is mechanical: all three at least 0.99 closes the finding (parked CQ-9 is then killed); any below 0.99 satisfies CQ-9's trigger. Falsified (finding closed) if all three are 0.99 or more. No write to the collection occurred.

**Gates / depends on.** Depends on: none. Operator answers: F2. Gates: CQ-9 (parked).

**Needs.** GPU: n · services up: vector store (CPU container) up; no embedder, no reranker · operator sign-off: n (no protected path is touched); operator answers: F2 (start the vector store container) · re-embed: n.

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Adding a method to `rag/vector_index.py` that is read-only by construction; the live collection is only read. Rollback: revert.

**Docs to update in the same PR.** The overlap report is a new doc (section 7 doc-map row); section 5/6 gets the verdict (finding closed or CQ-9 trigger met). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-7: Require --collection, stamp the fixture hash, preflight gold ids

Labels: wave:1-no-gpu, area:eval, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-7-eval-entrypoints-explicit-collection.md`.

**Review cross-reference:** S-02. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** `escalation_eval.py` and `score_distribution_census.py` are not run anywhere in the programme and drop out; `app/retrieval_eval.py` (the instrument) and the gold-id preflight stay. The failure is real but already mitigated: EV-5's run scripts pass `--collection` and check the hash.

**Why.** `--collection` still defaults to None in `app/retrieval_eval.py:780` (the same default exists in `app/escalation_eval.py` and `app/score_distribution_census.py`, which this programme does not run), which `build_mcp_server` turns into the main `papers` collection, so a mispointed run yields a plausible low number with `n_errors = 0` (RV-3 F-1.2). Reports stamp no hash of the ground-truth file (contrast `judge_eval`'s `rubric_sha256_12`). EV-5 already fixed the run scripts (fixture hash check, point-count guard, no fixture rewrite, run from the worktree under test); the Python entry points themselves were not touched.

**Scope.**
- In:
  - `--collection` `required=True` in `app/retrieval_eval.py` (precedent: `app/generation_capture.py`).
  - `ground_truth_sha256_12` in `build_report`, same pattern as `judge_eval`.
  - Preflight before scoring: every `gold_paper_id` of the loaded questions resolves in the document store, else exit 2 naming the unresolved ids.
- Out (explicitly):
  - `app/escalation_eval.py` and `app/score_distribution_census.py` (not run in this programme; they keep their default).
  - The run scripts, protocols and addenda (EV-5, done). The collection point-count check (stays in the run scripts' `check-points`). Lock-timeout validity (EV-10). Excerpt metric (EV-8).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings stating the three behaviours (required flag, hash stamp, preflight exit 2)
② failing tests for each
③ implementation to green
④ docstring/`--help` text updated

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py`
- `conda run -n agent-rag-research python -m app.retrieval_eval --help` shows `--collection` as required
- Unit test: report hash equals `sha256sum` of the fixture file (first 12 hex)

**Acceptance / falsification criterion.** Running `app.retrieval_eval` without `--collection` exits non-zero; the report's `ground_truth_sha256_12` equals the first 12 hex of `sha256sum` of the file; a fixture with an unresolvable gold paper id exits 2 naming it. Falsified if a run without `--collection` still starts.

**Gates / depends on.** Depends on: none. Gates: EV-8, EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Existing wrapper scripts that relied on the default break loudly. Mitigation: that is the point; EV-5's run scripts already pass `--collection`. Rollback: revert.

**Docs to update in the same PR.** Section 2: `--collection` is now required for `app.retrieval_eval`. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

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

**Gates / depends on.** Depends on: EV-7 (ordering only: same file, not a data dependency). Gates: EV-9, EV-11, EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Two metrics diverge in meaning from EV-6's member-passage metric and confuse later reports. Mitigation: the docstring reconciliation and one stamped `scoring_rule`. Rollback: revert; additive.

**Docs to update in the same PR.** Section 2: the new `passage_excerpt_hit` report fields. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-9: Record retrieved chunk ids in eval rows

Labels: wave:1-no-gpu, area:eval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-9-chunk-ids-in-eval-rows.md`.

**Review cross-reference:** S-05. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** only the additive `retrieved_chunk_ids` row field stays (rows from the 1-2 h standards run cannot be recollected cheaply, and EV-18 prints the structure-gate count from them); the `scripts/list_stub_chunks.py --ab` rewiring is cut and is done only if EV-21 is commissioned. The EV-9 -> EV-10 edge is a file-ownership order only (both own `app/retrieval_eval.py`), not a data dependency.

**Why.** Report rows carry only `retrieved_block_ids` (`app/retrieval_eval.py:229,371,551`), and `scripts/list_stub_chunks.py` identifies a stub by its anchor block, which is ambiguous for the 7.5% of standards chunks that share an anchor (35,714 chunks, 33,053 distinct anchors; RV-1 F-1.3, review section 2 on CQ-3). EV-18's structure-gate count and any later stub analysis (parked EV-21) need per-chunk identity in the rows.

**Scope.**
- In:
  - Add `retrieved_chunk_ids` to the per-question row. `GroundedResult` has no chunk id, so recover it from (paper id, anchor block id, passage text) through the document store the harness already holds; where two chunks match, record both and mark the row ambiguous.
- Out (explicitly):
  - `scripts/list_stub_chunks.py --ab` matching by chunk id (parked EV-21 does that if it is commissioned).
  - Any `contracts/` change. If chunk ids cannot be recovered without one, STOP and report: that is a RIDER-1 candidate, not an edit.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring of the recovery rule and the ambiguity marker
② failing tests: unique recovery; duplicate-text ambiguity marked; a shared-anchor fixture yields both chunk ids and the ambiguous flag
③ implementation to green

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_retrieval_eval.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** On a fixture with two chunks sharing one anchor, the row lists both chunk ids and is marked ambiguous; ambiguous rows are counted in the report, not hidden. Falsified if recovery silently picks one of two matching chunks.

**Gates / depends on.** Depends on: EV-8 (ordering only: same file, not a data dependency). Gates: EV-10, EV-6b, EV-12 (parked), EV-16, EV-18, EV-21 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Recovery by text may be slow on 30,000-chunk papers. Mitigation: per-paper lookup, cached. Rollback: revert; additive field.

**Docs to update in the same PR.** Section 2: the new `retrieved_chunk_ids` row field. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

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

**Gates / depends on.** Depends on: EV-9 (ordering only: same file, not a data dependency). Gates: RQ-2 (parked), EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A transient timeout on one question invalidates a long run. Mitigation: intended (a partially starved run is not a baseline); the run is repeatable. Rollback: revert.

**Docs to update in the same PR.** Section 2: the `run_valid` rule and non-zero exit. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-11: Record note-only duplicates as alternatives and re-freeze fixture hashes

Labels: wave:1-no-gpu, area:eval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-11-record-alternatives-refreeze-hashes.md`.

**Review cross-reference:** S-03. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** the `merge_gt` orphan-tolerance change is cut (run scripts no longer call `merge_gt`; no orphan has ever been observed), so `gt_tools.py` leaves Owns. Folded in from the unplaced lane findings: one caveat sentence in the addendum (RV-3 F-1.12: the chapter-level metric is a heading-string match).

**Why.** Cross-verification found three same-document duplicates recorded only as 'survive' notes (Q-STD-D-014, D-027, D-028) that are not in `alternative_gold_chunk_ids`, so a correct answer from the duplicate scores a miss (RV-3 F-1.5, review S-03). Fixing it changes a frozen fixture, so it must happen before any run and under a dated addendum, because the frozen protocols record each fixture's SHA-256.

**Scope.**
- In:
  - Dated addendum to the standards protocol first (commit 1), containing the change, why it is pre-run, the new hash procedure, and one caveat sentence that the chapter-level metric is a heading-string match (RV-3 F-1.12).
  - Then record the three duplicates as alternatives in the standards ground-truth file and update the standards, books and papers entries in `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`.
- Out (explicitly):
  - Rewriting any question or gold excerpt. Any `merge_gt` / `gt_tools.py` change (orphan tolerance cut). Collapsing the three `gt_tools.py` copies. The focus-set hash entry (EV-4b owns it). Promotion into `fixtures/eval/` (RIDER-1).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/2026-11-10-standards-gt/`
- `docs/eval-reports/data/2026-11-10-causal-books-gt/`
- `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`
- `docs/eval-reports/2026-11-10-standards-benchmark-protocol.md`

**Commits** (① is a stub, committed before any real work):
① stub: addendum text (what changes, why it is pre-run, the new hash procedure, the F-1.12 caveat) appended to the standards protocol BEFORE any fixture edit
② three duplicates recorded as alternatives
③ new hashes written to FIXTURE-HASHES.json for the files that changed
④ `scripts/eval_protocol_tools.py check-hash` transcript quoted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research python scripts/eval_protocol_tools.py check-hash docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json <fixture-relative-path>` passes for each fixture
- `git log --format=%H -- docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json` shows the addendum commit precedes the hash change

**Acceptance / falsification criterion.** Addendum commit precedes the fixture edit; the three duplicates appear as alternatives; hashes in the file equal `sha256sum` of each fixture; no question text or excerpt changed (diff shows only alternatives and the hash file). Falsified if `git diff` shows any other change in a fixture.

**Gates / depends on.** Depends on: EV-8. In-progress tickets on other branches (merge order or inputs): EV-4b. Gates: CQ-19 (parked), EV-12 (parked), EV-16, EV-18, RIDER-1.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A hash edit after a run would void that run. Mitigation: ordered before wave 2 by dependency. The hash file is shared with in-progress EV-4b (focus entry): edits are key-disjoint and EV-4b merges first or the two rebase over each other in key-disjoint hunks. Rollback: revert the fixture and hash commits together.

**Docs to update in the same PR.** The standards protocol addendum is the doc; the hash file is the record. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

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

**Gates / depends on.** Depends on: none. Gates: EV-16, EV-18.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A tokenisation difference makes the floor differ from the one the protocols quote. Mitigation: the reproduction check and the stated tolerance. Rollback: revert.

**Docs to update in the same PR.** Section 2: entry-point row for `scripts/bm25_floor.py`. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-6b: Dry-run and independently review the strata report script before the first baseline

Labels: wave:1-no-gpu, area:eval, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-6b-review-strata-report-script.md`.

**Review cross-reference:** review section 2 ('EV-6 not reviewed by any lane'); minimizer section 2 (critical-path gap). **Wave:** W1 do now, no GPU.

**Why.** `scripts/eval_strata_report.py` (EV-6, done) produces every per-stratum and member-passage number of EV-16, EV-17 and EV-18, yet no lane or reviewer has examined it, and its own docstring states known over-estimate cases (3.1% of sampled standards chunks have a member block missing from the chunk text; chunks sharing one anchor are merged). A wrong table would be read as a baseline. The minimizer proposed folding a dry run into EV-8's acceptance; the operator asked for a separate small ticket so that the review is done by an agent other than the author of the row-format changes (EV-8, EV-9, EV-10) and after the row format is final.

**Scope.**
- In:
  - A hand-computed example: a six-question fake rows file and a tiny ground-truth file (built in the test, no real corpus) in which every printed number (paper recall@k and P@1, anchor and member-passage hit, stub share, authority/edition ranking, cross-document, absent arm, focus contamination) is computed by hand and written into the test as a literal; the script's output must equal it.
  - A dry run of the script on the rows produced by the merged EV-7..EV-10 bundle's fake-backed tests (so rows carry `passage_excerpt_hit`, `retrieved_chunk_ids`, `scoring_rule`, `ground_truth_sha256_12`, `run_valid`): the script must not fail on the new fields and the review note states whether it ignores or uses each.
  - A written review note: each metric definition read against the frozen protocols, the known over-estimate cases listed with their bound, and any defect fixed minimally (or reported if the fix is larger than a few lines). The reviewer is a fresh agent, not the author of EV-8, EV-9 or EV-10.
- Out (explicitly):
  - New metrics. Using `passage_excerpt_hit` inside the strata tables (only if the review shows the member rule disagrees materially). Reading any real corpus database, any GPU or service.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `scripts/eval_strata_report.py`
- `scripts/test_eval_strata_report.py`
- `docs/eval-reports/<run-date>-eval-strata-report-review.md`

**Commits** (① is a stub, committed before any real work):
① stub: review-note skeleton listing every metric and the hand-computed expected table, committed before the script is run against it
② hand-computed example test (red where the script disagrees, green where it agrees) and the dry run on the bundle's fake rows
③ fixes for any defect found (omitted if none), each with its own test
④ review note final: per metric 'matches protocol' or 'deviates: how and by how much'

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check scripts/eval_strata_report.py scripts/test_eval_strata_report.py`
- `conda run -n agent-rag-research python scripts/eval_strata_report.py --help` still works
- Mutation proof: change one hand-computed literal and watch the test fail

**Acceptance / falsification criterion.** The script's output equals the hand-computed value for every metric of the example; the dry run on rows with the new fields succeeds; the review note gives each metric a verdict. Falsified if any hand-computed value differs from the script's output and the difference is not an explicitly documented rule of the script.

**Gates / depends on.** Depends on: EV-9. Gates: EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic work; no Opus-level design adjudication is needed.

**Risk and rollback.** A defect found late changes the reporting rule after rows exist. Mitigation: the review is a prerequisite of EV-16, before any real row exists. Rollback: revert; the script is post-processing only.

**Docs to update in the same PR.** The review note is a new doc (section 7 doc-map row, REFERENCE). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

### W2 first GPU session, measurements only

#### EV-16: Run the frozen main-corpus baselines (papers, books, legacy)

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-16-baseline-main-corpus.md`.

**Review cross-reference:** S-16. **Wave:** W2 first GPU session, measurements only.

**Baseline commit freeze (step of this ticket, not a separate ticket).** Before launch the orchestrator records the integration-branch head as `baseline_commit`; all code used by EV-16, EV-17 and EV-18 is that exact commit (run worktree checked out at it); the SHA is written into the stub and into every run's MANIFEST and output directory; nothing in the pre-baseline rule's list (plan section 4, rule 16) merges into the integration branch until the EV-18 report is merged.

**Why.** No baseline exists for the new papers-passage and causal-books sets, and every later A/B needs a measured reference on the same code and index; the first run is also the only moment the TEI truncation limit can be confirmed with one `/info` request (review S-16). Plain BM25 already reaches 0.96-0.98 paper recall on these sets, so only passage level and the title-ablated arm can show headroom (RV-3 F-1.3).

**Scope.**
- In:
  - Freeze the baseline commit (see above) and verify the strata-report instrument was reviewed (EV-6b merged) before any number is read.
  - Run `run_baseline_main.sh papers books legacy` exactly as the GPU-day runbook step 1a specifies (about 654 queries, estimated 20-40 min), as a detached process (LESSONS section 7.3); then the BM25 floor (EV-15) beside it, the title-ablated arm and the strata report (EV-6, reviewed by EV-6b).
  - One `/info` request to the embedder to confirm its truncation limit; record the value.
  - Report unmodified as a dated baseline document: passage-level headline (member-passage hit@10 and P@1, plus `passage_excerpt_hit`), paper recall as tripwire only, per-stratum Wilson intervals, `authority`/`edition`-style small strata labelled descriptive.
- Out (explicitly):
  - Any A/B or config change (later tickets). The focus set (EV-17) and standards (EV-18). Re-grounding or editing a fixture. Quoting a precision-95 headline number (operator question F8).
  - Baselines for the Motional, Waabi and Waymo corpora: none is planned (plan section 9).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-main-baseline.md`
- `docs/eval-reports/data/<run-date>-main-baseline/`
- `docs/eval-reports/data/2026-11-10-papers-passage-gt/runs/ (own stamp only)`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton citing the frozen main-corpus protocol and the stop conditions; hash file revision recorded; `baseline_commit` frozen (integration head SHA), recorded here, and the run worktree checked out at exactly that SHA
② detached run launched; MANIFEST committed when it starts (start time, collection, db, `baseline_commit`, fixture hashes)
③ raw reports copied into the data dir with `n_errors` and `run_valid` shown
④ BM25 floor and title-ablated arm
⑤ report written; every number carries {metric, fixture, arm, pool depth, config}

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research python -m app.doctor --no-auto-start` exits 0 before and after
- Run scripts print `check-hash` and `check-points` passes; the report's `ground_truth_sha256_12` equals the hash file's entry
- `n_errors` is 0 and `run_valid` is true in every report (else the arm is invalid and is not read)
- `git rev-parse HEAD` in the run worktree equals the recorded `baseline_commit` before and after the run, and the SHA appears in every output directory

**Acceptance / falsification criterion.** Per set (never averaged): passage-level hit@10 and P@1 with Wilson intervals, the BM25 floor beside it, the title-ablated paper recall, and stratum tables; the report hash equals the frozen hash; zero errors. The ceiling for each metric is printed with it (member hit@10 ceiling 1.00; paper recall tripwire headroom at most 2 items on the legacy 210-set). Every output carries the `baseline_commit` SHA. Falsified (run discarded) if a hash or point-count check fails, the recorded SHA differs from the code that ran, or any error is a lock timeout.

**Gates / depends on.** Depends on: EV-7, EV-8, EV-9, EV-10, EV-11, EV-15, EV-6b. Operator answers: F3. Gates: CQ-7 (parked), EV-17, EV-18, EV-20, EV-19 (parked), EV-21 (parked), EV-22 (parked), CQ-18 (parked), RQ-3 (parked).

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free of the foreign model process (operator question F3); about 20-40 min GPU (estimate, not measured).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A foreign GPU holder or a held lock starves the run. Mitigation: EV-10 invalidates a starved run (and `app.doctor`, if OP-5 has merged, names the holder); one GPU job at a time. The run only reads. Rollback: discard the run directory.

**Docs to update in the same PR.** The dated baseline report is the doc (section 7 doc-map row); section 3 ledger entry carries the `baseline_commit` SHA. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-17: Run the frozen topic-focus baseline

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-17-baseline-topic-focus.md`.

**Review cross-reference:** S-16. **Wave:** W2 first GPU session, measurements only.

**Why.** Whether off-topic papers enter the top ten for realistic questions is unmeasured: 37.4% of main-corpus papers are off-topic (labels audited at weighted kappa 0.90) and nothing has ever measured how often they surface in answers (review section 4 'Unknown'). The frozen topic-focus protocol defines the instrument; its fixture hash is null until authoring ends.

**Scope.**
- In:
  - Run the `focus` mode of the main baseline script (about 50 queries, estimated 2-5 min) once EV-4b (the repair of EV-4's focus fixture, which found 18 of 26 collision questions without their collision term and 6 of 10 weak absent items) has re-frozen the focus fixture hash in the hash file; the run uses the same `baseline_commit` as EV-16 (recorded in its MANIFEST); report off-topic share in the top 10 with its interval, `offtopic-legit` paper recall, and the control arms, per the frozen protocol.
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

**Acceptance / falsification criterion.** Report states off-topic share in the top 10 on the focus set with a Wilson interval, per question dimension, never averaged with the other sets, with the control arms' values beside it; its fixture hash matches EV-4b's frozen hash and its MANIFEST `baseline_commit` equals EV-16's. The ceiling and floor arithmetic of the protocol are printed with each metric. Falsified (not read) if the hash was null at launch or any error occurred.

**Gates / depends on.** Depends on: EV-16 (GPU-serial order and the shared baseline commit). In-progress tickets on other branches (merge order or inputs): EV-4b. Operator answers: F3. Gates: RQ-2 (parked), RQ-3 (parked).

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); focus fixture authoring finished and hash frozen (EV-4b).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Fixture hash still null: the script refuses to run, which is the intended guard. Rollback: discard run directory.

**Docs to update in the same PR.** The dated focus baseline report is the doc (section 7 doc-map row); the off-topic share goes to section 6 as an open measured number. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-18: Run the frozen standards baseline and evaluate the structure gate

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-18-baseline-standards.md`.

**Review cross-reference:** S-16, S-24 gate. **Wave:** W2 first GPU session, measurements only.

**Minimizer note.** The gate count here is the single trigger for parked CQ-8, CQ-12, CQ-13, CQ-14 and CQ-16 (count of 5 or more); the authority-stratum result is the trigger for parked CQ-19. Report both explicitly.

**Why.** The standards corpus (119 documents, 35,714 chunks, built with the new bounded chunker) has never been measured by any fixture; the standards protocol freezes a depth decision rule (D-1) and a falsifier (S-1) to be evaluated from this one run, and the review gates the whole standards structure bundle (CQ-12 to CQ-16) on a count taken from it (review S-24).

**Scope.**
- In:
  - Run `run_baseline.sh` exactly as GPU-day runbook step 1c specifies (about 1,198 queries across depth 128/32/64 and fused/dense/sparse arms plus ablations and controls; estimated 1-2 h), detached; BM25 floor and per-stratum tables beside it; evaluate D-1 and S-1 as written.
  - Gate evaluation for CQ-12: count answerable misses whose gold chunk or top-10 chunk has a furniture, numeric or NOTE root, or a split table (mechanical rules from `scripts/chunk_quality_census.py` and RV-2 F-2.5), and state whether the count reaches 5.
  - Run at EV-16's `baseline_commit` (recorded in the MANIFEST). Every per-question row must carry `retrieved_chunk_ids` (EV-9); the gate count is printed together with the list of qualifying questions.
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

**Acceptance / falsification criterion.** Verdicts for D-1 and S-1 are mechanical and quoted from the protocol; the structure-gate count is a number with the list of qualifying questions and the per-row chunk ids they rest on; the MANIFEST `baseline_commit` equals EV-16's; per-stratum intervals shown with edition/authority marked descriptive; no fixture averaged. Falsified (run not read) if the repeat arm disagrees beyond the envelope or any error occurs.

**Gates / depends on.** Depends on: EV-16 (GPU-serial order and the shared baseline commit), EV-9 (chunk ids in rows), EV-11, EV-15. Operator answers: F3. Gates: CQ-19 (parked), CQ-8 (parked), RQ-1 (parked), EV-20, EV-19 (parked), EV-21 (parked), EV-22 (parked), CQ-12 (parked), CQ-13 (parked), CQ-14 (parked), CQ-16 (parked), CQ-18 (parked), RIDER-1.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 1-2 h GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Longest read-only job of the session; a mid-run foreign GPU grab invalidates it. Mitigation: detached, validity arm, `run_valid`. Rollback: discard.

**Docs to update in the same PR.** The dated standards baseline report is the doc (section 7 doc-map row); the D-1 and S-1 verdicts go to section 5 or 6. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-20: Run the depth grid (32 versus 128) on papers and books, only if headroom allows

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-20-depth-weight-grid.md`.

**Review cross-reference:** S-19. **Wave:** W2 first GPU session, measurements only.

**Cut by minimizer:** 1,200 queries and 40-90 min of GPU against weak, sign-flipping prior evidence is cut to depth 32 versus 128 at weight 0.5 on the papers and books sets only; standards (depth already decided by D-1 from EV-18's depth arms) and Waymo drop; the weight arms wait. It runs only if that set's passage hit@10 in EV-16 leaves at least 6 items of headroom. The EV-19 -> EV-20 edge is cut (EV-19 is parked).

**Why.** Rerank depth and dense weight differ per corpus (standards depth 128; Waymo weight 0.7; others 32 and 0.5) with no recorded reason, and the existing measurements are single-question effects with the sign flipping between fixtures (RV-1 F-1.5, review S-19). The evidence that the settings matter is weak; the evidence that they differ for a reason is absent.

**Scope.**
- In:
  - Precondition (stated in commit 1, checked from EV-16's report): a set is run only if its passage hit@10 leaves at least 6 items of headroom (answerable items minus member-passage hits at 10); if neither set does, close the ticket by that gate with the numbers.
  - Arms: depth 32 versus depth 128 at dense weight 0.5 on the papers-passage and causal-books sets, each on its own fixture; arms already measured in the baselines are not repeated; paired flips via `scripts/nb_xp_deeppool_tables.py` with its jitter envelope.
  - Rule G-1 as already frozen in the runbook: a candidate arm is believed only with net member-passage hit@10 of at least +3 on that corpus's own fixture, wins:losses at least 3:1, no gating stratum (n at least 10) losing more than 1, and the same sign on the title-ablated arm.
- Out (explicitly):
  - Standards and Waymo grids; dense-weight arms 0.7 and 1.0 (they wait for a reason to run them). Reopening the standards depth question (D-1 decides it).
  - Changing any default (a verdict here is a recommendation; a default change needs sign-off and goes through RIDER-1 or a config edit the operator approves). The review's fallback 'otherwise set everything to 32/0.5' is NOT part of G-1: see risk.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-depth-weight-grid.md`
- `docs/eval-reports/data/<run-date>-depth-weight-grid/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton quoting rule G-1, the 6-item headroom precondition with the numbers from EV-16, and the unresolved difference with the review (see risk); pre-registered, no metric, threshold or fixture changes afterwards (dated addendum only)
② arms run one at a time (cheapest first); MANIFEST per arm, each recording the baseline commit SHA
③ flip tables per set with the jitter envelope
④ report: verdict per set (or closed by the headroom gate)

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Each arm names `--collection`, `--db-path`, `--blob-dir` explicitly
- Both fixtures (or all of a corpus's fixtures) are reported separately, never averaged

**Acceptance / falsification criterion.** Per set (papers, books): the flip table and the G-1 verdict (or the headroom gate that closed it); no default changes unless G-1 holds; the ceiling for 'net +3' is shown per fixture (n answerable). Falsified if the baseline arm repeated here differs from the EV-16/EV-18 arm beyond the jitter envelope (then the grid is not interpretable).

**Gates / depends on.** Depends on: EV-16, EV-18. Operator answers: F3. Gates: none.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); GPU time is not estimated here (a fraction of the original 40-90 min grid; the first run replaces any estimate).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** The review (S-19) says that if no arm wins, reset all corpora to 32/0.5; the runbook's frozen rule G-1 says defaults stay. The EV-20 stub commit must state which applies; default is G-1 as frozen, because resetting is a config change needing sign-off and a frozen rule changes only by dated addendum. Rollback: n/a (read-only).

**Docs to update in the same PR.** The grid report is the doc (section 7 doc-map row); a verdict goes to section 5 (tried) or 6 (open). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

### W4 rider and what it unblocks

#### RIDER-1: Raise the single foundation rider PR (promote ground-truth sets, reject dead lever, ruff step)

Labels: wave:4-rider, area:ops, area:eval, area:retrieval, needs-signoff, size:M. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/RIDER-1-foundation-signoff-rider.md`.

**Review cross-reference:** review (D), RV-5 F-5.6, RV-3 F-1.11, RV-6 F-A5, RV-1 F-1.10. **Wave:** W4 rider and what it unblocks.

**Cut by minimizer:** items 3 (`rerank_score` note) and 4 (fake imports `sparse_tokens`) die with parked RQ-4 and RQ-5; item 1 and conditional item 7 exist only if an adopted result needs them. Kept: item 5 (promote the ground-truth sets to `fixtures/eval/` with the invariants test, the drift guard), item 2 (reject the dead `relevance_filter`) and item 6 (ruff step, after F4). Items for adopted results are added by a plan amendment when the result exists.

**Why.** Several adopted changes can only land on protected paths (`contracts/`, `rag/config.py`, `config.example.yaml`, `rag/fakes/`, `fixtures/`, `.github/`), and every unrelated protected-path PR pays the same sign-off toll; batching them into one PR pays it once (`docs/AGENT-OPERATIONS-LESSONS.md` section 6.3). It is raised only after the baselines so no start-up or validation change precedes the frozen baseline commit; items whose source tickets are parked are absent.

**Scope.**
- In:
  - (2) `relevance_filter="embedding"` fails validation until a gate exists (dead lever, RV-5 F-5.6).
  - (5) Promote the three ground-truth sets to `fixtures/eval/` with one parametrised invariants test (unique ids, strata vocabulary, no gold on absent items, 6-word rule, excerpt verbatim in the live database with a skip when absent) and the SHA-256 in each set's metadata (RV-3 F-1.11), after the hash lock.
  - (6) `.github/`: a `ruff` step in CI and the nightly real-adapter workflow labelled manual-only (RV-6 F-A5).
- Out (explicitly):
  - Items 1, 3, 4 and conditional item 7 (their sources are parked or cut; each returns only by a plan amendment citing an ADOPT verdict). The `chunker_id` migration (not doing). Any logic change beyond the listed edits. Pushing to the default branch or merging (human only).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `contracts/config.py`
- `rag/config.py`
- `fixtures/eval/`
- `.github/workflows/ci.yml`
- `.github/workflows/nightly-real-adapters.yml`

**Commits** (① is a stub, committed before any real work):
① stub: PR description draft listing each item, its source and the operator decision it needs; empty diff
② item (5) (promotion and invariants test)
③ item (2) (validation of the dead lever)
④ item (6)
⑤ local enforcement transcript with the `foundation-change` label noted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check contracts/config.py rag/config.py`
- Mutation proof for the invariants test: edit one question in a copy and watch it fail

**Acceptance / falsification criterion.** One PR only; every protected-path edit is traceable to a listed item; the invariants test passes on the three promoted sets and fails when one question is altered; the PR carries the `foundation-change` label and waits for the operator's merge. Falsified if the PR touches any protected path not listed.

**Gates / depends on.** Depends on: EV-11 (hash lock before promotion), EV-18 (pre-baseline rule: no validation change before the last baseline). Operator answers: F4. Gates: RQ-4 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: y: this ticket IS the sign-off request; the operator merges (never an agent); operator answers: F4, F7 · re-embed: n. Also: operator sign-off and merge; push of the local commits so CI can judge them (F4).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Item 2 changes config validation (a start-up behaviour), so the ticket is sequenced after the last baseline (pre-baseline rule, plan section 4). A broad rider is slow to review; this one is small. Rollback: revert the merge (single PR).

**Docs to update in the same PR.** DATA-CONTRACTS is untouched by the kept items; the PR description is the record. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

### W3 gated changes after baselines

No active tickets. Every W3 ticket is parked (section 8A).

## 8A. Parked — do not start

These tickets stay in the plan but are not to be started, posted as issues or dispatched until their trigger holds (status `PARKED` in BACKLOG; issue files in `parked/` with a `Parked-until:` line). A trigger is a checkable condition on a baseline result or a named decision; the kill criteria are the minimizer's W3 list, applied the moment the baseline numbers arrive (a ticket whose kill criterion holds is closed with the report that shows it). Where the minimizer said 'defer until X', X is the trigger. Merged tickets: CQ-19 absorbs CQ-20; CQ-16 absorbs CQ-15; CQ-18 absorbs CQ-17. CQ-13 is a SHRINK verdict placed here because it depends on parked CQ-12 (section 11). Parked tickets keep the wave label of the original plan.

GPU-serial ordering edges that existed between parked tickets (EV-20 -> EV-21, EV-21 -> EV-22, CQ-16 -> CQ-18, RQ-3 -> CQ-10) are not dependencies: if two parked tickets are both started they run one at a time on the card, nothing more.

| id | title | start only if / only after (checkable) | kill criterion | depends on |
|---|---|---|---|---|
| CQ-19 | Author 38 more standards ground-truth items for the weak stratum (authority or edition) | start only if EV-18 shows authority-stratum hit@10 clearly below the other standards strata (at least 2 of the 4 current authority items missing at hit@10 while the other strata are strong); author only the stratum that is weak (the edition half, absorbed from CQ-20, is started only if the edition stratum is the weak one). | killed if no standards stratum is visibly weak in EV-18. | EV-11, EV-18 |
| CQ-7 | Build a ligature-repaired clone of the main collection on CPU | start only if EV-16's per-stratum rows show damaged-gold passage hit@10 at least 10 points below clean-gold passage hit@10, or at least 5 damaged-gold misses (computable from EV-16 rows, no extra GPU); and operator answer F2 (vector store up) and OP-4 done. | none listed by the minimizer; the trigger is the gate. | OP-4, EV-16, F2, F3 |
| CQ-8 | Make rechunk re-embed only chunks whose text changed | start only if EV-18's structure-gate count is 5 or more (its sole consumer is CQ-16). | killed if EV-18's count is below 5. | EV-18 |
| EV-12 | Amend the CQ-3 stub A/B pre-registration (fixtures, minimum effect) | only after the decision to commission EV-21 (it is a pure prerequisite of EV-21). | killed with EV-21. | EV-9, EV-11 |
| EV-13 | Capture cross-encoder scores and build the absence census tool | only after an abstention feature is commissioned by the operator and at least 60 distinct absent items exist (the sets hold 9-24). | killed if no abstention feature is commissioned. | RQ-1 |
| OP-2 | Construct the vector index lazily so the server starts without it | only after the operator needs the MCP server to start with the services down. | none. | OP-5, OP-6, MC-3 |
| RQ-1 | Fix three one-line retrieval defects (payload, partial rerank, cap) | only after EV-16, EV-17 and EV-18 are merged (the baseline commit is then released); it is the first post-baseline change and must be verified byte-identical against the real-index baseline rows. | none; if the byte-identical check fails it is not merged. | EV-18 |
| RQ-2 | Add an opt-in, default-off relevance demotion to the Retriever | start only if EV-17's off-topic top-10 share exceeds the operator's F6 bar (the share and a first demotion estimate are computable offline from EV-17 rows plus `relevance_score`). | killed if EV-17's share is below the bar. | RQ-1, EV-10, EV-17, F6 |
| RQ-5 | Extract one shared sparse_tokens() used by the index | only after the CQ-18 trigger holds (the sparse arm is shown to matter, see CQ-18). | killed with CQ-18. | RQ-1 |
| EV-19 | Run the reranker-score census on the absent arms | only together with EV-13 (same condition: abstention commissioned and 60+ distinct absent items). | the census closes the RQ-4 gate: RQ-4 dies if the census CI contains 0.5 on two of three sets. | EV-13, EV-16, EV-18, F3 |
| EV-21 | Run the amended CQ-3 stub-filter A/B | start only if baseline rows (with chunk ids) show a stub at rank 1 on at least 3 answerable items on some set; needs EV-12 and operator answer F3. | killed if the stub-at-rank-1 count is below 3 on every set. | EV-12, EV-9, EV-16, EV-18, F3 |
| EV-22 | Run the ligature-repair A/B on the repaired clone | start only if the damaged-gold stratum shows a gap (CQ-7's trigger holds and CQ-7 is done); needs F3. | killed with CQ-7. | CQ-7, EV-16, EV-18, F3 |
| CQ-12 | Add golden tests and rules to the section tracker (standards) | start only if EV-18's structure-attributable miss count is 5 or more. | killed if the count is below 5 or standards passage hit@10 leaves under 5 items of headroom. | EV-18 |
| CQ-13 | Add the running-furniture pre-pass (standards) | start only after CQ-12 has run and its in-memory re-derive leaves furniture roots among the qualifying-miss questions. | killed if zero furniture roots remain among the qualifying-miss questions. | CQ-12, EV-18 |
| CQ-14 | Fold heading-only chunks into the next group and guard normalisation regexes | only after the EV-21 verdict; the regex guard only if CQ-16 proceeds. | killed if EV-21 is REJECT, or stub-at-rank-1 occurs on fewer than 3 answerable standards items, or fewer than 3 qualifying misses have a stub in the top 10. | EV-18, EV-21 |
| CQ-16 | Rebuild the standards clone from re-derived paths and measure it against baseline (absorbs CQ-15) | start only if EV-18's structure-attributable miss count is 5 or more (net +3 must be reachable); the CQ-15 half (clone rebuild) also needs F2, F3 and F7. | killed if the EV-18 count is below 5 or the rebuilt clone shows fewer than 3 flipped questions; the CQ-15 half is killed if CQ-12, CQ-13 and CQ-14 are all killed, or F7 says keep stored paths and the operator will not pay the 35k re-embed. | CQ-12, CQ-13, CQ-14, CQ-8, EV-18, F2, F3, F7 |
| CQ-18 | Add BM25 weighting behind a flag and run the A/B on a repaired clone (absorbs CQ-17) | start only if on some set fused minus dense-only passage hit@10 is 3 items or more AND sparse-only passage hit@10 is more than 3 items from the plain-BM25 floor on that set (the sparse arm matters and is not merely BM25); needs F2 and F3, and a repaired base if EV-22 ran. | killed if on every set fused minus dense-only passage hit@10 is 2 items or fewer, or sparse-only is within 3 items of the BM25 floor on every set, or EV-22 shows ligature repair itself changed the sparse arm so that attribution is muddied and no gain remains. | RQ-5, EV-22, EV-16, EV-18, F2, F3 |
| CQ-9 | Add idempotent payload indexes and verify them on a clone | start only if EV-14 reports overlap below 0.99 on at least one of the three filters. | killed if EV-14 overlap is at least 0.99 on all three filters, or no baseline query returned fewer than k hits. | EV-14, RQ-5, RQ-1, F2 |
| MC-4 | Slim the MCP wire by projecting duplicated envelope fields away | start only if F5 = yes AND MC-3 telemetry shows agents lowering the default k. | killed if F5 = no, or MC-3 telemetry shows default-k calls are not lowered, or a standards k=10 response (about 4.2k tokens) is acceptable to the operator. | MC-3, F5 |
| RQ-3 | Run the relevance-demotion arms on the focus and passage sets | start only if EV-17's off-topic top-10 share exceeds the operator's F6 bar; needs RQ-2 built and F3. | killed if EV-17's share is below the bar, or an offline demotion on EV-17 rows (using `relevance_score`) removes under 50% of off-topic top-10 slots or drops any gold on papers-passage or books. | RQ-2, EV-16, EV-17, F3, F6 |
| RQ-4 | Expose the cross-encoder score in result metadata | only after an abstention feature is commissioned, the EV-19 census gate can open (60+ distinct absent items) and RIDER-1 has landed. | killed if the EV-19 census CI contains 0.5 on two of three sets. | RIDER-1, EV-19, RQ-1 |

#### CQ-19: Author 38 more standards ground-truth items for the weak stratum (authority or edition)

Labels: wave:1-no-gpu, area:eval, area:corpus, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-19-standards-authority-items.md`.

**Review cross-reference:** CQ-5 follow-up. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: start only if EV-18 shows authority-stratum hit@10 clearly below the other standards strata (at least 2 of the 4 current authority items missing at hit@10 while the other strata are strong); author only the stratum that is weak (the edition half, absorbed from CQ-20, is started only if the edition stratum is the weak one). Kill criterion: killed if no standards stratum is visibly weak in EV-18.

**Absorbs CQ-20** (CQ-20: Author 38 more standards edition-stratum ground-truth items). The merged ticket is one unit: author only the stratum that is visibly weak in the EV-18 baseline (the other half is not started); the two halves are sequenced on the shared hash file only.

**Why.** The authority stratum has 4 items (Q-STD-C-019..022), so any filter or tag effect is description only: with n=4 the best possible exact McNemar p is 0.125 and can never reach 0.05. CQ-5's pre-registered measurement (`docs/eval-reports/2026-11-10-cq5-standards-metadata.md` section 5) computes 42 items per stratum for a 30-point difference at alpha 0.05, power 80%, planning disagreement 0.5, so 38 more are needed. Absorbed from CQ-20: The edition stratum also has 4 items (Q-STD-A-021/022, B-021/022); same arithmetic as CQ-19: 42 per stratum needed, 38 to add (`docs/eval-reports/2026-11-10-cq5-standards-metadata.md` section 5). Edition questions are where BM25 scores 0.00 chunk@10 on n=4 (RV-3), so the stratum is the one that would show whether the standards metadata tags help.

**Scope.**
- In:
  - Author 38 new authority-stratum items from many different documents (the current four rest on four), phrased as a user would without hinting the tag, under the existing blind two-author plus cross-verification regime and `gt_tools.py verify`; recorded as a separate extension file with its own hash entry, dated addendum first.
  - Absorbed from CQ-20: Author 38 edition-stratum items (some naming an edition, some not, from many documents with superseded and current editions), same regime and extension-file procedure as CQ-19.
- Out (explicitly):
  - Running retrieval on them. Any change to the 128 existing items. The tag filters (CQ-5, done).
  - Absorbed from CQ-20: Running retrieval. Changing existing items. Using `status:current` as a filter in the design (excluded by CQ-5 because the gold documents may be superseded).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<date>-standards-gt-authority-extension/`
- `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`
- `docs/eval-reports/data/<date>-standards-gt-edition-extension/`

**Commits** (① is a stub, committed before any real work):
① stub: addendum and authoring protocol copy (strata definition, no-hint rule, hash procedure), before any item is written
② author A and author B draft files, blind to each other
③ cross-verification report with kills and fixes counted
④ adjudicated extension file, `verify` transcript and hash entry
⑤ [absorbed CQ-20] stub: addendum with the stratum definition and the named/unnamed edition quota
⑥ [absorbed CQ-20] author A and author B draft files
⑦ [absorbed CQ-20] cross-verification report
⑧ [absorbed CQ-20] adjudicated extension file, `verify` transcript and hash entry

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research python docs/eval-reports/data/2026-11-10-standards-gt/gt_tools.py verify <extension file>` passes (read-only against the standards database)
- Count of distinct source documents printed (target: at least 20)
- `conda run -n agent-rag-research python docs/eval-reports/data/2026-11-10-standards-gt/gt_tools.py verify <extension file>` passes

**Acceptance / falsification criterion.** 38 items pass verbatim-excerpt verification, 0 reuse a 6-word run of the excerpt, come from at least 20 distinct documents, are cross-verified by a reader other than the authors, and their SHA-256 is in the hash file before any run reads them. Falsified if any item fails `verify` or an excerpt is not verbatim in the stored chunk.

Absorbed from CQ-20: Same as CQ-19: 38 verified, cross-verified, hashed items from at least 20 documents, hash recorded before any run reads them. Falsified if any item fails `verify`.

**Gates / depends on.** Depends on: EV-11, EV-18. Gates: none.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Same-model-family authors and verifiers (0 kills on standards so far): residual defects are possible; the stratum stays labelled LLM-authored. Rollback: drop the extension file and its hash entry.

**Docs to update in the same PR.** The addendum and extension file are the docs (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### CQ-7: Build a ligature-repaired clone of the main collection on CPU

Labels: wave:1-no-gpu, area:corpus, needs-services, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-7-ligature-resparse-clone-cpu.md`.

**Review cross-reference:** S-17. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: start only if EV-16's per-stratum rows show damaged-gold passage hit@10 at least 10 points below clean-gold passage hit@10, or at least 5 damaged-gold misses (computable from EV-16 rows, no extra GPU); and operator answer F2 (vector store up) and OP-4 done. Kill criterion: none listed by the minimizer; the trigger is the gate.

**Why.** CQ-1 repairs ligature damage in the sparse arm but is deliberately not applied to any index, and CQ-2 added `app.resparse` to recompute sparse vectors without re-embedding. The A/B (EV-22) needs a repaired clone to exist, and the whole preparation is CPU-only, so it can run while the GPU is held by another process (GPU-day runbook step 5.1). About 35% of main-corpus chunks change; resparse time is unmeasured.

**Scope.**
- In:
  - Clone the main collection with `VectorIndex.clone_points_into` into a new scratch collection, then `app.resparse --collection <scratch> --target-is-clone --clone-of <live> --apply` after a dry run, following `docs/eval-reports/2026-11-10-cq2-index-maintenance.md`. Record measured resparse time and the sparse-staleness sample before and after.
- Out (explicitly):
  - Touching the live collection (read-only source only). The A/B (EV-22). Any BM25 weighting (CQ-18). Deleting the clone: EV-22 does that when done.

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

**Gates / depends on.** Depends on: OP-4, EV-16. Operator answers: F2, F3. Gates: EV-22 (parked).

**Needs.** GPU: n · services up: vector store (CPU container) up; no GPU services · operator sign-off: n (no protected path is touched); operator answers: F2 · re-embed: n. Also: vector store start approved (F2); 6-8 GB free for the clone.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Applying resparse to the live collection by mistake (the documented CQ-1 deployment hazard). Mitigation: `--target-is-clone` guard, explicit `--collection` on every command, live collection read-only. Rollback: delete the scratch collection.

**Docs to update in the same PR.** The CQ-2 operating note is the reference and the dated record is the doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### CQ-8: Make rechunk re-embed only chunks whose text changed

Labels: wave:1-no-gpu, area:corpus, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-8-rechunk-reuse-vectors-by-text-hash.md`.

**Review cross-reference:** S-14. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: start only if EV-18's structure-gate count is 5 or more (its sole consumer is CQ-16). Kill criterion: killed if EV-18's count is below 5.

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

**Gates / depends on.** Depends on: EV-18. Gates: CQ-16 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A wrongly reused vector silently pairs old text with a new position. Mitigation: vectors depend only on the embedded text (which includes title and section path prefix), guarded by model name. Rollback: revert.

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-12: Amend the CQ-3 stub A/B pre-registration (fixtures, minimum effect)

Labels: wave:1-no-gpu, area:eval, size:S, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/EV-12-cq3-preregistration-addendum.md`.

**Review cross-reference:** S-05. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: only after the decision to commission EV-21 (it is a pure prerequisite of EV-21). Kill criterion: killed with EV-21.

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

**Gates / depends on.** Depends on: EV-9, EV-11. Gates: EV-21 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (not a protected path); the amended rule is a decision for the operator in PR review. · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. An addendum cannot undo a result already seen; ordering is enforced by dependency. Rollback: revert.

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-13: Capture cross-encoder scores and build the absence census tool

Labels: wave:1-no-gpu, area:eval, area:retrieval, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/EV-13-rerank-score-capture-and-census.md`.

**Review cross-reference:** S-04. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: only after an abstention feature is commissioned by the operator and at least 60 distinct absent items exist (the sets hold 9-24). Kill criterion: killed if no abstention feature is commissioned.

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

**Gates / depends on.** Depends on: RQ-1. Gates: EV-19 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Adding a method to a real adapter widens its surface. Mitigation: documented experiment-only; fakes are untouched (protected). Rollback: revert.

**Docs to update in the same PR.** Section 2: new `app/` entry point. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### OP-2: Construct the vector index lazily so the server starts without it

Labels: wave:1-no-gpu, area:ops, area:mcp, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/OP-2-lazy-vector-index-construction.md`.

**Review cross-reference:** S-07. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: only after the operator needs the MCP server to start with the services down. Kill criterion: none.

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

**Gates / depends on.** Depends on: OP-5, OP-6, MC-3 (ordering only: shared `app/serve.py`). Gates: none.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Misconfiguration (wrong collection) surfaces on first search instead of at startup. Mitigation: doctor still checks the pairing (OP-6); the first-use error names the collection. Rollback: revert; behaviour returns to eager construction.

**Docs to update in the same PR.** Section 2: serve behaviour. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### RQ-1: Fix three one-line retrieval defects (payload, partial rerank, cap)

Labels: wave:1-no-gpu, area:retrieval, size:S, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-1-three-retrieval-one-liners.md`.

**Review cross-reference:** S-09. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: only after EV-16, EV-17 and EV-18 are merged (the baseline commit is then released); it is the first post-baseline change and must be verified byte-identical against the real-index baseline rows. Kill criterion: none; if the byte-identical check fails it is not merged.

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

**Gates / depends on.** Depends on: EV-18. Gates: EV-13 (parked), RQ-2 (parked), RQ-5 (parked), CQ-9 (parked), RQ-4 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Narrowing the payload could break a reader that silently used another field. Mitigation: the grep and the identical-hits test. Rollback: revert (three independent commits).

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### RQ-2: Add an opt-in, default-off relevance demotion to the Retriever

Labels: wave:1-no-gpu, area:retrieval, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-2-opt-in-relevance-demotion.md`.

**Review cross-reference:** S-21. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: start only if EV-17's off-topic top-10 share exceeds the operator's F6 bar (the share and a first demotion estimate are computable offline from EV-17 rows plus `relevance_score`). Kill criterion: killed if EV-17's share is below the bar.

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

**Gates / depends on.** Depends on: RQ-1, EV-10 (ordering only: same file, not a data dependency), EV-17. Operator answers: F6. Gates: RQ-3 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Demotion acts on the already-truncated pool and can starve it (a pool 40% off-topic still leaves about 19 of 32; RV-1 F-1.4). Mitigation: default off; RQ-3 reports `Coverage` pool sizes. Rollback: revert; nothing depends on it until RIDER-1.

**Docs to update in the same PR.** Section 2: the new eval flag; no contract or Config change here. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### RQ-5: Extract one shared sparse_tokens() used by the index

Labels: wave:1-no-gpu, area:retrieval, size:S, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-5-shared-sparse-tokens.md`.

**Review cross-reference:** none: RV-1 F-1.10, prerequisite of RIDER-1 item 4. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: only after the CQ-18 trigger holds (the sparse arm is shown to matter, see CQ-18). Kill criterion: killed with CQ-18.

**Why.** The fake vector store keeps its own `lower().split()` (`rag/fakes/fake_vector_store.py:131`) while the real index tokenizes and repairs ligatures in `_sparse_vector`, so a tokenizer change cannot fail any fake-backed test (review item h residual risk 2; RV-1 F-1.10). RIDER-1 item 4 makes the fake import a shared function, but that function must exist first and it is not a protected path.

**Scope.**
- In:
  - A small pure module (no vendor import, so vendor isolation holds) exposing `sparse_tokens(text)`, containing exactly today's behaviour including CQ-1's ligature repair, imported by `VectorIndex._sparse_vector`.
  - A test that pins the checksum of `rag/ligature_map.json` so the map cannot drift silently (review section 2, CQ-1: no test pins it).
- Out (explicitly):
  - Any tokenizer behaviour change (edge-punctuation stripping and BM25 weighting are CQ-18). Editing the fake (RIDER-1). A filter-parity test against an in-memory vector store (RV-1 F-1.10 part 2, not carried by the review).

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

**Gates / depends on.** Depends on: RQ-1. Gates: CQ-18 (parked), CQ-9 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Extraction subtly changes tokens, which would silently desynchronise stored sparse vectors from query tokens. Mitigation: the identical-vectors check. Rollback: revert.

**Docs to update in the same PR.** Section 2 (new `rag/` module) and the ARCHITECTURE.md module list line, both in this PR. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-19: Run the reranker-score census on the absent arms

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/EV-19-rerank-score-absence-census.md`.

**Review cross-reference:** S-16, S-04. **Wave:** W2 first GPU session, measurements only.

**Parked, do not start.** Parked-until: only together with EV-13 (same condition: abstention commissioned and 60+ distinct absent items). Kill criterion: the census closes the RQ-4 gate: RQ-4 dies if the census CI contains 0.5 on two of three sets.

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

**Gates / depends on.** Depends on: EV-13, EV-16, EV-18. Operator answers: F3. Gates: RQ-4 (parked).

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 15-30 min GPU (estimate).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Small n yields an inconclusive verdict. Mitigation: the rule treats inconclusive as 'gate closed, no change'. Rollback: n/a (read-only).

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-21: Run the amended CQ-3 stub-filter A/B

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/EV-21-stub-filter-ab.md`.

**Review cross-reference:** S-18. **Wave:** W2 first GPU session, measurements only.

**Parked, do not start.** Parked-until: start only if baseline rows (with chunk ids) show a stub at rank 1 on at least 3 answerable items on some set; needs EV-12 and operator answer F3. Kill criterion: killed if the stub-at-rank-1 count is below 3 on every set.

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

**Gates / depends on.** Depends on: EV-12, EV-9, EV-16, EV-18. Operator answers: F3. Gates: CQ-14 (parked).

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 40-80 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A noise flip adopting a filter: prevented by the amended minimum effect. Rollback: n/a (flag only).

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### EV-22: Run the ligature-repair A/B on the repaired clone

Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/EV-22-ligature-resparse-ab.md`.

**Review cross-reference:** S-17. **Wave:** W2 first GPU session, measurements only.

**Parked, do not start.** Parked-until: start only if the damaged-gold stratum shows a gap (CQ-7's trigger holds and CQ-7 is done); needs F3. Kill criterion: killed with CQ-7.

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

**Gates / depends on.** Depends on: CQ-7, EV-16, EV-18. Operator answers: F3. Gates: CQ-18 (parked).

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); the repaired clone exists (CQ-7); about 12-25 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Serving from the clone with the wrong code revision. Mitigation: manifest records revisions; arm B uses the CQ-1 code by design. Rollback: delete the clone.

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### CQ-12: Add golden tests and rules to the section tracker (standards)

Labels: wave:3-gated-change, area:corpus, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-12-section-tracker-rules-and-golden-tests.md`.

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Parked, do not start.** Parked-until: start only if EV-18's structure-attributable miss count is 5 or more. Kill criterion: killed if the count is below 5 or standards passage hit@10 leaves under 5 items of headroom.

**Why.** `_heading_depth` and `_SectionTracker` (`rag/parser.py:457-494`, fed by the unfiltered `text_level >= 2` test at `:539`) are the root cause of stale clause numbers, furniture roots and NOTE/output-line roots in section paths; neither has a unit test. Reproduced today: a path such as `'FOR UL INTERNAL REFERENCE > 6.4.1.2 Risk'`. It is a standards and books problem (1,678 furniture-root chunks in standards against 150 in main), high for standards and low for main (review item c). It cannot fix flat books: the parser emits only levels 1 and 2.

**Scope.**
- In:
  - Golden tests first, pinning the reproduced defects, then rules that reject or renest headings whose text equals the last path component, drop stale numeric markers, and refuse NOTE/output lines as roots; expose the tracker as a pure function over stored blocks so it can be re-run on CPU.
  - Starts only if EV-18's gate count is 5 or more.
- Out (explicitly):
  - Books' chapter structure (needs the PDF outline join; not carried by the review). Rewriting stored `Block.section_path` (operator question F7). Re-embedding (CQ-16).

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

**Gates / depends on.** Depends on: EV-18. Gates: CQ-13 (parked), CQ-16 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A tracker change affects every future parse. Mitigation: no live data is re-parsed here; golden tests pin the rest. Rollback: revert.

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### CQ-13: Add the running-furniture pre-pass (standards)

Labels: wave:3-gated-change, area:corpus, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-13-furniture-prepass-and-table-spans.md`.

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Parked, do not start.** Parked-until: start only after CQ-12 has run and its in-memory re-derive leaves furniture roots among the qualifying-miss questions. Kill criterion: killed if zero furniture roots remain among the qualifying-miss questions.

**Cut by minimizer:** table sup/sub and rowspan/colspan handling is cut (no qualifying miss is attributed to tables; unrelated to furniture). The furniture pre-pass is kept only if CQ-12's in-memory re-derive leaves furniture roots (furniture affects 4.7% of standards chunks and may be fixed by CQ-12's rules). Because it depends on parked CQ-12 it sits in the parked section (interpretation, reported).

**Why.** Running headers promoted to headings are a standards problem and are detectable positionally: 20 of 119 standards documents, 947 blocks, 1,678 chunks (4.7%) have a furniture string as their path root (RV-2 F-2.5).

**Scope.**
- In:
  - Pre-pass in `_build_blocks`: key `(text with digits collapsed, 12-point y bucket)` per page; a text item recurring on at least 4 pages is furniture and skipped before the tracker; also runnable on stored blocks.
- Out (explicitly):
  - Table sup/sub and rowspan/colspan handling (cut). Main-corpus table HTML (not stored). Re-embedding. Persisting `content_list` (not doing).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/parser.py`
- `rag/test_parser.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring for the pre-pass and the 70% / 4-page criteria
② golden tests: a furniture case and a real repeating template heading that must survive
③ pre-pass implementation to green; CPU probe re-run on standards blocks

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/parser.py rag/test_parser.py`
- Positional probe re-run on stored standards blocks reports 0 furniture roots; template headings that repeat at different y survive (RV-2 F-2.5 check)
- `conda run -n agent-rag-research python -m pytest -q rag/test_parser.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Probe finds 0 furniture roots in standards; the real template heading survives. Falsified if the 70% threshold removes a real template heading.

**Gates / depends on.** Depends on: CQ-12, EV-18. Gates: CQ-16 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** False positives delete real headings. Mitigation: y-clustering criterion and the survival test. Rollback: revert.

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### CQ-14: Fold heading-only chunks into the next group and guard normalisation regexes

Labels: wave:3-gated-change, area:corpus, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-14-stub-folding-and-regex-guard.md`.

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Parked, do not start.** Parked-until: only after the EV-21 verdict; the regex guard only if CQ-16 proceeds. Kill criterion: killed if EV-21 is REJECT, or stub-at-rank-1 occurs on fewer than 3 answerable standards items, or fewer than 3 qualifying misses have a stub in the top 10.

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

**Gates / depends on.** Depends on: EV-18, EV-21. Gates: CQ-16 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Folding changes chunk boundaries for every new ingest and invalidates gold chunk ids of re-chunked corpora (scoring uses the excerpt metric). Mitigation: nothing is re-chunked live here. Rollback: revert.

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### CQ-16: Rebuild the standards clone from re-derived paths and measure it against baseline (absorbs CQ-15)

Labels: wave:3-gated-change, area:corpus, area:eval, needs-gpu, needs-services, size:S, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-16-standards-rechunk-verdict.md`.

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Parked, do not start.** Parked-until: start only if EV-18's structure-attributable miss count is 5 or more (net +3 must be reachable); the CQ-15 half (clone rebuild) also needs F2, F3 and F7. Kill criterion: killed if the EV-18 count is below 5 or the rebuilt clone shows fewer than 3 flipped questions; the CQ-15 half is killed if CQ-12, CQ-13 and CQ-14 are all killed, or F7 says keep stored paths and the operator will not pay the 35k re-embed.

**Absorbs CQ-15** (CQ-15: Re-derive standards paths from stored blocks and re-chunk on a clone). The merged ticket is one unit: rebuild the standards clone from the re-derived paths and measure it against the EV-18 baseline in one ticket.

**Why.** Structure fixes are only worth a live re-embed if answers improve: the gate (EV-18) is a count of structure-attributable misses, and the standards fixture is scored by the chunker-independent excerpt metric so old and new chunkers are comparable (review S-24). Absorbed from CQ-15: The structure fixes (CQ-12 to CQ-14) change section paths and chunk boundaries, so they take effect on the existing corpus only through a re-chunk of the standards corpus (about 35k embeds; 477 MB collection); whether stored block paths may be rewritten at all is operator question F7.

**Scope.**
- In:
  - Run the standards GT on live and on the CPU-rebuilt clone, same code, excerpt metric, paired flips by stratum; plus the structural checks (furniture roots 0, stub rate under 2%, bare-number stubs 0).
  - Absorbed from CQ-15: A CPU tool that re-derives section paths from stored standards blocks with the CQ-12/13 functions into a derived column or copy (the default, until F7 is answered), then `app.rechunk` on a database copy and a clone of the standards collection, with CQ-8 reuse, GPU embed of the changed chunks only.
- Out (explicitly):
  - Applying to the live collection (follow-on ticket on ADOPT only; needs F7).
  - Absorbed from CQ-15: Rewriting stored `Block.section_path` in place (needs F7 = rewrite). Live application. Books' outline paths. Measurement (CQ-16).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-standards-rechunk-verdict.md`
- `docs/eval-reports/data/<run-date>-standards-rechunk-verdict/`
- `app/restructure_blocks.py`
- `app/test_restructure_blocks.py`
- `docs/eval-reports/data/<run-date>-standards-rechunk-clone/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton; rule: ADOPT only if net +3 excerpt hits on the standards set, flips at least 3:1, no stratum losing more than 1, and the structural checks pass
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ live and clone arms; MANIFEST
④ report
⑤ [absorbed CQ-15] stub: docstring stating derived-column route, read-only source, clone-only apply
⑥ [absorbed CQ-15] tool with tests on fixtures (idempotent, never writes the source database)
⑦ [absorbed CQ-15] database copy + clone; dry run: counts of changed paths and chunks
⑧ [absorbed CQ-15] apply on the clone; GPU embed time and counts recorded

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command names `--collection` (live and clone separately)
- Gold chunk ids of re-chunked documents are not used for scoring
- `conda run -n agent-rag-research ruff check app/restructure_blocks.py app/test_restructure_blocks.py`
- The tool opens the source `mode=ro` (a write attempt fails in the test)
- `--collection` explicit on every command; the first apply is `--dry-run`

**Acceptance / falsification criterion.** Verdict applies the stated rule; edition and authority strata (n=4 each) are shown as descriptive only. Ceiling: gain bounded by the EV-18 structure-attributable miss count. Falsified if the live arm differs from EV-18's beyond the jitter envelope.

Absorbed from CQ-15: Clone holds re-chunked standards with chunk count and changed-text count equal to the dry run; the live collection and database are byte-unchanged (point count, sampled vectors, file hash of the live database). Falsified if the live database hash changes.

**Gates / depends on.** Depends on: CQ-12, CQ-13, CQ-14, CQ-8, EV-18. Operator answers: F2, F3, F7. Gates: none.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 20-30 min GPU (estimate). Absorbed from CQ-15: GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) (embedder for the clone) · operator sign-off: n (no protected path is touched); operator answers: F2, F3, F7 · re-embed: y (about 35k, standards whole corpus, estimate). Also: GPU free (F3); vector store (F2); operator answer F7 on the section-path route; about 5-15 min GPU (estimate).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Gain unobservable at n=94. Mitigation: UNDERPOWERED is a verdict. Rollback: delete the clone. Absorbed from CQ-15: Mixing the derived column with the stored path in later tooling. Mitigation: derived route documented in the record; nothing live changes. Rollback: delete the clone and the database copy.

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### CQ-18: Add BM25 weighting behind a flag and run the A/B on a repaired clone (absorbs CQ-17)

Labels: wave:3-gated-change, area:corpus, area:eval, needs-gpu, needs-services, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-18-bm25-weighting-ab.md`.

**Review cross-reference:** S-25. **Wave:** W3 gated changes after baselines.

**Parked, do not start.** Parked-until: start only if on some set fused minus dense-only passage hit@10 is 3 items or more AND sparse-only passage hit@10 is more than 3 items from the plain-BM25 floor on that set (the sparse arm matters and is not merely BM25); needs F2 and F3, and a repaired base if EV-22 ran. Kill criterion: killed if on every set fused minus dense-only passage hit@10 is 2 items or fewer, or sparse-only is within 3 items of the BM25 floor on every set, or EV-22 shows ligature repair itself changed the sparse arm so that attribution is muddied and no gain remains.

**Absorbs CQ-17** (CQ-17: Add BM25 saturation and length normalisation to the sparse arm behind a flag). The merged ticket is one unit: the flag-gated implementation and the clone A/B are one ticket; the dependency CQ-9 -> CQ-17 (a file-ownership artefact of `rag/vector_index.py`) is cut.

**Why.** Whether length normalisation and saturation help the sparse arm is unmeasured; a separate A/B keeps attribution clean after the ligature A/B (review S-25). Absorbed from CQ-17: The sparse arm is raw term frequency times IDF with no saturation or length normalisation although its docstring says 'BM25-style' (`rag/vector_index.py:112`); legacy main chunks are unbounded (8,487 chunks over 8,000 characters), so long chunks can dominate (RV-1 F-1.6). A sparse recompute is CPU-only, so bundling it with ligature repair 'to save cost' is wrong and would confound attribution (review S-25).

**Scope.**
- In:
  - On a fresh clone: resparse with the option on (CPU), run the standards, causal-books and papers-passage sets and the lexical strata (standards clause lookups, books terminology) against the live baseline, paired flips.
  - Absorbed from CQ-17: Index-time weight `tf*(k1+1)/(tf + k1*(1-b+b*len/avglen))` behind an explicit option, `avglen` measured once per corpus from stored chunks (CPU) and recorded; applies only when (re)computing sparse vectors (`app.resparse` on a clone); default off.
  - Absorbed from CQ-17: Starts only after EV-22 (S-17 done).
- Out (explicitly):
  - Live application (follow-on on ADOPT only). Combining with any other change.
  - Absorbed from CQ-17: Edge-punctuation stripping in the tokenizer (measured effect on 12-26% of tokens, but it changes tokens; include only if the operator wants it in this A/B: stated as a separate flag, never bundled). Applying to any live collection. The A/B (CQ-18).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-bm25-weighting-ab.md`
- `docs/eval-reports/data/<run-date>-bm25-weighting-ab/`
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `rag/sparse_tokens.py`
- `rag/test_sparse_tokens.py`
- `app/resparse.py`
- `app/test_resparse.py`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton; rule: ADOPT only if net +3 items on at least one set, no set losing more than 1, and a gain on the lexical strata, else REJECT
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ clone built and resparsed; counts recorded
④ arms run; MANIFEST
⑤ report; clone deleted
⑥ [absorbed CQ-17] stub: docstring with the formula, parameters (k1, b, avglen), the default-off guarantee and the one-recompute-per-arm rule
⑦ [absorbed CQ-17] failing tests: option off leaves vectors byte-identical; option on gives the expected weights on a toy corpus
⑧ [absorbed CQ-17] implementation to green
⑨ [absorbed CQ-17] avglen measurement helper and recorded constants per corpus

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command names `--collection`; the live collection is never an apply target
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py rag/sparse_tokens.py rag/test_sparse_tokens.py app/resparse.py app/test_resparse.py`
- Identical sparse vectors with the option off on 200 stored chunks (RQ-5 check reused)
- `conda run -n agent-rag-research python -m pytest -q rag/test_vector_index.py rag/test_sparse_tokens.py app/test_resparse.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Verdict applies the stated rule per set (never averaged); the ceiling is stated per stratum (BM25 floor from EV-15 shows where lexical headroom exists). Falsified if the baseline arm differs from EV-16/EV-18 beyond the jitter envelope.

Absorbed from CQ-17: Option off: byte-identical vectors; option on: weights match a hand-computed toy example; avglen constants recorded with the command that produced them. Falsified if default behaviour changes by one byte.

**Gates / depends on.** Depends on: RQ-5, EV-22, EV-16, EV-18. Operator answers: F2, F3. Gates: none.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F2, F3 · re-embed: n. Also: GPU free (F3); vector store (F2); 6-8 GB for a clone. Absorbed from CQ-17: GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Disk or contention; mitigations as CQ-7. Rollback: delete the clone. Absorbed from CQ-17: Query-side tokens stay binary while index weights change, which a later reader might misread as a bug. Mitigation: documented in the docstring. Rollback: revert; no index depends on it.

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### CQ-9: Add idempotent payload indexes and verify them on a clone

Labels: wave:3-gated-change, area:corpus, area:retrieval, needs-services, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-9-payload-indexes-on-clone.md`.

**Review cross-reference:** S-22. **Wave:** W3 gated changes after baselines.

**Parked, do not start.** Parked-until: start only if EV-14 reports overlap below 0.99 on at least one of the three filters. Kill criterion: killed if EV-14 overlap is at least 0.99 on all three filters, or no baseline query returned fewer than k hits.

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

**Gates / depends on.** Depends on: EV-14, RQ-5, RQ-1. Operator answers: F2. Gates: none.

**Needs.** GPU: n · services up: vector store (CPU container) up; no GPU services · operator sign-off: n (no protected path is touched); operator answers: F2 · re-embed: n. Also: vector store start approved (F2); 6-8 GB free for one clone.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Index build on a large clone could fill the disk or slow other work. Mitigation: free-space abort rule, one clone, deleted after. Rollback: delete the clone; revert the code (no live collection touched).

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### MC-4: Slim the MCP wire by projecting duplicated envelope fields away

Labels: wave:3-gated-change, area:mcp, size:S, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/MC-4-mcp-wire-projection.md`.

**Review cross-reference:** S-26. **Wave:** W3 gated changes after baselines.

**Parked, do not start.** Parked-until: start only if F5 = yes AND MC-3 telemetry shows agents lowering the default k. Kill criterion: killed if F5 = no, or MC-3 telemetry shows default-k calls are not lowered, or a standards k=10 response (about 4.2k tokens) is acceptable to the operator.

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

**Gates / depends on.** Depends on: MC-3. Operator answers: F5. Gates: none.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched); operator answers: F5 · re-embed: n. Also: operator answer F5 (wire as a projection of the frozen envelope).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A client that read a dropped field breaks. Mitigation: only fields no LLM can use are dropped; the dropped list is documented in the server instructions. Rollback: revert.

**Docs to update in the same PR.** Section 2: the MCP wire projection. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### RQ-3: Run the relevance-demotion arms on the focus and passage sets

Labels: wave:3-gated-change, area:retrieval, area:eval, needs-gpu, needs-services, size:M, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-3-focus-lever-ab.md`.

**Review cross-reference:** S-21. **Wave:** W3 gated changes after baselines.

**Parked, do not start.** Parked-until: start only if EV-17's off-topic top-10 share exceeds the operator's F6 bar; needs RQ-2 built and F3. Kill criterion: killed if EV-17's share is below the bar, or an offline demotion on EV-17 rows (using `relevance_score`) removes under 50% of off-topic top-10 slots or drops any gold on papers-passage or books.

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

**Gates / depends on.** Depends on: RQ-2, EV-16, EV-17. Operator answers: F3, F6. Gates: none.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3, F6 · re-embed: n. Also: GPU free (F3); operator-set materiality bar (F6); about 15 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Demotion starves a pool that is already 40% off-topic. Mitigation: pool sizes are recorded and a starved pool is a REJECT reason. Rollback: n/a (flag only).

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

#### RQ-4: Expose the cross-encoder score in result metadata

Labels: wave:4-rider, area:retrieval, area:mcp, needs-signoff, size:S, parked. Issue file: `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-4-expose-rerank-score-metadata.md`.

**Review cross-reference:** S-20. **Wave:** W4 rider and what it unblocks.

**Parked, do not start.** Parked-until: only after an abstention feature is commissioned, the EV-19 census gate can open (60+ distinct absent items) and RIDER-1 has landed. Kill criterion: killed if the EV-19 census CI contains 0.5 on two of three sets.

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

**Gates / depends on.** Depends on: RIDER-1, EV-19, RQ-1. Gates: none.

**Needs.** GPU: n · services up: none · operator sign-off: y: blocked by RIDER-1 item 3 (contract note) merging · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A caller treating the new field as calibrated confidence. Mitigation: the contract note says 'uncalibrated rank-order score'. Rollback: revert.

**Docs to update in the same PR.** DATA-CONTRACTS section M7 paragraph rides the RIDER-1 amendment that adopts this item. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.

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
| MCP confidence/abstention wiring and score floors (review section 2 and 10 scope notes) | Needs at least 60 distinct real absent items; the sets hold 9-24. | An abstention feature is commissioned and 60+ absent items exist (parked EV-13/EV-19/RQ-4). |
| Focus lever options C (blending) and D (collection split); hard drop or filter of off-topic papers (review, operator decision) | Rejected by the review's reasoning and the operator decision: the off-topic papers stay; only demotion, opt-in, is on the table (parked RQ-2/RQ-3). | The operator reverses the decision. |
| Writing `relevance_score` into the vector payload (RQ-3 follow-on) | No evidence of pool starvation. | RQ-3 observes pool starvation. |
| GPU-lock priority scheduler; reranker-failure fallback to fused order (rejected in OP-5's Out) | The holder file is the smallest step; a fallback changes behaviour and needs a Coverage flag (foundation). | Repeated `run_valid: false` from lock contention (section 11 falsifier c). |
| Restart policy on containers; auto-restart of the foreign model server | A restart on a contended GPU is how the foreign-holder situation arises. | The operator decides the foreign process is theirs to restart. |
| CQ-10 and CQ-11 (embedder token-limit assessment and the truncation decision note) | CUT by the minimizer: the ticket's own ceiling says the gain on current fixtures is 0 by construction (no ground-truth item has a truncated gold chunk; 0 truncated in standards; 0.79% of main chunks); it needs an operator container restart with VRAM/OOM risk; no harm measured. CQ-11 is derived mechanically from CQ-10 and one BACKLOG line covers it. | Any EV-16 miss has its gold or top-10 chunk in `truncated_chunk_ids_main.txt`. |
| Edge-punctuation tokenizer change (named in CQ-17's Out) | No evidence; would change the sparse arm beyond the parked weighting experiment. | CQ-18 ADOPT plus a miss analysis showing edge punctuation. |
| Baselines for the Motional, Waabi and Waymo corpora (implied by omission before) | No ground truth in this programme exists for them; the three baselines are main, standards and focus only. | The operator commissions a ground-truth set for one of them. |
| Resetting per-corpus defaults to 32/0.5 (review S-19) | The frozen runbook rule G-1 says defaults stay unless an arm wins; G-1 is the rule that applies (EV-20), a reset is a config change needing sign-off. | The operator signs a reset, or G-1 is amended by a dated addendum. |
| Any off-device backup tooling | No target exists (F1). | F1 yields a target. |
| The 20 s query-path lock timeout and its Config field (cut from OP-5) | A behaviour change on the baseline path under contention, which is what wave 2 is. | A contended real session shows the 300 s wait. |
| Pieces cut from SHRINK tickets: `escalation_eval.py` and `score_distribution_census.py` `--collection` change (EV-7); `list_stub_chunks.py --ab` rewiring (EV-9); `merge_gt` orphan tolerance (EV-11); the `documents` list in `corpus_stats` (MC-2); `--client-label` (MC-3); `status.py:830` fallback and `reindex_idf` (OP-6); HANDOFF and precision-95 tick rows (EP-6); table sup/sub/span handling (CQ-13); standards and Waymo grids and the weight arms (EV-20) | Cut by the minimizer: not run anywhere in the programme, no observed harm, or a no-op tool. | The consumer is commissioned (for example EV-21 commissions the `--ab` rewiring), or an observed failure names the piece. |
| RV-3 F-1.1 one-command regression gate (manifest + `--baseline`) (lane finding, formerly unplaced) | Dropped now; the stored baselines do not exist yet. | After EV-16/EV-18 manifests exist: a diff script over stored baselines. |
| RV-3 F-1.6 question-style realism controls (lane finding, formerly unplaced) | Dropped: needs operator time; the title-ablated arm is already reported and the 'questions twice as long as real queries' caveat is in section 2. | The operator provides time for a logged-query comparison. |
| RV-2 F-2.7 front/back-matter role classifier and payload tag (lane finding, formerly unplaced) | Dropped. | EV-9 chunk ids show reference or TOC chunks in top-10 slots. |
| RV-2 F-2.11 books outline join for chapter paths (lane finding, formerly unplaced) | Dropped. | EV-16 shows flat-book chapter-level misses. |
| RV-2 F-2.13 chunks over 3,500 characters metric (lane finding, formerly unplaced) | Dropped (low value). | None stated. |
| RV-4 F-4.7 `get_section` clause-prefix match, `scan_corpus` `section_pattern` (lane finding, formerly unplaced) | Dropped: 4 clause references in 242 queries. | MC-3 telemetry shows clause references in volume. |
| RV-4 F-4.9 error text without absolute path, nearest-id hints, async tool wrappers (lane finding, formerly unplaced) | Dropped (low). | None stated. |
| RV-4 F-4.10 reorder BACKLOG MCP-E rows (lane finding, formerly unplaced) | Dropped: the evidence ranking is already recorded in this table. | None. |
| RV-6 F-A7 pre-migration snapshot guard, `busy_timeout` (the `quick_check` part is carried by OP-3) (lane finding, formerly unplaced) | Dropped: no migrations are planned and `migrations/` is protected. | A migration is scheduled. |
| RV-6 F-A9 canary eval slice and usage-log top-score columns (lane finding, formerly unplaced) | Dropped: the canary is the regression gate again (F-1.1). | Same as F-1.1. |
| RV-6 F-A10 dashboard bind default and `.phase0-data` naming (the doctor disk check is folded into OP-6) (lane finding, formerly unplaced) | Dropped (low). | None stated. |
| RV-5 F-5.7 on-topic supply understated; F-5.11 other corpora not rebuildable from tracked files; F-5.12 first-seed runs not reproducible (lane finding, formerly unplaced) | Dropped: no harvest is scheduled. | A harvest is scheduled. |
| RV-1 F-1.12 per-paper diversity default (lane finding, formerly unplaced) | Dropped: the lane recommends no change. | None. |

Also not done, by operator decision: removing the off-topic papers; any GPU work before F3; any protected-path edit outside RIDER-1. Tickets dropped without a will-not-do row: the batch tickets EP-3, EP-4, EP-5 (documentation is paid in the same PR, rule 13) and EP-7 (absorbed by OP-3, OP-5, OP-7).

## 10. Traceability

Every review item maps to an active ticket, a parked ticket, 'merged into <id>' or 'not doing: <reason>'. Nothing is unmapped.

| review item | claim | disposition |
|---|---|---|
| S-01 | No backup since 07-30, none off-device | OP-4 (active, IN PROGRESS, snapshot taken; vector-store data not copied, operator decision pending), OP-3 (active, quick_check + checksums + RUNBOOK backup section). Off-device copy and deletions: not doing until a target exists (section 9; F1) |
| S-02 | Eval inputs not frozen | EV-5 (done); EV-7 (active, `app/retrieval_eval.py` only), EV-15 (active, BM25 floor). Not doing: the `--collection` change to `escalation_eval.py` and `score_distribution_census.py` (cut, section 9) |
| CQ-5 follow-up | 38 more authority and 38 more edition items | CQ-19 (parked; absorbs CQ-20 = merged into CQ-19) |
| S-03 | Chunk-identity scoring ignores alternatives | EV-8 (active), EV-11 (active) |
| S-04 | Cross-encoder score never captured | EV-13 (parked), EV-19 (parked) |
| S-05 | CQ-3 pre-registration wrong fixtures, no minimum effect | EV-12 (parked); EV-9 (active, chunk ids in rows) |
| S-06 | GPU contention unnamed and slow to fail | OP-5 (active, holder file and doctor listing; the 20 s timeout is not doing now, section 9), EV-10 (active) |
| S-07 | Wrong-corpus guards cover one path | OP-6 (active, snapshot and corpus_integrity helper, doctor pairing and disk checks; the `status.py` fallback and `reindex_idf` are not doing: cut), OP-2 (parked, the two serve call sites) |
| S-08 | Unknown paper_id returns empty | MC-1 (active) |
| S-09 | Three one-line retrieval defects | RQ-1 (parked, first post-baseline change) |
| S-10 | Cold agent cannot see filters/corpus | MC-2 (active, without the `documents` list) |
| S-11 | Telemetry blind on scan/get tools | MC-3 (active, without `--client-label`) |
| S-12 | Containers not reproducible | OP-7 (active) |
| S-13 | Docs drift, chunker provenance, Decision 1 | EP-1 (done); EP-2 and EP-2b themselves; EP-6 (active: CORPORA.md, DECISIONS-PENDING, no-ingest rule; the HANDOFF and precision-95 tick rows are not doing: cut); EP-7 merged into OP-3, OP-5, OP-7 (RUNBOOK sections, row 22); EP-3, EP-4, EP-5 not doing as tickets: documentation is paid in each ticket's own PR (rule 13) |
| S-14 | rechunk re-embeds unchanged text | CQ-8 (parked) |
| S-15 | Filtered dense search without payload indexes | EV-14 (active, read-only on the live collection) |
| S-16 | No baselines, reranker score untested | EV-16, EV-17, EV-18 (active); EV-19 (parked); TEI `/info` check folded into EV-16 |
| S-17 | Ligature repair in sparse arm | CQ-7 (parked), EV-22 (parked) |
| S-18 | Stub filter | EV-21 (parked), EV-12 (parked prerequisite) |
| S-19 | Depth and weight per corpus | EV-20 (active, shrunk: depth only, papers and books, conditional on headroom); standards depth decided by D-1; weight arms not doing now (section 9) |
| S-20 | Expose cross-encoder score | RQ-4 (parked) |
| S-21 | Focus lever: post-rerank demotion | RQ-2 (parked), RQ-3 (parked) |
| S-22 | Payload indexes on live collections | CQ-9 (parked), gate = EV-14 |
| S-23 | Bounded re-chunk of oversized main papers | CQ-10 and CQ-11: not doing: cut (section 9; reopen on a truncated gold chunk in an EV-16 miss) |
| S-24 | Standards structure bundle | CQ-12, CQ-13 (shrunk to the furniture pre-pass), CQ-14, CQ-16 (absorbs CQ-15 = merged into CQ-16) (all parked); gate counted in EV-18; F7 |
| S-25 | BM25 saturation and length normalisation | CQ-18 (parked; absorbs CQ-17 = merged into CQ-18) |
| S-26 | Envelope slimming on the MCP wire | MC-4 (parked; gate F5) |
| (D) | Single foundation rider | RIDER-1 (active, shrunk to items 5, 2, 6); items 1, 3, 4 and conditional item 7 return only by plan amendment when their source tickets are adopted |
| (E) | Not worth doing | Section 9; no ticket |
| (F) | Open operator questions | Section 3, each linked to the tickets it blocks |

Lane findings and review adjudications kept by the synthesis:

| finding | disposition |
|---|---|
| Review 1a (score discarded, RV-1 F-1.1, RV-4 F-4.1) | EV-13, EV-19, RQ-4 (parked; =S-04, S-20) |
| Review 1b (no payload index, RV-1 F-1.2) | EV-14 (active), CQ-9 (parked) (=S-15, S-22) |
| Review 1c (`_SectionTracker`, RV-2 F-2.1) | CQ-12, CQ-13, CQ-14, CQ-16 (parked; =S-24); flat books not fixable by the tracker and not ticketed (the PDF outline join, RV-2 F-2.11, is dropped, section 9) |
| Review 1d (patches vs re-chunk rule, RV-2 F-2.2/F-2.3) | Rule applied by CQ-8 and CQ-16 (parked); the truncation route (CQ-10/CQ-11) is cut; full re-chunk and `chunker_id` in section 9; no-ingest rule in EP-6 (active) |
| Review 1e (saturation, run-time fixture rewrite, wrong checkout; RV-3 F-1.3, F-1.4) | EV-5 (done), EV-7, EV-15, EV-8, EV-11 (active); passage-level headline and title-ablated arm are in the frozen protocols (EV-5) |
| Review 1f (contamination cause, RV-5 F-5.1) | Section 9 (arXiv curl); the lexical gate is built with the next harvest |
| Review 1g (backups, RV-6 F-A1) | OP-4, OP-3 (active) |
| Review 1h (CQ-1 hazard refuted as regression) | No ticket for the refuted part. Residual risk 1 (ingest into a live collection mixes chunkers/sparse versions): EP-6 no-ingest rule (active). Residual risk 2 (fake tokenizer): RQ-5 (parked), and rider item 4 which is not in the shrunk RIDER-1 |
| Review 'other claims': RV-4 F-4.2 | MC-1 (active) |
| RV-1 F-1.3 shared anchors (confirmed) | EV-8 (excerpt metric) and EV-9 (chunk ids), both active. QW-1 remains parked on T-F7 and is not part of this programme |
| RV-1 F-1.9 300 s lock wait, RV-6 F-A3, F-A8 | OP-5 (holder only), EV-10 (active); the 20 s timeout is not doing now |
| RV-3 F-1.2 `--collection` default | EV-7 (active; `app/retrieval_eval.py` only) |
| RV-1 F-1.11 critique of CQ-3 (refuted) | No action. CQ-3 overfetches and stops once the pool is full |
| RV-6 F-A6 / Decision 1 (refuted as open) | EP-6 closes Decision 1 with the config evidence; `reindex_idf` default flip: not doing (section 9) |
| RV-5 foundation-protection notes; F-5.5 (refuted) | RIDER-1 item 2 carries the real protected change (`relevance_filter`); labels are in git, so no ticket |
| RV-5 F-5.6 inert config | RIDER-1 item 2 (active) |
| RV-3 F-1.11 promotion of the three sets | RIDER-1 item 5 (active) |
| RV-6 F-A5 CI (ruff step, nightly manual-only, push) | RIDER-1 item 6 (active); push is operator question F4. Self-hosted runner: section 9 |
| RV-3 F-1.14 ligature stratification | EV-22 (parked) |
| RV-3 F-1.10 abstention minimum data | EV-19 (parked, census only); no MCP wiring is proposed (section 9) |
| RV-2 F-2.5 / F-2.6 / F-2.8 (a) / F-2.10 | CQ-13 (furniture pre-pass only; table sup/sub/spans not doing: cut), CQ-14 (regex guard, stub folding) (both parked) |
| RV-4 F-4.3, F-4.4 | MC-2 (active) |
| RV-4 F-4.5 | MC-3 (active) |
| RV-4 F-4.6 | MC-4 (parked) |
| RV-4 F-4.11 | RQ-1 (parked) |
| RV-1 F-1.4 (focus lever options) | RQ-2, RQ-3 (parked; option A only); option B payload route only if RQ-3 sees starvation; C blending and D collection split: not doing (section 9) |
| RV-1 F-1.5 (depth/weight) | EV-20 (active, shrunk) |
| RV-1 F-1.6 (BM25 weighting) | CQ-18 (parked; absorbs CQ-17) |
| RV-1 F-1.7, F-1.8 #7 | RQ-1 (parked) |
| RV-1 F-1.10 shared tokenizer | RQ-5 (parked); rider item 4 not in the shrunk RIDER-1 |
| RV-6 F-A2 | OP-7 (active) |
| RV-6 B.1 punch list rows 1-23 | EP-1 (done), EP-2/EP-2b (BACKLOG rows), EP-6 (DECISIONS-PENDING; the HANDOFF and precision-95 rows are not doing: cut), RUNBOOK rows (incl. row 22) in OP-3, OP-5, OP-7 (EP-7 merged) |
| Review section 2: CQ-1 'no test pins the map checksum' | RQ-5 (parked) |
| Review section 2: OP-1 covers only 'TEI down' | OP-5 (active; doctor listing of foreign GPU processes) |
| Review section 2: EV-6 'not reviewed by any lane' | EV-6b (active, new): hand-computed example, dry run, independent review, before EV-16 |

Lane findings the synthesis neither ranked nor rejected, now placed by the minimizer: two are folded and twelve dropped (the twelve are rows in section 9 with their reopen conditions).

| finding | disposition |
|---|---|
| RV-3 F-1.12 chapter-level is a heading-string match (caveat) | Folded: one caveat sentence in EV-11's addendum (active) |
| RV-6 F-A10 doctor disk check on cwd only | Folded: the data-dir-device disk check is part of OP-6 (active); the rest of F-A10 is dropped (section 9) |
| RV-3 F-1.1, F-1.6; RV-2 F-2.7, F-2.11, F-2.13; RV-4 F-4.7, F-4.9, F-4.10; RV-6 F-A7, F-A9; RV-5 F-5.7/F-5.11/F-5.12; RV-1 F-1.12 | Not doing (section 9, each with its reason and reopen condition) |

## 11. Self-review

- **Counts.** 22 active tickets: W1 17, W2 4, W3 0, W4 1; 21 parked. Original 51 = KEEP 10 + SHRINK 12 + DEFER 20 + MERGE 7 + CUT 2; plus EV-6b (new) = 52 rows considered, 43 kept as tickets (22 + 21), 7 merged away (CQ-20 into CQ-19, CQ-15 into CQ-16, CQ-17 into CQ-18, EP-7 into OP-3/OP-5/OP-7, EP-3/EP-4/EP-5 dropped as batch tickets), 2 cut (CQ-10, CQ-11). The plan header, INDEX.md and the BACKLOG section state the same two numbers (checked mechanically).
- **Consistency check (throwaway script, not committed), result on this revision:** every dependency id exists and is active, parked-to-active, done or an operator answer; no active ticket depends on a parked ticket; no cycles; 170 unordered pairs of active tickets checked and none shares an `Owns` path (shared files are ordered by explicit edges: `app/retrieval_eval.py` by EV-7 -> EV-8 -> EV-9 -> EV-10, `app/serve.py` and `rag/mcp_server.py` by MC-1 -> MC-2 -> MC-3, `app/snapshot.py` by OP-3 -> OP-6, `app/doctor.py` by OP-6 -> OP-5, `docs/RUNBOOK.md` by OP-3 -> OP-6 -> OP-5 -> OP-7, the fixture hash file by EV-8 -> EV-11 and EV-4b merge order; the baseline run directories are serial EV-16 -> EV-17 -> EV-18); every active ticket has an issue file, an INDEX row and a BACKLOG row; every parked ticket has a `parked/` file with a `Parked-until:` line, a PARKED BACKLOG row and a INDEX row; issue files contain no absolute path outside the repo, no e-mail address and no personal name.
- **Every ticket has a falsifier**: each acceptance line contains an explicit 'Falsified' clause (checked mechanically).
- **Minimizer verdicts, interpretations and conflicts (each applied conservatively).** (1) CQ-13 is a SHRINK verdict but hard-depends on parked CQ-12, so it is placed in the parked section instead of leaving an active-to-parked edge. (2) EV-6b is a separate small ticket as the operator instructed; the minimizer would have folded the dry run into EV-8's acceptance. (3) The minimizer's 'combine EV-7 to EV-10 into one PR' is implemented as four chained tickets on one branch and one PR in two briefs (section 6.1). (4) The minimizer's 'decouple' remarks (EV-9/EV-10, MC-3/MC-2, MC-3/OP-2, CQ-9/CQ-17, RQ-3/CQ-10, EV-20/EV-21) are applied as 'no data dependency'; where the two tickets still own the same file the edge stays as an explicit ordering edge (EV-9 -> EV-10, MC-2 -> MC-3, parked OP-2 <- MC-3), and the pure artefacts are removed (CQ-9 -> CQ-17, RQ-3 -> CQ-10, EV-20 -> EV-21 and the other parked GPU-serial edges). (5) EP-7 is split by section into OP-3 (backup and restore), OP-5 (GPU contention and the `gpu_lock_path` row) and OP-7 (containers), which puts `docs/RUNBOOK.md` in three Owns lists, so OP-3 -> OP-6 -> OP-5 -> OP-7 is chained (OP-7's compose-file work has no dependency, only its RUNBOOK commit waits). (6) 'Remove OP-5 as a gate of EV-16' and 'MC-1/2/3 must merge before the frozen commit, not during' are reconciled by the hold rule in section 6.4: they do not gate EV-16, and any not yet merged at the freeze waits for EV-18. (7) The minimizer's RQ-1 trigger ('after EV-16 has landed') is applied as after EV-16, EV-17 and EV-18 are merged, because the freeze holds through EV-18. (8) CQ-18's trigger is composed as the negation of its kill criterion on the same set. (9) EV-14 still needs F2 (the vector store container must run, CPU only) although no clone is made. (10) RIDER-1 is kept active but depends on EV-18 so its config-validation item merges after the last baseline (pre-baseline rule). (11) EV-20 is active but conditional on a 6-item headroom gate. (12) EP-6's no-ingest rule is re-targeted from 'verdicts of EV-22 and CQ-11' to the operator's decision on the parked CQ-7/EV-22/CQ-16 questions. (13) OP-4 is IN PROGRESS, not DONE, because the vector store's on-disk data was not copied.
- **What would falsify this plan's structure.** (a) If the baselines show the new sets saturated even at passage level with the title-ablated arm high, every parked ticket stays parked and the programme's value is the instruments: the structure absorbs it because nothing downstream is started without a trigger. (b) If the one-PR instrument bundle produces merge conflicts anyway, the ownership partition is wrong. (c) If the first run shows `run_valid: false` from lock contention, the cheapest-first serialization is not enough and a scheduler (rejected here, section 9) comes back. (d) If EV-14 finds overlap of at least 0.99, CQ-9 is killed cleanly. (e) If EV-6b finds the strata script wrong, the first baseline's tables wait for the fix, by design.
- **Deviations to confirm.** (1) Docs batching (the former rule 13) is withdrawn; AGENT-PROCEDURES section B applies. (2) Review S-19 says reset unsupported per-corpus defaults to 32/0.5; the frozen runbook rule G-1 says defaults stay; EV-20 follows G-1. (3) After CQ-4 the review's S-23 targeted re-chunk was re-scoped, then cut by the minimizer (CQ-10/CQ-11). (4) RQ-5 has no S-nn: it is the prerequisite for rider item 4 and is parked. (5) RQ-2 is no longer built before the baseline; its build is parked behind EV-17's off-topic share. (6) Wording: 'sign-off' for non-protected paths means a decision in PR review, not RIDER-1.
- **Three weakest points, stated honestly.** (1) *One GPU session carries the value.* Every quality question sits behind a single serialized session that is blocked by a process this programme does not control (F3); if it slips, W2 does nothing and only the instruments and fixes land. (2) *Statistical power.* With n of 61-128 and strata of 4-26, even a clean win is hard to call; the plan deals with that by pre-registered minimum effects, UNDERPOWERED verdicts and kill criteria, but it cannot create power. (3) *The minimizer's kill criteria are applied by hand at baseline time.* A parked ticket whose trigger is read wrongly either starts too early (cost: a clone and a report) or never; the triggers are written as numbers on named baseline outputs to keep that reading mechanical.
- **Scope discipline.** No MCP confidence wiring, no corpus deletion, no full re-chunk, no harvest changes, no schema migration. Review items outside the ranked groups are placed in section 9 or 10, not smuggled in.
- **Dispatch survival encoded:** stub-first commits in every ticket including docs tickets; detached runs with MANIFEST committed at launch; death verified through git; one worktree per dispatch (the EV-7 to EV-10 bundle is one worktree, two briefs); no `pkill -f`.
