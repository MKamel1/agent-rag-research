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

### 1.4 Prove an alarming infrastructure claim by a second route before recording it

A benchmark run reported: "every gold chunk exists in SQLite but has **no vector** in Qdrant —
catastrophic fixture-vs-corpus mismatch." It was a payload-key error. The collection stores a
chunk's id in the payload field `_ext_id`; the harness looked for `chunk_id`, which does not exist,
so every lookup missed. Two cheap independent checks contradicted it immediately: the collection
reports 47,893 points against 46,155 SQLite chunks (a corpus with no vectors cannot), and scrolling
any single point shows the payload keys.

The asymmetry is what makes this worth a rule. A *boring* result that is wrong wastes one run. An
*alarming* result that is wrong redirects the whole investigation, and the alarm suppresses the
instinct to double-check — it feels urgent to report, not to verify. So: the more infrastructure-
shaped and severe the finding, the more it owes a second, differently-shaped confirmation before it
is written down.

Same shape as §1.1: a check that cannot fail for the reason you think it can is not evidence.

### 1.5 Verifying a fixture means handling every item shape it contains

Twice now a verification pass over a ground-truth fixture reported false failures because the
checker assumed one item shape. `waymo_gt_verified.json` has five: a plain single-passage item; one
with `supporting_sources` alongside a primary; a multi-paper item carrying **only**
`supporting_passages` and no top-level `source_paper_id` (this one raised `KeyError`, then, once
guarded, silently skipped); an `absent` item with no gold chunk at all by construction; and a
vision item with a `gold_block_id` and `page` but no chunk and an excerpt that is not in any text.

A checker that crashes is the good case — it tells you. A checker that skips what it does not
recognise reports a clean pass over a subset and calls it the whole set. Count what you checked and
assert the count: 519 checks over 73 items is a claim that can be wrong out loud; "0 failures" is
not.

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

### 3.1b The multi-item rule applies to the person writing the brief, too

**Cost: a 50-minute run, zero commits, everything lost — after §3.1 was already written.**

RI-27 was handed a five-part brief (four defects plus a design task). It spent its whole budget
reading and committed nothing. §3.1 above says exactly why this happens and was written hours
earlier by the same person who wrote that brief.

Two things make the rule stick better than "keep briefs small":

- **Name the failure in the brief itself.** The re-dispatch opened with "a previous attempt at this
  ticket was given five fixes, spent fifty minutes reading, and committed nothing." An agent that
  knows the failure mode guards against it.
- **Forbid reading ahead.** "Do fix 1, run its tests, COMMIT, and only then start fix 2. Do not read
  ahead to fix 2 before fix 1 is committed." Without that, an agent front-loads comprehension of
  the whole brief — which is the behaviour that runs out the budget.

Rule of thumb: **two items per brief, three at the absolute most**, and only when they share a
file. Anything larger is two dispatches.

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

### 3.3b A hang at startup leaves no trace at all — distinguish it from working quietly

**Cost: ~35 minutes across two agents before it was spotted.**

Three failure modes look similar from outside and are not:

| symptom | cause | signature |
|---|---|---|
| result `exit 0`, `tools: []`, empty output | provider quota refusal | 429 in a raw `opencode run` |
| commits partially done, work uncommitted | ran out of budget mid-task | session exists, tokens climbing |
| **nothing at all** | **hung before reaching the model** | **NO session row, no stderr, no log line** |

The third has no trace in the wrapper's output, so waiting looks identical to progress. Diagnose by
querying the session store directly:

```sql
SELECT COUNT(*) FROM session WHERE directory LIKE '%<worktree>%';
```

Zero rows plus a live process for many minutes means hung, not busy. Confirm the provider is fine
with an independent one-line `opencode run` before blaming it.

Observed cause candidate: the remote MCP servers in `opencode.json` blocking on connect. `--pure`
runs without external plugins and is worth trying when a dispatch hangs at startup.

**This is the argument for the watch page.** Without a live view into the session store, the only
signal is a 50-minute timeout.

### 3.3d The silent mid-work death: exit 0, no error, log ends at the model call

The dominant operational cost of one long session. A dispatch working normally simply stops. The
signature is unambiguous once you know it:

- the per-dispatch `opencode.log` ends at `message="llm runtime selected"` — the request went out
  and nothing came back;
