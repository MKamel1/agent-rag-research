"""`python -m app.set_payload_fields` -- CQ-2: merge-style payload backfill through the
`VectorIndex` seam (unlike `scripts/backfill_curated_author_orgs.py`, which uses raw REST and takes
no snapshot). Applies a mapping `paper_id -> {field: value}` to every point of each paper via
`VectorIndex.set_payload`: existing payload keys are never dropped, vectors are untouched.

Mapping sources (exactly one):
  --build relevance_score --db PAPERS.DB    `papers.relevance_score` (SQLite opened read-only;
                                            NULL scores are skipped, so the key stays absent)
  --build topic_label --labels TSV          `<paper_id>\\t<on|borderline|off>\\t<reason>` lines
                                            (docs/eval-reports/data/2026-11-10-topic-labels/)
  --mapping-file FILE                       `.json` {paper_id: {field: value}}, or a `.tsv` whose
                                            header is `paper_id\\t<field>...` (cells parsed as JSON,
                                            falling back to a plain string)

Which payload fields survive a re-ingest/rechunk (`rag.orchestrator.vector_payload` is the single
producer): `relevance_score` IS produced there (CQ-2) -- the backfill and future ingests agree.
`topic_label` is NOT: it comes from an offline labelling pass, has no ingest-time source, so a
re-ingest or rechunk of a paper drops it until this command is re-run. Neither field is filterable
yet: `SearchFilters` (contracts/, protected) has no such fields -- see the CQ-2 runbook's
"Needs operator sign-off".

Safety (same shape as `app.resparse`, whose guard it reuses): `--collection` required;
`--only-fields` required (the allow-list of keys this run may write; anything else in the mapping
is dropped); dry run by default, `--apply` plus `--i-have-a-snapshot` or `--target-is-clone --clone-of X`;
points-per-paper counts must be identical before and after, and a random read-back sample must show
the mapped values.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.resparse import (
    backup_root_resolver,
    check_apply_guard,
    open_index,
)
from contracts.errors import ContractError
from scripts.eval_strata_report import load_labels

_READBACK_SAMPLE = 500
_IDS_PER_REQUEST = 1_000

Mapping = dict[str, dict]


class PayloadStore(Protocol):
    def paper_point_ids(self, collection=None) -> dict[str, list[str]]: ...
    def set_payload(self, fields, *, point_ids=None, batch_size=..., **kw): ...
    def sample_payloads(self, n, collection=None) -> list[dict]: ...


# --- mapping builders (no vector store involved) --------------------------------------------------


def build_relevance_score_mapping(db_path: str | Path) -> Mapping:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT paper_id, relevance_score FROM papers WHERE relevance_score IS NOT NULL"
        ).fetchall()
    finally:
        con.close()
    return {paper_id: {"relevance_score": float(score)} for paper_id, score in rows}


def build_topic_label_mapping(tsv_path: str | Path) -> Mapping:
    # Reuses scripts/eval_strata_report.py::load_labels (same file, same accepted labels).
    return {pid: {"topic_label": label} for pid, label in load_labels(Path(tsv_path)).items()}


def load_mapping_file(path: str | Path) -> Mapping:
    path = Path(path)
    if path.suffix == ".json":
        return json.loads(path.read_text())
    with path.open(newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    header = rows[0]
    if header[:1] != ["paper_id"] or len(header) < 2:
        raise ContractError(f"{path}: TSV header must start with paper_id and name >=1 field")

    def cell(text: str):
        try:
            return json.loads(text)
        except ValueError:
            return text

    return {r[0]: {k: cell(v) for k, v in zip(header[1:], r[1:], strict=True)} for r in rows[1:]}


# --- the run --------------------------------------------------------------------------------------


def _group_ids(mapping: Mapping, by_paper: dict[str, list[str]], only: set[str]):
    """Groups point ids by identical field dict (one set_payload sweep per distinct value set,
    instead of one request chain per paper). Returns (groups, stats)."""
    groups: dict[str, tuple[dict, list[str]]] = {}
    dropped_fields = 0
    missing = 0
    for paper_id, fields in mapping.items():
        kept = {k: v for k, v in fields.items() if k in only}
        dropped_fields += len(fields) - len(kept)
        if not kept:
            continue
        ids = by_paper.get(paper_id)
        if not ids:
            missing += 1
            continue
        groups.setdefault(json.dumps(kept, sort_keys=True), (kept, []))[1].extend(ids)
    n_points = sum(len(ids) for _, ids in groups.values())
    n_papers_covered = len(mapping) - missing
    return groups, {
        "points": n_points,
        "distinct_value_sets": len(groups),
        "mapping_papers_not_in_collection": missing,
        "mapping_papers_in_collection": n_papers_covered,
        "collection_papers_without_mapping": len(set(by_paper) - set(mapping)),
        "mapping_fields_dropped_by_allowlist": dropped_fields,
    }


def run_set_payload_fields(
    vector_index: PayloadStore,
    mapping: Mapping,
    *,
    collection: str,
    only_fields: set[str],
    apply: bool,
    backup_root: Callable[[], Path],
    have_snapshot: bool,
    target_is_clone: bool,
    clone_of: str | None,
    count_of: Callable[[str], int],
) -> str:
    before = vector_index.paper_point_ids()
    groups, stats = _group_ids(mapping, before, only_fields)
    summary = ", ".join(f"{k}={v:,}" for k, v in stats.items())
    if not apply:
        return (
            f"set_payload_fields: DRY RUN on {collection!r} fields={sorted(only_fields)} -- "
            f"nothing written; would touch {stats['points']:,} points. {summary}"
        )

    guard_note = check_apply_guard(
        tool="set_payload_fields", collection=collection, backup_root=backup_root,
        have_snapshot=have_snapshot, target_is_clone=target_is_clone, clone_of=clone_of,
        count_of=count_of,
    )
    written = 0
    for fields, ids in groups.values():
        written += vector_index.set_payload(fields, point_ids=ids, batch_size=_IDS_PER_REQUEST)
    if written != stats["points"]:
        raise ContractError(
            f"set_payload_fields: matched {written:,} points but expected {stats['points']:,} -- "
            f"the collection changed under the run or ids are missing; investigate."
        )

    after = vector_index.paper_point_ids()
    if {p: len(i) for p, i in before.items()} != {p: len(i) for p, i in after.items()}:
        raise ContractError(
            f"set_payload_fields: POINTS-PER-PAPER CHANGED on {collection!r} -- restore from the "
            f"snapshot/clone; do not retry blindly."
        )
    expected = {pid: {k: v for k, v in f.items() if k in only_fields} for pid, f in mapping.items()}
    checked = bad = 0
    for payload in vector_index.sample_payloads(_READBACK_SAMPLE):
        want = expected.get(payload.get("paper_id"))
        if not want:
            continue
        checked += 1
        bad += any(payload.get(k) != v for k, v in want.items())
    if bad:
        raise ContractError(
            f"set_payload_fields: read-back mismatch on {bad}/{checked} sampled mapped points"
        )
    return (
        f"set_payload_fields: APPLIED to {collection!r}: {written:,} points written, per-paper "
        f"point counts unchanged, read-back {checked - bad}/{checked} sampled mapped points OK. "
        f"Guard: {guard_note}. {summary}"
    )


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--collection", required=True, help="collection to operate on (no default)")
    parser.add_argument("--only-fields", required=True,
                        help="comma-separated allow-list of payload keys this run may write")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--build", choices=["relevance_score", "topic_label"])
    src.add_argument("--mapping-file")
    parser.add_argument("--db", help="papers.db (opened read-only) for --build relevance_score")
    parser.add_argument("--labels", help="topic_labels.tsv for --build topic_label")
    parser.add_argument("--config", default="config.yaml", help="config.yaml (backup-root lookup)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="(default) report only")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--i-have-a-snapshot", action="store_true")
    parser.add_argument("--target-is-clone", action="store_true")
    parser.add_argument("--clone-of", default=None)
    parser.add_argument("--backup-root", default=None)
    parser.add_argument("--vector-store-host", default="localhost")
    parser.add_argument("--vector-store-port", type=int, default=6333)
    args = parser.parse_args(argv)
    if args.build == "relevance_score" and not args.db:
        parser.error("--build relevance_score needs --db")
    if args.build == "topic_label" and not args.labels:
        parser.error("--build topic_label needs --labels")
    return args


def main() -> None:
    args = _parse_args()
    if args.build == "relevance_score":
        mapping = build_relevance_score_mapping(args.db)
    elif args.build == "topic_label":
        mapping = build_topic_label_mapping(args.labels)
    else:
        mapping = load_mapping_file(args.mapping_file)
    print(f"mapping: {len(mapping):,} papers", file=sys.stderr)
    print(
        run_set_payload_fields(
            open_index(args, args.collection),
            mapping,
            collection=args.collection,
            only_fields={f for f in args.only_fields.split(",") if f},
            apply=args.apply,
            backup_root=backup_root_resolver(args),
            have_snapshot=args.i_have_a_snapshot,
            target_is_clone=args.target_is_clone,
            clone_of=args.clone_of,
            count_of=lambda name: open_index(args, name).point_count(),
        )
    )


if __name__ == "__main__":
    main()
