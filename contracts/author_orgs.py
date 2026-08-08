"""KNOWN_ORGS — the roster of organizations the author-org-tagging feature (see
docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md) matches extracted paper
affiliations against. A plain data constant, not a Config field: this roster is reference data
(which organizations does the user care about tracking), not a per-corpus scope lever the way
focus_area_queries is -- adding an organization is a code edit to this one file, not a config
change duplicated across every corpus's config.yaml.
"""

from typing import Literal

from contracts._base import FrozenModel


class AuthorOrgTag(FrozenModel):
    """One organization to match extracted paper affiliations against.

    `email_domains`: matched against email addresses found in a paper's extracted affiliation
    text (e.g. "waymo.com" matches "k.kusano@waymo.com") -- the higher-precision signal, hard to
    have without genuine employment there.

    `keywords`: matched as a case-insensitive substring against extracted affiliation text (e.g.
    "waymo" matches "Waymo LLC, Mountain View, CA") -- catches affiliations printed without an
    accompanying email. Also reused, separately, for the weaker `mentions_orgs` topical signal
    (org named in a paper's title/abstract, regardless of authorship).

    `curated_ids_path` (T-ORG3): an optional path, resolved relative to the repo root, to a
    newline-delimited file of paper ids the org itself is known to have authored -- an enumerated
    fact (e.g. built from the org's own published research index), not a heuristic. `None` (the
    default) means this org has no curated list; `rag/author_org_tagger.py::curated_orgs_for`
    then simply never produces a `"curated"` match for it -- no behavior change from before this
    field existed. This is deliberately reference data on the org roster, not a `Config` field:
    the roster already isn't corpus-scoped (module docstring above), and threading a corpus-
    specific file path through `Config`/pipeline code would leak a Waymo-only concern into `rag/`
    (see `curated_orgs_for`'s docstring for the seam this enables).
    """

    name: str
    email_domains: list[str]
    keywords: list[str]
    curated_ids_path: str | None = None


class AuthorOrgMatch(FrozenModel):
    """One matched organization, carried on `PaperRecord.author_orgs`
    (`contracts/document_store.py`) and (names only) on `VectorPayload.author_orgs`
    (`contracts/vector_index.py`).

    `method` records which signal fired -- never a bare "authored by org X" boolean -- so a
    consumer can demand the high-precision signal when precision matters and accept the broader
    one when recall matters:
    - `"curated"`: the paper id appears on the org's own enumerated list of its published
      research (`AuthorOrgTag.curated_ids_path`, `rag/author_org_tagger.py::curated_orgs_for`).
      This is an ENUMERATED FACT, not a derived signal -- the org itself is the source ("this is
      our research"), so a match here is exact by construction, not a measured approximation. A
      consumer that needs correctness (e.g. "what does Waymo's own research say") should require
      this method and reject the other two.
    - `"email_domain"`: an author's own email at the org's domain (e.g. `@waymo.com`) -- a
      DERIVED heuristic, higher-precision than keyword matching but still imperfect (an author can
      have that email and still not be writing on the org's behalf, or the org's own domain may be
      absent from a paper it did write).
    - `"keyword"`: the org's name/keyword found in extracted affiliation text with no
      accompanying email -- a DERIVED heuristic, broader (catches affiliations printed without an
      email) but noisier than either of the above.

    Precedence when multiple methods match the same org for the same paper: `curated` wins over
    both heuristics (enforced at merge time in `rag/orchestrator.py::_finish` -- an enumerated
    fact from the org itself is never second-guessed by a keyword scan); `email_domain` wins over
    `keyword` when only the two heuristics fire (`match_known_orgs_with_method`,
    `rag/author_org_tagger.py`).

    `email_domain`/`keyword` are DERIVED, IMPERFECT signals, never ground truth: measured live
    over 1,741 done papers against 138 enumerated Waymo-authored ids (T-ORG2/T-ORG3 ground-truth
    correction, `docs/eval-reports/2026-08-07-affiliation-retrieval-first-batch.md`'s 2026-08-08
    addendum) -- the combined email_domain+keyword matcher `match_known_orgs_with_method` ships
    scores precision 0.706 / recall 0.783 (F1 0.742). A consumer doing open-ended discovery
    ("candidates worth a closer look") may accept these; a consumer that needs a correct answer
    must require `curated` and must not accept `email_domain`/`keyword` as a substitute -- at
    ~0.71 precision, roughly 3 in 10 heuristic matches are wrong.
    """

    name: str
    method: Literal["curated", "email_domain", "keyword"]


# Seeded from docs/ONBOARDING_AND_ARXIV_KEYWORDS.md's Waymo AV-safety corpus context.
KNOWN_ORGS: list[AuthorOrgTag] = [
    AuthorOrgTag(
        name="Waymo", email_domains=["waymo.com"], keywords=["waymo"],
        curated_ids_path="fixtures/waymo/waymo_authored_ids.txt",
    ),
]
