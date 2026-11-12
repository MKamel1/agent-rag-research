"""MC-4: token cost of a `semantic_search` response before/after the MCP wire projection.

Method (RV-4 F-4.6): sample real chunks (text >= 150 chars) from a corpus `papers.db`, opened
READ-ONLY, build `SearchResponse` batches of size k with the real contract models, serialise the way
FastMCP does (`pydantic_core.to_json(indent=2)`) once as the full model and once through
`rag.mcp_server.to_wire`, and count `cl100k_base` tokens (tiktoken; characters if it is absent).

    python -m scripts.mcp_wire_tokens --db /path/to/papers.db [--k 5 10] [--batches 200]
"""

import argparse
import json
import random
import sqlite3
import statistics

import pydantic_core

from contracts.mcp_server import Coverage, SearchResponse
from contracts.provenance import Anchor
from contracts.retriever import Citation, GroundedResult
from rag.mcp_server import to_wire
from rag.retriever import source_url

_MIN_CHARS = 150  # RV-4's sampling floor: shorter chunks are headings, not passages


def _counter():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return "cl100k_base tokens", lambda text: len(enc.encode(text))
    except Exception:  # tiktoken missing, or its vocab file is not cached offline
        return "characters", len


def sample_results(db_path: str, n: int, seed: int = 0) -> list[GroundedResult]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT c.text, c.anchor_json, c.paper_id, c.section_path, p.title, p.authors_json, "
        "p.pdf_path, p.doc_type FROM chunks c JOIN papers p ON p.paper_id = c.paper_id "
        "WHERE length(c.text) >= ?", (_MIN_CHARS,)).fetchall()
    con.close()
    rng = random.Random(seed)
    out = []
    for text, anchor_json, paper_id, section_path, title, authors, pdf_path, doc_type in rng.sample(
            rows, min(n, len(rows))):
        out.append(GroundedResult(
            passage_text=text, anchor=Anchor(**json.loads(anchor_json)), paper_id=paper_id,
            score=0.5, citation=Citation(
                paper_id=paper_id, title=title, authors=json.loads(authors),
                arxiv_url=source_url(paper_id, pdf_path), section_path=section_path,
                doc_type=doc_type)))
    return out


def measure(results: list[GroundedResult], k: int, batches: int, seed: int = 1):
    """Median (full, wire) size over `batches` random k-sized responses; sizes in `unit`."""
    unit, count = _counter()
    rng = random.Random(seed)
    full, wire = [], []
    for _ in range(batches):
        resp = SearchResponse(results=rng.sample(results, k),
                              coverage=Coverage(returned=k, candidates=k))
        full.append(count(pydantic_core.to_json(resp.model_dump(mode="json"), indent=2).decode()))
        wire.append(count(pydantic_core.to_json(to_wire(resp), indent=2).decode()))
    return unit, statistics.median(full), statistics.median(wire)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--k", type=int, nargs="+", default=[5, 10])
    parser.add_argument("--batches", type=int, default=200)
    parser.add_argument("--chunks", type=int, default=400)
    args = parser.parse_args()
    results = sample_results(args.db, args.chunks)
    for k in args.k:
        unit, full, wire = measure(results, k, args.batches)
        print(f"k={k}: full {full:.0f} -> wire {wire:.0f} {unit} (median of {args.batches}); "
              f"{100 * (1 - wire / full):.1f}% smaller")


if __name__ == "__main__":
    main()
