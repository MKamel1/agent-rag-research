"""Plain BM25 floor ("EV-5b" in the 2026-11-10 protocols) over the stored chunk text of a corpus DB.

    python scripts/bm25_floor.py --ground-truth GT.json --db papers.db --k 10 \
        --report-path OUT.json [--variant standard|title-ablated|body-only]

Writes a report JSON in the SAME shape as `app.retrieval_eval.build_report` (it calls it), so
`scripts/eval_strata_report.py` post-processes it unchanged. Each question row also carries
`retrieved_chunk_ids` and `bm25_scores` (ordered top-k). NOT the system's retrieval output: a
lexical floor that must be printed beside every headline number, never a prediction of it.

DEFINITION (frozen; standards protocol section 7 (ii))
  * Okapi BM25:  score(q, d) = sum over DISTINCT query terms t of
        idf(t) * tf(t,d) * (k1 + 1) / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))
        idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
    k1 = 1.2, b = 0.75. N = number of chunks in the DB, df = chunks containing t, |d| = tokens in
    chunk d, avgdl = mean |d| over ALL N chunks (empty chunks included).
  * Tokens: lowercase text, `[a-z0-9]+` (split on non-alphanumerics), minus the stopword list
    `scripts.eval_protocol_tools.STOP`. Applied identically to chunk text and question.
    NO ligature repair: this is the naive floor (damaged words like "e ect" stay damaged).
  * Documents: every row of `chunks.text` as stored (`title\\nsection_path\\n\\nbody`).
    `--variant body-only` indexes `rag.retriever.body_of(text)` instead (no title/section header),
    showing how much recall rides on the header every chunk carries. `--variant title-ablated`
    scores `eval_protocol_tools.ablate_ground_truth` questions against the standard index.
  * Ties break by chunk table order (rowid). Query = `question_text` as written.
  * Hits: `app.retrieval_eval.score_question` (paper = first top-k chunk with paper_id in gold;
    passage = anchor block id == gold_block_id); `load_questions` handles absent items (no gold
    paper => never a hit). title_leak is not computed (always False here).

TWO-STAGE, EXACT (why 400k chunks fit in pure Python): scores depend only on the query terms'
postings, N and avgdl. So ONE streaming pass over the DB tokenizes each chunk, counts |d|, and
keeps postings (array('I') doc index, array('H') tf) ONLY for the union of the question
vocabularies; ranking then uses those postings. The result is identical to a full inverted index
but memory is O(postings of query terms). Build time and peak RSS are written to the report.

The database is opened `file:...?mode=ro`; no service, no network, no GPU; standard library only
(plus this repo's own helpers).
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import re
import resource
import sqlite3
import sys
import tempfile
import time
from array import array
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.retrieval_eval import build_report, load_questions, score_question  # noqa: E402
from rag.retriever import body_of  # noqa: E402
from scripts.eval_protocol_tools import STOP, ablate_ground_truth  # noqa: E402

K1, B = 1.2, 0.75
VARIANTS = ("standard", "title-ablated", "body-only")
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOP]


class Bm25Index:
    """Postings for a fixed set of query terms plus the corpus statistics BM25 needs."""

    def __init__(self, vocab: set[str]):
        self.vocab = vocab
        self.n_docs = 0
        self.total_len = 0
        self.doc_len = array("I")
        self.postings: dict[str, tuple[array, array]] = {t: (array("I"), array("H")) for t in vocab}
        self.chunk_ids: dict[
            int, tuple[str, str]
        ] = {}  # doc idx -> (chunk_id, paper_id), hits only

    def add(self, chunk_id: str, paper_id: str, text: str) -> None:
        idx = self.n_docs
        tokens = tokenize(text)
        self.n_docs += 1
        self.total_len += len(tokens)
        self.doc_len.append(len(tokens))
        counts = Counter(t for t in tokens if t in self.vocab)
        for term, tf in counts.items():
            docs, tfs = self.postings[term]
            docs.append(idx)
            tfs.append(min(tf, 65535))
        if counts:
            self.chunk_ids[idx] = (chunk_id, paper_id)

    def search(self, query: str, k: int) -> list[tuple[str, str, float]]:
        """Top-k (chunk_id, paper_id, score); only chunks matching >= 1 query term can score."""
        avgdl = self.total_len / self.n_docs if self.n_docs else 1.0
        scores: dict[int, float] = {}
        for term in set(tokenize(query)):
            docs, tfs = self.postings.get(term, ((), ()))
            df = len(docs)
            if not df:
                continue
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            for d, tf in zip(docs, tfs):
                norm = tf + K1 * (1 - B + B * self.doc_len[d] / avgdl)
                scores[d] = scores.get(d, 0.0) + idf * tf * (K1 + 1) / norm
        top = heapq.nsmallest(k, scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return [(*self.chunk_ids[d], s) for d, s in top]


def connect_ro(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def build_index(con: sqlite3.Connection, vocab: set[str], body_only: bool) -> Bm25Index:
    index = Bm25Index(vocab)
    for chunk_id, paper_id, text in con.execute(
        "SELECT chunk_id, paper_id, text FROM chunks ORDER BY rowid"
    ):
        index.add(chunk_id, paper_id, body_of(text) if body_only else text)
    return index


def anchors_for(con: sqlite3.Connection, chunk_ids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(chunk_ids), 500):
        part = chunk_ids[i : i + 500]
        marks = ",".join("?" * len(part))
        for cid, anchor_json in con.execute(
            f"SELECT chunk_id, anchor_json FROM chunks WHERE chunk_id IN ({marks})", part
        ):
            out[cid] = json.loads(anchor_json)["block_id"]
    return out


def run_floor(gt_path: Path, db_path: str, k: int, variant: str) -> dict:
    """Score `gt_path` against `db_path`; returns the retrieval_eval-shaped report dict."""
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")
    started = time.perf_counter()
    if variant == "title-ablated":
        ablated = ablate_ground_truth(json.loads(gt_path.read_text()))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ablated_gt.json"
            path.write_text(json.dumps(ablated))
            questions = load_questions(path)
    else:
        questions = load_questions(gt_path)
    vocab = {t for q in questions for t in tokenize(q.question_text)}
    con = connect_ro(db_path)
    try:
        index = build_index(con, vocab, body_only=variant == "body-only")
        build_seconds = time.perf_counter() - started
        ranked = [index.search(q.question_text, k) for q in questions]
        anchor_of = anchors_for(con, sorted({cid for hits in ranked for cid, _, _ in hits}))
    finally:
        con.close()
    results = []
    for q, hits in zip(questions, ranked):
        fake = [
            SimpleNamespace(
                paper_id=pid,
                score=s,
                anchor=SimpleNamespace(block_id=anchor_of[cid]),
                citation=SimpleNamespace(title=""),
                passage_text="",
            )
            for cid, pid, s in hits
        ]
        results.append(score_question(q, fake, k))
    report = build_report(results, k)
    report["scoring_rule"] = (
        f"BM25 floor (variant={variant}, k1={K1}, b={B}, tokens=[a-z0-9]+ lowercase minus "
        f"eval_protocol_tools.STOP, no ligature repair); "
        + report["scoring_rule"].split("; ", 1)[1]
    )
    for row, hits in zip(report["questions"], ranked):
        row["retrieved_chunk_ids"] = [cid for cid, _, _ in hits]
        row["bm25_scores"] = [round(s, 6) for _, _, s in hits]
    report["bm25_floor"] = {
        "variant": variant,
        "k1": K1,
        "b": B,
        "n_chunks": index.n_docs,
        "avgdl": index.total_len / index.n_docs if index.n_docs else 0.0,
        "query_vocab_size": len(vocab),
        "postings_in_memory": sum(len(d) for d, _ in index.postings.values()),
        "build_seconds": round(build_seconds, 1),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "ground_truth": str(gt_path),
        "db": str(db_path),
        "note": "lexical floor, not the system's retrieval output",
    }
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ground-truth", required=True, type=Path)
    ap.add_argument("--db", required=True)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--report-path", required=True, type=Path)
    ap.add_argument("--variant", choices=VARIANTS, default="standard")
    args = ap.parse_args(argv)
    report = run_floor(args.ground_truth, args.db, args.k, args.variant)
    args.report_path.write_text(json.dumps(report))
    f = report["bm25_floor"]
    p = report["paper_level"]["by_gold_status"]["answerable"]
    q = report["passage_level"]["overall"]
    print(
        f"{f['variant']}: n={report['n_questions']} paper R@{args.k} {p['recall_at_k']:.3f} "
        f"anchor passage hit@{args.k} {q['recall_at_k']:.3f} "
        f"(build {f['build_seconds']}s, peak {f['peak_rss_mb']} MB, {f['n_chunks']} chunks)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
