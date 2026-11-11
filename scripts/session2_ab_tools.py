"""Offline arithmetic for the session-2 A/B runs (docs/eval-reports/data/2026-11-11-session2/).

Pure post-processing of `app.retrieval_eval` reports + read-only SQLite (`mode=ro`): no retrieval,
no
network, no GPU, never writes a fixture. Rules live in that directory's PREREGISTRATION.md; this
file
only computes what the run scripts need. Exit codes: 0 ok, 10 = skip this set by its own rule,
11 = validity (jitter) gate failed, 12 = unusable input (fail closed).

  headroom      --strata S.json --report-suffix /papers.json [--min 6]
  stub-ceiling  --report R.json --gt GT --db DB [--min-effect 2] [--json-out F]
  paired        --gt GT --base R --arm R [--db DB] [--flags F] [--label L] [--tag k=v]
                [--tags-from F] [--max-abs-net N] [--json-out F]
  verdict       {depth|stub|ligature} --pair P.json [...]   (depth: --ablated-pair too)
  ligature-flag --gt GT --db DB --out F       (gold chunk holds a census-damaged token?)
  query-repair-check --gt GT [--gt GT ...]    (does query-side repair change any question string?)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.eval_strata_report import (  # noqa: E402  (after sys.path bootstrap)
    build_db_maps,
    first_rank,
    gold_papers,
    passage_ranks,
)
from scripts.list_stub_chunks import stub_chunks  # noqa: E402

SKIP, INVALID, BAD_INPUT = 10, 11, 12
GATING_N = 10  # a stratum with at least this many answerable items can veto
CENSUS = REPO / "docs/eval-reports/data/2026-11-10-ligature-census/census.py"
METRICS = ("member", "paper", "excerpt", "anchor")


def load_gt(path: str) -> dict[str, dict]:
    return {i["question_id"]: i for i in json.loads(Path(path).read_text())["ground_truth"]}


def load_gt_with_text(path: str) -> dict[str, dict]:
    """GT plus `question_text`; the 210 set keeps its text in a sibling
    eval_questions_blind.json."""
    gt = load_gt(path)
    blind = Path(path).with_name("eval_questions_blind.json")
    if blind.is_file():
        for q in json.loads(blind.read_text())["questions"]:
            if q["question_id"] in gt:
                gt[q["question_id"]].setdefault("question_text", q["question_text"])
    missing = [q for q, i in gt.items() if "question_text" not in i]
    if missing:
        raise SystemExit(f"{path}: {len(missing)} items without question_text (e.g. {missing[0]})")
    return gt


def load_report(path: str) -> dict:
    return json.loads(Path(path).read_text())


# ------------------------------------------------------------------ headroom (EV-20 gate)
def headroom(strata: dict, suffix: str) -> dict:
    keys = [k for k in strata if k.endswith(suffix)]
    if len(keys) != 1:
        raise SystemExit(f"{len(keys)} strata entries end with {suffix!r} (need exactly 1)")
    res = strata[keys[0]]
    dims = res["per_dimension"].values()
    scored = sum(d["member_hit"]["n"] for d in dims)
    hits = sum(d["member_hit"]["hits"] for d in dims)
    return {
        "scored": scored,
        "member_hits": hits,
        "headroom": scored - hits,
        "n_errored_rows": res["n_errored_rows"],
        "run_valid": res["run_valid"],
    }


# ------------------------------------------------------------------ per-question flags
def question_flags(row: dict, item: dict, k: int, maps) -> dict:
    out = {"paper": first_rank(row["retrieved_paper_ids"][:k], gold_papers(row, item)) is not None}
    out["member"] = out["excerpt"] = out["anchor"] = None
    scored = bool(item.get("gold_block_id"))
    if maps is not None and scored:
        out["member"] = passage_ranks(row, item, k, maps[0], maps[1])[1] is not None
    if scored and row.get("passage_excerpt_level", {}).get("scored"):
        out["excerpt"] = bool(row["passage_excerpt_level"]["hit"])
    if scored and row.get("passage_level", {}).get("scored"):
        out["anchor"] = bool(row["passage_level"]["hit"])
    return out


def _tally(pairs: list[tuple[bool, bool]]) -> dict:
    wins = sum(a and not b for b, a in pairs)
    losses = sum(b and not a for b, a in pairs)
    return {
        "n": len(pairs),
        "base": sum(b for b, _ in pairs),
        "arm": sum(a for _, a in pairs),
        "wins": wins,
        "losses": losses,
        "net": wins - losses,
    }


def paired(base: dict, arm: dict, gt: dict, maps, k: int, flags: dict | None = None) -> dict:
    b = {r["question_id"]: r for r in base["questions"]}
    a = {r["question_id"]: r for r in arm["questions"]}
    if set(b) != set(a):
        raise SystemExit("base and arm reports cover different question ids")
    missing = [q for q in b if q not in gt]
    if missing:
        raise SystemExit(f"{len(missing)} report question ids not in ground truth: {missing[:3]}")
    ids = [q for q in b if gt[q].get("tests", "answerable") == "answerable"]
    fb = {q: question_flags(b[q], gt[q], k, maps) for q in ids}
    fa = {q: question_flags(a[q], gt[q], k, maps) for q in ids}

    def metrics(qs):
        out = {}
        for m in METRICS:
            both = [
                (fb[q][m], fa[q][m]) for q in qs if fb[q][m] is not None and fa[q][m] is not None
            ]
            if both:
                out[m] = _tally(both)
        return out

    groups: dict[str, list[str]] = {}
    for q in ids:
        dim = gt[q].get("dimension") or b[q].get("question_type") or "all"
        groups.setdefault(f"dimension={dim}", []).append(q)
    if flags is not None:
        for q in ids:
            v = flags.get(q)
            tag = "unknown" if v is None else ("damaged" if v else "clean")
            groups.setdefault(f"ligature={tag}", []).append(q)
    strata = {g: {"n": len(qs), "metrics": metrics(qs)} for g, qs in sorted(groups.items())}
    total = metrics(ids)
    gate = "member" if "member" in total else "paper"
    worst = min(
        (
            s["metrics"][gate]["net"]
            for g, s in strata.items()
            if g.startswith("dimension=") and s["n"] >= GATING_N and gate in s["metrics"]
        ),
        default=0,
    )
    return {
        "n_answerable": len(ids),
        "n_errored_base": sum(bool(r.get("error")) for r in b.values()),
        "n_errored_arm": sum(bool(r.get("error")) for r in a.values()),
        "run_valid": [base.get("run_valid"), arm.get("run_valid")],
        "gating_metric": gate,
        "metrics": total,
        "strata": strata,
        "worst_stratum_net": worst,  # most negative net among dimension strata with n >= 10
    }


def render_paired(p: dict) -> str:
    L = [
        f"label={p.get('label')} tags={p.get('tags')} answerable={p['n_answerable']} "
        f"errored base/arm={p['n_errored_base']}/{p['n_errored_arm']} run_valid={p['run_valid']}"
    ]
    for m, t in p["metrics"].items():
        L.append(
            f"  {m:8s} n={t['n']:3d} base={t['base']:3d} arm={t['arm']:3d} "
            f"wins={t['wins']} losses={t['losses']} net={t['net']:+d}"
        )
    for g, s in p["strata"].items():
        cells = " ".join(
            f"{m}:{t['base']}->{t['arm']}({t['net']:+d})" for m, t in s["metrics"].items()
        )
        gating = " [gating]" if g.startswith("dimension=") and s["n"] >= GATING_N else ""
        L.append(f"  {g:34s} n={s['n']:3d}{gating} {cells}")
    L.append(f"  worst gating-stratum net ({p['gating_metric']}): {p['worst_stratum_net']:+d}")
    return "\n".join(L)


# ------------------------------------------------------------------ stub ceiling (EV-12/21)
def stub_ceiling(report: dict, gt: dict, maps, stub_ids: set[str], k: int, min_effect: int) -> dict:
    rows = [r for r in report["questions"] if r["question_id"] in gt]
    if any("retrieved_chunk_ids" not in r for r in rows):
        raise SystemExit("baseline rows lack retrieved_chunk_ids (pre-EV-9 report): no ceiling")

    def is_stub(cands: list[str]) -> bool:
        return bool(cands) and all(c in stub_ids for c in cands)

    ans = [r for r in rows if gt[r["question_id"]].get("tests", "answerable") == "answerable"]
    live = [r for r in rows if not r.get("error")]
    rank1 = sum(
        bool(r["retrieved_chunk_ids"]) and is_stub(r["retrieved_chunk_ids"][0]) for r in ans
    )
    slots = [is_stub(c) for r in live for c in r["retrieved_chunk_ids"][:k]]
    ceiling = with_stub = 0
    for r in ans:
        if not any(is_stub(c) for c in r["retrieved_chunk_ids"][:k]):
            continue
        with_stub += 1
        item = gt[r["question_id"]]
        if item.get("gold_block_id") and passage_ranks(r, item, k, maps[0], maps[1])[1] is None:
            ceiling += 1
    return {
        "n_answerable": len(ans),
        "stub_rank1_answerable": rank1,
        "stub_slots_topk": sum(slots),
        "slots_topk": len(slots),
        "stub_slot_share": sum(slots) / len(slots) if slots else 0.0,
        "answerable_with_stub_in_topk": with_stub,
        "ceiling": ceiling,
        "min_effect": min_effect,
        "run": ceiling >= min_effect,
    }


# ------------------------------------------------------------------ verdicts
def verdict_depth(pair: dict, ablated: dict | None) -> dict:
    m, worst = pair["metrics"]["member"], pair["worst_stratum_net"]
    prefer_128 = m["net"] >= 2 and worst >= -1
    g1 = m["net"] >= 3 and m["wins"] >= 3 * m["losses"] and worst >= -1
    sign = None if ablated is None else ablated["metrics"]["member"]["net"] > 0
    return {
        "set": pair.get("label"),
        "net_128_minus_32": m["net"],
        "wins_losses": [m["wins"], m["losses"]],
        "worst_stratum_net": worst,
        "rule_ge2_prefers": "128 (provisional)" if prefer_128 else "32",
        "G1_core": g1,
        "G1_ablated_same_sign": sign,
        "recommend_default_change": bool(prefer_128 and g1 and sign),
    }


def verdict_stub(pairs: list[dict]) -> dict:
    sets = {}
    for p in pairs:
        m = p["metrics"]["member"]
        r1 = p["tags"]["ceiling"]["stub_rank1_answerable"]
        sets[p["label"]] = {
            "net": m["net"],
            "stub_rank1": r1,
            "worst_stratum_net": p["worst_stratum_net"],
        }
    qualifying = [s for s, v in sets.items() if v["stub_rank1"] > 0 and v["net"] >= 2]
    vetoes = [s for s, v in sets.items() if v["worst_stratum_net"] <= -2]
    return {
        "sets": sets,
        "improving_sets_with_stub_at_rank1": qualifying,
        "stratum_vetoes": vetoes,
        "verdict": "ADOPT" if qualifying and not vetoes else "REJECT",
    }


def verdict_ligature(pairs: list[dict]) -> dict:
    """CQ-2 runbook rule; arm = clone (candidate), base = live (baseline)."""

    def get(label, mode):
        return next(
            (p for p in pairs if p["label"] == label and p["tags"].get("mode") == mode), None
        )

    a_pair = get("papers", "sparse_only")
    a = None if a_pair is None else a_pair["metrics"]["paper"]["net"] > 0
    b, missing = {}, []
    for label in ("papers", "books"):
        p = get(label, "fused")
        if p is None:
            missing.append(label)
            continue
        b[label] = (
            p["metrics"]["paper"]["net"] >= -1
            and p["metrics"].get("member", {"net": 0})["net"] >= -1
        )
    failed = a is False or not all(b.values())
    if a is None or missing:
        verdict = "INCOMPLETE (a measured clause is missing)"
    elif failed:
        verdict = "REJECT"
    else:
        verdict = "ADOPT-PENDING-STANDARDS"
    return {
        "a_sparse_only_papers_recall_strictly_higher": a,
        "b_fused_no_worse_than_minus_1": b,
        "missing": missing,
        "verdict": verdict,
    }


# ------------------------------------------------------------------ ligature flag / query check
def _census():
    spec = importlib.util.spec_from_file_location("ligature_census", CENSUS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ligature_flags(gt: dict, db: str, broken_re=None) -> dict[str, bool | None]:
    broken_re = broken_re or _census().BROKEN_RE
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out: dict[str, bool | None] = {}
    try:
        for qid, item in gt.items():
            row = con.execute(
                "select text from chunks where chunk_id=?", (item.get("gold_chunk_id"),)
            ).fetchone()
            out[qid] = None if row is None else bool(broken_re.search(row[0] or ""))
    finally:
        con.close()
    return out


def changed_by_query_repair(gt: dict, repair) -> list[str]:
    """Mirror of `_sparse_vector`'s query handling: repair(text.lower()) vs text.lower()."""
    return [
        q for q, i in gt.items() if repair(i["question_text"].lower()) != i["question_text"].lower()
    ]


