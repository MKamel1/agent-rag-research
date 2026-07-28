# WORK-BREAKDOWN — V0 build plan

Who builds what, in what order, and what "done" means for each piece. Read alongside ARCHITECTURE.md (the
design), DATA-CONTRACTS.md (the shapes), CONVENTIONS.md (the rules), and PHASE0-RUNBOOK.md (the de-risking).

**Sequencing principle:** the *interfaces* are fixed from day one, so most work runs in parallel. Only two
things are true prerequisites: (1) the **shared foundation** (Owner F) must exist before modules integrate;
(2) **Phase 0** must pick the three adapters before the modules that wrap them are final. Everything else fans
out.

**Gating on Phase 0 (the contract freeze is provisional — DATA-CONTRACTS.md Rule 1):** `Anchor` is a bet
Spike 1 settles. Concretely:
- **T-B1 Parser (M2), T-C1 Chunker (M3), and any ticket consuming `Anchor`/`Block`** must not *start*
  (implementation) before **Spike 1** (block-bbox + snippet round-trip ≥ ~95%, PHASE0-RUNBOOK.md) passes.
  If Spike 1 forces an `Anchor` shape change, these are exactly the tickets that would need rework.
  **Update: Spike 1 has concluded** — MinerU is locked as the sole V0 `Parser` adapter (round-trip
  100% audited, throughput the deciding factor; Docling and Marker evaluated and dropped). T-B1 and T-C1
  are unblocked to start implementation. See `phase0-results.md` for the full numbers and reasoning, and
  `fixtures/golden/` for the committed golden fixture set. One caveat carried forward, not a blocker: the
  arXiv-LaTeX ingest trial (runbook Spike 1 method step 4) was never run — see `phase0-results.md`'s "Open
  item carried forward" note.
