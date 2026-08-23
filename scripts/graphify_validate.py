"""Post-build health gate for the graphify knowledge graph.

Checks graph.json for silent corruption classes that matter to agents:
dangling edge endpoints and stale enrichment assumptions. Writes a machine-
readable flag (graphify-out/.needs_update.json) when problems are found so the
post-commit hook can surface staleness instead of hiding it. Never mutates the
graph — reporting only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def diagnose(graph_path: Path) -> dict:
    g = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = g.get("nodes", [])
    links = g.get("links", [])
    ids = {n["id"] for n in nodes}
    dangling = [
        {"source": e.get("source"), "target": e.get("target"), "relation": e.get("relation")}
        for e in links
        if e.get("source") not in ids or e.get("target") not in ids
    ]
    rel_counts = Counter(e.get("relation") for e in links)
    enrich_nodes = sum(
        1 for n in nodes if str(n.get("source_file", "")).startswith("enrichment:")
    )
    unlabeled = sorted(
        n["id"]
        for n in nodes
        if str(n.get("source_file", "")).startswith("enrichment:")
        and "community" not in n
    )
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "nodes": len(nodes),
        "edges": len(links),
        "enrichment_nodes": enrich_nodes,
        "dangling_edges": len(dangling),
        "dangling_sample": dangling[:10],
        "top_relations": dict(rel_counts.most_common(12)),
        "unlabeled_enrichment_nodes": len(unlabeled),
        "healthy": not dangling and not unlabeled,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-dir", required=True)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)

    graph_dir = Path(args.graph_dir).resolve()
    graph_path = graph_dir / "graph.json"
    if not graph_path.exists():
        print(f"error: no graph at {graph_path}", file=sys.stderr)
        return 2
    report = diagnose(graph_path)

    flag = graph_dir / ".needs_update.json"
    if report["healthy"]:
        if flag.exists():
            flag.unlink()
    else:
        flag.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"nodes={report['nodes']} edges={report['edges']} "
        f"dangling={report['dangling_edges']} "
        f"unlabeled_enrichment={report['unlabeled_enrichment_nodes']} "
        f"healthy={report['healthy']}"
    )
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
