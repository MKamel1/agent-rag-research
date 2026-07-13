# M1A-DORMANT (re-enable in M1b): skips until rag/summarizer.py exists. M1b DoD (CONVENTIONS §11)
# requires this suite active (importorskip resolves) and green.
"""Owner C · T-C2 — Summarizer (M3B) test suite, written test-first against the FROZEN interface.

Spec sources: TEST-STRATEGY.md "Summarizer" bullet, ARCHITECTURE.md §M3B, DATA-CONTRACTS.md §M3B,
CONVENTIONS §6 (single-GPU). Frozen interface (ARCHITECTURE §M3B, owner C): a real `*Summarizer`
adapter whose `__init__` takes an injected LLM client **and** a `gpu_lock: GpuLock` (CONVENTIONS §6,
T-F6 check f), exposing `summarize(ParsedDoc) -> str` (returns `summary_text`; `summary_id` is
derived by the caller, never invented here).

Two tiers, per TEST-STRATEGY "Golden rule" (downstream tests are zero-GPU):
  - The **lock** and **PermanentError** behaviours run zero-GPU here, in default CI (a stubbed LLM
    client + `FakeGpuLock`; no inference actually happens).
  - The **quality / non-degeneracy** check needs the real generation LLM over synthetic
    golden-paper fixtures — it opts out of the socket-disabled default run (`real_adapter`
    marker). The `real_summarizer`/`golden_papers` fixtures build a real Ollama-backed adapter
    directly and skip only if Ollama is actually unreachable, so the default suite stays green.
"""

import contextlib
import inspect
import json
from unittest.mock import MagicMock

import httpx
import pytest

# M1a CI convention (CONVENTIONS §0.7 / §11): skip the whole suite until rag/summarizer.py lands.
_mod = pytest.importorskip("rag.summarizer")

from contracts.errors import PermanentError, TransientError  # noqa: E402
from contracts.parser import Figure, ParsedDoc  # noqa: E402
from contracts.provenance import Block  # noqa: E402
from rag.fakes.fake_gpu_lock import FakeGpuLock  # noqa: E402

PAPER_ID = "2506.01234"


def _prose_doc(**overrides) -> ParsedDoc:
    fields = dict(
        paper_id=PAPER_ID,
        markdown="# A Causal Method\n\nWe propose a doubly-robust estimator for treatment effects "
        "under unobserved confounding, and prove its consistency.",
        blocks=[
            Block(
                block_id=f"{PAPER_ID}:b0",
                paper_id=PAPER_ID,
                text="We propose a doubly-robust estimator for treatment effects under "
                "unobserved confounding, and prove its consistency.",
                type="prose",
                page=0,
                bbox=(0.0, 0.0, 100.0, 200.0),
                section_path="1. Introduction",
                index=0,
            )
        ],
        figures=[],
        tables=[],
        references=[],
        parser_id="test-parser-1.x",
    )
    fields.update(overrides)
    return ParsedDoc(**fields)


def _figures_only_doc() -> ParsedDoc:
    """A degenerate parse: a figure but no usable prose block and whitespace-only markdown —
    the "figures-only after a bad parse" case ARCHITECTURE §M3B calls out for `PermanentError`.
    """
    return _prose_doc(
        markdown="   \n  ",
        blocks=[],
        figures=[
            Figure(
                paper_id=PAPER_ID,
                image_path="/blobs/2506.01234/fig1.png",
                caption="Figure 1: architecture.",
                page=0,
                bbox=(0.0, 0.0, 100.0, 200.0),
            )
        ],
    )


def _real_summarizer_cls():
    """The real GPU-bound adapter in rag.summarizer — the class T-F6's gpu_lock check (f) targets:
    name ends in 'Summarizer', not 'Fake'-prefixed, defined in this module.
    """
    for name, obj in vars(_mod).items():
        if (
            inspect.isclass(obj)
            and getattr(obj, "__module__", None) == _mod.__name__
            and name.endswith("Summarizer")
            and not name.startswith("Fake")
        ):
            return obj
    pytest.fail("rag.summarizer must define a real '*Summarizer' adapter class (CONVENTIONS §6)")


def _build_summarizer(gpu_lock):
    """Construct the real adapter injecting `FakeGpuLock` for `gpu_lock` (frozen param name,
    CONVENTIONS §6) and a permissive stub for every other required constructor dependency (the LLM
    client, per CONVENTIONS §2). No socket, no GPU — the stub returns Mocks; the tests below only
    assert on lock acquisition and the pre-inference error path, both of which are decided before
    any real inference would run.
    """
    cls = _real_summarizer_cls()
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


