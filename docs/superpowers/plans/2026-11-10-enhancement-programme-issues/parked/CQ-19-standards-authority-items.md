Title: CQ-19: Author 38 more standards ground-truth items for the weak stratum (authority or edition)
Labels: wave:1-no-gpu, area:eval, area:corpus, size:M, parked
Parked-until: start only if EV-18 shows authority-stratum hit@10 clearly below the other standards strata (at least 2 of the 4 current authority items missing at hit@10 while the other strata are strong); author only the stratum that is weak (the edition half, absorbed from CQ-20, is started only if the edition stratum is the weak one). Kill criterion: killed if no standards stratum is visibly weak in EV-18.

## CQ-19 -- Author 38 more standards ground-truth items for the weak stratum (authority or edition)

**Review cross-reference:** CQ-5 follow-up. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: start only if EV-18 shows authority-stratum hit@10 clearly below the other standards strata (at least 2 of the 4 current authority items missing at hit@10 while the other strata are strong); author only the stratum that is weak (the edition half, absorbed from CQ-20, is started only if the edition stratum is the weak one). Kill criterion: killed if no standards stratum is visibly weak in EV-18.

**Absorbs CQ-20** (CQ-20: Author 38 more standards edition-stratum ground-truth items). The merged ticket is one unit: author only the stratum that is visibly weak in the EV-18 baseline (the other half is not started); the two halves are sequenced on the shared hash file only.

**Why.** The authority stratum has 4 items (Q-STD-C-019..022), so any filter or tag effect is description only: with n=4 the best possible exact McNemar p is 0.125 and can never reach 0.05. CQ-5's pre-registered measurement (`docs/eval-reports/2026-11-10-cq5-standards-metadata.md` section 5) computes 42 items per stratum for a 30-point difference at alpha 0.05, power 80%, planning disagreement 0.5, so 38 more are needed. Absorbed from CQ-20: The edition stratum also has 4 items (Q-STD-A-021/022, B-021/022); same arithmetic as CQ-19: 42 per stratum needed, 38 to add (`docs/eval-reports/2026-11-10-cq5-standards-metadata.md` section 5). Edition questions are where BM25 scores 0.00 chunk@10 on n=4 (RV-3), so the stratum is the one that would show whether the standards metadata tags help.

**Scope.**
- In:
  - Author 38 new authority-stratum items from many different documents (the current four rest on four), phrased as a user would without hinting the tag, under the existing blind two-author plus cross-verification regime and `gt_tools.py verify`; recorded as a separate extension file with its own hash entry, dated addendum first.
  - Absorbed from CQ-20: Author 38 edition-stratum items (some naming an edition, some not, from many documents with superseded and current editions), same regime and extension-file procedure as CQ-19.
- Out (explicitly):
  - Running retrieval on them. Any change to the 128 existing items. The tag filters (CQ-5, done).
  - Absorbed from CQ-20: Running retrieval. Changing existing items. Using `status:current` as a filter in the design (excluded by CQ-5 because the gold documents may be superseded).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<date>-standards-gt-authority-extension/`
- `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`
- `docs/eval-reports/data/<date>-standards-gt-edition-extension/`

**Commits** (① is a stub, committed before any real work):
① stub: addendum and authoring protocol copy (strata definition, no-hint rule, hash procedure), before any item is written
② author A and author B draft files, blind to each other
③ cross-verification report with kills and fixes counted
④ adjudicated extension file, `verify` transcript and hash entry
⑤ [absorbed CQ-20] stub: addendum with the stratum definition and the named/unnamed edition quota
⑥ [absorbed CQ-20] author A and author B draft files
⑦ [absorbed CQ-20] cross-verification report
⑧ [absorbed CQ-20] adjudicated extension file, `verify` transcript and hash entry

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research python docs/eval-reports/data/2026-11-10-standards-gt/gt_tools.py verify <extension file>` passes (read-only against the standards database)
- Count of distinct source documents printed (target: at least 20)
- `conda run -n agent-rag-research python docs/eval-reports/data/2026-11-10-standards-gt/gt_tools.py verify <extension file>` passes

**Acceptance / falsification criterion.** 38 items pass verbatim-excerpt verification, 0 reuse a 6-word run of the excerpt, come from at least 20 distinct documents, are cross-verified by a reader other than the authors, and their SHA-256 is in the hash file before any run reads them. Falsified if any item fails `verify` or an excerpt is not verbatim in the stored chunk.

Absorbed from CQ-20: Same as CQ-19: 38 verified, cross-verified, hashed items from at least 20 documents, hash recorded before any run reads them. Falsified if any item fails `verify`.

**Gates / depends on.** Depends on: EV-11, EV-18. Gates: none.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Same-model-family authors and verifiers (0 kills on standards so far): residual defects are possible; the stratum stays labelled LLM-authored. Rollback: drop the extension file and its hash entry.

**Docs to update in the same PR.** The addendum and extension file are the docs (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
