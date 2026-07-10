"""Self-test suite for CONVENTIONS.md §12(a)-(h) mechanized in this package (T-F6's Done
criterion, WORK-BREAKDOWN.md): each check function is exercised directly against a committed
known-bad fixture (`negative_examples/*_bad.py`) and a known-good one
(`negative_examples/*_good.py`), proving the check fails what it should and passes what it
shouldn't flag — not just that it "looks right". Collected by the default `pytest` run
(`pyproject.toml` testpaths includes `ci/checks`); the fixtures themselves are never collected
(they aren't named `test_*.py`) and never executed (checks only read their source text/AST).
"""

import subprocess
from pathlib import Path

import pytest

from ci.checks import (
    DiffFile,
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

REPO_ROOT = Path(__file__).resolve().parents[2]
# "negative_examples" also appears in pyproject.toml's `extend-exclude` (keeps ruff off it) and
# ci/run_enforcement.py's _EXCLUDED_PREFIXES (keeps it out of the real enforcement scan) -- if this
# path ever moves, update all three.
FIXTURES = Path(__file__).resolve().parent / "negative_examples"


def _fixture(name: str, *, logical_path: str | None = None) -> DiffFile:
    return DiffFile.from_whole_file(
        str((FIXTURES / name).relative_to(REPO_ROOT)),
        REPO_ROOT,
        logical_path=logical_path,
    )


# --- (a) vendor isolation ----------------------------------------------------------------------


def test_check_a_flags_vendor_leak_outside_its_adapter():
    f = _fixture("vendor_isolation_bad.py", logical_path="rag/retriever.py")
    violations = check_a([f])
    assert violations
    assert any(v.check == "a" for v in violations)


def test_check_a_allows_vendor_name_inside_its_own_adapter():
    f = _fixture("vendor_isolation_bad.py", logical_path="rag/vector_index.py")
    # qdrant is allowed at rag/vector_index.py, but the same fixture also mentions mineru, which
    # isn't -> mineru is still flagged here, proving the exemption is per-vendor, not "any adapter,
    # any vendor".
    violations = check_a([f])
    flagged_vendors = {v.message.split("'")[1] for v in violations}
    assert "qdrant" not in flagged_vendors
    assert "mineru" in flagged_vendors


def test_check_a_passes_clean_file():
    f = _fixture("vendor_isolation_good.py", logical_path="rag/retriever.py")
    assert check_a([f]) == []


# --- (b) contract shadowing --------------------------------------------------------------------


def test_check_b_flags_shadowed_contract_name():
    f = _fixture("contract_shadowing_bad.py", logical_path="rag/embedder.py")
    violations = check_b([f], contract_names={"EmbedderInfo"})
    assert len(violations) == 1
    assert violations[0].check == "b"


def test_check_b_passes_non_colliding_name():
    f = _fixture("contract_shadowing_good.py", logical_path="rag/retriever.py")
    assert check_b([f], contract_names={"EmbedderInfo"}) == []


def test_check_b_ignores_files_under_contracts():
    f = _fixture("contract_shadowing_bad.py", logical_path="contracts/embedder.py")
    assert check_b([f], contract_names={"EmbedderInfo"}) == []


def test_discover_contract_names_finds_real_types():
    names = discover_contract_names(REPO_ROOT / "contracts")
    assert {"EmbedderInfo", "Config", "ContractError", "Chunk"} <= names


# --- (c) blind/bare except ----------------------------------------------------------------------


def test_check_c_flags_bare_and_blind_except():
    f = _fixture("blind_except_bad.py", logical_path="rag/harvester.py")
    violations = check_c([f])
    codes = {v.message.split(":")[0] for v in violations}
    assert codes == {"E722", "BLE001"}


def test_check_c_passes_specific_except():
    f = _fixture("blind_except_good.py", logical_path="rag/harvester.py")
    assert check_c([f]) == []


def test_check_c_fails_closed_when_ruff_itself_errors(monkeypatch):
    # ruff can error on a given file independently of whether that file has a blind/bare except
    # (a crash, an unreadable file, an internal error) -- a nonzero exit with empty stdout. This
    # check is the *only* place ruff runs in the enforcement job (no repo-wide `ruff check .`
    # backstop), so silently reading that as "no violation" is a fail-open with no safety net
    # (PR #12 design review, finding 2). Simulate the failure directly at the subprocess boundary
    # so the test doesn't depend on finding an input that happens to make the real ruff binary
    # misbehave the same way in every environment/version.
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0], returncode=2, stdout="", stderr="ruff: panicked"
        )

    monkeypatch.setattr("ci.checks.blind_except.subprocess.run", fake_run)
    f = _fixture("blind_except_good.py", logical_path="rag/harvester.py")
    violations = check_c([f])
    assert len(violations) == 1
    assert violations[0].check == "c"


# --- (d) os.getenv/os.environ -------------------------------------------------------------------


def test_check_d_flags_env_read_outside_config():
    f = _fixture("env_leak_bad.py", logical_path="rag/retriever.py")
    violations = check_d([f])
    assert len(violations) == 2  # os.getenv and os.environ, both flagged


def test_check_d_allows_env_read_inside_config():
    f = _fixture("env_leak_bad.py", logical_path="rag/config.py")
    assert check_d([f]) == []


def test_check_d_passes_clean_file():
    f = _fixture("env_leak_good.py", logical_path="rag/retriever.py")
    assert check_d([f]) == []


# --- (f) gpu_lock on real GPU-bound adapters ----------------------------------------------------


def test_check_f_flags_missing_gpu_lock_param():
    f = _fixture("gpu_lock_bad.py", logical_path="rag/embedder.py")
    violations = check_f([f])
    assert len(violations) == 1
    assert "TeiEmbedder" in violations[0].message


