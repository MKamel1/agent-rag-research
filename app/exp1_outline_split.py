"""`python -m app.exp1_outline_split` -- Experiment 1 (docs/PLAN-book-rag-experiments.md): builds
the outline-based chapter split for the 4 outline-bearing books, re-summarizes them
(`summarize_book()`, unmodified -- see below), embeds the results into a throwaway collection, and
writes a re-derived eval fixture. Scoring is a separate, already-existing step, not this script's
job: `app/retrieval_eval.py --collection <throwaway> --db-path <throwaway db> --blob-dir <throwaway
blobs> --ground-truth <the fixture this script writes> --k 10`.

Gate: docs/eval-reports/2026-07-29-outline-join-feasibility.md -- the offset between a PDF outline
entry's `page_index` and the `blocks.page` it actually lands on is a CONSTANT 0 for all 4
outline-bearing books (94-100% of matched entries), so this script cuts at `page_index` directly,
with no per-entry fuzzy re-verification at split time (that verification is
`app/outline_join_probe.py`'s job, already done once). Splitter itself:
`rag/book_summarizer.py`'s `_split_chapters_outline`/`pick_outline_level` -- a new function
alongside the existing `_split_chapters`, never replacing it (the gate doc's own risk note: the
outline only helps 4 of 5 books, so size-merge can never be deleted).

Read-only against the corpus: `sqlite3.connect` on `Config.db_path` always carries `?mode=ro`, this
script never constructs `rag.document_store.DocumentStore` against it (that class's constructor
opens its db_path read-write and runs `migrate()`), and `--dest-collection` has no default and is
checked against `Config.collection` (`app/reembed_experiment.py`'s own refuse-by-check pattern) so
the production Qdrant collection can never be targeted by omission. All writes land on a throwaway
SQLite copy under `--work-dir` (`app/snapshot.py`'s own `VACUUM INTO`-from-a-read-only-source
pattern, reused via `backup_sqlite`) and a throwaway Qdrant collection seeded from production via
`VectorIndex.clone_points_into` -- no re-embedding of the ~372k already-computed vectors this
experiment doesn't touch; GPU time is spent only on the ~90 chapter summaries + 4 book overviews
this experiment actually changes.

`summarize_book()` itself is never edited -- its only variable is which function the module-level
name `rag.book_summarizer._split_chapters` resolves to at call time, substituted for the duration
of one call via `unittest.mock.patch` (`_summarize_with_outline_split` below). The task's own
instruction was "if you find yourself editing summarize_book(), stop and report why" -- the
alternatives considered and rejected: (a) adding a splits parameter to `summarize_book()` itself
(an edit); (b) having `_split_chapters_outline` return a `ParsedDoc` whose block `section_path`s
are relabeled to trick the existing marker-regex strategy into reproducing the outline split (this
actually works for 3 of 4 books, whose outline titles already start with "Chapter"/"Part"/a bare
number, but corrupts the persisted title with a synthetic prefix for those, and fails entirely for
Elements of CI, whose topic-style titles never match the marker regex at all -- see gate doc Q5).
Substituting the module-level name is the one option that changes neither `summarize_book()`'s
source nor any book's persisted title.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from unittest import mock

import httpx
import pypdfium2 as pdfium

import rag.book_summarizer as book_summarizer
from app.snapshot import backup_sqlite
from contracts.document_store import ChapterSummary
from contracts.embedder import EmbedderInfo
from contracts.parser import ParsedDoc
from contracts.provenance import Block
from rag.book_summarizer import OutlineEntry, _split_chapters_outline, pick_outline_level, summarize_book
from rag.config import load_config
from rag.document_store import DocumentStore
from rag.embedder import TeiEmbedder
from rag.gpu_lock import FileGpuLock
from rag.summarizer import OllamaSummarizer
from rag.vector_index import VectorIndex

logger = logging.getLogger(__name__)

# Same real-service wiring app/assembly.py/app/reembed_experiment.py use -- composition-root
# constants, not Config fields (nothing here varies across environments beyond what --config
# already supplies for db_path/collection).
_TEI_EMBED_URL = "http://localhost:8080"
_OLLAMA_URL = "http://localhost:11434"
_OLLAMA_MODEL = "qwen3:14b"
_VECTOR_STORE_HOST = "localhost"
_VECTOR_STORE_PORT = 6333
_EMBEDDER_INFO = EmbedderInfo(model_id="Qwen3-Embedding-4B", dim=2560, version="v1")

# Same absolute path app/outline_join_probe.py already reads the 6 drop-in PDFs from -- this
# worktree has no `drop_in/` of its own (untracked, never copied by `git worktree add`), and the
# PDFs never change, so reading them from the checkout that has them is a plain file read, not a
# write, not a `cd`.
PDF_DIR = Path("/home/omar/ai-projects/research-system-rag/drop_in/done")

# The 4 outline-bearing books this experiment re-splits. Trustworthy OCE (local:14b7e283bdcd) is
# the untouched control -- deliberately absent, per the gate doc's go/no-go table (it has 0
# `get_toc()` entries).
BOOK_IDS = [
    "local:f0929288d4f3",  # Causal Inference in Python
    "local:f6c64e1e8c7d",  # Elements of Causal Inference
    "local:dfe850b3281a",  # Causal Inference and Discovery in Python
    "local:54d6ca71dda9",  # Causal Inference and ML in Econ/Social/Health
]


class Exp1Error(RuntimeError):
    """The requested run can't proceed as configured, or a book didn't behave the way the gate
    doc said it would -- refuses the whole run rather than partially run."""


def _check_collection_is_not_production(collection: str, production_collection: str) -> None:
    if collection == production_collection:
        raise Exp1Error(
            f"--dest-collection must not be the production collection ({production_collection!r})"
            " -- pass a throwaway name for this experiment"
        )


# --------------------------------------------------------------------------------------------
# Read-only corpus access (never DocumentStore -- its constructor opens db_path read-write)
# --------------------------------------------------------------------------------------------


def _row_to_block(row: sqlite3.Row) -> Block:
    """Same construction as rag/document_store.py's `DocumentStore._row_to_block` -- duplicated,
    not imported, because that class's constructor migrates its db_path on open, which this
    script must never do against the corpus's own `papers.db`."""
    return Block(
        block_id=row["block_id"],
        paper_id=row["paper_id"],
        text=row["text"],
        type=row["type"],
        page=row["page"],
        bbox=tuple(json.loads(row["bbox_json"])),
        section_path=row["section_path"],
        index=row["idx"],
    )


