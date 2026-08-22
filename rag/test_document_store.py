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

import concurrent.futures
import sqlite3
from datetime import date
from pathlib import Path

import pytest

_mod = pytest.importorskip("rag.document_store")

from contracts.author_orgs import AuthorOrgMatch  # noqa: E402
from contracts.chunker import Chunk  # noqa: E402  (imports follow importorskip, per M1a convention)
from contracts.document_store import ChapterSummary, PaperRecord  # noqa: E402
from contracts.errors import ContractError  # noqa: E402
from contracts.harvester import PaperRef  # noqa: E402
from contracts.parser import Figure, ParsedDoc, TableItem  # noqa: E402
from contracts.provenance import Anchor, Block  # noqa: E402

PAPER_ID = "2506.01234"
BBOX = (0.0, 0.0, 100.0, 200.0)
# T-DOC81 review fixes below build DBs at older schema versions by applying the real migration
# files directly with sqlite3 (bypassing migrate()) -- never a real database, always tmp_path.
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


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


def make_figure(**o) -> Figure:
    f = dict(
        paper_id=PAPER_ID,
        image_path="/blobs/figures/2506.01234/fig0.png",
        caption="Figure 1: An illustration.",
        page=0,
        bbox=BBOX,
    )
    f.update(o)
    return Figure(**f)


def make_table_item(**o) -> TableItem:
    f = dict(
        paper_id=PAPER_ID,
        markdown="| a | b |\n|---|---|\n| 1 | 2 |",
        caption="Table 1: Results.",
        page=0,
        bbox=BBOX,
    )
    f.update(o)
    return TableItem(**f)


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
# figures / tables (RI-18, migration 0006) — persisted, not thrown away at the storage boundary
# --------------------------------------------------------------------------------------------------


def test_put_get_round_trips_figures_and_tables(store):
    figures = [
        make_figure(image_path="/blobs/figures/2506.01234/fig0.png", caption="Fig 1", page=0),
        make_figure(image_path="/blobs/figures/2506.01234/fig1.png", caption="Fig 2", page=1),
    ]
    tables = [make_table_item(markdown="| x |\n|---|\n| 1 |", caption="Table 1", page=2)]
    record = make_paper_record(
        parsed=make_parsed_doc(figures=figures, tables=tables)
    )
    store.put(record)
    got = store.get(PAPER_ID)

    assert got.parsed.figures == figures, "figures must survive put()/get() field-for-field"
    assert got.parsed.tables == tables, "tables must survive put()/get() field-for-field"


def test_put_get_round_trips_empty_figures_and_tables(store):
    # The common case: a paper with no figures/tables at all -- must round-trip as [], not None.
    store.put(make_paper_record())
    got = store.get(PAPER_ID)

    assert got.parsed.figures == []
    assert got.parsed.tables == []


def test_put_get_figure_vlm_description_is_always_none(store):
    # contracts/parser.py's Figure: vlm_description is ALWAYS None in V0 -- put() must not invent
    # a value, and get() must read back exactly None, never an empty string or sentinel.
    store.put(make_paper_record(parsed=make_parsed_doc(figures=[make_figure()])))
    got = store.get(PAPER_ID)

    assert got.parsed.figures[0].vlm_description is None


def test_put_is_idempotent_for_figures_and_tables(store):
    store.put(make_paper_record(parsed=make_parsed_doc(figures=[make_figure(caption="old")])))
    store.put(make_paper_record(parsed=make_parsed_doc(figures=[make_figure(caption="new")])))

    got = store.get(PAPER_ID)
    assert [f.caption for f in got.parsed.figures] == ["new"], (
        "re-put must replace figures, not accumulate them (delete-then-insert, like blocks/chunks)"
    )


def test_markdown_blob_readable_after_a_relative_blob_dir_and_a_cwd_change(tmp_path, monkeypatch):
    # Real bug (T-DOC22): a relative `blob_dir` (production's own default, "blobs") used to get
    # written verbatim into `papers.markdown_path`, so `get()` from a *different* process/cwd than
    # the one that ran `put()` raised ContractError on a perfectly intact blob -- 96/145 T-EVAL
    # retrieval calls failed exactly this way. `DocumentStore.__init__` must resolve `blob_dir` to
    # an absolute path up front so the stored path is cwd-independent from then on.
    monkeypatch.chdir(tmp_path)
    store = _mod.DocumentStore(db_path=str(tmp_path / "store.db"), blob_dir="blobs")
    store.put(make_paper_record())

    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")

    got = store.get(PAPER_ID)
    assert got is not None
    assert got.parsed.markdown == make_parsed_doc().markdown


