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

## GPU busy / CPU-only operation (OP-1)

When another process holds the GPU, the TEI containers (`rag-tei-embed`, `rag-tei-reranker`) fail
to start with CUDA out of memory. The vector store (`rag-qdrant`) and the reference-resolution
service (`rag-grobid`) are CPU-only and do not care. The restart-policy decision above is
unchanged: nothing starts on its own, this is still a command you run.

```bash
python -m app.doctor --cpu-only
```

Checks disk headroom and starts/health-checks only the vector store and GROBID; skips TEI, the
VRAM-headroom check and the `.gpu.lock` check. Exit 0 and a tool table when they are ready.

| Tool | With the GPU busy |
|---|---|
| `scan_corpus`, `scan_methods`, `list_methods`, `get_paper`, `get_span`, `get_section`, `get_figures`, `corpus_stats` | works (SQLite only) |
| `semantic_search`, `search_papers` | fails at once with one message naming TEI, why, what still works, and the recovery command |

The MCP server itself still needs the vector store to start (its constructor connects to it), so
run `--cpu-only` *before* connecting/reconnecting the MCP client. With the vector store down,
`python -m app.serve` now exits with a message saying exactly that instead of a raw traceback.

Who holds the GPU:

```bash
nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv
```

Back to full operation: once that process has exited (or been stopped by you), run
`python -m app.doctor` (no flag). It starts the TEI containers, checks VRAM and `.gpu.lock`, and
exits 0 when everything, including the summarizer host service, is ready; then reconnect the MCP
client (`/mcp` in Claude Code).

### Diagnosing GPU contention (OP-5)

`python -m app.doctor` (also with `--cpu-only --no-auto-start`, which starts nothing) ends with a
"corpus / disk / GPU" block. Read it top-down:

1. `GPU: N MiB free VRAM ...` -- compare with what the embedder + reranker need resident. Two
   numbers exist and they disagree: doctor's preflight floor is **2000 MiB** (`_MIN_FREE_VRAM_MIB`,
   an old "is there any headroom" threshold, still what gates `app.ingest`), while ARCHITECTURE.md
   section 3 / CONVENTIONS.md section 6 give **~9.4 GB resident** for the TEI pair (embedder
   ~8.2-10 GB during a real batch + reranker ~1.4 GB). The report prints both and says plainly
   when free VRAM is below ~9400 MiB. Neither threshold was changed by OP-5.
2. `GPU process [foreign]: pid .. name .. MiB` -- every compute process `nvidia-smi` lists that is
   not the recorded `.gpu.lock` holder (the TEI containers appear here too while they are up).
   `nvidia-smi` absent: one line saying so, no crash.
3. `.gpu.lock holder: pid .. stage .. since .. -- <command>` -- who holds the cross-process
   compute lock right now (written on acquire to `.gpu.lock.holder`, removed on release). A record
   whose pid is dead (crashed holder) is ignored. `doctor` (full mode) also puts this in the
   `gpu_lock` issue text. Which processes take the lock: ingest (summarize/embed), the MCP server's
   embedder and reranker, the judge and other experiment scripts -- all per single inference call.
4. Foreign process holds the VRAM, lock is free: `python -m app.doctor --cpu-only`, stop the foreign
   process (your decision), then `python -m app.doctor`. Lock held by a live pid: wait, or stop
   that pid; do not delete `.gpu.lock`.

## Backup, restore and verify (OP-3)

What exists on disk today (taken by hand on 2026-11-10, main corpus, under
`<main corpus data dir>/backups/`):

| Artifact | What it is | Check |
|---|---|---|
| `papers.db.snapshot-20261110` + `.sha256` | consistent SQLite backup; integrity ok; row counts equal to the source on papers, chunks, blocks, summaries, ingest_state, quarantine | `python -m app.snapshot --verify <path>` |
| `qdrant-storage-20261110/` | plain file copy of the vector-store storage, container stopped, the five production collections only (`papers`, `waymo_av_safety`, `av_standards`, `motional_av`, `waabi_safety`); `MANIFEST.sha256` over 1,268 files; `README.txt` with restore steps | `python -m app.snapshot --verify <dir>` |

What was **not** taken: about 24 GB of experiment/scratch collections (`exp*`, `e2e_*`, `bench*`,
`scratch_*`, `tdoc87_*`, ...) were deliberately not copied, and the blob directory was not copied
(markdown text; rebuildable from the PDFs but not instantly). **Everything is still on the same
disk, which is ~98% full: there is no off-device copy.** These protect against a bad ingest or a
corrupted index, not against losing the disk.

Commands (run from the repo root; `--verify` reads only and needs no config or running services):

```bash
# verify any existing backup: snapshot-*/ dir, MANIFEST.sha256 dir, or a SQLite file + .sha256
python -m app.snapshot --verify /path/to/backup

# SQLite-only backup, no vector store needed: backup API from a read-only connection,
# integrity_check, row-count comparison, writes papers.db.snapshot-<YYYYMMDD> + .sha256
python -m app.snapshot --sqlite-only [--backup-root DIR]

# full snapshot (needs the vector store up): sqlite + blobs + collection, manifest.json carries
# quick_check and sha256 for every artifact; a failed check leaves snapshot-*.partial behind
python -m app.snapshot [--backup-root DIR] [--keep N]
```

Rules: snapshots abort when the backup device has less than **20 GiB** free (`doctor` warns below
the same figure); a tool pointed at a directory with no `papers.db` now refuses instead of creating
an empty one (`app.snapshot`, `app.corpus_integrity`).

