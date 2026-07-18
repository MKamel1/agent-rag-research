"""FileGpuLock — the real `GpuLock` adapter (DATA-CONTRACTS.md "GpuLock").

Wraps `filelock.FileLock` so any process constructing a `FileGpuLock` on the same `lock_path`
serializes against any other process doing the same — `IngestionOrchestrator` (M9) and
`McpServer` (M8) build theirs from the same `Config.gpu_lock_path` (default `.gpu.lock`), so they
contend on the same file by construction, not by convention. Not managed here: model residency or
eviction (contracts/gpu_lock.py's docstring) — this is a compute serializer only.
"""

from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import filelock

from contracts.errors import TransientError


class FileGpuLock:
    def __init__(self, lock_path: Path):
        self._lock_path = lock_path
        self._lock = filelock.FileLock(str(lock_path))

    def acquire(self, stage: str, *, timeout: float | None = None) -> AbstractContextManager[None]:
        # `stage` is a label only (GpuLock Protocol docstring). `timeout=None` (default) is
        # byte-identical to pre-timeout behavior: hand back the raw `FileLock` and let its own
        # context-manager protocol block-then-yield-then-release-on-exit, exactly as before this
        # parameter existed -- every existing caller that doesn't pass `timeout` is unaffected.
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
