"""Backfill the `curated` author-org tag onto an already-built corpus.

The corpus was ingested before T-ORG3 wired `curated_orgs_for()` into
`rag/orchestrator.py::_finish`, so every `papers.author_orgs` row is NULL and every Qdrant point
is missing the `author_orgs`/`curated_author_orgs` payload keys -- which is what
`SearchFilters.author_org_curated_only` filters against (`rag/vector_index.py:161`). Re-ingesting
1,745 papers to recover a fact that is pure set membership would be absurd; this writes the same
values `_finish` would have written, in both stores.

Only the `curated` tier is backfilled. That tier is an enumerated fact (the org's own published
research index), exact by construction -- unlike the `email_domain`/`keyword` heuristics, which
measure precision 0.706 and would need the parsed Blocks to recompute.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
CURATED_VALUE = [{"name": "Waymo", "method": "curated"}]


def load_ids(path: Path) -> list[str]:
    return sorted({line.strip() for line in path.read_text().splitlines() if line.strip()})


def backfill_sqlite(db_path: Path, ids: list[str]) -> int:
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ",".join("?" * len(ids))
        cur = conn.execute(
            f"update papers set author_orgs = ? where paper_id in ({placeholders})",
            [json.dumps(CURATED_VALUE), *ids],
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def backfill_qdrant(host: str, port: int, collection: str, ids: list[str]) -> None:
    # set_payload merges into existing payloads -- it does not replace them, so `text`,
    # `section_path` and the rest of VectorPayload survive untouched.
    response = httpx.post(
        f"http://{host}:{port}/collections/{collection}/points/payload?wait=true",
        json={
            "payload": {"author_orgs": ["Waymo"], "curated_author_orgs": ["Waymo"]},
            "filter": {"must": [{"key": "paper_id", "match": {"any": ids}}]},
        },
        timeout=300.0,
    )
    response.raise_for_status()


def count_qdrant(host: str, port: int, collection: str) -> int:
    response = httpx.post(
        f"http://{host}:{port}/collections/{collection}/points/count",
        json={"filter": {"must": [{"key": "curated_author_orgs", "match": {"value": "Waymo"}}]},
              "exact": True},
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()["result"]["count"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(REPO_ROOT / "waymo/data/papers.db"))
    parser.add_argument("--ids-file", default=str(REPO_ROOT / "fixtures/waymo/waymo_authored_ids.txt"))
    parser.add_argument("--collection", default="waymo_av_safety")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6333)
    args = parser.parse_args()

    ids = load_ids(Path(args.ids_file))
    print(f"curated ids: {len(ids)}")

    rows = backfill_sqlite(Path(args.db), ids)
    print(f"sqlite papers rows updated: {rows}")

    backfill_qdrant(args.host, args.port, args.collection, ids)
    points = count_qdrant(args.host, args.port, args.collection)
    print(f"qdrant points now tagged curated=Waymo: {points}")

    # A curated id that is not a stored paper means the list and the corpus disagree -- the whole
    # point of this tier is that it is exact, so surface it rather than silently tagging fewer.
    if rows != len(ids):
        print(f"WARNING: {len(ids) - rows} curated id(s) are not in the papers table", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
