# M1A-DORMANT (re-enable in M1b): skips until rag/document_store.py exists.
# M1b DoD (CONVENTIONS §11) requires this suite active (importorskip resolves) and green.
"""M5 DocumentStore test suite (T-D1), written test-first against the FROZEN interface
(DATA-CONTRACTS.md §M5 + SQLite schema, TEST-STRATEGY.md "DocumentStore").

`rag.document_store` does not exist yet — `pytest.importorskip` below skips this whole file until
M1b lands the implementation, keeping CI green in the meantime (CONVENTIONS §0.7 / M1a convention).

Assumed constructor (the seam this suite defines for M1b): `DocumentStore(db_path, blob_dir)` — a
SQLite file plus a filesystem root for blob paths the schema stores but `PaperRecord` doesn't carry
(`papers.pdf_path`/`markdown_path`). Tests never assert on those synthesized paths.

Round-trip note: the V0 schema is a deliberate *projection* of the rich contract objects (no
`parser_id`/`figures`/`tables`/`markdown`-text columns), so full pydantic `PaperRecord` equality is
not implementable and is NOT asserted. Instead each schema-backed field is checked directly — that
is what "round-trips a whole PaperRecord" means against this schema.
"""

import sqlite3
from datetime import date

import pytest

_mod = pytest.importorskip("rag.document_store")

from contracts.chunker import Chunk  # noqa: E402  (imports follow importorskip, per M1a convention)
from contracts.document_store import PaperRecord  # noqa: E402
from contracts.errors import ContractError  # noqa: E402
from contracts.harvester import PaperRef  # noqa: E402
from contracts.parser import ParsedDoc  # noqa: E402
from contracts.provenance import Anchor, Block  # noqa: E402

PAPER_ID = "2506.01234"
BBOX = (0.0, 0.0, 100.0, 200.0)


# --- local factory helpers (contracts/conftest.py fixtures are scoped to contracts/, not rag/) ---


def make_block(**o) -> Block:
    f = dict(
        block_id=f"{PAPER_ID}:b0",
        paper_id=PAPER_ID,
        text="Some prose.",
        type="prose",
        page=0,
        bbox=BBOX,
        section_path="3. Method",
        index=0,
    )
    f.update(o)
    return Block(**f)


def make_anchor(**o) -> Anchor:
    f = dict(
        paper_id=PAPER_ID,
        block_id=f"{PAPER_ID}:b0",
        page=0,
        bbox=BBOX,
        snippet="Some verbatim text.",
        section_path="3. Method",
    )
    f.update(o)
    return Anchor(**f)


def make_chunk(**o) -> Chunk:
    f = dict(
        chunk_id=f"{PAPER_ID}:c0",
        paper_id=PAPER_ID,
        text="Some chunk text.",
        anchor=make_anchor(),
        section_path="3. Method",
        parent_id=f"{PAPER_ID}:b0",
    )
    f.update(o)
    return Chunk(**f)


def make_paper_ref(**o) -> PaperRef:
    f = dict(
        paper_id=PAPER_ID,
        version="v1",
        title="A Causal Method",
        abstract="We propose...",
        authors=["A. Author", "B. Author"],
        categories=["cs.LG", "stat.ME"],
        published=date(2026, 6, 1),
        updated=date(2026, 6, 1),
        pdf_url="https://arxiv.org/pdf/2506.01234v1",
    )
    f.update(o)
    return PaperRef(**f)


def make_parsed_doc(**o) -> ParsedDoc:
    f = dict(
        paper_id=PAPER_ID,
        markdown="# Title",
        blocks=[make_block()],
        figures=[],
        tables=[],
        references=[],
        parser_id="test-parser-1.x",
    )
    f.update(o)
    return ParsedDoc(**f)


def make_paper_record(**o) -> PaperRecord:
    f = dict(
        ref=make_paper_ref(),
        parsed=make_parsed_doc(),
        chunks=[make_chunk()],
        summary_text="A short summary.",
        summary_id=f"{PAPER_ID}:summary",
        relevance_score=0.42,
    )
    f.update(o)
    return PaperRecord(**f)


