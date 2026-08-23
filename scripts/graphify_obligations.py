"""Documentation-obligation checker: AGENT-PROCEDURES.md §B as a mechanical pass.

Input is a changed-file list (one repo-relative path per line, e.g. from
`git diff --name-only`); output is the obligations a reviewer must discharge.
Limitation: a path list cannot distinguish added vs modified files, so rules
that key on "new" fire on any match — conservative by design.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FOUNDATION_PREFIXES = (
    "contracts/",
    "rag/config.py",
    "config.example.yaml",
    "migrations/",
    "rag/fakes/",
    "fixtures/",
    "ci/",
    ".github/",
)

OBLIGATION_RULES = [
    {"rule_id": "R1", "doc": "docs/PROJECT-STATUS.md", "action": "update §2 entry-point table"},
    {
        "rule_id": "R2",
        "doc": "docs/PROJECT-STATUS.md",
        "action": "add a §7 doc-map row for each new docs/*.md",
    },
    {
        "rule_id": "R3",
        "doc": ".github/CODEOWNERS",
        "action": "foundation-protected path: requires @MKamel1 sign-off before merge",
    },
    {
        "rule_id": "R5",
        "doc": "*",
        "action": (
            "self-check: does this diff make any existing doc claim false? "
            "If yes, fix that doc in this PR"
        ),
    },
]


def _is_entry_point_change(repo: Path, rel: str) -> bool:
    p = repo / rel
    if p.suffix != ".py" or not rel.startswith("app/"):
        return False
    try:
        return "add_argument" in p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _is_new_doc(rel: str) -> bool:
    if not rel.endswith(".md") or not rel.startswith("docs/"):
        return False
    name = rel.rsplit("/", 1)[-1]
    return name.startswith(("DECISION-", "DESIGN-")) or "/eval-reports/" in rel


def evaluate(repo: Path, changed: list[str]) -> dict:
    by_rule: dict[str, list[str]] = {}
    for rel in sorted(set(changed)):
        norm = rel.strip().replace("\\", "/")
        if not norm or norm.startswith("scripts/test_"):
            continue
        if norm.startswith(("rag/test_", "app/test_")):
            continue
        if _is_entry_point_change(repo, norm):
            by_rule.setdefault("R1", []).append(norm)
        if _is_new_doc(norm):
            by_rule.setdefault("R2", []).append(norm)
        if norm.startswith(FOUNDATION_PREFIXES):
            by_rule.setdefault("R3", []).append(norm)
    obligations = []
    for rule in OBLIGATION_RULES:
        rid = rule["rule_id"]
        entry = {
            "rule_id": rid,
            "files": sorted(by_rule.get(rid, [])),
            "doc": rule["doc"],
            "action": rule["action"],
        }
        if rid == "R5":
            entry["files"] = ["*"]
        obligations.append(entry)
    obligations.sort(key=lambda o: o["rule_id"])
    return {
        "changed_count": len(set(c.strip() for c in changed if c.strip())),
        "obligations": obligations,
        "clean": not any(o["files"] for o in obligations),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed", required=True, help="text file: one changed path per line")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="-")
    args = parser.parse_args(argv)

    changed_path = Path(args.changed)
    try:
        lines = changed_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"error: cannot read {changed_path}: {exc}", file=sys.stderr)
        return 2
    result = evaluate(Path(args.root).resolve(), lines)
    payload = json.dumps(result, indent=2)
    if args.out == "-":
        print(payload)
    else:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
