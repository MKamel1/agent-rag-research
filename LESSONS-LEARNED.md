# LESSONS-LEARNED.md

An append-only notebook for things noticed while building this project that are worth acting on
someday, but aren't today's work. **Not a spec, not a task list, not authoritative** — an entry
existing here creates no obligation and blocks nothing. If an entry needs to become real work, it
graduates into `WORK-BREAKDOWN.md` (or a real ticket/proposal doc); until then it just lives here so
it isn't lost between sessions.

Scope: lessons about this system's own design, about the process of building a project like this
with AI agents doing the work, and about running all of it on the `ai-workstation` environment.

Entry format: date, category (`system-design` / `build-process` / `infra` / `other`), the finding,
and why/when it's worth revisiting.

---

### 2026-07-12 — system-design — VectorIndex's sparse/BM25 channel never indexes real text

`DATA-CONTRACTS.md`'s frozen `VectorPayload` (§M6) only carries `section_path` into
`VectorIndex.upsert()` — never the actual chunk/summary text. Both `FakeVectorStore` and the real
Qdrant adapter's sparse-search side end up matching against a short, generic, highly-repeated
heading string (e.g. "3. Method") instead of real passage content — even though
`FakeVectorStore`'s own docstring claims the real adapter "has the real chunk/summary text to
index." It doesn't; the contract never gives it any. Found while investigating why Spike 2's
hybrid-search config scored far worse (0.13-0.24 Recall@10) than dense-only (0.75-0.79): fusing a
good dense ranking 50/50 with what's effectively noise (shared heading tokens) actively drags
correct results out of the top-k.

**Why it matters / when to revisit:** hybrid search exists specifically to rescue queries with real
vocabulary mismatch that dense embeddings miss — right now it structurally cannot do that job, on
the synthetic eval or on real queries. Revisit before leaning on hybrid search in V1+, or before
answering "does hybrid earn its complexity" one way or the other — that question can't be honestly
answered yet because the sparse side was never actually wired up. A fix means extending
`VectorPayload` to carry real text — a `contracts/`-level, foundation-change-protocol change, not a
quick patch, hence recorded here rather than just fixed in place.

---

### 2026-07-12 — system-design — No systematic accuracy check on OCR / equation-reading output

MinerU's OCR (for scanned pages with no real text layer) and formula-recognition (for equations
that only exist as a picture) are both used as-is — `rag/parser.py` deliberately relays whatever
MinerU produces without trying to "correct" it (a documented, deliberate choice: a model-accuracy
ceiling, not an adapter bug, same principle already applied to MinerU's known table/algorithm
misclassification). But the accuracy of that transcription is only spot-checked on the 11
hand-picked golden-fixture papers from Spike 1, by eye — not machine-verified, and not checked at
all across the rest of the corpus. Real evidence this isn't hypothetical: during the Spike 2
eval-set audit, ~10% of eval questions' gold passages failed to fuzzy-match anywhere in their
source paper's parsed text, partly traced to garbled, character-by-character formatting-tag
corruption in some parsed math/subscript notation.

**Why it matters / when to revisit:** citations still point to the correct page/location even when
the transcribed text is wrong (the provenance anchor — the link back to the exact source spot — is
unaffected), so this doesn't break "grounded." But it can silently degrade quoted-snippet quality
and retrieval scoring on math-heavy papers. Worth a real accuracy check (sample equation-heavy
pages across a larger set, compare the rendered LaTeX against the source PDF by eye or with a
second model) before leaning heavily on quoted equation text for anything V1+ builds on top of it —
e.g. claim extraction that captures a numeric result/condition — not just trusting it at ingest time
the way V0 currently does.

---

### 2026-07-13 — infra — MinerU + the full GPU-serving stack don't fit in 24GB together

The first real end-to-end run of the newly-built ingestion composition root (real arXiv harvest →
real PDF download → real GROBID+MinerU parse → chunk → embed → summarize → store — see the
`app/assembly.py` composition-root PR) got all the way through parsing (32 real pages, full
layout/OCR/formula/table pipeline succeeded) and then hit a **real CUDA OOM** in the TEI embedding
container. Root cause, confirmed via container logs, not a wiring bug: MinerU's own models are
GPU-resident while it runs, and the ingest process needs the embedder, summarizer, and reranker
loaded too (per `ARCHITECTURE.md`'s co-residence design) — all four together don't fit on this
workstation's 24GB card. The existing VRAM budget (`PRD.md` ADR-02/ADR-08: embedder ~8.5GB +
summarizer ~7-8GB + reranker ~1-2GB ≈ 17-18GB) never accounted for MinerU itself, because it was
reasoned about as the query-serving stack's footprint, not the ingest-time footprint where MinerU
also needs to be resident at the same time.

**Why it matters / when to revisit:** this blocks a real ingestion run (even the ~200-paper M3
smoke test) on the current single-24GB-GPU workstation as currently configured. Before attempting
M3, either (a) measure whether MinerU can be configured to release its VRAM between documents
(load-per-batch rather than staying resident for the life of the ingest process), (b) reconsider
whether the embedder/summarizer/reranker truly need to stay co-resident *during* the parse step
specifically (they're not needed until after a paper is parsed — a smarter pipeline could defer
loading them per-paper rather than holding all four simultaneously for the whole run), or (c)
accept a smaller quantization / different model for one of the four. Not a code defect in the
composition-root wiring itself, which was confirmed correct up to this point — this is a capacity
planning gap in the original VRAM budget.

