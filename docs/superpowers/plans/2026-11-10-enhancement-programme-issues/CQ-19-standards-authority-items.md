Title: CQ-19: Author 38 more standards authority-stratum ground-truth items
Labels: wave:1-no-gpu, area:eval, area:corpus, size:M

## CQ-19 -- Author 38 more standards authority-stratum ground-truth items

**Review cross-reference:** CQ-5 follow-up. **Wave:** W1 do now, no GPU.

**Why.** The authority stratum has 4 items (Q-STD-C-019..022), so any filter or tag effect is description only: with n=4 the best possible exact McNemar p is 0.125 and can never reach 0.05. CQ-5's pre-registered measurement (`docs/eval-reports/2026-11-10-cq5-standards-metadata.md` section 5) computes 42 items per stratum for a 30-point difference at alpha 0.05, power 80%, planning disagreement 0.5, so 38 more are needed.

**Scope.**
- In:
  - Author 38 new authority-stratum items from many different documents (the current four rest on four), phrased as a user would without hinting the tag, under the existing blind two-author plus cross-verification regime and `gt_tools.py verify`; recorded as a separate extension file with its own hash entry, dated addendum first.
  - If frozen before EV-18 launches, EV-18 may run them as a descriptive stratum; otherwise they wait for a later run.
- Out (explicitly):
  - Running retrieval on them. Any change to the 128 existing items. The tag filters (CQ-5, done).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<date>-standards-gt-authority-extension/`
- `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`

**Commits** (① is a stub, committed before any real work):
① stub: addendum and authoring protocol copy (strata definition, no-hint rule, hash procedure), before any item is written
② author A and author B draft files, blind to each other
③ cross-verification report with kills and fixes counted
④ adjudicated extension file, `verify` transcript and hash entry

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research python docs/eval-reports/data/2026-11-10-standards-gt/gt_tools.py verify <extension file>` passes (read-only against the standards database)
- Count of distinct source documents printed (target: at least 20)

**Acceptance / falsification criterion.** 38 items pass verbatim-excerpt verification, 0 reuse a 6-word run of the excerpt, come from at least 20 distinct documents, are cross-verified by a reader other than the authors, and their SHA-256 is in the hash file before any run reads them. Falsified if any item fails `verify` or an excerpt is not verbatim in the stored chunk.

**Gates / depends on.** Depends on: EV-11. Gates: EP-3, CQ-20.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Same-model-family authors and verifiers (0 kills on standards so far): residual defects are possible; the stratum stays labelled LLM-authored. Rollback: drop the extension file and its hash entry.

**Docs to update in the same PR.** Addendum and extension file are the docs; PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
