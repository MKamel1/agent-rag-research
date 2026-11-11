"""Small, pure helpers the 2026-11-10 benchmark run scripts call. No GPU, never writes a fixture.

  python scripts/eval_protocol_tools.py check-hash HASHES.json NAME [NAME ...]
  python scripts/eval_protocol_tools.py check-points --collection C --db PAPERS.db
  python scripts/eval_protocol_tools.py ablate GT.json OUT.json
  python scripts/eval_protocol_tools.py split --field paper_topic GT.json REPORT.json OUT_DIR
  python scripts/eval_protocol_tools.py wilson GT.json

check-hash    every NAME (a repo-relative fixture path) must be listed in HASHES.json with a
              non-null SHA-256 equal to the file's. A null hash means "not frozen yet" and fails.
check-points  wrong-corpus guard: the vector-store collection's point count (Qdrant REST, read
              only) must lie in [0.98 * chunks, chunks + papers + 1%] of the corpus DB (read only):
              one point per chunk plus at most one summary point per paper.
ablate        control (i): write a title-ablated copy of a ground-truth file (derived file; the
              fixture itself is never touched). Each answerable item that carries
              `source_paper_title` keeps its ids and everything else; only `question_text`
              changes: every whitespace-delimited word whose alphanumeric tokens ALL occur in the
              gold document's title (and that is not a stopword) is dropped. Items with no
              title (cross-document), `edition` / `authority` items (the document identity IS the
              question) and items left with < 4 words are omitted and counted in `_metadata`.
              Over-ablates by design: topical words shared with the title go too.
split         write one sub-report per distinct value of a ground-truth item field (e.g.
              paper_topic) so scripts/eval_strata_report.py can be run per value, never blended.
wilson        print per-dimension n (answerable / passage-scored) and the 95% Wilson half-width
              at the worst case p = 0.5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MIN_WORDS = 4
SKIP_DIMENSIONS = frozenset({"edition", "authority", "cross-document"})
STOP = frozenset(
    "the a an of in on for to and or is are what which how does do did under by with that this as "
    "at from be it its when why who whom into than then their there these those can could would "
    "should shall may might not no".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_hashes(hashes_path: Path, names: list[str], root: Path = REPO) -> list[str]:
    """Problem strings (empty = all frozen and unchanged)."""
    frozen = json.loads(hashes_path.read_text())["fixtures"]
    problems = []
    for name in names:
        want = frozen.get(name)
        if name not in frozen:
            problems.append(f"{name}: not listed in {hashes_path.name}")
        elif want is None:
            problems.append(f"{name}: hash not frozen yet (null) -- freeze it before measuring")
        elif not (root / name).is_file():
            problems.append(f"{name}: file missing")
        elif (got := sha256_of(root / name)) != want:
            problems.append(f"{name}: SHA-256 {got} != frozen {want}")
    return problems


def points_plausible(points: int, chunks: int, papers: int) -> bool:
    return 0.98 * chunks <= points <= chunks + papers + 0.01 * chunks


def qdrant_points(collection: str, url: str) -> int:
    with urllib.request.urlopen(f"{url}/collections/{collection}", timeout=10) as resp:
        return int(json.load(resp)["result"]["points_count"])


def db_counts(db_path: str) -> tuple[int, int]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return (
            con.execute("SELECT count(*) FROM chunks").fetchone()[0],
            con.execute("SELECT count(*) FROM papers").fetchone()[0],
        )
    finally:
        con.close()


def ablate_question(question: str, title: str) -> str:
    title_tokens = set(_TOKEN.findall(title.lower()))
    kept = []
    for word in question.split():
        tokens = _TOKEN.findall(word.lower())
        if (
            tokens
            and all(t in title_tokens for t in tokens)
            and word.lower().strip(".,;:()?") not in STOP
        ):
            continue
        kept.append(word)
    return " ".join(kept)


def ablate_ground_truth(gt: dict) -> dict:
    out, omitted = [], defaultdict(int)
    for item in gt["ground_truth"]:
        if item["tests"] != "answerable":
            omitted["not answerable"] += 1
        elif item["dimension"] in SKIP_DIMENSIONS or not item.get("source_paper_title"):
            omitted["no document name to remove"] += 1
        else:
            text = ablate_question(item["question_text"], item["source_paper_title"])
            if len(text.split()) < MIN_WORDS:
                omitted["fewer than 4 words left"] += 1
            else:
                out.append(
                    {**item, "question_text": text, "original_question_text": item["question_text"]}
                )
    meta = {**gt["_metadata"], "title_ablated": True, "n": len(out), "omitted": dict(omitted)}
    return {"_metadata": meta, "ground_truth": out}


def split_report(gt: dict, report: dict, field: str) -> dict[str, dict]:
    value_of = {i["question_id"]: i.get(field) for i in gt["ground_truth"]}
    groups: dict[str, list] = defaultdict(list)
    for row in report["questions"]:
        groups[str(value_of[row["question_id"]])].append(row)
    return {v: {**report, "questions": rows} for v, rows in sorted(groups.items())}


def wilson_halfwidth(n: int, p: float = 0.5, z: float = 1.96) -> float:
    if n == 0:
        return float("nan")
    return z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)


def wilson_table(gt: dict) -> list[tuple[str, int, int, float]]:
    rows: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for item in gt["ground_truth"]:
        if item["tests"] == "answerable":
            rows[item["dimension"]][0] += 1
            rows[item["dimension"]][1] += bool(item.get("gold_block_id"))
    return [(d, n, s, wilson_halfwidth(s)) for d, (n, s) in sorted(rows.items())]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-hash")
    p.add_argument("hashes", type=Path)
    p.add_argument("names", nargs="+")
    p = sub.add_parser("check-points")
    p.add_argument("--collection", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--url", default="http://localhost:6333")
    p = sub.add_parser("ablate")
    p.add_argument("gt", type=Path)
    p.add_argument("out", type=Path)
    p = sub.add_parser("split")
    p.add_argument("--field", required=True)
    p.add_argument("gt", type=Path)
    p.add_argument("report", type=Path)
    p.add_argument("out_dir", type=Path)
    p = sub.add_parser("wilson")
    p.add_argument("gt", type=Path)
    args = ap.parse_args(argv)

    if args.cmd == "check-hash":
        problems = check_hashes(args.hashes, args.names)
        print("\n".join(problems) if problems else f"hash check OK ({len(args.names)} fixtures)")
        return 1 if problems else 0
    if args.cmd == "check-points":
        chunks, papers = db_counts(args.db)
        points = qdrant_points(args.collection, args.url)
        ok = points_plausible(points, chunks, papers)
        print(
            f"collection {args.collection}: {points} points; db {args.db}: {chunks} chunks, "
            f"{papers} papers -> {'plausible' if ok else 'IMPLAUSIBLE: wrong corpus?'}"
        )
        return 0 if ok else 1
    if args.cmd == "ablate":
        out = ablate_ground_truth(json.loads(args.gt.read_text()))
        out["_metadata"]["title_ablated_from_sha256"] = sha256_of(args.gt)
        args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False))
        print(f"{args.out}: {out['_metadata']['n']} items, omitted {out['_metadata']['omitted']}")
        return 0
    if args.cmd == "split":
        args.out_dir.mkdir(parents=True, exist_ok=True)
        gt, report = json.loads(args.gt.read_text()), json.loads(args.report.read_text())
        for value, sub_report in split_report(gt, report, args.field).items():
            path = args.out_dir / f"{args.report.stem}.{args.field}-{value}.json"
            path.write_text(json.dumps(sub_report))
            print(f"{path}: {len(sub_report['questions'])} questions")
        return 0
    print(f"{'dimension':20} {'n_ans':>5} {'n_passage':>9} {'hw95@p=.5':>9}")
    for d, n, s, hw in wilson_table(json.loads(args.gt.read_text())):
        print(f"{d:20} {n:>5} {s:>9} {hw:>9.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
