# Design — Free/reload GPU (TEI) on demand + self-healing query path

*T-DOC78 follow-up. Root cause (found via systematic-debugging, code-verified): the dashboard's
pause/stop only sends OS signals (SIGTERM/SIGKILL) to the process tree it spawned. That correctly
frees the MinerU parser's VRAM (a real subprocess in that tree — process exit is an OS-level VRAM
release guarantee, already relied on elsewhere in this codebase), but the TEI containers
(`rag-tei-embed`/`rag-tei-reranker`, ~9.4GB combined) are separate, long-lived Docker containers —
not part of that process tree at all. `app/dashboard/controller.py` never references
`tei_lifecycle`/`docker`/`unload` anywhere (confirmed by grep). The only place anything ever stops
them is `app/assembly.py`'s `before_parse_phase` hook, which fires automatically at the start of
Pass 1 (to make room for MinerU) — never on a dashboard pause/stop, and TEI is deliberately left
running afterward so live MCP/semantic-search queries keep working (CONVENTIONS.md §6). So
whatever TEI was doing at the moment of pause/stop just sits there in VRAM indefinitely.*

## What changed from the first proposal

The first framing (wire TEI eviction into pause/resume itself) would have broken live search for
the whole duration of every pause — an invariant CONVENTIONS.md §6 documents as deliberate. Owner
decision: keep pause/resume's behavior exactly as it is today. Add a **separate, explicit "Free
GPU" action** instead, plus make the query path **self-healing** so a query right after freeing
the GPU (or right after Pass 1 evicted it) just works instead of erroring.

## Architecture: three pieces, one shared primitive

`app/tei_lifecycle.py` already has the two primitives this needs
(`stop_tei_containers()`/`start_tei_containers()`, used today only at the Pass-1/Pass-2 boundary).
Nothing new to build there except one small addition — everything else is wiring.

### Piece 1 — `app/tei_lifecycle.py`: `ensure_tei_running()`

```python
def ensure_tei_running(client: httpx.Client | None = None) -> None:
    """Best-effort, never raises (same contract as stop/start_tei_containers). If both containers
    are already healthy, this is two fast health GETs -- no docker call. Otherwise falls through
    to start_tei_containers() (docker start + the same bounded health poll)."""
```

Cheap in the common case (already healthy — just two GETs), only pays the full reload cost when
genuinely down. This is the one new primitive; pieces 2 and 3 are both just callers of it.

### Piece 2 — self-healing query path (the part that matters most)

Both `app/serve.py` (the real MCP server other tools connect to) and the dashboard's own search
box go through one shared composition point: `app/assembly.py::build_mcp_server`. Add a small
injected hook to the real adapters, matching the `before_parse_phase`/`before_embed`/`on_stage`
hook pattern `rag/orchestrator.py` already uses for cross-cutting orchestration concerns — this
isn't a new pattern for this codebase, just the same shape applied to a new hook point:

- `TeiEmbedder.__init__`/`TeiReranker.__init__` gain `ensure_ready: Callable[[], None] | None =
  None` (constructor-injected, default no-op — every existing caller/test unaffected).
- `embed()`/`rerank()` call it once, right after the existing empty-input guard (an empty call
  stays a zero-cost no-op, unchanged), before doing any HTTP work.
- **No new error handling needed anywhere.** `ensure_ready` is best-effort and never raises (same
  contract as `stop_tei_containers`/`start_tei_containers`); if it can't actually bring TEI up
  (docker unavailable, etc.), the subsequent HTTP call fails exactly as it does today and the
  *existing* `TransientError`/`PermanentError` retry classification handles it — this "defines the
  error away" rather than adding a second error path (module-design skill's error-handling
  priority: remove the error before adding a catch for it).
- `rag/embedder.py`/`rag/reranker.py` never name "tei"/"docker" anywhere — the hook is a generic
  `Callable[[], None]`, so the mechanical vendor-isolation CI check (`ci/checks/vendor_isolation.py`,
  the exact check that failed PR #170 once already) stays satisfied by construction, not by
  vigilance. Only `app/assembly.py` (already an allowed `tei_lifecycle` importer) writes the real
  wiring: `TeiEmbedder(..., ensure_ready=tei_lifecycle.ensure_tei_running)`.
- Wired into `build_mcp_server` **only** — not `build_ingestion_orchestrator`. Ingest's own Pass 2
  already guarantees TEI health via an explicit `start_tei_containers()` call before `finish_phase()`
  begins (T-DOC19); adding a per-call health-check hook there too would just be redundant HTTP
  round-trips on every one of thousands of ingest embed calls, for a case that can't occur on that
  path. This is the query path's problem specifically (queries can happen anytime, including right
  after someone clicks "Free GPU").