@pytest.fixture
def store(tmp_path):
    return _mod.DocumentStore(
        db_path=str(tmp_path / "store.db"), blob_dir=str(tmp_path / "blobs")
    )


def _by_id(items, key):
    return {getattr(i, key): i for i in items}


# --------------------------------------------------------------------------------------------------
# put -> get round-trip (whole record, incl. relevance_score)
# --------------------------------------------------------------------------------------------------


def test_put_get_round_trips_whole_record(store):
    record = make_paper_record()
    store.put(record)
    got = store.get(PAPER_ID)

    assert got is not None
    # ref core fields (schema-backed columns on `papers`)
    assert got.ref.paper_id == record.ref.paper_id
    assert got.ref.version == record.ref.version
    assert got.ref.title == record.ref.title
    assert got.ref.abstract == record.ref.abstract
    assert got.ref.authors == record.ref.authors
    assert got.ref.categories == record.ref.categories
    assert got.ref.published == record.ref.published
    assert got.ref.updated == record.ref.updated
    # summary + chunks + blocks (each has its own table holding every field)
    assert got.summary_text == record.summary_text
    assert got.summary_id == record.summary_id
    assert _by_id(got.chunks, "chunk_id") == _by_id(record.chunks, "chunk_id")
    assert _by_id(got.parsed.blocks, "block_id") == _by_id(record.parsed.blocks, "block_id")


def test_put_get_round_trips_relevance_score(store):
    # Explicit: relevance_score is the AUTHORITATIVE value on PaperRecord (DATA-CONTRACTS §M5) and
    # must survive the round-trip — a store that drops it into papers.relevance_score=NULL fails.
    store.put(make_paper_record(relevance_score=0.7314))
    assert store.get(PAPER_ID).relevance_score == pytest.approx(0.7314)


def test_get_unknown_paper_returns_none(store):
    assert store.get("9999.99999") is None


# --------------------------------------------------------------------------------------------------
# atomicity — a mid-put failure leaves ZERO rows (proven via a fresh connection, not just no-raise)
# --------------------------------------------------------------------------------------------------


def test_put_is_atomic_across_all_four_tables(tmp_path):
    db_path = str(tmp_path / "store.db")
    store = _mod.DocumentStore(db_path=db_path, blob_dir=str(tmp_path / "blobs"))

    # Inject a failure that fires DURING the chunks insert, AFTER papers+blocks are written: two
    # chunks share one chunk_id, so the second violates the chunks PRIMARY KEY. This is a
    # data-driven injection (sqlite3.Connection is a C type and can't be monkeypatched).
    record = make_paper_record(
        chunks=[make_chunk(chunk_id=f"{PAPER_ID}:c0"), make_chunk(chunk_id=f"{PAPER_ID}:c0")]
    )
    with pytest.raises((sqlite3.IntegrityError, ContractError)):
        store.put(record)

    # Fresh connection (bypasses any in-object caching): the whole put() must have rolled back.
    con = sqlite3.connect(db_path)
    try:
        for table in ("papers", "blocks", "chunks", "summaries"):
            (count,) = con.execute(
                f"SELECT count(*) FROM {table} WHERE paper_id = ?", (PAPER_ID,)
            ).fetchone()
            assert count == 0, f"{table} still holds rows for {PAPER_ID}: put() was not atomic"
    finally:
        con.close()


# --------------------------------------------------------------------------------------------------
# idempotency under CHANGED content — a re-put replaces, it does not silently no-op
# --------------------------------------------------------------------------------------------------


