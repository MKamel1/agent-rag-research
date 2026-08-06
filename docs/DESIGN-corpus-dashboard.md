# Design — Corpus Dashboard

> **HISTORICAL** — superseded by the 2026-07-30/31 dashboard specs under docs/superpowers/specs/. Current state: [PROJECT-STATUS.md](PROJECT-STATUS.md).

*A local web dashboard to observe AND control corpus ingestion runs, reachable over Tailscale.
Design proposal 2026-07-17. Deep-module lens: small interfaces over the messy reality of "what is the
run doing." Build target for dispatched agents; principal-design-review in progress.*

## Goal (from the owner)
"Keep track of the run so I don't keep asking." Specifically: track **steps/stages, passes, downloads —
everything**; **pause & resume** a run; **start a fresh run with a new target** (paper count); expose the
**important tuning parameters** with recommended + default values; and **show the keyword search
tags/queries** the papers are being downloaded for. Reachable over **Tailscale** (a private VPN — the
machine already has a Tailscale IP; the dashboard just needs to bind to a network interface, not only
localhost).

## The coordination contract: `run_manifest.json` (the ONE shared secret)
Both the launcher and the dashboard read/write a single JSON file at `<data_dir>/run_manifest.json`.
This is the seam between "a run" and "the dashboard" — neither imports the other. Schema (already
written by the live 3K run):
```json
{
  "run_id": "run-3k-20260717_190419",
  "pid": 2660759,
  "status": "running",              // running | paused | done | failed
  "target": 3000,                    // paper-count goal for this run (the --limit)
  "parse_workers": 3,
  "events_path": ".../ingest_events_3k.jsonl",
  "log_path": ".../ingest_3k.log",
  "db_path": ".../papers.db",
  "collection": "papers",
  "started_at": "2026-07-17T19:04:19",
  "focus_queries": ["causal inference", ...],   // the keyword search tags
  "params": { "parse_workers": 3, "limit": 3000, "telemetry_poll_interval": null }
}
```

## Modules & seams (build these)

### 1. `app/dashboard/status.py` — the Status Reader (deep; one method)
`get_status(data_dir) -> StatusSnapshot`. Hides WHERE each metric lives; callers just get a snapshot.
Reads, read-only:
- **Stage funnel** from `papers.db` `ingest_state`: counts per stage (harvested→parsed→chunked→
  summarized→embedded→stored→**done**) + quarantine count and top reasons (`quarantine` table).