- **no error line anywhere**, at any level;
- the process exits **0**, and the `--json` payload reports `"exit": 0` with
  `"tokens": {"input": 0, "output": 0}` and `"cost": 0.0`;
- the final `output` string is a running narration that stops mid-sentence.

Observed 8+ times across three tickets in one session, at 14-31 minutes in, on `stealth/ox-alpha`.

**It is not quota.** That was the first hypothesis (§3.3 says an empty result is a quota signal) and
it was wrong. A direct probe of the same model on the same key answered normally, cost 0, while
three dispatches were dying:

```
curl -s https://openrouter.ai/api/v1/chat/completions -H "Authorization: Bearer $KEY" \
  -d '{"model":"stealth/ox-alpha","messages":[{"role":"user","content":"Reply: alive"}],"max_tokens":200}'
# -> {"content": "alive", "usage": {"cost": 0, ...}}
```

Note the model id: `stealth/ox-alpha`, **not** `openrouter/stealth/ox-alpha` — the latter returns
`"is not a valid model ID"` (400) and would make a health check look like an outage.

The root cause was not found and chasing it further was not worth the time. What matters is that the
mitigation is cheap and total:

**Brief every dispatch to commit at every green point, never to batch work for the end.** Before that
instruction, three deaths lost 10-25 minutes of uncommitted work each — one left a repo file with a
truncated line that did not parse. After it, four more deaths cost nothing: each left a clean
worktree with its work on the branch. Same failure, zero loss.

Two corollaries:

- **Split long-running jobs out of agent sessions entirely.** A 6-hour corpus backfill cannot be
  supervised by something that dies every 20 minutes. Have the agent build and gate the tool, then
  launch the run as a detached process with its own log. Require the tool to survive a hard kill and
  resume, because it will get one.
- **A dead agent's reasoning is still recoverable and often worth more than its files.** One dispatch
  died immediately before writing three ground-truth items. The items were lost; the transcript in
  its session DB held the full analysis — three validated candidates with anchors, and two rejected
  ones with the evidence that killed them (a value that leaked into extracted text, a page with no
  blocks to anchor to). Reading that out of `part` turned a lost run into a complete handoff. Check
  the transcript before re-dispatching the same work.

### 3.3c Telling a startup hang from a working agent, by log line count

§3.3b says a startup hang leaves no trace. It leaves exactly one: the per-dispatch
`$XDG_DATA_HOME/opencode/log/opencode.log` stops at `message=init`, around **11 lines**. A healthy
dispatch passes `init` within seconds and reaches `message=stream providerID=... modelID=...`, then
grows steadily — a working agent 25 minutes in had **429** lines and a `loop ... step=37`.

So the check is a one-liner, and it is the first thing to run on a quiet agent:

```
wc -l $STATE/opencode/log/opencode.log     # ~11 and static  => hung at init
grep -c "llm runtime selected" .../opencode.log   # 0 => never reached the model
```

The session database does not tell you this. A hung dispatch creates its `opencode.db` and leaves it
at 4096 bytes with an unflushed WAL and **zero rows in `part`** — indistinguishable at a glance from
a store you cannot read.

**Cost: 25 minutes of a dead GT-A dispatch, three restarts in a row, none noticed.** What hid it was
watching the wrong signal: the monitor read the branch tip, which was legitimately unchanged, so
"no new commits" looked like "still working". Two rules follow:

- Watch the **working tree**, not the branch tip. Agents write files long before they commit, and a
  tip that has not moved is ambiguous between working, hung, and dead.
- A liveness signal must be able to distinguish *running* from *stalled*. Process-alive is not it:
  the hung dispatch held 7 seconds of CPU across 24 minutes and looked alive in `ps` throughout.

Observation, not a proven cause: the three hung GT-A dispatches all started against a worktree with
an uncommitted modified file, and the two healthy concurrent dispatches started against clean trees.
Committing the pending work and re-dispatching on a clean tree started normally. One data point
each way — worth trying before a deeper diagnosis, not worth believing yet.

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

### 4.5 One SQLite session store is why concurrent dispatches deadlock — isolate it, do not serialize

**Cost: parallelism abandoned for roughly an hour on a wrong diagnosis.** §6b.1b blamed
`opencode serve` and the fix recorded there was "do not run the server". That was half the story
and the wrong half to generalise from: the server is only the loudest writer. *Any* two concurrent
`opencode run` processes contend on the same `~/.local/share/opencode/opencode.db`, and the second
one stalls. Having found that, the response was to run dispatches one at a time — which made the
symptom go away and threw away the swarm.