def test_put_is_idempotent_and_reflects_new_content(store):
    store.put(make_paper_record(summary_text="old summary", relevance_score=0.1))

    changed = make_paper_record(
        summary_text="new summary",
        relevance_score=0.9,
        chunks=[make_chunk(text="new chunk text")],
    )
    store.put(changed)  # same paper_id, different content

    got = store.get(PAPER_ID)
    # The NEW content wins (a buggy silent no-op ignoring the second put would still show "old").
    assert got.summary_text == "new summary"
    assert got.relevance_score == pytest.approx(0.9)
    assert [c.text for c in got.chunks] == ["new chunk text"]
    # And there is exactly one paper — re-put upserts, never duplicates.
    assert sum(1 for _ in store.iter_papers()) == 1


# --------------------------------------------------------------------------------------------------
# get_span — resolves anchor.block_id to the FULL Block.text, not the shorter Anchor.snippet
# --------------------------------------------------------------------------------------------------


def test_get_span_returns_full_block_text_not_snippet(store):
    long_text = "word " * 60  # 300 chars — longer than the ~200-char snippet
    assert len(long_text) > 200
    block = make_block(block_id=f"{PAPER_ID}:b0", text=long_text)
    anchor = make_anchor(block_id=f"{PAPER_ID}:b0", snippet=long_text[:200])
    store.put(
        make_paper_record(
            parsed=make_parsed_doc(blocks=[block]),
            chunks=[make_chunk(anchor=anchor)],
        )
    )

    span = store.get_span(anchor)
    assert span == long_text  # full block text
    assert span != anchor.snippet  # NOT the truncated snippet (fails a snippet-returning impl)
    assert anchor.snippet in span  # snippet is a verbatim substring of the full text


# --------------------------------------------------------------------------------------------------
# get_block / get_chunk / get_summary / get_blocks — resolve, and raise ContractError on unknown ids
# --------------------------------------------------------------------------------------------------


def test_get_block_resolves_and_raises_on_unknown(store):
    store.put(make_paper_record())
    assert store.get_block(f"{PAPER_ID}:b0").block_id == f"{PAPER_ID}:b0"
    with pytest.raises(ContractError):
        store.get_block("2506.01234:b999")


def test_get_chunk_resolves_and_raises_on_unknown(store):
    store.put(make_paper_record())
    assert store.get_chunk(f"{PAPER_ID}:c0").chunk_id == f"{PAPER_ID}:c0"
    with pytest.raises(ContractError):
        store.get_chunk("2506.01234:c999")


def test_get_summary_resolves_and_raises_on_unknown(store):
    store.put(make_paper_record(summary_text="the summary body"))
    assert store.get_summary(f"{PAPER_ID}:summary") == "the summary body"
    with pytest.raises(ContractError):
        store.get_summary("2506.01234:summary-nope")


def test_get_blocks_returns_all_blocks_for_paper(store):
    blocks = [
        make_block(block_id=f"{PAPER_ID}:b0", index=0),
        make_block(block_id=f"{PAPER_ID}:b1", index=1, text="second block"),
    ]
    store.put(make_paper_record(parsed=make_parsed_doc(blocks=blocks)))
    assert _by_id(store.get_blocks(PAPER_ID), "block_id") == _by_id(blocks, "block_id")


# --------------------------------------------------------------------------------------------------
# iter_papers — yields every stored record (VectorIndex.rebuild()'s source)
# --------------------------------------------------------------------------------------------------


def test_iter_papers_yields_all_stored_papers(store):
    store.put(make_paper_record())
    other = "2507.55555"
    other_block = make_block(block_id=f"{other}:b0", paper_id=other)
    other_anchor = make_anchor(paper_id=other, block_id=f"{other}:b0")
    other_chunk = make_chunk(
        chunk_id=f"{other}:c0", paper_id=other, parent_id=f"{other}:b0", anchor=other_anchor
    )
    store.put(
        make_paper_record(
            ref=make_paper_ref(paper_id=other),
            parsed=make_parsed_doc(paper_id=other, blocks=[other_block]),
            chunks=[other_chunk],
            summary_id=f"{other}:summary",
        )
    )
    assert {r.ref.paper_id for r in store.iter_papers()} == {PAPER_ID, other}
