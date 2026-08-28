"""Tests for `app/exp_nb_rr_qwen_reranker.py` -- QW-3.

Zero-GPU, zero-network, matching this repo's CI posture (no real Qwen weights are loaded here):
`Qwen3Reranker`'s scoring internals (`_compute_scores`, which loads the model) are stubbed out in
every test that exercises `rerank()`, so what's actually pinned is the *contract* -- ordering,
empty-input short-circuit, gpu-lock usage, and the constructor's `TeiReranker`-compatible shape --
not the model's real numeric output. `run_arm`'s subprocess is stubbed the same way `dry-run`
lets `scripts/test_nb_eval_runner.py` avoid a real subprocess.
"""

from __future__ import annotations

import app.assembly as assembly
from app.exp_nb_rr_qwen_reranker import (
    Qwen3Reranker,
    _arm_tag,
    _looks_like_retrieval_eval_argv,
    _parse_orchestrator_args,
    apply_qwen_patch,
    run_arm,
)
from contracts.retriever import RerankCandidate
from rag.fakes.fake_gpu_lock import FakeGpuLock


def _candidates(*ids: str) -> list[RerankCandidate]:
    return [RerankCandidate(id=i, text=f"text-{i}") for i in ids]


# --- argv-shape dispatch (module docstring: no env var allowed in app/ scope) -----------------


def test_looks_like_retrieval_eval_argv_true_when_ground_truth_flag_present():
    argv = ["--ground-truth", "fixtures/eval/gt_wmr.json", "--config", "x.yaml", "--k", "10"]
    assert _looks_like_retrieval_eval_argv(argv) is True


def test_looks_like_retrieval_eval_argv_false_for_orchestrator_flags():
    argv = ["--arm", "qwen", "--out-dir", "docs/eval-reports/data/2026-08-28-qw3"]
    assert _looks_like_retrieval_eval_argv(argv) is False


def test_arm_tag_maps_both_arms():
    assert _arm_tag("bge") == "bge-baseline"
    assert _arm_tag("qwen") == "qwen3-0.6b"


# --- the monkeypatch itself ---------------------------------------------------------------------


def test_apply_qwen_patch_rebinds_assembly_tei_reranker(monkeypatch):
    original = assembly.TeiReranker
    monkeypatch.setattr(assembly, "TeiReranker", original)  # ensures pytest restores it after
    apply_qwen_patch()
    assert assembly.TeiReranker is Qwen3Reranker


# --- Qwen3Reranker's contract (scoring stubbed -- no real model load) --------------------------


def test_rerank_returns_empty_list_for_no_candidates_without_touching_gpu_lock():
    lock = FakeGpuLock()
    reranker = Qwen3Reranker(None, lock)
    assert reranker.rerank("q", []) == []
    assert lock.acquired == []  # empty-candidates short-circuit never takes the lock


def test_rerank_orders_by_score_descending_and_uses_gpu_lock(monkeypatch):
    lock = FakeGpuLock()
    reranker = Qwen3Reranker(None, lock)
    candidates = _candidates("a", "b", "c")
    # a=low, b=high, c=mid -- expected order after rerank: b, c, a
    monkeypatch.setattr(reranker, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(reranker, "_compute_scores", lambda pairs: [0.1, 0.9, 0.5])

    result = reranker.rerank("q", candidates)

    assert [c.id for c in result] == ["b", "c", "a"]
    assert lock.acquired == ["rerank"]


def test_rerank_tie_breaks_by_original_index_ascending(monkeypatch):
    lock = FakeGpuLock()
    reranker = Qwen3Reranker(None, lock)
    candidates = _candidates("a", "b")
    monkeypatch.setattr(reranker, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(reranker, "_compute_scores", lambda pairs: [0.5, 0.5])

    result = reranker.rerank("q", candidates)

    assert [c.id for c in result] == ["a", "b"]


def test_rerank_calls_ensure_ready_hook_before_scoring(monkeypatch):
    calls = []
    lock = FakeGpuLock()
    reranker = Qwen3Reranker(None, lock, ensure_ready=lambda: calls.append("ready"))
    monkeypatch.setattr(reranker, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(reranker, "_compute_scores", lambda pairs: [1.0])

    reranker.rerank("q", _candidates("a"))

    assert calls == ["ready"]


def test_qwen3reranker_accepts_tei_reranker_call_shape():
    # app.assembly.build_mcp_server constructs TeiReranker(<transport>, gpu_lock,
    # ensure_ready=...) -- Qwen3Reranker must accept that exact call shape once monkeypatched in.
    Qwen3Reranker(object(), FakeGpuLock(), ensure_ready=None)


# --- orchestrator: subprocess argv construction (subprocess.run stubbed, never executed) --------


def test_run_arm_bge_uses_default_runner_module(monkeypatch):
    captured = {}

    def fake_run(cmd, cwd, timeout):
        captured["cmd"] = cmd
        return type("P", (), {"returncode": 0})()

    monkeypatch.setattr("app.exp_nb_rr_qwen_reranker.subprocess.run", fake_run)
    args = _parse_orchestrator_args(["--arm", "bge", "--out-dir", "/tmp/x", "--date", "2026-08-28"])
    run_arm("bge", args)

    cmd = captured["cmd"]
    assert "--runner-module" not in cmd
    assert "--tag" in cmd and cmd[cmd.index("--tag") + 1] == "bge-baseline"
    assert "--collection" in cmd and cmd[cmd.index("--collection") + 1] == args.collection
    assert "--sparse-mode" in cmd and cmd[cmd.index("--sparse-mode") + 1] == "fused"


def test_run_arm_qwen_overrides_runner_module(monkeypatch):
    captured = {}

    def fake_run(cmd, cwd, timeout):
        captured["cmd"] = cmd
        return type("P", (), {"returncode": 0})()

    monkeypatch.setattr("app.exp_nb_rr_qwen_reranker.subprocess.run", fake_run)
    args = _parse_orchestrator_args(
        ["--arm", "qwen", "--out-dir", "/tmp/x", "--date", "2026-08-28"]
    )
    run_arm("qwen", args)

    cmd = captured["cmd"]
    assert "--runner-module" in cmd
    assert cmd[cmd.index("--runner-module") + 1] == "app.exp_nb_rr_qwen_reranker"
    assert cmd[cmd.index("--tag") + 1] == "qwen3-0.6b"


def test_run_arm_raises_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        "app.exp_nb_rr_qwen_reranker.subprocess.run",
        lambda cmd, cwd, timeout: type("P", (), {"returncode": 1})(),
    )
    args = _parse_orchestrator_args(["--arm", "bge"])
    try:
        run_arm("bge", args)
        raise AssertionError("expected SystemExit on nonzero subprocess exit")
    except SystemExit:
        pass
