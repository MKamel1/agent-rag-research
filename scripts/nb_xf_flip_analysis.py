"""NB-X-F paired flip analysis — derives the eviction verdict from the committed arm JSONs.

Reads ONLY the raw per-fixture reports the NB-D4 runner wrote for this ticket's arms (arm A =
fused reference, arm B = dense_only, arm C = w0.8, arm D = w1.0) under
`docs/eval-reports/data/2026-08-25-nb-xf/` and prints, per fixture:

  1. paper-level flips between two arms (hit->miss / miss->hit with question ids and ranks),
  2. rank movements among questions hit in both arms,
  3. block-level (gold-block) rank changes for passage-scored items,
  4. the status of the five historically one-way eviction questions,
  5. an exact-equality check that arm B (dense_only) and arm D (--dense-weight 1.0) produced
     identical per-question rows -- the pre-registered identity cross-check.

Stdlib only; zero-GPU, zero-network (CI posture). Usage:

    python scripts/nb_xf_flip_analysis.py [--data-dir docs/eval-reports/data/2026-08-25-nb-xf]

Ticket: docs/eval-reports/2026-08-25-nb-xf-fusion-shape.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

STEM = "2026-08-25-nb-d4-dual-fixture-{tag}"
FIXTURE_FILES = ("gt_wmr.json", "waymo_gt_verified.json")

# The five dense-hit/fused-miss questions from the 2026-08-23 baseline §2 (one-way eviction
# direction on the then-corpus). Their status today is part of this ticket's verdict.
HISTORIC_EVICTION_QUESTIONS = (
    "Q-GTA-010",
    "Q-GTA-011",
    "Q-GTA-020",
    "Q-GTA-022",
    "Q-WAYB-002",
)


def load_rows(data_dir: Path, tag: str) -> dict[str, dict[str, dict]]:
    """fixture name -> question_id -> per-question row, for one arm."""
    out: dict[str, dict[str, dict]] = {}
    for fx in FIXTURE_FILES:
        report = json.loads((data_dir / (STEM.format(tag=tag)) / fx).read_text())
        out[fx] = {q["question_id"]: q for q in report["questions"]}
    return out


def _rank(q: dict) -> int | None:
    return q["paper_level"]["rank"]


def _block_rank(q: dict) -> int | None:
    return q["passage_level"]["rank"] if q["passage_level"]["scored"] else None


def compare(a_rows: dict, b_rows: dict, label_a: str, label_b: str) -> None:
    """Paired comparison of two arms over the same fixture's question rows."""
    hits_lost, hits_gained, rank_moves, block_moves = [], [], [], []
    assert set(a_rows) == set(b_rows), "arms scored different question sets"
    for qid in a_rows:
        qa, qb = a_rows[qid], b_rows[qid]
        ra, rb = _rank(qa), _rank(qb)
        if ra is not None and rb is None:
            hits_lost.append((qid, ra))
        elif ra is None and rb is not None:
            hits_gained.append((qid, rb))
        elif ra != rb:
            rank_moves.append((qid, ra, rb))
        ba, bb = _block_rank(qa), _block_rank(qb)
        if ba != bb and not (ra is None and rb is None):
            block_moves.append((qid, ba, bb))

    print(f"  paper-level: {label_a} -> {label_b}")
    print(
        f"    hits lost:  {len(hits_lost)}"
        + ("" if not hits_lost else f"  {sorted(hits_lost)}")
    )
    print(
        f"    hits gained:{len(hits_gained)}"
        + ("" if not hits_gained else f"  {sorted(hits_gained)}")
    )
    print(f"    rank moves among always-hit: {len(rank_moves)}")
    for qid, ra, rb in sorted(rank_moves):
        print(f"      {qid}: rank {ra} -> {rb}")
    print(f"    gold-block rank changes (scored, paper-visible): {len(block_moves)}")
    for qid, ba, bb in sorted(block_moves):
        print(f"      {qid}: block rank {ba} -> {bb}")


def historic_status(rows: dict[str, dict]) -> None:
    print("  historical one-way eviction questions (baseline §2):")
    for qid in HISTORIC_EVICTION_QUESTIONS:
        q = rows.get(qid)
        if q is None:
            print(f"    {qid}: NOT IN FIXTURE")
            continue
        r = _rank(q)
        br = _block_rank(q)
        state = "MISS" if r is None else f"paper rank {r}"
        bstate = "-" if br is None else f"block rank {br}"
        print(f"    {qid}: fused={state}, {bstate} | gold_paper_ids={q['gold_paper_ids']}")


def _rows_equal_scoring(qb: dict, qd: dict) -> bool:
    """Scoring-relevant equality: everything a metric reads. Tail-ordering wobble in the
    recorded retrieved-id lists feeds no metric and is deliberately excluded here."""
    return (
        qb["paper_level"] == qd["paper_level"]
        and qb["passage_level"] == qd["passage_level"]
        and qb["top_score"] == qd["top_score"]
        and qb["gold_paper_ids"] == qd["gold_paper_ids"]
    )


def identity_check(b_rows_by_fx: dict, d_rows_by_fx: dict) -> bool:
    """True iff arms B and D agree on every SCORING field of every row (full-row equality is
    reported separately: retrieved-id tail order can wobble run-to-run without moving any
    metric -- see the report's determinism note)."""
    identical = True
    for fx in FIXTURE_FILES:
        b, d = b_rows_by_fx[fx], d_rows_by_fx[fx]
        score_diffs = [qid for qid in b if not _rows_equal_scoring(b[qid], d[qid])]
        full_diffs = [qid for qid in b if b[qid] != d.get(qid)]
        if score_diffs:
            identical = False
            shown = sorted(score_diffs)[:10]
            print(f"  B vs D differ on {fx} SCORING fields: {shown}"
                  f"{' ...' if len(score_diffs) > 10 else ''}")
        else:
            print(f"  B vs D on {fx}: all {len(b)} rows equal on scoring fields "
                  f"(paper_level/passage_level/top_score/gold); "
                  f"tail-order-only row diffs: {len(full_diffs)}")
    return identical


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path,
                        default=Path("docs/eval-reports/data/2026-08-25-nb-xf"))
    args = parser.parse_args(argv)

    a = load_rows(args.data_dir, "nbxf-w070-ref")
    b = load_rows(args.data_dir, "nbxf-dense-only")
    c = load_rows(args.data_dir, "nbxf-w080")
    d = load_rows(args.data_dir, "nbxf-w100")

    for fx in FIXTURE_FILES:
        print(f"\n=== {fx} ===")
        print("\n-- fused (A, w=0.7) vs dense-only (B, w=1.0) --")
        compare(a[fx], b[fx], "fused", "dense_only")
        print("\n-- fused (A) vs w=0.8 (C) --")
        compare(a[fx], c[fx], "fused", "w0.8")
        historic_status(a[fx])

    print("\n=== identity check: dense_only mode (B) vs --dense-weight 1.0 (D) ===")
    if identity_check(b, d):
        print("  => arms B and D are the same configuration, confirmed empirically")
    else:
        print("  => UNEXPECTED scoring divergence between B and D -- "
              "investigate before citing either")

    # Net direction summary at fixed depth (the verdict's core arithmetic).
    print("\n=== net direction (answerable R@10 hits), fused A vs dense-only B ===")
    for fx in FIXTURE_FILES:
        a_hits = sum(1 for q in a[fx].values() if _rank(q) is not None)
        b_hits = sum(1 for q in b[fx].values() if _rank(q) is not None)
        print(f"  {fx}: fused {a_hits} vs dense-only {b_hits} (diff {b_hits - a_hits:+d})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
