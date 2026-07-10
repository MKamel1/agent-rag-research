# TEST-STRATEGY — how V0 is tested

Testing is what lets five people build nine modules in parallel and have them fit together. The strategy is
built on one idea from the architecture: **the interface is the test surface.** You test each module by
driving its interface with fakes at the seams — never by reaching inside it.

Golden rule: **downstream unit tests run with zero GPU and zero network.** If a test needs a live Qdrant or a
loaded embedding model to run, it's in the wrong layer. The real adapters are exercised only by their own
isolated contract tests.

**Second rule: assert on fields, not full equality, for extensible envelopes.** `GroundedResult`,
`PaperSearchResult`, `SearchResponse`, `PaperSearchResponse` are forward-compat records — V1/V2 fill
`evidence_tier`/`metadata` rather than changing the type (ARCHITECTURE §M7 "Forward-compat"). A V0 test
that asserts full dataclass equality (`result == GroundedResult(...)`) stays green today (V0's `metadata`
is always `{}` and `evidence_tier` always `"A"`), but the moment V1 populates either field, that same test
starts failing on every module that touches the envelope — not because behavior broke, but because the
test pinned optional fields it didn't need to. Prefer asserting the fields the test actually cares about
(`result.anchor.paper_id == expected_id`, `result.passage_text == expected_text`) over `==` on the whole
object. This is a preference for new tests, not a retroactive rewrite of existing ones.

---

## The four kinds of test (and when each applies)

