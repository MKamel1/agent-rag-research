"""`python -m scripts.nb_c2_anchor_probe` -- NB-C2 pre-retrieval lexical anchor-coverage probe.

Ticket NB-C2 (A-series C2, per `docs/eval-reports/2026-08-25-nb-a1-abstention-signal-design.md`
§C2). Measures ONE feature per question -- the fraction of the question's high-IDF lexical
anchor tokens that have >=1 corpus hit under sparse-only presence queries against the
`waymo_av_safety` collection -- and evaluates A-1's PRE-COMMITTED falsification criterion on
both fixtures. Measurement only: decides nothing at serve time, builds no mechanism.

Subcommands:
  capture --fixtures ver84 gt_wmr  extract anchors + probe presence -> <name>_anchors.json
  analyze                          AUROC / best-cut FP-FN / Spearman guard -> results.json

The falsification criterion and extractor rules were frozen in the stub commit
(docs/eval-reports/2026-08-25-nb-c2-anchor-probe.md §1-§2) BEFORE any label-bearing run;
neither this script nor its flags can retune them.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

from rag.vector_index import _sparse_vector

logger = logging.getLogger(__name__)

_QDRANT_BASE_URL = "http://localhost:6333"  # app/assembly.py's own _QDRANT_HOST/_QDRANT_PORT
_COLLECTION_DEFAULT = "waymo_av_safety"  # programme constraint 8: always explicit
_FIXTURES = {
    "ver84": Path("fixtures/eval/waymo_gt_verified.json"),
    "gt_wmr": Path("fixtures/eval/gt_wmr.json"),
}
_OUT_DIR_DEFAULT = Path("docs/eval-reports/data/2026-08-25-nb-c2")

# --- Frozen anchor-extraction rules (stub-commit §2; do not retune) -------------------------
_RARE_PROXY_MIN_ALPHA = 11  # R4: length proxy for high-IDF rare terms (no client-side df)


def extract_anchor_tokens(text: str) -> list[tuple[str, str]]:
    """Returns deduped `(probe_form, rule)` pairs, in first-occurrence order.

    One rule per whitespace token, first match wins (frozen precedence):
      R1 numeric     -- token contains any digit ("0.31", "24", "85%", "1,000")
      R2 acronym     -- every letter in the token is uppercase, >=2 letters ("VRU")
      R3 entity      -- capitalized token NOT at sentence start (a sentence starts at the
                        beginning of the text and after any token ending in . ! ?)
      R4 rare-proxy  -- >=11 alphabetic characters ("teleoperation"); a length proxy because
                        no leak-free client-side document-frequency table exists
    Probe form is `token.lower()` VERBATIM -- punctuation included -- exactly matching
    `_sparse_vector`'s own `text.lower().split()` tokenization on the indexed side.
    """
    anchors: list[tuple[str, str]] = []
    seen: set[str] = set()
    at_sentence_start = True
    for token in text.split():
        rule: str | None = None
        if any(ch.isdigit() for ch in token):
            rule = "numeric"
        else:
            letters = [ch for ch in token if ch.isalpha()]
            if len(letters) >= 2 and all(ch.isupper() for ch in letters):
                rule = "acronym"
            elif token[:1].isupper() and not at_sentence_start:
                rule = "entity"
            elif sum(ch.isalpha() for ch in token) >= _RARE_PROXY_MIN_ALPHA:
                rule = "rare_proxy"
        at_sentence_start = token[-1] in ".!?"
        if rule is None:
            continue
        probe_form = token.lower()
        if probe_form not in seen:
            seen.add(probe_form)
            anchors.append((probe_form, rule))
    return anchors


# --- Presence probing (read-only Qdrant REST) -----------------------------------------------


def sparse_presence(base_url: str, collection: str, token: str, timeout_s: float = 15.0) -> bool:
    """True iff at least one point in `collection` contains `token` under `_sparse_vector`'s
    exact hashed index. Single-term sparse query: points sharing none of the query's index
    dimensions cannot match, so a returned point with score > 0 means the token exists in
    >=1 stored payload text. Query failures raise -- a failed probe must abort the run rather
    than silently masquerade as an absence hit.
    """
    vector = _sparse_vector(token)
    body = {
        "query": {"indices": list(vector.indices), "values": list(vector.values)},
        "using": "sparse",
        "limit": 1,
        "with_payload": False,
    }
    request = urllib.request.Request(
        f"{base_url}/collections/{collection}/points/query",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.load(response)
    except urllib.error.URLError as e:
        msg = f"sparse presence query failed for token {token!r}: {e}"
        raise RuntimeError(msg) from e
    points = payload.get("result", {}).get("points", [])
    return any(float(point.get("score", 0.0)) > 0.0 for point in points)


# --- Capture --------------------------------------------------------------------------------


def capture_fixture(name: str, fixture_path: Path, base_url: str, collection: str) -> dict:
    """Probes every question's anchors once each (global per-run cache) and returns the
    fixture record. Extraction sees question TEXT only; labels are carried alongside for
    `analyze` and never influence which tokens are extracted."""
    from app.retrieval_eval import load_questions  # deferred: keeps analyze import-light

    questions = load_questions(fixture_path)
    presence_cache: dict[str, bool] = {}
    records: list[dict] = []
    started = time.monotonic()
    for i, question in enumerate(questions, start=1):
        anchor_pairs = extract_anchor_tokens(question.question_text)
        anchor_entries = []
        for probe_form, rule in anchor_pairs:
            if probe_form not in presence_cache:
                presence_cache[probe_form] = sparse_presence(base_url, collection, probe_form)
            anchor_entries.append(
                {"token": probe_form, "rule": rule, "hit": presence_cache[probe_form]}
            )
        n_hits = sum(1 for entry in anchor_entries if entry["hit"])
        records.append(
            {
                "question_id": question.question_id,
                # Label partition exactly as D3 used it (by_gold_status equivalent):
                # known-absent <=> empty gold set after load_questions' dedup.
                "absent": not question.gold_paper_ids,
                "query_len_chars": len(question.question_text),
                "query_len_words": len(question.question_text.split()),
                "anchors": anchor_entries,
                "n_anchors": len(anchor_entries),
                "n_hits": n_hits,
                "hit_rate": (n_hits / len(anchor_entries)) if anchor_entries else None,
            }
        )
        if i % 20 == 0:
            logger.info("%s: probed %d/%d questions", name, i, len(questions))
    n_absent = sum(1 for r in records if r["absent"])
    return {
        "fixture": name,
        "fixture_path": str(fixture_path),
        "collection": collection,
        "n_questions": len(records),
        "n_absent": n_absent,
        "n_answerable": len(records) - n_absent,
        "n_distinct_anchor_tokens_probed": len(presence_cache),
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "questions": records,
    }


# --- Analysis (offline, label-bearing) -------------------------------------------------------


def _average_ranks(values: list[float]) -> list[float]:
    """Ranks 1..n with ties assigned their average rank (Spearman/Mann-Whitney convention)."""
    order = sorted(range(len(values)), key=lambda idx: values[idx])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        mean_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = mean_rank
        i = j + 1
    return ranks


def _brute_force_auroc(pos: list[float], neg: list[float]) -> float:
    """P(pos > neg) + 0.5 * P(equal), by direct pairwise counting (D3's definition)."""
    total = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                total += 1.0
            elif p == n:
                total += 0.5
    return total / (len(pos) * len(neg))


def auroc_pos_higher(pos: list[float], neg: list[float]) -> float:
    """Rank-based Mann-Whitney AUROC, P(pos > neg) + 0.5·P(equal); verified against brute-
    force pairwise counting on every call (same implementation-verification posture D3 §2
    used). The rank-based path exists so ties get average-rank handling while staying honest.
    """
    if not pos or not neg:
        msg = "AUROC needs both arms non-empty"
        raise ValueError(msg)
    combined = [(v, 1) for v in pos] + [(v, 0) for v in neg]
    ranks = _average_ranks([v for v, _ in combined])
    rank_sum_pos = sum(rank for rank, (_, label) in zip(ranks, combined, strict=True) if label == 1)
    n_pos, n_neg = len(pos), len(neg)
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2
    value = u / (n_pos * n_neg)
    brute = _brute_force_auroc(pos, neg)
    if math.isclose(value, brute, abs_tol=1e-12):
        return value
    msg = f"rank-based AUROC {value!r} != brute-force {brute!r}"
    raise AssertionError(msg)


def best_youden_cut(absent_rates: list[float], answerable_rates: list[float]) -> dict:
    """Best-Youden-J cut over every observed rate value; ABSTAIN if hit_rate < cut (D3's
    strict-< convention, so boundary ties resolve toward answering). Deterministic tie-break:
    higher TPR, then lower FP, then the lower threshold."""
    candidates = sorted(set(absent_rates) | set(answerable_rates))
    n_absent, n_answ = len(absent_rates), len(answerable_rates)
    best: dict | None = None
    for cut in candidates:
        fn = sum(1 for r in absent_rates if r >= cut)  # absent NOT flagged for abstention
        tp = n_absent - fn
        fp = sum(1 for r in answerable_rates if r < cut)
        tpr = tp / n_absent
        fpr = fp / n_answ
        j = tpr - fpr
        key = (j, tpr, -fp, -cut)
        if best is None or key > best["_key"]:
            best = {
                "_key": key,
                "threshold": cut,
                "FP": fp,
                "FN": fn,
                "TP_caught": tp,
                "TPR": round(tpr, 4),
                "FPR": round(fpr, 4),
                "youden_j": round(j, 4),
            }
    assert best is not None  # candidates is non-empty when both arms are non-empty
    del best["_key"]
    return best


def spearman_rho(xs: list[float], ys: list[float]) -> float:
    """Spearman correlation via average ranks + Pearson on the ranks (ties handled)."""
    if len(xs) != len(ys) or len(xs) < 2:
        msg = f"Spearman needs equal-length inputs >=2, got {len(xs)}/{len(ys)}"
        raise ValueError(msg)
    rx, ry = _average_ranks(xs), _average_ranks(ys)
    n = len(xs)
    mean_x, mean_y = sum(rx) / n, sum(ry) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True))
    var_x = sum((a - mean_x) ** 2 for a in rx)
    var_y = sum((b - mean_y) ** 2 for b in ry)
    if var_x == 0.0 or var_y == 0.0:
        return 0.0  # a constant series carries no monotone association
    return cov / math.sqrt(var_x * var_y)


