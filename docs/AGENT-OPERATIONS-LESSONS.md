# Agent operations — lessons log

**A living file. Append; don't rewrite.** Every entry is something that actually cost time or
produced a wrong result while running Claude-as-leader over opencode-as-implementer on this repo.
Each carries the concrete case, because a rule without its incident gets argued away by the next
session.

Started 2026-08-22. Newest section last within each part.

---

## 1. Verification claims

### 1.1 Running a checker's unit tests is not running the checker

**Cost: two merges landed on a red required CI gate; unnoticed for hours.**

`pytest ci/checks/` passes — it runs `ci/checks/test_checks.py`, the checks' own unit tests. The
`enforcement` job runs those checks **against the diff**. Those are different things, and "CI
checks pass" was reported from the first while the second was failing.

Concretely: run `32591144469` (the RI-18 merge) failed with 6 `[a]` violations —
`httpx.MockTransport` fixtures in `app/test_assembly.py`, a file never added to that rule's
allow-list. Run `32579939693` failed with 2 `[f]` violations. Neither was a code defect; both were
the checks being wrong. But nobody looked.

**Rule:** after any push, read the actual run result (`gh run list --branch main --limit 3`).
Before any push, run `python -m ci.run_enforcement --local main` — added by RI-23 precisely because
its absence caused this.

### 1.2 A local suite passing says nothing about the gate

Same root cause, different shape: the full pytest suite was green on every branch merged. It stayed
green while the gate was red. Two independent signals; check both.

### 1.3 `pytest -q` in this repo hides the summary line

`addopts` already contains `-q`, so passing `-q` again gives `-qq` and **suppresses the
`N passed` line entirely**. Several agents reported counts by parsing a summary that was not
printed. Count result characters instead:

```bash
dots=$(tr -cd '.' < out.txt | wc -c); skips=$(tr -cd 's' < out.txt | wc -c)
```

Agents that did this unprompted were right; agents that trusted a printed summary invented numbers.

---

## 2. Reviews

### 2.1 Documentation-anchored review finds documentation-shaped bugs

**Cost: a whole review campaign whose headline finding was wrong about its own consequence.**

The first campaign's FD-1 read `rag/parser.py`'s docstring, saw figure images default to an OS temp
directory, and filed "figures are being lost, redirect the output path." Reading the *code* showed
`DocumentStore.put()` had no figures table to write to and `get()` hard-coded `figures=[]`.
Redirecting the path would have preserved bytes nothing could reference. The real defect was
three times larger, in a different file, and the docstring gave no hint of it.

**Rule for review briefs:** state that a finding whose evidence is a docstring, comment, or `.md`
file is not a finding. Prose may orient; it may never prove behaviour. Put the FD-1 case in the
brief verbatim — an abstract instruction did not work, a worked example did.

### 2.2 Require a falsification attempt, and honour it

The second campaign required every finding to name the guard the reviewer went looking for that
would make the finding wrong. Results: one reviewer declined to file a finding it could not
construct a trigger for and explained why; another labelled its reasoning "code-order, not a live
repro"; a third reproduced its race in a real interpreter with 4 threads.

A confidently-wrong finding costs more than a missed one — someone must disprove it.

### 2.3 The highest-value finding came from outside the source tree

The red CI gate was found by a reviewer that ran `gh run list`. No amount of reading source would
have surfaced it. **Give at least one reviewer explicit licence to inspect CI history, issues, and
run logs — not just files.**

### 2.4 Reviewers scoped to disjoint areas do not duplicate; reviewers given the same area do

Five reviewers, one code area each, produced ~11 findings with almost no overlap. Where two areas
touched (dashboard vs. ops tooling) the overlap was corroboration, not noise.

---

## 3. Dispatching opencode

### 3.1 Multi-ticket briefs truncate and lose everything

**Cost: three wave-4 workstreams burned their entire budget reading and committed nothing.**

A brief with 3 tickets reliably ran out of room during context-gathering. The fix that worked:

> Do ONE ticket at a time and COMMIT it as soon as it is green, before starting the next. A
> committed ticket is worth more than three in progress.