def test_check_f_passes_with_gpu_lock_param():
    f = _fixture("gpu_lock_good.py", logical_path="rag/embedder.py")
    assert check_f([f]) == []


def test_check_f_exempts_fakes_directory():
    f = _fixture("gpu_lock_bad.py", logical_path="rag/fakes/fake_embedder.py")
    assert check_f([f]) == []


def test_check_f_exempts_contracts_directory():
    f = _fixture("gpu_lock_bad.py", logical_path="contracts/embedder.py")
    assert check_f([f]) == []


# --- (g) sibling test file ------------------------------------------------------------------


def test_check_g_flags_module_with_no_sibling_test():
    f = _fixture("sibling_tests_bad/lonely_module.py", logical_path="rag/lonely_module.py")
    violations = check_g([f], REPO_ROOT)
    assert len(violations) == 1
    assert violations[0].check == "g"


def test_check_g_passes_module_with_real_sibling_test():
    # rag/config.py + rag/test_config.py both really exist in this repo (T-F2) -- use them
    # directly rather than fabricating a second committed pair just for this test.
    f = DiffFile.from_whole_file("rag/config.py", REPO_ROOT)
    assert check_g([f], REPO_ROOT) == []


def test_check_g_ignores_files_outside_rag_and_contracts():
    f = _fixture("sibling_tests_bad/lonely_module.py", logical_path="ci/checks/lonely_module.py")
    assert check_g([f], REPO_ROOT) == []


def test_check_g_flags_deleted_test_file_whose_module_still_exists(tmp_path):
    # rag/config.py is still on disk (untouched by this diff); rag/test_config.py was deleted by
    # this diff and so never becomes a DiffFile (build_diff_files drops deletions, and _in_scope
    # excludes test_-prefixed files anyway) -- check_g must still catch the module silently losing
    # its only test coverage. This is finding 1 from the PR #12 design review.
    (tmp_path / "rag").mkdir()
    (tmp_path / "rag" / "config.py").write_text("VALUE = 1\n")
    violations = check_g([], tmp_path, deleted_paths=["rag/test_config.py"])
    assert len(violations) == 1
    assert violations[0].check == "g"
    assert violations[0].path == "rag/test_config.py"


def test_check_g_ignores_deleted_test_file_whose_module_is_also_deleted(tmp_path):
    # Both rag/config.py and rag/test_config.py are gone -- nothing left to lose test coverage.
    (tmp_path / "rag").mkdir()
    violations = check_g([], tmp_path, deleted_paths=["rag/test_config.py"])
    assert violations == []


def test_check_g_ignores_deleted_test_file_outside_pipeline_scope(tmp_path):
    (tmp_path / "ci" / "checks").mkdir(parents=True)
    (tmp_path / "ci" / "checks" / "foo.py").write_text("VALUE = 1\n")
    violations = check_g([], tmp_path, deleted_paths=["ci/checks/test_foo.py"])
    assert violations == []


# --- (h) manual chunk_id/block_id/summary_id slicing ----------------------------------------


def test_check_h_flags_manual_slicing_outside_document_store():
    f = _fixture("id_slicing_bad.py", logical_path="rag/retriever.py")
    violations = check_h([f])
    assert len(violations) == 1
    assert violations[0].check == "h"


def test_check_h_allows_slicing_inside_document_store():
    f = _fixture("id_slicing_bad.py", logical_path="rag/document_store.py")
    assert check_h([f]) == []


def test_check_h_passes_clean_file():
    f = _fixture("id_slicing_good.py", logical_path="rag/retriever.py")
    assert check_h([f]) == []


# --- (e) foundation-change label (pull_request-only; no DiffFile needed) ---------------------


def test_check_e_flags_protected_path_without_label():
    violations = check_e(
        changed_paths=["contracts/embedder.py"],
        labels=[],
        codeowners_paths=["/contracts/", "/rag/config.py"],
    )
    assert len(violations) == 1
    assert violations[0].check == "e"


def test_check_e_passes_with_label():
    violations = check_e(
        changed_paths=["contracts/embedder.py"],
        labels=["foundation-change"],
        codeowners_paths=["/contracts/", "/rag/config.py"],
    )
    assert violations == []


def test_check_e_passes_when_no_protected_path_touched():
    violations = check_e(
        changed_paths=["rag/retriever.py"],
        labels=[],
        codeowners_paths=["/contracts/", "/rag/config.py"],
    )
    assert violations == []


def test_check_e_matches_single_file_entries_exactly():
    # rag/config.py is CODEOWNERS-listed as a single file, not a directory -- rag/config_extra.py
    # must not be treated as protected just because it shares a prefix.
    violations = check_e(
        changed_paths=["rag/config_extra.py"],
        labels=[],
        codeowners_paths=["/rag/config.py"],
    )
    assert violations == []


def test_read_codeowners_paths_matches_real_file():
    paths = read_codeowners_paths(REPO_ROOT / ".github" / "CODEOWNERS")
    assert "/contracts/" in paths
    assert "/rag/config.py" in paths
    assert "/rag/fakes/" in paths


def test_read_codeowners_paths_ignores_comments_and_blanks(tmp_path):
    sample = tmp_path / "CODEOWNERS"
    sample.write_text("# a comment\n\n/contracts/   @someone\n/config.yaml @someone\n")
    assert read_codeowners_paths(sample) == ["/contracts/", "/config.yaml"]


@pytest.mark.parametrize("fixture_name", sorted(p.name for p in FIXTURES.glob("*.py")))
def test_every_negative_example_is_valid_python(fixture_name):
    # Even though these files are never executed, a syntax error in one would make every check's
    # AST-based logic (b, f) silently no-op on it rather than exercise the intended shape.
    import ast

    ast.parse((FIXTURES / fixture_name).read_text())
