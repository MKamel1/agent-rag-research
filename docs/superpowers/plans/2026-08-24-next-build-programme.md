# The next-build programme — passage precision, abstention, and the parallel plan to reach them

Written 2026-08-24, before execution (deliberately — see the 2026-08-23 programme's own §0 finding
that planning-after-dispatch left no dependency map). This is the successor to
[`2026-08-23-openevidence-programme.md`](2026-08-23-openevidence-programme.md) §8: it takes the three
findings in `HANDOFF-2026-08-24.md` §5 as its input and turns them into dispatched, parallelizable
tickets. **This document plans; it does not implement.** No ticket below has started.

Every number is cited to its source file or branch. Where something is unknown it says so.

---

## 0. Inputs this plan stands on

| fact | value | source |
|---|---|---|
| Paper recall | 0.9714 priority / 0.9559 full at live w=0.7 | handoff §3; sweep JSONs on `main` (`docs/eval-reports/2026-08-24-fuse*-*.json`) |
| Passage block-P@1 | 0.3750 ver84 dense / 0.7273 GT-WMR fused | PREC-1 headline table |
| Perfect-reranker ceiling over today's top-10 | **0.7812 ver84 / 0.9394 GT-WMR — both below the 0.95 bar** | PREC-1 §1 ceiling table |
| Right-paper-wrong-block population split | ~2/3 gold block in top-10 ranks 2–10 (heavily rank 2); ~1/3 absent from top-10 entirely | PREC-1 §1 |
| Fusion evicts on full corpus | dense-only top-10 hits 50/60 vs fused 43; direction one-way | baseline report §2 + handoff finding 2 |
| Vision arm | all 4 items right paper at rank 1, gold block unreachable by text retrieval; figures 24,708 rows location-ready, `vlm_description` populated on 0 | handoff §5.3; PROJECT-STATUS §1 Waymo-priority section |
| Abstention | 0/24 known-absent detected; score distributions do not separate | handoff §3; programme plan §5 |
| PREC-1 §2 (pool depth) and §3 (block adjacency) | **both still pending — instrumentation not yet run** | PREC-1 §2/§3 headers |
| PREC-1 §6 ranked fixes | deliberately withheld until §2–§5 landed | PREC-1 §6 |
| Fixture conditioning | block-P@1 gap survives a same-paper control (0.395 vs 0.750); never average or trade across fixtures | PREC-1 §5 |

**The load-bearing implication:** any plan that only says "rerank better" is capped at 0.78/0.94 —
short of target on both fixtures even with a perfect reranker. Pool depth (what reranking draws
from) is therefore a first-class workstream, not an optimization detail. This is why Wave 1 is
diagnosis completion rather than implementation.

---

## 1. Operator decisions this plan needs (none block Wave 1)

