#!/usr/bin/env python3
"""`python -m app.exp_confidence_v0_support` -- NB-QW2 confidence-surface v0 measurement.

Offline MiniCheck-class support-checking over the EXISTING generation captures
(`fixtures/eval/runs/2026-08-23-waymo-generation-run.{answerable,absent}.json`). The captures are
REUSED as stored -- answers are never regenerated. Zero paid APIs; the scorer is a local
Flan-T5-Large-class checkpoint (MiniCheck-FT5, 770M) run offline via HuggingFace transformers.

WHAT IT MEASURES (R2 §3 Rank 1 mechanism, verbatim scope from ticket NB-QW2):

* every answer sentence x every ACTUALLY-SERVED passage (the capture's `supporting_passages`,
  i.e. `n_passages_used`, not the wider retrieved pool) gets one raw support score;
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
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Primary captures (ticket-binding): the FAB-1 arm splits of the 2026-08-23 generation run.
CAPTURE_DIR = REPO_ROOT / "fixtures/eval/runs"
CAPTURE_ANSWERABLE = CAPTURE_DIR / "2026-08-23-waymo-generation-run.answerable.json"
CAPTURE_ABSENT = CAPTURE_DIR / "2026-08-23-waymo-generation-run.absent.json"
# Second arm (ticket: "worth scoring as a second arm") -- same shape, refusal-permitting prompt.
CAPTURE_AFFORDANCE_ANSWERABLE = (
    CAPTURE_DIR / "2026-08-24-waymo-generation-run-affordance.answerable.json"
)
CAPTURE_AFFORDANCE_ABSENT = CAPTURE_DIR / "2026-08-24-waymo-generation-run-affordance.absent.json"
ALL_CAPTURES = (
    CAPTURE_ANSWERABLE,
    CAPTURE_ABSENT,
    CAPTURE_AFFORDANCE_ANSWERABLE,
    CAPTURE_AFFORDANCE_ABSENT,
)
OUT_DIR_DEFAULT = REPO_ROOT / "docs/eval-reports/data/2026-08-28-confidence-v0"

# MiniCheck-FT5 (Tang et al. 2024): Flan-T5-Large fine-tuned as a binary support classifier.
# Released usage (github.com/Liyan06/MiniCheck, minicheck/inference.py) is reimplemented directly
# here (no `minicheck` pip dependency -- it pulls in extra runtime deps for model variants and
# doc-tokenizing paths we don't use) rather than pulled in as a dependency.
MINICHECK_CHECKPOINT = "lytang/MiniCheck-Flan-T5-Large"
# MiniCheck's own default word-chunk size for flan-t5-large (inference.py: `500 if
# model_name=='flan-t5-large'`). A handful of served passages here run past the model's 2048-token
# window (up to ~4000 words); plain truncation would silently blind the scorer to whatever's past
# the cut. Chunking + max mirrors the reference implementation instead of inventing our own.
_CHUNK_WORDS = 500
# Decoder-step-0 logits read off at these two fixed vocab ids give the (no-support, support)
# pair for this exact checkpoint (Tang et al. 2024's released inference code, unchanged since
# fine-tuning fixed this vocabulary mapping).
_NO_SUPPORT_TOKEN_ID = 3
_SUPPORT_TOKEN_ID = 209
_SCORE_BATCH_SIZE = 16

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


def _infer_arm_from_filename(path: Path) -> str | None:
    """Fallback arm label for captures with no `_metadata.arm` (see `load_capture`)."""
    if ".answerable." in path.name:
        return "answerable"
    if ".absent." in path.name:
        return "absent"
    return None


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
    """Per-sentence raw scores. `max_support` is the max passage support score for the sentence;
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
    arm = meta.get("arm") if isinstance(meta, dict) else None
    if arm is None:
        # The affordance-arm captures (2026-08-24-*) carry no `_metadata.arm` field -- fall back
        # to the filename's own ".answerable."/".absent." split marker rather than reject a
        # capture the ticket explicitly asks us to score. Only ever a fallback: a file that
        # doesn't name its arm either way still fails loudly below, same as before.
        arm = _infer_arm_from_filename(path)
    if arm is None:
        raise CaptureError(f"{path}: missing _metadata.arm")
    arm = str(arm)
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


def chunk_words(text: str, n: int = _CHUNK_WORDS) -> list[str]:
    """Split `text` into ~`n`-word chunks (whitespace split, MiniCheck's own flan-t5 recipe --
    see module docstring). A passage past the model's context window gets scored chunk-by-chunk
    with the max taken, instead of silently truncated."""
    words = text.split()
    if not words:
        return [""]
    return [" ".join(words[i : i + n]) for i in range(0, len(words), n)]


