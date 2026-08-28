#!/usr/bin/env python3
"""Independent Stage-B mechanical checker for W-A4 ground-truth sets (SB-2 cross-verify).

Written from scratch against the ticket's five checks -- does NOT import or call
either author's verify script. Reads papers.db read-only; never writes to it.

Checks, per item / sub-part:
  1. excerpt is a verbatim (whitespace-normalized) substring of the block and/or
     chunk it cites.
  2. gold_block_id resolves in `blocks`; gold_chunk_id (if present) resolves in `chunks`.
  3. every absent sub-part carries >=1 lexical probe with a numeric denominator and a
     stated scope, plus a semantic probe.
  4. probe denominators are arithmetically correct (re-run counts against the DB).
  5. frozen_after_retrieval is True.

Usage:
  python scripts/wa4_crossverify.py <file.json> [--author A|B] [--out report.json]

Exits nonzero if any item fails any check (useful for the Stage-D corruption test).
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "waymo" / "data" / "papers.db"


def norm_ws(s):
    return " ".join(s.split())


def load_items(path):
    d = json.load(open(path))
    return d["items"] if "items" in d else d


def db():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    return con


def block_text(con, block_id):
    row = con.execute("SELECT text FROM blocks WHERE block_id = ?", (block_id,)).fetchone()
    return row[0] if row else None


def chunk_text(con, chunk_id):
    row = con.execute("SELECT text FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
    return row[0] if row else None


def paper_chunk_count(con, paper_id):
    row = con.execute("SELECT COUNT(*) FROM chunks WHERE paper_id = ?", (paper_id,)).fetchone()
    return row[0]


def corpus_chunk_count(con):
    return con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]


def normalize_probes(sub_part):
    """Return list of dicts: {kind: lexical|semantic, query, hits, denominator, scope}
    scope is either 'corpus' or a paper_id string, or None if not determinable."""
    out = []
    log = sub_part.get("absence_probe_log", {})
    # Author-A shape: flat "probes" list with a "table" discriminator.
    if "probes" in log:
        for p in log["probes"]:
            table = p.get("table", "")
            kind = "semantic" if table.startswith("qdrant") else "lexical"
            scope_raw = p.get("scope")
            if scope_raw and scope_raw.startswith("paper:"):
                scope = scope_raw.split("paper:", 1)[1]
            elif kind == "lexical":
                scope = "corpus"
            else:
                scope = None
            out.append({
                "kind": kind, "query": p.get("query"), "hits": p.get("hits"),
                "denominator": p.get("denominator"), "scope": scope,
            })
    # Author-B shape: separate "lexical_probes" list + single "semantic_probe" dict.
    if "lexical_probes" in log:
        for p in log["lexical_probes"]:
            scope = "paper" if p.get("scope") == "paper" else p.get("scope")
            out.append({
                "kind": "lexical", "query": p.get("query"), "hits": p.get("hits"),
                "denominator": p.get("paper_chunk_count"), "scope": scope,
            })
    if "semantic_probe" in log:
        sp = log["semantic_probe"]
        out.append({
            "kind": "semantic", "query": sp.get("query"), "hits": None,
            "denominator": None, "scope": None,
        })
    return out


def check_item(con, item, author_hint):
    aid = item["id"]
    result = {"id": aid, "checks": []}
    ok = True

    frozen = item.get("frozen_after_retrieval")
    if frozen is not True:
        ok = False
        result["checks"].append({"check": "frozen_after_retrieval", "pass": False, "detail": frozen})
    else:
        result["checks"].append({"check": "frozen_after_retrieval", "pass": True})

    item_papers = set(item.get("gold_paper_ids", []))

    for i, sp in enumerate(item["sub_parts"]):
        tag = f"sub_part[{i}]:{sp['status']}"
        if sp["status"] == "supported":
            gr = sp["gold_ref"]
            block_id = gr.get("block_id")
            chunk_id = gr.get("chunk_id")
            excerpt = norm_ws(gr["excerpt"])

            block_id_resolves = False
            block_match = None
            if block_id:
                bt = block_text(con, block_id)
                block_id_resolves = bt is not None
                if bt is not None:
                    block_match = excerpt in norm_ws(bt)
            chunk_id_resolves = None
            chunk_match = None
            if chunk_id:
                ct = chunk_text(con, chunk_id)
                chunk_id_resolves = ct is not None
                if ct is not None:
                    chunk_match = excerpt in norm_ws(ct)

            substring_ok = bool(block_match) or bool(chunk_match)
            if not substring_ok:
                ok = False
            result["checks"].append({
                "check": f"{tag}:excerpt_verbatim_substring", "pass": substring_ok,
                "detail": {
                    "block_id": block_id, "block_id_resolves": block_id_resolves, "block_match": block_match,
                    "chunk_id": chunk_id, "chunk_id_resolves": chunk_id_resolves, "chunk_match": chunk_match,
                },
            })

            if block_id and not block_id_resolves:
                ok = False
                result["checks"].append({"check": f"{tag}:gold_block_id_resolves", "pass": False, "detail": block_id})
            elif block_id:
                result["checks"].append({"check": f"{tag}:gold_block_id_resolves", "pass": True})

            if chunk_id and not chunk_id_resolves:
                ok = False
                result["checks"].append({"check": f"{tag}:gold_chunk_id_resolves", "pass": False, "detail": chunk_id})
            elif chunk_id:
                result["checks"].append({"check": f"{tag}:gold_chunk_id_resolves", "pass": True})

        elif sp["status"] == "absent":
            probes = normalize_probes(sp)
            lexical = [p for p in probes if p["kind"] == "lexical"]
            semantic = [p for p in probes if p["kind"] == "semantic"]

            has_lexical_with_denominator = any(
                isinstance(p["hits"], int) and isinstance(p["denominator"], int) and p["scope"] is not None
                for p in lexical
            )
            has_semantic = len(semantic) >= 1
            struct_ok = has_lexical_with_denominator and has_semantic
            if not struct_ok:
                ok = False
            result["checks"].append({
                "check": f"{tag}:probe_structure", "pass": struct_ok,
                "detail": {"n_lexical": len(lexical), "n_semantic": len(semantic),
                           "has_lexical_with_denominator": has_lexical_with_denominator},
            })

            # Denominator arithmetic re-check.
            denom_results = []
            for p in lexical:
                if p["denominator"] is None:
                    continue
                if p["scope"] == "corpus":
                    actual = corpus_chunk_count(con)
                    pass_ = actual == p["denominator"]
                elif p["scope"] == "paper":
                    # Author-B doesn't name the paper in the probe; use item's single gold paper.
                    if len(item_papers) == 1:
                        actual = paper_chunk_count(con, next(iter(item_papers)))
                        pass_ = actual == p["denominator"]
                    else:
                        actual = None
                        pass_ = None
                else:
                    # Author-A names the paper explicitly in scope.
                    actual = paper_chunk_count(con, p["scope"])
                    pass_ = actual == p["denominator"]
                denom_results.append({
                    "query": p["query"], "scope": p["scope"], "stated": p["denominator"],
                    "actual": actual, "pass": pass_,
                })
            denom_all_ok = all(d["pass"] for d in denom_results if d["pass"] is not None)
            if not denom_all_ok:
                ok = False
            result["checks"].append({
                "check": f"{tag}:denominator_arithmetic", "pass": denom_all_ok, "detail": denom_results,
            })
        else:
            ok = False
            result["checks"].append({"check": f"{tag}:unknown_status", "pass": False, "detail": sp["status"]})

    result["pass"] = ok
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--author", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    items = load_items(args.file)
    con = db()
    results = [check_item(con, it, args.author) for it in items]
    con.close()

    n_pass = sum(1 for r in results if r["pass"])
    n_fail = len(results) - n_pass
    print(f"{args.file}: {n_pass}/{len(results)} PASS, {n_fail} FAIL")
    for r in results:
        if not r["pass"]:
            print(f"  FAIL {r['id']}:")
            for c in r["checks"]:
                if not c["pass"]:
                    print(f"    - {c['check']}: {json.dumps(c.get('detail'))[:300]}")

    if args.out:
        json.dump(results, open(args.out, "w"), indent=2)

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
