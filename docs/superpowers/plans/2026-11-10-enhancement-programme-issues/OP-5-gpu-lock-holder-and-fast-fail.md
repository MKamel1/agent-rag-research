Title: OP-5: Name the GPU lock holder and fail fast on the query path
Labels: wave:1-no-gpu, area:ops, size:M

## OP-5 -- Name the GPU lock holder and fail fast on the query path

**Review cross-reference:** S-06. **Wave:** W1 do now, no GPU.

**Why.** A query waits up to 300 s for the GPU lock before erroring (`app/assembly.py:630-640` passes no `gpu_lock_timeout`, default 300 s in the embedder and reranker), the timeout message does not name the holder (`rag/gpu_lock.py:38-41`), and doctor reports only 'unreachable' when a foreign process holds the GPU (OP-1 handles 'TEI down', not 'GPU held'; RV-1 F-1.9, RV-6 F-A3 and F-A8; review S-06). A foreign model server holds 18,609 of 24,576 MiB today.

**Scope.**
- In:
  - `FileGpuLock` writes pid, stage and UTC time to a `<lock>.holder` file on acquire (best effort, removed on release) and the timeout error reads it back.
  - Query path only: pass a short `gpu_lock_timeout` (proposed 20 s, a named constant; ingest keeps 300 s) with an actionable message.
  - `app.doctor`: list foreign GPU compute processes via `nvidia-smi --query-compute-apps` and read the TEI container exit code and OOM log line, so 'GPU held by a foreign process' is distinct from 'TEI crashed' (nvidia-smi and docker calls injected so tests need neither).
- Out (explicitly):
  - Marking eval runs invalid on lock timeouts (EV-10). A priority scheduler for the lock (not needed; the holder file is the smallest step). Reranker-failure fallback to fused order (changes behaviour, needs a Coverage flag: foundation).
  - The Config field for the timeout (RIDER-1 item 1).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/gpu_lock.py`
- `rag/test_gpu_lock.py`
- `app/doctor.py`
- `app/test_doctor.py`
- `app/assembly.py`
- `app/test_assembly.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings stating the holder-file format and the 20 s query-path timeout
② failing tests: second lock with timeout 0.1 raises with the first's stage label; query-path construction passes the short timeout; doctor names a foreign pid from a canned nvidia-smi output
③ implementation to green
④ doctor TEI exit-code and OOM-line reading with injected docker output

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/gpu_lock.py rag/test_gpu_lock.py app/doctor.py app/test_doctor.py app/assembly.py app/test_assembly.py`
- Two `FileGpuLock` objects on one path in a unit test (no GPU)
- Live check only when the operator frees the GPU: hold the lock from a second process, `semantic_search` returns the named error in under 22 s

**Acceptance / falsification criterion.** Holding the lock from a second process makes the query path fail in under 22 s with the holder named; doctor output against a canned foreign-holder state names the pid and says 'GPU held by a foreign process', not 'TEI unreachable'. Falsified if the error still waits the full default or omits the holder.

**Gates / depends on.** Depends on: OP-6. Gates: EP-7, EP-3, OP-2, EV-16, RIDER-1.

**Needs.** GPU: n · services up: none · operator sign-off: n for the code; the 20 s value is a decision in PR review. Moving it into Config rides RIDER-1 item 1. · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A 20 s ceiling will fail queries that today would have waited out a long GPU job. That is the intended behaviour but changes what an agent sees. Mitigation: ingest is unaffected; the value is one constant. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (doctor flags) via EP-3; RUNBOOK GPU-contention section via EP-7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
