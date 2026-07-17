"""ContextualHeaderGenerator — T-DOC41 (Contextual Retrieval spike, Approach A) real adapter over
the local generation LLM. Given a paper's already-generated summary and one chunk's text, asks the
model for a short header that situates the chunk within the paper -- prepended to the chunk's text
before embedding (never shown to a user as the citation; the anchor stays pinned to the real block,
`contracts/chunker.Chunk.anchor`, DATA-CONTRACTS.md "Provenance & structure").

This is a SPIKE module gathering before/after retrieval evidence, not a V0 ingest-path change:
`contracts/chunker.Chunk.contextual_header` stays `None` in the real V0 path (`rag/chunker.py`,
PRD ADR-07) -- nothing here wires into `rag/orchestrator.py`. The only caller is
`app/reembed_experiment.py`'s throwaway A/B re-embed script.

Same seam as `rag/summarizer.py`'s real `Summarizer` adapter (injected `httpx.Client` -> a local
`/api/generate`-style endpoint, an injected `GpuLock`, an injected model name) -- reused
deliberately, not reinvented, since both adapters call the same local generation-LLM server.

Vendor isolation (CONVENTIONS.md §1): like `rag/summarizer.py`, this adapter talks to that server
over plain HTTP (`httpx`, already a core dependency) -- no vendor SDK import needed, and this file
is allowed the same vendor-naming exemption `rag/summarizer.py` has. It doesn't need to exercise
that exemption for its own logic though, so it stays generic ("the generation LLM server")
throughout -- only the docstring above names *what kind* of endpoint this is, for a reader's
orientation.
"""

import httpx

from contracts.errors import PermanentError, TransientError
from contracts.gpu_lock import GpuLock

# ---------------------------------------------------------------------------------------------
# DEFAULT_HEADER_PROMPT -- the one thing this ticket exists to let the user iterate on. Isolated
# here as a single module-level constant (not inlined into `generate()`) so a prompt experiment is
# a one-line edit here, never a code change elsewhere.
#
# What a GOOD header (50-100 tokens) does that today's bare "title + section_path" glue-on
# (rag/chunker.py's `_build_chunk`, the `text` field) cannot:
#   1. Names the paper's topic/contribution, drawn from `{summary}` -- so a context-poor chunk (a
#      bare equation, an algorithm listing with no surrounding prose) gets embedded next to WHAT
#      IT'S FOR, not just where in the paper it happens to sit.
#   2. States what THIS SPECIFIC chunk (`{chunk}`) contributes to that topic -- the method it
#      defines, the result it states, the step it performs -- never a generic restatement of the
#      summary that would read identically for every chunk in the paper.
# The chunk's own text is never rewritten, summarized, or dropped here -- it stays verbatim,
# immediately after the header, in the text that actually gets embedded (see
# `app/reembed_experiment.py`). This prompt only asks the model for the situating sentence(s) that
# go in FRONT of it.
#
# Example of a good header: "This is the training loss for the contrastive objective in Method §3
# of a paper on causal representation learning, which proposes disentangling treatment effects via
# a contrastive pretraining objective."
# ---------------------------------------------------------------------------------------------
DEFAULT_HEADER_PROMPT = (
    "You are writing a short header for one passage from an academic paper. The header will be "
    "prepended to the passage before it is embedded for retrieval -- it is never shown to a user "
    "on its own, so it must stand on its own as a situating sentence, not a title.\n\n"
    "Paper summary:\n{summary}\n\n"
    "Passage:\n{chunk}\n\n"
    "In 50-100 tokens, write ONE header (one or two sentences) that: (a) names the paper's topic "
    "or contribution, drawn from the summary, and (b) states what this specific passage "
    "contributes to it -- the method it defines, the result it states, or the step it performs. "
    "Do not copy the passage verbatim. Do not add commentary, labels, or preamble outside the "
    "header itself."
)

