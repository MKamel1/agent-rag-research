"""Fixture proving check (h)'s sanctioned-exception fencing (`ci/checks/id_slicing.py`,
`SANCTIONED_PATH`/`SANCTIONED_FUNCTION`) is scoped to `_paper_id_from_summary_hit_id`'s own line
range, not to its whole file: a SECOND, unsanctioned function living in this same (logical)
`rag/retriever.py` file that parses the id attribute the same way must still trip the check. Never
imported or executed; `ci/checks/test_checks.py` reads this file as text with
`logical_path="rag/retriever.py"`.

`_paper_id_from_summary_hit_id` below takes the whole hit-like object (rather than the real
helper's bare `hit_id: str`) purely so this fixture's body actually contains an attribute-then-
removesuffix parse for check (h) to match — exercising the fencing logic for real, instead of
benefiting by accident from the real helper's bare-string parameter never touching a `.id`
attribute.
"""


def _paper_id_from_summary_hit_id(hit) -> str:
    """The one sanctioned parser (fixture stand-in) -- see rag/retriever.py."""
    return hit.id.removesuffix(":summary")


def _rogue_paper_id_from_hit(candidate) -> str:
    # A hypothetical second ad-hoc parse site elsewhere in the same file -- NOT sanctioned by name,
    # and must still be flagged even though it lives beside the sanctioned helper above.
    return candidate.id.removesuffix(":summary")