# --------------------------------------------------------------------------------------------------
# atomicity — a mid-put failure leaves ZERO rows (proven via a fresh connection, not just no-raise)
# --------------------------------------------------------------------------------------------------


def test_put_is_atomic_across_all_six_tables(tmp_path):
    db_path = str(tmp_path / "store.db")
    store = _mod.DocumentStore(db_path=db_path, blob_dir=str(tmp_path / "blobs"))

    # Inject a failure that fires DURING the chunks insert, AFTER papers+blocks+figures+tables are
    # written: two chunks share one chunk_id, so the second violates the chunks PRIMARY KEY. This
    # is a data-driven injection (sqlite3.Connection is a C type and can't be monkeypatched).
    record = make_paper_record(
        parsed=make_parsed_doc(figures=[make_figure()], tables=[make_table_item()]),
        chunks=[make_chunk(chunk_id=f"{PAPER_ID}:c0"), make_chunk(chunk_id=f"{PAPER_ID}:c0")],
    )
    with pytest.raises((sqlite3.IntegrityError, ContractError)):
        store.put(record)

    # Fresh connection (bypasses any in-object caching): the whole put() must have rolled back.
    con = sqlite3.connect(db_path)
    try:
        for table in ("papers", "blocks", "chunks", "summaries", "figures", "tables"):
            (count,) = con.execute(
                f"SELECT count(*) FROM {table} WHERE paper_id = ?", (PAPER_ID,)
            ).fetchone()
            assert count == 0, f"{table} still holds rows for {PAPER_ID}: put() was not atomic"
    finally:
        con.close()


def test_put_failure_on_reput_leaves_prior_blob_untouched(store):
    # The blob write is NOT inside the SQL transaction (it's a filesystem write), so it has to be
    # made atomic by hand: a failed re-put must not leave the OLD db row paired with the NEW
    # (should-be-rolled-back) markdown text on disk — that torn read is exactly the bug this test
    # guards against.
    store.put(make_paper_record())  # good initial put — "old" markdown is "# Title"

    # Same injection as test_put_is_atomic_across_all_four_tables: fails mid-transaction, AFTER
    # the blob for the new content would already have been written under the old (buggy) impl.
    bad_record = make_paper_record(
        parsed=make_parsed_doc(markdown="# NEW CONTENT THAT SHOULD NEVER BE VISIBLE"),
        chunks=[make_chunk(chunk_id=f"{PAPER_ID}:c0"), make_chunk(chunk_id=f"{PAPER_ID}:c0")],
    )
    with pytest.raises((sqlite3.IntegrityError, ContractError)):
        store.put(bad_record)

    # get() must still return the PRIOR good markdown, not the failed put's content.
    got = store.get(PAPER_ID)
    assert got.parsed.markdown == "# Title"
    assert "NEW CONTENT" not in got.parsed.markdown


def test_blob_staging_never_touches_another_writers_temp_file(tmp_path):
    """RI-21: the blob write used to stage through the FIXED name `<paper_id>.md.tmp` -- two
    concurrent ingests of the same paper shared that path, so one truncated the other's partial
    write and whichever publish landed second installed an interleaved blob (or died on a temp
    already moved away). The shared helper stages pid-qualified (`rag.atomic_write`), so another
    writer's staged temp -- materialized here as a foreign file at the old fixed name -- must
    survive our put byte-for-byte, and the real blob must land with OUR content, not theirs."""
    store = _mod.DocumentStore(
        db_path=str(tmp_path / "store.db"), blob_dir=str(tmp_path / "blobs")
    )
    stale_tmp = tmp_path / "blobs" / f"{PAPER_ID}.md.tmp"
    stale_tmp.write_text("another ingest's partial markdown")

    store.put(make_paper_record(parsed=make_parsed_doc(markdown="# real content")))

    assert stale_tmp.read_text() == "another ingest's partial markdown"
    assert (tmp_path / "blobs" / f"{PAPER_ID}.md").read_text() == "# real content"


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


# --------------------------------------------------------------------------------------------------
# raw_affiliations / author_orgs (T-ORG1, migration 0005) — evidence + which signal matched
# --------------------------------------------------------------------------------------------------


