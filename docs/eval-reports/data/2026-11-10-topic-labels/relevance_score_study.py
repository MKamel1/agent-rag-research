# ruff: noqa: E501, E731
"""EV-3: is papers.relevance_score a focus signal? Joins topic_labels.tsv to relevance_score (read-only);
reports NULLs, per-label distribution, rank-sum AUROC (on vs off, borderline excluded), threshold table
0.10-0.70, breakdown by year and primary category, top-15 categories among off-topic papers.
PRE-REGISTERED CRITERION: AUROC >= 0.85 -> usable query-time filter (propose thresholds);
0.70-0.85 -> ranking signal only; < 0.70 -> not usable.
Run: conda run -n agent-rag-research python relevance_score_study.py
"""
import csv
import json
import sqlite3
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
DB = "/home/omar/ai-projects/research-system-rag-data/papers.db"


def auroc(pos, neg):
    """P(score_pos > score_neg) + 0.5 P(tie), via the Mann-Whitney rank-sum formula with mid-ranks."""
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    ranks, i = [0.0] * len(allv), 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        i = j + 1
    r_pos = sum(r for r, (_, y) in zip(ranks, allv) if y)
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def deciles(v):
    s = sorted(v)
    return [s[min(len(s) - 1, int(len(s) * q / 10))] for q in range(1, 10)]


def main():
    labels = {r[0]: r[1] for r in csv.reader(open(HERE / "topic_labels.tsv"), delimiter="\t", quoting=csv.QUOTE_NONE)}
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = []
    for pid, pub, cats, rs in db.execute("select paper_id, published, categories_json, relevance_score from papers"):
        if pid in labels:
            rows.append((pid, labels[pid], pub[:4], (json.loads(cats) or ["?"])[0], rs))
    print(f"labelled papers joined: {len(rows)} of {len(labels)}; NULL relevance_score: {sum(r[4] is None for r in rows)}")
    rows = [r for r in rows if r[4] is not None]
    by = defaultdict(list)
    for r in rows:
        by[r[1]].append(r[4])
    print("\nPer-label distribution of relevance_score")
    print("label       n    mean  median  | deciles d1..d9")
    for k in ("on", "borderline", "off"):
        v = by[k]
        print(f"{k:10s} {len(v):5d} {st.mean(v):.3f} {st.median(v):.3f}  | " + " ".join(f"{x:.3f}" for x in deciles(v)))
    print(f"\nAUROC on vs off (borderline excluded): {auroc(by['on'], by['off']):.4f}")
    print(f"AUROC on vs (borderline+off), for reference: {auroc(by['on'], by['off'] + by['borderline']):.4f}")
    print(f"AUROC on vs borderline, for reference: {auroc(by['on'], by['borderline']):.4f}")
    print("\nThreshold table: remove papers with score < t")
    print("  t     off removed   on wrongly removed   borderline removed")
    for i in range(0, 13):
        t = 0.10 + 0.05 * i
        f = lambda v: sum(x < t for x in v) / len(v)
        print(f" {t:.2f}    {f(by['off']):.3f}          {f(by['on']):.3f}              {f(by['borderline']):.3f}")
    print("\nBy publication year (n on / n off, mean score on / off, AUROC)")
    yr = defaultdict(lambda: defaultdict(list))
    for r in rows:
        yr[r[2]][r[1]].append(r[4])
    for y in sorted(yr):
        d = yr[y]
        if len(d["on"]) >= 20 and len(d["off"]) >= 20:
            print(f" {y}: {len(d['on']):4d}/{len(d['off']):4d}  {st.mean(d['on']):.3f}/{st.mean(d['off']):.3f}  AUROC {auroc(d['on'], d['off']):.3f}  off share {len(d['off'])/sum(len(x) for x in d.values()):.2f}")
        else:
            print(f" {y}: {len(d['on']):4d}/{len(d['off']):4d}  (too few for a stable AUROC)  off share {len(d['off'])/sum(len(x) for x in d.values()):.2f}")
    print("\nTop 15 primary arXiv categories among off-topic papers (count, mean score, share of category that is off)")
    cat = defaultdict(lambda: defaultdict(list))
    for r in rows:
        cat[r[3]][r[1]].append(r[4])
    offc = Counter({c: len(d["off"]) for c, d in cat.items()})
    for c, n in offc.most_common(15):
        tot = sum(len(x) for x in cat[c].values())
        print(f" {c:18s} {n:5d}  mean off score {st.mean(cat[c]['off']):.3f}  off share of category {n/tot:.2f}")
    print("\nWithin-category AUROC (categories with >=40 on and >=40 off)")
    for c, d in sorted(cat.items(), key=lambda kv: -len(kv[1]["off"])):
        if len(d["on"]) >= 40 and len(d["off"]) >= 40:
            print(f" {c:18s} on {len(d['on']):4d} off {len(d['off']):4d} AUROC {auroc(d['on'], d['off']):.3f}")


if __name__ == "__main__":
    main()
