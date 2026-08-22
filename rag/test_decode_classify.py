"""RI-31 — `rag/decode_classify.decode_or_classify` unit tests.

Deliberately vendor-free: this module is shared mechanics, so like every non-adapter file it may
not name the adapters' HTTP client (CONVENTIONS.md §1, `ci/checks/vendor_isolation.py`'s
per-file allowlist). The fake response below therefore reproduces the two real decode failures
directly over raw bytes via `json.loads` -- malformed text raising JSONDecodeError, non-UTF-8
bytes raising UnicodeDecodeError -- instead of building a real client response; the end-to-end
path through the real response objects is covered at each adapter's own suite
(`rag/test_summarizer.py`, `rag/test_contextual_header.py`).
"""

import json

import pytest

from contracts.errors import PermanentError, TransientError
from rag.decode_classify import decode_or_classify


class _FakeResponse:
    """Stands in for the injected 200 response object: `.json()` decodes raw stored bytes, so the
    failure modes below are the real ones (a truncated body, binary garbage), not synthesized
    exception raises.
    """

    def __init__(self, body: bytes):
        self._body = body

    def json(self):
        return json.loads(self._body)


_OK_BODY = json.dumps({"response": "  A situating header sentence.  "}).encode()


def test_returns_the_stripped_response_field():
    assert decode_or_classify(_FakeResponse(_OK_BODY), "test source") == (
        "A situating header sentence."
    )


def test_empty_field_is_returned_as_is():
    # Emptiness policy belongs to the caller (the summarizer and the header generator each raise
    # their own PermanentError for an empty answer); the helper only classifies decode/shape.
    body = json.dumps({"response": ""}).encode()
    assert decode_or_classify(_FakeResponse(body), "test source") == ""


# ---------------------------------------------------------------------------
# Won't-decode-at-all -> TransientError (transit corruption: the server returned 2xx, so the
# request was accepted and resending can succeed)
# ---------------------------------------------------------------------------


def test_truncated_body_maps_to_transient_error():
    body = b'{"response": "cut off mid-fi'
    with pytest.raises(TransientError):
        decode_or_classify(_FakeResponse(body), "test source")


def test_non_utf8_body_maps_to_transient_error():
    # The flavor that rules out catching the JSON-specific type alone.
    with pytest.raises(TransientError):
        decode_or_classify(_FakeResponse(b"\x81\x81\x81\x81"), "test source")


def test_transient_error_names_the_source_and_underlying_cause():
    with pytest.raises(TransientError) as excinfo:
        decode_or_classify(_FakeResponse(b"<html>gateway garbage</html>"), "paper X: adapter")
    assert "paper X: adapter" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ValueError)


# ---------------------------------------------------------------------------
# Decodes-but-wrong-shape -> PermanentError (deterministic given this request, not transit noise)
# ---------------------------------------------------------------------------


def test_missing_response_field_maps_to_permanent_error():
    body = json.dumps({"unexpected": "shape"}).encode()
    with pytest.raises(PermanentError):
        decode_or_classify(_FakeResponse(body), "test source")


def test_non_mapping_payload_maps_to_permanent_error():
    # A JSON array body decodes fine but isn't subscriptable as the expected object.
    with pytest.raises(PermanentError):
        decode_or_classify(_FakeResponse(b'["a", "b"]'), "test source")


def test_non_string_response_field_maps_to_permanent_error():
    for value in ("null", "123", '{"nested": true}'):
        body = json.dumps({"response": json.loads(value)}).encode()
        with pytest.raises(PermanentError):
            decode_or_classify(_FakeResponse(body), "test source")
