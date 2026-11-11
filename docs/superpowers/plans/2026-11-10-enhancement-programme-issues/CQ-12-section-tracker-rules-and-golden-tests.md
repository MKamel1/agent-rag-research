Title: CQ-12: Add golden tests and rules to the section tracker (standards)
Labels: wave:3-gated-change, area:corpus, size:M

## CQ-12 -- Add golden tests and rules to the section tracker (standards)

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Why.** `_heading_depth` and `_SectionTracker` (`rag/parser.py:457-494`, fed by the unfiltered `text_level >= 2` test at `:539`) are the root cause of stale clause numbers, furniture roots and NOTE/output-line roots in section paths; neither has a unit test. Reproduced today: a path such as `'FOR UL INTERNAL REFERENCE > 6.4.1.2 Risk'`. It is a standards and books problem (1,678 furniture-root chunks in standards against 150 in main), high for standards and low for main (review item c). It cannot fix flat books: the parser emits only levels 1 and 2.

**Scope.**
- In:
  - Golden tests first, pinning the reproduced defects, then rules that reject or renest headings whose text equals the last path component, drop stale numeric markers, and refuse NOTE/output lines as roots; expose the tracker as a pure function over stored blocks so it can be re-run on CPU.
  - Starts only if EV-18's gate count is 5 or more.
- Out (explicitly):
  - Books' chapter structure (needs the PDF outline join; not carried by the review). Rewriting stored `Block.section_path` (operator question F7). Re-embedding (CQ-15/CQ-16).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/parser.py`
- `rag/test_parser.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring and a skipped golden-test file listing the reproduced sequences
② golden tests pinning current behaviour on the reproduced examples (green)
③ rules change the golden expectations; tests updated in the same commit with the reason
④ pure function over stored blocks; CPU diff over the standards documents (read-only), counts and a 30-diff manual sample recorded in the commit body

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/parser.py rag/test_parser.py`
- `conda run -n agent-rag-research python -m pytest -q rag/test_parser.py -o addopts="--disable-socket"`
- `python scripts/chunk_quality_census.py <standards.db>` before/after counts on the in-memory re-derivation

**Acceptance / falsification criterion.** The three reproduced paths no longer occur; the in-memory re-derivation over standards blocks changes only paths with a stale numeric, furniture or NOTE root (every changed path listed, 30 sampled by hand with zero wrong); main sample unchanged within stated tolerance. Falsified if a sampled changed path is wrong.

**Gates / depends on.** Depends on: EV-18. Gates: CQ-13, CQ-15.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A tracker change affects every future parse. Mitigation: no live data is re-parsed here; golden tests pin the rest. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS via EP-5; DATA-CONTRACTS wording is RIDER-1 conditional item 7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.
