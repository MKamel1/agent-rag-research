"""EV-14 (shrunk): approximate vs exact filtered dense search, read-only, plain HTTP, no embedder.

    python filtered_search_check.py --collection papers [--n 100] [--seed 20261111] [--k 10]
        [--url http://localhost:6333] --out-json OUT.json

Why plain HTTP and not the adapter: the vendor SDK may only be imported in rag/vector_index.py and
that module has no exact-search method; this script lives under docs/ (outside the CI
vendor-isolation
scope, which covers rag/, contracts/, app/ only) and speaks the store's REST API directly.
Only three calls are ever made (anything else raises): GET /collections/<c>,
POST /collections/<c>/points/scroll, POST /collections/<c>/points/query. See SESSION2-README.md
for bodies.

Sampling is seeded: a pseudo-random point id (uuid from random.Random(seed)) is the scroll
`offset`, so the
first point at or after it that satisfies the filter family is the sample. Query vector = that
point's
stored `dense` vector; its own id is dropped from both result lists (k+1 requested).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.request
import uuid
from pathlib import Path

BINDING = ("F1", "F3", "F4", "F6")  # PREREGISTRATION.md section 4
FALSIFIER = 0.99
PAPER_OR_MISSING = {
    "should": [
        {"key": "doc_type", "match": {"value": "paper"}},
        {"is_empty": {"key": "doc_type"}},
    ]
}


def eq(key: str, value) -> dict:
    return {"key": key, "match": {"value": value}}


# name -> (description, population conditions (sampled points satisfy them), per-point extra
# condition)
FILTERS = {
    "F1": ("kind=summary", [eq("kind", "summary")], None),
    "F2": ("kind=chunk", [eq("kind", "chunk")], None),
    "F3": ("kind=summary doc_type=book", [eq("kind", "summary"), eq("doc_type", "book")], None),
    "F4": ("kind=chunk doc_type=book", [eq("kind", "chunk"), eq("doc_type", "book")], None),
    "F5": ("kind=chunk doc_type=paper", [eq("kind", "chunk"), PAPER_OR_MISSING], None),
    "F6": ("kind=chunk paper_id=<own>", [eq("kind", "chunk")], "paper_id"),
    "F7": ("kind=summary categories any-of own", [eq("kind", "summary")], "categories"),
    "F8": ("kind=chunk categories any-of own", [eq("kind", "chunk")], "categories"),
}


def query_filter(name: str, payload: dict) -> dict | None:
    """The filter body for one sampled point, or None if it cannot form one (e.g. no categories)."""
    _, conds, extra = FILTERS[name]
    must = list(conds)
    if extra == "paper_id":
        must.append(eq("paper_id", payload["paper_id"]))
    elif extra == "categories":
        if not payload.get("categories"):
            return None
        must.append({"key": "categories", "match": {"any": list(payload["categories"])}})
    return {"must": must}


def overlap(approx: list[str], exact: list[str]) -> float:
    return len(set(approx) & set(exact)) / len(exact) if exact else 1.0


class ReadOnlyHttp:
    def __init__(self, url: str, collection: str):
        self.url, self.c = url.rstrip("/"), collection
        self.calls = 0

    def _go(self, req: urllib.request.Request) -> dict:
        self.calls += 1
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)["result"]

    def info(self) -> dict:
        return self._go(urllib.request.Request(f"{self.url}/collections/{self.c}"))

    def post(self, endpoint: str, body: dict) -> dict:
        if endpoint not in ("points/scroll", "points/query"):
            raise ValueError(f"refusing non-read endpoint {endpoint!r}")
        req = urllib.request.Request(
            f"{self.url}/collections/{self.c}/{endpoint}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        return self._go(req)


def sample_points(http, name: str, n: int, rng: random.Random) -> list[dict]:
    out, seen, tries = [], set(), 0
    while len(out) < n and tries < n * 5:
        tries += 1
        body = {
            "filter": {"must": FILTERS[name][1]},
            "limit": 1,
            "with_payload": ["paper_id", "kind", "doc_type", "categories"],
            "with_vector": ["dense"],
            "offset": str(uuid.UUID(int=rng.getrandbits(128))),
        }
        pts = http.post("points/scroll", body)["points"]
        if not pts:  # offset past the last matching id: try another
            continue
        p = pts[0]
        if p["id"] not in seen and query_filter(name, p["payload"]) is not None:
            seen.add(p["id"])
            out.append(p)
    return out


def search_ids(http, vec, flt, k: int, exact: bool, own_id) -> list[str]:
    body = {
        "query": vec,
        "using": "dense",
        "filter": flt,
        "limit": k + 1,
        "params": {"exact": exact},
        "with_payload": False,
    }
    ids = [p["id"] for p in http.post("points/query", body)["points"] if p["id"] != own_id]
    return ids[:k]


def run_filter(http, name: str, n: int, k: int, rng: random.Random) -> dict:
    pts = sample_points(http, name, n, rng)
    ovs, short = [], 0
    for p in pts:
        flt = query_filter(name, p["payload"])
        vec = p["vector"]["dense"] if isinstance(p["vector"], dict) else p["vector"]
        approx = search_ids(http, vec, flt, k, False, p["id"])
        exact = search_ids(http, vec, flt, k, True, p["id"])
        short += len(exact) < k or len(approx) < k
        ovs.append(overlap(approx, exact))
    return {
        "filter": FILTERS[name][0],
        "n": len(ovs),
        "mean_overlap": sum(ovs) / len(ovs) if ovs else None,
        "min_overlap": min(ovs, default=None),
        "share_perfect": sum(o == 1.0 for o in ovs) / len(ovs) if ovs else None,
        "n_short_lists": short,
    }


def verdict(results: dict) -> str:
    binding = {f: results[f] for f in BINDING if results[f]["n"]}
    if not binding:
        return "NO DATA: no binding filter had a population"
    below = [f for f, r in binding.items() if r["mean_overlap"] < FALSIFIER]
    if below:
        return f"CQ-9 TRIGGER MET: binding filters below {FALSIFIER}: {below}"
    if not any(r["n_short_lists"] for r in results.values()):
        return "CLOSE CQ-9 (all binding >= 0.99; also no short result list anywhere)"
    return "CLOSE CQ-9 (all binding filters >= 0.99)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--collection", required=True)
    ap.add_argument("--url", default="http://localhost:6333")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261111)
    ap.add_argument("--out-json", required=True)
    a = ap.parse_args(argv)
    http = ReadOnlyHttp(a.url, a.collection)
    info = http.info()
    print(
        f"collection={a.collection} points={info['points_count']} "
        f"payload_schema={json.dumps(info.get('payload_schema', {}))}"
    )
    rng = random.Random(a.seed)
    results = {}
    for name in FILTERS:
        results[name] = run_filter(http, name, a.n, a.k, rng)
        r = results[name]
        print(
            f"{name} {r['filter']:38s} n={r['n']:3d} mean={r['mean_overlap']} "
            f"min={r['min_overlap']} short={r['n_short_lists']}",
            flush=True,
        )
    out = {
        "collection": a.collection,
        "seed": a.seed,
        "k": a.k,
        "falsifier": FALSIFIER,
        "binding": BINDING,
        "results": results,
        "verdict": verdict(results),
        "http_calls": http.calls,
    }
    Path(a.out_json).write_text(json.dumps(out, indent=2))
    print("verdict:", out["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
