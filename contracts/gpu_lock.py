"""GpuLock — cross-process COMPUTE serialization for GPU-bound stages (DATA-CONTRACTS.md
"GpuLock"). This serializes *inference calls*, not model residency — a model served by a
long-running process (TEI, Ollama) stays resident in VRAM after the call returns and the lock is
released. The "embedder/reranker/summarizer never co-reside" invariant is delivered by
stage-batched ingestion + explicit model eviction (ARCHITECTURE "Operational invariants" §3);
`GpuLock` is the separate cross-process call serializer (e.g. the always-on `McpServer`'s
reranker vs. a running ingest stage), not a substitute for it.

Why this exists: the single-GPU rule must hold across processes, not just within one —
`IngestionOrchestrator` and `McpServer` are separate composition roots that V0 explicitly allows
to run concurrently, so an in-process `threading.Lock` cannot be the mechanism. This is the one
interface-shaped type `contracts/` defines (everywhere else, `contracts/` holds only the data
shapes that cross a seam, not the module interfaces themselves) because DATA-CONTRACTS.md itself
defines it as a `Protocol`, not a dataclass — every real GPU-bound adapter's constructor must
accept one of these (grep-checked by T-F6).
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
