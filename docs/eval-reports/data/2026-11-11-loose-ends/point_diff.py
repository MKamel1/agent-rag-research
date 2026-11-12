"""Read-only: diff Qdrant points (payload-only scroll) against DB chunks/summaries ids.
usage: point_diff.py <collection> <papers.db>"""
import json, sqlite3, sys, urllib.request, collections
coll, db = sys.argv[1], sys.argv[2]
def post(path, body):
    r = urllib.request.Request(f"http://localhost:6333/collections/{coll}/{path}", json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r))["result"]
pts, off = {}, None  # ext_id -> (kind, paper_id)
dup = collections.Counter()
while True:
    res = post("points/scroll", {"limit": 1000, "offset": off, "with_payload": ["_ext_id", "kind", "paper_id", "section_path"], "with_vector": False})
    for p in res["points"]:
        pl = p["payload"]; dup[pl.get("_ext_id")] += 1
        pts[pl.get("_ext_id")] = (pl.get("kind"), pl.get("paper_id"), pl.get("section_path"))
    off = res["next_page_offset"]
    if off is None: break
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
chunks = {r[0]: r[1] for r in con.execute("select chunk_id,paper_id from chunks")}
sums = {r[0]: r[1] for r in con.execute("select summary_id,paper_id from summaries")}
papers = {r[0] for r in con.execute("select paper_id from papers")}
print("points", sum(dup.values()), "distinct ext_id", len(pts), "dup ext_ids", sum(1 for v in dup.values() if v > 1))
print("kinds", collections.Counter(v[0] for v in pts.values()))
print("db chunks", len(chunks), "db summaries", len(sums), "db papers", len(papers))
print("summaries with ':ch' ids", sum(1 for s in sums if ":summary:ch" in s))
pc = {k for k, v in pts.items() if v[0] == "chunk"}; ps = {k for k, v in pts.items() if v[0] != "chunk"}
print("chunk pts not in DB chunks", len(pc - chunks.keys()), "DB chunks w/o pt", len(chunks.keys() - pc))
print("summary pts not in DB summaries", len(ps - sums.keys()), "DB summaries w/o pt", len(sums.keys() - ps))
ex = [(k, pts[k]) for k in (pc - chunks.keys()) | (ps - sums.keys())]
print("extra point paper_ids in papers table:", sum(1 for _, v in ex if v[1] in papers), "of", len(ex))
print("extra by kind", collections.Counter(v[0] for _, v in ex), "distinct papers", len({v[1] for _, v in ex}))
for k, v in sorted(ex, key=lambda x: str(x))[:15]: print("  extra", k, v)
print("points whose paper_id not in papers:", sum(1 for v in pts.values() if v[1] not in papers))
