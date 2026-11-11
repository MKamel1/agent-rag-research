"""FileGpuLock — the real `GpuLock` adapter (DATA-CONTRACTS.md "GpuLock").

Wraps `filelock.FileLock` so any process constructing a `FileGpuLock` on the same `lock_path`
serializes against any other process doing the same — `IngestionOrchestrator` (M9) and
`McpServer` (M8) build theirs from the same `Config.gpu_lock_path` (default `.gpu.lock`), so they
contend on the same file by construction, not by convention. Not managed here: model residency or
eviction (contracts/gpu_lock.py's docstring) — this is a compute serializer only.

OP-5: after a successful acquire the holder's pid, command, stage label and start time are written
to `<lock_path>.holder` (JSON); the record is removed just before release. It is metadata only --
acquire/release semantics, timeouts, blocking behaviour and exceptions are exactly `filelock`'s.
A failure to write or remove the record is logged and swallowed; it never fails an acquire. A
crashed holder leaves a stale record behind: `read_holder()` only reports a record whose pid is
still alive, and the next acquire overwrites it.
"""

import json
import logging
import os
import sys
import time
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import filelock

from contracts.errors import TransientError

logger = logging.getLogger(__name__)


def holder_path(lock_path: Path) -> Path:
    return lock_path.with_name(lock_path.name + ".holder")


def read_holder(lock_path: Path) -> dict | None:
    """Who recorded themselves as holding `lock_path` -- `{pid, command, stage, since}` -- or None
    if there is no record, it is unreadable, or its pid is no longer alive (crashed holder)."""
    try:
        record = json.loads(holder_path(lock_path).read_text())
        pid = int(record["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass  # alive, owned by another user
    return record


class _HolderRecordingLock(filelock.FileLock):
    """`filelock.FileLock` that records its holder after a *new* acquisition and clears it before
    the final release. Re-entrant acquires (counter > 1) neither rewrite nor clear it."""

    stage = ""

    def acquire(self, *args, **kwargs):
        proxy = super().acquire(*args, **kwargs)  # blocks / raises Timeout exactly as before
        if self.lock_counter == 1:
            try:
                record = {
                    "pid": os.getpid(),
                    "command": " ".join(sys.argv)[:200],
                    "stage": self.stage,
                    "since": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
                holder_path(Path(self.lock_file)).write_text(json.dumps(record))
            except OSError as error:
                logger.warning("gpu lock holder record not written: %s", error)
        return proxy

    def release(self, force: bool = False):
        if self.is_locked and (self.lock_counter == 1 or force):
            try:
                holder_path(Path(self.lock_file)).unlink(missing_ok=True)
            except OSError as error:
                logger.warning("gpu lock holder record not removed: %s", error)
        super().release(force=force)


class FileGpuLock:
    def __init__(self, lock_path: Path):
        self._lock_path = lock_path
        self._lock = _HolderRecordingLock(str(lock_path))

    def acquire(self, stage: str, *, timeout: float | None = None) -> AbstractContextManager[None]:
        # `stage` is a label only (GpuLock Protocol docstring). `timeout=None` (default) is
        # byte-identical to pre-timeout behavior: hand back the raw `FileLock` and let its own
        # context-manager protocol block-then-yield-then-release-on-exit, exactly as before this
        # parameter existed -- every existing caller that doesn't pass `timeout` is unaffected.
        self._lock.stage = stage
        if timeout is None:
            return self._lock
        return self._acquire_with_timeout(stage, timeout)

    @contextmanager
    def _acquire_with_timeout(self, stage: str, timeout: float):
        try:
            with self._lock.acquire(timeout=timeout):
                yield
        except filelock.Timeout as error:
            raise TransientError(
                f"gpu lock {self._lock_path} not acquired within {timeout}s for stage {stage!r} "
                "-- likely held by a stale or wedged process; check for a stuck holder before "
                "retrying"
            ) from error
