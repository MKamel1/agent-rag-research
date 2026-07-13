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