def test_put_get_round_trips_raw_affiliations_and_author_orgs(store):
    record = make_paper_record(
        raw_affiliations=["Waymo LLC, Mountain View, CA", "kusano@waymo.com"],
        author_orgs=[AuthorOrgMatch(name="Waymo", method="email_domain")],
    )
    store.put(record)
    got = store.get(PAPER_ID)

    assert got.raw_affiliations == ["Waymo LLC, Mountain View, CA", "kusano@waymo.com"]
    assert got.author_orgs == [AuthorOrgMatch(name="Waymo", method="email_domain")]


def test_put_get_round_trips_curated_method(store):
    # T-ORG3: "curated" needs no schema change (author_orgs is already a JSON TEXT column,
    # migrations/0005_author_orgs.sql) -- this is a pure Literal-widening round-trip proof.
    record = make_paper_record(
        author_orgs=[AuthorOrgMatch(name="Waymo", method="curated")],
    )
    store.put(record)
    got = store.get(PAPER_ID)

    assert got.author_orgs == [AuthorOrgMatch(name="Waymo", method="curated")]


def test_put_get_round_trips_empty_raw_affiliations_and_author_orgs(store):
    # The common case: no candidate affiliation text found at all. Empty list, not None/missing --
    # a store that round-trips NULL as something other than [] breaks PaperRecord's own contract
    # (raw_affiliations: list[str] = Field(default_factory=list)).
    record = make_paper_record()
    store.put(record)
    got = store.get(PAPER_ID)

    assert got.raw_affiliations == []
    assert got.author_orgs == []


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


# --------------------------------------------------------------------------------------------------
# delete — cascade removal by paper_id (T-DOC23)
# --------------------------------------------------------------------------------------------------


def test_delete_removes_rows_from_all_six_tables_and_the_blob(tmp_path):
    # RI-18/T-DOC40 FK trap: figures/tables also REFERENCES papers(paper_id) (migration 0006), and
    # PRAGMA foreign_keys=ON is enabled on this connection -- if delete() didn't also delete these
    # two child tables before the parent papers row, a paper with any figures/tables would raise
    # sqlite3.IntegrityError on delete() instead of cleanly removing everything.
    db_path = str(tmp_path / "store.db")
    blob_dir = tmp_path / "blobs"
    store = _mod.DocumentStore(db_path=db_path, blob_dir=str(blob_dir))
    store.put(
        make_paper_record(
            parsed=make_parsed_doc(figures=[make_figure()], tables=[make_table_item()])
        )
    )
    assert (blob_dir / f"{PAPER_ID}.md").exists()

    store.delete(PAPER_ID)  # must not raise sqlite3.IntegrityError

    assert store.get(PAPER_ID) is None
    assert not (blob_dir / f"{PAPER_ID}.md").exists()
    con = sqlite3.connect(db_path)
    try:
        for table in ("papers", "blocks", "chunks", "summaries", "figures", "tables"):
            (count,) = con.execute(
                f"SELECT count(*) FROM {table} WHERE paper_id = ?", (PAPER_ID,)
            ).fetchone()
            assert count == 0, f"{table} still holds rows for {PAPER_ID}: delete() left rows behind"
    finally:
        con.close()


def test_delete_returns_the_chunk_and_summary_ids_removed(store):
    # T-DOC40: the id set the caller (IngestionOrchestrator.delete_paper) hands to
    # VectorIndex.delete() to clean up the matching vector-store points -- delete() only ever
    # touches SQLite itself (CONVENTIONS.md §1: DocumentStore must not import the vector-store
    # vendor), so this return value is the only way the caller learns which ids to remove.
    store.put(make_paper_record())

    deleted = store.delete(PAPER_ID)

    assert sorted(deleted) == sorted([f"{PAPER_ID}:c0", f"{PAPER_ID}:summary"])


def test_delete_returns_every_chapter_summary_id_for_a_book(store):
    # Regression: a book's paper_id has N+1 summaries rows (whole-doc + one per chapter). The old
    # `.fetchone()` in delete() grabbed only one of them, silently orphaning the rest in the
    # vector index. All of them must come back so the caller can clean up every vector.
    chapters = [
        ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch0", title="Intro", text="ch0 summary"),
        ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch1", title="DAGs", text="ch1 summary"),
    ]
    store.put(make_paper_record(ref=make_paper_ref(doc_type="book"), chapter_summaries=chapters))

    deleted = store.delete(PAPER_ID)

    assert sorted(deleted) == sorted(
        [f"{PAPER_ID}:c0", f"{PAPER_ID}:summary", f"{PAPER_ID}:summary:ch0", f"{PAPER_ID}:summary:ch1"]
    )


