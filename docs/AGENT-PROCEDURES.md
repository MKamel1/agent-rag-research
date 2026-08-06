# Agent Procedures — onboarding, per-PR doc obligations, drift-correction

Standing procedure so the doc/reality drift the 2026-08-05/06 consolidation fixed (statuses claiming
OPEN for shipped work, modules with zero doc footprint, decisions marked unactioned weeks after they
shipped) doesn't recur. Three sections: (A) how to onboard into this repo, (B) what documentation
obligation a PR carries, (C) how to run a periodic drift-correction pass. Checklist, not an essay —
match `GIT-WORKFLOW.md`/`CONVENTIONS.md`'s register: concrete triggers, not prose reminders.

---

## A. Onboarding a new agent/session

1. **Read, in this order:** `AGENTS.md` → `docs/PROJECT-STATUS.md` → `CONVENTIONS.md` §0 →
   `GIT-WORKFLOW.md` (before your first commit) → `docs/BACKLOG.md` → whatever doc the specific task
   names. `AGENTS.md` is deliberately an index, not a copy — it tells you which doc to open, it
   doesn't restate the content.

2. **Don't trust a status label without checking it.** A "(not started)" in `WORK-BREAKDOWN.md` or
   "OPEN" in `docs/BACKLOG.md` is a claim, not a fact — the 2026-08-05/06 consolidation found nine
   `T-DOC<n>` tickets in `WORK-BREAKDOWN.md` falsely marked "(not started)" (T-DOC64/65/66/67/87/90/
   91/92/94 — see `WORK-BREAKDOWN.md`'s own now-standing warning banner and
   `docs/PROJECT-STATUS.md` §3/§4), each caught with one grep. Before acting on a stated ticket
   status:

   ```bash
   git log --oneline --all --grep="<ticket-id>"
   git branch --contains <sha> -r
   ```

   The first finds every commit mentioning the ticket ID across all branches (local and remote); the
   second confirms whether a given commit actually reached `origin/main`, vs. sitting only on an
   unmerged branch or a rebase-duplicate SHA. Verified working 2026-08-06 against D-11 (`docs/BACKLOG.md`
   lists it OPEN, but the commit history says otherwise): `git log --oneline --all --grep="D-11"`
   returns `4e07eb4 D-11: archive run logs on the failed transition, not only on done` (among others);
   `git branch --contains 4e07eb4 -r` returns `origin/main` — the fix is shipped, `BACKLOG.md`'s row is
   stale.

3. **Re-derive live numbers yourself.** Corpus counts, current PR ceiling, branch ahead/behind counts
   — anything you're about to state as fact — against source/git/a live query. Never copy a number
   from an existing doc without re-checking it; `docs/PROJECT-STATUS.md` §1's own numbers carry the
   query that produced them for exactly this reason — do the same for any number you write.

