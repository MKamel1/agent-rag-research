"""EV-2: seeded stratified sample (100 per Haiku label, random.seed(20261110)) from topic_labels.tsv,
joined read-only to papers (title, abstract[:600], categories_json); writes audit_sample.tsv WITHOUT the Haiku label.

PRE-REGISTERED CRITERION (EV-2, written before any labelling):
  Cohen's kappa (three-way, my labels vs Haiku) >= 0.70 AND binary off-vs-not-off agreement >= 0.92
  => labels ACCEPTED as-is. Otherwise report which band fails and recommend relabelling that band.
Run: conda run -n agent-rag-research python audit_sample.py
"""
import csv, random, sqlite3
from pathlib import Path

DB = "/home/omar/ai-projects/research-system-rag-data/papers.db"
HERE = Path(__file__).parent


def main():
    by_label = {}
    for pid, label, _ in csv.reader(open(HERE / "topic_labels.tsv"), delimiter="\t", quoting=csv.QUOTE_NONE):
        by_label.setdefault(label, []).append(pid)
    random.seed(20261110)
    ids = []
    for label in ("on", "borderline", "off"):
        ids += random.sample(sorted(by_label[label]), 100)
    random.shuffle(ids)  # order carries no stratum information
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    flat = lambda s: " ".join(s.split())
    with open(HERE / "audit_sample.tsv", "w") as f:
        f.write("paper_id\ttitle\tcategories\tabstract600\n")
        for pid in ids:
            t, a, c = db.execute("select title, abstract, categories_json from papers where paper_id=?", (pid,)).fetchone()
            f.write(f"{pid}\t{flat(t)}\t{flat(c)}\t{flat(a)[:600]}\n")


if __name__ == "__main__":
    main()