The store's location is controlled by `XDG_DATA_HOME`. Giving each dispatch its own removes the
contention entirely:

```python
state = Path(tempfile.gettempdir()) / f"oc-state-{os.getpid()}-{uuid.uuid4().hex[:8]}"
(state / "opencode").mkdir(parents=True, exist_ok=True)
link = state / "opencode" / "auth.json"          # credentials must still resolve
if (real := Path.home() / ".local/share/opencode/auth.json").exists() and not link.exists():
    link.symlink_to(real)
env["XDG_DATA_HOME"] = str(state)
```

`oc-task` now does this by default; `--shared-state` opts back into the single store. Four
concurrent dispatches ran clean afterwards.

Two lessons, and the second is the bigger one:

- Serializing to dodge a contention bug is a workaround wearing a fix's clothes. It looks like it
  worked because the symptom is gone, and it silently costs whatever the parallelism was worth.
- The watcher reads a *different* database per dispatch now. `oc-watch` had to learn to glob
  `/tmp/oc-state-*/opencode/opencode.db`, and until it did, the watch page showed nothing while
  four agents worked normally — a fix in one place breaking observability in another.

### 4.6 Do not resume a session that has accumulated a large context

Continuing GT-A by resuming its existing session (~3.3M accumulated tokens) produced 40 minutes of
re-reading its own history and **zero commits**. Re-dispatching a *fresh* agent with a narrow,
append-only brief — "the file exists and has 33 items, add items 34+, do not rewrite what is there"
— produced work immediately.

Resume (§3.2) is right for a session that was interrupted mid-task. It is wrong for one that has
already finished a phase: the accumulated context is now cost without value, and the model spends
its budget reconstructing a state the brief could have stated in three lines.

### 4.7 A queued chain script is an invisible second dispatcher

RI-32 ran **twice, concurrently, in the same worktree** for eight minutes. One dispatch was manual;
the other came from a `chain3.sh` started 80 minutes earlier that was blocked in
`until grep -q "CHAIN COMPLETE" chain2.log` and fired the moment chain2 finished. Nothing in `ps`,
the branch, or the agent list said "a dispatch is pending" — the chain was just a sleeping shell.

The tree survived: syntactically valid, no duplicated definitions. That is luck, not a property.
Two agents editing one `document_store.py` can interleave into something that parses and is wrong.

- **Before dispatching, check for a queued dispatcher**, not just a running agent:
  `ps -ef | grep -E "chain[0-9]*\.sh"` and read the tail of every chain log.
- **One ticket, one worktree, one live dispatch.** If a second is wanted, it needs its own worktree.
- A chain that waits on a marker in another log should re-check the precondition it was written for
  at fire time, not only the marker. "chain2 finished" is not "RI-32 still needs doing".

### 4.8 Never print an opencode process's command line

`tr '\0' ' ' < /proc/<pid>/cmdline` on an `opencode run` process prints **the entire brief** — the
brief is passed as the argument. Three of them cost thousands of tokens of context for one fact
(the parent pid) that `awk '/^PPid:/{print $2}' /proc/<pid>/status` gives in one line.

Read `/proc/<pid>/status` for parentage, `wc -l` on the dispatch's log for liveness (§3.3c), and
`cut -c1-120` on a cmdline if you genuinely need to identify it.

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

### 6b.1b `opencode serve` starves headless runs — do not leave it running

**Cost: four dispatches stalled across roughly two hours before the correlation was spotted.**

**Superseded in part by §4.5** — the real cause is any concurrent writer on the shared store, and
the fix is per-dispatch state isolation, not avoiding the server.

`opencode serve` and every `opencode run` share one SQLite store (`~/.local/share/opencode/
opencode.db`). A long-lived server holding write locks on it starves the headless runs: they either
never create a session row at all, or create one, complete a single request, and then sit idle
indefinitely.

The timeline was the evidence. RI-19, 21, 22, 23, 24, 26 and 28 all ran clean **before** the server
was started for the watch page. RI-27, 29, 30 and 31 all stalled **after**. Killing the server and
re-dispatching moved RI-30 from `18,302 in / idle 813s` (frozen) to `19,598 in / 2,475 out /
idle 6s` (working) immediately.

