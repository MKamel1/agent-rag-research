"""`app/prefetch_pdfs.py` — standalone PDF-backlog builder.

Covers the properties the design depends on:

1. Dedup against the shared `ingest_state` (never re-downloads a paper the live pipeline already
   claimed, at ANY stage including `"done"`) -- AND that checking never *writes* to that shared
   table: this script reads `all_known_paper_ids()` only, on purpose (see
   `app/prefetch_pdfs.py`'s module docstring point 1 for why an earlier, write-based design was
   rejected in review -- a second process's checkpoint/quarantine call is a non-atomic
   read-merge-write/delete race against the live pipeline's own writes to the same file).
2. A kill-and-restart resumes from the on-disk `.pdf` cache (the only durable progress marker this
   script uses), not from zero, and never re-fetches what a prior pass already downloaded.

Real sqlite schema (`migrations.migrate`), no real network (`httpx.MockTransport`) -- same pattern
`rag/test_harvester_arxiv_source.py` and `rag/test_ingest_state_sqlite.py` already use.
"""

from datetime import date

import httpx

from app.prefetch_pdfs import _cached_count, _skip_marker_path, run
from contracts.config import Config
from contracts.harvester import PaperRef
from migrations.migrate import migrate
from rag.ingest_state_sqlite import SqliteIngestState


def _make_ref(i: int) -> PaperRef:
    return PaperRef(
        paper_id=f"26{i:02d}.00001",
        version="v1",
        title=f"Paper {i}",
        abstract=f"Abstract {i}",
        authors=["A. Author"],
        categories=["cs.LG"],
        published=date(2026, 1, 1 + i),
        updated=date(2026, 1, 1 + i),
        pdf_url=f"https://arxiv.example/pdf/26{i:02d}.00001v1",
    )


class StubHarvester:
    """Mirrors `rag/test_ingest_state_sqlite.py`'s `StubHarvester` -- a fixed ref list, no
    network, no dedup/retry logic of its own (that's `Harvester`'s job, already covered
    elsewhere)."""

    def __init__(self, refs):
        self._refs = list(refs)

    def harvest(self, focus_area, cap, ordering):
        return iter(self._refs[:cap])


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _no_sleep(_seconds: float) -> None:
    pass


def _cfg() -> Config:
    return Config(focus_area_queries=["causal inference"], corpus_cap=10)


# ================================================================================================
# Dedup against the shared `ingest_state` -- read-only, never a write.
# ================================================================================================


def test_skips_a_paper_the_live_pipeline_already_checkpointed(tmp_path):
    """A paper already at ANY ingest_state stage (simulating the live fused-download-parse
    pipeline having already claimed it) must not be downloaded again -- no request at all -- and
    this script must not write anything back to that row."""
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    refs = [_make_ref(0), _make_ref(1)]
    state = SqliteIngestState(db_path)
    state.checkpoint(refs[0].paper_id, "parsed")  # live pipeline already has paper 0

    requested_ids = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_ids.append(str(request.url).rsplit("/", 1)[-1])
        return httpx.Response(200, content=b"%PDF-fake-bytes")

    new = run(
        _cfg(), db_path, cache_dir, target=10,
        harvester=StubHarvester(refs), client=_mock_client(handler), sleep=_no_sleep,
    )

    assert new == 1
    assert not (cache_dir / f"{refs[0].paper_id}.pdf").exists()
    assert (cache_dir / f"{refs[1].paper_id}.pdf").exists()
    assert requested_ids == ["2601.00001v1"]  # only paper 1 was ever requested
    # The live pipeline's own row for paper 0 is byte-for-byte untouched.
    assert SqliteIngestState(db_path).stage_of(refs[0].paper_id) == "parsed"


def test_a_paper_already_done_survives_a_full_pass_completely_unchanged(tmp_path):
    """Regression test for the exact scenario design review flagged as the blocker: a paper the
    live pipeline has fully finished (`"done"`, `ingest_checkpoint` row already cleared) must not
    be downloaded, and the shared row must not be downgraded/rewritten by this script in any way.
    """
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    ref = _make_ref(0)
    state = SqliteIngestState(db_path)
    state.checkpoint(ref.paper_id, "parsed")
    state.checkpoint(ref.paper_id, "done")
    before = state.get(ref.paper_id)
    assert before.stage == "done"

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never request a paper the live pipeline already finished")

    new = run(
        _cfg(), db_path, cache_dir, target=10,
        harvester=StubHarvester([ref]), client=_mock_client(handler), sleep=_no_sleep,
    )

    assert new == 0
    assert not (cache_dir / f"{ref.paper_id}.pdf").exists()
    after = SqliteIngestState(db_path).get(ref.paper_id)
    assert after.stage == "done"
    assert after.artifacts == before.artifacts  # completely untouched, not just same stage string


def test_quarantined_paper_is_also_skipped(tmp_path):
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    refs = [_make_ref(0)]
    state = SqliteIngestState(db_path)
    state.checkpoint(refs[0].paper_id, "parsed")
    state.quarantine(refs[0].paper_id, "parsed", RuntimeError("bad pdf"))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should never request an already-quarantined paper")

    new = run(
        _cfg(), db_path, cache_dir, target=10,
        harvester=StubHarvester(refs), client=_mock_client(handler), sleep=_no_sleep,
    )
    assert new == 0


# ================================================================================================
# Resumability: kill mid-run, restart, no duplicate downloads, progress continues -- purely via
# the on-disk `.pdf` cache (this script writes nothing to the shared db).
# ================================================================================================


