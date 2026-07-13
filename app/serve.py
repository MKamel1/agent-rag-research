"""`python -m app.serve` — the real McpServer composition root.

# ponytail: no transport loop yet (no MCP stdio/HTTP server started) — this builds the wired
# McpServer object; wiring correctness is proven by rag/test_composition_e2e.py calling its tools
# directly in-process. Add a real MCP transport loop when a client needs to connect to it.
"""

from app.assembly import build_mcp_server
from rag.config import load_config

if __name__ == "__main__":
    cfg = load_config()
    server = build_mcp_server(cfg)
    print(f"McpServer wired: {server}")
