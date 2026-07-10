"""Negative-example fixture for check (c) — CONVENTIONS.md §4/§12 (ci/checks/blind_except.py).

A bare `except:` and an `except Exception:` — both firing-offense shapes per CONVENTIONS §4. Never
imported or executed; `ci/checks/test_checks.py` points `ruff` at this file directly.
"""


def load_paper(paper_id: str) -> str:
    try:
        return _read(paper_id)
    except Exception:
        return ""


def _read(paper_id: str) -> str:
    try:
        return open(paper_id).read()
    except:
        return ""
