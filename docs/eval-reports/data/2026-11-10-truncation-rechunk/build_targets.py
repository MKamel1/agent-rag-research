"""CQ-4: build the re-chunk target lists for chunks truncated at embed time.

Read-only (sqlite `mode=ro`), standard library only, no GPU, no service calls.

Rule (APPROXIMATION): a chunk is treated as truncated when its text is longer than
THRESH_CHARS characters. The exact per-chunk list is NOT stored in
../2026-11-10-embed-truncation/results.json (it keeps only aggregates, top-10 and the
>30k list), so the exact token rule (> 4,096 Qwen3 tokens) cannot be re-derived here
without the tokenizer. The approximation is cross-checked against the exact aggregate
counts in results.json (over_4096) and the gap is written to summary.json.

Outputs (in this script's directory):
  targets_<corpus>.txt        one paper_id per line (format of app/rechunk.py --paper-ids-file)
  tsv_<corpus>.tsv            per affected paper: id, title, truncated chunks, total chunks, ...
  gt_affected.tsv             ground-truth items whose source paper is a main-corpus target
  summary.json                counts, concentration, top-20, embedding-cost estimate

Usage: python build_targets.py [--out-dir DIR]
"""

import argparse
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))

DBS = {
    "main": "/home/omar/ai-projects/research-system-rag-data/papers.db",
    "waymo": "/home/omar/ai-projects/research-system-rag/waymo/data/papers.db",
}
RESULTS = os.path.join(REPO, "docs/eval-reports/data/2026-11-10-embed-truncation/results.json")
GT_FILES = [
    os.path.join(REPO, "docs/eval-reports/data/2026-11-10-papers-passage-gt/"
                       "papers_passage_gt.json"),
    os.path.join(REPO, "docs/eval-reports/data/2026-11-10-causal-books-gt/causal_books_gt.json"),
    os.path.join(REPO, "fixtures/eval/eval_book_questions.json"),
]

# APPROXIMATION: ~3 chars/token for table/equation-dense text, ~4 for prose; 4,096 tokens sits
# between 12k and 16k chars. 14,000 is a middle cut that catches the measured exact set in
# practice (checked against results.json over_4096 below). Not the exact rule.
THRESH_CHARS = 14000
# Bounded chunker budget (rag/chunker.py _MAX_CHUNK_CHARS); used only for the cost estimate.
NEW_CHUNK_CHARS = 1200


def exact_ids(name):
    """Exact truncated chunk ids from exact_truncated_ids.py, or None if not yet produced."""
    p = os.path.join(HERE, f"truncated_chunk_ids_{name}.txt")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return {line.strip() for line in fh if line.strip()}


def scan_corpus(path, name):
    """Return per-paper aggregates and the set of truncated chunk ids (exact if available)."""
    exact = exact_ids(name)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        titles = dict(conn.execute("SELECT paper_id, title FROM papers"))
        papers = defaultdict(lambda: {"chunks": 0, "chars": 0, "ceil_chunks": 0,
                                      "trunc": 0, "trunc_chars": 0})
        trunc_ids = set()
        total_chunks = 0
        total_chars = 0
        for chunk_id, paper_id, n in conn.execute(
            "SELECT chunk_id, paper_id, length(text) FROM chunks"
        ):
            total_chunks += 1
            total_chars += n
            p = papers[paper_id]
            p["chunks"] += 1
            p["chars"] += n
            p["ceil_chunks"] += math.ceil(n / NEW_CHUNK_CHARS)
            is_trunc = (chunk_id in exact) if exact is not None else (n > THRESH_CHARS)
            if is_trunc:
                trunc_ids.add(chunk_id)
                p["trunc"] += 1
                p["trunc_chars"] += n
    finally:
        conn.close()
    return {
        "titles": titles, "papers": dict(papers), "trunc_ids": trunc_ids,
        "total_papers": len(titles), "total_chunks": total_chunks, "total_chars": total_chars,
    }


def clean(s):
    return " ".join((s or "").split())


def concentration(affected):
    """affected: list of (paper_id, trunc_chars). Papers needed for 50% / 90% of cut chars."""
    total = sum(c for _, c in affected)
    out = {"n50": None, "n90": None}
    if total == 0:
        return out
    run = 0
    for i, (_, c) in enumerate(sorted(affected, key=lambda x: -x[1]), 1):
        run += c
        if out["n50"] is None and run >= 0.5 * total:
            out["n50"] = i
        if out["n90"] is None and run >= 0.9 * total:
            out["n90"] = i
            break
    return out


