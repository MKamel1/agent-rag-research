# Drop-in folder + book ingestion — design spec

*2026-07-25. Approved in brainstorming session; status: awaiting user review of this written spec.*

## Objectives

1. **Drop-in folder:** drop any PDF (arXiv or not) into a folder → it ends up in the corpus via a
   manual command, with zero manual metadata entry.
2. **Books as first-class corpus members:** books and papers live in one searchable corpus. Books
   ground concepts/definitions; papers carry the latest evidence. The agent reasons across both.
3. **MCP leverage:** the tools let the calling agent exploit that division of labor explicitly
   (filter by document type, route into books at chapter granularity, cross-check paper claims
   against textbook definitions) — consistent with agent-as-reasoner (no server-side magic).

## Approach (decided)

**Thin script over the existing T-DOC48 cache-first path** — not a new `Source` adapter, not
`Config.sources` wiring (OG-38 stays open), not a watcher daemon. The entire pipeline downstream of
"a `PaperRef` + local PDF bytes exist" is reused unchanged except where document length genuinely
matters (parse batching, summarization).

## New entry point: `app/ingest_local.py`

Run manually: `python -m app.ingest_local`. Mirrors the existing script pattern
(`app/prefetch_pdfs.py`, `app/build_corpus.py`).

### Folder layout

```
drop_in/
  papers/   ← paper PDFs (arXiv or not)
  books/    ← book PDFs
  done/     ← moved here after successful hand-off
  failed/   ← moved here on per-file failure, with <name>.err reason file
```

The subfolder is the **only** `doc_type` signal. No sidecar metadata files (explicitly rejected —
auto-extract only).

### Per-file flow

1. Read PDF metadata + first-page text (pypdfium2, already a dependency).
2. Scan filename + first-page text for an arXiv id (`\d{4}\.\d{4,5}` with optional `vN`).
   - **Found** → `ArxivSource.fetch_by_ids([id])` (metadata-only network call, reuses existing
     T-DOC49 backoff) → authoritative `PaperRef`. The dropped file's bytes are used as-is; no PDF
     re-download. If the fetch ultimately fails, **fall back** to the local branch below rather
     than failing the file.
   - **Not found** → mint `paper_id = f"local:{sha256(pdf_bytes)[:12]}"` (content-addressed →
     naturally idempotent re-drops). Synthetic `PaperRef`: title/authors best-effort from PDF
     metadata + first page + filename; `abstract=""`; `categories=[]`; `published`/`updated` =
     extracted year if found, else file mtime; `pdf_url` = original filename (provenance note,
     never fetched).
3. Set `doc_type` (`"paper"` | `"book"`) from the subfolder.
4. Write `pdf_cache_dir/<paper_id>.pdf` + `<paper_id>.json` — the exact pair T-DOC48's
   `_cached_ref` already reads with zero network calls. The `.json` writer must round-trip through
   the same serialization `_cached_ref` parses (shared helper, not a second format).
5. Move source file to `done/`; append `paper_id` to a run manifest file.
6. After the scan, hand the manifest to the existing ingest entry points
   (`--paper-ids-file` / `Config.ingest_paper_ids`) — Parser → Chunker → Summarizer → Embedder →
   DocumentStore → VectorIndex run unchanged except as specified below.

### Idempotency

Content-hash ids + existing `ingest_state` stage checks → re-dropping an already-ingested file is
a logged no-op. arXiv-detected drops dedupe against harvested copies by shared `paper_id`.

## Books: same pipeline, three deliberate differences

**Unifying insight: a book chapter is roughly paper-sized.** Papers and chapters are the same
*routing unit*; books differ only where document length matters.

| Stage | Papers | Books |
|---|---|---|
| Parse (MinerU) | batched (`parse_batch_size`) | **batch of 1** (a book is its own batch); page/bbox anchors unchanged |
| Chunker | unchanged | unchanged — chapters are top-level sections, `section_path` already captures the hierarchy |
| Summarizer | one `summarize()` call | **map-reduce** (below) |
| Storage | 1 summary row | 1 book summary + N chapter summary rows |
| Embed / retrieve | unchanged | chapter summaries embed as `kind="summary"` vectors |

### Map-reduce summarization

- **Split:** chapters = top-level `section_path` groups from `ParsedDoc.blocks`. Fallback when no
  usable chapter structure (flat/scanned PDFs): fixed-size block windows.
- **Map:** summarize each chapter with the existing Summarizer (GPU lock, eviction hooks
  unchanged). A chapter whose text still exceeds the context window is summarized in windows, then
  those window summaries combined — bounded recursion, depth 2 is sufficient in practice.
- **Reduce:** distill chapter summaries into one **structured book-level summary**: a short
  overview + a one-line-per-chapter table of contents. This is `PaperRecord.summary_text`, so
  `get_paper` on a book returns a navigable TOC for free.
