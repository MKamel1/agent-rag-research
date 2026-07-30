"""THROWAWAY ANALYSIS SCRIPT -- Experiment 3 (docs/PLAN-book-rag-experiments.md): simulates a
Part -> Chapter hierarchy as a routing strategy over Experiment 1's already-embedded chapter
vectors, WITHOUT building it. Not shipped code, not reused by any other module, no CI dependency
on it beyond "it still runs and its own tests still pass" -- same posture `app/exp1_outline_split.py`
documents for itself ("spike script, no unit-test file" -- this one gets a thin test file for its
pure logic, following that same convention, since it has enough branching to be worth one).

**Persists nothing.** No writes to `summaries`, no migration, no `contracts/` change, no new
vector-store collection -- every Part-title embedding this script computes is used once, in memory, and never
upserted anywhere (`docs/PLAN-book-rag-experiments.md`'s own Experiment 3 section: "computed but
never persisted").

Mechanism (see the plan's Experiment 3 section for the full spec this implements):

  (a) FLAT -- reproduces Experiment 1's own chapter-routing number (0.325) EXACTLY, by reusing
      `app.retrieval_eval.load_questions/run/build_report` UNMODIFIED against the real
      `Retriever.retrieve_papers()` pipeline (same rerank + per-paper cap Experiment 1 scored
      through), pointed at the same throwaway `exp1_outline_chapters` vector-store collection and a
      READ-ONLY COPY of Experiment 1's own throwaway `papers.db`/`blobs` (see `_EXP1_WORK_DIR`
      below for why copying, not regenerating, is correct here). This is the script's own
      self-check: if this number doesn't match, the rest of the run is not trustworthy and `main()`
      stops before spending anything on step (b).

  (b) SIMULATED HIERARCHICAL -- for the ONE outline-bearing book whose PDF outline actually has a
      level coarser than the level Experiment 1 picked as "chapter" (`usable_parent_level` below;
      empirically only `local:f0929288d4f3`, Causal Inference in Python -- see the report doc for
      why the other 3 books structurally cannot participate, verified by `pick_outline_level`
      against their real `get_toc()` output, not assumed): embeds each top-level Part's own outline
      title once (ad hoc, never persisted), routes each question to its single best-matching Part
      by cosine similarity (vectors are L2-normalized per `TeiEmbedder`'s own contract, so a plain
      dot product IS cosine similarity), then reads chapter-level candidates back from
      `exp1_outline_chapters` via `VectorIndex.hybrid_search` (kind="summary", no rerank -- the
      plan's own cost estimate scopes this experiment to "a handful of additional embedding calls",
      not a second reranker pass) and keeps only the hits whose id belongs to the routed Part's
      children, in that hybrid-fused order, truncated to `k`.

`_EXP1_WORK_DIR` points at `/home/omar/ai-projects/rag-exp1`'s own scratch dir (untracked,
git-ignored, worktree-local per Experiment 1's own report) -- this worktree has none of its own
(`git worktree add` never copies untracked files), so a READ (never a write) of that directory is
the only way to get Experiment 1's exact final chapter/overview text without either (a) re-running
`summarize_book()` through the real LLM a second time (real GPU cost this experiment is explicitly
NOT supposed to pay -- "near-zero GPU" per the plan) or (b) reconstructing it from the vector
store's own payload text via a new `VectorIndex` read method this experiment has no need to add. Exactly the same
"read another worktree/checkout's files, never write them" pattern `app/exp1_outline_split.py`'s
own `PDF_DIR` already uses for the corpus's PDFs (see that module's docstring) -- reading bytes out
of a sibling worktree is not "touching" it.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
from pathlib import Path

import httpx

from app.exp1_outline_split import BOOK_IDS, PDF_DIR, _pdf_filenames, compute_splits, load_outline_entries
from app.retrieval_eval import build_report, load_questions, run
from contracts.embedder import EmbedderInfo
from contracts.vector_index import SearchFilters
from rag.book_summarizer import OutlineEntry, pick_outline_level
from rag.config import load_config
from rag.embedder import TeiEmbedder
from rag.gpu_lock import FileGpuLock
from rag.vector_index import VectorIndex

logger = logging.getLogger(__name__)

# Same real-service wiring app/assembly.py / app/exp1_outline_split.py already use -- composition
# constants, not Config fields (see those modules' own comments on why).
_TEI_EMBED_URL = "http://localhost:8080"
_VECTOR_STORE_HOST = "localhost"
_VECTOR_STORE_PORT = 6333
_EMBEDDER_INFO = EmbedderInfo(model_id="Qwen3-Embedding-4B", dim=2560, version="v1")

# Experiment 1's own throwaway scratch dir -- see module docstring for why this is a read, not a
# write, and why copying (not regenerating) is the GPU-free-correct choice here.
_EXP1_WORK_DIR = Path("/home/omar/ai-projects/rag-exp1/.exp1-work")

_DEST_COLLECTION = "exp1_outline_chapters"
_EXPECTED_FLAT_RECALL = 0.325  # Experiment 1's own reported chapter-routing recall@10
_PART_SEARCH_POOL = 5000  # >> any book's own chapter count; cheap (one vector-store query, no rerank)


class Exp3Error(RuntimeError):
    """The run can't proceed as configured, or a self-check failed -- refuses to continue rather
    than reporting a number that hasn't been validated."""


