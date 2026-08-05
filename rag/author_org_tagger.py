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

from contracts.author_orgs import KNOWN_ORGS
from contracts.provenance import Block

_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")


def _is_candidate_affiliation_block(block: Block) -> bool:
    """Page-0 blocks that are either front matter (section_path=="", the parser's marker for
    everything before the first real section heading -- see rag/parser.py's _SectionTracker
    comment) or contain an email address (a corresponding-author email is a strong positional
    signal that an affiliation statement is nearby) -- deliberately layout-position-agnostic
    beyond these two conditions, since real papers vary in exactly where affiliations print."""
    return block.page == 0 and (block.section_path == "" or "@" in block.text)


def extract_affiliations_rule_based(blocks: list[Block]) -> list[str]:
    """Step 1 (rule-based variant): each candidate block's raw text, one entry per block, no
    matching against KNOWN_ORGS yet. Blank/whitespace-only blocks are dropped."""
    return [
        block.text for block in blocks
        if _is_candidate_affiliation_block(block) and block.text.strip()
    ]


def match_known_orgs(raw_affiliations: list[str]) -> list[str]:
    """Step 2: deterministic, cheap, re-runnable without re-parsing or re-extracting -- matches
    already-extracted raw_affiliations text against KNOWN_ORGS by email domain (higher precision)
    or keyword substring (catches affiliations printed without an email)."""
    combined = " ".join(raw_affiliations).lower()
    found_domains = {d.lower() for d in _EMAIL_RE.findall(combined)}
    matched = []
    for org in KNOWN_ORGS:
        domain_hit = any(d.lower() in found_domains for d in org.email_domains)
        keyword_hit = any(kw.lower() in combined for kw in org.keywords)
        if domain_hit or keyword_hit:
            matched.append(org.name)
    return matched


def mentions_orgs(title: str, abstract: str) -> list[str]:
    """A weaker, topical signal independent of authorship: does an org's keyword appear in the
    paper's own title/abstract (e.g. "we evaluate on the Waymo Open Motion Dataset")? Must not be
    conflated with match_known_orgs's authorship signal."""
    text = (title + " " + abstract).lower()
    return [org.name for org in KNOWN_ORGS if any(kw.lower() in text for kw in org.keywords)]
