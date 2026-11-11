# ruff: noqa: E501, E731
"""EV-2: compare audit_labels.tsv (blind, independent) with the Haiku labels in topic_labels.tsv.
Confusion matrix, raw agreement, Cohen's kappa (3-way) and binary off-vs-not-off agreement, each also
re-weighted from the stratified sample (100 per Haiku label) to corpus Haiku-label proportions;
lists every on<->off disagreement; corrected corpus off-topic share.
Criterion (pre-registered in audit_sample.py): kappa >= 0.70 AND binary agreement >= 0.92 -> accept.
Run: conda run -n agent-rag-research python audit_score.py
"""
import csv
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
DB = "/home/omar/ai-projects/research-system-rag-data/papers.db"
L = ["on", "borderline", "off"]


def read(p):
    return {r[0]: r[1:] for r in csv.reader(open(HERE / p), delimiter="\t", quoting=csv.QUOTE_NONE)}


def kappa(w):
    """w[(h, m)] = weight of cell (Haiku label h, mine m)."""
    tot = sum(w.values())
    po = sum(v for (h, m), v in w.items() if h == m) / tot
    ph = {k: sum(v for (h, _), v in w.items() if h == k) / tot for k in L}
    pm = {k: sum(v for (_, m), v in w.items() if m == k) / tot for k in L}
    pe = sum(ph[k] * pm[k] for k in L)
    return po, (po - pe) / (1 - pe)


def boot(pairs, corp, n=2000):
    """Bootstrap within each Haiku stratum -> CIs for weighted kappa / binary agreement / off share."""
    import random
    rng = random.Random(1)
    by = {k: [p for p in pairs if p[0] == k] for k in L}
    res = []
    for _ in range(n):
        w = Counter()
        for k in L:
            s = [rng.choice(by[k]) for _ in by[k]]
            for p in s:
                w[p] += corp[k] / len(s)
        _, kap = kappa(w)
        bin_ = sum(v for (h, m), v in w.items() if (h == "off") == (m == "off")) / sum(w.values())
        off = sum(v for (h, m), v in w.items() if m == "off") / sum(w.values())
        res.append((kap, bin_, off))
    q = lambda i: [sorted(r[i] for r in res)[int(n * f)] for f in (0.025, 0.975)]
    return q(0), q(1), q(2)


def main():
    hai, mine = read("topic_labels.tsv"), read("audit_labels.tsv")
    mine.pop("paper_id")  # header row
    corp = Counter(v[0] for v in hai.values())
    pairs = [(hai[p][0], m[0]) for p, m in mine.items()]
    cm = Counter(pairs)
    print("Confusion (rows Haiku, cols mine), unweighted sample n=%d" % len(pairs))
    print("%-11s" % "", *["%10s" % m for m in L], "   row n")
    for h in L:
        print("%-11s" % h, *["%10d" % cm[(h, m)] for m in L], "%8d" % sum(cm[(h, m)] for m in L))
    n = len(pairs)
    # unweighted (sample is 1/3 each)
    po_u, k_u = kappa(Counter(pairs))
    bin_u = sum(v for (h, m), v in cm.items() if (h == "off") == (m == "off")) / n
    # re-weighted to corpus proportions: each sample paper in stratum h carries corp[h]/100
    w = Counter({(h, m): cm[(h, m)] / 100 * corp[h] for h in L for m in L})
    po_w, k_w = kappa(w)
    bin_w = sum(v for (h, m), v in w.items() if (h == "off") == (m == "off")) / sum(w.values())
    ci_k, ci_b, ci_o = boot(pairs, corp)
    print(f"\nUnweighted (balanced sample): raw agree {po_u:.3f}  kappa {k_u:.3f}  binary off/not-off agree {bin_u:.3f}")
    print(f"Corpus-weighted:              raw agree {po_w:.3f}  kappa {k_w:.3f} (95% CI {ci_k[0]:.3f}-{ci_k[1]:.3f})  binary agree {bin_w:.3f} (95% CI {ci_b[0]:.3f}-{ci_b[1]:.3f})")
    print("\nPer-band agreement (share of Haiku-band papers I labelled the same): " +
          ", ".join(f"{h} {cm[(h,h)]/100:.2f}" for h in L))
    for h in L:
        print(f"  Haiku {h:10s} -> binary off-vs-not-off agree {sum(cm[(h,m)] for m in L if (h=='off')==(m=='off'))/100:.2f}")
    print("\nMy-label composition inside each Haiku band: ", {h: {m: cm[(h, m)] for m in L} for h in L})
    # corrected off share: sum over Haiku bands of corpus share * P(I say off | Haiku band)
    N = sum(corp.values())
    est = sum(corp[h] / N * cm[(h, "off")] / 100 for h in L)
    print(f"\nHaiku off share {corp['off']/N:.3f}; audit-corrected off share {est:.3f} (95% bootstrap CI {ci_o[0]:.3f}-{ci_o[1]:.3f})")
    # costly disagreements
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    bad = [(p, hai[p][0], m[0]) for p, m in mine.items() if {hai[p][0], m[0]} == {"on", "off"}]
    print(f"\non<->off disagreements: {len(bad)}")
    for p, h, m in bad:
        t = db.execute("select title from papers where paper_id=?", (p,)).fetchone()[0]
        print(f"- {p} | {t[:90]} | Haiku={h} ({hai[p][1]}) | audit={m}")
    print("\nPosition of every disagreement with off<->borderline or on<->borderline:", {k: v for k, v in cm.items() if k[0] != k[1]})


if __name__ == "__main__":
    main()