# --------------------------------------------------------------------------------------------
# Pure logic (GPU-free, corpus-free) -- exercised by app/test_exp3_hierarchy_sim.py
# --------------------------------------------------------------------------------------------


def usable_parent_level(entries: list[OutlineEntry]) -> int | None:
    """The outline level one step coarser than the level Experiment 1's own `pick_outline_level`
    chose as "chapter", or `None` if no such level exists. Level 0 is `pypdfium2.get_toc()`'s own
    outermost level (`docs/eval-reports/2026-07-29-outline-join-feasibility.md`'s Q1 finding) --
    a book whose chapters were picked AT level 0 has nothing coarser to route through, structurally,
    not as a judgment call. Applies `docs/PLAN-book-rag-experiments.md`'s Experiment 3 mechanism to
    Experiment 1's own level choice, not a second independent rule.
    """
    chapter_level = pick_outline_level(entries)
    return chapter_level - 1 if chapter_level > 0 else None


def boundary_titles(entries: list[OutlineEntry], level: int) -> tuple[list[int], dict[int, str]]:
    """Same construction `rag.book_summarizer._split_chapters_outline` uses internally for its own
    chapter level -- reused at the PARENT level here. Returns (sorted unique page boundaries,
    {boundary_page: title}), earliest entry at a shared page winning the title (same tie-break)."""
    level_entries = [e for e in entries if e.level == level]
    boundaries = sorted({e.page_index for e in level_entries})
    title_by_boundary: dict[int, str] = {}
    for e in sorted(level_entries, key=lambda e: e.page_index):
        title_by_boundary.setdefault(e.page_index, e.title.strip())
    return boundaries, title_by_boundary


def assign_boundary(page: int, boundaries: list[int]) -> int:
    """Index into `boundaries` of the last boundary <= `page` -- the same per-block boundary
    assignment `_split_chapters_outline` runs, applied here to a whole chapter unit's own first
    page rather than to every block."""
    idx = 0
    for i, b in enumerate(boundaries):
        if page >= b:
            idx = i
    return idx


def chapter_to_part(chapter_first_pages: list[int], part_boundaries: list[int]) -> list[int]:
    """`chapter_to_part(...)[n]` is the Part-boundary index chapter unit `n` belongs to."""
    return [assign_boundary(p, part_boundaries) for p in chapter_first_pages]


def route_part(qvec: list[float], part_vecs: list[list[float]]) -> int:
    """Argmax cosine similarity -- a plain dot product, since `TeiEmbedder.embed()` L2-normalizes
    every vector it returns (that class's own documented postcondition). "Route to THE top-level
    Part" (plan's own wording, singular) -- a hard top-1 decision, not a top-N shortlist."""
    return max(range(len(part_vecs)), key=lambda i: sum(a * b for a, b in zip(qvec, part_vecs[i])))


