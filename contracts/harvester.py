"""M1 Harvester output (DATA-CONTRACTS.md "M1 Harvester output")."""

from datetime import date

from pydantic import Field

from contracts._base import FrozenModel


class PaperRef(FrozenModel):
    """One paper as returned by the Harvester, before parsing/summarizing.

    `relevance_score` is ALWAYS `None` when produced by the Harvester — scoring needs
    `summary_text`, which doesn't exist yet at harvest time. The authoritative value lives on
    `PaperRecord.relevance_score` (see `contracts/document_store.py`), computed later by
    `IngestionOrchestrator`. Do not compute it here.
    """

    paper_id: str  # base arXiv id (no version)
    version: str  # "v1", "v2", ...
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]  # e.g. ["cs.LG", "stat.ME"]
    published: date
    updated: date
    pdf_url: str
    # arXiv e-print source, if available (enables the LaTeX ingest path)
    latex_url: str | None = None
    relevance_score: float | None = Field(default=None)