- **T-D2 VectorIndex (M6) and T-E1 Retriever (M7) tuning** (top-k, hybrid weights, rerank depth) gate on
  **Spike 2** (retrieval eval, Recall@10 ≥ ~0.85).
  **Update: Spike 2 has concluded** — Qwen3-Embedding-4B + hybrid (dense+sparse+RRF) + BGE-reranker-v2-m3
  locked as the V0 retrieval config (PR #46). Qwen3-4B dense-only Recall@10 0.875 (clears the gate);
  hybrid+rerank Recall@10 0.844 (just under, locked anyway per `PHASE0-RUNBOOK.md`'s keep-hybrid-regardless
  rule). T-D2 (PR #37) and T-E1 (PR #34) have both shipped. See `phase0-results.md` for the full numbers.
- **M1/Harvester (T-A1) is NOT gated** — it produces `PaperRef`, never touches `Anchor`, and was safe to
  build regardless of Spike 1/2 outcomes; it has since shipped (PR #36).

---

## Milestones

| # | Milestone | Gate to exit |
|---|---|---|
| **M0** | Shared foundation (Owner F) + Phase 0 (B/C/D/E) | DATA-CONTRACTS types + Config + schema + fakes committed; parser & embedder & retrieval config **locked with numbers** (PHASE0-RUNBOOK) |
| **M1a** | Tests-first: every owner writes their module's test suite against the frozen interface + fakes | every module has a committed, red (failing/non-implemented) test suite reviewed and merged; no module's implementation code exists yet |
| **M1b** | Implementation: every owner fills in their module to green | every module's unit tests green through its interface, zero GPU/net; Definition of Done met |
| **M2** | Real adapters + contract tests | fake and real adapter agree at each seam (Embedder, VectorStore, Parser) |
| **M3** | Integration + smoke test on ~200 papers | full pipeline runs end-to-end; idempotency/resume/quarantine verified on real data |
| **M4** | Full 30k seed run | corpus ingested (overnight/days); retrieval eval ≥ Recall@10 0.85 on real corpus |
| **M5** | Ship criterion | an agent answers a factual question about an ingested paper with a correct, verifiable citation at ~0 API cost — and you use it (PRD §Phase V0) |

**Critical path:** M0 foundation → (Phase 0 in parallel) → Retriever + its stores (M7/M5/M6) → MCP server (M8)
→ integration. Parser (M2) is on the path too because everything downstream needs parsed text — start it in
Phase 0. Harvester (M1) can lag slightly (a fixture corpus unblocks everyone else). Summarizer (M3B) is
**not** on the critical path (Chunker/Embedder are) but must finish before `DocumentStore.put` — a
`PaperRecord` is incomplete without `summary_text`.

---

## M0 — Shared foundation (Owner F) — **do this first, freeze it, protect it**

Everyone codes against these. This is the highest-blast-radius artifact in the build (CONVENTIONS §0): if it
drifts after the fan-out, every module drifts with it and the failure surfaces late, at integration, across
several other agents' work at once. Build it, get it reviewed, **freeze it**, and put the freeze behind a
mechanical gate — don't rely on every other agent remembering not to touch it.

- **T-F1** `contracts/` package: every dataclass/TypedDict in DATA-CONTRACTS.md — including `GpuLock`
  (protocol), `Coverage`/`SearchResponse`/`PaperSearchResult`/`PaperSearchResponse` (§M8), and
  `fusion.py`'s `rrf_fuse` pure function (§M6) — plus
  `contracts/errors.py` (`TransientError`/`PermanentError`/`ContractError`). Prefer a runtime-validating form
  (e.g. `pydantic` models or `attrs` with validators) over plain dataclasses — a shape mismatch should raise
  loudly at construction, not pass silently because Python didn't check it. *Done:* imported by a trivial
  test from each module dir; constructing one with a wrong type raises; `rrf_fuse` has its own unit test
  against synthetic rank inputs (TEST-STRATEGY.md).
- **T-F2** `Config` loader: one `config.yaml` → `Config` object (incl. `gpu_lock_path`); no other module
  reads env/files. *Done:* Config injected at both entrypoints (orchestrator, MCP), both constructing their
  real `GpuLock` from the same `gpu_lock_path`.
- **T-F3** SQLite schema (papers/blocks/chunks/summaries/`ingest_state`/`quarantine`) in WAL mode; migration
  script. *Done:* schema creates cleanly; V1 tables intentionally absent.
- **T-F4** The fakes: `FakeEmbedder`, `FakeVectorStore`, `FakeSource` (with error-injection map),
  `FakeSummarizer`, `FakeReranker` (**non-identity, deterministic reorder, call-recording** — not an
  identity reorder, TEST-STRATEGY specs), `FakeGpuLock` (no-op context manager, call-recording). *Done:*
  each passes the seam's contract test against itself.
- **T-F5** CI harness: unit+fake+golden on every push (no GPU/net); nightly job slot for real-adapter +
  eval. *Done:* green pipeline on an empty skeleton.
- **T-F6 — the enforcement job (do not skip this one).** A CI check, run on every push from every agent, that
  mechanically enforces CONVENTIONS §12's automatable items: (a) greps for vendor names outside their
  adapter file, (b) fails if a diff defines a type shadowing a `contracts/` name, (c) fails on
  `except Exception`/bare `except`, (d) fails on `os.getenv`/`os.environ` outside the Config loader, (e)
  fails if a diff touches a foundation-protected path (`.github/CODEOWNERS` — currently `contracts/`,
  `rag/config.py`, `config.example.yaml`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`) **without**
  an explicit "foundation-change" label, (f) fails if the real `Embedder`/`Summarizer`/`Reranker` adapter's
  `__init__` doesn't declare a `gpu_lock: GpuLock` parameter — a **necessary prefilter, not sufficient
  proof**: it only shows the parameter exists in the signature, not that `acquire()` wraps the real
  inference call; the actual guarantor of that is the per-adapter `FakeGpuLock.acquired` unit assertion
  (TEST-STRATEGY.md), (g) fails if a module source file has no sibling test file (a pure existence check,
  not a check of what the sibling imports or asserts), (h) fails on manual
  `chunk_id`/`block_id`/`summary_id` string-slicing
  outside `DocumentStore`, (i) **runs every non-adapter unit-test suite (all of `pyproject.toml`'s
  `testpaths`, e.g. M1, M3, M5, M7, M8, M9, plus `app`) with network mechanically blocked and GPU
  visibility stripped** — `pytest --p no:cacheprovider -p pytest_socket
  --disable-socket` (or equivalent) plus `CUDA_VISIBLE_DEVICES=""` in the job's env — so a test that
  bypasses its fake and reaches for a live Qdrant, a real HF model download, or an actual GPU **crashes with
  a socket/CUDA error** instead of silently passing on a CI box that happens to have network or a GPU
  attached; the `CUDA_VISIBLE_DEVICES=""` half also catches the same class of leak on a local dev machine
  that has a GPU physically present. *Done:* a deliberately-broken sample diff for each of (a)–(i) is
  committed as a fixture and confirmed to fail the job — the check is proven to catch what it claims to; for
  (i) specifically, the fixture is a unit test that constructs a real `QdrantVectorStore` instead of
  `FakeVectorStore` and is confirmed to fail on socket block, not just "would have been slow."
- **T-F7 — foundation-change protocol.** Once T-F1–T-F5 are reviewed and merged, tag the commit
  (`foundation-v0-frozen`). From that point, any PR touching a foundation-protected path — the list lives
  in `.github/CODEOWNERS` (currently `contracts/`, `rag/config.py`, `config.example.yaml`, `migrations/`,
  `rag/fakes/`, `fixtures/`, `ci/`, `.github/`; see GIT-WORKFLOW.md "Foundation freeze") — must (i) carry
  the "foundation-change" label, (ii) state which module's need is forcing the change, and (iii) get
  **your (the human's) explicit sign-off** before merge — T-F6(e) blocks the merge button until that
  label + approval exist. This is the one deliberate human-in-the-loop point in the *build process* — not to
  be confused with the product's agent-as-reasoner design, which has none (CONTEXT.md).

---

## M1a — Tests first (per module, before any implementation)

**Gate, not a virtue** (CONVENTIONS §0.7): each owner (A–E) writes and commits their module's test suite —
unit tests via fakes, per TEST-STRATEGY.md's per-module list, driving the module's *frozen* interface from
ARCHITECTURE.md/DATA-CONTRACTS.md and the M0 fakes — and gets it reviewed and merged **before writing any of
that module's implementation code**. Concretely, per module:

- The test file(s) import the module's public interface and the relevant fakes; since the module doesn't
  exist yet, they fail on import/collection (red), not on assertion — that's expected and is the point.
- The PR is reviewable on its own: does the test suite actually cover TEST-STRATEGY's list for this module
  (including the fault-injection points, non-identity `FakeReranker` assertions, and fixture-size
  requirements called out there), or is it a thin pass-through that would go green under a wrong
  implementation?
- **Verifiable per T-F6(g)** (existence: a sibling test file exists) and, at this milestone's exit, **by git
  history** (ordering: the test file's first commit predates the implementation file's first commit for
  every module — this is checked once at the M1a→M1b gate, not on every push, since it needs history rather
  than a working-tree diff).

*Exit gate:* every module (M1–M9) has a committed, reviewed, red test suite; zero implementation code exists
for any of them yet. Only then does M1b begin.

## M1b — Implementation (parallel; each ticket carries its own acceptance criteria)

Every ticket's Definition of Done = the checklist in CONVENTIONS §11 (including "test suite committed in
M1a, before this implementation existed") **plus** the specifics below.

- **T-A1 Harvester (M1)** — arXiv `Source` adapter + `harvest()`. *Accept:* dedup by base id (the `FakeSource`
  fixture contains two versions of one base id, so this isn't vacuous); resume skips seen ids; rate-limited;
  transient→retry, permanent→quarantine (via `FakeSource`'s error-injection map). Tested via `FakeSource`.
- **T-A2 IngestionOrchestrator (M9)** — wires the stages; `ingest(focus_area, cap)`. *Accept:* idempotent
  (re-run = no dupes), resumable — kill **within** one paper (after `chunked`, before `embedded`) and
  restart; assert via call-count spies that `Chunker`/`Summarizer` are not re-invoked for that paper and
  that later-queued papers still complete; **also resumable across the `stored`→`done` gap** — kill right
  after `DocumentStore.put()` succeeds but before `VectorIndex.upsert()` runs, restart, and assert
  `upsert()` runs for that paper and it reaches `done` with a matching `FakeVectorStore` entry
  (DATA-CONTRACTS `ingest_state` schema; TEST-STRATEGY.md); writes source-of-truth before derived index; acquires the
  injected **`GpuLock`** around no work of its own (the GPU-bound stages acquire it themselves) but wires it
  identically to every stage adapter so two GPU stages never co-run; computes and persists `relevance_score`
  (DATA-CONTRACTS §M5/§M9) per paper — a test asserts `papers.relevance_score` is non-null after an
  end-to-end fake run; **hoists `topic_query_vec` to once per run** (ARCHITECTURE.md §M9) — a call-count
  assertion on `FakeEmbedder` (via a spy) asserts `embed()` is called `N+1` times for `N` fixture papers (one
  `topic_query_vec` embed + one `summary_text` embed per paper), not `2N` (a test that only checks the
  final `relevance_score` values would pass even if the topic query were re-embedded every paper, since
  `FakeEmbedder` is deterministic — this call-count assertion is what actually catches the loop-placement
  bug). Tested end-to-end with all fakes (incl. `FakeGpuLock`) and a poisoned paper. **Corrected accept**
  (was: GPU-stage pipelining across papers via a spy/timing test — real VRAM measurements showed this
  requires MinerU and the Summarizer to co-reside, which reproduces a real CUDA OOM on this project's GPU
  budget; ARCHITECTURE.md §3 has the numbers): the Orchestrator runs **two sequential passes**
  (`parse_phase()` then `finish_phase()`, both over the whole corpus) instead, with `before_parse_phase`/
  `before_finish_phase` hooks so a composition root can evict the model the other phase doesn't need.
  Accept: a test proves the hook ordering (fires once, before/after the right phase's work) and that
  correctness/idempotency/resume still hold under the two-pass split (`rag/test_orchestrator.py`).
- **T-B1 Parser (M2)** — the Phase-0-chosen adapter behind the `Parser` interface + PDF/LaTeX routing +
  GROBID references. *Accept:* golden fixtures pass; every block has page+bbox; broken PDF → quarantine.
  *CI-allowlist:* introduces the real parser vendor (MinerU/Marker/Docling/GROBID) → add it to `VENDOR_RULES`
  in `ci/checks/vendor_isolation.py` in this same PR (§12; CI green doesn't prove isolation for an unlisted vendor).
- **T-C1 Chunker (M3)** — section-aware, parent-child links (`parent_id` always a `block_id`, per the
  multi-block anchoring rule in DATA-CONTRACTS), anchors preserved, equations/code never split,
  title+section-path prefix. **Do NOT implement contextual-header generation** — it's a V1 feature (PRD
  ADR-07), not a V0 toggle; `contextual_header` stays `None` on every chunk. *V0's only obligation here:*
  during the Spike-2 eval, tag retrieval failures that look context-related, and hand that rate to V1 as the
  monitoring signal (TEST-STRATEGY). *Accept:* boundary + parent-link + anchor tests on `ParsedDoc` fixtures,
  plus a test asserting `contextual_header is None` for every emitted chunk (catches accidental scope creep).
- **T-C2 Summarizer (M3B)** — real adapter over the local generation LLM (ADR-08/ADR-09), constructor takes
  `gpu_lock: GpuLock`, `summarize()`. *Accept:* non-empty `summary_text` on the golden-fixture set, **and**
  non-degenerate (differs across ≥2 fixtures, differs from that paper's own title/abstract verbatim —
  catches a hardcoded-constant or copy-the-abstract implementation that a bare non-empty check would miss);
  `FakeGpuLock` test proves the real adapter acquires `gpu_lock.acquire("summarize")` around its inference
  call; degenerate/figures-only `ParsedDoc` → `PermanentError` → quarantine, not a crash. Tested via
  `FakeSummarizer` for anything downstream (zero GPU).
  *CI-allowlist:* introduces the real generation-LLM vendor and a GPU-bound adapter → add it to `VENDOR_RULES`
  and confirm its class name is covered by `_ADAPTER_SUFFIXES` in `ci/checks/` in this same PR (§12; CI green
  doesn't prove isolation/lock-coverage for an unlisted vendor/adapter).
- **T-C3 Embedder (M4)** — real adapter (TEI/vLLM), constructor takes `gpu_lock: GpuLock`, `embed()` +
  `info`. *Accept:* the Embedder **contract test** passes against fake and real (determinism, length, dim,
  normalization); real adapter acquires `gpu_lock.acquire("embed")` around the batch call.
  *CI-allowlist:* introduces the real embedding vendor (TEI/vLLM client) and a GPU-bound adapter → add it to
  `VENDOR_RULES` and confirm its class name is covered by `_ADAPTER_SUFFIXES` in `ci/checks/` in this same PR
  (§12; CI green doesn't prove isolation/lock-coverage for an unlisted vendor/adapter).
- **T-D1 DocumentStore (M5)** — SQLite + blob filesystem;
  `put/get/get_blocks/get_block/get_chunk/get_summary/get_span/iter_papers`. *Accept:* `put` **atomic** —
  a test injects a failure between the `blocks` and `chunks` inserts inside one `put()` and asserts, via a
  **fresh connection**, zero rows across all four tables for that `paper_id`; `put` **idempotent under
  changed content** — re-put the same `paper_id` with different content and assert the store reflects the
  new content, not just that row counts are unchanged; `get_span(anchor)` returns the *full* anchoring
  block's text (not the snippet) — tested against a fixture block **>200 characters** so a `get_span` that
  just returns `anchor.snippet` would fail, and `anchor.snippet` is asserted to be a substring of
  `get_span`'s result; `get_block`/`get_chunk`/`get_summary` raise `ContractError` on an unknown id;
  round-trips a whole `PaperRecord` including `relevance_score`.
- **T-D2 VectorIndex (M6)** — Qdrant adapter behind `VectorStore`; hybrid dense+sparse fused by calling the
  shared `rrf_fuse` (`contracts/fusion.py`, `RRF_K=60` + `hybrid_dense_weight`) — **not** a local
  reimplementation of the formula; `rebuild()`; `SearchFilters` (typed, not a dict) implemented identically
  to the fake. The sparse channel indexes `VectorPayload.text` — the real chunk/summary passage text — not
  `section_path`, so keyword search actually searches passage content. *Accept:* the `rrf_fuse` unit test
  (owned by T-F1, run here too) plus the **cross-adapter smoke test** — upsert→search round-trips the id,
  `SearchFilters` cases filter identically on both, `rebuild()` reproduces results, and **top-1** agreement
  between `FakeVectorStore` and real Qdrant on an engineered fixture (not full-ordering equality —
  TEST-STRATEGY.md explains why that's unachievable). **Only** module importing `qdrant_client`.
  *CI-allowlist:* `qdrant_client` is the real vendor → add it to `VENDOR_RULES` in `ci/checks/vendor_isolation.py`
  in this same PR (§12; CI green doesn't prove isolation for an unlisted vendor).
- **T-E1 Retriever (M7)** — two methods sharing one pipeline: embed-query → hybrid → RRF → rerank (injected
  `Reranker` dependency; real adapter takes `gpu_lock: GpuLock`, `FakeReranker` — **non-identity,
  call-recording** — in tests) → resolve. `retrieve()` restricts to `kind="chunk"`, resolves each `Hit` via
  `DocumentStore.get_chunk`/`get_block` into a `GroundedResult` whose `passage_text` is the resolved
  `Chunk`'s own text (**not** a `get_span(anchor)` fetch — DATA-CONTRACTS §Provenance & structure). 
  `retrieve_papers()` restricts to `kind="summary"`, resolves via `get_summary`/`get` into an unanchored
  `PaperSearchResult` → attach provenance/citation. *Accept:* every `GroundedResult` grounded (resolvable
  anchor + citation) and its `passage_text` matches the resolved `Chunk.text` exactly (a fixture with a
  2-block chunk must show `passage_text` covers both blocks, not just the anchor's first block) — assert
  this via a call-recording spy on `DocumentStore` proving `get_chunk`/`get_block` were actually called for
  `retrieve()` and `get_summary`/`get` for `retrieve_papers()`, not by trusting the output shape alone;
  `evidence_tier=="A"` on `GroundedResult`, envelope shapes per DATA-CONTRACTS; empty corpus → `[]` for
  both methods; **rerank is verifiably wired in for both methods**: `reranker.calls` non-empty with expected
  candidate ids, and final order matches the fake's reversal and differs from pre-rerank RRF order (a test
  that doesn't check this would pass identically whether or not `rerank()` is ever called); `Reranker`
  accepted as a constructor argument (never hardcoded). Where `GroundedResult.score` comes from — the
  pre-rerank RRF score carried through unchanged, vs. a cross-encoder score the reranker would have to
  start returning — is Owner E's decision to make here; the frozen docs deliberately don't presuppose it
  (if a cross-encoder score is later surfaced, adding a nullable `score` field to `RerankCandidate` would
  follow this repo's existing forward-compat-nullable convention, e.g. `Chunk.contextual_header`).
  `retrieve()` runs the Spike-2 eval set. Because `McpServer` is an always-on composition root, its real
  `Reranker` is expected to stay **resident for the life of the process** — that's exactly the
  co-residence-within-budget the Phase-0 VRAM measurement (ARCHITECTURE §3, PHASE0-RUNBOOK S0) confirms,
  not something this ticket needs to separately satisfy.
  *CI-allowlist (Reranker):* the real `Reranker` adapter introduces the cross-encoder vendor and a GPU-bound
  adapter → add it to `VENDOR_RULES` and confirm its class name is covered by `_ADAPTER_SUFFIXES` in
  `ci/checks/` in this same PR (§12; CI green doesn't prove isolation/lock-coverage for an unlisted vendor/adapter).
- **T-E2 McpServer (M8)** — `search_papers`/`semantic_search`/`get_paper`/`get_span`. *Accept:* every tool
  returns records (never bare text); `search_papers` calls `Retriever.retrieve_papers()` and returns the
  typed `PaperSearchResponse` (`results` + `Coverage`); `semantic_search` calls `Retriever.retrieve()` and
  returns the typed `SearchResponse` (`results` + `Coverage`) — both DATA-CONTRACTS §M8, each with a test
  asserting `coverage.candidates >= coverage.returned`; `get_paper` returns the typed `PaperSummaryView`;
  `filters?` is `SearchFilters`, never a raw dict; a citation resolves via `get_span`. A test asserts
  `McpServer` never imports or reimplements the embed/hybrid/RRF/rerank pipeline itself — it only calls the
  two `Retriever` methods.

---

## M2–M4 — Integration, smoke, seed

- **T-INT1** Swap fakes for real adapters at the two composition roots; run the real-adapter contract tests.
- **T-INT2** Smoke test on **~200 papers** (fail fast — parse time is the one unmeasured variable). Verify
  idempotency, resume-after-kill, and quarantine on real data. Fix before scaling.
- **T-SEED** Full **30k** freshest-first seed (overnight/days). Monitor papers/hour, quarantine rate, GPU
  memory, Qdrant RAM. `relevance_score` is computed per paper by `IngestionOrchestrator` itself during this
  same run (T-A2 — not a separate step here); spot-check that `papers.relevance_score` is non-null corpus-wide
  before calling the seed done, so the later `relevance_filter` flip has real numbers to threshold on. Also
  log **query attribution** + spot-check harvest precision (PRD Levers "instrumenting the off choice").
- **T-EVAL** Run the 210-question retrieval eval (`fixtures/eval/`, gold `chunk_id`s resolved in Spike 2 —
  PHASE0-RUNBOOK.md) on the real corpus; confirm Recall@10 ≥ 0.85. This number is the baseline every future
  swap must beat.

---

## Post-freeze status & handover (2026-07-15)

This section is a snapshot for a new agent/session picking up the project — what's actually shipped, what's
in flight, and what's known-broken right now. It does not replace `git log`/`gh pr list` as the source of
truth for full history; it's a pointer into that history plus the currently-open items that need action.

**T-SEED / corpus state:** the real production corpus (`papers.db` + `blobs/`, outside this repo at
`research-system-rag-data/`) currently holds 809 papers plus a separate 100-paper T-EVAL-targeted set
(`RAG_INGEST_PAPER_IDS`/`ArxivSource.fetch_by_ids()`, PR #89) built specifically to contain the 210-question
eval set's source papers. Not yet at the 30k target above.

**T-EVAL status:** real, end-to-end runs (not simulated) against the 210-question eval set. Two real bugs
were found and fixed via this process — see `.phase0-data/teval-results.md` for the full writeup with
before/after metric tables:
1. `DocumentStore` stored a relative `markdown_path`, crashing 66% of retrieval calls from any process
   whose cwd differed from ingest's (T-DOC22, PR #91, merged). Fixing it alone raised single-passage
   Recall@10 from 0.30 → 0.60.
2. `Retriever.retrieve()`/`retrieve_papers()` reranked only the caller's `k` candidates instead of a real
   pool, so the reranker could never promote a passage the initial hybrid search ranked below `k` — every
   one of 30 real misses fit this shape (T-DOC24, PR #92, merged; **then immediately regressed production
   to 0% recall** because the real TEI reranker's hard max batch size (32) was never checked against the
   chosen pool size (50) — see T-DOC25 below, PR #94, still open as of this writing).

**Currently open PRs — need review/merge:**
- **PR #93 (T-DOC23)** — adds `DocumentStore.delete(paper_id)`, a proper cascade-delete (chunks/blocks/
  summaries/papers in one transaction), fixing the root cause of 59 orphaned papers (chunks/blocks with no
  matching `papers` row — `.phase0-data/known-issue-orphaned-chunks.md`) that were silently crashing ~8% of
  real queries to zero results. This is the code-only half; the data cleanup itself (59 papers' orphaned
  rows + 1,780 Qdrant vectors) has **already been applied directly to the real production DB**, independent
  of this PR merging — verified 0 orphans remain. Merging this PR just lands the reusable `delete()` method
  so the bug can't silently recur from a future raw `DELETE FROM papers`.
- **PR #94 (T-DOC25) — URGENT.** T-DOC24 (above) shipped `_RERANK_POOL_SIZE=50`, which exceeds the real
  deployed TEI reranker's hard max batch size of 32 — confirmed live, every real `retrieve()`/
  `retrieve_papers()` call has been failing outright (`PermanentError`, 422 from the reranker) since T-DOC24
  merged. This PR caps the pool at 32 (the real measured limit) and adds a real-adapter test
  (`enable_socket`-gated) that would have caught this before merge. **Main is currently broken for any real
  retrieval until this merges.**

**Real Recall@10 after all of the above (T-DOC22 + T-DOC23 data cleanup + T-DOC24 + T-DOC25), re-measured
2026-07-15: single-passage primary gate = 0.96 (n=100, MRR 0.7215) — GATE MET (target was ≥ 0.85).**
Zero retrieval errors across all 145 resolved questions (down from 96 errors pre-T-DOC22, then 12 post-T-DOC22/
pre-T-DOC23, then 145-of-145 failing during the brief T-DOC24-without-T-DOC25 regression window). Full
before/after numbers and methodology: `.phase0-data/teval-results.md` (not yet updated with this final run as
of this doc's writing — do that alongside merging PR #94). Other splits from the same run: full_set 0.890
(n=145), multi-paper lower-bound 0.733 (n=45), title-present 0.955 (n=89), title-absent 0.786 (n=56).

**Known open issues, not yet fixed (no PR open):** the quarantine-write crash guard and the M5 re-verification
are now formally ticketed as T-DOC32 and T-DOC33 below (see full text there — not restated here to avoid a
second source of truth). Remaining untracked item:
- Broader architecture question (queues/pipelining for more consistent GPU/CPU utilization across Pass 1/
  Pass 2) was investigated but not acted on — current mitigations (TEI eviction T-DOC19, adaptive batch
  sizing T-DOC21, PDF cache/prefetch T-DOC18) close most of the gap without the bigger restructuring; revisit
  only if a real utilization regression reappears.
- **T-DOC27 (merged — PR #104; production Qdrant NOT yet re-indexed with the new IDF weighting, a
  deliberate follow-up decision left for @MKamel1 after reviewing the throwaway-collection before/after
  numbers in the PR)** — the sparse/hybrid search channel doesn't do what ADR-01 (`PRD.md`) actually
  decided. ADR-01 chose Qdrant specifically because *"Qdrant treats sparse vectors (BM25/SPLADE) as
  first-class beside dense"* — but `rag/vector_index.py`'s `_sparse_vector` never uses that; it hand-rolls a
  naive raw term-frequency hash with no IDF weighting, so common words carry as much weight as
  discriminative ones. Flagged as a suspect in the T-EVAL recall-gap investigation (an under-weighted sparse
  signal can drag a good dense ranking down in RRF fusion) and in `PRD.md` ADR-11's "Candidate mitigations"
  list (Tier A — a real V0 gap, not a new idea). Fix: either switch to Qdrant's native BM25/SPLADE sparse
  vector support, or add real IDF weighting to the existing hash-based approach; either way needs a
  before/after T-EVAL re-run to confirm it actually helps (not just assumed).
- **T-DOC28 (merged — PR #96)** — `Coverage.candidates` is a no-op: `rag/mcp_server.py`'s `_coverage()` sets
  `candidates=len(results)`, always identical to `returned`, defeating the field's whole documented purpose
  (DATA-CONTRACTS.md / PRD.md §8.5: the real fused candidate-pool size *before* rerank/top-k truncation, an
  "anti-miss" transparency signal so a caller can tell it's seeing a sample). The method's own comment admits
  this is a workaround — reporting the real value needs a `contracts/`-level change (Retriever would need to
  expose the pre-truncation pool size), a foundation-change-protocol item, likely why it was left as a stub
  rather than flagged. More consequential now than when first stubbed: T-DOC24/25 made the pre-rerank pool
  size a real, tuned, incident-prone number (32, vs. ≤10 typically returned) — exactly the gap this field
  exists to expose, currently invisible to every caller. `rag/test_mcp_server.py`'s existing coverage test
  only asserts `candidates >= returned`, trivially true when they're always equal — doesn't catch this.
- **T-DOC29 (implemented — PR #97, merged)** — `app/` (the real composition-root/entrypoint code: `ingest.py`, `parse_phase.py`,
  `assembly.py`, `prefetch_pdfs.py`) has 8 real `os.environ.get(...)` calls outside `Config`, directly
  violating the documented "only `Config` reads env/files, no other module" invariant (CONVENTIONS.md §3,
  restated verbatim in `rag/config.py`'s own docstring: *"this repo has no env-var config path"*). The CI
  check meant to enforce exactly this (`ci/checks/env_leak.py`, check (d)) is scoped via
  `ci/checks/model.py`'s `PIPELINE_SCOPE_PREFIXES = ("rag/", "contracts/")` — `app/` was never added, so this
  drift has been silently unenforced. Not a bug today (all 8 are real, working, intentional config paths —
  `RAG_DB_PATH`/`RAG_BLOB_DIR`/`RAG_COLLECTION`/`RAG_INGEST_PAPER_IDS`/`RAG_PDF_CACHE_DIR`/
  `RAG_BATCH_SIZE_LOG`/`PREFETCH_TARGET`), but it's a documented invariant the codebase claims to hold and
  doesn't. Fix is a real decision, not just widening the CI check's scope: either (a) accept `app/`'s env-var
  usage as an intentional, narrower exception to CONVENTIONS §3 (composition-root/entrypoint code, not
  `rag/`'s pipeline modules) and update the doc to say so explicitly, or (b) actually route these through
  `Config` and widen `env_leak.py`'s scope to include `app/` for real.
- **T-DOC30 (verified — see LESSONS-LEARNED.md's 2026-07-15 entry, PR #98, merged)** —
  T-INT2's acceptance bar ("idempotency, resume-after-kill, and quarantine... verified on real data") was
  unproven: no test, no `LESSONS-LEARNED.md` entry, no doc reference beyond the ticket's own promise text, and
  the one candidate real-run evidence (`.phase0-data/100-paper-run-stats.md`) turned out on inspection to be
  two clean, uninterrupted invocations, not an OS-level kill. No informal record of a real crash/kill/resume
  was found anywhere either (searched every `LESSONS-LEARNED.md` copy under `.claude/worktrees/*`). Fixed by
  running a real, deliberate kill-mid-ingest test against 5 real arXiv papers (real GROBID/MinerU/TEI/Ollama/
  Qdrant, throwaway db/collection/blob dir) covering both T-A2 DoD-named gaps — after `chunked`/before
  `embedded`, and after `DocumentStore.put()`/before `VectorIndex.upsert()` completes — via a real `SIGKILL`
  against the real `python -m app.ingest` process, then a real resume. Both gaps verified clean (no
  re-invoked Chunker/Summarizer, no duplicate/orphaned Qdrant points, all 5 papers reached `done`); full
  numbers/timestamps in `LESSONS-LEARNED.md`. Resume *logic* remains additionally unit-tested with fakes
  (`rag/test_orchestrator.py`'s `test_resume_after_summarized_does_not_reinvoke_chunker_or_summarizer` /
  `test_resume_after_stored_reruns_upsert_and_reaches_done`) as before. One unrelated pre-existing bug was
  found incidentally (a parser paper_id-derivation fallback leaking into `DocumentStore`'s `chunks.paper_id`
  for a paper with no extractable arXiv self-citation) and flagged, not fixed — out of this ticket's scope,
  now covered by T-DOC31 (PR #103).
- **T-DOC31 (implemented — PR #103, merged — production sweep already run
  against papers.db, backed up first; found 0 rows to update, see LESSONS-LEARNED.md 2026-07-15 entry
  for why and for the real gap it surfaced instead)** — `rag/parser.py`'s `_derive_paper_id` (~line 415-423) falls back to a content
  hash (`hashlib.sha256(raw).hexdigest()[:16]`, call sites ~line 154/193) when a PDF has no
  regex-matchable `arXiv:YYMM.NNNNN` watermark, even though the orchestrator already knows the real
  `paper_id` before it ever calls `Parser.parse(raw)` — the frozen `Parser` interface just has no id-hint
  parameter to pass it through (the module's own docstring at `rag/parser.py:36-43` already flags this
  tension). Confirmed real occurrence during T-DOC30's live kill test (`LESSONS-LEARNED.md`, 2026-07-15
  entry): paper `2411.14665` landed 42 chunks in SQLite under `chunks.paper_id='211c443e9b22f24a'`
  instead of the real id. `Qdrant` stayed correct — `_upsert_record` always uses the harvester's real
  `paper_id`, never the parser-derived one — so retrieval/citation output is unaffected, but any
  SQLite-side `DocumentStore` join between `papers` and `chunks` by `paper_id` for that paper silently
  drops 42 rows, and the paper is invisible to anything keying off `papers.paper_id` (e.g. a future
  `DocumentStore.delete()` cleanup, T-DOC23). Fix: pass the orchestrator's known `paper_id` into
  `Parser.parse()` (a `contracts/parser.py` interface change, foundation-protected) so the hash fallback
  is never needed on the ingest path; reserve the hash purely for a truly id-less standalone-file case, if
  one still needs to exist at all. A full corpus sweep for any other papers already affected (grep
  `chunks.paper_id` values that don't match any `papers.paper_id` row) is part of this ticket's cleanup,
  same shape as T-DOC23's orphaned-chunks sweep.
- **T-DOC32 (merged — PR #101)** — the per-paper unexpected-exception
  safety net (PR #78) that wraps each paper's pipeline stages isn't itself safe on its own error path: the
  `quarantine()` write *inside* that guard is not crash-guarded, so a failure while writing the quarantine
  record (e.g. a missing table, a locked DB) can still crash the whole ingestion run instead of just that
  one paper. This already happened once for real, for one specific cause (a missing table), fixed narrowly
  by T-DOC17's `quarantine.error` diagnostics work (PR #83) — the *general* case (any exception raised by
  the `quarantine()` write itself, not just that one cause) remains open. Fix: wrap the `quarantine()` call
  itself in a narrower try/except that logs and continues (never re-raises past the per-paper boundary),
  with a test that injects a failing quarantine write and asserts the run continues to the next paper
  instead of crashing.

  **Update:** PR #101 found the ticket's own premise didn't match `main` — the "per-paper
  unexpected-exception safety net (PR #78)" it references was never actually merged (a branch-stacking
  mishap: its base PR merged before PR #78's own commits landed on top, and the updated branch was never
  re-merged). What's actually on `main` is four narrower `TransientError`/`PermanentError`-specific
  retry-then-quarantine methods (T-DOC12/13) that all route through one shared write path,
  `SqliteIngestState.quarantine()` — that's what PR #101 crash-guards instead. **Merged.**
- **T-DOC33 (verified, merged — see `LESSONS-LEARNED.md`'s 2026-07-15 entry, PR #102)** —
  highest priority of this batch, it's the literal V0 ship criterion. M5's own exit bar (`WORK-BREAKDOWN.md`
  Milestones table above: *"an agent answers a factual question about an ingested paper with a correct,
  verifiable citation at ~0 API cost — and you use it"*) had never been independently re-verified end-to-end
  since the T-DOC22/23/24/25 fixes landed — every number cited above (Recall@10=0.96, zero retrieval errors)
  came from the offline T-EVAL harness calling `Retriever` directly, not from a real MCP client. Turned out
  this couldn't have been checked before this ticket even if someone had tried: `app/serve.py` had no MCP
  transport loop at all (its own comment said so) — no real MCP client of any kind could connect. Fixed by
  adding a real FastMCP stdio transport to `app/serve.py` (no new wiring — `build_mcp_server`'s own
  composition root, untouched) and a reusable real MCP client, `app/mcp_verify_client.py`. Ran it against
  real production data (809-paper `papers.db`/Qdrant `"papers"` collection): asked a real factual question
  about an ingested paper, got back a grounded, typed response whose citation resolved via `get_span` to
  real stored text and whose content independently verified correct against the source paper. Full
  transcript and methodology in `LESSONS-LEARNED.md`.
- **T-DOC34 (merged — PR #100)** — PRD.md ADR-11's "Candidate mitigations" list (Tier A — real V0 gaps, decided
  but never built) has a second item beyond the sparse/BM25 gap T-DOC27 already covers: **summary-level
  routing exists as a capability but is never automatically enforced.** `Retriever.retrieve_papers()` /
  `McpServer.search_papers` can narrow a query to the relevant papers *before* chunk-level retrieval and
  reranking run — which would shrink the reranker's candidate pool and reduce the chance of the
  T-DOC24/25-class incident recurring at larger corpus scale — but `PRD.md` §11A is explicit that this
  routing is "delegated to the agent-as-reasoner... no server-side auto-rewrite": today `semantic_search`
  always searches the full chunk index regardless of whether the calling agent could have scoped it via
  `search_papers` first. Not broken (both tools work correctly on their own), but the mitigation ADR-11
  actually decided on doesn't do anything today unless the calling agent happens to sequence its own tool
  calls that way — which is not something V0's own MCP tool descriptions currently guide it toward. Fix:
  either (a) update `McpServer`'s tool descriptions/docstrings to explicitly instruct the calling agent to
  route through `search_papers` first for multi-paper-scoped queries (a docs-only fix, consistent with
  "agent-as-reasoner, no server-side arbitration" — CONTEXT.md), or (b) if that proves insufficient in
  practice, revisit the "no server-side auto-rewrite" decision itself — but (b) would need a documented ADR
  change, not a silent behavior change, given ADR-11 explicitly decided against it once already.
- **T-DOC35 (implemented — PR #107, merged — all 59 papers re-ingested and verified;
  depends on T-DOC31/PR #103, still open, merging before/alongside this one)** — **59 papers are
  `ingest_state='done'` with a `summary` row but zero `blocks`/
  `chunks`** — surfaced during T-DOC31's production sweep (PR #103; count matches the 59 papers T-DOC23's
  orphaned-chunks cleanup deleted rows *for*, strongly suggesting these are the same papers whose
  chunk/block rows were removed as orphans but whose `papers`/`summaries`/`ingest_state='done'` rows were
  left behind — so the orchestrator's resume guard now treats them as fully ingested and skips them, while
  they contribute nothing to retrieval). Effect: these 59 papers are silently unretrievable — a real hole
  in the 809-paper corpus, invisible to any check that only counts `ingest_state='done'`. Fix: (1) identify
  the 59 via `SELECT p.paper_id FROM papers p LEFT JOIN chunks c ON c.paper_id=p.paper_id WHERE
  c.paper_id IS NULL` (confirm against blocks too); (2) reset their `ingest_state` (and clear the stale
  `summary` rows) so the orchestrator re-ingests them from `parsed` onward on the next run, OR run a
  targeted re-ingest via `RAG_INGEST_PAPER_IDS` against the real pipeline (real GPU/GROBID/TEI/Ollama/
  Qdrant, same infra T-DOC30/33 used); (3) back up `papers.db` first (T-DOC23/T-DOC31 precedent); (4) add a
  corpus-integrity check (a `done` paper must have ≥1 chunk) so this class of silent hole is detectable
  going forward — candidate for a standing diagnostic, not just a one-off. Also verify the matching Qdrant
  `"papers"` collection ends up with vectors for these papers after re-ingest.
- **T-DOC36 (WON'T DO — deferred by @MKamel1 2026-07-16: a hosted Google embedder breaks the V0 ~$0-API-cost, local-only invariant; revisit only as an explicit V1+ constraint change) — evaluate Google's Gemini API File Search + Gemini Embedding 2 against the V0
  stack (research/ADR task, not a code change yet).** Google shipped a fully-managed RAG system (Gemini API
  **File Search Tool**, Nov 2025; made multimodal early 2026) that does chunking + embedding + vector
  indexing + citation server-side, powered by the new **Gemini Embedding 2** model (all-modality, 100+
  languages, native MRL, 3072-dim). Two distinct questions for V0/V1, both currently unanswered and worth a
  written ADR before any adoption: (a) **as an embedding-model swap** — does Gemini Embedding 2 (or the
  open on-device **EmbeddingGemma**) beat the Spike-2-locked Qwen3-Embedding-4B on *this* corpus's T-EVAL
  set? The whole V0 design already treats the embedder as a swappable seam behind a fixed interface, and
  T-DOC27's throwaway-collection harness is exactly the before/after rig to test this — but note the
  **~0 API cost** V0 constraint (CONTEXT.md): a hosted Gemini embedder breaks the local-only, zero-API-cost
  invariant, so this is a V1+ consideration or an explicitly-flagged constraint change, not a silent V0
  swap. (b) **as a whole-pipeline alternative** — File Search would replace most of the self-hosted
  ingest→parse→chunk→embed→retrieve stack; this contradicts V0's deliberate local-only/self-hosted/zero-API
  posture and its provenance-anchor contract (block-bbox+snippet grounding — does File Search's page-level
  citation meet CONTEXT.md's anchor requirement?), so it is almost certainly **not** a V0 move, but is worth
  a documented decision (a new ADR in PRD.md §12) so a future session doesn't rediscover this question from
  scratch. Deliverable: a short ADR + a before/after T-EVAL number for (a) if the API-cost constraint is
  waived for a one-off benchmark run.

### T-DOC37–T-DOC42 — surfaced by the 2026-07-15 independent architecture + RAG-enhancement reviews

Two independent reviews (an Opus architecture/plan-consistency review and an Opus RAG-enhancement + Google-eval
review; full reports in the gitignored `reviews/` dir) converged on one theme: **the design is sound but the
"V0 ship criterion met" claim rests on weak evidence.** The 0.96 Recall@10 is offline, measured on a 100-paper
set built by `fetch_by_ids` *specifically to contain the gold papers* (`teval-results.md:38-44`), over a
denominator that dropped 53/210 `no_match` questions (plausibly the hardest), with title-absent (0.786) and
multi-paper (0.733) splits *below* the 0.85 gate — and the "real MCP works" proof (T-DOC33) was n=1. These
tickets are the concrete follow-ups.

- **T-DOC37 (DONE — GATE MET UNDER REALISTIC NOISE; PR #109 for T-DOC37+42 merged).** Re-ran all 210
  questions against the **real 809-paper production `"papers"` corpus** (READ-ONLY) — the gold papers now sit
  among ~709 relevant-but-wrong causal-methods papers we never wrote questions for, and **those ~709 ARE the
  distractors** (the distractor-noise methodology the human operator asked for: gold papers + the rest of 809
  as noise, delta vs a gold-only corpus = the noise-robustness signal). For a clean same-harness delta, also
  ran a throwaway gold-only 100-paper copy (`e2e_teval_goldonly`, READ-ONLY vector copy, no re-embed).
  **Result: single-passage Recall@10 = 0.952 on the real 809 corpus, identical to 0.952 gold-only — the 709
  distractors cost ZERO recall on every split** (deltas 0 to +0.02, within noise; MRR down ≤0.008). Validated
  the search really ranges over 809 (19 distinct distractor papers surface, 5% of top-10 slots, 58/151
  questions hit ≥1 distractor). Real MCP round-trip (`app/serve.py` + `app/mcp_verify_client.py`, T-DOC33)
  spot-checked on 4 questions against the 809 corpus — all returned a gold paper as top hit + resolved span.
  Under **multi-gold scoring (T-DOC42) every split clears 0.85** (single 0.952, multi-paper 0.957,
  title-present 0.947, title-absent 0.965, full 0.954); under single-gold, multi-paper (0.761) and
  title-absent (0.807) sit below 0.85 — precisely the two splits the single-gold scoring artifact depresses.
  Gate relabelled in `teval-results.md` (new "distractor-noise robustness eval (2026-07-15)" section, the
  full side-by-side split table + deltas). A5 (T-DOC34 summary-routing effect on multi-paper) not folded in —
  the multi-paper split is now explained by the scoring artifact, not a routing gap, so it's deferred as
  non-blocking. **Depended on T-DOC35** (satisfied: `chunks` has 809 distinct paper_ids = `papers` count, no
  orphan hole).
- **T-DOC38 (merged — PR #106) — BLOCKER, small, high-value read-path robustness.** `rag/retriever.py:106-107,
  157-158` raise `ContractError` and zero the *entire* query when a single reranked hit can't be resolved
  (e.g. an orphaned/stale candidate). The ingest side quarantines bad papers; the read side never mirrored
  that invariant — already measured crashing ~8% of eval queries to zero results. Fix: **skip-and-continue**
  (drop the unresolvable hit, log it, return the rest) instead of raising. Pure `rag/` code, no infra.
- **T-DOC39 (merged — PR #106)** — the rerank batch ceiling (32) leaks a vendor limit into the pure module and is
  incompletely guarded: `retriever.py:91,143`'s `max(k, 32)` means **any caller passing `k>32` re-triggers
  the same 0%-recall 422 crash T-DOC24/25 caused** (MCP exposes `k` unclamped). Fix: move the batch ceiling
  into `TeiReranker` (where the vendor limit belongs), clamp `k` there, and add a real-adapter contract test
  asserting the reranker's actual max batch size (the test that would have caught T-DOC24 pre-merge). Pure
  code + one `enable_socket`-gated adapter test. **Touches `rag/retriever.py` — coordinate with T-DOC38
  (same file); build them together or sequence T-DOC39 after T-DOC38.**
- **T-DOC40 (implemented — PR #108, merged)** — `DocumentStore.delete()` (T-DOC23) removes SQLite rows only, **not** the
  matching Qdrant vectors, so a deleted paper's orphaned vectors still surface and crash `get_chunk` — the
  same orphan-recurrence class T-DOC23 was meant to close, and the likely root cause of the T-DOC35 hole.
  Fix: make delete atomic across SQLite **and** Qdrant, and turn on `PRAGMA foreign_keys=ON` (nothing in the
  codebase enables it, so a stray raw `DELETE FROM papers` silently orphans children — `migrations/`, a
  foundation path). Foundation-touching → PR left open for @MKamel1.
- **T-DOC41 (SPIKE RUN 2026-07-17 — measured x2, HOLD (upgraded rationale); see `reviews/T-DOC41-CONTEXTUAL-RETRIEVAL-SPIKE.md`. **Follow-up (same day, GPU-free):** rewrote the 40 questions topic/title-absent -> baseline headroom appeared (Recall@10 1.000 -> 0.900); headered arm small but consistent positive (Recall@10 +0.025, MRR +0.047; equations MRR +0.055) — inside the n=40 noise band, directionally encouraging, not significant. Decisive test is corpus SCALE, not more questions at 809. **Recommendation: never run headers standalone (~18 GPU-days at 30k); fold a headered arm into the next big re-ingest and measure at scale with the topic-absent slice.** Approach A (summary-conditioned headers) measured against full-corpus distractors: passage Recall@10 1.000 -> 1.000, MRR 0.841 -> 0.838 (noise). **The eval is SATURATED — baseline already retrieves the gold equation chunk top-10 for 40/40, so Recall@10 cannot improve; the null is INCONCLUSIVE, not a refutation.** Headers were high quality (prompt is not the limiter). Cost measured: ~11.7 GPU-hours at 809 papers, ~18.1 GPU-DAYS at the 30k target. Blocker is the eval, not the header path (which is built + merged: `rag/contextual_header.py`, `app/reembed_experiment.py`, re-runnable in ~45min). **Prerequisite for any future go/no-go: a topic/title-absent equation eval with real headroom.** Approach B NOT justified — costs strictly more than A, whose benefit is currently unmeasurable) — highest-impact retrieval-quality lever, but a real design decision, not a blind
  build.** Contextual Retrieval (prepend a local-LLM-generated 50–100-token document-context to each chunk
  *before* embedding; Anthropic measured −49%/−67% retrieval failures) is the best fit for this corpus's hard
  case — bare LaTeX/equation/algorithm blocks that lack situating context (recall correlates strongly with
  chunk size: 0.90 smallest quartile vs 0.65–0.76 largest). Maps to `PRD.md` ADR-07. Requires a corpus
  re-embed and a chunker change → **wants a design/brainstorm pass and an explicit go/no-go before
  implementation, and a before/after T-EVAL** (via T-DOC37's harness) to prove it helps. V0-cost (local LLM)
  or V1.
- **T-DOC42 (DONE — the multi-paper "weakness" was mostly a scoring artifact; PR #109 for T-DOC37+42 merged;
  @MKamel1).** Confirmed: the multi-paper split *was* partly a measurement artifact. Added
  `additional_gold_paper_ids` to all **60** multi-paper ground-truth records (**82 co-gold labels**),
  sourced from each record's own `section_path`, which authoritatively names every co-source paper by arXiv
  ID (more reliable + complete than parsing `question_text`). Single-paper records untouched (verified none
  name a second paper), so the single-passage gate methodology is unchanged. **Effect: multi-paper jumps
  0.739 → 0.935 (gold-only) / 0.761 → 0.957 (809); title-absent 0.807 → 0.965 (809)** — ~⅔ of the apparent
  weakness was single-gold miscounting. **`no_match` denominator bias quantified: NOT hard-skewed** — 151/210
  resolve (72%); the 55 `no_match` drops are 45% hard/expert vs 56% among scored, dominated by
  Method-Comprehension (17/55) equation/LaTeX excerpts that fail verbatim substring-matching after NFKC
  normalization — a fixture-normalization artifact orthogonal to retrieval difficulty, not an easy-survivor
  skew. So 0.73 was never a retrieval defect to chase. Touches `fixtures/eval/` (foundation) → PR left OPEN
  for @MKamel1 with the `foundation-change` label. Full analysis + tables in `teval-results.md`.

- **T-DOC51 (implemented — PR #113, merged; `python -m app.ingest --parse-workers N`, default 1) **[OG-19 determinism: RESOLVED 2026-07-17 — N>1 safe; anchor round-trip proven by construction + all 25,387 real anchors verified, see LESSONS-LEARNED]** — Pass-1 throughput: run N=3 concurrent parse workers (+63%, measured).** The
  Pass-1 GPU-underutilization problem (`.phase0-data/pass1-gpu-underutilization.md`, diagnosed 2026-07-14:
  27-38% avg GPU util, ~45% of samples at 0%) is **solved** — by parallelism, not by tuning MinerU. A
  rigorous serialized benchmark (2026-07-16; one GPU, verified clean before every run, TEI+Ollama evicted,
  warm-up excluded, fixed 25-paper/488-page set) measured: **1 worker = 171.9 pages/min (baseline,
  confirmed) → 3 concurrent `pipeline` workers = 280.7 pages/min = 1.63x**, GPU idle collapsing 45.2% →
  13.4%. Root cause it exploits: MinerU renders each doc with **exactly 1 process**
  (`pdf_image_tools.py`: `MIN_PAGES_PER_RENDER_PROCESS=30`, `page_limited_threads = total_pages // 30` → any
  paper <60pp → 1) while the GPU idles; a second/third worker's GPU work fills that CPU-render gap.
  **Quality risk is nil in principle** — identical model, identical `pipeline` backend, identical settings;
  the same code path run as N processes over disjoint `paper_id`s (empirically confirmed: block/text
  identical except a <0.03% LaTeX-formula-boundary nondeterminism on one 56pp paper, consistent with GPU
  batch-composition floating-point nondeterminism, not content loss — worth watching at 30k scale).
  **All other levers were tested and lose** (do not retry — full numbers in the doc): window-size 64→192
  null; `MINERU_VIRTUAL_VRAM_SIZE=32`/ratio16 **OOMs at both 2 and 3 workers** (batch activations dominate
  VRAM and scale with page size — one 56pp paper spiked a single worker to 13.2GB); ratio4 halves
  per-worker VRAM but its smaller batches cancel the extra overlap (4w=265.6, 6w=275.7 — both lose to
  3w=280.7); tuned `vlm` backend is **4.75x slower** (its 92.7% util proves it was never KV-starved — a
  1.2B model decoding every page is ~7x more compute than specialized single-pass CNNs, so PagedAttention/
  continuous batching can't help); external parsers rejected on quality (`reviews/PARSER-ALTERNATIVES-EVAL.md`).
  **Ceiling reached: GPU-seconds of real work are invariant (~84-91s) across every config** — the residual
  13-16% idle is intra-GPU kernel gaps, not render starvation (proven: 6 workers gained nothing over 3).
  Beyond ~281 pages/min needs a second GPU, not software.
  **The actual work in this ticket is the integration, which is NOT trivial and is the reason this is a
  ticket and not a config change:** `app/parse_phase.py` runs Pass 1 as a single subprocess today; N workers
  sharing `papers.db` is unsafe as-is because `SqliteIngestState.checkpoint()` is a non-atomic
  read-merge-write whose `threading.Lock` only serializes **within** one process (the same hazard
  `app/prefetch_pdfs.py`'s docstring already documents for a second writer). Disjoint `paper_id` slices are
  *probably* safe since each row is touched by exactly one worker, but that needs a real design decision —
  options: (a) shard `refs` across N subprocesses with disjoint paper_ids and rely on row-disjointness,
  (b) make `checkpoint()` an atomic UPSERT, (c) per-worker DBs merged post-run. Touches `app/parse_phase.py`
  and possibly `rag/ingest_state_sqlite.py` → **foundation-adjacent, needs @MKamel1 sign-off**. The
  benchmark sidestepped it entirely with disjoint slices + throwaway output. Reusable benchmark scripts are
  in the session scratchpad (`pipeline_worker.py`, `run_pipeline_multi.py`, `evict_gpu.sh`,
  `compare_quality_pipeline.py`).
  **Update (PR #113): the safety concern above resolved in favor of option (a).** Reading the code
  confirmed `SqliteIngestState.checkpoint()`'s read-merge-write runs inside one implicit transaction, WAL is
  on, and `sqlite3.connect`'s default 5s busy_timeout serializes cross-process writers — and, decisively,
  disjoint `paper_id` shards mean no two workers ever touch the same row, so the race cannot occur by
  construction. The implementation shards `refs[i::n]` (round-robin, provably disjoint-and-complete, unit
  tested), spawns N `app.parse_phase` subprocesses, and **fails the whole run if any shard exits non-zero**
  (a dead/OOM'd shard must never silently ship a partial corpus). `app/`-only, non-foundation.
  **OPEN ACCEPTANCE CRITERION before a full 30k seed run (OG-19, `reviews/OPERATIONAL-GAPS.md`): the
  "quality risk is nil" claim is true bit-for-bit only on 24/25 benchmarked papers.** One 56pp paper showed
  a <0.03% (2/403 blocks) LaTeX-formula-boundary shift under *every* multi-worker config (never at 1 worker),
  consistent with GPU batch-composition floating-point nondeterminism. It has **NOT** been verified that such
  a boundary shift can never (a) corrupt a formula's extracted LaTeX or (b) move a block edge such that an
  `Anchor`'s quotable snippet no longer round-trips against its source — which would breach CONTEXT.md's
  "no anchor → the item is invalid" contract. **Required before N>1 is used for a real seed run:** parse a
  math-heavy sample under N=1 vs N=3 and confirm every multi-worker block still yields a valid, round-trip-able
  `Anchor` (or, if it can't be guaranteed, pin determinism — fixed batch composition / deterministic kernels,
  at a throughput cost — or accept-and-document the risk explicitly). N=1 (the default) is unaffected and
  needs no such check.

**Key `.phase0-data/` docs for a new agent to read first** (all gitignored/local, not in git history):
`teval-results.md` (T-EVAL methodology + full before/after numbers), `known-issue-orphaned-chunks.md`
(the T-DOC23 bug), `known-issue-pass2-oom.md` (Pass 2 VRAM history), `pass1-gpu-underutilization.md` (the
GPU-utilization investigation series behind T-DOC16/18/19/21).

### T-DOC43–T-DOC50 — operational readiness gaps surfaced by the 2026-07-15 100-paper GPU-utilization run

A real 100-paper end-to-end ingest run (full log in the gitignored `reviews/OPERATIONAL-GAPS.md`, OG-1..OG-11)
converged on one theme: **the system is built to pass tests, not yet to be operated.** No preflight/doctor
check, no auto-provisioned DB, no offline/cache-first ingest path (it re-hits arXiv for metadata even when
the PDF is already local — which is what got this exact run 429'd and killed), no built-in GPU/perf
telemetry, no run summary. 11 gaps, grouped into 8 tickets below where several gaps are genuinely one unit of
work (OG-1 preflight + OG-8 service lifecycle share one "the run should own its own readiness" fix; OG-5
telemetry + OG-6 run-events + OG-7 run-summary share one underlying counters/reporting layer), kept separate
otherwise. **T-DOC48 (OG-9, offline/cache-first ingest) is the highest-value ticket in the batch** — it both
blocks the ~1,700-PDF cached-corpus backlog from being processable at all, and directly caused the 429 that
killed this run.

- **T-DOC43 (implemented — PR #117, merged; `python -m app.doctor` + `run_preflight()` in `app.ingest`, `--no-preflight`/`--no-auto-start`) — 🔴 operational preflight/doctor + full service lifecycle (OG-1 + OG-8).** Before
  launching, the operator had to manually check disk headroom (`df -h`), GPU/VRAM headroom (`nvidia-smi`),
  the GPU lock not held (`.gpu.lock`), every required container up (`docker ps`: TEI-embed, TEI-reranker,
  GROBID, Qdrant) and Ollama reachable (`curl localhost:11434/api/ps`) — none of which `app.ingest` checks
  itself. Not hypothetical: `LESSONS-LEARNED.md` (T-DOC30) records a real run where GROBID's container was
  silently down and quarantined all 5 papers before anyone noticed. The one piece of lifecycle code that
  exists, `app/tei_lifecycle.py`, only manages the TEI containers around a run — GROBID, Qdrant, and Ollama
  have no managed lifecycle at all, so the same "must already be up" assumption OG-1 works around is baked
  into it. Fix: a `python -m app.doctor`/`--preflight` gate on `app.ingest` that health-pings every required
  service (both TEIs, GROBID, Qdrant, Ollama) plus disk/VRAM/GPU-lock, refusing to start (or `--force`) with
  one clear message naming what's missing instead of quarantining papers or crashing partway; extend
  `app/tei_lifecycle.py`'s start/stop pattern to the other services (at minimum a health-gate, ideally
  start-if-down for the ones safe to auto-start).
- **T-DOC44 (implemented — PR #117, merged) — 🔴 DB auto-provision (OG-2).** Pointing a run at a fresh `papers.db` crashes with
  an opaque `no such table` — the `IngestionOrchestrator`/`DocumentStore` never creates or verifies schema —
  so `migrations/migrate.py <db>` has to be run by hand first, and re-running `migrate` on an
  already-migrated DB fails loudly by design (forcing an `rm -f db db-wal db-shm` workaround). Fix: detect an
  absent/unmigrated DB on startup and either auto-migrate or fail with an actionable message ("database not
  initialized — run `migrations/migrate.py <path>`"); add an idempotent `migrate --if-needed` mode to remove
  the re-run foot-gun.
- **T-DOC45 (implemented — PR #117, merged; CLI `--limit N`) — 🟠 run-scoped corpus cap (OG-3).** `corpus_cap` is a foundation `Config` value
  (30000) with no per-run override — no `--limit 100`/`RAG_CORPUS_CAP`. Capping a run at exactly 100 papers
  required prefetching 100 PDFs, extracting their ids, and feeding them via `RAG_INGEST_PAPER_IDS` — the
  only lever, and an indirect one. Fix: a run-scoped cap override (`RAG_CORPUS_CAP` env or
  `app.ingest --limit N`) for test/benchmark/smoke runs.
- **T-DOC46 (implemented — PR #117, merged; `--scratch`) — 🟠 scratch/benchmark run mode (OG-4).** Running without touching production
  required hand-wiring four things: a throwaway `RAG_DB_PATH`, `RAG_BLOB_DIR`, a disposable `RAG_COLLECTION`
  (e.g. `e2e_gpuutil_100`), and pointing the prefetcher's dedup at the **real** `papers.db` read-only — a
  bespoke orchestration script, where getting any one wrong risks mutating production. Fix: a first-class
  `--scratch`/bench mode that provisions an isolated DB + blob dir + uniquely-named Qdrant collection
  automatically (and tears them down/lists them for cleanup), with production used read-only for dedup.
- **T-DOC47 (implemented — PR #119, merged; `app/telemetry.py`: `GpuSampler` + `RunEventLog` (`--events-path`) + `summarize_run`. Follow-up: telemetry is tagged at the coarse Pass-1/finish-phase boundary; the finer summarize/embed/store split OG-5 names needs a stage hook inside `finish_phase()`) — 🔴 run instrumentation & reporting (OG-5 + OG-6 + OG-7).** The system cannot
  answer "was the GPU well-utilized during this run" about itself — it emits no per-stage
  GPU-util/timing/papers-per-hour telemetry, no structured run-start/stage/run-end events, and no
  end-of-run summary. Confirming GPU utilization required wiring an **external** workstation-dashboard MCP
  and hand-stamping `RUN_START`/`PREFETCH_*`/`INGEST_START`/`INGEST_END`/`RUN_END` timestamps to a
  `timestamps.env` for post-hoc correlation; the production data dir already contains a hand-rolled
  `gpu_cpu_sampler.sh` + `gpu_cpu_perf_log.csv` — evidence this is a recurring, previously-unmet need, not a
  one-off. End-of-run outcome (done/quarantined/stuck) likewise has to be hand-queried
  (`SELECT stage, count(*) FROM ingest_state GROUP BY stage`) — directly relevant given Pass 1 (MinerU) is
  historically only ~44% GPU-utilized (`pass1-gpu-underutilization.md`). Fix: built-in per-run performance
  telemetry (sample GPU util/VRAM/power on an interval, tag by pipeline stage), structured JSON-line run
  events (run id, stage, timestamp, paper counts) external monitors can correlate against, and an
  end-of-run summary (N done, N quarantined + reasons, wall-clock, papers/hour, SQLite↔Qdrant consistency
  check) — three faces of one "the run can report on itself" capability, sharing the same underlying
  counters, worth building together.
- **T-DOC48 (implemented — PR #115, merged; `<paper_id>.json` sidecars, cache-first `harvest_refs`) — 🔴 HIGHEST-VALUE, offline/cache-first ingest (OG-9).** There are 2,542 PDFs
  already downloaded in `research-system-rag-data/pdf_cache` but only 809 processed — ~1,700 papers sit
  downloaded-but-unprocessed — yet a run over them still failed, because the pipeline re-fetches each
  paper's **metadata** from arXiv even when its PDF is already local. Root cause: `PaperRef`
  (`contracts/harvester.py`) has 11 required fields (title/abstract/authors/categories/published/updated/
  pdf_url/version); `app/prefetch_pdfs.py` writes only `<paper_id>.pdf` and discards the metadata it fetched
  to decide the download, so nothing local carries the `PaperRef` — `app/parse_phase.py:39` and
  `app/ingest.py` are therefore forced to call `ArxivSource().fetch_by_ids()` (network) before they can parse
  a PDF already on disk. Consequence, observed: that forced re-fetch got HTTP 429 (arXiv refusing even a
  single-id probe) and killed the whole run. Highest-value ticket in this batch — it both blocks the
  ~1,700-PDF cached-corpus backlog from being processable at all AND directly caused the run-killing 429
  (T-DOC49). Fix: persist harvested `PaperRef` metadata alongside each cached PDF (a `<paper_id>.json`
  sidecar, or a local `refs` table) at download time, and make ingest cache-first — if the PDF *and* its
  metadata are both local, process fully offline with zero arXiv calls.
- **T-DOC49 (implemented — PR #115, merged; bounded exp. backoff around `fetch_by_ids`. Follow-up: honor `Retry-After` header needs `rag/harvester.py`) — 🔴 arXiv 429 run-level backoff/resume (OG-10).** A single transient 429 from
  arXiv (metadata fetch) raised `TransientError` and killed the entire `app.ingest` run (Pass 1 crashed →
  `CalledProcessError` → exit); `ArxivSource` has per-call retry but no run-level "arXiv is throttling —
  pause and resume" handling. Fix: treat arXiv 429 as a pause-and-resume condition at the run level (honor
  `Retry-After`, back off, resume from `ingest_state` — resume already exists). Kept separate from T-DOC48:
  cache-first removes the metadata re-fetch that triggered *this* 429 for the cached backlog, but this is
  the general run-level resilience fix for any live arXiv call (harvest, non-cached papers) that gets
  throttled.
- **T-DOC50 (implemented — PR #115, merged; `--max-idle N`) — 🔴 prefetch stall visibility (OG-11).** With dedup pointed at production, only 4
  genuinely-new papers were available; prefetch downloaded the 4 and logged "below target, sleeping 3600s
  before re-harvesting" — it would have sat idle an hour making zero progress while looking healthy, caught
  only because the operator noticed no GPU spike, not because any telemetry flagged it. Fix: surface
  stalled/waiting state loudly (a "prefetch stalled: 4/100, only N new available, next attempt in 3600s"
  status line / non-zero signal), a `--max-idle` bound, and a "target unreachable — only N papers available"
  terminal message instead of an invisible hour-long sleep.

### T-DOC52–T-DOC55 — remaining operational gaps from the 2026-07-15/16 100-paper run and Pass-1 benchmark (OG-12..OG-20)

Continuation of the operational-gaps log (`reviews/OPERATIONAL-GAPS.md`, gitignored) started under
T-DOC43–T-DOC50 (OG-1..OG-11, unmerged PR #110). This batch covers OG-12 through OG-20. OG-18 (the
data-parallel-workers positive result) is already ticketed as **T-DOC51** (unmerged PR #111) and is not
duplicated here. OG-19 (multi-worker formula-boundary nondeterminism) is not a standalone feature — it
qualifies T-DOC51's "zero quality risk" claim and belongs in that ticket's acceptance criteria; **T-DOC51
currently exists only on PR #111's branch, not on `main`, so it could not be amended in place from this
branch** — see the PR body for the exact caveat text to fold in once #111 lands (or is rebased onto this
work). OG-21 is explicitly an agent-workflow process lesson, not a system feature, and is intentionally not
ticketed.

- **T-DOC52 (implemented — PR #117, merged; folded into `app.doctor` — auto-starts a stopped TEI container via `tei_lifecycle.start_tei_containers()`, per this ticket's own "fold into T-DOC43" note) — 🟠 no container restart policy; a power event silently kills every dependency
  (OG-12).** The workstation power-cycled (`uptime` showed 32 min since boot); all 4 required containers
  (Qdrant, GROBID, TEI-embed, TEI-reranker) came back `Exited (255)`, none auto-restarted, and had to be
  brought back up by hand (`docker start ...`). Production data itself survived intact (Qdrant's on-disk
  segments and `papers.db` both verified post-recovery) — only the *services* needed a human to notice and
  intervene. Same root cause as OG-1/OG-8 (T-DOC43), now with a second real incident (a hardware power
  event, not just a forgotten container) as evidence. Fix: give the required containers
  `restart: unless-stopped` in their compose/run config, or have the preflight/doctor check auto-start any
  stopped required service instead of only health-checking it. **Belongs in T-DOC43's scope** (preflight +
  service lifecycle) per the gap's own note, but T-DOC43 lives on unmerged PR #110's branch and can't be
  amended from here — ticketed standalone; fold into T-DOC43 when #110 lands.
- **T-DOC53 (recorded — negative result, no action) — MinerU's `vlm` backend: investigated, unblocked, and rejected on measured
  performance — negative-result record, not a feature (OG-13 + OG-14 + OG-15 + OG-17).** Four related
  findings from validating `vlm` as a Pass-1 alternative to `pipeline`, kept as one ticket because the
  action for all four is "don't repeat this, here's why":
  1. *(OG-13)* The shared conda env had a pre-existing, silently broken `vllm==0.24.0` (unrelated origin,
     `Required-by:` empty) that MinerU's `vlm-engine` backend auto-imports (`_select_linux_engine`,
     `mineru/utils/engine_utils.py`), crashing on first use — its `transformers>=5.5.3` requirement
     conflicted with MinerU's own `transformers<5.0.0` pin, and `vllm==0.24.0` was itself outside MinerU's
     declared-supported range. Fixed by downgrading to `vllm<0.22.0,>=0.10.1.1` (resolver landed 0.21.0, no
     torch/transformers change needed); `pipeline` backend re-verified correct post-downgrade. Side effect:
     bumped `anthropic`/`openai`/`opencv-python*`/`starlette` and vllm-internal kernel packages, which now
     flag conflicts against unused `marker-pdf`/`surya-ocr`/`gradio` leftovers — a `pip check` sweep is owed
     before this env is next touched for an unrelated reason.
  2. *(OG-14)* `do_parse`'s public/synchronous entry point hardcodes the synchronous `vllm.LLM` engine
     (`mineru/cli/common.py`: `get_vlm_engine(inference_engine='auto', is_async=False)`), and that specific
     path produces degenerate output (`content_list.json` with zero real blocks) on this vLLM 0.21.0 +
     Qwen2VL-1.2B + RTX 3090 combination. The async path (`AsyncLLM` via `aio_doc_analyze`) on the identical
     model/checkpoint is correct — the bug is narrowly scoped to the sync `vllm.LLM` wrapper, not vLLM or
     the model in general — but `do_parse` cannot reach it.
  3. *(OG-17)* Built the async wrapper OG-14 called for — simpler than expected, since
     `mineru.cli.common.aio_do_parse` already exists (no hand-rolled `_process_output` replication needed,
     ~25 lines: `asyncio.run(aio_do_parse(backend="vlm-engine", ...))`). A real, timed, quality-checked
     25-paper/488-page `pipeline`-vs-`vlm` comparison confirmed the async path is correct (88.8% avg GPU
     util vs `pipeline`'s 38.1%, materially equivalent output quality) but **~3.06x slower wall-clock**
     (530.9s vs 173.3s) and **~7x more GPU-seconds** for the same pages — the 1.2B model's sequential
     per-page token decoding is intrinsically more expensive than `pipeline`'s specialized narrower
     sub-models, so better utilization of much costlier work is still a net loss. Also flags a reusable-code
     gotcha: calling `asyncio.run(aio_do_parse(...))` twice in one process (warm-up then timed run) crashes
     the second call (`RuntimeError: Future attached to a different loop`) because `AsyncLLM`'s
     process-cached `ModelSingleton` binds to the event loop it was created in — fix is one `asyncio.run()`
     wrapping both warm-up and the timed batch inside a single `async def main()`.
  4. *(OG-15)* Separately, tripling `MINERU_PROCESSING_WINDOW_SIZE` (64→192) to test the "bigger window
     amortizes render/infer handoff cost" theory produced only a ~3.2% wall-clock change — within
     cross-run noise. Root cause: `doc_analyze_streaming`'s CPU render step is page-count-proportional, not
     a fixed per-batch tax, so fewer/bigger batches barely move total render time.

  **Recommendation (confirmed under clean re-testing by OG-18/T-DOC51, not a false negative from
  confounds): do not adopt `vlm` for Pass-1 throughput on this hardware, and do not expect
  `MINERU_PROCESSING_WINDOW_SIZE` alone to fix GPU underutilization.** Action: fold this record into
  `pass1-gpu-underutilization.md`'s tuning-parameters guidance (already the plan per OG-15's own note) so a
  future operator doesn't re-run either experiment from scratch; if `vlm` is ever revisited, do it via the
  async path explicitly, with a `pip check`-clean env verified first, and re-measure on the actual target
  hardware rather than extrapolate from this box.
- **T-DOC54 (implemented — PR #119, merged; resolved-by-T-DOC47 + note in `LESSONS-LEARNED.md` / `app/telemetry.py` docstring: pipeline's own telemetry is now source of truth, cross-check external dashboards only) — 🟠 `workstation-dashboard` MCP's retained history has silent internal gaps; not
  trustworthy alone for post-hoc GPU analysis (OG-16).** `export_history(components="gpu")` for a 736s
  Pass-1 window returned only 386 dense samples covering the *last* 217s — the earlier ~519s (including all
  model-loading and the bulk of inference) had zero stored samples, with no error, warning, or row-count
  hint from the tool itself. Cross-checked against `run.log`'s own timestamped lines and this run's
  independent `nvidia-smi`-polling `monitor.sh` (no gap, since it's this run's own process) to confirm the
  partial data was at least internally consistent before reporting it as explicitly lower-confidence. Not
  this project's own bug (external MCP tool), but a second, independent argument for OG-5/OG-6's built-in
  per-run GPU telemetry (T-DOC47): an external dashboard's retention/collection can have silent holes
  exactly when a post-hoc analysis needs it most. Action: once T-DOC47 ships, treat the pipeline's own
  telemetry as the source of truth for run analysis; until then, cross-check any `workstation-dashboard`
  export against the run's own log timestamps (or an independent local poller, as this run did) before
  trusting it.
- **T-DOC55 (implemented — PR #116, merged; `python -m app.benchmark`, reuses `FileGpuLock`) — 🟠 no controlled benchmark harness; every perf measurement hand-builds its own
  controls, and GPU benchmarks must be serialized (OG-20, new part only).** Answering "how do we raise
  pages/min" required hand-building, from scratch, every control needed to trust the numbers: evict TEI
  *and* Ollama, verify `nvidia-smi` at true baseline before each run, exclude model-init via a discarded
  warm-up, hold the paper set fixed, poll GPU at 0.5s, normalize to pages/min, and treat any OOM'd worker as
  invalidating its config — none of this exists in the repo; each benchmark reinvented it. Two real
  near-misses this caused: the first `vlm` test was a false negative (default `gpu_memory_utilization=0.5`,
  Ollama possibly still resident) and had to be redone from a clean GPU to be trusted; and a session nearly
  dispatched three GPU benchmarks in parallel, which on one GPU would have contended and produced
  confidently wrong numbers for all three — there is no lock preventing that. Fix (the genuinely new part —
  overlaps but does not duplicate T-DOC46's scratch/isolated-storage mode or T-DOC47's built-in telemetry):
  a `benchmark`/`perf` mode or harness owning evict-and-verify GPU baseline, warm-up-then-time convention,
  fixed-corpus selection, OOM detection that invalidates a config, and — the part with no existing
  analogue — **a GPU serialization lock so two benchmarks can never run concurrently** (the repo already has
  a `.gpu.lock` file used to serialize production ingest runs against each other; extend that same
  mechanism to cover benchmark runs rather than inventing a second lock). Cross-references T-DOC46
  (scratch/benchmark run mode) and T-DOC47 (run instrumentation & reporting) for the rest of "the system can
  measure itself honestly."

### T-DOC56–T-DOC59 — gaps surfaced during the T-DOC41 spike + prior batches (OG-22..25)

- **T-DOC56 (implemented — this fix; `app/assembly.py` `_resolve_store_paths`) — 🔴 `build_mcp_server`
  silently ignored `config.db_path`/`config.blob_dir` (OG-22).** Took a `Config` but resolved
  `db_path or "papers.db"` / `blob_dir or "blobs"`, never reading the Config's own fields — a caller that
  set `config.db_path` (e.g. an eval pointed at the real data dir) ran against the **empty repo-root
  `papers.db`** and got a confident fake `Recall@10 = 0.000` (hit for real 2026-07-17). Dormant in prod
  (Config default coincides with the fallback; `app/serve.py` uses `RAG_DB_PATH`). Fixed +
  unit-tested (`_resolve_store_paths`: explicit arg wins, else `config.db_path`/`config.blob_dir`;
  backward-compatible).
- **T-DOC57 (implemented — PR #131, merged; report now has a `questions` array with paper/passage hit+rank per question, `--no-per-question` to suppress, error-vs-miss distinguished) — 🟡 `app/retrieval_eval.py` reports only aggregates, no per-question rows
  (OG-23).** Blocks computing per-question deltas / listing regressions between two runs from the JSON
  alone. Add an optional per-question array (qid, gold ids, hit rank per granularity).
- **T-DOC58 (implemented — PR #132, merged; `Retry-After` threaded via `TransientError.diagnostics`, parsed seconds/HTTP-date, clamped 300s, falls back to exponential; no `contracts/` edit) — 🟠 arXiv 429 backoff doesn't honor `Retry-After` (OG-24, T-DOC49 follow-up).**
  `ArxivSource.fetch_by_ids` doesn't surface the header through `TransientError`; thread it through and
  prefer it over the exponential schedule when present (`rag/harvester.py`).
- **T-DOC59 (implemented — PR #138, merged; `on_stage` hook on the orchestrator, wired to `set_stage` in `app/ingest.py`, no telemetry import in `rag/`) — 🟡 per-run telemetry only tags the coarse parse/finish boundary (OG-25,
  T-DOC47 follow-up).** `finish_phase()` runs summarize+embed+store as one call; add a stage-boundary hook
  inside `rag/orchestrator.py` so GPU time can be attributed to those three sub-stages.
- **T-DOC60 (implemented — PR #133, merged; `python -m app.reindex_idf`) — 🟡 enable IDF sparse on an
  existing collection (OG-27).** `VectorIndex.rebuild()` had no CLI; now wired with snapshot-first safety
  (verifies a real backup exists, since `rebuild()` is destructive-in-place), a before/after point-count
  invariant, an IDF-modifier post-check, `--dry-run`, and an already-has-IDF no-op. Post-seed enhancement
  (V0 gate met without IDF); run it once after the seed to enable IDF weighting.
- **OG-28 (fixed — PR #130, merged) — 🔴 `_ensure_collection` raced under `--parse-workers N` into a fresh
  collection (409 Conflict, killed 2/3 workers).** Caught by the seed-command smoke test. Now idempotent
  (catch `ApiException` on create, re-check existence). Didn't affect the existing-collection seed, but
  cleared the fresh-collection N>1 path.

---

## T-DOC series — post-M1b real-run hardening fixes (2026-07-13/14)

Found and fixed while running the real end-to-end pipeline against live infra (`.phase0-data/100-paper-run-stats.md`),
not part of any owner's original M1b ticket — tracked here per GIT-WORKFLOW.md's "every ticket has a stable
ID" rule rather than left as bare PR titles/branch names. All merged to `main`.

- **T-DOC4** (PR #62, `T-DOC-pdf-download-ratelimit`) — add a fixed inter-request delay to the PDF-download
  parser (`app/assembly.py`'s `_PdfDownloadParser`), to avoid tripping arXiv's rate limiting on sequential
  per-paper PDF fetches.
- **T-DOC5** (PR #63, `T-DOC-fix-before-embed-race`) — close the `before_embed` unload race: poll Ollama's
  `/api/ps` until the Summarizer is confirmed evicted, instead of trusting the `keep_alive: 0` HTTP response
  alone (`rag/summarizer.py`'s `unload()`; ARCHITECTURE.md §3 has the full mechanism).
- **T-DOC6** (PR #64, `T-DOC6-unload-malformed-response-handling`) — `unload()` must not raise on a
  malformed `/api/ps` response (non-JSON body, unexpected shape) — degrades to the same best-effort warning
  path as a timeout, rather than crashing the caller's phase transition.
- **T-DOC7** (PR #65, `T-DOC7-pdf-transient-error-retry`) — retry transient PDF-download failures
  (429/502/503/504, timeouts, transport errors) once with backoff instead of quarantining immediately.
- **T-DOC8** (PR #67, `T-DOC8-arxiv-harvest-query-timeout`) — split `ArxivSource.fetch()`'s single
  combined `focus_area_queries` search into one sequential request per term; the combined `" OR "` query
  reliably got `HTTP 429`/timeout from arXiv and returned zero papers.
- **T-DOC9** (PR #66, `T-DOC9-ci-testpaths-app-coverage`) — add `app/` to pytest's `testpaths` so its test
  suite (e.g. `_PdfDownloadParser`, composition-root wiring) actually runs in CI.
- **T-DOC10** (PR #68, `T-DOC10-harvest-quarantine-visibility`) — wire a real `QuarantineSink` for
  harvest-level failures (`app/assembly.py`'s `_sqlite_harvest_quarantine_sink`); previously an
  exhausted-retry-budget harvest failure was silently dropped (no DB row, no log line).
- **T-DOC12** (PR #75, `T-DOC12-parse-phase-error-boundary`) — a real 2,000-paper end-to-end run crashed
  the whole `parse_phase()` subprocess (and, via `app/ingest.py`'s `subprocess.run(...,
  check=True)`, the parent `app.ingest` process too) when one paper's reference-extraction
  call raised `TransientError`: `rag/orchestrator.py`'s `_prepare()` only ever caught
  `PermanentError` around `parser.parse(ref)`, so the `TransientError` propagated out of
  `ingest()` and every paper still queued behind the failing one lost its progress for that run.
  Added a bounded retry (`IngestionOrchestrator.__init__`'s new `max_retries`/`retry_sleep`,
  same shape as `rag/harvester.py`'s `Harvester`) then quarantine for `TransientError` from
  `parser.parse`, alongside the pre-existing (and already-correct) immediate quarantine for
  `PermanentError`.
- **T-DOC13** (PR #76, `T-DOC13-finish-phase-error-boundary`) — the `_finish()`/`finish_phase()`
  (Pass 2) analog of T-DOC12 (`_prepare()`/`parse_phase()`, Pass 1), found while fixing T-DOC12 and
  filed as its direct follow-up: `summarizer.summarize()` only guarded `PermanentError` (a
  `TransientError` propagated uncaught and would crash the whole `finish_phase()` subprocess, same
  shape as the crash T-DOC12 fixed); both `embedder.embed()` call sites (main path and the
  stored->done resume path) were guarded against neither error type at all. Added the same
  bounded-retry-then-quarantine shape T-DOC12 established (`max_retries`/`retry_sleep`, same
  exponential backoff). Also found and fixed the same gap in `_upsert_record`'s
  `vector_index.upsert()` calls while auditing this method for the same bug class -- not named in
  the original ticket, only `TransientError` applies there (the real vector-store adapter never
  raises `PermanentError`).
- **T-DOC15** (`T-DOC15-mineru-vram-peak-fix`) — correct ARCHITECTURE.md/CONVENTIONS.md's claim that
  MinerU uses a flat ~6.6GB of VRAM; real measurement shows its pipeline backend (sequential
  layout/OCR/table/formula sub-model loads, `rag/parser.py`'s `_run_mineru_pipeline`) peaks around
  ~13GB routinely and up to ~23.7GB observed, leaving Pass 1 a real margin of ~1GB rather than the
  "~16.2GB fits comfortably" previously claimed. **Open risk, not fixed here:** that ~1GB margin is thin
  and needs a human decision on footprint reduction or a guard — out of scope for this doc-only fix.
- **T-DOC16** (`T-DOC16-mineru-batch-parse`) — real Pass 1 GPU-utilization measurement found the GPU idling
  *inside* one document's sequential MinerU sub-model stages (avg 27.4% util, 62.7% of samples at 0%, vs.
  Pass 2's 82.2% on the same card — `.phase0-data/pass1-gpu-underutilization.md`), because `rag/parser.py`
  only ever sent MinerU one PDF at a time even though `do_parse` natively batches. Added
  `Parser.parse_batch(raws) -> list[ParsedDoc]` (one `do_parse` call for N documents, whole-batch-fails --
  no partial results, per a `principal-design-reviewer` pass: MinerU pools every open document's pages into
  shared windows, so one bad page anywhere aborts the whole call and true per-document isolation would
  require coupling to MinerU's private, unexposed `on_doc_ready` callback). `parse_phase()` now batches
  `config.parse_batch_size` (default 4) papers per `parser.parse_batch()` call and falls back to the
  existing per-paper `_parse_with_retry` path, unchanged, on any batch failure. Code + fake-backed tests
  only (no real GPU/MinerU run) — a real-GPU validation spike is still required before live rollout.
- **T-DOC17** (`T-DOC17-quarantine-diagnostics`) — `quarantine.error` was `str(exception)` only, with no
  structured category or forensic context to diagnose a real parse-content failure once one occurs (none
  exist in the corpus yet — pure instrumentation). Added the additive `quarantine_diagnostics` table
  (`migrations/0003_quarantine_diagnostics.sql`) capturing `error_type` (`type(error).__name__`) and an
  optional `diagnostics_json`, populated by `SqliteIngestState.quarantine()` from a new opportunistic
  `.diagnostics` attribute-setting convention (`contracts/errors.py`) that `rag/parser.py`'s failure sites
  now use for cheaply-available context like `pdf_size_bytes`.
- **T-DOC18** (`T-DOC18-pdf-cache-check`) — the live ingestion pipeline never read the standalone PDF
  prefetcher's (PR #79) cache: `_PdfDownloadParser._download_once` (`app/assembly.py`) unconditionally
  issued a live HTTP GET for every paper, always re-downloading even when `pdf_cache/<paper_id>.pdf`
  already existed. Added a cache-check before any HTTP call (hit: read from disk, zero HTTP/rate-limit
  cost) plus write-through on a cache miss (the live path now also populates `pdf_cache/`, same
  convention the prefetcher writes to), and a single-lookahead prefetch in `parse_batch` so batch N+1's
  downloads overlap batch N's GPU-bound `parse_batch()` call instead of running strictly before it.
- **T-DOC19** (`T-DOC19-tei-pass1-eviction`) — real GPU spikes this session confirmed Pass 1 (MinerU) sat
  far below Pass 2's utilization in part because the TEI Embedder (~8.2GB) and Reranker (~1.4GB)
  containers stayed GPU-resident through Pass 1 even though neither does any work during it. Added
  `app/tei_lifecycle.py` (`stop_tei_containers`/`start_tei_containers`, best-effort `docker
  stop`/`start` + health-poll, same shape as `rag/summarizer.py`'s `unload()`) and wired it into
  `build_ingestion_orchestrator`'s `before_parse_phase` (alongside the existing summarizer eviction) and
  previously-unwired `before_finish_phase` hooks, freeing ~9.4GB of VRAM for larger MinerU batches during
  Pass 1. Safe only because ingestion and live querying never overlap for this deployment (confirmed
  operational fact, not a general architectural claim) — live MCP queries would fail for the whole Pass 1
  duration if that assumption ever changes.
- **T-DOC20** (this doc-sync entry) — recorded T-DOC18/T-DOC19 in ARCHITECTURE.md, CONVENTIONS.md, and
  PHASE0-RUNBOOK.md (the `rag-tei-embed`/`rag-tei-reranker` container names hadn't appeared anywhere in
  the repo before this), plus the full GPU-utilization audit findings this session's investigation
  turned up: Pass 1 measured at 27% GPU utilization vs. Pass 2 at 82%; Embedder and Summarizer confirmed
  already near-optimal within their serving stacks' real constraints (no further code-level lever
  available); MinerU's alternative `vlm-engine` backend investigated as the more fundamental fix for
  Pass 1 but found blocked on an incomplete model download plus missing `transformers`/`vllm`
  dependencies, correctly deferred as a separate follow-on rather than folded into this pass.

---

## Dependency graph (who blocks whom)

```
Owner F foundation ─────────────► everyone
Phase 0 (parser, embedder, reranker, config) ─► B1, C3, D2, E1
Parser(B1) ─► Chunker(C1) + Summarizer(C2) ─► Embedder(C3) ─► DocumentStore(D1)+VectorIndex(D2) ─► Retriever(E1) ─► McpServer(E2)
Harvester(A1) ─► Orchestrator(A2) ── wires all stages
Fakes(F4) let C1, C2, D1, E1, E2, A2 be built and tested BEFORE the real adapters exist.
```

The fakes are what break the vertical dependency: Retriever (E1) is built and fully tested against
`FakeEmbedder` + `FakeVectorStore` + `FakeReranker` **before** the real embedder, Qdrant, or reranker
adapter is finished. That's the whole point of the seams — don't wait.

---

## Guardrails, repeated because they matter (build team = AI agents — CONVENTIONS §0)

These are mechanically enforced (CI), not left to a reader's judgment — because the team is AI agents, not
junior humans who slowly build institutional memory. See CONVENTIONS §0 for why that distinction matters.

- **No module invents a shared type** — it lives in `contracts/` or it doesn't cross a seam (DATA-CONTRACTS);
  CI (T-F6) fails a diff that shadows a contract name.
- **No vendor import outside its adapter** — CI-checked (T-F6), not just review (CONVENTIONS §1, §12).
- **The shared foundation is frozen** after M0 — changing it requires the label + your sign-off (T-F7), not a
  silent patch by whichever agent hits a mismatch first.
- **A ticket isn't done because it ran once** — it's done at the Definition of Done (CONVENTIONS §11), i.e.
  tests green through the interface, not "the agent reports success."
- **Tests exist before the code they test** — M1a is a real milestone gate, not a convention. An
  implementation PR for a module opened before that module's test-suite PR is out of order; T-F6(g) catches
  the mechanical proxy (missing sibling test file), the M1a→M1b gate catches the ordering (git history).
- **A GPU-bound real adapter without an injected `GpuLock` is a bug, not a style nit** — T-F6(f) fails the
  build; there is no "release between, or accept the load cost" exception (CONVENTIONS §6).
- **Don't build V1** — no claims, tiers, reconciliation, Obsidian, self-describing MCP scaffolding, or
  contextual headers (ADR-07 — explicitly deferred, V0 only monitors). If a ticket seems to need one of
  these, it's mis-scoped; check CONTEXT.md and flag it rather than building it "while in there."
- **When two modules disagree at the seam**, the fix is in `contracts/` (shared, via T-F7) + this doc, moved
  together — never a private patch on one side that papers over the mismatch.

---

## V1 Roadmap + Remaining Gaps — ticketed for parallel/sequential execution (2026-07-17)

V1 is **gated behind V0 shipping + Spikes 3/5 passing** (PRD §9, CONTEXT.md). This section tickets V1's
deliverables plus the remaining V0-era gaps, with an explicit dependency graph so work parallelizes
safely. **Hard rule (ADR-12): claim-extraction quality bounds everything downstream — no claim-layer
build before Spike 3 clears its bar.**

### Remaining V0-era gaps (do now, parallel — no gate)
- **T-DOC59 (implemented — PR #138, merged) — 🟡 finer telemetry sub-stages (OG-25).** `finish_phase()` runs
  summarize+embed+store as one call; add a stage-boundary hook inside `rag/orchestrator.py` so GPU time
  attributes to those three sub-stages.
- **T-DOC61 (implemented — PR #137, merged; `logging.basicConfig` + harvest/rate-limited-progress/sleep lines, `--log-every`) — 🟡 prefetch stdout logging (OG-29).** `app/prefetch_pdfs.py` is silent
  during a days-long run; add `logging.basicConfig` + harvest/download/sleep lines so the cache build is
  observable. High value while the seed-cache build is underway.

### V1 gating spikes (RUN FIRST — the whole V1 build waits on these)
- **T-V1-S3 (DONE 2026-07-17 — GO, flag-only; see `reviews/SPIKE3-CLAIM-EXTRACTION.md`. Extraction feasible: 305 claims/20 papers (JSON-repair recovered 2 failed papers), no fabrication found in hand-audit (the 57.6% "grounding" was a verbatim-vs-paraphrase artifact), well-conditioned, hand-audited good. The `conditions` field IS load-bearing — it correctly flags cross-paper claims as NON-COMPARABLE (e.g. IHDP/coverage: stress-test vs DP-noise-budget experiments), which is ADR-12's thesis working. What's absent is same-method same-metric numeric comparison (corpus sparsity) → **auto-supersession bar NOT met, claims are flag-only, per the PRD default**. Wave B UNBLOCKED. Fixes folded into T-V1-CLAIM-EXTRACT: verbatim spans, numeric-value/results-section extraction, JSON-parse robustness) — 🔴 Spike 3: claim extraction + reconciliation feasibility (the long pole;
  ADR-12, PRD §11 Q4).** Can the local LLM extract atomic claims with **structured conditions**
  (method/task/dataset/metric/value/conditions) + artifact links at usable precision on THIS corpus?
  What judge precision clears the bar for **auto-supersession vs. flag-only-forever**? Deliverable: a
  measured go/no-go + the precision number. Gates T-V1-CLAIM-*, T-V1-DEDUP, T-V1-TIERS. GPU (local LLM)
  — schedule around the V0 seed so they don't contend.
- **T-V1-S5 (not started) — 🟠 Spike 5: LLM-consumption behavior (ADR-16/17).** Does the result-contract
  scaffolding (evidence-tier envelope, `describe_capabilities`, epistemic envelope) measurably change how
  the consuming agent composes/drives the system vs. a bare tool bag? Deliverable: a measured behavior
  delta. Gates T-V1-MCP.

### V1 infrastructure (parallelizable — limited spike dependency)
- **T-V1-VLLM (not started) — 🟠 generation-side vLLM migration (ADR-09).** Embedder-side already
  spiked+REJECTED (stay on TEI); this is the GEN side (summaries/claims), needed before claim extraction
  runs at 30k scale. **Re-validate the VRAM eviction-hook interaction** (ADR-09 caveat) before it lands.
  Can be built/spiked in parallel with the spikes.
- **T-V1-OBSIDIAN (implemented — PR #136, merged; `python -m app.obsidian_export`, keyed on paper_id, idempotent, `## Claims` deferred) — 🟢 Obsidian note-per-paper (generated view over SQLite; PRD §11 Q5 →
  generated, not hand-edited, SQLite is truth).** Renders V0 summaries now, extends to claims when they
  exist. Mostly independent (rendering layer) — can start early.

### V1 claim layer (GATED on T-V1-S3 passing + V0 shipped)
- **T-V1-CLAIM-SCHEMA (not started) — 🔴 claim data model (ADR-12).** Atomic Claim
  (method/task/dataset/metric/value/conditions + type + confidence + embedding), bidirectional
  Claim↔Artifact links, Claim-relation edges (duplicate/refines/supports/contradicts). Foundation
  (`contracts/` + migration). DATA-CONTRACTS.md already carries a nullable stub (no migration surprise).
- **T-V1-CLAIM-EXTRACT (not started; Spike-3 fixes REQUIRED: prompt for VERBATIM evidence spans, preserve results/tables sections + push for numeric `value`, add JSON-repair/retry — 2/20 papers failed raw-JSON parse) — claim extraction pipeline stage** (local LLM, per-paper, after
  summarize). Depends on SCHEMA + S3 + (for scale) VLLM.
- **T-V1-DEDUP (not started) — duplicate/near-duplicate claim detection** (Claim-relation `duplicate`
  edges). Depends on claims existing.
- **T-V1-TIERS (not started) — activate the evidence-tier envelope B/C/D** (currently hard-pinned to
  `"A"` in `contracts/retriever.py`). Depends on claims + tier labels. ADR-16.

### V1 MCP self-description (GATED on T-V1-S5)
- **T-V1-MCP (not started) — 🟠 self-describing/orchestratable MCP (ADR-17):** `describe_capabilities`,
  `corpus_stats`/`whats_covered`, + the MCP instructions/resources/prompts primitives. Depends on S5.

### Gated on V0 30k + at-scale eval
- **T-V1-HEADERS (not started) — contextual-retrieval headers (ADR-07).** Already spiked → HOLD
  (`rag/contextual_header.py` + `app/reembed_experiment.py` built; ~18 GPU-days at 30k). Gate: run the
  topic-absent equation eval (`fixtures/eval/eval_equation_slice_topic_absent.json`) at 30k scale; adopt
  only if it clears. Re-embed is the cost.

### Dependency graph / waves
```
WAVE A (now, || V0 seed/prefetch):  T-DOC59 · T-DOC61 · T-V1-S3 · T-V1-S5 · T-V1-VLLM · T-V1-OBSIDIAN
     (gaps + spikes + independent infra; GPU-heavy ones scheduled around the seed run)
WAVE B (after S3 + V0 ships):        T-V1-CLAIM-SCHEMA → T-V1-CLAIM-EXTRACT → { T-V1-DEDUP, T-V1-TIERS }
WAVE C (after S5):                   T-V1-MCP
WAVE D (after 30k + eval):           T-V1-HEADERS
```

---

## Dogfooding + turn-on tickets (2026-07-17 — first real use of V0 at 809 papers)

Found by actually using the system (a method-research session) and bringing it online. **All point at
retrieval quality + operability, not the claim layer** — reinforcing the "use it first" decision.

### Retrieval quality (from the first real method-research session, OG-30)
- **T-DOC62 (code fix implemented; data gap closed by option B, `app/rechunk.py`) — 🟡 chunker:
  de-duplicate the leading section header (OG-30 #1).** Status here was stale: the code fix landed
  2026-07-17 as commit `157af4d` (`rag/chunker.py:58` `_strip_duplicate_heading`, applied at `:178`)
  — everything ingested since is clean (measured: 0.01% duplication vs. 58.49% before). What
  remained was stale *data* — 809 papers ingested before that date, ~14,850 chunks (4.1% of the
  corpus) still carrying the duplicated header (`docs/DECISION-t-doc62-duplicate-chunk-headers.md`).
  Closed by re-chunking those papers from their already-stored blocks (option B in that decision
  doc) via the general, reusable `python -m app.rechunk` tool
  (`docs/superpowers/specs/2026-07-28-rechunk-from-blocks-design.md`) — no re-parse, no full
  re-embed.
- **T-DOC63 (implemented — landed as part of T-DOC82, not this ticket directly: `rag/retriever.py:59`
  `_MAX_HITS_PER_PAPER = 3`, `:62` `_cap_per_paper(...)`, applied at `:289`
  `return _cap_per_paper(results)[:k], ...`) — 🟡 retrieval: diversify-by-paper option (OG-30 #2).** A
  survey-style method query returned 3 chunks of the SAME paper in the top 5; for "what are my
  options?" 5 distinct papers is far more useful. **One substantive difference from the ticket as
  written: this is a fixed cap, not an option.** `_MAX_HITS_PER_PAPER` is a module-level constant with
  no per-call parameter to disable or tune it, and no MMR-style diversification. This resolves the
  observed problem (one paper can no longer fill `k`) but leaves a remainder: nothing lets a caller
  raise/lower the per-paper limit or turn it off for a query that genuinely wants many chunks from one
  paper.
- **T-DOC64 (not started) — 🟢 HIGHEST-VALUE retrieval enhancement for the owner's uses:
  section-aware retrieval (OG-30 #3).** Retrieval finds the right paper but often lands on the
  Introduction/Related-Work block, not the "we propose X which does Y" method sentence. Boost/filter
  by `section_path` type (favor Method/Results for method questions, Limitations for gap questions).
  Directly serves method-research + why-this-method + gap-finding. Candidate first real enhancement
  after dogfooding. (Also absorbs the minor topic-drift seen — a causal-flavored LLM-prompt paper
  surfaced on 2 treatment-effect queries.)

### Turn-on / operability
- **T-DOC65 (not started) — 🟡 production config generation (OG-31).** Document or script creating the
  data-dir `config.yaml` (repo config + absolute paths) so bringing the system up isn't tribal
  knowledge.
- **T-DOC66 (not started) — 🟡 MCP deploy runbook + connectivity doctor-check (OG-32).** Capture the
  `--no-capture-output` / `PYTHONPATH` / `cwd` requirements, and add a check that the MCP server
  launches and answers `list_tools` before the user relies on it.
- **T-DOC67 (not started) — 🟢 delete the stray repo-root `papers.db` + gitignore `papers.db*`
  (OG-33).** Remove the near-empty file that caused the fake `Recall@10=0.000` trap; prevent recreation.

### T-DOC80 — drop-in folder ingestion + book support (2026-07-25)

- **T-DOC80 (implemented — this branch, `feat/t-doc80-drop-in-and-books`, commits `7372062..36d1b35`;
  spec: `docs/superpowers/specs/2026-07-25-drop-in-folder-and-books-design.md`; plan:
  `docs/superpowers/plans/2026-07-25-drop-in-folder-and-books.md`) — drop-in folder ingestion (arXiv
  PDFs, non-arXiv papers, and books dropped under `Config.drop_in_dir`'s `papers/`/`books/`
  subfolders) plus book support end to end: map-reduce book summarization
  (`rag/book_summarizer.py`), chapter summaries persisted and embedded as their own routing units,
  `doc_type` filtering (`SearchFilters.doc_type`/`VectorPayload.doc_type`, legacy points still count
  as papers), `local:{sha256[:12]}` ids for files with no arXiv id, and chapter-level `search_papers`
  routing (`PaperSearchResult.chapter`).** New staging CLI: `python -m app.ingest_local
  [--stage-only] [--drop-dir PATH]` (`app/ingest_local.py`). Full contract/module changes are
  recorded in place in DATA-CONTRACTS.md (§IDs, §M1, §M5, §M6, §M7/§M8, SQL schema, §Config) and
  ARCHITECTURE.md (§M3B, §M9, "Operational tooling") rather than restated here.

### T-DOC81 — additive migrations have no supported path to an existing populated database (2026-07-26)

- **T-DOC81 (implemented — this branch, `fix/t-doc81-migration-mechanism`, commits `f433529`
  onward; spec: `docs/superpowers/specs/2026-07-28-migration-mechanism-design.md`) — 🔴 HIGH
  PRIORITY: `migrations/migrate.py` cannot reach a database that already has rows; T-DOC80's 0004
  migration never applied to production, silently broke every ingest path.** Discovered running a
  real ingest against the real 11,019-paper production DB on 2026-07-26: every ingest run — the
  normal arXiv corpus build and T-DOC80's new drop-in path alike — crashed with
  `sqlite3.OperationalError: table papers has no column named doc_type`. Root cause was
  structural, not a one-off missed step:
  1. `migrations/migrate.py`'s `migrate()` applied **every** numbered `.sql` file in `migrations/`,
     in filename order, on every call, using plain `CREATE TABLE`/`ALTER TABLE` (no `IF NOT EXISTS`
     guard) — this was deliberate (the module's own docstring used to read: "there is no
     tracked-migration framework here... every file in this directory is applied... every time
     `migrate()` runs. Re-running against an already-migrated database is expected to fail
     loudly") and was pinned by
     `migrations/test_migrate.py::test_migrate_on_already_migrated_db_fails_loudly_not_silently`
     (asserted `sqlite3.OperationalError` matching "already exists"). **T-DOC81 deliberately
     reverses this contract**: `migrate()` now tracks applied files in a `schema_version` table and
     is idempotent — re-running it against an already-migrated database is the supported, expected
     path, not a failure. The test above is rewritten
     (`test_migrate_on_already_migrated_db_is_idempotent_not_a_failure`) to assert that instead.
  2. `rag/document_store.py`'s `DocumentStore.__init__` (line 58-61) only called `migrate(db_path)`
     when `not db_file.exists()` — an existing DB, however far behind the `migrations/` directory,
     was just opened and connected to, never re-migrated. **Fixed**: it now calls `migrate(db_path)`
     unconditionally, safe because `migrate()` is idempotent.
  Net effect: an additive migration (0002, 0003, 0004, ...) can only ever reach a **brand-new**
  database; there is no supported operator path to apply one to an existing, populated database.
  0004 (`ALTER TABLE papers ADD COLUMN doc_type ...; ALTER TABLE summaries ADD COLUMN title ...`)
  simply never ran against production, so `DocumentStore.put()`'s unconditional `doc_type` write
  (`rag/document_store.py:114`) hit a column that didn't exist. How 0002/0003 previously reached
  production is an open question, not asserted here — plausibly the DB was recreated at some point,
  or they were applied by hand as this one now is; worth checking before assuming the mechanism ever
  worked. **Already resolved as a data-state issue, not part of this ticket's scope:** backed up to
  `research-system-rag-data/backups/papers-pre-0004-20260726T054148Z.db`, then the two `ALTER TABLE`
  statements from `migrations/0004_doc_type_and_chapter_titles.sql` applied directly to production.
  Production is correct today; this ticket is about the mechanism gap so it doesn't recur on 0005+.
  **Why the existing test/review chain missed it:** every `migrate()` unit test starts from a fresh
  `tmp_path` DB, where applying 0001→0004 in order works perfectly — the bug is invisible to any test
  that starts empty. `migrations/test_migrate.py`'s per-migration parity tests (DATA-CONTRACTS.md's
  documented SQL vs. the actual `.sql` file) verify a migration is *correctly written*, not that it
  can *reach* a database that already has rows. T-DOC80's 10 per-task code reviews each saw one
  task's diff; the final whole-branch review confirmed 0004 was additive, documented, and
  parity-tested, but nobody asked how the migration reaches a database with 11,019 existing rows —
  only a live run against the real production DB surfaced it. **Candidate fixes (options, not a
  prescribed answer):**
  (a) a real `schema_version` tracking table so `migrate()` applies only the files not yet recorded
      as applied, making it idempotent and safe to run on every startup;
  (b) a separate, explicit `migrate --upgrade` operator command distinct from the create-new-DB path,
      run deliberately against a populated DB instead of folded into every `DocumentStore.__init__`;
  (c) `DocumentStore.__init__` detects a DB whose schema is behind the `migrations/` directory (e.g.
      a missing column) and refuses to open with a clear, actionable message, instead of letting the
      first `put()` fail mid-ingest with a confusing `OperationalError`. (c) is complementary to
      (a)/(b) — a fast, clear failure mode — not an alternative to actually closing the gap.
  Whatever is chosen needs a test that starts from a **populated DB at an older schema version**
  (apply 0001-0003, insert rows, then run the fix against it with 0004 present) — a fresh-tmp_path
  test, however thorough, cannot exercise this path at all, and the next additive migration repeats
  this exact incident otherwise. High priority: this blocks every future additive migration and
  silently breaks all ingest (both existing and new paths) the moment one is added.

### T-DOC82 — book chapter detection + book-appropriate summarization (2026-07-26)

- **T-DOC82 (implemented — this branch, `feat/t-doc82-book-chapters-and-prompts`, commits
  `36d1b35..HEAD`; spec: `docs/superpowers/specs/2026-07-26-book-chapter-and-summary-fixes-design.md`;
  plan: `docs/superpowers/plans/2026-07-26-book-chapter-and-summary-fixes.md`) — fixes two defects
  T-DOC80's own feature exposed on the **first live drop-in ingest against the real corpus**; both
  were invisible to the unit suite because its fixtures are synthetic 3-block `ParsedDoc`s with a
  real `" > "` hierarchy, summarized by `FakeSummarizer` (a truncation stub that cannot fabricate) —
  only a real book through real MinerU and the real local LLM exposed either one.
  - **D1 — chapter splitting degenerated to ~1 chapter per heading.** `_split_chapters` grouped
    blocks by top-level `section_path`, which MinerU builds as a real hierarchy for arXiv papers
    (113 `" > "`-bearing blocks on `0705.1270`) but emits FLAT for books (zero `" > "`-bearing
    blocks, 306 distinct flat values, on the 2,520-block, ~144k-word *Causal Inference in Python*).
    Grouping-by-`section_path` was therefore an identity function on books: 530 chapter summaries
    for 535 chunks, with titles like `Contributors`, `About the author`, `Italic`, `Constant width`
    — ~530 LLM calls per book instead of ~15-30, and chapter-level `search_papers` routing hits
    polluted with front-matter/typographic-convention "chapters". Fixed with a two-strategy
    `_split_chapters` (marker regex with a plausibility guard, falling back to accumulating heading
    groups to a target word count; unchanged single-group windowing for flat/scanned docs) — full
    behavior in ARCHITECTURE.md §M3B.
  - **D2 — paper-shaped prompt fabricated numbers for books.** The one `_SUMMARY_PROMPT` asked for
    "effect size"/"sample size"/"benchmark" results; asked of a textbook, the model invented them —
    a real stored book summary claimed "a novel hybrid method... approximately 15%... mean squared
    error on benchmark datasets", none of which the book states. Fixed by giving `Summarizer.summarize`
    a `kind="paper"|"book"|"book_overview"` keyword (`rag/summarizer.py`; unknown `kind` raises
    `ValueError`) selecting a book-specific prompt that drops paper-shaped fields and explicitly
    forbids inventing numbers — full behavior in DATA-CONTRACTS.md §M3B. The paper path (`kind="paper"`,
    the default) is byte-identical to the prompt before this change.
  - **Also folded in — deferred-minor findings from T-DOC80's own reviews:** `document_store.py`
    raises a typed `ContractError` (not a bare `ValueError`) for a malformed chapter `summary_id`;
    `retriever.py` gained a comment documenting that its `chapter=None` fallback for an orphaned
    chapter id is deliberate (logic unchanged); `obsidian_export.py` no longer renders the same URL
    twice for a `local:` id's PDF/Source links; `ingest_local.py`'s `detect_arxiv_id` now requires
    either an explicit `arXiv` prefix or the id being the whole filename stem — a bare
    `\d{4}\.\d{4,5}` anywhere in body text (e.g. "Table 4.12345") used to false-positive into an
    arXiv metadata lookup.
  - **Also, `retrieve_papers()` gained a per-paper cap** (`_MAX_HITS_PER_PAPER = 3`,
    `rag/retriever.py`) — a book contributes one vector per chapter, so a strong book match could
    otherwise fill every slot of `k` with chapters of the same paper and crowd papers out of a
    mixed-corpus query. Applied after rerank, before the `[:k]` truncation — full behavior in
    ARCHITECTURE.md §M7.
  - `summarize_book` also now raises `PermanentError` (same taxonomy `Summarizer` itself uses) when
    a book parse has no usable blocks at all, so `IngestionOrchestrator`'s existing quarantine path
    catches it — previously this produced an empty summary that nothing quarantined.

### T-DOC83 — `enforcement` job crashes exit 128 on every force-push, `compute_diff_base` trusts an orphaned `before` SHA (2026-07-27)

- **T-DOC83 (implemented — branch `fix/t-doc83-enforcement-force-push`) — 🔴 the `push`-triggered
  `enforcement` job dies before running a single check, on *any* force-pushed branch.** Observed on
  a real CI run on PR #174 (`push` event, head `58aba07`, after a rebase + force-push):
  `ci/checks/changed_files.py::compute_diff_base` reads `event["before"]` and, whenever it's
  present and non-zero, returns it unchecked; `ci/run_enforcement.py` then feeds it straight into
  `list_changed_paths` → `git diff --name-only <before> HEAD`, which dies with
  `subprocess.CalledProcessError: ... returned non-zero exit status 128`. Root cause: GitHub's
  `push` event's `before` is the branch's *previous* head at the time of the push. A normal
  (fast-forward) push keeps that commit reachable, so diffing against it is correct and cheap. A
  **force-push** rewrites history out from under it — `before` still names a real-looking 40-hex
  SHA, but this clone has no ref to it, and `git diff` against an object that isn't there is exit
  128, not an empty diff. **Why this is systemic here, not a one-off:** GIT-WORKFLOW.md mandates
  `gh pr merge --rebase`, and rebasing any already-pushed PR branch requires a force-push to update
  it — so this triggers on every rebased PR, not an edge case. Re-running the job doesn't help
  either: the replayed event payload carries the same orphaned `before` SHA. **Why no violation was
  ever actually missed despite this:** the `pull_request`-triggered run of the same workflow never
  reads `event["before"]` at all — it diffs `merge-base(pull_request.base.sha,
  pull_request.head.sha)` instead — so it kept catching real violations throughout; the force-push
  bug only produced a spurious red `enforcement` check context on an otherwise-clean push, never a
  false-negative silently letting a violation through. **Fix:** added
  `changed_files._rev_exists(repo_root, rev)` (`git cat-file -e <rev>^{commit}`, `check=False` —
  a missing object is the expected case, not an error) and gated the `push` early-return on it:
  `before` is only trusted if it actually resolves in this clone; otherwise `compute_diff_base`
  falls through to the same merge-base-with-default-branch fallback already used for a branch's
  first push. `pull_request` behavior is untouched. Tests added to `ci/checks/test_diff.py`: a
  reachable `before` is still returned unchanged (no behavior change for a normal push), an
  orphaned/unreachable `before` falls back to the merge-base instead of raising, and the
  `pull_request` path is unaffected.

### T-DOC84 — `delete_paper()` leaves `ingest_state`/`ingest_checkpoint` behind, so re-ingest silently no-ops (2026-07-27)

- **T-DOC84 (implemented — PR #177, merged 2026-07-28) — 🔴 `delete_paper()` deletes a document's rows and vectors but not its
  ingest-state, so re-ingesting the same id is a silent no-op.** `rag/orchestrator.py:210
  delete_paper(paper_id)` deletes from `DocumentStore` (SQLite rows) and `VectorIndex` (vectors)
  only. It never touches `ingest_state` or `ingest_checkpoint`, even though `IngestionOrchestrator`
  already holds `self._state` and wires it everywhere else in the ingest path.
  **Observed live, 2026-07-27**, during the T-DOC82 rollout (spec
  `docs/superpowers/specs/2026-07-26-book-chapter-and-summary-fixes-design.md` step 2, "delete ONE
  book and re-ingest it"): deleting `local:f0929288d4f3` (*Causal Inference in Python*) through
  `delete_paper()` correctly dropped it from `papers` (11026 → 11025) and removed all its
  `chunks`/`summaries` rows and Qdrant points, correctly scoped to that one id — but `SELECT stage
  FROM ingest_state WHERE paper_id='local:f0929288d4f3'` still returned `'done'`.
  **Consequence:** a re-ingest of that id skips every stage — the orchestrator's resume logic treats
  a `done` checkpoint as already-complete — so the document is never re-parsed, never re-embedded,
  and never comes back. No error is raised and no quarantine row is written. The operator sees a
  successful-looking run and a permanently missing document. The re-ingest only worked because the
  stale row was deleted by hand first.
  **The capability already exists but is not reachable:** `rag/ingest_state_sqlite.py:184-185`
  deletes exactly these two rows (`DELETE FROM ingest_state ...` / `DELETE FROM ingest_checkpoint
  ...`) — but only as a side effect *inside* `quarantine()`. There is no `forget()`/`delete()` on
  the state adapter, so `delete_paper` has nothing to call. `SqliteIngestState`'s public surface is
  `get`, `checkpoint`, `quarantine`, `stage_of`, `all_known_paper_ids`.
  **The existing integrity checker is blind to this shape by construction.**
  `app/corpus_integrity.py:32` reads `FROM ingest_state s JOIN papers p ON p.paper_id = s.paper_id
  WHERE s.stage='done' AND (chunk_count=0 OR block_count=0)`. That is an INNER JOIN, so a `done`
  state row whose `papers` row was deleted is dropped from the result set entirely — the one orphan
  shape `delete_paper()` actually produces is the one shape `find_done_papers_without_chunks`
  cannot see. It catches the T-DOC23/T-DOC35 shape (paper row present, chunks missing) but not this
  one.
  **Deletion has no operator entrypoint at all.** `delete_paper` has zero non-test callers
  repo-wide (`rag/test_orchestrator.py:1240-1274` and the T-DOC82 plan's prose are the only
  references). There is no `app/` CLI for it, unlike every other operator action
  (`app/ingest.py`, `app/doctor.py`, `app/corpus_integrity.py`, `app/snapshot.py`, ...). Every
  deletion today is throwaway Python plus hand-written SQL — which is precisely how the
  stale-state trap gets hit, since an ad-hoc script has no reason to know about the third table.
  **Fix (three parts):** (a) add a `forget(paper_id)` method to the ingest-state adapter that
  removes the `ingest_state` and `ingest_checkpoint` rows in one transaction — the same two
  statements `quarantine()` already runs, lifted into their own method and called from both
  places; mirror it on `rag/fakes/fake_ingest_state.py`'s `FakeIngestState` so the zero-GPU suite
  can assert it. (b) call it from `IngestionOrchestrator.delete_paper` *after* the two store
  deletes, preserving the existing deliberate ordering rationale in that method's docstring
  (SQLite first, then vectors) — state last, so a crash mid-delete leaves a re-runnable
  `delete_paper`, never a resurrectable-looking document. (c) add an `app/delete_docs.py` operator
  CLI taking one or more paper_ids, using the real assembly wiring, so no operator ever needs raw
  SQL for this again. Optionally also widen `corpus_integrity`'s query to a LEFT JOIN so the
  papers-row-missing shape is reported.
  **Blocking note:** until this lands, each of the four remaining books queued for T-DOC82
  re-ingest needs its `ingest_state`/`ingest_checkpoint` rows cleared by hand between the delete
  and the re-ingest.
  **Verified in production 2026-07-28:** `app/delete_docs.py` removed all five books' rows, vectors,
  and ingest-state with no hand-written SQL. Post-delete verification showed
  `papers`/`chunks`/`summaries`/`ingest_state`/`ingest_checkpoint` all zero for the five ids, and the
  subsequent re-ingest genuinely re-ran — the previous rollout had needed manual SQL to clear stale
  state.

### T-DOC85 — book chapter titles under the size-merge strategy are whichever heading happens to start the window (2026-07-27)

- **T-DOC85 (implemented — PR #177, merged 2026-07-28) — 🟡 strategy-B chapter titles are the first heading in the merge window,
  not the most representative one.** T-DOC82's `rag/book_summarizer.py::_merge_to_target`
  (strategy B) titles each merged unit by its **first** heading group
  (`units.append((title, list(blocks)))`, line ~104). That is deliberate and documented — B is
  text-independent by design, which is what makes it the safe general fallback — but the resulting
  label is arbitrary with respect to the unit's actual content.
  **Observed on the verified re-ingest of `local:f0929288d4f3`** (2026-07-27, 26 units over ~144k
  words, ~5.5k words each): the titles include real section names (`Why We Do Causal Inference`,
  `Canonical Difference-in-Differences`, `Neutral Controls`, `Regularized Regression`, `Optimal
  Switchback Design`) but also `Assign`, `See Also`, `F`, `\* and : Operators`, `PRACTICAL EXAMPLE`,
  and `Violations` — mid-chapter or incidental headings that happened to land at a window boundary.
  **Why it matters beyond cosmetics:** these strings are the routing labels. `summaries.title` is
  what `search_papers` surfaces as `ChapterHit.chapter` (ARCHITECTURE §M7), so an agent choosing
  which chapter to open sees `F` and gets no signal from it. The chapter *contents* are coherent —
  this is a labelling defect, not a splitting defect; the 26-unit split itself is correct and was
  verified by eye.
  Note this is strictly a strategy-B problem. Strategy A (explicit `Chapter N`/`Part N`/`Appendix X`
  markers) already yields real chapter titles; B runs precisely when a book has no such markers,
  which is the common case measured so far. T-DOC87 covers the strategy-A path this ticket does
  not reach: A's marker regex itself over-matches on some books, producing spurious unit boundaries
  before titling even applies.
  **Fix — needs a design decision, not obvious:** candidate approaches are (i) pick the most
  title-like heading within the unit rather than the first — e.g. longest, or first exceeding some
  word count, filtering single-character and punctuation-only headings; (ii) have the map-step LLM
  call emit a title line alongside the section summary, since it is already reading the full unit
  text and `kind="book"` already has its own prompt (`rag/summarizer.py::_BOOK_SECTION_PROMPT`) —
  costs no extra call, but makes the title model-generated and therefore subject to the same
  grounding caution as the summary; (iii) title the unit by a page range or ordinal (`Section 14
  (pp. 210-228)`) — always honest, never informative. Do not pick one in this ticket; record the
  options.
  **Verified in production 2026-07-28:** the three strategy-B books produced 16, 26, and 8 chapters
  with genuine section titles. The two strategy-A books remain broken — that gap is T-DOC87, and was
  already known before this rollout, not a new regression it introduced.

### T-DOC86 — the drop-in path has no topic-relevance signal, so an off-topic PDF ingests silently (2026-07-27)

- **T-DOC86 (implemented — PR #177, merged 2026-07-28) — 🟢 the drop-in folder applies no topic-relevance check, so any PDF
  placed there is ingested regardless of subject.** T-DOC80's drop-in folder
  (`app/ingest_local.py`) stages any PDF placed in `drop_in/` into the same pipeline as the arXiv
  corpus. Unlike the arXiv harvest path, which is inherently topic-scoped by its query
  (`focus_area`), the drop-in path applies no relevance check whatsoever — parse, chunk, summarize,
  embed, done.
  **Observed 2026-07-25 on the first live drop-in run:** `not-murphys-law-e-book-final (1).pdf` — a
  general-audience book unrelated to causal inference — was staged and ingested alongside the
  intended papers and books. It was caught only because a human read the first page manually with
  pypdfium2 after noticing its garbled extracted title; nothing in the pipeline flagged it. It has
  since been moved to `drop_in/excluded/`.
  **This is by design, not a regression** — the system has never had a topic gate, and the arXiv
  path never needed one. The drop-in folder is what changes the risk profile: dropping a wrong file
  into a directory is a much easier mistake than writing a wrong arXiv query, and the cost of a
  book-sized mistake is high (the verified run took 349s of GPU time for one book; the pre-T-DOC82
  run took 76 minutes).
  **Fix — cheapest useful version first:** a `--dry-run` / confirm mode on `app/ingest_local.py`
  that prints, per staged file, the detected title and the first ~500 characters of extracted text
  and requires operator confirmation before staging. That is one operator read against a whole
  book's ingest cost, needs no model, and no new dependency. A relevance *score* (embedding the
  summary against the configured `focus_area` terms and routing below-threshold documents to
  `drop_in/excluded/`) is the fuller version but needs a threshold nobody has data to set yet, and
  would run only after the expensive stages have already happened — note it as the upgrade path, do
  not build it.

### T-DOC87 — `_CHAPTER_MARKER` matches numbered list items, so Strategy A mis-splits books into non-chapters (2026-07-27)

- **T-DOC87 (not started) — 🟡 strategy-A's numbered-heading alternative matches ordinary numbered
  list items, not just chapter headings, producing spurious unit boundaries and titles.**
  `rag/book_summarizer.py`'s `_CHAPTER_MARKER` (line 38) has two alternatives; the second,
  `^\s*\d+\.\s+\S`, was meant to catch numbered chapter headings like `3. Estimation`. It also
  matches **any numbered list item that the parser emitted as its own heading group** — ordered
  lists in body text, procedure steps, reference lists.
  **Measured, 2026-07-27, on two real books in the corpus:**
  - `local:54d6ca71dda9` (*Causal Inference and Machine Learning in Economics, Social, and Health
    Sciences*): 252 heading groups, **43 of which match `_CHAPTER_MARKER`**. Sample matches:
    `2. Define Gini Index for a Node t`, `4. Choose Optimal Split Point for Each Variable`,
    `1. Setup: Define the Problem and Data`, `2. Second Stage:`,
    `1. https://freakonometrics.hypotheses.org/52776`, `4. Verify GPU availability:`. None is a
    chapter.
  - `local:dfe850b3281a` (*Causal Inference and Discovery in Python*): 530 heading groups, 6
    matches — of which 3 are genuine (`Part 1: Causality – an Introduction`,
    `Part 2: Causal Inference`, `Part 3: Causal Discovery`) and the rest are not, including
    `3. Finally, let's examine the results in Table 3.1:`. The genuine `Part 2`/`Part 3` titles each
    appear **twice**, producing duplicate chapter titles.
  **Why the existing plausibility guards don't catch it.** `_split_by_markers` already rejects an
  implausible split via `_MIN_MARKER_UNITS` (3), `_MAX_MARKER_UNITS` (60), and
  `_MAX_UNIT_WORD_SHARE` (0.5). 43 units is comfortably inside the 3-60 band, so the split is
  accepted. The guards were designed to catch a book that merely *mentions* "Chapter 3" once and
  produces 2 lopsided units — they do not catch the opposite failure, dozens of plausible-looking
  but spurious markers.
  **Why this is a SPLITTING defect, not the labelling defect T-DOC85 fixed.** T-DOC85 added
  `_title_score`/`_best_heading`, but those apply only inside `_merge_to_target` (strategy B).
  Strategy A titles units by whatever matched the marker. The obvious-looking fix — gate marker
  titles through `_title_score` and fall through to `""` when they score 0 — **was measured and
  does not work**: only 2 of the 43 junk titles on `local:54d6ca71dda9` score 0. Most score *well*
  (`4. Choose Optimal Split Point for Each Variable` scores 38, `1. Setup: Define the Problem and
  Data` scores 28, `2. Define Gini Index for a Node t` scores 22) because they are well-formed
  English. The titles are not the problem; the unit boundaries are.
  **Consequence.** These books get chapter *summaries* whose boundaries are arbitrary mid-body
  slices, and routing labels that read like procedure steps. Retrieval recall is unaffected —
  `rag/orchestrator.py` embeds the chapter summary's `text`, never its title — so this degrades the
  routing label and the summary boundaries, not whether content is findable.
  **Fix — needs a design decision, do not pick one in this ticket.** Candidates: (i) require
  numbered-heading markers to be *sequential from 1* across the document before accepting strategy
  A, so a scattered set of list items is rejected; (ii) require a marker's unit to exceed a minimum
  word count, so a one-paragraph list item can't be a chapter; (iii) drop the bare `^\d+\.`
  alternative entirely and rely on the `chapter|part|appendix` alternative plus strategy B's size
  merge, accepting that genuinely numbered-only chapter headings fall through to B; (iv) require
  markers to be consistent in *form* — all `N.` or all `Chapter N`, not a mixture. Record the
  options.
  **Discovered by** the final whole-branch review of the T-DOC84/85/86 branch (PR #177), which
  simulated the new splitter against every book's real `blocks` rows before the T-DOC85 rollout
  rather than after. **T-DOC85 improves 3 of the 5 books in the corpus; these two take the
  strategy-A path and are unaffected by it.**

### T-DOC88 — an operator has no deterministic way to set a drop-in document's title (2026-07-27)

- **T-DOC88 (implemented — branch `feat/t-doc88-explicit-title-marker`) — 🟢 added an opt-in
  `title--` filename prefix so a drop-in operator can state a document's title explicitly instead
  of hoping PDF extraction gets it right.** `app/ingest_local.py:mint_local_ref` (invoked from
  `stage_file` for every dropped file that isn't a recognized arXiv paper — the whole `books/` path
  plus any `papers/` file arXiv can't resolve) derives `title` through a three-rung fallback chain:
  `title_meta or _first_nonempty_line(first_page) or Path(filename).stem`. All three rungs are
  **extraction luck** — whichever one fires first depends entirely on whether the publisher
  happened to set PDF metadata, and if not, whatever text pypdfium2 finds first on page 1.
  **Measured against the five books live in the corpus, 2026-07-27:** four get good titles this way
  (*Causal Inference and Discovery in Python*, *Causal Inference and Machine Learning in Economics,
  Social, and Health Sciences*, *Causal Inference in Python*, *Causality: Models, Reasoning, and
  Inference*); one — `local:...` for *Handbook of Labor, Human Resources and Population Economics*
  — stores `Handbook of Labor, Human Resources and Population Economics (Mutlu Yuksel, Yigit
  Aydede)`, author names appended by whichever rung fired. This ticket does not repair that title
  (a stored title is not touched retroactively); it is *control* over what the next drop mints, not
  a fix for what's already in the corpus — Task 8 (re-ingest all five books) is the follow-up that
  will actually pick up a corrected filename.
  **Two alternatives were considered and rejected.** (i) "Always prefer the filename stem" —
  rejected because the operator's real filenames are libgen-style download names (e.g. `Matheus
  Facure - Causal Inference in Python_ ... (2023, O'Reilly Media) - libgen.li.pdf`), and the stem
  of that is a worse title than what extraction luck already produces for most files; it would fix
  the one bad book and break others. (ii) A heuristic blocklist of download-name shapes (strip
  `- libgen.li`, parenthesized publisher/year, etc.) — rejected on T-DOC82 precedent, which already
  refused an equivalent front-matter blocklist as open-ended: every new download source is a new
  shape, and the list never actually closes.
  **Design: an explicit, opt-in marker instead of a heuristic.** A new module-level constant
  `TITLE_PREFIX = "title--"` (`app/ingest_local.py:73`) and a new `_explicit_title(filename)`
  helper (`app/ingest_local.py:143-154`) are checked first, ahead of the existing three rungs:
  `title = _explicit_title(filename) or title_meta or _first_nonempty_line(first_page) or
  Path(filename).stem` (`app/ingest_local.py:167-172`). `_explicit_title` matches the prefix
  case-insensitively against `Path(filename).stem.lower()` — `Title--`/`TITLE--` also work, so a
  capitalization slip is never a silent fall-through the operator wouldn't notice until inspecting
  the corpus — and returns the remainder after the prefix, `.strip()`-ed and otherwise untouched
  (no underscore-to-space, no title-casing: the operator typed what they wanted). An empty or
  whitespace-only remainder (`title--.pdf`) returns `None`, i.e. falls through to the unchanged
  three-rung chain rather than minting an empty title. The mechanism is generic and applies to both
  `doc_type="paper"` and `doc_type="book"` with no branch on `doc_type` — a paper with bad metadata
  benefits identically, and a `doc_type` special-case would be unrequested complexity the marker
  doesn't need. `pdf_url` (`app/ingest_local.py:184`, `pdf_url=filename`) is left untouched and
  still carries the prefix verbatim — it is a provenance record of the file actually on disk, not a
  display title. The content-addressed `paper_id` (`sha256(pdf_bytes)[:12]`,
  `app/ingest_local.py:164,176`) is computed from `pdf_bytes` only and was never touched by this
  change — verified by
  `test_mint_local_ref_title_prefix_does_not_change_content_addressed_id`
  (`app/test_ingest_local.py`), which mints the same bytes under a plain and a `title--`-prefixed
  filename and asserts identical ids; this is load-bearing for the Task 8 re-ingest, which renames
  files in place without wanting to re-mint ids for already-cached content.
  **Second change: the `--dry-run` preview (T-DOC86, `_report_dry_run`) now reports the resolved
  title**, reusing `mint_local_ref`'s own return value (`app/ingest_local.py:378-386`) rather than
  re-deriving title logic a second time — a duplicate chain could silently drift from what actually
  gets stored. This is what closes the loop: an operator who forgot to add or misspelled the
  `title--` marker sees the wrong title in the preview before any GPU time is spent on parse/
  chunk/embed, instead of discovering it by inspecting the corpus afterward, the same discovery
  path that surfaced the *Handbook of Labor* author-name noise in the first place.
  **Tests** (`app/test_ingest_local.py`): prefix used; case-insensitive (`Title--`/`TITLE--`);
  whitespace stripped but not otherwise transformed; empty-remainder falls through; applies to
  `doc_type="paper"` as well as `"book"`; id unchanged by renaming; dry-run reports the title; and
  a regression pin (`test_mint_local_ref_no_prefix_title_unchanged`) asserting a file WITHOUT the
  prefix produces byte-for-byte the same title the pre-T-DOC88 chain already produced, against the
  real `fixtures/golden/2409.01266.pdf` fixture (no PDF metadata Title, so this exercises the
  `_first_nonempty_line` rung) — the assertion protecting the 11k-paper corpus and today's book
  behavior from an accidental change here.
  **Fix round 2 (2026-07-27): the marker now also overrides a successful arXiv fetch's title.**
  The original design above only reached `mint_local_ref` — and therefore `_explicit_title` — for
  files `stage_file` couldn't or didn't resolve via arXiv. A file whose filename or page-1 text
  *did* yield an arXiv id, fetched successfully via `fetch_by_ids`, used the fetched `PaperRef`
  wholesale (`fetched[0].model_copy(update={"doc_type": doc_type})`,
  `app/ingest_local.py:stage_file`) — the operator's marker was silently ignored for exactly the
  files most likely to already have a wrong or unwanted title (arXiv's own, e.g. a preprint's
  working title that differs from what the operator wants displayed). **The operator's ruling:** a
  `title--` marker is a deliberate act, and a deliberate marker outranks fetched metadata — so it
  must win in both branches, not just the local one. **Fix:** `stage_file`'s arXiv branch now
  checks `_explicit_title(path.name)` and includes `"title"` in the `model_copy(update=...)` dict
  only when it returns non-`None`, exactly mirroring how `doc_type` already overrode the fetched
  ref (`app/ingest_local.py:stage_file`, the `if fetched:` block). Every other fetched field —
  authors, abstract, categories, published, paper_id, version — is left exactly as arXiv supplied
  it; only `title` (and, as before, `doc_type`) are ever overridden. **The marker still only
  short-circuits the title *search*, not the PDF parse it depends on for other fields** —
  `mint_local_ref`'s fallback chain (`_explicit_title(filename) or title_meta or
  _first_nonempty_line(first_page) or Path(filename).stem`) already stopped at the first truthy
  value before this fix, but `_pdf_title_author` and `_safe_first_page` still run unconditionally
  either way, because their OTHER return values (`author_meta` for `authors=`, and the page-1 text
  for the `published` year regex) are needed regardless of whether a marker is present — a comment
  was added at the title chain (`app/ingest_local.py:mint_local_ref`) making this explicit rather
  than leaving it as a trap for the next reader who might try to skip those calls and quietly break
  `authors`/`published`. **`--dry-run` (`_report_dry_run`) updated to match:** it used to show
  `"(from arXiv metadata, not previewed offline)"` whenever `arxiv_id` was detected, because the
  local title chain's result would have been discarded by staging regardless of a marker (fix round
  1). That's no longer true — the preview now checks `_explicit_title` first and shows the marker's
  title in *either* branch (it's accurate now, since the marker really will be what's stored); only
  falls back to the arXiv label when no marker is present and `arxiv_id` is set; and shows the
  local chain's title as before when neither applies. Still zero network — no `fetch_by_ids` call
  added, per its existing offline contract.
  **Tests** (`app/test_ingest_local.py`): `test_stage_file_title_marker_overrides_fetched_arxiv_title`
  (marker wins over a successful fetch, with explicit assertions that authors/abstract/categories/
  published/paper_id/version all survive untouched — the assertion that would catch an over-broad
  `model_copy`); `test_stage_file_no_marker_fetched_title_used_unchanged` (regression pin: no
  marker still uses the fetched title verbatim); `test_stage_file_title_marker_wins_on_fetch_failure_too`
  (marker + a failing fetch falls back to `mint_local_ref`, where the marker still wins);
  `test_dry_run_shows_arxiv_label_when_no_marker_present` (new: the label is still shown when there
  really is no marker to preview). One existing test,
  `test_dry_run_does_not_preview_local_title_for_arxiv_detected_file` (added in fix round 1), tested
  exactly the behavior fix round 2 reverses — that a marker was hidden behind the arXiv label. It
  was renamed to `test_dry_run_shows_marker_title_for_arxiv_detected_file` and its assertions
  flipped to match the new rule, with a note in its docstring explaining why: this is an intentional
  update to a test that encoded round 1's now-superseded behavior, not a regression.
  **Confirmed in production (2026-07-28 re-ingest of all five books).** `local:54d6ca71dda9`
  produced **44 chapters** whose titles are numbered list items lifted from body text. Verbatim
  examples: `1. https://freakonometrics.hypotheses.org/52776`, `2. DiD%20Resources`, `4. Verify GPU
  availability:`, `2. Define Gini Index for a Node t`, `5. Recursive Partitioning: Split Left and
  Right Nodes`, `8. Cross-Validation to Select Optimal Tree Size`. The unit *boundaries* are
  arbitrary mid-body slices, not just the labels. `local:dfe850b3281a` produced **7 chapters** for
  an entire book, including `3. Finally, let's examine the results in Table 3.1:`.
  **NEW FINDING — duplicate titles.** In `local:dfe850b3281a`, `Part 2: Causal Inference` appears as
  the title of BOTH chapter 2 and chapter 5, and `Part 3: Causal Discovery` as BOTH chapter 3 and
  chapter 6. Two distinct routing units carry byte-identical labels, so an agent selecting a chapter
  by title cannot distinguish them — `search_papers` surfaces the title as `PaperSearchResult.chapter`.
  This is strictly worse than an unhelpful label and was not anticipated when the ticket was filed.
  Record it as an added requirement: the fix must guarantee UNIQUE chapter labels within a document,
  not merely plausible ones.
  **Contrast, same run:** the three books that took the strategy-B size-merge path produced 16, 26,
  and 8 chapters with genuine section titles (e.g. `Hypothesis Testing: Establishing Statistical
  Significance`, `Goodhart's Law, Campbell's Law, and the Lucas Critique`). T-DOC85 works; it simply
  never reaches strategy A.
  Also record the known strategy-B ceiling observed on `local:f6c64e1e8c7d` (8 chapters): where every
  heading inside a merged window is mid-content, the chosen title is mid-content too —
  `{probabilistically/interventionally/counterfactually} equivalent`, `Example 9.2 Consider the
  following SCM`, `C.2 Proof of Proposition 6.3`. Not a defect of T-DOC85's scorer (it picks the
  best of what exists) but a real limit worth noting beside T-DOC87.

### T-DOC89 — config resolution depends on the current working directory, and has silently corrupted results four times (2026-07-28)

- **T-DOC89 (part 1 implemented — branch `fix/t-doc89-config-resolution`; spec:
  `docs/superpowers/specs/2026-07-28-operability-config-resolution-design.md`) — 🔴 `load_config`'s
  default path resolves against the process's current
  working directory, and paths inside a resolved config are cwd-relative too — the combination has
  silently produced wrong results four times.** `rag/config.py`'s `load_config(path="config.yaml")`
  resolves its default relative to the **process's current working directory** — its own docstring
  says so. Two problems compound:
  1. **Which config file you get depends on where you stand.** Two exist.
     `/home/omar/ai-projects/research-system-rag/config.yaml` is **tracked in git**, a template
     whose every path is relative (`db_path: "papers.db"`, `blob_dir: "blobs"`, `pdf_cache_dir:
     "pdf_cache"`, `drop_in_dir: "drop_in"`). `/home/omar/ai-projects/research-system-rag-data/config.yaml`
     is untracked, outside the repo, and real — all paths absolute, pointing at the actual
     11,026-document corpus.
  2. **Paths *inside* a config are also cwd-relative.** The template's `db_path: "papers.db"` does
     not mean "the repo's database"; it means "a `papers.db` wherever this process happens to be
     running." From the repo root that resolves to an empty, migrated, 0-row stub file.
  **Every failure mode is silent** — no exception, no warning, just wrong results.
  **Four recurrences, three of them already ticketed:**
  - **OG-33** — relative-path runs creating empty/partial `papers.db`/`pdf_cache` copies at the repo
    root. Mitigated by `.gitignore` entries (lines 6-14), which stop them being *committed* but not
    created.
  - **T-DOC56** — the empty repo-root `papers.db` was what `build_mcp_server` silently fell back to,
    producing a **false benchmark result of Recall@10 = 0.000**. The `.gitignore` comment still
    records this as "the fake Recall@10=0.000 trap".
  - **T-DOC22** — a process whose cwd differed from ingest's.
  - **2026-07-28, this rollout, twice.** `app/delete_docs.py` called
    `build_ingestion_orchestrator(load_config())` without `db_path`/`blob_dir`/`collection`; that
    function defaults `db_path = db_path or "papers.db"`, so run from the repo root — where
    `docs/RUNBOOK.md` tells the operator to stand — the deletion tool would have deleted nothing,
    logged five successes, and exited 0. Caught by the final whole-branch review of PR #177, not by
    any test. Then, operating the corrected tool, `app.ingest_local --dry-run` reported "no PDFs in
    drop_in" from the data directory (whose config has no `drop_in_dir`, so it defaulted to a
    relative `drop_in` that does not exist there), while running from the repo root would have found
    the books but targeted the empty stub database. **Neither working directory was correct**; the
    rollout proceeded only via an explicit `--drop-dir` override, which is a workaround, not a fix.
  **Corroborating artifact:** a stray 20-file `pdf_cache/` currently sits in the repo root, evidence
  that something has already run in the wrong place.
  **`docs/RUNBOOK.md` documents no working-directory convention at all** — grepping it for `cd`,
  `config.yaml`, `RAG_CONFIG`, `drop_in`, or "working directory" returns nothing.
  **Fix — designed to be correct by default, not to fail first.** The operator was explicit that
  this must not become a tool that fails repeatedly; it should resolve the right config on its own,
  and when it genuinely cannot, say exactly what it tried and what to set. Three parts:
  1. **A config describes itself.** Relative paths *inside* a config resolve against **that config
     file's own directory**, not cwd. `drop_in` in the repo template then permanently means
     `<repo>/drop_in` from anywhere. This alone eliminates the "ran from the wrong place" class — a
     config stops being instructions whose meaning shifts underneath the process.
  2. **Discovery that finds the right file unaided.** Precedence: explicit `--config` argument →
     `RAG_CONFIG` environment variable → `config.yaml` in cwd → walk up parent directories → only
     then an error that names every location tried and both ways to fix it. Rename the tracked
     template to `config.example.yaml` so it is not *named* `config.yaml` and therefore can never be
     discovered by accident — that is what stops the wrong file winning, without requiring anyone to
     be disciplined about cwd. Rollout sets the link once (either `RAG_CONFIG` exported, or a
     gitignored symlink at the repo root pointing at the real config) so the common path works from
     day one and the error path is genuinely rare.
  3. **Always report what was resolved.** Every `app/` entrypoint logs its resolved absolute
     `db_path`, `collection`, and `drop_in_dir` at startup. `app/delete_docs.py` already does exactly
     this — added after the final review caught the bug above — so this generalizes a proven pattern
     rather than inventing one.
  **Risks to check during implementation, not to assume away:** `rag/config.py` and `config.yaml`
  are both CODEOWNERS foundation paths, so this needs the `foundation-change` label. Renaming a
  tracked config is the risky part — verify nothing else depends on that filename (CI workflows, the
  corpus dashboard, `app/serve.py`, tests) before committing to it.
  **Part 1 implemented (this section only, §1-3 of the design):** a config resolves its own paths
  against its own directory, the tracked template moved to `config.example.yaml` so it can't be
  discovered by accident (plus a stub-validation warning when a resolved `db_path` lands inside the
  repo tree), and `load_config()`'s no-arg default runs real discovery (`RAG_CONFIG` -> cwd -> walk
  up to the repo boundary) instead of a bare cwd-relative `open()`. §4-7 (resolved-path startup
  logging, `init_config`, doctor/runbook checks, deleting the stray repo-root `papers.db`/
  `pdf_cache/`) are part 2, a separate branch.
  **Design-doc review found three Criticals part 1's own design didn't anticipate**, all fixed on
  the same branch: (1) §1's absolute-path resolution silently defeated
  `app/dashboard/controller.py::_resolve_override_config`'s `(data_dir / value)` re-rooting
  whenever `_load_base_config`'s fallback branch fired (already-absolute paths make that join a
  no-op) — reopened OG-49#1; fixed by resetting the fallback's path fields back to the plain
  `Config` class defaults before handing them to the override resolver. (2)
  `app/dashboard/server.py`'s module-level `_STATIC_CONFIG = load_config()` made the whole module
  unimportable (and `scripts/dashboard.sh` unable to start) in any checkout with no real deployed
  config discoverable from the repo root — fixed by making it a lazy `@lru_cache`d
  `_static_config()`, since every actual use site was already inside a function body. (3)
  discovery's cwd/walk-up rungs returned the candidate unresolved while the explicit/`RAG_CONFIG`
  rungs called `.resolve()` — a symlinked repo-root `config.yaml` (the design's own rollout
  mechanism) would silently resolve relative paths against the SYMLINK's directory instead of the
  real target's, re-creating OG-33 one level down.

### T-DOC90 — document titles are never derived from OCR, so an image-cover book falls through to its filename (2026-07-28)

- **T-DOC90 (not started) — 🟢 title extraction never sees OCR output, so a book whose cover page is
  a scanned image with no text layer falls all the way through to its raw filename stem.**
  Explicitly a documented future option, not work to schedule now. The operator's current answer is
  to name drop-in files with T-DOC88's `title--` prefix, which is deterministic and requires no
  inference. This ticket exists so the scalable alternative is on record for when files arrive
  without a marker.
  **The measurement (2026-07-28, the five corpus books).** `app/ingest_local.py`'s `mint_local_ref`
  resolves a title through `_explicit_title(filename) or title_meta or
  _first_nonempty_line(first_page) or Path(filename).stem`. The `first_page` there comes from
  `_first_page_text`, which uses **pypdfium2's `get_textpage().get_text_bounded()` — embedded
  text-layer extraction, with no OCR whatsoever.** Measured text-layer characters on page 1:

  | book | page-1 text chars | PDF metadata Title | source actually used |
  |---|---|---|---|
  | `local:dfe850b3281a` | **0** | "Causal Inference and Discovery in Python" | metadata |
  | `local:54d6ca71dda9` | **0** | *(empty)* | **filename stem** |
  | `local:f0929288d4f3` | **0** | "Causal Inference in Python" | metadata |
  | `local:f6c64e1e8c7d` | **0** | "Elements of Causal Inference" | metadata |
  | `local:14b7e283bdcd` | 2438 | *(empty)* | first line of page-1 text |

  **Four of five book covers carry no text layer at all** — they are images. The first page
  contributed a title for exactly one book, and only because that one happened to ship a text layer.
  **This explains a real observed defect.** Before the operator renamed the files,
  `local:54d6ca71dda9`'s stored title was `Causal Inference and Machine Learning In Economics,
  Social, and Health Sciences (Mutlu Yuksel, Yigit Aydede)` — with author names appended. That book
  has neither PDF metadata nor a page-1 text layer, so the chain fell all the way through to the raw
  libgen-style filename stem. The title was never extracted from the document at all.
  **The pipeline does have OCR — at the wrong time.** MinerU runs `OCR-det`/`OCR-rec` and is how
  these books get parsed at all. But that happens at *parse* time, whereas `mint_local_ref` fixes the
  title at *staging* time, before MinerU sees the file. OCR output has never been available to the
  title chain.
  **The option to record:** after parsing, refine a title that fell through to the filename stem by
  taking the first heading of the OCR'd markdown. That would have produced a correct title for
  `local:54d6ca71dda9` with no renaming.
  **Two caveats that must be weighed if this is ever built:** (a) it means a document's title changes
  *after* staging, while the `PaperRef` sidecar is written earlier — so the sidecar/`papers` row
  relationship needs deciding; (b) it reintroduces inference where T-DOC88 now provides a
  deterministic operator control, so it should apply only as a fallback when no `title--` marker is
  present and the chain would otherwise land on the filename stem.

### T-DOC91 — the MCP SDK is pinned below a major version we have not evaluated (2026-07-28)

- **T-DOC91 (not started) — 🟡 `environment.yml` now pins the MCP SDK to `<2`, which stops the CI
  breakage recorded below but permanently cuts us off from every 2.x release — including security
  fixes — until someone deliberately migrates.** **What happened (2026-07-28):** CI went red across
  `main`, #181, and #182 with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` at
  `app/serve.py:32`. Root cause was not a code or test defect: `environment.yml` had declared the SDK
  as a bare `- mcp` with no version constraint; PyPI published `mcp 2.0.0`; CI, which builds a fresh
  environment on every run, installed it; `2.0.0` removed or moved `mcp.server.fastmcp`. The local dev
  environment had `1.28.1` already installed, where the import still works, which is why every local
  test run stayed green while CI was red — the defect was invisible from the developer's own machine.
  Fixed in PR #183 by pinning `mcp>=1.28,<2` (`environment.yml:41`).
  **The API surface an upgrade must re-verify:**
  - `app/serve.py:32` — `from mcp.server.fastmcp import FastMCP`
  - `app/serve.py:75` — `FastMCP("research-system-rag")`
  - `app/serve.py:78,92,…` — the `@mcp.tool()` decorator on each of the four MCP tools
  - `app/serve.py:22` — stdio transport via `mcp.run()`'s default; the module docstring records that
    choice explicitly
  - `app/mcp_verify_client.py` — the client half, used by the connectivity check T-DOC66 adds to
    `app/doctor.py`
  **Why a ceiling is a deferred obligation, not a fix.** `<2` means we no longer receive 2.x releases
  at all, including security fixes. If a vulnerability is found that upstream only patches on the 2.x
  line, the migration becomes urgent and unplanned — exactly the situation a pin exists to avoid.
  Migrating deliberately, on our own schedule, is cheaper than migrating under a CVE.
  **Fix — evaluate and migrate to 2.x on purpose.** Read the 2.0 changelog for what replaced
  `mcp.server.fastmcp`; port the four tool registrations and the transport choice; re-verify with
  `app/mcp_verify_client.py` and the `app/doctor.py` MCP connectivity check (T-DOC66) that the server
  launches and answers `list_tools`; then raise the ceiling. Re-check the stdio transport decision at
  the same time, since transport is the most likely thing to have changed across a major version.
  `app/doctor.py`'s MCP check is what makes this migration verifiable end to end, rather than another
  change that only local dev happens to exercise.

### T-DOC92 — ten more dependencies remain unpinned and can break CI the same way (2026-07-28)

- **T-DOC92 (not started) — 🟢 `environment.yml` still declares ten packages with no version
  constraint, each capable of reproducing T-DOC91's CI break with zero change on our side.** The
  unpinned set: `pytest`, `pytest-cov`, `pytest-socket`, `qdrant-client`, `pyyaml`, `httpx`,
  `filelock`, `ruff`, `pypdfium2`, `markdownify`. Because CI builds a fresh environment on every run
  (the same mechanism that turned `mcp`'s unconstrained entry into a red build), any of these can
  break CI spontaneously on a new upstream release, with no PR of ours as the trigger.
  `qdrant-client` and `pypdfium2` carry the most risk, being the vector-store and PDF-parsing adapters
  respectively — both sit on the critical path of ingestion and retrieval. `ruff` is next: several CI
  enforcement checks in `ci/` shell out to it, so a new lint rule shipping in a minor release would
  surface as a spurious enforcement violation unrelated to any real code change.
  **Deliberately not fixed alongside the mcp hotfix**, which was kept to one line (`environment.yml:41`)
  so it could merge fast while `main` was red; broadening it to ten packages would have widened the
  diff and slowed the fix everyone was blocked on.
  **Fix needs a judgement call, not a script:** pinning everything maximizes reproducibility but
  creates upgrade churn — every pin becomes a future manual bump. Pinning only the adapters whose APIs
  we call directly (`qdrant-client`, `pypdfium2`, arguably `ruff` for its CI role) is a middle path
  that leaves general-purpose libraries (`pytest`, `pyyaml`, `httpx`, `filelock`, `markdownify`,
  `pytest-cov`, `pytest-socket`) floating. Recording both options here; not choosing one.

### T-DOC93 — 🟢 LOW: `_strip_duplicate_heading` misses one chunk per document, cause unknown (2026-07-28)

- **T-DOC93 (code fix implemented; re-chunk retrofit for the 34 affected papers still pending) —
  🟢 `_strip_duplicate_heading` still leaves a duplicated heading in exactly one chunk per
  affected document.** Cause found: `_build_chunk` (`rag/chunker.py:160`) ran the dedup check
  against `first.text` unconditionally, but when a split's `overlap` block is present it is
  prepended ahead of `first.text` in `body` — so `overlap.text`, not `first.text`, is the body's
  true opening line. A split's first sub-group can end up containing nothing but the section
  heading (a small heading block immediately followed by a single block so large it alone blows
  `_MAX_CHUNK_WORDS`), and that heading-only block then becomes the *next* sub-chunk's borrowed
  `overlap`, landing unchecked as body's real first line — duplicating the title+section_path
  prefix. Fixed by running the dedup check against whichever block actually opens `body` (overlap
  when present, else `first`), not unconditionally against `first.text`. Reproduced with a
  synthetic fixture in `rag/test_chunker.py::test_overlap_carrying_the_section_heading_is_not_duplicated_in_the_next_sub_chunk`
  (fails on prior `main`, passes after the fix) — no corpus data was touched to find or fix this.
  This is a re-chunk trigger for the 34 affected papers; `app/rechunk.py` (T-DOC62 option B)
  already exists to retrofit it and has not yet been run for this fix. All figures below were
  measured read-only against the live corpus on 2026-07-28; they are not to be re-derived.
  T-DOC62's analysis measured duplicate-heading rates before and after the chunker fix
  (`rag/chunker.py::_strip_duplicate_heading`, commit `157af4d`, 2026-07-17): 58.49% of pre-fix
  chunks duplicated, **0.01% of post-fix chunks**. The fix works. But 0.01% should be 0.
  **The residue has a very specific signature — 34 papers, exactly one affected chunk each**,
  regardless of document size (1 of 10 chunks, 1 of 85, 1 of 647, 1 of 1444; two papers have 2).
  That uniformity is the interesting part: a legacy-data explanation would show the pre-fix ~58%
  rate within an affected paper, and it does not.
  **It is a live bug, not stale data.** One of the 34 is `local:54d6ca71dda9`, a book **deleted and
  re-ingested on 2026-07-28** with the current chunker. Whatever this is, it still happens on every
  ingest.
  **The affected chunks share a shape.** They sit at high chunk indices (`2410.15166:c23`,
  `2505.13921:c42`, `2511.17170:c80`, `2606.12968:c66`) and their `section_path` values skew toward
  document furniture and repeated headings: `References` (multiple papers), `Contents`, `Dataset:`,
  `Confidential`, `6 Numerical Simulations`, `CAgent – Weight Reconciliation`.
  **Why the obvious explanations were ruled out:**
  - *Not* misclassified pre-fix data — see the one-chunk-per-paper uniformity above.
  - *Not* two adjacent byte-identical heading blocks (an initial hypothesis). Checked directly on
    `2410.15166`: that paper has **zero** adjacent byte-identical blocks sharing a `section_path`,
    and its `section_path = "6 Numerical Simulations"` section begins with exactly one heading block
    followed by ordinary prose.
  - *Not* a whitespace or unicode normalization mismatch. The stored chunk's line 1 (`section_path`)
    and line 3 (first body line) are **byte-identical** — verified with `repr()` on both, `L[1] ==
    L[3]` is `True`. So `_strip_duplicate_heading`'s comparison, which normalizes with `"
    ".join(x.split())`, should have matched and stripped.
  **Cause unknown.** The comparison that should fire, doesn't, on exactly one chunk per document.
  Investigation should start from `rag/chunker.py:178` —
  `group_texts = [_strip_duplicate_heading(first.text, first.section_path)]` — and establish which
  chunk in a document takes a path where `first` is not the block the stored text's line 3 came
  from. Note that when the strip *does* work, the resulting chunk text has an empty line 3, so the
  failing cases are distinguishable by that alone.
  **Impact is small but real:** ~0.01% of chunks carry a duplicated heading, wasting embedded tokens
  and showing the heading twice in a retrieved passage. Same symptom as T-DOC62, ~4000× rarer.
  **Fix:** find the actual cause before changing anything — the byte-identical evidence means the
  current hypothesis space is empty, and a speculative fix risks masking it. Once understood, the
  repair is likely small and belongs in `rag/chunker.py`. Any fix is a **re-chunk trigger** for
  affected papers, and `app/rechunk.py` (T-DOC62 option B) is the tool that retrofits it, so this
  can ride along with a future re-chunk rather than needing its own migration.
  **Discovered by** the T-DOC62 option B work (PR #185), while characterising the post-fix residue.