def restrict_and_rank(hit_ids: list[str], allowed: set[str], k: int) -> list[str]:
    """`hit_ids` in their existing (already globally fused-ranked) order, filtered down to only
    ids in `allowed`, truncated to `k` -- "only consider that Part's child chapters for the
    chapter-level score" (plan's own wording)."""
    return [h for h in hit_ids if h in allowed][:k]


def rank_of(gold_id: str, ranked_ids: list[str]) -> int | None:
    return ranked_ids.index(gold_id) + 1 if gold_id in ranked_ids else None


def recall_mrr(ranks: list[int | None]) -> dict:
    n = len(ranks)
    if n == 0:
        return {"recall_at_k": None, "mrr": None, "n": 0}
    hits = sum(1 for r in ranks if r is not None)
    rr_sum = sum(1.0 / r for r in ranks if r is not None)
    return {"recall_at_k": hits / n, "mrr": rr_sum / n, "n": n}


# --------------------------------------------------------------------------------------------
# Level-structure survey (GPU-free, read-only corpus access) -- which books can participate
# --------------------------------------------------------------------------------------------


def survey_books(conn: sqlite3.Connection) -> dict:
    """For every outline-bearing book: its raw `get_toc()` level histogram, the chapter level
    Experiment 1 picked, and whether a usable parent (Part) level exists. Answers "which books
    could actually be simulated" from data, not from re-stating the gate doc's own prose."""
    pdf_by_id = _pdf_filenames(conn, BOOK_IDS)
    report = {}
    for paper_id in BOOK_IDS:
        entries = load_outline_entries(PDF_DIR / pdf_by_id[paper_id])
        levels: dict[int, int] = {}
        for e in entries:
            levels[e.level] = levels.get(e.level, 0) + 1
        chapter_level = pick_outline_level(entries)
        parent_level = usable_parent_level(entries)
        report[paper_id] = {
            "level_histogram": dict(sorted(levels.items())),
            "chapter_level": chapter_level,
            "parent_level": parent_level,
            "hierarchy_usable": parent_level is not None,
        }
    return report


# --------------------------------------------------------------------------------------------
# Arm (a): flat -- reuses the real Retriever pipeline unmodified
# --------------------------------------------------------------------------------------------


def stage_exp1_db_copy(work_dir: Path) -> tuple[Path, Path]:
    """Read-only copy of Experiment 1's own throwaway `papers.db` + `blobs/` -- see module
    docstring for why this is correct and GPU-free. Copies INTO `work_dir` (this worktree's own
    scratch), never writes anything under `_EXP1_WORK_DIR` itself."""
    work_dir.mkdir(parents=True, exist_ok=True)
    dest_db = work_dir / "papers.db"
    dest_blobs = work_dir / "blobs"
    src_db = _EXP1_WORK_DIR / "papers.db"
    src_blobs = _EXP1_WORK_DIR / "blobs"
    if not src_db.exists():
        raise Exp3Error(
            f"{src_db} not found -- Experiment 1's throwaway db copy is required to reproduce its "
            "flat chapter-routing number (see module docstring); it must still exist in "
            "rag-exp1's own worktree scratch dir"
        )
    shutil.copy2(src_db, dest_db)
    if dest_blobs.exists():
        shutil.rmtree(dest_blobs)
    shutil.copytree(src_blobs, dest_blobs)
    return dest_db, dest_blobs


def run_flat_arm(config_path: str | None, db_path: Path, blob_dir: Path, fixture_path: Path, k: int) -> dict:
    """`app.retrieval_eval`'s own `load_questions`/`run`/`build_report`, UNMODIFIED -- this
    experiment must never touch that harness (task instruction), only call it."""
    from app.assembly import build_mcp_server  # deferred: pulls in real GPU-backed adapter wiring

    cfg = load_config(config_path)
    server = build_mcp_server(
        cfg, db_path=str(db_path), blob_dir=str(blob_dir), collection=_DEST_COLLECTION
    )
    questions = load_questions(fixture_path)
    results = run(questions, server.retriever, k)
    return build_report(results, k, include_per_question=True)


