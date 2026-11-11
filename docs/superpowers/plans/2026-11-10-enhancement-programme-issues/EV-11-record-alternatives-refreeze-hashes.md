Title: EV-11: Record note-only duplicates as alternatives and re-freeze fixture hashes
Labels: wave:1-no-gpu, area:eval, size:S

## EV-11 -- Record note-only duplicates as alternatives and re-freeze fixture hashes

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