Restore the SQLite copy: stop everything that writes, `python -m app.snapshot --verify` the file,
copy it over `papers.db` (keep the old file aside until `python -m app.corpus_integrity` is happy).
Restore the vector store from the file copy: `sha256sum -c --quiet MANIFEST.sha256` inside the
backup directory, stop the container, copy `collections/<name>` back into the storage directory's
`collections/` folder (the bind mount shown by `docker inspect rag-qdrant`), start the container,
then `python -m app.doctor` -- its corpus-pairing check compares the collection's point count with
chunks + summaries in the database (5% tolerance). Restore the SQLite and vector-store copies
together; they only make sense as a pair.

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

### Which corpus is this MCP connection serving? (2026-08-23)

One server process serves exactly one corpus. A client session wired only to the default
connection sees the main causal-methods corpus and *nothing else*: Waymo ids answer
"unknown paper_id", org-filtered scans scan zero papers -- both true of that store, and easy to
misread as "the Waymo corpus has no data". Three ways to know where you are:

1. Call `corpus_stats()` first: its `serving` key names the answering process
   (`collection=<name> db=<path>`), and unknown-id errors carry the same suffix.
2. The server logs its resolution at startup (`serve: resolved db_path=... collection=...`,
   stderr -- visible in the client's MCP server logs).
3. To reach more than one corpus from one client, register one server entry per corpus: the default
   one above, plus one per extra corpus with `"args": [..., "-m", "app.serve", "--data-dir",
   "<data dir>"]` (data directories are tabulated under "Running a second corpus" below; for example
   `/home/omar/ai-projects/research-system-rag/waymo/data`). Same PYTHONPATH rules apply.

`app.mcp_verify_client` takes the same `--data-dir` (e.g. `python -m app.mcp_verify_client "query"
--data-dir waymo/data`) -- before 2026-08-23 it accepted the flag and silently ignored it,
reporting main-corpus results for another corpus's question.

## Running a second corpus

**Five corpora are registered today** (counts, per-corpus settings, build provenance and evaluation status
are in `docs/PROJECT-STATUS.md` §1.1 — deliberately not repeated here). Each is a data directory with its
own `config.yaml`; pass the directory to `app.serve --data-dir`, or `cd` into it for ingest-side tools:

| corpus | data directory | `collection` |
|---|---|---|
| main (causal methods) | `/home/omar/ai-projects/research-system-rag-data` | `papers` |
| Waymo AV safety | `/home/omar/ai-projects/research-system-rag/waymo/data` (gitignored, inside the main checkout) | `waymo_av_safety` |
| AV standards | `/home/omar/ai-projects/research-system-rag-standards/data` | `av_standards` |
| Motional | `/home/omar/ai-projects/research-system-rag-motional/data` | `motional_av` |
| Waabi | `/home/omar/ai-projects/research-system-rag-waabi/data` | `waabi_safety` |

The three sibling directories are not git repositories, and none of the five can be rebuilt from tracked
files. A new data directory also needs its own `collection`; and `app.init_config` writes a **private**
`gpu_lock_path` (the template default `.gpu.lock`, resolved under the new directory) that must be edited to
the shared lock `/home/omar/ai-projects/research-system-rag/.gpu.lock`, which all five existing configs
use — otherwise two corpora can hold the GPU at once. Do not ingest into a live collection from the
`EP-programme-20261110` branch (it mixes chunker generations; `docs/PROJECT-STATUS.md` §6.1).

A second corpus is just a second data directory with its own `config.yaml` -- nothing in this
repo's pipeline is hardcoded to one corpus. Bootstrap it with
`python -m app.init_config --data-dir <dir>` (writes every path field resolved absolute under
`<dir>`), then hand-edit at minimum `collection` (a distinct Qdrant collection name -- never reuse
`papers`) and `focus_area_queries`. Most ingest-side tools (`app.ingest`, `app.build_corpus`,
`app.parse_phase`, `app.prefetch_pdfs`) take no `--data-dir` flag at all -- they use the process's
own `cwd` as the data dir by convention, so run them as `cd <dir> && python -m app.ingest ...` (or
`app.build_corpus`). Only four tools take `--data-dir` explicitly and don't need the `cd`:
`app.serve`, `app.dashboard.server`, `app.dashboard.verify_numbers`, and `app.init_config` itself.

`gpu_lock_path` should normally point at the **same shared lock file** across every corpus's
`config.yaml` (not a separate per-corpus lock) -- both corpora's GPU-heavy parse/embed work then
serialize on the one physical GPU instead of risking a concurrent OOM. A second dashboard instance
for live monitoring is just `DASHBOARD_DATA_DIR=<dir> DASHBOARD_PORT=<port> scripts/dashboard.sh
start` with a port other than 8700.

```bash
python -m app.init_config --data-dir "$PWD/second-corpus/data"
# hand-edit second-corpus/data/config.yaml: collection, focus_area_queries, gpu_lock_path
cd second-corpus/data && python -m app.doctor
DASHBOARD_DATA_DIR="$PWD" DASHBOARD_PORT=8701 /home/omar/ai-projects/research-system-rag/scripts/dashboard.sh start
python -m app.build_corpus --target 1000 --parse-workers 3
```

See `docs/WAYMO-CORPUS-STATUS.md` for a worked example of this -- including where its own
execution drifted from these supported mechanisms (a hand-rolled batch script instead of
`app.build_corpus`) and what that cost.
