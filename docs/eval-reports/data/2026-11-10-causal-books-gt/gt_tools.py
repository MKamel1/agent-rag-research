"""Read-only helper + mechanical verifier for authoring the standards-corpus ground truth.

Zero GPU, zero network: everything is a read-only SQLite query against the corpus DB.

  python gt_tools.py docs                         # every document: id, type, chunk count, title
  python gt_tools.py sections PAPER_ID            # section paths with chunk counts, in order
  python gt_tools.py chunks PAPER_ID [--section S] [--grep REGEX] [--limit N]
  python gt_tools.py scan REGEX [--paper PAPER_ID] # corpus-wide hit counts per document + samples
  python gt_tools.py verify ITEMS.json [--write]  # ground + check items; --write fills the ids in
"""
import argparse
import json
import re
import sqlite3
import sys

DB = "/home/omar/ai-projects/research-system-rag-data/papers.db"
MIN_BODY = 60        # chars of chunk body (after the title/section header) -- rejects heading stubs
MAX_COPIED_RUN = 6   # a question may not reuse a word run this long from its own excerpt

STRATA = {
    "clause-lookup", "definition-lookup", "table-requirement", "authority", "edition",
    "cross-document", "book-passage", "guidance-factual", "absent", "partial-absent",
    "paper-passage", "numeric-result", "method-detail", "equation-context",
}


