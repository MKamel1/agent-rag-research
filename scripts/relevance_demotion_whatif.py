"""RQ-3 offline what-if: how many papers/gold papers fall below each relevance tau (read-only, CPU).

    python scripts/relevance_demotion_whatif.py --db papers.db --labels topic_labels.tsv \
        --gt focus=focus_gt.json --gt papers=papers_passage_gt.json --gt books=causal_books_gt.json

Uses only `papers.relevance_score` (SQLite opened mode=ro), the topic labels and the fixtures; no retrieval.
A paper with a NULL score is never demoted, so it counts as "not below".
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

TAUS = (0.20, 0.25, 0.30, 0.35)


def below_share(papers: list[str], scores: dict[str, float | None], tau: float) -> tuple[int, int]:
    return sum((scores.get(p) is not None) and scores[p] < tau for p in papers), len(papers)


def gold_groups(gt: dict) -> dict[str, list[str]]:
    """Answerable items' gold papers (one entry per item-gold pair), grouped by `dimension|paper_topic`;
    distractor / lookalike papers grouped as `<dimension>:distractors` / `<dimension>:lookalikes`."""
    out: dict[str, list[str]] = defaultdict(list)
    for it in gt["ground_truth"]:
        if it.get("tests") != "answerable":
            continue
        dim = it.get("dimension", "?")
        topic = it.get("paper_topic")
        golds = {it["source_paper_id"], *(it.get("additional_gold_paper_ids") or [])}
        out[f"{dim}|{topic}" if topic else dim] += sorted(golds)
        out[f"{dim}:distractors"] += it.get("distractor_paper_ids") or []
        out[f"{dim}:lookalikes"] += it.get("causal_lookalike_paper_ids") or []
    return {k: v for k, v in out.items() if v}


def render(scores, labels, gts: dict[str, dict]) -> str:
    h = "| " + " | ".join(["group", "n", *[f"< {t:.2f}" for t in TAUS]]) + " |\n|" + "---|" * (len(TAUS) + 2) + "\n"

    def row(name, papers):
        cells = []
        for t in TAUS:
            b, n = below_share(papers, scores, t)
            cells.append(f"{b} ({b / n:.1%})" if n else "n/a")
        return f"| {name} | {len(papers)} | " + " | ".join(cells) + " |\n"

    by_label: dict[str, list[str]] = defaultdict(list)
    for p, lab in labels.items():
        by_label[lab].append(p)
    s = "Corpus papers by topic label (share below tau)\n\n" + h
    s += "".join(row(f"label={lab}", by_label[lab]) for lab in ("off", "borderline", "on"))
    for name, gt in gts.items():
        s += f"\nFixture `{name}`: gold papers (answerable items; counts are item-gold pairs)\n\n" + h
        s += "".join(row(g, ps) for g, ps in sorted(gold_groups(gt).items()))
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--labels", required=True, type=Path)
    ap.add_argument("--gt", action="append", default=[], help="NAME=path/to/gt.json (repeatable)")
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    scores = dict(con.execute("SELECT paper_id, relevance_score FROM papers"))
    con.close()
    labels = {}
    for line in a.labels.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1] in ("on", "borderline", "off"):
            labels[parts[0]] = parts[1]
    gts = {n: json.loads(Path(p).read_text()) for n, p in (g.split("=", 1) for g in a.gt)}
    print(render(scores, labels, gts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
