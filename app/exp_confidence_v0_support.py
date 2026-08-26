#!/usr/bin/env python3
"""`python -m app.exp_confidence_v0_support` -- NB-QW2 confidence-surface v0 measurement.

Offline MiniCheck-class support-checking over the EXISTING generation captures
(`fixtures/eval/runs/2026-08-23-waymo-generation-run.{answerable,absent}.json`). The captures are
REUSED as stored -- answers are never regenerated. Zero paid APIs; the scorer is a local
Flan-T5-Large-class checkpoint (MiniCheck-FT5, 770M) run offline via HuggingFace transformers.

WHAT IT MEASURES (R2 §3 Rank 1 mechanism, verbatim scope from ticket NB-QW2):

* every answer sentence x every ACTUALLY-SERVED passage (the capture's `supporting_passages`,
  i.e. `n_passages_used`, not the wider retrieved pool) gets one raw support probability;
* per sentence, the score is the max over served passages;
* per answer, the raw aggregate is the mean of those per-sentence maxima (min/median/max also
  recorded); nothing is ever binarized.

HONEST SEMANTICS (binding, B0 §4 + R2 §3):

* This ships a RAW SCORE plus an explicit "unvalidated prototype" label. There is NO level
  language and NO probability wording anywhere in outputs: the number measures
  faithfulness-to-served-context, not truth, not correctness, and carries no measured error rate.
* The absent arm stays OUT of any level logic entirely -- support != truth, so an absence-arm
  answer can be perfectly supported by wrong-side context. Its distributions are reported only
  to demonstrate exactly that failure mode.
* Five-level thresholds are EXPLICITLY OUT OF SCOPE here: gated on IN-2's >=100 graded anchors
  (B0 §4 sizing), of which zero exist today. If this score ever becomes MCP-visible, that edge
  is contracts-gated and is NOT part of this ticket.

Known failure mode under test (must be exemplified in the report from real runs): a confidently
wrong answer whose claims ARE entailed by served-but-wrong context scores HIGH. Support-checking
is blind to it by construction (Tang et al. 2024 §1; R2 §1.1).

Usage:
    # plumbing check only -- load captures, print pair counts, touch no model (commit ①):
    python -m app.exp_confidence_v0_support --check-plumbing

    # full scoring run over both arms (GPU arm serialized on .gpu.lock; commit ②):
    python -m app.exp_confidence_v0_support

Outputs land under docs/eval-reports/data/2026-08-25-nb-qw2/, one JSON per fixture arm --
per-fixture distributions are reported SEPARATELY and are never averaged (PREC-1 constraint 10).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Primary captures (ticket-binding): the FAB-1 arm splits of the 2026-08-23 generation run.
CAPTURE_DIR = REPO_ROOT / "fixtures/eval/runs"
CAPTURE_ANSWERABLE = CAPTURE_DIR / "2026-08-23-waymo-generation-run.answerable.json"
CAPTURE_ABSENT = CAPTURE_DIR / "2026-08-23-waymo-generation-run.absent.json"
OUT_DIR_DEFAULT = REPO_ROOT / "docs/eval-reports/data/2026-08-25-nb-qw2"

# Sentences shorter than this are degenerate fragments of the split (headers, stray numerals).
_MIN_SENTENCE_CHARS = 8

# Markdown emphasis/backtick decoration the generator emits; stripped before splitting/scoring
# so it neither breaks sentence boundaries nor wastes tokenizer budget. Content words untouched.
_MARKDOWN_DECOR = re.compile(r"\*\*|__|`")

# Sentence break: end punctuation (+ optional closing quote/paren/bracket) then whitespace/EOF,
# or a bare newline. Matched with finditer (not lookbehind split) so the optional closers keep
# variable width without tripping re's fixed-width-lookbehind rule.
_SENTENCE_BREAK = re.compile(r"[.!?]+[\"'\u201d\u2019)\]]*(?:\s+|$)|\n+")


class CaptureError(RuntimeError):
    """A capture file does not have the shape the instrument requires."""


@dataclass(frozen=True)
class Passage:
    """One actually-served passage from a generation capture."""

    paper_id: str
    text: str


@dataclass(frozen=True)
class CaptureItem:
    """One question/answer record of a generation-capture arm."""

    question_id: str
    question_text: str
    answer_text: str
    passages: tuple[Passage, ...]
    n_passages_retrieved: int
    n_passages_used: int
    passages_truncated: bool


@dataclass(frozen=True)
class ScoredSentence:
    """Per-sentence raw scores. `max_support` is the max passage probability for the sentence;
    `per_passage` keeps every pair's raw value so downstream calibration loses nothing."""

    text: str
    max_support: float
    per_passage: list[dict] = field(default_factory=list)


