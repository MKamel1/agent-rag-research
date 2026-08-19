# agent-rag-research

Personal AI Research Knowledge System. **V0** is a plain grounded RAG cache over causal-methods arXiv
papers (causal inference, causal ML, causal discovery, treatment-effect estimation, causal
representation learning, causal LLM/agent setups), since extended to books and drop-in PDFs from other
sources: **ingest → parse → chunk → embed → retrieve → return grounded passages + summaries + citations
over MCP**, at ~0 API cost. Everything runs on local models; nothing calls a paid API.

An agent (Claude Code, Claude Desktop, anything speaking MCP) asks a question and gets back passages it
can quote, each anchored to a page and block in a real PDF. No claims, no reconciliation, no evidence
tiers beyond a pinned `"A"` — those are V1–V3 (`CONTEXT.md`).

The pipeline isn't tied to one corpus: a second data directory with its own `config.yaml` is a second,
independent corpus. A Waymo AV-safety corpus exists today this way.

**Doc index: [`AGENTS.md`](AGENTS.md)** (or [`CLAUDE.md`](CLAUDE.md), same content) — it tells you which
doc is authoritative for what. **Current state — what's shipped, what's open, live corpus numbers:**
[`docs/PROJECT-STATUS.md`](docs/PROJECT-STATUS.md). This README deliberately states no numbers and no
ticket statuses; those live in one place so they can't drift.

## What's in the box

| Layer | Where | What it does |
|---|---|---|
| Harvest | `rag/harvester.py` | arXiv search over `focus_area_queries`; `app/prefetch_pdfs.py` keeps `pdf_cache/` filled |
| Parse | `rag/parser.py` | MinerU (GPU) → blocks with page + bbox anchors; GROBID resolves references |
| Chunk | `rag/chunker.py` | Retrieval-sized child chunks, parent blocks returned for context |
| Summarize | `rag/summarizer.py`, `rag/book_summarizer.py` | Per-paper and per-chapter summaries via Ollama |
| Embed | `rag/embedder.py` | Qwen3-Embedding-4B over TEI; dense + sparse IDF |
| Store | `rag/document_store.py`, `rag/vector_index.py` | SQLite is the source of truth, Qdrant is a rebuildable projection |
| Retrieve | `rag/retriever.py`, `rag/reranker.py` | Hybrid search + BGE reranker |
| Serve | `rag/mcp_server.py`, `app/serve.py` | MCP tools: `semantic_search`, `search_papers`, `get_paper`, `get_span` |
| Operate | `app/dashboard/` | Local web dashboard: run control, live telemetry, consistency checks, reachable over Tailscale |

Module boundaries, invariants, and extensibility seams: [`ARCHITECTURE.md`](ARCHITECTURE.md) (M1–M9).
Frozen shapes, IDs, SQLite schema, `Config` fields: [`DATA-CONTRACTS.md`](DATA-CONTRACTS.md).

## Requirements

- NVIDIA GPU (the parse and embed paths are GPU-bound and serialize on one lock, `.gpu.lock`)
- Docker, for four services: Qdrant, TEI embedder, TEI reranker, GROBID
- Ollama running on the host (`ollama serve`) for summarization — deliberately never auto-started
- Conda env `agent-rag-research` (`environment.yml`) — **not** the machine's `pytorch-env`

## Quickstart

```bash
conda env create -f environment.yml && conda activate agent-rag-research

# 1. Point the system at a data directory (its own config.yaml, paths resolved under it).
python -m app.init_config --data-dir "$PWD/../research-system-rag-data" --link

# 2. Bring the services up and check readiness. Auto-starts stopped containers.
python -m app.doctor

# 3. Watch it, from the repo root. http://localhost:8700/ — the token's path is printed, never its value.
scripts/dashboard.sh start

# 4. Build a corpus, from inside the data dir. Runs until `ingest_state` has N papers at stage='done'.
cd ../research-system-rag-data && python -m app.build_corpus --target 1000 --parse-workers 3
```

