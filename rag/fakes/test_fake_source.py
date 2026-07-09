"""Tests for FakeSource (T-F4) — fixture loading, the v1/v2 dedup pair, and error injection.

Uses the default fixture (`fixtures/harvester/paper_refs.json`), which is committed specifically
so a future Harvester dedup-by-base-id test (T-A1) has a real duplicate to dedupe, per
TEST-STRATEGY.md's `FakeSource` bullet.
"""

import pytest

from contracts.errors import PermanentError, TransientError
from rag.fakes.fake_source import FakeSource


def test_yields_all_fixture_refs_up_to_cap():
    source = FakeSource()
    refs = list(source.fetch(focus_area=["causal inference"], cap=100, ordering="freshest_first"))
    assert len(refs) == 4
    assert {r.paper_id for r in refs} == {"2506.01234", "2507.05678", "2504.09999"}


def test_cap_limits_number_of_refs_yielded():
    source = FakeSource()
    refs = list(source.fetch(focus_area=["x"], cap=2, ordering="freshest_first"))
    assert len(refs) == 2


def test_fixture_contains_v1_and_v2_of_the_same_base_paper_id():
    source = FakeSource()
    refs = list(source.fetch(focus_area=["x"], cap=100, ordering="freshest_first"))
    versions_by_paper_id: dict[str, set[str]] = {}
    for r in refs:
        versions_by_paper_id.setdefault(r.paper_id, set()).add(r.version)
    dup_base_ids = {pid for pid, versions in versions_by_paper_id.items() if len(versions) > 1}
    assert dup_base_ids, "fixture must contain >=1 base paper_id with more than one version"
    assert versions_by_paper_id["2506.01234"] == {"v1", "v2"}


def test_error_injection_raises_mapped_error_for_mapped_paper_id():
    source = FakeSource(errors={"2507.05678": TransientError})
    with pytest.raises(TransientError):
        list(source.fetch(focus_area=["x"], cap=100, ordering="freshest_first"))


def test_error_injection_accepts_an_exception_instance():
    injected = PermanentError("bad paper")
    source = FakeSource(errors={"2507.05678": injected})
    with pytest.raises(PermanentError) as exc_info:
        list(source.fetch(focus_area=["x"], cap=100, ordering="freshest_first"))
    assert exc_info.value is injected


def test_error_injection_does_not_affect_other_ids():
    # Only "2507.05678" is mapped; fetching with a cap that stops before reaching it must yield
    # cleanly with no error.
    source = FakeSource(errors={"2507.05678": TransientError})
    refs = list(source.fetch(focus_area=["x"], cap=2, ordering="freshest_first"))
    assert [r.paper_id for r in refs] == ["2506.01234", "2506.01234"]


def test_error_injection_yields_earlier_refs_before_raising():
    source = FakeSource(errors={"2507.05678": TransientError})
    it = source.fetch(focus_area=["x"], cap=100, ordering="freshest_first")
    yielded = []
    with pytest.raises(TransientError):
        for ref in it:
            yielded.append(ref.paper_id)
    assert yielded == ["2506.01234", "2506.01234"]
