# M1A-DORMANT (re-enable in M1b): skips until rag/harvester.py exists. M1b's Definition of Done
# (CONVENTIONS §11) requires this suite to be active (importorskip resolves) and green.
"""T-A1 Harvester (M1) — tests-first suite (M1a), driven through the frozen `harvest()` interface
with the committed `FakeSource` (T-F4). Zero network, zero GPU.

Covers TEST-STRATEGY.md "Harvester" + WORK-BREAKDOWN T-A1:
  - dedup by base paper_id, latest version wins (the `FakeSource` fixture ships v1+v2 of one base
    id, so the assertion is non-vacuous — a fixture with no duplicate would pass trivially);
  - resume skips already-seen base ids;
  - transient error -> retried, then eventually yielded (via `FakeSource`'s `(error, fail_count)`
    injection map);
  - transient error whose retries are exhausted -> quarantined, run continues;
  - permanent error -> quarantined, run continues (earlier papers still delivered).

--------------------------------------------------------------------------------------------------
ASSUMED Harvester interface (T-A1) — documented, not yet frozen in `contracts/`.
ARCHITECTURE.md M1 freezes only the *public method* and `PaperRef` (contracts/harvester.py):

    harvest(focus_area: list[str], cap: int, ordering: str) -> Iterator[PaperRef]

It does NOT pin Harvester's *constructor* / injected collaborators — exactly the gap
`rag/fakes/fake_source.py` flags for Owner A ("`Source`... named, not specified"). This suite
therefore commits the first concrete constructor shape, mirroring how FakeSource committed the
first `Source.fetch()` shape. If M1b adjusts it, this file moves with it (it is the spec the
implementation is written against, per CONVENTIONS §0.7):

    Harvester(
        source,                 # `Source`: .fetch(focus_area, cap, ordering) -> Iterator[PaperRef]
        *,
        seen_ids=(),            # base paper_ids already harvested in a prior run -> resume skips
                                #   them. In production these come from the `ingest_state` table
                                #   (the Harvester composes an interface; it does not touch sqlite3,
                                #   which CONVENTIONS §1 restricts to DocumentStore/migrations).
        quarantine=None,        # sink called `quarantine(paper_id, error)` for a paper that fails
                                #   permanently or exhausts its transient retries; the run continues.
                                #   Backed by the `quarantine` dead-letter table in production.
        max_retries=2,          # transient-error retry budget (per base id).
        retry_sleep=None,       # injected backoff hook `retry_sleep(seconds)` so a unit test never
                                #   really sleeps and can assert backoff was applied.
    )

Rationale for each: dedup/resume need a seen-set; transient retry needs a budget + a no-real-sleep
seam; permanent/exhausted failures need a dead-letter sink — every one is required by a named
TEST-STRATEGY case, none is speculative.
--------------------------------------------------------------------------------------------------
"""

import logging

import pytest

from contracts.errors import PermanentError, TransientError
from rag.fakes.fake_source import FakeSource

_mod = pytest.importorskip("rag.harvester")  # suite SKIPS until rag/harvester.py exists
Harvester = _mod.Harvester

FOCUS = ["causal inference"]
ORDERING = "freshest_first"

# Fixture base ids (fixtures/harvester/paper_refs.json, committed by T-F4):
DUP_ID = "2506.01234"      # ships as v1 AND v2 -> dedup target
MIDDLE_ID = "2507.05678"
LAST_ID = "2504.09999"
ALL_BASE_IDS = {DUP_ID, MIDDLE_ID, LAST_ID}


class QuarantineSink:
    """Records `(paper_id, error)` the Harvester dead-letters, so a test can assert the run
    quarantined the right paper instead of crashing."""

    def __init__(self):
        self.calls = []

    def __call__(self, paper_id, error):
        self.calls.append((paper_id, error))

    @property
    def paper_ids(self):
        return [pid for pid, _ in self.calls]


def make_harvester(source, **kw):
    """Build a Harvester with a no-op backoff so retry tests don't actually sleep."""
    kw.setdefault("retry_sleep", lambda _seconds: None)
    return Harvester(source, **kw)


def harvest_all(harvester, cap=100):
    return list(harvester.harvest(FOCUS, cap, ORDERING))


# --- dedup ---------------------------------------------------------------------------------------

def test_dedup_collapses_the_two_versions_of_one_base_id():
    refs = harvest_all(make_harvester(FakeSource()))
    base_ids = [r.paper_id for r in refs]
    assert len(base_ids) == len(set(base_ids)), "each base paper_id must appear at most once"
    assert set(base_ids) == ALL_BASE_IDS


def test_dedup_keeps_the_latest_version():
    # The frozen invariant (ARCHITECTURE M1) is "latest version" — v2 beats v1 for DUP_ID.
    refs = harvest_all(make_harvester(FakeSource()))
    dup = next(r for r in refs if r.paper_id == DUP_ID)
    assert dup.version == "v2"


# --- resume --------------------------------------------------------------------------------------