4. **Environment quick-facts** (verified against `rag/config.py` and `app/ingest.py` 2026-08-06 —
   re-verify if this doc is more than a few weeks old):
   - Use the `agent-rag-research` conda env (`environment.yml`).
   - Ingest-side tools (`app.ingest`, `app.build_corpus`, `app.parse_phase`, `app.prefetch_pdfs`,
     `app.ingest_local`, `app.rechunk`, `app.reindex_idf`, `app.delete_docs`, `app.snapshot`,
     `app.obsidian_export`, `app.corpus_integrity`) have **no `--data-dir` flag** — confirmed by
     grepping `app/ingest.py`'s `add_argument` calls, none named `--data-dir`. Your shell's cwd IS
     the data dir (`rag/config.py`'s `find_config_path`: explicit path → `RAG_CONFIG` env var →
     `config.yaml` in cwd → walk up parent directories). Only `app.init_config`, `app.serve`,
     `app.dashboard.server`, `app.dashboard.verify_numbers` take `--data-dir`
     (`docs/PROJECT-STATUS.md` §2 trap (b)).
   - `config.yaml` path fields resolve against **the config file's own directory**, not cwd —
     confirmed at `rag/config.py::_resolve_paths`, called with `config_path.parent` as `base_dir`.
     Loading the same `config.yaml` from two different cwds yields identical absolute paths.
   - **`app.build_corpus`'s batches and `app.prefetch_pdfs`'s downloads are two independent,
     mismatched processes — know this before touching either.** `app.build_corpus` only ever batches
     IDs already sitting in `pdf_cache/` (`cached_not_done`, `app/build_corpus.py:203`). It spawns
     `app.prefetch_pdfs` to keep that cache filled, but prefetch harvests from `cfg.focus_area_queries`
     (`app/prefetch_pdfs.py:297`) and **never reads `cfg.ingest_paper_ids`** — confirmed by grep,
     zero hits for `ingest_paper_ids` in `app/prefetch_pdfs.py`. So an ID-scoped build (a
     `--paper-ids-file`/`ingest_paper_ids` corpus, not a query-driven one) gets nothing useful from
     the default prefetcher no matter how long you wait — this is the actual root cause the v1 Waymo
     attempt worked around by setting `prefetch_target: 1` and hand-rolling a batch script, per
     `docs/WAYMO-CORPUS-STATUS.md`. For an ID-scoped corpus, populate `pdf_cache/` yourself (e.g. via
     `app.ingest_local`/`drop_in/`, or a direct-download step) rather than relying on
     `app.prefetch_pdfs` to do it.

---

## B. Per-PR / per-trigger documentation obligation

| Trigger | Doc to update | What to write |
|---|---|---|
| A `docs/BACKLOG.md` (D/T/B/O) ticket ships | `docs/BACKLOG.md` | Flip the row to DONE + the landing commit SHA. |
| Same ticket | `docs/PROJECT-STATUS.md` §3 (Shipped-work ledger) | One entry: ticket → what it did → SHA. |
| A `T-DOC<n>` ad-hoc fix ships | `docs/PROJECT-STATUS.md` §3 | One entry, in the **same PR**, not deferred to a retroactive batch. `GIT-WORKFLOW.md`'s existing allowance to batch `T-DOC<n>` IDs into `WORK-BREAKDOWN.md`'s registry *retroactively* still stands — that's about the ticket-ID registry. This row is about the `PROJECT-STATUS.md` ledger entry specifically, which is **not** deferrable: deferring exactly that is what produced the 2026-08-05/06 backlog this doc exists to prevent recurring. |
| A new top-level entry point/module ships (new `app/*.py` with argparse, new `rag/*.py` seam) | `docs/PROJECT-STATUS.md` §2 (entry-point table) + `ARCHITECTURE.md` if it's a new module/seam | The flag/signature and a one-line purpose, verified against the actual `argparse` block in the diff, not guessed. |
| A design decision is made or reversed (an experiment concludes, an option is chosen) | A new `docs/DECISION-*.md` or `docs/eval-reports/*.md` (existing naming pattern — e.g. `docs/DECISION-book-rag-what-to-ship.md`, `docs/eval-reports/2026-07-29-exp1-outline-split-ab.md`) + `docs/PROJECT-STATUS.md` §5 (Tried and failed / deliberately not shipped) or §6 (Open and known-broken) | The verdict and why, with the measurement/report it rests on. |
| A doc becomes superseded by this PR's work | The superseded doc's top line | The HISTORICAL banner, added in the **same PR** that causes the supersession, not later: `> **HISTORICAL** — <why>. Current state: [PROJECT-STATUS.md](PROJECT-STATUS.md).` (exact format taken from `docs/DESIGN-corpus-dashboard.md`'s and `docs/ROADMAP-AND-PRIORITIES-PLAIN-ENGLISH.md`'s live banners.) |
| A new `docs/*.md` ships | `docs/PROJECT-STATUS.md` §7 (Doc map) | One row: path, class (AUTHORITATIVE/REFERENCE/HISTORICAL), a one-line note on what it's for and what (if anything) it supersedes or is superseded by. Don't skip this because the new doc "explains itself" — §7 is the only place that tells a cold reader the doc *exists* at all. |
| Every PR, regardless | — | Self-check before opening: does this diff make any existing doc claim false? If yes, fix that doc in this PR. |

