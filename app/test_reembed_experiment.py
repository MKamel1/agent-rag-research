"""T-DOC41 (Contextual Retrieval spike) — `app/reembed_experiment.py` test suite. Zero-GPU,
zero-network (TEST-STRATEGY.md golden rule): drives the pure `reembed()` function with
`rag.fakes.FakeEmbedder`/`FakeVectorStore` plus a small local fake header generator and fake
document store over 2-3 synthetic papers -- no real HTTP client, no real vector-store server, no
GPU.

`reembed()` (not `__main__`) is the unit under test: the real composition in `__main__` builds a
real `VectorIndex`, which makes a live network call in its own constructor
(`_ensure_collection()`), so it is deliberately NOT exercised here -- same "compose real adapters
only at the very edge, test the logic against fakes" split `app/parse_phase.py`'s own
`_run_parse_phase`/`__main__` split follows.
"""

from datetime import date

import pytest

from app.reembed_experiment import (
    ReembedError,
    _check_collection_is_not_production,
    _paper_ids_from_args,
    _write_headers_out,
    reembed,
)
from contracts.chunker import Chunk
from contracts.document_store import PaperRecord
from contracts.errors import PermanentError
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor
from rag.fakes.fake_embedder import FakeEmbedder
from rag.fakes.fake_vector_store import FakeVectorStore

_BBOX = (0.0, 0.0, 100.0, 200.0)


def _make_ref(paper_id: str, **overrides) -> PaperRef:
    fields = dict(
        paper_id=paper_id,
        version="v1",
        title=f"Paper {paper_id}",
        abstract="We propose...",
        authors=["A. Author"],
        categories=["cs.LG"],
        published=date(2026, 6, 1),
        updated=date(2026, 6, 1),
        pdf_url=f"https://arxiv.org/pdf/{paper_id}v1",
    )
    fields.update(overrides)
    return PaperRef(**fields)


def _make_chunk(paper_id: str, index: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"{paper_id}:c{index}",
        paper_id=paper_id,
        text=text,
        anchor=Anchor(
            paper_id=paper_id,
            block_id=f"{paper_id}:b{index}",
            page=0,
            bbox=_BBOX,
            snippet=text[:50],
            section_path="3. Method",
        ),
        section_path="3. Method",
        parent_id=f"{paper_id}:b{index}",
    )


def _make_record(
    paper_id: str, n_chunks: int = 2, summary_text: str = "A short summary."
) -> PaperRecord:
    chunks = [
        _make_chunk(paper_id, i, f"Chunk {i} text for {paper_id}.") for i in range(n_chunks)
    ]
    return PaperRecord(
        ref=_make_ref(paper_id),
        parsed=ParsedDoc(
            paper_id=paper_id, markdown="# Title", blocks=[], figures=[], tables=[],
            references=[], parser_id="test-parser-1.x",
        ),
        chunks=chunks,
        summary_text=summary_text,
        summary_id=f"{paper_id}:summary",
    )


class _FakeDocumentStore:
    """Minimal stand-in for `rag.document_store.DocumentStore.get()` -- an in-memory dict, no
    SQLite, no filesystem. `reembed()` only ever calls `.get()` (never `put()`/`delete()`), so
    that's the only method this fake needs.
    """

    def __init__(self, records: dict[str, PaperRecord]):
        self._records = records

    def get(self, paper_id: str) -> PaperRecord | None:
        return self._records.get(paper_id)


class _FakeHeaderGenerator:
    """Deterministic: header text is derived from the chunk text, so a test can assert the
    embed-text's prefix without depending on any real generation-LLM response shape.
    """

    def __init__(self, *, fail_for: set[str] | None = None):
        self.calls: list[tuple[str, str]] = []
        self._fail_for = fail_for or set()

    def generate(self, summary_text: str, chunk_text: str) -> str:
        self.calls.append((summary_text, chunk_text))
        if chunk_text in self._fail_for:
            raise PermanentError(f"synthetic failure for: {chunk_text!r}")
        return f"HEADER({chunk_text[:12]})"