@dataclass(frozen=True)
class AnswerAggregate:
    """Per-answer raw-score summary: mean/median/min/max of its sentences' `max_support` values.
    Never binarized, never leveled -- see module docstring's HONEST SEMANTICS."""

    n_sentences: int
    mean: float
    median: float
    min: float
    max: float


@dataclass(frozen=True)
class ScoredItem:
    """One fully-scored capture item: every answer sentence's scores plus the answer-level
    aggregate. `aggregate` is `None` only if the answer had zero scoreable sentences."""

    question_id: str
    question_text: str
    answer_text: str
    n_passages_used: int
    sentences: tuple[ScoredSentence, ...]
    aggregate: AnswerAggregate | None


class MiniCheckScorer:
    """Reimplements MiniCheck-FT5's own scoring recipe (github.com/Liyan06/MiniCheck,
    minicheck/inference.py, Tang et al. 2024) directly on `transformers` -- not the `minicheck`
    pip package, which pulls in extra runtime deps for model variants and doc-tokenizing paths
    this instrument doesn't use. Loads `lytang/MiniCheck-Flan-T5-Large` (770M) once; `score_pair`
    scores one (served-passage, answer-sentence) pair.

    Verified against the checkpoint's own published demo (its README's two-sentence example):
    this reimplementation reproduces its published raw probabilities (0.9806 / 0.0071) to 4
    decimal places -- the input format and the [3, 209] (no-support, support) decoder-logit read
    are byte-identical to the released inference code, not a new scoring method.
    """

    def __init__(self, device: str = "cpu"):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self._torch = torch
        self.device = device
        # Ticket requirement: zero network calls once the checkpoint is cached (this is an
        # OFFLINE experiment). `local_files_only=True` refuses the network outright instead of
        # an HF_HUB_OFFLINE env var (CONVENTIONS §12(d): process-env reads belong to
        # rag/config.py only) -- same guarantee, scoped to this one load call.
        self.tokenizer = AutoTokenizer.from_pretrained(
            MINICHECK_CHECKPOINT, local_files_only=True
        )
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            MINICHECK_CHECKPOINT, local_files_only=True
        )
        self.model.eval()
        self.model.to(device)

    def score_pair(self, passage_text: str, claim_text: str) -> float:
        """Raw support score in [0, 1] for one (document, claim) pair: max over the document's
        word-chunks of softmax([no-support, support])[support]. Not a probability of truth --
        see module docstring."""
        torch = self._torch
        chunks = chunk_words(passage_text)
        texts = [f"predict: {chunk}{self.tokenizer.eos_token}{claim_text}" for chunk in chunks]
        best = 0.0
        for start in range(0, len(texts), _SCORE_BATCH_SIZE):
            batch = texts[start : start + _SCORE_BATCH_SIZE]
            enc = self.tokenizer(
                batch, max_length=2048, truncation=True, padding=True, return_tensors="pt"
            )
            enc = {k: v.to(self.device) for k, v in enc.items()}
            decoder_input_ids = torch.zeros(
                (enc["input_ids"].size(0), 1), dtype=torch.long, device=self.device
            )
            with torch.no_grad():
                out = self.model(
                    input_ids=enc["input_ids"],
                    attention_mask=enc["attention_mask"],
                    decoder_input_ids=decoder_input_ids,
                )
            logits = out.logits.squeeze(1)[:, [_NO_SUPPORT_TOKEN_ID, _SUPPORT_TOKEN_ID]]
            probs = torch.softmax(logits, dim=-1)[:, 1]
            best = max(best, probs.max().item())
        return best


def score_item(item: CaptureItem, scorer: MiniCheckScorer) -> ScoredItem | None:
    """Score every answer sentence x every served passage for one item; `None` if the answer
    split to zero sentences (nothing to score, not a zero score)."""
    sentences = split_answer_sentences(item.answer_text)
    if not sentences:
        return None
    scored_sentences = []
    for sent in sentences:
        per_passage = [
            {"paper_id": passage.paper_id, "support": scorer.score_pair(passage.text, sent)}
            for passage in item.passages
        ]
        max_support = max(p["support"] for p in per_passage)
        scored_sentences.append(
            ScoredSentence(text=sent, max_support=max_support, per_passage=per_passage)
        )
    maxima = [s.max_support for s in scored_sentences]
    aggregate = AnswerAggregate(
        n_sentences=len(maxima),
        mean=statistics.fmean(maxima),
        median=statistics.median(maxima),
        min=min(maxima),
        max=max(maxima),
    )
    return ScoredItem(
        question_id=item.question_id,
        question_text=item.question_text,
        answer_text=item.answer_text,
        n_passages_used=item.n_passages_used,
        sentences=tuple(scored_sentences),
        aggregate=aggregate,
    )


