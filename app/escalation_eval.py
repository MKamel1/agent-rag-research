"""`python -m app.escalation_eval` -- Experiment 5 of `docs/PLAN-book-rag-experiments.md`
(Self-Route-style agent escalation), scoped down per the exp5 brief's Task B: escalation adds a
`doc_type="book"` filter on retry, since Task A already measured that filter alone is worth +0.225
chapter-routing recall on this fixture and `search_papers`' own docstring already recommends it.

**Falsification bar, pre-committed by the brief: escalation must beat the best single-shot
configuration already available (`doc_type="book"` on every call, 0.650 measured by Task A), not
the unfiltered baseline (0.425).** Beating 0.425 only proves the filter works, which Task A already
establishes without any agent-loop machinery.

Mirrors `app/retrieval_eval.py`'s shape deliberately (`Question`/`load_questions` reused directly,
same `Retriever.retrieve_papers()` seam, same real-vs-fake retriever split) rather than introducing
a second harness -- this is a scoring wrapper around the existing retriever, not new infrastructure
(brief: "Keep it cheap... A scoring wrapper around the existing retriever is the whole build.").

No index change, no re-embed, no migration, no `contracts/` edit. Opt-in only: nothing outside this
module ever calls `escalating_retrieve_papers`, so it changes no production behavior -- the "toggle"
is simply "run this script or don't."
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.retrieval_eval import Question, load_questions
from contracts.mcp_server import PaperSearchResult
from contracts.vector_index import SearchFilters

logger = logging.getLogger(__name__)

_DEFAULT_K = 10


def top_hit_not_book(results: list[PaperSearchResult]) -> bool:
    """Default insufficiency signal: true when the unfiltered call returned nothing, or its
    rank-1 hit isn't a book. This is the one signal a real agent could read straight off
    `search_papers`' own response (`PaperSearchResult.view.citation.doc_type`) with no gold
    label and no second LLM call -- a book-routing question whose top hit is a `paper` is exactly
    the "candidate set" failure mode the exp5 brief's programme-level finding describes (a
    non-book competitor crowded the right book out of the pool), and is the case
    `filters={"doc_type": "book"}` exists to fix.
    """
    if not results:
        return True
    return results[0].view.citation.doc_type != "book"


@dataclass(frozen=True)
class EscalationResult:
    question_id: str
    chapter_rank: int | None  # 1-indexed rank of the first chapter-routing hit, else None
    escalated: bool
    error: str | None = None


def escalating_retrieve_papers(
    retriever, query: str, k: int, *, insufficient=top_hit_not_book
):
    """One unfiltered `retrieve_papers()` call; if `insufficient(results)` says the first call's
    top hit doesn't look book-shaped, retry once with `doc_type="book"` and return the retry's
    results instead. At most one retry (Experiment 5's "one allowed escalation" framing) -- this
    is not a search loop, it's a single conditional filter swap.

    Returns `(results, escalated)`.
    """
    results, _coverage = retriever.retrieve_papers(query, None, k)
    if not insufficient(results):
        return results, False
    results, _coverage = retriever.retrieve_papers(query, SearchFilters(doc_type="book"), k)
    return results, True


def _chapter_rank(results: list[PaperSearchResult], question: Question, k: int) -> int | None:
    truncated = results[:k]
    return next(
        (
            i
            for i, r in enumerate(truncated, start=1)
            if r.view.paper_id in question.gold_paper_ids and r.chapter == question.gold_chapter_title
        ),
        None,
    )


def run(
    questions: list[Question], retriever, k: int, *, insufficient=top_hit_not_book
) -> list[EscalationResult]:
    """Only questions carrying a `gold_chapter_title` are chapter-routable at all (mirrors
    `app/retrieval_eval.run()`'s own gate) -- a question with none is skipped rather than scored
    as a guaranteed miss, since it was never a chapter-routing question to begin with.
    """
    out = []
    for i, question in enumerate(questions, start=1):
        if question.gold_chapter_title is None:
            continue
        try:
            results, escalated = escalating_retrieve_papers(
                retriever, question.question_text, k, insufficient=insufficient
            )
        except Exception as e:  # noqa: BLE001 -- one bad question must not abort the whole run
            logger.warning("escalating_retrieve_papers() failed for %s: %s", question.question_id, e)
            out.append(EscalationResult(question.question_id, None, escalated=False, error=str(e)))
            continue
        out.append(
            EscalationResult(
                question.question_id, _chapter_rank(results, question, k), escalated, error=None
            )
        )
        if i % 20 == 0:
            logger.info("scored %d/%d questions", i, len(questions))
    return out


def build_report(results: list[EscalationResult], k: int) -> dict:
    n = len(results)
    hits = sum(1 for r in results if r.chapter_rank is not None)
    rr_sum = sum(1.0 / r.chapter_rank for r in results if r.chapter_rank is not None)
    escalations = sum(1 for r in results if r.escalated)
    return {
        "k": k,
        "n_questions": n,
        "n_errors": sum(1 for r in results if r.error),
        "n_escalated": escalations,
        "escalation_rate": escalations / n if n else None,
        "chapter_level": {
            "recall_at_k": hits / n if n else None,
            "mrr": rr_sum / n if n else None,
            "n": n,
        },
        "questions": [
            {
                "question_id": r.question_id,
                "chapter_rank": r.chapter_rank,
                "hit": r.chapter_rank is not None,
                "escalated": r.escalated,
                "error": r.error,
            }
            for r in results
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", default="fixtures/eval/eval_book_questions.json")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--blob-dir", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--k", type=int, default=_DEFAULT_K)
    parser.add_argument("--report-path", default=None)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()

    # Deferred import -- same reasoning as app/retrieval_eval.py's main(): pulls in the real
    # GPU-backed adapter wiring, which unit tests (app/test_escalation_eval.py) must never touch.
    from app.assembly import build_mcp_server
    from rag.config import load_config

    config = load_config(args.config)
    build_kwargs = {}
    if args.db_path is not None:
        build_kwargs["db_path"] = args.db_path
    if args.blob_dir is not None:
        build_kwargs["blob_dir"] = args.blob_dir
    if args.collection is not None:
        build_kwargs["collection"] = args.collection
    server = build_mcp_server(config, **build_kwargs)

    questions = load_questions(Path(args.ground_truth))
    results = run(questions, server.retriever, args.k)
    report = build_report(results, args.k)

    print(f"Questions scored: {report['n_questions']} (errors: {report['n_errors']})")
    print(f"Escalated: {report['n_escalated']} ({report['escalation_rate']:.1%})")
    cl = report["chapter_level"]
    print(f"Chapter-level Recall@{args.k}={cl['recall_at_k']:.3f} MRR={cl['mrr']:.3f} (n={cl['n']})")

    if args.report_path:
        Path(args.report_path).write_text(json.dumps(report, indent=2))
        print(f"\nWrote report to {args.report_path}")


if __name__ == "__main__":
    main()
