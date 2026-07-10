"""Check (i)'s proof (CONVENTIONS.md §12, WORK-BREAKDOWN.md T-F6 Done criterion): the
`--disable-socket` wiring `unit-tests` already runs under (`pyproject.toml`'s `addopts`, T-F6(i))
actually blocks a real network call, instead of "would have been slow" being taken on faith.

Deliberately NOT collected by the default `pytest` run: `pyproject.toml`'s `testpaths` is
`["rag", "contracts", "ci/checks"]` and this file lives outside all three, so a bare `pytest` from
repo root never sees it. It exists to prove the block works, not to test real product code, and
running it inside the normal `unit-tests` suite would be testing pytest-socket's own test suite,
not this repo -- the `enforcement` CI job (`.github/workflows/ci.yml`) runs it as its own explicit
step: `pytest ci/proof_socket_block/ --disable-socket`.

Two proofs, from concrete to closer-to-real-usage:

1. `test_raw_socket_connect_is_blocked` -- the mechanism itself: a bare `socket.socket().connect()`
   raises `SocketBlockedError` under `--disable-socket`.
2. `test_constructing_a_real_qdrant_client_is_blocked` -- the actual failure mode T-F6's Done
   criterion names: constructing a real `qdrant_client.QdrantClient` (pointed at a real host, as
   Owner D's future `VectorIndex` adapter (T-D2) will do) and calling it reaches for the network on
   the first real request, and that reach is what --disable-socket blocks -- proving the "someone
   swaps `FakeVectorStore` for a real client in a test by mistake" leak is actually caught, not
   just "the option is passed on the command line". `qdrant_client`'s HTTP layer catches the raw
   `SocketBlockedError` and re-wraps it as its own `ResponseHandlingException(source=...)` rather
   than letting it propagate directly -- this test unwraps `.source` to confirm the failure really
   is the socket block, not some unrelated connection error that would also be raised with a live
   network (which would make this test pass for the wrong reason).
"""

import socket

import pytest
from pytest_socket import SocketBlockedError
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException


def test_raw_socket_connect_is_blocked():
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("example.com", 80))


def test_constructing_a_real_qdrant_client_is_blocked():
    client = QdrantClient(host="example.com", port=6333)
    with pytest.raises(ResponseHandlingException) as exc_info:
        client.get_collections()
    assert isinstance(exc_info.value.source, SocketBlockedError)
