Title: CQ-20: Author 38 more standards edition-stratum ground-truth items
Labels: wave:1-no-gpu, area:eval, area:corpus, size:M

## CQ-20 -- Author 38 more standards edition-stratum ground-truth items

**Review cross-reference:** CQ-5 follow-up. **Wave:** W1 do now, no GPU.

**Why.** The edition stratum also has 4 items (Q-STD-A-021/022, B-021/022); same arithmetic as CQ-19: 42 per stratum needed, 38 to add (`docs/eval-reports/2026-11-10-cq5-standards-metadata.md` section 5). Edition questions are where BM25 scores 0.00 chunk@10 on n=4 (RV-3), so the stratum is the one that would show whether the standards metadata tags help.

**Scope.**
- In:
  - Author 38 edition-stratum items (some naming an edition, some not, from many documents with superseded and current editions), same regime and extension-file procedure as CQ-19.
- Out (explicitly):
  - Running retrieval. Changing existing items. Using `status:current` as a filter in the design (excluded by CQ-5 because the gold documents may be superseded).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<date>-standards-gt-edition-extension/`
- `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`

**Commits** (① is a stub, committed before any real work):
① stub: addendum with the stratum definition and the named/unnamed edition quota
② author A and author B draft files
③ cross-verification report
④ adjudicated extension file, `verify` transcript and hash entry

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research python docs/eval-reports/data/2026-11-10-standards-gt/gt_tools.py verify <extension file>` passes
- Count of distinct source documents printed (target: at least 20)

**Acceptance / falsification criterion.** Same as CQ-19: 38 verified, cross-verified, hashed items from at least 20 documents, hash recorded before any run reads them. Falsified if any item fails `verify`.

**Gates / depends on.** Depends on: CQ-19. Gates: EP-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** As CQ-19; the hash file is shared with CQ-19, hence the sequencing. Rollback: drop the extension file and hash entry.

**Docs to update in the same PR.** PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