**Update, same day — the fix above is built and Pass 1 is confirmed working; Pass 2 has its own,
separate tightness.** Built the two-pass ingest this entry called for: `IngestionOrchestrator`
now runs `parse_phase()` (MinerU, in a subprocess so its exit guarantees VRAM release — an
in-process cache-clear was tried first and measured to only free 57% of what one parse allocated,
so subprocess isolation was used instead) then `finish_phase()` (Summarizer+Embedder, in the main
process). Ran the real end-to-end test twice: **Pass 1 succeeded cleanly both times, no OOM** —
confirms the MinerU/Summarizer conflict this entry describes is fixed. But Pass 2 then hit its
*own* real, reproducible `CUDA_ERROR_OUT_OF_MEMORY` in the TEI embed container — not because
MinerU was involved, but because a **real, full-length paper** needs more than the small isolated
test calls suggested: Summarizer ~13.5GB (long context → bigger KV cache than a short test
prompt, not the ~11.8GB a short prompt measured), Embedder ~9-10GB during its actual batch call
(many real chunks, not 1-2 test strings), plus the always-on Reranker's 1.4GB — together at or
over the 24GB ceiling.

**Why it matters / when to revisit:** this is a second, separate capacity gap from the one this
entry originally found, uncovered only because a *real* paper (not a short test call) was finally
pushed through Pass 2. Revisit before the M3 smoke test: candidates are batching the embed call
into smaller sub-batches (peak activation memory scales with batch size, so a big paper's full
chunk set in one call is the likely spike), evicting the Reranker specifically during ingest-only
runs (it's query-time-only, per `ARCHITECTURE.md`'s module map — nothing in `IngestionOrchestrator`
needs it), or a smaller Summarizer quantization. Not solved here — this entry exists so the next
session doesn't have to rediscover it from a fresh OOM.

---

### 2026-07-15 — build-process — a fixed-size tuning constant shipped without checking the real server's own limit, broke production for a day

T-DOC24 fixed a real, confirmed retrieval bug: `Retriever.retrieve()`/`retrieve_papers()` reranked
only the caller's own `k` (e.g. 10) candidates instead of a real pool, so the cross-encoder reranker
could never promote a correct passage the cheaper first-pass hybrid/RRF ranking had ranked just
below `k` — every one of 30 real T-EVAL misses fit this exact shape. The fix (`_RERANK_POOL_SIZE =
50`, `rag/retriever.py`) was well-reasoned and passed the full fakes-only test suite. It also broke
every single real `retrieve()` call the moment it merged: the actually-deployed TEI reranker
container enforces a hard server-side max batch size of **32** (its own default, never explicitly
raised), and 50 > 32 makes every request 422. Caught the same day via a real T-EVAL re-run
(Recall@10 dropped to 0.0 across every split — the number itself was the tell, not a separate audit)
rather than shipped as a false "it works" result; fixed as T-DOC25, `_RERANK_POOL_SIZE = 32`, plus a
new `enable_socket` real-adapter test that sends exactly `_RERANK_POOL_SIZE` candidates to the real
local reranker and fails loudly (not skips) if the server rejects it.

**Why it matters / when to revisit:** the general lesson, not just this one constant — **any tuning
knob whose value is "how much to send a real vendor service in one call" needs a real-adapter test
proving that value against the actual deployed server, not just fakes-only coverage**, because a
fake has no server-side ceiling to violate and will happily accept any batch size. `FakeReranker`
(and `FakeVectorStore`/`FakeEmbedder`) intentionally have no such ceiling — that's correct for what
they're for (testing wiring/logic fast, without GPU) — but it means they can't catch this whole
class of bug, only a live call can.

