"""`python -m app.score_distribution_census` -- RI-M7: does the retrieval score distribution
over known-answerable questions actually separate from known-absent ones?

Provenance: a relevance floor was PROPOSED AND REJECTED during the RI review (see
docs/superpowers/plans/2026-08-22-review-implementation.md, RI-10). The rejection stands until a
census like this one shows separation -- if it does not separate, no threshold can be chosen
honestly, and RI-10's absence-honesty docstrings (the system returns its best-available top-k
regardless of whether anything in the corpus answers the question) remain the whole answer. This
module is that census, an INSTRUMENT only: it decides nothing and adds no floor anywhere. Running
it against the live corpus and acting on the verdict is operator work.

REUSE, not a second eval runner: `load_questions`/`run`/`build_report` are `app.retrieval_eval`'s,
unmodified. The only new capture this needed was `QuestionResult.top_score` (added there, RI-M7)
-- the rank-1 result's fused/reranked score for every question, hit or miss. This module's own
job is strictly the comparison: pull `top_score` out of each arm's report, summarize each
distribution, and apply one mechanical separation rule to both.

Two arms:
  * known-answerable -- `fixtures/eval/eval_ground_truth.json` (210 items) plus
    `fixtures/eval/eval_equation_slice.json` (~40 items), the same fixtures the rest of the eval
    programme already uses.
  * known-absent -- `fixtures/eval/eval_known_absent.json` (RI-M7, new): questions naming a
    FABRICATED causal-inference method/test/bound/dataset, verified absent from the real corpus
    (see that fixture's own `_metadata` and `fixtures/eval/test_eval_known_absent_invariants.py`).
    NOT `fixtures/eval/eval_equation_slice_topic_absent.json` -- that fixture's answers ARE in the
    corpus; only its question phrasing avoids naming the paper/topic. A genuinely absent arm has
    no gold paper at all (`source_paper_id: null`), which `app.retrieval_eval.load_questions`
    resolves to an empty `gold_paper_ids` rather than a stray `None`.

Separation rule (`_iqr_separates`): the two arms' interquartile ranges (`p25`..`p75`) must not
overlap AT ALL, in either direction. This is deliberately strict and direction-agnostic -- it does
not presume the known-absent arm scores lower, it only asks whether the middle 50% of one arm
sits entirely above or entirely below the middle 50% of the other. A looser rule (e.g. comparing
means) could report "separation" driven by a handful of outliers on either side; this one cannot.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
from pathlib import Path

from app.retrieval_eval import build_report, load_questions, run

logger = logging.getLogger(__name__)

_DEFAULT_K = 10
_DEFAULT_ANSWERABLE_PATHS = (
    "fixtures/eval/eval_ground_truth.json",
    "fixtures/eval/eval_equation_slice.json",
)
_DEFAULT_KNOWN_ABSENT_PATH = "fixtures/eval/eval_known_absent.json"


def collect_top_scores(report: dict) -> list[float]:
    """Pulls every non-None `top_score` out of a `build_report()` report's per-question array.

    Raises rather than silently returning `[]` if the array is missing -- a census over an
    accidentally-empty arm would still compute (empty-list) statistics without anyone noticing
    the arm never actually ran, which is exactly the kind of silent poisoning RI-M7 exists to
    avoid. Build the report with `include_per_question=True` (retrieval_eval's own default).
    """
    if "questions" not in report:
        raise ValueError(
            "report has no 'questions' array -- build it with include_per_question=True "
            "(app.retrieval_eval.build_report's default) so top_score is readable per question"
        )
    return [row["top_score"] for row in report["questions"] if row["top_score"] is not None]


def distribution_stats(scores: list[float]) -> dict:
    """Summary statistics for one arm's `top_score` list -- enough to judge overlap without
    re-deriving anything from the raw scores. `n < 2` degrades gracefully (no `stdev`/quartiles a
    single point can't support) rather than raising, since a tiny fixture (or a `--limit` smoke
    run) can legitimately produce one scored question.
    """
    n = len(scores)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "stdev": None,
                 "min": None, "max": None, "p25": None, "p75": None}
    if n == 1:
        value = scores[0]
        return {"n": 1, "mean": value, "median": value, "stdev": None,
                 "min": value, "max": value, "p25": value, "p75": value}
    p25, _p50, p75 = statistics.quantiles(scores, n=4)
    return {
        "n": n,
        "mean": statistics.mean(scores),
        "median": statistics.median(scores),
        "stdev": statistics.stdev(scores),
        "min": min(scores),
        "max": max(scores),
        "p25": p25,
        "p75": p75,
    }


def _iqr_separates(a: dict, b: dict) -> bool | None:
    """See module docstring's "Separation rule". `None` (not `False`) when either arm has zero
    scored questions -- there is nothing to compare, which is a different fact from "compared and
    found overlapping."""
    if a["n"] == 0 or b["n"] == 0:
        return None
    return a["p75"] < b["p25"] or b["p75"] < a["p25"]


_SEPARATION_RULE_NOTE = (
    "IQR separation: the two arms' interquartile ranges (p25..p75 of top_score) must not overlap "
    "at all, in either direction. Deliberately strict and direction-agnostic -- see module "
    "docstring for why a looser (e.g. mean-based) rule was not used."
)

# Reviewer objection on RI-M7: a bare "separates"/"does not separate" verdict travels without the
# known-absent arm's one construction limitation, and this census is the named condition for
# revisiting a previously-rejected relevance floor -- a verdict read out of context could reverse
# a correct rejection. Same posture as retrieval_eval.py's _TITLE_LEAK_NOTE: the caveat rides
# inside the emitted report itself, not only a docstring, so it travels wherever the JSON is read.
_KNOWN_ABSENT_LIMITATION_NOTE = (
    "Known-absent arm construction limitation: every question names a FABRICATED entity, verified "
    "absent from the corpus's own text (see eval_known_absent.json's _metadata). That guarantees "
    "the sparse/lexical retrieval arm a zero exact-term match by construction -- a real-but-"
    "uncovered topic would not get this guarantee, since a real term can still partially match "
    "real corpus text. The dense arm is still exercised close to normally (plausible in-domain "
    "vocabulary, well-formed methodological asks), so this caveat bites the sparse arm "
    "specifically, not the whole comparison. Net effect: separation measured against this arm is "
    "plausibly an UPPER BOUND on the separation a real uncovered topic would show. A 'separate' "
    "verdict should be read with that ceiling in mind, not quoted as a bare conclusion."
)


def build_census(answerable_report: dict, known_absent_report: dict) -> dict:
    """The whole comparison, from two `build_report()` reports to a plain verdict. Neither report
    is mutated or reinterpreted -- this only reads `top_score` back out of each (`collect_top_
    scores`) and applies `_iqr_separates`. Excluded counts (`n_questions` minus scored `n`) are
    carried alongside each arm's stats so a census over a run with retrieval errors or empty
    corpus responses states that plainly rather than silently shrinking the sample.

    The verdict string always carries `_KNOWN_ABSENT_LIMITATION_NOTE`'s substance (in full when it
    matters most -- a "separate" verdict, the direction the limitation can inflate -- and as an
    explicit non-weakening note otherwise) so the caveat cannot be dropped by quoting the verdict
    on its own. The full note is also emitted as its own `known_absent_limitation` field.
    """
    answerable_scores = collect_top_scores(answerable_report)
    known_absent_scores = collect_top_scores(known_absent_report)
    answerable_stats = distribution_stats(answerable_scores)
    known_absent_stats = distribution_stats(known_absent_scores)
    separates = _iqr_separates(answerable_stats, known_absent_stats)

    if separates is None:
        verdict = "undetermined -- one or both arms have zero scored (non-null top_score) questions"
    elif separates:
        # The at-risk direction (see _KNOWN_ABSENT_LIMITATION_NOTE): say so in the verdict itself.
        verdict = (
            "the distributions separate -- but this is plausibly an UPPER BOUND on the separation "
            "a real uncovered topic would show, not a measurement of it; see "
            "known_absent_limitation before treating this as grounds to revisit a relevance floor"
        )
    else:
        # This direction is NOT weakened by the limitation: the arm's construction can only
        # inflate apparent separation, never manufacture false overlap, so "no separation" here
        # is at least as strong as it would be for a real uncovered topic.
        verdict = (
            "the distributions do not separate -- known_absent_limitation does not weaken this "
            "conclusion, since the arm's construction can only inflate apparent separation, not "
            "create false overlap"
        )

    return {
        "answerable": {
            **answerable_stats,
            "n_excluded": answerable_report["n_questions"] - len(answerable_scores),
        },
        "known_absent": {
            **known_absent_stats,
            "n_excluded": known_absent_report["n_questions"] - len(known_absent_scores),
        },
        "separation_rule": _SEPARATION_RULE_NOTE,
        "known_absent_limitation": _KNOWN_ABSENT_LIMITATION_NOTE,
        "distributions_separate": separates,
        "verdict": verdict,
    }


def _print_census(census: dict) -> None:
    def _fmt(stats: dict) -> str:
        if stats["n"] == 0:
            return "n=0 (no scored questions in this arm)"
        parts = [f"n={stats['n']}", f"mean={stats['mean']:.4f}", f"median={stats['median']:.4f}"]
        if stats["stdev"] is not None:
            parts.append(f"stdev={stats['stdev']:.4f}")
        parts.append(f"range=[{stats['min']:.4f}, {stats['max']:.4f}]")
        parts.append(f"IQR=[{stats['p25']:.4f}, {stats['p75']:.4f}]")
        return "  ".join(parts)

    print(f"Separation rule: {census['separation_rule']}")
    a, k = census["answerable"], census["known_absent"]
    print(f"Known-answerable  {_fmt(a)}  (excluded: {a['n_excluded']})")
    print(f"Known-absent      {_fmt(k)}  (excluded: {k['n_excluded']})")
    print(f"\nVerdict: {census['verdict']}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--blob-dir", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--k", type=int, default=_DEFAULT_K)
    parser.add_argument(
        "--answerable-ground-truth", action="append", default=None,
        help="a known-answerable ground-truth file (repeatable); defaults to "
             f"{' + '.join(_DEFAULT_ANSWERABLE_PATHS)}",
    )
    parser.add_argument("--known-absent-path", default=_DEFAULT_KNOWN_ABSENT_PATH)
    parser.add_argument("--report-path", default=None, help="write the full JSON census here")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()

    # Deferred import, same reasoning as app.retrieval_eval.main(): pulls in the real (GPU-backed)
    # adapter wiring, which unit tests must never touch.
    from app.assembly import build_mcp_server
    from rag.config import load_config

    config = load_config(args.config)
    build_kwargs = {}
    if args.db_path is not None:
        build_kwargs["db_path"] = args.db_path
    if args.blob_dir is not None:
        build_kwargs["blob_dir"] = args.blob_dir
    if args.collection is not None:
        build_kwargs["collection"] = args.collection
    server = build_mcp_server(config, **build_kwargs)

    answerable_paths = args.answerable_ground_truth or list(_DEFAULT_ANSWERABLE_PATHS)
    answerable_questions = [
        q for path in answerable_paths for q in load_questions(Path(path))
    ]
    known_absent_questions = load_questions(Path(args.known_absent_path))

    answerable_results = run(answerable_questions, server.retriever, args.k)
    known_absent_results = run(known_absent_questions, server.retriever, args.k)
    answerable_report = build_report(answerable_results, args.k)
    known_absent_report = build_report(known_absent_results, args.k)

    census = build_census(answerable_report, known_absent_report)
    _print_census(census)

    if args.report_path:
        Path(args.report_path).write_text(json.dumps({
            "census": census,
            "answerable_report": answerable_report,
            "known_absent_report": known_absent_report,
        }, indent=2))
        print(f"\nWrote report to {args.report_path}")


if __name__ == "__main__":
    main()
