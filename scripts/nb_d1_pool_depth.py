"""NB-D1 — candidate-pool depth instrumentation (completes PREC-1 §2).

QUESTION (one): for scored items whose rank-1 PAPER is correct but whose gold BLOCK is not at
rank 1 -- PREC-1 §1's C1 population (gold block inside the returned top-10, ranks 2-10) and C2
population (gold block absent from the returned top-10 entirely) -- does the gold chunk exist
DEEPER in the candidate pool? I.e. would retrieving k in {32, 64, 128} candidates before the
rerank-to-10 expose it (and at what depth), or is it absent from every pool size?

METHOD (reuse-first, nothing new invented):

  * Fixture loading is `app.retrieval_eval.load_questions` UNCHANGED (same duplicate_of
    exclusion, same multi-gold folding, same vision_derived flag as every published eval).
  * Retrieval is the REAL production pipeline wired exactly the way
    `app/retrieval_eval.py::main()` wires it: `load_config` on the corpus's own config.yaml
    (frozen shipped values -- hybrid_dense_weight=0.7, rerank_depth=32; nothing is overridden)
    and `app.assembly.build_mcp_server` with the collection named explicitly.
  * The depth knob already exists: `Retriever.retrieve(query, filters, K)` fetches
    `max(K, rerank_pool_size)` hybrid candidates, reranks the WHOLE pool (the cross-encoder
    packs oversized pools into token-budgeted batches and merges with a global sort --
    rag/reranker.py), and truncates to K only afterwards (rag/retriever.py, T-DOC24). So
    retrieve(..., K) IS the depth-K experiment, and because the merged sort is
    length-preserving, the returned list contains every resolvable pool candidate in rerank
    order: a gold block absent from that list was never in the hybrid pool at all. Nothing else
    in the repo exposes deeper-than-10 ordering, which is why this script exists.
  * Scoring/classification reuses `app.retrieval_eval.score_question` UNCHANGED: called with
    k=10 for the shipped-shape pass (pool=max(10, 32)=32 candidates -> rerank -> truncate to 10,
    byte-for-byte the shipped retrieval shape) and with k=K for each deep pass.

Populations are defined ONCE per fixture from the shipped-shape run (k=10), using PREC-1 §1's
own one-bucket-each joint decomposition (A / C1 / C2 / D / E), then tracked across pool sizes.
The bottomless-pool ceiling at depth K = share of scored items whose gold block appears ANYWHERE
in the depth-K reranked list -- what a perfect reranker drawing from that pool would score at
rank 1 (it reorders the whole pool before any truncation). Read-only end to end.

One fixture per invocation (one input file -> one output JSON). Run detached; ~656 retrievals
for both fixtures x {10, 32, 64, 128}.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from app.retrieval_eval import Question, load_questions, score_question

logger = logging.getLogger(__name__)

SHIPPED_K = 10

# Depth histogram bins for where gold sits when present deeper than the top-10. Bin edges track
# the measured pool sizes so a reader can see "reachable only if the pool grew past X" directly.
DEPTH_BINS = ((11, 32), (33, 64), (65, 128))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--collection", required=True,
                        help="named vector-store collection (constraint 8: always explicit)")
    parser.add_argument("--pool-sizes", type=int, nargs="+", default=[32, 64, 128])
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--limit", type=int, default=None, help="first N scored questions (smoke)")
    return parser.parse_args()


def classify(row: dict) -> str:
    """PREC-1 §1's joint decomposition, one bucket per item, checked in its precedence order."""
    if row["error"]:
        return "error"
    if row["passage_rank"] == 1:
        return "A"
    if row["paper_rank"] == 1 and row["passage_rank"] is not None:
        return "C1"
    if row["paper_rank"] == 1 and row["passage_rank"] is None:
        return "C2"
    if row["paper_rank"] is not None:
        return "D"
    return "E"


def retrieve_once(question: Question, retriever, k: int) -> tuple[dict, int]:
    """One production `retrieve()` call, scored by the UNMODIFIED `score_question`. Returns the
    scoring dict plus the true pre-rerank hybrid pool size (`coverage.candidate_count`) -- at
    K=128 a count below 128 means the store itself ran out of candidates, which changes how an
    'absent' verdict must be read."""
    hits, coverage = retriever.retrieve(question.question_text, None, k)
    result = score_question(question, hits, k)
    return {
        "error": None,
        "paper_rank": result.paper_rank,
        "passage_rank": result.passage_rank,
        "n_returned": len(result.retrieved_block_ids),
    }, coverage.candidate_count


