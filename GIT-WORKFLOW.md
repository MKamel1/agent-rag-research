# GIT-WORKFLOW — branch, PR, CI, and foundation-freeze procedure

Read this before your first commit. It's the concrete, mechanical answer to "how do we keep ~15 tickets
across 6 owners from colliding" for a build team with no cross-session memory (CONVENTIONS.md §0).

## Branch naming — reuse ticket IDs, no second scheme

Every ticket already has a stable ID (T-A1, T-F1, …, WORK-BREAKDOWN.md). Don't invent a parallel naming
convention. Because WORK-BREAKDOWN's M1a (write failing tests) and M1b (implement to green) are separate
milestones, they are **separate branches and separate PRs** per ticket:

- `T-<id>-tests` — the M1a branch: commits the failing/non-implemented test suite only.
- `T-<id>-<slug>` — the M1b branch: the implementation, opened only after `T-<id>-tests` has merged.

Example: `T-C1-tests` → merges → `T-C1-chunker` opens.

Owner F's tickets (T-F1…T-F7) don't need the split — see `owners/OWNER-F.md`.

## Commit messages and authorship

Subject: `T-<id>: <imperative what>` (e.g. `T-C1: add Chunker unit tests against frozen interface`).
Body: the *why*, not a restatement of the diff.

Ad-hoc documentation-only fixes not tied to a WORK-BREAKDOWN ticket use a `T-DOC<n>` subject prefix
instead (e.g. `T-DOC1`, `T-DOC2`, informally numbered) — these aren't formal tickets and aren't tracked
in WORK-BREAKDOWN.md.

**Single author, no trailers.** Every commit in this repo is authored as
`MKamel1 <47995864+MKamel1@users.noreply.github.com>` (repo-local `git config user.name`/`user.email` —
set this before your first commit, regardless of which tool or model is actually doing the typing). Do
**not** add `Co-authored-by:`, session-ID trailers, or any other tool-attribution line to the commit
message — this repo's history shows one identity. If your tool normally appends its own attribution
trailers by default, override or strip that behavior for commits in this repo.

## Agent git-action authorization

Agents (any tool — Claude Code, OpenCode, etc.) are **always authorized to `git push`, `git pull`/`git
fetch`, and `git commit`** in this repo without asking first — these are reversible, low-blast-radius
actions, and asking permission for each one just slows down routine work.

**Merging is different and stays gated: an agent must never run `gh pr merge` (or any equivalent merge
action) on its own initiative, on any PR — foundation-path or not.** Always open/update the PR and leave
it for the human operator to review and merge, unless the human explicitly asks the agent to merge that
specific PR in that conversation (a standing "you can always merge" instruction doesn't count — this is
a per-request, in-the-moment ask each time). This supersedes the older "resolve findings, then merge"
language for non-foundation PRs below — that merge step is now always the human's, not the agent's; it
was already true for foundation-path PRs (see Foundation freeze, below), this just makes it universal.

## PR flow

1. **M1a PR** (`T-<id>-tests` → `main`): opens once the red test suite is committed. Reviewed via the
   review-agent gate (below). **Does not merge until every owner's M1a PR for every module is also
   ready** — WORK-BREAKDOWN.md's M1a exit gate is global ("zero implementation code exists for any
   module yet"), not per-ticket. Coordinate before merging the last one.
2. **M1b PR** (`T-<id>-<slug>` → `main`): opens only after the M1a milestone gate above has fully
   closed for every module. Reviewed via the review-agent gate. Merges once CI is green and the review
   has no unresolved blocking findings.

## CI gating (mechanizes CONVENTIONS §12 / WORK-BREAKDOWN T-F6)

Every push runs `.github/workflows/ci.yml`. Non-adapter suites (M1, M3, M5, M7, M8, M9) run with network
sockets blocked and `CUDA_VISIBLE_DEVICES=""` — a test that bypasses its fake and reaches for a live
Qdrant/HF download/GPU fails loudly instead of silently passing. Real-adapter contract tests and the
retrieval eval run nightly/on-demand — they block release, not every commit. Branch protection on `main`
requires this check to pass before merge, no exceptions.

## Review-agent gate (non-foundation PRs)

