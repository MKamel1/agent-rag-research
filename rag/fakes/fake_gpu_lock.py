"""FakeGpuLock — the default `GpuLock` dependency for every zero-GPU test of the real
Embedder/Summarizer/Reranker adapters and of `IngestionOrchestrator`/`Retriever` (T-F4).

Implements `contracts.gpu_lock.GpuLock` exactly: `acquire(stage: str) ->
AbstractContextManager[None]`. `GpuLock` is the one interface-shaped `Protocol` `contracts/`
defines (see that module's docstring) — this fake satisfies it structurally (it's
`@runtime_checkable`), no explicit subclassing needed.
"""

from contextlib import AbstractContextManager, nullcontext


class FakeGpuLock:
    """No-op context manager — never blocks, never touches a real file or process. Records each
    `stage` label passed to `.acquire(stage)` into `.acquired`, in call order, so a test can
    assert a GPU-bound call actually acquired the lock, without a real lock file.
    """

    def __init__(self):
        self.acquired: list[str] = []

    def acquire(self, stage: str, *, timeout: float | None = None) -> AbstractContextManager[None]:
        # `timeout` accepted (matching the real `GpuLock` Protocol, contracts/gpu_lock.py) but
        # ignored -- this fake never blocks, so there is nothing to time out against. Needed since
        # OG-48#4 threads a bounded timeout through TeiEmbedder/TeiReranker's real `.acquire()`
        # calls; without this param every test constructing them with a FakeGpuLock would TypeError.
        self.acquired.append(stage)
        return nullcontext()
