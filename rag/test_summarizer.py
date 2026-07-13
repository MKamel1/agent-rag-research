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
  - The **quality / non-degeneracy** check needs the real generation LLM over Owner B's golden
    fixtures — it opts out of the socket-disabled default run (nightly / M2 real-adapter job).
    Its assertions are encoded here; the `real_summarizer`/`golden_papers` fixtures that feed it
    are provided by that job and skip by default, so the default suite stays green.
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
from rag.summarizer import (  # noqa: E402
    _NUM_CTX_CEILING,
    _NUM_CTX_FLOOR,
    _fit_for_summarization,
)

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
# _fit_for_summarization: reference/appendix trimming + per-paper num_ctx sizing
# (.phase0-data/known-issue-pass2-oom.md) -- pure logic, no GPU/network involved.
# ---------------------------------------------------------------------------


def test_fit_for_summarization_drops_references_section():
    prose = "# Method\n\nWe do X.\n\n# References\n\n" + ("Citation. " * 5000)
    text, _ = _fit_for_summarization(PAPER_ID, prose)
    assert "References" not in text
    assert "We do X." in text


def test_fit_for_summarization_drops_appendix_section():
    prose = "# Method\n\nWe do X.\n\n# Appendix\n\n" + ("Proof. " * 5000)
    text, _ = _fit_for_summarization(PAPER_ID, prose)
    assert "Appendix" not in text
    assert "We do X." in text


def test_fit_for_summarization_num_ctx_scales_with_length_within_bounds():
    _, short_ctx = _fit_for_summarization(PAPER_ID, "word " * 50)
    _, long_ctx = _fit_for_summarization(PAPER_ID, "word " * 5000)
    assert short_ctx < long_ctx
    assert _NUM_CTX_FLOOR <= short_ctx <= _NUM_CTX_CEILING
    assert _NUM_CTX_FLOOR <= long_ctx <= _NUM_CTX_CEILING


def test_fit_for_summarization_truncates_and_clamps_for_huge_input():
    # No references/appendix heading here -- exercises the fallback truncation path for a paper
    # whose main body alone still exceeds the safe ceiling (a real, observed corpus case).
    huge = "word " * 200_000
    text, num_ctx = _fit_for_summarization(PAPER_ID, huge)
    assert num_ctx <= _NUM_CTX_CEILING  # rounding can land a few tokens under, never over
    assert len(text.split()) < 200_000


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


def test_summarize_request_disables_thinking_and_sets_context_options():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "A summary."})

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    adapter = _build_summarizer_with_client(client, FakeGpuLock())
    adapter.summarize(_prose_doc())

    body = captured["body"]
    assert body["think"] is False, (
        "thinking must stay off on this Ollama-based v1 stack -- verified directly this session "
        "that a thinking-enabled call shares one token budget between reasoning and the answer, "
        "so an unbounded/large budget risks an empty answer (see rag/summarizer.py's comment)"
    )
    assert "num_ctx" in body["options"] and "num_predict" in body["options"]


def test_response_body_missing_response_field_maps_to_permanent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected_shape": True})

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    adapter = _build_summarizer_with_client(client, FakeGpuLock())
    with pytest.raises(PermanentError):
        adapter.summarize(_prose_doc())


# ---------------------------------------------------------------------------
# Quality / non-degeneracy on the golden-fixture set (real LLM — nightly / M2).
# The `real_summarizer` and `golden_papers` fixtures are supplied by the real-adapter job and
# skip by default, so this assertion set is encoded now but stays green in default CI.
# ---------------------------------------------------------------------------


@pytest.fixture
def real_summarizer():
    pytest.skip(
        "real generation-LLM Summarizer runs only in the nightly/M2 real-adapter job (GPU); "
        "the default socket-disabled CI has no service — see pyproject [tool.pytest] socket note"
    )


@pytest.fixture
def golden_papers():
    # Owner B's golden Parser fixtures (fixtures/golden/) exposed as objects with `.parsed`
    # (ParsedDoc), `.title`, `.abstract`. Provided by the real-adapter job alongside a live LLM.
    pytest.skip("golden Parser fixtures + real LLM are supplied by the nightly/M2 real-adapter job")


def test_summaries_are_non_empty_and_non_degenerate_on_golden_fixtures(
    real_summarizer, golden_papers
):
    summaries = {p.paper_id: real_summarizer.summarize(p.parsed) for p in golden_papers}

    for pid, text in summaries.items():
        assert text.strip(), f"{pid}: summary_text must be non-empty"

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