def _build_summarizer_with_client(client, gpu_lock):
    """Like `_build_summarizer`, but injects a real `client` (an `httpx.Client` wired to a
    `MockTransport`, same offline-fixture style as `rag/test_harvester_arxiv_source.py`) instead
    of a `MagicMock` — needed by the HTTP-failure-mapping tests below, where
    `client.post(...).raise_for_status()` must actually raise.
    """
    cls = _real_summarizer_cls()
    kwargs = {}
    for pname, p in inspect.signature(cls).parameters.items():
        if pname == "gpu_lock":
            kwargs[pname] = gpu_lock
        elif pname == "client":
            kwargs[pname] = client
        elif pname == "model":
            # Goes into the real JSON request body below (`json={"model": ...}` in
            # rag/summarizer.py) — a MagicMock isn't JSON-serializable, unlike the other
            # MagicMock-stubbed dependencies, which are never touched before the HTTP call fails.
            kwargs[pname] = "test-model"
        elif p.default is inspect.Parameter.empty and p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            kwargs[pname] = MagicMock()
    return cls(**kwargs)


# ---------------------------------------------------------------------------
# GPU lock: acquires "summarize", never co-resides with Embedder/Reranker
# ---------------------------------------------------------------------------


def test_summarize_acquires_the_gpu_lock_with_the_summarize_stage_label():
    lock = FakeGpuLock()
    adapter = _build_summarizer(lock)
    # The stubbed client makes real inference impossible; suppress whatever post-processing does
    # with a Mock result — the lock is acquired *around* that call, so `.acquired` is recorded
    # regardless of what the inference returns.
    with contextlib.suppress(Exception):
        adapter.summarize(_prose_doc())
    assert lock.acquired == ["summarize"], (
        "real Summarizer must acquire gpu_lock.acquire('summarize') exactly once and share the "
        "single GPU slot with nothing else (never 'embed'/'rerank') — CONVENTIONS §6"
    )


# ---------------------------------------------------------------------------
# Degenerate / figures-only input -> PermanentError -> quarantine, not a crash
# ---------------------------------------------------------------------------


def test_figures_only_parsed_doc_raises_permanent_error():
    adapter = _build_summarizer(FakeGpuLock())
    with pytest.raises(PermanentError):
        adapter.summarize(_figures_only_doc())


def test_empty_markdown_parsed_doc_raises_permanent_error():
    adapter = _build_summarizer(FakeGpuLock())
    with pytest.raises(PermanentError):
        adapter.summarize(_prose_doc(markdown="", blocks=[]))


# ---------------------------------------------------------------------------
# Vendor/HTTP failure mapping (CONVENTIONS §4): a real Ollama/vLLM hiccup must come out as
# TransientError/PermanentError, never as a bare httpx/KeyError exception — otherwise the
# orchestrator (which only catches PermanentError from this stage) crashes the whole run instead
# of retrying/quarantining the one paper. Same split as rag/harvester.py's `ArxivSource`.
# ---------------------------------------------------------------------------


def test_5xx_response_maps_to_transient_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "model is loading"})

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    adapter = _build_summarizer_with_client(client, FakeGpuLock())
    with pytest.raises(TransientError):
        adapter.summarize(_prose_doc())


def test_connection_failure_maps_to_transient_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    adapter = _build_summarizer_with_client(client, FakeGpuLock())
    with pytest.raises(TransientError):
        adapter.summarize(_prose_doc())


def test_response_body_missing_response_field_maps_to_permanent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected_shape": True})

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    adapter = _build_summarizer_with_client(client, FakeGpuLock())
    with pytest.raises(PermanentError):
        adapter.summarize(_prose_doc())


# ---------------------------------------------------------------------------
# unload() — proactive eviction for the two-pass ingest's phase boundary (ARCHITECTURE.md §3).
# No `prompt` and `keep_alive: 0` is Ollama's documented no-generation unload; must not acquire
# gpu_lock (it's not an inference call) and must not raise on a failed request (best-effort).
# ---------------------------------------------------------------------------


def test_unload_sends_keep_alive_zero_with_no_prompt_and_does_not_acquire_the_lock():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    lock = FakeGpuLock()
    adapter = _build_summarizer_with_client(client, lock)

    adapter.unload()

    assert len(requests) == 1
    assert requests[0] == {"model": "test-model", "keep_alive": 0}
    assert lock.acquired == []  # not an inference call -- must not queue behind gpu_lock


def test_unload_is_best_effort_and_swallows_a_failed_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    adapter = _build_summarizer_with_client(client, FakeGpuLock())

    adapter.unload()  # must not raise