def test_delete_of_unknown_paper_returns_empty_list(store):
    assert store.delete("9999.99999") == []


def test_delete_does_not_touch_another_papers_rows(store):
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

    deleted = store.delete(PAPER_ID)

    assert store.get(PAPER_ID) is None
    assert other not in deleted and f"{other}:c0" not in deleted
    got_other = store.get(other)
    assert got_other is not None
    assert [c.chunk_id for c in got_other.chunks] == [f"{other}:c0"]


def test_delete_unknown_paper_id_is_a_safe_no_op(store):
    store.delete("9999.99999")  # must not raise


def test_delete_cleans_up_chunks_and_blocks_with_no_matching_papers_row(tmp_path):
    # The real T-DOC23 orphan shape: chunks/blocks rows exist with NO matching papers row (an
    # earlier cleanup pass deleted the papers row directly, bypassing put()'s atomicity and
    # leaving these behind -- from back when nothing in this codebase enforced the declared
    # foreign keys). delete()'s three non-papers DELETEs must run unconditionally, not gated on a
    # papers row existing first, or this exact case slips through.
    db_path = str(tmp_path / "store.db")
    store = _mod.DocumentStore(db_path=db_path, blob_dir=str(tmp_path / "blobs"))
    orphan_id = "2508.00000"
    # T-DOC40: FK enforcement is ON for this connection now (see __init__), so inserting a child
    # row with no matching `papers` row would itself raise `sqlite3.IntegrityError`. Turned off
    # just for this fixture insert to model data that predates the fix (real production orphans,
    # created back when nothing enforced the constraint) -- turned back on before delete() runs,
    # proving cleanup of pre-existing orphans still works under the new enforcement regime.
    store._con.execute("PRAGMA foreign_keys=OFF;")
    store._con.execute(
        "INSERT INTO blocks (block_id, paper_id, idx, type, text, page, bbox_json, section_path) "
        "VALUES (?, ?, 0, 'prose', 'orphan text', 0, '[0,0,1,1]', '1. Intro')",
        (f"{orphan_id}:b0", orphan_id),
    )
    store._con.execute(
        "INSERT INTO chunks (chunk_id, paper_id, text, anchor_json, section_path, parent_id, "
        "contextual_header) VALUES (?, ?, 'orphan chunk text', '{}', '1. Intro', ?, NULL)",
        (f"{orphan_id}:c0", orphan_id, f"{orphan_id}:b0"),
    )
    store._con.commit()
    store._con.execute("PRAGMA foreign_keys=ON;")

    deleted = store.delete(orphan_id)

    assert deleted == [f"{orphan_id}:c0"]
    con = sqlite3.connect(db_path)
    try:
        for table in ("blocks", "chunks"):
            (count,) = con.execute(
                f"SELECT count(*) FROM {table} WHERE paper_id = ?", (orphan_id,)
            ).fetchone()
            assert count == 0, f"{table} still holds orphaned rows for {orphan_id}"
    finally:
        con.close()


# --------------------------------------------------------------------------------------------------
# doc_type + chapter_summaries (T-DOC80) — book ingestion round-trips through papers.doc_type and
# one summaries row per chapter (migration 0004)
# --------------------------------------------------------------------------------------------------


def test_put_get_round_trips_doc_type_and_chapters(store):
    chapters = [
        ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch0", title="Intro", text="ch0 summary"),
        ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch1", title="DAGs", text="ch1 summary"),
    ]
    record = make_paper_record(
        ref=make_paper_ref(doc_type="book"), chapter_summaries=chapters
    )
    store.put(record)

    got = store.get(PAPER_ID)

    assert got.ref.doc_type == "book"
    assert got.chapter_summaries == chapters


def test_chapter_order_is_numeric_not_lexical(store):
    # ch10 must come after ch2 — lexical ordering would break this at 10+ chapters. Inserted
    # out of numeric order (11 down to 0) so a missing/wrong sort in get() can't hide behind
    # chapter_summaries already arriving pre-sorted.
    chapters_out_of_order = [
        ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch{i}", title=f"C{i}", text="t")
        for i in range(11, -1, -1)
    ]
    store.put(
        make_paper_record(
            ref=make_paper_ref(doc_type="book"), chapter_summaries=chapters_out_of_order
        )
    )

    got = store.get(PAPER_ID)

    expected_ascending = [f"{PAPER_ID}:summary:ch{i}" for i in range(12)]
    assert [c.summary_id for c in got.chapter_summaries] == expected_ascending


