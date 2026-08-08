"""Offline unit tests for rag/author_org_tagger.py -- no network, no GPU, canned Block fixtures.
Fixture shape mirrors rag/test_parser.py's `_block()` helper (Block's real required fields,
including `index`, which `contracts.provenance.Block` requires but is otherwise irrelevant here)."""
import rag.author_org_tagger as tagger
from contracts.author_orgs import AuthorOrgMatch, AuthorOrgTag
from contracts.provenance import Block
from rag.author_org_tagger import (
    curated_orgs_for,
    extract_affiliations_rule_based,
    match_known_orgs,
    match_known_orgs_with_method,
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


# --- T-ORG2: the abstract must not be read as an affiliation ------------------------------------


def test_extract_excludes_the_abstract_even_though_it_is_page_zero_front_matter():
    """Regression (T-ORG2, measured 2026-08-07/08 on the live Waymo corpus). The abstract is page-0
    front matter (`section_path == ""`), so it was being handed to `match_known_orgs` as candidate
    affiliation text. Any paper that merely benchmarks on a Waymo dataset -- most of an AV-safety
    corpus -- therefore keyword-matched as Waymo-AUTHORED.

    Measured over 1,741 done papers against the 114 enumerated Waymo-authored ids:
        no cap (old)      precision 0.311, recall 0.851
        <=40-word cap     precision 0.573, recall 0.754
    The separation is stark because the two kinds of block are different objects: front-matter
    blocks containing "waymo" have a median of 6 words in genuinely Waymo-authored papers
    ("Waymo LLC") versus 166 in other papers (an abstract citing the Waymo Open Dataset).

    A word ceiling is used rather than matching against `papers.abstract` because this module is a
    pure function over `Block`s with no store access -- and it also catches the other observed
    false-positive source, long index-terms/keyword lines naming the dataset.
    """
    affiliation = "Waymo LLC, Mountain View, CA"
    abstract = (
        "We propose a method for trajectory prediction. " * 3
        + "Evaluations using the Waymo Open Motion Dataset demonstrate that our model reduces "
        "the mean minimum time-to-collision from 1.62 to 1.08 seconds, substantially "
        "outperforming prior work across every scenario category we considered. " * 4
    )
    assert len(abstract.split()) > 40, "fixture must exceed the cap to exercise it"

    blocks = [_block(abstract, section_path="", block_id="abs", index=1)]
    assert extract_affiliations_rule_based(blocks) == [], (
        "an abstract-length front-matter block must not be offered as affiliation text"
    )

    # The genuine affiliation line is short, and must still come through.
    blocks = [_block(affiliation, section_path="", block_id="aff", index=0)]
    assert extract_affiliations_rule_based(blocks) == [affiliation]


def test_a_dataset_mention_in_the_abstract_no_longer_reads_as_waymo_authorship():
    """The end-to-end shape of the false positive: real authors from another institution, plus an
    abstract citing a Waymo dataset. Before the cap this returned ["Waymo"]."""
    blocks = [
        _block("Yuewen Mei, Tongji University, Shanghai, China", block_id="a", index=0),
        _block("meiyuewen@tongji.edu.cn", block_id="b", index=1),
        _block(
            "Evaluations using the Waymo Open Motion Dataset demonstrate that our model "
            "reduces the mean minimum time-to-collision from 1.62 to 1.08 seconds. " * 4,
            block_id="c", index=2,
        ),
    ]
    assert match_known_orgs(extract_affiliations_rule_based(blocks)) == []


# --- T-ORG1: match_known_orgs_with_method -- which signal fired ---------------------------------


def test_match_known_orgs_with_method_email_domain_only():
    result = match_known_orgs_with_method(["Contact: k.kusano@waymo.com"])
    assert result == [AuthorOrgMatch(name="Waymo", method="email_domain")]


def test_match_known_orgs_with_method_keyword_only_no_email():
    result = match_known_orgs_with_method(["Waymo LLC, Mountain View, CA"])
    assert result == [AuthorOrgMatch(name="Waymo", method="keyword")]


def test_match_known_orgs_with_method_email_domain_wins_when_both_present():
    result = match_known_orgs_with_method(
        ["Waymo LLC, Mountain View, CA. Correspondence: k.kusano@waymo.com"]
    )
    assert result == [AuthorOrgMatch(name="Waymo", method="email_domain")]


# --- T-ORG3: curated_orgs_for -- the enumerated, authoritative tier -----------------------------


def _write_ids(tmp_path, *ids):
    path = tmp_path / "curated_ids.txt"
    path.write_text("\n".join(ids) + "\n")
    return str(path)  # absolute -- _resolve_curated_path leaves an absolute path untouched


def test_curated_orgs_for_matches_an_id_on_the_curated_list(tmp_path, monkeypatch):
    ids_path = _write_ids(tmp_path, "2604.03827", "2605.22997")
    monkeypatch.setattr(
        tagger, "KNOWN_ORGS",
        [AuthorOrgTag(name="Waymo", email_domains=[], keywords=[], curated_ids_path=ids_path)],
    )
    assert curated_orgs_for("2604.03827") == [AuthorOrgMatch(name="Waymo", method="curated")]


def test_curated_orgs_for_finds_no_match_for_an_id_not_on_the_list():
    # 2006.15505 is a real "1st Place Solution for Waymo Open Dataset Challenge"-style paper --
    # the exact false-positive shape T-ORG3 exists to close -- and is not in the curated fixture.
    assert curated_orgs_for("2006.15505") == []


def test_curated_orgs_for_does_not_depend_on_any_heuristic_text_signal(tmp_path, monkeypatch):
    # The whole point: a curated id gets a curated match with ZERO reliance on affiliation text --
    # this test never constructs a Block or calls extract_affiliations_rule_based/
    # match_known_orgs_with_method at all.
    ids_path = _write_ids(tmp_path, "9999.99999")
    monkeypatch.setattr(
        tagger, "KNOWN_ORGS",
        [AuthorOrgTag(name="Waymo", email_domains=[], keywords=[], curated_ids_path=ids_path)],
    )
    assert curated_orgs_for("9999.99999") == [AuthorOrgMatch(name="Waymo", method="curated")]


def test_curated_orgs_for_empty_for_an_org_with_no_curated_ids_path(monkeypatch):
    # No behavior change for an org that never opts in (curated_ids_path=None, the default) --
    # even for a paper id that would otherwise plausibly match nothing else either.
    monkeypatch.setattr(
        tagger, "KNOWN_ORGS",
        [AuthorOrgTag(name="MIT", email_domains=["mit.edu"], keywords=["mit"])],
    )
    assert curated_orgs_for("anything") == []


def test_curated_ids_file_is_read_once_not_per_call(tmp_path, monkeypatch):
    ids_path = _write_ids(tmp_path, "1111.11111")
    monkeypatch.setattr(
        tagger, "KNOWN_ORGS",
        [AuthorOrgTag(name="Waymo", email_domains=[], keywords=[], curated_ids_path=ids_path)],
    )
    monkeypatch.setattr(tagger, "_curated_ids_cache", {})

    calls: list[str] = []
    real_read = tagger._read_ids_file

    def counting_read(path):
        calls.append(path)
        return real_read(path)

    monkeypatch.setattr(tagger, "_read_ids_file", counting_read)

    for paper_id in ["1111.11111", "2222.22222", "1111.11111", "3333.33333"]:
        curated_orgs_for(paper_id)

    assert len(calls) == 1, f"expected exactly one file read across 4 calls, got {len(calls)}"


def test_curated_orgs_for_against_the_real_waymo_fixture():
    # Exercises the real KNOWN_ORGS Waymo entry (contracts/author_orgs.py) + the real
    # fixtures/waymo/waymo_authored_ids.txt -- no monkeypatching. Read-only.
    matched = curated_orgs_for("1812.03079")  # first id in the committed fixture file
    assert matched == [AuthorOrgMatch(name="Waymo", method="curated")]


def test_match_known_orgs_with_method_empty_when_no_match():
    assert match_known_orgs_with_method(["MIT, Cambridge, MA", "contact@mit.edu"]) == []


def test_match_known_orgs_with_method_empty_list_input():
    assert match_known_orgs_with_method([]) == []


def test_match_known_orgs_is_still_a_thin_wrapper_returning_names_only():
    # Regression guard (T-ORG1): match_known_orgs's existing list[str] shape and callers
    # (app/exp_author_org_tagging.py) must keep working unchanged.
    assert match_known_orgs(["Contact: k.kusano@waymo.com"]) == ["Waymo"]
    assert match_known_orgs(["Waymo LLC, Mountain View, CA"]) == ["Waymo"]
    assert match_known_orgs([]) == []


def test_a_long_block_is_still_kept_when_it_carries_an_email():
    """The cap must not silently drop a genuine affiliation just because the parser merged it into
    a longer block -- an email address is strong positive evidence of an affiliation region, so it
    overrides the length ceiling."""
    text = (
        "Kristofer D. Kusano, John M. Scanlon, Waymo LLC, Mountain View, California, USA. "
        "Correspondence: kusano@waymo.com. " + "Additional boilerplate text. " * 30
    )
    assert len(text.split()) > 40
    blocks = [_block(text, block_id="a", index=0)]
    assert match_known_orgs(extract_affiliations_rule_based(blocks)) == ["Waymo"]