# Same taxonomy split as rag/summarizer.py: a rate-limited or momentarily-unhealthy server is
# transient (retry, then skip this chunk's header); any other 4xx is this request's fault.
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Fixed, generous context ceiling -- not the dynamic per-paper sizing rag/summarizer.py's
# `_fit_for_summarization` does. Unlike a whole paper, this call's input is always small and
# bounded: the summary is a few sentences, and `chunk_text` is capped by the Chunker's own
# `_MAX_CHUNK_WORDS` (1,500 words, rag/chunker.py). A single fixed ceiling generous enough to cover
# the summary + a maximal chunk + prompt overhead is simpler and just as safe here.
# ponytail: fixed ceiling, not dynamic per-input sizing -- revisit if the chunker's own cap grows.
_NUM_CTX = 8192
# Output budget: a 50-100 token header needs far less than the summarizer's 768 -- capped low so a
# misbehaving model can't run long and eat GPU time. The response is also word-clamped below
# regardless of what the server actually returns.
_NUM_PREDICT = 200
# ~100 tokens at rag/summarizer.py's own measured ~1.84-2.11 tokens/word, plus margin -- a
# safety-net clamp, not the primary length control (the prompt itself asks for 50-100 tokens).
_MAX_HEADER_WORDS = 130


def _clamp(header: str) -> str:
    words = header.split()
    if len(words) <= _MAX_HEADER_WORDS:
        return header
    return " ".join(words[:_MAX_HEADER_WORDS])


class ContextualHeaderGenerator:
    """One local generation-LLM call per chunk, through an injected HTTP client pointed at a local
    `/api/generate`-style endpoint (or a compatible server) -- same construction as
    `rag/summarizer.py`'s real `Summarizer` adapter.

    Preconditions: none beyond `summary_text`/`chunk_text` being strings. An empty or
    whitespace-only `summary_text` or `chunk_text` is not an error (a chunk can legitimately lack a
    paper summary yet, e.g. mid-ingest) -- it just has nothing to condition a header on, so
    `generate()` short-circuits to `""` WITHOUT calling the LLM or acquiring `gpu_lock`.
    Postconditions: given non-empty input, returns a non-empty header string clamped to
    `_MAX_HEADER_WORDS` words (a safety backstop, not the primary length control -- the prompt
    itself asks for 50-100 tokens). A response that comes back genuinely empty is a
    `PermanentError` (mirrors `rag/summarizer.py`'s own rule for an empty summary) -- the
    caller skips that one chunk's header, it does not crash the whole re-embed run.
    Acquires `gpu_lock.acquire("header")` around the inference call only (CONVENTIONS.md §6) --
    never around the precondition check, so an empty-input call never queues behind the GPU lock.
    """

    def __init__(self, client: httpx.Client, gpu_lock: GpuLock, model: str):
        self._client = client
        self._gpu_lock = gpu_lock
        self._model = model

    def generate(
        self, summary_text: str, chunk_text: str, *, prompt: str = DEFAULT_HEADER_PROMPT
    ) -> str:
        summary = summary_text.strip()
        chunk = chunk_text.strip()
        if not summary or not chunk:
            return ""

        with self._gpu_lock.acquire("header"):
            try:
                response = self._client.post(
                    "/api/generate",
                    json={
                        "model": self._model,
                        "prompt": prompt.format(summary=summary, chunk=chunk),
                        "stream": False,
                        "think": False,
                        "options": {"num_ctx": _NUM_CTX, "num_predict": _NUM_PREDICT},
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status in _RETRYABLE_STATUSES:
                    raise TransientError(
                        f"header generation LLM server returned {status}"
                    ) from error
                raise PermanentError(
                    f"header generation LLM server returned {status}"
                ) from error
            except httpx.HTTPError as error:
                raise TransientError(
                    f"header generation LLM request failed: {error}"
                ) from error

            try:
                header = response.json()["response"].strip()
            except KeyError as error:
                raise PermanentError(
                    "header generation LLM response missing 'response' field"
                ) from error

        if not header:
            raise PermanentError("header generation LLM returned an empty header")
        return _clamp(header)
