"""GpuLock — cross-process serialization for GPU-bound stages (DATA-CONTRACTS.md "GpuLock").

Why this exists: the single-GPU rule (ARCHITECTURE "Operational invariants" §3, CONVENTIONS §6)
must hold across processes, not just within one — `IngestionOrchestrator` and `McpServer` are
separate composition roots that V0 explicitly allows to run concurrently, so an in-process
`threading.Lock` cannot be the mechanism. `GpuLock` is a **compute serializer only**: it stops two
GPU-bound inference calls from *executing* at the same instant. It does not manage model
residency or eviction — the embedder, summarizer, and reranker are expected to co-reside in VRAM
for the life of the process (ARCHITECTURE §3); the lock exists so their calls don't overlap. This
is the one interface-shaped type `contracts/` defines (everywhere else, `contracts/` holds only
the data shapes that cross a seam, not the module interfaces themselves) because DATA-CONTRACTS.md
itself defines it as a `Protocol`, not a dataclass — every real GPU-bound adapter's constructor
must accept one of these (grep-checked by T-F6 as a necessary prefilter; TEST-STRATEGY.md's
`FakeGpuLock.acquired` assertion is what actually proves `acquire()` wraps inference).
"""

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable


@runtime_checkable
class GpuLock(Protocol):
    def acquire(
        self, stage: str, *, timeout: float | None = None
    ) -> AbstractContextManager[None]:
        """Blocks until the single GPU slot is free, then yields; releases on exit (incl. on
        exception). `stage` is a label ("embed" | "rerank" | "summarize") used only for
        logging/timeout messages.

        Reliability-audit gap (FOUNDATION, minimal diff): `timeout` (seconds, keyword-only) bounds
        how long to wait for a wedged/crashed holder before giving up. `None` (the default)
        preserves today's behavior exactly — block forever — so every existing caller/adapter is
        unaffected. A finite `timeout` that elapses before the lock is free raises `TransientError`
        (a caller can retry/surface it) instead of hanging the process forever.
        """
        ...
