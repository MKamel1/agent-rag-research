"""contracts — frozen shared types (T-F1, Owner F).

Every dataclass/TypedDict/protocol shape from DATA-CONTRACTS.md, translated into
runtime-validating pydantic models (see `contracts/_base.py` for why) so a shape mismatch raises
loudly at construction instead of passing silently. **Rule 1 (DATA-CONTRACTS.md): these are
frozen for V0** — changing a shape here is a cross-team event that goes through the T-F7
foundation-change protocol, never a quiet edit in one module.

Import the specific submodule (e.g. `from contracts.provenance import Anchor`) or the flat
re-export below (`from contracts import Anchor`) — both resolve to the same class.
"""

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.document_store import PaperRecord
from contracts.embedder import EmbedderInfo, Vector
from contracts.errors import ContractError, PermanentError, TransientError
from contracts.fusion import RRF_K, rrf_fuse
from contracts.gpu_lock import GpuLock
from contracts.harvester import PaperRef
from contracts.mcp_server import (
    Coverage,
    PaperSearchResponse,
    PaperSearchResult,
    PaperSummaryView,
    SearchResponse,
)
from contracts.parser import Figure, ParsedDoc, Reference, TableItem
from contracts.provenance import Anchor, Bbox, Block, BlockType
from contracts.retriever import Citation, EvidenceTier, GroundedResult, RerankCandidate
from contracts.vector_index import Hit, SearchFilters, VectorPayload

__all__ = [
    "RRF_K",
    "Anchor",
    "Bbox",
    "Block",
    "BlockType",
    "Chunk",
    "Citation",
    "Config",
    "ContractError",
    "Coverage",
    "EmbedderInfo",
    "EvidenceTier",
    "Figure",
    "GpuLock",
    "GroundedResult",
    "Hit",
    "PaperRecord",
    "PaperRef",
    "PaperSearchResponse",
    "PaperSearchResult",
    "PaperSummaryView",
    "ParsedDoc",
    "PermanentError",
    "Reference",
    "RerankCandidate",
    "SearchFilters",
    "SearchResponse",
    "TableItem",
    "TransientError",
    "Vector",
    "VectorPayload",
    "rrf_fuse",
]
