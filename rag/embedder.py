"""TeiEmbedder — the real `Embedder` adapter (T-C3, M4) over the batching-optimized embedding
server (TEI/Infinity per PRD ADR-03; vLLM's OpenAI-compatible embeddings endpoint is the eventual
convergence point per ADR-09).

The final embedding model (Qwen3-Embedding-4B vs. BGE-M3) is a still-open Spike-2 decision
(PHASE0-RUNBOOK.md) — this adapter never hardcodes a model name or dimension. It is generic over
whichever `EmbedderInfo` its composition root constructs it with, so it works unchanged whichever
model Spike 2 locks in.

Vendor isolation (CONVENTIONS.md §1): this is the only module allowed to name the embedding
serving stack ("vllm" — ADR-09's convergence point; see `ci/checks/vendor_isolation.py`'s
`VENDOR_RULES`, which already allowlists it here). The adapter talks to the server over plain
HTTP (`httpx`, already a core dependency), so no vendor SDK import is needed.
"""

import math

import httpx

from contracts.embedder import EmbedderInfo, Vector
from contracts.errors import ContractError
from contracts.gpu_lock import GpuLock


class TeiEmbedder:
    """Real `Embedder` adapter: one batched HTTP call per `embed()` invocation, through an
    injected client pointed at a TEI-style `/embed` endpoint (or a compatible server).

    Preconditions: none beyond `texts` being a list of `str` — an empty list is a valid, zero-cost
    call (returns `[]`), not a precondition violation (matches the frozen contract test).
    Postconditions: `len(output) == len(texts)`, order-preserving (`output[i]` is the vector for
    `texts[i]`); every vector has `len == info.dim` and is L2-normalized — re-normalized here
    regardless of whether the server already does, so the invariant holds independent of server
    config. A response that violates either of these is `ContractError` (a broken invariant, not
    a per-paper failure — CONVENTIONS.md §4).
    Acquires `gpu_lock.acquire("embed")` around the batch call only (CONVENTIONS.md §6).
    """

    def __init__(self, client: httpx.Client, gpu_lock: GpuLock, info: EmbedderInfo):
        self._client = client
        self._gpu_lock = gpu_lock
        self._info = info

    @property
    def info(self) -> EmbedderInfo:
        return self._info

    def embed(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []

        with self._gpu_lock.acquire("embed"):
            response = self._client.post("/embed", json={"inputs": texts})
            response.raise_for_status()
            raw_vectors = response.json()

        if len(raw_vectors) != len(texts):
            raise ContractError(
                f"embedding server returned {len(raw_vectors)} vectors for {len(texts)} inputs"
            )
        return [self._normalize(v) for v in raw_vectors]

    def _normalize(self, vector: list[float]) -> Vector:
        if len(vector) != self._info.dim:
            raise ContractError(
                f"embedding server returned a {len(vector)}-dim vector, expected {self._info.dim}"
            )
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:
            raise ContractError("embedding server returned an all-zero vector")
        return [x / norm for x in vector]