# ------------------------------------------------------------------ CLI
def _maps(gt: dict, reports: list[dict], db: str, k: int):
    papers: set[str] = set()
    for rep in reports:
        for r in rep["questions"]:
            papers |= set(r["retrieved_paper_ids"][:k]) | set(r["gold_paper_ids"])
    for i in gt.values():
        papers |= set(i.get("additional_gold_paper_ids") or [])
    return build_db_maps(Path(db), papers)


def _emit(obj: dict, path: str | None) -> None:
    if path:
        Path(path).write_text(json.dumps(obj, indent=2))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("headroom")
    p.add_argument("--strata", required=True)
    p.add_argument("--report-suffix", required=True)
    p.add_argument("--min", type=int, default=6)
    p = sub.add_parser("stub-ceiling")
    p.add_argument("--report", required=True)
    p.add_argument("--gt", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--min-effect", type=int, default=2)
    p.add_argument("--json-out")
    p = sub.add_parser("paired")
    p.add_argument("--gt", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--arm", required=True)
    p.add_argument("--db")
    p.add_argument("--flags")
    p.add_argument("--label")
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--tags-from")
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--max-abs-net", type=int)
    p.add_argument("--json-out")
    p = sub.add_parser("verdict")
    p.add_argument("rule", choices=["depth", "stub", "ligature"])
    p.add_argument("--pair", action="append", required=True)
    p.add_argument("--ablated-pair")
    p = sub.add_parser("ligature-flag")
    p.add_argument("--gt", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("query-repair-check")
    p.add_argument("--gt", action="append", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "headroom":
        h = headroom(json.loads(Path(args.strata).read_text()), args.report_suffix)
        print(json.dumps(h))
        if h["n_errored_rows"] or h["run_valid"] is False:
            print("baseline arm has errored rows / run_valid false: not usable", file=sys.stderr)
            return BAD_INPUT
        return 0 if h["headroom"] >= args.min else SKIP

    if args.cmd == "stub-ceiling":
        gt, rep = load_gt(args.gt), load_report(args.report)
        res = stub_ceiling(
            rep,
            gt,
            _maps(gt, [rep], args.db, args.k),
            {c for c, _, _ in stub_chunks(args.db)},
            args.k,
            args.min_effect,
        )
        print(json.dumps(res))
        _emit(res, args.json_out)
        return 0 if res["run"] else SKIP

    if args.cmd == "paired":
        gt, base, arm = load_gt(args.gt), load_report(args.base), load_report(args.arm)
        maps = _maps(gt, [base, arm], args.db, args.k) if args.db else None
        flags = json.loads(Path(args.flags).read_text()) if args.flags else None
        res = paired(base, arm, gt, maps, args.k, flags)
        res["label"] = args.label
        res["tags"] = dict(t.split("=", 1) for t in args.tag)
        if args.tags_from:
            res["tags"]["ceiling"] = json.loads(Path(args.tags_from).read_text())
        print(render_paired(res))
        _emit(res, args.json_out)
        gate = res["metrics"][res["gating_metric"]]["net"]
        if args.max_abs_net is not None and abs(gate) > args.max_abs_net:
            print(f"VALIDITY GATE FAILED: |net| {abs(gate)} > {args.max_abs_net}", file=sys.stderr)
            return INVALID
        return 0

    if args.cmd == "verdict":
        pairs = [json.loads(Path(f).read_text()) for f in args.pair]
        if args.rule == "depth":
            abl = json.loads(Path(args.ablated_pair).read_text()) if args.ablated_pair else None
            out = verdict_depth(pairs[0], abl)
        else:
            out = (verdict_stub if args.rule == "stub" else verdict_ligature)(pairs)
        print(json.dumps(out, indent=2))
        return 0

    if args.cmd == "ligature-flag":
        gt = load_gt(args.gt)
        flags = ligature_flags(gt, args.db)
        Path(args.out).write_text(json.dumps(flags, indent=2))
        vals = list(flags.values())
        print(f"damaged={vals.count(True)} clean={vals.count(False)} unknown={vals.count(None)}")
        # absent items carry no gold chunk: unknown by design, not bad input
        lost = [q for q, v in flags.items() if v is None and gt[q].get("gold_chunk_id")]
        return 0 if not lost else BAD_INPUT

    from rag.ligatures import repair_ligatures

    bad = {}
    for path in args.gt:
        bad[path] = changed_by_query_repair(load_gt_with_text(path), repair_ligatures)
        print(f"{path}: {len(bad[path])} question strings changed by query-side repair")
    return 0 if not any(bad.values()) else BAD_INPUT


if __name__ == "__main__":
    sys.exit(main())