**The more specific, still-open worry:** 32 was measured and works fine against the *current*,
small T-EVAL-scale corpus (809 papers, ~25K chunks) — Run 3's 0.96 Recall@10 confirms it's enough
candidate room *at this scale*. It is **not** validated at the project's actual target scale
(`WORK-BREAKDOWN.md`'s T-SEED ticket: 30,000 papers). A fixed absolute pool size becomes a *smaller
relative fraction* of the candidate space as the corpus grows — with far more topically-similar
chunks competing for the initial hybrid/RRF stage's top-32, the odds that the correct passage even
lands within that window (before the reranker gets a chance to promote it) go down, not up. In other
words: **the same class of "right paper, wrong passage" miss T-DOC24 fixed at 809 papers could
plausibly reappear at 30,000 papers, for the same underlying reason (not enough pre-rerank
candidate room) but now bottlenecked by the *reranker server's own hard limit* rather than a
code-level constant we can just raise.** None of the fixes tried so far do anything to reduce
*dependence* on pool size in the first place — they just make the pool as big as the server allows.
A fuller menu of standard techniques that instead make the *first* retrieval pass put the correct
passage where a fixed-size pool can find it (aggressive summary-level routing, a cheap cascade
filtering stage before the capacity-limited reranker, real IDF-weighted sparse search instead of
today's raw-TF hashing, query expansion/HyDE, tuning Qdrant's own HNSW `ef_search` accuracy knob,
structured pre-filtering) is recorded in `PRD.md` ADR-11's "Candidate mitigations" list — not
decided or built, just there so the next session doesn't have to invent this list from scratch.
**Revisit T-EVAL Recall@10 at each real corpus-size milestone** (the next being whatever T-SEED
actually reaches) — don't assume 0.96 at 809 papers holds at 30,000; re-measure.

---

### 2026-07-15 — build-process — M5's ship criterion verified against a real MCP client for the first time (T-DOC33) — required building the MCP transport itself, which didn't exist

M5's own exit bar — *"an agent answers a factual question about an ingested paper with a correct,
verifiable citation at ~0 API cost — and you use it"* — had never actually been checked. Every
existing recall number (Recall@10=0.96, etc.) came from the offline T-EVAL harness calling
`Retriever` directly, and `rag/test_composition_e2e.py` calls `McpServer`'s Python methods
in-process — neither one speaks the actual MCP protocol, so neither proves an MCP client can
connect at all.

**Real gap found, not just unverified: `app/serve.py` had no MCP transport.** Before this ticket
it was `build_mcp_server(cfg); print(f"McpServer wired: {server}")` — its own `# ponytail` comment
said outright: *"no transport loop yet ... add a real MCP transport loop when a client needs to
connect to it."* The `mcp` SDK was listed in `environment.yml` (`# M8 McpServer — MCP protocol is
decided, not a Phase-0 open question`) and installed in the conda env, but nothing in the repo
imported it. Concretely: **no real MCP client of any kind — Claude Desktop, Claude Code, or a
protocol-level script — could have connected to this system before this ticket.** This is exactly
the gap M5's exit bar exists to catch, and it had gone unnoticed because every prior "it works"
signal (T-EVAL, the composition e2e test) bypassed the protocol layer entirely.

**Fix (in scope for this ticket — "write a minimal real-run script following [the composition
root] exactly" is literally what T-DOC33 asked for, not a silent side-fix):** extended
`app/serve.py` to wrap `build_mcp_server`'s four tools (`semantic_search`/`search_papers`/
`get_paper`/`get_span`) in a `mcp.server.fastmcp.FastMCP` stdio server — no new wiring pattern, the
`McpServer` construction itself is untouched, still built by `build_mcp_server` exactly as
`rag/test_composition_e2e.py` already proves correct. Also added `RAG_DB_PATH`/`RAG_BLOB_DIR`/
`RAG_COLLECTION` env-var overrides to `app/serve.py`'s `build_mcp_server` call — `app/ingest.py`
and `app/parse_phase.py` already read these same three for the ingest-side composition root;
`app/serve.py` was the one entrypoint that didn't, an inconsistency worth closing while touching
this file for the first time. New reusable script: `app/mcp_verify_client.py` — a real MCP client
using the official `mcp` SDK's `ClientSession`/`stdio_client` (not a bypass: real JSON-RPC over a
real stdio child process), for repeating this check later (T-DOC27/31/34 will all want a re-run).

**The real query → citation round trip, run against real production data** (`papers.db`/`blobs`
at `research-system-rag-data/`, real Qdrant `"papers"` collection — 809 papers, live TEI
embed/rerank services, live GPU):

```
RAG_DB_PATH=.../research-system-rag-data/papers.db RAG_BLOB_DIR=.../research-system-rag-data/blobs \
    python -m app.mcp_verify_client \
    "How long does it take to compute DML with dummies for one dataset in the baseline simulation with 500 units and 10 periods?" --k 5
```

Question picked from a real ingested paper (`2409.01266`, "Double Machine Learning meets Panel
Data", found via `pdf_cache/`, confirmed present in `papers.db`'s `papers` table) — a specific
numeric claim, not something the answer could plausibly come from a model's own training-data
recall of this fairly obscure 2024 econometrics preprint.

`semantic_search` (real MCP `tools/call`, real embed → Qdrant hybrid search → real TEI rerank)
returned a typed `SearchResponse` (`results: list[GroundedResult]`, `coverage: Coverage`) — never
bare text. Top hit's `passage_text` (verbatim, not summarized):

> "...In our baseline simulation with 500 units and 10 periods, computing DML with dummies for one
> dataset takes about 330 seconds, whereas the second slowest method (DML with CRE) is computed
> within less than 8 seconds."

A second returned passage (from the paper's Appendix A.2 table) corroborates with the precise
figure: `DML (dummies) | N=500/T=10: 329.43` seconds. **Both numbers (verbatim quote and table
value) match the source paper exactly** — confirmed independently by reading
`research-system-rag-data/blobs/2409.01266.md` directly (not through the pipeline) and by querying
`papers.db`'s `blocks` table directly by SQL (bypassing `DocumentStore`/`McpServer` entirely).

**Citation resolves to real, non-hallucinated source text.** The top hit's `anchor` (`paper_id:
"2409.01266"`, `block_id: "2409.01266:b63"`, `page: 15`, `section_path: "4 Simulations > 4.1
Method implementations"`) was passed to a second real MCP `tools/call`, `get_span`. It returned
`"4.1 Method implementations"` — the section heading, not the full passage. This is *correct*,
documented behavior, not a bug: `contracts/provenance.py`'s multi-block anchoring rule points a
multi-block `Chunk`'s `anchor` at its *first* block, and a direct SQL check of `papers.db`'s
`blocks` table confirmed block `2409.01266:b63`'s own stored text is exactly that heading (the
"330 seconds" sentence lives in the next block, `:b64`, correctly included in the chunk's
`passage_text` already returned above) — and it exactly matches `anchor.snippet`, which is the
re-grounding check `contracts/provenance.py` documents. `Citation.title`/`.authors`/`.arxiv_url`
(`"Double Machine Learning meets Panel Data..."`, `["Jonathan Fuhr", "Dominik Papies"]`,
`arxiv.org/abs/2409.01266`) match `papers.db`'s `papers` row exactly.

