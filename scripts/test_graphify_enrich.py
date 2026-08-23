from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.graphify_enrich import (
    assign_communities,
    enrich,
    parse_backlog,
    parse_codeowners,
    parse_doc_classes,
    parse_entry_points,
)

STATUS_MD = """# PROJECT-STATUS
## 2. How to actually run it
| Module | Key flags | Purpose |
|---|---|---|
| `app.build_corpus` | `--target N` | Supervisor loop |
| `app.ghost` | `--x` | Not in graph |

## 7. Doc map
| Doc | Class | Notes |
|---|---|---|
| `AGENTS.md` | AUTHORITATIVE | Entry index |
| `docs/RUNBOOK.md` | REFERENCE | Bring-up |
"""

BACKLOG_MD = """# Backlog
| id | item | status | notes |
|---|---|---|---|
| D-0 | fix a thing | **DONE** | PR #206. sha `abc1234def` |
| T-9 | open work | **OPEN** | nothing yet |
| not-a-ticket row | x | y | z |
"""

CODEOWNERS = "# comment\n/contracts/          @MKamel1\n/fixtures/           @MKamel1\n"

BASE_GRAPH = {
    "directed": False,
    "multigraph": False,
    "nodes": [
        {"id": "agents", "label": "AGENTS.md", "file_type": "document",
         "source_file": "/r/AGENTS.md", "community": 1},
        {"id": "app_build_corpus", "label": "build_corpus.py", "file_type": "code",
         "source_file": "/r/app/build_corpus.py", "community": 2},
        {"id": "contracts_types", "label": "types.py", "file_type": "code",
         "source_file": "/r/contracts/types.py"},
        {"id": "rag_test_chunker", "label": "test_chunker.py", "file_type": "code",
         "source_file": "/r/rag/test_chunker.py"},
        {"id": "rag_chunker", "label": "chunker.py", "file_type": "code",
         "source_file": "/r/rag/chunker.py"},
        {"id": "contracts_vector_index_searchfilters", "label": "SearchFilters",
         "file_type": "code", "source_file": "/r/contracts/vector_index.py"},
    ],
    "links": [],
}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "contracts").mkdir()
    (tmp_path / "rag" / "fakes").mkdir(parents=True)
    (tmp_path / "app").mkdir()
    (tmp_path / ".github").mkdir()
    (tmp_path / "docs" / "PROJECT-STATUS.md").write_text(STATUS_MD, encoding="utf-8")
    (tmp_path / "docs" / "BACKLOG.md").write_text(BACKLOG_MD, encoding="utf-8")
    (tmp_path / ".github" / "CODEOWNERS").write_text(CODEOWNERS, encoding="utf-8")
    (tmp_path / "contracts" / "vector_index.py").write_text(
        "class SearchFilters:\n  pass\nclass Ghost:\n  pass\n", encoding="utf-8"
    )
    (tmp_path / "rag" / "fakes" / "fake_searchfilters.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def graph_file(repo: Path) -> Path:
    gf = repo / "graph.json"
    gf.write_text(json.dumps(BASE_GRAPH), encoding="utf-8")
    return gf


def fake_rig(repo: Path) -> dict:
    return {"tests": [{"file": "rag/test_chunker.py", "node_id_hint": "rag_test_chunker",
                       "covers_modules": ["rag.chunker", "rag.nothere"]}]}


def test_parse_doc_classes() -> None:
    got = dict(parse_doc_classes(STATUS_MD))
    assert got["AGENTS.md"] == "AUTHORITATIVE"
    assert got["docs/RUNBOOK.md"] == "REFERENCE"


def test_parse_entry_points_skips_non_app() -> None:
    rows = parse_entry_points(STATUS_MD)
    assert [r[0] for r in rows] == ["app.build_corpus", "app.ghost"]


def test_parse_backlog_rows() -> None:
    tickets = {t["id"]: t for t in parse_backlog(BACKLOG_MD)}
    assert tickets["D-0"]["status"] == "DONE"
    assert tickets["D-0"]["shas"] == ["abc1234def"]
    assert tickets["T-9"]["status"] == "OPEN"
    assert len(tickets) == 2


def test_parse_codeowners() -> None:
    assert parse_codeowners(CODEOWNERS) == ["/contracts", "/fixtures"]


def test_enrich_full_pass(repo: Path, graph_file: Path) -> None:
    summary = enrich(repo, graph_file, None, rig_collect=fake_rig)
    g = json.loads(graph_file.read_text(encoding="utf-8"))
    idx = {n["id"]: n for n in g["nodes"]}

    assert idx["agents"]["doc_class"] == "AUTHORITATIVE"
    entry = idx["entry_app_build_corpus"]
    assert entry["source_file"].startswith("enrichment:")
    assert any(
        e["source"] == "entry_app_build_corpus" and e["target"] == "app_build_corpus"
        for e in g["links"]
    )
    assert any(e["target"] == "entry_app_ghost" for e in g["links"]) is False
    assert summary["skipped"].get("entry_missing_module") == 1

    assert idx["contracts_types"].get("foundation_frozen") is True
    assert summary["frozen_flagged"] >= 1

    ticket = idx["ticket_d0"]
    assert ticket["ticket_status"] == "DONE"
    covers = [e for e in g["links"] if e["relation"] == "covers"]
    assert covers and covers[0]["target"] == "rag_chunker"

    seams = [
        e
        for e in g["links"]
        if e["relation"] == "implements" and "enrichment:" in e["source_file"]
    ]
    assert seams and seams[0]["target"] == "contracts_vector_index_searchfilters"

    traps = [n for n in g["nodes"] if n["id"].startswith("trap_")]
    assert len(traps) == 5
    assert all(
        n.get("community") is not None
        for n in g["nodes"]
        if str(n.get("source_file", "")).startswith("enrichment:")
    )

    assert summary["added_nodes"] > 8


def test_enrich_idempotent(repo: Path, graph_file: Path) -> None:
    enrich(repo, graph_file, None, rig_collect=fake_rig)
    first = json.loads(graph_file.read_text(encoding="utf-8"))
    n_first, e_first = len(first["nodes"]), len(first["links"])
    enrich(repo, graph_file, None, rig_collect=fake_rig)
    second = json.loads(graph_file.read_text(encoding="utf-8"))
    assert len(second["nodes"]) == n_first
    assert len(second["links"]) == e_first


def test_cochange_edges_added(repo: Path, graph_file: Path) -> None:
    cc = repo / "cc.json"
    cc.write_text(
        json.dumps(
            {"edges": [{"files": ["app/build_corpus.py", "contracts/types.py"],
                        "support": 4}]}
        ),
        encoding="utf-8",
    )
    enrich(repo, graph_file, cc, rig_collect=fake_rig)
    g = json.loads(graph_file.read_text(encoding="utf-8"))
    cc_edges = [e for e in g["links"] if e["relation"] == "co_changed_with"]
    assert len(cc_edges) == 1
    assert cc_edges[0]["confidence_score"] == 0.75


def test_assign_communities_inherits_from_neighbor() -> None:
    nodes = [{"id": "a", "community": 3}, {"id": "b"}]
    idx = {n["id"]: n for n in nodes}
    links = [{"source": "b", "target": "a"}]
    assign_communities([idx["b"]], idx, links)
    assert idx["b"]["community"] == 3