def load_blocks_readonly(conn: sqlite3.Connection, paper_id: str) -> list[Block]:
    rows = conn.execute(
        "SELECT * FROM blocks WHERE paper_id = ? ORDER BY idx", (paper_id,)
    ).fetchall()
    return [_row_to_block(r) for r in rows]


def load_outline_entries(pdf_path: Path) -> list[OutlineEntry]:
    """`pdf.get_toc()` -> `OutlineEntry`, resolving each bookmark's page via `get_dest().
    get_index()` -- 0-based, confirmed against `blocks.page` in the gate doc (Q1). Entries
    `get_dest()` can't resolve (0 of 1,035 across these 4 books, per the gate doc) are dropped,
    not passed through as a placeholder page."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    entries = []
    for e in pdf.get_toc():
        dest = e.get_dest()
        if dest is None:
            continue
        entries.append(
            OutlineEntry(level=e.level, title=e.get_title(), page_index=dest.get_index())
        )
    return entries


def _minimal_parsed_doc(paper_id: str, blocks: list[Block]) -> ParsedDoc:
    """Good enough for `_split_chapters_outline`/`summarize_book`: both only ever read `.blocks`
    and `.paper_id` off a `ParsedDoc`. `.markdown` is unconditionally overwritten per-chapter by
    `_doc_from_text` (rag/book_summarizer.py) before any `summarize()` call reads it, so a
    placeholder here is never actually read."""
    return ParsedDoc(
        paper_id=paper_id,
        markdown="",
        blocks=blocks,
        figures=[],
        tables=[],
        references=[],
        parser_id="exp1-db-reconstructed",
    )


def _pdf_filenames(conn: sqlite3.Connection, paper_ids: list[str]) -> dict[str, str]:
    rows = conn.execute(
        "SELECT paper_id, pdf_path FROM papers WHERE paper_id IN (%s)"
        % ",".join("?" for _ in paper_ids),
        paper_ids,
    ).fetchall()
    found = {r["paper_id"]: r["pdf_path"] for r in rows}
    missing = set(paper_ids) - found.keys()
    if missing:
        raise Exp1Error(f"paper_id(s) not found in corpus: {sorted(missing)}")
    return found


# --------------------------------------------------------------------------------------------
# Split computation (GPU-free)
# --------------------------------------------------------------------------------------------


class BookSplit:
    def __init__(
        self, paper_id: str, parsed: ParsedDoc, units: list[tuple[str, list[Block]]]
    ):
        self.paper_id = paper_id
        self.parsed = parsed
        self.units = units


def compute_splits(conn: sqlite3.Connection) -> dict[str, BookSplit]:
    """GPU-free: reads blocks + PDF outlines read-only, computes the outline split for all 4
    books. Raises `Exp1Error` if any book doesn't clear >=2 boundaries -- the gate doc found all
    4 do, so a failure here means something upstream changed and this experiment should stop, not
    silently skip a book."""
    pdf_by_id = _pdf_filenames(conn, BOOK_IDS)
    result = {}
    for paper_id in BOOK_IDS:
        entries = load_outline_entries(PDF_DIR / pdf_by_id[paper_id])
        blocks = load_blocks_readonly(conn, paper_id)
        parsed = _minimal_parsed_doc(paper_id, blocks)
        units = _split_chapters_outline(parsed, entries)
        if units is None:
            raise Exp1Error(
                f"{paper_id}: outline split produced <2 boundaries -- the gate doc found this "
                "book qualifies; something changed, re-check before proceeding"
            )
        result[paper_id] = BookSplit(paper_id, parsed, units)
    return result


def duplicate_titles(units: list[tuple[str, list[Block]]]) -> list[str]:
    titles = [t for t, _ in units if t]
    return sorted({t for t in titles if titles.count(t) > 1})


def split_report(splits: dict[str, BookSplit]) -> dict:
    report = {}
    for paper_id, split in splits.items():
        total_words = sum(len(b.text.split()) for b in split.parsed.blocks) or 1
        shares = sorted(
            sum(len(b.text.split()) for b in blocks) / total_words for _, blocks in split.units
        )
        n = len(shares)
        median = shares[n // 2] if n % 2 else (shares[n // 2 - 1] + shares[n // 2]) / 2
        report[paper_id] = {
            "unit_count": len(split.units),
            "word_share_min": shares[0],
            "word_share_median": median,
            "word_share_max": shares[-1],
            "duplicate_titles": duplicate_titles(split.units),
            "titles": [t for t, _ in split.units],
        }
    return report


# --------------------------------------------------------------------------------------------
# GPU step: summarize_book(), unmodified -- see module docstring
# --------------------------------------------------------------------------------------------


def summarize_with_outline_split(
    parsed: ParsedDoc, units: list[tuple[str, list[Block]]], summarizer
) -> tuple[str, list[ChapterSummary]]:
    """Runs the UNCHANGED `summarize_book()` with `rag.book_summarizer._split_chapters`
    substituted to return `units`, for the duration of this one call only. See module docstring
    for why this substitution point was chosen over editing `summarize_book()`."""
    with mock.patch.object(book_summarizer, "_split_chapters", return_value=units):
        return summarize_book(parsed, summarizer)


# --------------------------------------------------------------------------------------------
# Throwaway SQLite copy
# --------------------------------------------------------------------------------------------


def build_throwaway_db(source_db_path: str, work_dir: Path) -> Path:
    """`app/snapshot.py`'s own `backup_sqlite` -- `VACUUM INTO` from a **read-only** connection to
    the source, so this never blocks or touches a live writer against the corpus. Returns the
    copy's path (writable -- it's a new file, not the corpus's own)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    backup_sqlite(source_db_path, work_dir)
    return work_dir / "papers.db"


