# T-DOC62 option B — re-chunk stored papers from their blocks

*2026-07-28. Decision recorded in `docs/DECISION-t-doc62-duplicate-chunk-headers.md`; the operator
chose option B and a general, reusable tool over a one-off script.*

## Goal

Apply an already-landed chunker change to papers that were chunked before it, without re-parsing.

Concretely: 809 papers ingested before 2026-07-17 carry `title\nsection_path\n\n<section_path>…`,
duplicating the heading. `rag/chunker.py::_strip_duplicate_heading` (commit `157af4d`) fixed this
for everything ingested since — measured 58.49% duplication before, 0.01% after — but stored data
was never revisited.

## Why this is cheap

`DocumentStore.get(paper_id)` returns a full `PaperRecord`, including `parsed: ParsedDoc` with the
blocks. All 809 affected papers still have their blocks (166,561 of them, 100% coverage). So the
expensive stages — harvest, MinerU parse, LLM summarize — are all skipped. Only chunking and
embedding re-run.

## Design

`python -m app.rechunk --paper-ids <file-or-ids>` — general and reusable, because this is the second
retrofit of this shape (`app/reindex_idf.py` was the first) and there will be a third.

Per paper, in order:

1. `record = store.get(paper_id)` — the current source of truth.
2. `new_chunks = chunker.chunk(record.parsed)` — re-chunk from the stored blocks.
3. Compare old and new `chunk_id` sets.
4. `store.put(record.model_copy(update={"chunks": new_chunks}))` — atomic per paper.
5. Vector sync: **delete the vectors for chunk ids that no longer exist**, then upsert the new
   chunks' vectors.

Step 5 is the part that must not be got wrong. Chunk ids can change when text changes, so a
plain upsert would leave the old points orphaned — searchable, with no matching SQLite row. That is
exactly the T-DOC23/T-DOC35 shape, and `get_chunk` crashes on a hit against one.

**Do not reuse `IngestionOrchestrator.delete_paper`** — it removes *all* of a paper's vectors
including its summaries, which are unaffected here and would then need regenerating. Delete only
the chunk ids that actually disappeared.

## Safety requirements

This mutates 809 papers in a live 11,026-document corpus.

- **`--dry-run` first, and it must be the default posture.** Report, per paper: old chunk count, new
  chunk count, how many ids change, how many duplicated headers would be removed. Stage nothing.
- **Back up before the real run.** `python -m app.snapshot` uses `VACUUM INTO` from a read-only
  connection, so it neither blocks nor is blocked by a live writer.
- **Resumable and idempotent.** Re-running over an already-processed paper must be a no-op, not a
  double-apply. A paper whose chunk ids and text are already correct should be skipped and counted
  as such.
- **Per-paper atomicity, not per-run.** `put()` is already atomic per paper; a crash mid-run must
  leave every processed paper consistent and every unprocessed one untouched.
- **Verify after.** Total chunk count, per-paper SQLite↔vector-store parity, and the duplication
  rate measured the same way the decision doc measured it (compare `lines[1]` against `lines[3]`).
- **Never touch** `papers`, `blocks`, `summaries`, `ingest_state`, or `ingest_checkpoint` content.
  `put()` rewrites the record wholesale, so confirm round-tripping `get`→`put` with only `chunks`
  changed genuinely preserves everything else — **including chapter summaries for books**, which are
  a separate table and must survive.

## Testing

- Round-trip: `get` → `put` with unchanged chunks leaves every table byte-identical.
- A paper with duplicated headers loses them; chunk text otherwise unchanged.
- Chunk ids that disappear have their vectors deleted; ids that persist are upserted, not
  duplicated.
- Re-running is a no-op (idempotency).
- A book with chapter summaries keeps them across a re-chunk.
- `--dry-run` writes nothing — assert against both stores.

## Risks

- **Chunk boundaries may shift**, not just text. `_strip_duplicate_heading` removes a line, which
  changes character offsets and can move a chunk's end. Anchors (`Anchor`, used by `get_span`) are
  derived per chunk and must stay valid — verify `get_span` still resolves for a re-chunked paper.
- **The 7 post-fix chunks that still show duplication** are unexplained. Worth looking at one before
  assuming the fix is total; they may reveal a second, narrower bug.
- Vector-store deletes are not transactional with SQLite. Same ordering rationale as
  `delete_paper`: commit SQLite first, then reconcile vectors, so a crash leaves a detectable
  vector-side orphan rather than the worse inverse.

## Out of scope

- Re-embedding the whole corpus (option C) — only justified if the contextual-header A/B (T-DOC41)
  happens, which would subsume this.
- Changing the chunker itself. It is already correct.