def score_items(items: list[CaptureItem], scorer: MiniCheckScorer) -> list[ScoredItem]:
    return [s for item in items if (s := score_item(item, scorer)) is not None]


def scored_item_to_dict(scored: ScoredItem) -> dict:
    assert scored.aggregate is not None
    return {
        "question_id": scored.question_id,
        "question_text": scored.question_text,
        "answer_text": scored.answer_text,
        "n_passages_used": scored.n_passages_used,
        "n_sentences": scored.aggregate.n_sentences,
        "sentence_scores": [
            {"text": s.text, "max_support": s.max_support, "per_passage": s.per_passage}
            for s in scored.sentences
        ],
        "answer_aggregate": {
            "mean": scored.aggregate.mean,
            "median": scored.aggregate.median,
            "min": scored.aggregate.min,
            "max": scored.aggregate.max,
        },
    }


def dump_arm(
    out_path: Path,
    arm: str,
    fixture_name: str,
    n_items_loaded: int,
    scored: list[ScoredItem],
) -> dict:
    """Write one arm's score dump as committed JSON (report numbers are read back from this,
    never recomputed ad hoc)."""
    payload = {
        "_metadata": {
            "prototype_label": (
                "UNVALIDATED PROTOTYPE -- raw support score (not a probability, not a truth "
                "judgment). No calibration data, no confidence levels, no thresholds. Measures "
                "support-by-served-context only; see NB-QW2 report for the wrong-context-scores-"
                "high failure mode (Q-GTA-037)."
            ),
            "arm": arm,
            "fixture": fixture_name,
            "model": MINICHECK_CHECKPOINT,
            "n_items_loaded": n_items_loaded,
            "n_items_scored": len(scored),
        },
        "items": [scored_item_to_dict(s) for s in scored],
    }
    out_path.write_text(json.dumps(payload, indent=2))
    return payload


def _cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check-plumbing", action="store_true", help="load captures, print counts, exit"
    )
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR_DEFAULT)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="rag config.yaml path (else RAG_CONFIG env var / discovery, see rag/config.py)",
    )
    args = parser.parse_args(argv)

    loaded: dict[Path, tuple[str, list[CaptureItem]]] = {}
    for cap_path in ALL_CAPTURES:
        arm, items = load_capture(cap_path)
        loaded[cap_path] = (arm, items)

    print("capture loading OK:")
    for cap_path, (arm, items) in loaded.items():
        print(f"  {cap_path.name}: arm={arm} items={len(items)} pairs={build_pairs(items)}")

    if args.check_plumbing:
        return 0

    from rag.config import load_config
    from rag.gpu_lock import FileGpuLock

    cfg = load_config(args.config)
    gpu_lock = FileGpuLock(Path(cfg.gpu_lock_path))
    device = "cuda" if _cuda_available() else "cpu"
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nscoring on device={device} (model={MINICHECK_CHECKPOINT})")
    dumps: dict[str, dict] = {}
    # Ticket NB-QW2: "hold the lock only while scoring; release it after" -- one acquire/release
    # cycle spans model load through the last pair of the last arm, nothing on either side of it.
    with gpu_lock.acquire("confidence-v0-support-scoring"):
        scorer = MiniCheckScorer(device=device)
        for cap_path, (arm, items) in loaded.items():
            scored = score_items(items, scorer)
            out_name = cap_path.stem + ".minicheck-v0.json"
            payload = dump_arm(args.out_dir / out_name, arm, cap_path.name, len(items), scored)
            dumps[cap_path.name] = payload
            print(f"  scored {cap_path.name}: {len(scored)}/{len(items)} items -> {out_name}")

    print("\nper-arm answer-aggregate MEAN distribution (reported separately -- never blended):")
    for name, payload in dumps.items():
        means = [it["answer_aggregate"]["mean"] for it in payload["items"]]
        if not means:
            print(f"  {name}: n=0")
            continue
        print(
            f"  {name}: n={len(means)} mean={statistics.fmean(means):.3f} "
            f"median={statistics.median(means):.3f} min={min(means):.3f} max={max(means):.3f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
