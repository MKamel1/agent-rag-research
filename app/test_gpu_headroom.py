"""Tests for `app.gpu_headroom` (T-DOC21) -- offline, no real nvidia-smi/GPU calls."""

import subprocess
from types import SimpleNamespace

import pytest

from app.gpu_headroom import free_vram_mib


def _fake_completed(stdout: str):
    return SimpleNamespace(stdout=stdout, returncode=0)


def test_free_vram_mib_parses_real_nvidia_smi_output_shape(monkeypatch):
    # Real output verified live this session: a bare integer, no header, no units.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed("2966\n"))
    assert free_vram_mib() == 2966


def test_free_vram_mib_invokes_the_expected_nvidia_smi_command(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _fake_completed("1000\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    free_vram_mib()

    assert calls == [
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"]
    ]


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(1, "nvidia-smi"),
        subprocess.TimeoutExpired("nvidia-smi", 10.0),
        FileNotFoundError("no nvidia-smi"),
    ],
)
def test_free_vram_mib_returns_none_on_subprocess_failure(monkeypatch, error):
    def raise_error(*a, **k):
        raise error

    monkeypatch.setattr(subprocess, "run", raise_error)
    assert free_vram_mib() is None


def test_free_vram_mib_returns_none_on_unparseable_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed("not a number\n"))
    assert free_vram_mib() is None


def test_free_vram_mib_returns_none_on_empty_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed(""))
    assert free_vram_mib() is None


def test_free_vram_mib_never_raises_logs_a_warning_on_failure(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
    )
    with caplog.at_level(logging.WARNING):
        result = free_vram_mib()
    assert result is None
    assert "nvidia-smi probe failed" in caplog.text


# --- OP-5: compute-apps listing -------------------------------------------------------------

from app.gpu_headroom import GpuProcess, gpu_compute_processes, parse_compute_apps  # noqa: E402


def test_parse_compute_apps_reads_rows_and_tolerates_junk():
    out = "1234, python, 512\n77, /usr/bin/my, app, 9000\nbad row\n5, ollama, [N/A]\n\n"
    assert parse_compute_apps(out) == [
        GpuProcess(1234, "python", 512),
        GpuProcess(77, "/usr/bin/my, app", 9000),
        GpuProcess(5, "ollama", None),
    ]


def test_parse_compute_apps_empty_output_means_no_processes():
    assert parse_compute_apps("") == []


def test_gpu_compute_processes_uses_the_compute_apps_query(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _fake_completed("1, a, 2\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert gpu_compute_processes() == [GpuProcess(1, "a", 2)]
    assert "--query-compute-apps=pid,process_name,used_memory" in calls[0]


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(1, "nvidia-smi"),
        subprocess.TimeoutExpired("nvidia-smi", 10.0),
        FileNotFoundError("no nvidia-smi"),
    ],
)
def test_gpu_compute_processes_returns_none_when_nvidia_smi_is_unavailable(monkeypatch, error):
    def raise_error(*a, **k):
        raise error

    monkeypatch.setattr(subprocess, "run", raise_error)
    assert gpu_compute_processes() is None
