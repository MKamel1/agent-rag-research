#!/usr/bin/env python3
"""`python -m app.exp_nb_xc_member_citation` -- NB-XC's conversion measurement.

Read-only over the stored 2026-08-23 Waymo-priority baseline records
(`docs/eval-reports/data/2026-08-23-waymo-priority/<fixture>_<mode>.json`) plus `papers.db`
opened `mode=ro`. No retrieval runs, no GPU, no network.

QUESTION (ticket NB-XC): exactly which stored-run items convert if passage citation granularity
is the served chunk's MEMBER BLOCKS rather than its anchor alone?

Definitions are frozen in docs/eval-reports/2026-08-25-nb-xc-citation.md §1 (committed before
this instrument ran); this module implements them verbatim:

* baseline hit := gold_block_id ∈ retrieved_block_ids (exact string match; eval semantics);
* member hit   := ∃ j with paper(retrieved_block_ids[j]) == paper(gold_block_id) -- STRING
  PREFIX identity, never cross-identity -- and gold's blocks.idx inside that anchor chunk's span
  [anchor_idx, next_anchor_idx) of the paper's anchor-partition (NB-D2 §0 membership rule);
* converts     := scored ∧ ¬baseline_hit ∧ member_hit. Monotone: anchors are members of their
  own chunks, so no baseline hit can become a miss.

GATES (refuse to emit results if any fail):
  G1 recomputed baseline hit/rank == stored passage_level.hit/rank for every scored item;
  G2 every referenced block id resolves in papers.db;
  G3 per-paper geometry validity (unique anchors, consecutive chunk-id suffixes,
     member-section consistency reported, same posture as NB-D2);
  G4 monotonicity: baseline hit ⇒ member hit for every scored item.

Usage:
    python -m app.exp_nb_xc_member_citation [--db PATH] [--data-dir PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

DB_DEFAULT = Path("/home/omar/ai-projects/research-system-rag/waymo/data/papers.db")
DATA_DIR_DEFAULT = (
    Path(__file__).resolve().parent.parent / "docs/eval-reports/data/2026-08-23-waymo-priority"
)

# Headline configs (PREC-1 §1); remaining arms as appendix context. Never averaged across.
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

_CHUNK_ID_RE = re.compile(r"^(?P<paper>.+):c(?P<n>\d+)$")


class GateError(RuntimeError):
    """A sanity gate failed -- results must not be trusted or emitted."""


def paper_prefix(block_id: str) -> str:
    """Everything before the final ':b<idx>' -- the ingest identity a block id lives under."""
    return block_id.rsplit(":", 1)[0]


def load_records(data_dir: Path, fixture: str, mode: str) -> tuple[list[dict], int]:
    """Load per-question records + k for one stored config."""
    path = data_dir / f"{fixture}_{mode}.json"
    payload = json.loads(path.read_text())
    return payload["questions"], payload["k"]


def open_db_ro(db_path: Path) -> sqlite3.Connection:
    """Open papers.db strictly read-only."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass(frozen=True)
class MemberHit:
    """One qualifying membership: gold block sits inside the chunk anchored by serving_anchor
    at 0-based top-k position serving_position."""

    serving_position: int
    serving_anchor: str
    span_start: int
    span_end: int  # exclusive
    at_rank_1: bool


class PaperGeometry:
    """Block/chunk layout of ONE paper identity, reconstructed read-only from papers.db.

    Membership rule (NB-D2 §0, mechanically verified there): chunks sorted by their anchor
    block's blocks.idx partition the block-index space.
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
        saw_suffix_chunk = False
        for row in conn.execute(
            "SELECT chunk_id, anchor_json, section_path FROM chunks WHERE paper_id=?",
            (paper_id,),
        ):
            m = _CHUNK_ID_RE.match(row["chunk_id"])
            if m and m.group("paper") == paper_id:
                saw_suffix_chunk = True
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
        # A paper whose only chunk rows carry foreign-format ids would silently have no
        # geometry; every paper we look up here was ingested with the canonical scheme.
        if saw_suffix_chunk is False and anchored:
            raise GateError(f"{paper_id}: chunk rows present but none match '<paper>:c<n>'")

        anchored.sort(key=lambda t: t[0])
        self.anchor_idxs: list[int] = [i for i, _ in anchored]
        self.chunk_rows: list[sqlite3.Row] = [r for _, r in anchored]
        self.max_block_idx = max(self.blocks_by_idx)
        if not self.anchor_idxs:
            raise GateError(f"{paper_id}: no chunks -- blocks cannot belong to any served chunk")

    def block(self, block_id: str) -> sqlite3.Row:
        try:
            return self.blocks_by_id[block_id]
        except KeyError:
            raise GateError(f"{self.paper_id}: unknown block {block_id}") from None

    def span_of_chunk_pos(self, pos: int) -> tuple[int, int]:
        """Half-open block-index span [start, end) of the anchor-ordered chunk at `pos`."""
        start = self.anchor_idxs[pos]
        end = (
            self.anchor_idxs[pos + 1] if pos + 1 < len(self.anchor_idxs) else self.max_block_idx + 1
        )
        return start, end

    def section_violations(self) -> list[tuple[int, str, str]]:
        """Member blocks whose section_path differs from their chunk's (should be empty)."""
        violations = []
        for pos, start in enumerate(self.anchor_idxs):
            chunk_sec = self.chunk_rows[pos]["section_path"]
            end = self.span_of_chunk_pos(pos)[1]
            for x in range(start, end):
                blk = self.blocks_by_idx.get(x)
                if blk is not None and blk["section_path"] != chunk_sec:
                    violations.append((x, blk["section_path"], chunk_sec))
        return violations