def gt_items(path):
    """Yield (item_id, source_paper_id, gold_chunk_id) for every dict with source_paper_id."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    counter = [0]

    def walk(node):
        if isinstance(node, dict):
            if "source_paper_id" in node:
                counter[0] += 1
                item_id = node.get("id") or node.get("question_id") or node.get("qid") \
                    or f"#{counter[0]}"
                yield (str(item_id), node["source_paper_id"], node.get("gold_chunk_id"))
            for v in node.values():
                yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)

    return list(walk(data)), counter[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", default=HERE)
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    with open(RESULTS, encoding="utf-8") as fh:
        exact = json.load(fh)

    summary = {"rule": ("exact token count > 4096 (truncated_chunk_ids_<corpus>.txt from "
                        "exact_truncated_ids.py); fallback approximation: chars > "
                        f"{THRESH_CHARS} when that file is absent"),
               "new_chunk_chars": NEW_CHUNK_CHARS, "corpora": {}}
    main_targets = set()
    trunc_ids_main = set()

    for name, path in DBS.items():
        scan = scan_corpus(path, name)
        titles, papers = scan["titles"], scan["papers"]
        affected = [(pid, p) for pid, p in papers.items() if p["trunc"] > 0]
        affected.sort(key=lambda x: -x[1]["trunc_chars"])

        with open(os.path.join(args.out_dir, f"targets_{name}.txt"), "w", encoding="utf-8") as fh:
            for pid, _ in sorted(affected):
                fh.write(pid + "\n")
        with open(os.path.join(args.out_dir, f"tsv_{name}.tsv"), "w", encoding="utf-8") as fh:
            fh.write("paper_id\ttitle\ttruncated_chunks\ttotal_chunks\ttruncated_chars"
                     "\tpaper_chars\test_new_chunks_lo\test_new_chunks_hi\n")
            for pid, p in affected:
                lo = math.ceil(p["chars"] / NEW_CHUNK_CHARS)
                fh.write(f"{pid}\t{clean(titles.get(pid))}\t{p['trunc']}\t{p['chunks']}"
                         f"\t{p['trunc_chars']}\t{p['chars']}\t{lo}\t{p['ceil_chunks']}\n")

        conc = concentration([(pid, p["trunc_chars"]) for pid, p in affected])
        repl_chunks = sum(p["chunks"] for _, p in affected)
        repl_chars = sum(p["chars"] for _, p in affected)
        est_lo = sum(math.ceil(p["chars"] / NEW_CHUNK_CHARS) for _, p in affected)
        est_hi = sum(p["ceil_chunks"] for _, p in affected)
        exact_n = exact.get(name, {}).get("over_4096")
        approx_n = sum(p["trunc"] for _, p in affected)
        summary["corpora"][name] = {
            "papers_total": scan["total_papers"],
            "chunks_total": scan["total_chunks"],
            "affected_papers": len(affected),
            "truncated_chunks_approx": approx_n,
            "truncated_chunks_exact_results_json": exact_n,
            "truncated_chars_approx": sum(p["trunc_chars"] for _, p in affected),
            "chunks_to_replace": repl_chunks,
            "chars_to_replace": repl_chars,
            "papers_for_50pct_truncated_chars": conc["n50"],
            "papers_for_90pct_truncated_chars": conc["n90"],
            "est_new_chunks_lo": est_lo,
            "est_new_chunks_hi": est_hi,
            "top20": [
                {"paper_id": pid, "title": clean(titles.get(pid))[:120],
                 "truncated_chunks": p["trunc"], "total_chunks": p["chunks"],
                 "truncated_chars": p["trunc_chars"]}
                for pid, p in affected[:20]
            ],
        }
        if name == "main":
            main_targets = {pid for pid, _ in affected}
            trunc_ids_main = scan["trunc_ids"]

    gt_rows = []
    gt_totals = {}
    for path in GT_FILES:
        rel = os.path.relpath(path, REPO)
        items, n_items = gt_items(path)
        gt_totals[rel] = n_items
        for item_id, src, gold in items:
            if src in main_targets:
                gt_rows.append((rel, item_id, src, gold or "",
                                "yes" if gold in trunc_ids_main else "no"))
    with open(os.path.join(args.out_dir, "gt_affected.tsv"), "w", encoding="utf-8") as fh:
        fh.write("file\titem_id\tsource_paper_id\tgold_chunk_id\tgold_chunk_truncated_approx\n")
        for row in gt_rows:
            fh.write("\t".join(row) + "\n")
    summary["gt"] = {"items_per_file": gt_totals, "affected_items": len(gt_rows)}

    with open(os.path.join(args.out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)

    for name, c in summary["corpora"].items():
        print(name, {k: v for k, v in c.items() if k != "top20"})
    print("gt", summary["gt"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
