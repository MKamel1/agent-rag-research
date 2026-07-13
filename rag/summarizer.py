"""OllamaSummarizer — the real `Summarizer` adapter (T-C2, M3B) over the local generation LLM
(Qwen tier, PRD ADR-08; served via Ollama for v1, PRD ADR-09).

Vendor isolation (CONVENTIONS.md §1): this is the only module allowed to name the local
generation-LLM serving stack ("ollama"/"vllm" — ADR-09's v1→later migration) — see
`ci/checks/vendor_isolation.py`'s `VENDOR_RULES`, which already allowlists both tokens to this
file. The adapter talks to that stack over plain HTTP (`httpx`, already a core dependency used by
several adapters), so no vendor SDK import is needed at all.
"""

import httpx

from contracts.errors import PermanentError, TransientError
from contracts.gpu_lock import GpuLock
from contracts.parser import ParsedDoc

# Kept short and generic: the workhorse-tier model (ADR-08) fills in method + finding from the
# paper's own text. Prompt tuning is not this ticket's job (no golden-fixture LLM to tune
# against here, see the M1a test suite's docstring) — this is a reasonable v1 default, not a
# locked contract.
_SUMMARY_PROMPT = (
    "Summarize the following academic paper in 3-5 sentences. Cover its method and its main "
    "finding. Do not copy the title or abstract verbatim.\n\n{paper}"
)

# Same taxonomy split as rag/harvester.py's ArxivSource (CONVENTIONS.md §4): a rate-limited or
# momentarily-unhealthy server is transient (retry, then quarantine); any other 4xx is this
# server's/request's fault (quarantine the paper, don't retry).
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class OllamaSummarizer:
    """Real `Summarizer` adapter: one local generation-LLM call per paper, through an injected
    HTTP client pointed at Ollama's `/api/generate` endpoint (v1, ADR-09) or a compatible server.

    Preconditions: `parsed.markdown` contains usable prose (non-whitespace) — a degenerate parse
    (figures-only, or an empty document) has nothing to summarize; that is a `PermanentError`
    (DATA-CONTRACTS.md §M3B), not a crash, so the caller quarantines the paper and continues.
    Postconditions: returns a non-empty `summary_text`. `summary_id` is never invented here — the
    caller always derives it as `f"{paper_id}:summary"` (DATA-CONTRACTS.md §IDs).
    Acquires `gpu_lock.acquire("summarize")` around the inference call only (CONVENTIONS.md §6) —
    never around the precondition check, so a degenerate paper never queues behind the GPU lock.
    """

    def __init__(self, client: httpx.Client, gpu_lock: GpuLock, model: str):
        self._client = client
        self._gpu_lock = gpu_lock
        self._model = model

    def summarize(self, parsed: ParsedDoc) -> str:
        prose = parsed.markdown.strip()
        if not prose:
            raise PermanentError(
                f"{parsed.paper_id}: no usable prose to summarize (empty or figures-only parse)"
            )

        with self._gpu_lock.acquire("summarize"):
            try:
                response = self._client.post(
                    "/api/generate",
                    json={
                        "model": self._model,
                        "prompt": _SUMMARY_PROMPT.format(paper=prose),
                        "stream": False,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status in _RETRYABLE_STATUSES:
                    raise TransientError(
                        f"{parsed.paper_id}: generation LLM server returned {status}"
                    ) from error
                raise PermanentError(
                    f"{parsed.paper_id}: generation LLM server returned {status}"
                ) from error
            except httpx.HTTPError as error:
                # Timeouts, connection errors, etc. — all transient (retry with backoff).
                raise TransientError(
                    f"{parsed.paper_id}: generation LLM request failed: {error}"
                ) from error

            try:
                summary_text = response.json()["response"].strip()
            except KeyError as error:
                raise PermanentError(
                    f"{parsed.paper_id}: generation LLM response missing 'response' field"
                ) from error

        if not summary_text:
            raise PermanentError(
                f"{parsed.paper_id}: generation LLM returned an empty summary"
            )
        return summary_text

    def unload(self) -> None:
        """Proactively evict this model from GPU memory (ARCHITECTURE.md §3's two-phase ingest:
        Pass 1/MinerU needs this model's VRAM back). `keep_alive: 0` with no `prompt` is Ollama's
        documented no-generation unload (what `ollama stop <model>` wraps) -- returns immediately,
        no inference call, so it doesn't queue behind `gpu_lock`. Best-effort: a server that's
        unreachable or already has the model unloaded just leaves it not-loaded either way, so a
        failure here isn't a reason to fail the caller's phase transition.
        """
        try:
            self._client.post("/api/generate", json={"model": self._model, "keep_alive": 0})
        except httpx.HTTPError:
            pass