**`Coverage.candidates` (T-DOC28) confirmed live and correct in this same run:** `returned: 5,
candidates: 32` — genuinely different numbers (the real pre-rerank pool size vs. the truncated
top-k), not the `len(results)` stand-in T-DOC28 flagged. Useful incidental confirmation that
T-DOC28's fix (already on `main`, `rag/mcp_server.py`'s `_coverage()`) is live in a real MCP
response, even though `WORK-BREAKDOWN.md` still shows that ticket as "in progress" — a doc-staleness
note only, out of this ticket's scope to fix (T-DOC33 doesn't touch other tickets' lines).

**Result: M5's exit bar is now genuinely verified — a real MCP client, over the real protocol,
asked a real factual question about a real ingested paper, and got back a grounded, typed,
citable answer whose citation resolves to real stored text and whose content is independently
confirmed correct.** Ran cleanly and repeatably once the transport existed (`app/serve.py`) and
the client pointed at the real data paths.

**Aside, found and fixed before it ever shipped (own script, not the system under test):** an
early draft of `app/mcp_verify_client.py` guessed the production data directory as "the repo
root's sibling directory" via `__file__`— this breaks inside a nested git worktree (this session's
own `.claude/worktrees/<id>/` checkout is 3 levels deep, not a sibling of
`research-system-rag-data/`), silently pointing `RAG_DB_PATH` at a nonexistent path that `sqlite3`
happily auto-creates as an empty file, which then fails deep inside the reranker step with an
error `mcp`'s stdio transport surfaces as non-JSON tool-error text. Fixed by dropping the
path-guessing entirely — the script now just passes through whatever `RAG_DB_PATH`/`RAG_BLOB_DIR`
the caller already exported, same as `app/ingest.py`. Not a system bug, but a reminder that
"sibling of the repo" is not a safe assumption for any script that might run from a worktree.

**Why it matters / when to revisit:** re-run `app/mcp_verify_client.py` after T-DOC27 (sparse/BM25
fix), T-DOC31 (parser paper_id fallback), and T-DOC34 (summary-level routing enforcement) land —
each changes retrieval behavior in ways a real protocol-level check, not just T-EVAL, should
re-confirm. If Claude Desktop or another interactive MCP host is ever set up on this workstation
for daily use, that would be a stronger form of "and you use it" than this one-shot scripted
client — worth doing once, but is a human/environment setup decision, not something to automate
from inside a sandboxed session.

---

### 2026-07-15 — build-process — real OS-level kill-mid-ingest + resume verified against real data (T-DOC30)

