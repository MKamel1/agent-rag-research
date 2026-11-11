"""OP-6: refuse to run against a missing database instead of creating an empty one.

The T-DOC56 failure shape: a tool started from the wrong directory resolves a relative `db_path`
to a place with no `papers.db`; `sqlite3.connect` happily creates an empty one and the tool
"succeeds" against nothing. Tools that must only ever *read or back up* an existing corpus call
`require_existing_db` first.
"""

from pathlib import Path


class MissingDatabaseError(FileNotFoundError):
    """Raised (and turned into a one-line exit message by each CLI) when `db_path` is absent."""


def require_existing_db(db_path: str | Path) -> Path:
    path = Path(db_path)
    if not path.is_file():
        raise MissingDatabaseError(
            f"no database at {path.resolve()} -- refusing to continue (an empty one would be "
            "created otherwise). Run from the intended corpus directory or pass --config."
        )
    return path
