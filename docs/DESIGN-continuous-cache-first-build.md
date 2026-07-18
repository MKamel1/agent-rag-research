# Design — Continuous cache-first corpus build (OG-41 + parallel prefetch)

*Owner-approved 2026-07-18. Goal: one command builds the corpus to a target N, hands-off. The GPU
parses cached PDFs while the downloader fills the cache in parallel, so the GPU never stalls waiting
on a download. "Cache-first by default" + "downloader auto-starts with the run" + "the run keeps
going until it reaches target."*

## Why (plain English)
Downloading (network, throttled ~15s/PDF ≈ 240/hr) is *faster* than parsing (GPU, ~180/hr) and uses
a different resource, so running them together is free throughput and the cache stays ahead of the
parser. Today the ingest re-runs its own keyword *discovery* (capped, dedup-eaten → only ~809 of a
30k target) instead of just consuming the PDFs the downloader already fetched. See OG-40/OG-41 in
`reviews/OPERATIONAL-GAPS.md`.

## The one hard constraint that shapes the design
Ingest is **two-pass with VRAM isolation**: Pass 1 (`app.parse_phase` subprocesses) parses a set of
papers, then Pass 2 (`_run_finish_phase`) embeds *the same set*. Both passes call
`assembly.harvest_refs`, so **both must agree on the identical paper set**. If a pass scanned the
live `pdf_cache` directory, Pass 1 and Pass 2 (separated by hours of parsing, during which the
downloader adds files) would get *different* sets → Pass 2 tries to embed papers Pass 1 never parsed.
**Therefore each ingest invocation must run against a FIXED snapshot of ids** — exactly what the
OG-40 `--paper-ids-file` path already guarantees (both passes read the same `ingest_paper_ids`).

## Architecture: a thin supervisor, NOT an ingest refactor
New module **`app/build_corpus.py`** — a deep module hiding "build the corpus to N" behind one entry
point. It reuses `app.ingest --paper-ids-file` (OG-40) unchanged as its per-iteration executor and
`app.prefetch_pdfs` unchanged as the downloader. It does NOT touch ingest's two-pass internals.

```
python -m app.build_corpus --target N --parse-workers K [--events-path P] [--batch-size B]
```

Loop (pseudocode):
```
ensure_prefetch_running(target=N)          # launch app.prefetch_pdfs as a child iff not already up
while done_count(db) < N:
    ids = cached_not_done(cache_dir, db)[: N - done_count(db)]   # snapshot: cached PDFs minus done
    if not ids:
        if prefetch_alive():  sleep(POLL_INTERVAL); continue      # caught up — wait for downloads
        else:                 break                               # cache drained AND downloads done
    write ids -> <data_dir>/build_batch_<ts>.ids
    run:  env PYTHONPATH=<repo> python -m app.ingest \
             --paper-ids-file <batch file> --parse-workers K --events-path <events> [--no-preflight?]
    # each ingest run does a full fixed-set two-pass; ingest_state records done; idempotent/resumable
log "build_corpus: reached N done (or exhausted): <done>/<N>"
```

### `ensure_prefetch_running(target)`
- Detect an existing downloader (avoid a duplicate that would double-check/double-download): a
  `<data_dir>/prefetch.pid` file whose pid is alive AND whose `/proc/<pid>/cmdline` contains
  `app.prefetch_pdfs` (identity check, same rigor as the dashboard controller). If found, reuse it.
- Else launch `python -m app.prefetch_pdfs` as a **child in build_corpus's process group** (inherit
  session; do NOT `start_new_session` on the child) so a SIGTERM to build_corpus's group stops the
  downloader too. Write its pid to `prefetch.pid`.
- Note: prefetch reads its target from `config.prefetch_target` (no `--target` flag today). If N >
  that, prefetch will only fill to `prefetch_target`; that's acceptable for now — flag it in a code
  comment (a follow-up can add a `--target` to prefetch). Do NOT edit config.yaml (foundation).

### `cached_not_done(cache_dir, db)`
- Cached ids = basenames of `cache_dir/*.pdf` (strip `.pdf`). (Same naming as `prefetch._pdf_path`.)
- Done ids = `SELECT paper_id FROM ingest_state WHERE stage='done'` (read-only).
- Return cached − done, stable order (sorted) for determinism. This is the cache-first "to-do list."

