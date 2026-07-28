"""`python -m app.init_config --data-dir <path>` -- T-DOC65: the supported way to produce a real,
loadable `config.yaml` for a data directory, instead of tribal knowledge (copy
`config.example.yaml` by hand, fill in absolute paths, remember to symlink it at the repo root --
T-DOC89's "Why one change" section names exactly this gap as why people fall back to the template).

Writes `<data-dir>/config.yaml` from the tracked `config.example.yaml` template, with every
path-valued field (`rag.config._PATH_FIELDS`) resolved absolute against `<data-dir>` -- the same
resolution `rag.config.load_config` performs at load time (T-DOC89 §1), done once here at write
time so the written file is legible on its own: an operator can open it and see exactly where it
points, without loading it through Python first.

Refuses to overwrite an existing `<data-dir>/config.yaml` without `--force` -- this is meant to be
run once per data dir, and silently clobbering a hand-edited config would be exactly the kind of
silent failure T-DOC89's whole cluster exists to kill.

`--link` additionally creates a gitignored repo-root `config.yaml` symlink -> `<data-dir>/config.yaml`
(T-DOC89 §3's intended rollout mechanism: "establish the link once"). Opt-in, not automatic -- a
repo checkout isn't necessarily the one that should hold the link, and creating it silently would
be a surprise mutation of the repo root. The same `--force` gate covers replacing an existing
repo-root config.yaml/symlink.

ponytail: the written config.yaml is a plain re-dump of config.example.yaml's data -- it drops the
template's explanatory comments. config.example.yaml remains the annotated reference; this is the
operational copy. Worth revisiting only if operators report they actually re-read the generated
file's comments, which none has yet.
"""

import argparse
import sys
from pathlib import Path

import yaml

# Private but same-package reuse: `_resolve_paths` already carries the exact resolution semantics
# (which fields are paths, the pdf_cache_dir="" disabled-cache sentinel) `load_config` uses at load
# time -- reimplementing that list/sentinel here would drift from it. Doesn't touch rag/config.py
# (CODEOWNERS-protected), just imports from it, same as every other `app/` module already does.
from rag.config import _PATH_FIELDS, _resolve_paths

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLE_CONFIG = _REPO_ROOT / "config.example.yaml"
_CONFIG_FILENAME = "config.yaml"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", required=True,
        help="Directory to hold the real config.yaml; db_path/blob_dir/etc. are written absolute "
             "under it.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing <data-dir>/config.yaml and/or repo-root config.yaml/symlink.",
    )
    parser.add_argument(
        "--link", action="store_true",
        help="Also create a gitignored repo-root config.yaml symlink -> <data-dir>/config.yaml.",
    )
    return parser.parse_args(argv)


def write_config(data_dir: Path, *, force: bool) -> Path:
    """Writes `<data_dir>/config.yaml` from `config.example.yaml`, path fields resolved absolute
    against `data_dir`. Refuses (exit 1) if the destination exists and `force` is False."""
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / _CONFIG_FILENAME
    if dest.exists() and not force:
        print(
            f"init_config: {dest} already exists -- refusing to overwrite without --force",
            file=sys.stderr,
        )
        sys.exit(1)
    data = yaml.safe_load(_EXAMPLE_CONFIG.read_text())
    _resolve_paths(data, data_dir)
    dest.write_text(yaml.dump(data, sort_keys=False, default_flow_style=False))
    return dest


def create_symlink(data_dir_config: Path, *, force: bool) -> Path:
    """Creates (or replaces, with `force`) a repo-root `config.yaml` symlink pointing at
    `data_dir_config`. Refuses (exit 1) if something is already there and `force` is False."""
    link = _REPO_ROOT / _CONFIG_FILENAME
    if link.exists() or link.is_symlink():
        if not force:
            print(
                f"init_config: {link} already exists -- refusing to replace without --force",
                file=sys.stderr,
            )
            sys.exit(1)
        link.unlink()
    link.symlink_to(data_dir_config)
    return link


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    data_dir = Path(args.data_dir).resolve()
    dest = write_config(data_dir, force=args.force)

    written = yaml.safe_load(dest.read_text())
    print(f"init_config: wrote {dest}")
    for field in _PATH_FIELDS:
        print(f"  {field:<18} = {written.get(field)}")

    if args.link:
        link = create_symlink(dest, force=args.force)
        print(f"init_config: linked {link} -> {dest}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
