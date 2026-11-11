"""Tests for FileGpuLock — the real GpuLock adapter. Runs in default CI: no GPU, no network, just
local temp files (contracts/gpu_lock.py's Protocol; DATA-CONTRACTS.md "GpuLock")."""

import os

import filelock
import pytest

from contracts.errors import TransientError
from contracts.gpu_lock import GpuLock
from rag.gpu_lock import FileGpuLock, holder_path, read_holder


def test_file_gpu_lock_satisfies_the_gpu_lock_protocol(tmp_path):
    """Protocol conformance (DATA-CONTRACTS.md "GpuLock"): the real adapter must structurally
    satisfy `GpuLock` (it's `@runtime_checkable`) -- same check `rag/fakes/test_fake_gpu_lock.py`
    already runs for `FakeGpuLock`. Both sides of the fake/real pair need this; only the fake one
    existed before this test."""
    assert isinstance(FileGpuLock(tmp_path / "x.lock"), GpuLock)


def test_basic_enter_and_exit_is_clean(tmp_path):
    lock = FileGpuLock(tmp_path / "x.lock")
    with lock.acquire("embed"):
        pass  # entering and exiting without error is the whole assertion


def test_releases_on_exception(tmp_path):
    lock_path = tmp_path / "x.lock"
    lock = FileGpuLock(lock_path)
    with pytest.raises(ValueError):
        with lock.acquire("embed"):
            raise ValueError("boom")
    # a fresh FileLock on the same path can acquire immediately -- proves the first released
    fresh = filelock.FileLock(str(lock_path))
    with fresh.acquire(timeout=0):
        pass


def test_two_instances_on_the_same_path_are_mutually_exclusive(tmp_path):
    """The load-bearing property: FileGpuLock must serialize across independent instances (this
    is what makes it a real cross-process lock and not just an in-process convenience)."""
    lock_path = tmp_path / "shared.lock"
    a = FileGpuLock(lock_path)
    b = FileGpuLock(lock_path)

    with a.acquire("embed"):
        # b.acquire("rerank") returns the same underlying FileLock a's is built on (same path) --
        # call the underlying lock's own acquire(timeout=0) directly, since FileGpuLock's own
        # Protocol-conforming acquire() takes no timeout argument.
        with pytest.raises(filelock.Timeout):
            with b.acquire("rerank").acquire(timeout=0):
                pass  # never reached -- b must fail to acquire while a holds the lock

    # after a releases, b can now acquire cleanly
    with b.acquire("rerank"):
        pass


def test_different_paths_do_not_contend(tmp_path):
    a = FileGpuLock(tmp_path / "a.lock")
    b = FileGpuLock(tmp_path / "b.lock")
    with a.acquire("embed"):
        with b.acquire("summarize"):  # different file -- must not raise
            pass


# ---------------------------------------------------------------------------
# Reliability-audit gap (FOUNDATION, contracts/gpu_lock.py): unbounded `acquire()` hangs forever if
# a process crashes/wedges holding the lock. `timeout` (seconds, keyword-only) bounds the wait and
# raises `TransientError` instead. No real GPU/live lock involved -- a temp lock file held by this
# test process itself stands in for the "stale holder" (HARD GUARDRAILS: never touch the real
# `.gpu.lock` in the production data dir).
# ---------------------------------------------------------------------------


def test_acquire_with_timeout_raises_transient_error_when_lock_is_held(tmp_path):
    lock_path = tmp_path / "held.lock"
    holder = FileGpuLock(lock_path)
    contender = FileGpuLock(lock_path)

    with holder.acquire("embed"):
        with pytest.raises(TransientError):
            with contender.acquire("rerank", timeout=0.05):
                pass  # never reached -- the holder still has the lock


def test_acquire_with_timeout_succeeds_when_lock_is_free(tmp_path):
    lock = FileGpuLock(tmp_path / "free.lock")
    with lock.acquire("embed", timeout=1.0):
        pass  # entering and exiting without error is the whole assertion