RI-22 later proved it in reverse: it truncated *exactly* at the GREEN step with its RED tests
written and verified but uncommitted. Resuming the same session recovered it; a fresh dispatch
would have redone the work.

### 3.2 Resume the session, never restart it

`oc-task -s <session_id> "continue…"` keeps the agent's context. A fresh dispatch starts cold and
re-reads everything. Always capture the session id from the result.

### 3.3 An empty result is a quota signal, not a model failure

A result with `exit 0`, `tools: []`, and empty output is almost always the provider refusing.
Diagnose with the raw command, not the wrapper:

```bash
opencode run --format json --auto "ping" 2>&1 | head -c 500
```

That surfaced `Rate limit exceeded: free-models-per-day-stealth`, `X-RateLimit-Remaining: 0`,
1000/day — exhausted by ~600 tool calls across parallel max-effort agents. It looked identical to
"the model gave up mid-task," which sent the first diagnosis in the wrong direction.

### 3.4 Free-tier limits are per ACCOUNT, not per key

A new API key on the same account inherits the same exhausted bucket — the 429 body names the
`user_id`. Only a different account has a separate quota.

### 3.5 Stealth models have their own quota bucket

`free-models-per-day-stealth` exhausted while ordinary free models still worked. When ox-alpha is
throttled, another free model may still run — check before waiting.

### 3.6 Pace the budget by task value

1000 requests/day sounds like plenty and is not: three review campaigns plus six implementation
workstreams at max effort consumed it in one session. Spend ox-alpha on reasoning-heavy work
(review, adjudication, design argument); let a cheaper model take mechanical passes.

---

## 4. Parallelism

### 4.1 Partition tickets by file ownership, not by topic

Two agents editing one file is the collision that costs a merge conflict and a re-run. Group
tickets so concurrently-running branches touch **disjoint files**, and hold a ticket rather than
run it into a conflict.

Worked example: RI-21 (atomic-write helper) touches `server.py` and `controller.py`. RI-19 owned
both. RI-21 was held, then rebased onto main and dispatched the moment RI-19 merged.

### 4.2 One git worktree per agent

`git worktree add -b <branch> .worktrees/<branch> main`. Agents sharing a checkout race on the
working tree. Clean up with `git worktree remove --force` after merge.

### 4.3 Rebase a held branch before dispatching it

A worktree created from an older `main` gives the agent a stale baseline and a misleading test
count. `git rebase main` in the worktree first.

### 4.4 A stale baseline number invalidates the agent's own verification

Briefs state "baseline is N passed". If `main` moved, N is wrong and the agent either reports a
false regression or misses a real one. Re-read the baseline at dispatch time.

---

## 5. Writing briefs

### 5.1 State the rejected alternative and why

Fixes came back with the rationale embedded in code comments — including why the *other* option was
not taken — only when the brief supplied it. The next reader has the brief nowhere; the comment is
the only surviving record.

### 5.2 Invite disagreement explicitly, and mean it

"If you think I am wrong, say why and do not change it" produced three corrections to briefs that
were factually wrong:

- **`env=None` does not inherit the parent environment.** The brief claimed it did; the SDK
  substitutes a curated default set. The agent checked the library, implemented anyway for a
  stronger reason, and said so.
- **"Confirm zero violations over the whole tree" was unachievable.** `main` carries ~110
  pre-existing check-(a) hits in prose; making that green would require allowlisting lines no PR
  ever added — what the checker exists to prevent. The agent built the diff-scoped version instead.
- **The RI-6 sidecar refusal placement.** The agent initially defended it, then produced a better
  argument for the change than the reviewer had.

### 5.3 Name the reuse target, or demand the search that justifies new code

"Before proposing a fix, grep for whether the repo already solves it; name the existing helper you
would reuse, or state in one line what you searched for and why nothing fits."

This produced: `functools.partial` reusing RI-8's own mechanism; `_top_up_distinct_papers` reused
rather than reimplemented; `rag/vector_index.py`'s concurrent-creator pattern reused for the
`migrate()` race. Only one ticket needed genuinely new logic, with its search stated.

### 5.4 Prefer one fix at a shared choke point over N fixes at N call sites

