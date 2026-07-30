"""SCRATCH / THROWAWAY -- not part of the permanent suite, not imported by anything else.

One-off measurement script for the Decision 2 (option B) scoped per-paper cap change
(docs/DECISIONS-PENDING-operator.md, rag/retriever.py `_MAX_HITS_PER_PAPER_SCOPED`). Written
instead of modifying `app/retrieval_eval.py` because that runner never threads `filters` through
to `retrieve()`/`retrieve_papers()` (task instructions: do not change it for this task).

Two measurements, both against a `--collection` the caller supplies (this run always points it at
`exp1_ctrl_sizemerge_idf`, never production `papers`):

1. `book_chapter_eval`: the 40-question `fixtures/eval/eval_book_questions.json` set, scored at
   chapter level via `retriever.retrieve_papers()` -- once with `filters=None` (unscoped
   regression guard), once with `filters=SearchFilters(doc_type="book")` (the scoped case Decision
   2 targets). Mirrors `app/retrieval_eval.py`'s own `score_question`/`chapter_rank` logic exactly
   (same hit definition: gold paper_id AND gold chapter title), just with `filters` threaded in.

2. `paper_eval_210`: the 210-question `fixtures/eval/eval_ground_truth.json` set, scored at paper
   level via `retriever.retrieve()` with `filters=None` (this fixture carries no `gold_block_id`,
   so no passage-level score -- same graceful-degrade `app/retrieval_eval.py` already documents).
   This is the "does the change hurt corpus-wide paper search" regression check -- run against the
   SAME collection so any drift is attributable to the code change, not a different corpus.

Usage: python scripts/scratch_scoped_cap_eval.py --collection exp1_ctrl_sizemerge_idf --out /tmp/x.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from contracts.vector_index import SearchFilters


def _recall_mrr(ranks: list[int | None]) -> dict:
    n = len(ranks)
    if n == 0:
        return {"recall_at_k": None, "mrr": None, "n": 0}
    hits = sum(1 for r in ranks if r is not None)
    rr_sum = sum(1.0 / r for r in ranks if r is not None)
    return {"recall_at_k": hits / n, "mrr": rr_sum / n, "n": n}


def _chapter_rank(chapter_results, gold_paper_ids: set[str], gold_chapter_title: str, k: int):
    for i, r in enumerate(chapter_results[:k], start=1):
        if r.view.paper_id in gold_paper_ids and r.chapter == gold_chapter_title:
            return i
    return None


def _paper_rank(results, gold_paper_ids: set[str], k: int):
    for i, r in enumerate(results[:k], start=1):
        if r.paper_id in gold_paper_ids:
            return i
    return None


def run_book_chapter_eval(retriever, questions_path: Path, k: int, limit: int | None = None) -> dict:
    data = json.loads(questions_path.read_text())["ground_truth"]
    if limit is not None:
        data = data[:limit]
    unscoped_ranks, scoped_ranks = [], []
    for q in data:
        gold_papers = {q["source_paper_id"]}
        text = q["question_text"]
        chapter_title = q["gold_chapter_title"]

        results_unscoped, _ = retriever.retrieve_papers(text, None, k)
        unscoped_ranks.append(_chapter_rank(results_unscoped, gold_papers, chapter_title, k))

        results_scoped, _ = retriever.retrieve_papers(text, SearchFilters(doc_type="book"), k)
        scoped_ranks.append(_chapter_rank(results_scoped, gold_papers, chapter_title, k))

    return {
        "n": len(data),
        "unscoped_chapter_recall": _recall_mrr(unscoped_ranks),
        "scoped_doc_type_book_chapter_recall": _recall_mrr(scoped_ranks),
    }


def run_paper_eval_210(retriever, questions_path: Path, k: int, limit: int | None = None) -> dict:
    # Reuses app/retrieval_eval.py's own `load_questions` (not its `run()`, which never threads
    # `filters` through) so the question_text/blind-sibling join logic isn't duplicated here --
    # this fixture's `question_text` lives in eval_questions_blind.json, joined by question_id.
    from app.retrieval_eval import load_questions

    questions = load_questions(questions_path)
    if limit is not None:
        questions = questions[:limit]
    ranks = []
    n_errors = 0
    for q in questions:
        try:
            results, _ = retriever.retrieve(q.question_text, None, k)
        except Exception as e:  # noqa: BLE001 -- scratch script, mirrors retrieval_eval.run()'s posture
            n_errors += 1
            ranks.append(None)
            print(f"  ERROR {q.question_id}: {e}")
            continue
        ranks.append(_paper_rank(results, set(q.gold_paper_ids), k))
    return {"n": len(questions), "n_errors": n_errors, "paper_recall": _recall_mrr(ranks)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--out", default=None, help="write the JSON result here")
    parser.add_argument(
        "--skip-210", action="store_true", help="skip the 210-question paper-recall run"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="score only the first N questions of each set (smoke test)"
    )
    args = parser.parse_args()

    from app.assembly import build_mcp_server
    from rag.config import load_config
    from rag.gpu_lock import FileGpuLock

    config = load_config(args.config)

    lock = FileGpuLock(Path(config.gpu_lock_path))
    print(f"Waiting for GPU lock at {config.gpu_lock_path} ...")
    t0 = time.monotonic()
    with lock.acquire("scratch-eval"):
        wait_s = time.monotonic() - t0
    print(f"Acquired (and released) GPU lock after waiting {wait_s:.1f}s")

    server = build_mcp_server(config, collection=args.collection)
    retriever = server.retriever

    print(f"\n=== 40-question book chapter eval (collection={args.collection}) ===")
    book_result = run_book_chapter_eval(
        retriever, Path("fixtures/eval/eval_book_questions.json"), args.k, args.limit
    )
    print(json.dumps(book_result, indent=2))

    paper_result = None
    if not args.skip_210:
        print(f"\n=== 210-question paper recall eval (collection={args.collection}) ===")
        paper_result = run_paper_eval_210(
            retriever, Path("fixtures/eval/eval_ground_truth.json"), args.k, args.limit
        )
        print(json.dumps(paper_result, indent=2))

    report = {
        "collection": args.collection,
        "k": args.k,
        "gpu_lock_wait_s": wait_s,
        "book_chapter_eval": book_result,
        "paper_eval_210": paper_result,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
