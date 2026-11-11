Title: EP-5: Batch BACKLOG and PROJECT-STATUS updates for waves 3 and 4
Labels: wave:4-rider, area:docs, size:S

## EP-5 -- Batch BACKLOG and PROJECT-STATUS updates for waves 3 and 4

**Review cross-reference:** S-13. **Wave:** W4 rider and what it unblocks.

**Why.** Same reason as EP-3 and EP-4: the gated tickets land verdicts (ADOPT, REJECT, UNDERPOWERED, closed-by-gate) that belong in the ledger and in PROJECT-STATUS section 5 (tried and failed) in one pass.

**Scope.**
- In:
  - BACKLOG rows flipped with SHAs, including tickets closed by their gate ('CLOSED -- gate not met: <report>'); ledger entries; section 5 entries for each REJECT; the list of on-ADOPT follow-on tickets the operator should now commission.
- Out (explicitly):
  - Writing the follow-on tickets themselves.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/PROJECT-STATUS.md`
- `docs/BACKLOG.md`

**Commits** (① is a stub, committed before any real work):
① stub: checklist of W3/W4 tickets and their gate outcomes
② BACKLOG rows + SHAs
③ PROJECT-STATUS ledger and section 5 entries
④ follow-on list

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `git cat-file -e <sha>^{commit}` for every SHA written
- Every verdict quoted equals its report's verdict line

**Acceptance / falsification criterion.** Every W3/W4 ticket has a row stating DONE, CLOSED-by-gate or BLOCKED with its reason; no verdict text differs from its report. Falsified if any SHA fails to resolve.

**Gates / depends on.** Depends on: EP-4, RQ-3, CQ-9, CQ-11, CQ-16, CQ-17, CQ-18, MC-4, RIDER-1, RQ-4. Gates: nothing further (programme close).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Haiku; S (up to 2 h of agent work). Mechanical work, no judgement calls.

**Risk and rollback.** Low. Rollback: revert.

**Docs to update in the same PR.** This ticket is the docs obligation for waves 3 and 4.
