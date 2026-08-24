"""T-DOC33 — a real MCP client for `app.serve`, speaking the actual MCP stdio protocol (the
official `mcp` SDK's `ClientSession`/`stdio_client`), not calling `McpServer`'s Python methods
in-process the way `rag/test_composition_e2e.py` and the T-EVAL harness do. This is the tool
M5's exit bar ("an agent answers a factual question... and you use it") needs someone to have
actually run — see `LESSONS-LEARNED.md`'s T-DOC33 entry for the transcript this produced.

Usage:

    python -m app.mcp_verify_client "your factual query" [--k N] [--data-dir DIR]

Spawns `python -m app.serve` as a real child process over stdio (`cwd=_REPO_ROOT`, fixed below).
Without `--data-dir`, the child resolves `config.yaml` from THIS repo's root via `app.serve`'s
plain `load_config()` fallback (T-DOC89 §3 discovery: `RAG_CONFIG` -> `config.yaml` in `_REPO_ROOT`
-> walk up -- an operator with `RAG_CONFIG` set gets that instead of the repo root). With
`--data-dir DIR`, `["--data-dir", DIR]` is appended to the child's argv so it loads that corpus's
own config.yaml instead -- this is how you round-trip a non-default corpus (e.g. waymo/data).

The RAG_DB_PATH/RAG_BLOB_DIR/RAG_COLLECTION env vars this docstring used to tell you to export no
longer do anything -- `app.serve` doesn't read the process environment at all now (CONVENTIONS.md
§3; see its own docstring for the `--data-dir` flag that replaced them). 2026-08-23: this script
used to accept `--data-dir` and silently drop it (raw sys.argv scanning, no parser), reporting
main-corpus results for a Waymo ask; argparse now rejects unknown flags instead of ignoring them.
"""

import argparse
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _run(query: str, k: int, data_dir: str | None) -> None:
    # No explicit `env`: the SDK then spawns the child with its get_default_environment()
    # (PATH/HOME/SHELL/TERM/USER/LOGNAME on POSIX -- verified in mcp/client/stdio's
    # stdio_client). That is sufficient here because the child reads no configuration from the
    # process environment (CONVENTIONS.md §3; config.yaml is resolved from `cwd` below, and
    # RAG_CONFIG intentionally does NOT propagate -- this script's documented contract is to
    # spawn against THIS repo root's config.yaml). The previous explicit pass-through of a copy
    # of the parent environment handed all of it to the child by hand, which check (d) rightly
    # flags as pipeline code plumbing env outside Config (RI-23).
    spawn_args = ["-m", "app.serve"]
    if data_dir is not None:
        spawn_args += ["--data-dir", data_dir]
    params = StdioServerParameters(
        command=sys.executable, args=spawn_args, cwd=_REPO_ROOT,
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
    parser = argparse.ArgumentParser(
        description="Full query->citation MCP round trip against a spawned app.serve.",
    )
    parser.add_argument("query", nargs="?", default=(
        "how long does DML with dummies take to compute for one dataset"
    ))
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--data-dir", default=None,
        help="Corpus directory whose config.yaml the spawned server should load "
             "(e.g. waymo/data). Omit for the repo-root default corpus.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.query, args.k, args.data_dir))


if __name__ == "__main__":
    main()
