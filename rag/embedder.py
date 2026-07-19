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
import time
from collections.abc import Callable

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

# Reliability-audit gap: unlike the ingest side (rag/harvester.py's Harvester, rag/orchestrator.py's
# IngestionOrchestrator), the query path used to raise on the FIRST transient failure — one TEI
# hiccup (429/502/503/504/timeout) failed a user's whole search. Bounded retry-with-backoff below,
# same shape (`max_retries`, injected `retry_sleep`, `2 ** (attempt - 1)` backoff) as those two
# ingest call sites, so this codebase has one retry idiom, not two. `PermanentError` is never
# retried.
RetrySleep = Callable[[float], None]

# OG-48#4: how long `embed()` waits for a wedged/crashed GpuLock holder before giving up (raises
# TransientError instead of hanging forever) -- see `contracts/gpu_lock.py`'s `timeout` param.
# Generous enough that a legitimate long ingest batch holding the lock doesn't trip it, bounded
# enough that a query never hangs indefinitely behind a dead holder. `app/assembly.py` is the one
# composition root that could override this per-caller; nothing does today (both build sites use
# the default), so this constant is that default, not a hardcoded-everywhere value.
_DEFAULT_GPU_LOCK_TIMEOUT_S = 300.0


def _default_retry_sleep(seconds: float) -> None:
    time.sleep(seconds)


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

    A `TransientError` from any one sub-batch's HTTP call gets a bounded, backed-off retry
    (`max_retries`, `retry_sleep` — same shape as `rag/harvester.py`'s `Harvester`); a
    `PermanentError` is never retried. Unlike the ingest-side retry sites, there is no quarantine
    outcome here — a query-path caller has no "skip this paper and continue" fallback, so once the
    retry budget is exhausted the (still-classified) error simply propagates.

    OG-48#3: `gpu_lock.acquire("embed")` is held only around a SINGLE HTTP attempt (one sub-batch,
    one try) — never across the retry/backoff loop. Before this fix the lock was held for the
    whole `embed()` call, including every backoff sleep between retries; a flaky TEI call on the
    query path could hold the cross-process `FileGpuLock` for minutes while sleeping, blocking a
    concurrent ingest's GPU stage the entire time (ingest acquires the same lock with no timeout).
    Re-acquiring per attempt means the lock is free during every backoff sleep, and — OG-48#4 — a
    bounded `gpu_lock_timeout` (ctor param, default `_DEFAULT_GPU_LOCK_TIMEOUT_S`) is threaded into
    every acquire, so waiting for a wedged/crashed holder raises `TransientError` instead of
    blocking forever.
    """

    def __init__(
        self,
        client: httpx.Client,
        gpu_lock: GpuLock,
        info: EmbedderInfo,
        *,
        max_retries: int = 2,
        retry_sleep: RetrySleep | None = None,
        gpu_lock_timeout: float | None = _DEFAULT_GPU_LOCK_TIMEOUT_S,
    ):
        self._client = client
        self._gpu_lock = gpu_lock
        self._info = info
        self._max_retries = max_retries
        self._retry_sleep = retry_sleep or _default_retry_sleep
        self._gpu_lock_timeout = gpu_lock_timeout

    @property
    def info(self) -> EmbedderInfo:
        return self._info

    def embed(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []

        raw_vectors = []
        for start in range(0, len(texts), _MAX_BATCH_SIZE):
            batch = texts[start : start + _MAX_BATCH_SIZE]
            raw_vectors.extend(self._post_batch_with_retry(batch))

        if len(raw_vectors) != len(texts):
            raise ContractError(
                f"embedding server returned {len(raw_vectors)} vectors for {len(texts)} inputs"
            )
        return [self._normalize(v) for v in raw_vectors]

    def _post_batch_with_retry(self, batch: list[str]) -> list:
        """One sub-batch's `/embed` call, retried up to `_max_retries` times on `TransientError`
        (429/502/503/504, timeout, connection failure) with exponential backoff between attempts —
        same two-outcome shape as `rag/orchestrator.py`'s `_embed_with_retry`, minus the
        quarantine (no per-paper fallback exists on the query path). A non-retryable status raises
        `PermanentError` immediately, same as before this method existed.

        `gpu_lock.acquire("embed", timeout=...)` wraps only the single HTTP attempt inside the
        `try` below (OG-48#3) — the `with` block is exited (lock released) before the `except`
        clauses even run, so `self._retry_sleep(...)` at the bottom always sleeps with the lock
        already free.
        """
        attempt = 0
        while True:
            try:
                with self._gpu_lock.acquire("embed", timeout=self._gpu_lock_timeout):
                    response = self._client.post("/embed", json={"inputs": batch})
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status not in _RETRYABLE_STATUSES:
                    raise PermanentError(f"embedding server returned {status}") from error
                attempt += 1
                if attempt > self._max_retries:
                    raise TransientError(f"embedding server returned {status}") from error
            except httpx.HTTPError as error:
                attempt += 1
                if attempt > self._max_retries:
                    raise TransientError(f"embedding request failed: {error}") from error
            self._retry_sleep(self._backoff(attempt))

    @staticmethod
    def _backoff(attempt: int) -> float:
        # Same exponential curve (1s, 2s, 4s, ...) as rag/harvester.py's Harvester._backoff /
        # rag/orchestrator.py's IngestionOrchestrator._backoff — not shared code across files (one
        # line), just the same documented shape (CONVENTIONS.md §4).
        return float(2 ** (attempt - 1))

    def _normalize(self, vector: list[float]) -> Vector:
        if len(vector) != self._info.dim:
            raise ContractError(
                f"embedding server returned a {len(vector)}-dim vector, expected {self._info.dim}"
            )
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:
            raise ContractError("embedding server returned an all-zero vector")
        return [x / norm for x in vector]
