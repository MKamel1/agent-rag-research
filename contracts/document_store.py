"""M5 DocumentStore — what `put` persists (DATA-CONTRACTS.md "M5 DocumentStore — what `put`
persists").

`DocumentStore`'s own interface (`put`/`get`/`get_blocks`/`get_block`/`get_chunk`/`get_summary`/
`get_span`/`iter_papers`) is the module's own interface (ARCHITECTURE.md, owned by Owner D) —
not reproduced here as a `contracts/` type; only the data shape it persists (`PaperRecord`)
crosses the seam.
"""

from pydantic import Field

from contracts._base import FrozenModel
from contracts.chunker import Chunk
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc


class PaperRecord(FrozenModel):
    """The complete source-of-truth bundle for one paper. `DocumentStore.put(PaperRecord)` is
    atomic: either the whole paper is stored or none of it (so a crash never leaves half a
    paper).

    `relevance_score` here is the AUTHORITATIVE value (unlike `PaperRef.relevance_score`, which
    is always `None`). Computed by `IngestionOrchestrator` (M9), after `Summarizer` and before
    this `put()` call, as `cosine(embed(summary_text), topic_query_vec)` — see DATA-CONTRACTS.md
    for the exact "compute topic_query_vec exactly once per ingestion run" rule. Persisted to
    `papers.relevance_score` (SQL schema).
    """

    ref: PaperRef
    parsed: ParsedDoc
    chunks: list[Chunk]
    summary_text: str
    summary_id: str
    relevance_score: float | None = Field(default=None)
    # blobs (PDF, figure PNGs, markdown) are written to the filesystem; their paths live on
    # ref/parsed.
