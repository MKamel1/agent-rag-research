"""M4 Embedder output (DATA-CONTRACTS.md "M4 Embedder output").

`Embedder.embed(texts) -> list[Vector]` and `Embedder.info -> EmbedderInfo` are the module's own
interface (ARCHITECTURE.md, owned by Owner C) — `contracts/` only defines the data shapes that
cross the seam, not the module interface itself (see `contracts/gpu_lock.py` for the one
interface-shaped exception, `GpuLock`, which DATA-CONTRACTS.md defines as a `Protocol`
explicitly).
"""

from pydantic import Field

from contracts._base import FrozenModel

Vector = list[float]  # L2-normalized; length == EmbedderInfo.dim


class EmbedderInfo(FrozenModel):
    model_id: str  # e.g. "Qwen3-Embedding-4B"
    dim: int = Field(gt=0)  # e.g. 2560
    version: str  # bump when weights/config change -> invalidates the vector collection
