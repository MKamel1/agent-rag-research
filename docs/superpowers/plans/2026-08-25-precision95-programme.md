# The precision-0.95 + agentic-RAG programme — ratified metrics, quick wins, structural bets, integration

Written 2026-08-25, before execution (house rule inherited from the
[`2026-08-24-next-build-programme.md`](2026-08-24-next-build-programme.md) planning precedent: the wave
map exists so dependencies are decided before dispatch, not reconstructed after deaths). Inputs: the
NB-B0 benchmark audit, NB-R1 agentic-RAG research, NB-R2 confidence/Qwen research, NB-XC member-citation
measurement, NB-D2 block-adjacency analysis. **This document plans; it does not implement.** Every
number is cited to its source report. Where something is unknown or not commissioned, it says so.

---

## 0. Inputs this plan stands on

| fact | value | source |
|---|---|---|
| Honest single-shot ceiling, ver84 all-arm | block-P@1 ≤ 56/64 = **0.8750** @K=128 under a *perfect* reranker (text-arm 56/60 = **0.9333**, one item short); paper-P@1 fused bound 61/68 = **0.8971** | B0 §1.2b/§1.2c |
| gt_wmr clears 0.95 | paper-P@1 bound 69/70 = 0.9857 (Δ = **+3 items** from 64/70); block-P@1 @K=32 63/66 = 0.9545 all-arm, text-arm 65/65 = 1.0000 @K=128 | B0 §1.2b/§1.2c |
| Member-block citation (measured, monotone) | ver84 dense hit-rate 78.1% → **84.4%** (+4 conversions, Q-WAYB-027 at rank 1); GT-WMR fused 93.9% → **95.5%** (C2 bucket erased to zero); zero regression risk by construction | X-C §2 |
| Full-population pricing cap | with no abstention mechanism, any precision priced over absent queries caps at N_ans/N_tot = **0.8537 / 0.8293** regardless of retrieval | B0 §1.2d |
| Chunk-boundary yield | boundary-defined misses (`same_chunk`+`adjacent_chunk`) = 9/27 (33%) of ver84 near-misses, 3/12 (25%) of GT-WMR; `same_doc_elsewhere` dominates both (63% / 75%), golds up to 16–29 chunks away | D2 §1/§3 |
| R1 ranked adoptables | #1 Qwen3-Reranker-0.6B (+8.8 MTEB-R pts over BGE-v2-m3 on identical candidate pool [V]); #2 depth-first reranking K=64–128 (23/23 C2 items exposed at K=64); #3 contextual chunk enrichment (−49%/−67% top-20 failure rate [V]+[I]); #4 CRAG-pattern retrieval evaluator (pre-commit AUROC ≥ 0.75 both fixtures); #5 stratum-routed retrieval | R1 §5 |
| R2 confidence ranks | Rank 1 MiniCheck-class support-checking (770M FT5, claim-level, supervised-by-construction); Rank 2 conformal/LTT wrapper (**≥100 graded anchors needed vs 26 absence-GT items that exist**); Rank 3 discrete semantic entropy (needs k≈5–10 multi-sample captures; **zero exist**) | R2 §3 |
| Serving posture P0 (adopted) | `qwen3-14b-16k` co-resident with TEI pair (9.3 GB + ~11.1 GB ≈ 20.4 GB), `num_ctx=16384` proven end-to-end incl. truncation guard, `think:false` per ADR-09 | R2 §4; NB-NUMCTX commits `5a74d7a`+`96dc650` |
| Serving posture P1 (pilot only) | Qwen3.8-27B UD-Q4_K_S 15.4 GB — cannot co-reside (15.4 > 13.0 free); **stop-TEI maintenance windows only**; vLLM `thinking_token_budget` available inside the same windows; `qwen38:160k` rejected for interactive use (~50 GB fp16 KV rule-of-thumb) | R2 §2.4/§4 |
| Judge channel broken | amended rubric delivered on only **38/84 items** (Ollama v0.31.2 silent front-truncation) ⇒ every existing judge rate non-comparable-by-hash AND -by-delivery; fix ticket NB-JUDGE-CTX filed (ledger `d62fb87`) | B0 §1.2e/§4.1; NB-JUDGE-RERUN §3 |
| Confidence anchor deficit | 26 scored Waymo absence items exist; ≥100 graded anchors required before five thresholds carry measured semantics (~4× gap); graded answer-claim↔passage pairs: 0 | B0 §4; R2 §3.4 |
| Agentic GT deficit | every instrument scores one pass end-state; multi-paper exposure 13 items / 5 scored on ONE fixture; zero process scoring; W-A1..W-A5 set shapes total ≈105–135 scored items + trajectory layer — none authored | B0 §3 |
| Dispatch survival | ox-alpha 429s on ~1 request in 3 upstream (root-caused); commit-as-you-go mandatory; `setsid` forks so `$!` tracks a dead intermediate; kill zombies by PID from `/proc/*/cwd` scan, never `pkill -f`; oc-task model strings need the provider prefix | lessons §3.3d, §8.1, §8.4, §8.3 |

