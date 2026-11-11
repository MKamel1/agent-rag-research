Title: EV-11: Record note-only duplicates as alternatives and re-freeze fixture hashes
Labels: wave:1-no-gpu, area:eval, size:S

## EV-11 -- Record note-only duplicates as alternatives and re-freeze fixture hashes

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
