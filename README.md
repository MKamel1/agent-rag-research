# agent-rag-research

Personal AI Research Knowledge System — **V0** is a plain grounded RAG cache over causal-methods arXiv
papers (causal ML, causal inference, causal discovery, treatment-effect estimation, causal
representation learning, causal LLM/agent setups), now also handling books and drop-in PDFs from other
sources: ingest → parse → chunk → embed → retrieve → return grounded passages + summaries + citations
over MCP, at ~0 API cost. A local web dashboard (`app.dashboard.server`) observes and controls ingestion
runs over Tailscale. The pipeline isn't tied to one corpus — pointing it at a second data directory (its
own `config.yaml`) runs a second, independent corpus; a Waymo AV-safety corpus exists today this way.

Start at [`AGENTS.md`](AGENTS.md) (or [`CLAUDE.md`](CLAUDE.md), same content) — it indexes every doc in
this repo and tells you where to find your task if you're an agent picking up work here, whether that's
Claude Code, a local LLM under OpenCode, or another tool. For current system state — what's shipped,
what's open — see [`docs/PROJECT-STATUS.md`](docs/PROJECT-STATUS.md).
