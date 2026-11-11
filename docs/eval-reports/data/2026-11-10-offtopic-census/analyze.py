import glob, json, math, statistics, collections

BASE = "/home/omar/ai-projects/research-system-rag/docs/eval-reports/data/2026-11-10-offtopic-census/"
CORPUS = 12385

rows = [json.loads(l) for l in open(BASE + "sample.jsonl")]
labels = {}
for path in sorted(glob.glob(BASE + "labels_part_*.txt")):
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        idx, label, reason = line.split("|", 2)
        labels[int(idx)] = (label, reason)
assert len(labels) == len(rows) == 400, (len(labels), len(rows))

out_rows = []
for i, r in enumerate(rows):
    label, reason = labels[i]
    out_rows.append({
        "paper_id": r["paper_id"],
        "label": label,
        "reason": reason,
        "abstract_missing": not (r["abstract"] or "").strip(),
    })
with open(BASE + "labels.jsonl", "w") as f:
    for o in out_rows:
        f.write(json.dumps(o) + "\n")

def wilson(k, n, z=1.959964):
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half

n = len(rows)
counts = collections.Counter(o["label"] for o in out_rows)
lo, hi = wilson(counts["off"], n)
extrap = counts["off"] / n * CORPUS
extrap_lo, extrap_hi = lo * CORPUS, hi * CORPUS

def primary(cj):
    try:
        cats = json.loads(cj) if isinstance(cj, str) else cj
        return cats[0] if cats else "(none)"
    except (ValueError, TypeError, IndexError):
        return "(unparsed)"

def year(pub):
    return str(pub)[:4] if pub else "(none)"

by_cat = collections.defaultdict(collections.Counter)
by_year = collections.defaultdict(collections.Counter)
for r, o in zip(rows, out_rows):
    by_cat[primary(r["categories_json"])][o["label"]] += 1
    by_year[year(r["published"])][o["label"]] += 1

scores = collections.defaultdict(list)
nulls = collections.Counter()
for r, o in zip(rows, out_rows):
    if r["relevance_score"] is None:
        nulls[o["label"]] += 1
    else:
        scores[o["label"]].append(float(r["relevance_score"]))

off_rows = [(r, o) for r, o in zip(rows, out_rows) if o["label"] == "off"]
empty_abs = sum(1 for o in out_rows if o["abstract_missing"])

L = []
L.append("# Off-topic census: causal-methods corpus sample\n")
L.append(f"Sample: 400 rows, doc_type='paper', seed 20261110. Corpus size {CORPUS:,}.")
L.append("Labels are judged from title + abstract (first 400 chars) only; they are a single-reviewer LLM judgement, not a validated gold standard.\n")
L.append("## Label counts\n")
L.append("| Label | Count | Share |\n|---|---|---|")
for lab in ["on", "borderline", "off"]:
    L.append(f"| {lab} | {counts[lab]} | {counts[lab]/n*100:.1f}% |")
L.append(f"\n**Off share:** {counts['off']/n*100:.1f}% (95% Wilson CI {lo*100:.1f}% to {hi*100:.1f}%)\n")
L.append(f"**Extrapolated off-topic papers in corpus of {CORPUS:,}:** {extrap:,.0f} (95% CI {extrap_lo:,.0f} to {extrap_hi:,.0f}), sampling error only.\n")
L.append("## Label by primary arXiv category\n")
L.append("| Primary category | on | borderline | off | total |\n|---|---|---|---|---|")
for cat, c in sorted(by_cat.items(), key=lambda kv: -sum(kv[1].values())):
    L.append(f"| {cat} | {c['on']} | {c['borderline']} | {c['off']} | {sum(c.values())} |")
L.append("\n## Label by publication year\n")
L.append("| Year | on | borderline | off | total |\n|---|---|---|---|---|")
for y in sorted(by_year):
    c = by_year[y]
    L.append(f"| {y} | {c['on']} | {c['borderline']} | {c['off']} | {sum(c.values())} |")
L.append("\n## relevance_score by label\n")
L.append("| Label | n (non-NULL) | mean | median | NULL count |\n|---|---|---|---|---|")
for lab in ["on", "borderline", "off"]:
    s = scores[lab]
    mean = f"{statistics.mean(s):.3f}" if s else "n/a"
    med = f"{statistics.median(s):.3f}" if s else "n/a"
    L.append(f"| {lab} | {len(s)} | {mean} | {med} | {nulls[lab]} |")
tot_null = sum(nulls.values())
L.append(f"\nTotal NULL relevance_score in sample: {tot_null} of {n}.\n")
L.append("## 20 clearly off-topic examples (first 20 off rows in sample order)\n")
for r, o in off_rows[:20]:
    L.append(f"- {r['paper_id']}: {r['title']} ({o['reason']})")
L.append(f"\n## Empty abstracts\n\nSampled rows with empty abstract: {empty_abs} of {n}.\n")
open(BASE + "report.md", "w").write("\n".join(L) + "\n")
print("\n".join(L))

notes = """
## Caveats and findings

- Labels come from title + abstract only, by one reviewer (the agent), with no second-rater check; borderline cases (53) are where label noise concentrates. Off share could move several points under a different rater or a stricter "borderline" cut.
- The Wilson CI covers sampling error from n=400 only, not labelling error.
- Strong recency skew: 100 of the 154 off-topic sampled papers are dated 2026 (71% of the 140 sampled 2026 papers). Whether this reflects a bulk ingest of unrelated cs.LG/cs.CV/cs.AI content is worth checking directly against the DB before any cleanup.
- relevance_score separates the labels only partially (median 0.42 on vs 0.26 off, with substantial overlap). It has no NULLs in this sample, so it is usable as a ranking signal but not a reliable hard filter without a validated threshold.
- Top 5 primary categories among off-topic papers: cs.LG (25), cs.CV (23), cs.AI (10), cs.CL (10), cs.RO (7) (cs.SE also 7).
"""
with open(BASE + "report.md", "a") as f:
    f.write(notes)
