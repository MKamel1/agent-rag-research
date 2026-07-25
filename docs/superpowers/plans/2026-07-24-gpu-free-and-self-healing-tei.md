# GPU Free/Reload + Self-Healing TEI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator explicitly free the TEI containers' VRAM (~9.4GB) on demand and reload
it on demand, and make the real MCP query path self-healing so a query right after a free (or
right after Pass 1 evicted TEI) reloads it automatically instead of erroring.

**Architecture:** One new primitive (`app/tei_lifecycle.py::ensure_tei_running`, health-check-first
then start-if-needed) is consumed two ways: as an injected `ensure_ready` hook on the real
`TeiEmbedder`/`TeiReranker` adapters (wired only into the MCP query-path composition,
`app/assembly.py::build_mcp_server`), and directly by two new dashboard control actions
(`free_gpu`/`load_for_mcp` in `app/dashboard/controller.py`). No change to pause/resume/stop.

**Tech Stack:** Python 3 stdlib (`urllib`, `sqlite3`), `httpx` (already a core dependency for the
TEI-facing adapters), pytest + `httpx.MockTransport` for adapter tests, vanilla JS/HTML for the
dashboard frontend (no framework, no JS test harness — this repo tests frontend changes via
HTML-substring assertions in `app/dashboard/test_server.py`).

## Global Constraints

- `ensure_ready`/`ensure_tei_running` must be **best-effort and never raise** — same contract as
  the existing `stop_tei_containers()`/`start_tei_containers()` (a failure logs a warning and
  returns). No new exception type, no new try/except needed at any call site that uses it — the
  existing `TransientError`/`PermanentError` classification on the subsequent real HTTP call
  already covers "TEI still not up after the best-effort attempt."