---

## 1. Honest framing — read before dispatching anything at "0.95"

1. **Single-shot retrieval cannot reach 0.95 on ver84 all-arm. This is proven arithmetic, not
   pessimism**: a perfect reranker over today's pools and extraction caps block-P@1 at 0.8750
   all-arm / 0.9333 text-arm @K=128, and paper-P@1 in the shipped fused config at 0.8971
   (B0 §1.2). Any plan that promises otherwise is lying.
2. **GT-WMR already clears the bar once citation honesty is counted**: member-block citation takes
   its passage hit-rate to 95.5% with monotone-zero risk (X-C §2). That is real and cheap, but it is
   a citation/metric-honesty fix — it must never be presented as a retrieval improvement.
3. **The plan's path to honest higher numbers is three-legged**: (a) citation honesty (QW-1),
   (b) upstream structural changes that move the *bound itself* — chunk-boundary/contextual work;
   the ver84 text-arm crosses 0.95 exactly when ONE of the four non-vision unexposed-at-K=128 D/E
   items becomes exposed (57/60 = 0.95; two make it comfortable) (B0 §2.4 #3, SB-1), and
   (c) agentic capability against purpose-built multi-hop GT (SB-2/SB-3).
4. **Two-arm statement to the operator, now** (B0 verdict language): priority fixture ✓ clearable;
   full-corpus text-arm ~0.93 achievable single-shot, all-arm bounded by vision/extraction limits.
   Extraction repair for figure numerics (B0 §2.4 #2) and the vision path are recorded as
   bound-movers but are **NOT commissioned by this plan** — commissioning them is an operator
   decision, not an agent's scope expansion.
5. **Denominator discipline**: until abstention exists, the 0.95 claim excludes known-absent queries
   and displays that arm next to the headline (B0 §2.3). Every number quoted anywhere in this
   programme carries the five-part qualifier `{metric, fixture, arm, pool depth, config}` or it is
   not a number.

---

## 2. Execution model — how this programme dispatches

One orchestrator + parallel dispatched agents + detached measurement processes, per
`docs/AGENT-OPERATIONS-LESSONS.md`: fan out *measurements* as detached `setsid` processes; spend
agent sessions only on judgment work (§7.3). The orchestrator writes briefs, dispatches, verifies
artifacts against git, merges lanes, owns integration. It never implements a ticket.

### Global constraints — encode into EVERY brief verbatim-adapted

1. **Assume every dispatch dies.** ox-alpha 429s on ~1 request in 3 upstream (lessons §3.3d,
   root-caused 2026-08-24). Each ticket IS a numbered list of commits; **commit ① is a stub committed
   before any real work**; commit after every green step. A dead dispatch must be resumable from
   committed state with zero loss. Name commit ① as a deliverable in its own right (§4.5b) —
   "commit-as-you-go" as a process note does not produce commits.
2. **One ticket, one worktree, one live dispatch** (§4.2): `git worktree add -b <branch>
   .claude/worktrees/<branch> main` off freshly-fetched main; rebase held branches before dispatch
   (§4.3). Before ANY dispatch check for queued chain scripts (§4.7). Never `git checkout` inside
   another session's checkout.
3. **Resume vs restart** (§3.2/§4.6): resume the session id only if the dispatch died mid-task; if a
   session already finished its phase, re-dispatch FRESH with a narrow append-only brief.
4. **Verify death honestly** (§3.3d/§3.3c): exit 0 + zeroed tokens + log ending at
   `llm runtime selected` = dead, not done. Confirm artifact existence via git (`git ls-tree`,
   `git cat-file -e ref:path`) — never `ls` of someone else's working tree (§8.2). Probe
   intermittent failures N times, not once.
5. **`setsid` fork trap** (§8.1): `$!` after `setsid nohup ... &` tracks a dead intermediate. Liveness
   = scan `/proc/*/cwd` for the worktree path or query the per-dispatch session store. When a lane
   dies repeatedly, kill zombies by exact PID from the scan BEFORE re-dispatching (§8.4) — never
   `pkill -f` patterns your own command line contains (§6b.3).
6. **File ownership partitions concurrency** (§4.1): two concurrent branches may not touch the same
   file. Ownership is stated per ticket below; hold a ticket rather than run it into a conflict.
7. **Baseline re-read at dispatch time** (§4.4): each brief states "baseline is N passed" fetched
   fresh from that worktree's merge-base, not quoted from this doc.
8. **Waymo runs name the collection explicitly**: `--collection waymo_av_safety` on every
   Qdrant-touching command. Omitting it silently queries the wrong corpus.
9. **Foundation paths are gated** (`contracts/`, `rag/config.py`, `config.example.yaml`,
   `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/` — CODEOWNERS/T-F7 sign-off by
   `@MKamel1`). Designs route around them: experiment reports go under `docs/eval-reports/data/`;
   harness code lives in `scripts/` or throwaway `app/exp_*.py`. Anything that genuinely must touch a
   frozen path OR a contract-reserved act (e.g. populating `GroundedResult.metadata`, new MCP tool
   enumeration) gets batched into ONE rider PR and flagged to the operator before dispatch — never
   implemented blindly.
10. **Cross-fixture no-average rule** (PREC-1 §5): block metrics are fixture-conditioned. Any claimed
    improvement reports BOTH fixtures' numbers, changes exactly one variable per run, and is believed
    only if the other fixture holds as held-out control. Never average, compare across, or trade
    between fixtures.
11. **Ceiling-check before freezing any new metric definition** (lessons §7.2): compute the
    achievability bound in thirty seconds of arithmetic before freezing protocol text — including new
    agentic metrics (hop-efficiency, decomposition coverage).
12. **Docs obligations ride with each landing PR** (AGENT-PROCEDURES §B): BACKLOG row, PROJECT-STATUS
    ledger entry in the same PR, HISTORICAL banners same-PR.
13. **CI enforcement locally before every push**:
    `GITHUB_EVENT_PATH=/tmp/fake_push_event.json GITHUB_EVENT_NAME=push python -m ci.run_enforcement`.
    A local pytest pass says nothing about the gate (lessons §1.1–1.2).

### Ticket ID scheme

Waves `P0` (prereqs) → `P1` (quick wins) → `P2` (structural bets) → `P3` (integration). Ticket IDs
`P0-n` / `QW-n` / `SB-n` / `IN-n`. Branches `P95-<id>-<slug>`. Each ticket lists owner files, numbered
commits (stub first), verification commands, gates, and the failure bucket / benchmark it targets.

---

## 3. Wave map

```
Wave P0 (prereqs, parallel)          P0-1 NUMCTX merge · P0-2 metric ratification · P0-3 multihop-GT authoring PLAN
        P0-1 ──gate──▶ every GPU-serving lane (QW-2 arms, QW-3 arms, SB-3 posture, SB-4)
        P0-2 ──gate──▶ every headline claim (IN-1 sign-off target)
        P0-3 ──gate──▶ SB-2 (authoring starts only from an approved plan)
Wave P1 (quick wins, max parallel)   QW-1 X-C adoption design note · QW-2 confidence surface v0 · QW-3 reranker-seat experiment
        QW-1 sign-off route ──▶ ONE batched rider PR (constraint 9)
Wave P2 (structural bets, parallel)  SB-1 boundary mitigation · SB-2 multihop-GT authoring · SB-3 agentic loop v0 · SB-4 Qwen3.8 pilot
        SB-2 first authored batches ──gate──▶ SB-3's evaluation arm
Wave P3 (integration, serial-ish)    IN-1 adopted-stack dual-fixture runs · IN-2 calibration collection → conformal fit
```

Dependency edges, exhaustive:

- P0-1 ∥ P0-2 ∥ P0-3 — fully independent (merge bookkeeping / operator decision / judgment doc).
- QW-1 ∥ QW-2 ∥ QW-3 — disjoint files (design doc / exp script + generation captures / reranker exp
  script + config delta). QW-2 and QW-3 measurement arms need P0-1 merged (GPU postures assume the
  truncation guard); QW-1 needs nothing.
- SB-1 ∥ SB-2 ∥ SB-4 — independent lanes. SB-3's evaluator half may start anytime (labeled seeds =
  existing fixtures); SB-3's *evaluation* half needs SB-2's first authored batch AND P0 posture.
- IN-1 needs the adoption verdicts it integrates (QW-1 rider merged if signed, QW-3 adopt/reject,
  SB-1 adopt/reject) + P0-2's ratified metrics. IN-2 needs the NB-JUDGE-CTX fix landed first; its
  conformal fit needs ≥100 anchors collected.
- GPU serialization is cross-wave: GPU-heavy arms schedule on `.gpu.lock`; they do not race it.

---

## 4. Tickets

### Wave P0 — prerequisites (parallel-safe; none implement new science)

- [ ] **P0-1 — finish the NUMCTX merge (reference; do NOT duplicate the work).**
      The num_ctx/truncation-guard work is in flight on branch `NB-NUMCTX-fix` (measurements +
      sentinel-verified 16384 window + truncation guard, commits `cdf4c5f`/`5a74d7a`/`96dc650`). This
      ticket ONLY: verify branch state against git (not against any working tree, lessons §8.2),
      complete review/merge to `main` if not already landed, record PROJECT-STATUS ledger entry.
      Orchestrator-direct; no dispatch warranted.
      Owns: merge of `NB-NUMCTX-fix` → `main`; `docs/PROJECT-STATUS.md` row.
      Commits: ① merge/review commit(s) on that branch's existing history ② status-ledger entry.
      Verification: `git log --oneline main -- grep NUMCTX paths` shows landed; `pytest` green;
      `ci.run_enforcement` PASS on the merge result; `gh run list --branch main --limit 3` read
      (lessons §1.1).
      Gates: every GPU-serving lane below. Targets: serving-posture prerequisite for F-bucket work
      (R1 §1) and confidence/agentic arms.

- [ ] **P0-2 — RATIFY the programme's metric definitions (operator sign-off item; B0 §2).**
      Put the operator's "precision ≥ 0.95" onto named instruments with shown achievability bounds:
      primary = paper-level P@1, answerable arm, shipped fused config; secondary = block-level P@1,
      text-answerable arm, pool depth stated; every reported number carries the five-part qualifier
      `{metric, fixture, arm, pool depth, config}`; forbidden as gates: P@10 (retired, ~1/k wall),
      full-population pricing before abstention exists (cap 0.8537/0.8293), answer-level precision
      until a delivered-rubric judge run exists. Record the ratification + the two-arm statement (§1
      item 4 above) in PROJECT-STATUS's tuning-decision section (decision-A precedent).
      Owns: `docs/PROJECT-STATUS.md` decision entry + short ratification addendum
      `docs/eval-reports/2026-08-26-precision95-metric-ratification.md` (new file, quotes B0 §2 tables
      verbatim).
      Commits: ① stub addendum with the frozen definitions table ② operator sign-off header + status
      entry.
      Verification: addendum renders both bound tables with denominators; sign-off line present;
      no fixture averaged anywhere in the text (grep-check).
      Gates: IN-1 (no headline claim without ratified definitions); informs every brief's Targets
      line. Targets: prevents a second gates-B/D freeze-time failure (lessons §7.2).

- [ ] **P0-3 — multi-hop GT authoring PLAN (B0 §3 gap analysis → executable spec).**
      Turn W-A1..W-A5 into an authoring-ready spec: per-set sizing via explicit power calculation
      (T-DOC-BOOK-EVAL-115 precedent) against expected effect size; per-item shape (gold sub-goal
      graph fields for W-A5, per-sub-part absence logs for W-A4); the openevidence-§3 authoring regime
      (two independent model authors blind to each other → third-session cross-verification with
      mechanical re-checks → adversarial second pass over stated probe denominators → spot-check the
      checker → disclosed drift, `duplicate_of` policy, substring-fidelity machine checks, frozen-
      protocol §5.8 no-edit-after-retrieval rule); trajectory-layer verification extended per graph
      node. The AUTHORING itself is Wave P2 (SB-2) under this regime — this ticket plans it.
      Owns: `docs/eval-reports/2026-08-27-multihop-gt-authoring-plan.md` (new file).
      Commits: ① stub with set-shape table copied from B0 §3.2 ② power calcs + regime checklist ③
      final spec.
      Verification: every set has n derived from a stated effect size at α/power, not vibes; regime
      steps enumerated as checkboxes; new-metric candidates (hops-to-answer, decomposition coverage)
      each have a §7.2 reachability note.
      Gates: SB-2. Targets: the agentic benchmark gap (F5 + process-blindness, R1 §1/§4).

### Wave P1 — quick wins (max parallel; disjoint files)

- [ ] **QW-1 — X-C member-block citation ADOPTION: design note FIRST, foundation-flagged, no blind
      implementation.**
      Evidence (already measured, monotone-zero risk): ver84 dense 78.1%→84.4%, GT-WMR fused
      93.9%→95.5% (X-C §2). Write the adoption design note selecting between X-C §3's variants:
      Variant C (`get_chunk_members` MCP tool — touches `contracts/mcp_server.py` tool enumeration)
      vs Variant A (populate contract-reserved `GroundedResult.metadata["member_block_ids"]` slot +
      DATA-CONTRACTS §M7 paragraph). STOP at the design note: every caller-facing route crosses a
      foundation-protected path or a contract-reserved act — file it for the ONE batched rider PR
      (constraint 9) and get T-F7 sign-off BEFORE any implementation dispatch.
      Owns: `docs/design-notes/2026-08-28-xc-member-citation-adoption.md` (new; cites X-C §3 diff
      sketches). Does NOT touch `contracts/` in this ticket.
      Commits: ① stub with variant comparison table ② full note with recommendation + rider-PR diff
      preview.
      Verification: note states measured effect sizes with fixtures/denominators; names the exact
      frozen paths each variant touches; contains NO implementation commits (`git diff main --name-only`
      shows docs only).
      Gates: rider PR (post-sign-off) → IN-1. Targets: citation honesty (B0 §2.4 lever 1); converts
      anchor-exactness artifacts invisible to any reranker (D2 §2).

- [ ] **QW-2 — confidence surface v0: MiniCheck-class support-checking, raw score + prototype label
      only (R2 rank 1; B0 §4 constraints honored).**
      Stand up MiniCheck-FT5 (770M) as an offline experiment over the EXISTING generation captures
      (`fixtures/eval/runs/2026-08-23-waymo-generation-run.*`, 84 answers × prompt variants — reuse,
      do not regenerate): score each answer sentence × actually-served passages → support fraction.
      Ship semantics honestly: raw score + explicit "unvalidated prototype" label; NO level language,
      NO probability wording, absent arm stays with abstention logic (it measures support, not truth).
      5-level thresholds are EXPLICITLY OUT OF SCOPE here — gated on IN-2's calibration data
      (≥100 graded anchors, B0 §4). If the score ever becomes an MCP-visible field, that edge is
      contracts-gated (constraint 9) — not in this ticket.
      Owns: `app/exp_confidence_v0_support.py` (throwaway exp convention) +
      `docs/eval-reports/2026-08-28-confidence-v0.md` (+ data under `docs/eval-reports/data/`).
      Commits: ① stub + capture-loading plumbing ② scorer integration + score dump ③ report.
      Verification: run offline over stored captures (zero paid APIs); model download happens once,
      GPU arm scheduled on `.gpu.lock`; report prints per-fixture score distributions separately
      (no averaging); states the wrong-context-high-score failure mode with an example.
      Gates: IN-2 (score family feeds the conformal wrapper). Targets: confidence-surface gap (B0
      §4 instrument #8 UNSOUND-today verdict; generation layer never measured as signal source,
      R2 §3).

- [ ] **QW-3 — reranker-seat upgrade EXPERIMENT: Qwen3-Reranker-0.6B, measure before adopt (R1 #1).**
      A/B in one harness on both fixtures: shipped BGE reranker vs Qwen3-Reranker-0.6B (fallback arm:
      PyLate/GTE-ModernColBERT late-interaction as competing candidate, R1 §3.1). Verify TEI hosting
      compatibility FIRST (R1 serving note); if awkward, 0.6B fits beside everything else on the
      shared card. Report block-P@1 + full rank histogram per fixture AGAINST THE PRE-COMMITTED
      CEILINGS (perfect-ordering 0.7812/0.9394 over top-10; depth bounds 0.8750/0.9333 @K=128) —
      not against vibes. Adoption decision is a separate verdict commit; no config flip inside this
      ticket. Re-run the F6 feature census post-change IF adopted (deeper pools shift distributions;
      NB-R1 §5 #2 caution).
      Owns: `app/exp_nb_rr_qwen_reranker.py` + dated report + data JSONs under
      `docs/eval-reports/data/`. Config deltas live in the worktree only until the verdict.
      Commits: ① stub + harness plumbing ② BGE baseline reproduction arm ③ Qwen3-Reranker arm
      ④ verdict report.
      Verification: retrieval eval invocations pass `--collection waymo_av_safety` (constraint 8);
      both fixtures' tables in the report (constraint 10); vendor numbers labeled [V] and local
      numbers separated; ceiling lines printed next to results.
      Gates: adoption verdict feeds IN-1; interacts with SB-1 depth knobs (coordinate ownership).
      Targets: F1 near-misses at rank 2 (7/18 ver84, 8/12 GT-WMR sit there) + F2 partially.

### Wave P2 — structural bets (parallel lanes)

- [ ] **SB-1 — chunk-boundary mitigation experiments (cite D2 yields; R1 #3 mechanism).**
      Boundary classes explain 33%/25% of near-misses but `same_doc_elsewhere` dominates (63%/75%) —
      so experiment order: (a) late-chunking-style section-scoped embedding variant (32k-ctx embedder
      already hosted, zero generative calls) targeting boundary + sibling-section findability;
      (b) neighbor-chunk score smoothing across adjacent blocks — R1 found NO published measurement;
      treat as local experiment with the D2 strata as instrument, pre-registered criterion, expect
      nothing; (c) Anthropic-style per-chunk contextualization via qwen3-14b only as heavy fallback.
      Measure NB-D2 boundary-stratum re-run + block-P@1 both fixtures; track anchor-exactness
      artifacts separately (enrichment may shift which block is gold-adjacent). Full re-embed/reindex
      is ingest-side and touches only the rebuildable Qdrant projection — SQLite truth untouched;
      still serialize the big index rebuild through maintenance scheduling, not the GPU lock alone.
      Owns: `app/exp_chunk_boundary_*.py` scripts + dated report + data dir. Does NOT touch
      `rag/chunker.py` in the experiment ticket; adoption (if any) becomes its own app-level change.
      Commits: ① stub + stratum-replay harness ② arm (a) ③ arm (b) ④ report/verdict.
      Verification: `--collection waymo_av_safety` everywhere; one variable per run; both fixtures'
      boundary-stratum tables; verdict states whether ANY non-vision unexposed-at-K=128 D/E item got
      exposed (the 57/60 = 0.95 trigger, B0 §2.4 #3).
      Gates: adoption feeds IN-1. Targets: F3 boundary misses; partially F1/F2 tail.

- [ ] **SB-2 — multi-hop GT AUTHORING under two-model mutual verification (executes P0-3's plan).**
      Author W-A1 (decomposition-required) and W-A2 (iterative-retrieval-required) first slices per
      the approved plan, under the openevidence-§3 regime verbatim: two independent blind authors →
      third-session read-only cross-verify + independently re-run mechanical checks → adversarial
      second pass on riskiest items (absence claims) over stated probe denominators → fourth-agent
      spot-check of the checker → disclosed drift, machine-checked excerpt fidelity (difflib ≥85%
      coverage then substitute exact DB span, log `_metadata.corrections`; never hand-type excerpts,
      lessons §7.4). Fixtures stay un-blended; items spread across BOTH fixtures per B0 §3.2 W-A3
      symmetry note where applicable.
      Owns: new fixture files under `fixtures/` are FOUNDATION-GATED (constraint 9) — author into
      `docs/eval-reports/data/` drafts; the promotion PR into `fixtures/eval/` rides the batched
      rider PR with sign-off.
      Commits: ① stub + authoring protocol copy ② author-A set ③ author-B set ④ cross-verification
      report ⑤ adjudicated draft set.
      Verification: counts asserted out loud (items checked, probes run — lessons §1.5); every gold
      anchor resolves in `papers.db`; no item edited after any retrieval output was seen for it.
      Gates: first adjudicated batches gate SB-3's evaluation arm. Targets: the agentic benchmark gap
      (B0 §3: 13 exposed / 5 scored today, zero process scoring).

- [ ] **SB-3 — agentic loop prototype v0 (posture P0; CRAG-pattern evaluator; query decomposition)
      against NEW multi-hop GT.**
      Build the loop as an offline prototype under posture P0 exactly (qwen3-14b-16k co-resident with
      TEI, `num_ctx=16384` with the truncation guard, `think:false` per ADR-09 — R2 §4): (a) CRAG-style
      retrieval evaluator scoring retrieved-context sufficiency → {proceed, decompose, abstain}
      actions; pre-commit the falsification criterion BEFORE running: AUROC separating known-absent
      from answerable arms ≥ 0.75 on BOTH fixtures (NB-C2's bar; CRAG never published absent-query
      behavior — hypothesis, not importable result, R1 §5 #4); (b) IRCoT/Self-Ask-style decomposition
      routed by stratum (multi-hop/hard/negation flags), never global — decomposition has negative
      passage-level evidence on non-multi-hop data (R1 §2.4). Evaluate ONLY on SB-2's first adjudicated
      batches + existing fixtures as controls; report end-state AND process metrics (hops-to-answer,
      sub-goal coverage) with their §7.2 reachability notes. Loop stays OUT of MCP product surface —
      `app/exp_agentic_loop_v0.py` only.
      Owns: `app/exp_agentic_loop_v0.py` + evaluator training/seeding data under
      `docs/eval-reports/data/` + dated report.
      Commits: ① stub + posture config plumbing ② evaluator arm ③ decomposition arm ④ evaluation
      report.
      Verification: posture assertions logged at startup (model tag, num_ctx, think flag); GPU arms
      serialized; both control fixtures reported alongside GT-batch results; no product-code edits
      (`git diff main --name-only` = app/exp_* + docs).
      Gates: needs P0-1 (posture), SB-2 batch-1 (evaluation), existing absence arms (evaluator bar).
      Targets: F5 multi-paper synthesis, F6 abstention signal class, F4 hard/negation (routed).

- [ ] **SB-4 — Qwen3.8-27B UD-Q4_K_S pilot in stop-TEI windows (R2 posture P1).**
      Pilot protocol, house style: inside a declared maintenance window (TEI stopped — 15.4 GB weights
      cannot co-reside, R2 §2.4), serve via Ollama; if thinking-budget economics become requirements,
      serve the SAME window through vLLM (`--reasoning-parser qwen3` + `thinking_token_budget`;
      `gpu_memory_utilization` claims total VRAM so vLLM also cannot share with TEI — window-only).
      Avoid q4_0 KV quantization (documented repetition hazard, ollama PR #17566 discussion); prefer
      q8_0 KV if extension needed. A/B against posture P0 on judge-quality tasks over the existing
      captures and loop tasks from SB-3's harness. NO standing infra change without a winning A/B;
      restore TEI and verify retrieval health (`python -m app.doctor`) before the window closes.
      Owns: `docs/eval-reports/2026-08-XX-qwen38-pilot.md` + pilot script under `scripts/`.
      Commits: ① stub + protocol with pre-registered comparisons ② pilot results ③ verdict.
      Verification: window open/close checks logged (doctor green after close); estimates labeled
      estimate-class (KV arithmetic is rule-of-thumb, R2 §2.4); both postures' outputs judged under
      IDENTICAL delivered prompts (count them — NB-JUDGE-CTX lesson).
      Gates: none (independent lane); outcome informs future serving decisions only. Targets:
      capability headroom for the agentic half; NOT part of any 0.95 claim.

### Wave P3 — integration (after adoptions resolve)

- [ ] **IN-1 — full dual-fixture runs of the adopted stack, scored against RATIFIED metrics.**
      One config state containing only ADOPTED changes (each with its verdict commit: QW-1 rider if
      signed, QW-3 adopt/reject, SB-1 adopt/reject); run `scripts/nb_eval_runner.py` dual-fixture;
      emit the standard combined table (R@10/MRR/paper-P@1/block-P@1, answerable + absent arms
      reported separately, pool depths stated) as dated JSON + md. Each adoption validated against
      the other fixture as held-out control (constraint 10) BEFORE it is believed; headline numbers
      formatted with the five-part qualifier and checked against P0-2's ratified gates. Absent arm
      displayed next to every headline (B0 §2.3).
      Owns: dated run pair under `docs/eval-reports/data/` + summary report; PROJECT-STATUS ledger
      entry.
      Commits: ① stub ② adopted-stack run artifacts ③ summary + ledger.
      Verification: runner exits green with artifact guard (silent-death check, D4 pattern); numbers
      reproduce from stored records; `ci.run_enforcement` PASS; no fixture averaged anywhere.
      Gates: closes the precision leg of the programme. Targets: the ratified primary/secondary
      gates themselves.

- [ ] **IN-2 — calibration data collection → conformal level fit (only when anchors exist).**
      Sequence: (1) land the NB-JUDGE-CTX delivery fix (ledger `d62fb87`) and run ONE clean judge
      re-run over the EXISTING ~276 captured claims (delivered-rubric counts asserted per item);
      (2) collect graded anchors toward ≥100 absence-arm items (≈4× the current 26, B0 §4) plus the
      ~200–300 answer-claim↔passage support pairs (R2 rank 1 requirement) drawn across BOTH fixtures'
      strata from real query traffic; (3) capture k≈5 samples/question at moderate temperature for
      semantic-entropy features (today: zero multi-sample records); (4) ONLY THEN fit split-conformal/
      LTT cut-points (Rank 2 wrapper) on the winning score(s); publish per-bin measured error rates
      next to any level label — a level without a measured rate is decoration (R2 §3.4); re-fit after
      any corpus refresh or model swap (Kumar et al. coverage-collapse caveat).
      Owns: `app/exp_calibration_collect.py` + anchor-set drafts under `docs/eval-reports/data/`
      (promotion into `fixtures/` = rider PR, constraint 9) + dated calibration report.
      Commits: ① stub + collector plumbing ② judge re-run artifacts ③ anchor sets ④ conformal fit +
      report.
      Verification: anchor counts printed against the ≥100 / ~200–300 floors; exchangeability notes
      (what changed since capture); reliability table per level; no threshold published off <20
      items/level (B0 rule-of-thumb).
      Gates: unlocks QW-2's 5-level thresholds (until then raw score + prototype label stands).
      Targets: confidence-surface gap end-to-end (B0 §4; R2 §§1.6/3.4).

---

## 5. Verification & completion audit for the programme

Done when ALL hold:

1. P0-1 merged and verified against `main` via git (not a working-tree listing); posture P0 provable
   from committed code.
2. P0-2 ratified definitions recorded WITH operator sign-off; no headline number anywhere in the
   programme lacks the five-part qualifier.
3. At least one P1 verdict adopted or rejected WITH both-fixture evidence, behind its own merged PR
   with CI watched to conclusion; QW-1's foundation routing resolved explicitly (signed rider PR or
   recorded deferral — not silence).
4. SB-2's first adjudicated multi-hop batches exist under the openevidence-§3 regime with counts
   asserted aloud; SB-3 evaluated against them or its gate recorded as unmet.
5. IN-1's adopted-stack dual-fixture run exists with both arms separate; IN-2's anchor count stated
   against the ≥100 floor (met, or honestly short with the coarse-2–3-level fallback noted).
6. `pytest` green + `ci.run_enforcement` green on every branch at merge time; no foundation-path diff
   without recorded sign-off; docs obligations paid on every landing PR.

---

## 6. Self-review (written before execution, per house format)

- **Does any ticket promise 0.95 on ver84?** No — §1 forbids it in prose and every brief will carry
  the ceiling lines (0.8750/0.9333 @K=128; paper-P@1 0.8971 fused). The plan's honest upside on ver84
  is bound-moving (one exposed D/E item = exactly 0.95 text-arm) plus citation honesty, and it says
  which is which.
- **Does any ticket average across fixtures?** No — constraint 10; SB-2 deliberately spreads GT across
  BOTH fixtures because current exposure is lopsided (B0 §3.2 W-A3 symmetry note).
- **Is anything foundation-gated hidden in fine print?** Checked: QW-1 stops at a design note; SB-2/IN-2
  author fixture drafts outside `fixtures/` and ride ONE batched rider PR; QW-2 keeps its score out of
  MCP surfaces; SB-3 stays `app/exp_*`. If the operator signs the rider, implementation gets its own
  dispatched tickets with the sign-off hash in the brief.
- **Dispatch-survival encoded?** Yes — stub-first numbered commits in EVERY ticket including
  orchestrator-direct ones; setsid/$! and zombie-scan rules (constraints 1/5); queued-chain check and
  one-worktree-per-dispatch (constraint 2); death-verification via git not `ls` (constraint 4);
  model-string prefix probe before any fan-out (§8.3).
- **GPU contention?** Named per ticket (QW-2/QW-3/SB-3/SB-4 serialize on `.gpu.lock`; SB-1's index
  rebuild scheduled in maintenance windows; SB-4 IS a maintenance-window lane and must not overlap
  SB-1's rebuild — sequenced by the orchestrator).
- **What would falsify this plan's structure?** If QW-3's local harness contradicts the vendor delta
  (reranker swap ≈ flat on both fixtures), the ordering lever dies cleanly and SB-1 inherits priority
  — the wave map absorbs it because adoptions are per-ticket verdicts, not plan-level assumptions. If
  SB-2 authoring stalls, SB-3 still ships its evaluator half against existing absence arms with its
  pre-committed AUROC bar. If IN-2's anchors can't reach ≥100, the honest output is the coarse 2–3-level
  surface (affordance A/B already demonstrates its value) — recorded, not forced.
- **Scope discipline?** Extraction repair for figure numerics and the vision path are recorded as
  bound-movers and deliberately NOT commissioned here (§1 item 4); HyDE/GraphRAG/Search-R1-class/
  Self-RAG-training remain rejected per R1 §5 with reasons on file.