def run_row(question: Question, retriever, pool_sizes: list[int]) -> dict:
    """One question: the shipped-shape pass (population definer) + one deep pass per pool size."""
    row: dict = {
        "question_id": question.question_id,
        "vision_derived": question.vision_derived,
        "n_gold_papers": len(question.gold_paper_ids),
    }
    try:
        shipped, cand_count = retrieve_once(question, retriever, SHIPPED_K)
    except Exception as e:  # noqa: BLE001 -- mirrors app/retrieval_eval.run()'s posture: one bad
        # question must not blank the fixture; the error travels into the row and the aggregate.
        logger.warning("shipped-shape retrieve failed for %s: %s", question.question_id, e)
        shipped, cand_count = {"error": str(e), "paper_rank": None, "passage_rank": None,
                               "n_returned": 0}, 0
    shipped["candidate_count"] = cand_count
    shipped["population"] = classify(shipped)
    row["shipped"] = shipped

    row["deep"] = {}
    for k in pool_sizes:
        try:
            deep, deep_cand = retrieve_once(question, retriever, k)
        except Exception as e:  # noqa: BLE001 -- same posture as above
            logger.warning("deep k=%d retrieve failed for %s: %s", k, question.question_id, e)
            deep, deep_cand = {"error": str(e), "paper_rank": None, "passage_rank": None,
                               "n_returned": 0}, 0
        # passage_rank within the first k == its 1-based position in the full deep list, because
        # Retriever.retrieve already truncated the reranked pool to exactly k.
        deep["candidate_count"] = deep_cand
        row["deep"][str(k)] = deep
    return row


def _depth_bin(depth: int | None) -> str | None:
    if depth is None or depth <= SHIPPED_K:
        return None  # <=10 is the shipped top-10 itself, reported elsewhere
    for lo, hi in DEPTH_BINS:
        if lo <= depth <= hi:
            return f"{lo}-{hi}"
    return f">{DEPTH_BINS[-1][1]}"


