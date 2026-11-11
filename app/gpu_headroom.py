"""Real free-VRAM probe, via `nvidia-smi` -- stdlib `subprocess`, no vendor SDK (same
core-tool-exempt precedent as `app/tei_lifecycle.py`'s `docker` calls; `ci/checks/
vendor_isolation.py`'s `VENDOR_RULES` doesn't govern `subprocess`/system-tool invocations, and
this file lives outside `PIPELINE_SCOPE_PREFIXES` (`rag/`, `contracts/`) regardless).

T-DOC21 (`.claude/plans/giggly-tumbling-globe.md`, "Adaptive Pass-1 batch sizing"): the adaptive
batch sizer needs a real, current free-VRAM reading to decide whether to grow or shrink the next
Pass-1 batch. Best-effort, matching `app/tei_lifecycle.py`'s philosophy for this class of optional
system probe: never raises, `None` on any failure (missing binary, non-zero exit, unparseable
output) -- a caller that can't get a real reading should hold its current behavior steady, not
guess.
"""

import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def free_vram_mib() -> int | None:
    """Real, current free VRAM in MiB on GPU 0, or `None` if it can't be determined.

    Verified real output shape this session: `nvidia-smi --query-gpu=memory.free
    --format=csv,noheader,nounits` prints a single bare integer (e.g. `2966`), no units, no
    header -- exactly what int() expects with no further parsing.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("free_vram_mib: nvidia-smi probe failed, returning None: %s", e)
        return None

    try:
        # Real output is one line per queried GPU; this project's whole architecture is
        # single-GPU (ARCHITECTURE.md §3 "single-GPU rule") -- the first line is the only line.
        return int(result.stdout.strip().splitlines()[0])
    except (ValueError, IndexError) as e:
        logger.warning("free_vram_mib: unparseable nvidia-smi output %r: %s", result.stdout, e)
        return None


@dataclass(frozen=True)
class GpuProcess:
    pid: int
    name: str
    used_mib: int | None  # None when nvidia-smi reports "[N/A]" / "[Not Supported]"


def parse_compute_apps(stdout: str) -> list[GpuProcess]:
    """Parse `nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,
    noheader,nounits` rows (`1234, python, 512`). Defensive: a malformed row is skipped, a
    non-numeric memory becomes None, a name containing commas survives (pid is the first field,
    memory the last)."""
    procs = []
    for line in stdout.splitlines():
        head, _, rest = line.partition(",")
        name, _, mem = rest.rpartition(",")
        try:
            pid = int(head.strip())
        except ValueError:
            continue
        mem = mem.strip()
        procs.append(GpuProcess(pid, name.strip(), int(mem) if mem.isdigit() else None))
    return procs


def gpu_compute_processes() -> list[GpuProcess] | None:
    """Processes currently holding GPU compute contexts, or `None` if `nvidia-smi` can't be run
    (absent binary, non-zero exit, timeout) -- same never-raises contract as `free_vram_mib`."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("gpu_compute_processes: nvidia-smi probe failed, returning None: %s", e)
        return None
    return parse_compute_apps(result.stdout)
