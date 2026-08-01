"""`app/dashboard/verify_numbers.py` -- D-10: an independent cross-check for every `/api/status`
field.

**Why this exists.** D-6's unit tests for `downloader.orphan` passed, CI was green, and the field
was still wrong in production on 2026-08-01 (a run's own legitimate `app.prefetch_pdfs` child was
reported as an orphan -- fixed separately in `status.py`/`server.py`, D-10 Task 3). Unit tests that
inject fake data and assert against `status.py`'s own logic can never catch a bug IN that logic.
The only check that can is one that recomputes each number from a DIFFERENT source -- the SQLite
DB, the filesystem, the process table, the raw manifest JSON -- and refuses to import `status.py`'s
readers to do it. Every function below therefore duplicates just enough of `status.py`'s query/scan
logic to answer the same question a second, independent way (this module's own instance of the
"own your own copies" convention `status.py`'s module docstring already names).

`verify(data_dir, status)` is pure given its inputs: `status` is an already-fetched `/api/status`
JSON body, `data_dir` is where to look for ground truth. All I/O here is read-only -- `sqlite3`
connections are `mode=ro`, nothing is written under `data_dir`, `config.yaml`/`tag_pool.json`/
`papers.db` are never touched.

**Fields sampled at different instants can legitimately disagree** between the dashboard's read and
this script's independent read a moment later -- disk headroom, a live process table, a live TEI
health probe. Those are reported as discrepancies with `note` starting `"racy"` and are NOT treated
as failures by `main()`'s exit code; only silence would be dishonest, but hard-failing on them would
be too.

A missing ground-truth source (no `papers.db` yet, no `tag_pool.json`, no `mcp_usage.db`) or a
`status` payload that simply doesn't carry a given field yields no discrepancy at all for that
field -- absent is not disagreement, there is nothing to compare.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

_STAGES = ("harvested", "parsed", "chunked", "summarized", "embedded", "stored", "done")
_DEFAULT_DB_NAME = "papers.db"
_SQLITE_IN_CHUNK = 900
_DISK_TOLERANCE_GB = 2.0  # disk usage can legitimately shift between the dashboard's read and ours
_MAX_ANCESTOR_DEPTH = 32  # bounds the PPID walk against a cycle/reparented process (see status.py)
_LOG_TAIL_BYTES = 65_536
_DOWNLOAD_STALL_RE = re.compile(r"prefetch stalled: (\d+)/(\d+) cached, only (\d+) new available")
_DOWNLOAD_PACE_RE = re.compile(r"downloaded (\d+) / target (\d+)")
_TEI_EMBED_HEALTH_URL = "http://localhost:8080/health"
_TEI_RERANK_HEALTH_URL = "http://localhost:8082/health"

# Sentinel: "derive from the raw run_manifest.json" -- distinct from an explicit `None` ("no run"),
# which a caller must be able to pass.
_UNSET = object()


@dataclass(frozen=True)
class Discrepancy:
    field: str
    dashboard: object
    ground_truth: object
    note: str = ""


def verify(
    data_dir: str | Path,
    status: dict,
    *,
    _pid_parent: Callable[[int], int | None] | None = None,
    _manifest_pid: int | None = _UNSET,  # type: ignore[assignment]
) -> list[Discrepancy]:
    """Every discrepancy between `status` (an already-fetched `/api/status` body) and ground truth
    recomputed from `data_dir`. `_pid_parent`/`_manifest_pid` are test seams for the orphan check
    (real defaults: `/proc/<pid>/stat`'s PPID field, and the raw `run_manifest.json`'s `pid`) --
    never read `/proc` directly in a test."""
    data_dir = Path(data_dir)
    manifest_pid = _manifest_pid_from_disk(data_dir) if _manifest_pid is _UNSET else _manifest_pid
    out: list[Discrepancy] = []
    out += _verify_funnel(data_dir, status.get("funnel"))
    out += _verify_by_doc_type(data_dir, status.get("by_doc_type"))
    out += _verify_run(data_dir, status.get("run"))
    out += _verify_downloads(data_dir, status.get("downloads"))
    out += _verify_downloader(data_dir, status.get("downloader"), _pid_parent, manifest_pid)
    out += _verify_tags(data_dir, status.get("tags"))
    out += _verify_drop_in(data_dir, status.get("drop_in"))
    out += _verify_disk(data_dir, status.get("disk"))
    out += _verify_usage(data_dir, status.get("usage"))
    out += _verify_tei(status.get("tei"))
    return out


# --- shared helpers -------------------------------------------------------------------------------


def _ro_connect(db_path: Path) -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        conn.execute("SELECT 1")
        return conn
    except sqlite3.Error:
        return None


def _cumulative(stage_counts: dict[str, int]) -> dict[str, int]:
    running = 0
    out = {}
    for stage in reversed(_STAGES):
        running += stage_counts.get(stage, 0)
        out[stage] = running
    return out


# --- funnel / by_doc_type (papers.db) -------------------------------------------------------------


def _verify_funnel(data_dir: Path, funnel: dict | None) -> list[Discrepancy]:
    if not funnel:
        return []
    conn = _ro_connect(data_dir / _DEFAULT_DB_NAME)
    if conn is None:
        return []
    try:
        stage_counts = dict(
            conn.execute("SELECT stage, count(*) FROM ingest_state GROUP BY stage").fetchall()
        )
        quarantined = conn.execute(
            "SELECT count(*) FROM quarantine q WHERE NOT EXISTS "
            "(SELECT 1 FROM ingest_state s WHERE s.paper_id = q.paper_id AND s.stage = 'done')"
        ).fetchone()[0]
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    truth = _cumulative(stage_counts)
    truth["quarantined"] = quarantined
    return _diff_dict("funnel", funnel, truth)


def _verify_by_doc_type(data_dir: Path, by_doc_type: dict | None) -> list[Discrepancy]:
    if not by_doc_type:
        return []
    conn = _ro_connect(data_dir / _DEFAULT_DB_NAME)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT p.doc_type, i.stage, count(*) FROM ingest_state i "
            "JOIN papers p ON p.paper_id = i.paper_id GROUP BY p.doc_type, i.stage"
        ).fetchall()
        quarantined = dict(
            conn.execute(
                "SELECT p.doc_type, count(*) FROM quarantine q "
                "JOIN papers p ON p.paper_id = q.paper_id "
                "WHERE NOT EXISTS (SELECT 1 FROM ingest_state s "
                "                  WHERE s.paper_id = q.paper_id AND s.stage = 'done') "
                "GROUP BY p.doc_type"
            ).fetchall()
        )
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    per_type: dict[str, dict[str, int]] = {}
    for doc_type, stage, n in rows:
        per_type.setdefault(str(doc_type), {})[str(stage)] = int(n)

    out: list[Discrepancy] = []
    for doc_type, dash_funnel in by_doc_type.items():
        truth = _cumulative(per_type.get(doc_type, {}))
        truth["quarantined"] = int(quarantined.get(doc_type, 0))
        out += _diff_dict(f"by_doc_type.{doc_type}", dash_funnel, truth)
    return out


def _diff_dict(prefix: str, dashboard: dict, truth: dict) -> list[Discrepancy]:
    return [
        Discrepancy(f"{prefix}.{field}", dashboard[field], value)
        for field, value in truth.items()
        if field in dashboard and dashboard[field] != value
    ]


# --- downloads (pdf_cache/, config.yaml, prefetch.log) --------------------------------------------


def _verify_downloads(data_dir: Path, downloads: dict | None) -> list[Discrepancy]:
    if not downloads:
        return []
    out: list[Discrepancy] = []
    cache_dir = data_dir / "pdf_cache"
    if cache_dir.is_dir():
        if "staged_pdfs" in downloads:
            truth = len(glob.glob(str(cache_dir / "*.pdf")))
            if downloads["staged_pdfs"] != truth:
                out.append(Discrepancy("downloads.staged_pdfs", downloads["staged_pdfs"], truth))
        if "sidecars" in downloads:
            truth = len(glob.glob(str(cache_dir / "*.json")))
            if downloads["sidecars"] != truth:
                out.append(Discrepancy("downloads.sidecars", downloads["sidecars"], truth))

    config_path = data_dir / "config.yaml"
    if config_path.exists() and "prefetch_target" in downloads:
        try:
            cfg = yaml.safe_load(config_path.read_text()) or {}
            truth = cfg.get("prefetch_target", 30_000)
        except yaml.YAMLError:
            truth = None
        if truth is not None and downloads["prefetch_target"] != truth:
            out.append(
                Discrepancy("downloads.prefetch_target", downloads["prefetch_target"], truth)
            )

    log_path = data_dir / "prefetch.log"
    if log_path.exists():
        stalled, new_last_pass = _tail_download_stall(log_path)
        if "stalled" in downloads and downloads["stalled"] != stalled:
            out.append(Discrepancy("downloads.stalled", downloads["stalled"], stalled))
        if new_last_pass is not None and downloads.get("new_last_pass") != new_last_pass:
            out.append(
                Discrepancy(
                    "downloads.new_last_pass", downloads.get("new_last_pass"), new_last_pass,
                    "racy: the log can advance between the dashboard's read and this one",
                )
            )
    return out


def _tail_download_stall(log_path: Path) -> tuple[bool, int | None]:
    try:
        size = log_path.stat().st_size
        with log_path.open("rb") as f:
            f.seek(max(0, size - _LOG_TAIL_BYTES))
            tail = f.read().decode(errors="replace")
    except OSError:
        return False, None
    stall_matches = list(_DOWNLOAD_STALL_RE.finditer(tail))
    if not stall_matches:
        return False, None
    pace_matches = list(_DOWNLOAD_PACE_RE.finditer(tail))
    last_stall = stall_matches[-1]
    if pace_matches and pace_matches[-1].start() > last_stall.start():
        return False, None
    return True, int(last_stall.group(3))


# --- downloader liveness / orphan (process table, raw run_manifest.json) --------------------------


def _manifest_pid_from_disk(data_dir: Path) -> int | None:
    try:
        manifest = json.loads((data_dir / "run_manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return manifest.get("pid")


def _manifest_run_id_from_disk(data_dir: Path) -> str | None:
    try:
        manifest = json.loads((data_dir / "run_manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return manifest.get("run_id")


def _verify_run(data_dir: Path, run: dict | None) -> list[Discrepancy]:
    """O-1: `run.outcome` (`"supply_exhausted"` or `None`, `server.py`'s `/api/status` ->
    `controller.outcome_for_run`) against ground truth read directly from
    `<data_dir>/run_outcome_<run_id>.json` (`app/build_corpus.py`'s own completion record) --
    keyed off the run_id on disk (`run_manifest.json`), NOT `run["run_id"]` from the payload under
    test, so a wrong run_id the dashboard itself reported can't launder its own outcome check."""
    if not run or "outcome" not in run:
        return []
    run_id = _manifest_run_id_from_disk(data_dir)
    truth = None
    if run_id:
        try:
            payload = json.loads((data_dir / f"run_outcome_{run_id}.json").read_text())
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and payload.get("run_id") == run_id:
            truth = payload.get("outcome")
    if run["outcome"] != truth:
        return [Discrepancy("run.outcome", run["outcome"], truth)]
    return []


def _real_pid_parent(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        after_comm = stat.rsplit(")", 1)[1].split()
        return int(after_comm[1])
    except (OSError, IndexError, ValueError):
        return None


def _is_descendant(
    pid: int, ancestor_pid: int | None, pid_parent: Callable[[int], int | None],
) -> bool:
    if ancestor_pid is None:
        return False
    current = pid
    for _ in range(_MAX_ANCESTOR_DEPTH):
        parent = pid_parent(current)
        if parent is None or parent <= 1:
            return False
        if parent == ancestor_pid:
            return True
        current = parent
    return False


def _live_prefetch_pids_via_pgrep() -> list[int] | None:
    """`pgrep -f app.prefetch_pdfs` -- a DIFFERENT mechanism than `status.py::_live_prefetch_pids`
    (which walks `/proc` itself) -- for a broad CANDIDATE set, then two structural checks neither
    imported from nor textually copied off `status.py` narrow it to real downloaders:
    `/proc/<pid>/exe` resolves to a python interpreter binary (`_exe_is_python`), AND
    `/proc/<pid>/cmdline`'s argv (parsed here from scratch, not `status.py`'s
    `_read_cmdline_argv`) has `-m` immediately followed by `app.prefetch_pdfs`
    (`_has_prefetch_module_flag`).

    D-12: `pgrep -f` alone is the exact loose substring predicate that let this cross-check agree
    with `status.py`'s old bug -- a diagnostic `pgrep -af "app.prefetch_pdfs"` or a
    `bash -c "...app.prefetch_pdfs..."` both satisfy `pgrep -f` but fail BOTH structural checks
    here (no python `exe`, no `-m`-adjacent argv), so a flaw in one check can't be masked by the
    other agreeing with it -- and a flaw in `status.py`'s own argv-adjacency logic can't silently
    reproduce here, since this module's argv parsing and python-binary check are its own
    independent code, not a shared helper. `None` (not `[]`) when `pgrep` itself is
    unavailable/errors -- distinct from "confirmed nothing live"."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "app.prefetch_pdfs"], capture_output=True, text=True, timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in (0, 1):  # 1 == "no processes matched", still a valid answer
        return None
    candidates = sorted(int(p) for p in result.stdout.split())
    return [pid for pid in candidates if _exe_is_python(pid) and _has_prefetch_module_flag(pid)]


def _exe_is_python(pid: int) -> bool:
    """`/proc/<pid>/exe` resolves to a binary named like a python interpreter -- a fact `pgrep -f`
    (which only ever looks at cmdline text) cannot see at all, and `status.py`'s reader never
    checks either. A `pgrep`/`grep`/`bash` process naming the pattern in its own arguments fails
    this outright, independent of anything argv-shaped."""
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return False
    return "python" in Path(exe).name


def _has_prefetch_module_flag(pid: int) -> bool:
    """Own from-scratch argv parse (not a call into `status.py`) confirming `-m` is immediately
    followed by `app.prefetch_pdfs` as adjacent argv elements."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    parts = raw.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    argv = [p.decode(errors="replace") for p in parts]
    return any(a == "-m" and b == "app.prefetch_pdfs" for a, b in zip(argv, argv[1:]))


def _verify_downloader(
    data_dir: Path, downloader: dict | None,
    pid_parent: Callable[[int], int | None] | None, manifest_pid: int | None,
) -> list[Discrepancy]:
    if not downloader:
        return []
    pid_parent = pid_parent or _real_pid_parent
    out: list[Discrepancy] = []

    if "orphan" in downloader and "live_pids" in downloader:
        truth = any(
            p != manifest_pid and not _is_descendant(p, manifest_pid, pid_parent)
            for p in downloader["live_pids"]
        )
        if downloader["orphan"] != truth:
            out.append(Discrepancy("downloader.orphan", downloader["orphan"], truth))

    if "live_pids" in downloader:
        truth_live = _live_prefetch_pids_via_pgrep()
        if truth_live is not None and sorted(downloader["live_pids"]) != truth_live:
            out.append(
                Discrepancy(
                    "downloader.live_pids", downloader["live_pids"], truth_live,
                    "racy: a downloader can start/stop between the two reads",
                )
            )
    return out


# --- tags (tag_pool.json) -------------------------------------------------------------------------


def _verify_tags(data_dir: Path, tags: dict | None) -> list[Discrepancy]:
    if not tags:
        return []
    pool_path = data_dir / "tag_pool.json"
    try:
        pool = json.loads(pool_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    out: list[Discrepancy] = []
    if "active_count" in tags:
        truth = len(pool.get("active", []))
        if tags["active_count"] != truth:
            out.append(Discrepancy("tags.active_count", tags["active_count"], truth))
    if "held_count" in tags:
        truth = len(pool.get("held", []))
        if tags["held_count"] != truth:
            out.append(Discrepancy("tags.held_count", tags["held_count"], truth))
    return out


# --- drop_in tray -----------------------------------------------------------------------------


def _count_pdfs(d: Path) -> int:
    if not d.is_dir():
        return 0
    return sum(1 for p in d.iterdir() if p.suffix.lower() == ".pdf")


def _read_drop_in_manifest_ids(drop_dir: Path) -> set[str]:
    ids: set[str] = set()
    for m in sorted(drop_dir.glob("manifest-*.txt")):
        try:
            ids.update(line.strip() for line in m.read_text().splitlines() if line.strip())
        except OSError:
            continue
    return ids


def _processed_count(db_path: Path, manifest_ids: set[str]) -> int | None:
    if not manifest_ids:
        return None
    conn = _ro_connect(db_path)
    if conn is None:
        return None
    try:
        ids = sorted(manifest_ids)
        n = 0
        for i in range(0, len(ids), _SQLITE_IN_CHUNK):
            chunk = ids[i : i + _SQLITE_IN_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            row = conn.execute(
                "SELECT count(*) FROM ingest_state "
                f"WHERE stage = 'done' AND paper_id IN ({placeholders})",  # noqa: S608 - '?' only
                chunk,
            ).fetchone()
            n += row[0]
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return n


def _verify_drop_in(data_dir: Path, drop_in: dict | None) -> list[Discrepancy]:
    if not drop_in or not drop_in.get("dir"):
        return []
    drop_dir = Path(drop_in["dir"])
    if not drop_dir.is_dir():
        return []
    out: list[Discrepancy] = []
    subdirs = {
        "pending_papers": "papers", "pending_books": "books", "staged": "done",
        "failed": "failed", "excluded": "excluded",
    }
    for field, sub in subdirs.items():
        if field not in drop_in:
            continue
        truth = _count_pdfs(drop_dir / sub)
        if drop_in[field] != truth:
            out.append(Discrepancy(f"drop_in.{field}", drop_in[field], truth))

    if "processed" in drop_in and drop_in["processed"] is not None:
        manifest_ids = _read_drop_in_manifest_ids(drop_dir)
        truth = _processed_count(data_dir / _DEFAULT_DB_NAME, manifest_ids)
        if truth is not None and drop_in["processed"] != truth:
            out.append(Discrepancy("drop_in.processed", drop_in["processed"], truth))
    return out


# --- disk headroom (racy by nature) -------------------------------------------------------------


def _verify_disk(data_dir: Path, disk: dict | None) -> list[Discrepancy]:
    if not disk or disk.get("free_gb") is None:
        return []
    try:
        usage = shutil.disk_usage(data_dir)
    except OSError:
        return []
    truth = usage.free / 1e9
    if abs(disk["free_gb"] - truth) > _DISK_TOLERANCE_GB:
        return [
            Discrepancy(
                "disk.free_gb", disk["free_gb"], truth,
                "racy: disk usage can shift between the dashboard's read and this one",
            )
        ]
    return []


# --- usage (mcp_usage.db) -----------------------------------------------------------------------


def _verify_usage(data_dir: Path, usage: dict | None) -> list[Discrepancy]:
    if not usage:
        return []
    db_path = data_dir / "mcp_usage.db"
    if not db_path.exists():
        if usage.get("available") not in (False, None):
            return [Discrepancy("usage.available", usage.get("available"), False)]
        return []
    conn = _ro_connect(db_path)
    if conn is None:
        return []
    try:
        truth = conn.execute("SELECT count(*) FROM requests").fetchone()[0]
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    if "total" in usage and usage["total"] != truth:
        return [Discrepancy("usage.total", usage["total"], truth)]
    return []


# --- TEI live health (racy by nature) -----------------------------------------------------------


def _probe_tei_health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3.0):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _verify_tei(tei: dict | None) -> list[Discrepancy]:
    if not tei:
        return []
    out: list[Discrepancy] = []
    checks = {"embed_healthy": _TEI_EMBED_HEALTH_URL, "rerank_healthy": _TEI_RERANK_HEALTH_URL}
    for field, url in checks.items():
        if field not in tei:
            continue
        truth = _probe_tei_health(url)
        if tei[field] != truth:
            out.append(Discrepancy(f"tei.{field}", tei[field], truth, "racy: live health probe"))
    return out


# --- CLI ------------------------------------------------------------------------------------------


def _fetch_status(data_dir: Path, host: str, port: int) -> dict:
    token = (data_dir / ".dashboard_token").read_text().strip()
    req = urllib.request.Request(
        f"http://{host}:{port}/api/status", headers={"X-Dashboard-Token": token},
    )
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        return json.loads(resp.read())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8700)
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)

    try:
        status = _fetch_status(data_dir, args.host, args.port)
    except (OSError, json.JSONDecodeError) as e:
        print(f"verify_numbers: could not fetch /api/status: {e}")
        return 1

    discrepancies = verify(data_dir, status)
    if not discrepancies:
        print("verify_numbers: OK -- every field matches ground truth")
        return 0

    hard = [d for d in discrepancies if not d.note.startswith("racy")]
    racy = [d for d in discrepancies if d.note.startswith("racy")]
    for label, group in (("DISCREPANCY", hard), ("racy (informational)", racy)):
        for d in group:
            note = f" ({d.note})" if d.note and label == "DISCREPANCY" else ""
            print(
                f"{label:22s} {d.field}: dashboard={d.dashboard!r} "
                f"ground_truth={d.ground_truth!r}{note}"
            )
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
