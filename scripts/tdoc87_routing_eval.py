"""SCRATCH / THROWAWAY -- not part of the permanent suite, not imported by anything else.

T-DOC87 phase-2 measurement: chapter-routing recall/MRR for the re-derived book-questions fixture
(`app.exp_tdoc87_marker_repair`'s `--fixture-out`), against a `--collection` the caller supplies
(always the throwaway `tdoc87_marker_repair` collection for this task, never production `papers`).
Same shape as `scripts/scratch_scoped_cap_eval.py`'s `run_book_chapter_eval` (Decision 2's own
measurement script) -- reuses its `_chapter_rank`/`_recall_mrr` helpers directly rather than
reimplementing them -- but adds a PER-BOOK breakdown (grouped by `source_paper_id`), since the
task's gate explicitly calls for per-book numbers, not just the aggregate (Experiment 1's
regression hid inside an aggregate that looked fine).

Two configurations per question, same as the Decision 2 script: `filters=None` (unscoped) and
`filters=SearchFilters(doc_type="book")` (scoped) -- both compared against
`docs/DECISIONS-PENDING-operator.md`'s already-established baseline on this collection shape
(0.425 unscoped / 0.725 scoped).

Usage:
    python scripts/tdoc87_routing_eval.py \
        --collection tdoc87_marker_repair \
        --questions fixtures/eval/eval_book_questions_tdoc87.json \
        --config /home/omar/ai-projects/research-system-rag-data/config.yaml \
        --out /tmp/tdoc87_routing_result.json
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from contracts.vector_index import SearchFilters
from scripts.scratch_scoped_cap_eval import _chapter_rank, _recall_mrr


def run_routing_eval(retriever, questions_path: Path, k: int, limit: int | None = None) -> dict:
    data = json.loads(questions_path.read_text())["ground_truth"]
    data = [q for q in data if q.get("gold_chapter_title")]  # chapter-scored questions only
    if limit is not None:
        data = data[:limit]

    by_book_unscoped: dict[str, list[int | None]] = defaultdict(list)
    by_book_scoped: dict[str, list[int | None]] = defaultdict(list)
    unscoped_ranks: list[int | None] = []
    scoped_ranks: list[int | None] = []

    for q in data:
        gold_papers = {q["source_paper_id"]}
        text = q["question_text"]
        chapter_title = q["gold_chapter_title"]
        book = q["source_paper_id"]

        results_unscoped, _ = retriever.retrieve_papers(text, None, k)
        r_u = _chapter_rank(results_unscoped, gold_papers, chapter_title, k)
        unscoped_ranks.append(r_u)
        by_book_unscoped[book].append(r_u)

        results_scoped, _ = retriever.retrieve_papers(text, SearchFilters(doc_type="book"), k)
        r_s = _chapter_rank(results_scoped, gold_papers, chapter_title, k)
        scoped_ranks.append(r_s)
        by_book_scoped[book].append(r_s)

    return {
        "n": len(data),
        "overall": {
            "unscoped": _recall_mrr(unscoped_ranks),
            "scoped_doc_type_book": _recall_mrr(scoped_ranks),
        },
        "by_book": {
            book: {
                "unscoped": _recall_mrr(by_book_unscoped[book]),
                "scoped_doc_type_book": _recall_mrr(by_book_scoped[book]),
            }
            for book in sorted(set(by_book_unscoped) | set(by_book_scoped))
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--questions", required=True, help="re-derived fixture path")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--out", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--db-path", default=None, help="corpus db (defaults to config's) -- throwaway db copies "
        "carry the same block/summary content as production, so the config's own db_path is fine "
        "unless the caller specifically needs the throwaway SQLite copy's paths",
    )
    parser.add_argument("--blob-dir", default=None)
    args = parser.parse_args()

    from app.assembly import build_mcp_server
    from rag.config import load_config
    from rag.gpu_lock import FileGpuLock

    config = load_config(args.config)

    lock = FileGpuLock(Path(config.gpu_lock_path))
    print(f"Waiting for GPU lock at {config.gpu_lock_path} ...")
    t0 = time.monotonic()
    with lock.acquire("tdoc87-routing-eval"):
        wait_s = time.monotonic() - t0
    print(f"Acquired (and released) GPU lock after waiting {wait_s:.1f}s")

    build_kwargs = {"collection": args.collection}
    if args.db_path is not None:
        build_kwargs["db_path"] = args.db_path
    if args.blob_dir is not None:
        build_kwargs["blob_dir"] = args.blob_dir
    server = build_mcp_server(config, **build_kwargs)
    retriever = server.retriever

    print(f"\n=== T-DOC87 chapter routing eval (collection={args.collection}) ===")
    result = run_routing_eval(retriever, Path(args.questions), args.k, args.limit)
    print(json.dumps(result, indent=2))

    report = {"collection": args.collection, "k": args.k, "gpu_lock_wait_s": wait_s, **result}
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
