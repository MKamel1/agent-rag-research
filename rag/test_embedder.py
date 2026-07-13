# M1A-DORMANT (re-enable in M1b): skips until rag/embedder.py exists. M1b DoD (CONVENTIONS §11)
# requires this suite active (importorskip resolves) and green.
"""Owner C · T-C3 — Embedder (M4) test suite, written test-first against the FROZEN interface.

Spec sources: TEST-STRATEGY.md "Embedder" bullet + "Contract tests", ARCHITECTURE.md §M4,
DATA-CONTRACTS.md §M4, CONVENTIONS §6 (single-GPU). Frozen interface (ARCHITECTURE §M4, owner C):
`embed(texts: list[str]) -> list[Vector]` (order-preserving, 1:1 with input) and `info ->
EmbedderInfo`. `Vector` is L2-normalized with `len == info.dim`.

Two parts, deliberately separate (TEST-STRATEGY "Embedder"):
  - The **contract test** (determinism, length, dim, normalization) parametrized over embedder
    implementations. `FakeEmbedder` runs in default CI now; the real embedding-server adapter
    joins the *same* parametrized body in the nightly / M2 real-adapter job (it opts out of the
    socket block there) — the extension point is marked below but NOT wired here (needs a live GPU
    service). The lock is intentionally NOT asserted inside the contract test.
  - A **separate** lock-focused test: the real adapter acquires `gpu_lock.acquire("embed")`,
    asserted via `FakeGpuLock.acquired`.
"""

import contextlib
import hashlib
import inspect
import math
import random
from unittest.mock import MagicMock

import httpx
import pytest

# M1a CI convention (CONVENTIONS §0.7 / §11): skip the whole suite until rag/embedder.py lands.
_mod = pytest.importorskip("rag.embedder")

from contracts.embedder import EmbedderInfo  # noqa: E402
from rag.fakes.fake_embedder import FakeEmbedder  # noqa: E402
from rag.fakes.fake_gpu_lock import FakeGpuLock  # noqa: E402

# ---------------------------------------------------------------------------
# The Embedder contract — standalone assert_*(embedder) functions run against every
# implementation, same shape as rag/test_vector_index.py's CONTRACT tuple. FakeEmbedder runs in
# default CI (fast, no GPU); the real TeiEmbedder runs the identical assertions against a live TEI
# server (`test_real_adapter_satisfies_contract` below), opting out of --disable-socket via
# `enable_socket` and skipping cleanly if no server is reachable — this is what proves "swap the
# embedding model" is safe (TEST-STRATEGY "Contract tests"), not just that the fake behaves.
# ---------------------------------------------------------------------------


def assert_output_length_equals_input_length(embedder):
    texts = ["alpha", "beta", "gamma"]
    vectors = embedder.embed(texts)
    assert len(vectors) == len(texts)


def assert_every_vector_has_length_equal_to_info_dim(embedder):
    for vec in embedder.embed(["alpha", "beta"]):
        assert len(vec) == embedder.info.dim


def assert_vectors_are_l2_normalized(embedder):
    for vec in embedder.embed(["alpha", "beta", "a longer passage of text about estimators"]):
        norm = math.sqrt(sum(x * x for x in vec))
        assert norm == pytest.approx(1.0, abs=1e-6)


def assert_deterministic_same_input_same_output(embedder):
    # Elementwise approx, not exact `==`: FakeEmbedder (a hash) is bit-exact either way, but the
    # real TEI server batches concurrent requests server-side, and reduction-order/kernel
    # non-associativity under load can make two separate /embed calls on the same text differ in
    # the last bits — a one-off manual check being bit-exact on a quiet server isn't proof it stays
    # that way under real traffic. A tolerance-based check is still a real determinism assertion
    # for both adapters, just not brittle to real-server floating-point noise.
    text = "the doubly-robust estimator"
    a, b = embedder.embed([text])[0], embedder.embed([text])[0]
    assert a == pytest.approx(b, abs=1e-6)


def assert_order_preserving_and_distinct_texts_give_distinct_vectors(embedder):
    a, b = "alpha", "beta"
    batch = embedder.embed([a, b])
    # 1:1 order-preserving: batch[i] is the vector for texts[i].
    assert batch[0] == embedder.embed([a])[0]
    assert batch[1] == embedder.embed([b])[0]
    # A collapsed/constant embedder would make everything retrieve identically — distinct inputs
    # must give distinct vectors.
    assert batch[0] != batch[1]


def assert_empty_input_gives_empty_output(embedder):
    assert embedder.embed([]) == []


def assert_info_exposes_model_id_dim_and_version(embedder):
    info = embedder.info
    assert info.dim > 0
    assert isinstance(info.model_id, str) and info.model_id
    assert isinstance(info.version, str) and info.version


CONTRACT = (
    assert_output_length_equals_input_length,
    assert_every_vector_has_length_equal_to_info_dim,
    assert_vectors_are_l2_normalized,
    assert_deterministic_same_input_same_output,
    assert_order_preserving_and_distinct_texts_give_distinct_vectors,
    assert_empty_input_gives_empty_output,
    assert_info_exposes_model_id_dim_and_version,
)


@pytest.mark.parametrize("check", CONTRACT, ids=[c.__name__ for c in CONTRACT])
def test_fake_adapter_satisfies_contract(check):
    check(FakeEmbedder(dim=64))


