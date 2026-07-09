"""The `Config` loader (T-F2, CONVENTIONS.md §3): the one place in this codebase allowed to
read `config.yaml` off disk. Every other module receives an already-constructed `Config`
instance — see `contracts/config.py`'s module docstring for the split between "shape" (T-F1,
`contracts/`) and "loader" (T-F2, here).
"""

from pathlib import Path

import yaml

from contracts.config import Config
from contracts.errors import ContractError


def load_config(path: str | Path = "config.yaml") -> Config:
    """Read `path` as YAML and construct a validated `Config` from it.

    Precondition: `path` names a file containing a single YAML mapping whose keys are a subset
    of `Config`'s fields (`focus_area_queries` required, everything else optional with the V0
    defaults in `contracts/config.py`). If `path` is left at its default, it resolves relative to
    the process's current working directory, not this file's location — callers that rely on the
    default (e.g. the future `IngestionOrchestrator`/`McpServer` composition roots) must be
    launched from a directory containing `config.yaml`, or pass an explicit path.

    Postcondition: returns a `Config` that has passed pydantic's strict validation (frozen,
    strict types, `extra="forbid"`). None of the following are caught here: this is a
    startup-time crash-early path (CONVENTIONS §4), not a pipeline stage with retry/quarantine
    semantics, so all four propagate uncaught:
      - a missing required field, an unknown key, a wrong type, or an out-of-range value on an
        otherwise well-formed mapping raises `pydantic.ValidationError`.
      - malformed YAML syntax raises `yaml.YAMLError`.
      - a well-formed YAML document that isn't a mapping (an empty file, which `yaml.safe_load`
        turns into `None`, or a top-level list/scalar) raises `ContractError` — a broken
        invariant per CONVENTIONS §4's three-class taxonomy, checked here because it's the
        cheapest precondition to enforce and otherwise surfaces as an opaque
        `TypeError: Config() argument after ** must be a mapping, ...` from the `**` unpacking.
      - a missing file raises `FileNotFoundError`, raised naturally by `open()`.

    Does not read `os.environ` — this repo has no env-var config path (CONVENTIONS §3).
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ContractError(f"{path}: expected a YAML mapping, got {type(data).__name__}")
    return Config(**data)