After a reboot the whole sequence is `nvidia-smi` → `python -m app.doctor` →
`scripts/dashboard.sh start`. Full operator bring-up, Tailscale access, and where the dashboard token
lives: [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

**Trap worth knowing before your first run:** most ingest-side tools have no `--data-dir` flag — **your
shell's cwd is the data dir**. Only `app.init_config`, `app.serve`, `app.dashboard.server`, and
`app.dashboard.verify_numbers` take one. Every entry point with its real flags is tabulated in
`docs/PROJECT-STATUS.md` §2.

Non-arXiv PDFs go in `drop_in/papers/` or `drop_in/books/` and enter via `python -m app.ingest_local`.

## Connecting an MCP client

`app/serve.py` is launched by the client, not by hand:

```json
{
  "command": "conda",
  "args": ["run", "-n", "agent-rag-research", "--no-capture-output", "python", "-m", "app.serve"],
  "env": { "PYTHONPATH": "/home/omar/ai-projects/research-system-rag" }
}
```

`--no-capture-output` is required — MCP's stdio transport *is* stdout, and `conda run` buffers it by
default, which looks identical to a hang. Verify a deploy with `python -m app.doctor --check-mcp`, or do
a full query→citation round trip with `python -m app.mcp_verify_client "some query"`. Why each part
matters, and what happens if `cwd` is wrong: `docs/RUNBOOK.md`.

## Repo layout

```
contracts/   Frozen interfaces + shared types. Foundation-protected — see below.
rag/         Implementations and vendor adapters. One vendor SDK per adapter, never elsewhere.
app/         Entry points (python -m app.*) + the dashboard. app/exp_*.py are throwaway experiments.
migrations/  Numbered SQL, applied idempotently by migrations/migrate.py.
ci/checks/   The mechanical guardrails, with committed negative examples that must fail them.
fixtures/    Golden fixtures + the retrieval eval set.
docs/        Status, backlog, runbooks, design decisions, eval reports.
```

Tests live next to the code they test (`rag/test_chunker.py`, not a `tests/` tree).

## Development

```bash
pytest                                    # zero-GPU, zero-network — sockets are disabled by config
ruff check .
```

Real-adapter tests need live vendor infra and are deselected by default (`-m real_adapter`).

Before pushing, run the actual CI enforcement over your diff — the unit tests are not the same check:

```bash
echo '{}' > /tmp/fake_push_event.json
GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH=/tmp/fake_push_event.json python -m ci.run_enforcement
```

**The guardrails are mechanical, not cultural.** Vendor-import isolation, no `os.getenv` outside the
config loader, no blind `except Exception`, no shared type defined outside `contracts/` — each is a CI
job that blocks merge, and none has a comment-based exemption. The reasoning (the build team is
memoryless AI agents, so a rule in prose is only a suggestion) is [`CONVENTIONS.md`](CONVENTIONS.md) §0 —
read it before writing code.

Paths listed in `.github/CODEOWNERS` are **foundation-protected**: `contracts/`, `rag/config.py`,
`config.example.yaml`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`. A diff touching them
needs explicit human sign-off. If a frozen contract looks wrong, stop and flag it — do not define a
"close enough" local version. Branch naming, PR flow, and the freeze mechanism:
[`GIT-WORKFLOW.md`](GIT-WORKFLOW.md).

## If you're an agent picking up work here

Read [`docs/AGENT-PROCEDURES.md`](docs/AGENT-PROCEDURES.md) §A first — the onboarding checklist,
including why a ticket status is a claim to verify against git, not a fact to act on, and what
documentation obligation your PR carries. Then `docs/PROJECT-STATUS.md` for what exists, and
[`docs/BACKLOG.md`](docs/BACKLOG.md) for what's open.

## License

See [`LICENSE`](LICENSE).
