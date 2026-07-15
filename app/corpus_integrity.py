"""`python -m app.corpus_integrity` -- standing corpus-integrity diagnostic (T-DOC35).

A paper whose `ingest_state.stage == 'done'` is supposed to mean "fully ingested and retrievable."
T-DOC23's orphaned-chunks cleanup showed that isn't mechanically guaranteed: it deleted 59 papers'
orphaned `chunks`/`blocks` rows (rows whose `paper_id` didn't match any `papers` row at the time),
but the *real* paper's own `papers`/`summaries`/`ingest_state='done'` rows were untouched -- so the
orchestrator's resume guard (`rag/orchestrator.py`'s `_at_least(stage, "done")`) now skips them on
every future run while they contribute zero retrievable chunks. No existing check catches this: it
only counts `ingest_state='done'`, never cross-checks against `chunks`/`blocks` actually existing.

This module is the standing check for that invariant: a `done` paper must have >=1 chunk row and
>=1 block row. Pure SQL against whatever connection it's given -- no ingest-pipeline dependency, no
GPU, no network -- so it's safe to run against the real production DB at any time.
"""

import sqlite3
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrityOffender:
    paper_id: str
    chunk_count: int
    block_count: int


_QUERY = """
SELECT p.paper_id,
       (SELECT count(*) FROM chunks c WHERE c.paper_id = p.paper_id) AS chunk_count,
       (SELECT count(*) FROM blocks b WHERE b.paper_id = p.paper_id) AS block_count
FROM ingest_state s
JOIN papers p ON p.paper_id = s.paper_id
WHERE s.stage = 'done' AND (chunk_count = 0 OR block_count = 0)
ORDER BY p.paper_id
"""


def find_done_papers_without_chunks(conn: sqlite3.Connection) -> list[IntegrityOffender]:
    """Every `ingest_state='done'` paper with zero `chunks` rows and/or zero `blocks` rows --
    silently unretrievable despite looking fully ingested. Empty list means the corpus is clean.
    """
    return [
        IntegrityOffender(paper_id=row[0], chunk_count=row[1], block_count=row[2])
        for row in conn.execute(_QUERY).fetchall()
    ]


def main() -> None:
    import os

    db_path = os.environ.get("RAG_DB_PATH")
    if not db_path:
        print("usage: RAG_DB_PATH=<path/to/papers.db> python -m app.corpus_integrity", file=sys.stderr)
        sys.exit(2)

    conn = sqlite3.connect(db_path)
    try:
        offenders = find_done_papers_without_chunks(conn)
    finally:
        conn.close()

    if not offenders:
        print("corpus-integrity: OK -- every 'done' paper has >=1 chunk and >=1 block.")
        return

    print(f"corpus-integrity: {len(offenders)} offender(s) -- 'done' but missing chunks/blocks:")
    for o in offenders:
        print(f"  {o.paper_id}: chunks={o.chunk_count} blocks={o.block_count}")
    sys.exit(1)


if __name__ == "__main__":
    main()