def test_restart_after_a_crash_resumes_without_redownloading_and_finishes_the_backlog(tmp_path):
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    refs = [_make_ref(0), _make_ref(1), _make_ref(2)]
    request_log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(str(request.url))
        return httpx.Response(200, content=b"%PDF-fake-bytes")

    # "Run 1" only ever sees paper 0 -- standing in for a process that got killed after
    # downloading paper 0 but before ever reaching papers 1/2.
    run1_new = run(
        _cfg(), db_path, cache_dir, target=10,
        harvester=StubHarvester(refs[:1]), client=_mock_client(handler), sleep=_no_sleep,
    )
    assert run1_new == 1
    assert _cached_count(cache_dir) == 1
    assert len(request_log) == 1
    # Nothing was ever written to the shared db by this script -- there is no row at all.
    assert SqliteIngestState(db_path).get(refs[0].paper_id) is None

    # "Run 2" -- a brand-new process (fresh SqliteIngestState is constructed inside `run()` from
    # just `db_path`, same as a real restart would), now sees the FULL ref list again (a real
    # restart re-harvests from scratch, same as the live pipeline's own harvest() does).
    run2_new = run(
        _cfg(), db_path, cache_dir, target=10,
        harvester=StubHarvester(refs), client=_mock_client(handler), sleep=_no_sleep,
    )

    assert run2_new == 2  # only papers 1 and 2 -- paper 0 was never re-requested
    assert _cached_count(cache_dir) == 3
    assert len(request_log) == 3  # total across both runs: exactly one request per paper


def test_restart_never_redownloads_a_file_already_on_disk(tmp_path):
    """A `.pdf` already present (e.g. from a pass that downloaded it but got killed before this
    call returned) must be recognized on the next pass without re-requesting it."""
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    ref = _make_ref(0)
    (cache_dir / f"{ref.paper_id}.pdf").write_bytes(b"%PDF-already-here")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should never re-download a file already on disk")

    new = run(
        _cfg(), db_path, cache_dir, target=10,
        harvester=StubHarvester([ref]), client=_mock_client(handler), sleep=_no_sleep,
    )

    assert new == 0  # not counted as a NEW download this pass
    assert _cached_count(cache_dir) == 1  # but still correctly counted as progress


# ================================================================================================
# Target stop condition and error taxonomy -- local `.pdf.skip` marker, never shared quarantine.
# ================================================================================================


def test_stops_once_target_is_reached_even_with_more_refs_available(tmp_path):
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    refs = [_make_ref(i) for i in range(5)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-fake-bytes")

    new = run(
        _cfg(), db_path, cache_dir, target=2,
        harvester=StubHarvester(refs), client=_mock_client(handler), sleep=_no_sleep,
    )
    assert new == 2
    assert _cached_count(cache_dir) == 2


def test_permanent_download_failure_writes_a_local_marker_and_does_not_stop_the_run(tmp_path):
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    refs = [_make_ref(0), _make_ref(1)]

    def handler(request: httpx.Request) -> httpx.Response:
        if refs[0].paper_id in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=b"%PDF-fake-bytes")

    new = run(
        _cfg(), db_path, cache_dir, target=10,
        harvester=StubHarvester(refs), client=_mock_client(handler), sleep=_no_sleep,
    )

    assert new == 1
    assert not (cache_dir / f"{refs[0].paper_id}.pdf").exists()
    assert (cache_dir / f"{refs[1].paper_id}.pdf").exists()
    # Dead-lettered locally, not in the shared `quarantine` table.
    assert _skip_marker_path(cache_dir, refs[0].paper_id).exists()
    assert SqliteIngestState(db_path).get(refs[0].paper_id) is None  # shared db never touched


def test_permanently_failed_paper_is_skipped_on_a_later_pass_without_a_request(tmp_path):
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    ref = _make_ref(0)
    _skip_marker_path(cache_dir, ref.paper_id).write_text("404 on a prior pass")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should never re-request a permanently-failed paper_id")

    new = run(
        _cfg(), db_path, cache_dir, target=10,
        harvester=StubHarvester([ref]), client=_mock_client(handler), sleep=_no_sleep,
    )
    assert new == 0


def test_transient_failure_retries_with_backoff_floored_at_the_pdf_delay_then_gives_up_retryable(
    tmp_path,
):
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    ref = _make_ref(0)
    call_count = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(503)  # always transient -- exhausts retries

    new = run(
        _cfg(), db_path, cache_dir, target=10,
        harvester=StubHarvester([ref]), client=_mock_client(handler), sleep=sleeps.append,
    )

    assert new == 0
    assert not (cache_dir / f"{ref.paper_id}.pdf").exists()
    assert not _skip_marker_path(cache_dir, ref.paper_id).exists()  # retryable, not permanent
    assert SqliteIngestState(db_path).get(ref.paper_id) is None  # shared db never touched
    assert call_count > 1  # actually retried, not a single attempt
    # Every retry backoff sleep is floored at the routine PDF pacing -- a 429/5xx must never make
    # this script hit arXiv MORE often than its normal cadence (module docstring point 3).
    assert all(s >= 15.0 for s in sleeps)


# ================================================================================================
# `SqliteIngestState.all_known_paper_ids` -- the bulk-read this script's dedup check relies on.
# ================================================================================================


def test_all_known_paper_ids_includes_both_ingest_state_and_quarantine_rows(tmp_path):
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    state = SqliteIngestState(db_path)

    state.checkpoint("2601.00001", "parsed")
    state.checkpoint("2601.00002", "harvested")
    state.checkpoint("2601.00003", "parsed")
    state.quarantine("2601.00003", "parsed", RuntimeError("boom"))

    ids = state.all_known_paper_ids()
    assert ids == {"2601.00001", "2601.00002", "2601.00003"}