- **Current run** from `run_manifest.json`: run_id, status, target, params, focus_queries, started_at.
- **Live telemetry** from the manifest's `events_path` (tail the JSONL): latest stage, papers/hour,
  wall-clock, and GPU util/VRAM/power (T-DOC47's telemetry already writes these).
- **Downloads** from the prefetch cache: `len(glob pdf_cache/*.pdf)` vs target, sidecar count, and the
  prefetch log tail if present.
- **Consistency**: done-count vs vector-store point count (reuse the telemetry summary's check).
Return a typed `StatusSnapshot` (a dataclass/pydantic). NO writes. Must degrade gracefully (missing
manifest / no events file / DB locked → partial snapshot with nulls, never crash).

### 2. `app/dashboard/controller.py` — the Run Controller (deep; hides subprocess+manifest)
`start(target, parse_workers, **tuning)`, `pause()`, `resume()`, `stop()`, `retarget(new_target)`.
- **start / fresh-run**: writes a new manifest, launches `python -m app.ingest --parse-workers N
  --limit TARGET --events-path ... ` (the SAME invocation the 3K run used — env `PYTHONPATH=<repo>`,
  cwd=`<data_dir>`), records the PID, status=running. **Guard: refuse to start if a run is already
  `running`** (two ingest processes would contend for the GPU + the `.gpu.lock` — never allow it).
- **pause**: `SIGTERM` the manifest PID, set status=paused. Safe by construction — ingestion is
  checkpointed/idempotent (verified this session: SIGKILL-mid-run + resume works), so a paused run
  loses at most the in-flight parse batch, which re-does on resume.
- **resume**: relaunch `app.ingest` with the SAME params (it picks up from `ingest_state` checkpoints),
  update PID, status=running.
- **retarget / fresh run with new target**: stop current (if any) + start with the new `--limit`.
- Detect a naturally-finished/failed run (PID gone) and reconcile manifest status to done/failed.

### 3. `app/dashboard/server.py` — the Web App (FastAPI)
- `GET /api/status` → `StatusSnapshot` JSON (the frontend polls this every ~3–5s).
- `POST /api/control` → `{action: "pause"|"resume"|"stop"|"start", target?, parse_workers?, tuning?}`.
- Serves the single-page frontend (static HTML/JS) at `/`.
- **Binds to `0.0.0.0:<port>`** (default e.g. 8700) so the Tailscale IP can reach it (localhost-only
  would be invisible over Tailscale). Port via `--port` argparse (no env in app/).
- **Auth (flag for reviewer):** the control API can start/kill GPU processes. Tailscale is the network
  boundary, but recommend a simple shared token (`--token`, sent as a header) so a control command
  can't be issued by anything else on the tailnet. At minimum, make `GET /api/status` open but
  `POST /api/control` token-gated.

### 4. Frontend — single self-contained page (`app/dashboard/static/index.html` + inline JS/CSS)
Polls `GET /api/status`, renders:
- **Stage funnel** (harvested→…→done) with live counts + a done/target progress bar.
- **Downloads**: cached PDFs vs target, sidecars, prefetch pace.
- **Pass 1 / Pass 2** indicator (parse vs finish, from the current telemetry stage).
- **Throughput**: papers/hour, wall-clock, ETA to target.
- **GPU**: util %, VRAM, power (from telemetry).
- **Quarantine**: count + top reasons.
- **Keyword search tags**: the `focus_queries` list (what the corpus is being built for) — prominent.
- **Tuning panel** (see below) with current / default / recommended, and **control buttons**:
  Pause, Resume, and "Start fresh run" (with a target-N input + parse-workers selector).
Keep it dependency-free (vanilla JS, inline) — no build step, works over Tailscale as one file.

## Tuning parameters to expose (current / default / recommended)
| Param | Default | Recommended | Note |
|---|---|---|---|
| **target** (`--limit`) | none (=corpus_cap 30000) | set per run | The paper-count goal. |
| **parse_workers** | 1 | **3** | +63% Pass-1 throughput, proven safe (T-DOC51/OG-19). |
| **parse_batch_size** | 4 | 4 | Papers per MinerU batch; smaller = less at-risk per crash. |
| **telemetry_poll_interval** | 5s | 5s | GPU sampling cadence. |
| **focus_queries** (keyword tags) | (config's 33 causal queries) | edit = fresh run | Changing what's harvested requires a fresh run. Display always; edit spawns a new run. |
| **relevance_filter** | off | off | Currently dead code (OG-36) — display-only, note "not yet wired". |
| MINERU_VIRTUAL_VRAM_SIZE (advanced) | auto (24GB→ratio 8) | auto | GPU batch-ratio tier; leave auto unless tuning. |

## Constraints for builders
- **Non-foundation only** (`contracts/`, `rag/config.py`, `config.yaml`, `migrations/`, `rag/fakes/`,
  `fixtures/`, `ci/`, `.github/` are off-limits). New `app/dashboard/` package + tests. If a new HTTP
  dep (FastAPI/uvicorn) trips the vendor-isolation check, that ci/ allowlist edit is foundation → flag,
  don't self-merge. Prefer stdlib `http.server` if it keeps the PR non-foundation and avoids new deps;
  FastAPI is nicer but check the dep/isolation cost first.
- **No `os.environ` in app/** (argparse for `--port`/`--token`/`--data-dir`).
- **Read-only on `papers.db`**; the controller only touches `run_manifest.json` and the subprocess.
- Tests with fakes/temp: status reader against a temp DB + fake manifest/events; controller with a
  fake/echo subprocess (don't launch a real GPU ingest in tests); assert the double-run guard, the
  pause→SIGTERM, the resume relaunch, and a graceful partial snapshot.
- No AI attribution in commits/PRs. Vendor-neutral language.

## Open questions for the principal reviewer
1. **Control-plane safety**: is manifest-PID + signals the right control model, or is a small
   long-lived supervisor process cleaner? (Manifest is simplest and matches the existing resumable-
   ingest design; supervisor adds a moving part.)
2. **Auth**: is a shared `--token` on `POST /api/control` sufficient given Tailscale is the boundary,
   or overkill / underkill?
3. **HTTP framework**: stdlib `http.server` (zero deps, non-foundation-safe) vs FastAPI (nicer, new
   dep + possible ci/ allowlist). Which is the right call for a single-user local dashboard?
4. **Seam check**: are status-reader / controller / server the right three modules, or is there a
   Temporal-Decomposition smell (are we splitting by read→control→serve rather than by information
   hiding)?
