import pytest
from pydantic import ValidationError

from contracts.author_orgs import KNOWN_ORGS, AuthorOrgMatch, AuthorOrgTag


def test_known_orgs_has_a_waymo_entry():
    names = [org.name for org in KNOWN_ORGS]
    assert "Waymo" in names


def test_waymo_entry_has_expected_domain_and_keyword():
    waymo = next(org for org in KNOWN_ORGS if org.name == "Waymo")
    assert "waymo.com" in waymo.email_domains
    assert "waymo" in [kw.lower() for kw in waymo.keywords]


def test_author_org_tag_is_frozen():
    tag = AuthorOrgTag(name="Test", email_domains=["test.com"], keywords=["test"])
    with pytest.raises(Exception):
        tag.name = "Changed"


def test_author_org_match_constructs_with_email_domain_method():
    m = AuthorOrgMatch(name="Waymo", method="email_domain")
    assert m.method == "email_domain"


def test_author_org_match_constructs_with_keyword_method():
    m = AuthorOrgMatch(name="Waymo", method="keyword")
    assert m.method == "keyword"


def test_author_org_match_constructs_with_curated_method():
    m = AuthorOrgMatch(name="Waymo", method="curated")
    assert m.method == "curated"


def test_author_org_match_method_must_be_a_valid_literal():
    with pytest.raises(ValidationError):
        AuthorOrgMatch(name="Waymo", method="guess")


def test_author_org_match_is_frozen():
    m = AuthorOrgMatch(name="Waymo", method="keyword")
    with pytest.raises(Exception):
        m.name = "Changed"


# --- curated_ids_path seam ------------------------------------------------------------------


def test_author_org_tag_curated_ids_path_defaults_to_none():
    tag = AuthorOrgTag(name="Test", email_domains=["test.com"], keywords=["test"])
    assert tag.curated_ids_path is None


def test_author_org_tag_constructs_with_explicit_curated_ids_path():
    tag = AuthorOrgTag(
        name="Test", email_domains=["test.com"], keywords=["test"],
        curated_ids_path="fixtures/test/ids.txt",
    )
    assert tag.curated_ids_path == "fixtures/test/ids.txt"


def test_waymo_entry_points_at_the_curated_ids_fixture():
    waymo = next(org for org in KNOWN_ORGS if org.name == "Waymo")
    assert waymo.curated_ids_path == "fixtures/waymo/waymo_authored_ids.txt"
