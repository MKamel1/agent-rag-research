"""OllamaSummarizer — the real `Summarizer` adapter (T-C2, M3B) over the local generation LLM
(Qwen tier, PRD ADR-08; served via Ollama for v1, PRD ADR-09).

Vendor isolation (CONVENTIONS.md §1): this is the only module allowed to name the local
generation-LLM serving stack ("ollama"/"vllm" — ADR-09's v1→later migration) — see
`ci/checks/vendor_isolation.py`'s `VENDOR_RULES`, which already allowlists both tokens to this
file. The adapter talks to that stack over plain HTTP (`httpx`, already a core dependency used by
several adapters), so no vendor SDK import is needed at all.
"""

import httpx

from contracts.errors import PermanentError
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
            response = self._client.post(
                "/api/generate",
                json={
                    "model": self._model,
                    "prompt": _SUMMARY_PROMPT.format(paper=prose),
                    "stream": False,
                },
            )
            response.raise_for_status()
            summary_text = response.json()["response"].strip()

        if not summary_text:
            raise PermanentError(
                f"{parsed.paper_id}: generation LLM returned an empty summary"
            )
        return summary_text
