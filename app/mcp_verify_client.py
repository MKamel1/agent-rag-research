"""T-DOC33 — a real MCP client for `app.serve`, speaking the actual MCP stdio protocol (the
official `mcp` SDK's `ClientSession`/`stdio_client`), not calling `McpServer`'s Python methods
in-process the way `rag/test_composition_e2e.py` and the T-EVAL harness do. This is the tool
M5's exit bar ("an agent answers a factual question... and you use it") needs someone to have
actually run — see `LESSONS-LEARNED.md`'s T-DOC33 entry for the transcript this produced.

Usage — export RAG_DB_PATH/RAG_BLOB_DIR (same env vars `app/ingest.py`/`app/parse_phase.py` read)
to point at real production data before running, same as any other real run against that data;
unset falls back to `build_mcp_server`'s own cwd-relative defaults (`"papers.db"`/`"blobs"`):

    RAG_DB_PATH=/path/to/papers.db RAG_BLOB_DIR=/path/to/blobs \
        python -m app.mcp_verify_client "your factual query" [--k N]

Spawns `python -m app.serve` as a real child process over stdio, calls `semantic_search`, then
calls `get_span` on the top hit's anchor to prove the citation resolves back to real stored text
— the full query -> citation round trip, over the wire.
"""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _run(query: str, k: int) -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app.serve"], cwd=_REPO_ROOT, env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("connected -- server advertises tools:", [t.name for t in tools.tools])

            print(f"\n>>> calling semantic_search(query={query!r}, k={k})")
            result = await session.call_tool("semantic_search", {"query": query, "k": k})
            if result.isError:
                raise RuntimeError(f"semantic_search tool call failed: {result.content[0].text}")
            payload = json.loads(result.content[0].text)
            print(json.dumps(payload, indent=2)[:4000])

            if not payload["results"]:
                print("\nNO RESULTS -- nothing to verify against.")
                return

            top = payload["results"][0]
            anchor = top["anchor"]
            print(f"\n>>> calling get_span(anchor) for top hit (paper_id={anchor['paper_id']!r}, "
                  f"block_id={anchor['block_id']!r})")
            span_result = await session.call_tool("get_span", {"anchor": anchor})
            span_text = span_result.content[0].text
            print(f"\nresolved span ({len(span_text)} chars):\n{span_text[:2000]}")


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else (
        "how long does DML with dummies take to compute for one dataset"
    )
    k = 10
    if "--k" in sys.argv:
        k = int(sys.argv[sys.argv.index("--k") + 1])
    asyncio.run(_run(query, k))


if __name__ == "__main__":
    main()