def aggregate(rows: list[dict], pool_sizes: list[int]) -> dict:
    """Every number the report quotes, computed here so report == script output by construction.
    Denominators ride next to every count; fixtures are never mixed (one invocation = one file).
    """
    n_rows = len(rows)
    errors_shipped = [r["question_id"] for r in rows if r["shipped"]["population"] == "error"]
    scorable = [r for r in rows if r["shipped"]["population"] != "error"]
    n_scorable = len(scorable)

    pops = Counter(r["shipped"]["population"] for r in rows)
    pop_members = {p: sorted(r["question_id"] for r in rows if r["shipped"]["population"] == p)
                   for p in ("A", "C1", "C2", "D", "E", "error")}

    # Reorder-only ceiling (PREC-1 §1's number, recomputed on THIS run): gold anywhere in the
    # shipped top-10 -> a perfect reranker of that top-10 scores it at rank 1.
    reorder_only_hits = [r["question_id"] for r in scorable
                         if r["shipped"]["passage_rank"] is not None]

    population_rows = [r for r in rows if r["shipped"]["population"] in ("C1", "C2")]

    per_k = {}
    for k in pool_sizes:
        key = str(k)
        # Population focus: C1+C2 members -- is gold in the depth-k pool, and how deep?
        pres_ids, absent_ids, bins = [], [], Counter()
        c1_present = c2_present = 0
        vision_absent_everywhere = []
        for r in population_rows:
            d = r["deep"][key]
            if d["error"]:
                continue
            depth = d["passage_rank"]
            if depth is not None:
                pres_ids.append(r["question_id"])
                bin_ = _depth_bin(depth)
                bins[bin_ if bin_ else f"<={SHIPPED_K}"] += 1
                if r["shipped"]["population"] == "C1":
                    c1_present += 1
                else:
                    c2_present += 1
            else:
                absent_ids.append(r["question_id"])
                if r["vision_derived"]:
                    vision_absent_everywhere.append(r["question_id"])
        n_deep_ok = len(pres_ids) + len(absent_ids)

        # Bottomless ceiling over ALL scorable items: gold anywhere in the depth-k pool ->
        # a perfect reranker drawing from that pool scores it at rank 1.
        ceiling_hits = sum(
            1 for r in scorable
            if not r["deep"][key]["error"] and r["deep"][key]["passage_rank"] is not None
        )
        cand_counts = [r["deep"][key]["candidate_count"] for r in scorable
                       if not r["deep"][key]["error"]]
        deeper_than_10 = sum(
            1 for r in population_rows
            if not r["deep"][key]["error"]
            and (depth := r["deep"][key]["passage_rank"]) is not None and depth > SHIPPED_K
        )
        per_k[key] = {
            "population_n": len(population_rows),
            "population_deep_scored_n": n_deep_ok,
            "gold_in_deep": len(pres_ids),
            "gold_absent_from_deep": len(absent_ids),
            "gold_absent_ids": absent_ids,
            "c1_gold_in_deep": c1_present,
            "c2_gold_in_deep": c2_present,
            "depth_histogram": dict(sorted(bins.items())),
            "present_only_beyond_10": deeper_than_10,
            "bottomless_ceiling": {
                "hits": ceiling_hits,
                "n": n_scorable,
                "rate": (ceiling_hits / n_scorable) if n_scorable else None,
            },
            "pre_rerank_candidate_count_min": min(cand_counts) if cand_counts else None,
            "pre_rerank_candidate_count_max": max(cand_counts) if cand_counts else None,
            "vision_derived_still_absent": vision_absent_everywhere,
        }

    return {
        "fixture_questions_total": n_rows,
        "scored_n": n_scorable,
        "shipped_pass_errors": errors_shipped,
        "joint_decomposition": {p: pops.get(p, 0) for p in ("A", "C1", "C2", "D", "E", "error")},
        "population_members": pop_members,
        "reorder_only_ceiling": {
            "hits": len(reorder_only_hits), "n": n_scorable,
            "rate": (len(reorder_only_hits) / n_scorable) if n_scorable else None,
        },
        "per_pool_size": per_k,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()

    # Deferred imports: real GPU-backed adapter wiring, never touched by unit tests (same shape
    # as app/retrieval_eval.main()).
    from app.assembly import build_mcp_server
    from rag.config import load_config

    config = load_config(args.config)
    server = build_mcp_server(config, collection=args.collection)

    questions = load_questions(Path(args.ground_truth))
    scored = [q for q in questions if q.gold_block_id is not None]
    if args.limit is not None:
        scored = scored[: args.limit]
    logger.info("fixture %s: %d records, %d passage-scored, pools %s",
                args.ground_truth, len(questions), len(scored), args.pool_sizes)

    rows = []
    for i, q in enumerate(scored, start=1):
        rows.append(run_row(q, server.retriever, args.pool_sizes))
        if i % 10 == 0 or i == len(scored):
            logger.info("scored %d/%d questions", i, len(scored))

    agg = aggregate(rows, args.pool_sizes)
    out = {
        "ticket": "NB-D1",
        "ground_truth": args.ground_truth,
        "config": args.config,
        "collection": args.collection,
        "hybrid_dense_weight": config.hybrid_dense_weight,
        "rerank_depth": config.rerank_depth,
        "shipped_k": SHIPPED_K,
        "pool_sizes": args.pool_sizes,
        **agg,
        "rows": rows,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2))

    print(f"\n== NB-D1 summary: {args.ground_truth} ==")
    print(f"scored n={agg['scored_n']}  decomposition {agg['joint_decomposition']}")
    roc = agg["reorder_only_ceiling"]
    print(f"reorder-only ceiling: {roc['hits']}/{roc['n']} = {roc['rate']:.4f}")
    for k in args.pool_sizes:
        p = agg["per_pool_size"][str(k)]
        bc = p["bottomless_ceiling"]
        print(f"K={k:>4}: population(C1+C2)={p['population_n']}"
              f"  gold-in-deep={p['gold_in_deep']}/{p['population_deep_scored_n']}"
              f"  absent={p['gold_absent_from_deep']}"
              f"  hist={p['depth_histogram']}"
              f"  bottomless-ceiling={bc['hits']}/{bc['n']}={bc['rate']:.4f}"
              f"  pre-rerank-pool[min,max]="
              f"{p['pre_rerank_candidate_count_min'], p['pre_rerank_candidate_count_max']}")
    print(f"Wrote {args.out_json}")


if __name__ == "__main__":
    main()