def load_capture(path: Path) -> tuple[str, list[CaptureItem]]:
    """Load one generation-capture arm file into typed records.

    Validates the frozen capture shape (FAB-1 split layout: `_metadata.arm` +
    `ground_truth[]` with answer_text and supporting_passages present on every item) rather
    than trusting it -- a malformed arm must fail loudly before any model runs.
    """
    payload = json.loads(path.read_text())
    meta = payload.get("_metadata")
    if not isinstance(meta, dict) or "arm" not in meta:
        raise CaptureError(f"{path}: missing _metadata.arm")
    arm = str(meta["arm"])
    records = payload.get("ground_truth")
    if not isinstance(records, list) or not records:
        raise CaptureError(f"{path}: ground_truth missing or empty")

    items: list[CaptureItem] = []
    for rec in records:
        for key in ("question_id", "question_text", "answer_text", "supporting_passages"):
            if key not in rec:
                raise CaptureError(f"{path}: item missing {key!r}: {rec.get('question_id')}")
        passages = []
        for p in rec["supporting_passages"]:
            if "paper_id" not in p or "passage_excerpt" not in p:
                raise CaptureError(
                    f"{path}: {rec['question_id']}: malformed supporting_passage entry"
                )
            passages.append(Passage(paper_id=str(p["paper_id"]), text=str(p["passage_excerpt"])))
        served = len(passages)
        used = int(rec.get("n_passages_used", served))
        if served == 0:
            raise CaptureError(f"{path}: {rec['question_id']}: zero served passages")
        items.append(
            CaptureItem(
                question_id=str(rec["question_id"]),
                question_text=str(rec["question_text"]),
                answer_text=str(rec["answer_text"]),
                passages=tuple(passages),
                n_passages_retrieved=int(rec.get("n_passages_retrieved", served)),
                n_passages_used=used,
                passages_truncated=bool(rec.get("passages_truncated", False)),
            )
        )
    return arm, items


def split_answer_sentences(answer_text: str) -> list[str]:
    """Split one captured answer into candidate claim sentences.

    Deterministic plain-regex split (no model dependency): strip markdown decoration, cut on
    sentence-end punctuation or newlines, drop degenerate fragments. Deliberately conservative
    -- a missed boundary only means two sentences scored together, never a fabricated claim.
    """
    cleaned = _MARKDOWN_DECOR.sub("", answer_text)
    sentences: list[str] = []
    start = 0
    for m in _SENTENCE_BREAK.finditer(cleaned):
        chunk = cleaned[start : m.end()].strip()
        if chunk:
            sentences.append(chunk)
        start = m.end()
    tail = cleaned[start:].strip()
    if tail:
        sentences.append(tail)
    return [s for s in sentences if len(s) >= _MIN_SENTENCE_CHARS]


def build_pairs(items: list[CaptureItem]) -> int:
    """Count the sentence-x-passage pairs scoring will consume for one arm."""
    total = 0
    for item in items:
        n_sentences = len(split_answer_sentences(item.answer_text))
        total += n_sentences * len(item.passages)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check-plumbing", action="store_true", help="load captures, print counts, exit"
    )
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR_DEFAULT)
    args = parser.parse_args(argv)

    captures = [CAPTURE_ANSWERABLE, CAPTURE_ABSENT]
    loaded = {}
    for cap_path in captures:
        arm, items = load_capture(cap_path)
        loaded[cap_path.name] = (arm, items)

    print("capture loading OK:")
    for name, (arm, items) in loaded.items():
        print(f"  {name}: arm={arm} items={len(items)} pairs={build_pairs(items)}")

    if args.check_plumbing:
        return 0
    # Commit ② wires the scorer here; the stub refuses to fake results past this point.
    print("scorer integration not present yet (commit ① stub)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
