"""OllamaSummarizer — the real `Summarizer` adapter (T-C2, M3B) over the local generation LLM
(Qwen tier, PRD ADR-08; served via Ollama for v1, PRD ADR-09).

Vendor isolation (CONVENTIONS.md §1): this is the only module allowed to name the local
generation-LLM serving stack ("ollama"/"vllm" — ADR-09's v1→later migration) — see
`ci/checks/vendor_isolation.py`'s `VENDOR_RULES`, which already allowlists both tokens to this
file. The adapter talks to that stack over plain HTTP (`httpx`, already a core dependency used by
several adapters), so no vendor SDK import is needed at all.
"""

import logging
import re

import httpx

from contracts.errors import PermanentError, TransientError
from contracts.gpu_lock import GpuLock
from contracts.parser import ParsedDoc

logger = logging.getLogger(__name__)

# Empirically validated, not a hand-picked default: a fork this session ran the current 3-5
# sentence "method + finding" prompt and this richer one against 5 real papers' own abstracts
# and skeptically graded the results (does each summary state a concrete, checkable fact the
# abstract doesn't?). The old prompt added a real new fact in only 2/5 papers -- it's mostly a
# reworded abstract, which the paper already provides for free at harvest time. This prompt added
# a real new fact in 5/5 (named alternative methods, convergence rates, sample sizes, stated
# limitations -- see .phase0-data/known-issue-pass2-oom.md for the full comparison).
_SUMMARY_PROMPT = (
    "Summarize this academic paper's contribution in 4-6 sentences. Include, if stated in the "
    "paper: (a) the core method, (b) the main quantitative result or effect size, (c) key "
    "assumptions or conditions required for the method to work, (d) dataset or sample size used, "
    "(e) any limitations the authors state. Do not copy the abstract verbatim.\n\n{paper}"
)

# Same taxonomy split as rag/harvester.py's ArxivSource (CONVENTIONS.md §4): a rate-limited or
# momentarily-unhealthy server is transient (retry, then quarantine); any other 4xx is this
# server's/request's fault (quarantine the paper, don't retry).
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# References/appendix sections can dominate a real paper's length (one real corpus paper: ~72,000
# of 109,000 words was a proof appendix) while adding nothing a method+finding summary needs --
# dropped before summarizing. See .phase0-data/known-issue-pass2-oom.md for the corpus evidence.
_LOW_VALUE_SECTION_HEADING = re.compile(
    r"\n#{1,3}\s*(references|bibliography|appendix|supplementary)\b", re.IGNORECASE
)

# ponytail: fixed interim limits, not a proper per-request budget. Real testing this session found
# (a) VRAM scales with the *configured* context window, not the text actually sent, so a smaller
# num_ctx than the server's default saves real memory; (b) a single call can't be trusted to
# reliably use anywhere near a large requested num_ctx -- real truncation appeared as low as
# ~20,500 tokens for reasons not root-caused. So the ceiling here is deliberately conservative,
# and thinking is off (`think: False` below) because a thinking-enabled model shares ONE token
# budget between its reasoning and its answer (verified directly: a 30-token budget produced only
# reasoning text and an empty answer) -- there's no way to protect the answer's budget from it on
# this Ollama-based v1 stack. Upgrade path: PRD.md ADR-09's planned v1->vLLM migration ships a real
# `thinking_token_budget` that forces the model out of reasoning at a set token count instead of
# silently starving the answer -- re-enable thinking and retune all four constants below then,
# rather than tightening this blunt setup further.
_TOKENS_PER_WORD_ESTIMATE = 2.2  # real corpus samples this session measured 1.84-2.11 tokens/word
_PROMPT_OVERHEAD_TOKENS = 200
_NUM_CTX_FLOOR = 4096
_NUM_CTX_CEILING = 16384
_NUM_PREDICT = 768


def _fit_for_summarization(paper_id: str, prose: str) -> tuple[str, int]:
    """Drops low-value sections, then truncates further if the paper still doesn't fit the safe
    ceiling, returning the text to actually send plus the `num_ctx` sized for it.
    """
    match = _LOW_VALUE_SECTION_HEADING.search(prose)
    trimmed = prose[: match.start()] if match else prose

    words = trimmed.split()
    max_words = int((_NUM_CTX_CEILING - _PROMPT_OVERHEAD_TOKENS) / _TOKENS_PER_WORD_ESTIMATE)
    if len(words) > max_words:
        logger.warning(
            "%s: paper text (%d words after dropping references/appendix) still exceeds the "
            "summarizer's safe token ceiling -- truncating to the first %d words",
            paper_id,
            len(words),
            max_words,
        )
        words = words[:max_words]
        trimmed = " ".join(words)

    estimated_tokens = int(len(words) * _TOKENS_PER_WORD_ESTIMATE) + _PROMPT_OVERHEAD_TOKENS
    num_ctx = max(_NUM_CTX_FLOOR, min(estimated_tokens, _NUM_CTX_CEILING))
    return trimmed, num_ctx


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

        text, num_ctx = _fit_for_summarization(parsed.paper_id, prose)

        with self._gpu_lock.acquire("summarize"):
            try:
                response = self._client.post(
                    "/api/generate",
                    json={
                        "model": self._model,
                        "prompt": _SUMMARY_PROMPT.format(paper=text),
                        "stream": False,
                        "think": False,
                        "options": {"num_ctx": num_ctx, "num_predict": _NUM_PREDICT},
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
