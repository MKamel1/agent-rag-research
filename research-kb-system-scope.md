# AI Research Knowledge System — Scope

**Date:** 2026-07-04
**Status:** Scoping / pre-build
**Owner:** Omar AKA Mohamed (mkamel1)

## What we're building

A **personal AI research knowledge system** that runs on the local workstation
(RTX 3090 24GB / Ryzen 9950X / 96GB RAM / ~2.3TB free), continuously ingests
AI/ML research, and builds up a searchable "expert memory" that both Claude and
local models can query cheaply (minimal API tokens).

The goal: leave it running overnight / over a week → it accumulates an indexed,
summarized, cross-linked corpus of the latest AI research. Any model can then ask
it questions and get grounded, cited answers without burning tokens re-reading PDFs.

## The four parts

### 1. Ingestion (the collectors)
Scheduled background jobs that pull new AI/ML research from **legal** sources:
- **arXiv** — full-text, primary source (cs.AI, cs.LG, cs.CL, cs.CV, etc.).
  Most big-tech lab papers (DeepMind, Meta, Microsoft, Google, etc.) land here anyway.
- **Semantic Scholar / OpenAlex** — metadata + **citation graph** (who cites whom, references).
- **Unpaywall** — legal open-access fallback for anything paywalled.
- **Lab RSS feeds** — Google Research, Meta AI, MSR, DeepMind blogs for things
  that lag or skip arXiv.
- **big-tech published research** — covered via arXiv + lab RSS feeds 
- **user provided sources** — user will provide other sources in the future 

### 2. Processing (the brain-builder) — runs on local GPU
- Extract PDF text → chunk it.
- **Embed** each chunk with a local embedding model → store vectors. This enables
  *semantic* search ("find papers about idea X") rather than keyword match.
- Local LLM writes a structured summary per paper.
- All of this runs on local models via a serving stack (Ollama or vLLM) so it
  **costs zero API tokens**.
- Citation graph is built from Semantic Scholar / OpenAlex metadata, and stored
  in SQLite for fast queries.
- The brain need to be able to reason, understand math, understand tables, understand graphs and images, and understand code snippets.
- the findings should be linked to artifacts (paper, code, datasets, models), so it can be verified and reviewed by other models or humans. The artifacts should be stored in a structured way, and the links should be bidirectional (from findings to artifacts and from artifacts to findings).

### 3. Storage (the memory)
the memory need to be alive, that newly accumlated knowledge can affect the existing knowledge, and the existing knowledge can affect the newly accumlated knowledge.
I am not expert in this area, but I think the following can be considered:
- **Vector DB** (LanceDB or Chroma) for semantic search.
- **Quadrand database**.
- **SQLite** for metadata + citation edges.
- **Obsidian vault** (new, dedicated) — one linked markdown note per paper,
  wikilinked to related and cited papers → graph view + hand-browsable KB.

### 4. Access (the query layer):
think about what the user (agent) wants to do with the knowledge, and how to expose it to them. I am not expert in this area, but I think the following can be considered:
- An **MCP server** exposing tools like `search_papers`, `semantic_search`,
  `get_paper`, `get_citations`, `whats_new`.
- Lets **both Claude and local models** query the accumulated knowledge instead
  of re-fetching and re-reading papers — this is the token savings.

## Environment (confirmed)
- **GPU:** RTX 3090 24GB (driver 580.95.05; note: `nvidia-smi` currently shows an
  NVML driver/library version mismatch — needs a reboot or driver reload before GPU work).
- **CPU:** Ryzen 9950X (16C/32T), **RAM:** 96GB, **Disk:** ~2.3TB free.
- **Python:** 3.13 system; `pytorch-env` has Python 3.12 + torch 2.6.0+cu124 + transformers 4.57.
- **Ollama:** installed at `/usr/local/bin/ollama` (server not currently running).
- **Obsidian:** none yet — will create a new dedicated vault.

## Open decisions (recommendations)
plus the mentioned open issues above, the following are open decisions that need to be made:
- how to go from pdf to format susitable for next steps, how to deal with grphs and most importantly equations, and how to deal with code snippets, if any.
- **Embedding model:** the project whole archeticture and scope is still underdevelopment.
- what data system to be used for storing the embeddings and metadata (SQLite, LanceDB, Chroma, Quadrand, etc.)
- what local model for embedding and summarization to be used (LLaMA, Mistral, Qwen etc.): we want a fast model that is acurate, with appropriate dimensions capability to understand text, equations, graphs (if possible), and code snippets.
- what serving stack to be used (Ollama, vLLM, SGLang, etc.)
- **should a RAG be used**
- **what RAG system to be used**
- what are the RAG compnonets to be used
- **Serving stack:** lean **Ollama** for v1 (simple, ideal for batch/background
  embedding + summarization on a single GPU). Move to **vLLM** later only if
  throughput becomes the bottleneck.
- **v1 scope:** start with a thin vertical slice
  (**arXiv → embed → Obsidian → MCP search**), then layer on citation graph,
  Unpaywall, and RSS feeds. Avoids building everything at once.
- what steps should we have after the ingestion, embedding, and summarization, to make sure the knowledge is stored in a way that can be queried by the models and the user (indexing, retrieval, Reciprocal Rank Fusion, etc.).
