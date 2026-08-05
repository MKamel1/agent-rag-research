"""Offline unit tests for rag/author_org_tagger.py -- no network, no GPU, canned Block fixtures.
Fixture shape mirrors rag/test_parser.py's `_block()` helper (Block's real required fields,
including `index`, which `contracts.provenance.Block` requires but is otherwise irrelevant here)."""
from contracts.provenance import Block
from rag.author_org_tagger import (
    extract_affiliations_rule_based,
    match_known_orgs,
    mentions_orgs,
)


def _block(text, page=0, section_path="", block_id="b1", index=0):
    return Block(
        block_id=block_id, paper_id="test", text=text, type="prose",
        page=page, bbox=(10.0, 20.0, 110.0, 220.0), section_path=section_path, index=index,
    )


def test_extract_picks_up_front_matter_blocks_on_page_zero():
    blocks = [
        _block("K. Kusano, J. Doe", section_path=""),
        _block("Introduction", section_path="Introduction"),  # not front matter -- excluded
        _block("We study rare events.", section_path="Introduction"),
    ]
    result = extract_affiliations_rule_based(blocks)
    assert result == ["K. Kusano, J. Doe"]


def test_extract_picks_up_blocks_with_an_email_even_outside_front_matter():
    blocks = [
        _block("Correspondence: k.kusano@waymo.com", section_path="Author Note"),
    ]
    result = extract_affiliations_rule_based(blocks)
    assert result == ["Correspondence: k.kusano@waymo.com"]


def test_extract_ignores_page_one_even_if_it_looks_like_front_matter():
    blocks = [_block("Some footer text", page=1, section_path="")]
    assert extract_affiliations_rule_based(blocks) == []


def test_extract_skips_blank_blocks():
    blocks = [_block("   ", section_path="")]
    assert extract_affiliations_rule_based(blocks) == []


def test_match_known_orgs_finds_waymo_by_email_domain():
    assert match_known_orgs(["Contact: k.kusano@waymo.com"]) == ["Waymo"]


def test_match_known_orgs_finds_waymo_by_keyword_without_email():
    assert match_known_orgs(["Waymo LLC, Mountain View, CA"]) == ["Waymo"]


def test_match_known_orgs_empty_when_no_match():
    assert match_known_orgs(["MIT, Cambridge, MA", "contact@mit.edu"]) == []


def test_match_known_orgs_empty_list_input():
    assert match_known_orgs([]) == []


def test_mentions_orgs_finds_waymo_in_abstract():
    result = mentions_orgs("A study of driving", "We evaluate on the Waymo Open Motion Dataset.")
    assert result == ["Waymo"]


def test_mentions_orgs_case_insensitive():
    result = mentions_orgs("WAYMO study", "")
    assert result == ["Waymo"]


def test_mentions_orgs_empty_when_absent():
    assert mentions_orgs("A study of driving", "We use naturalistic data.") == []
