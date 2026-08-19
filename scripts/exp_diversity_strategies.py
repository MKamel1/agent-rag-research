"""Compare paper-diversity strategies for `semantic_search`, on real questions and a real corpus.

Claim under test: the ADDITIVE strategy (`SearchFilters.min_distinct_papers`) reaches the same
paper coverage as the SUBTRACTIVE one (`max_hits_per_paper`) without deleting any passage the plain
query returned -- trading a larger result set for a guarantee.

Measured 2026-08-19 (60 questions, k=10, causal corpus):

    mode                          gold    distinct papers  result size  passages lost vs plain
    plain (uncapped)              60/60   3.92             10.00        0
    capped max_hits_per_paper=2   60/60   8.58             10.00        298
    additive min_distinct=8       60/60   8.00             14.08        0

Note the gold column is PAPER-level: it cannot see the cap's cost, because deleting a paper's
second-best passage is invisible while its best one survives. That is a limitation of the fixture,
not evidence the deletions are free -- see
docs/eval-reports/2026-08-19-retrieval-recall-precision.md.

    python scripts/exp_diversity_strategies.py [--limit 60] [--k 10]
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.assembly import build_mcp_server  # noqa: E402  (after sys.path bootstrap)
from contracts.vector_index import SearchFilters  # noqa: E402
from rag.config import load_config  # noqa: E402

_GROUND_TRUTH = REPO_ROOT / "fixtures/eval/eval_ground_truth.json"
_BLIND = REPO_ROOT / "fixtures/eval/eval_questions_blind.json"


def load_questions(limit: int) -> list[dict]:
    """`question_text` lives in the sibling blind file, joined by `question_id` -- the same shape
    `app/retrieval_eval.py::load_questions` handles."""
    records = json.loads(_GROUND_TRUTH.read_text())["ground_truth"]
    blind = json.loads(_BLIND.read_text())
    if isinstance(blind, dict):
        blind = blind.get("questions") or blind.get("ground_truth") or []
    text_by_id = {r["question_id"]: r["question_text"] for r in blind if "question_text" in r}
    return [dict(r, question_text=text_by_id[r["question_id"]])
            for r in records if r["question_id"] in text_by_id][:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT.parent / "research-system-rag-data/config.yaml"),
    )
    args = parser.parse_args()

    questions = load_questions(args.limit)
    server = build_mcp_server(load_config(args.config))
    modes = {
        "plain (uncapped)": None,
        "capped max_hits=2": SearchFilters(max_hits_per_paper=2),
        "additive min_papers=8": SearchFilters(min_distinct_papers=8),
    }
    agg = {name: {"gold": 0, "papers": [], "size": [], "lost": 0} for name in modes}
    plain_blocks: dict[str, set] = {}

    for index, question in enumerate(questions, 1):
        gold = {question["source_paper_id"], *(question.get("additional_gold_paper_ids") or [])}
        for name, filters in modes.items():
            results, _coverage = server.retriever.retrieve(
                question["question_text"], filters, args.k
            )
            blocks = {r.anchor.block_id for r in results}
            agg[name]["gold"] += 1 if {r.paper_id for r in results} & gold else 0
            agg[name]["papers"].append(len({r.paper_id for r in results}))
            agg[name]["size"].append(len(results))
            if name == "plain (uncapped)":
                plain_blocks[question["question_id"]] = blocks
            else:
                agg[name]["lost"] += len(plain_blocks[question["question_id"]] - blocks)
        if index % 20 == 0:
            print(f"  ...{index}/{len(questions)}", flush=True)

    n = len(questions)
    print(f"\n{'mode':26s} {'gold':>10s} {'distinct papers':>16s} "
          f"{'result size':>12s} {'passages LOST':>14s}")
    print("-" * 84)
    for name in modes:
        a = agg[name]
        print(f"{name:26s} {a['gold']:>5d}/{n:<4d} {statistics.mean(a['papers']):>16.2f} "
              f"{statistics.mean(a['size']):>12.2f} {a['lost']:>14d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
