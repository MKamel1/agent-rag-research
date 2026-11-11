"""CQ-4: exact per-chunk truncation list, same rule as ../2026-11-10-embed-truncation/measure.py.

A chunk is truncated when its Qwen3-Embedding-4B token count exceeds 4,096. Read-only (sqlite
`mode=ro`), CPU only, no service calls. Needs the `tokenizers` package (conda env
agent-rag-research). Writes truncated_chunk_ids_<corpus>.txt, one chunk_id per line, which
build_targets.py reads in preference to its character-length approximation.

Usage: conda run -n agent-rag-research python exact_truncated_ids.py
"""

import os
import sqlite3

from tokenizers import Tokenizer

HERE = os.path.dirname(os.path.abspath(__file__))
TOK = ("/home/omar/docker-volumes/tei-data-hf/models--Qwen--Qwen3-Embedding-4B/snapshots/"
       "5cf2132abc99cad020ac570b19d031efec650f2b/tokenizer.json")
DBS = {
    "main": "/home/omar/ai-projects/research-system-rag-data/papers.db",
    "waymo": "/home/omar/ai-projects/research-system-rag/waymo/data/papers.db",
}
EMBED_LIMIT = 4096
# measure.py tokenizes every chunk above 3,500 chars exactly; shorter ones are never over
# 4,096 tokens at the observed chars/token (sample check: 0 of 5,000 in measure.py).
EXACT_ABOVE_CHARS = 3500

tk = Tokenizer.from_file(TOK)
tk.no_truncation()
tk.no_padding()

for name, path in DBS.items():
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT chunk_id, text FROM chunks WHERE length(text) > ?", (EXACT_ABOVE_CHARS,)
        ).fetchall()
    finally:
        conn.close()
    over = []
    for chunk_id, text in rows:
        if len(tk.encode(text, add_special_tokens=False).ids) > EMBED_LIMIT:
            over.append(chunk_id)
    with open(os.path.join(HERE, f"truncated_chunk_ids_{name}.txt"), "w", encoding="utf-8") as fh:
        fh.write("".join(c + "\n" for c in sorted(over)))
    print(name, "tokenized", len(rows), "over_4096", len(over))