`docs/PROJECT-STATUS.md`'s section numbers above (§2 entry-point table, §3 shipped-work ledger, §5
tried-and-failed, §6 open) were confirmed against the file as of 2026-08-06 — re-check the actual
headings before citing a section number if this doc has since been renumbered; `docs/PROJECT-STATUS.md`
itself, not this doc, is authoritative for its own structure.

### Before you report a PR as done

Two steps, both mandatory, neither optional because "the tests looked fine locally":

1. **Run the actual CI enforcement check yourself before pushing — not a narrower stand-in for it.**
   `pytest ci/checks/test_checks.py` alone is not the same check CI runs: it only exercises the
   functions in isolation, not the lexical scan (`ruff`'s `BLE001` and friends, CONVENTIONS.md §12
   checks (a)-(d)/(f)-(h)) that `ci/run_enforcement.py` runs over every changed file in the diff —
   including files that are never imported or called by anything else, since checks (a)-(d) are a
   grep/lint pass over the diff's *text*, not a call graph. Run it locally by simulating a push
   event (no `GITHUB_EVENT_NAME` in a local shell otherwise):
   ```bash
   echo '{}' > /tmp/fake_push_event.json
   GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH=/tmp/fake_push_event.json python -m ci.run_enforcement
   ```
   This diffs your branch against `origin/<default-branch>` (`ci/checks/changed_files.py`'s
   `compute_diff_base` fallback) the same way the real `push`/`pull_request` CI trigger would.

2. **After `gh pr create` or a push to an open PR, watch CI to actual conclusion before declaring the
   task done — do not just push and report success.** `gh pr checks <number> --watch` (interval a few
   seconds; it blocks until every check finishes, pass or fail). A PR that merely *exists* is not
   verified — only a PR whose checks you've watched conclude is.

   **Check the rollup against the commit you actually pushed, not a snapshot from a few minutes ago.**
   `git commit` and `git push` are two different actions — a commit made after you last watched CI is
   not covered by that earlier "all green" result, even if it feels like the same PR. Confirm the SHA
   before trusting the rollup:
   ```bash
   gh pr view <number> --json headRefOid,mergeable,mergeStateStatus,statusCheckRollup \
     --jq '.headRefOid, .mergeable, .mergeStateStatus, (.statusCheckRollup[] | {name, status, conclusion})'
   ```
   Compare `.headRefOid` against `git rev-parse HEAD` (and against `git log origin/<branch>..HEAD` —
   non-empty means something local is still unpushed) before trusting `mergeStateStatus`. Only
   `CLEAN` means done; `BLOCKED` with everything showing `SUCCESS` in the rollup usually means the
   rollup is still for an older SHA, not that something is silently wrong.

   **A `CANCELLED` job with zero steps run, or a "Service Unavailable"/"Failed to resolve action
   download info" error during "Set up job," is GitHub Actions infrastructure flakiness, not a code
   problem** — check `gh run view <job-id> --json jobs` for zero completed steps before assuming your
   diff caused it. `gh run rerun <run-id> --failed` re-runs only the failed/cancelled jobs (not the
   whole workflow) and is safe to repeat. If it keeps failing the same way across several retries
   within a short window, stop retrying and say so plainly rather than looping — it may be a live
   platform incident, not something a retry will fix; local verification (step 1 above, plus the full
   test suite) stands on its own in the meantime, and the live CI check can be revisited once GitHub's
   infra is stable again.

**Real incident, 2026-08-06, PR #236:** step 1 above didn't exist yet as a rule, so a subagent building
`ci/checks/doc_touch_reminder.py` ran only the targeted `pytest ci/checks/test_checks.py` (61 passed)
and a YAML parse check, reported success, and the PR was opened without anyone watching its CI. The
`enforcement` job failed twice in a row on check (c): the script had a `# ponytail:`-commented
`except Exception` that its own author believed was a documented, deliberate exemption — but
CONVENTIONS.md §12 check (c) has no exemption mechanism for any comment; it blocks the pattern
unconditionally, per §0.1's own point that a checkable rule must be a CI job, not something a
reviewer (human or agent) is trusted to read and honor. Running step 1 above against the real diff
would have caught it before the first push, at zero cost. This is why the rule above exists.