- **Persist the map outputs:** chapter summaries stored in the existing `summaries` table
  (additive rows — table is already keyed by `summary_id` with `paper_id` FK) under
  `summary_id = f"{paper_id}:summary:ch{n}"`, and embedded as `kind="summary"` vectors.
- Errors: one chapter failing permanently → the book quarantines (summary is a required field,
  same rule as papers); transient failures retry per existing Summarizer behavior.
- Incidental benefit: the same path handles any *paper* too long for a single summarize() call.

## Contract & schema changes (all additive; foundation-protected — needs @MKamel1 approval)

| Change | Where | Shape |
|---|---|---|
| `doc_type: str = "paper"` | `contracts/harvester.py` `PaperRef` | additive, defaulted — existing sidecars/fixtures parse unchanged |
| `doc_type: str \| None = None` filter | `SearchFilters` (§M6) | `None` = mixed (default) |
| `doc_type` surfaced on results | `GroundedResult` / `PaperSearchResult` envelopes | fill-fields pattern (PRD §8.5), defaulted |
| `chapter: str \| None = None` | `PaperSearchResult` | set when the routing hit is a chapter summary; `None` for papers/whole-book |
| `papers.doc_type` column | SQLite schema + `migrations/` | `TEXT NOT NULL DEFAULT 'paper'` |
| Summary-id format extension | DATA-CONTRACTS §IDs | `{paper_id}:summary:ch{n}` alongside `{paper_id}:summary`; `rag/retriever.py`'s `_paper_id_from_summary_hit_id` (the one sanctioned parser) updated to handle both |
| `drop_in_dir` lever | `Config` + `config.yaml` | default `"drop_in"` |

`VectorPayload` gains `doc_type` so `SearchFilters.doc_type` filters at the index, consistent with
existing category/date filters.

## MCP leverage (all additive; no existing tool changes shape)

1. **`doc_type` filter + labels.** Agent scopes searches (books-only for definitions,
   papers+date-filter for latest evidence, mixed by default) and always knows whether a passage
   came from a textbook or a preprint — enabling explicit cross-checking.
2. **Chapters as routing hits.** `search_papers("instrumental variables")` can return
   *"Mostly Harmless Econometrics — Ch. 4"* alongside papers, because chapter summaries are
   summary-kind vectors. Coarse→fine flow (which chapter → which passage) works exactly like
   which paper → which passage.
3. **`get_paper` on a book = TOC.** The structured reduce output (overview + per-chapter lines).
4. **Tool-description guidance, not server-side routing** (T-DOC34 precedent): docstrings state
   the pattern — books = foundations/definitions, papers = current evidence; filter accordingly;
   cite both when cross-checking. Server stays dumb-but-grounded.

Citations are unchanged and fully grounded: book passages carry page+bbox anchors →
`get_span`-verifiable "*Causality*, p. 340".

## Error handling (quarantine-and-continue, per CONVENTIONS §4)

- Corrupt/unreadable dropped PDF → `drop_in/failed/` + `.err` file; scan continues.
- arXiv metadata fetch failure → fall back to `local:` branch (file still ingests).
- Chapter summarize permanent failure → book quarantined via existing dead-letter path.
- Re-drop of ingested file → logged skip, moved to `done/`.

## Testing (zero-GPU, fakes; per TEST-STRATEGY)

- **Unit:** id minting (arXiv regex hit/miss, hash stability), sidecar write ↔ `_cached_ref` read
  round-trip, subfolder→`doc_type`, failed-file handling, manifest contents.
- **Map-reduce with `FakeSummarizer`:** chapter split points, reduce composition, no-structure
  fallback, chapter summary-id generation, quarantine on permanent chapter failure.
- **Contract:** `_paper_id_from_summary_hit_id` handles both summary-id forms; `doc_type` filter
  through the fake `VectorStore`; `chapter` field populated on chapter hits.
- **Golden fixture:** small multi-chapter PDF end-to-end (parse → chunk → map-reduce → store),
  asserting chapter summary rows + TOC-structured book summary.

## Out of scope (explicit)

- Folder-watcher daemon (manual trigger only).
- Sidecar metadata override files.
- Book-specific MCP tools (filters + tool descriptions cover the need).
- OG-38 `Config.sources` registry wiring.
- Relevance-gating of dropped files (dropping the file *is* the relevance signal;
  `relevance_score` still computed, still non-gating).

## Open risks

- **MinerU on a 400-page book** is untested here: parse time and host-RAM/VRAM behavior at that
  length are unknown. Mitigation order: batch-of-1 (this spec) → if it OOMs, pre-split the PDF
  into page ranges with a page-offset map so anchors stay correct (not built until needed).
- **Auto-extracted metadata quality** for non-arXiv PDFs is best-effort; a messy title is
  cosmetic (retrieval is content-driven) but visible in citations. Accepted; fix-up tooling only
  if it actually annoys.
