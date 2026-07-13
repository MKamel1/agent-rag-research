"""FileGpuLock — the real `GpuLock` adapter (DATA-CONTRACTS.md "GpuLock").

Wraps `filelock.FileLock` so any process constructing a `FileGpuLock` on the same `lock_path`
serializes against any other process doing the same — `IngestionOrchestrator` (M9) and
`McpServer` (M8) build theirs from the same `Config.gpu_lock_path` (default `.gpu.lock`), so they
contend on the same file by construction, not by convention. Not managed here: model residency or
eviction (contracts/gpu_lock.py's docstring) — this is a compute serializer only.
"""

from contextlib import AbstractContextManager
from pathlib import Path

import filelock


class FileGpuLock:
    def __init__(self, lock_path: Path):
        self._lock = filelock.FileLock(str(lock_path))

    def acquire(self, stage: str) -> AbstractContextManager[None]:
        # `stage` is a label only (GpuLock Protocol docstring) -- FileLock's own context-manager
        # protocol already blocks-then-yields-then-releases-on-exit, so no wrapper logic is needed
        # beyond handing it back directly.
        return self._lock