# --------------------------------------------------------------------------------------------
# Arm (b): simulated hierarchical -- Part-title embeddings computed ad hoc, never persisted
# --------------------------------------------------------------------------------------------


def build_hierarchy(conn: sqlite3.Connection, paper_id: str) -> dict:
    """Everything needed to simulate routing for one participating book: Part boundaries/titles,
    each chapter unit's parent Part index, and the gold-index -> parent-Part-index map."""
    pdf_by_id = _pdf_filenames(conn, [paper_id])
    entries = load_outline_entries(PDF_DIR / pdf_by_id[paper_id])
    parent_level = usable_parent_level(entries)
    if parent_level is None:
        raise Exp3Error(f"{paper_id}: no usable parent level -- caller must check first")

    part_boundaries, part_titles_by_boundary = boundary_titles(entries, parent_level)
    part_titles = [part_titles_by_boundary[b] for b in part_boundaries]

    splits = compute_splits(conn)
    units = splits[paper_id].units
    first_pages = [blocks[0].page for _, blocks in units]
    parent_index = chapter_to_part(first_pages, part_boundaries)

    part_children: dict[int, list[int]] = {i: [] for i in range(len(part_boundaries))}
    for chapter_idx, part_idx in enumerate(parent_index):
        part_children[part_idx].append(chapter_idx)

    return {
        "part_titles": part_titles,
        "part_children": part_children,  # part_index -> [chapter_index, ...]
        "chapter_to_part": parent_index,  # chapter_index -> part_index
        "unit_titles": [t for t, _ in units],
        "unit_count": len(units),
    }


def run_hierarchical_arm(
    config_path: str | None, fixture_path: Path, paper_id: str, k: int
) -> dict:
    cfg = load_config(config_path)
    corpus_conn = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True)
    corpus_conn.row_factory = sqlite3.Row
    hierarchy = build_hierarchy(corpus_conn, paper_id)
    corpus_conn.close()

    gpu_lock = FileGpuLock(Path(cfg.gpu_lock_path))
    embedder = TeiEmbedder(httpx.Client(base_url=_TEI_EMBED_URL, timeout=60.0), gpu_lock, _EMBEDDER_INFO)
    vector_index = VectorIndex(
        _VECTOR_STORE_HOST, _VECTOR_STORE_PORT, _DEST_COLLECTION, _EMBEDDER_INFO.dim, cfg.hybrid_dense_weight
    )

    # Ad hoc Part-title embeddings -- computed once, reused for every question on this book, NEVER
    # upserted anywhere (plan's own "computed but never persisted"). TeiEmbedder.embed() acquires
    # the shared FileGpuLock internally, per call (rag/embedder.py's own documented contract) --
    # this IS "taking the GPU lock for the handful of Part embeddings" the task asked for.
    part_vecs = embedder.embed(hierarchy["part_titles"])

    all_chapter_ids = {
        i: f"{paper_id}:summary:ch{i}" for i in range(hierarchy["unit_count"])
    }
    all_ids = set(all_chapter_ids.values())

    fixture = json.loads(fixture_path.read_text())
    questions = [r for r in fixture["ground_truth"] if r["source_paper_id"] == paper_id]

    per_question = []
    for r in questions:
        qtext = r["question_text"]
        gold_idx = r["gold_chapter_index"]
        gold_part = hierarchy["chapter_to_part"][gold_idx]
        gold_id = all_chapter_ids[gold_idx]

        qvec = embedder.embed([qtext])[0]
        routed_part = route_part(qvec, part_vecs)
        hits = vector_index.hybrid_search(
            qvec, qtext, SearchFilters(kind="summary"), _PART_SEARCH_POOL
        )
        hit_ids = [h.id for h in hits]

        part_children_ids = {
            all_chapter_ids[c] for c in hierarchy["part_children"].get(routed_part, [])
        }
        hier_ranked = restrict_and_rank(hit_ids, part_children_ids, k)
        hier_rank = rank_of(gold_id, hier_ranked)

        # Book-scoped-flat control: same raw hybrid_search + no rerank + no cross-book competition,
        # but WITHOUT the Part restriction -- isolates "scoping to one book" from "scoping to one
        # Part within that book", so the Part-specific effect can be read on its own.
        book_ranked = restrict_and_rank(hit_ids, all_ids, k)
        book_rank = rank_of(gold_id, book_ranked)

        per_question.append({
            "question_id": r["question_id"],
            "gold_chapter_index": gold_idx,
            "gold_chapter_title": r["gold_chapter_title"],
            "gold_part_index": gold_part,
            "gold_part_title": hierarchy["part_titles"][gold_part],
            "routed_part_index": routed_part,
            "routed_part_title": hierarchy["part_titles"][routed_part],
            "part_routing_correct": routed_part == gold_part,
            "part_children_count": len(hierarchy["part_children"].get(routed_part, [])),
            "hierarchical_rank": hier_rank,
            "book_scoped_flat_rank": book_rank,
        })

    return {
        "paper_id": paper_id,
        "hierarchy": {
            "part_titles": hierarchy["part_titles"],
            "part_children": hierarchy["part_children"],
            "unit_titles": hierarchy["unit_titles"],
        },
        "questions": per_question,
        "part_routing_accuracy": recall_mrr(
            [1 if q["part_routing_correct"] else None for q in per_question]
        ),
        "hierarchical_chapter_level": recall_mrr([q["hierarchical_rank"] for q in per_question]),
        "book_scoped_flat_chapter_level": recall_mrr(
            [q["book_scoped_flat_rank"] for q in per_question]
        ),
    }


