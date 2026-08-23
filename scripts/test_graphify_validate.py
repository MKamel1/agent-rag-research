from __future__ import annotations

import json
from pathlib import Path

from scripts.graphify_brief import build_brief, score_nodes
from scripts.graphify_validate import diagnose

GRAPH = {
    "nodes": [
        {"id": "agents", "label": "AGENTS.md project index", "file_type": "document",
         "source_file": "/r/AGENTS.md", "doc_class": "AUTHORITATIVE", "community": 1},
        {"id": "docs_backlog", "label": "BACKLOG open work queue", "file_type": "document",
         "source_file": "/r/docs/BACKLOG.md", "doc_class": "AUTHORITATIVE", "community": 1},
        {"id": "ticket_t9", "label": "[OPEN] T-9 — open work", "file_type": "document",
         "source_file": "enrichment:backlog", "ticket_status": "OPEN", "community": 1},
        {"id": "contracts_types", "label": "types.py", "file_type": "code",
         "source_file": "/r/contracts/types.py", "foundation_frozen": True, "community": 2},
    ],
    "links": [
        {"source": "agents", "target": "docs_backlog", "relation": "references",
         "confidence": "EXTRACTED", "confidence_score": 1.0, "source_file": "/r/AGENTS.md"},
        {"source": "ticket_t9", "target": "rag_ghost", "relation": "references",
         "confidence": "EXTRACTED", "confidence_score": 1.0, "source_file": "enrichment:"},
        {"source": "agents", "target": "docs_backlog", "relation": "references",
         "confidence": "EXTRACTED", "confidence_score": 1.0, "source_file": "/r/AGENTS.md"},
    ],
}


def test_score_nodes_ranks_authority_and_tickets_first() -> None:
    scored = score_nodes("where is the open work queue documented", GRAPH["nodes"])
    ids = [n["id"] for _, n in scored]
    assert ids[0] in {"docs_backlog", "ticket_t9"}
    assert scored and scored[0][0] > 0


def test_score_nodes_empty_on_no_overlap() -> None:
    assert score_nodes("zzz qqq", GRAPH["nodes"]) == []


def test_brief_shape_and_budget() -> None:
    out = build_brief("where is the open work queue", GRAPH, budget=200)
    b = out["brief"]
    assert b.startswith("# Brief:")
    assert "## Key nodes" in b and "## Evidence edges" in b
    assert out["tokens_est"] <= 200 + 60
    assert "AGENTS.md" in b or "BACKLOG" in b


def test_brief_cites_source_files() -> None:
    out = build_brief("open work queue", GRAPH)
    assert "/r/AGENTS.md" in out["brief"]


def test_diagnose_flags_dangling(tmp_path: Path) -> None:
    gp = tmp_path / "graph.json"
    gp.write_text(json.dumps(GRAPH), encoding="utf-8")
    d = diagnose(gp)
    assert d["dangling_edges"] == 1
    assert d["healthy"] is False
    assert (tmp_path / ".needs_update.json").exists() is False


def test_diagnose_clean_graph_healthy(tmp_path: Path) -> None:
    g = json.loads(json.dumps(GRAPH))
    g["links"] = [e for e in g["links"] if e["target"] != "rag_ghost"]
    for n in g["nodes"]:
        n.setdefault("source_file", "x")
        if str(n.get("source_file")).startswith("enrichment:"):
            n["community"] = 1
    gp = tmp_path / "graph.json"
    gp.write_text(json.dumps(g), encoding="utf-8")
    d = diagnose(gp)
    assert d["healthy"] is True
