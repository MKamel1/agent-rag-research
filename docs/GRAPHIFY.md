# Graphify + Obsidian — codebase visualization

A **[Graphify](https://pypi.org/project/graphifyy/)** knowledge graph of this repo, usable two ways:

- **For AI** — an agent (Claude Code, or any tool) navigates the code by *structure* (imports, calls,
  class/function relationships, doc↔code links) via `graphify query/path/explain`, instead of grepping
  and re-reading files. Typically answers a "where/how" question in a few thousand tokens.
- **For humans** — an interactive `graph.html` and a generated **Obsidian vault** (one note per node +
  a `graph.canvas`) you can browse to *see* the module clusters and how the design docs map to the code.

> This is **dev tooling**, not part of the V0–V3 product. It is unrelated to the paper-corpus Obsidian
> view on the product roadmap (see `AGENTS.md`).

Current graph: ~**3,200 nodes / 8,300 edges / ~180 named communities** from the `.py` source + the
design docs. The semantic (doc→code) pass runs **free** through the local `claude` CLI — no API key.

---

## What's tracked vs. what's local

**Tracked in the repo** (this is all you need to reproduce the graph):

| Path | Purpose |
|---|---|
| `.graphifyignore` | Corpus filter — defines what enters the graph. **The make-or-break file** (see below). |
| `.gitattributes` | Union merge-driver for `graph.json`, so the graph could be tracked across worktrees without merge conflicts. |
| `.gitignore` (`graphify-out/`) | The generated graph is a local artifact, not versioned. |
| `AGENTS.md` (pointer) | Tells agents to query the graph first. |
| `docs/GRAPHIFY.md` | This file. |

**Local / machine-level** (NOT committed — set up once per machine, see "Install"):

- The `graphify` CLI + the `/graphify` Claude Code skill
- Obsidian and the vault at `~/obsidian-vaults/research-system-rag/`
- `graphify-out/` (the generated `graph.json`, `graph.html`, `GRAPH_REPORT.md`) — git-ignored, rebuilt for free
- The git hooks (`.git/hooks/post-commit`, `post-checkout`)

---

## Install (once per machine)

Prerequisites: Python ≥ 3.10, and the `claude` CLI on `PATH` (used as the free LLM backend).

```bash
# 1. Graphify CLI (isolated) + register the /graphify skill for Claude Code
curl -LsSf https://astral.sh/uv/install.sh | sh      # if you don't have uv/pipx
uv tool install graphifyy                            # installs the `graphify` binary
graphify install --platform claude                   # registers the /graphify skill globally

# 2. Obsidian (for the human view) + the vault directory
flatpak install -y flathub md.obsidian.Obsidian
mkdir -p ~/obsidian-vaults/research-system-rag

# 3. Auto-update git hooks (post-commit rebuild — free, main-worktree only)
cd <this repo>
graphify hook install
```

Then do a first build (next section). To open the human view: in Obsidian → **Open folder as vault** →
`~/obsidian-vaults/research-system-rag/`, enable the **Graph view** and **Canvas** core plugins, and
open `graph.canvas`.

---

## The corpus filter (`.graphifyignore`) — read this

`.graphifyignore` decides what gets parsed. The **critical exclusion is `.claude/`**: it holds ~74 full
worktree copies of this repo — without excluding them, every node is multiplied ~75× and the graph is
meaningless. It also excludes data/caches (`pdf_cache/`, `fixtures/`, `blobs/`, `papers.db*`). Keep it
accurate; if a build ever reports a wildly inflated node count, a bad/missing exclusion here is why.

---

## Build & rebuild

Run these from the repo root. Two backends matter: **AST** (code, deterministic, no LLM, instant) and
**semantic** (docs → concept/`doc↔code` edges, via the local `claude` CLI, a few minutes, free).

```bash
# Code graph only — fast, deterministic, zero LLM. Good for a quick refresh.
graphify extract . --code-only

# Full graph incl. design docs as nodes + doc↔code edges (uses the claude CLI):
graphify extract . --backend claude-cli

# After ANY extract, name the communities (they're "Community N" until you do):
graphify label . --backend claude-cli        # re-clusters + names + rewrites GRAPH_REPORT.md/graph.html

# Refresh the human Obsidian vault from the current graph:
graphify export obsidian --dir ~/obsidian-vaults/research-system-rag
```

Typical full refresh after editing docs:

```bash
graphify extract . --backend claude-cli \
  && graphify label . --backend claude-cli \
  && graphify export obsidian --dir ~/obsidian-vaults/research-system-rag
```

**Auto-update:** the installed **post-commit hook** re-extracts changed *code* files for free after each
commit (no LLM), and only fires in the **main worktree** (agent worktrees stay quiet). Doc/semantic
changes and community re-labeling are not automatic — rerun the commands above when you edit docs.

---

## Use it — for AI

Any of these (or `/graphify <question>` inside Claude Code, which auto-detects `graphify-out/graph.json`):

```bash
graphify query "how does cache-first ingest work"     # BFS over the graph, token-budgeted
graphify query "..." --dfs                             # trace one dependency chain deep
graphify path "app/dashboard/server.py" "rag/retriever.py"   # shortest connection between two nodes
graphify explain "rag/retriever.py"                    # a node + its neighbors, in plain language
graphify affected "load_config()"                      # reverse traversal: what depends on X
```

Prefer these over blind grep when locating code or tracing dependencies — that's the whole point of the
"for AI" side.

## Use it — for humans

- **`graphify-out/graph.html`** — open in a browser for the interactive force-directed graph.
- **Obsidian vault** (`~/obsidian-vaults/research-system-rag/`) — one note per node with backlinks; the
  **Graph view** shows the module communities; **`graph.canvas`** lays the communities out as named groups.
- **`graphify-out/GRAPH_REPORT.md`** — a plain-text audit: community list, "god nodes", EXTRACTED vs
  INFERRED edge ratio, freshness (the commit the graph was built from).

---

## Troubleshooting

- **`graphify-out/` missing** (fresh checkout / new machine) — it's git-ignored on purpose. Rebuild:
  `graphify extract . --code-only` (instant, free), then `label` + `export obsidian` for the full experience.
- **Communities named "Community 0/1/2…"** — you ran `extract`/`cluster-only` without labeling. Run
  `graphify label . --backend claude-cli`.
- **"out-of-scope source_file" warnings during a doc pass** — expected; a few large docs aren't dispatched
  for semantic extraction. Harmless — Graphify also drops any node the model mis-attributes.
- **`.sql` files "contributed nothing"** — the optional SQL grammar isn't installed. It's minor (the
  Python graph is complete); add it with `uv tool install "graphifyy[sql]"` if you want the migration SQL parsed.
- **Version the graph across worktrees** — flip the `graphify-out/` line off in `.gitignore`; the union
  merge-driver in `.gitattributes` is already registered to keep `graph.json` merges clean.