def test_acquire_without_timeout_still_blocks_forever_by_default(tmp_path):
    """`timeout=None` (the default, unchanged) must still hand back the raw, block-forever
    `FileLock` -- byte-identical to pre-timeout behavior -- not a new always-bounded wrapper.
    Same proof shape as test_two_instances_on_the_same_path_are_mutually_exclusive: a SEPARATE
    instance's zero-timeout probe must still see the lock as held, meaning `acquire()` (no
    `timeout` kwarg) did not silently start enforcing some default bound of its own.
    """
    lock_path = tmp_path / "default.lock"
    holder = FileGpuLock(lock_path)
    contender = FileGpuLock(lock_path)
    with holder.acquire("embed"):
        with pytest.raises(filelock.Timeout):
            with contender.acquire("rerank").acquire(timeout=0):
                pass


# ---------------------------------------------------------------------------
# OP-5: holder record. Metadata only -- the tests above (unchanged) prove acquire/release/timeout
# behaviour; the ones below prove the record and that it can never change those outcomes.
# ---------------------------------------------------------------------------


def test_holder_record_is_written_on_acquire_and_cleared_on_release(tmp_path):
    lock_path = tmp_path / "x.lock"
    lock = FileGpuLock(lock_path)
    assert read_holder(lock_path) is None
    with lock.acquire("embed"):
        record = read_holder(lock_path)
        assert record["pid"] == os.getpid() and record["stage"] == "embed"
        assert record["command"] and record["since"]
    assert read_holder(lock_path) is None
    assert not holder_path(lock_path).exists()


def test_holder_record_is_written_with_a_timeout_and_cleared_on_exception(tmp_path):
    lock_path = tmp_path / "x.lock"
    lock = FileGpuLock(lock_path)
    with pytest.raises(ValueError):
        with lock.acquire("rerank", timeout=1.0):
            assert read_holder(lock_path)["stage"] == "rerank"
            raise ValueError("boom")
    assert not holder_path(lock_path).exists()


def test_failed_acquire_leaves_the_real_holders_record_alone(tmp_path):
    lock_path = tmp_path / "x.lock"
    holder, contender = FileGpuLock(lock_path), FileGpuLock(lock_path)
    with holder.acquire("embed"):
        with pytest.raises(TransientError, match="not acquired within 0.05s for stage 'rerank'"):
            with contender.acquire("rerank", timeout=0.05):
                pass
        assert read_holder(lock_path)["stage"] == "embed"
    assert not holder_path(lock_path).exists()


def test_reentrant_acquire_keeps_the_record_until_the_outer_release(tmp_path):
    lock_path = tmp_path / "x.lock"
    lock = FileGpuLock(lock_path)
    with lock.acquire("embed"):
        with lock.acquire("embed"):
            pass
        assert read_holder(lock_path) is not None
    assert read_holder(lock_path) is None


def test_stale_record_from_a_dead_pid_is_ignored_and_overwritten_by_the_next_acquire(tmp_path):
    lock_path = tmp_path / "x.lock"
    holder_path(lock_path).write_text(
        '{"pid": 2147483646, "command": "gone", "stage": "embed", "since": "x"}'
    )
    assert read_holder(lock_path) is None
    with FileGpuLock(lock_path).acquire("rerank"):
        assert read_holder(lock_path)["pid"] == os.getpid()


@pytest.mark.parametrize("junk", ["", "not json", "[]", '{"pid": "x"}', "{}"])
def test_unreadable_record_reads_as_none(tmp_path, junk):
    lock_path = tmp_path / "x.lock"
    holder_path(lock_path).write_text(junk)
    assert read_holder(lock_path) is None


def test_unwritable_holder_record_never_fails_the_acquire(tmp_path):
    lock_path = tmp_path / "x.lock"
    holder_path(lock_path).mkdir()  # write_text -> IsADirectoryError, an OSError
    lock = FileGpuLock(lock_path)
    with lock.acquire("embed"):
        pass
    with lock.acquire("embed", timeout=1.0):
        pass
    with pytest.raises(filelock.Timeout):
        with lock.acquire("x"):
            with FileGpuLock(lock_path).acquire("y").acquire(timeout=0):
                pass


def test_default_acquire_still_returns_a_filelock(tmp_path):
    """No-timeout callers still get a raw `filelock.FileLock` (a subclass), as before."""
    assert isinstance(FileGpuLock(tmp_path / "x.lock").acquire("embed"), filelock.FileLock)
