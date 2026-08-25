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
  G3  anchor uniqueness per paper, chunk-id suffix monotonic w.r.t. anchor idx;
  G4  per-fixture denominators sum: buckets partition the near-miss population.

OUTPUT: stdout tables + docs/eval-reports/data/2026-08-23-waymo-priority/
nb_d2_block_adjacency_results.json (machine-readable copy of every number).

Usage: python nb_d2_block_adjacency.py [--db PATH] [--data-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
from bisect import bisect_right
from pathlib import Path

# --- frozen constants -------------------------------------------------------

DB_DEFAULT = Path("/home/omar/ai-projects/research-system-rag/waymo/data/papers.db")
DATA_DIR_DEFAULT = Path(__file__).resolve().parent

# Headline configs (PREC-1 §1): (fixture, mode).
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

BUCKET_ORDER = [
    "cross_gold_paper",
    "same_chunk",
    "adjacent_chunk",
    "same_section",
    "same_doc_elsewhere",
]

_CHUNK_ID_RE = re.compile(r"^(?P<paper>.+):c(?P<n>\d+)$")


class GateError(RuntimeError):
    """A sanity gate failed — results must not be trusted or emitted."""


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

    Membership rule: chunks sorted by anchor-block `blocks.idx` partition the
    paper's block-index space (module docstring). Every lookup is verified.
    """

    def __init__(self, conn: sqlite3.Connection, paper_id: str) -> None:
        self.paper_id = paper_id

        self.blocks_by_id: dict[str, sqlite3.Row] = {}
        for row in conn.execute(
            "SELECT block_id, idx, type, section_path, text FROM blocks WHERE paper_id=?",
            (paper_id,),
        ):
            self.blocks_by_id[row["block_id"]] = row
        self.blocks_by_idx: dict[int, sqlite3.Row] = {
            r["idx"]: r for r in self.blocks_by_id.values()
        }
        if len(self.blocks_by_idx) != len(self.blocks_by_id):
            raise GateError(f"{paper_id}: duplicate blocks.idx values")

        anchored: list[tuple[int, sqlite3.Row]] = []
        seen_anchor_blocks: set[str] = set()
        last_suffix = -1
        for row in conn.execute(
            "SELECT chunk_id, anchor_json, section_path, text FROM chunks WHERE paper_id=?",
            (paper_id,),
        ):
            m = _CHUNK_ID_RE.match(row["chunk_id"])
            if m and m.group("paper") == paper_id:
                suffix = int(m.group("n"))
                if suffix != last_suffix + 1:
                    raise GateError(
                        f"{paper_id}: chunk-id suffixes not consecutive at {row['chunk_id']}"
                    )
                last_suffix = suffix

            anchor = json.loads(row["anchor_json"])
            bid = anchor["block_id"]
            blk = self.blocks_by_id.get(bid)
            if blk is None:
                raise GateError(f"{paper_id}: chunk {row['chunk_id']} anchors unknown block {bid}")
            if bid in seen_anchor_blocks:
                raise GateError(f"{paper_id}: block {bid} anchors two chunks")
            seen_anchor_blocks.add(bid)
            anchored.append((blk["idx"], row))

        anchored.sort(key=lambda t: t[0])
        self.anchor_idxs: list[int] = [i for i, _ in anchored]
        self.chunk_rows: list[sqlite3.Row] = [r for _, r in anchored]
        self.max_block_idx = max(self.blocks_by_idx)

    def block(self, block_id: str) -> sqlite3.Row:
        try:
            return self.blocks_by_id[block_id]
        except KeyError:
            raise GateError(f"{self.paper_id}: unknown block {block_id}") from None

    def chunk_pos_of_block(self, block_idx: int) -> int | None:
        """Position (0-based, anchor-ordered) of the chunk containing block idx.

        Returns None only when block_idx precedes the first anchor — which would
        mean a block no chunk covers; callers gate on that.
        """
        pos = bisect_right(self.anchor_idxs, block_idx) - 1
        if pos < 0:
            return None
        return pos

    def section_consistency_violations(self) -> list[tuple[int, str, str]]:
        """Blocks whose section_path differs from their containing chunk's.

        Under the documented grouping rule this should be empty; measured, not
        assumed, because the contracts text leaves split/merge edge behaviour implicit.
        """
        violations = []
        for pos, a_idx in enumerate(self.anchor_idxs):
            chunk_sec = self.chunk_rows[pos]["section_path"]
            nxt = (
                self.anchor_idxs[pos + 1]
                if pos + 1 < len(self.anchor_idxs)
                else self.max_block_idx + 1
            )
            for x in range(a_idx, nxt):
                blk = self.blocks_by_idx.get(x)
                if blk is not None and blk["section_path"] != chunk_sec:
                    violations.append((x, blk["section_path"], chunk_sec))
        return violations


# --- classification ---------------------------------------------------------


def decompose_joint(record: dict) -> str | None:
    """PREC-1 §1 joint failure decomposition: one of A/C1/C2/D/E per scored item.

    Ordering follows PREC-1 §0 field semantics: passage hit/rank is recall-style
    over top-10; A (gold block at rank 1) takes precedence; then rank-1-paper
    items split C1/C2 by whether the gold block appears anywhere in the top-10;
    then D (gold paper in top-10 but not rank 1); then E.
    """
    pl = record["passage_level"]
    papl = record["paper_level"]
    if not pl["scored"]:
        return None
    if pl["rank"] == 1:
        return "A"
    if papl["rank"] == 1:
        return "C1" if pl["hit"] else "C2"
    if papl["hit"]:
        return "D"
    return "E"


def classify_near_miss(
    geo_gold: PaperGeometry,
    geo_b1: PaperGeometry,
    gold_blk: sqlite3.Row,
    b1_blk: sqlite3.Row,
) -> tuple[str, int | None]:
    """Assign one adjacency bucket (module docstring definitions).

    Returns (bucket, chunk_position_distance_or_None). Raises GateError only for
    unmappable blocks (a block no chunk covers) — that invalidates geometry.
    """
    if geo_gold.paper_id != geo_b1.paper_id:
        return "cross_gold_paper", None

    gold_idx, b1_idx = gold_blk["idx"], b1_blk["idx"]
    cg = geo_gold.chunk_pos_of_block(gold_idx)
    cb = geo_b1.chunk_pos_of_block(b1_idx)
    if cg is None or cb is None:
        raise GateError(
            f"{geo_gold.paper_id}: block without chunk coverage "
            f"(gold_idx={gold_idx}, b1_idx={b1_idx})"
        )

    if cg == cb:
        return "same_chunk", 0
    dist = abs(cg - cb)
    if dist == 1:
        return "adjacent_chunk", dist
    if gold_blk["section_path"] == b1_blk["section_path"]:
        return "same_section", dist
    return "same_doc_elsewhere", dist


# --- per-config analysis ----------------------------------------------------


def _geometry(
    conn: sqlite3.Connection,
    cache: dict[str, PaperGeometry],
    section_violations: dict[str, list],
    paper_id: str,
) -> PaperGeometry:
    if paper_id not in cache:
        geo = PaperGeometry(conn, paper_id)
        cache[paper_id] = geo
        viols = geo.section_consistency_violations()
        if viols:
            section_violations[paper_id] = viols
    return cache[paper_id]


def analyze_config(
    conn: sqlite3.Connection,
    data_dir: Path,
    fixture: str,
    mode: str,
    geo_cache: dict[str, PaperGeometry],
    section_violations: dict[str, list],
) -> dict:
    records = load_records(data_dir, fixture, mode)

    # --- decomposition over all scored items (gate G1) ----------------------
    decomp = {"A": 0, "C1": 0, "C2": 0, "D": 0, "E": 0}
    n_scored = 0
    for rec in records:
        bucket = decompose_joint(rec)
        if bucket is not None:
            decomp[bucket] += 1
            n_scored += 1

    published = PREC1_DECOMPOSITION.get((fixture, mode))
    g1_ok: bool | str
    if published is not None:
        g1_ok = decomp == published
        if not g1_ok:
            print(
                f"GATE G1 FAILED for {fixture}_{mode}: recomputed {decomp} != "
                f"published {published}",
                file=sys.stderr,
            )
    else:
        g1_ok = "not_tabulated"

    # --- near-miss population ----------------------------------------------
    near_misses = []
    for rec in records:
        pl = rec["passage_level"]
        if not pl["scored"]:
            continue
        if rec["retrieved_paper_ids"][0] not in rec["gold_paper_ids"]:
            continue
        if pl["rank"] == 1:
            continue
        assert decompose_joint(rec) in ("C1", "C2"), rec["question_id"]
        near_misses.append(rec)

    items = []
    buckets = {b: 0 for b in BUCKET_ORDER}
    block_dists: list[int] = []
    chunk_dists: list[int] = []
    textual_overlap_notes = 0

    for rec in near_misses:
        qid = rec["question_id"]
        gold_bid = rec["gold_block_id"]
        b1_bid = rec["retrieved_block_ids"][0]
        p1 = rec["retrieved_paper_ids"][0]

        gold_paper = gold_bid.rsplit(":", 1)[0]
        b1_paper = b1_bid.rsplit(":", 1)[0]
        if b1_paper != p1:
            raise GateError(f"{qid}: rank-1 paper id {p1} != rank-1 block's paper {b1_paper}")

        geo_gold = _geometry(conn, geo_cache, section_violations, gold_paper)
        geo_b1 = _geometry(conn, geo_cache, section_violations, b1_paper)

        gold_blk = geo_gold.block(gold_bid)
        b1_blk = geo_b1.block(b1_bid)

        bucket, cdist = classify_near_miss(geo_gold, geo_b1, gold_blk, b1_blk)
        buckets[bucket] += 1

        bdist = abs(gold_blk["idx"] - b1_blk["idx"])
        block_dists.append(bdist)
        if cdist is not None:
            chunk_dists.append(cdist)

        # Textual evidence spot-check: does G's verbatim text appear inside the
        # rank-1 chunk's BODY? Expected YES iff same_chunk; may ALSO be yes for
        # adjacent pairs via the documented sub-chunk overlap block (report, don't fail).
        # Header ({title}\n{section_path}, rag/chunker.py _build_chunk) is stripped
        # first: the title header would otherwise substring-match every chunk of the
        # paper and fake "served content" for title-block golds.
        b1_chunk_text = geo_b1.chunk_rows[geo_b1.chunk_pos_of_block(b1_blk["idx"])]["text"]
        b1_chunk_body = b1_chunk_text.partition("\n\n")[2]
        in_text = (
            bool(b1_chunk_body)
            and gold_blk["text"] in b1_chunk_body
            and len(gold_blk["text"].strip()) > 0
        )
        if bucket == "same_chunk" and not in_text:
            raise GateError(
                f"{qid}: same_chunk claimed but gold text absent from rank-1 chunk body"
            )
        if bucket != "same_chunk" and in_text:
            textual_overlap_notes += 1

        items.append(
            {
                "question_id": qid,
                "sub_bucket": decompose_joint(rec),  # C1 or C2
                "bucket": bucket,
                "gold_rank_in_top10": rec["passage_level"]["rank"],  # None => C2 (absent)
                "rank1_paper": p1,
                "gold_paper": gold_paper,
                "block_distance": bdist,
                "chunk_distance": cdist,
                "gold_text_in_rank1_chunk": in_text,
                "gold_section": gold_blk["section_path"],
                "rank1_section": b1_blk["section_path"],
            }
        )

    # --- gates --------------------------------------------------------------
    if published is not None and g1_ok is False:
        raise GateError(f"G1 failed for {fixture}_{mode}")
    if sum(buckets.values()) != len(near_misses):
        raise GateError(f"G4 failed for {fixture}_{mode}")
    if n_scored != sum(decomp.values()):
        raise GateError(f"decomposition does not sum to n_scored for {fixture}_{mode}")

    def dist_stats(values: list[int]) -> dict:
        if not values:
            return {"n": 0}
        return {
            "n": len(values),
            "min": min(values),
            "median": statistics.median(values),
            "max": max(values),
            "histogram": {str(v): values.count(v) for v in sorted(set(values))},
        }

    # Cross-tab: adjacency bucket × C-sub-bucket (gold elsewhere-in-top10 vs absent).
    crosstab = {b: {"C1": 0, "C2": 0} for b in BUCKET_ORDER}
    gold_ranks_among_c1: list[int] = []
    for it in items:
        crosstab[it["bucket"]][it["sub_bucket"]] += 1
        if it["sub_bucket"] == "C1":
            gold_ranks_among_c1.append(it["gold_rank_in_top10"])

    result = {
        "config": f"{fixture}_{mode}",
        "n_questions": len(records),
        "n_scored": n_scored,
        "decomposition": decomp,
        "g1_matches_prec1_table": g1_ok,
        "n_near_miss": len(near_misses),
        "near_miss_share_of_scored": round(len(near_misses) / n_scored, 4) if n_scored else None,
        "buckets": buckets,
        "crosstab_bucket_x_sub": crosstab,
        "gold_rank_histogram_C1": dist_stats(gold_ranks_among_c1),
        "block_distance": dist_stats(block_dists),
        "chunk_distance": dist_stats(chunk_dists),
        "textual_overlap_notes": textual_overlap_notes,
        "items": items,
    }
    return result


# --- output -----------------------------------------------------------------


def print_report(results: dict) -> None:
    for key, r in results.items():
        headline = "HEADLINE" if key in ("ver84_dense_only", "gt_wmr_fused") else "appendix"
        print(f"\n=== {r['config']} ({headline}) ===")
        print(
            f"scored={r['n_scored']}  decomposition={r['decomposition']}  "
            f"G1-vs-PREC1: {r['g1_matches_prec1_table']}"
        )
        nm = r["n_near_miss"]
        if nm:
            print(
                f"near-misses (rank-1 paper right, gold block not rank 1): "
                f"{nm} / {r['n_scored']} scored = {r['near_miss_share_of_scored']:.1%}"
            )
        else:
            print(f"near-misses: 0 / {r['n_scored']}")
        for b in BUCKET_ORDER:
            n = r["buckets"][b]
            share = f" ({n / nm:.1%} of near-misses)" if nm else ""
            ct = r["crosstab_bucket_x_sub"][b]
            print(f"  {b:<20} {n:>3}{share}   [in-top10 C1={ct['C1']}, absent C2={ct['C2']}]")
        bd, cd = r["block_distance"], r["chunk_distance"]
        if bd.get("n"):
            print(
                f"  block distance |G−B1|: median {bd['median']}, max {bd['max']},"
                f" hist {bd['histogram']}"
            )
        if cd.get("n"):
            print(
                f"  chunk-position distance: median {cd['median']}, max {cd['max']},"
                f" hist {cd['histogram']}"
            )
        if r["textual_overlap_notes"]:
            print(
                f"  note: {r['textual_overlap_notes']} non-same-chunk item(s) whose gold text "
                f"still appears verbatim in the rank-1 chunk text (documented sub-chunk overlap)"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB_DEFAULT)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR_DEFAULT)
    parser.add_argument(
        "--out", type=Path, default=None, help="results JSON path (default: alongside data)"
    )
    args = parser.parse_args(argv)

    conn = open_db_ro(args.db)
    geo_cache: dict[str, PaperGeometry] = {}
    section_violations: dict[str, list] = {}
    try:
        results = {}
        for fixture, mode in HEADLINE_CONFIGS + APPENDIX_CONFIGS:
            results[f"{fixture}_{mode}"] = analyze_config(
                conn, args.data_dir, fixture, mode, geo_cache, section_violations
            )
    finally:
        conn.close()

    if section_violations:
        total = sum(len(v) for v in section_violations.values())
        sample = {p: v[:3] for p, v in list(sorted(section_violations.items()))[:5]}
        print(
            f"WARNING: {total} member-section consistency violations across "
            f"{len(section_violations)} papers; samples: {sample}"
        )

    print_report(results)

    out_path = args.out or (args.data_dir / "nb_d2_block_adjacency_results.json")
    out_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
