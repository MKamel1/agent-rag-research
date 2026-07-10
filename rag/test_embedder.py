# M1A-DORMANT (re-enable in M1b): skips until rag/embedder.py exists. M1b DoD (CONVENTIONS §11)
# requires this suite active (importorskip resolves) and green.
"""Owner C · T-C3 — Embedder (M4) test suite, written test-first against the FROZEN interface.

Spec sources: TEST-STRATEGY.md "Embedder" bullet + "Contract tests", ARCHITECTURE.md §M4,
DATA-CONTRACTS.md §M4, CONVENTIONS §6 (single-GPU). Frozen interface (ARCHITECTURE §M4, owner C):
`embed(texts: list[str]) -> list[Vector]` (order-preserving, 1:1 with input) and `info ->
EmbedderInfo`. `Vector` is L2-normalized with `len == info.dim`.

Two parts, deliberately separate (TEST-STRATEGY "Embedder"):
  - The **contract test** (determinism, length, dim, normalization) parametrized over embedder
    implementations. `FakeEmbedder` runs in default CI now; the real TEI/vLLM adapter joins the
    *same* parametrized body in the nightly / M2 real-adapter job (it opts out of the socket
    block there) — the extension point is marked below but NOT wired here (needs a live GPU
    service). The lock is intentionally NOT asserted inside the contract test.
  - A **separate** lock-focused test: the real adapter acquires `gpu_lock.acquire("embed")`,
    asserted via `FakeGpuLock.acquired`.
"""

import contextlib
import inspect
import math
from unittest.mock import MagicMock

import pytest

# M1a CI convention (CONVENTIONS §0.7 / §11): skip the whole suite until rag/embedder.py lands.
_mod = pytest.importorskip("rag.embedder")

from rag.fakes.fake_embedder import FakeEmbedder  # noqa: E402
from rag.fakes.fake_gpu_lock import FakeGpuLock  # noqa: E402

# Contract cases. FakeEmbedder is the in-CI implementation of the seam (fast, no GPU). The real
# TEI/vLLM adapter is appended to this list by the nightly / M2 real-adapter job — the SAME
# assertions below then run against it, which is what makes "swap the embedding model" safe
# (TEST-STRATEGY "Contract tests"). Do NOT add the real adapter here: it needs a live GPU service
# and must opt out of --disable-socket at the point that job invokes it.
_CONTRACT_EMBEDDERS = [pytest.param(lambda: FakeEmbedder(dim=64), id="fake")]


@pytest.fixture(params=_CONTRACT_EMBEDDERS)
def embedder(request):
    return request.param()


# ---------------------------------------------------------------------------
# The Embedder contract (runs against every implementation in _CONTRACT_EMBEDDERS)
# ---------------------------------------------------------------------------


def test_output_length_equals_input_length(embedder):
    texts = ["alpha", "beta", "gamma"]
    vectors = embedder.embed(texts)
    assert len(vectors) == len(texts)


def test_every_vector_has_length_equal_to_info_dim(embedder):
    for vec in embedder.embed(["alpha", "beta"]):
        assert len(vec) == embedder.info.dim


def test_vectors_are_l2_normalized(embedder):
    for vec in embedder.embed(["alpha", "beta", "a longer passage of text about estimators"]):
        norm = math.sqrt(sum(x * x for x in vec))
        assert norm == pytest.approx(1.0, abs=1e-6)


def test_deterministic_same_input_same_output(embedder):
    text = "the doubly-robust estimator"
    assert embedder.embed([text]) == embedder.embed([text])


def test_order_preserving_and_distinct_texts_give_distinct_vectors(embedder):
    a, b = "alpha", "beta"
    batch = embedder.embed([a, b])
    # 1:1 order-preserving: batch[i] is the vector for texts[i].
    assert batch[0] == embedder.embed([a])[0]
    assert batch[1] == embedder.embed([b])[0]
    # A collapsed/constant embedder would make everything retrieve identically — distinct inputs
    # must give distinct vectors.
    assert batch[0] != batch[1]


def test_empty_input_gives_empty_output(embedder):
    assert embedder.embed([]) == []


def test_info_exposes_model_id_dim_and_version(embedder):
    info = embedder.info
    assert info.dim > 0
    assert isinstance(info.model_id, str) and info.model_id
    assert isinstance(info.version, str) and info.version


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
    CONVENTIONS §6) and a permissive stub for every other required dependency (the TEI/vLLM
    client, CONVENTIONS §2). No socket, no GPU — the lock is acquired *around* the batch inference
    call, so `.acquired` is recorded before any Mock result is post-processed.
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
