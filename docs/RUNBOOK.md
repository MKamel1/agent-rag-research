# RUNBOOK — bringing the system up after a reboot (T-DOC78)

This is the concrete, mechanical answer to "the machine just rebooted, now what" -- previously this
sequence only existed in chat history: `docker start` four containers by hand, then hand-run a
`nohup python -m app.dashboard.server ... --token $(cat .dashboard_token)`, then manage a PID file
by hand. `AGENTS.md`'s doc-map points here; this file is the actual runbook, not a copy of it.

## Why manual, on-demand startup (not systemd, not `--restart` policies)

Deliberate choice, not an oversight: TEI (the embedder/reranker containers) holds several GB of
VRAM, and this GPU has had OOM trouble before. Pinning that at boot is the wrong default for a
personal, single-operator system that isn't always doing retrieval/ingest work. Nothing in this
repo starts anything automatically at boot -- every bring-up below is a command the operator runs
on purpose, when they actually want the system up.

## Post-reboot bring-up sequence

Run these from the repo root (`/home/omar/ai-projects/research-system-rag`), in this order:

1. **`nvidia-smi` sanity check.** Confirms the NVIDIA driver actually loaded after the reboot
   (a driver-module/on-disk-version mismatch after a driver upgrade without a reboot is a real,
   previously-hit failure mode -- `nvidia-smi` exits nonzero and no CUDA process can start until a
   reboot picks up the matching module). If this fails, reboot again before doing anything else --
   don't chase it as an application bug.

   ```bash
   nvidia-smi
   ```

2. **`python -m app.doctor`.** The single "make the system ready" command (T-DOC43/T-DOC52/
   T-DOC78). Checks disk headroom, GPU/VRAM headroom, that `.gpu.lock` isn't held by a stale
   process, and health-pings every required service -- both TEI containers, the parser's
   reference-resolution service (GROBID), the vector store (Qdrant), and the summarizer's
   model-serving endpoint (Ollama, a host service). Any of the four containerized services that's
   merely *stopped* (the common post-reboot case -- `docker start` was never run) gets one
   automatic recovery attempt (`docker start` + a bounded health poll) before being reported as an
   issue. Prints one of:

   ```bash
   /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.doctor
   ```

   - `doctor: OK -- disk/GPU/lock/all required services healthy.` -- exit 0, proceed to step 3.
   - `doctor: N issue(s) found -- not ready:` followed by one line per unresolved problem -- exit 1.
     Everything it can fix itself (a stopped container), it already tried. What's left named here
     needs a human: e.g. the summarizer's host service isn't running (`ollama serve`, by hand --
     it's intentionally never auto-started, see `app/doctor.py`'s module docstring), or a real
     disk/VRAM shortage.
   - `--no-auto-start`: health-check only, skips every recovery attempt (useful to see the *raw*
     post-reboot state before doctor "fixes" anything).

3. **Start the dashboard.**

   ```bash
   scripts/dashboard.sh start
   ```

   Prints the pid, the URL, and where the control token lives (see below) -- never the token's
   value itself. `scripts/dashboard.sh {start|stop|status}` is the whole interface; see
   "Dashboard start/stop/status" below for what each does and how it avoids the pidfile bug that
   made the old hand-run version error-prone.

That's the whole sequence: `nvidia-smi` → `python -m app.doctor` → `scripts/dashboard.sh start`.

## Reaching the dashboard over Tailscale

The dashboard binds `0.0.0.0` by default (not just `127.0.0.1`) specifically so a Tailscale IP can
reach it -- from a phone or laptop on the tailnet, browse to:

```
http://<this-machine's-tailscale-IP>:8700/
```

(`tailscale ip -4` on this host prints that address.) Tailscale itself is the network boundary --
nothing outside the tailnet can reach this port at all. Within the tailnet, `X-Dashboard-Token`
(below) is what stops any other device on it from issuing `POST /api/control` commands.

## Where the token lives

`app/dashboard/server.py` manages its own token file at `<data-dir>/.dashboard_token` (T-DOC78):

- If the file already exists, it's read as-is and used unchanged -- permissions are never touched.
- If it doesn't exist, one is generated (`secrets.token_hex(16)`) and written at mode `0600`
  (owner read/write only) before its content is ever written, and the server prints *where* it was
  written (never the value) so the operator can retrieve it (`cat <data-dir>/.dashboard_token`).
- Passing `--token <value>` explicitly to `python -m app.dashboard.server` always overrides the
  file, for anyone scripting this.

This also gets the token out of `ps`/`/proc/<pid>/cmdline` in the normal (no explicit `--token`)
path -- previously any other local user could read a live dashboard's control token straight off
the process list.

## Checking service health without starting the dashboard

`python -m app.doctor` (step 2 above) is also the answer to "is everything actually up right now" 
on its own, independent of the dashboard -- it's read-only (beyond its auto-start attempts) and
safe to re-run any time. `--no-auto-start` makes it purely diagnostic.

