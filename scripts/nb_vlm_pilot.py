"""NB-VLM-PILOT harness — bounded VLM falsification pilot (NB-6 §3 protocol).

Throwaway experiment tooling (programme constraint 9 home: scripts/). Subcommands:

  population   Draw the N=100 stratified figure-bearing-page sample (O4) -> population.json
  audit-g03    Fitz-first true-vision re-audit of the 5 D1-unreachable items (G0.3)
  render       Render gold + sampled pages to PNG cache (pymupdf, dpi fixed at 170)
  describe     Blind VLM describe of rendered pages via Ollama under FileGpuLock;
               per-page wall timing (G0.2) + optional background VRAM sampling (G0.1)

Read-only against the corpus DB; writes only under docs/eval-reports/data/2026-08-25-nb6-pilot/.
GPU discipline: every Ollama inference call acquires the production `.gpu.lock` so sibling
lanes queue ahead of us, never around our sleeps.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

WAYMO_DATA = Path("/home/omar/ai-projects/research-system-rag/waymo/data")
DB_PATH = WAYMO_DATA / "papers.db"
PDF_CACHE = WAYMO_DATA / "pdf_cache"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs/eval-reports/data/2026-08-25-nb6-pilot"
RENDER_DIR = OUT_DIR / "renders"
GPU_LOCK_PATH = Path("/home/omar/ai-projects/research-system-rag/.gpu.lock")
OLLAMA_URL = "http://localhost:11434"

SAMPLE_N = 100
RENDER_DPI = 170  # inside NB-6 §2's 150-200 ESTIMATE band

# --- pre-registered constants (stub commit 173fb96; do not tune after results exist) ---

SEED = 20260825

# O4 strata signals, applied to a page's concatenated figure captions (lowercased).
CHART_RE = re.compile(r"chart|\bgraph\b|bar\b|\bline plot|scatter|histogram|\bplot\b|curve")
DIAGRAM_RE = re.compile(r"diagram|architecture|\bmap\b|layout|timeline|flow|schematic|overview of")
GENERIC_CAPTION_RE = re.compile(
    r"^\s*\(?\s*[a-f]?\)?\s*(figure|fig\.?|table|exhibit)?\s*\d*\s*[:.\)]?\s*$")

# O1/O6: per-item audit tokens (normalized substring/boundary-regex targets) and the
# fixture-derived asked-value count used for Stage 1 scoring.
ITEMS = [
    {
        "question_id": "Q-WAYB-027",
        "paper_id": "2208.12833",
        "page": 35,
        "gold_block_id": "2208.12833:b188",
        "audit_tokens": ["human drowsiness rating", "vigilance assessment"],
        "asked_values_n": 3,
    },
    {
        "question_id": "Q-GTA-042",
        "paper_id": "2508.19425",
        "page": 13,
        "gold_block_id": "2508.19425:b88",
        "audit_tokens": ["crashed passenger vehicles", "ipmm"],
        "asked_values_n": 1,
    },
    {
        "question_id": "Q-GTA-043",
        "paper_id": "2506.08228",
        "page": 9,
        "gold_block_id": "2506.08228:b75",
        "audit_tokens": ["0.026", "-0.18", "1.03"],
        "asked_values_n": 2,
        "numeric_tokens": True,
    },
    {
        "question_id": "Q-GTA-044",
        "paper_id": "2104.10133",
        "page": 7,
        "gold_block_id": "2104.10133:b66",
        "audit_tokens": [
            "99.29", "93.50", "87.31",
            "0.1849", "0.1958", "0.2738",
            "0.2342", "0.2721", "0.3800",
        ],
        "asked_values_n": 6,
        "numeric_tokens": True,
    },
    {
        "question_id": "Q-WMR-094",
        "paper_id": "2312.12675",
        "page": 9,
        "gold_block_id": "2312.12675:b66",
        "audit_tokens": ["86%", "54%"],
        "asked_values_n": 2,
    },
]

# O3: the single fixed describe prompt. Contains no fixture content.
DESCRIBE_PROMPT = (
    "You are given one page of a research paper as an image. Describe everything informative "
    "on this page for a retrieval system: transcribe the caption(s) verbatim; for every chart, "
    "graph, diagram or table state what it shows, its title, axis labels, legend entries, and "
    "any printed numeric values, exactly as legible. Be exhaustive about printed text inside "
    "figures; do not speculate beyond what is visible."
)

# O6 survivor rule: an item is DISCOUNTED (not true-vision) iff >=50% of its audit tokens are
# recoverable via fitz get_text() (whole page OR gold-region clip, normalized). Else it survives.


def connect_ro() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2009", " ").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text)


def token_hit(norm_text: str, token: str, numeric: bool) -> bool:
    if not numeric:
        return token in norm_text
    # boundary-guarded so '1.03' doesn't match '1.034' etc.
    pat = r"(?<![\w.])" + re.escape(token) + r"(?![\w])"
    return re.search(pat, norm_text) is not None


# ---------------------------------------------------------------- population ---

def cmd_population(args: argparse.Namespace) -> None:
    con = connect_ro()
    rows = con.execute(
        """
        SELECT paper_id, page, GROUP_CONCAT(caption, ' || ') AS captions, COUNT(*) AS n_fig
        FROM figures GROUP BY paper_id, page
        """
    ).fetchall()
    con.close()

    eligible: list[dict] = []
    excluded_no_pdf = 0
    for r in rows:
        if not (PDF_CACHE / f"{r['paper_id']}.pdf").exists():
            excluded_no_pdf += 1
            continue
        caps = [normalize(c) for c in (r["captions"] or "").split(" || ") if c and c.strip()]
        non_generic = [c for c in caps if not GENERIC_CAPTION_RE.match(c)]
        if any(CHART_RE.search(c) for c in caps):
            stratum = "chart"
        elif any(DIAGRAM_RE.search(c) for c in caps):
            stratum = "diagram"
        elif non_generic:
            stratum = "caption-only"  # has real captions but no chart/diagram signal
        else:
            stratum = "caption-only"  # empty/generic captions only
        eligible.append(
            {"paper_id": r["paper_id"], "page": r["page"], "stratum": stratum,
             "n_figures": r["n_fig"],
             "caption_sample": (non_generic[0] if non_generic else "")[:120]}
        )

    strata = sorted({e["stratum"] for e in eligible})
    counts = {s: sum(1 for e in eligible if e["stratum"] == s) for s in strata}
    total = len(eligible)
    rng = random.Random(SEED)
    drawn: list[dict] = []
    alloc: dict[str, int] = {}
    # largest-remainder proportional allocation, deterministic order
    exact = {s: counts[s] / total * SAMPLE_N for s in strata}
    floors = {s: int(exact[s]) for s in strata}
    rem = SAMPLE_N - sum(floors.values())
    order = sorted(strata, key=lambda s: (-(exact[s] - floors[s]), s))
    for i, s in enumerate(order):
        alloc[s] = floors[s] + (1 if i < rem else 0)
    for s in strata:
        pool = [e for e in eligible if e["stratum"] == s]
        rng.shuffle(pool)
        take = min(alloc[s], len(pool))
        drawn.extend(pool[:take])
        alloc[s] = take
    rng.shuffle(drawn)

    out = {
        "seed": SEED,
        "frame": "waymo/data/papers.db figures GROUP BY (paper_id, page)",
        "frame_total_pages_with_any_pdf": total,
        "pages_excluded_pdf_missing": excluded_no_pdf,
        "strata_frame_counts": counts,
        "strata_weights_frac_of_frame": {s: round(counts[s] / total, 4) for s in strata},
        "allocation": alloc,
        "drawn": drawn,
    }
    path = OUT_DIR / "population.json"
    path.write_text(json.dumps(out, indent=1))
    print(f"eligible={total} excluded(no pdf)={excluded_no_pdf}")
    print(f"strata frame counts={counts} weights={out['strata_weights_frac_of_frame']}")
    print(f"drew {len(drawn)} -> {path}")


# ---------------------------------------------------------------- audit g03 ----

def cmd_audit_g03(_: argparse.Namespace) -> None:
    import pymupdf

    results = []
    for item in ITEMS:
        pdf = PDF_CACHE / f"{item['paper_id']}.pdf"
        doc = pymupdf.open(pdf)
        page = doc[item["page"]]
        whole = normalize(page.get_text())
        bbox = json.loads(
            connect_ro().execute(
                "SELECT bbox_json FROM blocks WHERE block_id=?", (item["gold_block_id"],)
            ).fetchone()[0]
        )
        clip = pymupdf.Rect(bbox[0] - 20, bbox[1] - 20, bbox[2] + 20, bbox[3] + 20)
        region = normalize(page.get_text(clip=clip))
        doc.close()
        numeric = item.get("numeric_tokens", False)
        tokens = {}
        for tok in item["audit_tokens"]:
            tokens[tok] = {
                "whole_page": token_hit(whole, tok, numeric),
                "gold_region": token_hit(region, tok, numeric),
            }
        n_hit = sum(1 for t in tokens.values() if t["whole_page"] or t["gold_region"])
        frac = n_hit / len(item["audit_tokens"])
        results.append({
            **{k: item[k] for k in ("question_id", "paper_id", "page", "gold_block_id")},
            "tokens": tokens,
            "tokens_hit": n_hit,
            "tokens_total": len(item["audit_tokens"]),
            "text_reachable_frac": round(frac, 3),
            "survives_as_true_vision": frac < 0.5,
        })

    survivors = [r["question_id"] for r in results if r["survives_as_true_vision"]]
    out = {"rule": "discounted iff >=50% of audit tokens text-reachable (O6)", "items": results,
           "survivors": survivors, "n_survivors": len(survivors),
           "gate": ("PASS (continue)" if len(survivors) >= 3
                    else "FAIL (<3 survive -> STOP, operator review)")}
    (OUT_DIR / "g03_audit.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


# ---------------------------------------------------------------- render -------


def cmd_render(_: argparse.Namespace) -> None:
    import pymupdf

    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    wanted = {f"{it['paper_id']}_p{it['page']}": it["page"] for it in ITEMS}
    pop = json.loads((OUT_DIR / "population.json").read_text())
    for e in pop["drawn"]:
        wanted[f"{e['paper_id']}_p{e['page']}"] = e["page"]

    missing = []
    done = 0
    for key, page in sorted(wanted.items()):
        paper_id = key.rsplit("_p", 1)[0]
        dest = RENDER_DIR / f"{key}.png"
        if dest.exists():
            done += 1
            continue
        pdf = PDF_CACHE / f"{paper_id}.pdf"
        if not pdf.exists():
            missing.append(key)
            continue
        doc = pymupdf.open(pdf)
        pix = doc[page].get_pixmap(dpi=RENDER_DPI)
        pix.save(dest)
        doc.close()
        done += 1
    sizes = [p.stat().st_size for p in RENDER_DIR.glob("*.png")]
    print(f"rendered/total={done}/{len(wanted)} missing_pdfs={len(missing)} "
          f"avg_kb={int(sum(sizes) / max(len(sizes), 1) / 1024)}")
    if missing:
        print("missing:", missing[:10])


# ---------------------------------------------------------------- describe -----

def vram_sampler(stop_evt: threading.Event, samples: list[str]) -> None:
    while not stop_evt.is_set():
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True).stdout.strip()
        samples.append(f"{time.time():.0f},{out}")
        time.sleep(2.0)


def cmd_describe(args: argparse.Namespace) -> None:
    import urllib.request

    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from rag.gpu_lock import FileGpuLock

    keys: list[str] = []
    if args.gold_only:
        keys = [f"{it['paper_id']}_p{it['page']}" for it in ITEMS]
    else:
        pop = json.loads((OUT_DIR / "population.json").read_text())
        keys = [f"{e['paper_id']}_p{e['page']}" for e in pop["drawn"]]
        keys += [f"{it['paper_id']}_p{it['page']}" for it in ITEMS]
    keys = [k for k in keys if (RENDER_DIR / f"{k}.png").exists()]

    default_out = "descriptions.jsonl" if not args.gold_only else "descriptions_gold.jsonl"
    out_path = OUT_DIR / (args.out or default_out)
    already = set()
    if out_path.exists() and not args.fresh:
        for line in out_path.read_text().splitlines():
            if line.strip():
                already.add(json.loads(line)["key"])
    fout = open(out_path, "a")
    samples: list[str] = []
    stop_evt = threading.Event()
    if args.sample_vram:
        threading.Thread(target=vram_sampler, args=(stop_evt, samples), daemon=True).start()

    lock = FileGpuLock(GPU_LOCK_PATH)
    timings = []
    try:
        for key in keys:
            if key in already:
                continue
            img_b64 = base64.b64encode((RENDER_DIR / f"{key}.png").read_bytes()).decode()
            payload = json.dumps({
                "model": args.model,
                "messages": [{"role": "user", "content": DESCRIBE_PROMPT, "images": [img_b64]}],
                "stream": False,
                "options": {"temperature": 0,
                            "num_predict": args.num_predict, "num_ctx": args.num_ctx},
            }).encode()
            req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=payload,
                                         headers={"Content-Type": "application/json"})
            t0 = time.time()
            with lock.acquire("nb_vlm_pilot_describe"):
                resp = urllib.request.urlopen(req, timeout=600)
                body = json.loads(resp.read())
            dt = time.time() - t0
            desc = body.get("message", {}).get("content", "")
            rec = {"key": key, "model": args.model, "seconds": round(dt, 2),
                   "chars": len(desc), "description": desc}
            fout.write(json.dumps(rec) + "\n")
            fout.flush()
            timings.append(dt)
            print(f"{key}: {dt:.1f}s chars={len(desc)}", flush=True)
    finally:
        stop_evt.set()
        fout.close()
        if samples:
            (OUT_DIR / f"vram_samples_{args.tag_label}.csv").write_text(
                "epoch_s,used_mib,total_mib\n" + "\n".join(samples))
    if timings:
        timings.sort()
        n = len(timings)
        print(f"\nn={n} min={timings[0]:.1f}s median={timings[n // 2]:.1f}s "
              f"p90={timings[int(n * 0.9)]:.1f}s max={timings[-1]:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("population").set_defaults(func=cmd_population)
    sub.add_parser("audit-g03").set_defaults(func=cmd_audit_g03)
    sub.add_parser("render").set_defaults(func=cmd_render)
    d = sub.add_parser("describe")
    d.add_argument("--model", required=True)
    d.add_argument("--num-predict", type=int, default=700)
    d.add_argument("--num-ctx", type=int, default=8192)
    d.add_argument("--gold-only", action="store_true")
    d.add_argument("--sample-vram", action="store_true")
    d.add_argument("--tag-label", default="run")
    d.add_argument("--out", default=None)
    d.add_argument("--fresh", action="store_true")
    d.set_defaults(func=cmd_describe)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
