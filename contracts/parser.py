"""M2 Parser output (DATA-CONTRACTS.md "M2 Parser output")."""

from pydantic import Field

from contracts._base import FrozenModel
from contracts.provenance import Bbox, Block


class Figure(FrozenModel):
    paper_id: str
    image_path: str  # filesystem path to extracted PNG (source-of-truth blob)
    caption: str
    page: int = Field(ge=0)
    bbox: Bbox
    vlm_description: str | None = None  # ALWAYS None in V0; filled by the V3 VLM enricher


class TableItem(FrozenModel):
    paper_id: str
    markdown: str  # table rendered as markdown
    caption: str
    page: int = Field(ge=0)
    bbox: Bbox


class Reference(FrozenModel):
    raw: str  # raw reference string (from GROBID)
    title: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None


class ParsedDoc(FrozenModel):
    """Parser invariant (DATA-CONTRACTS.md): every `Block` has a valid `page` and `bbox`. A block
    without them is a contract violation -> crash early; never emit a block with
    `bbox=(0,0,0,0)` as a fake.
    """

    paper_id: str
    markdown: str  # full body as markdown (equations as LaTeX, code fenced)
    blocks: list[Block]  # reading-order; EVERY block carries page+bbox (the anchor source)
    figures: list[Figure]
    tables: list[TableItem]
    references: list[Reference]
    parser_id: str  # which adapter produced this (e.g. "mineru-1.x") — for reproducibility
