"""CQ-5: validate the reviewed standards-metadata table and emit category-tag artefacts.

The table (docs/eval-reports/data/2026-11-10-standards-metadata/standards_metadata.json) holds, per
document of the standards corpus, a hand-reviewed `kind`, `status`, `issuer`, `normative`,
`completeness`, edition and supersession links. Retrieval can only filter on payload fields that
`SearchFilters` already exposes, and the one free-form list it has is `categories` (any-overlap
match, see rag/vector_index.py::_qdrant_filter). So the fields are encoded as category-style tags:

    kind:<v>  status:<v>  issuer:<slug>  normative:<true|false>  completeness:<v>
    kindstatus:<kind>+<status>   normstatus:<true|false>+<status>        (combined tags)

Filter semantics, exactly: `SearchFilters(categories=[a, b])` keeps a point iff its payload
`categories` list contains `a` OR `b` (MatchAny); it is ANDed with every other SearchFilters field
(paper_id, doc_type, published_*, kind=chunk|summary ...). There is no AND across several category
values and no negation, so "standard AND current" is not `categories=["kind:standard",
"status:current"]` (that is standard OR current). The combined `kindstatus:` / `normstatus:` tags
exist so the common conjunctions are a single value.

    python scripts/standards_metadata.py validate [--table T] [--db DB]
    python scripts/standards_metadata.py emit --out-dir D [--table T] [--db DB]

`validate` exits non-zero on any error. `emit` validates first, then writes three files; it
opens the DB mode=ro, never executes the SQL and never touches Qdrant:
  payload_mapping.json   {paper_id: {"categories": [...]}}   for `python -m app.set_payload_fields
                         --only-fields categories --mapping-file` (existing categories kept: that
                         tool replaces the whole `categories` value, so the merge is done here)
  categories_update.sql  guarded `UPDATE papers SET categories_json = ... WHERE paper_id = ... AND
                         categories_json = <value read now>` (a no-op if the row changed since)
  categories_update.tsv  paper_id, old, new, for review
Re-running is idempotent: tags in the managed namespaces are stripped before the new ones are added.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contracts.errors import ContractError  # noqa: E402  (after sys.path bootstrap)

DEFAULT_TABLE = (
    Path(__file__).resolve().parent.parent
    / "docs/eval-reports/data/2026-11-10-standards-metadata/standards_metadata.json"
)
DEFAULT_DB = "/home/omar/ai-projects/research-system-rag-standards/data/papers.db"

KINDS = {"standard", "technical-specification", "regulation", "guidance", "handbook", "report",
         "book", "paper", "slides", "commentary", "letter"}
STATUSES = {"current", "superseded", "draft", "withdrawn", "preview-only"}
COMPLETENESS = {"full", "preview"}
YEAR_BASES = {"document", "cross-reference", "arxiv-date", None}
BINDING_KINDS = {"standard", "technical-specification", "regulation"}  # must carry a designation
# every tag this tool owns; stripped from existing categories before re-adding (idempotence)
TAG_PREFIXES = ("kind:", "status:", "issuer:", "normative:", "completeness:", "kindstatus:",
                "normstatus:")


def norm_text(text: str) -> str:
    """How a quote is compared with chunk text: table pipes, `---` runs and private-use glyphs
    (PDF bullets) removed, whitespace collapsed. The same function built the stored quotes."""
    text = re.sub(r"-{3,}", " ", text)
    text = re.sub(r"[|-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def load_table(path: str | Path = DEFAULT_TABLE) -> dict:
    return json.loads(Path(path).read_text())


def _open_ro(db_path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


# --- validation -----------------------------------------------------------------------------------


def validate(table: dict, db_path: str | Path) -> list[str]:
    """Every problem found, as strings (empty list = valid). Does not stop at the first."""
    errors: list[str] = []
    docs = table["documents"]
    by_id = {d["paper_id"]: d for d in docs}
    if len(by_id) != len(docs):
        errors.append("duplicate paper_id rows in table")
    con = _open_ro(db_path)
    try:
        db_titles = dict(con.execute("SELECT paper_id, title FROM papers"))
        for pid in sorted(set(by_id) - set(db_titles)):
            errors.append(f"{pid}: not in DB")
        for pid in sorted(set(db_titles) - set(by_id)):
            errors.append(f"{pid}: in DB but missing from table")
        for d in docs:
            errors += _validate_row(d, by_id, db_titles, con)
    finally:
        con.close()
    return errors


def _validate_row(d: dict, by_id: dict, db_titles: dict, con: sqlite3.Connection) -> list[str]:
    pid = d["paper_id"]
    err = []

    def bad(msg):
        err.append(f"{pid}: {msg}")

    if pid in db_titles and d["title"] != db_titles[pid]:
        bad("title differs from DB title")
    if d["kind"] not in KINDS:
        bad(f"kind {d['kind']!r} not in vocabulary")
    if d["status"] not in STATUSES:
        bad(f"status {d['status']!r} not in vocabulary")
    if d["completeness"] not in COMPLETENESS:
        bad(f"completeness {d['completeness']!r} not in vocabulary")
    if d["year_basis"] not in YEAR_BASES:
        bad(f"year_basis {d['year_basis']!r} not in vocabulary")
    if d["normative"] not in (True, False, None):
        bad("normative must be true, false or null")
    if not (d["edition_year"] is None or isinstance(d["edition_year"], int)):
        bad("edition_year must be an int or null")
    if (d["edition_year"] is None) != (d["year_basis"] is None):
        bad("edition_year and year_basis must be null together")
    reasons = d.get("null_reasons", {})
    for field in ("issuer", "designation", "edition_year", "normative", "edition_label"):
        if d[field] is None and not reasons.get(field):
            bad(f"{field} is null with no null_reasons entry")
    if d["designation"] is None and d["kind"] in BINDING_KINDS:
        bad(f"kind {d['kind']} requires a designation")
    if d["status"] == "preview-only" and d["completeness"] != "preview":
        bad("status preview-only requires completeness preview")
    if (d["status"] == "superseded") != bool(d["superseded_by"]):
        bad("status 'superseded' must hold exactly when superseded_by is non-empty")
    if d["status"] == "withdrawn" and not d["withdrawn_by"]:
        bad("status 'withdrawn' needs withdrawn_by")
    for field, back in (("superseded_by", "supersedes"), ("supersedes", "superseded_by")):
        for target in d[field]:
            if target == pid:
                bad(f"{field} points at itself")
            elif target not in by_id:
                bad(f"{field} target {target} is not a table row (orphan)")
            elif pid not in by_id[target][back]:
                bad(f"{field} {target} is not reciprocated by that row's {back}")
    for target in d["withdrawn_by"]:
        if target not in by_id:
            bad(f"withdrawn_by target {target} is not a table row (orphan)")
    if not d["evidence"]:
        bad("no evidence")
    for ev in d["evidence"]:
        row = con.execute(
            "SELECT text FROM chunks WHERE chunk_id = ?", (ev["chunk_id"],)).fetchone()
        if row is None:
            bad(f"evidence chunk {ev['chunk_id']} not in DB")
        elif ev["quote"] not in norm_text(row[0]):
            bad(f"evidence quote not found verbatim in {ev['chunk_id']}: {ev['quote'][:60]!r}")
    return err


def check(table: dict, db_path: str | Path) -> None:
    """`validate`, but raises ContractError listing every problem (fail loudly)."""
    errors = validate(table, db_path)
    if errors:
        raise ContractError(
            f"standards metadata table invalid ({len(errors)} problems):\n  " + "\n  ".join(errors)
        )


# --- tags -----------------------------------------------------------------------------------------


def tags_for(doc: dict) -> list[str]:
    """The tags for one row, in a stable order. normative=null and issuer=null emit no tag of
    that family (an absent tag is 'unknown', never silently 'false')."""
    tags = [f"kind:{doc['kind']}", f"status:{doc['status']}", f"completeness:{doc['completeness']}",
            f"kindstatus:{doc['kind']}+{doc['status']}"]
    if doc["issuer"]:
        tags.append(f"issuer:{slug(doc['issuer'])}")
    if doc["normative"] is not None:
        flag = "true" if doc["normative"] else "false"
        tags += [f"normative:{flag}", f"normstatus:{flag}+{doc['status']}"]
    return tags


def merged_categories(existing: list[str], doc: dict) -> list[str]:
    """Existing categories (arXiv codes etc.) first, unmanaged ones untouched, then the tags."""
    kept = [c for c in existing if not c.startswith(TAG_PREFIXES)]
    return kept + tags_for(doc)


def existing_categories(db_path: str | Path) -> dict[str, tuple[str, list[str]]]:
    """paper_id -> (raw categories_json as stored, parsed list). Read-only."""
    con = _open_ro(db_path)
    try:
        return {pid: (raw, json.loads(raw or "[]"))
                for pid, raw in con.execute("SELECT paper_id, categories_json FROM papers")}
    finally:
        con.close()


def build_payload_mapping(table: dict, existing: dict) -> dict[str, dict]:
    """The `--mapping-file` JSON for app.set_payload_fields (`--only-fields categories`)."""
    return {d["paper_id"]: {"categories": merged_categories(existing[d["paper_id"]][1], d)}
            for d in table["documents"]}


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_sql(table: dict, existing: dict) -> str:
    """Reviewable, NOT executed. Each UPDATE is guarded by the value read at emit time."""
    lines = ["-- CQ-5: tag standards documents in papers.categories_json. Review, then apply with",
             "-- the apply sequence in docs/eval-reports/2026-11-10-cq5-standards-metadata.md.",
             "BEGIN;"]
    for d in table["documents"]:
        raw, parsed = existing[d["paper_id"]]
        new = json.dumps(merged_categories(parsed, d))
        lines.append(
            f"UPDATE papers SET categories_json = {_sql_str(new)} "
            f"WHERE paper_id = {_sql_str(d['paper_id'])} AND categories_json = {_sql_str(raw)};")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def build_tsv(table: dict, existing: dict) -> str:
    rows = ["paper_id\told_categories_json\tnew_categories_json"]
    for d in table["documents"]:
        raw, parsed = existing[d["paper_id"]]
        rows.append(f"{d['paper_id']}\t{raw}\t{json.dumps(merged_categories(parsed, d))}")
    return "\n".join(rows) + "\n"


def emit(table_path: str | Path, db_path: str | Path, out_dir: str | Path) -> str:
    table = load_table(table_path)
    check(table, db_path)
    existing = existing_categories(db_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mapping = build_payload_mapping(table, existing)
    (out / "payload_mapping.json").write_text(json.dumps(mapping, indent=1) + "\n")
    (out / "categories_update.sql").write_text(build_sql(table, existing))
    (out / "categories_update.tsv").write_text(build_tsv(table, existing))
    distinct = {t for m in mapping.values() for t in m["categories"]}
    return f"wrote {len(mapping)} rows, {len(distinct)} distinct category values, to {out}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["validate", "emit"])
    parser.add_argument("--table", default=str(DEFAULT_TABLE))
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out-dir", help="emit: output directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            check(load_table(args.table), args.db)
            print(f"standards_metadata: {args.table} valid against {args.db}")
        else:
            if not args.out_dir:
                parser.error("emit needs --out-dir")
            print("standards_metadata:", emit(args.table, args.db, args.out_dir))
    except ContractError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
