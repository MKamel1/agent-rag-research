"""GpuLock — cross-process serialization for GPU-bound stages (DATA-CONTRACTS.md "GpuLock").

Why this exists: the single-GPU rule (ARCHITECTURE "Operational invariants" §3, CONVENTIONS §6)
must hold across processes, not just within one — `IngestionOrchestrator` and `McpServer` are
separate composition roots that V0 explicitly allows to run concurrently, so an in-process
`threading.Lock` cannot be the mechanism. This is the one interface-shaped type `contracts/`
defines (everywhere else, `contracts/` holds only the data shapes that cross a seam, not the
module interfaces themselves) because DATA-CONTRACTS.md itself defines it as a `Protocol`, not a
dataclass — every real GPU-bound adapter's constructor must accept one of these (grep-checked by
T-F6).
"""

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable


@runtime_checkable
class GpuLock(Protocol):
    def acquire(self, stage: str) -> AbstractContextManager[None]:
        """Blocks until the single GPU slot is free, then yields; releases on exit (incl. on
        exception). `stage` is a label ("embed" | "rerank" | "summarize") used only for
        logging/timeout messages.
        """
        ...