| # | decision | recommendation recorded here | blocks |
|---|---|---|---|
| A | `hybrid_dense_weight`: keep 0.7 or restore 0.5 | **DECIDED 2026-08-25: keep 0.7** (operator). Recorded in PROJECT-STATUS.md's tuning-decision section. Re-evaluate once, after NB-2x lands, against both fixtures. Rollback stays one line (`waymo/data/config.yaml`, backup `config.yaml.bak-w0.5-20260824T122256`). | nothing — experiments measure, they don't flip config |
| B | Fabrication rubric amendments F-A1..F-A3: apply or defer | **DECIDED 2026-08-25: apply, after verifying each amendment first** (operator condition). Done: all three verified against their sources before application (F-A1/A3 are faithful ports of the signed groundedness rubric's proven clauses; F-A2 checked against the review's run evidence) and applied with a SIGNED OFF header on `fabrication-audit-rubric.md`. Consequence recorded there: one judge re-run is owed under the new rubric hash before any fabrication number is treated as a trend — folds into the already-open "build the real Judge" item (programme plan §8), since no non-fake `Judge` exists yet. | NB-4 |
| C | VLM/vision project start now or after passage work | **DECIDED 2026-08-25: conditional** (operator) — proceed only if VLM earns its cost by information *only it* can reach. NB-6 scoping therefore leads with a unique-information-yield analysis: which operator-relevant questions require figure content no text path can serve (vision arm's rank-1-paper/unreachable-block pattern is the n=4 seed), priced against VRAM co-residency and project size. No build commitment until that number exists. | NB-6 build tickets (scoping itself unblocked) |
| D | OpenEvidence shared-benchmark head-to-head | Out of scope for this programme (never scoped, externally dependent). Revisit only after abstention exists. | nothing |

If the operator answers differently, only the blocked tickets change — the wave structure does not.

---

## 2. Execution model — how this plan uses parallelism

This programme is designed for **one orchestrator + parallel dispatched agents + detached measurement
processes**, per `docs/AGENT-OPERATIONS-LESSONS.md`. The division of labor is the single most
important operational decision in it:

> **Fan out *measurements* as detached processes; spend agent sessions only on judgment work.**
> (lessons §7.3 — the six benchmark runs finished in ~90 s unsupervised as `setsid` processes, while
> the same fan-out shape died nine times when run as concurrent agent sessions.)

Concretely:

- **Orchestrator (the session running this plan)**: writes briefs, dispatches, verifies artifacts,
  merges lanes, owns the integration branch. Never implements a ticket itself.
- **Dispatched agents** (`oc-task` / headless opencode): judgment work only — analysis write-ups,
  code tickets, review passes. One ticket per brief, two items absolute max (lessons §3.1b).
- **Detached processes**: every retrieval eval, sweep arm, and census script. One input file → one
  output report file, no mid-flight judgment needed.

### Global constraints — encode these into EVERY brief verbatim

1. **Assume every dispatch dies.** ox-alpha 429s on ~1 request in 3 upstream (lessons §3.3d,
   root-caused 2026-08-24). Each ticket IS a numbered list of commits; **commit 1 is a stub committed
   before any real work**; commit after every green step. A dead dispatch must be resumable from
   committed state with zero loss.
2. **One ticket, one worktree, one live dispatch.** `git worktree add -b <branch>
   .claude/worktrees/<branch> main` off freshly-fetched main; rebase held branches before dispatch
   (§4.3). Before ANY dispatch: check for queued chain scripts (§4.7). Never `git checkout` inside
   another session's checkout.
3. **Resume vs restart:** resume the session id only if the dispatch died *mid-task* (§3.2); if a
   session already finished its phase, re-dispatch FRESH with a narrow append-only brief instead of
   resuming accumulated context (§4.6).
4. **Verify death honestly:** exit 0 + zeroed tokens + log ending at `llm runtime selected` = dead,
   not done. Confirm artifact existence on disk (report file committed) before crediting a ticket.
   Probe intermittent failures N times, not once (§3.3d).
5. **Observation:** `oc-watch` read-only. Never leave `opencode serve` running during a fan-out (§6b).
6. **File ownership partitions concurrency.** Two concurrent branches may not touch the same file
   (§4.1). The ownership matrix is stated per wave below; hold a ticket rather than run it into a
   conflict.
7. **Baseline re-read at dispatch time** (§4.4): each brief states "baseline is N passed" fetched
   fresh from that worktree's merge-base commit, not quoted from this doc.
8. **Waymo runs name the collection explicitly:** `--collection waymo_av_safety` on every Qdrant
   touching command. Omitting it silently queries the wrong corpus.
9. **Foundation paths are gated** (`contracts/`, `migrations/`, `fixtures/`, `rag/config.py`,
   `ci/`, `.github/`, `pyproject.toml` — CODEOWNERS/T-F7). Designs route around them: experiment
   reports go under `docs/eval-reports/data/`; harness code lives in `scripts/` or throwaway
   `app/exp_*.py`; anything that genuinely must touch a frozen path gets batched into ONE rider PR
   (§6.3) and flagged to the operator before dispatch.
10. **Cross-fixture guardrail:** block-P@1 is fixture-conditioned (PREC-1 §5). Any claimed
    improvement reports BOTH fixtures' numbers, changes exactly one variable per run, and is believed
    only if the other fixture holds as a held-out control. Never average across fixtures.
11. **Ceiling-check before freezing any new metric definition** (lessons §7.2): compute the
    achievability bound in thirty seconds of arithmetic before freezing protocol text.
12. **Docs obligations ride with each landing PR** (AGENT-PROCEDURES §B): BACKLOG row, PROJECT-STATUS
    ledger entry in the same PR, HISTORICAL banners same-PR, §7 doc-map row for new docs.
13. **CI enforcement locally before every push** (AGENT-PROCEDURES §B.1):
    `GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH=/tmp/fake_push_event.json python -m ci.run_enforcement`.

### Ticket ID scheme

`NB-<wave><n>` (next-build). Branches `NB-<id>-<slug>`. Each ticket below lists: owner-lane files,
commits, verification, and what it gates.

---

## 3. Wave map

```
Wave 0 (closures, tiny, parallel)          C1 merge FUSE artifacts · C2/C3 operator decisions
Wave 1 (diagnosis + harness, 4 parallel)   D1 pool-depth · D2 block-adjacency · D3 abstention census · D4 eval runner
        D1,D2 ──gate──▶ Wave 2 (fix ranking, then parallel implementation)
                               R0 rank fixes ──▶ X-series experiments (detached processes)
                                                  │
Wave 3 (gated on X verdicts)                   └──▶ A-series abstention build
NB-6 VLM scoping (operator gate C) — starts whenever C is answered, independent lane
```

Dependency edges, exhaustive:
- D1 ∥ D2 ∥ D3 ∥ D4 — fully independent (disjoint files, disjoint questions).
- R0 needs D1+D2 (it completes PREC-1 §6, withheld until then). Needs D4 (experiments must be
  runnable). Does NOT need D3.
- Every X-ticket needs R0's ranking + D4's runner. X-tickets are mutually parallel ONLY where their
  file ownership is disjoint (each owns its own dated report + its own worktree; no shared source
  edits without R0 assigning ownership).
- A-series needs D3 (+ benefits from X verdicts but does not require them).

---

## 4. Tickets

### Wave 0 — closures (day 0, parallel-safe)

- [x] **C1 — merge stranded FUSE artifacts into `main`.**
      **Closed 2026-08-25 as already satisfied: the diagnosis and all 22 sweep JSONs were verified
      present on `main`, byte-identical to `FUSE-2-lower-sweep`** (`git checkout FUSE-2-lower-sweep
      -- <23 paths>` produced a zero diff). The "stranded" premise was this plan's own error: it had
      run `ls` against the shared checkout's stale working tree (branch `JUDGE-1-groundedness`, 87
      commits behind `main`) instead of `git ls-tree main` — exactly the verify-against-git-not-
      working-tree trap AGENT-PROCEDURES §A.2 exists for, caught by this ticket's own verification
      step. Lesson recorded; no merge needed.

