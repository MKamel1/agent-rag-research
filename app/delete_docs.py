"""Operator CLI: delete one or more documents from the corpus, completely.

T-DOC84. Before this existed, deletion was reachable only from Python -- `delete_paper` had zero
non-test callers -- so every real deletion was an ad-hoc script plus hand-written SQL. That is
how the stale-`ingest_state` trap got hit during the T-DOC82 rollout: an ad-hoc script has no
reason to know a third table is involved. This module is the one supported way to remove a
document, and it goes through `IngestionOrchestrator.delete_paper`, which owns all three deletes
(SQLite rows, vectors, ingest state).

Deletion is irreversible -- there is no undo and no tombstone. `--yes` is required.

    python -m app.delete_docs --yes local:f0929288d4f3
"""

import argparse
import logging

from app.assembly import build_ingestion_orchestrator
from rag.config import load_config

logger = logging.getLogger(__name__)


def _build():
    # Indirection exists so tests can substitute a recording double without standing up the real
    # assembly (which would need a live Qdrant).
    return build_ingestion_orchestrator(load_config())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper_ids", nargs="+", metavar="PAPER_ID",
                        help="One or more paper_ids to delete (e.g. 2401.00001, local:abc123)")
    parser.add_argument("--yes", action="store_true",
                        help="Required. Confirms the deletion is intended -- it cannot be undone.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)
    if not args.yes:
        logger.error(
            "delete_docs: refusing to delete %d document(s) without --yes. Deletion removes the "
            "SQLite rows, the vectors, and the ingest state, and cannot be undone. Ids: %s",
            len(args.paper_ids), ", ".join(args.paper_ids),
        )
        return 1
    orchestrator = _build()
    for paper_id in args.paper_ids:
        orchestrator.delete_paper(paper_id)
        logger.info("delete_docs: deleted %s (rows, vectors, ingest state)", paper_id)
    logger.info("delete_docs: %d document(s) deleted", len(args.paper_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