def test_malformed_chapter_summary_id_raises_contract_error(store):
    """A summary row that is neither the whole-doc summary nor a parseable `:ch{n}` previously
    raised a bare ValueError out of get() -- every other malformed-id condition in this module
    raises the typed ContractError instead (see get_block/get_chunk/get_summary below)."""
    store.put(make_paper_record(ref=make_paper_ref(doc_type="book")))
    store._con.execute(
        "INSERT INTO summaries (summary_id, paper_id, text, title) VALUES (?, ?, ?, ?)",
        (f"{PAPER_ID}:summary:chXYZ", PAPER_ID, "t", "T"),
    )
    store._con.commit()

    with pytest.raises(ContractError, match="chapter summary_id"):
        store.get(PAPER_ID)


def test_get_summary_resolves_chapter_ids(store):
    chapters = [
        ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch0", title="Intro", text="ch0 summary"),
        ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch1", title="DAGs", text="ch1 summary"),
    ]
    store.put(make_paper_record(ref=make_paper_ref(doc_type="book"), chapter_summaries=chapters))

    assert store.get_summary(f"{PAPER_ID}:summary:ch1") == "ch1 summary"


def test_paper_without_chapters_unchanged(store):
    store.put(make_paper_record())  # plain paper, no chapter_summaries, default doc_type

    got = store.get(PAPER_ID)

    assert got.ref.doc_type == "paper"
    assert got.chapter_summaries == []


def test_delete_removes_chapter_rows(store):
    chapters = [
        ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch0", title="Intro", text="ch0 summary"),
    ]
    store.put(make_paper_record(ref=make_paper_ref(doc_type="book"), chapter_summaries=chapters))

    store.delete(PAPER_ID)

    (count,) = store._con.execute(
        "SELECT count(*) FROM summaries WHERE paper_id = ?", (PAPER_ID,)
    ).fetchone()
    assert count == 0


# --------------------------------------------------------------------------------------------------
# PRAGMA foreign_keys=ON (T-DOC40) — prevents the T-DOC23/T-DOC35 orphan class at the schema level
# --------------------------------------------------------------------------------------------------


def test_foreign_keys_pragma_is_on_for_a_fresh_connection(store):
    (value,) = store._con.execute("PRAGMA foreign_keys;").fetchone()
    assert value == 1


def test_raw_delete_from_papers_with_children_present_is_rejected_not_silently_orphaning(store):
    # This is the exact T-DOC23/T-DOC35 bug reproduced directly: a raw DELETE against `papers`
    # while `chunks`/`blocks`/`summaries` rows still reference that paper_id, run outside
    # DocumentStore.delete()'s own cascading interface. Before T-DOC40 this silently succeeded and
    # left orphans; with PRAGMA foreign_keys=ON it must now fail loudly instead (CONVENTIONS.md
    # §4 "crash early") -- proving the pragma is not just set but actually enforced.
    store.put(make_paper_record())

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store._con.execute("DELETE FROM papers WHERE paper_id = ?", (PAPER_ID,))

    # The statement never committed (SQLite checks an immediate FK constraint at execute() time,
    # before any commit) -- every row (parent AND children) is still exactly as put() left it.
    assert store.get(PAPER_ID) is not None


# --------------------------------------------------------------------------------------------------
# T-DOC81 review fixes: DocumentStore's own unconditional migrate() call, and the (c) safety net
# --------------------------------------------------------------------------------------------------