### Piece 3 — dashboard "Free GPU" / "Load for MCP" buttons

Explicit, on-demand, independent of the run manifest/lifecycle (unlike T-DOC78's earlier
`mode="download"` work, this isn't a "run" — it's a stateless action against the TEI containers):

- `controller.free_gpu(data_dir)` — refuses (`DoubleRunError`, same exception the existing
  double-run guard already raises, same 409 handling `server.py` already has) if a **full-mode**
  run is actively `status == "running"` (not paused/stopped) — freeing TEI out from under an
  in-flight Pass-2 embed/rerank call would fail real papers' retries and wrongly quarantine them.
  Safe anytime nothing is live, a run is paused, or a download-only run is live/paused (download
  mode never touches TEI at all, so no guard needed there). Otherwise calls
  `tei_lifecycle.stop_tei_containers()`.
- `controller.load_for_mcp(data_dir)` — the explicit counterpart, always safe (starting an
  already-started container is a no-op), calls `tei_lifecycle.start_tei_containers()`. Exists so an
  operator can restore live search immediately instead of waiting for the next query to pay the
  reload cost inline via Piece 2's self-healing hook.
- Both serialize under the existing `_control_lock` (same "every control op serialized" convention,
  OG-47#1), for consistency with every other control action — even though neither touches the
  manifest.
- `POST /api/control` gains `"free_gpu"`/`"load_for_mcp"` actions in `_dispatch`.
- `/api/status` gains a small `tei` block (`{"embed_healthy": bool, "rerank_healthy": bool}`, a
  live two-GET health probe in `status.py`, same pattern as the existing live vector-store
  point-count probe in `read_consistency`) — otherwise the two new buttons have no visible effect
  in the dashboard; the operator would have to shell out to `docker ps` to confirm they worked.
- Two new buttons in `index.html`, placed near the existing "Downloads"/downloader status panel
  (the other GPU/container-lifecycle display), showing the new `tei` status block.

## What this deliberately does not do

- No change to pause/resume/stop's existing behavior — CONVENTIONS.md §6's "live serving stays up
  except during Pass 1" invariant is untouched for the normal (non-Free-GPU) case.
- No Ollama/Summarizer eviction wired into "Free GPU" — the Summarizer already self-evicts before
  every embed call during Pass 2 and reloads only transiently for actual summarize calls
  (CONVENTIONS.md §6), so its residency at any given moment is already narrow and already handled
  by the pipeline itself; adding it here would require constructing a real `OllamaSummarizer` +
  Ollama HTTP client inside the dashboard controller, a heavier dependency than this
  "lightweight, network-facing" module currently carries (`controller.py`'s own module docstring
  convention). Flagged, not implemented — revisit if Ollama residency during a "freed" window turns
  out to be a real problem in practice.
- No self-healing hook added to the Summarizer or any ingest-side adapter — scoped to the query
  path only, per Piece 2's own reasoning above.

## Testing

- `app/test_tei_lifecycle.py`: `ensure_tei_running()` — already-healthy short-circuits (no
  `subprocess.run` call), not-healthy falls through to the real `start_tei_containers()` behavior
  (reuse the existing `httpx.MockTransport` pattern already in this file).
- `rag/test_embedder.py`/`rag/test_reranker.py`: `ensure_ready` called exactly once per
  `embed()`/`rerank()` call (not once per sub-batch), never called on the empty-input short-circuit,
  a `None` hook (the default) behaves byte-for-byte like today.
- `app/dashboard/test_controller.py`: `free_gpu` refused while a full-mode run is `running`, allowed
  while paused/stopped/absent/download-mode-running; `load_for_mcp` always allowed.
- `app/dashboard/test_server.py`: `POST /api/control` action wiring, `/api/status`'s new `tei` block
  shape.
- `app/dashboard/static/index.html`: HTML-substring tests matching this repo's existing convention
  (no JS test harness).
