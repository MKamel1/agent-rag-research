"""T-DOC62 option B -- `app/rechunk.py` test suite. Zero-GPU, zero-network (TEST-STRATEGY.md
golden rule): `run_rechunk` is driven against a REAL `rag.document_store.DocumentStore` (a real
`tmp_path` SQLite file -- this is exactly the put/get round-trip machinery the safety
requirements need proven for real, not faked) and a REAL `rag.chunker.Chunker` (the actual fix
under retrofit), plus `rag.fakes.FakeEmbedder`/`FakeVectorStore` standing in for the two real
services this tool would otherwise need a live GPU/vector-store server for.

Simulates "data written before the chunker fix" by taking the REAL (fixed) chunker's own output
for a block and swapping in the un-stripped, duplicated-heading text a pre-`157af4d` chunker
would have produced for the same block -- everything else about the chunk (id, anchor,
section_path, parent_id) is left exactly as the real chunker built it, because those fields never
depended on `_strip_duplicate_heading` in the first place (see the anchor tests below).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.rechunk import (
    PaperRechunkResult,
    _is_duplicated,
    _paper_ids_from_args,
    format_report,
    run_rechunk,
)
from contracts.author_orgs import AuthorOrgMatch
from contracts.chunker import Chunk
from contracts.config import Config
from contracts.document_store import ChapterSummary, PaperRecord
from contracts.errors import ContractError
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from contracts.provenance import Block
from rag.chunker import Chunker
from rag.document_store import DocumentStore
from rag.fakes.fake_embedder import FakeEmbedder
from rag.fakes.fake_gpu_lock import FakeGpuLock
from rag.fakes.fake_ingest_state import FakeIngestState
from rag.fakes.fake_vector_store import FakeVectorStore
from rag.orchestrator import IngestionOrchestrator

PAPER_ID = "2506.01234"
TITLE = "Some Paper Title"
SECTION_PATH = "1. Introduction"
PROSE = "Large language models are now real."
BBOX = (0.0, 0.0, 100.0, 200.0)


# --- local factory helpers (same convention as rag/test_document_store.py / rag/test_chunker.py,
# each test file in this codebase owns its own small helpers rather than sharing a fixtures
# module across app/ and rag/) ---------------------------------------------------------------


def _block(index: int = 0, **o) -> Block:
    f = dict(
        block_id=f"{PAPER_ID}:b{index}",
        paper_id=PAPER_ID,
        # The real-world shape of the bug: the parser's block text already opens with the
        # section heading, which `_build_chunk` then prefixes AGAIN via `title\nsection_path`.
        text=f"{SECTION_PATH}\n\n{PROSE}",
        type="prose",
        page=0,
        bbox=BBOX,
        section_path=SECTION_PATH,
        index=index,
    )
    f.update(o)
    return Block(**f)


def _parsed_doc(**o) -> ParsedDoc:
    f = dict(
        paper_id=PAPER_ID,
        markdown=f"# {TITLE}\n\n## {SECTION_PATH}\n\n{PROSE}",
        blocks=[_block()],
        figures=[],
        tables=[],
        references=[],
        parser_id="test-parser-1.x",
    )
    f.update(o)
    return ParsedDoc(**f)


def _paper_ref(**o) -> PaperRef:
    f = dict(
        paper_id=PAPER_ID,
        version="v1",
        title=TITLE,
        abstract="We propose...",
        authors=["A. Author"],
        categories=["cs.LG"],
        published=date(2026, 6, 1),
        updated=date(2026, 6, 1),
        pdf_url="https://arxiv.org/pdf/2506.01234v1",
    )
    f.update(o)
    return PaperRef(**f)


def _config(**o) -> Config:
    f = dict(focus_area_queries=["causal inference"], child_parent_expansion=True)
    f.update(o)
    return Config(**f)


def _duplicated_text(chunk: Chunk, block: Block) -> str:
    """What a pre-157af4d chunker would have produced for `chunk`'s own block -- the exact
    `title\\nsection_path\\n\\n{block.text}` shape `_build_chunk` used before
    `_strip_duplicate_heading` existed, one un-stripped step earlier than `chunk.text`."""
    return f"{TITLE}\n{chunk.section_path}\n\n{block.text}"


def _paper_record(chunks: list[Chunk], **o) -> PaperRecord:
    f = dict(
        ref=_paper_ref(),
        parsed=_parsed_doc(),
        chunks=chunks,
        summary_text="A short summary.",
        summary_id=f"{PAPER_ID}:summary",
        relevance_score=0.5,
    )
    f.update(o)
    return PaperRecord(**f)


def _stale_record(store: DocumentStore, chunker: Chunker) -> tuple[PaperRecord, Chunk]:
    """Puts a paper whose stored chunk carries the T-DOC62 duplicated heading, and returns the
    stored record plus the REAL chunker's own (fixed) chunk for the same block -- what
    `run_rechunk` should produce."""
    parsed = _parsed_doc()
    fixed_chunk = chunker.chunk(parsed)[0]
    stale_chunk = fixed_chunk.model_copy(
        update={"text": _duplicated_text(fixed_chunk, parsed.blocks[0])}
    )
    record = _paper_record([stale_chunk], parsed=parsed)
    store.put(record)
    return record, fixed_chunk


class _SpyVectorStore(FakeVectorStore):
    """Records every `delete`/`upsert` call on top of the real `FakeVectorStore` behavior, so
    tests can assert exactly what was (or, for --dry-run, was NOT) sent to the vector store."""

    def __init__(self):
        super().__init__()
        self.delete_calls: list[list[str]] = []
        self.upsert_ids: list[str] = []

    def delete(self, ids):
        self.delete_calls.append(list(ids))
        super().delete(ids)

    def upsert(self, id, vector, payload):
        self.upsert_ids.append(id)
        super().upsert(id, vector, payload)


class _EmbedderSpy:
    def __init__(self, inner: FakeEmbedder):
        self._inner = inner
        self.embed_calls = 0

    @property
    def info(self):
        return self._inner.info

    def embed(self, texts):
        self.embed_calls += 1
        return self._inner.embed(texts)


@pytest.fixture
def store(tmp_path) -> DocumentStore:
    return DocumentStore(db_path=str(tmp_path / "papers.db"), blob_dir=str(tmp_path / "blobs"))


@pytest.fixture
def chunker() -> Chunker:
    return Chunker(_config())


@pytest.fixture
def vector_store() -> _SpyVectorStore:
    return _SpyVectorStore()


@pytest.fixture
def embedder() -> _EmbedderSpy:
    return _EmbedderSpy(FakeEmbedder(dim=8))


# --------------------------------------------------------------------------------------------
# _is_duplicated -- the same lines[1]-vs-lines[3] measurement the decision doc used
# --------------------------------------------------------------------------------------------


def test_is_duplicated_true_for_repeated_heading():
    text = "Title\n1. Introduction\n\n1. Introduction\n\nBody."
    assert _is_duplicated(text) is True


def test_is_duplicated_false_for_clean_text():
    text = "Title\n1. Introduction\n\nBody that does not repeat the heading."
    assert _is_duplicated(text) is False


def test_is_duplicated_false_for_short_text_with_no_body_line():
    assert _is_duplicated("Title\n1. Introduction\n") is False


# --------------------------------------------------------------------------------------------
# --dry-run: reports richly, writes to neither store
# --------------------------------------------------------------------------------------------


def test_dry_run_writes_to_neither_store(store, chunker, vector_store, embedder):
    record, fixed_chunk = _stale_record(store, chunker)

    results = run_rechunk(
        store, vector_store, embedder, chunker, [PAPER_ID], dry_run=True
    )

    assert vector_store.delete_calls == []
    assert vector_store.upsert_ids == []
    assert embedder.embed_calls == 0
    # SQLite side untouched: get() still returns the ORIGINAL (stale, duplicated) chunk.
    assert store.get(PAPER_ID).chunks == record.chunks

    [result] = results
    assert result == PaperRechunkResult(
        paper_id=PAPER_ID, status="would_rechunk",
        old_chunk_count=1, new_chunk_count=1,
        ids_removed=0, ids_added=0, duplicated_headers_removed=1,
    )


def test_dry_run_report_mentions_duplicate_and_paper_id(store, chunker, vector_store, embedder):
    _stale_record(store, chunker)
    results = run_rechunk(store, vector_store, embedder, chunker, [PAPER_ID], dry_run=True)

    report = format_report(results, dry_run=True)
    assert "DRY RUN" in report
    assert PAPER_ID in report
    assert "1 duplicated header(s) total" in report


# --------------------------------------------------------------------------------------------
# real run: strips the duplicate, syncs vectors
# --------------------------------------------------------------------------------------------


def test_rechunk_strips_duplicate_and_upserts_fixed_text(store, chunker, vector_store, embedder):
    record, fixed_chunk = _stale_record(store, chunker)
    # Pre-seed the vector store with the STALE (duplicated) text, as if a prior real ingest had
    # already embedded it -- the whole point of the vector-sync step is to overwrite this.
    vector_store.upsert(record.chunks[0].chunk_id, [0.0] * 8, {
        "paper_id": PAPER_ID, "kind": "chunk", "section_path": SECTION_PATH,
        "text": record.chunks[0].text, "categories": ["cs.LG"], "published": "2026-06-01",
        "embedding_version": "v1", "doc_type": "paper",
    })

    results = run_rechunk(store, vector_store, embedder, chunker, [PAPER_ID], dry_run=False)

    [result] = results
    assert result.status == "rechunked"
    assert result.duplicated_headers_removed == 1
    # Same chunk_id -- this fix never changes chunk_id (it's purely positional), so nothing was
    # deleted, only re-upserted with corrected text.
    assert result.ids_removed == 0

    stored = store.get(PAPER_ID)
    assert stored.chunks == [fixed_chunk]
    assert not _is_duplicated(stored.chunks[0].text)

    assert fixed_chunk.chunk_id in vector_store.upsert_ids
    _, payload = vector_store._store[fixed_chunk.chunk_id]
    assert payload["text"] == fixed_chunk.text  # stale duplicated text is gone from the vector too


def test_disappeared_chunk_ids_are_deleted_not_left_orphaned(
    store, chunker, vector_store, embedder
):
    """General vector-sync case (not triggered by T-DOC62 itself, since this fix never changes
    chunk_id -- but the tool is built to handle a future chunker change that does): an old chunk
    id with no counterpart in the freshly re-chunked set must be deleted from the vector store,
    never just left upserted-over-with-nothing (the T-DOC23/T-DOC35 orphan shape)."""
    record, fixed_chunk = _stale_record(store, chunker)
    stale_extra = fixed_chunk.model_copy(
        update={"chunk_id": f"{PAPER_ID}:c1", "text": "a chunk that no longer exists after rechunk"}
    )
    store.put(record.model_copy(update={"chunks": [record.chunks[0], stale_extra]}))
    vector_store.upsert(stale_extra.chunk_id, [0.0] * 8, {
        "paper_id": PAPER_ID, "kind": "chunk", "section_path": SECTION_PATH,
        "text": stale_extra.text, "categories": ["cs.LG"], "published": "2026-06-01",
        "embedding_version": "v1", "doc_type": "paper",
    })

    results = run_rechunk(store, vector_store, embedder, chunker, [PAPER_ID], dry_run=False)

    [result] = results
    assert result.ids_removed == 1
    assert vector_store.delete_calls == [[stale_extra.chunk_id]]
    assert stale_extra.chunk_id not in vector_store._store  # actually gone, not just un-referenced
    assert fixed_chunk.chunk_id in vector_store._store


# --------------------------------------------------------------------------------------------
# idempotency / resumability
# --------------------------------------------------------------------------------------------


def test_rerun_over_already_fixed_paper_is_a_noop(store, chunker, vector_store, embedder):
    _stale_record(store, chunker)
    run_rechunk(store, vector_store, embedder, chunker, [PAPER_ID], dry_run=False)
    vector_store.delete_calls.clear()
    vector_store.upsert_ids.clear()
    embedder.embed_calls = 0

    [result] = run_rechunk(store, vector_store, embedder, chunker, [PAPER_ID], dry_run=False)

    assert result.status == "skipped_noop"
    assert vector_store.delete_calls == []
    assert vector_store.upsert_ids == []
    assert embedder.embed_calls == 0


def test_unknown_paper_id_raises_but_leaves_earlier_papers_committed(
    store, chunker, vector_store, embedder
):
    _stale_record(store, chunker)  # only PAPER_ID exists

    with pytest.raises(ContractError, match="unknown paper_id"):
        run_rechunk(
            store, vector_store, embedder, chunker, [PAPER_ID, "does-not-exist"], dry_run=False
        )

    # PAPER_ID's own work already landed before the crash -- not rolled back.
    assert not _is_duplicated(store.get(PAPER_ID).chunks[0].text)
    assert vector_store.upsert_ids  # its vectors were synced too


# --------------------------------------------------------------------------------------------
# put()/get() round trip: only chunks change, everything else -- including chapter summaries --
# survives (the non-negotiable safety requirement)
# --------------------------------------------------------------------------------------------


def test_round_trip_preserves_everything_but_chunks_including_book_chapter_summaries(
    store, chunker, vector_store, embedder
):
    parsed = _parsed_doc()
    fixed_chunk = chunker.chunk(parsed)[0]
    stale_chunk = fixed_chunk.model_copy(
        update={"text": _duplicated_text(fixed_chunk, parsed.blocks[0])}
    )
    chapters = [
        ChapterSummary(
            summary_id=f"{PAPER_ID}:summary:ch0", title="Ch 1", text="chapter one summary"
        ),
        ChapterSummary(
            summary_id=f"{PAPER_ID}:summary:ch1", title="Ch 2", text="chapter two summary"
        ),
    ]
    record = _paper_record(
        [stale_chunk], parsed=parsed, ref=_paper_ref(doc_type="book"),
        chapter_summaries=chapters, summary_text="whole-book summary",
    )
    store.put(record)

    run_rechunk(store, vector_store, embedder, chunker, [PAPER_ID], dry_run=False)

    got = store.get(PAPER_ID)
    assert got.chunks == [fixed_chunk]  # the only thing that changed
    assert got.ref == record.ref
    assert got.summary_text == record.summary_text
    assert got.summary_id == record.summary_id
    assert got.chapter_summaries == chapters
    assert got.parsed.blocks == parsed.blocks
    assert got.parsed.markdown == parsed.markdown
    assert got.relevance_score == record.relevance_score


# --------------------------------------------------------------------------------------------
# RI-3 payload parity: what `run_rechunk` upserts for a paper's chunks must equal, field for
# field, what the ingest-time upsert (`IngestionOrchestrator._upsert_record`) built for the
# same record. The two paths used to be independent payload builders and had already drifted
# (rechunk's copy omitted `author_orgs`/`curated_author_orgs`, so a rechunked paper silently
# dropped out of org-filtered retrieval).
# --------------------------------------------------------------------------------------------


class _OneRefHarvester:
    def __init__(self, ref: PaperRef):
        self._ref = ref

    def harvest(self, focus_area, cap, ordering):
        return iter([self._ref][:cap])


class _StaticParser:
    def __init__(self, parsed: ParsedDoc):
        self._parsed = parsed

    def parse(self, ref: PaperRef) -> ParsedDoc:
        return self._parsed


class _StaticSummarizer:
    def summarize(self, parsed: ParsedDoc, *, kind: str = "paper") -> str:
        return "A short summary."


def _affiliation_parsed_doc() -> ParsedDoc:
    """`_parsed_doc()` plus a front-matter affiliation block, so the ingest path's T-ORG1
    tagging puts a NON-empty `author_orgs` on the record -- the exact fields whose drift RI-3
    is about (a parity test over an all-empty org list could not tell a missing key from [])."""
    affiliation_block = Block(
        block_id=f"{PAPER_ID}:aff",
        paper_id=PAPER_ID,
        text="K. Kusano, Waymo LLC, Mountain View, CA. Correspondence: kusano@waymo.com",
        type="prose",
        page=0,
        bbox=BBOX,
        section_path="",  # front matter -- the extractor's candidate-block signal
        index=0,
    )
    return _parsed_doc(blocks=[affiliation_block, _block(index=1)])


def test_rechunked_chunk_payload_equals_the_ingest_time_payload_field_for_field(
    store, chunker, embedder
):
    # Ingest side: a real `IngestionOrchestrator` drive over the committed fakes (same wiring
    # shape as rag/test_orchestrator.py's Rig; local doubles, per this file's no-shared-fixture
    # convention). Whatever lands in `ingest_vectors` is "the ingest-time payload".
    parsed = _affiliation_parsed_doc()
    ingest_vectors = FakeVectorStore()
    IngestionOrchestrator(
        harvester=_OneRefHarvester(_paper_ref()),
        parser=_StaticParser(parsed),
        chunker=chunker,
        summarizer=_StaticSummarizer(),
        embedder=embedder,
        document_store=store,
        vector_index=ingest_vectors,
        state=FakeIngestState(),
        gpu_lock=FakeGpuLock(),
        config=_config(),
    ).ingest(["causal inference"], cap=1)

    stored = store.get(PAPER_ID)
    assert stored.author_orgs == [AuthorOrgMatch(name="Waymo", method="email_domain")]
    fixed_chunks = stored.chunks
    assert len(fixed_chunks) == 2  # front matter + prose -- both points get parity-checked
    for chunk in fixed_chunks:
        _, payload = ingest_vectors._store[chunk.chunk_id]
        assert payload["author_orgs"] == ["Waymo"]
        assert payload["curated_author_orgs"] == []

    # Rechunk side: the same stored record with one chunk's text staled back to the
    # pre-157af4d duplicated-heading shape, so `run_rechunk` has real work to do; its upserts
    # go to a fresh store, standing in for the points being rewritten in place.
    staled = fixed_chunks[1].model_copy(
        update={"text": _duplicated_text(fixed_chunks[1], parsed.blocks[1])}
    )
    store.put(stored.model_copy(update={"chunks": [fixed_chunks[0], staled]}))
    rechunk_vectors = FakeVectorStore()
    [result] = run_rechunk(store, rechunk_vectors, embedder, chunker, [PAPER_ID], dry_run=False)
    assert result.status == "rechunked"

    assert set(rechunk_vectors._store) == {c.chunk_id for c in fixed_chunks}
    for chunk in fixed_chunks:
        _, ingest_payload = ingest_vectors._store[chunk.chunk_id]
        _, rechunk_payload = rechunk_vectors._store[chunk.chunk_id]
        assert rechunk_payload == ingest_payload  # dict equality: keys AND values, field for field


# --------------------------------------------------------------------------------------------
# Anchors (T-DOC62 design doc risk #1): _strip_duplicate_heading changes chunk TEXT, but Anchor
# is block-level (paper_id/block_id/page/bbox/section_path), never derived from character
# offsets into that text -- so it cannot be moved by this migration. Verified two ways.
# --------------------------------------------------------------------------------------------


def test_anchor_is_unchanged_by_the_strip(store, chunker):
    record, fixed_chunk = _stale_record(store, chunker)
    assert fixed_chunk.anchor == record.chunks[0].anchor


def test_get_span_resolves_correctly_after_rechunk(store, chunker, vector_store, embedder):
    _stale_record(store, chunker)
    run_rechunk(store, vector_store, embedder, chunker, [PAPER_ID], dry_run=False)

    got = store.get(PAPER_ID)
    [chunk] = got.chunks
    span = store.get_span(chunk.anchor)
    # get_span resolves the FULL source block, independent of anything chunk.text does --
    # confirms re-chunking cannot desync an anchor from its block.
    assert span == store.get_block(chunk.anchor.block_id).text
    assert span == _block().text


# --------------------------------------------------------------------------------------------
# CLI arg parsing
# --------------------------------------------------------------------------------------------


def test_paper_ids_from_args_comma_separated():
    class _Args:
        paper_ids = "a, b ,c"
        paper_ids_file = None

    assert _paper_ids_from_args(_Args()) == ["a", "b", "c"]


def test_paper_ids_from_args_requires_one_source():
    class _Args:
        paper_ids = None
        paper_ids_file = None

    with pytest.raises(ContractError, match="one of --paper-ids"):
        _paper_ids_from_args(_Args())