def member_lookup(
    geo_cache: dict[str, PaperGeometry],
    conn: sqlite3.Connection,
    load_paper,
    gold_block_id: str,
    retrieved_block_ids: list[str],
) -> MemberHit | None:
    """First (lowest-position) membership of `gold_block_id` in any served chunk.

    Dual-id rule: membership is asserted ONLY when the serving anchor carries the SAME paper
    prefix as the gold block -- a `local:<hash>` twin never vouches for a canonical block or
    vice versa (report §1).
    """
    gold_paper = paper_prefix(gold_block_id)
    geo = load_paper(conn, geo_cache, gold_paper)
    gold_idx = geo.block(gold_block_id)["idx"]

    for pos, anchor_id in enumerate(retrieved_block_ids):
        if paper_prefix(anchor_id) != gold_paper:
            continue
        anchor_geo = geo  # same prefix ⇒ same geometry
        try:
            anchor_idx = anchor_geo.block(anchor_id)["idx"]
        except GateError:
            raise GateError(f"retrieved anchor {anchor_id} unresolved in {gold_paper}") from None
        chunk_pos = bisect_right(anchor_geo.anchor_idxs, anchor_idx) - 1
        if chunk_pos < 0:
            raise GateError(f"{gold_paper}: anchor {anchor_id} precedes first chunk anchor")
        start, end = anchor_geo.span_of_chunk_pos(chunk_pos)
        if start <= gold_idx < end:
            return MemberHit(
                serving_position=pos,
                serving_anchor=anchor_id,
                span_start=start,
                span_end=end,
                at_rank_1=(pos == 0),
            )
    return None


def decompose_joint(record: dict) -> str | None:
    """PREC-1 §0 joint decomposition (A/C1/C2/D/E), as in NB-D2's instrument."""
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


def analyze_config(
    conn: sqlite3.Connection,
    geo_cache: dict[str, PaperGeometry],
    section_violations: dict[str, list],
    data_dir: Path,
    fixture: str,
    mode: str,
    watch_items: dict[str, str],
) -> dict:
    """One fixture×config over stored records. Raises GateError on G1/G2/G4 failure."""

    def load_paper(c: sqlite3.Connection, cache: dict, paper_id: str) -> PaperGeometry:
        if paper_id not in cache:
            geo = PaperGeometry(c, paper_id)
            cache[paper_id] = geo
            viols = geo.section_violations()
            if viols:
                section_violations[paper_id] = viols
        return cache[paper_id]

    records, k = load_records(data_dir, fixture, mode)
    n_scored = 0
    n_baseline_hits = 0
    conversions: list[dict] = []
    watch_status: dict[str, str] = {}

    for rec in records:
        pl = rec["passage_level"]
        if not pl["scored"]:
            continue
        n_scored += 1

        gold_bid = rec["gold_block_id"]
        retrieved = rec["retrieved_block_ids"][:k]
        base_positions = [i for i, b in enumerate(retrieved) if b == gold_bid]

        # G1: recompute baseline from raw strings; must equal the stored verdict.
        recomputed_rank = base_positions[0] + 1 if base_positions else None
        if bool(base_positions) != pl["hit"] or pl["rank"] != recomputed_rank:
            raise GateError(
                f"G1 {fixture}_{mode} {rec['question_id']}: stored pl != recomputed baseline"
            )

        member = member_lookup(geo_cache, conn, load_paper, gold_bid, retrieved)

        # G4: monotonicity -- an anchor is always a member of its own chunk.
        if pl["hit"] and member is None:
            raise GateError(
                f"G4 {fixture}_{mode} {rec['question_id']}: baseline hit without membership"
            )

        # G2: every retrieved anchor resolves somewhere (even cross-prefix ones).
        for anchor_id in retrieved:
            pfx = paper_prefix(anchor_id)
            if pfx != paper_prefix(gold_bid):
                _ = load_paper(conn, geo_cache, pfx).block(anchor_id)

        if pl["hit"]:
            n_baseline_hits += 1

        qid = rec["question_id"]
        status_line = None
        if qid in watch_items:
            member_desc = (
                f"pos {member.serving_position} anchor {member.serving_anchor}"
                if member
                else "none"
            )
            status_line = (
                f"{qid}: baseline_hit={pl['hit']} pl_rank={pl['rank']} member={member_desc}"
            )
            watch_status[qid] = status_line

        if not pl["hit"] and member is not None:
            conversions.append(
                {
                    "question_id": qid,
                    "joint_bucket": decompose_joint(rec),
                    "gold_block_id": gold_bid,
                    "serving_position": member.serving_position,
                    "serving_anchor": member.serving_anchor,
                    "at_rank_1": member.at_rank_1,
                    "span": [member.span_start, member.span_end],
                    "baseline_rank_if_C1": pl["rank"],
                }
            )

    rank1_conversions = [c for c in conversions if c["at_rank_1"]]
    result = {
        "config": f"{fixture}_{mode}",
        "k": k,
        "n_scored": n_scored,
        "n_baseline_hits": n_baseline_hits,
        "n_member_hits": n_baseline_hits + len(conversions),
        "baseline_hit_rate": round(n_baseline_hits / n_scored, 4) if n_scored else None,
        "member_hit_rate": round((n_baseline_hits + len(conversions)) / n_scored, 4)
        if n_scored
        else None,
        "n_converted_anywhere_top_k": len(conversions),
        "n_converted_at_rank_1": len(rank1_conversions),
        "conversions": conversions,
        "watch_items": watch_status,
    }
    return result


