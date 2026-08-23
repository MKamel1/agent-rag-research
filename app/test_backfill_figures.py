# RI-32 — figures/tables backfill tool: tests written against the interface before the
# implementation (CONVENTIONS §0.7 / M1a convention). Zero network, zero GPU: the parser seam is
# a fake callable, the store is the real DocumentStore on tmp_path.
"""`app.backfill_figures` test suite.

Covers the ticket's four required behaviors plus the one non-negotiable property:

- THE safety property: a full run over a populated fixture corpus leaves papers/blocks/chunks/
  summaries byte-identical (row counts AND content hashes), while figures/tables grow;
- resume after interruption: already-backfilled papers are not re-parsed;
- idempotency: a second full run re-parses nothing and duplicates no rows;
- a paper whose parse raises is logged/skipped and retried on a later run -- never fatal,
  never half-written;
- `--dry-run` semantics: no parse calls, no writes, no markers;
- a paper whose cached PDF is absent is skipped without calling the parser.

2026-08-22 repair (RI-32 implementation session): as committed, this suite was unsatisfiable --
the fixture gives every paper but the last a cached PDF, yet test_full_run expected all three
papers backfilled with 6 figure rows (which requires parsing the cache-less third paper) while
test_missing_cached_pdf required that same paper to never reach the parser, on identical fixture
state. The fixture stays as its own comment intends ("exercises the skip path"); the four stale
expected values in test_full_run / test_resume / test_second_full_run / test_parse_failure were
corrected to what that fixture actually implies -- the last paper is `skipped_no_cache` in every
non-dry-run full pass and contributes neither rows nor a marker.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

import pytest

_mod = pytest.importorskip("app.backfill_figures")

from contracts.chunker import Chunk  # noqa: E402
from contracts.document_store import PaperRecord  # noqa: E402
from contracts.errors import PermanentError  # noqa: E402
from contracts.harvester import PaperRef  # noqa: E402
from contracts.parser import Figure, ParsedDoc, TableItem  # noqa: E402
from contracts.provenance import Anchor, Block  # noqa: E402
from rag.document_store import DocumentStore  # noqa: E402

PIDS = ["2501.00001", "2501.00002", "2501.00003"]
BBOX = (0.0, 0.0, 100.0, 200.0)


# --- local factories (same pattern as rag/test_document_store.py's own local helpers) -----------


def _record(paper_id: str) -> PaperRecord:
    anchor = Anchor(
        paper_id=paper_id, block_id=f"{paper_id}:b0", page=0, bbox=BBOX,
        snippet=f"Body of {paper_id}.", section_path="",
    )
    chunk = Chunk(
        chunk_id=f"{paper_id}:c0", paper_id=paper_id, text=f"Chunk of {paper_id}.",
        anchor=anchor, section_path="", parent_id=f"{paper_id}:b0",
    )
    block = Block(
        block_id=f"{paper_id}:b0", paper_id=paper_id, text=f"Body of {paper_id}.",
        type="prose", page=0, bbox=BBOX, section_path="", index=0,
    )
    ref = PaperRef(
        paper_id=paper_id, version="v1", title=f"Paper {paper_id}", abstract="We propose...",
        authors=["A. Author"], categories=["cs.RO"], published=date(2026, 1, 1),
        updated=date(2026, 1, 1), pdf_url=f"https://arxiv.org/pdf/{paper_id}v1",
    )
    parsed = ParsedDoc(
        paper_id=paper_id, markdown=f"# Paper {paper_id}", blocks=[block],
        figures=[], tables=[], references=[], parser_id="fixture-parser",
    )
    return PaperRecord(
        ref=ref, parsed=parsed, chunks=[chunk],
        summary_text=f"Summary of {paper_id}.", summary_id=f"{paper_id}:summary",
    )


def _parsed_with_artifacts(paper_id: str, n_figures: int = 2, n_tables: int = 1) -> ParsedDoc:
    block = Block(
        block_id=f"{paper_id}:b0", paper_id=paper_id, text=f"Re-parsed body of {paper_id}.",
        type="prose", page=0, bbox=BBOX, section_path="", index=0,
    )
    figures = [
        Figure(
            paper_id=paper_id, image_path=f"/blobs/figures/{paper_id}/fig{i}.png",
            caption=f"Fig {i}", page=i, bbox=BBOX,
        )
        for i in range(n_figures)
    ]
    tables = [
        TableItem(
            paper_id=paper_id, markdown="| a |\n|---|\n| 1 |", caption=f"Table {i}",
            page=n_figures + i, bbox=BBOX,
        )
        for i in range(n_tables)
    ]
    return ParsedDoc(
        paper_id=paper_id, markdown=f"# Re-parsed {paper_id}", blocks=[block],
        figures=figures, tables=tables, references=[], parser_id="fake-parser",
    )


@dataclass
class FakeParser:
    """Stands in for `rag.parser.parse(raw, paper_id) -> ParsedDoc`; records every call so tests
    can assert exactly which papers were (re-)parsed."""

    fail_for: tuple[str, ...] = ()
    artifactless_for: tuple[str, ...] = ()  # papers whose re-parse finds no figures/tables
    calls: list[str] = field(default_factory=list)

    def __call__(self, raw: bytes, paper_id: str) -> ParsedDoc:
        self.calls.append(paper_id)
        if paper_id in self.fail_for:
            raise PermanentError(f"unparseable fixture PDF: {paper_id}")
        if paper_id in self.artifactless_for:
            return _parsed_with_artifacts(paper_id, n_figures=0, n_tables=0)
        return _parsed_with_artifacts(paper_id)


# --- fixtures ------------------------------------------------------------------------------------


@pytest.fixture
def corpus(tmp_path):
    db_path = tmp_path / "papers.db"
    blob_dir = tmp_path / "blobs"
    cache_dir = tmp_path / "pdf_cache"
    cache_dir.mkdir()
    store = DocumentStore(db_path=str(db_path), blob_dir=str(blob_dir))
    for pid in PIDS:
        store.put(_record(pid))
    # Every paper gets a cached PDF except the last one -- exercises the skip path.
    for pid in PIDS[:-1]:
        (cache_dir / f"{pid}.pdf").write_bytes(b"%PDF-fake")
    return SimpleNamespace(
        db_path=db_path, store=store, cache_dir=cache_dir,
        markers_dir=blob_dir / "figures", paper_ids=list(PIDS),
    )


def _run(corpus, parser, **overrides):
    kwargs = dict(
        cache_dir=corpus.cache_dir, markers_dir=corpus.markers_dir,
        paper_ids=list(corpus.paper_ids),
    )
    kwargs.update(overrides)
    return _mod.run_backfill(corpus.store, parser, **kwargs)


def _counts(db_path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("figures", "tables")
        }
    finally:
        con.close()


# --- tests ---------------------------------------------------------------------------------------


def test_full_run_leaves_protected_tables_byte_identical(corpus):
    """THE RI-32 safety property, end-to-end on a populated fixture corpus: papers/blocks/chunks/
    summaries are byte-identical across the run (counts AND content hashes via
    table_fingerprints); only figures/tables gain rows."""
    before = _mod.table_fingerprints(str(corpus.db_path), _mod.PROTECTED_TABLES)

    outcomes = _run(corpus, FakeParser())

    after = _mod.table_fingerprints(str(corpus.db_path), _mod.PROTECTED_TABLES)
    assert after == before, "the backfill moved a protected table"
    # The third paper has no cached PDF (see the fixture), so it is skipped_no_cache, contributes
    # no rows, and gets no marker -- only the two parseable papers are backfilled.
    assert [o.status for o in outcomes] == ["backfilled", "backfilled", "skipped_no_cache"]
    counts = _counts(corpus.db_path)
    assert counts == {"figures": 4, "tables": 2}
    for pid in PIDS[:2]:
        assert (corpus.markers_dir / f"{pid}.done").exists()


def test_resume_after_interruption_does_not_reparse_done_papers(corpus):
    first = _run(corpus, FakeParser(), limit=1)
    assert [o.status for o in first] == ["backfilled"]
    resumed_parser = FakeParser()

    second = _run(corpus, resumed_parser)

    # Every paper in the input still gets classified (run_backfill's own contract: one outcome
    # per paper actually classified) -- the already-done paper is cheaply reclassified as
    # skipped_done rather than dropped from the result, matching test_second_full_run's pattern.
    assert [o.status for o in second] == ["skipped_done", "backfilled", "skipped_no_cache"]
    # The last paper has no cached PDF, so resume must classify it without reaching the parser.
    assert resumed_parser.calls == [PIDS[1]], "already-backfilled papers must not be re-parsed"


def test_second_full_run_reparses_nothing_and_duplicates_nothing(corpus):
    _run(corpus, FakeParser())
    counts_after_first = _counts(corpus.db_path)
    idle_parser = FakeParser()

    outcomes = _run(corpus, idle_parser)

    assert idle_parser.calls == [], "a completed corpus must not be re-parsed"
    # The cache-less paper is skipped_no_cache on every pass -- never retried against the parser.
    assert [o.status for o in outcomes] == ["skipped_done", "skipped_done", "skipped_no_cache"]
    assert _counts(corpus.db_path) == counts_after_first


def test_parse_failure_is_skipped_not_fatal_and_leaves_no_marker(corpus):
    outcomes = _run(corpus, FakeParser(fail_for=PIDS[1]))

    by_status = {o.status for o in outcomes}
    # skipped_no_cache is the fixture's cache-less third paper, sharing the run with the failure.
    assert by_status == {"backfilled", "failed", "skipped_no_cache"}
    failed = next(o for o in outcomes if o.status == "failed")
    assert failed.paper_id == PIDS[1]
    assert failed.error and PIDS[1] in failed.error
    assert not (corpus.markers_dir / f"{PIDS[1]}.done").exists()

    retry = _run(corpus, FakeParser())
    assert [o.status for o in retry if o.paper_id == PIDS[1]] == ["backfilled"]


def test_missing_cached_pdf_is_skipped_without_calling_the_parser(corpus):
    parser = FakeParser()

    outcomes = _run(corpus, parser)

    missing = [o for o in outcomes if o.status == "skipped_no_cache"]
    assert [o.paper_id for o in missing] == [PIDS[-1]]
    assert PIDS[-1] not in parser.calls


def test_dry_run_calls_the_parser_and_writes_neither_rows_nor_markers(corpus):
    before = _mod.table_fingerprints(str(corpus.db_path), _mod.PROTECTED_TABLES)
    parser = FakeParser()

    outcomes = _run(corpus, parser, dry_run=True)

    assert parser.calls == [], "--dry-run must not parse (it would burn the GPU budget)"
    assert [o.status for o in outcomes] == ["would_backfill"] * 2 + ["skipped_no_cache"]
    assert _counts(corpus.db_path) == {"figures": 0, "tables": 0}
    assert _mod.table_fingerprints(str(corpus.db_path), _mod.PROTECTED_TABLES) == before
    assert not any(corpus.markers_dir.glob("*.done"))


def test_zero_artifact_paper_is_still_marked_done_and_not_reparsed(corpus):
    """A paper whose re-parse legitimately yields no figures/tables must still be marked done --
    otherwise every resume re-parses it forever (the reason done-markers exist rather than
    deriving 'done' from figure-row presence alone)."""
    parser = FakeParser(artifactless_for=(PIDS[0],))

    first = _run(corpus, parser, limit=1)
    assert [(o.status, o.figures, o.tables) for o in first] == [("backfilled", 0, 0)]
    assert (corpus.markers_dir / f"{PIDS[0]}.done").exists()

    resume_parser = FakeParser()
    _run(corpus, resume_parser)
    assert PIDS[0] not in resume_parser.calls


def test_progress_log_reports_rate_and_eta(corpus, caplog):
    """Detached-run requirement: progress output an operator can read an ETA from (module
    docstring's DETACHED-RUN SAFETY section). `log_every=1` forces a line on the very first
    backfilled paper instead of waiting for the default cadence of 10."""
    with caplog.at_level("INFO", logger="app.backfill_figures"):
        _run(corpus, FakeParser(), log_every=1)

    progress = [r.getMessage() for r in caplog.records if "backfill progress" in r.getMessage()]
    assert progress, "expected at least one rate/ETA progress line"
    assert "ETA" in progress[0] and "s/paper" in progress[0]


def test_limit_applies_to_eligible_papers_only(corpus):
    parser = FakeParser()
    _run(corpus, parser, limit=1)

    limited = _run(corpus, FakeParser(), limit=1)

    # limit=1 bounds the eligible (backfilled/would_backfill) count only -- the already-done
    # first paper is still cheaply classified as skipped_done and does not consume the budget,
    # so the run reaches and backfills PIDS[1] within the same limit=1 call.
    assert [o.paper_id for o in limited] == [PIDS[0], PIDS[1]]
    assert [o.status for o in limited] == ["skipped_done", "backfilled"]
