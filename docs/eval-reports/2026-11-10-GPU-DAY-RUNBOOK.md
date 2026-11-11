# GPU-day runbook — every GPU-dependent job queued on 2026-11-10, serialized cheapest-first

Written 2026-11-10 while the embedder/reranker are down and the GPU is busy. Nothing here has been run.
Protocols (frozen before any run): `2026-11-10-standards-benchmark-protocol.md`,
`2026-11-10-main-corpus-benchmark-protocol.md`, `2026-11-10-topic-focus-benchmark-protocol.md`;
CQ-3: `2026-11-10-cq3-stub-chunks.md`. Run scripts: `data/2026-11-10-standards-gt/run_baseline.sh`,
`data/2026-11-10-papers-passage-gt/run_baseline_main.sh`. Both only verify and hash fixtures; neither writes one.

**Durations are ESTIMATES, not measurements.** Basis: an existing note records two retrieval-eval jobs of ~80–150
questions as "normally minutes" (`AGENT-OPERATIONS-LESSONS.md` §9.1); I use ≈ 2 s/question at rerank depth 32 and up
to ≈ 6 s at depth 128 (rerank work grows with the pool). Each run's `MANIFEST.txt` stamps start/finish, so the first
GPU day replaces these with real rates. Query counts are computed from the fixtures.

## Summary (in order)

| # | job | needs | est. GPU time | index effect |
|---|---|---|---|---|
| 0 | free the GPU, bring services up | operator | 5–15 min | none |
| 1a | baseline, main (`papers books legacy`) | 0 | 20–40 min (≈ 654 queries) | **read-only** |
| 1b | baseline, focus | 0, `focus_gt.json` hash frozen | 2–5 min (≈ 50) | **read-only** |
| 1c | baseline, standards (depth + ablations + controls) | 0 | 1–2 h (≈ 1,198 queries) | **read-only** |
| 2 | reranker-score census on absent arms | 0, **recording shim (not committed)** | 15–30 min (≈ 500) | **read-only** |
| 3 | depth/weight grid per corpus | 1a, 1c | 40–90 min (≈ 1,200) | **read-only** |
| 4 | CQ-3 stub-filter A/B | 0 | 40–80 min (≈ 1,176) | **read-only** (query-time flag) |
| 5 | ligature resparse A/B | CQ-1 + CQ-2 merged | GPU 12–25 min; CPU prep unmeasured | **modifies a CLONE only** |
| 6 | relevance-score payload + demotion arm | CQ-2 + demotion ticket applied | ≈ 15 min | payload route modifies a **CLONE only**; DB route read-only |
| 7 | targeted re-chunk of the truncated chunks | `app.rechunk` on a copy | 25–40 min (whole-paper) / minutes (if a targeted op is written) | **modifies a CLONE (DB copy + collection) only** |

Rule for every step: one GPU job at a time. `.gpu.lock` serializes correctly but has no priority and no fairness;
a cheap job launched behind a long one just sleeps (`AGENT-OPERATIONS-LESSONS.md` §9.1). Never start step N+1 until
step N has printed `done ->` and exited.

## Why this order (and the deviations)

- Baselines first: every A/B below needs a measured reference on the same code and index, and the frozen rules were
  written against the shipped config.
- Inside step 1 the order is cheapest-first (main ≈ 25 min, focus ≈ 3 min, standards 1–2 h) rather than the order
  the ticket listed (standards, main, focus): the lesson cited above cost 20 minutes once. Focus has a hard
  prerequisite (its fixture hash is null until authoring ends) and is simply skipped if still null.
- Step 7 is last because **re-chunking renumbers chunk ids** (`Chunk.chunk_id = "<paper>:c<index>"`, positional) and
  moves anchors for the papers it touches; doing it first would invalidate gold chunk ids in the A/Bs before it.
  Step 5 and 6 each use their own clone; they are never stacked on one clone.
- Steps 5–7 have CPU/Qdrant-only preparation (clone, resparse, payload write, dry-run) that does NOT need the
  GPU. Do those today while the GPU is busy with `python -m app.doctor --cpu-only` (brings up only the CPU
  services) and spend GPU time only on the evaluation.
- The census (2) is ahead of the grid because it is the cheapest read-only job after the baselines, but it is
  **blocked on code that does not exist** (an experiment-only `TeiReranker` subclass that keeps `(id, score)`, RV-1
  F-1.1). If it has not landed, skip it; do not wait. When it exists it can alternatively be recorded inside step 1
  at zero extra GPU cost.

## Step 0 — free the GPU and bring services up (prerequisite for everything)

Which process holds the GPU, as seen at writing (2026-11-10; re-check, it will have changed):
`nvidia-smi` showed 18,609 of 24,576 MiB used by `/usr/local/lib/ollama/llama-server` (pid 2094959, 18,586 MiB), and
`fuser -v /home/omar/ai-projects/research-system-rag/.gpu.lock` printed nothing (the repo's own lock is free; the
GPU is held by Ollama, which does not take that lock).

