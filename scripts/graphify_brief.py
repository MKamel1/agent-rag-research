"""Answer-shaped brief over the graphify knowledge graph (no LLM, deterministic).

Turns a natural-language question into a token-budgeted mini-brief: scored seed
nodes, their strongest evidence edges with citations, and suggested follow-ups.
Complements `graphify query` (raw traversal) with an answer-shaped default for
cold-start agents.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

STOP = set(
    "a an and are as at be by for from has have how i in is it its of on or that the "
    "this to was we what when where which who why will with".split()
)


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if t not in STOP and len(t) > 1]


def score_nodes(question: str, nodes: list[dict]) -> list[tuple[float, dict]]:
    terms = _terms(question)
    tf = Counter(terms)
    out = []
    for n in nodes:
        hay = " ".join(
            str(n.get(k, "")) for k in ("id", "label", "file_type", "purpose", "doc_class")
        ).lower()
        hits = [t for t in terms if t in hay]
        if not hits:
            continue
        s = sum(
            math.log(1 + tf[t]) * (2 if t in str(n.get("label", "")).lower() else 1)
            for t in hits
        )
        boost = 0.0
        if n.get("doc_class") == "AUTHORITATIVE":
            boost += 1.5
        if n.get("ticket_status"):
            boost += 1.0
        if n.get("foundation_frozen"):
            boost += 0.5
        out.append((s + boost, n))
    out.sort(key=lambda x: -x[0])
    return out


def build_brief(question: str, g: dict, budget: int = 800) -> dict:
    nodes = g.get("nodes", [])
    links = g.get("links", [])
    by_id = {n["id"]: n for n in nodes}
    scored = score_nodes(question, nodes)[:6]
    seeds = [n for _, n in scored]
    seed_ids = {n["id"] for n in seeds}

    edge_score: list[tuple[float, dict]] = []
    for e in links:
        s, t = e.get("source"), e.get("target")
        touch = sum(1 for x in (s, t) if x in seed_ids)
        if not touch:
            continue
        conf = e.get("confidence_score") or (1.0 if e.get("confidence") == "EXTRACTED" else 0.5)
        edge_score.append((touch * 2 + float(conf), e))
    edge_score.sort(key=lambda x: -x[0])

    def _src(n_or_e: dict) -> str:
        raw = str(n_or_e.get("source_file", ""))
        return raw.replace("enrichment:enrichment/", "graph:")

    lines: list[str] = [f"# Brief: {question}", ""]
    used = sum(len(ln) for ln in lines) // 4 + 40
    lines.append("## Key nodes")
    for _, n in scored:
        loc = n.get("source_location")
        base = _src(n)
        tail = f" {loc}" if loc else ""
        cite = f" [{base}{tail}]"
        kind = n.get("file_type", "?")
        cls = f", {n['doc_class']}" if n.get("doc_class") else ""
        row = f"- **{n['label']}** ({kind}{cls}){cite}"
        if used + len(row) // 4 > budget:
            break
        lines.append(row)
        used += len(row) // 4

    lines.append("")
    lines.append("## Evidence edges")
    shown = 0
    seen_pairs: set[frozenset] = set()
    for _, e in edge_score:
        s, t = e.get("source"), e.get("target")
        pair = frozenset((s or "", t or ""))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        sn, tn = by_id.get(s, {}), by_id.get(t, {})
        row = (
            f"- {sn.get('label', s)} —[{e.get('relation')}"
            f"/{e.get('confidence')}→ {tn.get('label', t)}"
            f"  ({_src(e)})"
        )
        if used + len(row) // 4 > budget:
            break
        lines.append(row)
        used += len(row) // 4
        shown += 1
        if shown >= 12:
            break

    lines.append("")
    lines.append("## Caveats")
    lines.append("- Deterministic retrieval; verify citations before acting on them.")
    return {"brief": "\n".join(lines), "tokens_est": used}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--graph-dir", default="graphify-out")
    parser.add_argument("--budget", type=int, default=800)
    args = parser.parse_args(argv)

    graph_path = Path(args.graph_dir).resolve() / "graph.json"
    if not graph_path.exists():
        print(f"error: no graph at {graph_path}", file=sys.stderr)
        return 2
    g = json.loads(graph_path.read_text(encoding="utf-8"))
    print(build_brief(args.question, g, args.budget)["brief"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