### Termination
- `done_count >= target` → success.
- `cached_not_done` empty AND prefetch process no longer alive → cache exhausted / downloads done →
  stop (can't reach N). Log the shortfall clearly.
- A bounded idle guard (like prefetch's `--max-idle`): after M consecutive "empty batch, waited"
  cycles with no growth, stop with a "stalled" message rather than looping forever.

### Batch efficiency
Process the *whole* current `cached_not_done` set each iteration (big batches → good GPU batching,
model-load/TEI-restart overhead amortized). Because downloading outpaces parsing, iteration 1 is
large (~all currently cached), and subsequent iterations pick up whatever downloaded meanwhile —
few, large iterations, not many tiny ones.

## Cache-first as the DEFAULT (the OG-41 ask)
- `build_corpus` is the new default "run" launched by the dashboard (below) — its very nature is
  cache-first, so a normal run needs no `--paper-ids-file`.
- **Cold-start fallback:** if `cached_not_done` is empty AND prefetch has downloaded nothing yet
  (fresh machine, empty cache), `build_corpus` should wait for the downloader's first PDFs rather
  than doing its own query harvest — the downloader owns discovery now. (Query harvest stays only as
  `app.ingest`'s own behavior when invoked directly with neither `--paper-ids-file` nor a cache;
  do NOT delete it — it's the bootstrap/eval path.)

## Dashboard integration (`app/dashboard/controller.py`)
- `_spawn` / `start`: launch `python -m app.build_corpus --target N --parse-workers K
  --events-path <events>` instead of `python -m app.ingest ...`. Keep `start_new_session=True` on
  build_corpus (it's the group leader); its ingest and prefetch children inherit the group, so the
  existing `os.killpg` pause/stop/resume machinery reaches all of them unchanged.
- Manifest: `pid` = build_corpus pid; identity capture, atomic writes, reconcile — all unchanged.
- `resume` re-launches build_corpus with the same `--target`; build_corpus + ingest are
  idempotent/resumable via `ingest_state`, so resume picks up where it left off. The
  `paper_ids_file` manifest field (OG-40) is no longer needed for the default path but leave the
  threading in place (harmless; still used if someone starts an explicit id-list run).
- Events: point every iteration's ingest at the SAME `--events-path`; the dashboard funnel is driven
  by `ingest_state` (cumulative, correct across iterations). Multiple RUN_START/RUN_END cycles in
  the events file are expected — note it; the funnel/done-count is the source of truth.

## Constraints for the builder
- **Non-foundation only.** New `app/build_corpus.py` + tests; edit `app/dashboard/controller.py`.
  Do NOT touch `contracts/`, `rag/config.py`, `config.yaml`, `migrations/`, `ci/`, `.github/`,
  `rag/fakes/`, `fixtures/`. No `os.environ` reads in `app/` (argparse only; the `env` *command*
  is fine for subprocess PYTHONPATH, as `controller._spawn` already does).
- **Do NOT disturb the live run.** A real ingest (`run-3995`, pid 2753456) is running and holds
  `<data_dir>/.ingest.lock`. Do NOT launch any real `app.ingest`/`app.build_corpus`/GPU run, do NOT
  touch the production `papers.db`/`pdf_cache`, do NOT kill any process. Test ONLY with fakes and
  temp dirs (inject the ingest-runner, the prefetch-launcher, `cached_not_done`, and `done_count`
  as seams — same dependency-injection style as `controller._spawn` and `prefetch.prefetch_loop`).
- **Tests** (offline, no GPU/network): the loop reaches target over several fake iterations;
  stops on cache-exhausted+prefetch-dead; waits when caught-up-but-prefetch-alive; idle guard trips;
  `ensure_prefetch_running` reuses an existing live downloader (no duplicate) and launches one when
  absent; `cached_not_done` = cached−done. Update `controller` tests for the build_corpus command.
- Run the offline suite green in the `agent-rag-research` conda env (it has the deps).
- **No AI attribution** in commits or PR (no `Co-Authored-By: Claude`, no "Generated with" line).
- Open ONE PR bundling this (OG-41) with the already-in-working-tree OG-40 changes (`--paper-ids-file`
  + controller threading + its tests) — they're one cache-first feature. Non-foundation → self-merge
  on green CI per repo norm. Do NOT `git stash`/`reset`/`checkout` existing working-tree changes;
  only add/edit forward and commit.
```
```
