"""`python -m app.rechunk` -- T-DOC62 option B: retrofit an already-landed chunker fix onto
papers that were chunked before it landed, without re-parsing.

`rag/chunker.py::_strip_duplicate_heading` (commit `157af4d`, landed 2026-07-17) stops a chunk's
body from repeating its own section heading (`title\\nsection_path\\n\\n<body>`, where the
body's first block used to also start with that same heading). Everything ingested since is
clean; 809 papers ingested before that date still carry the duplicate in their stored `chunks`
(measured in `docs/DECISION-t-doc62-duplicate-chunk-headers.md`: 58.49% of their chunks, ~14,850
total, 4.1% of the whole corpus). `DocumentStore.get(paper_id)` returns the stored `blocks`
untouched by the bug -- only `Chunk.text` (derived from them) was ever wrong -- so this re-derives
`chunks` from those blocks and re-embeds, skipping harvest/parse/summarize entirely (the expensive
stages). See `docs/superpowers/specs/2026-07-28-rechunk-from-blocks-design.md` for the full design.

General and reusable, not a one-off: this is the second retrofit of this exact shape
(`app/reindex_idf.py` was the first, for a different fix) and there will be a third. Any future
chunker change that needs retrofitting onto already-stored papers can reuse `run_rechunk`
unchanged -- it never assumes anything about *why* the new chunks differ from the old ones.

Per paper, in order (`run_rechunk` below):

1. `record = document_store.get(paper_id)` -- the current source of truth.
2. `new_chunks = chunker.chunk(record.parsed)` -- re-chunk from the stored blocks.
3. If `new_chunks == record.chunks` (pydantic value equality, e.g. an already-migrated paper on a
   re-run), this paper is a no-op: counted `skipped_noop`, nothing is read or written further.
4. `--dry-run` stops here too, before any write, reporting what step 5 onward *would* do.
5. `document_store.put(record.model_copy(update={"chunks": new_chunks}))` -- atomic per paper,
   changes nothing else in the record (ref/parsed/summary_text/summary_id/chapter_summaries are
   all copied from the `get()` result verbatim).
6. Vector sync -- the part that must not be got wrong. `Chunk.chunk_id` is `f"{paper_id}:c{index}"`
   (`rag/chunker.py`), purely positional, so for THIS fix (a same-first-line strip; grouping and
   split points are unaffected) the chunk_id set never actually changes. But the tool is built
   generically, because a future chunker change (re-grouping, a different split policy) could
   change how many chunks a paper produces and what their ids are, and a plain upsert over that
   would leave the old ids' points orphaned -- searchable, with no matching SQLite row, the exact
   T-DOC23/T-DOC35 shape that crashes `get_chunk` on a hit. So: delete the ids that disappeared
   (`old_ids - new_ids`) first, then embed and upsert every new chunk. Deliberately NOT
   `IngestionOrchestrator.delete_paper` -- that drops a paper's summary vectors too, which this
   never touches.

SQLite (`put`) commits before the vector-store reconciliation, same ordering rationale as
`delete_paper` (`rag/orchestrator.py`): a crash between the two leaves a detectable vector-side
orphan (a point with no matching SQLite chunk row) rather than the worse inverse (SQLite pointing
at chunks with no vectors). An orphan from this window is idempotently fixed by re-running this
paper_id -- `document_store.put` and `vector_index.delete`/`upsert` are all safe to repeat.

Resumable: paper_ids are processed one at a time, each either fully committed (SQLite + vectors)
or, on a crash, not committed at all (the exception propagates and stops the run -- CONVENTIONS.md
§4, an unexpected exception here is a bug, not a per-paper `PermanentError` case). Re-running the
same `--paper-ids` list afterward finds every already-fixed paper equal on step 3 and skips it;
only the papers after the crash point actually do any work.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from contracts.chunker import Chunk
from contracts.document_store import PaperRecord
from contracts.embedder import EmbedderInfo, Vector
from contracts.errors import ContractError
from contracts.parser import ParsedDoc
from contracts.vector_index import VectorPayload
from rag.config import load_config
from rag.orchestrator import vector_payload

# Same real-service wiring `app/reembed_experiment.py` uses (composition-root constants, not
# `Config` fields -- nothing here varies across environments beyond what `--config` already
# supplies for the document store / vector-store collection).
_EMBEDDER_URL = "http://localhost:8080"
_VECTOR_STORE_HOST = "localhost"
_VECTOR_STORE_PORT = 6333
_EMBEDDER_INFO = EmbedderInfo(model_id="Qwen3-Embedding-4B", dim=2560, version="v1")


class RechunkableDocumentStore(Protocol):
    def get(self, paper_id: str) -> PaperRecord | None: ...
    def put(self, record: PaperRecord) -> None: ...


class RechunkableVectorStore(Protocol):
    def delete(self, ids: list[str]) -> None: ...
    def upsert(self, id: str, vector: Vector, payload: VectorPayload) -> None: ...


# Named *Seam, not *Embedder (same convention app/reembed_experiment.py's `_EmbedderSeam` uses):
# CI check (f) flags any class ending in "Embedder"/"Summarizer"/"Reranker" outside contracts/ or
# rag/fakes/ as a real GPU-bound adapter missing its required `gpu_lock: GpuLock` parameter -- this
# is a Protocol (an interface, not an adapter), so it must not end in one of those suffixes.
class RechunkableEmbedderSeam(Protocol):
    @property
    def info(self) -> EmbedderInfo: ...
    def embed(self, texts: list[str]) -> list[Vector]: ...


class RechunkableChunker(Protocol):
    def chunk(self, doc: ParsedDoc) -> list[Chunk]: ...


@dataclass(frozen=True)
class PaperRechunkResult:
    """One paper's outcome -- what `--dry-run` reports and what a real run actually did."""

    paper_id: str
    status: Literal["rechunked", "would_rechunk", "skipped_noop"]
    old_chunk_count: int
    new_chunk_count: int
    ids_removed: int  # old chunk_ids absent from the new set -- vectors were/would be deleted
    ids_added: int  # new chunk_ids absent from the old set
    duplicated_headers_removed: int  # old chunks whose body repeated section_path (T-DOC62 bug)


