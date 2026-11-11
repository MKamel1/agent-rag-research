# ruff: noqa  (one-off data-repair script; dense on purpose)
"""EV-4b mechanical self-check for focus_gt.json (read-only DB). Run from this directory."""
import json, re, sqlite3, statistics, sys
DB = "/home/omar/ai-projects/research-system-rag-data/papers.db"
LAB = "../2026-11-10-topic-labels/topic_labels.tsv"
STEM = {  # collision_term -> regex that a natural inflection must match
    "instrument": r"instrument", "matching": r"match", "interference": r"interfer", "discontinuity": r"discontinu",
    "shock": r"shock", "intervention": r"intervention", "collider": r"collider", "control": r"control",
    "backdoor": r"back-?door", "attribution": r"attribut", "causal attention": r"causal[- ]attention",
    "exposure": r"exposure", "dose": r"dos(e|age)", "selection": r"select", "treatment": r"treatment",
    "mediation": r"mediat", "propensity": r"propensity", "confounding": r"confound",
}
words = lambda s: re.findall(r"[a-z0-9]+", s.lower())
lab = {l.split("\t")[0]: l.split("\t")[1] for l in open(LAB) if l.count("\t") >= 2}
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
items = json.load(open("focus_gt.json"))["ground_truth"]
bad = []
def fail(m): bad.append(m); print("FAIL", m)
def title_run(q, title, n=4):
    qw, tw = words(q), " " + " ".join(words(title)) + " "
    return any(" " + " ".join(qw[i:i + n]) + " " in tw for i in range(len(qw) - n + 1))
terms = {}
for it in items:
    q, d = it["question_text"], it["dimension"]
    if d == "collision":
        t = it["collision_term"]; terms.setdefault(t, []).append(it["question_id"])
        if not re.search(STEM[t], q, re.I): fail(f"{it['question_id']} term {t!r} not in question")
        if it.get("trap_strength") not in ("strong", "moderate", "weak"): fail(f"{it['question_id']} trap_strength")
        if lab.get(it["source_paper_id"]) != "on": fail(f"{it['question_id']} gold not on")
        for p in it["distractor_paper_ids"]:
            if lab.get(p) != "off": fail(f"{it['question_id']} distractor {p} not off")
        if len(it["distractor_paper_ids"]) < 2: fail(f"{it['question_id']} <2 distractors")
    if d == "offtopic-legit":
        if lab.get(it["source_paper_id"]) != "off": fail(f"{it['question_id']} gold not off")
        for p in it.get("lookalike_paper_ids", []):
            if lab.get(p) != "on": fail(f"{it['question_id']} lookalike {p} not on")
    if it.get("source_paper_id"):
        title = con.execute("select title from papers where paper_id=?", (it["source_paper_id"],)).fetchone()[0]
        if title_run(q, title): fail(f"{it['question_id']} shares a 4-word run with title")
        for c in it.get("alternative_gold_chunk_ids", []):
            if not con.execute("select 1 from chunks where chunk_id=?", (c,)).fetchone(): fail(f"{it['question_id']} alt chunk {c} missing")
print("collision terms:", {k: len(v) for k, v in terms.items()}, "distinct", len(terms), "max", max(map(len, terms.values())))
if len(terms) < 12 or max(map(len, terms.values())) > 3: fail("term spread")
from collections import Counter
print("trap_strength:", Counter(i.get("trap_strength") for i in items if i["dimension"] == "collision"))
print("dimensions:", Counter(i["dimension"] for i in items))
L = lambda ds: [len(words(i["question_text"])) for i in items if i["dimension"] in ds]
for name, ds in (("collision", {"collision"}), ("focus-absent", {"focus-absent"}), ("offtopic-legit", {"offtopic-legit"})):
    v = L(ds); print(f"question words {name}: median {statistics.median(v)} range {min(v)}-{max(v)}")
a, c = L({"focus-absent"}), L({"collision"})
if not (min(a) <= max(c) and min(c) <= max(a)) or abs(statistics.median(a) - statistics.median(c)) > 6: fail("length distributions do not overlap")
print("SELFCHECK", "FAILED" if bad else "OK", len(bad), "failures")
sys.exit(1 if bad else 0)
