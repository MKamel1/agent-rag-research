"""SCRATCH / THROWAWAY -- not part of the permanent suite, not imported by anything else.

One-off measurement script for Decision 3 (option A): does `SearchFilters.paper_id` scoping beat
`doc_type="book"` scoping, past the noise floor, on the 115-question book eval set
(`fixtures/eval/eval_book_questions.json`)? Written instead of modifying `app/retrieval_eval.py`
because that runner never threads `filters` through to `retrieve()`/`retrieve_papers()` (task
instructions: do not change it for this task) -- same reasoning `scripts/scratch_scoped_cap_eval.py`
(Decision 2's own measurement script) already documents; this script mirrors its shape.

Three configurations, scored via `retriever.retrieve_papers()` at chapter level (same hit
definition as `app/retrieval_eval.py`/`scratch_scoped_cap_eval.py`: gold paper_id AND gold chapter
title, within the top k):

1. unfiltered (`filters=None`)
2. `doc_type="book"` (today's shipped scoping)
3. `paper_id=<question's own source_paper_id>` (the new capability this task adds)

Reported per book (keyed by `source_paper_id`) AND overall -- a single aggregate can hide a
per-book collapse (T-DOC87's own lesson, cited in this task's brief).

Read-only against whatever `--collection` is passed (defaults to production `papers`, per the
task: production now carries IDF, and retrieval is read-only/safe -- never upsert/delete/rebuild).

Usage: python scripts/scratch_paperid_filter_eval.py --out /tmp/paperid_filter_eval.json
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from contracts.vector_index import SearchFilters

_NOISE_FLOOR = 0.125  # per the task brief: measured noise floor on this eval set


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


def run_paperid_filter_eval(retriever, questions_path: Path, k: int, limit: int | None = None) -> dict:
    data = json.loads(questions_path.read_text())["ground_truth"]
    if limit is not None:
        data = data[:limit]

    # per_book[source_paper_id][config_name] -> list[rank|None], in question order
    per_book: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    titles: dict[str, str] = {}
    overall: dict[str, list] = defaultdict(list)

    for q in data:
        paper_id = q["source_paper_id"]
        gold_papers = {paper_id}
        text = q["question_text"]
        chapter_title = q["gold_chapter_title"]
        titles[paper_id] = q.get("source_paper_title", paper_id)

        configs = {
            "unfiltered": None,
            "doc_type_book": SearchFilters(doc_type="book"),
            "paper_id": SearchFilters(paper_id=paper_id),
        }
        for name, filters in configs.items():
            results, _ = retriever.retrieve_papers(text, filters, k)
            rank = _chapter_rank(results, gold_papers, chapter_title, k)
            per_book[paper_id][name].append(rank)
            overall[name].append(rank)

    per_book_report = {}
    for paper_id, by_config in per_book.items():
        per_book_report[paper_id] = {
            "title": titles[paper_id],
            **{name: _recall_mrr(ranks) for name, ranks in by_config.items()},
        }

    overall_report = {name: _recall_mrr(ranks) for name, ranks in overall.items()}

    return {"n": len(data), "per_book": per_book_report, "overall": overall_report}


def _print_summary(report: dict) -> None:
    overall = report["overall"]
    print("\n=== Overall (n={}) ===".format(report["n"]))
    for name in ("unfiltered", "doc_type_book", "paper_id"):
        r = overall[name]
        print(f"  {name:16s}  recall@10={r['recall_at_k']:.3f}  mrr={r['mrr']:.3f}  n={r['n']}")

    unfiltered_r = overall["unfiltered"]["recall_at_k"]
    doc_type_r = overall["doc_type_book"]["recall_at_k"]
    paper_id_r = overall["paper_id"]["recall_at_k"]
    delta_vs_doc_type = paper_id_r - doc_type_r
    delta_vs_unfiltered = paper_id_r - unfiltered_r
    print(f"\n  paper_id vs doc_type=book delta: {delta_vs_doc_type:+.3f} "
          f"(noise floor {_NOISE_FLOOR:.3f} -> {'BEATS' if delta_vs_doc_type > _NOISE_FLOOR else 'does NOT beat'} it)")
    print(f"  paper_id vs unfiltered delta:    {delta_vs_unfiltered:+.3f}")

    print("\n=== Per book ===")
    for paper_id, by_config in report["per_book"].items():
        title = by_config["title"]
        print(f"\n  {paper_id} -- {title}")
        for name in ("unfiltered", "doc_type_book", "paper_id"):
            r = by_config[name]
            print(f"    {name:16s}  recall@10={r['recall_at_k']:.3f}  mrr={r['mrr']:.3f}  n={r['n']}")
        pid_r = by_config["paper_id"]["recall_at_k"]
        dt_r = by_config["doc_type_book"]["recall_at_k"]
        print(f"    delta (paper_id - doc_type_book): {pid_r - dt_r:+.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default="papers", help="defaults to production 'papers'")
    parser.add_argument("--config", default=None, help="defaults to $RAG_CONFIG")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--out", default=None, help="write the JSON result here")
    parser.add_argument(
        "--limit", type=int, default=None, help="score only the first N questions (smoke test)"
    )
    args = parser.parse_args()

    from app.assembly import build_mcp_server
    from rag.config import load_config
    from rag.gpu_lock import FileGpuLock

    import os
    config_path = args.config or os.environ.get("RAG_CONFIG")
    if not config_path:
        raise SystemExit("pass --config or set RAG_CONFIG")
    config = load_config(config_path)

    lock = FileGpuLock(Path(config.gpu_lock_path))
    print(f"Waiting for GPU lock at {config.gpu_lock_path} ...")
    t0 = time.monotonic()
    with lock.acquire("scratch-paperid-filter-eval"):
        wait_s = time.monotonic() - t0
    print(f"Acquired (and released) GPU lock after waiting {wait_s:.1f}s")

    server = build_mcp_server(config, collection=args.collection)
    retriever = server.retriever

    print(f"\n=== 115-question paper_id-filter eval (collection={args.collection}) ===")
    result = run_paperid_filter_eval(
        retriever, Path("fixtures/eval/eval_book_questions.json"), args.k, args.limit
    )
    _print_summary(result)

    report = {
        "collection": args.collection,
        "k": args.k,
        "gpu_lock_wait_s": wait_s,
        **result,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