def test_document_store_migrates_a_populated_pre_existing_db_on_open(tmp_path):
    """T-DOC81 review fix (item 3): every T-DOC81 required test calls `migrate()` directly --
    nothing pinned that `DocumentStore.__init__` itself calls it unconditionally. Restoring the old
    `if not db_file.exists()` guard would break no test without this one. Build a DB at 0001-0003
    (no `doc_type` column) with real rows, then construct `DocumentStore` straight against it and
    `put()` a record -- `put()` unconditionally writes `papers.doc_type`, so this only succeeds if
    `DocumentStore.__init__` itself applied 0004, not a test calling `migrate()` on its behalf."""
    db_path = str(tmp_path / "store.db")
    conn = sqlite3.connect(db_path)
    try:
        for name in (
            "0001_init.sql",
            "0002_ingest_checkpoint.sql",
            "0003_quarantine_diagnostics.sql",
        ):
            conn.executescript((MIGRATIONS_DIR / name).read_text())
        conn.commit()
    finally:
        conn.close()

    store = _mod.DocumentStore(db_path=db_path, blob_dir=str(tmp_path / "blobs"))
    store.put(make_paper_record())  # writes papers.doc_type -- raw OperationalError pre-fix

    got = store.get(PAPER_ID)
    assert got.ref.doc_type == "paper"


def test_verify_required_columns_raises_when_adoption_misclassifies_partial_0004(tmp_path):
    """T-DOC81 review fix (item 2): `_verify_required_columns` is design item (c), the mitigation
    the design doc's own Risks section names for adoption mis-classification -- nothing exercised
    it. Build the case the design predicts: `papers.doc_type` present (satisfies the 0004 adoption
    probe) but `summaries.title` absent (0004's SECOND `ALTER` never ran, e.g. a hand-applied
    partial migration) -- adoption records 0004 as fully applied from the doc_type probe alone, so
    `DocumentStore` must still catch the missing column and raise a clear, actionable
    `ContractError` naming it, instead of a bare `OperationalError` surfacing later mid-`put()`."""
    db_path = str(tmp_path / "store.db")
    conn = sqlite3.connect(db_path)
    try:
        for name in (
            "0001_init.sql",
            "0002_ingest_checkpoint.sql",
            "0003_quarantine_diagnostics.sql",
        ):
            conn.executescript((MIGRATIONS_DIR / name).read_text())
        # Only 0004's FIRST ALTER -- the adoption probe for 0004 checks papers.doc_type alone, so
        # this alone is enough to make adoption (wrongly) mark 0004 as fully applied.
        conn.execute("ALTER TABLE papers ADD COLUMN doc_type TEXT NOT NULL DEFAULT 'paper';")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        ContractError, match=r"summaries.*title.*0004_doc_type_and_chapter_titles"
    ):
        _mod.DocumentStore(db_path=db_path, blob_dir=str(tmp_path / "blobs"))


# --------------------------------------------------------------------------------------------------
# scan_blocks -- exhaustive lexical enumeration (2026-08-19)
#
# The store-side half of `McpServer.scan_corpus`. It exists because ranked retrieval cannot answer
# "which papers contain X": top-k samples a ranked list, so a paper that names a method once ranks
# below a paper that discusses it at length, and no amount of `k` proves nothing was missed.
# Measured on the live corpus, an enumeration answered by retrieval alone found 3 of 4 qualifying
# papers; the same question via this scan found 4 of 4.
# --------------------------------------------------------------------------------------------------


def _put_paper(store, paper_id, blocks, title="T", author_orgs=None):
    record = make_paper_record(
        ref=make_paper_ref(paper_id=paper_id, title=title),
        parsed=make_parsed_doc(paper_id=paper_id, blocks=blocks),
        chunks=[], summary_id=f"{paper_id}:summary",
    )
    store.put(record)
    if author_orgs is not None:
        store._con.execute("UPDATE papers SET author_orgs=? WHERE paper_id=?",
                           (author_orgs, paper_id))
        store._con.commit()


def test_scan_blocks_finds_every_matching_paper_not_just_the_best_ranked(store):
    """Recall is the whole point: every paper containing the pattern must come back."""
    for i in range(4):
        pid = f"2506.0000{i}"
        _put_paper(store, pid, [make_block(block_id=f"{pid}:b0", paper_id=pid,
                                           text="we used a Poisson bootstrap here")])
    _put_paper(store, "2506.00009", [make_block(block_id="2506.00009:b0",
                                                paper_id="2506.00009", text="nothing relevant")])

    rows, scanned, matched, _truncated = store.scan_blocks("bootstrap")

    assert scanned == 5
    assert matched == 4
    assert {r[0] for r in rows} == {f"2506.0000{i}" for i in range(4)}