```
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv     # who holds VRAM
fuser -v /home/omar/ai-projects/research-system-rag/.gpu.lock                 # who holds the repo lock (empty = free)
ollama ps                                                                     # loaded models
ollama stop <MODEL>      # operator action: unloads the model, keeps the Ollama server up (doctor still wants it healthy)
```

Never `pkill -f`; confirm a pid with `readlink /proc/<pid>/cwd` first (`AGENT-OPERATIONS-LESSONS.md` §6b.3). Free
VRAM must cover both TEI containers (embedder Qwen3-Embedding-4B and the reranker); `doctor` checks headroom and
says so. Then, from the corpus data directory (it reads `./config.yaml`):

```
conda activate agent-rag-research
cd /home/omar/ai-projects/research-system-rag-data && python -m app.doctor          # starts stopped containers, then health-checks
```

Expect `doctor: OK -- disk/GPU/lock/all required services healthy.` `doctor` also requires the parser's
reference-resolution service (port 8070) although no eval uses it; it auto-starts that container. The run scripts
themselves call `app.doctor --no-auto-start` and STOP with a message if anything is down; they never start a
service. Disk check before any clone: `df -h /` (91 GB free at writing, 98% used); the `papers` collection is 5.8 GB
on disk, `av_standards` 477 MB, `waymo_av_safety` 787 MB (`.phase0-data/qdrant/collections/`).

## Step 1 — baselines (read-only; protocols are binding)

```
cd /home/omar/ai-projects/research-system-rag/docs/eval-reports/data/2026-11-10-papers-passage-gt
./run_baseline_main.sh papers books legacy                      # 1a, ≈ 20–40 min
cd ../2026-11-10-focus-gt && sha256sum focus_gt.json            # 1b: only after authoring ends: put the hash in
#   data/2026-11-10-FIXTURE-HASHES.json (dated commit), then:
cd ../2026-11-10-papers-passage-gt && ./run_baseline_main.sh focus     # ≈ 2–5 min
cd ../2026-11-10-standards-gt && ./run_baseline.sh              # 1c, ≈ 1–2 h
```

Each script: checks fixture SHA-256, verifies the GT read-only, requires services ready, asserts the collection's
point count against the corpus DB (`check-points`), then writes one `runs/<stamp>/`. If a check stops the run, fix
the cause; do not edit the script or a hash to get past it (a changed hash needs an addendum first). Outputs and
reports of record: see each protocol's §10. Write them up unmodified as `2026-11-10-<corpus>-baseline.md`.
Standards depth rule D-1 and falsifier S-1 are evaluated from this one run (standards protocol §5); the
`depth128-fused-repeat` arm is its validity gate.

## Step 2 — reranker-score census on the absent arms (read-only; BLOCKED until the shim exists)

Definition frozen in the protocols (standards §7 iii). Arms: standards absent 9 and partial-absent 13 (separately),
main known-absent 24 and books partial-absent 5, each against the answerable top-1 reranker score; AUROC with
Hanley–McNeil CI and `app/score_distribution_census.py::_iqr_separates`. That module's `--collection` defaults
to `papers`: pass `--collection`, `--db-path`, `--blob-dir` explicitly for every corpus (RV-3 F-1.2). Floor viable
only at AUROC ≥ 0.85; no wiring decision from these n (needs ≥ 60 distinct real absent items, RV-3 F-1.10).
Est. ≈ 500 queries, 15–30 min.

## Step 3 — per-corpus depth/weight grid (read-only)

Depth {32, 128} × `--dense-weight` {0.5, 0.7, 1.0} per corpus, using the flags `app.retrieval_eval` already has
(`--dense-weight`, config copy for depth, as `run()` does in `run_baseline.sh`). Arms already measured in step 1
(standards 128/0.5 and 32/0.5; main 32/0.5) are not repeated: standards 4 new arms on `standards_gt` (≈ 512
queries), main 5 new arms on papers + books (≈ 675). Name `--collection`, `--db-path`, `--blob-dir` explicitly.
Pre-registered rule G-1 (written now, from RV-1 F-1.5): the standards DEPTH question is already decided by D-1 and
is not reopened here; for any other default change (the weight axis, main depth) the candidate arm must show
member-passage hit@10 net ≥ +3 questions vs the shipped arm on that corpus's own fixture(s), a paired
wins:losses ratio ≥ 3:1, no gating stratum (n ≥ 10) losing more than one, and the same sign on the title-ablated
arm; otherwise defaults stay. Compute paired flips with `scripts/nb_xp_deeppool_tables.py` (jitter envelope
included). Any default change is operator sign-off, not automatic. Est. 40–90 min.

## Step 4 — CQ-3 stub-filter A/B (read-only: query-time flag only)

Pre-registered in `2026-11-10-cq3-stub-chunks.md` (criteria 1–3); do not restate or alter them. Both arms
back-to-back on the same collection, per fixture; baseline arm re-run (not reused from step 1):

