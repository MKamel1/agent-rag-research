"""M6 VectorIndex (DATA-CONTRACTS.md "M6 VectorIndex").

`VectorIndex`'s own interface (`hybrid_search`/`upsert`/`rebuild`) is the module's own interface
(ARCHITECTURE.md, owned by Owner D) — not reproduced here; only the data shapes that cross the
seam are. The RRF fusion formula and its `RRF_K` constant live in `contracts/fusion.py`, not
here — see that module.
"""

from datetime import date
from typing import Literal, TypedDict

from contracts._base import FrozenModel


class Hit(FrozenModel):
    id: str  # chunk_id or summary_id
    kind: Literal["chunk", "summary"]  # so Retriever branches on type without parsing the id string
    score: float  # the fused RRF score (see contracts/fusion.py)


class SearchFilters(FrozenModel):
    """Replaces an untyped `filters: dict` — the one hot-path shape that was crossing the
    VectorStore seam with no agreed grammar. Every field maps to a `VectorPayload` field of the
    same name.
    """

    categories: list[str] | None = None  # any-overlap match against VectorPayload.categories
    published_after: date | None = None  # inclusive
    published_before: date | None = None  # inclusive
    kind: Literal["chunk", "summary"] | None = None  # restrict to VectorPayload.kind


class VectorPayload(TypedDict):
    """Stored beside each vector. A plain `TypedDict` (not a `FrozenModel`) on purpose: this is
    exactly the dict handed to the vector store adapter's `payload=` argument (real vector-store
    clients expect plain dicts, not model instances) — DATA-CONTRACTS.md itself defines it as
    `TypedDict`, unlike every other shape in this file.

    `text` carries the real chunk/summary passage text — it is what the sparse/keyword search
    channel tokenizes and indexes (previously the sparse channel had no real text available at this
    seam and hashed `section_path` instead, a heading string, which meant "keyword search" wasn't
    actually searching passage content). `section_path` remains as metadata only (filtering/display),
    not as a text source for search. The DocumentStore is still the source of truth for this text;
    it is duplicated here because the vector store needs it locally to build the sparse vector.
    """

    paper_id: str
    kind: Literal["chunk", "summary"]
    section_path: str
    text: str
    categories: list[str]  # for metadata filtering
    published: str  # ISO date, for date-range filters
    embedding_version: str  # must match the collection's model version