- [x] **C2/C3 — record operator decisions A/B, and C's conditional answer** (§1 above).
      Done 2026-08-25: A recorded in PROJECT-STATUS (commit `c681f70`); B verified + applied to
      `docs/eval-rubrics/fabrication-audit-rubric.md` with SIGNED OFF header; C recorded as
      conditional in §1. Orchestrator-direct; no dispatch warranted. One commit each.

### Wave 1 — complete the diagnosis, build the ruler (4 parallel lanes)

- [ ] **D1 — PREC-1 §2: candidate-pool depth instrumentation.**
      Question: for the C1 population (gold block in top-10 ranks 2–10) AND the C2 population
      (rank-1 paper right, gold block absent from top-10), is the gold chunk present in the reranker's
      deeper candidate pool (retrieve k≫10 → rerank → top-10) or never retrieved at all?
      Method: read-only replay over stored per-question records + targeted re-retrieval runs as
      DETACHED PROCESSES (pool sizes e.g. 32/64/128 × both fixtures × current shipped config;
      w=0.7 frozen for instrumentation regardless of decision A outcome).
      Owns: `docs/eval-reports/2026-08-24-nb-d1-pool-depth.md` + its analyze script.
      Deliverable: the missing half of PREC-1 §1's ceiling table — "block-P@1 ceiling if the pool
      were bottomless" alongside "if reordered only". Ceiling-check the new metric before trusting it
      (constraint 11).
      Gates: R0.

