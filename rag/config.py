"""The `Config` loader (T-F2, CONVENTIONS.md §3): the one place in this codebase allowed to
read `config.yaml` off disk. Every other module receives an already-constructed `Config`
instance — see `contracts/config.py`'s module docstring for the split between "shape" (T-F1,
`contracts/`) and "loader" (T-F2, here).
"""

from pathlib import Path

import yaml

from contracts.config import Config


def load_config(path: str | Path = "config.yaml") -> Config:
    """Read `path` as YAML and construct a validated `Config` from it.

    Precondition: `path` names a file containing a single YAML mapping whose keys are a subset
    of `Config`'s fields (`focus_area_queries` required, everything else optional with the V0
    defaults in `contracts/config.py`).

    Postcondition: returns a `Config` that has passed pydantic's strict validation (frozen,
    strict types, `extra="forbid"`) — a missing required field, an unknown key, a wrong type, or
    an out-of-range value all raise `pydantic.ValidationError`. A malformed YAML document raises
    `yaml.YAMLError`. Neither is caught here: this is a startup-time crash-early path (CONVENTIONS
    §4), not a pipeline stage with retry/quarantine semantics, so both propagate uncaught.

    Does not read `os.environ` — this repo has no env-var config path (CONVENTIONS §3).
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    return Config(**data)
