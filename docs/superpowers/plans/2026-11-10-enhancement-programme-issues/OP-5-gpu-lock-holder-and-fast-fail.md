Title: OP-5: Name the GPU lock holder and list foreign GPU processes in doctor
Labels: wave:1-no-gpu, area:ops, size:M

## OP-5 -- Name the GPU lock holder and list foreign GPU processes in doctor

**Review cross-reference:** S-06. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** the 20 s query-path timeout is deferred (a behaviour change on the baseline path, and a Config field the rider would have to add) until a contended real session shows the 300 s wait; `app/assembly.py` leaves Owns. Holder file and doctor foreign-process listing stay (the foreign holder of 18.6 GB is real and current). OP-5 is no longer a dependency of EV-16. Absorbs the GPU-contention section of EP-7 (see Absorbs).

**Absorbs EP-7** (part: the GPU-contention RUNBOOK section and the `gpu_lock_path` second-corpus warning, RV-6 punch row 22). EP-7's other sections go to OP-3 (backup and restore) and OP-7 (containers).

**Why.** A query waits up to 300 s (the wait itself is left as is here) for the GPU lock before erroring (`app/assembly.py:630-640` passes no `gpu_lock_timeout`, default 300 s in the embedder and reranker), the timeout message does not name the holder (`rag/gpu_lock.py:38-41`), and doctor reports only 'unreachable' when a foreign process holds the GPU (OP-1 handles 'TEI down', not 'GPU held'; RV-1 F-1.9, RV-6 F-A3 and F-A8; review S-06). A foreign model server holds 18,609 of 24,576 MiB today.

**Scope.**
- In:
  - `FileGpuLock` writes pid, stage and UTC time to a `<lock>.holder` file on acquire (best effort, removed on release) and the timeout error reads it back.
  - `app.doctor`: list foreign GPU compute processes via `nvidia-smi --query-compute-apps` and read the TEI container exit code and OOM log line, so 'GPU held by a foreign process' is distinct from 'TEI crashed' (nvidia-smi and docker calls injected so tests need neither).
  - `docs/RUNBOOK.md`: GPU-contention section (holder file, doctor's foreign-process listing, cheapest-first ordering rule from LESSONS section 9.1) and, in 'Running a second corpus', the warning that `app.init_config` writes a private `gpu_lock_path` that must be edited to the shared lock (punch row 22). Commands quoted from a run, not guessed.
- Out (explicitly):
  - The 20 s query-path timeout and its Config field (deferred until a contended real session; RIDER-1 would carry the field). Any change to `app/assembly.py` or to the lock wait time.
  - Marking eval runs invalid on lock timeouts (EV-10). A priority scheduler for the lock. Reranker-failure fallback to fused order (changes behaviour, needs a Coverage flag: foundation).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/gpu_lock.py`
- `rag/test_gpu_lock.py`
- `app/doctor.py`
- `app/test_doctor.py`
- `docs/RUNBOOK.md`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings stating the holder-file format and the doctor listing
② failing tests: second lock with timeout 0.1 raises naming the first's pid and stage; doctor names a foreign pid from a canned nvidia-smi output
③ implementation to green
④ doctor TEI exit-code and OOM-line reading with injected docker output
⑤ RUNBOOK GPU-contention section and the `gpu_lock_path` warning; every command run or `--help`-checked

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/gpu_lock.py rag/test_gpu_lock.py app/doctor.py app/test_doctor.py`
- Two `FileGpuLock` objects on one path in a unit test (no GPU)
- `grep -n 'gpu_lock_path' docs/RUNBOOK.md` shows the second-corpus warning
- Live check only when the operator frees the GPU: hold the lock from a second process; the timeout error names the holder

**Acceptance / falsification criterion.** Holding the lock from a second process (test timeout 0.1 s) makes the second acquirer's error name the holder's pid and stage; doctor output against a canned foreign-holder state names the pid and says 'GPU held by a foreign process', not 'TEI unreachable'; the default query-path wait is unchanged (no `app/assembly.py` diff). Falsified if the error omits the holder or the diff changes a timeout.

**Gates / depends on.** Depends on: OP-6 (ordering only: same file, not a data dependency). Gates: OP-7, OP-2 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** The holder file is written on every lock acquire, including on the eval path: best effort and removed on release, so no result changes (listed in the pre-baseline rule, plan section 4). A stale holder file could name a dead pid: the message states the write time. Rollback: revert.

**Docs to update in the same PR.** Section 2: doctor flags; `docs/RUNBOOK.md` GPU-contention section is part of this PR. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
