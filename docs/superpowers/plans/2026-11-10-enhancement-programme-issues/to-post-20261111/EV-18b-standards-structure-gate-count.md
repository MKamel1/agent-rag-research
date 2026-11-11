Title: EV-18b: Produce the standards structure-gate count (remainder of EV-18)
Labels: wave:1-no-gpu, area:eval, area:corpus, size:S

## EV-18b -- Produce the standards structure-gate count (remainder of EV-18)

**Wave:** W1 no GPU. **Remainder of:** EV-18 (marked PARTLY DONE in `docs/BACKLOG.md`).

**Why.** The standards baseline ran on 2026-11-11 (`docs/eval-reports/2026-11-11-standards-baseline.md`): rule D-1 resolved to keep depth 128 (84/94 fused against 81/94 at depth 32) and S-1 is unresolved; but the structure-gate count was not produced (the report's "Not in this report" list). That count is the single trigger for the parked tickets CQ-8, CQ-12, CQ-13 and CQ-16 (start only if the count is 5 or more; killed if below 5). CQ-14 depends on a separate stub trigger that the stub-filter result already addresses. Until the count exists those tickets are stuck for lack of a number, not for lack of a decision.

**Gate definition (from EV-18 and the CQ-12 text).** The count of answerable standards misses at member-passage hit@10 whose gold chunk, or whose top-10 chunk, has a structure defect of a mechanical kind: a furniture root (running page furniture as the first section-path component), a numeric root, a NOTE or output-line root, or a split table. Mechanical rules come from `scripts/chunk_quality_census.py` and the RV-2 F-2.5 finding; the ticket must state each rule as code before counting, so the count is reproducible. The question list is printed with the count.

**Scope.** CPU only, from existing output. No new retrieval run.
- Inputs (exactly):
  - Per-question rows of the depth-128 fused arm: `docs/eval-reports/data/2026-11-10-standards-gt/runs/20261111T013215/depth128-fused.json` (fields `retrieved_chunk_ids`, `gold_block_id`, `passage_level`, `chunk_id_ambiguous`). This run directory is untracked in git; commit the single JSON (or the extracted miss list) as evidence so the count can be re-derived, or state in the report where it is kept.
  - The set: `docs/eval-reports/data/2026-11-10-standards-gt/standards_gt.json` (hash in `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`).
  - The standards corpus database, opened read-only, to resolve chunk ids to chunk text and section paths.
  - The existing analysis in `docs/eval-reports/data/2026-11-11-baseline-analysis/` (`standards_paired_arms.py` and its output) for the miss list.
  - `scripts/chunk_quality_census.py` and `rag/retriever.py::body_of` / `is_stub_chunk_text` for the stub and body rules.
- In: (1) list the answerable misses at depth 128 fused (member-passage hit@10, 94 scored items); (2) for each, resolve the gold chunk and the top-10 chunks and classify each against the stated rules; (3) report the count of qualifying misses, the list, and the per-row chunk ids it rests on; (4) state the CQ-12 trigger (5 or more) and the CQ-12 second kill clause (standards passage hit@10 leaving under 5 items of headroom: 94 scored minus 84 hits is 10, so that clause does not fire); (5) report the same count for the depth-32 arm as a sensitivity row; (6) also judge the CQ-19 authority-stratum trigger (at least 2 of the 4 authority items missing while other strata are clearly higher), which the baseline report left open, from the same rows.
- Out (explicitly): any structure fix (CQ-12 to CQ-16); any change to parser or chunker; any retrieval or GPU run; authoring new ground truth.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-standards-structure-gate.md`
- `docs/eval-reports/data/<run-date>-standards-structure-gate/` (miss list, classification table, the script)
- `scripts/standards_structure_gate.py` (only if the classification cannot be done by an existing script)

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the rules stated as code or text before any count
② miss list and classification table
③ count, trigger statements for CQ-8, CQ-12, CQ-13, CQ-16 and CQ-19, report

**Verification:**
**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- The script opens the database read-only and makes no network call
- The count is reproducible: re-running the script prints the same list and the same number
- A hand check of every qualifying question and 10 random non-qualifying misses is recorded in the report

**Acceptance / falsification criterion.** One number with the list of qualifying questions and the chunk ids each rests on; the trigger is stated as met or not met for each parked ticket it gates. Falsified if re-running the script changes the count, or if any qualifying miss cannot be shown from the stored chunk text.

**Gates / depends on.** Depends on: EV-18 run output (exists). Gates: CQ-8, CQ-12, CQ-13, CQ-16, CQ-19 (parked). The result may close several of them.

**Needs.** GPU: n · services up: none (database read-only) · operator sign-off: n · re-embed: n.

**Model tier and size.** Sonnet; S.

**Risk and rollback.** The classification rules are the judgement; stating them before counting guards against fitting them to the answer. Rollback: discard the report.

**Docs to update in the same PR.** Per `docs/AGENT-PROCEDURES.md` section B: flip this ticket's row in `docs/BACKLOG.md` to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 ledger; add a row to `docs/eval-reports/EXPERIMENT-REGISTER.md` for any new result; add a section 7 doc-map row for every new `docs/*.md`. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns.