def _is_duplicated(chunk_text: str) -> bool:
    """Same measurement `docs/DECISION-t-doc62-duplicate-chunk-headers.md` used: a chunk's text
    is `title\\n{section_path}\\n\\n{body}` (`rag/chunker.py::_build_chunk`) -- line index 1 is
    the section_path, line index 3 is the body's own first line. They match (whitespace-
    normalized) iff the heading is duplicated there."""
    lines = chunk_text.split("\n")
    if len(lines) <= 3 or not lines[1].strip():
        return False
    return " ".join(lines[1].split()) == " ".join(lines[3].split())


def run_rechunk(
    document_store: RechunkableDocumentStore,
    vector_index: RechunkableVectorStore,
    embedder: RechunkableEmbedderSeam,
    chunker: RechunkableChunker,
    paper_ids: list[str],
    *,
    dry_run: bool,
) -> list[PaperRechunkResult]:
    """Re-chunks every id in `paper_ids` from its stored blocks; see module docstring for the
    full per-paper flow. `dry_run=True` calls only `document_store.get` and `chunker.chunk`
    (both read-only/pure) -- never `document_store.put`, `vector_index.delete`/`upsert`, or
    `embedder.embed`.

    Precondition: every id in `paper_ids` must resolve via `document_store.get` -- an unknown
    paper_id raises `ContractError` and stops the run there (CONVENTIONS.md §4: this is an
    operator input error, not a per-paper data problem to quarantine and skip past). Every result
    already appended to the returned list at that point describes paper(s) already fully
    committed -- safe to leave as-is; re-run with the bad id fixed or removed.
    """
    results: list[PaperRechunkResult] = []
    for paper_id in paper_ids:
        record = document_store.get(paper_id)
        if record is None:
            raise ContractError(
                f"rechunk: unknown paper_id {paper_id!r} -- not found in the document store. "
                f"{len(results)} paper(s) processed above are already committed; fix or remove "
                f"this id and re-run the same --paper-ids list to resume."
            )

        new_chunks = chunker.chunk(record.parsed)
        old_ids = {c.chunk_id for c in record.chunks}
        new_ids = {c.chunk_id for c in new_chunks}
        duplicated = sum(1 for c in record.chunks if _is_duplicated(c.text))

        if new_chunks == record.chunks:
            results.append(
                PaperRechunkResult(
                    paper_id=paper_id, status="skipped_noop",
                    old_chunk_count=len(record.chunks), new_chunk_count=len(new_chunks),
                    ids_removed=0, ids_added=0, duplicated_headers_removed=duplicated,
                )
            )
            continue

        ids_removed = old_ids - new_ids
        ids_added = new_ids - old_ids

        if dry_run:
            results.append(
                PaperRechunkResult(
                    paper_id=paper_id, status="would_rechunk",
                    old_chunk_count=len(record.chunks), new_chunk_count=len(new_chunks),
                    ids_removed=len(ids_removed), ids_added=len(ids_added),
                    duplicated_headers_removed=duplicated,
                )
            )
            continue

        updated = record.model_copy(update={"chunks": new_chunks})
        document_store.put(updated)  # source of truth, committed before the derived vector index

        vector_index.delete(list(ids_removed))
        vectors = embedder.embed([c.text for c in new_chunks])
        for chunk, vector in zip(new_chunks, vectors, strict=True):
            # RI-3: the payload comes from rag/orchestrator.py's one shared builder, not a local
            # copy -- this tool's own copy once omitted `author_orgs`/`curated_author_orgs`, so a
            # rechunked paper silently dropped out of org-filtered retrieval.
            vector_index.upsert(
                chunk.chunk_id,
                vector,
                vector_payload(
                    updated,
                    embedder.info.version,
                    kind="chunk",
                    section_path=chunk.section_path,
                    text=chunk.text,
                ),
            )

        results.append(
            PaperRechunkResult(
                paper_id=paper_id, status="rechunked",
                old_chunk_count=len(record.chunks), new_chunk_count=len(new_chunks),
                ids_removed=len(ids_removed), ids_added=len(ids_added),
                duplicated_headers_removed=duplicated,
            )
        )
    return results


