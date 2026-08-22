"""Query the Waymo corpus over a real MCP stdio session and print passages with their section.

Why this exists rather than `app/mcp_verify_client.py`: that tool has no `--data-dir` passthrough
(its own docstring says so), so it always spawns against the repo-root config and would answer from
the CAUSAL corpus, silently. This one targets `waymo/data`.

The `section` field on every hit is the point. A method named under "Related Work" or
"Introduction" was probably being CITED; a method named under "Methods"/"Analysis" was probably
being USED. Retrieval alone cannot tell those apart -- `Anchor.section_path` can, so it is printed
on every line rather than left for the caller to go fetch.

Scope is Waymo-authored papers BY DEFAULT (the `curated` tier -- an enumerated list taken from
Waymo's own publication index, so it is exact by construction rather than a keyword guess). Widening
to the full corpus requires passing `--all-papers` explicitly. The default is the safe direction: a
caller who forgets a flag gets a narrower, correct answer instead of one silently contaminated with
third-party literature.

    python scripts/ask_waymo_corpus.py "bootstrap resampling" --k 25 [--all-papers] [--json]
"""

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "waymo/data"
PY_BIN = sys.executable


def titles() -> dict[str, str]:
    conn = sqlite3.connect(f"file:{DATA_DIR / 'papers.db'}?mode=ro", uri=True)
    try:
        return dict(conn.execute("select paper_id, title from papers"))
    finally:
        conn.close()


async def ask(query: str, k: int, curated_only: bool) -> list[dict]:
    params = StdioServerParameters(
        command=PY_BIN, args=["-m", "app.serve", "--data-dir", str(DATA_DIR)],
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"}, cwd=str(REPO_ROOT),
    )
    payload: dict = {"query": query, "k": k}
    if curated_only:
        payload["filters"] = {"author_org": "Waymo", "author_org_curated_only": True}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            response = await session.call_tool("semantic_search", payload)
            return json.loads(response.content[0].text)["results"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--k", type=int, default=25)
    parser.add_argument("--all-papers", action="store_true",
                        help="widen beyond Waymo-authored papers to the whole corpus, including "
                             "third-party AV-safety literature. Off by default -- see module docstring.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = asyncio.run(ask(args.query, args.k, curated_only=not args.all_papers))
    scope = "ALL PAPERS (Waymo + third-party)" if args.all_papers else "WAYMO-AUTHORED ONLY"
    name = titles()
    if args.json:
        for r in results:
            r["title"] = name.get(r["anchor"]["paper_id"], "")
        print(json.dumps(results, indent=1))
        return 0
    print(f"scope: {scope}")
    for i, r in enumerate(results, 1):
        anchor = r["anchor"]
        pid = anchor["paper_id"]
        # Title first and in full -- see the note in scripts/enumerate_corpus.py.
        print(f"\n[{i}] {name.get(pid, '')}")
        print(f"    PAPER  : {pid}  p.{anchor['page']}  score={r['score']:.3f}")
        print(f"    SECTION: {anchor['section_path'] or '(front matter / unsectioned)'}")
        print(f"    TEXT   : {' '.join(r['passage_text'].split())[:700]}")
    print(f"\n({len(results)} results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
