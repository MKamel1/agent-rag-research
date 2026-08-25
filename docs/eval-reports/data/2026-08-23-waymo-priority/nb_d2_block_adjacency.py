#!/usr/bin/env python3
"""NB-D2 — block adjacency / chunking-artifact analysis (completes PREC-1 §3).

Ticket: docs/superpowers/plans/2026-08-24-next-build-programme.md §4 D2.
Read-only over stored eval records + papers.db (opened mode=ro). No retrieval
runs, no GPU, no network.

QUESTION: among near-misses — items whose rank-1 PAPER is correct but whose gold
BLOCK is not at rank 1 (PREC-1 §1 buckets C1 ∪ C2) — how far is the gold block
from what the retriever DID return at rank 1?

POPULATION (per fixture, scored answerable items only):
    near-miss := passage_level.scored
                 and retrieved_paper_ids[0] ∈ gold_paper_ids      (rank-1 paper right)
                 and passage_level.rank != 1                       (gold block not at rank 1)

REFERENCE POINT: B1 = retrieved_block_ids[0] — the anchor.block_id of the chunk
returned at rank 1 (app/retrieval_eval.py: retrieved ids ARE returned chunks'
anchor block ids). G = gold_block_id.

ADJACENCY DEFINITIONS (frozen before use, per ticket MUST DO):

* Chunk↔block membership: rag/chunker.py groups CONSECUTIVE same-section_path
  blocks into one chunk and anchors the chunk at the group's FIRST block
  (DATA-CONTRACTS.md "Multi-block anchoring rule"). Therefore, within a paper,
  sorting chunks by their anchor block's blocks.idx partitions the block-index
  space: block x belongs to chunk_i iff
      anchor_idx[i] <= x < anchor_idx[i+1]        (anchors sorted ascending).
  Verified mechanically below (anchor uniqueness, chunk-id suffix monotonicity,
  member-section consistency); verbatim text containment used as a spot-check.

* Bucket classification (mutually exclusive, FIRST match wins):
    1. cross_gold_paper   doc(G) != doc(B1)            (multi-paper gold sets only)
    2. same_chunk         chunk(G) == chunk(B1)         (pure chunking artifact:
                                                        gold sits inside the very
                                                        chunk that was returned)
    3. adjacent_chunk     chunk(G), chunk(B1) exist and their positions in the
                          paper's anchor-ordered chunk sequence differ by exactly 1
    4. same_section       same document and blocks.section_path equal
    5. same_doc_elsewhere same document, everything else

* Raw distances reported alongside (not buckets): block distance
  |blocks.idx(G) − blocks.idx(B1)| and chunk-position distance, both per fixture.

FIXTURES (headline configs, PREC-1 §1 — never averaged across):
    verified-84  × dense_only
    GT-WMR       × fused
Remaining arms computed by the same code and reported as appendix context only.

SANITY GATES (script refuses to emit results if any fail):
  G1  recomputed joint failure decomposition (buckets A/C1/C2/D/E from raw
      records) reproduces PREC-1 §1's published counts for the three configs
      tabulated there;
  G2  every referenced block/chunk id resolves in papers.db;
  G3  anchor uniqueness per block, chunk-id suffix monotonic w.r.t. anchor idx,
      and member-section consistency hold for every paper touched;
  G4  per-fixture denominators sum: buckets partition the near-miss population.

OUTPUT: stdout tables + docs/eval-reports/data/2026-08-23-waymo-priority/
nb_d2_block_adjacency_results.json (machine-readable copy of every number).

Usage: python nb_d2_block_adjacency.py [--db PATH] [--data-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from bisect import bisect_right
from pathlib import Path

# --- frozen constants -------------------------------------------------------

DB_DEFAULT = Path("/home/omar/ai-projects/research-system-rag/waymo/data/papers.db")
DATA_DIR_DEFAULT = Path(__file__).resolve().parent

# Headline configs (PREC-1 §1): (fixture, mode) -> data file stem.
HEADLINE_CONFIGS = [
    ("ver84", "dense_only"),
    ("gt_wmr", "fused"),
]
APPENDIX_CONFIGS = [
    ("ver84", "fused"),
    ("ver84", "sparse_only"),
    ("gt_wmr", "dense_only"),
    ("gt_wmr", "sparse_only"),
]

# PREC-1 §1 published joint decomposition (bucket -> count), for gate G1.
PREC1_DECOMPOSITION = {
    ("ver84", "dense_only"): {"A": 24, "C1": 18, "C2": 9, "D": 11, "E": 2},
    ("ver84", "fused"): {"A": 23, "C1": 16, "C2": 11, "D": 7, "E": 7},
    ("gt_wmr", "fused"): {"A": 48, "C1": 11, "C2": 1, "D": 5, "E": 1},
}

BUCKET_ORDER = ["cross_gold_paper", "same_chunk", "adjacent_chunk", "same_section", "same_doc_elsewhere"]


# --- data access ------------------------------------------------------------


def load_records(data_dir: Path, fixture: str, mode: str) -> list[dict]:
    """Load per-question records for one config."""
    path = data_dir / f"{fixture}_{mode}.json"
    payload = json.loads(path.read_text())
    return payload["questions"]


def open_db_ro(db_path: Path) -> sqlite3.Connection:
    """Open papers.db strictly read-only."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


class PaperGeometry:
    """Block/chunk layout of ONE paper, reconstructed read-only from papers.db.

    Membership rule and verification: see module docstring.
    """

    def __init__(self, conn: sqlite3.Connection, paper_id: str) -> None:
        raise NotImplementedError("stub — implemented in commit 2")

    def block(self, block_id: str) -> sqlite3.Row:
        raise NotImplementedError("stub — implemented in commit 2")

    def chunk_of_block(self, block_idx: int) -> int | None:
        """Position (0-based, anchor-ordered) of the chunk containing block idx."""
        raise NotImplementedError("stub — implemented in commit 2")


# --- classification ---------------------------------------------------------


def decompose_joint(record: dict) -> str:
    """PREC-1 §1 joint failure decomposition: one of A/C1/C2/D/E per scored item."""
    raise NotImplementedError("stub — implemented in commit 2")


def classify_near_miss(geo_gold: PaperGeometry, geo_b1: PaperGeometry,
                       gold_idx: int, b1_idx: int) -> str:
    """Assign one adjacency bucket (module docstring definitions)."""
    raise NotImplementedError("stub — implemented in commit 2")


# --- main -------------------------------------------------------------------


def analyze_config(conn: sqlite3.Connection, data_dir: Path,
                   fixture: str, mode: str) -> dict:
    """Full per-config result dict: denominators, decomposition, buckets, distances."""
    raise NotImplementedError("stub — implemented in commit 2")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB_DEFAULT)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR_DEFAULT)
    parser.add_argument("--out", type=Path, default=None,
                        help="results JSON path (default: alongside data)")
    args = parser.parse_args(argv)

    conn = open_db_ro(args.db)
    try:
        results = {}
        for fixture, mode in HEADLINE_CONFIGS + APPENDIX_CONFIGS:
            results[f"{fixture}_{mode}"] = analyze_config(conn, args.data_dir, fixture, mode)
    finally:
        conn.close()

    out_path = args.out or (args.data_dir / "nb_d2_block_adjacency_results.json")
    out_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
