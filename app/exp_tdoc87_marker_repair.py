"""`python -m app.exp_tdoc87_marker_repair` -- T-DOC87 phase 2: re-summarizes the two books whose
chapter-marker split changed under the repaired `rag.book_summarizer._split_chapters` (Discovery
in Python, Econ/Social/Health -- see docs/eval-reports/2026-07-29-tdoc87-marker-regex-repair.md),
embeds the results into a throwaway collection cloned from production, and writes a re-derived
eval fixture. Scoring is a separate step: `scripts/tdoc87_routing_eval.py` (chapter routing,
unfiltered + `doc_type="book"`, per-book breakdown).

Mirrors `app/exp1_outline_split.py`'s infrastructure almost exactly (read-only corpus access,
throwaway SQLite copy via `VACUUM INTO`, throwaway Qdrant collection via `clone_points_into`,
`rederive_fixture`) -- reused directly from that module rather than duplicated, since none of it
is outline-specific. The only different piece is `compute_splits`: no PDF, no outline join, no
`unittest.mock.patch` substitution -- the repair lives IN `_split_chapters` itself now, so calling
it directly on each book's blocks already gets the repaired behavior, and `summarize_book()` is
called completely unmodified (it always resolves `_split_chapters` to the live, already-fixed
module-level function).

Read-only against the corpus: `sqlite3.connect` on `Config.db_path` always carries `?mode=ro`, and
this script never constructs `rag.document_store.DocumentStore` against it. `--dest-collection`
has no default and is checked against `Config.collection` so the production Qdrant collection can
never be targeted by omission. All writes land on a throwaway SQLite copy under `--work-dir` and a
throwaway Qdrant collection seeded from production via `VectorIndex.clone_points_into` -- GPU time
is spent only on the 2 books' chapter summaries + overviews, never a re-embed of the ~372k
already-computed vectors this experiment doesn't touch.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from pathlib import Path

import httpx

import rag.book_summarizer as book_summarizer
from app.exp1_outline_split import (
    BookSplit,
    _check_collection_is_not_production,
    _minimal_parsed_doc,
    build_throwaway_db,
    clone_production_collection,
    load_blocks_readonly,
    rederive_fixture,
    split_report,
    swap_chapter_vectors,
    write_new_chapters,
)
from contracts.document_store import ChapterSummary
from contracts.embedder import EmbedderInfo
from rag.book_summarizer import summarize_book
from rag.config import load_config
from rag.document_store import DocumentStore
from rag.embedder import TeiEmbedder
from rag.gpu_lock import FileGpuLock
from rag.summarizer import OllamaSummarizer
from rag.vector_index import VectorIndex

logger = logging.getLogger(__name__)

# Same real-service wiring app/assembly.py/app/exp1_outline_split.py use -- composition-root
# constants, duplicated per that module's own convention (each experiment script wires its own
# copy rather than importing another script's private names for values that never vary).
_TEI_EMBED_URL = "http://localhost:8080"
_OLLAMA_URL = "http://localhost:11434"
_OLLAMA_MODEL = "qwen3:14b"
_VECTOR_STORE_HOST = "localhost"
_VECTOR_STORE_PORT = 6333
_EMBEDDER_INFO = EmbedderInfo(model_id="Qwen3-Embedding-4B", dim=2560, version="v1")

# The 2 books T-DOC87's regex repair changed the chapter split for (the other 3 are byte-identical
# before/after -- see the eval report's projection table -- so re-summarizing them would burn GPU
# time to reproduce the same vectors already in production).
BOOK_IDS = [
    "local:dfe850b3281a",  # Causal Inference and Discovery in Python
    "local:54d6ca71dda9",  # Causal Inference and ML in Econ/Social/Health
]


class TDoc87Error(RuntimeError):
    """The requested run can't proceed as configured, or a book didn't behave as expected --
    refuses the whole run rather than partially run."""


def compute_splits(conn: sqlite3.Connection) -> dict[str, BookSplit]:
    """GPU-free: loads each book's blocks read-only and runs them through the ALREADY-REPAIRED
    `book_summarizer._split_chapters` -- this IS the module's live default split now, so no
    substitution is needed (contrast `app/exp1_outline_split.py`'s `mock.patch`, needed there only
    because the outline split was never the default)."""
    result = {}
    for paper_id in BOOK_IDS:
        blocks = load_blocks_readonly(conn, paper_id)
        parsed = _minimal_parsed_doc(paper_id, blocks)
        units = book_summarizer._split_chapters(parsed)
        result[paper_id] = BookSplit(paper_id, parsed, units)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="corpus config.yaml (RAG_CONFIG env also works)")
    parser.add_argument("--dest-collection", required=True, help="throwaway target vector-store collection")
    parser.add_argument("--work-dir", required=True, help="writable scratch dir for the throwaway db copy")
    parser.add_argument("--fixture-in", default="fixtures/eval/eval_book_questions.json")
    parser.add_argument("--fixture-out", required=True)
    parser.add_argument("--report-out", default=None, help="write the split/duplicate-title report JSON here")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="compute + report splits only -- no GPU, no db copy, no vector-store writes",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()
    cfg = load_config(args.config)

    corpus_conn = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True)
    corpus_conn.row_factory = sqlite3.Row

    splits = compute_splits(corpus_conn)
    report = split_report(splits)
    print(json.dumps(report, indent=2))
    if args.report_out:
        Path(args.report_out).write_text(json.dumps(report, indent=2))

    if args.dry_run:
        corpus_conn.close()
        return

    _check_collection_is_not_production(args.dest_collection, cfg.collection)

    work_dir = Path(args.work_dir)
    throwaway_db_path = build_throwaway_db(cfg.db_path, work_dir)
    throwaway_blob_dir = work_dir / "blobs"
    document_store = DocumentStore(str(throwaway_db_path), str(throwaway_blob_dir))

    copied = clone_production_collection(cfg.collection, args.dest_collection, _EMBEDDER_INFO.dim)
    print(f"cloned {copied} points from {cfg.collection!r} into {args.dest_collection!r}")

    gpu_lock = FileGpuLock(Path(cfg.gpu_lock_path))
    t0 = time.monotonic()
    with gpu_lock.acquire("exp-tdoc87-marker-repair"):
        wait_s = time.monotonic() - t0
    print(f"GPU lock acquired (and released) after waiting {wait_s:.2f}s")

    summarizer = OllamaSummarizer(
        httpx.Client(base_url=_OLLAMA_URL, timeout=300.0), gpu_lock, _OLLAMA_MODEL
    )
    embedder = TeiEmbedder(
        httpx.Client(base_url=_TEI_EMBED_URL, timeout=60.0), gpu_lock, _EMBEDDER_INFO
    )
    vector_index = VectorIndex(
        _VECTOR_STORE_HOST, _VECTOR_STORE_PORT, args.dest_collection, _EMBEDDER_INFO.dim,
        cfg.hybrid_dense_weight,
    )

    final_chapters: dict[str, list[ChapterSummary]] = {}
    for paper_id, split in splits.items():
        logger.info("summarizing %s (%d repaired-split units)", paper_id, len(split.units))
        overview_text, chapters = summarize_book(split.parsed, summarizer)
        final_chapters[paper_id] = chapters

        old_chapter_ids = write_new_chapters(document_store, paper_id, overview_text, chapters)

        record = document_store.get(paper_id)
        assert record is not None  # just put() it
        payload_common = {
            "paper_id": paper_id,
            "categories": record.ref.categories,
            "published": record.ref.published.isoformat(),
            "embedding_version": embedder.info.version,
            "doc_type": record.ref.doc_type,
        }
        swap_chapter_vectors(
            vector_index, embedder, paper_id, overview_text, chapters, old_chapter_ids, payload_common
        )
        logger.info("%s: %d new chapter units embedded, %d stale old ids removed",
                     paper_id, len(chapters), len(set(old_chapter_ids) - {c.summary_id for c in chapters}))

    corpus_conn.close()

    old_fixture = json.loads(Path(args.fixture_in).read_text())
    new_fixture, unmapped = rederive_fixture(old_fixture, splits, final_chapters)
    if unmapped:
        raise TDoc87Error(
            f"{len(unmapped)} question(s) had a gold_block_id outside every new unit "
            f"(block-level provenance should be untouched): {unmapped}"
        )
    Path(args.fixture_out).write_text(json.dumps(new_fixture, indent=2))
    print(f"wrote re-derived fixture to {args.fixture_out}")


if __name__ == "__main__":
    main()