- `rag/embedder.py`/`rag/reranker.py` must **never** contain the literal string "tei" or "docker"
  anywhere (case-insensitive) — `ci/checks/vendor_isolation.py`'s mechanical CI check enforces this
  (it already broke PR #170 once on an unrelated docstring). The new hook parameter must be named
  and documented generically (e.g. `ensure_ready: Callable[[], None] | None`), never naming the
  vendor.
- `app/assembly.py::build_ingestion_orchestrator` (the ingest-side composition) is **not** touched
  by this plan — only `build_mcp_server` (the query-side composition) gets the new hook wired in.
  Ingest's own Pass 2 already guarantees TEI health via an explicit `start_tei_containers()` call
  before `finish_phase()` begins (T-DOC19); this plan does not change that.
- No change anywhere to `pause()`/`resume()`/`stop()` in `app/dashboard/controller.py` — the new
  `free_gpu`/`load_for_mcp` actions are additive, independent functions.
- Spec: `docs/DESIGN-gpu-free-and-self-healing-tei.md`.

---

### Task 1: `app/tei_lifecycle.py` — `ensure_tei_running()`

**Files:**
- Modify: `app/tei_lifecycle.py`
- Test: `app/test_tei_lifecycle.py`

**Interfaces:**
- Produces: `tei_lifecycle.ensure_tei_running(client: httpx.Client | None = None) -> None` —
  best-effort, never raises. If both containers are already healthy, this is two health GETs and
  nothing else (no `docker` call). Otherwise calls the existing `start_tei_containers(client=client)`.

- [ ] **Step 1: Write the failing tests**

Add to `app/test_tei_lifecycle.py`, after the existing `start_tei_containers()` test section (after
`test_start_tei_containers_swallows_a_connection_error_as_unhealthy`, end of file):

```python
# ---------------------------------------------------------------------------
# ensure_tei_running()
# ---------------------------------------------------------------------------


def test_ensure_tei_running_is_a_pure_health_check_when_already_healthy(monkeypatch):
    """The common case: both containers already up -- must NOT call `docker start` at all, just
    the two health GETs."""
    docker_calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kwargs: docker_calls.append((args, kwargs))
    )

    from app.tei_lifecycle import ensure_tei_running

    ensure_tei_running(client=_healthy_client())

    assert docker_calls == [], "already-healthy must never shell out to docker"


def test_ensure_tei_running_falls_through_to_start_when_not_healthy(monkeypatch):
    """Either endpoint unhealthy -- must fall through to the real start_tei_containers() behavior
    (docker start + poll), proven by the same docker-call assertion start_tei_containers()'s own
    tests already use."""
    docker_calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kwargs: docker_calls.append((args, kwargs))
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)  # healthy once docker start "ran" -- proves the fallthrough path

    client = httpx.Client(transport=httpx.MockTransport(handler))

    from app.tei_lifecycle import ensure_tei_running

    ensure_tei_running(client=client)

    assert len(docker_calls) == 1
    args, kwargs = docker_calls[0]
    assert args == ["docker", "start", *_TEI_CONTAINERS]


def test_ensure_tei_running_checks_both_endpoints_not_just_the_first(monkeypatch):
    """One endpoint healthy, the other not -- must still fall through to start (both must be
    healthy to skip it), not short-circuit on the first check alone."""
    docker_calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kwargs: docker_calls.append((args, kwargs))
    )

    def handler(request: httpx.Request) -> httpx.Response:
        # Embedder (8080) healthy, reranker (8082) not -- both must be checked.
        return httpx.Response(200 if "8080" in str(request.url) else 503)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    from app.tei_lifecycle import ensure_tei_running

    ensure_tei_running(client=client)

    assert len(docker_calls) == 1, "must fall through to start when EITHER endpoint is unhealthy"


def test_ensure_tei_running_default_client_is_none_and_still_works(monkeypatch):
    """No client injected -- must build its own (matching start_tei_containers()'s own default
    behavior) rather than raising on a missing argument."""
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: None)
    monkeypatch.setattr(_mod, "_TEI_START_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(_mod, "_TEI_START_POLL_TIMEOUT_SECONDS", 0.05)

    from app.tei_lifecycle import ensure_tei_running

    ensure_tei_running()  # must not raise -- real network calls will just fail fast/timeout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/test_tei_lifecycle.py -k ensure_tei_running -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_tei_running'`.

- [ ] **Step 3: Implement `ensure_tei_running`**

In `app/tei_lifecycle.py`, add after `start_tei_containers` (after its closing `logger.warning(...)`
block, before `_is_healthy`):

```python
def ensure_tei_running(client: httpx.Client | None = None) -> None:
    """Best-effort, never raises (same contract as `stop_tei_containers`/`start_tei_containers`).
    If both containers are ALREADY healthy, this is two fast `GET /health` calls and nothing else
    -- no `docker` command. Otherwise falls through to `start_tei_containers` (docker start + the
    same bounded health poll that function already does).

    `client` is injectable for tests, same as `start_tei_containers`. When `None`, builds one
    short-lived `httpx.Client` and reuses it for both the health check here and (if needed) the
    poll inside `start_tei_containers`, rather than constructing two."""
    if client is None:
        client = httpx.Client(timeout=5.0)

    urls = (_TEI_EMBED_HEALTH_URL, _TEI_RERANK_HEALTH_URL)
    if all(_is_healthy(client, url) for url in urls):
        return

    start_tei_containers(client=client)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest app/test_tei_lifecycle.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add app/tei_lifecycle.py app/test_tei_lifecycle.py
git commit -m "T-DOC78: add tei_lifecycle.ensure_tei_running() -- health-check-first reload"
```

---

### Task 2: `rag/embedder.py` + `rag/reranker.py` — `ensure_ready` hook

**Files:**
- Modify: `rag/embedder.py`
- Modify: `rag/reranker.py`
- Test: `rag/test_embedder.py`
- Test: `rag/test_reranker.py`

**Interfaces:**
- Produces: `TeiEmbedder.__init__(..., *, ..., ensure_ready: Callable[[], None] | None = None)` and
  `TeiReranker.__init__(..., *, ..., ensure_ready: Callable[[], None] | None = None)` — both
  keyword-only, both default `None` (today's exact behavior, byte-for-byte, for every existing
  caller/test). When set, called exactly once per `embed()`/`rerank()` invocation (never per
  sub-batch), immediately after the existing empty-input short-circuit, before any HTTP work.

- [ ] **Step 1: Write the failing tests**

Add to `rag/test_embedder.py`. Existing tests build a real `TeiEmbedder` via `_build_real_embedder(client,
gpu_lock, **kwargs)` (kwargs forward straight to `TeiEmbedder(...)`, so `ensure_ready=...` passes
through unmodified) combined with `_FakeTeiClient(dim)` (a `client.post()` stand-in that returns
one correctly-`dim`-shaped vector per input text, already used by
`test_embed_sub_batches_over_the_tei_limit_and_preserves_order` — reuse it exactly, don't build a
raw `httpx.MockTransport` response by hand, since `_build_real_embedder` fixes `dim=8` internally
and a hand-built response of the wrong dimension will raise `ContractError`). Add these tests near
the existing sub-batching test (`test_embed_sub_batches_over_the_tei_limit_and_preserves_order`):

```python
def test_ensure_ready_hook_called_once_before_the_http_call():
    calls = []
    client = _FakeTeiClient(8)
    adapter = _build_real_embedder(client, FakeGpuLock(), ensure_ready=lambda: calls.append("ready"))

    adapter.embed(["one text"])

    assert calls == ["ready"]


def test_ensure_ready_hook_called_once_even_with_multiple_sub_batches():
    """Proves the hook fires once per embed() call, not once per _MAX_BATCH_SIZE sub-batch."""
    calls = []
    client = _FakeTeiClient(8)
    adapter = _build_real_embedder(client, FakeGpuLock(), ensure_ready=lambda: calls.append("ready"))

    adapter.embed([f"text {i}" for i in range(45)])  # > _MAX_BATCH_SIZE (32) -- forces 2 sub-batches

    assert calls == ["ready"], "must fire once per embed() call, not once per sub-batch"
    assert len(client.batch_sizes) > 1  # sanity check: this really did multi-batch


def test_ensure_ready_hook_not_called_on_empty_input():
    calls = []
    client = _FakeTeiClient(8)
    adapter = _build_real_embedder(client, FakeGpuLock(), ensure_ready=lambda: calls.append("ready"))

    result = adapter.embed([])

    assert result == []
    assert calls == [], "an empty call is a zero-cost no-op -- must not pay for a readiness check"


def test_no_ensure_ready_hook_is_the_unchanged_default():
    """Every existing caller/test omits ensure_ready -- must behave exactly as before this
    feature existed (no AttributeError, no behavior change)."""
    client = _FakeTeiClient(8)
    adapter = _build_real_embedder(client, FakeGpuLock())  # no ensure_ready kwarg at all

    result = adapter.embed(["one text"])

    assert len(result) == 1
```

Add to `rag/test_reranker.py`. Existing tests construct `TeiReranker` directly (`TeiReranker(client,
lock)`, no builder helper) and build candidates via the existing `_candidates(*pairs)` helper
already in this file (`_candidates(("a", "text a"))` -> `[RerankCandidate(id="a", text="text a")]`)
— reuse both exactly as-is, add these tests near the existing GPU-lock test
(`test_rerank_acquires_the_rerank_gpu_lock`):

```python
def test_ensure_ready_hook_called_once_before_the_http_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"index": 0, "score": 0.9}])

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock(), ensure_ready=lambda: calls.append("ready"))

    reranker.rerank("query", _candidates(("a", "text a")))

    assert calls == ["ready"]


def test_ensure_ready_hook_not_called_on_empty_candidates():
    calls = []
    client = httpx.Client(base_url="http://tei.local")
    reranker = TeiReranker(client, FakeGpuLock(), ensure_ready=lambda: calls.append("ready"))

    result = reranker.rerank("query", [])

    assert result == []
    assert calls == [], "an empty candidate list is a zero-cost no-op"


def test_no_ensure_ready_hook_is_the_unchanged_default():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"index": 0, "score": 0.9}])

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock())  # no ensure_ready kwarg at all

    result = reranker.rerank("query", _candidates(("a", "text a")))

    assert len(result) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest rag/test_embedder.py -k ensure_ready -v rag/test_reranker.py -k ensure_ready -v`
Expected: FAIL — `TypeError: ... got an unexpected keyword argument 'ensure_ready'` (both files).

- [ ] **Step 3: Add the hook to `TeiEmbedder`**

In `rag/embedder.py`, add `from collections.abc import Callable` is already imported (check the
existing `import` block — `RetrySleep = Callable[[float], None]` already uses it, so no new import
needed). Modify `__init__` and `embed`:

```python
    def __init__(
        self,
        client: httpx.Client,
        gpu_lock: GpuLock,
        info: EmbedderInfo,
        *,
        max_retries: int = 2,
        retry_sleep: RetrySleep | None = None,
        gpu_lock_timeout: float | None = _DEFAULT_GPU_LOCK_TIMEOUT_S,
        ensure_ready: Callable[[], None] | None = None,
    ):
        self._client = client
        self._gpu_lock = gpu_lock
        self._info = info
        self._max_retries = max_retries
        self._retry_sleep = retry_sleep or _default_retry_sleep
        self._gpu_lock_timeout = gpu_lock_timeout
        self._ensure_ready = ensure_ready

    @property
    def info(self) -> EmbedderInfo:
        return self._info

    def embed(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []

        if self._ensure_ready is not None:
            self._ensure_ready()

        raw_vectors = []
        for start in range(0, len(texts), _MAX_BATCH_SIZE):
            batch = texts[start : start + _MAX_BATCH_SIZE]
            raw_vectors.extend(self._post_batch_with_retry(batch))
```

Also add one sentence to the class docstring (right after the "Acquires `gpu_lock.acquire`..."
paragraph): `"ensure_ready` (optional, default `None`): called once per `embed()` call, before any
HTTP work, if the caller wants a readiness check/side effect run first — this adapter never
interprets what it does or catches anything it raises; a caller that wants best-effort semantics
must make its own hook best-effort."`

- [ ] **Step 4: Add the hook to `TeiReranker`**

In `rag/reranker.py`, same shape:

```python
    def __init__(
        self,
        client: httpx.Client,
        gpu_lock: GpuLock,
        *,
        max_retries: int = 2,
        retry_sleep: RetrySleep | None = None,
        gpu_lock_timeout: float | None = _DEFAULT_GPU_LOCK_TIMEOUT_S,
        ensure_ready: Callable[[], None] | None = None,
    ):
        self._client = client
        self._gpu_lock = gpu_lock
        self._max_retries = max_retries
        self._retry_sleep = retry_sleep or _default_retry_sleep
        self._gpu_lock_timeout = gpu_lock_timeout
        self._ensure_ready = ensure_ready

    def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankCandidate]:
        if not candidates:
            return []

        if self._ensure_ready is not None:
            self._ensure_ready()

        if len(candidates) > _MAX_BATCH_SIZE:
```

(`rag/reranker.py` already has `from collections.abc import Callable` via its own
`RetrySleep = Callable[[float], None]` line — no new import needed here either.) Add the same
one-sentence docstring note to `TeiReranker`'s class docstring.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest rag/test_embedder.py rag/test_reranker.py -v`
Expected: PASS (every existing test plus the new ones — existing tests never pass `ensure_ready`,
so they exercise the unchanged `None` default path)

- [ ] **Step 6: Commit**

```bash
git add rag/embedder.py rag/reranker.py rag/test_embedder.py rag/test_reranker.py
git commit -m "T-DOC78: add optional ensure_ready hook to TeiEmbedder/TeiReranker"
```

---

### Task 3: `app/assembly.py` — wire the hook into the query path

**Files:**
- Modify: `app/assembly.py:588-612` (`build_mcp_server`)
- Test: `app/test_assembly.py`

**Interfaces:**
- Consumes: `tei_lifecycle.ensure_tei_running` (Task 1), `TeiEmbedder`/`TeiReranker`'s `ensure_ready`
  kwarg (Task 2).

- [ ] **Step 1: Write the failing test**

Add to `app/test_assembly.py`. First extend the existing `_FakeTeiLifecycle` class (around line 751)
with a spy for the new function:

```python
class _FakeTeiLifecycle:
    def __init__(self):
        self.stop_calls = 0
        self.start_calls = 0
        self.ensure_calls = 0

    def stop_tei_containers(self) -> None:
        self.stop_calls += 1

    def start_tei_containers(self) -> None:
        self.start_calls += 1

    def ensure_tei_running(self) -> None:
        self.ensure_calls += 1
```

(This REPLACES the existing 3-method class at that location — add the `ensure_calls`
counter/method, keep `stop_calls`/`start_calls`/their methods exactly as they are.)

Then add a new test near `build_mcp_server`'s other tests (search the file for any existing
`build_mcp_server` test to place this near; if none exist yet, place it after
`test_build_ingestion_orchestrator_wires_on_stage_when_given`):

