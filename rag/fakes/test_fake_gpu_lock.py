"""Tests for FakeGpuLock (T-F4) — no-op context manager behavior and `.acquired` recording."""

from contracts.gpu_lock import GpuLock
from rag.fakes.fake_gpu_lock import FakeGpuLock


def test_satisfies_the_gpu_lock_protocol():
    assert isinstance(FakeGpuLock(), GpuLock)


def test_acquire_yields_a_context_manager_that_does_not_block_or_error():
    lock = FakeGpuLock()
    with lock.acquire("embed"):
        pass  # must not block, error, or require any real resource


def test_acquire_records_stage_in_acquired():
    lock = FakeGpuLock()
    with lock.acquire("embed"):
        pass
    assert lock.acquired == ["embed"]


def test_sequential_acquires_all_record_correctly():
    lock = FakeGpuLock()
    with lock.acquire("embed"):
        pass
    with lock.acquire("rerank"):
        pass
    with lock.acquire("summarize"):
        pass
    assert lock.acquired == ["embed", "rerank", "summarize"]


def test_nested_acquires_all_record_correctly():
    lock = FakeGpuLock()
    with lock.acquire("outer"):
        with lock.acquire("inner"):
            pass
    assert lock.acquired == ["outer", "inner"]


def test_context_manager_still_releases_on_exception():
    lock = FakeGpuLock()
    try:
        with lock.acquire("embed"):
            raise ValueError("boom")
    except ValueError:
        pass
    assert lock.acquired == ["embed"]