def db():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def norm(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def ground(con, paper_id, excerpt):
    """Chunk(s) of `paper_id` containing `excerpt` (whitespace/case-insensitive), best first."""
    needle = norm(excerpt)
    hits = []
    for chunk_id, text, anchor in con.execute(
        "select chunk_id, text, anchor_json from chunks where paper_id=?", (paper_id,)
    ):
        if needle in norm(text):
            body = text.split("\n\n", 1)[-1].strip()  # chunk text = header, blank line, body
            hits.append((chunk_id, len(body), json.loads(anchor)["block_id"]))
    return hits


def excerpt_block(con, paper_id, excerpt):
    needle = norm(excerpt)
    for block_id, text in con.execute(
        "select block_id, text from blocks where paper_id=? order by idx", (paper_id,)
    ):
        if needle in norm(text):
            return block_id
    return None  # excerpt spans blocks or the chunker normalized it -- not an error


def check_passage(con, item_id, paper_id, excerpt, errors):
    """Grounds one (paper, excerpt) pair. Returns the id fields, or None after logging why not."""
    if not con.execute("select 1 from papers where paper_id=?", (paper_id,)).fetchone():
        errors.append(f"{item_id}: unknown paper_id {paper_id}")
        return None
    if len(words(excerpt)) < 8:
        errors.append(f"{item_id}: excerpt shorter than 8 words")
        return None
    hits = ground(con, paper_id, excerpt)
    if not hits:
        errors.append(f"{item_id}: excerpt is not verbatim in any chunk of {paper_id}")
        return None
    chunk_id, length, anchor_block = hits[0]
    if length < MIN_BODY:
        errors.append(f"{item_id}: gold chunk {chunk_id} is a stub ({length}-char body)")
        return None
    return {
        "gold_chunk_id": chunk_id,
        "gold_block_id": anchor_block,  # what app/retrieval_eval.py scores against today
        "excerpt_block_id": excerpt_block(con, paper_id, excerpt),  # survives a rechunk
        "n_chunks_containing_excerpt": len(hits),
    }


def copied_run(question, excerpt):
    q, e = words(question), " " + " ".join(words(excerpt)) + " "
    return any(
        " " + " ".join(q[i:i + MAX_COPIED_RUN]) + " " in e
        for i in range(len(q) - MAX_COPIED_RUN + 1)
    )


def verify(path, write):
    con = db()
    data = json.load(open(path))
    items = data["ground_truth"]
    errors, seen = [], set()
    for it in items:
        qid = it.get("question_id", "<no id>")
        if qid in seen:
            errors.append(f"{qid}: duplicate question_id")
        seen.add(qid)
        for field in ("question_text", "tests", "dimension", "difficulty", "question_type",
                      "answer_text"):
            if not it.get(field):
                errors.append(f"{qid}: missing {field}")
        if it.get("dimension") not in STRATA:
            errors.append(f"{qid}: dimension {it.get('dimension')!r} not in {sorted(STRATA)}")
        question = it.get("question_text", "")

        if it.get("tests") == "absent":
            if it.get("source_paper_id") or it.get("supporting_passages"):
                errors.append(f"{qid}: absent item must carry no gold")
            evidence = it.get("absence_evidence") or []
            if len(evidence) < 2:
                errors.append(f"{qid}: absent item needs >=2 absence_evidence scans")
            for ev in evidence:  # re-run every recorded scan; the recorded count must reproduce
                scope = "where paper_id=?" if ev.get("paper_id") else ""
                args = (ev["paper_id"],) if ev.get("paper_id") else ()
                rx = re.compile(ev["pattern"], re.I)
                n = sum(1 for (t,) in con.execute(f"select text from chunks {scope}", args)
                        if rx.search(t))
                if n != ev.get("hits"):
                    errors.append(f"{qid}: scan {ev['pattern']!r} recorded {ev.get('hits')} hits, "
                                  f"reproduces as {n}")
            continue

        passages = it.get("supporting_passages")
        if passages:  # cross-document item: no top-level source_paper_id, by loader convention
            if it.get("source_paper_id"):
                errors.append(f"{qid}: cross-document item must not set source_paper_id")
            if len({p["paper_id"] for p in passages}) < 2:
                errors.append(f"{qid}: cross-document item needs >=2 distinct documents")
            for p in passages:
                ids = check_passage(con, qid, p["paper_id"], p["passage_excerpt"], errors)
                if ids and write:
                    p.update(ids)
                if copied_run(question, p["passage_excerpt"]):
                    errors.append(f"{qid}: question copies a {MAX_COPIED_RUN}-word run from an excerpt")
        else:
            ids = check_passage(con, qid, it.get("source_paper_id"),
                                it.get("passage_excerpt", ""), errors)
            if ids and write:
                it.update(ids)
            if copied_run(question, it.get("passage_excerpt", "")):
                errors.append(f"{qid}: question copies a {MAX_COPIED_RUN}-word run from its excerpt")

    if write and not errors:
        json.dump(data, open(path, "w"), indent=1, ensure_ascii=False)
    for e in errors:
        print("FAIL", e)
    print(f"{len(items)} items, {len(errors)} failures" + (" -- ids written" if write and not errors else ""))
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("docs")
    p = sub.add_parser("sections"); p.add_argument("paper_id")
    p = sub.add_parser("chunks"); p.add_argument("paper_id")
    p.add_argument("--section"); p.add_argument("--grep"); p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("scan"); p.add_argument("pattern"); p.add_argument("--paper")
    p = sub.add_parser("verify"); p.add_argument("path"); p.add_argument("--write", action="store_true")
    a = ap.parse_args()
    con = db()

    if a.cmd == "docs":
        for r in con.execute("select p.paper_id, doc_type, (select count(*) from chunks k where "
                             "k.paper_id=p.paper_id), title from papers p order by title"):
            print(*r, sep="\t")
    elif a.cmd == "sections":
        for path, n in con.execute("select section_path, count(*) from chunks where paper_id=? "
                                   "group by 1 order by min(rowid)", (a.paper_id,)):
            print(f"{n:4d}  {path}")
    elif a.cmd == "chunks":
        rx = re.compile(a.grep, re.I) if a.grep else None
        shown = 0
        for chunk_id, path, text in con.execute(
            "select chunk_id, section_path, text from chunks where paper_id=? order by rowid",
            (a.paper_id,),
        ):
            if a.section and a.section.lower() not in path.lower():
                continue
            if rx and not rx.search(text):
                continue
            print(f"=== {chunk_id} | {path} | {len(text)} chars\n{text}\n")
            shown += 1
            if shown >= a.limit:
                break
    elif a.cmd == "scan":
        rx = re.compile(a.pattern, re.I)
        scope, args = ("where paper_id=?", (a.paper,)) if a.paper else ("", ())
        per_doc, samples, total = {}, [], 0
        for pid, text in con.execute(f"select paper_id, text from chunks {scope}", args):
            m = rx.search(text)
            if m:
                total += 1
                per_doc[pid] = per_doc.get(pid, 0) + 1
                if len(samples) < 5:
                    samples.append((pid, text[max(0, m.start() - 120):m.end() + 120].replace("\n", " ")))
        print(f"hits (chunks): {total}")
        for pid, n in sorted(per_doc.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {n:4d}  {pid}")
        for pid, s in samples:
            print(f"  ~ {pid}: ...{s}...")
    elif a.cmd == "verify":
        sys.exit(verify(a.path, a.write))


if __name__ == "__main__":
    main()