def _rule_breakdown(records: list[dict]) -> dict[str, dict]:
    """Informational per-rule presence rates per arm (where does any signal live?)."""
    out: dict[str, dict] = {}
    for arm in ("answerable", "absent"):
        wanted = arm == "absent"
        by_rule: dict[str, tuple[int, int]] = {}
        for rec in records:
            if rec["absent"] is not wanted:
                continue
            for entry in rec["anchors"]:
                hits, total = by_rule.get(entry["rule"], (0, 0))
                by_rule[entry["rule"]] = (hits + (1 if entry["hit"] else 0), total + 1)
        out[arm] = {
            rule: {"hits": h, "n": t, "rate": round(h / t, 4)}
            for rule, (h, t) in sorted(by_rule.items())
        }
    return out


def analyze(data_dir: Path) -> dict:
    """Evaluates the pre-committed criterion verbatim on both fixtures; `main()` persists the
    returned dict to <data_dir>/results.json."""
    criterion_text = [
        "AUROC(hit_rate) >= 0.75 on BOTH fixtures (absent-lower orientation)",
        'best-cut FP <=10/68 (ver84) and <=10/70 (gt_wmr) at FN <=25%',
        "Spearman |rho|(hit_rate, query length) <= 0.8 for chars AND words, both fixtures",
    ]
    fixtures_out: dict[str, dict] = {}
    for name in sorted(_FIXTURES):
        path = data_dir / f"{name}_anchors.json"
        data = json.loads(path.read_text())
        records = [r for r in data["questions"] if r["n_anchors"] > 0]
        excluded = len(data["questions"]) - len(records)
        absent = [r["hit_rate"] for r in records if r["absent"]]
        answ = [r["hit_rate"] for r in records if not r["absent"]]
        # Pre-stated orientation: the mechanism predicts absent items score LOWER (fewer
        # covered anchors), so AUROC is oriented as P(answerable > absent) (+1/2 ties); the
        # raw opposite direction is recorded alongside.
        oriented = auroc_pos_higher(answ, absent)
        raw_direction = 1.0 - oriented
        cut = best_youden_cut(absent, answ)
        lens_chars = [float(r["query_len_chars"]) for r in records]
        lens_words = [float(r["query_len_words"]) for r in records]
        rates = [float(r["hit_rate"]) for r in records]
        rho_chars = spearman_rho(rates, lens_chars)
        rho_words = spearman_rho(rates, lens_words)
        n_absent, n_answ = len(absent), len(answ)
        fixtures_out[name] = {
            "data_file": str(path),
            "n_used": len(records),
            "n_zero_anchor_excluded": excluded,
            "n_answerable": n_answ,
            "n_absent": n_absent,
            "auroc_oriented_answerable_higher": round(oriented, 4),
            "raw_direction_auroc_P_absent_higher": round(raw_direction, 4),
            "best_cut": cut,
            "fp_within_le_10": cut["FP"] <= 10,
            "fn_fraction": round(cut["FN"] / n_absent, 4),
            "fn_within_le_25pct": cut["FN"] <= 0.25 * n_absent,
            "spearman_len_chars": round(rho_chars, 4),
            "spearman_len_words": round(rho_words, 4),
            "rule_breakdown_by_arm": _rule_breakdown(records),
        }

    def both(pred):  # noqa: ANN001 - tiny local helper over the two fixture dicts
        return all(pred(fixtures_out[name]) for name in fixtures_out)

    checks = {
        "criterion": criterion_text,
        "auroc_both_fixtures_ge_075": both(
            lambda f: f["auroc_oriented_answerable_higher"] >= 0.75
        ),
        "best_cut_fp_and_fn_both_fixtures": both(
            lambda f: f["fp_within_le_10"] and f["fn_within_le_25pct"]
        ),
        "leakage_guard_ok": both(
            lambda f: abs(f["spearman_len_chars"]) <= 0.8
            and abs(f["spearman_len_words"]) <= 0.8
        ),
    }
    verdict = (
        "PROMOTED"
        if checks["auroc_both_fixtures_ge_075"]
        and checks["best_cut_fp_and_fn_both_fixtures"]
        and checks["leakage_guard_ok"]
        else "DEAD"
    )
    return {"fixtures": fixtures_out, "checks": checks, "verdict": verdict}