# --------------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--work-dir", default=".exp3-work")
    parser.add_argument("--fixture", default="fixtures/eval/eval_book_questions_outline_split.json")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--report-out", default=None)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()
    cfg = load_config(args.config)
    fixture_path = Path(args.fixture)

    corpus_conn = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True)
    corpus_conn.row_factory = sqlite3.Row
    survey = survey_books(corpus_conn)
    corpus_conn.close()
    print("Level-structure survey:")
    print(json.dumps(survey, indent=2))

    usable = [pid for pid, s in survey.items() if s["hierarchy_usable"]]
    print(f"\nBooks with a usable parent (Part) level: {usable}")
    print(f"Books WITHOUT one (cannot participate): {[p for p in survey if p not in usable]}")

    work_dir = Path(args.work_dir)
    db_path, blob_dir = stage_exp1_db_copy(work_dir)
    flat_report = run_flat_arm(args.config, db_path, blob_dir, fixture_path, args.k)
    flat_recall = flat_report["chapter_level"]["overall"]["recall_at_k"]
    print(f"\nArm (a) flat chapter-routing recall@{args.k}: {flat_recall}")

    if flat_recall is None or abs(flat_recall - _EXPECTED_FLAT_RECALL) > 1e-9:
        raise Exp3Error(
            f"Arm (a) flat recall@{args.k} = {flat_recall!r}, expected {_EXPECTED_FLAT_RECALL} "
            "(Experiment 1's own reported number) -- stopping before arm (b); something upstream "
            "changed (wrong collection/db copy/fixture) and must be checked before proceeding."
        )
    print("Arm (a) reproduces Experiment 1's 0.325 exactly -- proceeding to arm (b).")

    hierarchical_results = {}
    for paper_id in usable:
        hierarchical_results[paper_id] = run_hierarchical_arm(args.config, fixture_path, paper_id, args.k)
        print(f"\n{paper_id} hierarchical arm:")
        print(json.dumps(hierarchical_results[paper_id]["hierarchical_chapter_level"], indent=2))
        print(f"{paper_id} book-scoped-flat control:")
        print(json.dumps(hierarchical_results[paper_id]["book_scoped_flat_chapter_level"], indent=2))

    output = {
        "survey": survey,
        "usable_books": usable,
        "flat_arm_report": flat_report,
        "hierarchical_results": hierarchical_results,
    }
    if args.report_out:
        Path(args.report_out).write_text(json.dumps(output, indent=2))
        print(f"\nWrote report to {args.report_out}")


if __name__ == "__main__":
    main()