A reviewer found one unqualified temp-file path. Grepping found **eight write sites, four of them
unqualified**, and four more each re-implementing the pattern inline. The ticket became one shared
helper rather than four patches.

### 5.5 Give the failure mode, not just the requirement

"Pin the test at a value above 32" plus *"a test pinned at 32 would pass against the bug"* got a
correct test. The requirement alone would not have.

---

## 6. Repo-specific traps

### 6.1 `git rm --cached` for files that predate `.gitignore`

`.gitignore` does not apply to already-tracked paths. Two `.pyc` files stayed tracked for months.

### 6.2 A locally-modified tracked file blocks a merge that deletes it

`git merge` aborts with "Merge with strategy ort failed" when the incoming change deletes a file
the working tree has modified. `git checkout -- <path>` first.

### 6.3 CODEOWNERS-gated paths: batch the riders

`contracts/`, `migrations/`, `ci/`, `.github/`, and now `pyproject.toml` need sign-off. Batching
four unrelated frozen-path changes into one PR pays the gate toll once.

### 6.4 Tests that stub a function hide its default-argument behaviour

`app/dashboard/test_server.py` stubbed `_live_prefetch_pids` as a **zero-argument** fake. The real
function's `data_dir=None` default — which skipped corpus qualification and made a restart SIGKILL
another corpus's downloader — was therefore invisible to the entire suite. When a bug lives in a
default argument, a stub cannot see it: exercise the real function.

### 6.5 A docstring asserting parity is not parity

`_write_sidecar`'s docstring claimed the "same atomic tmp-then-rename discipline as the PDF write"
in the same module. It did not have it — no pid qualification. Check the claim against the sibling
it names.

### 6.6 A docstring stating a precondition nothing enforces

`SqliteIngestState.__init__` documented "caller has already run `migrate()`". Nothing checked it, so
construction against an unmigrated database survived `__init__` and died later on `no such table`.
Where a precondition is cheap to satisfy, satisfy it instead of documenting it.

---

## 6b. Watching agents work

### 6b.1 `opencode serve` cannot show a headless fan-out

It lists sessions started by separate `opencode run` processes but returns **zero messages** for
them — it only streams sessions it created itself. The live data is in
`~/.local/share/opencode/opencode.db` (WAL-mode SQLite, updates as agents work). Read that
read-only instead. `~/.local/bin/oc-watch` does exactly this.

Also: `opencode serve` starts **unauthenticated** by default and warns about it in one line that is
easy to miss. That API can drive opencode with full tool access. Set `OPENCODE_SERVER_PASSWORD`
(HTTP Basic, any username) and bind to the tailnet address, never `0.0.0.0`.

### 6b.2 Show what a tool DID, not which tool it was

First version of the watch page rendered `part.data["tool"]` — a feed of `bash`, `edit`, `bash`.
Useless: the tool name says nothing about the work. The store already holds
`state.input.command`, `state.output`, `state.metadata.exit`, and for edits
`input.newString`. Render the command and its result.

This is the same mistake as reviewing documentation instead of code: the real artifact was
available and a label was displayed instead of it.

### 6b.3 `pkill -f <pattern>` matches its own command line

**Cost: killed the controlling shell twice, the second time an hour after writing this file.**

`pkill -f 'opencode serve'` matches the pkill invocation itself, because that string is in its own
`/proc/self/cmdline`. Same for a bracket trick when the *calling* shell's command line also
contains the literal text.

This is verbatim the D-12 bug already fixed in this repo (`_live_prefetch_pids` counting its own
observing process) and the RI-19 bug (an unqualified scan killing the wrong corpus's downloader).
Three instances of one bug class, two of them self-inflicted while working on the other.

**Rule:** kill by port or by a PID you captured at spawn time, never by pattern match on a string
your own command contains.

---

## 7. Open items

- Superpowers skills are wired into opencode by a **version-pinned** path
  (`.../superpowers/6.3.0/skills`). After the next upgrade it silently stops resolving with no
  error. Convert to a symlink or re-point on upgrade.
- Nested dispatch was enabled for opencode agents on 2026-08-22 (free model → fan-out costs no
  quota). Watch whether children's work gets verified by their parent before commit; the rule is
  that a child's report is a draft, not evidence.
