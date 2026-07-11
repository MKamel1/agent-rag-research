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
from unittest.mock import MagicMock

import pytest

# M1a CI convention (CONVENTIONS §0.7 / §11): skip the whole suite until rag/summarizer.py lands.
_mod = pytest.importorskip("rag.summarizer")

from contracts.errors import PermanentError  # noqa: E402
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
