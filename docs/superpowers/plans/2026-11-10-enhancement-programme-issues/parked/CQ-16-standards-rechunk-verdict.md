Title: CQ-16: Rebuild the standards clone from re-derived paths and measure it against baseline (absorbs CQ-15)
Labels: wave:3-gated-change, area:corpus, area:eval, needs-gpu, needs-services, size:S, parked
Parked-until: start only if EV-18's structure-attributable miss count is 5 or more (net +3 must be reachable); the CQ-15 half (clone rebuild) also needs F2, F3 and F7. Kill criterion: killed if the EV-18 count is below 5 or the rebuilt clone shows fewer than 3 flipped questions; the CQ-15 half is killed if CQ-12, CQ-13 and CQ-14 are all killed, or F7 says keep stored paths and the operator will not pay the 35k re-embed.

## CQ-16 -- Rebuild the standards clone from re-derived paths and measure it against baseline (absorbs CQ-15)

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
