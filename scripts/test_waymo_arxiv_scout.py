"""Offline unit tests for waymo_arxiv_scout.py — canned data only, no network calls, same pattern
as rag/test_harvester_arxiv_source.py.

Atom-parsing coverage lives in rag/test_harvester_arxiv_source.py (tests ArxivSource._parse_entries
directly) and is deliberately not duplicated here."""
from datetime import date

import pytest

from contracts.errors import TransientError
from contracts.harvester import PaperRef
from rag.harvester import Harvester
import waymo_arxiv_scout as scout_mod
from waymo_arxiv_scout import (
    ALREADY_CAPTURED_IDS,
    _TOPIC_QUERIES,
    _fetch_page_with_retry,
    _is_modern_arxiv_id,
    _run_query,
    dedup_by_id,
    score_text,
)


def _make_ref(paper_id="1234.5678", **overrides):
    defaults = dict(
        paper_id=paper_id, version="v1", title="Title", abstract="Abstract",
        authors=["A. Author"], categories=["cs.LG"],
        published=date(2024, 1, 1), updated=date(2024, 1, 1),
        pdf_url=f"https://arxiv.org/pdf/{paper_id}",
    )
    defaults.update(overrides)
    return PaperRef(**defaults)


def test_score_text_sums_matched_keyword_weights():
    text = "bayesian rare event crash rate importance sampling autonomous vehicle"
    # bayesian=2, rare event=4, crash rate=4, importance sampling=4, autonomous vehicle=2
    assert score_text(text) == 2 + 4 + 4 + 4 + 2


def test_score_text_zero_for_no_keyword_match():
    assert score_text("a generic paper about unrelated topics") == 0


def test_dedup_by_id_keeps_first_occurrence_highest_fields():
    a = _make_ref(paper_id="1234.5678", title="First")
    b = _make_ref(paper_id="1234.5678", title="Duplicate")
    c = _make_ref(paper_id="9999.0001", title="Different")
    result = dedup_by_id([a, b, c])
    assert len(result) == 2
    assert [r.paper_id for r in result] == ["1234.5678", "9999.0001"]
    assert result[0].title == "First"


def test_already_captured_ids_is_empty():
    # §5 of the v2 plan: this list is a *seed/priority* list now, not an exclusion list -- treating
    # it as an exclusion list is what kept every Waymo-authored paper out of the corpus.
    assert len(ALREADY_CAPTURED_IDS) == 0


def test_is_modern_arxiv_id_rejects_legacy_ids():
    assert _is_modern_arxiv_id("9304006") is False
    assert _is_modern_arxiv_id("hep-th/9304006") is False
    assert _is_modern_arxiv_id("2504.09999") is True
    assert _is_modern_arxiv_id("2011.00038") is True


def test_score_text_scores_new_scope_keywords():
    # waymax=5, sim agents=4, sotif=4 (docs/ONBOARDING_AND_ARXIV_KEYWORDS.md §2b.3)
    assert score_text("waymax sim agents sotif") == 5 + 4 + 4


def test_topic_queries_cover_every_scope_area():
    assert len(_TOPIC_QUERIES) == 36
    joined = " ".join(_TOPIC_QUERIES).lower()
    for term in (
        "sotif",
        "ul 4600",
        "pegasus",
        "scenario generation",
        "sim-to-real",
        "traffic simulation",
        "waymax",
    ):
        assert term in joined, term


def test_fetch_page_with_retry_retries_on_transient_then_succeeds():
    calls = []

    class FlakySource:
        def _fetch_page(self, query, start, page_cap, ordering):
            calls.append(1)
            if len(calls) < 3:
                raise TransientError("arXiv API returned 503")
            return [_make_ref()]

    sleeps = []
    result = _fetch_page_with_retry(FlakySource(), "abs:test", 0, 25, sleeps.append)
    assert len(result) == 1
    assert len(calls) == 3
    assert sleeps == [Harvester._backoff(1), Harvester._backoff(2)]


