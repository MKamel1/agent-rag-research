Title: CQ-13: Add the running-furniture pre-pass and table sup/sub and span handling
Labels: wave:3-gated-change, area:corpus, size:M

## CQ-13 -- Add the running-furniture pre-pass and table sup/sub and span handling

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Why.** Running headers promoted to headings are a standards problem and are detectable positionally: 20 of 119 standards documents, 947 blocks, 1,678 chunks (4.7%) have a furniture string as their path root (RV-2 F-2.5); table conversion drops superscripts and rowspan content (`<10-8 h-1` instead of `<10^-8 h^-1`; 2,189 standards tables) (RV-2 F-2.10).

**Scope.**
- In:
  - Pre-pass in `_build_blocks`: key `(text with digits collapsed, 12-point y bucket)` per page; a text item recurring on at least 4 pages is furniture and skipped before the tracker; also runnable on stored blocks.
  - `markdownify` `sup_symbol`/`sub_symbol`, and rowspan/colspan expansion before conversion (fallback: `col: value` lines for irregular spans).
- Out (explicitly):
  - Main-corpus table HTML (not stored, needs a re-parse: not carried by the review). Re-embedding. Persisting `content_list` (explicitly not doing).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/parser.py`
- `rag/test_parser.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings for both changes and the 70% / 4-page criteria
② golden tests: the PMHF row and a severity table (`10^-8`, equal cell counts); a furniture case and a real repeating template heading that must survive
③ pre-pass implementation to green
④ table fix to green; CPU probe re-run on standards blocks

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/parser.py rag/test_parser.py`
- Positional probe re-run on stored standards blocks reports 0 furniture roots; template headings that repeat at different y survive (RV-2 F-2.5 check)
- `conda run -n agent-rag-research python -m pytest -q rag/test_parser.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Probe finds 0 furniture roots in standards; the real template heading survives; golden table tests pass with equal cell counts per row. Falsified if the 70% threshold removes a real template heading.

**Gates / depends on.** Depends on: CQ-12, EV-18. Gates: CQ-15.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** False positives delete real headings. Mitigation: y-clustering criterion and the survival test. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.
