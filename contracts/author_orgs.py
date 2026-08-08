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
    """

    name: str
    email_domains: list[str]
    keywords: list[str]


class AuthorOrgMatch(FrozenModel):
    """One matched organization, carried on `PaperRecord.author_orgs`
    (`contracts/document_store.py`) and (names only) on `VectorPayload.author_orgs`
    (`contracts/vector_index.py`).

    `method` records which signal fired -- never a bare "authored by org X" boolean -- so a
    consumer can demand the high-precision signal when precision matters and accept the broader
    one when recall matters:
    - `"email_domain"`: an author's own email at the org's domain (e.g. `@waymo.com`) -- the
      higher-precision signal.
    - `"keyword"`: the org's name/keyword found in extracted affiliation text with no
      accompanying email -- broader (catches affiliations printed without an email) but noisier.

    `email_domain` wins when both signals fire for the same org (`match_known_orgs_with_method`,
    `rag/author_org_tagger.py`). This is a DERIVED, IMPERFECT signal, never ground truth: measured
    live over 1,741 done papers against 114 enumerated Waymo-authored ids (T-ORG2, commit
    `d3e79c3`) -- keyword matching scores precision 0.569 / recall 0.763; email-domain-only scores
    precision 0.700 but recall only 0.123 (81% of extracted affiliation regions carry no email at
    all). At 0.569 precision, close to half of keyword-derived matches are wrong.
    """

    name: str
    method: Literal["email_domain", "keyword"]


# Seeded from docs/ONBOARDING_AND_ARXIV_KEYWORDS.md's Waymo AV-safety corpus context.
KNOWN_ORGS: list[AuthorOrgTag] = [
    AuthorOrgTag(name="Waymo", email_domains=["waymo.com"], keywords=["waymo"]),
]
