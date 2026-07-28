"""Suite-scoped pytest bootstrap for `app/dashboard/`.

T-DOC89 part-1-review item 4 (superseding the original repo-root `conftest.py`, deleted): two real
(non-faked) consumers in this directory need a discoverable `config.yaml` at test time --
`app/dashboard/server.py::_static_config()` (lazy since Critical 2, but still a real
`rag.config.load_config()` call the first time a route handler needs it -- `status_module`/
`controller_module` are faked by `test_server.py`'s own fixtures, the static `Config` levers are
not) and `app/dashboard/controller.py::_load_base_config`'s fallback branch (hit by every
`test_controller.py` test that doesn't write its own `<data_dir>/config.yaml`).

Session-scoped, not autouse-per-test: `RAG_CONFIG` is set ONCE, before any test in this directory
runs, to a `tmp_path_factory` COPY of `config.example.yaml` -- copied (not pointed at directly) so
its `db_path` resolves (T-DOC89 §1) against that throwaway directory, not the repo, and the
repo-tree stub-validation warning (T-DOC89 §2) never fires just from running this suite. A test
that wants to exercise discovery itself (`app/dashboard/test_controller.py`'s own fallback test)
sets `RAG_CONFIG` explicitly via `monkeypatch`, which pytest restores after that one test --
taking precedence for its duration over this session-wide default.
"""

import os
import shutil

import pytest

import rag.config as config_mod


@pytest.fixture(scope="session", autouse=True)
def _dashboard_static_config(tmp_path_factory):
    config_dir = tmp_path_factory.mktemp("dashboard_static_config")
    target = config_dir / "config.yaml"
    shutil.copy(config_mod._REPO_ROOT / "config.example.yaml", target)

    previous = os.environ.get("RAG_CONFIG")
    os.environ["RAG_CONFIG"] = str(target)
    yield
    if previous is None:
        os.environ.pop("RAG_CONFIG", None)
    else:
        os.environ["RAG_CONFIG"] = previous
