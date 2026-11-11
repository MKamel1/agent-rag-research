Title: EP-4: Batch BACKLOG and PROJECT-STATUS updates for wave 2
Labels: wave:2-gpu-measure, area:docs, size:S

## EP-4 -- Batch BACKLOG and PROJECT-STATUS updates for wave 2

**Review cross-reference:** S-13. **Wave:** W2 first GPU session, measurements only.

**Why.** Wave 2 produces the first measured numbers for the new sets; they must land in the shipped-work ledger and the open-questions section in one pass, not from seven concurrent branches editing the same two files (same reason as EP-3).

**Scope.**
- In:
  - BACKLOG rows for EV-16 to EV-22 flipped with SHAs; PROJECT-STATUS section 3 ledger entries quoting each verdict and its report; section 5 (tried and failed) for any REJECT; section 6 for open questions (F3 answered or not, F6 bar, F8).
- Out (explicitly):
  - Interpreting results beyond what each report states. Editing reports.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/PROJECT-STATUS.md`
- `docs/BACKLOG.md`

**Commits** (① is a stub, committed before any real work):
① stub: checklist of wave-2 tickets with report paths, empty verdict cells
② BACKLOG rows + SHAs
③ PROJECT-STATUS ledger and section 5/6 entries
④ open-question status lines

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `git cat-file -e <sha>^{commit}` for every SHA written
- Every verdict quoted equals the verdict line in its report (grep)

**Acceptance / falsification criterion.** Each wave-2 ticket has a row and a ledger entry whose verdict text is copied from its report and whose SHA resolves. Falsified if any quoted verdict differs from the report.

**Gates / depends on.** Depends on: EP-3, EV-16, EV-17, EV-18, EV-19, EV-20, EV-21, EV-22. Gates: EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Haiku; S (up to 2 h of agent work). Mechanical work, no judgement calls.

**Risk and rollback.** Low. Rollback: revert.

**Docs to update in the same PR.** This ticket is the docs obligation for wave 2.