def test_resume_skips_already_seen_base_ids():
    # A prior run already harvested two of the three base ids; only the unseen one comes back.
    harvester = make_harvester(FakeSource(), seen_ids={DUP_ID, MIDDLE_ID})
    refs = harvest_all(harvester)
    assert {r.paper_id for r in refs} == {LAST_ID}


def test_resume_with_all_seen_yields_nothing():
    harvester = make_harvester(FakeSource(), seen_ids=ALL_BASE_IDS)
    assert harvest_all(harvester) == []


# --- transient -> retry then succeed -------------------------------------------------------------

def test_transient_error_is_retried_then_the_paper_is_yielded():
    # DUP_ID fails on its first reach, then succeeds — with a retry budget the paper is recovered
    # and every base id (including DUP_ID) is delivered, none quarantined.
    source = FakeSource(errors={DUP_ID: (TransientError, 1)})
    quarantine = QuarantineSink()
    refs = harvest_all(make_harvester(source, quarantine=quarantine, max_retries=2))
    assert set(r.paper_id for r in refs) == ALL_BASE_IDS
    assert quarantine.calls == []


def test_transient_retry_applies_backoff():
    source = FakeSource(errors={DUP_ID: (TransientError, 1)})
    slept = []
    harvester = Harvester(
        source,
        quarantine=QuarantineSink(),
        max_retries=2,
        retry_sleep=lambda seconds: slept.append(seconds),
    )
    harvest_all(harvester)
    assert slept, "a transient retry must apply the injected backoff before retrying"


# --- transient retries exhausted -> quarantine ---------------------------------------------------

def test_transient_error_exhausting_retries_is_quarantined_and_run_continues():
    # LAST_ID keeps failing past the retry budget -> it is dead-lettered, but the earlier base ids
    # (already yielded before the failure) still come through: one bad paper doesn't kill the run.
    source = FakeSource(errors={LAST_ID: (TransientError, 99)})
    quarantine = QuarantineSink()
    refs = harvest_all(make_harvester(source, quarantine=quarantine, max_retries=1))
    assert set(r.paper_id for r in refs) == {DUP_ID, MIDDLE_ID}
    assert quarantine.paper_ids == [LAST_ID]
    assert isinstance(quarantine.calls[0][1], TransientError)


# --- permanent -> quarantine ---------------------------------------------------------------------

def test_permanent_error_is_quarantined_and_run_continues():
    # A permanent failure on the last base id: earlier papers were already yielded, the bad one is
    # dead-lettered, and harvest completes without raising.
    source = FakeSource(errors={LAST_ID: PermanentError})
    quarantine = QuarantineSink()
    refs = harvest_all(make_harvester(source, quarantine=quarantine))
    assert set(r.paper_id for r in refs) == {DUP_ID, MIDDLE_ID}
    assert quarantine.paper_ids == [LAST_ID]
    assert isinstance(quarantine.calls[0][1], PermanentError)


# --- OG-49 L11: a truncated harvest logs a WARNING, still never raises -----------------------


def test_transient_exhausted_logs_a_truncation_warning(caplog):
    source = FakeSource(errors={LAST_ID: (TransientError, 99)})
    with caplog.at_level("WARNING", logger="rag.harvester"):
        refs = harvest_all(
            make_harvester(source, quarantine=QuarantineSink(), max_retries=1), cap=100
        )
    assert set(r.paper_id for r in refs) == {DUP_ID, MIDDLE_ID}  # never raises -- contract intact
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "truncated early" in warnings[0].message
    assert "cap was 100" in warnings[0].message
    assert LAST_ID in warnings[0].message


def test_permanent_error_logs_a_truncation_warning(caplog):
    source = FakeSource(errors={LAST_ID: PermanentError})
    with caplog.at_level("WARNING", logger="rag.harvester"):
        harvest_all(make_harvester(source, quarantine=QuarantineSink()), cap=50)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "truncated early" in warnings[0].message
    assert "cap was 50" in warnings[0].message
    assert LAST_ID in warnings[0].message


def test_no_truncation_warning_when_harvest_completes_cleanly(caplog):
    with caplog.at_level("WARNING", logger="rag.harvester"):
        harvest_all(make_harvester(FakeSource()))
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_permanent_error_is_not_retried():
    # A permanent error must go straight to quarantine — never consume the retry/backoff budget.
    source = FakeSource(errors={LAST_ID: PermanentError})
    slept = []
    harvester = Harvester(
        source,
        quarantine=QuarantineSink(),
        max_retries=5,
        retry_sleep=lambda seconds: slept.append(seconds),
    )
    harvest_all(harvester)
    assert slept == [], "a PermanentError must not be retried"


def test_arxiv_http_client_sends_descriptive_user_agent():
    """arXiv best-practice: automated clients must send a descriptive User-Agent so their team can
    identify the tool. The shared factory (used by both ArxivSource and the PDF prefetcher) must set
    one that names this tool, not the HTTP library's anonymous default."""
    from rag.harvester import arxiv_http_client

    client = arxiv_http_client(30.0)
    try:
        ua = client.headers.get("User-Agent", "")
        # tool name present => it's not the HTTP library's anonymous default UA
        assert "research-system-rag" in ua, f"expected tool name in User-Agent, got {ua!r}"
    finally:
        client.close()