def test_fetch_page_with_retry_raises_after_max_attempts():
    class AlwaysFailsSource:
        def _fetch_page(self, query, start, page_cap, ordering):
            raise TransientError("arXiv API returned 429")

    with pytest.raises(TransientError):
        _fetch_page_with_retry(AlwaysFailsSource(), "abs:test", 0, 25, lambda s: None)


def test_run_query_sleeps_between_pages_but_skips_only_the_first_fetch_overall():
    """A shared `first` flag threaded across `_run_query` calls (as `scout()` does across its
    query loop) must skip the pre-sleep only before the single very first page-fetch of the whole
    run -- not once per query. Mirrors rag/test_harvester_arxiv_source.py's
    test_fetch_applies_rate_limit_sleep_between_requests_across_focus_area_entries."""

    class EmptySource:
        def _fetch_page(self, query, start, page_cap, ordering):
            return []  # each query's first page is immediately exhausted

    sleeps = []
    first = [True]
    source = EmptySource()
    _run_query(source, "query-a", sleeps.append, first)
    _run_query(source, "query-b", sleeps.append, first)
    _run_query(source, "query-c", sleeps.append, first)
    # 3 queries, one fetch each -> 2 sleeps (before query-b's and query-c's fetch); never before
    # query-a's, the very first fetch of the whole run.
    assert sleeps == [scout_mod._RATE_LIMIT_SECONDS, scout_mod._RATE_LIMIT_SECONDS]


class _FakeArxivSource:
    """Stands in for rag.harvester.ArxivSource at the `scout()` level: exposes only the
    `_fetch_page` surface `_fetch_page_with_retry` calls, no network. Each distinct query
    returns exactly one paper on its first page, then exhausts."""

    def __init__(self, sleep=None):
        self.calls = []

    def _fetch_page(self, query, start, page_cap, ordering):
        self.calls.append(query)
        if start > 0:
            return []
        return [_make_ref(paper_id=f"2401.{len(self.calls):04d}", title="rare event paper")]


def test_scout_emits_candidates_keyed_by_id_not_paper_id(monkeypatch):
    """Finding 1: Task 3's brief reads candidates.json as `c['id']`; PaperRef's own field is
    `paper_id`. scout() must not leak the raw model_dump shape into its output."""
    monkeypatch.setattr(scout_mod, "ArxivSource", _FakeArxivSource)
    monkeypatch.setattr(scout_mod, "_TOPIC_QUERIES", ['abs:"rare event"'])
    monkeypatch.setattr(scout_mod, "_AUTHOR_QUERIES", [])
    candidates = scout_mod.scout(sleep=lambda s: None)
    assert len(candidates) == 1
    c = candidates[0]
    assert set(c) == {"id", "title", "authors", "categories", "published", "score"}
    assert c["id"] == "2401.0001"
    assert c["published"] == "2024-01-01"


class _EmptyPageArxivSource:
    """Like `_FakeArxivSource`, but every query is exhausted on its first (empty) page -- one
    fetch per query, same shape as rag/test_harvester_arxiv_source.py's cross-term rate-limit
    test ("3 requests total... -> 2 sleeps")."""

    def __init__(self, sleep=None):
        self.calls = []

    def _fetch_page(self, query, start, page_cap, ordering):
        self.calls.append(query)
        return []


def test_scout_sleeps_between_queries_but_skips_only_the_first_fetch_overall(monkeypatch):
    """Finding 2, at the `scout()` integration level: with 3 queries (2 topic + 1 author) each
    exhausted on their first page, only 2 sleeps happen -- never before the very first fetch."""
    sleeps = []
    monkeypatch.setattr(scout_mod, "ArxivSource", _EmptyPageArxivSource)
    monkeypatch.setattr(scout_mod, "_TOPIC_QUERIES", ['abs:"rare event"', 'abs:"crash rate"'])
    monkeypatch.setattr(scout_mod, "_AUTHOR_QUERIES", ["au:Kusano_K"])
    scout_mod.scout(sleep=sleeps.append)
    assert sleeps == [scout_mod._RATE_LIMIT_SECONDS, scout_mod._RATE_LIMIT_SECONDS]
