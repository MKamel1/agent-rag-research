"""Operator CLI: delete one or more documents from the corpus, completely.

T-DOC84. Before this existed, deletion was reachable only from Python -- `delete_paper` had zero
non-test callers -- so every real deletion was an ad-hoc script plus hand-written SQL. That is
how the stale-`ingest_state` trap got hit during the T-DOC82 rollout: an ad-hoc script has no
reason to know a third table is involved. This module is the one supported way to remove a
document, and it goes through `IngestionOrchestrator.delete_paper`, which owns all three deletes
(SQLite rows, vectors, ingest state).

Deletion is irreversible -- there is no undo and no tombstone. `--yes` is required.

    python -m app.delete_docs --yes local:f0929288d4f3

Exit codes:
    0 -- every id was deleted.
    1 -- refused: `--yes` was not passed. Nothing was deleted.
    2 -- deletion failed partway through a multi-id run. The log line for this run states which
         ids were already deleted (gone for good, and safe to pass again -- `delete_paper` is
         idempotent), which id raised, and which ids were never attempted.
"""

import argparse
import logging

from app.assembly import build_ingestion_orchestrator
from rag.config import load_config

logger = logging.getLogger(__name__)


def _build():
    # Indirection exists so tests can substitute a recording double without standing up the real
    # assembly (which would need a live vector index).
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
    deleted: list[str] = []
    for index, paper_id in enumerate(args.paper_ids):
        try:
            orchestrator.delete_paper(paper_id)
        except Exception:
            # Caught (not re-raised) so this function can report exit code 2 -- a distinct code
            # from the uncaught-exception default of 1, which is also `--yes`-refusal's code.
            # Without this split a caller can't tell "you forgot --yes, nothing happened" from
            # "N documents are already gone and the next one blew up" (finding from Task 3 review).
            not_attempted = args.paper_ids[index + 1:]
            logger.exception(
                "delete_docs: failed deleting %s (document %d of %d). %d document(s) already "
                "deleted -- gone for good, and safe to pass again since delete_paper is "
                "idempotent: %s. %d document(s) NOT attempted: %s.",
                paper_id, index + 1, len(args.paper_ids),
                len(deleted), ", ".join(deleted) or "(none)",
                len(not_attempted), ", ".join(not_attempted) or "(none)",
            )
            return 2
        deleted.append(paper_id)
        logger.info("delete_docs: deleted %s (rows, vectors, ingest state)", paper_id)
    logger.info("delete_docs: %d document(s) deleted", len(args.paper_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
