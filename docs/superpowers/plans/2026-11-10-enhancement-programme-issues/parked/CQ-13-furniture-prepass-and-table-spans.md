Title: CQ-13: Add the running-furniture pre-pass (standards)
Labels: wave:3-gated-change, area:corpus, size:M, parked
Parked-until: start only after CQ-12 has run and its in-memory re-derive leaves furniture roots among the qualifying-miss questions. Kill criterion: killed if zero furniture roots remain among the qualifying-miss questions.

## CQ-13 -- Add the running-furniture pre-pass (standards)

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