| Kind | What it checks | Speed / deps | Who writes it |
|---|---|---|---|
| **Unit (via fakes)** | one module's behaviour through its interface | ms, no GPU/net | every owner, for their module |
| **Golden fixtures** | Parser output on real PDFs (the one thing fakes can't cover) | seconds, no net | Owner B |
| **Contract tests** | a fake and its real adapter behave identically at the seam | slow (real deps) | Owner of the seam (C, D) |
| **Retrieval eval** | end-to-end retrieval quality on labeled questions | slow | Owner E, questions agent-generated |

---

## Fakes (Owner F builds these first; everyone depends on them)

A fake is a **large adapter with a small implementation** — it satisfies the real interface with trivial,
deterministic behaviour so downstream modules can be tested in isolation.

**`FakeEmbedder`** — deterministic hash→vector. Same text always yields the same vector; different texts yield
different ones; output is L2-normalized and length `dim`. No model, no GPU. This is the default `Embedder` for
every test of Chunker/Retriever/Orchestrator.
```python
def embed(self, texts):  # deterministic, order-preserving
    return [self._hash_to_unit_vector(t, self.info.dim) for t in texts]
```

**`FakeVectorStore`** — in-memory dict of vectors + a brute-force search: dense = cosine over all vectors,
sparse = simple BM25/token-overlap over `qtext`, fused with the *same RRF* the real store uses. Powers all
`Retriever` tests. Because it fuses the same way, a test that passes here should pass against Qdrant — which is
exactly what the contract test verifies.

**`FakeSource`** — yields a fixed list of `PaperRef`s from a fixture file (no arXiv calls); the fixture
**must include two versions (`v1`/`v2`) of at least one base `paper_id`** so the dedup-by-base-id assertion
in T-A1 is exercised rather than vacuously true. Also accepts an optional error-injection map (`{paper_id:
TransientError | PermanentError}`) so Harvester's retry/quarantine paths (T-A1) have something concrete to
trigger, rather than being untestable without a real flaky API. Used to test the Harvester's dedup/resume
and the Orchestrator end-to-end.

**`FakeSummarizer`** — deterministic (e.g. a fixed-length truncation of the input `ParsedDoc.markdown`), no
model, no GPU. Default `Summarizer` dependency for every test of `IngestionOrchestrator` and any module that
needs a `PaperRecord.summary_text`.

**`FakeReranker`** — deterministic but **non-identity**: reverses the input candidate order (a pure
reorder — `RerankCandidate` carries no score, so nothing is actually scored), no model, no GPU. Also
records every call into `.calls` (`(query, [c.id for
c in candidates])`). This is what makes the "zero GPU" claim for Retriever tests actually meaningful, since
`retrieve()`'s pipeline includes a real cross-encoder rerank step in production — an **identity** fake was
tried first and rejected: it made every Retriever test pass identically whether or not `rerank()` was even
called, so a `retrieve()` that dropped the call, reranked the wrong slice, or mismatched ids would still
have passed. With a non-identity fake, a Retriever test must assert the final order actually **differs**
from the pre-rerank RRF order and **matches** the fake's reversal — see the Retriever bullet below.

**`FakeGpuLock`** — a no-op context manager (`contextlib.nullcontext`) that also records each `stage` label
passed to `.acquire(stage)` into an `.acquired` list. Default `GpuLock` dependency for every test of
`Embedder`/`Summarizer`/`Reranker`'s real adapters and of `IngestionOrchestrator`/`Retriever` — lets a test
assert a GPU-bound call acquired the lock (via `.acquired`) without a real file or a second process.

All six implement the **exact** interfaces in ARCHITECTURE.md / DATA-CONTRACTS.md. If the real interface
changes, the fake changes with it (they're tested together — see contract tests).

---

## Golden fixtures (Parser — the one place correctness can't be faked)

Parsing is the only stage whose correctness depends on messy real-world input, so it's tested against
hand-checked truth.

- A small set (~8–12) of real PDFs from the causal-methods corpus: math-heavy, code-heavy, multi-column,
  table-heavy, and one deliberately broken/scanned PDF (to test quarantine).
- For each, a committed expected `ParsedDoc` (or the assertions that matter: block count in range, equations
  present as LaTeX, every block has page+bbox, section paths sane, references parsed).
- **Every Parser adapter (MinerU/Marker/Docling) runs the same golden set** — that's how Spike 1 picks one and
  how a later swap stays safe.
- The broken PDF must raise `PermanentError` and be quarantined, not crash the run.

Don't assert exact string equality on the whole markdown — parsers vary in whitespace. Assert the **invariants
that downstream modules rely on** (anchors valid, equations preserved, reading order).

---

## Contract tests (the safety net for every swap seam)

For each real seam, **the same assertion suite runs against the fake and the real adapter.** This is what makes
"swap Qdrant for LanceDB" or "swap the embedding model" safe.

- `Embedder` contract: determinism, output length == input length, vector dim == `info.dim`, normalization.
  Run against `FakeEmbedder` (fast, in CI) and the real TEI-served model (nightly / on demand, needs GPU).
- `VectorStore` contract, **split in two** (a strict full-ordering "RRF matches on both" test was found to be
  unachievable — `rank_dense`/`rank_sparse` come from unrelated dense/sparse computations on each side, so
  agreeing exactly past the top few results would be luck, not correctness, and an agent hitting that
  flakiness would be tempted to quietly weaken the assertion while keeping its name):
  1. **`rrf_fuse` unit test (fast, CI, no adapters involved):** `contracts/fusion.py`'s pure function is
     tested directly against synthetic rank-list inputs — asserts `RRF_K=60`, 1-indexed ranks, and that
     changing `hybrid_dense_weight` changes the result in the expected direction. This is the actual arbiter
     of "is the formula right," and it's what makes the formula frozen in a checkable sense rather than a
     shared prose description two adapters each reimplement.
  2. **Cross-adapter "best-effort agreement" smoke test (weaker, explicit tolerance):** upsert→search
     round-trips the id; `SearchFilters` cases (categories, published date range, `kind`) filter identically
     on both; `rebuild()` reproduces results; and the **top-1** result (not the full ordering) matches
     between `FakeVectorStore` (CI) and real Qdrant (needs the Docker service) on a fixture engineered so one
     document dominates both the dense and sparse signal. Both adapters must call the same `rrf_fuse`
     (from `contracts/fusion.py`) — never a local reimplementation — so if they disagree even on top-1,
     that's a real bug in one adapter's rank-list construction, not fusion-formula drift.
- `Reranker` contract: the real adapter is checked in isolation — there is no second reranker adapter to
  prove agreement against in V0 (ARCHITECTURE principle 4), so this is a unit test of the real adapter's
  shape, not a fake/real agreement test. (`FakeReranker` itself is still **non-identity** — see "Fakes"
  above; this bullet is about the real adapter's own contract test, not `FakeReranker`'s behavior.)
- `Summarizer` contract: `FakeSummarizer` powers every downstream test; the real adapter is checked only
  for non-empty output on the golden-fixture set (summarization quality isn't machine-gradable in V0 the
  way retrieval is — no numeric gate, unlike Embedder/VectorStore).

If the fake and the real adapter disagree, one of them is wrong — fix it before trusting any downstream test
that used the fake.

---

## Retrieval eval set (the headline quality gate — from Spike 2)

**Agent-generated, no human labeler (PRD §11 Q6, RESOLVED).** A teacher-student pattern:

- **(a) Generation.** After Spike 1's parser + chunker run over the golden/representative papers, sample
  chunks stratified across CONTEXT.md's 6 V0 sub-topics (causal ML / inference / discovery /
  treatment-effect estimation / representation learning / causal-LLM setups), section type
  (method/results/related-work), and equation-bearing vs. prose blocks — capped per paper so no single
  paper dominates. Prompt the local generation LLM (same tier as Summarizer, ADR-08 — no new dependency)
  to write **one natural question each sampled chunk answers**. **Gold label = that chunk's `chunk_id`**
  — this is what makes Recall@10/MRR computable with zero human labeling: the gold answer is
  definitionally the source chunk. Commit to `fixtures/eval/eval_set.jsonl`:
  `{question, gold_chunk_id, paper_id, sub_topic, generator_model, prompt_version}`.
- **(b) Automated judge/quality filter.** A second LLM pass discards degenerate generated questions:
  near-verbatim question/chunk lexical overlap (would be trivially retrievable), questions answerable
  without the passage (general knowledge), under-specified questions (the gold chunk isn't uniquely the
  target), and questions answerable from the title/section-path prefix alone rather than the chunk body.
  Over-generate ~300, target **~200 survivors** committed (raised from an earlier ~50-question plan now
  that generation is compute, not a human labeling bottleneck — ~200 tightens the Recall@10 confidence
  interval and gives each of the 6 sub-topics enough questions to expose sub-topic-specific failures).
- **(c) Explicit caveat — read this, don't try to engineer it away.** Questions generated *from* a chunk
  carry higher lexical/semantic overlap with it than an independent user's phrasing would, so
  **Recall@10 on this set is an optimistic upper bound, not a guarantee of real-world query quality.**
  It's still valid as a **permanent regression gate** — a swap that drops it is still worse — just don't
  read "Recall@10 = 0.85 on this set" as "0.85 on real user queries."
- This is a **build-time QA** decision, distinct from CONTEXT.md's *runtime* "no human in the loop"
  principle (agent-as-reasoner, no approval queue) — using an LLM to build a test fixture doesn't touch
  the ~0-API-cost *runtime* property.

Runs against the **real** `Retriever.retrieve()` end-to-end and reports **Recall@10 and MRR**.
- Also record **retrieval-failure rate** (faithfulness ≠ correctness — PRD §11B): how often the right passage
  simply wasn't in the returned set.
- **Tag context-related failures** (chunk retrieved-adjacent but scored low because it reads ambiguously
  without surrounding text) — this is the monitoring signal handed to V1 for the contextual-header decision
  (ADR-07). Record the rate; V0 does not act on it.
- This set is permanent: it's the **regression gate** for any future embedding-model or vector-DB swap. A swap
  that drops Recall@10 below the Spike-2 baseline is rejected.
- Gate: Recall@10 ≥ ~0.85 (PRD Spike 2).

---

## What to test per module (minimum, via fakes)

- **Harvester** — dedup by base id (fixture must contain two versions of one base id, per `FakeSource`
  above — a fixture with no duplicate base ids passes this test vacuously); resume skips seen ids; transient
  error retries (via `FakeSource`'s error-injection map), permanent quarantines.
- **Parser** — golden fixtures; every block has page+bbox; broken PDF → quarantine.
- **Chunker** — equations/code never split from context; `parent_id` is always a `block_id` (never a
  `chunk_id`) and resolves; when a chunk groups multiple blocks, `parent_id`/`anchor` pin to the *first*
  block in the group (multi-block anchoring rule); anchors survive; title+section-path prefix present;
  `contextual_header` is `None` on every chunk (it's not built in V0 — ADR-07; a test asserting this
  catches an agent that implements it by mistake).
- **Summarizer** — non-empty `summary_text` on golden fixtures **plus a non-degeneracy check**: a bare
  non-empty assertion passes for a hardcoded constant string or a verbatim copy of the abstract, which would
  make every summary vector collapse near one point — assert `summary_text` differs across **at least two**
  distinct golden fixtures, and differs from that paper's own `title`/`abstract` verbatim. `FakeSummarizer`
  is deterministic (same input → same output); `FakeGpuLock` test proves the real adapter acquires
  `gpu_lock.acquire("summarize")` and never co-resides with Embedder/Reranker (assert via `.acquired`).
- **Embedder** — the contract test (above); real adapter acquires `gpu_lock.acquire("embed")` (assert via
  `FakeGpuLock.acquired` in a lock-focused test, not the contract test itself).
- **DocumentStore** — put→get round-trips a whole `PaperRecord`; `get_block`/`get_chunk`/`get_summary`
  each resolve their id and raise `ContractError` on an unknown one; `get_span(anchor)` returns the
  **full** text of `anchor.block_id` (not the shorter `Anchor.snippet`) — use a fixture block **longer than
  200 characters** and assert both `get_span(anchor) == block.text` and `get_span(anchor) !=
  anchor.snippet` (a `get_span` that just returns `anchor.snippet` passes a short-fixture test by accident);
  also assert `anchor.snippet` is a substring of `get_span(anchor)`. `put` is **atomic**: inject a failure
  between the `blocks` insert and the `chunks` insert inside one `put()` call, then open a **fresh
  connection** and assert zero rows across all four tables (`papers`/`blocks`/`chunks`/`summaries`) for that
  `paper_id` — a test that only checks "no exception propagated" doesn't prove atomicity. `put` is
  **idempotent**: re-put the *same* `paper_id` with **changed** content (not just re-put unchanged) and
  assert the store reflects the new content — a naive re-put test that only checks row *count* passes even
  for a buggy silent no-op that ignores the second `put()` entirely.
- **VectorIndex** — the `rrf_fuse` unit test + the weaker cross-adapter smoke test (contract tests, above);
  `rebuild()` from DocumentStore reproduces search results.
- **Retriever** — seeded fake stores + non-identity `FakeReranker`. `retrieve()` returns grounded results
  resolved via `get_chunk`/`get_block` (not manual id-parsing — assert this by wrapping the (real,
  temp-SQLite) `DocumentStore` in a call-recording spy for this test and asserting those methods were
  actually invoked, since a hand-parsed id would still produce a plausible-looking passing result
  otherwise); every result has a resolvable anchor + citation, and `passage_text` equals the resolved
  `Chunk.text` **exactly** — the fixture set must include at least one multi-block chunk (2+ blocks grouped
  by the multi-block anchoring rule) and assert `passage_text` contains content from every block in the
  group, not just the anchor's first block (this is the regression test for the "get_span(anchor) instead
  of Chunk.text" bug, DATA-CONTRACTS §Provenance & structure); `evidence_tier == "A"`; empty corpus → `[]`
  (not an error); `filters` is exercised as `SearchFilters`, not a dict. `retrieve_papers()` returns
  unanchored `PaperSearchResult`s resolved via `get_summary`/`get` (same call-recording-spy technique);
  empty corpus → `[]`. **Rerank wiring is its own assertion for both methods, not incidental**:
  `reranker.calls` is non-empty with the expected candidate ids, and the final result order matches the
  `FakeReranker`'s reversal and **differs from** the pre-rerank RRF order — this is what makes the rerank
  stage actually covered (see Fakes, above).
- **McpServer** — each tool returns records (never bare text); `get_paper` returns `PaperSummaryView`;
  `search_papers` returns `PaperSearchResponse` (composed from `Retriever.retrieve_papers()`); `semantic_search`
  returns `SearchResponse` (composed from `Retriever.retrieve()`); both assert `coverage.candidates >=
  coverage.returned` (a real field now, DATA-CONTRACTS §M8 — not just "present" in the loose sense); a
  citation from either search tool resolves via `get_span`; a spy/mock on `Retriever` asserts `McpServer`
  calls exactly one of its two methods per tool and does not touch `Embedder`/`VectorStore`/`Reranker`
  directly (proves M8 stays thin and doesn't reimplement M7's pipeline).
- **Orchestrator** — full run with all fakes (incl. `FakeGpuLock`); re-run produces no duplicates
  (idempotency); **resume**: inject the kill *within* one paper's processing — after `chunked`, before
  `embedded` in `ingest_state` — then restart and assert (via call-count spies on `Chunker`/`Summarizer`)
  that already-completed stages for that paper are **not** re-invoked, and that later-queued papers still
  complete (a test that only kills *between* papers would pass even if `ingest_state` were ignored entirely,
  defeating the point of resume); **a second resume case**: inject the kill right after `DocumentStore.put()`
  succeeds (paper at `stored`) but before `VectorIndex.upsert()` runs, restart, and assert `upsert()` is
  called for that paper on the resumed run and the paper ends at `done` with a corresponding vector present
  in `FakeVectorStore` (this is the regression test for the `stored`-vs-`done` gap, ARCHITECTURE "Operational
  invariants" §1 — a naive implementation that marks `done` as soon as `put()` succeeds would pass every
  other test here while silently never indexing that paper); one poisoned paper quarantines and the rest
  complete; every stored paper has a non-null `papers.relevance_score` (DATA-CONTRACTS §M5/§M9) — catches
  the Orchestrator silently skipping that computation; `FakeEmbedder`'s call count is `N+1` for `N` fixture
  papers, not `2N` (catches the topic-query-vector hoist regressing — see T-A2, WORK-BREAKDOWN.md).

---

## CI expectations

- Unit + fake-contract + golden tests run on **every push**, no GPU, no network — must be fast and green.
  This is **mechanically enforced**, not just true by convention: the T-F6 CI job (WORK-BREAKDOWN.md)
  runs the non-adapter suites (M1, M3, M5, M7, M8, M9) with sockets blocked (`pytest-socket
  --disable-socket`) and `CUDA_VISIBLE_DEVICES=""` set, so a test that bypasses its fake and reaches for a
  real Qdrant/HF model/GPU fails loudly instead of silently passing on a machine that happens to have
  network or a GPU attached.
- Real-adapter contract tests and the retrieval eval run **nightly or on demand** (they need the GPU box +
  Qdrant). A red nightly blocks release, not every commit.
- Coverage target is a floor, not a goal: the invariants above must each have a test. A green suite with the
  atomicity/idempotency/quarantine tests missing is not "done" (see CONVENTIONS §11).

Testing *mechanics* — how to structure a test file, fixture layout, assertion style — follow the superpowers
testing skills; this doc defines *what* must be tested and *with what*. **Ordering is not left to "normal
practice," though**: CONVENTIONS §0.7 and WORK-BREAKDOWN's M1a/M1b split make the test suite for a module a
committed, reviewed artifact that exists *before* that module's implementation — an agent team with no
cross-session memory can't be trusted to supply an unstated convention, so the ordering is a milestone gate
instead.
