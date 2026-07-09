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

## Commit messages

Subject: `T-<id>: <imperative what>` (e.g. `T-C1: add Chunker unit tests against frozen interface`).
Body: the *why*, not a restatement of the diff. Trailers: this harness's standard
`Co-Authored-By`/`Claude-Session` trailers, same as any other commit made through Claude Code.

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

Before marking a PR ready for merge, dispatch a review pass — the `design-review` skill or a
code-reviewer agent — against the diff. Resolve any blocking findings it reports, then merge. The human
operator spot-checks a sample of merged PRs periodically; this is **not** a per-PR requirement for
regular module tickets (that's foundation-path PRs, see below).

## Foundation freeze — the concrete GitHub mechanism for T-F7

> **Current status (2026-07-08): repo is public, branch protection on `main` IS active** (required PR +
> 1 CODEOWNER approval, no force-push/deletion). Two things to know:
>
> - **`gh` cannot self-approve.** GitHub blocks a PR author from approving their own PR
>   (`Review Can not approve your own pull request`), which matters a lot for a solo-operator repo where
>   the CODEOWNER and every author are the same GitHub identity. The practical merge path for this repo
>   is **`gh pr merge --admin`** — the repo admin (the human) reviews the diff themselves, then uses
>   admin privilege to merge past the unsatisfiable self-approval requirement. This *is* the human
>   sign-off (a deliberate admin action, not a rubber stamp) — it just doesn't produce a formal GitHub
>   "Approved" review artifact. Don't try to get a normal approval on a solo PR; use `--admin` once
>   you've actually looked at the diff.
> - **`.github/workflows/ci.yml` needed a separate fix.** The `gh` auth token initially lacked the
>   `workflow` OAuth scope, which blocks pushing *any* commit whose branch history includes a change to
>   a `.github/workflows/*.yml` file — even unrelated later commits on top of it. If you hit "refusing to
>   allow an OAuth App to create or update workflow ... without workflow scope" on a push, either (a) run
>   `gh auth refresh -h github.com -s workflow` (interactive) once, or (b) if that's not available,
>   cherry-pick your commit onto a branch based on a point in history *before* the workflow-file commit,
>   push that instead, and reconcile later once the scope is granted.

CONVENTIONS.md §0.2 / WORK-BREAKDOWN.md T-F7 require the human operator's explicit sign-off on any change
to `contracts/`, `Config`, the SQLite schema, or the fakes. This is mechanized, not left to memory:

- `.github/CODEOWNERS` names the human (`@MKamel1`) as required reviewer for `contracts/**`,
  `rag/config.py`, `config.yaml`, `migrations/**`, `rag/fakes/**`.
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

The very first commit (this scaffold: docs + `CLAUDE.md` + `owners/` + `environment.yml` + `config.yaml`
+ CI skeleton) went directly to `main` before branch protection was enabled, since protection would have
blocked the initial push. Protection, `CODEOWNERS`, and the `foundation-change` label were enabled
immediately after. Every commit from here on follows the branch/PR flow above, no exceptions — including
Owner F's own T-F1–T-F7 work.
