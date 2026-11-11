"""Per-stratum report over `app.retrieval_eval` JSON reports joined to ONE ground-truth file.

    python scripts/eval_strata_report.py --ground-truth GT.json --db papers.db \
        [--topic-labels topic_labels.tsv] [--k 10] [--json-out out.json] REPORT.json [...]

Pure post-processing: read-only SQLite (`mode=ro`), no retrieval, no network, no GPU. One
invocation = one ground-truth file; numbers are never averaged across ground-truth files (run it
once per GT and compare the printed tables). Every rate prints as `hits/n = 0.xxx`.

Metrics (all over the top-k of each question's ordered `retrieved_*` lists):
  1. per-`dimension` over answerable items: paper Recall@k / P@1; anchor-passage hit@k / P@1
     (stock rule: retrieved anchor block id == gold_block_id); member-passage hit@k / P@1 (a
     retrieved anchor counts if it anchors the gold chunk, or an `alternative_gold_chunk_ids`
     chunk, or the chunk's member blocks contain `excerpt_block_id`).
  2. stub analysis: share of rank-1 results / of all top-k slots whose chunk body (< 40 chars) is
     empty-ish. Chunk text = `title\\nsection_path\\n\\nbody`.
  3. authority / edition: how often a `commentary_paper_ids` / `other_edition_paper_ids` document
     ranks strictly above EVERY gold document (gold missing from top-k counts as rank infinity).
  4. cross-document: fraction with ALL gold documents in top-k, and with at least one.
  5. absent arm (never blended): n, top-score min/median/max beside the answerable arm's, and how
     often `nearest_distractor_paper_id` is rank 1.
  6. focus (needs --topic-labels): contamination by `off` papers for answerable items whose gold
     papers are all `on`; distractor outranking; lookalike outranking for `offtopic-legit`;
     contamination by dimension; chance baseline = corpus off-topic share in the labels file.

CHUNK -> MEMBER BLOCKS (reused from app/exp_nb_xc_member_citation.py `PaperGeometry` /
`member_lookup`, NB-D2 §0: chunks sorted by anchor block `idx` partition the block-index space;
chunk spans [anchor_idx, next_anchor_idx); the last chunk runs to the paper's last block). That
module raises on anything irregular and works per paper object; this one is a bulk, tolerant
re-implementation of the same rule working at the level the reports expose: the ANCHOR BLOCK ID.
Verified 2026-11-10 (read-only) on a random 40-paper sample of each DB, comparing each member
block's text prefix with the chunk text:
  * main DB: 1284 chunks, 1284 (100%) have every member block's text inside the chunk text.
  * standards DB: 10403 chunks, 10086 (96.9%) do; 317 (3.1%) have a member block whose text is
    missing from the chunk text.
Where the rule can be WRONG (member set is then an over-estimate, never an under-estimate):
  * Several chunks share ONE anchor block (standards: a long block split over chunks c3,c4,...).
    Reports only carry the anchor block id, so these chunks are indistinguishable; they are merged
    (members = the shared span) and a hit on any of them counts. Stub status for such an anchor
    needs ALL its chunks to be stubs.
  * Chunks that stop before their span ends (size cap) or table blocks re-rendered/split into
    rows: a block the rule calls a member may not be in the served text (the 3.1% above, mostly
    `table` and some long `prose` blocks).
  * Overlap: some chunks quote the start of the NEXT block (737/10403 in standards); the rule does
    not count it as a member (under-counts there, but only for overlap text, not the chunk body).
  * Blocks before the first anchor belong to no chunk.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

STUB_BODY_CHARS = 40
INF = 10**9


# ---------------------------------------------------------------- pure helpers
def first_rank(ids: list[str], wanted: set[str]) -> int | None:
    """1-based rank of the first id in `wanted`, else None."""
    return next((i + 1 for i, x in enumerate(ids) if x in wanted), None)


def rate(flags: list[bool]) -> dict:
    return {"hits": sum(flags), "n": len(flags)}


def fmt(r: dict) -> str:
    n = r["n"]
    return f"{r['hits']}/{n} = {r['hits'] / n:.3f}" if n else "0/0 = n/a"


def join_ground_truth(report: dict, gt: dict[str, dict]) -> list[tuple[dict, dict]]:
    """(row, gt item) per report question. Missing ids fail loudly: a silent drop would shrink n."""
    rows = report["questions"]
    missing = [r["question_id"] for r in rows if r["question_id"] not in gt]
    if missing:
        raise ValueError(f"{len(missing)} report question ids not in ground truth: {missing[:5]}")
    return [(r, gt[r["question_id"]]) for r in rows]


def gold_papers(row: dict, item: dict) -> set[str]:
    return set(row["gold_paper_ids"]) | set(item.get("additional_gold_paper_ids") or [])


def passage_ranks(
    row: dict, item: dict, k: int, chunk_anchor: dict[str, str], members: dict[str, set[str]]
) -> tuple[int | None, int | None]:
    """(anchor rank, member rank) within top-k; None = miss. Caller ensures gold_block_id is set."""
    anchors = row["retrieved_block_ids"][:k]
    gold_anchors = {item["gold_block_id"]}
    gold_chunks = [item.get("gold_chunk_id"), *(item.get("alternative_gold_chunk_ids") or [])]
    gold_anchors |= {chunk_anchor[c] for c in gold_chunks if c in chunk_anchor}
    excerpt = item.get("excerpt_block_id")
    anchor_rank = first_rank(anchors, {item["gold_block_id"]})
    member_rank = next(
        (
            i + 1
            for i, a in enumerate(anchors)
            if a in gold_anchors or (excerpt and excerpt in members.get(a, ()))
        ),
        None,
    )
    return anchor_rank, member_rank


def dimension_table(pairs, k, chunk_anchor, members) -> dict:
    by_dim = defaultdict(list)
    for row, item in pairs:
        if item["tests"] == "answerable":
            by_dim[item["dimension"]].append((row, item))
    out = {}
    for dim, ps in sorted(by_dim.items()):
        pranks = [first_rank(r["retrieved_paper_ids"][:k], gold_papers(r, i)) for r, i in ps]
        scored = [(r, i) for r, i in ps if i.get("gold_block_id")]
        psg = [passage_ranks(r, i, k, chunk_anchor, members) for r, i in scored]
        out[dim] = {
            "n": len(ps),
            "paper_recall": rate([x is not None for x in pranks]),
            "paper_p1": rate([x == 1 for x in pranks]),
            "anchor_hit": rate([a is not None for a, _ in psg]),
            "anchor_p1": rate([a == 1 for a, _ in psg]),
            "member_hit": rate([m is not None for _, m in psg]),
            "member_p1": rate([m == 1 for _, m in psg]),
        }
    return out


def stub_analysis(rows: list[dict], k: int, stub_anchors: set[str]) -> dict:
    top1 = [r["retrieved_block_ids"][0] in stub_anchors for r in rows if r["retrieved_block_ids"]]
    slots = [b in stub_anchors for r in rows for b in r["retrieved_block_ids"][:k]]
    return {"rank1": rate(top1), "topk_slots": rate(slots)}


def outranked(pairs, field: str, k: int) -> dict:
    """Items listing `field` papers: does one rank strictly above every gold document?"""
    flags = []
    for row, item in pairs:
        others = set(item.get(field) or [])
        if not others:
            continue
        ids = row["retrieved_paper_ids"][:k]
        gold = first_rank(ids, gold_papers(row, item)) or INF
        flags.append((first_rank(ids, others) or INF) < gold)
    return rate(flags)


def cross_document(pairs, k: int) -> dict:
    multi = [(r, gold_papers(r, i)) for r, i in pairs if i["tests"] == "answerable"]
    multi = [(r, g) for r, g in multi if len(g) > 1]
    return {
        "all_gold_in_topk": rate([g <= set(r["retrieved_paper_ids"][:k]) for r, g in multi]),
        "any_gold_in_topk": rate([bool(g & set(r["retrieved_paper_ids"][:k])) for r, g in multi]),
    }


def score_stats(rows: list[dict]) -> dict:
    s = sorted(r["top_score"] for r in rows if r.get("top_score") is not None)
    if not s:
        return {"n": 0}
    return {"n": len(s), "min": s[0], "median": statistics.median(s), "max": s[-1]}


def absent_arm(pairs) -> dict:
    ans = [r for r, i in pairs if i["tests"] == "answerable"]
    ab = [(r, i) for r, i in pairs if i["tests"] == "absent"]
    with_d = [(r, i) for r, i in ab if i.get("nearest_distractor_paper_id")]
    return {
        "n_absent": len(ab),
        "top_score_absent": score_stats([r for r, _ in ab]),
        "top_score_answerable": score_stats(ans),
        "nearest_distractor_at_rank1": rate(
            [r["retrieved_paper_ids"][:1] == [i["nearest_distractor_paper_id"]] for r, i in with_d]
        ),
    }


def load_labels(path: Path) -> dict[str, str]:
    labels = {}
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1] in ("on", "borderline", "off"):
            labels[parts[0]] = parts[1]
    return labels


def _contamination(ps, labels, k) -> dict:
    off_share = [
        sum(labels.get(p) == "off" for p in r["retrieved_paper_ids"][:k])
        / len(r["retrieved_paper_ids"][:k])
        for r, _ in ps
        if r["retrieved_paper_ids"]
    ]
    dist = []
    for r, i in ps:
        d = set(i.get("distractor_paper_ids") or [])
        if d:
            ids = r["retrieved_paper_ids"][:k]
            dist.append((first_rank(ids, d) or INF) < (first_rank(ids, gold_papers(r, i)) or INF))
    return {
        "n": len(ps),
        "mean_off_share_topk": statistics.fmean(off_share) if off_share else None,
        "off_at_rank1": rate(
            [
                labels.get(r["retrieved_paper_ids"][0]) == "off"
                for r, _ in ps
                if r["retrieved_paper_ids"]
            ]
        ),
        "distractor_outranks_gold": rate(dist),
    }


def focus_analysis(pairs, labels: dict[str, str], k: int) -> dict:
    on_items = [
        (r, i)
        for r, i in pairs
        if i["tests"] == "answerable"
        and gold_papers(r, i)
        and all(labels.get(p) == "on" for p in gold_papers(r, i))
    ]
    by_dim = defaultdict(list)
    for r, i in on_items:
        by_dim[i["dimension"]].append((r, i))
    legit = []
    for r, i in pairs:
        if i.get("dimension") == "offtopic-legit" and i["tests"] == "answerable":
            la = set(i.get("causal_lookalike_paper_ids") or [])
            ids = r["retrieved_paper_ids"][:k]
            legit.append((first_rank(ids, la) or INF) < (first_rank(ids, gold_papers(r, i)) or INF))
    return {
        "on_gold_answerable": _contamination(on_items, labels, k),
        "by_dimension": {d: _contamination(ps, labels, k) for d, ps in sorted(by_dim.items())},
        "offtopic_legit_lookalike_outranks_gold": rate(legit),
        "chance_baseline_off_share": {
            "hits": sum(v == "off" for v in labels.values()),
            "n": len(labels),
        },
    }


def analyze(report, gt, k, chunk_anchor, members, stub_anchors, labels=None) -> dict:
    pairs = join_ground_truth(report, gt)
    rows = [r for r, _ in pairs]
    out = {
        "n_questions": len(rows),
        "gt_items_not_in_report": len(gt) - len(rows),
        # An errored question has empty retrieved lists and is scored as a miss everywhere below;
        # an EV-10 report marks `run_valid: false`. Both must be visible next to the numbers.
        "n_errored_rows": sum(1 for r in rows if r.get("error")),
        "run_valid": report.get("run_valid"),
        "per_dimension": dimension_table(pairs, k, chunk_anchor, members),
        "stub": stub_analysis(rows, k, stub_anchors),
        "authority_commentary_outranks_gold": outranked(pairs, "commentary_paper_ids", k),
        "edition_other_outranks_gold": outranked(pairs, "other_edition_paper_ids", k),
        "cross_document": cross_document(pairs, k),
        "absent_arm": absent_arm(pairs),
    }
    if labels is not None:
        out["focus"] = focus_analysis(pairs, labels, k)
    return out


# ---------------------------------------------------------------- SQLite (read-only)
def build_db_maps(db_path: Path, paper_ids: set[str]):
    """-> (chunk_id->anchor block id, anchor block id->member block ids, stub anchor ids)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    chunk_anchor, members, stubs = {}, {}, set()
    for pid in sorted(paper_ids):
        idx = dict(con.execute("SELECT block_id, idx FROM blocks WHERE paper_id=?", (pid,)))
        by_idx = sorted((i, b) for b, i in idx.items())
        body_is_stub: dict[str, list[bool]] = defaultdict(list)
        for cid, text, anchor_json in con.execute(
            "SELECT chunk_id, text, anchor_json FROM chunks WHERE paper_id=?", (pid,)
        ):
            a = json.loads(anchor_json)["block_id"]
            chunk_anchor[cid] = a
            body = text.split("\n\n", 1)[1] if "\n\n" in text else text
            body_is_stub[a].append(len(body.strip()) < STUB_BODY_CHARS)
        stubs |= {a for a, flags in body_is_stub.items() if all(flags)}
        starts = sorted(idx[a] for a in body_is_stub if a in idx)
        idxs = [i for i, _ in by_idx]
        for n, s in enumerate(starts):
            e = starts[n + 1] if n + 1 < len(starts) else INF
            lo, hi = bisect.bisect_left(idxs, s), bisect.bisect_left(idxs, e)
            members[by_idx[lo][1]] = {b for _, b in by_idx[lo:hi]}
    con.close()
    return chunk_anchor, members, stubs