Before marking a PR ready for merge, run a review pass against the diff covering: module depth and
information hiding (is the interface small relative to what it hides), coupling (did this leak a vendor
or a `contracts/` shape it shouldn't own), naming/consistency, and whether the diff matches its ticket's
acceptance criteria (WORK-BREAKDOWN.md) — the same checklist this project's design skills use. *In Claude
Code* this is the `design-review` skill or a code-reviewer agent; *under another tool* (e.g. OpenCode),
use whatever equivalent review subagent/prompt it provides, covering the same checklist — the mechanism
differs by tool, the checklist doesn't. Resolve any blocking findings — the PR is then ready to merge,
but per "Agent git-action authorization" above, the agent leaves the actual merge to the human unless
explicitly asked to do it. The human operator's diff review at merge time is therefore the real gate for
regular module tickets too, not just a periodic spot-check (that framing predates the universal
human-merge rule above; foundation-path PRs, see below, already worked this way).

## Foundation freeze — the concrete GitHub mechanism for T-F7

> **Current status (2026-07-08): repo is public, branch protection on `main` IS active** (required PR +
> 1 CODEOWNER approval, no force-push/deletion). Two things to know:
>
> - **`gh` cannot self-approve.** GitHub blocks a PR author from approving their own PR
>   (`Review Can not approve your own pull request`), which matters a lot for a solo-operator repo where
>   the CODEOWNER and every author are the same GitHub identity. The practical merge path for this repo
>   is **`gh pr merge --rebase --admin`** — the repo admin (the human) reviews the diff themselves, then
>   uses admin privilege to merge past the unsatisfiable self-approval requirement. This *is* the human
>   sign-off (a deliberate admin action, not a rubber stamp) — it just doesn't produce a formal GitHub
>   "Approved" review artifact. Don't try to get a normal approval on a solo PR; use `--admin` once
>   you've actually looked at the diff. **Use `--rebase`, not `--squash`**: squash-merge lets GitHub
>   generate a brand-new commit authored as the merging account's GitHub display name, overriding whatever
>   the branch's real commits were authored as — rebase-merge replays the branch's existing commits onto
>   `main` unchanged, so the `MKamel1 <...noreply...>` authorship set above actually survives the merge.
> - **`.github/workflows/ci.yml` needed a separate fix.** The `gh` auth token initially lacked the
>   `workflow` OAuth scope, which blocks pushing *any* commit whose branch history includes a change to
>   a `.github/workflows/*.yml` file — even unrelated later commits on top of it. If you hit "refusing to
>   allow an OAuth App to create or update workflow ... without workflow scope" on a push, either (a) run
>   `gh auth refresh -h github.com -s workflow` (interactive) once, or (b) if that's not available,
>   cherry-pick your commit onto a branch based on a point in history *before* the workflow-file commit,
>   push that instead, and reconcile later once the scope is granted.
> - **Invariant: only the human merges foundation-path PRs** (one instance of the general
>   "agent never merges" rule in "Agent git-action authorization" above, stated here because it was the
>   original, mechanically-enforced case). Agents may *open* PRs that touch
>   protected paths, but must never run `gh pr merge` on them. Only the human operator merges — and
>   only after reviewing the diff and confirming the `foundation-change` label is present. Because
>   `--admin` bypasses both the required CODEOWNER review and the required `enforcement` status check
>   (where check (e)'s label gate lives), that deliberate diff review immediately before typing
>   `--admin` **is** the actual sign-off mechanism for this repo — not a formality, since nothing else
>   blocks the merge at that point.

CONVENTIONS.md §0.2 / WORK-BREAKDOWN.md T-F7 require the human operator's explicit sign-off on any change
to `contracts/`, `Config`, the SQLite schema, or the fakes. This is mechanized, not left to memory:

- `.github/CODEOWNERS` names the human (`@MKamel1`) as required reviewer for `contracts/**`,
  `rag/config.py`, `config.yaml`, `migrations/**`, `rag/fakes/**`, `fixtures/**`, `ci/**`, and
  `.github/**` — the last two so the enforcement mechanism and CI config can't be weakened by an
  ordinary unprotected PR.
- The `foundation-change` label (registered at repo bootstrap) must be applied to any PR touching those
  paths.
- Branch protection on `main` requires: CI green **+** the `foundation-change` label present **+**
  CODEOWNER (human) approval, for any PR touching those paths. Label + required review together
  mechanize the sign-off — a PR can't merge with only a green CI check if it touches a foundation path.

**Sequence:** Owner F builds T-F1–T-F5, gets them reviewed and merged (as normal PRs — protection isn't
active yet for the very first bootstrap commit, but is active for every PR after that, including Owner
F's own). Once merged, tag the commit `foundation-v0-frozen` on `main`. Only then do Owners A–E open
their M1a branches — each additionally waits on its own Phase-0 prerequisite where its owner brief names
one (Spike 1 for Parser, Spike 2 for Embedder/VectorIndex/Retriever/McpServer).

## One-time bootstrap (already done for the initial scaffold; documented here for reference)

The very first commit (this scaffold: docs + `AGENTS.md`/`CLAUDE.md` + `owners/` + `environment.yml` +
`config.yaml` + CI skeleton) went directly to `main` before branch protection was enabled, since
protection would have blocked the initial push. Protection, `CODEOWNERS`, and the `foundation-change`
label were enabled immediately after. Every commit from here on follows the branch/PR flow above, no
exceptions — including Owner F's own T-F1–T-F7 work.