## Dashboard start/stop/status

```bash
scripts/dashboard.sh start   # no-op (prints "already running") if it's already up
scripts/dashboard.sh stop    # SIGTERM, waits up to 10s, SIGKILL if it hasn't exited by then
scripts/dashboard.sh status  # running/not-running, plus pid + URL if running
```

Config (env vars, all optional -- defaults match this host's real setup):

| Var | Default |
|---|---|
| `DASHBOARD_DATA_DIR` | `<repo-root>/../research-system-rag-data` (this host's real corpus dir) |
| `DASHBOARD_PORT` | `8700` |
| `DASHBOARD_HOST` | `0.0.0.0` |
| `DASHBOARD_PYTHON` | the `agent-rag-research` conda env's python, by absolute path |

The pidfile (`<data-dir>/dashboard.pid`) is written from `$!` (the PID bash itself just assigned
the backgrounded server process) at start time, never rediscovered later via a process-table scan
-- a real bug hit twice during this feature's own development: a naive `pgrep -f "dashboard"` (or
anything similarly loose) also matches this very wrapper script's own invocation, because its path
(`scripts/dashboard.sh`) contains that same substring, and `pgrep -f` matches a regex against each
process's *entire* command line, not just the target program's name. `status`'s fallback path (used
only when the pidfile is missing or stale) anchors on the actual `-m app.dashboard.server` module
invocation instead -- a substring nothing but the real server process's own argv ever contains.

No process supervisor, no restart-on-crash, no boot integration -- see "why manual" above. If the
dashboard dies, `scripts/dashboard.sh status` will say so; `start` again.

## Connecting an MCP client (Claude Code / Claude Desktop) — T-DOC66

`app/serve.py` is the MCP server. It is launched by the MCP client itself (not by hand, not by
`scripts/dashboard.sh`), driven by the client's own MCP server config. The exact command shape
that's actually launched, and every requirement that trips a client-config edit if missed:

```json
{
  "command": "conda",
  "args": ["run", "-n", "agent-rag-research", "--no-capture-output", "python", "-m", "app.serve"],
  "env": { "PYTHONPATH": "/home/omar/ai-projects/research-system-rag" }
}
```

- **`--no-capture-output` is required.** `conda run` buffers/intercepts the child process's stdout
  by default -- MCP's stdio transport is the JSON-RPC protocol itself riding on stdout, so a
  captured/buffered stdout means the client's handshake never arrives and the connection just
  hangs (no error, no timeout message -- it looks identical to a slow start). `--no-capture-output`
  is what makes `conda run` pass the child's stdout straight through, unbuffered.
- **`PYTHONPATH` must include this repo's root.** The client spawns `python -m app.serve` as a bare
  subprocess, not through a shell that's `cd`'d into the repo with its venv/conda env already
  active the way an interactive terminal is -- without `PYTHONPATH` pointing at the repo root,
  `import app...`/`import rag...`/`import contracts...` fail at the top of `app/serve.py` and the
  server never starts.
- **`cwd` matters because `app.serve` (no `--data-dir`) uses plain `load_config()` discovery**
  (T-DOC89 §3: `RAG_CONFIG` env var -> `config.yaml` in the spawned process's cwd -> walk up parent
  directories -> loud error naming every location tried). If the client doesn't set an explicit
  `cwd`, whatever directory the client itself was launched from is what discovery starts from. The
  supported fix is the same T-DOC89 §3 rollout used everywhere else in this repo: a gitignored
  repo-root `config.yaml` symlink (`python -m app.init_config --data-dir <path> --link`, T-DOC65)
  -- discovery's walk-up rung then finds it from any cwd inside this repo, including the repo root
  itself. Setting an explicit `"cwd"` in the client's server config to this repo's root is the
  belt-and-braces alternative if a client's own launch cwd is unpredictable.
- **`RAG_DB_PATH`/`RAG_BLOB_DIR`/`RAG_COLLECTION` env vars do nothing.** `app/serve.py` doesn't read
  the process environment at all (CONVENTIONS.md §3) -- only `RAG_CONFIG` (the config file's own
  location) and `rag/config.py`'s discovery matter. A client config carrying these from before
  T-DOC29 is inert, not wrong-but-working; delete them, or pass `--data-dir <path>` in `args`
  instead if the target corpus isn't reachable via discovery.

**Verifying a deploy before relying on it:** `python -m app.doctor --check-mcp` (T-DOC66) spawns
`python -m app.serve` for real and confirms it answers `list_tools` -- the automated version of
"connect a client and see if it works." It is opt-in (`run_preflight`, what `app.ingest` calls
automatically, never touches the MCP server) since it spawns a real subprocess and shouldn't slow
down every ingest run. For a full query -> citation round trip (semantic_search, then get_span on
the top hit), use `python -m app.mcp_verify_client "some query"` -- see that module's own docstring.
