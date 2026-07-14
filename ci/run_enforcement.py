#!/usr/bin/env python
"""CLI entrypoint for the `enforcement` CI job (T-F6, WORK-BREAKDOWN.md M0) — the only place that
composes `ci/checks/*` against a real push/PR diff. Each check itself stays independently
importable and testable (`ci/checks/test_checks.py`); this script's only job is wiring: figure out
what changed, hand it to the checks that apply, print what failed, set the exit code.

Usage (as run from `.github/workflows/ci.yml`):

    python -m ci.run_enforcement

Reads `GITHUB_EVENT_NAME` and `GITHUB_EVENT_PATH` from the environment (both set by every GitHub
Actions job) to compute the changed-file list and, for `pull_request` events, the PR's labels.

Checks (a)-(d) and (f)-(h) run here against *only the changed files* — not a full-repo scan (a
full-repo scan would re-flag pre-existing content forever, the exact trap this ticket's design
constraint calls out). Only `.py` files are handed to them (every one is Python-source-specific;
see `_is_scannable`), and (a)/(d)/(g)/(h) further scope themselves to `rag/`/`contracts/`
(`ci.checks.model.in_pipeline_scope`) since their CONVENTIONS.md rules are about the pipeline's own
modules, not this repo's CI tooling — each check's own module docstring explains its scope.

`check_g` additionally gets `list_deleted_paths(diff_base, REPO_ROOT)` — the raw deleted-path list
`build_diff_files` otherwise throws away — so it can catch a deleted `test_<name>.py` whose sibling
module survives untouched (PR #12 design review, finding 1); see `ci/checks/sibling_tests.py`.

`ci/checks/negative_examples/` and `ci/proof_socket_block/` are excluded from this scan: they are
intentionally-bad (or intentionally-real-network) reference material committed so
`ci/checks/test_checks.py` and the check (i) proof test can point at them directly — not "the
diff" this job is supposed to be linting. Excluding them here is what keeps this PR's own push
from tripping the checks it adds (the "your own enforcement job fails every future push forever"
trap named in the T-F6 ticket).

Check (e) (the `foundation-change` label) only runs on `pull_request` events — a `push` event's
payload has no label context, so this script prints an explicit "skipped" line for it on `push`
runs instead of silently omitting it (T-F6 ticket requirement: "don't make push runs fail or
silently skip in a way that looks broken").

Check (e)'s labels come from a *live* `GET` to the GitHub API (`_pr_labels`/`_fetch_live_labels`),
not straight from the cached `GITHUB_EVENT_PATH` snapshot: that file is written once, when the
triggering event fires, so a label added afterwards (the normal "review, then label" workflow)
isn't in it and check (e) would fail on a now-stale complaint. The cached payload is still used as
a fallback -- no `GITHUB_TOKEN`/`GITHUB_REPOSITORY` (e.g. a local dry run) or the API call failing
for any reason falls back to it rather than crashing the job over a transient API hiccup.

Check (i) is not run from here at all — it's proven by a pytest test
(`ci/proof_socket_block/test_real_network_blocked.py`), run as its own workflow step.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

from ci.checks import (
    check_a,
    check_b,
    check_c,
    check_d,
    check_e,
    check_f,
    check_g,
    check_h,
    discover_contract_names,
    read_codeowners_paths,
)
from ci.checks.changed_files import compute_diff_base, list_changed_paths, list_deleted_paths
from ci.checks.diff import build_diff_files
from ci.checks.model import Violation

REPO_ROOT = Path(__file__).resolve().parent.parent

# Paths that exist only to be pointed at by ci/checks/test_checks.py (or, for the socket-block
# fixture, run explicitly as their own workflow step) -- never "the diff" this job lints.
#
# "ci/checks/negative_examples/" also appears in pyproject.toml's `extend-exclude` (keeps ruff off
# it) and ci/checks/test_checks.py's FIXTURES (points the self-tests at it) -- if this path ever
# moves, update all three.
_EXCLUDED_PREFIXES = ("ci/checks/negative_examples/", "ci/proof_socket_block/")


def _is_scannable(path: str) -> bool:
    # Every check here is Python-source-specific (vendor imports, class defs, except blocks, env
    # reads, id-slicing) -- pointing e.g. ruff (check c) at a non-.py file (a workflow YAML, a
    # markdown doc) doesn't "pass", it errors out trying to parse it as Python.
    return path.endswith(".py") and not path.startswith(_EXCLUDED_PREFIXES)


def main() -> int:
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = _load_event()

    diff_base = compute_diff_base(event_name, event, REPO_ROOT)
    changed = list_changed_paths(diff_base, REPO_ROOT)
    deleted = list_deleted_paths(diff_base, REPO_ROOT)
    scannable = [p for p in changed if _is_scannable(p)]
    files = build_diff_files(scannable, REPO_ROOT, diff_base)

    violations: list[Violation] = []
    violations += check_a(files)
    violations += check_b(files, contract_names=discover_contract_names(REPO_ROOT / "contracts"))
    violations += check_c(files)
    violations += check_d(files)
    violations += check_f(files)
    violations += check_g(files, REPO_ROOT, deleted_paths=deleted)
    violations += check_h(files)

    if event_name == "pull_request":
        labels = _pr_labels(event)
        codeowners_paths = read_codeowners_paths(REPO_ROOT / ".github" / "CODEOWNERS")
        violations += check_e(changed, labels, codeowners_paths)
        print(f"check (e): ran (pull_request event, {len(labels)} label(s) on PR)")
    else:
        print(f"check (e): skipped -- {event_name!r} event has no PR label context to check")

    print(f"scanned {len(files)} changed file(s) (of {len(changed)} total changed)")
    if not violations:
        print("enforcement: PASS -- no violations in checks (a)-(d), (f)-(h)")
        return 0

    print(f"enforcement: FAIL -- {len(violations)} violation(s):")
    for v in violations:
        print(f"  {v}")
    return 1


def _pr_labels(event: dict) -> list[str]:
    """Check (e)'s label list -- fetched live from the GitHub API when possible (see module
    docstring for why: `GITHUB_EVENT_PATH` is a one-time snapshot, and a label added to the PR
    after the triggering event fired is the common case, not an edge case). Falls back to the
    cached event payload's labels, same as this function's only-ever-had-that behavior, when there
    is no token/repo to call the API with, or the live call itself fails for any reason.
    """
    cached_labels = [label["name"] for label in event["pull_request"]["labels"]]

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = event["pull_request"].get("number") or event.get("number")
    if not token or not repo or not pr_number:
        print(
            "check (e): no GITHUB_TOKEN/GITHUB_REPOSITORY/PR number available -- "
            "using cached event payload labels"
        )
        return cached_labels

    try:
        live_labels = _fetch_live_labels(repo, pr_number, token)
    except (OSError, ValueError, KeyError) as exc:
        print(f"check (e): live label fetch failed ({exc!r}) -- using cached event payload")
        return cached_labels

    print(f"check (e): fetched {len(live_labels)} label(s) live from the GitHub API")
    return live_labels


def _fetch_live_labels(repo: str, pr_number: int, token: str) -> list[str]:
    """`GET` a PR's current labels straight from GitHub -- the Issues API also serves PRs (a PR
    *is* an issue in GitHub's data model), and it's the same endpoint the `gh` CLI itself calls.
    Raises on any failure (network error, non-2xx response, unexpected body shape); `_pr_labels`
    decides what to do about that, so this function's only job is "ask GitHub the truth right now."
    """
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read())
    return [label["name"] for label in body]


def _load_event() -> dict:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return {}
    return json.loads(Path(event_path).read_text())


if __name__ == "__main__":
    sys.exit(main())
