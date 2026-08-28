"""`app/exp_chunk_boundary_latechunk_embed.py` -- SB-1 arm (a): late-chunking-style section-scoped
embedding.

MECHANISM: today's chunk embedding text is `{title}\n{section_path}\n\n{body}` -- the chunk's own
span only (`rag/chunker.py::_build_chunk`, read but never edited by this ticket). This arm embeds
a chunk together with a bounded WORD WINDOW pulled from its position-adjacent siblings (same
paper, chunk-id numeric suffix +/-1 -- the identical chunk-position ordering
`app/exp_chunk_boundary_neighbor_smooth.py` and D2's own instrument both use), so a chunk's DENSE
vector reflects some of its neighbourhood, not only its own text. This targets D2's
`adjacent_chunk` bucket and, for the rarer case where a section was split across multiple chunks
(`rag/chunker.py::_split_oversized`), its `same_section` bucket too -- a split section's chunks
are, by construction, also position-adjacent, so one mechanism covers both of the ticket's named
targets ("boundary and sibling-section findability") without a second code path.

WHY A WORD WINDOW, NOT LITERAL TOKEN-LEVEL LATE CHUNKING: true late chunking (embed a long context
once, mean-pool each chunk's own token span out of it) needs per-token embeddings from the serving
stack; the deployed embedding server here returns one pooled vector per request (`GET /info`:
`"pooling":"last_token"`), not per-token output -- there is no seam to pool from without changing
the serving stack itself, which is out of scope for an experiment ticket. A neighbour-word-window
prefix/suffix is the documented, "-style" approximation this ticket's own wording anticipates
("late-chunking-STYLE") -- it costs zero generative calls, exactly like real late chunking, and
needs no serving-stack change.

WHY THIS FILE HAS NO GPU/vendor CODE OF ITS OWN: everything here is a pure `(PaperRecord, Chunk)
-> str` text transform (`build_section_context_text` / `make_embed_text_fn`), zero-GPU,
zero-network, fully unit-testable offline. The actual re-embed run -- constructing a real
embedder/vector-store client -- happens entirely inside `app/reembed_experiment.py` (T-DOC41's
already-allowlisted composition root, `ci/checks/vendor_isolation.py`), which this ticket extended
with one small, additive, backward-compatible hook (`reembed()`'s `embed_text_fn` parameter,
`--section-context-window` CLI flag) rather than duplicating its GPU-adapter wiring into a
second, un-allowlisted composition root. See that module's own docstring/diff for the extension;
see this ticket's report for why (a new file constructing the vendor HTTP client itself would trip
`ci/checks/vendor_isolation.py`'s check (a), and `ci/` is a foundation-gated path this ticket must
not touch).

CHUNK ORDERING CAVEAT (load-bearing): `rag/document_store.py::DocumentStore.get()` selects a
paper's chunks with no `ORDER BY` -- `record.chunks`' list order is NOT guaranteed to be
chunk-index order. `_sorted_chunks()` below re-derives the true order from each `chunk_id`'s own
`:c{n}` numeric suffix before ever looking at a neighbour, exactly like D2's own `PaperGeometry`
does from `blocks.idx`/anchor ordering -- never trust DB row order for this.

`payload.text` (the sparse/keyword channel) is UNTOUCHED by this arm -- `reembed()`'s own
discipline (module docstring: "Always the chunk's own real passage text -- NOT `embed_text`")
still applies unconditionally when `embed_text_fn` is given, so only the DENSE embedding differs
from baseline, isolating this arm's effect (one-variable-per-run, programme constraint).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from contracts.chunker import Chunk
from contracts.document_store import PaperRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = Path("/home/omar/ai-projects/research-system-rag/waymo/data/papers.db")

# Same chunk-id format as D2's own instrument and app/exp_chunk_boundary_neighbor_smooth.py's
# chunk_position() -- "{paper_id}:c{n}", n the chunker's own emission-order index.
_CHUNK_ID_RE = re.compile(r"^(?P<paper>.+):c(?P<n>\d+)$")

# Word count taken from each neighbour, one side. Modest relative to the deployed embedder's own
# max_input_length (measured live: 4096 tokens, `GET /info` on the TEI-style embed server this
# ticket's dry run priced against -- NOT the 32k the ticket text assumed; see the report) --
# most chunks (median ~440 words, rag/chunker.py's own docstring) plus two ~100-word windows sit
# comfortably under that ceiling; the server's own auto_truncate is the safety net for the tail.
DEFAULT_WINDOW_WORDS = 100


def _chunk_index(chunk_id: str) -> int:
    m = _CHUNK_ID_RE.match(chunk_id)
    if not m:
        raise ValueError(f"unexpected chunk_id format (not '{{paper}}:c{{n}}'): {chunk_id!r}")
    return int(m.group("n"))


def sorted_chunks(record: PaperRecord) -> list[Chunk]:
    """`record.chunks` in true chunk-position order -- see module docstring's ordering caveat."""
    return sorted(record.chunks, key=lambda c: _chunk_index(c.chunk_id))


