"""`python -m app.retrieval_eval` -- T-DOC41 (Contextual Retrieval spike): the measurement
runner. Loads a ground-truth question set, calls the real `Retriever.retrieve()` for each
question, and scores Recall@10/MRR at two granularities:

  * paper-level -- a hit if any returned chunk's `paper_id` is in the question's gold-paper set
    (`source_paper_id` plus, when present, `additional_gold_paper_ids` -- same multi-gold
    methodology as the 210-question eval, T-DOC42).
  * passage-level -- a hit only if a returned chunk's `anchor.block_id` equals the question's
    `gold_block_id`. This is the granularity `fixtures/eval/eval_ground_truth.json` cannot see
    (its own `_metadata.multi_gold_note` -- any chunk from the right paper passes) and
    `fixtures/eval/eval_equation_slice.json` was built to make visible: whether the *specific*
    equation/algorithm chunk was retrieved, not just the right paper.

Only questions carrying a `gold_block_id` are scored at passage level -- the 210-question set
doesn't have one (see that fixture's schema), so pointing this runner at it degrades gracefully to
paper-level-only reporting instead of crashing or silently scoring zero.

Same real, production retrieval pipeline the 210-question eval already uses end to end
(`app.assembly.build_mcp_server`) -- no simplified stand-in, and this module never talks to the
vector store or LLM adapters directly (CONVENTIONS §1): it only ever imports the composition root.
`--collection` is threaded straight through to `build_mcp_server`'s own existing `collection=`
parameter, so the same runner can score a throwaway "headered" collection against a throwaway
baseline collection during the actual before/after measurement -- no new wiring, no foundation
edit.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_GROUND_TRUTH = "fixtures/eval/eval_ground_truth.json"
_DEFAULT_K = 10


@dataclass(frozen=True)
class Question:
    question_id: str
    question_text: str
    question_type: str
    gold_paper_ids: frozenset[str]
    gold_block_id: str | None  # None -> not scorable at passage level (e.g. the 210-set today)


@dataclass(frozen=True)
class QuestionResult:
    question_id: str
    question_type: str
    paper_rank: int | None  # 1-indexed rank of the first paper-level hit, else None
    passage_rank: int | None  # 1-indexed rank of the first passage-level hit, else None
    passage_scored: bool  # whether this question had a gold_block_id to score against
    error: str | None = None


def load_questions(ground_truth_path: Path) -> list[Question]:
    """Loads a ground-truth file into `Question`s. Two supported shapes, distinguished by
    whether a record already carries `question_text`:

      * the equation slice (`eval_equation_slice.json`): every record is self-contained.
      * the 210-question set (`eval_ground_truth.json`): `question_text` lives in the sibling
        `eval_questions_blind.json` (same directory), joined here by `question_id` -- mirrors the
        methodology `.phase0-data/teval/resolve_and_score_v2.py` already used for this file.
    """
    data = json.loads(ground_truth_path.read_text())
    records = data["ground_truth"]

    text_by_id = {r["question_id"]: r["question_text"] for r in records if "question_text" in r}
    if len(text_by_id) < len(records):
        blind_path = ground_truth_path.parent / "eval_questions_blind.json"
        blind = json.loads(blind_path.read_text())["questions"]
        text_by_id.update({q["question_id"]: q["question_text"] for q in blind})

    questions = []
    for r in records:
        qid = r["question_id"]
        if qid not in text_by_id:
            raise ValueError(
                f"{qid}: no question_text in {ground_truth_path} or its blind sibling"
            )
        gold_papers = {r["source_paper_id"], *r.get("additional_gold_paper_ids", [])}
        questions.append(
            Question(
                question_id=qid,
                question_text=text_by_id[qid],
                question_type=r["question_type"],
                gold_paper_ids=frozenset(gold_papers),
                gold_block_id=r.get("gold_block_id"),
            )
        )
    return questions


def score_question(question: Question, results: list, k: int) -> QuestionResult:
    """`results` is the `list[GroundedResult]` a real (or fake) `Retriever.retrieve()` call
    returned -- already truncated to `k` by `Retriever` itself, but truncated again here so a
    test double that doesn't truncate still scores correctly.
    """
    truncated = results[:k]
    paper_rank = next(
        (i for i, r in enumerate(truncated, start=1) if r.paper_id in question.gold_paper_ids),
        None,
    )
    passage_scored = question.gold_block_id is not None
    passage_rank = None
    if passage_scored:
        passage_rank = next(
            (
                i
                for i, r in enumerate(truncated, start=1)
                if r.anchor.block_id == question.gold_block_id
            ),
            None,
        )
    return QuestionResult(
        question_id=question.question_id,
        question_type=question.question_type,
        paper_rank=paper_rank,
        passage_rank=passage_rank,
        passage_scored=passage_scored,
    )


def run(questions: list[Question], retriever, k: int) -> list[QuestionResult]:
    """Calls the real (or fake) `retriever.retrieve(question_text, filters, k)` for every
    question. A retrieval error for one question is recorded and skipped, not fatal to the whole
    run (mirrors `Retriever`'s own "drop the bad hit, keep going" posture, T-DOC38) -- a single
    orphaned/unresolvable corpus row shouldn't blank out every other question's score.
    """
    results = []
    for i, question in enumerate(questions, start=1):
        try:
            hits, _coverage = retriever.retrieve(question.question_text, None, k)
        except Exception as e:  # noqa: BLE001 -- deliberately broad, see docstring
            logger.warning("retrieve() failed for %s: %s", question.question_id, e)
            results.append(
                QuestionResult(
                    question_id=question.question_id,
                    question_type=question.question_type,
                    paper_rank=None,
                    passage_rank=None,
                    passage_scored=question.gold_block_id is not None,
                    error=str(e),
                )
            )
            continue
        results.append(score_question(question, hits, k))
        if i % 20 == 0:
            logger.info("scored %d/%d questions", i, len(questions))
    return results


def _recall_mrr(ranks: list[int | None]) -> dict:
    n = len(ranks)
    if n == 0:
        return {"recall_at_k": None, "mrr": None, "n": 0}
    hits = sum(1 for r in ranks if r is not None)
    rr_sum = sum(1.0 / r for r in ranks if r is not None)
    return {"recall_at_k": hits / n, "mrr": rr_sum / n, "n": n}


def build_report(results: list[QuestionResult], k: int) -> dict:
    question_types = sorted({r.question_type for r in results})
    passage_eligible = [r for r in results if r.passage_scored]

    return {
        "k": k,
        "n_questions": len(results),
        "n_errors": sum(1 for r in results if r.error),
        "paper_level": {
            "overall": _recall_mrr([r.paper_rank for r in results]),
            "by_question_type": {
                t: _recall_mrr([r.paper_rank for r in results if r.question_type == t])
                for t in question_types
            },
        },
        "passage_level": {
            "n_scored": len(passage_eligible),
            "overall": _recall_mrr([r.passage_rank for r in passage_eligible]),
            "by_question_type": {
                t: _recall_mrr(
                    [r.passage_rank for r in passage_eligible if r.question_type == t]
                )
                for t in sorted({r.question_type for r in passage_eligible})
            },
        },
    }


def _print_summary(report: dict) -> None:
    def _fmt(m: dict) -> str:
        if m["n"] == 0:
            return "n=0 (no questions in this split)"
        return f"Recall@{report['k']}={m['recall_at_k']:.3f}  MRR={m['mrr']:.3f}  (n={m['n']})"

    print(f"Questions scored: {report['n_questions']} (errors: {report['n_errors']})")
    print(f"Paper-level   {_fmt(report['paper_level']['overall'])}")
    pl = report["passage_level"]
    if pl["n_scored"]:
        print(f"Passage-level {_fmt(pl['overall'])}  [{pl['n_scored']}/{report['n_questions']} "
              "questions carry a gold_block_id]")
    else:
        print("Passage-level: no question in this ground-truth file carries a gold_block_id "
              "-- nothing to score (this is expected for the 210-question set)")

    print("\nBy question_type (paper-level):")
    for t, m in sorted(report["paper_level"]["by_question_type"].items()):
        print(f"  {t:30s} {_fmt(m)}")
    if pl["n_scored"]:
        print("\nBy question_type (passage-level):")
        for t, m in sorted(pl["by_question_type"].items()):
            print(f"  {t:30s} {_fmt(m)}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", default=_DEFAULT_GROUND_TRUTH)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--blob-dir", default=None)
    parser.add_argument(
        "--collection", default=None,
        help="named vector-store collection to search (defaults to the retriever wiring's own "
             "default) -- point this at a throwaway baseline/headered collection to compare them",
    )
    parser.add_argument("--k", type=int, default=_DEFAULT_K)
    parser.add_argument("--report-path", default=None, help="write the JSON report here")
    parser.add_argument(
        "--limit", type=int, default=None, help="score only the first N questions (smoke test)"
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()

    # Deferred import: these pull in the real (GPU-backed) adapter wiring, which unit tests must
    # never touch (they exercise load_questions/score_question/run/build_report against a fake
    # retriever instead) -- see app/test_retrieval_eval.py.
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
    if args.limit is not None:
        questions = questions[: args.limit]

    results = run(questions, server.retriever, args.k)
    report = build_report(results, args.k)
    _print_summary(report)

    if args.report_path:
        Path(args.report_path).write_text(json.dumps(report, indent=2))
        print(f"\nWrote report to {args.report_path}")


if __name__ == "__main__":
    main()