This is nasty because it presents as two *different* failures — the startup hang of §3.3b and a
mid-stream stall — and neither points at the server.

**Rule:** do not run `opencode serve` while dispatching headless agents. `oc-watch` reads the same
database **read-only** and does not cause this — it stayed up throughout, including while the fix
was verified. Prefer it for observation, and treat any unexplained agent stall by first checking
whether something is holding that database.

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

**Third occurrence (same session):** `pgrep -f "RI-27-dashboard-accuracy"` — the bracket trick does
not help when the *calling shell's* command line carries the literal, which it always does. The
only reliable form is a script file where the pattern arrives as an argument and never appears in
the shell invocation, and which excludes its own pid and ancestor chain:

```python
mine = {os.getpid()}  # plus the ppid chain, walked from /proc/<pid>/stat
for d in os.listdir("/proc"):
    if d.isdigit() and int(d) not in mine and target in open(f"/proc/{d}/cmdline").read():
        os.kill(int(d), signal.SIGTERM)
```

Three self-inflicted instances of the bug class this repo has fixed twice in product code. The
lesson is not "be careful with pkill" — it is that **any process scan must exclude its own
observer**, and a scan written inline in a shell cannot.

---

## 7. Open items

- Superpowers skills are wired into opencode by a **version-pinned** path
  (`.../superpowers/6.3.0/skills`). After the next upgrade it silently stops resolving with no
  error. Convert to a symlink or re-point on upgrade.
- Nested dispatch was enabled for opencode agents on 2026-08-22 (free model → fan-out costs no
  quota). Watch whether children's work gets verified by their parent before commit; the rule is
  that a child's report is a draft, not evidence.

## 7. The Waymo-priority benchmark programme (2026-08-23)

### 7.1 An image read ends the turn — batch around it

Reading an image file with the Read tool returns the image as a new user message, which ends the
assistant turn mid-chain. During GT-WMR authoring three image reads (figure renders for vision
items) landed mid-workflow and the operator experienced each break as the agent "stopping",
asking twice why. The work was never stalled — but perception is the experience. Rule: batch all
non-image work into the same turn, do image reads only when nothing else remains, and say once,
explicitly, that an image read will end the turn before doing it.

### 7.2 Ceiling-check every metric BEFORE freezing a benchmark protocol

The frozen protocol defined Precision@10 as `|top-k ∩ gold| / k` over single-gold-paper queries.
With a retriever returning k mostly-distinct papers, that quantity is structurally capped near
`1/k` (measured ceiling 0.1086–0.1132): a literally perfect retrieval system scores ~0.10 against
a 0.95 target. The failure was caught only at measurement time, costing a dated addendum and two
"failed" gates that mean nothing. A frozen metric needs an achievability bound computed at freeze
time — thirty seconds of arithmetic (`max P@10 = min(distinct results, gold count)/k`) would have
caught it. Definitions get reviewed for vagueness; they also need review for reachability.

### 7.3 Measurement fan-out: N detached processes beat N agent sessions

The six benchmark runs (2 fixtures × 3 sparse-modes) were launched as detached `setsid` processes
writing independent report files and finished in ~90 s wall clock, with zero supervision. This is
the same fan-out shape that repeatedly died when done as concurrent opencode agent sessions
(§6b, the nine silent deaths). The difference is not concurrency — it's that a benchmark run is a
deterministic process with one input and one output file, needing no judgment mid-flight. Rule:
fan out *measurements* as processes; spend agent sessions only on the judgment work around them.
(The one headless agent dispatched this programme — the isolated-XDG_DATA_HOME verifier — did
complete, and earned its keep: it caught Q-WMR-080's absence note understating a real 41%-vs-24%
evening/overnight figure in the 56.7M paper's Limitations, the Q-GTA-035 near-miss pattern again.)

### 7.4 Never hand-type verbatim excerpts from terminal dumps

9 of 66 excerpt-bearing GT-WMR items failed verbatim verification on first build: `<sup>` tags
invisible in trimmed dumps, citation digits ("et al.5"), case drift from a probe transcript. The
builder's fix — difflib match (≥85% coverage) against the tag-stripped chunk, then substitute the
exact DB span and log the re-grounding in `_metadata.corrections` — converted all 9 into verified
verbatim excerpts. The general rule: excerpt fidelity is a build-time machine check, not an
authoring skill; author intent + programmatic extraction, and log every substitution.