def _tail_words(text: str, n: int) -> str:
    words = text.split()
    return " ".join(words[-n:]) if n > 0 else ""


def _head_words(text: str, n: int) -> str:
    words = text.split()
    return " ".join(words[:n]) if n > 0 else ""


def build_section_context_text(
    record: PaperRecord, chunk: Chunk, window_words: int = DEFAULT_WINDOW_WORDS
) -> str:
    """The chunk's own text, with a bounded word window from each position-adjacent sibling (same
    paper) prepended/appended -- see module docstring's MECHANISM. Falls back to `chunk.text`
    unchanged at either end of a paper's chunk sequence (no previous/next sibling exists), and is
    therefore identical to baseline for any single-chunk paper.
    """
    ordered = sorted_chunks(record)
    idx = next((i for i, c in enumerate(ordered) if c.chunk_id == chunk.chunk_id), None)
    if idx is None:
        raise ValueError(f"chunk {chunk.chunk_id!r} not found in its own record's chunks")

    prev_ctx = _tail_words(ordered[idx - 1].text, window_words) if idx > 0 else ""
    next_ctx = _head_words(ordered[idx + 1].text, window_words) if idx + 1 < len(ordered) else ""
    parts = [p for p in (prev_ctx, chunk.text, next_ctx) if p]
    return "\n\n".join(parts)


def make_embed_text_fn(
    window_words: int = DEFAULT_WINDOW_WORDS,
) -> Callable[[PaperRecord, Chunk], str]:
    """Binds `window_words` into a plain `(PaperRecord, Chunk) -> str` callable -- the exact shape
    `app/reembed_experiment.py::reembed`'s `embed_text_fn` parameter expects."""

    def fn(record: PaperRecord, chunk: Chunk) -> str:
        return build_section_context_text(record, chunk, window_words)

    return fn


# --- dry-run pricing (offline: counts + word-length deltas; zero GPU, zero network) --------------


def price_corpus(records: Iterable[PaperRecord], window_words: int = DEFAULT_WINDOW_WORDS) -> dict:
    """Counts what a full re-embed over `records` would touch, and how much longer this arm's
    embed text runs vs. baseline -- the "count items" half of the ticket's required dry run. The
    timing half (real per-item throughput) is measured separately, over a small real sample, by
    timing `app/reembed_experiment.py` itself as a subprocess (see the report) -- this function
    stays zero-GPU/zero-network so it can run standalone, offline, over the whole corpus.
    """
    n_papers = 0
    n_chunks = 0
    baseline_words = 0
    arm_words = 0
    multi_chunk_sections = 0
    for record in records:
        n_papers += 1
        ordered = sorted_chunks(record)
        by_section: dict[str, int] = {}
        for c in ordered:
            by_section[c.section_path] = by_section.get(c.section_path, 0) + 1
        multi_chunk_sections += sum(1 for n in by_section.values() if n > 1)
        for chunk in ordered:
            n_chunks += 1
            baseline_words += len(chunk.text.split())
            arm_words += len(build_section_context_text(record, chunk, window_words).split())
    return {
        "n_papers": n_papers,
        "n_chunks": n_chunks,
        "multi_chunk_sections": multi_chunk_sections,
        "baseline_total_words": baseline_words,
        "arm_total_words": arm_words,
        "arm_vs_baseline_word_ratio": (arm_words / baseline_words) if baseline_words else None,
    }