def write_new_chapters(
    document_store: DocumentStore, paper_id: str, overview_text: str, chapters: list[ChapterSummary]
) -> list[str]:
    """`document_store` must be opened against the THROWAWAY copy, never the corpus. Returns the
    OLD chapter summary_ids (before this call) -- `DocumentStore.put()`'s delete-then-insert
    already retires them from the SQLite copy; the caller still has to delete them from the
    vector store, which `put()` doesn't touch (T-DOC40's split: SQLite and vectors are two
    stores, kept in sync by the caller that owns both)."""
    record = document_store.get(paper_id)
    if record is None:
        raise Exp1Error(f"{paper_id}: not found in the throwaway db copy")
    old_chapter_ids = [cs.summary_id for cs in record.chapter_summaries]
    document_store.put(
        record.model_copy(update={"summary_text": overview_text, "chapter_summaries": chapters})
    )
    return old_chapter_ids


# --------------------------------------------------------------------------------------------
# Throwaway Qdrant collection
# --------------------------------------------------------------------------------------------


def clone_production_collection(source_collection: str, dest_collection: str, dim: int) -> int:
    source = VectorIndex(_VECTOR_STORE_HOST, _VECTOR_STORE_PORT, source_collection, dim)
    return source.clone_points_into(dest_collection)


