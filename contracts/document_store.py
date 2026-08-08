"""M5 DocumentStore — what `put` persists (DATA-CONTRACTS.md "M5 DocumentStore — what `put`
persists").

`DocumentStore`'s own interface (`put`/`get`/`get_blocks`/`get_block`/`get_chunk`/`get_summary`/
`get_span`/`iter_papers`) is the module's own interface (ARCHITECTURE.md, owned by Owner D) —
not reproduced here as a `contracts/` type; only the data shape it persists (`PaperRecord`)
crosses the seam.
"""

from pydantic import Field

from contracts._base import FrozenModel
from contracts.author_orgs import AuthorOrgMatch
from contracts.chunker import Chunk
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc


class ChapterSummary(FrozenModel):
    """One chapter's map-step summary for a doc_type="book" record. Persisted in the same
    `summaries` table as the whole-document summary (migration 0004 adds `title`), embedded as its
    own kind="summary" vector so search_papers can return individual chapters as routing hits."""

    summary_id: str  # f"{paper_id}:summary:ch{n}", n = 0-based chapter index (DATA-CONTRACTS §IDs)
    # Best-scoring top-level heading merged into this unit (T-DOC85's `_title_score`), NOT
    # necessarily its first heading. "" only when no merged heading scored above the usability
    # floor -- in that case the title may instead be MODEL-GENERATED (an LLM asked to title the
    # chapter from its own summary, kind="book_title"), not extracted from the document at all;
    # "" persists only if that fallback also failed to produce a usable title.
    title: str
    text: str        # non-empty chapter summary


class PaperRecord(FrozenModel):
    """The complete source-of-truth bundle for one paper. `DocumentStore.put(PaperRecord)` is
    atomic: either the whole paper is stored or none of it (so a crash never leaves half a
    paper).

    `relevance_score` here is the AUTHORITATIVE value (unlike `PaperRef.relevance_score`, which
    is always `None`) — computed by `IngestionOrchestrator`; full rule (incl. the
    once-per-run `topic_query_vec` invariant): ARCHITECTURE.md §M9.
    """

    ref: PaperRef
    parsed: ParsedDoc
    chunks: list[Chunk]
    summary_text: str
    summary_id: str
    relevance_score: float | None = Field(default=None)
    chapter_summaries: list[ChapterSummary] = Field(default_factory=list)  # non-empty only for books
    # T-ORG1: author-org tagging evidence (rag/author_org_tagger.py). `raw_affiliations` is the
    # extracted candidate text (Step 1); `author_orgs` is what it matched against KNOWN_ORGS, WITH
    # which signal fired (Step 2, `match_known_orgs_with_method`) -- see `AuthorOrgMatch`'s
    # docstring (`contracts/author_orgs.py`) for the measured precision/recall. Both default to
    # `[]`: most pre-existing rows genuinely have never been checked, and a paper with no
    # extractable affiliation text legitimately has no evidence either. NEVER treat a non-empty
    # `author_orgs` as ground-truth authorship -- it is a derived, imperfect signal.
    raw_affiliations: list[str] = Field(default_factory=list)
    author_orgs: list[AuthorOrgMatch] = Field(default_factory=list)
    # blobs (PDF, figure PNGs, markdown) are written to the filesystem; their paths live on
    # ref/parsed.
