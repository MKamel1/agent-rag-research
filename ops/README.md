# ops/ — container definitions (a record and a recovery path)

`docker-compose.yml` records the four service containers (`rag-qdrant`, `rag-grobid`,
`rag-tei-embed`, `rag-tei-reranker`) as `docker inspect` showed them on 2026-11-10, with every
image pinned by digest. **The running containers were not created from this file and the file has
never been applied.** Treat it as a mirror: re-inspect (`docker inspect <name>`) and diff against
`docker compose -f ops/docker-compose.yml config` before trusting it. There is deliberately no
`restart:` policy (see `docs/RUNBOOK.md`, "Why manual, on-demand startup").

## WARNING — the vector store

`rag-qdrant` was running `qdrant/qdrant:latest`, which resolved to **v1.18.2**
(`sha256:75eab8c4...`, built 2026-06-03); that digest is what the file pins. Recreating the
container against the existing ~31 GB store with a **different** Qdrant version can migrate or alter
the on-disk format, and that is not reversible. Never change the digest, and never re-pull
`latest`, without a snapshot first. A copy of the store was taken 2026-11-10 at
`backups/qdrant-storage-20261110` under the main corpus data directory (sibling directory
`research-system-rag-data`; also `backups/papers.db.snapshot-20261110`). Verify it before relying on it.

## Host paths (env vars, never hard-coded)

| Variable | Default in the file | Real value on this machine |
|---|---|---|
| `QDRANT_STORAGE_DIR` | `../.phase0-data/qdrant` (relative to `ops/`) | `<main checkout>/.phase0-data/qdrant` (gitignored). Inside a git worktree the default points at a path that does not exist and Docker would create an empty directory there: **set it explicitly** when not running from the main checkout. |
| `TEI_HF_CACHE` | `$HOME/docker-volumes/tei-data-hf` | same (HuggingFace model cache shared by embedder and reranker) |

## Recreate one container

The old container must not exist (name clash); compose will not touch the others.
`docker rm <name>` removes only the stopped container, never the bind-mounted data.

```bash
cd ops
docker compose -f docker-compose.yml config            # local, starts nothing: inspect first
docker compose -f docker-compose.yml up -d --no-deps rag-grobid        # or any one service name
```

GPU services (`rag-tei-embed`, `rag-tei-reranker`): check `nvidia-smi` first; a foreign holder
(e.g. a loaded Ollama model) causes CUDA OOM. Start order and health checks: `docs/RUNBOOK.md`.
Known differences from the originals: compose puts them on a new `ops_default` network instead of
the default bridge (clients use `localhost:<port>`, so no effect).

## What is recorded

| Service | Image (digest above) | Args | Ports (host:container) | Mounts | GPU |
|---|---|---|---|---|---|
| `rag-qdrant` | `qdrant/qdrant` v1.18.2 | image default (`./entrypoint.sh`) | 6333, 6334 | store -> `/qdrant/storage` | no |
| `rag-grobid` | `lfoppiano/grobid:0.8.0` | image default | 8070:8070 | none | no |
| `rag-tei-embed` | TEI `86-1.9` | `--model-id Qwen/Qwen3-Embedding-4B --max-batch-tokens 4096` | 8080:80 | HF cache -> `/data` | all |
| `rag-tei-reranker` | TEI `86-1.9` | `--model-id BAAI/bge-reranker-v2-m3` | 8082:80 | HF cache -> `/data` | all |

`--max-batch-tokens 4096` is also what silently truncates every embedding at 4,096 tokens (model
max 40,960): `docs/eval-reports/data/2026-11-10-embed-truncation/report.md`. Changing it only
affects newly embedded text and needs the re-embed plan. All container environment variables are
image-baked defaults (PATH, CUDA/NVIDIA, `HUGGINGFACE_HUB_CACHE=/data`, `RUN_MODE=production`, ...);
none looked like a token or key. Source of the inspection: `docs/eval-reports/data/2026-11-10-system-review/RV-6-ops-docs.md`.
Other stopped TEI containers on the machine (`rag-tei-embed-8b`, `rag-tei-bge-m3`) are old
experiments and are not recorded.

## Non-container dependency: Ollama (host service, port 11434)

Not in compose; runs on the host and is not changed by anything here. Models the code expects:

- `qwen3:14b` — summarizer / generation (`app/assembly.py` `_OLLAMA_MODEL`, `app/generation_capture.py`,
  `app/exp1_outline_split.py`, `app/reembed_experiment.py` header model). Must stay tag-qualified:
  `OllamaSummarizer.unload()` matches it exactly against `/api/ps`.
- `qwen3-14b-16k:latest` — the judge / agentic-loop model (`app/exp_agentic_loop_v0.py`,
  `app/generation_capture.py` comments). A custom 16k-context build of qwen3:14b; not a registry tag,
  so a fresh host must recreate it. Both were present in `ollama list` on 2026-11-10.