- [x] **D2 — PREC-1 §3: block adjacency / chunking-artifact analysis.**
      Question: when rank-1 paper is right and the gold block is near-missed, how far away is it
      (same chunk? adjacent chunk? same section?) — measured via papers.db block adjacency, read-only.
      Owns: `docs/eval-reports/2026-08-24-nb-d2-block-adjacency.md` + script.
      Note: shares NO files with D1 by design (ownership rule); conclusions cross-reference by path.
      Gates: R0.
      **Done 2026-08-25** (branch `NB-D2-block-adjacency`, analysis commits `87bfa51`/`d89fa15`):
      report landed as `docs/eval-reports/2026-08-25-nb-d2-block-adjacency.md` (+ reproducible
      script beside its input data). Verdict: boundary classes are real but secondary
      (9/27 = 33% of verified-84 near-misses vs 3/12 = 25% GT-WMR; elsewhere-in-document dominates
      both); sharpest slice = gold content served at rank 1 under a sibling anchor (anchor/citation
      artifact, invisible to rerankers).

- [ ] **D3 — abstention feasibility census v2.**
      Question: do ANY observable quantities separate answerable from known-absent — fused score,
      dense score, sparse score, hit-count@k, score-gap rank1→rank2, agreement between arms?
      (The 0/24 finding used top-score alone; the census widens the feature set before concluding
      "no signal exists".)
      Method: offline over stored run records + one detached re-run per fixture. Explicitly marked
      REFRESH-POST-RERANK: distributions shift if retrieval changes.
      Owns: `docs/eval-reports/2026-08-24-nb-d3-abstention-census.md`.
      Gates: A-series design fork (signal exists → threshold/calibration ticket; no signal →
      new-signal-source design doc).