# ---------------------------------------------------------------- printing + CLI
def render(path: str, res: dict, k: int) -> str:
    L = [
        f"\n=== {path}  (k={k}, questions={res['n_questions']}, GT items not in"
        f" report={res['gt_items_not_in_report']})"
    ]
    if res["run_valid"] is False or res["n_errored_rows"]:
        L.append(
            f"  WARNING: {res['n_errored_rows']} errored question(s) are scored as misses below"
            + ("; report is marked run_valid=false (INVALID RUN: do not quote these numbers)"
               if res["run_valid"] is False else "")
        )
    L.append("per dimension (answerable only):")
    for d, t in res["per_dimension"].items():
        L.append(
            f"  {d:20} n={t['n']:<3} paperR@k {fmt(t['paper_recall'])} | paperP@1"
            f" {fmt(t['paper_p1'])} | "
            f"anchor hit@k {fmt(t['anchor_hit'])} | anchor P@1 {fmt(t['anchor_p1'])} | "
            f"member hit@k {fmt(t['member_hit'])} | member P@1 {fmt(t['member_p1'])}"
        )
    s = res["stub"]
    L.append(f"stub chunks: rank-1 {fmt(s['rank1'])}; top-k slots {fmt(s['topk_slots'])}")
    L.append(
        f"authority, commentary outranks gold: {fmt(res['authority_commentary_outranks_gold'])}"
    )
    L.append(f"edition, other edition outranks gold: {fmt(res['edition_other_outranks_gold'])}")
    c = res["cross_document"]
    L.append(
        f"cross-document: all gold in top-k {fmt(c['all_gold_in_topk'])}; any"
        f" {fmt(c['any_gold_in_topk'])}"
    )
    a = res["absent_arm"]
    L.append(
        f"absent arm (n={a['n_absent']}): top-score absent"
        f" {a['top_score_absent']} vs answerable {a['top_score_answerable']}"
    )
    L.append(f"  nearest distractor at rank 1: {fmt(a['nearest_distractor_at_rank1'])}")
    if "focus" in res:
        f = res["focus"]
        b = f["chance_baseline_off_share"]
        L.append(f"focus (chance baseline: corpus off share {fmt(b)}):")
        for name, x in [
            ("on-gold answerable", f["on_gold_answerable"]),
            *f["by_dimension"].items(),
        ]:
            m = x["mean_off_share_topk"]
            share = "n/a" if m is None else f"{m:.3f}"
            L.append(
                f"  {name:20} n={x['n']:<3} mean off share of top-k {share}"
                f" | off at rank 1 "
                f"{fmt(x['off_at_rank1'])} | distractor outranks gold"
                f" {fmt(x['distractor_outranks_gold'])}"
            )
        L.append(
            f"  offtopic-legit: lookalike outranks gold"
            f" {fmt(f['offtopic_legit_lookalike_outranks_gold'])}"
        )
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ground-truth", required=True, type=Path)
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--topic-labels", type=Path)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("reports", nargs="+", type=Path)
    args = ap.parse_args(argv)

    gt = {i["question_id"]: i for i in json.loads(args.ground_truth.read_text())["ground_truth"]}
    reports = {str(p): json.loads(p.read_text()) for p in args.reports}
    papers: set[str] = set()
    for rep in reports.values():
        for r in rep["questions"]:
            papers |= set(r["retrieved_paper_ids"][: args.k]) | set(r["gold_paper_ids"])
    for i in gt.values():
        papers |= set(i.get("additional_gold_paper_ids") or [])
    maps = build_db_maps(args.db, papers)
    labels = load_labels(args.topic_labels) if args.topic_labels else None
    results = {}
    for path, rep in reports.items():
        results[path] = analyze(rep, gt, args.k, *maps, labels=labels)
        print(render(path, results[path], args.k))
    if args.json_out:
        args.json_out.write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
