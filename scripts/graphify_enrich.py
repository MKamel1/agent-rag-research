"""Deterministic enrichment of the graphify knowledge graph from repo sources of truth.

Reads PROJECT-STATUS.md tables, docs/BACKLOG.md, .github/CODEOWNERS, and the RIG
inventory, then patches nodes/edges into graphify-out/graph.json. Every artifact this
module creates carries source_file prefix "enrichment:" so re-runs replace cleanly.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ENRICH_PREFIX = "enrichment:"
TRAPS: list[tuple[str, str, list[str]]] = [
    (
        "trap_cwd_is_data_dir",
        "Trap: ingest-side tools have no --data-dir; shell cwd IS the data dir",
        ["app_ingest", "app_build_corpus", "rag_config"],
    ),
    (
        "trap_conda_env",
        "Trap: use conda env agent-rag-research, never pytorch-env",
        [],
    ),
    (
        "trap_zero_gpu_network_tests",
        "Invariant: unit tests run zero-GPU zero-network by config (CI-enforced)",
        ["contracts_errors", "rag_fakes_fake_gpu_lock"],
    ),
    (
        "trap_gpu_lock",
        "Constraint: one GPU; parse and embed serialize on .gpu.lock",
        ["app_assembly", "rag_embedder"],
    ),
    (
        "trap_mcp_stdio_capture",
        "Trap: MCP client must use conda run --no-capture-output; buffering looks like a hang",
        ["app_serve"],
    ),
]
SEAM_FAKE_OVERRIDES: dict[str, str] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_enrichment(graph: dict) -> tuple[dict, int, int]:
    nodes = [
        n
        for n in graph["nodes"]
        if not str(n.get("source_file", "")).startswith(ENRICH_PREFIX)
    ]
    links = [
        e
        for e in graph.get("links", [])
        if not str(e.get("source_file", "")).startswith(ENRICH_PREFIX)
    ]
    return {"nodes": nodes, "links": links}, len(graph["nodes"]) - len(nodes), len(
        graph.get("links", [])
    ) - len(links)


def _index(nodes: list[dict]) -> dict[str, dict]:
    return {n["id"]: n for n in nodes}


def _mk_node(nid: str, label: str, ftype: str, src: str, loc: str | None = None) -> dict:
    return {
        "id": nid,
        "label": label,
        "file_type": ftype,
        "source_file": ENRICH_PREFIX + src,
        "source_location": loc,
        "source_url": None,
        "captured_at": None,
        "author": None,
        "contributor": None,
    }


def _mk_edge(
    src: str, dst: str, rel: str, sloc: str, conf: str = "EXTRACTED", score: float = 1.0
) -> dict:
    return {
        "source": src,
        "target": dst,
        "relation": rel,
        "confidence": conf,
        "confidence_score": score,
        "source_file": ENRICH_PREFIX + sloc,
        "source_location": sloc,
        "weight": 1.0,
    }


def parse_doc_classes(status_md: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in status_md.splitlines():
        m = re.match(r"^\|\s*`?([^`|]+?)`?\s*\|\s*(AUTHORITATIVE|REFERENCE|HISTORICAL)\s*\|", line)
        if m:
            out.append((m.group(1).strip(), m.group(2)))
    return out


def parse_entry_points(status_md: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for line in status_md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.fullmatch(r"`app\.[a-z_0-9]+`", cells[0]):
            mod = cells[0].strip("`")
            flags = cells[1].replace("`", "")
            purpose = cells[2]
            rows.append((mod, flags, purpose))
    return rows


def parse_backlog(backlog_md: str) -> list[dict]:
    tickets: list[dict] = []
    for line in backlog_md.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        tid = cells[0].strip("`")
        if not re.fullmatch(r"[DTBO]-\d+[a-z]?", tid):
            continue
        status_m = re.search(r"\*\*(OPEN|IN PROGRESS|BLOCKED|READY|DONE)\*\*", cells[2])
        status = status_m.group(1) if status_m else "UNKNOWN"
        note = cells[3] if len(cells) > 3 else ""
        shas = re.findall(r"\b[0-9a-f]{7,40}\b", note)
        prs = re.findall(r"#\d+", note)
        tickets.append({"id": tid, "title": cells[1], "status": status, "shas": shas, "prs": prs})
    return tickets


def parse_codeowners(text: str) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts and parts[0].startswith("/"):
            paths.append(parts[0].rstrip("/"))
    return paths


def ticket_files(repo: Path, shas: list[str], cap: int = 12) -> list[str]:
    files: set[str] = set()
    for sha in shas[:3]:
        try:
            out = subprocess.run(
                ["git", "show", "--name-only", "--format=", sha],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
                timeout=20,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        for ln in out.stdout.splitlines():
            ln = ln.strip()
            if ln:
                files.add(ln)
            if len(files) >= cap:
                break
    return sorted(files)[:cap]


def contract_symbols(contracts_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for py in sorted(contracts_dir.glob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                out[node.name.lower()] = py.stem.lower()
    return out


def seam_edges(graph_idx: dict[str, dict], repo: Path) -> tuple[list[dict], list[dict], Counter]:
    edges: list[dict] = []
    extra: list[dict] = []
    skipped = Counter()
    syms = contract_symbols(repo / "contracts")
    fakes = sorted((repo / "rag" / "fakes").glob("fake_*.py"))
    seen_pairs: set[tuple[str, str]] = set()
    for fake in fakes:
        stem = fake.stem[len("fake_") :]
        contract_stem = syms.get(stem)
        fake_nid = f"rag_fakes_{fake.stem}"
        target = None
        if contract_stem:
            cand = f"contracts_{contract_stem}_{stem}"
            if cand in graph_idx:
                target = cand
        if target is None:
            for nid in graph_idx:
                if nid.startswith("contracts_") and nid.endswith(f"_{stem}"):
                    target = nid
                    break
        if target is None:
            skipped["seam_no_contract"] += 1
            continue
        pair = (fake_nid, target)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        if fake_nid not in graph_idx:
            extra.append(_mk_node(fake_nid, fake.name, "code", str(fake)))
            graph_idx[fake_nid] = extra[-1]
        edges.append(_mk_edge(fake_nid, target, "implements", f"enrichment/seam/{stem}"))
    return edges, extra, skipped


def assign_communities(new_nodes: list[dict], idx: dict[str, dict], links: list[dict]) -> None:
    neighbor: dict[str, int] = {}
    for e in links:
        s, t = e.get("source"), e.get("target")
        cs = idx.get(s, {}).get("community")
        ct = idx.get(t, {}).get("community")
        if isinstance(cs, int) and t is not None:
            neighbor.setdefault(t, cs)
        if isinstance(ct, int) and s is not None:
            neighbor.setdefault(s, ct)
    fallback = 0
    counts = Counter(
        n.get("community") for n in idx.values() if isinstance(n.get("community"), int)
    )
    if counts:
        fallback = counts.most_common(1)[0][0]
    for n in new_nodes:
        if "community" not in n:
            n["community"] = neighbor.get(n["id"], fallback)


def enrich(repo: Path, graph_path: Path, cochange_path: Path | None, rig_collect=None) -> dict:
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph, dropped_nodes, dropped_edges = _strip_enrichment(graph)
    nodes, links = graph["nodes"], graph["links"]
    idx = _index(nodes)
    added_nodes: list[dict] = []
    added_edges: list[dict] = []
    skipped = Counter()
    stats: dict[str, int] = {}

    status_md = (repo / "docs" / "PROJECT-STATUS.md").read_text(encoding="utf-8")

    doc_classes = parse_doc_classes(status_md)
    patched = 0
    for rel, cls in doc_classes:
        rel_clean = rel.strip("`")
        for n in nodes:
            sf = str(n.get("source_file", ""))
            if sf.endswith(rel_clean) and not sf.startswith(ENRICH_PREFIX):
                n["doc_class"] = cls
                patched += 1
                break
        else:
            skipped["doc_class_no_node"] += 1
    stats["doc_class_patched"] = patched

    for mod, flags, purpose in parse_entry_points(status_md):
        nid = f"entry_{mod.replace('.', '_').lower()}"
        if nid in idx:
            skipped["entry_dup"] += 1
            continue
        node = _mk_node(
            nid, f"{mod} (entry point)", "concept", "enrichment/entry_points", flags[:80]
        )
        node["purpose"] = purpose
        added_nodes.append(node)
        idx[nid] = node
        target = mod.replace(".", "_").lower()
        if target in idx:
            added_edges.append(_mk_edge(nid, target, "references", "enrichment/entry_points"))
        else:
            skipped["entry_missing_module"] += 1

    for trap_id, label, targets in TRAPS:
        node = _mk_node(trap_id, label, "rationale", "enrichment/traps")
        added_nodes.append(node)
        idx[trap_id] = node
        for t in targets:
            if t in idx:
                added_edges.append(
                    _mk_edge(trap_id, t, "conceptually_related_to", "enrichment/traps")
                )
            else:
                skipped["trap_missing_target"] += 1

    co_path = repo / ".github" / "CODEOWNERS"
    frozen = 0
    if co_path.exists():
        patterns = parse_codeowners(co_path.read_text(encoding="utf-8"))
        for n in nodes:
            sf = str(n.get("source_file", ""))
            if not sf:
                continue
            rel = sf.replace("\\", "/")
            for pat in patterns:
                p = pat.lstrip("/")
                hit = rel == p or rel.startswith(p + "/")
                hit = hit or (not p.endswith(".py") and f"/{p}" in f"/{rel}")
                if hit:
                    n["foundation_frozen"] = True
                    n["codeowner"] = "@MKamel1"
                    frozen += 1
                    break
    stats["frozen_flagged"] = frozen

    backlog_path = repo / "docs" / "BACKLOG.md"
    if backlog_path.exists():
        for tk in parse_backlog(backlog_path.read_text(encoding="utf-8")):
            tid_l = tk["id"].lower().replace("-", "")
            nid = f"ticket_{tid_l}"
            if nid in idx:
                continue
            node = _mk_node(
                nid,
                f"[{tk['status']}] {tk['id']} — {tk['title']}",
                "document",
                "enrichment/backlog",
                (", ".join(tk["prs"]) or None),
            )
            node["ticket_status"] = tk["status"]
            node["ticket_id"] = tk["id"]
            added_nodes.append(node)
            idx[nid] = node
            touched = ticket_files(repo, tk["shas"])
            if tk["status"] == "DONE" and not touched:
                skipped["ticket_done_no_files"] += 1
            for f in touched:
                target = f[:-3].replace("/", "_").lower()
                if target in idx:
                    added_edges.append(
                        _mk_edge(nid, target, "references", f"enrichment/backlog/{tk['id']}")
                    )
                else:
                    skipped["ticket_file_missing"] += 1

    seam_e, seam_n, s_skip = seam_edges(idx, repo)
    added_edges.extend(seam_e)
    added_nodes.extend(seam_n)
    skipped.update(s_skip)

    if rig_collect is not None:
        inv = rig_collect(repo)
        for t in inv.get("tests", []):
            tnid = t.get("node_id_hint")
            if tnid not in idx:
                skipped["test_node_missing"] += 1
                continue
            for mod in t.get("covers_modules", []):
                mid = mod.replace(".", "_").lower()
                if mid in idx and mid != tnid:
                    added_edges.append(
                        _mk_edge(tnid, mid, "covers", "enrichment/test_map", "EXTRACTED", 1.0)
                    )

    if cochange_path is not None and cochange_path.exists():
        cc = json.loads(cochange_path.read_text(encoding="utf-8"))
        for e in cc.get("edges", []):
            a, b = e.get("files", [None, None])[:2]
            ia = str(a)[:-3].replace("/", "_").lower() if a else None
            ib = str(b)[:-3].replace("/", "_").lower() if b else None
            if ia in idx and ib in idx:
                added_edges.append(
                    _mk_edge(ia, ib, "co_changed_with", "enrichment/cochange", "INFERRED", 0.75)
                )
            else:
                skipped["cochange_missing_endpoint"] += 1

    assign_communities(added_nodes, idx, links)
    nodes.extend(added_nodes)
    links.extend(added_edges)

    out = {"nodes": nodes, "links": links}
    stats.update(
        {
            "added_nodes": len(added_nodes),
            "added_edges": len(added_edges),
            "dropped_prev_nodes": dropped_nodes,
            "dropped_prev_edges": dropped_edges,
        }
    )
    summary = {"generated_at": _now(), **stats, "skipped": dict(skipped)}
    tmp = graph_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    shutil.move(str(tmp), str(graph_path))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--graph-dir", required=True)
    parser.add_argument("--cochange", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    graph_path = Path(args.graph_dir).resolve() / "graph.json"
    if not graph_path.exists():
        print(f"error: no graph at {graph_path}", file=sys.stderr)
        return 2

    def rig_collect(root: Path) -> dict:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from scripts.graphify_rig import collect_inventory

        return collect_inventory(root)

    if args.dry_run:
        print(json.dumps({"dry_run": True, "graph": str(graph_path)}))
        return 0
    cc = Path(args.cochange).resolve() if args.cochange else None
    summary = enrich(repo, graph_path, cc, rig_collect)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
