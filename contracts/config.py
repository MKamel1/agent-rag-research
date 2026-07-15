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
    # Pass 1 (rag/orchestrator.py `parse_phase`): how many papers `Parser.parse_batch`
    # (rag/parser.py) sends through one parser backend call at a time. T-DOC16 (.phase0-data/
    # pass1-gpu-underutilization.md): the parser backend's per-document pipeline leaves the GPU
    # idle between its own sequential sub-model stages; batching N documents into one call fills
    # those gaps -- see rag/parser.py's module docstring for the vendor-specific mechanism.
    # Conservative default, not yet validated against real GPU/host-RAM headroom at N>4
    # (real-GPU spike still pending -- see that doc's "Still required" section).
    parse_batch_size: int = Field(default=4, gt=0)
    # composition-root levers (T-DOC29): previously scattered process-environment reads in
    # app/ingest.py, app/parse_phase.py, app/assembly.py, app/prefetch_pdfs.py -- moved onto
    # Config so CONVENTIONS.md §3 ("only Config reads env/files") actually holds for app/, not
    # just rag/contracts/ (this module's own docstring). Defaults below match each old call
    # site's env-var-with-fallback behavior exactly, so an unedited config.yaml reproduces the
    # old unset-env-var behavior byte for byte.
    db_path: str = "papers.db"
    blob_dir: str = "blobs"
    collection: str = "papers"
    # "" (empty string) explicitly disables the PDF cache (app/assembly.py logs this, doesn't
    # crash) -- same meaning an explicitly-empty `RAG_PDF_CACHE_DIR=""` used to have.
    pdf_cache_dir: str = "pdf_cache"
    # Unset (None) writes no CSV -- investigation tooling for one run, not a default-on feature
    # (app/assembly.py's AdaptiveBatchSizer wiring).
    batch_size_log_path: str | None = None
    # app/prefetch_pdfs.py's standalone PDF-backlog target. Distinct from corpus_cap (how many
    # papers one harvest() call returns): this is how many local PDF files the prefetcher tries to
    # keep cached, independently of the live pipeline's own corpus size.
    prefetch_target: int = Field(default=30_000, gt=0)
    # T-EVAL harvest-scoping override (PR #89): when set, app/ingest.py and app/parse_phase.py
    # fetch exactly these known arXiv ids via `ArxivSource.fetch_by_ids()` instead of the
    # query-driven harvest() below -- guarantees the 210-question eval set's 100 source papers are
    # actually in the corpus. None (the default) leaves normal harvest() behavior unchanged.
    ingest_paper_ids: list[str] | None = None