```python
def test_build_mcp_server_wires_ensure_ready_into_embedder_and_reranker(monkeypatch, tmp_path):
    """T-DOC78: the query-path composition (unlike build_ingestion_orchestrator) wires
    tei_lifecycle.ensure_tei_running as the embedder/reranker's readiness hook, so a query right
    after TEI gets evicted (Free GPU, or Pass 1) self-heals instead of erroring."""
    fake_tei_lifecycle = _FakeTeiLifecycle()
    monkeypatch.setattr("app.assembly.tei_lifecycle", fake_tei_lifecycle)

    cfg = Config(focus_area_queries=["causal inference"], gpu_lock_path=str(tmp_path / ".gpu.lock"))
    server = build_mcp_server(
        cfg, db_path=str(tmp_path / "papers.db"), blob_dir=str(tmp_path / "blobs"),
        collection="papers",
    )

    embedder = server._retriever._embedder
    reranker = server._retriever._reranker

    assert embedder._ensure_ready is fake_tei_lifecycle.ensure_tei_running
    assert reranker._ensure_ready is fake_tei_lifecycle.ensure_tei_running


def test_build_ingestion_orchestrator_embedder_has_no_ensure_ready_hook(monkeypatch, tmp_path):
    """The ingest-side composition must NOT get this hook -- Pass 2 already guarantees TEI health
    via its own explicit start_tei_containers() call before finish_phase() begins (T-DOC19); a
    per-call health-check hook there would just be a redundant HTTP round-trip on every one of
    thousands of ingest embed calls."""
    orchestrator, _fake_summarizer, _fake_tei_lifecycle = _build_orchestrator_for_hook_test(
        monkeypatch, tmp_path
    )

    assert orchestrator._embedder._ensure_ready is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/test_assembly.py -k "wires_ensure_ready or embedder_has_no_ensure_ready" -v`
Expected: FAIL — `AttributeError: 'TeiEmbedder' object has no attribute '_ensure_ready'` (unless
Task 2 already landed on this branch, in which case: FAIL because `build_mcp_server` doesn't pass
`ensure_ready` yet, so `embedder._ensure_ready` is `None`, not
`fake_tei_lifecycle.ensure_tei_running`).

- [ ] **Step 3: Wire it in**

In `app/assembly.py`, find `build_mcp_server` (~line 588-612) and modify the embedder/reranker
construction lines:

```python
    embedder = TeiEmbedder(
        httpx.Client(base_url=_TEI_EMBED_URL, timeout=60.0), gpu_lock, _EMBEDDER_INFO,
        ensure_ready=tei_lifecycle.ensure_tei_running,
    )
    document_store = DocumentStore(db_path, blob_dir)
    vector_index = VectorIndex(
        _QDRANT_HOST, _QDRANT_PORT, collection, _EMBEDDER_INFO.dim, config.hybrid_dense_weight
    )
    reranker = TeiReranker(
        httpx.Client(base_url=_TEI_RERANK_URL, timeout=60.0), gpu_lock,
        ensure_ready=tei_lifecycle.ensure_tei_running,
    )
```

(Everything else in `build_mcp_server` is unchanged — only these two constructor calls gain the
new kwarg.) Confirm `app.assembly` already imports `tei_lifecycle` at module level (it does — used
by `_before_parse_phase` already) — no new import needed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest app/test_assembly.py -v`
Expected: PASS (all tests, including both new ones)

- [ ] **Step 5: Commit**

```bash
git add app/assembly.py app/test_assembly.py
git commit -m "T-DOC78: wire ensure_tei_running as the query-path's readiness hook"
```

---

### Task 4: `app/dashboard/controller.py` — `free_gpu()` / `load_for_mcp()`

**Files:**
- Modify: `app/dashboard/controller.py`
- Test: `app/dashboard/test_controller.py`

**Interfaces:**
- Produces: `controller.free_gpu(data_dir: str | Path, *, stop_tei=tei_lifecycle.stop_tei_containers) -> dict`
  — raises `DoubleRunError` if a full-mode run is `status == "running"`; otherwise calls `stop_tei()`
  and returns `{"tei_stopped": True}`.
- Produces: `controller.load_for_mcp(data_dir: str | Path, *, start_tei=tei_lifecycle.start_tei_containers) -> dict`
  — always allowed, calls `start_tei()`, returns `{"tei_started": True}`.

- [ ] **Step 1: Write the failing tests**

Add to `app/dashboard/test_controller.py`, in a new section near the end of the file (after the
last existing test):

```python
# --- T-DOC78: free_gpu() / load_for_mcp() -- explicit, on-demand TEI eviction/reload -----------