PAPER_IDS = ["2601.00001", "2601.00002", "2601.00003"]


def _records() -> dict[str, PaperRecord]:
    return {pid: _make_record(pid) for pid in PAPER_IDS}


# ---------------------------------------------------------------------------
# Matched A/B: same paper set -> same chunk_ids upserted, regardless of --with-headers
# ---------------------------------------------------------------------------


def test_baseline_and_headered_runs_upsert_the_identical_chunk_id_set():
    records = _records()

    baseline_store = FakeVectorStore()
    reembed(
        document_store=_FakeDocumentStore(records),
        embedder=FakeEmbedder(),
        vector_index=baseline_store,
        header_generator=None,
        paper_ids=PAPER_IDS,
        with_headers=False,
    )

    headered_store = FakeVectorStore()
    reembed(
        document_store=_FakeDocumentStore(records),
        embedder=FakeEmbedder(),
        vector_index=headered_store,
        header_generator=_FakeHeaderGenerator(),
        paper_ids=PAPER_IDS,
        with_headers=True,
    )

    expected_ids = {c.chunk_id for pid in PAPER_IDS for c in records[pid].chunks}
    assert set(baseline_store._store.keys()) == expected_ids
    assert set(headered_store._store.keys()) == expected_ids
    assert len(expected_ids) == len(PAPER_IDS) * 2  # sanity: 2 chunks/paper, no dedup surprises


# ---------------------------------------------------------------------------
# Embed-text content: baseline unchanged, headered = header + "\n\n" + original text
# ---------------------------------------------------------------------------


def test_baseline_embed_text_equals_the_chunks_own_unmodified_text():
    records = {"2601.00001": _make_record("2601.00001", n_chunks=1)}
    embedder = FakeEmbedder()
    store = FakeVectorStore()

    reembed(
        document_store=_FakeDocumentStore(records),
        embedder=embedder,
        vector_index=store,
        header_generator=None,
        paper_ids=["2601.00001"],
        with_headers=False,
    )

    original_text = records["2601.00001"].chunks[0].text
    chunk_id = records["2601.00001"].chunks[0].chunk_id
    # FakeEmbedder is a deterministic hash-of-text -> vector; the fake vector store round-trips
    # whatever was upserted, so recomputing the embedder's own output on the ORIGINAL text and
    # comparing vectors proves the text handed to embed() was the original, unmodified text.
    expected_vector = embedder.embed([original_text])[0]
    stored_vector, stored_payload = store._store[chunk_id]
    assert stored_vector == expected_vector
    assert stored_payload["text"] == original_text


def test_headered_embed_text_starts_with_the_header_then_the_original_text():
    records = {"2601.00001": _make_record("2601.00001", n_chunks=1)}
    embedder = FakeEmbedder()
    store = FakeVectorStore()
    header_gen = _FakeHeaderGenerator()

    reembed(
        document_store=_FakeDocumentStore(records),
        embedder=embedder,
        vector_index=store,
        header_generator=header_gen,
        paper_ids=["2601.00001"],
        with_headers=True,
    )

    chunk = records["2601.00001"].chunks[0]
    expected_header = f"HEADER({chunk.text[:12]})"
    expected_embed_text = f"{expected_header}\n\n{chunk.text}"
    expected_vector = embedder.embed([expected_embed_text])[0]

    stored_vector, stored_payload = store._store[chunk.chunk_id]
    assert stored_vector == expected_vector
    # Payload's own `text` field stays the ORIGINAL passage (sparse channel parity between arms,
    # module docstring) even though the DENSE vector above was computed from the headered text.
    assert stored_payload["text"] == chunk.text


