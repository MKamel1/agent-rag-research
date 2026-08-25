"""`python -m app.exp_nb_d3_fresh_capture` -- NB-D3's ONE fresh confirmation pass per fixture.

Reuses `app.retrieval_eval.load_questions` unmodified (same duplicate-exclusion the stored
2026-08-23 baseline used, hence comparable denominators) and the same server wiring
`app.score_distribution_census` uses. The ONLY new thing here is capturing the FULL score vector
(all k ranks) plus rank order, which the standard report shape does not persist -- that is what
makes the census's rank1->rank2-gap and above-threshold-count features computable at all.

Measurement instrument only: decides nothing, abstains nowhere. Output feeds
`scripts.abstention_feature_census --fresh-dir`.

Run against the LIVE stack (services up), config frozen at hybrid_dense_weight=0.7,
`--collection waymo_av_safety` explicit -- omitting it silently queries the wrong corpus
(programme constraint 8).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from app.retrieval_eval import load_questions

logger = logging.getLogger(__name__)

_WAYMO_CONFIG = "/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml"
_FIXTURES = {
    "ver84": Path("fixtures/eval/waymo_gt_verified.json"),
    "gt_wmr": Path("fixtures/eval/gt_wmr.json"),
}
_K = 10


def capture_fixture(name: str, fixture_path: Path, server, k: int) -> dict:
    questions = load_questions(fixture_path)
    records = []
    errored = 0
    started = time.monotonic()
    for i, question in enumerate(questions, start=1):
        try:
            hits, _coverage = server.retriever.retrieve(question.question_text, None, k)
            records.append({
                "question_id": question.question_id,
                "absent": not question.gold_paper_ids,
                "scores": [float(r.score) for r in hits[:k]],
                "paper_ids": [r.paper_id for r in hits[:k]],
            })
        except Exception as e:  # noqa: BLE001 -- mirrors retrieval_eval.run()'s posture
            logger.warning("retrieve() failed for %s: %s", question.question_id, e)
            records.append({
                "question_id": question.question_id,
                "absent": not question.gold_paper_ids,
                "scores": [],
                "paper_ids": [],
                "error": str(e),
            })
            errored += 1
        if i % 20 == 0:
            logger.info("%s: scored %d/%d", name, i, len(questions))
    elapsed = time.monotonic() - started
    return {
        "fixture": name,
        "fixture_path": str(fixture_path),
        "k": k,
        "n_questions": len(questions),
        "n_errors": errored,
        "elapsed_seconds": round(elapsed, 1),
        "questions": records,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", nargs="*", choices=sorted(_FIXTURES), default=None,
                        help="subset to run; default = both")
    parser.add_argument("--config", default=_WAYMO_CONFIG)
    parser.add_argument("--collection", default="waymo_av_safety")
    parser.add_argument("--k", type=int, default=_K)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("docs/eval-reports/data/2026-08-25-nb-d3"))
    args = parser.parse_args()

    from rag.config import load_config
    from app.assembly import build_mcp_server

    config = load_config(args.config)
    server = build_mcp_server(config, collection=args.collection)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    names = args.fixtures or sorted(_FIXTURES)
    for name in names:
        result = capture_fixture(name, _FIXTURES[name], server, args.k)
        weight = getattr(config, "hybrid_dense_weight", None)
        result["hybrid_dense_weight"] = float(weight) if weight is not None else None
        result["config_path"] = args.config
        result["collection"] = args.collection
        out_path = args.out_dir / f"{name}_fresh.json"
        out_path.write_text(json.dumps(result, indent=2))
        logger.info("wrote %s (%d questions, %d errors, %.1fs)",
                    out_path, result["n_questions"], result["n_errors"], result["elapsed_seconds"])


if __name__ == "__main__":
    main()
