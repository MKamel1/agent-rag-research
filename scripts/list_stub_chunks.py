"""List heading-only stub chunks of a corpus DB. Read-only (SQLite `mode=ro`), no Qdrant, no GPU.

A stub is a chunk whose body is shorter than `rag.retriever._MIN_BODY_CHARS`, the definition the
`Retriever(drop_stub_chunks=True)` filter and `chunk_quality_census.py` use (CQ-3).

    python scripts/list_stub_chunks.py DB --out stubs.tsv
        # writes `chunk_id<TAB>anchor_block_id<TAB>paper_id` per stub (the input for deleting stub
        # points from a CLONED collection) and prints per-document counts.
    python scripts/list_stub_chunks.py DB --report base.json [--k 10]
        # stub-at-rank-1 share, stub share of top-k slots, and share of questions with a stub in the
        # top k, from an `app.retrieval_eval` report (needs the per-question rows).
    python scripts/list_stub_chunks.py DB --ab base.json drop.json
        # per-fixture ADOPT facts, docs/eval-reports/2026-11-10-cq3-stub-chunks.md.
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.retriever import _MIN_BODY_CHARS, body_of  # noqa: E402  (after sys.path bootstrap)


def stub_chunks(db_path: str, min_chars: int = _MIN_BODY_CHARS) -> list[tuple[str, str, str]]:
    """`(chunk_id, anchor_block_id, paper_id)` for every stub chunk, in chunk_id order."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select chunk_id, anchor_json, paper_id, text from chunks order by chunk_id"
        ).fetchall()
    finally:
        con.close()
    return [
        (cid, json.loads(anchor)["block_id"], pid)
        for cid, anchor, pid, text in rows
        if len(body_of(text)) < min_chars
    ]


def rank_shares(report: dict, stub_blocks: set[str], k: int = 10) -> dict:
    """Stub exposure in a baseline report. A stub's anchor is its heading block, so a retrieved
    block id in `stub_blocks` is a stub slot."""
    rows = [q for q in report["questions"] if not q["error"] and q["retrieved_block_ids"]]
    n = len(rows) or 1
    at1 = sum(q["retrieved_block_ids"][0] in stub_blocks for q in rows)
    slots = [b for q in rows for b in q["retrieved_block_ids"][:k]]
    any_k = sum(any(b in stub_blocks for b in q["retrieved_block_ids"][:k]) for q in rows)
    return {
        "questions": len(rows),
        "stub_at_rank1_share": at1 / n,
        "stub_slot_share_topk": sum(b in stub_blocks for b in slots) / (len(slots) or 1),
        "questions_with_stub_in_topk_share": any_k / n,
    }


def ab_facts(base: dict, drop: dict, stub_blocks: set[str], k: int = 10) -> dict:
    """The three pre-registered criteria for ONE fixture (ADOPT needs them across all fixtures:
    criterion 1 on at least one, 2 on every one, 3 on at least one)."""
    b = {q["question_id"]: q for q in base["questions"]}
    d = {q["question_id"]: q for q in drop["questions"]}
    both = [qid for qid in b if qid in d and not b[qid]["error"] and not d[qid]["error"]]
    net: Counter = Counter()  # (stratum, metric) -> hits(drop) - hits(base)
    for qid in both:
        for stratum in (
            f"doc_type={b[qid]['doc_type']}",
            f"question_type={b[qid]['question_type']}",
        ):
            net[(stratum, "paper_hit")] += (
                d[qid]["paper_level"]["hit"] - b[qid]["paper_level"]["hit"]
            )
            if b[qid]["passage_level"]["scored"]:
                net[(stratum, "passage_hit")] += (
                    d[qid]["passage_level"]["hit"] - b[qid]["passage_level"]["hit"]
                )
    scored = [q for q in both if b[q]["passage_level"]["scored"]]

    def p1(r, qs):
        return sum(r[q]["passage_level"]["rank"] == 1 for q in qs)

    def hit(r, qs):
        return sum(r[q]["passage_level"]["hit"] for q in qs)

    return {
        "stub_at_rank1_share": rank_shares(base, stub_blocks, k)["stub_at_rank1_share"],
        "worst_stratum_net_change": min(net.values(), default=0),
        "passage_p_at_1_change": p1(d, scored) - p1(b, scored),
        "passage_hit_at_k_change": hit(d, scored) - hit(b, scored),
        "criterion_1_stub_at_rank1_positive": rank_shares(base, stub_blocks, k)[
            "stub_at_rank1_share"
        ]
        > 0,
        "criterion_2_no_stratum_drops_more_than_one": all(v >= -1 for v in net.values()),
        "criterion_3_p1_or_hit_improves": (p1(d, scored) > p1(b, scored))
        or (hit(d, scored) > hit(b, scored)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("db")
    ap.add_argument("--out", help="write chunk_id<TAB>anchor_block_id<TAB>paper_id here")
    ap.add_argument("--report", help="baseline app.retrieval_eval report JSON")
    ap.add_argument("--ab", nargs=2, metavar=("BASE", "DROP"))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--min-chars", type=int, default=_MIN_BODY_CHARS)
    args = ap.parse_args()
    stubs = stub_chunks(args.db, args.min_chars)
    if args.out:
        Path(args.out).write_text("".join(f"{c}\t{b}\t{p}\n" for c, b, p in stubs))
    blocks = {b for _, b, _ in stubs}
    if args.report:
        print(
            json.dumps(
                rank_shares(json.loads(Path(args.report).read_text()), blocks, args.k), indent=1
            )
        )
    elif args.ab:
        base, drop = (json.loads(Path(p).read_text()) for p in args.ab)
        print(json.dumps(ab_facts(base, drop, blocks, args.k), indent=1))
    else:
        per_doc = Counter(p for _, _, p in stubs)
        print(f"{args.db}: {len(stubs)} stub chunks in {len(per_doc)} documents")
        for paper_id, n in per_doc.most_common():
            print(f"{n}\t{paper_id}")


if __name__ == "__main__":
    main()
