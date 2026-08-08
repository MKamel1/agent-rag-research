"""Rule-based affiliation extraction + KNOWN_ORGS matching (see
docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md §4). Pure functions, no
vendor/HTTP dependency -- the LLM-based extraction alternative lives in the generation-LLM
summarizer adapter instead, per this repo's vendor-isolation rule confining any generation-vendor
name to that one adapter file (ci/checks/vendor_isolation.py).

extract_affiliations_rule_based is genuinely org-agnostic (returns raw candidate-region block
text, no KNOWN_ORGS awareness) -- match_known_orgs is the separate, cheap, re-runnable-without-
re-parsing step that actually checks against known organizations. Adding an organization later
only means re-running match_known_orgs over already-extracted raw_affiliations.
"""

import re

from contracts.author_orgs import KNOWN_ORGS, AuthorOrgMatch
from contracts.provenance import Block

_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")


# T-ORG2: front matter includes the ABSTRACT, and an abstract that cites a Waymo dataset used to
# keyword-match as Waymo AUTHORSHIP -- the dominant false-positive source on a corpus where most
# papers benchmark on such datasets. Affiliation lines and abstracts are different objects by
# length: measured over 1,741 done papers, front-matter blocks containing "waymo" run a median of
# 6 words in genuinely Waymo-authored papers ("Waymo LLC, Mountain View, CA") against 166 in the
# rest. Capping candidate blocks at 40 words took precision 0.311 -> 0.573 against the 114
# enumerated Waymo-authored ids, costing recall 0.851 -> 0.754. A length ceiling is used rather
# than diffing against `papers.abstract` because this module is a pure function over Blocks with
# no store access; it also catches the other observed false-positive source, long index-terms
# lines naming the dataset.
_MAX_AFFILIATION_BLOCK_WORDS = 40


def _is_candidate_affiliation_block(block: Block) -> bool:
    """Page-0 blocks that are either front matter (section_path=="", the parser's marker for
    everything before the first real section heading -- see rag/parser.py's _SectionTracker
    comment) or contain an email address (a corresponding-author email is a strong positional
    signal that an affiliation statement is nearby) -- deliberately layout-position-agnostic
    beyond these two conditions, since real papers vary in exactly where affiliations print.

    Long blocks are excluded (see `_MAX_AFFILIATION_BLOCK_WORDS`) UNLESS they carry an email: a
    parser that merges the affiliation into a longer run of text would otherwise lose a genuine
    affiliation, and an email is strong enough positive evidence to override the ceiling."""
    if block.page != 0:
        return False
    has_email = "@" in block.text
    if not (block.section_path == "" or has_email):
        return False
    return has_email or len(block.text.split()) <= _MAX_AFFILIATION_BLOCK_WORDS


def extract_affiliations_rule_based(blocks: list[Block]) -> list[str]:
    """Step 1 (rule-based variant): each candidate block's raw text, one entry per block, no
    matching against KNOWN_ORGS yet. Blank/whitespace-only blocks are dropped."""
    return [
        block.text for block in blocks
        if _is_candidate_affiliation_block(block) and block.text.strip()
    ]


def match_known_orgs_with_method(raw_affiliations: list[str]) -> list[AuthorOrgMatch]:
    """Step 2, method-preserving variant (T-ORG1): same matching as `match_known_orgs`, but keeps
    which signal fired for each match -- see `AuthorOrgMatch`'s docstring (`contracts/author_orgs.py`)
    for the measured precision/recall behind why that matters. `email_domain` wins when both
    signals fire for the same org, since it is the higher-precision one.

    Returns `AuthorOrgMatch` (not a bare `(name, method)` tuple): `AuthorOrgMatch` is also what
    `PaperRecord.author_orgs` (`contracts/document_store.py`) stores, so this function's output is
    the exact value the orchestrator persists -- one shape, not a tuple representation that then
    needs converting."""
    combined = " ".join(raw_affiliations).lower()
    found_domains = {d.lower() for d in _EMAIL_RE.findall(combined)}
    matched = []
    for org in KNOWN_ORGS:
        domain_hit = any(d.lower() in found_domains for d in org.email_domains)
        keyword_hit = any(kw.lower() in combined for kw in org.keywords)
        if domain_hit or keyword_hit:
            method = "email_domain" if domain_hit else "keyword"
            matched.append(AuthorOrgMatch(name=org.name, method=method))
    return matched


def match_known_orgs(raw_affiliations: list[str]) -> list[str]:
    """Step 2: deterministic, cheap, re-runnable without re-parsing or re-extracting -- matches
    already-extracted raw_affiliations text against KNOWN_ORGS by email domain (higher precision)
    or keyword substring (catches affiliations printed without an email). Thin wrapper over
    `match_known_orgs_with_method` -- exactly one matching implementation, not two that can drift
    -- for callers that only need the matched org names (existing shape, unchanged)."""
    return [match.name for match in match_known_orgs_with_method(raw_affiliations)]


def mentions_orgs(title: str, abstract: str) -> list[str]:
    """A weaker, topical signal independent of authorship: does an org's keyword appear in the
    paper's own title/abstract (e.g. "we evaluate on the Waymo Open Motion Dataset")? Must not be
    conflated with match_known_orgs's authorship signal."""
    text = (title + " " + abstract).lower()
    return [org.name for org in KNOWN_ORGS if any(kw.lower() in text for kw in org.keywords)]