def print_results(results: dict) -> None:
    for name, fx in results["fixtures"].items():
        cut = fx["best_cut"]
        logger.info(
            "%s: n=%d (%d answ/%d absent, %d zero-anchor excl) AUROC=%.4f "
            "(raw dir %.4f) | abstain<%.4f: FP=%d/%d FN=%d/%d (%.1f%%) J=%.4f | "
            "rho_chars=%+.4f rho_words=%+.4f",
            name,
            fx["n_used"],
            fx["n_answerable"],
            fx["n_absent"],
            fx["n_zero_anchor_excluded"],
            fx["auroc_oriented_answerable_higher"],
            fx["raw_direction_auroc_P_absent_higher"],
            cut["threshold"],
            cut["FP"],
            fx["n_answerable"],
            cut["FN"],
            fx["n_absent"],
            100 * fx["fn_fraction"],
            cut["youden_j"],
            fx["spearman_len_chars"],
            fx["spearman_len_words"],
        )
    logger.info("checks: %s", json.dumps(results["checks"], indent=2))
    logger.info("VERDICT: %s", results["verdict"])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="extract anchors + probe presence (needs Qdrant UP)")
    cap.add_argument("--fixtures", nargs="*", choices=sorted(_FIXTURES), default=None,
                     help="subset to run; default = both")
    cap.add_argument("--collection", default=_COLLECTION_DEFAULT)
    cap.add_argument("--qdrant-base-url", default=_QDRANT_BASE_URL)
    cap.add_argument("--out-dir", type=Path, default=_OUT_DIR_DEFAULT)

    ana = sub.add_parser("analyze", help="evaluate the pre-committed criterion (offline)")
    ana.add_argument("--data-dir", type=Path, default=_OUT_DIR_DEFAULT)

    args = parser.parse_args()
    if args.command == "capture":
        args.out_dir.mkdir(parents=True, exist_ok=True)
        names = args.fixtures or sorted(_FIXTURES)
        for name in names:
            result = capture_fixture(name, _FIXTURES[name], args.qdrant_base_url, args.collection)
            out_path = args.out_dir / f"{name}_anchors.json"
            out_path.write_text(json.dumps(result, indent=2))
            logger.info("wrote %s (%d questions, %d distinct tokens probed, %.1fs)",
                        out_path, result["n_questions"],
                        result["n_distinct_anchor_tokens_probed"], result["elapsed_seconds"])
    else:
        results = analyze(args.data_dir)
        out_path = args.data_dir / "results.json"
        out_path.write_text(json.dumps(results, indent=2))
        logger.info("wrote %s", out_path)
        print_results(results)


if __name__ == "__main__":
    main()