def swap_chapter_vectors(
    vector_index: VectorIndex,
    embedder,
    paper_id: str,
    overview_text: str,
    chapters: list[ChapterSummary],
    old_chapter_ids: list[str],
    payload_common: dict,
) -> None:
    """Overwrites the whole-book summary vector (same id, plain upsert) and the chapter vectors
    (new ids upserted, stale old ids explicitly deleted -- an upsert alone never removes an id
    that's no longer produced, same T-DOC40 reasoning `rag/orchestrator.py`'s own upsert path
    documents)."""
    texts = [overview_text] + [c.text for c in chapters]
    vectors = embedder.embed(texts)
    overview_vec, chapter_vecs = vectors[0], vectors[1:]

    vector_index.upsert(
        f"{paper_id}:summary",
        overview_vec,
        {**payload_common, "kind": "summary", "section_path": "", "text": overview_text},
    )
    new_ids = {c.summary_id for c in chapters}
    stale = [i for i in old_chapter_ids if i not in new_ids]
    vector_index.delete(stale)
    for chapter, vector in zip(chapters, chapter_vecs, strict=True):
        vector_index.upsert(
            chapter.summary_id,
            vector,
            {**payload_common, "kind": "summary", "section_path": chapter.title, "text": chapter.text},
        )


# --------------------------------------------------------------------------------------------
# Eval fixture re-derivation
# --------------------------------------------------------------------------------------------


def _block_id_to_unit_index(units: list[tuple[str, list[Block]]]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for n, (_, blocks) in enumerate(units):
        for b in blocks:
            mapping[b.block_id] = n
    return mapping


def rederive_fixture(
    old_fixture: dict,
    splits: dict[str, BookSplit],
    final_chapters: dict[str, list[ChapterSummary]],
) -> tuple[dict, list[str]]:
    """Re-derives `gold_chapter_title`/`gold_chapter_index` for every question whose
    `source_paper_id` is one of the 4 re-split books, by looking up its (unchanged)
    `gold_block_id` in the NEW split's block->unit map, then reading that unit's FINAL persisted
    title off `final_chapters` (post any LLM title-fallback `summarize_book()` ran) -- the exact
    title that ends up embedded/searchable, not the pre-fallback "". A question on the untouched
    OCE book, or any other book outside `splits`, is carried over byte-for-byte. Returns
    (new_fixture, unmapped_question_ids) -- a question whose gold_block_id falls in NO unit of the
    new split is a real bug (block-level provenance is supposed to be untouched by this
    experiment) and is surfaced, not silently dropped or left with a stale title.
    """
    id_maps = {pid: _block_id_to_unit_index(s.units) for pid, s in splits.items()}
    new_records = []
    unmapped = []
    for r in old_fixture["ground_truth"]:
        r = dict(r)
        pid = r["source_paper_id"]
        if pid in id_maps:
            idx = id_maps[pid].get(r["gold_block_id"])
            if idx is None:
                unmapped.append(r["question_id"])
            else:
                r["gold_chapter_title"] = final_chapters[pid][idx].title
                r["gold_chapter_index"] = idx
        new_records.append(r)
    new_fixture = dict(old_fixture)
    new_fixture["ground_truth"] = new_records
    return new_fixture, unmapped


# --------------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------------


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
        logger.info("summarizing %s (%d outline units)", paper_id, len(split.units))
        overview_text, chapters = summarize_with_outline_split(split.parsed, split.units, summarizer)
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
        raise Exp1Error(
            f"{len(unmapped)} question(s) had a gold_block_id outside every new unit "
            f"(block-level provenance should be untouched): {unmapped}"
        )
    Path(args.fixture_out).write_text(json.dumps(new_fixture, indent=2))
    print(f"wrote re-derived fixture to {args.fixture_out}")


if __name__ == "__main__":
    main()