def test_a_chunk_whose_header_generation_fails_still_gets_embedded_with_its_own_text():
    chunk = _make_chunk("2601.00001", 0, "A failing chunk.")
    record = PaperRecord(
        ref=_make_ref("2601.00001"),
        parsed=ParsedDoc(
            paper_id="2601.00001", markdown="# T", blocks=[], figures=[], tables=[],
            references=[], parser_id="test-parser-1.x",
        ),
        chunks=[chunk],
        summary_text="A summary.",
        summary_id="2601.00001:summary",
    )
    header_gen = _FakeHeaderGenerator(fail_for={chunk.text})

    headers = reembed(
        document_store=_FakeDocumentStore({"2601.00001": record}),
        embedder=FakeEmbedder(),
        vector_index=FakeVectorStore(),
        header_generator=header_gen,
        paper_ids=["2601.00001"],
        with_headers=True,
    )

    assert chunk.chunk_id not in headers


# ---------------------------------------------------------------------------
# Headers recorded: reembed()'s return value + _write_headers_out
# ---------------------------------------------------------------------------


def test_headers_dict_has_one_entry_per_chunk_and_is_empty_in_baseline_mode():
    records = _records()

    headered_headers = reembed(
        document_store=_FakeDocumentStore(records),
        embedder=FakeEmbedder(),
        vector_index=FakeVectorStore(),
        header_generator=_FakeHeaderGenerator(),
        paper_ids=PAPER_IDS,
        with_headers=True,
    )
    expected_ids = {c.chunk_id for pid in PAPER_IDS for c in records[pid].chunks}
    assert set(headered_headers.keys()) == expected_ids

    baseline_headers = reembed(
        document_store=_FakeDocumentStore(records),
        embedder=FakeEmbedder(),
        vector_index=FakeVectorStore(),
        header_generator=None,
        paper_ids=PAPER_IDS,
        with_headers=False,
    )
    assert baseline_headers == {}


def test_write_headers_out_writes_json_when_path_given(tmp_path):
    out_path = tmp_path / "headers.json"
    _write_headers_out(str(out_path), {"2601.00001:c0": "A header."})
    assert out_path.read_text() == '{\n  "2601.00001:c0": "A header."\n}'


def test_write_headers_out_is_a_noop_when_path_is_none(tmp_path):
    # No path -> no file, no exception -- covers the --no-headers-out CLI default.
    _write_headers_out(None, {"x": "y"})


# ---------------------------------------------------------------------------
# Precondition failures: refuse to run rather than silently produce a mismatched corpus
# ---------------------------------------------------------------------------


def test_unknown_paper_id_raises_reembed_error():
    with pytest.raises(ReembedError):
        reembed(
            document_store=_FakeDocumentStore({}),
            embedder=FakeEmbedder(),
            vector_index=FakeVectorStore(),
            header_generator=None,
            paper_ids=["nonexistent"],
            with_headers=False,
        )


def test_with_headers_true_requires_a_header_generator():
    with pytest.raises(ReembedError):
        reembed(
            document_store=_FakeDocumentStore(_records()),
            embedder=FakeEmbedder(),
            vector_index=FakeVectorStore(),
            header_generator=None,
            paper_ids=PAPER_IDS,
            with_headers=True,
        )


def test_check_collection_is_not_production_rejects_the_live_collection_name():
    with pytest.raises(ReembedError):
        _check_collection_is_not_production("papers", "papers")
    _check_collection_is_not_production("papers-header-experiment", "papers")  # does not raise


# ---------------------------------------------------------------------------
# --paper-ids / --paper-ids-file parsing
# ---------------------------------------------------------------------------


class _Args:
    def __init__(self, paper_ids=None, paper_ids_file=None):
        self.paper_ids = paper_ids
        self.paper_ids_file = paper_ids_file


def test_paper_ids_from_comma_separated_arg():
    assert _paper_ids_from_args(_Args(paper_ids="2601.00001, 2601.00002,2601.00003")) == [
        "2601.00001",
        "2601.00002",
        "2601.00003",
    ]


def test_paper_ids_from_file(tmp_path):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("2601.00001\n2601.00002\n\n2601.00003\n")
    assert _paper_ids_from_args(_Args(paper_ids_file=str(ids_file))) == [
        "2601.00001",
        "2601.00002",
        "2601.00003",
    ]


def test_paper_ids_missing_both_raises():
    with pytest.raises(ReembedError):
        _paper_ids_from_args(_Args())