def test_free_gpu_refused_while_a_full_run_is_running(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        calls = []
        with pytest.raises(DoubleRunError):
            controller_mod.free_gpu(tmp_path, stop_tei=lambda: calls.append("stopped"))
        assert calls == [], "must refuse BEFORE calling stop_tei, not race it"
    finally:
        _cleanup(manifest)


def test_free_gpu_allowed_while_a_full_run_is_paused(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        controller_mod.pause(tmp_path)
        calls = []
        result = controller_mod.free_gpu(tmp_path, stop_tei=lambda: calls.append("stopped"))
        assert calls == ["stopped"]
        assert result == {"tei_stopped": True}
    finally:
        _cleanup(controller_mod._read_manifest(tmp_path))


def test_free_gpu_allowed_while_a_download_only_run_is_running(tmp_path):
    """Download-only mode never touches TEI -- freeing the GPU while it's live is always safe."""
    manifest = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
    )
    try:
        calls = []
        result = controller_mod.free_gpu(tmp_path, stop_tei=lambda: calls.append("stopped"))
        assert calls == ["stopped"]
        assert result == {"tei_stopped": True}
    finally:
        _cleanup(manifest)


def test_free_gpu_allowed_with_no_run_at_all(tmp_path):
    calls = []
    result = controller_mod.free_gpu(tmp_path, stop_tei=lambda: calls.append("stopped"))
    assert calls == ["stopped"]
    assert result == {"tei_stopped": True}


def test_load_for_mcp_always_allowed_even_while_a_full_run_is_running(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        calls = []
        result = controller_mod.load_for_mcp(tmp_path, start_tei=lambda: calls.append("started"))
        assert calls == ["started"]
        assert result == {"tei_started": True}
    finally:
        _cleanup(manifest)


def test_load_for_mcp_with_no_run_at_all(tmp_path):
    calls = []
    result = controller_mod.load_for_mcp(tmp_path, start_tei=lambda: calls.append("started"))
    assert calls == ["started"]
    assert result == {"tei_started": True}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/dashboard/test_controller.py -k "free_gpu or load_for_mcp" -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'free_gpu'`.

- [ ] **Step 3: Implement `free_gpu`/`load_for_mcp`**

In `app/dashboard/controller.py`, add the import at the top (alongside the existing
`from contracts.config import Config` / `from rag.config import load_config` lines):

```python
from app import tei_lifecycle
```

Add the two new functions after `retarget` (the last function in the "public control surface"
section, end of file):

```python
def free_gpu(
    data_dir: str | Path, *, stop_tei=tei_lifecycle.stop_tei_containers,
) -> dict:
    """T-DOC78: stops the TEI containers (embedder+reranker, ~9.4GB) on demand -- independent of
    pause/resume/stop, which deliberately leave TEI running (CONVENTIONS.md §6: live MCP search
    stays available except during Pass 1). Refuses while a FULL-mode run is actively `running` --
    freeing TEI out from under an in-flight Pass-2 embed/rerank call would fail real papers'
    retries and wrongly quarantine them. Safe anytime nothing is live, a run is paused/stopped, or
    a download-only run is live/paused (that mode never touches TEI at all)."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        manifest = reconcile(data_dir)
        if (
            manifest is not None
            and manifest.get("status") == "running"
            and manifest.get("mode", "full") == "full"
        ):
            raise DoubleRunError(
                f"run {manifest['run_id']!r} is a full run actively running -- pause or stop it "
                "before freeing the GPU (freeing TEI mid-Pass-2 would fail in-flight embed/rerank "
                "calls and wrongly quarantine real papers)"
            )
        stop_tei()
        return {"tei_stopped": True}


def load_for_mcp(
    data_dir: str | Path, *, start_tei=tei_lifecycle.start_tei_containers,
) -> dict:
    """T-DOC78: starts the TEI containers back up and waits for them to report healthy -- the
    explicit counterpart to `free_gpu`, for restoring live MCP search immediately instead of
    waiting for the next query to pay the reload cost inline (the query path also self-heals on
    its own via `ensure_ready`, `rag/embedder.py`/`rag/reranker.py` -- this is just the eager
    version). Always safe: starting an already-started container is a no-op."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        start_tei()
        return {"tei_started": True}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest app/dashboard/test_controller.py -k "free_gpu or load_for_mcp" -v`
Expected: PASS

- [ ] **Step 5: Run the full controller suite**

Run: `pytest app/dashboard/test_controller.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/dashboard/controller.py app/dashboard/test_controller.py
git commit -m "T-DOC78: add controller.free_gpu()/load_for_mcp() -- on-demand TEI eviction/reload"
```

---

### Task 5: `app/dashboard/status.py` + `server.py` — API wiring + TEI status

**Files:**
- Modify: `app/dashboard/status.py`
- Modify: `app/dashboard/server.py`
- Test: `app/dashboard/test_status.py`
- Test: `app/dashboard/test_server.py`

**Interfaces:**
- Consumes: `controller.free_gpu`/`controller.load_for_mcp` (Task 4).
- Produces: `status.read_tei_status() -> dict` — `{"embed_healthy": bool | None, "rerank_healthy":
  bool | None}` (`None` only on a genuine probe error, e.g. an unexpected exception type — a
  refused/timed-out connection is `False`, a healthy real response is `True`).
- `/api/status` gains a top-level `"tei"` key holding that dict.
- `POST /api/control` gains `"free_gpu"`/`"load_for_mcp"` actions.

- [ ] **Step 1: Write the failing tests**

Add to `app/dashboard/test_status.py`, near the existing `read_consistency` tests (search for
`def test_read_consistency` to find that section and place these after it):

```python
# --- T-DOC78: read_tei_status() -- live TEI health probe (mirrors read_consistency's vector-store
# point-count probe: a live HTTP call, best-effort, never raises) -------------------------------


def test_read_tei_status_reports_healthy_when_both_endpoints_respond_ok(monkeypatch):
    def fake_urlopen(url, timeout=None):
        import io
        return io.BytesIO(b"")  # health endpoints return an empty 200 body, not JSON

    monkeypatch.setattr(status_mod.urllib.request, "urlopen", fake_urlopen)

    result = status_mod.read_tei_status()

    assert result == {"embed_healthy": True, "rerank_healthy": True}


def test_read_tei_status_reports_unhealthy_on_connection_error(monkeypatch):
    def fake_urlopen(url, timeout=None):
        raise status_mod.urllib.error.URLError("connection refused")

    monkeypatch.setattr(status_mod.urllib.request, "urlopen", fake_urlopen)

    result = status_mod.read_tei_status()

    assert result == {"embed_healthy": False, "rerank_healthy": False}


def test_read_tei_status_checks_each_endpoint_independently(monkeypatch):
    """One up, one down -- must report each independently, not collapse to a single verdict."""
    def fake_urlopen(url, timeout=None):
        import io
        if "8080" in url:
            return io.BytesIO(b"")
        raise status_mod.urllib.error.URLError("connection refused")

    monkeypatch.setattr(status_mod.urllib.request, "urlopen", fake_urlopen)

    result = status_mod.read_tei_status()

    assert result == {"embed_healthy": True, "rerank_healthy": False}
```

(`status_mod` is this test file's existing import alias for `app.dashboard.status` — reuse it, do
not add a second import under a different name.)

Add to `app/dashboard/test_server.py`. First extend `_FakeStatus` (around line 36-65) with the new
method:

```python
    def read_tei_status(self):
        return {"embed_healthy": True, "rerank_healthy": True}
```

Extend `_FakeController` (around line 68-98) with the two new methods:

```python
    def free_gpu(self, data_dir):
        self.calls.append(("free_gpu",))

    def load_for_mcp(self, data_dir):
        self.calls.append(("load_for_mcp",))
```

Then add the new tests (near the existing `test_control_pause_dispatches_and_returns_ok`):

```python
def test_control_free_gpu_dispatches(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "free_gpu"})
    assert status == 200
    assert body["ok"] is True
    assert fake_controller.calls[-1] == ("free_gpu",)


def test_control_load_for_mcp_dispatches(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "load_for_mcp"})
    assert status == 200
    assert fake_controller.calls[-1] == ("load_for_mcp",)


def test_control_free_gpu_refused_while_running_returns_409(running_server):
    url, fake_controller = running_server

    def raise_double_run(data_dir):
        raise DoubleRunError("a full run is actively running")

    fake_controller.free_gpu = raise_double_run
    status, body = _post(url, "/api/control", {"action": "free_gpu"})
    assert status == 409
    assert body["ok"] is False