T-INT2/T-A2's acceptance bar ("idempotency, resume-after-kill, and quarantine ... verified on real
data") had never actually been proven: `.phase0-data/100-paper-run-stats.md`'s "idempotent/resume
semantics confirmed working" claim, on inspection, was two *clean, uninterrupted* invocations
(Run 2 simply skipped Run 1's already-`done` papers via the `ingest_state` guard) — not a real
OS-level kill mid-stage. No gap in that run's 20s-interval timing snapshots either. A search of
every `LESSONS-LEARNED.md` copy under `.claude/worktrees/*` for `kill`/`resume`/`crash`/`interrupt`
found nothing — the ticket's "this session's own history strongly suggests a real crash-and-resume
happened" could not be corroborated, so this was treated as unproven and a real test was run instead
of accepting it as already-verified.

**Setup:** throwaway resources only (`RAG_DB_PATH=/tmp/t-doc30-resume-verify/papers.db`,
`RAG_BLOB_DIR=.../blobs`, `RAG_COLLECTION=t_doc30_resume_verify_23770`, all deleted afterward — never
touched the real `papers` Qdrant collection or a real `RAG_DB_PATH`). 5 real arXiv papers via
`RAG_INGEST_PAPER_IDS=2409.01266,2409.02332,2410.00903,2411.14665,2503.00557` (already cached in
`pdf_cache/`). Real composition root, `python -m app.ingest`, run three times in sequence (fresh →
kill → resume → kill → resume), through the real `GpuLock` file lock, real GROBID/MinerU/TEI/Ollama/
Qdrant. An external Python poller read `ingest_state.stage` directly every ~20ms (SQLite WAL mode,
documented in `rag/ingest_state_sqlite.py` as safe for a second process's reads) and sent `SIGKILL`
to the ingest process's real PID the instant the target stage was observed — not a `sleep`-based
guess.

**Infra note (unrelated to the resume logic, but blocked the first attempt):** the first invocation
quarantined all 5 papers at `parsed` with `GROBID reference extraction failed: [Errno 111] Connection
refused` — the `rag-grobid` Docker container (`lfoppiano/grobid:0.8.0`, port 8070) had exited and
wasn't running, unlike TEI/Qdrant which were already warm. `docker start rag-grobid` fixed it. Worth
remembering for the next real-data run on this workstation: GROBID isn't part of the "already warm"
set the way TEI/Qdrant are.

**Gap 1 (T-A2 DoD: "after `chunked`, before `embedded`" — Chunker/Summarizer must not be
re-invoked on resume):** killed the process the instant paper `2409.01266` first showed
`stage='summarized'` (2026-07-15T09:04:34 UTC), before its `embedded` checkpoint could be written.
Confirmed: process dead, paper stuck at `summarized`, zero quarantines, the other 4 papers untouched
at `chunked` (Pass 2 processes papers strictly sequentially). Resumed with the identical invocation:
`2409.01266` went from `summarized` straight to `stored` (0.64s later, per the resumed process's own
`ingest_state.updated_at`) then `done` (0.08s after that) — and the *whole* resumed process, from
`python -m app.ingest` start to that paper reaching `done`, took only ~6.2s wall-clock (includes
re-harvest, Pass-1 subprocess skip-check, and the once-per-run topic-query embed). That is far too
short to have included a real summarize call — this project's own measured real-adapter Pass-2 cost
(`.phase0-data/100-paper-run-stats.md`) is **avg 15.02s / median 14.54s / min 6.74s** per paper
*including* summarize+embed+store. Timing is the evidence here (the project has no spy-style fakes
in front of the real Ollama/TEI adapters to assert call counts directly), and it lines up exactly
with `rag/orchestrator.py`'s `_finish`'s `_at_least(stage, "summarized")` guard, which skips the
`summarizer.summarize()` call entirely once a paper is already checkpointed past that stage.

**Gap 2 (T-A2 DoD: "after `DocumentStore.put()` succeeds, before `VectorIndex.upsert()` runs" —
`upsert()` must run on resume and the paper must reach `done` with a matching Qdrant entry):** left
the same resumed process running and killed it the instant a *second* paper, `2503.00557`, first
showed `stage='stored'` (2026-07-15T09:05:16 UTC). Confirmed directly against real state: SQLite
already had the full `DocumentStore.put()` result (51 chunks + 1 summary row, matching the paper's
real chunk count), but Qdrant had only 6 of the expected 52 points for that paper — `_upsert_record`'s
per-point loop (`rag/orchestrator.py`, one `vector_index.upsert()` call per chunk/summary, not
batched) was caught genuinely mid-flight, not just at the boundary. Resumed a third time (same
invocation): all 5 papers reached `done`, zero quarantines. `2503.00557` ended with **exactly 52**
Qdrant points — the missing 46 were added and the 6 that already landed were not duplicated (Qdrant
upsert is idempotent by point id, as `_finish`'s own docstring already documented — this confirms it
against a real Qdrant instance, not just the claim). Corpus-wide integrity check: SQLite's `chunks`
table (184 rows total across all 5 papers) + 5 summary rows = 189, which matched Qdrant's real total
collection point count (189) exactly — no orphaned or duplicate points anywhere in the corpus, not
just the two directly-killed papers.

**Result: both DoD-named gaps are now verified against real data, real infra, a real OS-level
SIGKILL, and a real resumed process — not fakes, not a clean-invocation stand-in.** `git log`/PR
history for this entry (`T-DOC30-resume-after-kill-verification`) is the durable record; no permanent
automated test was added (a real GPU/GROBID/MinerU/Ollama/Qdrant-dependent kill-timing test doesn't
fit this project's zero-GPU/zero-network CI rule for non-adapter suites, and a one-off manual
real-data verification — same category as `.phase0-data/100-paper-run-stats.md` — is what T-DOC30
itself asked for as the alternative to a committed test).

**Aside, found but explicitly not fixed here (out of T-DOC30's scope — flagged, not touched):**
`rag/parser.py`'s `_derive_paper_id` falls back to a content hash (`stem =
hashlib.sha256(raw).hexdigest()[:16]`, a documented, deliberate behavior) whenever a PDF's own text
has no machine-readable arXiv self-citation. That fallback id is what ends up in the SQLite `chunks`
table's `paper_id` column (and every `chunk_id` prefix) for such a paper — it happened for
`2411.14665` in this very test run (42 of its chunks landed under
`chunks.paper_id='211c443e9b22f24a'` instead of `'2411.14665'`). Qdrant's own payload stayed correct
throughout regardless (`_upsert_record` always uses `record.ref.paper_id`, the harvester's real id,
never the parser-derived one), so this did not affect this ticket's resume/idempotency conclusions or
retrieval via Qdrant — but it likely breaks any SQLite-side `DocumentStore` lookup keyed by the real
`paper_id` for that paper's chunks (e.g. a future `get_chunk`/debugging query joining `papers` to
`chunks` by `paper_id` would silently miss these rows). Not investigated further; worth its own
ticket if `DocumentStore`'s own paper_id consistency is ever audited. (Now ticketed and fixed —
see T-DOC31, PR #103.)

---

### 2026-07-15 — build-process — T-DOC31 production sweep found zero live instances of the bug it was hunting, because an earlier, unrelated cleanup had already deleted them

**Doc-accuracy flag first, since it affects how much to trust the rest of this ticket's premise:**
`WORK-BREAKDOWN.md`'s T-DOC31 entry cites "T-DOC30's live kill test (`LESSONS-LEARNED.md`, 2026-07-15
entry)" as where the `2411.14665` → `chunks.paper_id='211c443e9b22f24a'` occurrence was confirmed.
As of this session, **no such entry exists in this file**, and `WORK-BREAKDOWN.md` itself still lists
T-DOC30 as `(not started)`. Flagging this rather than silently treating an unverifiable citation as
read (CONVENTIONS.md §0's "stop and flag it" principle) — this entry does not claim to have read that
kill-test writeup, because it doesn't exist yet. The underlying bug mechanism itself is real and
independently confirmed by reading `rag/parser.py`'s pre-fix code directly (`_derive_paper_id`'s
`hashlib.sha256(raw).hexdigest()[:16]` fallback, called whenever the `arXiv:YYMM.NNNNN` regex didn't
match watermark text MinerU extracted) — only the specific citation trail is unverifiable.

**The fix (T-DOC31, this ticket):** `rag/parser.py`'s `parse`/`parse_batch` now take a required
`paper_id`/`paper_ids` parameter and use it directly — the content-hash fallback is deleted outright
(not kept for a "manual/standalone" case: grepping the whole codebase found no caller that doesn't
already have a real id). `contracts/parser.py` documents the new interface (a docstring-only change,
still foundation-protected via CODEOWNERS since it touches `contracts/`). `app/assembly.py`'s
`_PdfDownloadParser` (the actual bridge from `IngestionOrchestrator`'s `PaperRef`-shaped call to the
real byte-taking Parser) now passes `ref.paper_id` through. `rag/orchestrator.py` itself needed no
change — it already calls `self._parser.parse(ref)` with the full `PaperRef` (paper_id included); the
plumbing gap was one level down, in the composition-root bridge, not the orchestrator.

**Production sweep result: zero orphaned/mismatched rows found — see why below, not a clean bill of
health.** Backed up the real production DB first (`sqlite3 papers.db ".backup ..."` — an online,
WAL-consistent snapshot, not a raw file copy, since another process had `papers.db` open for reads at
the time) to
`research-system-rag-data/papers.db.bak-pre-T-DOC31-paperid-sweep-20260715-095049` (same directory,
same naming convention as T-DOC23's `.bak-pre-orphan-cleanup-*`). Then ran the ticket's own sweep query
(`chunks`/`blocks`/`summaries` LEFT JOIN `papers`, `papers.paper_id IS NULL`) — zero rows, every table.
Broadened it (in case some instance wasn't "orphaned" in the exact join sense): scanned every
`paper_id` column in every table (`chunks`, `blocks`, `papers`, `summaries`, `quarantine`) for the
literal 16-lowercase-hex-char shape `_derive_paper_id`'s fallback produced — also zero, everywhere.
**No `UPDATE` was run; there was nothing to rename.**

Why zero: `2411.14665` itself (the ticket's cited example) still has its correct `papers` row and a
`summaries` row under the real id, `ingest_state.stage='done'` — but **zero `blocks` and zero `chunks`
under either the real id or the hash**. Checking systematically, exactly **59** papers are in this same
"done, has a summary, zero blocks/chunks" state — the identical count `WORK-BREAKDOWN.md`'s handover
section attributes to **T-DOC23's** orphaned-row cleanup ("59 orphaned papers... already applied
directly to the real production DB... verified 0 orphans remain"). Conclusion: T-DOC23's cascade
delete (same day, run before this session) already swept up every row this bug class produced — a
hash-derived `paper_id` chunk/block is *definitionally* orphaned under that join, since
`DocumentStore.put()` always writes the `papers` row under the harvester's real id, never the parser's
hash. T-DOC23 deleted the mislabeled rows instead of relabeling them, because relabeling wasn't its
job and it had no way to know the "orphan" and "wrong-hash-id" causes were the same bug.

**Real, unresolved gap this surfaces (left alone, not fixed here — out of this ticket's scope):**
those same 59 papers (including `2411.14665`) are currently invisible to retrieval — `ingest_state`
claims `done`, `search_papers`/`get_paper` would return their summary, but zero passages exist to
ground any answer about their actual content. Fixing this needs real re-ingestion (re-parse + re-chunk
under the now-fixed Parser, real GPU/MinerU work) for those 59 `paper_id`s specifically, not a metadata
`UPDATE` — a different, larger action than "correct a mislabeled column," and this ticket's brief was
explicit that it's a metadata-correction pass, not a re-ingestion one. Worth its own follow-up ticket
(a `T-DOC<n>` re-ingest-the-59 pass, keyed off exactly the list this entry's query produced) rather than
assuming T-DOC23's "0 orphans remain" line meant those 59 papers' content gap was also closed — it
wasn't; T-DOC23 only removed the mislabeled evidence of a gap that JOIN can't see it "closed."

**Known limitation of this sweep, noted for whoever picks up the follow-up above:** both queries only
catch the *hash-fallback* shape of this bug (an unmatched/orphaned id). A different failure mode of the
same root cause — MinerU's `_ARXIV_ID_RE` regex matching a *different* real paper's arXiv id (e.g. from
a citation/reference block) instead of failing to match at all — would produce a **valid-looking,
non-orphaned** `paper_id` that silently misattributes chunks to the wrong existing paper, and neither
query here would catch it (it doesn't leave an orphan). Not investigated in this pass; would need a
per-paper chunk-count/content sanity check across the corpus, not a join, and wasn't ticketed here.

**Why it matters / when to revisit:** two lessons, not one. (1) A sweep query written for one root
cause can return "zero found" for a genuinely correct reason (the damage was already cleaned up by
something else) that still leaves the *actual* problem — missing content, not just a mislabeled row —
completely open; "0 orphans" is not the same claim as "0 papers affected," and conflating them here
would have closed this ticket without noticing 59 papers are silently empty. (2) A ticket's own cited
evidence trail (a `LESSONS-LEARNED.md` entry, in this case) should be checked, not assumed present just
because the ticket text asserts it confidently — this is the second time in this project's history a
downstream doc referenced something upstream that didn't actually land (see `WORK-BREAKDOWN.md`'s
T-DOC30 entry itself, which exists for exactly this reason: an assumed-but-unrecorded past validation).

---

### 2026-07-15 — build-process — 59 `done`-but-chunkless papers re-ingested; discovered mid-fix that the real fix requires T-DOC31 (PR #103), still unmerged (T-DOC35)

**Scale, confirmed exactly:** `SELECT p.paper_id FROM papers p JOIN ingest_state s ON s.paper_id =
p.paper_id LEFT JOIN chunks c ON c.paper_id = p.paper_id WHERE s.stage='done' AND c.paper_id IS
NULL` (cross-checked against `blocks` the same way, and against having a `summaries` row) returned
**exactly 59 paper_ids** against the real production DB — matching the ticket's estimate exactly,
not just "about 59." Full list captured in the PR; first is `2411.14665` (the same paper T-DOC30's
2026-07-15 entry above flagged), rest are a contiguous-looking run of `2607.0*`-`2607.11*` ids plus
a few earlier ones (`2602.07478`, `2605.24076`). Each had a `papers` row, an `ingest_state='done'`
row, and exactly one `summaries` row, but zero `chunks`/zero `blocks` — and, checked directly
against the real Qdrant `"papers"` collection, exactly one point each (`kind='summary'`) and zero
`kind='chunk'` points, i.e. summary-level search could surface them but no passage-level grounding
existed. Backup: `research-system-rag-data/papers.db.bak-pre-T-DOC35-20260715-145530` (online
`.backup`, not a raw copy, same precedent as T-DOC23/T-DOC31).

**Reset:** `DELETE FROM ingest_state` + `DELETE FROM summaries` for all 59 (the `papers` row was
left in place — `DocumentStore.put()` upserts it, never duplicates). No `ingest_checkpoint` rows
existed for any of the 59 (confirmed before deleting anything), so there was no cached
`parsed`/`chunks` artifact to resume from — a reset to `harvested`/`parsed` would have been a lie;
these had to go all the way back to "never ingested" and re-parse for real.

**The subset-first check (2-3 papers) caught a real blocker before it could hit all 59.** Ran
`RAG_INGEST_PAPER_IDS=2411.14665,2602.07478,2605.24076 python -m app.ingest` against real
GROBID/MinerU/TEI/Ollama/Qdrant (all already warm) straight off `main` as it stood at the start of
this ticket. All 3 reached `done` in ~60s with zero quarantines — looked like a clean success. It
wasn't: `app.corpus_integrity` (the diagnostic this same ticket adds, run immediately after) flagged
all 3 as *still* offenders. Cause: `rag/parser.py`'s content-hash paper_id fallback (T-DOC31,
PR #103 — **still open, not merged**, contrary to how the T-DOC30 aside above might read) fired for
all 3 papers (none has a machine-readable arXiv self-citation MinerU could extract), so their fresh
chunks/blocks landed in SQLite under a derived hash id (`211c443e9b22f24a`, `a023fccb7c91983b`,
`ad6936641aef9163`) instead of the real `paper_id` — reproducing the *exact* orphaned-chunks shape
this ticket exists to clean up, one layer deeper than the ticket's own stated hypothesis. (Qdrant's
`payload.paper_id` field stayed correct throughout, same as T-DOC30 observed — only the SQLite side
and the chunk_id itself, which embeds the derived id, were wrong.) Blindly running this same command
against all 59 would have partially "fixed" the hole while quietly recreating a fresh batch of
orphans under new hash ids for however many of the 59 hit the same fallback (turned out to be all of
them — see below).

**Fix for the blocker, scoped to not touch `main` or this ticket's own PR diff:** a throwaway git
worktree (`/tmp/t-doc35-fixed-ingest`, deleted after use) off `origin/main` with T-DOC31's two
functional commits cherry-picked on top (`ccbefae` "pass orchestrator's known paper_id into Parser,
drop hash fallback", `f09ac62` its test updates — both from `origin/T-DOC31-parser-paper-id-hint`,
PR #103; the two later doc-only T-DOC31 commits were left out, they only touch
`WORK-BREAKDOWN.md`/`LESSONS-LEARNED.md` and aren't needed to run real code). Full non-adapter suite
green in that worktree (`pytest app rag contracts ci/checks fixtures/eval --disable-socket`, zero
failures) before it touched production data. **T-DOC35's own branch/PR never merged or cherry-picked
T-DOC31's commits** — `contracts/parser.py` is foundation-protected and PR #103 is still awaiting
@MKamel1's own review; using its code to run the real pipeline correctly is not the same as landing
it, and this entry — plus the PR body — is the explicit flag that **T-DOC31 (PR #103) needs to merge
before or alongside this PR**, or any *future* re-ingest of a similarly-fallback-prone paper will
reproduce this same hole a third time.

**Cleanup of the 3-paper false start:** `DocumentStore.delete(paper_id)` (T-DOC23's cascade-delete,
designed for exactly this "no matching `papers` row" shape) against the 3 hash ids — cleared their
orphaned `chunks`/`blocks` rows. Matching Qdrant points deleted via `points/delete` filtered on
`payload.paper_id` for the 3 *real* ids (106 stale points total — all of them were the mis-keyed
ones, nothing correct to preserve). `ingest_state`/`summaries` reset again for the same 3 real ids,
then re-ran the identical `RAG_INGEST_PAPER_IDS` command from the T-DOC31-patched worktree. This
time all 3 landed chunks/blocks under their real `paper_id` (`2411.14665`: 42 chunks/311 blocks;
`2602.07478`: 30/114; `2605.24076`: 31/165) — `app.corpus_integrity` clean, and per-paper SQLite
(chunks+summaries) count matched the real Qdrant point count exactly (43/31/32) for all 3.

**Remaining 56 run the same way** (same patched worktree, same real infra, background process,
polled every ~25-30s by directly querying `ingest_state.stage` rather than waiting on a
notification): harvest → MinerU parse batch (all 56 reached `chunked` before Pass 2 started, ~7
min) → summarize/embed/store (~1 paper every 15-25s once Pass 2 began), all 56 reached `done` with
zero quarantines, zero `TransientError`/`PermanentError` in the log (only expected
summarizer-truncation warnings for long papers and MinerU's own OCR-classification debug noise).

**Final verification, real numbers:** `app.corpus_integrity` against the full production DB — **0
offenders** (every one of the now-809 `done` papers has ≥1 chunk and ≥1 block; corpus-wide `papers`
count unchanged at 809). No orphaned `chunks`/`blocks` anywhere (`paper_id` not in `papers`) — 0
rows either direction. Corpus-wide SQLite `chunks`+`summaries` total (26,196) matches the real
Qdrant `"papers"` collection's `points_count` (26,196) exactly. Per-paper check across all 59:
SQLite (chunks+summaries) count equals the real Qdrant point count for every single one, zero
mismatches, zero papers with 0 chunks or 0 blocks.

**Nothing left as a human-triggered follow-up for the 59 themselves — all fixed and verified.** What
*is* left, explicitly, for @MKamel1: **merge T-DOC31 (PR #103) into `main`.** Until it merges, this
fallback can fire again for any future ingest of a paper MinerU can't extract a watermark from
(observed rate in this run: 3/3 of the first subset, and — since the fix was applied before the
remaining 56 ran — unmeasured for those, but plausibly similar given they're the same historical
cohort). `app/corpus_integrity.py` (this ticket's other deliverable) is the standing check that
would catch a recurrence either way, but the parser-side fix is what stops it from happening at all.

---

### 2026-07-15 — build-process — the 0.96 ship-gate number held up under realistic distractor noise (T-DOC37/42)

The V0 ship gate (single-passage Recall@10 ≥ 0.85) was originally cleared at 0.96 on a 100-paper corpus
that `fetch_by_ids` had built *specifically to contain the gold papers* — no distractors. Two independent
reviews flagged that this partly measures "find the answer in a haystack we pre-filtered to contain it,"
not "find it among hundreds of relevant-but-wrong causal-methods papers." T-DOC37 re-ran all 210 questions
against the real 809-paper production `"papers"` collection (gold papers among ~709 distractors,
READ-ONLY) and, for a clean same-harness delta, against a throwaway gold-only copy of just the 100 gold
papers. **Result: single-passage Recall@10 = 0.952 on both — the 709 distractors cost zero recall on every
split** (deltas 0 to +0.02, within noise; only MRR dipped ≤0.008). Distractors occupied ~5% of top-10
result slots (validated they really surface) but almost never displaced the correct gold passage. Lesson:
for *this* retriever/corpus the pre-filtered-corpus worry turned out to be unfounded — but the only way to
know was to run it against the real noise; a strong cross-encoder reranker over a discriminative 2560-dim
embedder is what makes recall noise-robust here. Any future retrieval-quality regression test should run
against the full `"papers"` collection, not a gold-only subset, or it won't see distractor pressure at all.

Second lesson (T-DOC42 — denominator honesty): the multi-paper split's apparent weakness (0.73–0.76) was
**mostly a scoring artifact**, not a retrieval defect. Multi-paper questions draw on 2+ papers but the
fixture carried a single gold label, so a correct hit on the *other* co-source paper counted as a miss.
Adding `additional_gold_paper_ids` (co-source arXiv IDs, recoverable from the ground-truth `section_path`)
lifted multi-paper to 0.96. And the eval's dropped denominator (55/210 `no_match`, gold excerpt not found
verbatim) is **not** biased toward hard questions (45% hard/expert vs 56% among scored) — it's an
excerpt-normalization artifact concentrated in Method-Comprehension/equation text, orthogonal to retrieval
difficulty. Takeaway: before chasing a weak-looking eval split as a quality defect, first rule out the
label schema and the resolved-question denominator — the measurement was understating two splits at once.

---

### 2026-07-16 — infra — the pipeline's own run telemetry (T-DOC47) is now the source of truth for run analysis, not the external workstation dashboard (T-DOC54)

`workstation-dashboard` (an external MCP tool) turned out not to be trustworthy alone for post-hoc
GPU analysis: `export_history(components="gpu")` for a 736s Pass-1 window silently returned only
386 samples covering the *last* 217s — the earlier ~519s (all of the parser's model-loading and
the bulk of its inference) had zero stored samples, with no error, warning, or row-count hint from
the tool itself. Only caught because the run's own `run.log` timestamps and an independent local
`nvidia-smi`-polling script were cross-checked by hand before trusting the export (OG-16).

Now that `app/telemetry.py` ships (T-DOC47: `python -m app.ingest`'s own per-stage GPU util/VRAM/
power sampling, JSON-line `RUN_START`/`STAGE_START`/`STAGE_END`/`RUN_END` events written to
`--events-path`, and the printed end-of-run summary), **treat that built-in telemetry as the
source of truth for analyzing any given run** — it is produced by the run itself, so it cannot
have the kind of silent retention gap an external tool's collection/storage layer can. Still cross-
check `workstation-dashboard` (or any other external dashboard) against the run's own JSON-line
events/summary before trusting it for anything post-hoc; never trust an external dashboard's
export alone the way OG-16 almost did.
