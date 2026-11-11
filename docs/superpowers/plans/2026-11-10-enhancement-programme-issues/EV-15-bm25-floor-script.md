Title: EV-15: Add the plain BM25 floor script named EV-5b in the protocols
Labels: wave:1-no-gpu, area:eval, size:S

## EV-15 -- Add the plain BM25 floor script named EV-5b in the protocols

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