def copy_summary_vectors(
    *, source_collection: str, dest_collection: str, host: str, port: int, dim: int,
    hybrid_dense_weight: float,
) -> int:
    """Copies every `kind="summary"` point from `source_collection` into `dest_collection`,
    verbatim (no re-embedding) -- via `rag.vector_index.VectorIndex.copy_kind_into` (see that
    method's own docstring for the mechanism). Real caller for arm (a)'s confound fix: this
    ticket's re-embed only touches `kind="chunk"` points, so a fresh destination collection
    otherwise holds zero summary vectors -- an unintended second variable (fewer candidates for
    `retrieve_papers()`/summary-kind hybrid search) alongside the one actually under test (chunk
    embed text). Deferred import of `rag.vector_index` (this file otherwise imports no vendor-
    adjacent module at all) -- reused only here, at the one real call site.
    """
    from rag.vector_index import VectorIndex

    source = VectorIndex(host, port, source_collection, dim, hybrid_dense_weight)
    return source.copy_kind_into(dest_collection, "summary")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"))
    parser.add_argument("--db-path", default=None, help="override Config.db_path")
    parser.add_argument("--blob-dir", default=None, help="override Config.blob_dir")
    parser.add_argument(
        "--window-words", type=int, default=DEFAULT_WINDOW_WORDS,
        help="word count taken from each position-adjacent neighbour",
    )
    parser.add_argument(
        "--copy-summaries-into", default=None, metavar="DEST_COLLECTION",
        help="skip the dry-run pricing path; instead copy every kind=summary point from "
             "--config's own Config.collection (read-only) into DEST_COLLECTION, verbatim, via "
             "copy_summary_vectors() -- the confound fix a chunk-only re-embed target needs "
             "before it can be evaluated on equal footing with the baseline collection",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """`python -m app.exp_chunk_boundary_latechunk_embed [--config ...]` -- offline dry-run
    pricing over the WHOLE corpus (every paper `DocumentStore.iter_papers()` yields). Read-only:
    only `DocumentStore.iter_papers()`/`.get()` are used, `papers.db` is never written.

    `--copy-summaries-into DEST_COLLECTION` switches to the confound-fix mode instead
    (`copy_summary_vectors()`) -- see that function's docstring.
    """
    args = _parse_args(argv)
    from rag.config import load_config

    cfg = load_config(args.config)

    if args.copy_summaries_into is not None:
        from app.reembed_experiment import _EMBEDDER_INFO, _VECTOR_STORE_HOST, _VECTOR_STORE_PORT

        copied = copy_summary_vectors(
            source_collection=cfg.collection, dest_collection=args.copy_summaries_into,
            host=_VECTOR_STORE_HOST, port=_VECTOR_STORE_PORT, dim=_EMBEDDER_INFO.dim,
            hybrid_dense_weight=cfg.hybrid_dense_weight,
        )
        print(
            f"SB-1 arm (a): copied {copied} kind=summary point(s) from {cfg.collection!r} "
            f"into {args.copy_summaries_into!r} (source untouched -- read-only scroll)"
        )
        return 0

    from rag.document_store import DocumentStore

    db_path = args.db_path or cfg.db_path
    blob_dir = args.blob_dir or cfg.blob_dir
    store = DocumentStore(db_path, blob_dir)

    result = price_corpus(store.iter_papers(), args.window_words)
    print(
        f"SB-1 arm (a) dry-run pricing: {result['n_papers']} papers, {result['n_chunks']} chunks, "
        f"{result['multi_chunk_sections']} multi-chunk sections; "
        f"words baseline={result['baseline_total_words']} arm={result['arm_total_words']} "
        f"(ratio {result['arm_vs_baseline_word_ratio']:.3f})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