def test_status_route_includes_tei_block(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    assert body["tei"] == {"embed_healthy": True, "rerank_healthy": True}
```

Update the EXISTING `test_status_route_shape_matches_api_contract` (search for
`set(body.keys())`) to add `"tei"` to the expected top-level key set:

```python
    assert set(body.keys()) == {
        "funnel", "run", "telemetry", "downloads", "downloader", "disk", "consistency",
        "quarantine_reasons", "search", "tei",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/dashboard/test_status.py -k tei -v` (no conda env needed for this file)
Run (needs `agent-rag-research` conda env — `source /home/omar/miniconda3/etc/profile.d/conda.sh
&& conda activate agent-rag-research` first): `pytest app/dashboard/test_server.py -k "free_gpu or
load_for_mcp or tei_block or shape_matches_api_contract" -v`
Expected: FAIL — `AttributeError: module 'app.dashboard.status' has no attribute 'read_tei_status'`
(status.py); `KeyError: "unknown action 'free_gpu'"` (server.py).

- [ ] **Step 3: Implement `read_tei_status`**

In `app/dashboard/status.py`, add near `_query_vector_store_point_count` (after it, since it's the
same "live, best-effort, stdlib urllib" pattern):

```python
# T-DOC78: same host/port app/tei_lifecycle.py already uses for its own health poll -- duplicated
# rather than imported (this module's own "own your own copies" convention, e.g. _PREFETCH_PID_NAME
# above), and deliberately stdlib urllib rather than httpx, matching this module's existing
# vendor-neutral live-probe style (_query_vector_store_point_count above).
_TEI_EMBED_HEALTH_URL = "http://localhost:8080/health"
_TEI_RERANK_HEALTH_URL = "http://localhost:8082/health"


def read_tei_status() -> dict:
    """Live health probe for both TEI containers -- `{"embed_healthy": bool, "rerank_healthy":
    bool}`. Each endpoint checked independently (one can be up while the other isn't). Best-effort:
    a connection failure/timeout means `False` (not healthy), never raises."""
    return {
        "embed_healthy": _probe_tei_health(_TEI_EMBED_HEALTH_URL),
        "rerank_healthy": _probe_tei_health(_TEI_RERANK_HEALTH_URL),
    }


def _probe_tei_health(url: str) -> bool:
    # A non-2xx response makes urlopen() itself raise urllib.error.HTTPError (a URLError
    # subclass) rather than returning -- so simply not raising already means "healthy", no
    # `.status` check needed (same pattern _query_vector_store_point_count above relies on
    # implicitly by only ever reading the body on the non-raising path).
    try:
        with urllib.request.urlopen(url, timeout=3.0):
            return True
    except (urllib.error.URLError, OSError):
        return False
```

- [ ] **Step 4: Wire the API actions and status field**

In `app/dashboard/server.py`, find `_dispatch` (search for `elif action == "stop":`) and add the
two new branches right before the `else: raise KeyError(...)` line:

```python
            elif action == "free_gpu":
                controller_module.free_gpu(data_dir)
            elif action == "load_for_mcp":
                controller_module.load_for_mcp(data_dir)
            else:
                raise KeyError(f"unknown action {action!r}")
```

Find `_status_dict` (search for `def _status_dict`) and add `"tei"` to the returned dict, right
after `"search": {...}`:

```python
        "search": {
            **_search_display(),
            "hybrid_dense_weight": _STATIC_CONFIG.hybrid_dense_weight,
        },
        "tei": status_module.read_tei_status(),
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest app/dashboard/test_status.py -v` (no conda env needed)
Run (conda env activated): `pytest app/dashboard/ -v`
Expected: PASS (both, full dashboard suite)

- [ ] **Step 6: Commit**

```bash
git add app/dashboard/status.py app/dashboard/server.py app/dashboard/test_status.py app/dashboard/test_server.py
git commit -m "T-DOC78: wire free_gpu/load_for_mcp API actions; expose live tei status"
```

---

### Task 6: Frontend — "Free GPU" / "Load for MCP" buttons + status display

**Files:**
- Modify: `app/dashboard/static/index.html`
- Test: `app/dashboard/test_server.py`

**Interfaces:**
- Consumes: `POST /api/control {"action": "free_gpu" | "load_for_mcp"}` (Task 5),
  `snap.tei.embed_healthy`/`snap.tei.rerank_healthy` (Task 5).

- [ ] **Step 1: Write the failing tests**

Add to `app/dashboard/test_server.py`, near the existing `test_root_html_has_download_now_button_wired_to_the_download_action`:

```python
def test_root_html_has_free_gpu_and_load_for_mcp_buttons(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b'id="btnFreeGpu"' in body
    assert b'"free_gpu"' in body
    assert b'id="btnLoadForMcp"' in body
    assert b'"load_for_mcp"' in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run (conda env activated): `pytest app/dashboard/test_server.py -k free_gpu_and_load_for_mcp_buttons -v`
Expected: FAIL — neither string exists in `index.html` yet.

- [ ] **Step 3: Add the buttons and status display**

In `app/dashboard/static/index.html`, find the `<h2>Downloads</h2>` panel (search for
`<h2>Downloads</h2>` — the existing panel showing `#cachedPdfs`/`#prefetchAlive`/`#prefetchPace`).
Add a new row inside that SAME panel, right before its closing `</div>`:

```html
    <div class="row"><span class="stat-label">TEI embed</span><span id="teiEmbedHealthy">-</span></div>
    <div class="row"><span class="stat-label">TEI rerank</span><span id="teiRerankHealthy">-</span></div>
    <div class="controls" style="margin-top: .5rem;">
      <button id="btnFreeGpu" class="secondary" type="button">Free GPU</button>
      <button id="btnLoadForMcp" class="secondary" type="button">Load for MCP</button>
    </div>
    <span class="note" style="margin:0;">Free GPU stops the TEI embedder/reranker containers (~9.4GB VRAM) on demand -- independent of Pause/Resume/Stop, which deliberately leave them running for live search. Refused while a full run is actively running. Live search self-heals on its own on the next query either way; Load for MCP just restores it immediately instead of waiting.</span>
```

- [ ] **Step 4: Wire the buttons and render the status**

In the `<script>` block, find `render()`'s section that sets `#prefetchAlive`/`#prefetchPace`
(search for `document.getElementById("prefetchAlive")`). Add right after those two lines:

```js
  const tei = snap.tei || {};
  document.getElementById("teiEmbedHealthy").textContent =
    tei.embed_healthy === null || tei.embed_healthy === undefined ? "-" : (tei.embed_healthy ? "up" : "down");
  document.getElementById("teiRerankHealthy").textContent =
    tei.rerank_healthy === null || tei.rerank_healthy === undefined ? "-" : (tei.rerank_healthy ? "up" : "down");
```

Find the end of the `<script>` block, right before `poll();` (same insertion point Task 4 of the
prior download-only-control plan used for `btnDownloadOnly` — if that button's wiring is present,
add this right after it; otherwise right before `poll();`):

```js
document.getElementById("btnFreeGpu").addEventListener("click", () => control("free_gpu"));
document.getElementById("btnLoadForMcp").addEventListener("click", () => control("load_for_mcp"));
```

- [ ] **Step 5: Run the test to verify it passes**

Run (conda env activated): `pytest app/dashboard/test_server.py -k free_gpu_and_load_for_mcp_buttons -v`
Expected: PASS

- [ ] **Step 6: Run the full dashboard suite**

Run (conda env activated): `pytest app/dashboard/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/dashboard/static/index.html app/dashboard/test_server.py
git commit -m "T-DOC78: dashboard Free GPU / Load for MCP buttons + live TEI status"
```

---

---

### Task 7: Final-review fixes — CI allowlist, Pass-1 OOM guard, `_LIVE_STATUSES`

*Added after the final whole-branch review. The review found: (1) a Critical CI failure — the
mechanical vendor-isolation check (`ci/checks/vendor_isolation.py`, the same one that broke PR #170
on an unrelated "MinerU" docstring) flags 16 new `httpx`-token occurrences this plan introduced in
`app/tei_lifecycle.py`/`app/test_tei_lifecycle.py`/`app/assembly.py` (files not in that rule's
`allowed_paths`) plus one false-positive in a `status.py` comment; (2) an Important safety gap —
`ensure_ready` (Task 2/3) can now reload TEI's ~9.4GB mid-Pass-1, when the documented safety margin
against MinerU's peak VRAM is only ~1GB (the exact condition a prior real CUDA OOM happened under,
ARCHITECTURE.md/CONVENTIONS.md §6) — owner decision: add a real guard, not just documentation;
(3) a related latency concern — the query path's `ensure_ready` inherits a 60s health-poll timeout
sized for a phase transition, meaning a query with TEI genuinely unreachable blocks up to a full
minute; (4) a Minor — `free_gpu`'s liveness guard checks `status == "running"` but the live-status
set is `_LIVE_STATUSES = ("running", "pausing", "stopping")`, so a full run that's mid-escalation
(SIGTERM sent, not yet confirmed dead) isn't guarded.*

**Files:**
- Modify: `ci/checks/vendor_isolation.py` (the `httpx` `VendorRule`'s `allowed_paths`)
- Modify: `app/dashboard/status.py` (one comment, no code change)
- Modify: `app/tei_lifecycle.py` (new `pass1_is_active`; `ensure_tei_running`/`start_tei_containers`
  gain optional params)
- Modify: `app/ingest.py` (new `.pass1.lock`, held for Pass 1's exact duration)
- Modify: `app/assembly.py` (`build_mcp_server`'s hook wiring)
- Modify: `app/dashboard/controller.py` (`free_gpu`'s guard condition)
- Test: `app/test_tei_lifecycle.py`, `app/test_ingest.py`, `app/test_assembly.py`,
  `app/dashboard/test_controller.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6 (this task modifies several of their signatures).
- Produces: `tei_lifecycle.pass1_is_active(lock_path: Path) -> bool`;
  `ensure_tei_running(client=None, *, lock_path: Path | None = None, poll_timeout_s: float | None =
  None) -> None`; `start_tei_containers(client=None, *, poll_timeout_s: float | None = None) ->
  None`; `app.ingest._pass1_lock_path(cfg: Config) -> Path`.

- [ ] **Step 1: Fix the CI vendor-isolation allowlist**

In `ci/checks/vendor_isolation.py`, find the `httpx` `VendorRule` (search for `"httpx"`) and add
three paths to its `allowed_paths` tuple:

```python
    VendorRule(
        "httpx",
        re.compile(r"httpx", re.I),
        (
            "rag/harvester.py",
            "rag/test_harvester_arxiv_source.py",
            "rag/embedder.py",
            "rag/test_embedder.py",
            "rag/summarizer.py",
            "rag/test_summarizer.py",
            "rag/parser.py",
            "rag/reranker.py",
            "rag/test_reranker.py",
            "app/test_prefetch_pdfs.py",
            "rag/contextual_header.py",
            "rag/test_contextual_header.py",
            "app/reembed_experiment.py",
            "app/tei_lifecycle.py",
            "app/test_tei_lifecycle.py",
            "app/assembly.py",
        ),
    ),
```

(Only the three new entries at the end are added — every existing path stays exactly as-is, same
order.) Add one line to the comment block directly above `VENDOR_RULES` (search for "T-DOC41
(Contextual Retrieval spike)" to find the end of the existing httpx-rule comment) explaining the
addition:

```python
    # T-DOC78: app/tei_lifecycle.py talks to the TEI containers' health endpoints over the same
    # httpx client; app/test_tei_lifecycle.py exercises it offline via httpx.MockTransport, same
    # pattern as every other adapter test above. app/assembly.py is this rule's composition root
    # (already allowlisted implicitly by not being scanned before -- now explicit since its
    # TeiEmbedder/TeiReranker construction lines were reformatted by an unrelated diff and now
    # register as "added" lines containing "httpx").
```

In `app/dashboard/status.py`, find the comment at the `_TEI_EMBED_HEALTH_URL`/`_TEI_RERANK_HEALTH_URL`
constants (search for `"deliberately stdlib urllib rather than httpx"`) and reword it to avoid the
literal substring "httpx" (this file doesn't use it at all — the mechanical check has no way to
know a comment is explaining an ABSENCE, not a usage):

```python
# T-DOC78: same host/port app/tei_lifecycle.py already uses for its own health poll -- duplicated
# rather than imported (this module's own "own your own copies" convention, e.g. _PREFETCH_PID_NAME
# above), and deliberately stdlib urllib, not a third-party HTTP client library, matching this
# module's existing vendor-neutral live-probe style (_query_vector_store_point_count above).
```

Run `python -m ci.run_enforcement` (or, if that needs a specific diff-range env var locally, check
`ci/run_enforcement.py`'s own `__main__` for how to invoke it against the working tree — e.g.
`GITHUB_EVENT_NAME=push python -m ci.run_enforcement` matches what a prior session used
successfully for this exact check) and confirm it now reports zero violations for check (a) on this
branch's diff. If you genuinely cannot get it to run locally in a way that matches CI's diff range,
fall back to a case-insensitive grep for "httpx" across every file this whole plan touched (`git
diff --name-only $(git merge-base main HEAD) HEAD`) and confirm every hit is in an allowlisted path.

- [ ] **Step 2: `app/tei_lifecycle.py` — `pass1_is_active` + threaded `poll_timeout_s`**

Add near the top of `app/tei_lifecycle.py`, after the existing imports:

```python
from pathlib import Path

import filelock
```

Add `pass1_is_active` after `ensure_tei_running` (before `_is_healthy`):

```python
def pass1_is_active(lock_path: Path) -> bool:
    """Non-blocking check: True iff `app.ingest` currently holds the Pass-1 lock at `lock_path`
    (`app.ingest._pass1_lock_path`) -- i.e. MinerU is actively parsing right now. A zero-timeout
    acquire attempt: succeeds (and is immediately released) when Pass 1 is NOT running, times out
    when it is. Best-effort like every other function in this module: a missing lock FILE (no
    ingest has ever run yet) is treated as "not active" -- the lock can still be acquired -- never
    an error."""
    lock = filelock.FileLock(str(lock_path))
    try:
        lock.acquire(timeout=0)
    except filelock.Timeout:
        return True
    lock.release()
    return False
```

Modify `ensure_tei_running`'s signature and body:

```python
def ensure_tei_running(
    client: httpx.Client | None = None, *,
    lock_path: Path | None = None, poll_timeout_s: float | None = None,
) -> None:
    """Best-effort, never raises (same contract as `stop_tei_containers`/`start_tei_containers`).
    If both containers are ALREADY healthy, this is two fast `GET /health` calls and nothing else
    -- no `docker` command. Otherwise falls through to `start_tei_containers` (docker start + the
    same bounded health poll that function already does).

    `client` is injectable for tests, same as `start_tei_containers`. When `None`, builds one
    short-lived `httpx.Client` and reuses it for both the health check here and (if needed) the
    poll inside `start_tei_containers`, rather than constructing two.

    T-DOC78: `lock_path` (default `None` -- existing callers unaffected), when given, is checked
    FIRST via `pass1_is_active` -- if Pass 1 is actively running, this returns immediately WITHOUT
    reloading TEI, even if unhealthy: reloading ~9.4GB mid-Pass-1 risks the exact CUDA OOM TEI
    eviction exists to prevent (ARCHITECTURE.md/CONVENTIONS.md Sec 6 -- Pass 1's real safety margin
    against MinerU's peak is ~1GB). The caller's subsequent real HTTP call fails exactly as
    documented ("a live MCP query during Pass 1 fails outright, not delayed") instead of silently
    reintroducing the OOM risk.

    `poll_timeout_s` (default `None` -- falls back to `start_tei_containers`'s own
    `_TEI_START_POLL_TIMEOUT_SECONDS`): overrides the health-poll deadline forwarded to
    `start_tei_containers` on the fallthrough path -- the query path uses a much shorter one (see
    `app/assembly.py::build_mcp_server`) so a query with TEI genuinely unreachable fails in seconds,
    not up to a full minute; phase-transition callers (Pass 2's own explicit `start_tei_containers()`
    call) keep the original, more patient default by never passing this."""
    if lock_path is not None and pass1_is_active(lock_path):
        return

    if client is None:
        client = httpx.Client(timeout=5.0)

    urls = (_TEI_EMBED_HEALTH_URL, _TEI_RERANK_HEALTH_URL)
    if all(_is_healthy(client, url) for url in urls):
        return

    start_tei_containers(client=client, poll_timeout_s=poll_timeout_s)
```

Modify `start_tei_containers`'s signature and its poll loop (everything else in the function is
unchanged):

```python
def start_tei_containers(
    client: httpx.Client | None = None, *, poll_timeout_s: float | None = None,
) -> None:
    """... (keep the existing docstring, add this paragraph at the end) ...

    `poll_timeout_s` (default `None`): overrides `_TEI_START_POLL_TIMEOUT_SECONDS` for this call
    only (T-DOC78) -- lets `ensure_tei_running`'s query-path caller use a shorter deadline than the
    phase-transition default, without changing that default for every other caller."""
    try:
        subprocess.run(["docker", "start", *_TEI_CONTAINERS], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        logger.warning(
            "could not start TEI containers %s -- best-effort, not blocking the caller's phase "
            "transition: %s",
            _TEI_CONTAINERS,
            error,
        )

    if client is None:
        client = httpx.Client(timeout=5.0)

    timeout_s = poll_timeout_s if poll_timeout_s is not None else _TEI_START_POLL_TIMEOUT_SECONDS
    urls = (_TEI_EMBED_HEALTH_URL, _TEI_RERANK_HEALTH_URL)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if all(_is_healthy(client, url) for url in urls):
            return
        time.sleep(_TEI_START_POLL_INTERVAL_SECONDS)

    logger.warning(
        "could not confirm TEI containers %s were healthy within %.1fs -- proceeding anyway "
        "(best-effort; caller's phase transition is not blocked)",
        _TEI_CONTAINERS,
        timeout_s,
    )
```

(This changes two lines inside the existing poll loop: `deadline = time.monotonic() +
_TEI_START_POLL_TIMEOUT_SECONDS` becomes `... + timeout_s`, and the final warning's `%.1fs` arg
`_TEI_START_POLL_TIMEOUT_SECONDS` becomes `timeout_s` — every existing test that doesn't pass
`poll_timeout_s` still exercises the exact same `_TEI_START_POLL_TIMEOUT_SECONDS`-driven behavior,
since `timeout_s` resolves to that same module constant when `poll_timeout_s` is `None`.)

Add tests to `app/test_tei_lifecycle.py`:

```python
# ---------------------------------------------------------------------------
# pass1_is_active() / T-DOC78 Pass-1 guard
# ---------------------------------------------------------------------------


def test_pass1_is_active_false_when_lock_is_free(tmp_path):
    from app.tei_lifecycle import pass1_is_active

    assert pass1_is_active(tmp_path / ".pass1.lock") is False


def test_pass1_is_active_true_when_lock_is_held(tmp_path):
    from app.tei_lifecycle import pass1_is_active

    lock_path = tmp_path / ".pass1.lock"
    holder = filelock.FileLock(str(lock_path))
    holder.acquire()
    try:
        assert pass1_is_active(lock_path) is True
    finally:
        holder.release()


def test_pass1_is_active_releases_its_own_probe_lock(tmp_path):
    """A probe that finds the lock free must not itself leave it held -- two consecutive checks
    must both see it as free."""
    from app.tei_lifecycle import pass1_is_active

    lock_path = tmp_path / ".pass1.lock"
    assert pass1_is_active(lock_path) is False
    assert pass1_is_active(lock_path) is False  # would be True if the first check leaked the lock


def test_ensure_tei_running_skips_reload_when_pass1_is_active(monkeypatch, tmp_path):
    """The whole point of the guard: even with TEI unhealthy, must NOT call docker start while
    Pass 1 holds the lock -- reloading ~9.4GB mid-Pass-1 risks the OOM eviction exists to prevent."""
    docker_calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kwargs: docker_calls.append((args, kwargs))
    )

    lock_path = tmp_path / ".pass1.lock"
    holder = filelock.FileLock(str(lock_path))
    holder.acquire()
    try:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)  # unhealthy -- would normally trigger a reload

        client = httpx.Client(transport=httpx.MockTransport(handler))

        from app.tei_lifecycle import ensure_tei_running

        ensure_tei_running(client=client, lock_path=lock_path)

        assert docker_calls == [], "must never reload TEI while Pass 1 is active, even if unhealthy"
    finally:
        holder.release()


def test_ensure_tei_running_reloads_normally_once_pass1_is_no_longer_active(monkeypatch, tmp_path):
    """Sanity check: the guard is specific to an ACTIVELY held lock, not to lock_path merely being
    set -- once Pass 1 finishes (lock released), reload behaves exactly as it did before this
    guard existed."""
    docker_calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kwargs: docker_calls.append((args, kwargs))
    )
    lock_path = tmp_path / ".pass1.lock"  # never acquired -- Pass 1 is not active

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    from app.tei_lifecycle import ensure_tei_running

    ensure_tei_running(client=client, lock_path=lock_path)

    assert docker_calls == [], "already-healthy must still skip docker start regardless of lock_path"


def test_start_tei_containers_poll_timeout_s_overrides_the_module_default(monkeypatch):
    """A caller-supplied poll_timeout_s must actually change the deadline, not just be ignored."""
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: None)
    monkeypatch.setattr(_mod, "_TEI_START_POLL_INTERVAL_SECONDS", 0.01)
    # Module default left large/unmonkeypatched -- if poll_timeout_s were ignored, this test would
    # hang for the module default's full duration instead of the short override below.
    monkeypatch.setattr(_mod, "_TEI_START_POLL_TIMEOUT_SECONDS", 30.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)  # never healthy -- forces the loop to run until ITS OWN timeout

    client = httpx.Client(transport=httpx.MockTransport(handler))

    start_tei_containers(client=client, poll_timeout_s=0.05)  # must return quickly, not after 30s
```

You will need `import subprocess` and `import filelock` already present or added at the top of
`app/test_tei_lifecycle.py` (check what's already imported — `subprocess`/`httpx`/`pytest` are;
`filelock` likely needs adding).

- [ ] **Step 3: `app/ingest.py` — hold `.pass1.lock` for Pass 1's exact duration**

Add near the other lock-name constant (search for `_INGEST_LOCK_NAME`):

```python
# T-DOC78: marks "Pass 1 (MinerU) is actively running" for the query path's self-healing hook
# (app/assembly.py::build_mcp_server's ensure_ready, via app/tei_lifecycle.py's pass1_is_active) to
# check before reloading TEI mid-Pass-1 -- see ensure_tei_running's own docstring for the OOM risk
# this exists to prevent. A DIFFERENT lock than _INGEST_LOCK_NAME: that one guards against two
# concurrent app.ingest runs; this one just marks "Pass 1 specifically is in flight right now,"
# checked from a completely different process (a live MCP query, possibly app.serve.py).
_PASS1_LOCK_NAME = ".pass1.lock"
```

Add a helper near `_ingest_lock_path` (same resolution convention — absolute against `db_path`'s
own directory, not cwd):

```python
def _pass1_lock_path(cfg: Config) -> Path:
    return Path(cfg.db_path).resolve().parent / _PASS1_LOCK_NAME
```

In `__main__`, find the block:

```python
            run.stage_start("parse")
            _run_parse_phase_subprocesses(args.parse_workers, cwd=subprocess_cwd)
            run.stage_end("parse")
```

Replace it with (same indentation level, still inside the existing outer `try` this block already
sits in):

```python
            _pass1_lock = filelock.FileLock(str(_pass1_lock_path(cfg)))
            _pass1_lock.acquire()
            try:
                run.stage_start("parse")
                _run_parse_phase_subprocesses(args.parse_workers, cwd=subprocess_cwd)
                run.stage_end("parse")
            finally:
                _pass1_lock.release()
```

(The lock is scoped to ONLY this block — acquired right before `stage_start("parse")`, released in
a `finally` right after `stage_end("parse")` or on any exception `_run_parse_phase_subprocesses`
raises, so it's never held during Pass 2 or during any preflight/setup work. `filelock` is already
imported in this file.)

Add a test to `app/test_ingest.py`. First find how existing tests in that file drive
`_run_parse_phase_subprocesses`/the `__main__` flow (search for existing tests that monkeypatch
`subprocess.run` or call into the module's `__main__`-adjacent functions) and match that pattern.
If `__main__` itself isn't easily testable in isolation in this file's existing style, instead add
a focused unit test directly on the new pieces:

```python
def test_pass1_lock_path_resolves_absolute_against_db_path_directory(tmp_path):
    from app.ingest import _pass1_lock_path
    from contracts.config import Config

    cfg = Config(
        focus_area_queries=["x"], db_path=str(tmp_path / "sub" / "papers.db"),
        gpu_lock_path=str(tmp_path / ".gpu.lock"),
    )

    result = _pass1_lock_path(cfg)

    assert result == (tmp_path / "sub").resolve() / ".pass1.lock"
```

(This proves the path-resolution helper is correct in isolation; the acquire/release-around-Pass-1
wiring itself is exercised end-to-end by Task 7's own `test_ensure_tei_running_skips_reload_when_pass1_is_active`
test in `app/test_tei_lifecycle.py`, which directly proves the CONSUMER side of the contract — a
held lock at this path blocks reload — without needing a real Pass-1 subprocess in this test.)

- [ ] **Step 4: `app/assembly.py` — wire the guard into the query path**

Find `build_mcp_server` (the function Task 3 already modified) and change the embedder/reranker
construction to route through a local closure instead of the bare `tei_lifecycle.ensure_tei_running`
reference (same pattern `build_ingestion_orchestrator`'s own `_before_parse_phase` already uses — a
local function closing over this call's own config):

```python
def build_mcp_server(
    config: Config, *, db_path: str | None = None, blob_dir: str | None = None,
    collection: str = "papers",
) -> McpServer:
    gpu_lock = FileGpuLock(Path(config.gpu_lock_path))  # same path as the ingest root -> same file
    db_path, blob_dir = _resolve_store_paths(config, db_path, blob_dir)

    # T-DOC78: the query path's readiness hook must refuse to reload TEI while Pass 1 is actively
    # running (app/tei_lifecycle.py's ensure_tei_running docstring explains the OOM risk) and
    # should fail fast rather than block up to a minute -- both need config-derived state
    # (db_path, for the same Pass-1 lock app/ingest.py writes) this composition root has and
    # tei_lifecycle.py itself does not, so this is a local closure, same pattern
    # build_ingestion_orchestrator's own _before_parse_phase hook already uses.
    _pass1_lock_path = Path(config.db_path).resolve().parent / ".pass1.lock"
    _QUERY_PATH_TEI_POLL_TIMEOUT_S = 15.0

    def _ensure_query_tei_ready() -> None:
        tei_lifecycle.ensure_tei_running(
            lock_path=_pass1_lock_path, poll_timeout_s=_QUERY_PATH_TEI_POLL_TIMEOUT_S,
        )

    embedder = TeiEmbedder(
        httpx.Client(base_url=_TEI_EMBED_URL, timeout=60.0), gpu_lock, _EMBEDDER_INFO,
        ensure_ready=_ensure_query_tei_ready,
    )
    document_store = DocumentStore(db_path, blob_dir)
    vector_index = VectorIndex(
        _QDRANT_HOST, _QDRANT_PORT, collection, _EMBEDDER_INFO.dim, config.hybrid_dense_weight
    )
    reranker = TeiReranker(
        httpx.Client(base_url=_TEI_RERANK_URL, timeout=60.0), gpu_lock,
        ensure_ready=_ensure_query_tei_ready,
    )
    rerank_pool_size = min(config.rerank_depth, _RERANKER_MAX_BATCH_SIZE)
    retriever = Retriever(embedder, vector_index, document_store, reranker, rerank_pool_size)

    return McpServer(retriever, document_store, default_k=config.top_k)
```

(Everything else in the function — the `rerank_pool_size` comment block, `DocumentStore`/
`VectorIndex` construction, the final `Retriever`/`McpServer` lines — is unchanged; only the
embedder/reranker construction and the new closure above them change.)

Update the EXISTING test `test_build_mcp_server_wires_ensure_ready_into_embedder_and_reranker` in
`app/test_assembly.py` — its current `==` bound-method comparison (`embedder._ensure_ready ==
fake_tei_lifecycle.ensure_tei_running`) no longer holds, since `_ensure_ready` is now a fresh local
closure, not `tei_lifecycle.ensure_tei_running` itself. Replace the test body with a behavior-based
check, and extend `_FakeTeiLifecycle` (in the same file, search for `class _FakeTeiLifecycle`) to
accept and record the new kwargs:

```python
class _FakeTeiLifecycle:
    def __init__(self):
        self.stop_calls = 0
        self.start_calls = 0
        self.ensure_calls = 0
        self.ensure_kwargs = None

    def stop_tei_containers(self) -> None:
        self.stop_calls += 1

    def start_tei_containers(self) -> None:
        self.start_calls += 1

    def ensure_tei_running(self, **kwargs) -> None:
        self.ensure_calls += 1
        self.ensure_kwargs = kwargs
```

```python
def test_build_mcp_server_wires_ensure_ready_into_embedder_and_reranker(monkeypatch, tmp_path):
    """T-DOC78: the query-path composition (unlike build_ingestion_orchestrator) wires a readiness
    hook that calls tei_lifecycle.ensure_tei_running with this run's own Pass-1 lock path and a
    short query-path poll timeout, so a query right after TEI gets evicted (Free GPU, or Pass 1)
    self-heals instead of erroring -- and refuses to do so while Pass 1 is actually active."""
    fake_tei_lifecycle = _FakeTeiLifecycle()
    monkeypatch.setattr("app.assembly.tei_lifecycle", fake_tei_lifecycle)
    monkeypatch.setattr("app.assembly.VectorIndex", lambda *a, **k: object())

    db_path = str(tmp_path / "papers.db")
    cfg = Config(
        focus_area_queries=["causal inference"], gpu_lock_path=str(tmp_path / ".gpu.lock"),
        db_path=db_path,
    )
    server = build_mcp_server(cfg, db_path=db_path, blob_dir=str(tmp_path / "blobs"), collection="papers")

    embedder = server._retriever._embedder
    reranker = server._retriever._reranker

    embedder._ensure_ready()
    reranker._ensure_ready()

    assert fake_tei_lifecycle.ensure_calls == 2
    assert fake_tei_lifecycle.ensure_kwargs == {
        "lock_path": Path(db_path).resolve().parent / ".pass1.lock",
        "poll_timeout_s": 15.0,
    }
```

(`db_path` must be passed to BOTH `Config(...)` and `build_mcp_server(...)` as the same value here
-- the closure derives the lock path from `config.db_path`, so the test's expected path must be
derived the same way, not from `tmp_path / "papers.db"` typed out separately, which could silently
diverge from what `Config`'s own default/validation does to the value.)

- [ ] **Step 5: `app/dashboard/controller.py` — `free_gpu`'s guard uses `_LIVE_STATUSES`**

Find `free_gpu` (added by Task 4) and change one condition:

```python
        if (
            manifest is not None
            and manifest.get("status") in _LIVE_STATUSES
            and manifest.get("mode", "full") == "full"
        ):
```

(Was `manifest.get("status") == "running"` — now matches the same `_LIVE_STATUSES = ("running",
"pausing", "stopping")` tuple already defined earlier in this file and already used by
`_start_locked`'s own double-run guard, so a full run that's mid-SIGTERM-escalation, not yet
confirmed dead, is guarded too.) Update the docstring's second sentence to say "actively running or
mid-pause/stop" instead of just "running".

Add a test to `app/dashboard/test_controller.py` near the existing `free_gpu` tests:

```python
def test_free_gpu_refused_while_a_full_run_is_pausing_not_yet_confirmed_dead(tmp_path, monkeypatch):
    """SIGTERM sent (status: "pausing") but the process hasn't confirmed dead yet -- still
    potentially mid-Pass-2 embed/rerank, same risk as "running"."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        manifest["status"] = "pausing"
        (tmp_path / "run_manifest.json").write_text(json.dumps(manifest))
        monkeypatch.setattr(controller_mod, "_wait_for_death", lambda pid, timeout_s=None: False)
        calls = []
        with pytest.raises(DoubleRunError):
            controller_mod.free_gpu(tmp_path, stop_tei=lambda: calls.append("stopped"))
        assert calls == []
    finally:
        _cleanup(manifest)
```

(This mirrors the existing `test_resume_refuses_while_pausing_has_not_yet_confirmed_dead` test's
pattern in the same file — reuse that exact style: manually set `status` to `"pausing"` in the
manifest, monkeypatch `_wait_for_death` to keep `reconcile()` from self-healing it away, since the
process really is a `sleep 100` that's still alive and unsignaled in this test.)

- [ ] **Step 6: Run every affected test suite**

Run: `python -m ci.run_enforcement` (or the env-var form from Step 1) — expect zero violations.
Run: `pytest app/test_tei_lifecycle.py app/test_ingest.py app/test_assembly.py -v` — expect all pass.
Run: `pytest app/dashboard/test_controller.py -v` — expect all pass.
Run (conda env activated): `pytest app/dashboard/ -v` and `pytest rag/ -v` — expect all pass (confirm
nothing in Tasks 1-6's already-shipped code broke from this task's signature changes).

- [ ] **Step 7: Commit**

```bash
git add ci/checks/vendor_isolation.py app/dashboard/status.py app/tei_lifecycle.py app/test_tei_lifecycle.py app/ingest.py app/test_ingest.py app/assembly.py app/test_assembly.py app/dashboard/controller.py app/dashboard/test_controller.py
git commit -m "T-DOC78: fix CI vendor-isolation allowlist; guard TEI self-heal against Pass-1 OOM risk"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 = Piece 1 (`ensure_tei_running`); Task 2+3 = Piece 2 (self-healing hook,
  wired into the query path only, per the design's explicit "not `build_ingestion_orchestrator`"
  constraint — Task 3 has a dedicated test proving that); Task 4+5+6 = Piece 3 (dashboard buttons +
  API + status + UI). The design's "What this deliberately does not do" (no Ollama eviction, no
  pause/resume/stop change) has no corresponding task by design — nothing to build.
- **Placeholder scan:** no TBD/TODO; every step has literal code and literal test bodies.
- **Type consistency:** `ensure_ready: Callable[[], None] | None = None` is identical across
  `TeiEmbedder`/`TeiReranker` (Task 2) and the one thing `app/assembly.py` (Task 3) passes into
  both. `tei_lifecycle.ensure_tei_running`'s signature (`client: httpx.Client | None = None`)
  satisfies `Callable[[], None]` when called with zero args (as `TeiEmbedder`/`TeiReranker` call
  it) — Python allows a function with only-defaulted params to satisfy a zero-arg `Callable` type.
  `free_gpu`/`load_for_mcp`'s injectable `stop_tei`/`start_tei` params (Task 4) match
  `tei_lifecycle.stop_tei_containers`/`start_tei_containers`'s real zero-arg call shape exactly.
  `read_tei_status()`'s return shape (`{"embed_healthy": bool, "rerank_healthy": bool}`, Task 5) is
  used identically by the `/api/status` `"tei"` key (Task 5) and the frontend's `snap.tei.*` reads
  (Task 6).
