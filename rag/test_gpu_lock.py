"""Tests for FileGpuLock — the real GpuLock adapter. Runs in default CI: no GPU, no network, just
local temp files (contracts/gpu_lock.py's Protocol; DATA-CONTRACTS.md "GpuLock")."""

import filelock
import pytest

from rag.gpu_lock import FileGpuLock


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