# ---------------------------------------------------------------------------
# Quality / non-degeneracy on synthetic golden-paper fixtures (real LLM, `real_adapter` marker).
# `real_summarizer` builds a real Ollama-backed Summarizer directly and skips only if Ollama is
# unreachable — not supplied externally — so this assertion set stays green in default CI (marker
# deselected) and self-contained whenever `-m real_adapter` is actually run.
# ---------------------------------------------------------------------------


@pytest.fixture
def real_summarizer():
    client = httpx.Client(base_url="http://localhost:11434", timeout=120.0)
    summarizer = _real_summarizer_cls()(client, FakeGpuLock(), model="qwen3:14b")
    try:
        client.get("/api/tags").raise_for_status()
    except httpx.HTTPError as e:
        pytest.skip(f"no live Ollama at localhost:11434: {e}")
    return summarizer


class _GoldenPaper:
    """ponytail: a minimal stand-in for Owner B's golden-fixture objects (paper_id/parsed/title/
    abstract) — synthetic, not a real re-parse of fixtures/golden/'s PDFs. This test's job is to
    prove the real Ollama-backed Summarizer produces real, non-degenerate signal, not to re-prove
    Parser works (that's rag/test_parser.py's real_adapter suite, already covered)."""

    def __init__(self, paper_id: str, title: str, abstract: str, markdown: str):
        self.paper_id = paper_id
        self.title = title
        self.abstract = abstract
        self.parsed = ParsedDoc(
            paper_id=paper_id,
            markdown=markdown,
            blocks=[
                Block(
                    block_id=f"{paper_id}:b0", paper_id=paper_id, text=abstract,
                    type="prose", page=0, bbox=(10.0, 20.0, 110.0, 220.0),
                    section_path="1. Introduction", index=0,
                )
            ],
            figures=[], tables=[], references=[], parser_id="test-parser-1.x",
        )


@pytest.fixture
def golden_papers():
    return [
        _GoldenPaper(
            paper_id="2506.01234",
            title="A Causal Method for Treatment Effect Estimation",
            abstract="We propose a novel double machine learning estimator for treatment effect "
            "estimation under high-dimensional confounding.",
            markdown="# A Causal Method\n\nWe propose a novel double machine learning estimator "
            "for treatment effect estimation under high-dimensional confounding. Our method "
            "combines cross-fitting with a debiased Neyman-orthogonal score, and we show it "
            "achieves root-n consistency under standard regularity conditions. Experiments on "
            "semi-synthetic benchmarks demonstrate lower bias than naive plug-in estimators.",
        ),
        _GoldenPaper(
            paper_id="2507.05678",
            title="Sparse Attention Mechanisms for Long-Context Retrieval",
            abstract="We introduce a sparse attention variant that reduces quadratic attention "
            "cost to near-linear while preserving retrieval accuracy on long documents.",
            markdown="# Sparse Attention for Long Context\n\nWe introduce a sparse attention "
            "variant that reduces quadratic attention cost to near-linear while preserving "
            "retrieval accuracy on long documents. Our approach clusters keys by locality-"
            "sensitive hashing and attends only within-cluster, then verifies against a held-out "
            "long-document benchmark showing negligible accuracy loss versus full attention.",
        ),
    ]


@pytest.mark.real_adapter  # needs a live Ollama instance — never run by default
def test_summaries_are_non_empty_and_non_degenerate_on_golden_fixtures(
    real_summarizer, golden_papers
):
    summaries = {p.paper_id: real_summarizer.summarize(p.parsed) for p in golden_papers}

    for p in golden_papers:
        text = summaries[p.paper_id]
        assert text.strip(), f"{p.paper_id}: summary_text must be non-empty"
        assert text.strip() != p.parsed.markdown.strip(), (
            f"{p.paper_id}: summary must not just echo the input back"
        )

    # Non-degenerate across the set: a hardcoded constant / near-collapsed summary would make
    # every vector land on one point. At least two distinct golden papers must summarize
    # differently.
    assert len(set(summaries.values())) >= 2, "summaries must differ across >=2 golden fixtures"

    # Not a copy-the-title / copy-the-abstract implementation: the summary must differ verbatim
    # from the paper's own title and abstract (a bare non-empty check misses this).
    for p in golden_papers:
        text = summaries[p.paper_id].strip()
        assert text != (p.title or "").strip(), f"{p.paper_id}: summary is a verbatim title copy"
        assert text != (p.abstract or "").strip(), (
            f"{p.paper_id}: summary is a verbatim abstract copy"
        )
