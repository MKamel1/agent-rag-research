# app/exp_author_org_tagging.py
"""Validation experiment for docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md
§6 -- measures precision AND recall (both false-positive and false-negative rates) for both
candidate affiliation-extraction methods (rule-based, LLM-based) against a real positive set
(known Waymo-authored papers) and a real negative set (sampled from the existing causal-inference
corpus). A throwaway validation script (app/exp_* convention -- see app/exp3_hierarchy_sim.py,
app/exp_tdoc87_marker_repair.py), not a permanent module; its output is a decision, not a library.

Constructs OllamaSummarizer directly (composition-root shape, same as app/exp1_outline_split.py)
-- names no vendor token itself, per ci/checks/vendor_isolation.py's VENDOR_RULES.
"""

import argparse
import random
from pathlib import Path

import httpx

from rag.author_org_tagger import extract_affiliations_rule_based, match_known_orgs
from rag.document_store import DocumentStore
from rag.gpu_lock import FileGpuLock
from rag.summarizer import OllamaSummarizer

_OLLAMA_URL = "http://localhost:11434"  # matches app/assembly.py's _OLLAMA_URL exactly
_MODEL = "qwen3:14b"  # matches app/assembly.py's _OLLAMA_MODEL exactly


def _first_page_text(blocks) -> str:
    return "\n".join(b.text for b in blocks if b.page == 0)


def _reservoir_sample(iterator, k: int) -> list:
    """Sample up to k items uniformly at random from a (possibly large) iterator without
    materializing it fully -- DocumentStore.iter_papers() streams from SQLite; the production
    corpus is 12,390+ full PaperRecords (parsed blocks/chunks included), too much to load into a
    list just to random.sample() 30 of them."""
    reservoir: list = []
    for i, item in enumerate(iterator):
        if i < k:
            reservoir.append(item)
        else:
            j = random.randint(0, i)
            if j < k:
                reservoir[j] = item
    return reservoir


def _score(predicted_true_ids: set[str], actual_true_ids: set[str]) -> dict:
    tp = len(predicted_true_ids & actual_true_ids)
    fp = len(predicted_true_ids - actual_true_ids)
    fn = len(actual_true_ids - predicted_true_ids)
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall}


def run(
    positive_db: Path, positive_blob_dir: Path,
    production_db: Path, production_blob_dir: Path,
    negative_sample_size: int = 30,
    negative_db: Path | None = None,
    negative_blob_dir: Path | None = None,
) -> None:
    # DocumentStore.__init__ takes str, not Path -- explicit str() to match its declared contract.
    positive_store = DocumentStore(str(positive_db), str(positive_blob_dir))

    positive_records = list(positive_store.iter_papers())
    print(f"positive set: {len(positive_records)} papers (expected Waymo-authored)")
    positive_ids = {r.ref.paper_id for r in positive_records}

    if negative_db is not None and negative_blob_dir is not None:
        # DocumentStore has no id-filtering query -- iter_papers() streams everything in the DB.
        # A --negative-db can legitimately contain the positive set too (e.g. the same scratch
        # corpus a verified positive pool was drawn from), so exclude those ids here rather than
        # assuming the DB holds only true negatives.
        negative_store = DocumentStore(str(negative_db), str(negative_blob_dir))
        negative_records = [
            r for r in negative_store.iter_papers() if r.ref.paper_id not in positive_ids
        ]
        print(
            f"negative set: {len(negative_records)} papers "
            "(from --negative-db, positive ids excluded)"
        )
    else:
        production_store = DocumentStore(str(production_db), str(production_blob_dir))
        negative_records = _reservoir_sample(production_store.iter_papers(), negative_sample_size)
        print(
            f"negative set: {len(negative_records)} papers "
            "(sampled from causal-inference corpus)"
        )

    client = httpx.Client(base_url=_OLLAMA_URL, timeout=120.0)
    gpu_lock = FileGpuLock(Path("/home/omar/ai-projects/research-system-rag/.gpu.lock"))
    summarizer = OllamaSummarizer(client, gpu_lock, _MODEL)

    actual_true = positive_ids

    rule_based_true: set[str] = set()
    rule_signal_true: set[str] = set()  # any known-org match -- the combined method's prefilter
    llm_true: set[str] = set()

    for record in positive_records + negative_records:
        pid = record.ref.paper_id
        page_text = _first_page_text(record.parsed.blocks)

        raw_rule = extract_affiliations_rule_based(record.parsed.blocks)
        rule_matches = match_known_orgs(raw_rule)
        if rule_matches:
            rule_signal_true.add(pid)
        if "Waymo" in rule_matches:
            rule_based_true.add(pid)

        try:
            raw_llm = summarizer.extract_affiliations(page_text)
            if "Waymo" in match_known_orgs(raw_llm):
                llm_true.add(pid)
        except Exception as error:  # noqa: BLE001 -- experiment script: log and continue, never crash the whole run over one paper
            print(f"  {pid}: LLM extraction failed ({error}) -- counted as no-match")

    # Combined: rule-based as a cheap pre-filter (recall=1.0 on the positive set means it should
    # never wrongly skip a real match), LLM confirms only what rule-based already flagged as
    # having some signal. A paper rule-based found zero signal on never gets an LLM call in
    # production; here the same result falls out of intersecting the two sets after the fact,
    # since a paper outside rule_signal_true can never end up "combined-true" regardless of what
    # the LLM would have said.
    combined_true = rule_signal_true & llm_true

    print("\n=== Rule-based method ===")
    print(_score(rule_based_true, actual_true))
    print("\n=== LLM-based method ===")
    print(_score(llm_true, actual_true))
    print("\n=== Combined (rule-based prefilter + LLM confirm) ===")
    print(_score(combined_true, actual_true))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-db", required=True, type=Path)
    parser.add_argument("--positive-blob-dir", required=True, type=Path)
    parser.add_argument(
        "--production-db", type=Path,
        default=Path("/home/omar/ai-projects/research-system-rag-data/papers.db"),
    )
    parser.add_argument(
        "--production-blob-dir", type=Path,
        default=Path("/home/omar/ai-projects/research-system-rag-data/blobs"),
    )
    parser.add_argument("--negative-sample-size", type=int, default=30)
    parser.add_argument(
        "--negative-db", type=Path, default=None,
        help="Optional: use this DB's papers (minus any --positive-db ids) as the negative set "
        "instead of a reservoir sample of --production-db. Requires --negative-blob-dir.",
    )
    parser.add_argument(
        "--negative-blob-dir", type=Path, default=None,
        help="Blob dir for --negative-db.",
    )
    args = parser.parse_args()
    run(
        args.positive_db, args.positive_blob_dir,
        args.production_db, args.production_blob_dir,
        args.negative_sample_size,
        args.negative_db, args.negative_blob_dir,
    )


if __name__ == "__main__":
    main()
