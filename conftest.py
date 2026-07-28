"""Session-wide pytest bootstrap.

T-DOC89 (§2/§3, `config.yaml` -> `config.example.yaml`): one module reads a config at IMPORT
time -- `app/dashboard/server.py`'s `_STATIC_CONFIG`, needed even to build the module because it
feeds a real request-routing default (the vector-store collection name). Discovery
(`rag/config.py::load_config`) has nothing to find in a CI/dev checkout with no real deployed
`config.yaml` anywhere on the walk-up path -- only the tracked template.

`setdefault` here gives that import-time load somewhere to land, without masking a test that
deliberately wants to exercise discovery itself: pytest's `monkeypatch.setenv`/`delenv("RAG_CONFIG")`
(see `rag/test_config_path_resolution.py`) overrides this default for the duration of that test and
is restored after, same as any other env var monkeypatch.
"""

import os
from pathlib import Path

os.environ.setdefault("RAG_CONFIG", str(Path(__file__).resolve().parent / "config.example.yaml"))
