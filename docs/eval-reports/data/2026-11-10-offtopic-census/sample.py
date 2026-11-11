import json, random, sqlite3

random.seed(20261110)
conn = sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro", uri=True)
rows = conn.execute(
    "SELECT paper_id, title, abstract, categories_json, published, relevance_score "
    "FROM papers WHERE doc_type='paper' ORDER BY paper_id"
).fetchall()
sample = random.sample(rows, 400)
with open("sample.jsonl", "w") as f:
    for pid, title, abstract, cats, pub, score in sample:
        f.write(json.dumps({
            "paper_id": pid,
            "title": title,
            "abstract": (abstract or "")[:400],
            "categories_json": cats,
            "published": pub,
            "relevance_score": score,
        }) + "\n")
print(len(sample))
