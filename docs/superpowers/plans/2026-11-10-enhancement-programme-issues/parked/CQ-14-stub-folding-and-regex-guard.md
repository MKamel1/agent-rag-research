Title: CQ-14: Fold heading-only chunks into the next group and guard normalisation regexes
Labels: wave:3-gated-change, area:corpus, size:M, parked
Parked-until: only after the EV-21 verdict; the regex guard only if CQ-16 proceeds. Kill criterion: killed if EV-21 is REJECT, or stub-at-rank-1 occurs on fewer than 3 answerable standards items, or fewer than 3 qualifying misses have a stub in the top 10.

## CQ-14 -- Fold heading-only chunks into the next group and guard normalisation regexes

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