- [x] **D4 — one-command dual-fixture evaluation runner (the ruler).** **Closed 2026-08-25** on
      branch `NB-D4-eval-runner`: `scripts/nb_eval_runner.py` (subprocess orchestration of
      `app/retrieval_eval` per fixture, silent-death artifact guard) + synthetic-input unit tests +
      committed SAMPLE dual-fixture output pair dated 2026-08-25 under
      `docs/eval-reports/data/2026-08-25-nb-d4-dual-fixture-SAMPLE.*`. Its gt_wmr R@10 68/70 =
      0.9714 and ver84 65/68 = 0.9559 reproduce handoff §0's live-w=0.7 headline numbers exactly;
      block-P@1 denominators are the VARM-1 text arm (65/60, not PREC-1's pre-VARM-1 66/64).
      Reuse-first (constraint from lessons §5.3): **the runner exists — `app/retrieval_eval.py` on
      `main`** (CLI: `--ground-truth`, `--config`, `--k`, `--report-path`, …). The FUSE sweeps were
      driven by it plus per-arm wrappers in branch history. D4 wires a thin dual-fixture orchestrator
      over it (run both fixtures, emit the standard combined table), it does NOT rewrite evaluation
      logic. Grep the FUSE branches for the sweep wrapper before writing anything new.
      Deliverable: one entry point that takes a config delta and emits BOTH fixtures' standard table
      (R@10/MRR/block-P@1, answerable + absent arms reported separately per protocol) as dated JSON +
      md, plus a README stub. Lives in `scripts/` (not foundation-gated).
      Commits: ① stub ② runner ③ golden-output test vs stored 2026-08-23 outputs. (As executed:
      ③ became synthetic-input math tests per the dispatched brief; the SAMPLE pair is the
      golden-output check against stored baselines.)
      Gates: every X-ticket.

### Wave 2 — rank the fixes, then implement in parallel

- [ ] **R0 — complete PREC-1 §6: ranked candidate fixes (judgment work).**
      Input: D1+D2 addenda, eviction data, Q4 stratum collapses (hard 0.167, negation 1/7),
      ceiling arithmetic. Output: ranked fix list, each entry with its predicted ceiling gain per
      fixture and its cost class (config-only / scripts-only / contracts-gated). Orchestrator +
      oracle consult; no swarm. One commit to the diagnosis report family.
      Gates: X-series dispatch.

- [ ] **X-series — implementation/experiment tickets (parallel, shape depends on R0).**
      Expected shapes, pre-registered so R0 fills in orderings rather than inventing tickets:
      - **X-P (pool depth):** retrieve-deeper→rerank-to-10 configs. Fan out pool-size arms as
        detached processes; agent writes the comparison report.
      - **X-O (ordering quality):** reranker-side improvements within the existing top-10.
      - **X-F (fusion shape):** sparse_mode/dense-only variants at fixed weights — targets the
        eviction finding directly.
      - **X-H (hard/negation strata):** whatever R0 ranks for the verified-84 collapse points.
      Rules per ticket: numbered commits with stub first; one variable per run; BOTH fixtures'
      tables in every report; results land under `docs/eval-reports/data/` (not fixtures/);
      GPU-heavy arms serialize on the GPU lock — schedule them, don't race them.
      Gate: nothing downstream except A-series refresh.

### Wave 3 — abstention build (uses D3's verdict)

- [ ] **A-1 — abstention design fork resolved.** Signal found in D3 → threshold/calibration ticket
      with a pre-registered false-refusal budget measured on the answerable arm. No signal → design
      doc for a new signal source, explicitly NOT promised to work. Either way: dated report,
      falsification criterion stated before building (house rule from the book-RAG experiments).
- [ ] **A-2..** follow from A-1; planned only after A-1 lands.

### Standing independent lane

- [ ] **NB-6 — VLM/vision project scoping (blocked only on operator decision C).** Scoping doc only:
      what reading the retrieved page would buy (the 15% unreachable slice), candidate local VLMs,
      VRAM co-residency with TEI, and the n=4 honest-denominator problem. Project-scale; no build
      tickets written here.

---

## 5. Verification & completion audit for the programme

The programme is done when ALL hold:

1. D1/D2 addenda merged; PREC-1 §6 ranking exists with cited ceilings (no invented numbers).
2. At least one X-verdict adopted or rejected WITH both-fixture evidence; the adoption (if any)
   shipped behind its own PR with CI watched to conclusion (AGENT-PROCEDURES §B.2), docs obligations
   paid.
3. D3's abstention verdict recorded; A-1's fork resolved with a falsification criterion either way.
4. Decisions A–D recorded in PROJECT-STATUS with their rationale.
5. `pytest` green, `ci.run_enforcement` green on every branch at merge time; no foundation-path diff
   without operator sign-off.
6. Handoff §5's three findings each have either a shipped response or a documented rejection.

---

## 6. Self-review (written before execution, per house format)

- **Does any ticket average across fixtures?** No — constraint 10 forbids it; D1/X-tables report
  both arms separately. The known temptation (GT-WMR looks better everywhere) is named in the briefs.
- **Is "rerank better" treated as sufficient?** No — the ceiling math (§0) is the reason Wave 1
  exists; pool depth is instrumented before any reranker work is ranked.
- **Swarm failure modes covered?** Silent deaths (constraint 1+4), startup hangs vs quota (§3.3b/3.3
  referenced for the orchestrator), store contention (oc-task isolates XDG_DATA_HOME by default,
  §4.5), queued chain double-dispatch (constraint 2), large-context resume trap (constraint 3).
- **File-ownership conflicts possible?** Within waves, no (each lane owns distinct report files).
  Across waves, serialization is explicit (R0 after D1+D2; X after R0). The one shared file risk —
  multiple X-tickets editing repo source — is constrained: X-tickets default to config deltas +
  scripts, and any source change gets exclusive ownership assigned by R0.
- **Anything foundation-gated hidden in the fine print?** Checked: C1 excludes fixtures/;
  D4 lives in scripts/; experiment outputs go to docs/eval-reports/data/. If R0's winner requires a
  `contracts/VectorIndex` change, that becomes ONE rider PR with sign-off requested first
  (constraint 9) — not smuggled.
- **Are the open operator decisions actually blocking?** No (§1 states what each blocks); Wave 1
  proceeds regardless, which is the point of front-loading measurement.
- **What would falsify this plan's structure?** If D1 shows the pool is already bottomless-effective
  (gold chunks absent from deep pools too), X-P dies and R0's ranking shifts to chunking/retrieval
  upstream (X-F/X-H classes) — the wave map absorbs this because R0, not this document, picks the
  winners. If D3 finds separation, A-series accelerates ahead of X — allowed; the edge is "benefits
  from", not "requires".

---

## 7. Completion audit (executed 2026-08-25, against §5 above)

| # | criterion | result |
|---|---|---|
| 1 | D1/D2 addenda merged; PREC-1 §6 ranking exists with cited ceilings | **met** — D1/D2 merged (e95825d lineage); ranking in `docs/eval-reports/2026-08-25-nb-r0-fix-ranking.md`, reviewed, five corrections applied |
| 2 | ≥1 X-verdict adopted/rejected with both-fixture evidence | **met ×3** — X-F (eviction does not survive production depth; dense_only ≡ w=1.0 proven bit-identical; config stays w=0.7), X-P (depth = serving win / ordering hazard; ver84 text-arm 0.3833 @K=64), X-O (no cheap ordering lever clears the bar; reranking itself is load-bearing — off ⇒ ver84 0.1667). Each merged with per-branch enforcement PASS |
| 3 | D3 verdict recorded; A-1 fork resolved with falsification criteria | **met** — census "no separation found"; design doc fixes five falsifiers before any build; C1 refusal-affordance detector recommended first |
| 4 | Decisions A–D recorded with rationale | **met** — PROJECT-STATUS "Next-build programme" ledger + tuning-decision resolution; B applied in the signed rubric header |
| 5 | pytest/enforcement green at every merge; no ungated foundation diff | **met** — gates rerun independently by the orchestrator per lane (two false PASS claims caught and fixed: NB-D3 check-(a), NB-X-O check-(f)); all lane diffs scanned CLEAN |
| 6 | Handoff §5 findings each answered | **met** — F1 passage gap: diagnosed to pool-depth + ordering layers, cheap-lever space exhausted honestly; F2 fusion eviction: measured gone at production settings; F3 vision arm: proven text-unreachable at any depth, scoped CONDITIONAL CLEAR with pilot criteria |

**Disposition of gated items:** X-O executed to its pre-registered second branch (negative verdict);
**X-H not executed** — its R0 gate ("stratum-shaped residual after X-P/X-O") is arguably met, but
the honest-ceiling statement already bounds what any ordering-side work could return, so X-H is
recorded as the successor programme's first candidate alongside the A-series C1 falsification run
and the NB-6 bounded pilot. **NB-A1 channel deviation recorded:** oc-task failed 4× on that lane;
completed via harness subagent fallback after zombie-dispatch reconciliation (lessons §8).