def test_scan_blocks_returns_section_path_so_use_can_be_told_from_citation(store):
    """`section_path` is what makes a match adjudicable -- Related Work means cited, Methods means
    used. Without it, a lexical hit is undecidable."""
    _put_paper(store, "2506.00001", [
        make_block(block_id="2506.00001:b0", paper_id="2506.00001",
                   text="prior work applied a bootstrap", section_path="2 Related Work"),
        make_block(block_id="2506.00001:b1", paper_id="2506.00001", index=1,
                   text="we computed a bootstrap CI", section_path="4 Methods"),
    ])

    rows, _scanned, _matched, _truncated = store.scan_blocks("bootstrap", max_per_paper=5)

    assert {r[4] for r in rows} == {"2 Related Work", "4 Methods"}


def test_scan_blocks_caps_evidence_per_paper_but_never_drops_the_paper(store):
    """Truncation must cost extra QUOTES, never a PAPER -- losing a paper is the failure this tool
    exists to prevent."""
    blocks = [make_block(block_id=f"2506.00001:b{i}", paper_id="2506.00001", index=i,
                         text="bootstrap again") for i in range(5)]
    _put_paper(store, "2506.00001", blocks)

    rows, _scanned, matched, truncated = store.scan_blocks("bootstrap", max_per_paper=2)

    assert len(rows) == 2
    assert matched == 1, "the paper still appears"
    assert truncated is True


def test_scan_blocks_paper_id_scopes_to_one_document_for_definition_lookup(store):
    _put_paper(store, "2506.00001", [make_block(block_id="2506.00001:b0", paper_id="2506.00001",
                                                text="we call this exponential bootstrap (EB)")])
    _put_paper(store, "2506.00002", [make_block(block_id="2506.00002:b0", paper_id="2506.00002",
                                                text="unrelated exponential bootstrap mention")])

    rows, _scanned, matched, _t = store.scan_blocks("exponential bootstrap",
                                                    paper_id="2506.00001")

    assert matched == 1
    assert {r[0] for r in rows} == {"2506.00001"}


def test_scan_blocks_curated_org_matches_only_the_enumerated_tier(store):
    """`curated` is an enumerated fact; `keyword` is a 0.706-precision heuristic. Asking for one
    must never silently return the other."""
    _put_paper(store, "2506.00001", [make_block(block_id="2506.00001:b0", paper_id="2506.00001",
               text="bootstrap")], author_orgs='[{"name": "Waymo", "method": "curated"}]')
    _put_paper(store, "2506.00002", [make_block(block_id="2506.00002:b0", paper_id="2506.00002",
               text="bootstrap")], author_orgs='[{"name": "Waymo", "method": "keyword"}]')
    _put_paper(store, "2506.00003", [make_block(block_id="2506.00003:b0", paper_id="2506.00003",
               text="bootstrap")], author_orgs=None)

    rows, scanned, matched, _t = store.scan_blocks("bootstrap", curated_org="Waymo")

    assert matched == 1
    assert {r[0] for r in rows} == {"2506.00001"}
    assert scanned == 1, "papers outside the curated tier are not even scanned"


def test_scan_blocks_rejects_an_invalid_regex_rather_than_matching_nothing(store):
    """A malformed pattern must fail loudly -- silently returning zero matches would read as
    'no paper contains this', the exact false-negative this tool exists to prevent."""
    _put_paper(store, "2506.00001", [make_block(block_id="2506.00001:b0",
                                                paper_id="2506.00001")])
    with pytest.raises(ContractError):
        store.scan_blocks("bootstrap(")


# --------------------------------------------------------------------------------------------------
# cross-thread reads (RI-1) — the dashboard builds the retrieval stack on one thread and reads
# through it from ThreadingHTTPServer request threads on every search
# --------------------------------------------------------------------------------------------------


def test_store_readable_from_a_thread_other_than_its_creating_thread(tmp_path):
    """RI-1: sqlite3.connect defaults to check_same_thread=True, so a DocumentStore built on one
    thread raised ProgrammingError on the first read from another -- exactly the dashboard's shape:
    app.assembly.build_mcp_server constructs the store inside whichever request thread happens to
    run the first search, and every later search is a different ThreadingHTTPServer thread."""
    store = _mod.DocumentStore(
        db_path=str(tmp_path / "store.db"), blob_dir=str(tmp_path / "blobs")
    )
    store.put(make_paper_record())

    # .result() re-raises a worker-thread exception in THIS thread, so a check_same_thread
    # violation fails the test loudly instead of killing a worker silently.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        got = pool.submit(store.get, PAPER_ID).result()

    assert got is not None
    assert got.ref.paper_id == PAPER_ID
