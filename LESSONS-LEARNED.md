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
