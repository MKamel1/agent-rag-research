"""M6 VectorIndex (DATA-CONTRACTS.md "M6 VectorIndex").

`VectorIndex`'s own interface (`hybrid_search`/`upsert`/`rebuild`/`delete`) is the module's own
interface (ARCHITECTURE.md, owned by Owner D) — not reproduced here; only the data shapes that
cross the seam are. The RRF fusion formula and its `RRF_K` constant live in `contracts/fusion.py`,
not here — see that module.

`delete(ids: list[str]) -> None` (T-DOC40): removes the points for the given `chunk_id`/
`summary_id`s. Idempotent — deleting an id that was never upserted (or already deleted) is a safe
no-op, same as `upsert`'s own by-id semantics. This is the other half of `DocumentStore.delete()`'s
cross-store cleanup (see that module's docstring) — a caller that deletes from SQLite alone and
never calls this leaves exactly the orphaned-vector class T-DOC23/T-DOC40 exist to close.
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
    doc_type: Literal["paper", "book"] | None = None  # restrict to VectorPayload.doc_type
    paper_id: str | None = None  # restrict to VectorPayload.paper_id -- one document, Decision 3
    # T-ORG1: restrict to VectorPayload.author_orgs containing this name -- one org name in, not a
    # list (unlike categories' any-overlap), since a caller asks "papers by org X," not "papers by
    # any of these orgs." By default this matches ANY method (curated, email_domain, or keyword)
    # -- NOT authoritative on its own: the email_domain/keyword heuristic (the majority source of
    # VectorPayload.author_orgs) measures precision 0.706 / recall 0.783 over 1,741 done papers
    # against 138 known-positive ids (T-ORG2/T-ORG3, docs/eval-reports/2026-08-07-affiliation-
    # retrieval-first-batch.md's 2026-08-08 addendum) -- see AuthorOrgMatch's docstring
    # (contracts/author_orgs.py) for the full numbers. Treat a hit here as "worth a closer look,"
    # not "confirmed," UNLESS `author_org_curated_only` is also set (see below).
    author_org: str | None = None
    # T-ORG3: when True, restrict to VectorPayload.curated_author_orgs instead of author_orgs --
    # the enumerated, authoritative tier only (AuthorOrgMatch.method == "curated"), never the
    # email_domain/keyword heuristic. This is the flag a caller sets to demand "papers Waymo
    # actually wrote" and get back only exact hits, not "worth a closer look" candidates. Only
    # takes effect when `author_org` is also set -- on its own (author_org=None) it is a no-op,
    # same as every other filter field here that means "don't filter on this."
    author_org_curated_only: bool = False
    # 2026-08-19: cap how many passages a SINGLE paper may contribute to one result set.
    #
    # `None` (the default) means uncapped, which is `semantic_search`'s long-standing behaviour and
    # is deliberately left as the default: passage-level search is often a DEEP DIVE ("show me the
    # evidence in this paper"), and a blanket cap would drop a gold passage that happens to rank
    # 5th within its own paper -- a recall regression, the opposite of what this field is for.
    #
    # Set it when the question is an ENUMERATION ("which papers used method X"), where the failure
    # mode runs the other way: ranking is by passage relevance, so one verbose paper crowds out
    # papers that mention the method once, plainly. Measured on the Waymo corpus before this
    # existed: a single paper took 13 of 30 result slots for "bootstrap resampling confidence
    # interval", starving the enumeration of distinct papers.
    #
    # `retrieve_papers()` (search_papers) applies its own separate default cap
    # (`rag/retriever.py::_MAX_HITS_PER_PAPER`, T-DOC82) and does not need this; this field is what
    # gives the PASSAGE path the same lever, on demand rather than always.
    #
    # Note this bounds distinct papers only as far as the candidate pool allows -- it cannot invent
    # papers the first-stage hybrid search never surfaced. For guaranteed-complete enumeration use
    # the corpus scan tool, which touches every paper, rather than expecting top-k to be exhaustive.
    max_hits_per_paper: int | None = None
    # 2026-08-19: ensure at least this many DISTINCT papers appear, by ADDING rather than removing.
    #
    # The additive counterpart to `max_hits_per_paper` above, and the safer of the two. Capping is
    # SUBTRACTIVE: it deletes passages to make room, so a gold passage ranked 5th inside its own
    # paper is silently gone under a cap of 3, and nothing in the response says so. This instead
    # keeps the top `k` exactly as ranked and APPENDS the best not-yet-seen passage from further
    # papers until the count is met -- so no passage that would have been returned is ever lost.
    # Recall cannot regress under this field; it can under `max_hits_per_paper`.
    #
    # The cost is the honest one: the result set can exceed `k`. A caller with a fixed context
    # budget is trading tokens for coverage, which is the right trade to make explicitly rather
    # than to have a cap make silently on its behalf.
    #
    # Bounded by the candidate pool: this can only surface papers the first-stage hybrid search
    # already retrieved. Guaranteed-complete enumeration is `scan_corpus`, which examines every
    # paper rather than the pool.
    min_distinct_papers: int | None = None


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
    doc_type: str  # "paper" | "book" — mirrors PaperRef.doc_type
    author_orgs: list[str]  # T-ORG1: matched org names only (no method -- filtering doesn't need
    # it) -- mirrors PaperRecord.author_orgs. Absent (not []) on any point upserted before this
    # field existed, same legacy-key convention as doc_type above.
    curated_author_orgs: list[str]  # T-ORG3: the subset of author_orgs whose method is "curated"
    # -- what SearchFilters.author_org_curated_only filters against. Absent (not []) on any point
    # upserted before this field existed, same legacy-key convention as author_orgs above.