def print_report(results: dict) -> None:
    for key, r in results.items():
        headline = key in ("ver84_dense_only", "gt_wmr_fused")
        print(f"\n=== {r['config']} ({'HEADLINE' if headline else 'appendix'}) ===")
        print(
            f"scored={r['n_scored']}  baseline hits={r['n_baseline_hits']} "
            f"({r['baseline_hit_rate']:.1%})  member hits={r['n_member_hits']} "
            f"({r['member_hit_rate']:.1%})"
        )
        print(
            f"conversions: anywhere-in-top-{r['k']}={r['n_converted_anywhere_top_k']}  "
            f"rank-1={r['n_converted_at_rank_1']}"
        )
        for c in r["conversions"]:
            where = "RANK-1" if c["at_rank_1"] else f"top-k pos {c['serving_position']}"
            print(
                f"  CONVERTS {c['question_id']} [{c['joint_bucket']}] gold={c['gold_block_id']} "
                f"in {c['serving_anchor']} ({where}, span {c['span'][0]}-{c['span'][1] - 1})"
            )
        for qid, line in sorted(r["watch_items"].items()):
            print(f"  watch {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB_DEFAULT)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR_DEFAULT)
    parser.add_argument("--out", type=Path, default=None, help="results JSON path")
    args = parser.parse_args(argv)

    # NB-D2 §2 named these three; their expected outcomes are asserted below, not assumed.
    WATCH_ITEMS = {
        "Q-WAYB-027": "expect rank-1 conversion (ver84 dense)",
        "Q-WMR-094": "expect rank-1 conversion (gt_wmr fused)",
        # Overlap straddle (NB-D2 §2): its gold text rides along inside the rank-1 chunk via the
        # documented one-block overlap, but the contract says overlap is NOT a member -- it stays
        # a C1 hit through its own chunk's anchor at rank 7, converting nowhere.
        "Q-WMR-036": "expect NO conversion (already C1 hit at rank 7; overlap is not a member)",
    }

    conn = open_db_ro(args.db)
    geo_cache: dict[str, PaperGeometry] = {}
    section_violations: dict[str, list] = {}
    try:
        results = {}
        for fixture, mode in HEADLINE_CONFIGS + APPENDIX_CONFIGS:
            results[f"{fixture}_{mode}"] = analyze_config(
                conn, geo_cache, section_violations, args.data_dir, fixture, mode, WATCH_ITEMS
            )

        # Watch-item expectations are gates too: the evidence this ticket acts on must reproduce.
        h1 = results["ver84_dense_only"]["watch_items"].get("Q-WAYB-027", "")
        h2 = results["gt_wmr_fused"]["watch_items"].get("Q-WMR-094", "")
        h3 = results["gt_wmr_fused"]["watch_items"].get("Q-WMR-036", "")
        if "member=pos 0" not in h1 or "baseline_hit=False" not in h1:
            raise GateError(f"watch gate failed for Q-WAYB-027: {h1!r}")
        if "member=pos 0" not in h2 or "baseline_hit=False" not in h2:
            raise GateError(f"watch gate failed for Q-WMR-094: {h2!r}")
        if "baseline_hit=True" not in h3:
            raise GateError(f"watch gate failed for Q-WMR-036 (expected existing C1 hit): {h3!r}")
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

    out_path = args.out or (args.data_dir / "nb_xc_member_citation_results.json")
    out_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
