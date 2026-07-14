"""Config — the levers, one injected object, never scattered env reads (DATA-CONTRACTS.md
"Config").

This module defines only the `Config` *shape* (it is a dataclass/TypedDict-equivalent listed in
DATA-CONTRACTS.md like every other type in this package, so T-F1 owns it). The *loader* —
reading `config.yaml` from disk and constructing a `Config` from it — is T-F2's ticket, and
lives outside `contracts/` (see `GIT-WORKFLOW.md`'s CODEOWNERS list, which names `rag/config.py`
and `contracts/**` as two separate foundation paths). No module other than that loader may call
`os.getenv`/read `config.yaml` directly (CONVENTIONS.md §3) — everyone else receives a
already-constructed `Config` instance.
"""

from typing import Literal

from pydantic import Field

from contracts._base import FrozenModel


class Config(FrozenModel):
    # scope levers (CONTEXT.md registry) — the knobs that must never be buried constants
    focus_area_queries: list[str]  # arXiv search queries defining the topic
    corpus_cap: int = Field(default=15_000, gt=0)
    ordering: Literal["freshest_first"] = "freshest_first"
    ingestion_mode: Literal["one_shot_seed"] = "one_shot_seed"
    sources: list[str] = Field(default_factory=lambda: ["arxiv"])
    relevance_filter: Literal["off", "embedding"] = "off"
    # retrieval knobs (tuned in Spike 2)
    # NOTE: no `contextual_header` toggle — it's not built in V0 (PRD ADR-07).
    child_parent_expansion: bool = True
    top_k: int = Field(default=10, gt=0)
    rerank_depth: int = Field(default=50, gt=0)
    hybrid_dense_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    # both composition roots build their real GpuLock from this path, so they contend for the
    # same file.
    gpu_lock_path: str = ".gpu.lock"
    # Pass 1 (rag/orchestrator.py `parse_phase`): how many papers `Parser.parse_batch` sends
    # through one MinerU `do_parse` call at a time. T-DOC16 (.phase0-data/
    # pass1-gpu-underutilization.md): MinerU's per-document pipeline leaves the GPU idle between
    # its own sequential sub-model stages; batching N documents into one `do_parse` call fills
    # those gaps. Conservative default, not yet validated against real GPU/host-RAM headroom at
    # N>4 (real-GPU spike still pending -- see that doc's "Still required" section).
    parse_batch_size: int = Field(default=4, gt=0)
