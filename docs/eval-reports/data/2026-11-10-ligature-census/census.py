"""Ligature-loss census over the research-system RAG corpora (read-only).

Standard library only. Opens each papers.db with mode=ro and streams the chunks table.
Writes results.json next to this file and prints a per-corpus summary.
"""

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

CORPORA = {
    "main": "/home/omar/ai-projects/research-system-rag-data/papers.db",
    "waymo": "/home/omar/ai-projects/research-system-rag/waymo/data/papers.db",
    "standards": "/home/omar/ai-projects/research-system-rag-standards/data/papers.db",
    "motional": "/home/omar/ai-projects/research-system-rag-motional/data/papers.db",
    "waabi": "/home/omar/ai-projects/research-system-rag-waabi/data/papers.db",
}

# Broken (ligature-dropped) forms only. Each is checked against the correct spelling it
# must NOT match (noted in comments). Matching is case-insensitive.
BROKEN_PATTERNS = [
    # e-ff-ect family (ff dropped to f)
    r"efects?",                       # effect(s) ; not "effect" (e-f-f)
    r"efect(?:ive|ively|iveness|ed|ing)",  # effective, effectively ; "efect" never a word
    r"eficient(?:ly)?",               # efficient ; correct has "ff"
    r"eficienc(?:y|ies)",             # efficiency
    r"effcien[a-z]*",                 # efficient with ffi->ff
    r"suficient(?:ly)?",              # sufficient
    r"suficienc(?:y|ies)",
    r"afect(?:s|ed|ing|ion|ions|ive)?",  # affect ; correct has "ff"
    r"ofsets?",                       # offset ; correct has "ff"
    r"coefcient[a-z]*",               # coefficient (ffi->f)
    r"coeficients?",                  # coefficient (ffi->fi)
    r"diferen[a-z]*",                 # difference, different ; correct "diff"
    r"dificult[a-z]*",                # difficult ; correct "diff"
    # f-i ligature dropped
    r"signifcan[a-z]*",               # significant, significance
    r"specifc[a-z]*",                 # specific, specifically
    r"specifed",                      # specified
    r"identifc[a-z]*",                # identification, identifcation
    r"identifed",                     # identified
    r"classifc[a-z]*",                # classification
    r"defnit[a-z]*",                  # definition, definite ; correct has "fi"
    r"defne[ds]?",                    # define, defined, defines
    r"defned",                        # defined
    r"frst",                          # first
    r"fnd(?:s|ing)?",                 # find, finds, finding ; correct has "fi"
    r"fnal(?:ly)?",                   # final, finally
    r"fnanc[a-z]*",                   # financial
    r"fgures?",                       # figure(s)
    r"fxed",                          # fixed
    r"benefts?",                      # benefit(s)
    r"confdenc[a-z]*",                # confidence
    r"satisfed",                      # satisfied
    r"verifed",                       # verified
    r"modifed",                       # modified
    r"quantifed",                     # quantified
    r"fexib[a-z]*",                   # flexible ; correct "fl"
    # f-l ligature dropped
    r"fows?",                         # flow(s) ; correct "fl"
    r"fuent(?:ly)?",                  # fluent
    r"workfows?",                     # workflow(s)
    r"confict(?:s|ed|ing)?",          # conflict(s) ; correct "fl"
    r"refect(?:s|ed|ing|ion|ions|ive)?",  # reflect ; correct "fl". Not "refectory"
    r"infuenc[a-z]*",                 # influence ; correct "fl"
]

BROKEN_RE = re.compile(
    r"\b(?:" + "|".join(BROKEN_PATTERNS) + r")\b", re.IGNORECASE
)
LIGATURE_RE = re.compile("[ﬀ-ﬄ]")
MIN_CHUNKS_FOR_WORST = 5
TOP_TOKENS = 15
WORST_DOCS = 10


def census(name: str, path: str) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        titles = dict(con.execute("SELECT paper_id, title FROM papers"))
        total_chunks = 0
        affected_chunks = 0
        ligature_chunks = 0
        token_counts: Counter = Counter()
        per_doc_total: Counter = Counter()
        per_doc_affected: Counter = Counter()

        cur = con.execute("SELECT paper_id, text FROM chunks")
        for paper_id, text in cur:  # streamed row by row
            total_chunks += 1
            per_doc_total[paper_id] += 1
            text = text or ""
            hits = BROKEN_RE.findall(text)
            if hits:
                affected_chunks += 1
                per_doc_affected[paper_id] += 1
                token_counts.update(h.lower() for h in hits)
            if LIGATURE_RE.search(text):
                ligature_chunks += 1
    finally:
        con.close()

    total_docs = len(per_doc_total)
    docs_affected = 0
    docs_10pct = 0
    rows = []
    for pid, n_total in per_doc_total.items():
        n_aff = per_doc_affected.get(pid, 0)
        if n_aff:
            docs_affected += 1
        if n_total and n_aff / n_total >= 0.10:
            docs_10pct += 1
        rows.append((pid, n_aff, n_total))

    worst_pool = [r for r in rows if r[1] > 0 and r[2] >= MIN_CHUNKS_FOR_WORST]
    worst_pool.sort(key=lambda r: (-(r[1] / r[2]), -r[1]))
    worst = [
        {
            "paper_id": pid,
            "title": titles.get(pid),
            "affected_chunks": a,
            "total_chunks": t,
            "pct": round(100 * a / t, 1),
        }
        for pid, a, t in worst_pool[:WORST_DOCS]
    ]

    return {
        "corpus": name,
        "total_chunks": total_chunks,
        "total_docs": total_docs,
        "affected_chunks": affected_chunks,
        "affected_chunks_pct": round(100 * affected_chunks / max(total_chunks, 1), 2),
        "docs_with_affected": docs_affected,
        "docs_with_affected_pct": round(100 * docs_affected / max(total_docs, 1), 2),
        "docs_ge10pct_affected": docs_10pct,
        "docs_ge10pct_affected_pct": round(100 * docs_10pct / max(total_docs, 1), 2),
        "ligature_char_chunks": ligature_chunks,
        "top_tokens": token_counts.most_common(TOP_TOKENS),
        "token_counts_all": dict(token_counts),
        "worst_docs": worst,
        "worst_doc_rule": f"fraction affected, docs with >= {MIN_CHUNKS_FOR_WORST} chunks",
    }


def main() -> None:
    results = {"patterns": BROKEN_PATTERNS, "corpora": {}}
    overall: Counter = Counter()
    for name, path in CORPORA.items():
        r = census(name, path)
        overall.update(r.pop("token_counts_all"))
        results["corpora"][name] = r
        print(
            f"{name}: chunks={r['total_chunks']} "
            f"affected_chunks={r['affected_chunks']} ({r['affected_chunks_pct']}%) "
            f"docs={r['total_docs']} docs_affected={r['docs_with_affected']} "
            f"({r['docs_with_affected_pct']}%) docs>=10%={r['docs_ge10pct_affected']} "
            f"({r['docs_ge10pct_affected_pct']}%) ligature_chunks={r['ligature_char_chunks']}"
        )
        print("  top:", ", ".join(f"{t}={c}" for t, c in r["top_tokens"][:5]))
    results["overall_top_tokens"] = overall.most_common(15)
    print("overall top:", ", ".join(f"{t}={c}" for t, c in overall.most_common(5)))
    (OUT_DIR / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
