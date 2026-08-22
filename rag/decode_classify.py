"""One decode-or-classify primitive shared by the generation-LLM adapters (RI-31).

Every adapter that POSTs to a local generation endpoint and reads the JSON reply needs the same
unglamorous step after the HTTP call succeeds: turn the 200 body into the model's text answer,
without letting a decode failure escape as a raw exception outside the repo's error taxonomy
(`contracts/errors.py`). Before RI-31 there were three inline copies of that step -- two of them
(the summarizer's `summarize`/`extract_affiliations`, the header generator's `generate`) caught
only the wrong-shape case and let an undecodable body sail through as a raw
JSONDecodeError/UnicodeDecodeError; the reranker/embedder had drawn the right line inline
(RI-28/29) but inside their own retry loops, which the generation adapters deliberately do not
have. This module owns the shape once, so the classification cannot drift per adapter again.

The line it draws (settled in RI-28 and reused since): a body that WON'T DECODE AT ALL is
transient -- the server returned 2xx, so it accepted this request, and an undecodable body is
most plausibly corruption in transit (truncation, proxy garbage) rather than a property of the
request; resending can genuinely succeed. A body that DECODES but has the wrong shape stays
permanent -- deterministic given this request, not transit noise. Both decode failures are
caught as ValueError rather than the JSON-specific type because a non-UTF-8 body raises
UnicodeDecodeError; both mean "this body didn't decode".

Why the parameter is a structural protocol instead of the concrete response type: like
`rag/atomic_write.py`, this is shared mechanics, not an adapter, so it names no vendor -- not
even its HTTP client (`ci/checks/vendor_isolation.py`'s allowlist is per-file, and this module is
deliberately absent from it). Anything with a `.json()` method satisfies `_JsonResponse`.

Why the shape arm also catches TypeError/AttributeError, beyond the historical KeyError: a body
that decodes to a non-object (an array) fails subscripting with TypeError, and a `"response"`
field holding null or a number fails `.strip()` with AttributeError -- all the same "decodes but
wrong shape" condition, and leaving any of them unclassified would reopen the exact escape this
module exists to close.
"""

from __future__ import annotations

from typing import Any, Protocol

from contracts.errors import PermanentError, TransientError


class _JsonResponse(Protocol):
    """The one method of a 200 response object the decode below touches."""

    def json(self) -> Any: ...


def decode_or_classify(response: _JsonResponse, source: str) -> str:
    """Decode a successful generation response and return its stripped `response` field.

    Raises `TransientError` when the body won't decode at all (transit corruption -- retryable;
    see the module docstring for the split and its RI-28 origin) and `PermanentError` when it
    decodes but holds no usable `response` field (missing field, non-object payload, non-string
    value). Returns the stripped text as-is otherwise -- including "", whose emptiness policy
    (quarantine vs skip-one-chunk) belongs to each caller, not here. `source` names the
    request/response pair for error messages, e.g. `"{paper_id}: generation LLM"`.
    """
    try:
        return response.json()["response"].strip()
    except ValueError as error:
        # Undecodable on a 2xx: classified HERE, in one place, as transient -- resending can
        # genuinely succeed (RI-28/29's rationale, applied at the no-retry-loop seams).
        raise TransientError(
            f"{source} returned HTTP 200 with an undecodable body: {error}"
        ) from error
    except (KeyError, TypeError, AttributeError) as error:
        raise PermanentError(
            f"{source} response missing or malformed 'response' field: {error!r}"
        ) from error
