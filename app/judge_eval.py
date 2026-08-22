"""`python -m app.judge_eval` -- RI-M2 (fabrication audit) and RI-M6 (groundedness), one shared
harness parameterised by rubric rather than two duplicated pipelines. Both take the same triple
(question, retrieved passages, generated answer) and ask a judge to mark each claim in the answer
`supported` / `unsupported` / `contradicted` against the passages -- only the rubric text differs
between the two (`docs/eval-rubrics/fabrication-audit-rubric.md` vs.
`docs/eval-rubrics/groundedness-rubric.md`).

**This module never calls a live model.** `Judge` is a `Protocol` -- an operator wires in a real
judge later (a call to whatever model they choose) by writing a factory function and pointing
`--judge-factory` at it; nothing here hardcodes a vendor, so this module needs no entry in
`ci/checks/vendor_isolation.py`'s `VENDOR_RULES`. The test suite (`app/test_judge_eval.py`) only
ever exercises a `FakeJudge` with canned verdicts -- the default pytest run is socket-disabled
(CONVENTIONS.md §12 T-F6(i)), so a suite that depended on a live call would simply fail there.

**RI-M6 hard constraint:** a report produced under `groundedness-rubric.md` is never a baseline --
that rubric's own banner says so, and `build_report`'s `disclaimer` field repeats it in every
emitted report (not just RI-M6's) so the caveat travels with the artifact, not just this
docstring. The rubric is plain text an operator can read and edit without touching this file --
see the two files under `docs/eval-rubrics/`.

**Known limitation, stated rather than silently carried:** `unsupported` collapses two different
situations the judge cannot tell apart from text alone -- a true fact imported from outside the
passages, and genuine invention. That is why unsupported (and contradicted) claims are retained
verbatim in the report for human inspection, not just counted.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

VERDICTS = ("supported", "unsupported", "contradicted")

_DEFAULT_GROUND_TRUTH = "fixtures/eval/eval_ground_truth.json"

# Repeated in every emitted report (build_report), not just this docstring -- a JSON file on disk
# outlives everyone's memory of the caveat that produced it.
DISCLAIMER = (
    "A judge model is itself fallible: these rates are one instrument's reading of the answer "
    "against the supplied passages, not ground truth. The rubric that produced this report lives "
    "at rubric_path (plain text, operator-editable) and is stamped by rubric_sha256_12 below so "
    "two reports produced under different rubric wording are never silently compared. This report "
    "is not a baseline -- see the rubric file's own header for sign-off status."
)


@dataclass(frozen=True)
class Claim:
    """One claim the judge extracted from the audited answer, with its verdict against the
    supplied passages and the judge's own stated reasoning -- retained verbatim (never just
    counted) so an `unsupported`/`contradicted` call can be inspected by a human."""

    text: str
    verdict: str  # one of VERDICTS
    rationale: str

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {self.verdict!r}, must be one of {VERDICTS}")


@dataclass(frozen=True)
class AuditItem:
    """One (question, retrieved passages, generated answer) triple to run a judge over."""

    question_id: str
    question_text: str
    passages: tuple[str, ...]
    answer: str


@dataclass(frozen=True)
class AuditResult:
    question_id: str
    claims: tuple[Claim, ...]
    error: str | None = None


class Judge(Protocol):
    """The one seam RI-M2 and RI-M6 share. A real judge is an LLM call behind this same
    signature -- not shipped in this module, see the module docstring."""

    def __call__(self, item: AuditItem, rubric: str) -> list[Claim]: ...


def load_items(ground_truth_path: Path) -> list[AuditItem]:
    """Builds `AuditItem`s straight from an eval ground-truth file -- no new labelling needed.

    Per RI-M2's brief: `passage_excerpt` stands in for "the passages retrieval supplied" and
    `answer_text` stands in for "the text a real generation run produced" -- both already exist
    in every `fixtures/eval/eval_ground_truth*.json` file, so pointing this harness at one proves
    the plumbing works on real, grounded fixture data without claiming the resulting rates
    describe this system's actual generation output (that would need a real generation run
    first, which is operator work -- see the ticket's INSTRUMENTS ONLY note).

    `question_text` isn't always in the ground-truth file itself (see
    `app/retrieval_eval.py::load_questions`'s identical situation) -- fall back to the sibling
    `eval_questions_blind*.json` file when needed, and to `""` if neither has it, since the judge
    only strictly needs the passages and the answer.
    """
    data = json.loads(ground_truth_path.read_text())
    records = data["ground_truth"]

    text_by_id = {r["question_id"]: r["question_text"] for r in records if "question_text" in r}
    if len(text_by_id) < len(records):
        blind_path = ground_truth_path.parent / (
            ground_truth_path.name.replace("eval_ground_truth", "eval_questions_blind")
        )
        if blind_path.exists():
            blind = json.loads(blind_path.read_text())["questions"]
            text_by_id.update({q["question_id"]: q["question_text"] for q in blind})

    return [
        AuditItem(
            question_id=r["question_id"],
            question_text=text_by_id.get(r["question_id"], ""),
            passages=(r["passage_excerpt"],),
            answer=r["answer_text"],
        )
        for r in records
    ]


def run_audit(items: list[AuditItem], judge: Judge, rubric: str) -> list[AuditResult]:
    """Calls `judge(item, rubric)` for every item. A judge failure on one item is recorded and
    skipped, not fatal to the whole run -- mirrors `app/retrieval_eval.py::run`'s posture: a
    single bad call shouldn't blank out every other item's audit."""
    results = []
    for item in items:
        try:
            claims = judge(item, rubric)
        except Exception as e:  # noqa: BLE001 -- deliberately broad, see docstring
            logger.warning("judge failed for %s: %s", item.question_id, e)
            results.append(AuditResult(question_id=item.question_id, claims=(), error=str(e)))
            continue
        results.append(AuditResult(question_id=item.question_id, claims=tuple(claims)))
    return results


def build_report(results: list[AuditResult], rubric_path: Path) -> dict:
    rubric_text = rubric_path.read_text()
    rubric_hash = hashlib.sha256(rubric_text.encode("utf-8")).hexdigest()[:12]

    scored = [r for r in results if r.error is None]
    all_claims = [(r.question_id, c) for r in scored for c in r.claims]
    total = len(all_claims)
    counts = {v: sum(1 for _, c in all_claims if c.verdict == v) for v in VERDICTS}

    def _rate(verdict: str) -> float | None:
        return (counts[verdict] / total) if total else None

    def _retained(verdict: str) -> list[dict]:
        return [
            {"question_id": qid, "claim": c.text, "rationale": c.rationale}
            for qid, c in all_claims
            if c.verdict == verdict
        ]

    return {
        "rubric_path": str(rubric_path),
        "rubric_sha256_12": rubric_hash,
        "n_items": len(results),
        "n_errors": sum(1 for r in results if r.error is not None),
        "n_claims": total,
        "rates": {v: _rate(v) for v in VERDICTS},
        "counts": counts,
        # RETAINED for inspection, not just counted -- the whole point of the "unsupported"
        # verdict is that it can't tell true-but-outside-passages apart from invention by itself.
        "unsupported_claims": _retained("unsupported"),
        "contradicted_claims": _retained("contradicted"),
        "disclaimer": DISCLAIMER,
    }


def _print_summary(report: dict) -> None:
    print(f"Rubric: {report['rubric_path']} (sha256:{report['rubric_sha256_12']})")
    print(
        f"Items: {report['n_items']} (errors: {report['n_errors']})  "
        f"Claims: {report['n_claims']}"
    )
    for v in VERDICTS:
        rate = report["rates"][v]
        rate_str = f"{rate:.3f}" if rate is not None else "n/a"
        print(f"  {v:13s} {report['counts'][v]:4d}  (rate={rate_str})")
    if report["unsupported_claims"] or report["contradicted_claims"]:
        print(
            f"\n{len(report['unsupported_claims'])} unsupported, "
            f"{len(report['contradicted_claims'])} contradicted claim(s) retained in the report "
            "for inspection."
        )
    print(f"\n{report['disclaimer']}")


def _load_judge(dotted_path: str) -> Judge:
    module_name, _, attr = dotted_path.partition(":")
    if not attr:
        raise ValueError(
            f"--judge-factory must be 'module.path:factory_name', got {dotted_path!r}"
        )
    factory = getattr(importlib.import_module(module_name), attr)
    return factory()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", default=_DEFAULT_GROUND_TRUTH)
    parser.add_argument(
        "--rubric", required=True,
        help="path to a rubric .md file (operator-editable, not code) -- e.g. "
             "docs/eval-rubrics/fabrication-audit-rubric.md or "
             "docs/eval-rubrics/groundedness-rubric.md",
    )
    parser.add_argument(
        "--judge-factory", required=True,
        help="dotted 'module.path:factory_name' -- factory() must return a Judge. This module "
             "ships no real judge (see module docstring); wire your own in.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report-path", default=None, help="write the JSON report here")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()

    items = load_items(Path(args.ground_truth))
    if args.limit is not None:
        items = items[: args.limit]

    judge = _load_judge(args.judge_factory)
    rubric_path = Path(args.rubric)
    results = run_audit(items, judge, rubric_path.read_text())
    report = build_report(results, rubric_path)
    _print_summary(report)

    if args.report_path:
        Path(args.report_path).write_text(json.dumps(report, indent=2))
        print(f"\nWrote report to {args.report_path}")


if __name__ == "__main__":
    main()
