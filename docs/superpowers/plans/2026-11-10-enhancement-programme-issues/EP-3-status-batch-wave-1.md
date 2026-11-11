Title: EP-3: Batch BACKLOG and PROJECT-STATUS updates for wave 1
Labels: wave:1-no-gpu, area:docs, size:S

## EP-3 -- Batch BACKLOG and PROJECT-STATUS updates for wave 1

**Review cross-reference:** S-13. **Wave:** W1 do now, no GPU.

**Why.** The common brief for this programme forbids parallel tickets from editing `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` (they are the two most conflict-prone files), so AGENT-PROCEDURES section B's ledger obligations are paid here, once per wave, from each ticket's 'Docs to update' list. The BACKLOG drift rows of RV-6 B.1 (SB-1, SB-3, P0-2/T-F7, FD-1, B-4, B-5) were corrected by EP-2 itself.

**Scope.**
- In:
  - For every wave-1 ticket merged: flip its row in the 'Enhancement programme (2026-11-10)' BACKLOG section to `DONE -- <sha>`; add one PROJECT-STATUS section 3 ledger entry; add section 2 entry-point rows and section 7 doc-map rows exactly where the ticket's docs line says a trigger fired.
  - Any further BACKLOG drift row found while flipping rows, each with its git evidence.
  - Record operator answers received so far (F1-F8) in PROJECT-STATUS section 6 as open or closed.
- Out (explicitly):
  - Any claim about retrieval quality (none exists until wave 2). Rewriting PROJECT-STATUS sections EP-1 already corrected on 2026-11-10; this ticket only appends ledger entries.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/PROJECT-STATUS.md`
- `docs/BACKLOG.md`

**Commits** (① is a stub, committed before any real work):
① stub: checklist of the wave-1 tickets with their merge SHAs, empty status cells
② BACKLOG row flips + punch rows 1,5,6,17,18
③ PROJECT-STATUS ledger, entry-point and doc-map rows
④ open-question status lines

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `grep -c 'IN PROGRESS' docs/BACKLOG.md` no longer lists SB-1
- Each ledger SHA exists: `git cat-file -e <sha>^{commit}` for every SHA written
- `git diff --stat` touches only the two owned files

**Acceptance / falsification criterion.** Every merged wave-1 ticket has a DONE row with a SHA that resolves and a ledger entry; no row says DONE for an unmerged ticket (checked by `git branch --contains <sha>` against the integration branch). Falsified if any SHA does not resolve.

**Gates / depends on.** Depends on: EP-6, EP-7, OP-2, OP-3, OP-4, OP-5, OP-6, OP-7, MC-1, MC-2, MC-3, RQ-1, RQ-2, RQ-5, EV-7, EV-8, EV-9, EV-10, EV-11, EV-12, EV-13, EV-14, EV-15, CQ-7, CQ-8, CQ-19, CQ-20. Gates: EP-4.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Haiku; S (up to 2 h of agent work). Mechanical work, no judgement calls.

**Risk and rollback.** Low. A wrong SHA is the failure; mitigation is the `git cat-file` check. Rollback: revert.

**Docs to update in the same PR.** This ticket is the docs obligation for wave 1.
