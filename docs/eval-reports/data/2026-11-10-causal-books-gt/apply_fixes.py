"""Apply crossverify verdicts to the three author item files (standard library only)."""
import json

DATE = "2026-11-10"
AUTHORS = ["author-H/items.json", "author-I/items.json", "author-J/items.json"]

with open("crossverify/verdicts.json", encoding="utf-8") as f:
    verdicts = {v["question_id"]: v for v in json.load(f)}

# Pre-run check: every "fix" verdict must mention a chapter title, so none is skipped silently.
for qid, v in verdicts.items():
    if v["verdict"] == "fix":
        text = (v.get("suggested_fix") or "") + " " + (v.get("reason") or "")
        if not ("gold_chapter_title" in text.lower() or "chapter" in text.lower()):
            print("UNMATCHED FIX (not applied):", qid, json.dumps(v, ensure_ascii=False))

for path in AUTHORS:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    killed, chapter_deleted, alt_added = [], [], []
    kept = []
    for item in data["ground_truth"]:
        qid = item["question_id"]
        v = verdicts.get(qid)
        if v is None:
            print("WARNING no verdict for", qid)
            kept.append(item)
            continue
        if v["verdict"] == "kill":
            killed.append(qid)
            continue
        if v["verdict"] == "fix":
            text = (v.get("suggested_fix") or "") + " " + (v.get("reason") or "")
            if ("gold_chapter_title" in text.lower() or "chapter" in text.lower()) and "gold_chapter_title" in item:
                del item["gold_chapter_title"]
                chapter_deleted.append(qid)
        alts = v.get("alternative_gold_chunk_ids") or []
        if alts:
            item["alternative_gold_chunk_ids"] = alts
            alt_added.append(qid)
        kept.append(item)
    data["ground_truth"] = kept
    data["_metadata"]["crossverify_applied"] = {
        "date": DATE,
        "killed": killed,
        "chapter_title_deleted": chapter_deleted,
        "alternative_chunks_added": alt_added,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print(path)
    print("  killed", len(killed), killed)
    print("  chapter_title_deleted", len(chapter_deleted), chapter_deleted)
    print("  alternative_chunks_added", len(alt_added), alt_added)
