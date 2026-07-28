"""The `Config` loader (T-F2, CONVENTIONS.md §3): the one place in this codebase allowed to
read `config.yaml` off disk. Every other module receives an already-constructed `Config`
instance — see `contracts/config.py`'s module docstring for the split between "shape" (T-F1,
`contracts/`) and "loader" (T-F2, here).

T-DOC89 (2026-07-28): a config now describes itself and finds itself. Two changes from the
original T-F2 loader:

  §1 — every relative path *inside* a config (`db_path`, `blob_dir`, `pdf_cache_dir`,
  `drop_in_dir`, `gpu_lock_path`, `batch_size_log_path`) resolves against **that config file's
  own directory**, not the process's cwd. `drop_in: "drop_in"` in a config then permanently means
  "the `drop_in` next to that config", loaded from anywhere -- see `_resolve_paths`.

  §3 — `load_config()` with no explicit path no longer just opens `./config.yaml` and fails if
  absent; it runs `find_config_path`'s discovery precedence (explicit -> `RAG_CONFIG` env var ->
  `config.yaml` in cwd -> walk up parent directories -> a loud error naming every location tried).

The tracked template moved to `config.example.yaml` (T-DOC89 §2) so it can never be discovered by
accident; a real `config.yaml` is untracked (`.gitignore`) and lives wherever an operator's setup
puts it (repo root via a symlink, or found via `RAG_CONFIG`/walk-up).
"""

import logging
import os
from pathlib import Path

import yaml

from contracts.config import Config
from contracts.errors import ContractError

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]

_CONFIG_FILENAME = "config.yaml"

# Every path-valued Config field (contracts/config.py) -- resolved against the config file's own
# directory by `_resolve_paths`, not the process cwd. Same fields as app/ingest.py's own
# `_PATH_FIELDS` / app/dashboard/controller.py's `_OVERRIDE_PATH_FIELDS`, plus `drop_in_dir`
# (T-DOC80 added it after those two override-mechanism lists were written; neither writer's
# override ever carries a drop_in override, so it was never needed there -- it's needed here since
# this is every config's baseline resolution, and drop_in is section 1's own motivating example).
_PATH_FIELDS = (
    "db_path", "blob_dir", "pdf_cache_dir", "drop_in_dir", "gpu_lock_path", "batch_size_log_path",
)


def _resolve_paths(data: dict, base_dir: Path) -> None:
    """Mutates `data` in place: every path field present resolves absolute against `base_dir`
    (the config file's own directory). `Path(base_dir) / value` is a no-op join when `value` is
    already absolute (same trick `app/dashboard/controller.py::_resolve_override_config` uses),
    so this is safe whether the YAML value was relative or already absolute.

    `pdf_cache_dir: ""` is a deliberate sentinel ("PDF cache disabled", contracts/config.py) and
    is left alone -- an empty string must not become `base_dir` itself.
    """
    for field in _PATH_FIELDS:
        value = data.get(field)
        if not value:
            continue
        data[field] = str((base_dir / value).resolve())


def find_config_path(explicit: str | Path | None = None) -> Path:
    """Discovery precedence (T-DOC89 §3): `explicit` -> `RAG_CONFIG` env var -> `config.yaml` in
    the process cwd -> walk up parent directories (stopping at the repo boundary, the first
    ancestor containing `.git` -- part-1-review item 6: this workspace has sibling projects one
    directory up, so walking past the repo root risks silently adopting an unrelated project's
    config instead of raising) -> `ContractError` naming every location tried and both ways to fix
    it. Every returned path is `.resolve()`d, including the cwd/walk-up rungs (part-1-review
    Critical 3) -- a symlinked `config.yaml` must describe itself relative to its real target's
    directory, not the symlink's, or §1's own path resolution silently re-roots into the wrong
    place.

    `explicit`, when given, is trusted as-is (resolved to absolute, not existence-checked here) --
    `load_config`'s `open()` raises the natural `FileNotFoundError` for a bad explicit path, same
    as before this change.
    """
    if explicit is not None:
        return Path(explicit).resolve()

    tried: list[str] = []

    # The one legitimate `os.getenv` call in this codebase (CONVENTIONS.md §3 / ci/checks/
    # env_leak.py check (d)): this module IS the Config loader T-F2 built, and check (d)'s
    # `EXEMPT_PATH = "rag/config.py"` already carves it out. The "no module calls os.getenv" rule
    # exists to stop config reads leaking into every OTHER module -- it was never meant to stop
    # the one loader itself from loading (see this repo's ci/checks/env_leak.py module docstring).
    env_value = os.getenv("RAG_CONFIG")
    if env_value:
        candidate = Path(env_value).resolve()
        if candidate.is_file():
            return candidate
        tried.append(f"$RAG_CONFIG={candidate} (set, but not a file)")

    cwd = Path.cwd().resolve()
    for directory in (cwd, *cwd.parents):
        candidate = directory / _CONFIG_FILENAME
        if candidate.is_file():
            # T-DOC89 part-1-review Critical 3: `.resolve()` follows a symlink to its real target
            # -- the design's own rollout mechanism (a gitignored repo-root config.yaml symlinked
            # to the real data-dir config) is exactly this shape. Without it, §1's own path
            # resolution (against `config_path.parent`) would use the SYMLINK's directory, not the
            # real config's directory, silently re-rooting every relative path back into the repo
            # tree -- the identical OG-33 failure this whole ticket exists to kill, just moved one
            # level down. The explicit/RAG_CONFIG rungs above already `.resolve()`; this makes all
            # three rungs agree.
            return candidate.resolve()
        tried.append(str(candidate))
        # T-DOC89 part-1-review item 6: stop at the repo boundary -- this workspace has sibling
        # projects one directory up (`~/ai-projects/*`), each plausibly with its own config.yaml;
        # walking past this repo's root would silently adopt an unrelated project's config
        # instead of raising the loud "nowhere found" error. A directory actually inside a repo
        # always has `.git` somewhere on its own walk-up before the filesystem root, so this only
        # gives up the walk early when cwd isn't inside a git repo at all -- same as today.
        if (directory / ".git").exists():
            break

    tried_block = "\n".join(f"  - {t}" for t in tried)
    raise ContractError(
        "no config.yaml found. Tried:\n" + tried_block + "\n\n"
        "Fix this by either:\n"
        "  1. passing an explicit path (a --config flag, or load_config(path=...)), or setting "
        "RAG_CONFIG=/path/to/config.yaml\n"
        "  2. placing a config.yaml at one of the locations above -- copy config.example.yaml and "
        "fill in real paths, or symlink it to your real data directory's config.yaml"
    )


