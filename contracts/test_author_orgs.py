from contracts.author_orgs import KNOWN_ORGS, AuthorOrgTag


def test_known_orgs_has_a_waymo_entry():
    names = [org.name for org in KNOWN_ORGS]
    assert "Waymo" in names


def test_waymo_entry_has_expected_domain_and_keyword():
    waymo = next(org for org in KNOWN_ORGS if org.name == "Waymo")
    assert "waymo.com" in waymo.email_domains
    assert "waymo" in [kw.lower() for kw in waymo.keywords]


def test_author_org_tag_is_frozen():
    tag = AuthorOrgTag(name="Test", email_domains=["test.com"], keywords=["test"])
    import pytest
    with pytest.raises(Exception):
        tag.name = "Changed"