```
python -m app.retrieval_eval --config <cfg> --ground-truth <GT> --collection <C> --db-path <DB> --blob-dir <BLOBS> \
    --k 10 --report-path base.json
python -m app.retrieval_eval ... --drop-stub-chunks --report-path drop.json
python scripts/list_stub_chunks.py <DB> --ab base.json drop.json
```

Fixtures: standards GT (collection `av_standards`), `fixtures/eval/eval_ground_truth.json` and
`fixtures/eval/eval_book_questions.json` (collection `papers`), plus the papers and books passage sets for the
member-passage criterion. ≈ 588 queries × 2 arms, 40–80 min. Per-question rows are required (no `--no-per-question`).

## Step 5 — ligature resparse A/B (MODIFIES AN INDEX: clone only)

Prerequisites: CQ-1 (ligature repair in `_sparse_vector`) and CQ-2 (`app.resparse`) merged; read the CQ-2 operating
note (`docs/eval-reports/2026-11-10-cq2-index-maintenance.md` once merged) — the commands below follow the
`app.resparse` docstring on branch EP-CQ2-resparse-setpayload and must be re-checked against its final text.
The deployment hazard there is real: CQ-1 code on an un-resparsed collection serves repaired queries against
unrepaired sparse vectors, so arm A must be the pre-CQ-1 checkout (the step-1 baseline, whose `MANIFEST.txt`
records its git rev) and arm B is CQ-1 code on the resparsed clone.

1. CPU only, can run while the GPU is busy: clone `papers` (5.8 GB) with `VectorIndex.clone_points_into`
   (the pattern in `app/exp1_outline_split.py::clone_production_collection`) into a new collection, e.g.
   `papers_ligfix`; then `python -m app.resparse --collection papers_ligfix --target-is-clone --clone-of papers --apply`
   (dry run first; `--collection` is required, it never auto-creates). Resparse time is unmeasured (~35% of
   main-corpus chunks change).
2. GPU: run `run_baseline_main.sh`-equivalent commands with `--collection papers_ligfix` on the papers, books and
   210 fixtures (≈ 345 queries, 12–25 min). Stratify by `ligature_damaged` (35 damaged / 26 clean papers items; 27 / 42
   books; flag from the census regexes in `data/2026-11-10-ligature-census/results.json`). The live `papers`
   collection is never touched; delete the clone when done.

## Step 6 — relevance-score payload + demotion arm (payload route modifies a CLONE only)

Prerequisites: CQ-2's `app.set_payload_fields` and the retriever demotion ticket applied (both written, not yet
applied). Arms R-demote(τ = 0.25) and R-demote(τ = 0.30) vs baseline; adoption rule frozen in the topic-focus
protocol §6 (never a hard drop; includes the legitimate-off-topic guards). Payload route, CPU: clone `papers`, then
`python -m app.set_payload_fields --collection <clone> --build relevance_score --db <papers.db> --only-fields
relevance_score --target-is-clone --clone-of papers --apply` (dry run first). Document-store route: no index change.
GPU: focus set + papers set, three arms back-to-back, ≈ 111 queries × 3, ≈ 15 min. Record the exact demotion flag in
a dated addendum to the focus protocol before reading any number.

## Step 7 — targeted re-chunk of the truncated chunks (MODIFIES A CLONE: DB copy + collection)

Scope: `docs/eval-reports/data/2026-11-10-embed-truncation/report.md` counts 3,138 main + 126 Waymo = 3,264 chunks over
4,096 tokens (the embedder silently truncates; 0 in standards). The 3,264 figure is both corpora; main alone is 3,138
chunks (0.79%), in ≤ 3,135 papers. The report's "few minutes of GPU" assumes a TARGETED op that replaces only the
oversized chunks; **no such op exists** — `app.rechunk` re-chunks whole papers from stored blocks, which re-embeds
every chunk of each affected paper (order of 100k chunks if all ~3,135 main papers; full-corpus re-embed was projected
at ~98 min, `AGENT-OPERATIONS-LESSONS.md` §9.1, so ≈ 25–40 min). Choose before the day: write the targeted op, or
accept the whole-paper cost. Procedure: SQLite copy via `VACUUM INTO`, `clone_points_into` the collection, `python -m
app.rechunk --config <clone cfg> --paper-ids-file <affected ids> --dry-run`, then apply on the CLONE only (pattern:
`app/exp_tdoc87_marker_repair.py`). Measure with the member-passage metric (it uses `excerpt_block_id`, stable
across a re-chunk); fixture gold chunk ids for re-chunked papers are stale by design and the fixtures are NOT
re-grounded or rewritten. Papers/books items whose `excerpt_block_id` is null (1 papers, 7 books) fall back to anchors
and must be listed separately. The Waymo 126 follow the same procedure on its own collection, if wanted.

## Stop conditions (any step)

- `check-hash` or `check-points` fails: stop, do not adjust the script; diagnose (wrong collection? changed fixture?).
- `n_errors > 0` in any report: the arm is invalid; do not read its numbers.
- `app.doctor` non-zero mid-day: stop; do not start a second GPU job to compensate.
- Anything that would change a frozen definition, threshold or fixture: dated addendum in the matching protocol first.