def format_report(results: list[PaperRechunkResult], *, dry_run: bool) -> str:
    """Per-paper line + a totals line -- the "report richly" half of `--dry-run`'s contract, but
    used for both dry-run and real-run output so the two are easy to compare by eye."""
    verb = "would rechunk" if dry_run else "rechunked"
    lines = []
    for r in results:
        if r.status == "skipped_noop":
            lines.append(f"{r.paper_id}: already correct -- skipped (no-op)")
        else:
            lines.append(
                f"{r.paper_id}: {verb} -- {r.old_chunk_count} -> {r.new_chunk_count} chunks, "
                f"{r.ids_removed} vector id(s) to delete, {r.ids_added} new, "
                f"{r.duplicated_headers_removed} duplicated header(s) removed"
            )

    changed = [r for r in results if r.status != "skipped_noop"]
    skipped = [r for r in results if r.status == "skipped_noop"]
    prefix = "DRY RUN -- " if dry_run else ""
    lines.append(
        f"{prefix}rechunk: {len(results)} paper(s) -- {len(changed)} {verb}, "
        f"{len(skipped)} already correct (skipped), "
        f"{sum(r.duplicated_headers_removed for r in results)} duplicated header(s) total, "
        f"{sum(r.ids_removed for r in results)} vector id(s) to delete total"
    )
    return "\n".join(lines)


def _paper_ids_from_args(args: argparse.Namespace) -> list[str]:
    # Same shape as `app/reembed_experiment.py`'s own `_paper_ids_from_args` -- one house
    # convention for "a CLI's target paper set," not reinvented here.
    if args.paper_ids:
        return [p.strip() for p in args.paper_ids.split(",") if p.strip()]
    if args.paper_ids_file:
        return [
            line.strip()
            for line in Path(args.paper_ids_file).read_text().splitlines()
            if line.strip()
        ]
    raise ContractError("rechunk: one of --paper-ids / --paper-ids-file is required")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default="config.yaml",
        help="config.yaml to read db_path/blob_dir/collection from",
    )
    parser.add_argument("--paper-ids", default=None, help="comma-separated paper ids")
    parser.add_argument(
        "--paper-ids-file", default=None, help="path to a file of one paper id per line"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what would change; write to neither the document store nor the vector index",
    )
    return parser.parse_args()


def main() -> None:
    import httpx

    from rag.chunker import Chunker
    from rag.document_store import DocumentStore
    from rag.embedder import TeiEmbedder
    from rag.gpu_lock import FileGpuLock
    from rag.vector_index import VectorIndex  # only imported here (CONVENTIONS.md §1)

    args = _parse_args()
    cfg = load_config(args.config)
    paper_ids = _paper_ids_from_args(args)

    gpu_lock = FileGpuLock(Path(cfg.gpu_lock_path))
    document_store = DocumentStore(cfg.db_path, cfg.blob_dir)
    vector_index = VectorIndex(
        _VECTOR_STORE_HOST, _VECTOR_STORE_PORT, cfg.collection, _EMBEDDER_INFO.dim,
        cfg.hybrid_dense_weight,
    )
    embedder = TeiEmbedder(
        httpx.Client(base_url=_EMBEDDER_URL, timeout=60.0), gpu_lock, _EMBEDDER_INFO
    )
    chunker = Chunker(cfg)

    results = run_rechunk(
        document_store, vector_index, embedder, chunker, paper_ids, dry_run=args.dry_run
    )
    print(format_report(results, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
