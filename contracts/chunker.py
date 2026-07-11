"""M3 Chunker output (DATA-CONTRACTS.md "M3 Chunker output")."""

from contracts._base import FrozenModel
from contracts.provenance import Anchor


class Chunk(FrozenModel):
    """`contextual_header` is a V1 feature, not a V0 toggle — do not populate it in V0.
    Full rationale: PRD ADR-07.
    """

    chunk_id: str
    paper_id: str
    text: str
    anchor: Anchor
    # derived — copied from the anchoring block at chunk time (see Block.section_path)
    section_path: str
    # ALWAYS a block_id, never a chunk_id (parent-child, ON in V0). By construction this is the
    # same block as `anchor.block_id` (multi-block anchoring rule, DATA-CONTRACTS.md "Provenance
    # & structure") — Retriever never needs to guess which one it is.
    parent_id: str | None
    contextual_header: str | None = None  # ALWAYS None in V0 — see docstring above
