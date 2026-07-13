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
from contracts.errors import ContractError, PermanentError, TransientError
from contracts.gpu_lock import GpuLock

# The real TEI server enforces `max_client_batch_size=32` (empirically confirmed: 161 texts ->
# HTTP 422 "batch size 161 > maximum allowed batch size 32"; 32 texts -> HTTP 200). Not a tunable
# — it's the server's own hard ceiling, so `embed()` sub-batches to respect it.
_MAX_BATCH_SIZE = 32

# Same taxonomy split as rag/summarizer.py / rag/reranker.py: a rate-limited or momentarily-
# unhealthy server (or a real OOM in the embedding server, seen for real this session on a
# long-tail paper) is transient (retry, then quarantine); any other 4xx is this request's fault.
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class TeiEmbedder:
    """Real `Embedder` adapter: one or more batched HTTP calls per `embed()` invocation — split
    into groups of at most `_MAX_BATCH_SIZE` to respect the server's batch-size limit — through an
    injected client pointed at a TEI-style `/embed` endpoint (or a compatible server).

    Preconditions: none beyond `texts` being a list of `str` — an empty list is a valid, zero-cost
    call (returns `[]`), not a precondition violation (matches the frozen contract test).
    Postconditions: `len(output) == len(texts)`, order-preserving (`output[i]` is the vector for
    `texts[i]`) — holds across sub-batches too, since their results are concatenated back in the
    same order the inputs were split; every vector has `len == info.dim` and is L2-normalized —
    re-normalized here regardless of whether the server already does, so the invariant holds
    independent of server config. A response that violates either of these is `ContractError` (a
    broken invariant, not a per-paper failure — CONVENTIONS.md §4).
    Acquires `gpu_lock.acquire("embed")` once around all sub-batches (CONVENTIONS.md §6): from the
    caller's side `embed()` is still a single call, so the lock scope matches that.
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
            raw_vectors = []
            for start in range(0, len(texts), _MAX_BATCH_SIZE):
                batch = texts[start : start + _MAX_BATCH_SIZE]
                try:
                    response = self._client.post("/embed", json={"inputs": batch})
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    status = error.response.status_code
                    if status in _RETRYABLE_STATUSES:
                        raise TransientError(f"embedding server returned {status}") from error
                    raise PermanentError(f"embedding server returned {status}") from error
                except httpx.HTTPError as error:
                    raise TransientError(f"embedding request failed: {error}") from error
                raw_vectors.extend(response.json())

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