@pytest.mark.enable_socket  # opts out of the default job's --disable-socket for this test only
@pytest.mark.parametrize("check", CONTRACT, ids=[c.__name__ for c in CONTRACT])
def test_real_adapter_satisfies_contract(check):
    # Needs a live TEI embedding server at localhost:8080 (this repo's documented default,
    # Qwen3-Embedding-4B/dim 2560 per phase0-results.md's Spike 2 lock). Most default runs of this
    # suite don't have one up, so a connection failure skips with a clear reason rather than
    # failing the build — the nightly/M2 job is where this is expected to actually run and be
    # required green.
    real = pytest.importorskip("rag.embedder")

    client = httpx.Client(base_url="http://localhost:8080", timeout=30.0)
    info = EmbedderInfo(model_id="Qwen3-Embedding-4B", dim=2560, version="v1")
    adapter = real.TeiEmbedder(client, FakeGpuLock(), info)
    try:
        adapter.embed(["probe"])
    except httpx.TransportError as e:
        # TransportError (connect/timeout) means no server to talk to -> skip cleanly. It does NOT
        # include HTTPStatusError, so a server that IS up but returns a real 4xx/5xx fails this
        # test instead of silently skipping past a genuine regression.
        pytest.skip(f"no live TEI embedder reachable at localhost:8080: {e}")

    check(adapter)


# ---------------------------------------------------------------------------
# Separate lock-focused test: the REAL adapter acquires gpu_lock.acquire("embed").
# Not folded into the contract test (which also runs against the lock-less FakeEmbedder).
# ---------------------------------------------------------------------------


def _real_embedder_cls():
    """The real GPU-bound adapter in rag.embedder — the class T-F6's gpu_lock check (f) targets:
    name ends in 'Embedder', not 'Fake'-prefixed, defined in this module (FakeEmbedder lives in
    rag.fakes, so it is not picked up here).
    """
    for name, obj in vars(_mod).items():
        if (
            inspect.isclass(obj)
            and getattr(obj, "__module__", None) == _mod.__name__
            and name.endswith("Embedder")
            and not name.startswith("Fake")
        ):
            return obj
    pytest.fail("rag.embedder must define a real '*Embedder' adapter class (CONVENTIONS §6)")


def _build_embedder(gpu_lock):
    """Construct the real adapter injecting `FakeGpuLock` for `gpu_lock` (frozen param name,
    CONVENTIONS §6) and a permissive stub for every other required dependency (the real
    embedder's client, CONVENTIONS §2). No socket, no GPU — the lock is acquired *around* the
    batch inference call, so `.acquired` is recorded before any Mock result is post-processed.
    """
    cls = _real_embedder_cls()
    kwargs = {}
    for pname, p in inspect.signature(cls).parameters.items():
        if pname == "gpu_lock":
            kwargs[pname] = gpu_lock
        elif p.default is inspect.Parameter.empty and p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            kwargs[pname] = MagicMock()
    return cls(**kwargs)


def test_real_embedder_acquires_the_embed_gpu_lock():
    lock = FakeGpuLock()
    adapter = _build_embedder(lock)
    with contextlib.suppress(Exception):
        adapter.embed(["a passage to embed"])
    assert lock.acquired == ["embed"], (
        "real Embedder must acquire gpu_lock.acquire('embed') around its batch call — the "
        "single-GPU rule's only enforcement (CONVENTIONS §6)"
    )


# ---------------------------------------------------------------------------
# Sub-batching: the real TEI server enforces `max_client_batch_size=32` (empirically confirmed:
# 161 texts -> HTTP 422, 32 texts -> HTTP 200). `IngestionOrchestrator` relies on exactly one
# `embed()` call per paper covering the summary plus every chunk together, so `embed()` itself
# must split any larger input into <=32-item HTTP batches, transparently to the caller.
# ---------------------------------------------------------------------------


def _hash_to_raw_vector(text: str, dim: int) -> list[float]:
    # Same recipe as FakeEmbedder: same text -> same vector, different text -> (virtually
    # certainly) different vector, with no cross-process randomness.
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(dim)]


class _FakeTeiResponse:
    def __init__(self, vectors):
        self._vectors = vectors

    def raise_for_status(self):
        pass

    def json(self):
        return self._vectors


class _FakeTeiClient:
    """Stand-in for `httpx.Client`. Records the size of every POSTed batch (so a test can assert
    sub-batching happened and stayed within the server's limit) and returns one vector per input
    text, derived only from that text's own content — so a text's embedding is the same no matter
    which sub-batch it lands in, and order-preservation can be checked against content, not just
    position.
    """

    def __init__(self, dim: int):
        self._dim = dim
        self.batch_sizes: list[int] = []

    def post(self, url, json):
        batch = json["inputs"]
        self.batch_sizes.append(len(batch))
        return _FakeTeiResponse([_hash_to_raw_vector(t, self._dim) for t in batch])


def test_embed_sub_batches_over_the_tei_limit_and_preserves_order():
    dim = 8
    client = _FakeTeiClient(dim)
    info = EmbedderInfo(model_id="fake-tei", dim=dim, version="v1")
    adapter = _real_embedder_cls()(client=client, gpu_lock=FakeGpuLock(), info=info)

    texts = [f"paper chunk number {i}" for i in range(45)]  # > 32, forces >=2 HTTP batches
    vectors = adapter.embed(texts)

    # (a) multiple POSTs, each within the server's 32-item limit.
    assert len(client.batch_sizes) > 1
    assert all(size <= 32 for size in client.batch_sizes)
    assert sum(client.batch_sizes) == len(texts)

    # (b) same length, SAME ORDER: vectors[i] is specifically the vector for texts[i] -- not just
    # "any 45 embeddings" -- verified by recomputing each text's embedding on its own (a
    # single-text call always stays under the batch limit) and comparing position-by-position.
    assert len(vectors) == len(texts)
    for i, text in enumerate(texts):
        assert vectors[i] == adapter.embed([text])[0]

    # (c) determinism preserved across sub-batching: re-running the same multi-batch call gives
    # byte-identical output (mirrors test_deterministic_same_input_same_output's style).
    assert adapter.embed(texts) == vectors
