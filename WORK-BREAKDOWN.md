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
  `rag/config.py`, `config.yaml`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`) **without**
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
  in `.github/CODEOWNERS` (currently `contracts/`, `rag/config.py`, `config.yaml`, `migrations/`,
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
- **T-DOC12** (`T-DOC12-parse-phase-error-boundary`) — a real 2,000-paper end-to-end run crashed
  the whole `parse_phase()` subprocess (and, via `app/ingest.py`'s `subprocess.run(...,
  check=True)`, the parent `app.ingest` process too) when one paper's GROBID reference-extraction
  call raised `TransientError`: `rag/orchestrator.py`'s `_prepare()` only ever caught
  `PermanentError` around `parser.parse(ref)`, so the `TransientError` propagated out of
  `ingest()` and every paper still queued behind the failing one lost its progress for that run.
  Added a bounded retry (`IngestionOrchestrator.__init__`'s new `max_retries`/`retry_sleep`,
  same shape as `rag/harvester.py`'s `Harvester`) then quarantine for `TransientError` from
  `parser.parse`, alongside the pre-existing (and already-correct) immediate quarantine for
  `PermanentError`. `_finish()`'s matching gap (`summarizer.summarize`/`embedder.embed` in
  `finish_phase()`) was found but is a separate, not-yet-filed follow-up ticket.

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
