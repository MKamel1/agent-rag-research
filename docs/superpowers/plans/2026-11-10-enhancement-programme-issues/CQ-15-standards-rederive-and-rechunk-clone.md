Title: CQ-15: Re-derive standards paths from stored blocks and re-chunk on a clone
Labels: wave:3-gated-change, area:corpus, needs-gpu, needs-services, size:M

## CQ-15 -- Re-derive standards paths from stored blocks and re-chunk on a clone

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
