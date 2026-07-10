"""Positive-example fixture for check (c) (ci/checks/blind_except.py) — catches the specific
exception classes it can actually handle, per CONVENTIONS §4's three-class taxonomy.
"""

from contracts.errors import PermanentError


def load_paper(paper_id: str) -> str:
    try:
        return _read(paper_id)
    except FileNotFoundError as exc:
        raise PermanentError(f"{paper_id}: source file missing") from exc


def _read(paper_id: str) -> str:
    with open(paper_id) as f:
        return f.read()
