# Test staleness audit — 2026-07-31

Read-only audit of the whole live suite, run as four parallel shards. **No test was modified.**
The fix list at the end is a proposal awaiting operator approval (backlog **D-4**).

## Headline

The premise that prompted this audit — "the tests built might be old at this point" — is **not
borne out**. Across 78 test files and ~1,440 test functions, the audit found **2 low-severity
stale tests and 0 dead, superseded, or stale-constant tests**.

Every constant the 2026-07 experiment programme moved was already reflected in its tests:

| moved thing | expected staleness | actual |
|---|---|---|
| `_MAX_HITS_PER_PAPER` 3 → scoped 50 | tests pinned to flat 3 | **none** — tests read the live constants off the module, so they cannot drift silently |
| Sparse IDF off → on | tests asserting IDF-off scoring | **none** — every test asserts the IDF-on contract |
| Book eval set 40 → 115 questions | tests pinned to 40 | **none** — already `TOTAL_ITEMS = 115`, `QUESTIONS_PER_BOOK = 23` |
| `SearchFilters` gained `paper_id` | tests asserting the old field list | **none** — real coverage of default and explicit construction |
| Dashboard `/api/status` gained 3 blocks | tests asserting the old key set | **none** — the full-key-set contract test already includes all three |

**What the suite actually has is not staleness but thinness in specific places.** The real output
of this audit is 6 coverage gaps — places where no test exists — and the most valuable one is a
silent-failure path in the dashboard's telemetry.

## Coverage

| shard | scope | files | test functions | stale findings | coverage gaps |
|---|---|---|---|---|---|
| A | `rag/` | 25 | 515 | 1 | 0 |
| B | `app/` (excl. dashboard) | 28 | 540 | 1 | 1 |
| C | `app/dashboard/` | 4 | 226 | 0 | 3 |
| D | `contracts/`, `fixtures/`, `ci/`, `migrations/` | 21 | 159 | 0 | 2 |
| **total** | | **78** | **~1,440** | **2** | **6** |

Each shard ran its scope's suite: all green. `.worktrees/` and `.claude/worktrees/` were excluded
as stale copies of other branches.

Shard C was predicted to be highest-yield (four PRs in two days) and came back **cleanest** — its
tests were re-thought alongside each change, not merely extended.

---

## Proposed fix list, ranked by value

Ordered by what each buys, not by effort. **Items 1–3 are worth doing; 4–8 are optional.**

### 1. Funnel → telemetry end-to-end test *(gap, shard C)*

**The one silent-failure path the audit found.** `server.py` reads
`corpus["funnel"].get("done")` — a `.get`, not an index — and passes it to `read_telemetry` as
`total_done`. Both layers are tested in isolation, but the only test joining them
(`test_server.py:335`) uses `_FakeStatus.read_corpus`, which hardcodes `"done": 5` and never runs
the real `_funnel_from_stage_counts`.

If that key were ever renamed, nested, or dropped, `.get` would return `None`,
`papers_per_hour`/`eta_s` would silently zero out on the live dashboard, and **no test would
fail**. This session's `by_doc_type` change was protected only by hand-diffing — that protection
was manual, not systematic.

**Proposal:** one test driving a real scratch `papers.db` through
`status.read_corpus → server._status_dict` and asserting the `total_done` actually handed to
`read_telemetry`.
**Risk:** none — purely additive.

### 2. `ingest_local --drop-dir` CLI path test *(gap, shard B)*

Untested, and it is the path production uses: `controller._spawn_drop_in` passes `--drop-dir`
explicitly precisely because `Config.drop_in_dir` resolves relative and the dashboard and its
spawned child have different working directories. A regression here means a drop-in run scans the
wrong directory, stages nothing, and **exits 0** — success that isn't.

**Proposal:** one test asserting `--drop-dir` overrides `cfg.drop_in_dir`.
**Risk:** none — purely additive.

### 3. `promote_pending_drop_in` concurrency test *(gap, shard C)*

Its docstring names the exact race it defends against — two concurrent `/api/status` polls both
seeing `terminal + pending` and both spawning — but both existing tests call it once,
single-threaded. The suite already has the right pattern in
`test_concurrent_starts_are_serialized_exactly_one_run` (`test_controller.py:1495`); it just was
not applied here.

**Proposal:** copy that thread-race pattern onto `promote_pending_drop_in`.
**Risk:** none — additive, and reuses an established in-repo idiom.

### 4. `_pr_labels` payload-shape tests *(gap, shard D)*

All three existing tests supply a complete payload, so neither the raise-on-missing-`labels` path
nor the graceful-fallback-on-missing-`number` path is exercised. Both are real behaviors this
session hit by accident.

### 5. Check (a)/(d) comment-matching tests *(gap, shard D)*

Both checks regex raw added lines, so a vendor name or `os.getenv` appearing **only in a comment**
trips them. This is a known, previously-hit failure mode — `env_leak_bad.py`'s own docstring says
its author had to avoid spelling out the flagged calls to keep from tripping the check — yet no
test covers a comment-only occurrence in either direction.

### 6. `test_start_tei_containers_poll_timeout_s_overrides_the_module_default` *(stale, shard B)*

`app/test_tei_lifecycle.py:384`. Its docstring says `poll_timeout_s` "must actually change the
deadline, not just be ignored," but the body asserts nothing about elapsed time or poll count. If
the parameter were silently dropped, the test would still pass — just take ~30 real seconds. No
`pytest-timeout` is configured, so nothing else would catch it either.

**Proposal:** add a wall-clock or poll-count assertion.

### 7. `_crashed_before_target` drop-in-mode test *(gap, shard C, minor)*

The download-mode path has a regression test proving a clean finish is never misreported as
`failed`; the drop-in path relies on the same `target=0` guarantee with no equivalent test. Safe
by construction today, but unguarded if a drop-in run ever gets a non-zero target.

### 8. Vacuous assertion in `rag/test_mcp_server.py:351` *(stale, shard A, cosmetic)*

`assert server is not None` after a constructor call, which can never be `None`. The test's real
value is that construction with only two kwargs did not raise. **Delete the assert line only, not
the test** — the test still guards against `McpServer.__init__` growing a required argument.

### Maintenance note (not a fix)

8 files under `rag/` carry stale `M1A-DORMANT (re-enable in M1b)` header comments. Every module
they gate on now exists and resolves, so the suites are fully active. The comments are wrong prose,
not wrong behavior — worth a docs pass, not a code change.

---

## Correction to the audit brief

The shard-D brief asserted that `ci/checks/changed_files.py::compute_diff_base` requires both
`number` and `labels` in the event payload. **That attribution was wrong.** `compute_diff_base`
reads only `pull_request.base.sha` / `head.sha` (or `before` / `repository.default_branch`). The
function that reads those fields is `ci/run_enforcement.py::_pr_labels`, and the requirement is
asymmetric:

- `event["pull_request"]["labels"]` — no `.get`, so a missing key **raises `KeyError`**
- `event["pull_request"].get("number") or event.get("number")` — **optional by design**, falls
  through to cached-payload mode

The working local invocation is unchanged (supplying both is still correct), but
`docs/BACKLOG.md`'s standing-constraints note has been corrected to match.

## Method

Each shard ran a mechanical pass (AST scan for assertion-free tests, greps for vacuous assertions
and moved constants), then **read every candidate in context** before recording it. Shards were
instructed that a no-assert smoke test asserting by not raising is valid and must not be flagged,
that a test using a fake is `over-mocked` only if the real code could break without it failing,
and that an empty findings file is a legitimate result. Two shards returned empty findings tables.
