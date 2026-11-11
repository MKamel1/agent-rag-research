Title: EV-12: Amend the CQ-3 stub A/B pre-registration (fixtures, minimum effect)
Labels: wave:1-no-gpu, area:eval, size:S, parked
Parked-until: only after the decision to commission EV-21 (it is a pure prerequisite of EV-21). Kill criterion: killed with EV-21.

## EV-12 -- Amend the CQ-3 stub A/B pre-registration (fixtures, minimum effect)

**Review cross-reference:** S-05. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: only after the decision to commission EV-21 (it is a pure prerequisite of EV-21). Kill criterion: killed with EV-21.

**Why.** CQ-3's pre-registration names the wrong fixtures (the 210-question set and the legacy books set, which have no passage gold), has no minimum effect so one noise flip would ADOPT, and identifies stubs by anchor (ambiguous for 7.5% of standards chunks); the stub length threshold also differs across three tools (40, 60 and 80 characters; review section 2).

**Scope.**
- In:
  - Dated addendum appended to `docs/eval-reports/2026-11-10-cq3-stub-chunks.md`: fixtures are the standards, causal-books and papers-passage sets (post-EV-11 hashes); ADOPT needs net +3 items on at least one set and no stratum losing more than 1; stubs identified by chunk id (EV-9); the single binding stub definition for this A/B is the retriever's (40 characters) with the other two tools' thresholds stated as non-binding.
- Out (explicitly):
  - Changing any threshold in code (the three tools stay as they are). Running the A/B (EV-21). Editing the original pre-registration text: append only.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/2026-11-10-cq3-stub-chunks.md`

**Commits** (① is a stub, committed before any real work):
① stub: addendum heading with date and the four amendments as a list, committed before any stub A/B report exists
② addendum text with ceiling arithmetic for the new minimum effect (n of each set vs +3)
③ cross-check that every number cited resolves to a file

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `git log --diff-filter=A --format='%H %cI' -- <any stub A/B report>` shows no such file older than this addendum's commit

**Acceptance / falsification criterion.** Addendum is committed before any stub A/B report exists and states fixtures, ADOPT rule (net +3 on one set, no stratum worse by more than 1), chunk-id matching and the binding threshold; the ceiling note shows +3 is reachable on each set (n=94, 69, 61 answerable). Falsified if a stub A/B report predates the addendum.

**Gates / depends on.** Depends on: EV-9, EV-11. Gates: EV-21 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (not a protected path); the amended rule is a decision for the operator in PR review. · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. An addendum cannot undo a result already seen; ordering is enforced by dependency. Rollback: revert.

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
