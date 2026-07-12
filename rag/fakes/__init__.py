"""rag.fakes — deterministic, zero-GPU, zero-network stand-ins for every real adapter seam
(T-F4, Owner F).

Per TEST-STRATEGY.md's "Fakes" section: each fake is a *large adapter with a small
implementation* — it satisfies the real interface with trivial, deterministic behaviour so
downstream modules (Chunker, Retriever, Orchestrator, ...) can be tested in isolation, with no
model, no GPU, and no network call. Every one implements the **exact** interface named in
ARCHITECTURE.md / DATA-CONTRACTS.md — if the real interface changes, the fake changes with it
(they're tested together, see contract tests in TEST-STRATEGY.md).

Import the specific submodule (e.g. `from rag.fakes.fake_embedder import FakeEmbedder`) or the
flat re-export below.
"""

from rag.fakes.fake_embedder import FakeEmbedder
from rag.fakes.fake_gpu_lock import FakeGpuLock
from rag.fakes.fake_ingest_state import FakeIngestState
from rag.fakes.fake_reranker import FakeReranker
from rag.fakes.fake_source import FakeSource
from rag.fakes.fake_summarizer import FakeSummarizer
from rag.fakes.fake_vector_store import FakeVectorStore

__all__ = [
    "FakeEmbedder",
    "FakeGpuLock",
    "FakeIngestState",
    "FakeReranker",
    "FakeSource",
    "FakeSummarizer",
    "FakeVectorStore",
]
