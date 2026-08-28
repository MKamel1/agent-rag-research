"""`python -m app.exp_chunk_boundary_stratum` -- SB-1's stratum-replay harness.

Reuses NB-D2's own boundary-adjacency instrument (`docs/eval-reports/data/2026-08-23-waymo-
priority/nb_d2_block_adjacency.py`) UNCHANGED -- the ticket names it as SB-1's stratum instrument
("reuse it, do not rewrite it") -- against any arm's own `app/retrieval_eval.py` report, not just
the frozen 2026-08-23 baseline it originally shipped with.

WHY A DYNAMIC IMPORT, NOT A NORMAL PACKAGE IMPORT: that script lives under `docs/eval-reports/
data/...`, a data directory, never on `sys.path` as a package -- and it is a prior, frozen
deliverable outside SB-1's owned files (this ticket must not edit it). `importlib.util.
spec_from_file_location` loads it by path and executes it as an ordinary module object, exposing
its `analyze_config`/`open_db_ro`/`print_report`/`GateError` for direct reuse, with zero copy-paste
of its ~200 lines of anchor-partition/classification/gate logic.

WHY `analyze_config()` DIRECTLY, NOT ITS OWN `main()`: `main()` hardcodes six fixed (fixture, mode)
pairs (`HEADLINE_CONFIGS + APPENDIX_CONFIGS`) tied to the frozen 2026-08-23 files. `analyze_config
(conn, data_dir, fixture, mode, geo_cache, section_violations)` is the reusable unit underneath
that loop: it loads `data_dir/{fixture}_{mode}.json` and runs the SAME classification, gated by the
SAME G2/G3/G4 sanity checks (anchor uniqueness, chunk-id monotonicity, bucket partition). Its G1
gate (recomputed decomposition == PREC-1's published table) only fires for the three (fixture,
mode) keys that table has entries for; any other `mode` string -- every SB-1 arm's own label --
reports `g1_matches_prec1_table: "not_tabulated"` and is not gated, by that module's own design,
not a hole this harness opens.

INPUT CONTRACT: `--data-dir` must contain a file named `{fixture}_{mode}.json` in the exact shape
`app/retrieval_eval.py --report-path` writes (a `questions` array with per-item `passage_level`/
`paper_level`/`retrieved_paper_ids`/`retrieved_block_ids`/`gold_block_id`/`gold_paper_ids`). This
harness never re-derives that shape -- `stage_report()` below stages a raw per-fixture report
(`scripts/nb_eval_runner.py`'s `raw_reports/{name}.json`, or `app/retrieval_eval.py
--report-path` directly) to that exact name via a byte-for-byte copy.

USAGE:
    python -m app.exp_chunk_boundary_stratum --data-dir DIR --fixture ver84 --mode <label>
    python -m app.exp_chunk_boundary_stratum --data-dir DIR --fixture ver84 gt_wmr --mode <label>

Fixtures are never averaged (programme constraint 7) -- `--fixture` accepts one or more names and
each gets its own entry in the output, always.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
_D2_SCRIPT = (
    REPO_ROOT / "docs/eval-reports/data/2026-08-23-waymo-priority/nb_d2_block_adjacency.py"
)
# Absolute, not REPO_ROOT-relative: `waymo/data/` (the corpus db/blobs) is gitignored and lives at
# ONE shared location on this workstation, not replicated into each git worktree -- same
# convention as `nb_d2_block_adjacency.py`'s own `DB_DEFAULT` and `scripts/nb_eval_runner.py`'s
# `DEFAULT_CONFIG`.
_DEFAULT_DB = Path("/home/omar/ai-projects/research-system-rag/waymo/data/papers.db")

# The two ground-truth fixtures this programme measures, D2's own short names (never "waymo_
# gt_verified" here -- match D2's file-naming convention exactly since load_records builds
# `{fixture}_{mode}.json` from this string).
FIXTURES = ("ver84", "gt_wmr")


def load_d2_module() -> ModuleType:
    """Loads the frozen NB-D2 script by path -- see module docstring's "WHY A DYNAMIC IMPORT"."""
    spec = importlib.util.spec_from_file_location("nb_d2_block_adjacency", _D2_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load stratum instrument at {_D2_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stage_report(retrieval_eval_report: Path, data_dir: Path, fixture: str, mode: str) -> Path:
    """Copies a raw `app/retrieval_eval.py` / `scripts/nb_eval_runner.py` report to the exact
    `{fixture}_{mode}.json` name `nb_d2_block_adjacency.load_records` expects. A plain byte-for-
    byte copy -- no content is touched -- so the D2 instrument classifies the same report a real
    eval run produced, never a re-derived or re-shaped copy of it.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / f"{fixture}_{mode}.json"
    shutil.copyfile(retrieval_eval_report, dest)
    return dest


def analyze(d2: ModuleType, db_path: Path, data_dir: Path, fixture: str, mode: str) -> dict:
    """One (fixture, mode) config's bucket table -- `d2.analyze_config`, unmodified. Raises the
    D2 module's own `GateError` (propagated, never swallowed) if any of its sanity gates fail -- a
    stratum table this harness can't trust must not be silently emitted.
    """
    conn = d2.open_db_ro(db_path)
    try:
        return d2.analyze_config(conn, data_dir, fixture, mode, {}, {})
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument(
        "--data-dir", type=Path, required=True,
        help="directory containing {fixture}_{mode}.json report file(s) (see stage_report())",
    )
    parser.add_argument(
        "--fixture", nargs="+", choices=FIXTURES, default=list(FIXTURES),
        help="never averaged across fixtures (programme constraint 7) -- always reported "
             "and returned separately",
    )
    parser.add_argument("--mode", required=True, help="arm label, e.g. sb1b_smooth / fused_before")
    parser.add_argument(
        "--out", type=Path, default=None,
        help="write the combined {fixture_mode: result} JSON here "
             "(default: <data-dir>/<mode>_bucket_analysis.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    d2 = load_d2_module()
    results = {}
    for fixture in args.fixture:
        results[f"{fixture}_{args.mode}"] = analyze(d2, args.db, args.data_dir, fixture, args.mode)
    d2.print_report(results)
    out_path = args.out or (args.data_dir / f"{args.mode}_bucket_analysis.json")
    out_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
