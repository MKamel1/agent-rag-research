"""Per-stratum table for one app.retrieval_eval report, joined to standards_gt.json.

    python analyze_run.py runs/<stamp>/depth128-fused.json [more reports...]

Adds what the stock report cannot say: results by `dimension`, whether a commentary document
outranks the normative one (authority), whether the other edition outranks the named one
(edition), cross-document coverage, and how often a heading-only stub chunk holds rank 1.
"""
import collections
import json
import sqlite3
import sys

DB = "/home/omar/ai-projects/research-system-rag-standards/data/papers.db"
gt = {it["question_id"]: it for it in json.load(open("standards_gt.json"))["ground_truth"]}

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
stub_anchor_blocks = {
    json.loads(anchor)["block_id"]
    for text, anchor in con.execute("select text, anchor_json from chunks")
    if len(text.split("\n\n", 1)[-1].strip()) < 40
}


def first_rank(ids, wanted):
    return next((i + 1 for i, x in enumerate(ids) if x in wanted), None)


def frac(xs):
    return f"{sum(xs)}/{len(xs)} = {sum(xs) / len(xs):.3f}" if xs else "n/a"


for path in sys.argv[1:]:
    report = json.load(open(path))
    rows = report["questions"]
    print(f"\n=== {path}")
    by_dim = collections.defaultdict(list)
    for r in rows:
        by_dim[gt[r["question_id"]]["dimension"]].append(r)
    print(f"{'dimension':20} {'n':>3}  paper R@10        paper P@1         passage hit@10    passage P@1")
    for dim, rs in sorted(by_dim.items()):
        ans = [r for r in rs if r["gold_paper_ids"]]
        if not ans:
            continue
        psg = [r for r in ans if r["passage_level"]["scored"]]
        print(f"{dim:20} {len(ans):>3}  "
              f"{frac([r['paper_level']['hit'] for r in ans]):17} "
              f"{frac([r['paper_level']['rank'] == 1 for r in ans]):17} "
              f"{frac([r['passage_level']['hit'] for r in psg]):17} "
              f"{frac([r['passage_level']['rank'] == 1 for r in psg])}")

    answerable = [r for r in rows if r["gold_paper_ids"]]
    absent = [r for r in rows if not r["gold_paper_ids"]]
    print("stub chunk at rank 1 (all questions):",
          frac([bool(r["retrieved_block_ids"]) and r["retrieved_block_ids"][0] in stub_anchor_blocks
                for r in rows]))
    print("stub share of all top-10 slots:",
          frac([b in stub_anchor_blocks for r in rows for b in r["retrieved_block_ids"]]))

    def outranked(field):
        out = []
        for r in rows:
            others = set(gt[r["question_id"]].get(field) or [])
            if others:
                gold = first_rank(r["retrieved_paper_ids"], set(r["gold_paper_ids"])) or 99
                other = first_rank(r["retrieved_paper_ids"], others) or 99
                out.append(other < gold)
        return out

    print("authority: commentary outranks the normative document:", frac(outranked("commentary_paper_ids")))
    print("edition: other edition outranks the named one:", frac(outranked("other_edition_paper_ids")))

    cross = [r for r in rows if gt[r["question_id"]]["dimension"] == "cross-document"]
    print("cross-document: ALL gold documents in top-10:",
          frac([set(r["gold_paper_ids"]) <= set(r["retrieved_paper_ids"]) for r in cross]))

    def scores(rs):
        s = sorted(r["top_score"] for r in rs if r["top_score"] is not None)
        return f"n={len(s)} min={s[0]:.4f} median={s[len(s) // 2]:.4f} max={s[-1]:.4f}" if s else "n/a"

    print("top-score, answerable:", scores(answerable))
    print("top-score, absent:    ", scores(absent), "(overlap = the system cannot abstain on score alone)")
    for r in absent:
        distractor = gt[r["question_id"]].get("nearest_distractor_paper_id")
        if distractor and r["retrieved_paper_ids"][:1] == [distractor]:
            print("  predicted distractor at rank 1:", r["question_id"])
