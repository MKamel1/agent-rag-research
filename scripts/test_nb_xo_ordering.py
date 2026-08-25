"""Tests for scripts/nb_xo_* — NB-X-O ordering-quality sweep (stub commit).

All pure-function tests, zero-GPU zero-network, mirroring scripts/test_nb_xp_deeppool_tables.py.
Real assertions land with the implementation commits; this file exists from the stub commit so
the numbered-commit chain starts green.
"""

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_blend_arm_stub_imports_and_parses():
    mod = _load("nb_xo_blend_arm")
    args = mod.parse_args([
        "--ground-truth", "fixtures/eval/gt_wmr.json",
        "--config", "/tmp/config.yaml",
        "--alpha", "0.5",
        "--report-path", "/tmp/report.json",
    ])
    assert args.alpha == 0.5 and args.k == 10 and args.collection == "waymo_av_safety"


def test_sweep_stub_imports_and_parses():
    mod = _load("nb_xo_ordering_sweep")
    args = mod.parse_args(["--dry-run"])
    assert args.dry_run and args.limit is None