---

## C. Periodic drift-correction pass

### When to trigger one

- **Before a new initiative that will create a second corpus/major surface.** The Waymo AV-safety
  corpus expansion (`docs/WAYMO-CORPUS-STATUS.md`, `docs/superpowers/plans/2026-08-05-waymo-corpus-
  expansion.md`) is the example of what should have triggered a drift-correction pass first, and
  didn't — it started against docs that already had accumulated drift.
- **An agent mid-task notices two docs making contradictory claims.** This is a stop-and-flag trigger
  (`CONVENTIONS.md` §0.2's existing "stop and flag" norm for a frozen-contract mismatch, applied here
  to docs) — not something to silently work around by picking whichever doc seems more plausible.
- **A size threshold: roughly 15-20 `T-DOC`-class fixes accumulated, or 2+ weeks since
  `docs/PROJECT-STATUS.md` was last updated** (check its own "Written <date>" line at the top) —
  whichever comes first.

### How to run one

Distilled from what actually worked in this branch's real commit sequence
(`git log --oneline --reverse main..HEAD` on `docs-consolidation-2026-08-05`, verified 2026-08-06):

1. **Verify before writing.** Every number re-derived from source/git/a live DB query, never copied
   from an existing doc.
2. **Flat Sonnet subagents, one per workstream, sequential commits on one branch** — not parallel.
   Concurrent `git commit`s in one working tree race each other. If true parallelism across
   workstreams is wanted, use `isolation: worktree` (separate working trees, still one integration
   branch at the end) rather than letting multiple agents commit into the same tree at once.
3. **Cross-check subagents against each other's claims** rather than trusting one report. Real
   example from this branch: two subagents disagreed about whether Decisions 2/3
   (`docs/DECISIONS-PENDING-operator.md`) had shipped to `origin/main`. Resolved by running
   `git merge-base --is-ancestor <sha> origin/main` directly — they had shipped, just as
   rebase-duplicate commits under different SHAs (original local commits `ecf866b`/`2ebd491`; the
   landed SHAs were `73336f3`/`2dad68a` under `T-DOC-DECISION2`/`T-DOC-DECISION3`), which is exactly
   the kind of thing a single subagent's unverified claim would get wrong.
4. **Git hygiene, in this order — preserve before ignore, always. Never delete data, never
   `git stash`.**
   1. Sync main (`git fetch origin main`).
   2. Gitignore large/stray data directories that shouldn't be tracked.
   3. Before anything gitignored disappears from view, preserve small reusable artifacts out of it
      into a tracked location (this branch: `fixtures/waymo/` pulled out of the newly-gitignored
      `waymo/` dir).
   4. Commit anything that existed on disk but was never committed to git at all.
   5. Correct stale statuses (the ticket-verification loop in §A.2 above, applied at scale).
   6. Add HISTORICAL banners to superseded docs.
5. **Verify at the end:** `python -m app.doctor`, the full test suite, `git status` clean.
6. **Worked examples of expected output format and evidence density** — every claim carries a SHA,
   a `file:line`, or a report path, never a bare assertion: `docs/PROJECT-STATUS.md` and
   `docs/WAYMO-CORPUS-STATUS.md`.

A drift-correction pass produces status/ledger docs (§6 above). **Writing a forward-looking implementation
plan is a different shape** — this repo already has a convention for that, don't improvise one:
`docs/superpowers/plans/<date>-<slug>.md` (checkbox tasks, explicit Global Constraints, a Self-Review
section before handing it off) is the format every plan in this repo follows. Look at
`docs/superpowers/plans/2026-08-05-waymo-corpus-expansion.md` or the newer
`docs/superpowers/plans/2026-08-06-waymo-av-safety-corpus-expansion-v2.md` for the actual shape before
writing a new one — don't reverse-engineer it from the status docs above.

Every claim in this doc was checked against the actual repo state as of 2026-08-06 before being
written — a doc about not trusting unverified doc claims has to model that discipline itself, not just
prescribe it.
