"""Git co-change miner for the graphify knowledge graph (ticket T-G5).

Mines `git log <since>..HEAD --name-only` to find files that historically change
together and emits a graphify-compatible edge layer -- making temporal coupling
visible to agents planning changes. Commits touching more than
``--max-files-per-commit`` source files are skipped entirely so bulk renames do
not fabricate edges. Output is deterministic JSON on stdout or ``--out FILE``.

Python 3.12+ stdlib only; no network, no GPU.
"""

import argparse
import fnmatch
import itertools
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

SOURCE_EXTENSIONS = frozenset({".py", ".md", ".sql", ".yaml", ".yml", ".toml"})
COMMIT_MARKER_PREFIX = "COMMIT:"
DEFAULT_MIN_SUPPORT = 3
DEFAULT_MAX_FILES_PER_COMMIT = 50


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_commit_bundles(log_text: str) -> list[list[str]]:
    """Split ``git log --format=COMMIT:%H --name-only`` output into per-commit file lists.

    Returns bundles in log order; blank lines (separators, merge commits with no
    file list) yield no bundle. Duplicate paths within one commit are collapsed.
    """
    bundles: list[list[str]] = []
    current: list[str] = []
    for line in log_text.splitlines():
        if line.startswith(COMMIT_MARKER_PREFIX):
            if current:
                bundles.append(current)
            current = []
        elif line.strip():
            current.append(line)
    if current:
        bundles.append(current)
    return [sorted(set(bundle)) for bundle in bundles]


def is_source_file(path: str, extensions: frozenset[str] = SOURCE_EXTENSIONS) -> bool:
    return Path(path).suffix in extensions


def filter_bundle(
    files: list[str], exclude_patterns: list[str] | None = None
) -> list[str]:
    """Keep tracked source/doc files, dropping anything matching an exclude pattern."""
    patterns = exclude_patterns or []
    kept = [path for path in files if is_source_file(path)]
    for pattern in patterns:
        kept = [path for path in kept if not fnmatch.fnmatch(path, pattern)]
    return sorted(kept)


def count_pairs(
    bundles: list[list[str]], max_files_per_commit: int = DEFAULT_MAX_FILES_PER_COMMIT
) -> tuple[Counter[tuple[str, str]], int]:
    """Count unordered co-occurrence pairs across commits.

    A commit whose filtered file set exceeds ``max_files_per_commit`` is a
    mass-edit commit and contributes nothing. Returns the pair counter plus the
    number of individual pairs considered (sum of C(n, 2) over kept commits).
    """
    counter: Counter[tuple[str, str]] = Counter()
    considered = 0
    for files in bundles:
        if len(files) > max_files_per_commit:
            continue
        for first, second in itertools.combinations(sorted(files), 2):
            counter[(first, second)] += 1
            considered += 1
    return counter, considered


def build_report(
    repo: str,
    since: str,
    bundles: list[list[str]],
    pair_counts: Counter[tuple[str, str]],
    pairs_considered: int,
    min_support: int,
) -> dict:
    """Assemble the graphify-compatible JSON payload, fully sorted for determinism."""
    edges = [
        {"files": [first, second], "support": support}
        for (first, second), support in sorted(
            pair_counts.items(), key=lambda item: (-item[1], item[0])
        )
        if support >= min_support
    ]
    return {
        "generated_at": _utcnow(),
        "repo": repo,
        "since": since,
        "commits_scanned": len(bundles),
        "pairs_considered": pairs_considered,
        "edges": [
            {
                "files": edge["files"],
                "support": edge["support"],
                "confidence": "INFERRED",
                "confidence_score": 0.75,
            }
            for edge in edges
        ],
    }


def mine_git_log(repo: Path, since: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", f"{since}..HEAD", "--name-only", "--format=COMMIT:%H"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="path to the git repository")
    parser.add_argument("--since", required=True, help="tag or SHA to range from (<since>..HEAD)")
    parser.add_argument("--min-support", type=int, default=DEFAULT_MIN_SUPPORT)
    parser.add_argument("--out", default="-", help="output path ('-' for stdout)")
    parser.add_argument("--exclude", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--max-files-per-commit", type=int, default=DEFAULT_MAX_FILES_PER_COMMIT)
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    try:
        log_text = mine_git_log(repo, args.since)
    except FileNotFoundError:
        print(f"error: git executable not found while scanning {repo}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else f"git exited {exc.returncode}"
        print(f"error: git failed on {repo} ({detail})", file=sys.stderr)
        return 2

    bundles = [
        filtered
        for raw in parse_commit_bundles(log_text)
        if (filtered := filter_bundle(raw, args.exclude))
    ]
    pair_counts, pairs_considered = count_pairs(bundles, args.max_files_per_commit)
    report = build_report(
        repo=str(args.repo),
        since=args.since,
        bundles=bundles,
        pair_counts=pair_counts,
        pairs_considered=pairs_considered,
        min_support=args.min_support,
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"

    if args.out == "-":
        sys.stdout.write(payload)
    else:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