def load_config(path: str | Path | None = None) -> Config:
    """Locate (`find_config_path`) and read a config file as YAML, constructing a validated
    `Config`.

    Precondition: the resolved file contains a single YAML mapping whose keys are a subset of
    `Config`'s fields (`focus_area_queries` required, everything else optional with the V0
    defaults in `contracts/config.py`). `path` follows T-DOC89 §3's discovery precedence when
    left at its default (`None`): an explicit `path` always wins; otherwise `RAG_CONFIG`, then
    `config.yaml` in the process cwd, then a walk up parent directories, then a loud error.

    Postcondition: returns a `Config` whose path-valued fields (`db_path`, `blob_dir`,
    `pdf_cache_dir`, `drop_in_dir`, `gpu_lock_path`, `batch_size_log_path`) are absolute, resolved
    against the CONFIG FILE'S OWN DIRECTORY (T-DOC89 §1) -- loading the same file from two
    different working directories yields identical absolute paths. The `Config` itself has passed
    pydantic's strict validation (frozen, strict types, `extra="forbid"`). None of the following
    are caught here: this is a startup-time crash-early path (CONVENTIONS §4), not a pipeline
    stage with retry/quarantine semantics, so all four propagate uncaught:
      - a missing required field, an unknown key, a wrong type, or an out-of-range value on an
        otherwise well-formed mapping raises `pydantic.ValidationError`.
      - malformed YAML syntax raises `yaml.YAMLError`.
      - a well-formed YAML document that isn't a mapping (an empty file, which `yaml.safe_load`
        turns into `None`, or a top-level list/scalar) raises `ContractError` — a broken
        invariant per CONVENTIONS §4's three-class taxonomy, checked here because it's the
        cheapest precondition to enforce and otherwise surfaces as an opaque
        `TypeError: Config() argument after ** must be a mapping, ...` from the `**` unpacking.
      - an explicit `path` that names no file raises `FileNotFoundError`, raised naturally by
        `open()`. A `path=None` discovery failure raises `ContractError` instead (see
        `find_config_path`) -- there IS no single file to blame, so a bare "not found" would be
        useless without the list of everywhere it looked.

    Also logs a warning (does not raise) if the resolved `db_path` falls inside this repo's own
    working tree -- see `_warn_if_db_path_in_repo`.
    """
    config_path = find_config_path(path)
    with open(config_path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ContractError(f"{config_path}: expected a YAML mapping, got {type(data).__name__}")
    _resolve_paths(data, config_path.parent)
    cfg = Config(**data)
    _warn_if_db_path_in_repo(cfg)
    return cfg


def _warn_if_db_path_in_repo(cfg: Config) -> None:
    """T-DOC89 §2 stub validation: a resolved `db_path` inside this repo's own working tree is
    `config.example.yaml`'s signature -- no legitimate setup puts the corpus there (`.gitignore`:
    "the REAL store lives in the sibling research-system-rag-data/ dir"). Logs loudly, does not
    raise -- a still-usable (if wrong) config must not become unloadable.

    Deliberately does NOT check row count: a genuinely fresh corpus legitimately has zero papers,
    and refusing on that basis would break bootstrap. Repo-tree containment is the precise
    signature the template leaves; a row count is a proxy that misfires on a fresh-but-correct
    setup.
    """
    db_path = Path(cfg.db_path).resolve()
    try:
        db_path.relative_to(_REPO_ROOT)
    except ValueError:
        return
    logger.warning(
        "db_path resolves to %s, INSIDE this repo's own working tree (%s). This is "
        "config.example.yaml's signature, not a real setup -- the real corpus belongs in the "
        "sibling research-system-rag-data/ directory (see .gitignore). If this is deliberate, "
        "ignore this warning.",
        db_path, _REPO_ROOT,
    )
