"""KNOWN_ORGS — the roster of organizations the author-org-tagging feature (see
docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md) matches extracted paper
affiliations against. A plain data constant, not a Config field: this roster is reference data
(which organizations does the user care about tracking), not a per-corpus scope lever the way
focus_area_queries is -- adding an organization is a code edit to this one file, not a config
change duplicated across every corpus's config.yaml.
"""

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


# Seeded from docs/ONBOARDING_AND_ARXIV_KEYWORDS.md's Waymo AV-safety corpus context.
KNOWN_ORGS: list[AuthorOrgTag] = [
    AuthorOrgTag(name="Waymo", email_domains=["waymo.com"], keywords=["waymo"]),
]
