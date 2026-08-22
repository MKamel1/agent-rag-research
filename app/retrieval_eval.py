"""`python -m app.retrieval_eval` -- T-DOC41 (Contextual Retrieval spike): the measurement
runner. Loads a ground-truth question set, calls the real `Retriever.retrieve()` for each
question, and scores Recall@10/MRR at two granularities:

  * paper-level -- a hit if any returned chunk's `paper_id` is in the question's gold-paper set
    (`source_paper_id` plus, when present, `additional_gold_paper_ids` -- same multi-gold
    methodology as the 210-question eval, T-DOC42).
  * passage-level -- a hit only if a returned chunk's `anchor.block_id` equals the question's
    `gold_block_id`. This is the granularity `fixtures/eval/eval_ground_truth.json` cannot see
    (its own `_metadata.multi_gold_note` -- any chunk from the right paper passes) and
    `fixtures/eval/eval_equation_slice.json` was built to make visible: whether the *specific*
    equation/algorithm chunk was retrieved, not just the right paper.

Only questions carrying a `gold_block_id` are scored at passage level -- the 210-question set
doesn't have one (see that fixture's schema), so pointing this runner at it degrades gracefully to
paper-level-only reporting instead of crashing or silently scoring zero.

A third granularity, book-only (docs/DESIGN-book-chapters-and-hierarchy.md Part 3 Step 1):

  * chapter-level -- a hit only if `Retriever.retrieve_papers()` (what `search_papers` wraps)
    returns a `PaperSearchResult` whose `paper_id` is gold AND whose `chapter` string equals the
    question's `gold_chapter_title`. This is a DIFFERENT question from passage-level: passage-level
    asks whether `semantic_search` finds the right span; chapter-level asks whether the chapter
    *routing* step (what `ChapterSummary`/`book_summarizer.py` exist for) points an agent at the
    right chapter at all. Only questions carrying a `gold_chapter_title` are scored here -- same
    graceful-degrade posture as passage-level's `gold_block_id` gate, so pointing this runner at
    the 210-question or equation-slice fixtures (neither carries book fields) still just reports
    paper/passage level, chapter-level empty. `retrieve_papers()` is only called for questions that
    need it -- an unscored (paper) question costs no extra retrieval call.
  * `doc_type` ("paper" | "book", default "paper" for backward compatibility with the existing
    fixtures) rides along on every `Question`/`QuestionResult` so `build_report`'s `by_doc_type`
    breakdown can report books and papers separately from one mixed-fixture run, per the design
    doc's "must be able to evaluate books separately from papers, and report them separately."

Same real, production retrieval pipeline the 210-question eval already uses end to end
(`app.assembly.build_mcp_server`) -- no simplified stand-in, and this module never talks to the
vector store or LLM adapters directly (CONVENTIONS §1): it only ever imports the composition root.
`--collection` is threaded straight through to `build_mcp_server`'s own existing `collection=`
parameter, so the same runner can score a throwaway "headered" collection against a throwaway
baseline collection during the actual before/after measurement -- no new wiring, no foundation
edit.

Two report-level honesty features (RI-15):

  * `scoring_rule` -- every emitted report carries a string naming the hit rule in force and the
    truncation k, so two numbers produced under different rules cannot be compared silently: a
    number in a JSON file outlives everyone's memory of how it was computed. (Pinned by
    test_build_report_stamps_the_scoring_rule_with_k.)
  * `paper_level.title_leak` -- a verbatim diagnostic counting paper-level hits whose retrieved
    passage embeds the gold paper's own title (casefolded, whitespace runs collapsed), i.e.
    retrievals that may have succeeded on title overlap rather than passage semantics. It is
    reported ALONGSIDE Recall/MRR and deducted from nothing -- deciding what to do about the
    number is not the instrument's call. Matching is verbatim-after-normalization only, so
    paraphrase-level leaks go uncounted and the figure is a floor; the report itself says so.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_GROUND_TRUTH = "fixtures/eval/eval_ground_truth.json"
_DEFAULT_K = 10

# Stated in the emitted report itself (build_report), not just here: a verbatim predicate leaves
# paraphrase-level leaks uncounted, so the reported figure is a floor, not a measurement.
_TITLE_LEAK_NOTE = (
    "Floor, not a measurement: the predicate matches the gold title verbatim only (casefolded, "
    "whitespace runs collapsed), so paraphrase-level leaks go uncounted and true title-driven "
    "retrieval is at least this large. Diagnostic alongside Recall/MRR -- deducted from neither."
)


@dataclass(frozen=True)
class Question:
    question_id: str
    question_text: str
    question_type: str
    gold_paper_ids: frozenset[str]
    gold_block_id: str | None  # None -> not scorable at passage level (e.g. the 210-set today)
    doc_type: str = "paper"  # "paper" | "book" -- default keeps every existing fixture unchanged
    gold_chapter_title: str | None = None  # None -> not scorable at chapter level (papers today)


@dataclass(frozen=True)
class QuestionResult:
    question_id: str
    question_type: str
    paper_rank: int | None  # 1-indexed rank of the first paper-level hit, else None
    passage_rank: int | None  # 1-indexed rank of the first passage-level hit, else None
    passage_scored: bool  # whether this question had a gold_block_id to score against
    error: str | None = None
    # Carried through from Question so build_report's per-question breakdown (T-DOC57) can emit
    # gold ids without a second questions-by-id lookup at report time.
    gold_paper_ids: frozenset[str] = frozenset()
    gold_block_id: str | None = None
    doc_type: str = "paper"
    chapter_rank: int | None = None  # 1-indexed rank of the first chapter-routing hit, else None
    chapter_scored: bool = False  # whether this question had a gold_chapter_title to score against
    gold_chapter_title: str | None = None
    title_leak: bool = False  # a top-k gold passage embeds its own paper's title verbatim


def load_questions(ground_truth_path: Path) -> list[Question]:
    """Loads a ground-truth file into `Question`s. Two supported shapes, distinguished by
    whether a record already carries `question_text`:

      * the equation slice (`eval_equation_slice.json`): every record is self-contained.
      * the 210-question set (`eval_ground_truth.json`): `question_text` lives in the sibling
        `eval_questions_blind.json` (same directory), joined here by `question_id` -- mirrors the
        methodology `.phase0-data/teval/resolve_and_score_v2.py` already used for this file.
    """
    data = json.loads(ground_truth_path.read_text())
    records = data["ground_truth"]

    text_by_id = {r["question_id"]: r["question_text"] for r in records if "question_text" in r}
    if len(text_by_id) < len(records):
        blind_path = ground_truth_path.parent / "eval_questions_blind.json"
        blind = json.loads(blind_path.read_text())["questions"]
        text_by_id.update({q["question_id"]: q["question_text"] for q in blind})

    questions = []
    for r in records:
        qid = r["question_id"]
        if qid not in text_by_id:
            raise ValueError(
                f"{qid}: no question_text in {ground_truth_path} or its blind sibling"
            )
        gold_papers = {r["source_paper_id"], *r.get("additional_gold_paper_ids", [])}
        questions.append(
            Question(
                question_id=qid,
                question_text=text_by_id[qid],
                question_type=r["question_type"],
                gold_paper_ids=frozenset(gold_papers),
                gold_block_id=r.get("gold_block_id"),
                doc_type=r.get("doc_type", "paper"),
                gold_chapter_title=r.get("gold_chapter_title"),
            )
        )
    return questions


def _normalized(text: str) -> str:
    """Casefold + collapse runs of whitespace -- the entire normalization behind the title_leak
    predicate. Nothing smarter (stemming, punctuation folding) on purpose: the diagnostic's
    honesty depends on matching being strictly verbatim-after-normalization."""
    return " ".join(text.casefold().split())


def _title_leak(result, gold_paper_ids: frozenset[str]) -> bool:
    """The verbatim title-leak predicate for one retrieved result (RI-15). Narrow by design:

      * scoped to would-be hits -- a result whose `paper_id` is outside the gold set is out of
        scope even when its passage quotes some title;
      * the title examined is the result's own citation title -- the one place a gold paper's
        title is observable at scoring time without a second corpus lookup;
      * matching is contiguous-substring after `_normalized`, so paraphrase-level overlap leaves
        this False, which is why the aggregate is reported as a floor (see `_TITLE_LEAK_NOTE`).

    Diagnostic input only: it qualifies a hit, it does not un-hit it.
    """
    if result.paper_id not in gold_paper_ids:
        return False
    title = _normalized(result.citation.title or "")
    return bool(title) and title in _normalized(result.passage_text)


def score_question(
    question: Question, results: list, k: int, chapter_results: list | None = None
) -> QuestionResult:
    """`results` is the `list[GroundedResult]` a real (or fake) `Retriever.retrieve()` call
    returned -- already truncated to `k` by `Retriever` itself, but truncated again here so a
    test double that doesn't truncate still scores correctly.

    `chapter_results` is the `list[PaperSearchResult]` a real (or fake) `Retriever.
    retrieve_papers()` call returned, for `gold_chapter_title` questions only -- `run()` doesn't
    make that call at all for a question that isn't chapter-scored, so this is `None` in that
    case (never an empty list standing in for "not scored").
    """
    truncated = results[:k]
    paper_rank = next(
        (i for i, r in enumerate(truncated, start=1) if r.paper_id in question.gold_paper_ids),
        None,
    )
    passage_scored = question.gold_block_id is not None
    passage_rank = None
    if passage_scored:
        passage_rank = next(
            (
                i
                for i, r in enumerate(truncated, start=1)
                if r.anchor.block_id == question.gold_block_id
            ),
            None,
        )
    chapter_scored = question.gold_chapter_title is not None
    chapter_rank = None
    if chapter_scored and chapter_results is not None:
        chapter_rank = next(
            (
                i
                for i, r in enumerate(chapter_results[:k], start=1)
                if r.view.paper_id in question.gold_paper_ids
                and r.chapter == question.gold_chapter_title
            ),
            None,
        )
    return QuestionResult(
        question_id=question.question_id,
        question_type=question.question_type,
        paper_rank=paper_rank,
        passage_rank=passage_rank,
        passage_scored=passage_scored,
        gold_paper_ids=question.gold_paper_ids,
        gold_block_id=question.gold_block_id,
        doc_type=question.doc_type,
        chapter_rank=chapter_rank,
        chapter_scored=chapter_scored,
        gold_chapter_title=question.gold_chapter_title,
        title_leak=any(_title_leak(r, question.gold_paper_ids) for r in truncated),
    )


def run(questions: list[Question], retriever, k: int) -> list[QuestionResult]:
    """Calls the real (or fake) `retriever.retrieve(question_text, filters, k)` for every
    question -- plus `retriever.retrieve_papers(question_text, filters, k)` too, but only for a
    question carrying a `gold_chapter_title` (a chapter-routing question doesn't get scored
    without it, so there's no point spending the extra retrieval call on every other question --
    in particular the existing 210-question/equation-slice fixtures, which carry no book fields
    at all, cost exactly what they did before this metric existed).

    A retrieval error for one question is recorded and skipped, not fatal to the whole run
    (mirrors `Retriever`'s own "drop the bad hit, keep going" posture, T-DOC38) -- a single
    orphaned/unresolvable corpus row shouldn't blank out every other question's score. Both calls
    for one question share a single try/except: if `retrieve()` succeeds but the follow-up
    `retrieve_papers()` then fails, the whole question is recorded as errored rather than
    half-scored on a retrieval pipeline that just proved itself unreliable for this query.
    """
    results = []
    for i, question in enumerate(questions, start=1):
        try:
            hits, _coverage = retriever.retrieve(question.question_text, None, k)
            chapter_hits = None
            if question.gold_chapter_title is not None:
                chapter_hits, _coverage2 = retriever.retrieve_papers(
                    question.question_text, None, k
                )
        except Exception as e:  # noqa: BLE001 -- deliberately broad, see docstring
            logger.warning("retrieve() failed for %s: %s", question.question_id, e)
            results.append(
                QuestionResult(
                    question_id=question.question_id,
                    question_type=question.question_type,
                    paper_rank=None,
                    passage_rank=None,
                    passage_scored=question.gold_block_id is not None,
                    error=str(e),
                    gold_paper_ids=question.gold_paper_ids,
                    gold_block_id=question.gold_block_id,
                    doc_type=question.doc_type,
                    chapter_scored=question.gold_chapter_title is not None,
                    gold_chapter_title=question.gold_chapter_title,
                )
            )
            continue
        results.append(score_question(question, hits, k, chapter_hits))
        if i % 20 == 0:
            logger.info("scored %d/%d questions", i, len(questions))
    return results


def _recall_mrr(ranks: list[int | None]) -> dict:
    n = len(ranks)
    if n == 0:
        return {"recall_at_k": None, "mrr": None, "n": 0}
    hits = sum(1 for r in ranks if r is not None)
    rr_sum = sum(1.0 / r for r in ranks if r is not None)
    return {"recall_at_k": hits / n, "mrr": rr_sum / n, "n": n}


def _question_row(r: QuestionResult) -> dict:
    """One `results` entry as a before/after-diffable dict: gold ids plus hit/rank at both
    granularities. `error` is carried at the top so a question that errored in one run but
    scored in another is visible without inferring it from `null` ranks (a null rank alone is
    ambiguous between "errored" and "ran clean but missed").
    """
    return {
        "question_id": r.question_id,
        "question_type": r.question_type,
        "doc_type": r.doc_type,
        "gold_paper_ids": sorted(r.gold_paper_ids),
        "gold_block_id": r.gold_block_id,
        "gold_chapter_title": r.gold_chapter_title,
        "error": r.error,
        # Diagnostic only -- see build_report's paper_level.title_leak note; not an input to
        # hit/rank above (pinned by test_build_report_reports_leaks_alongside_untouched_metrics).
        "title_leak": r.title_leak,
        "paper_level": {"hit": r.paper_rank is not None, "rank": r.paper_rank},
        "passage_level": {
            "scored": r.passage_scored,
            "hit": r.passage_rank is not None,
            "rank": r.passage_rank,
        },
        "chapter_level": {
            "scored": r.chapter_scored,
            "hit": r.chapter_rank is not None,
            "rank": r.chapter_rank,
        },
    }


def _scoring_rule(k: int) -> str:
    """The hit rule in force, formatted with the k it was applied at. Stamped into every emitted
    report (`build_report`) so two numbers produced under different rules cannot be silently
    compared -- a number in a JSON file outlives everyone's memory of how it was computed."""
    return (
        f"top-{k} truncation; paper-level hit = first rank r <= {k} with result.paper_id in "
        f"question.gold_paper_ids; passage-level hit = first rank r <= {k} with "
        f"result.anchor.block_id == question.gold_block_id; chapter-level hit = first "
        f"retrieve_papers rank with paper_id in gold_paper_ids and chapter == "
        f"gold_chapter_title"
    )


def build_report(results: list[QuestionResult], k: int, *, include_per_question: bool = True) -> dict:
    question_types = sorted({r.question_type for r in results})
    doc_types = sorted({r.doc_type for r in results})
    passage_eligible = [r for r in results if r.passage_scored]
    chapter_eligible = [r for r in results if r.chapter_scored]
    # The leak aggregate is computed over the hits so leaking is structurally a subset of hitting,
    # whatever a hand-built QuestionResult claims.
    hits = [r for r in results if r.paper_rank is not None]
    n_leaking = sum(1 for r in hits if r.title_leak)

    report = {
        # RI-15: names the hit rule and k in force, so reports produced under different rules are
        # not comparable by accident. See _scoring_rule.
        "scoring_rule": _scoring_rule(k),
        "k": k,
        "n_questions": len(results),
        "n_errors": sum(1 for r in results if r.error),
        "paper_level": {
            "overall": _recall_mrr([r.paper_rank for r in results]),
            "by_question_type": {
                t: _recall_mrr([r.paper_rank for r in results if r.question_type == t])
                for t in question_types
            },
            # T-DOC-BOOK-EVAL: lets one mixed paper+book fixture be scored in a single run and
            # still reported separately -- "must be able to evaluate books separately from papers,
            # and report them separately" (docs/DESIGN-book-chapters-and-hierarchy.md Part 3 Step 1).
            "by_doc_type": {
                dt: _recall_mrr([r.paper_rank for r in results if r.doc_type == dt])
                for dt in doc_types
            },
            # RI-15 verbatim title-leak diagnostic. Reported alongside the metrics, deducted from
            # none of them (pinned by test_build_report_reports_leaks_alongside_untouched_metrics):
            # what to do about the number is not the instrument's call. `_TITLE_LEAK_NOTE` travels
            # inside the emitted JSON because the floor limitation belongs to the artifact, not
            # just this module's docstring.
            "title_leak": {
                "predicate": "verbatim-substring",
                "n_hits": len(hits),
                "n_leaking": n_leaking,
                "fraction_of_hits": (n_leaking / len(hits)) if hits else None,
                "note": _TITLE_LEAK_NOTE,
            },
        },
        "passage_level": {
            "n_scored": len(passage_eligible),
            "overall": _recall_mrr([r.passage_rank for r in passage_eligible]),
            "by_question_type": {
                t: _recall_mrr(
                    [r.passage_rank for r in passage_eligible if r.question_type == t]
                )
                for t in sorted({r.question_type for r in passage_eligible})
            },
            "by_doc_type": {
                dt: _recall_mrr([r.passage_rank for r in passage_eligible if r.doc_type == dt])
                for dt in sorted({r.doc_type for r in passage_eligible})
            },
        },
        # Chapter-routing accuracy (search_papers) -- distinct from passage_level (semantic_search)
        # per the design doc: "This is what chapter summaries exist for" vs. "whether chapter work
        # affects retrieval at all, or only navigation." Empty/all-n=0 for any fixture with no
        # gold_chapter_title (the 210-question and equation-slice sets today).
        "chapter_level": {
            "n_scored": len(chapter_eligible),
            "overall": _recall_mrr([r.chapter_rank for r in chapter_eligible]),
            "by_question_type": {
                t: _recall_mrr(
                    [r.chapter_rank for r in chapter_eligible if r.question_type == t]
                )
                for t in sorted({r.question_type for r in chapter_eligible})
            },
        },
    }
    if include_per_question:
        # T-DOC57: lets a before/after diff (e.g. the T-EVAL re-measure) be computed from two
        # report JSONs alone -- no re-running the eval to find which questions moved.
        report["questions"] = [_question_row(r) for r in results]
    return report


def _print_summary(report: dict) -> None:
    def _fmt(m: dict) -> str:
        if m["n"] == 0:
            return "n=0 (no questions in this split)"
        return f"Recall@{report['k']}={m['recall_at_k']:.3f}  MRR={m['mrr']:.3f}  (n={m['n']})"

    print(f"Scoring rule: {report['scoring_rule']}")
    print(f"Questions scored: {report['n_questions']} (errors: {report['n_errors']})")
    print(f"Paper-level   {_fmt(report['paper_level']['overall'])}")
    tl = report["paper_level"]["title_leak"]
    if tl["n_hits"]:
        print(
            f"Title-leak    {tl['n_leaking']}/{tl['n_hits']} of paper-level hits embed their gold "
            "title verbatim -- a floor estimate, paraphrase leaks go uncounted; diagnostic only, "
            "not deducted from the metrics above"
        )
    pl = report["passage_level"]
    if pl["n_scored"]:
        print(f"Passage-level {_fmt(pl['overall'])}  [{pl['n_scored']}/{report['n_questions']} "
              "questions carry a gold_block_id]")
    else:
        print("Passage-level: no question in this ground-truth file carries a gold_block_id "
              "-- nothing to score (this is expected for the 210-question set)")
    cl = report["chapter_level"]
    if cl["n_scored"]:
        print(f"Chapter-level {_fmt(cl['overall'])}  [{cl['n_scored']}/{report['n_questions']} "
              "questions carry a gold_chapter_title]")
    else:
        print("Chapter-level: no question in this ground-truth file carries a gold_chapter_title "
              "-- nothing to score (this is expected for a papers-only fixture)")

    print("\nBy question_type (paper-level):")
    for t, m in sorted(report["paper_level"]["by_question_type"].items()):
        print(f"  {t:30s} {_fmt(m)}")
    if pl["n_scored"]:
        print("\nBy question_type (passage-level):")
        for t, m in sorted(pl["by_question_type"].items()):
            print(f"  {t:30s} {_fmt(m)}")
    if cl["n_scored"]:
        print("\nBy question_type (chapter-level):")
        for t, m in sorted(cl["by_question_type"].items()):
            print(f"  {t:30s} {_fmt(m)}")

    dt = report["paper_level"]["by_doc_type"]
    if len(dt) > 1:
        print("\nBy doc_type (paper-level):")
        for t, m in sorted(dt.items()):
            print(f"  {t:30s} {_fmt(m)}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", default=_DEFAULT_GROUND_TRUTH)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--blob-dir", default=None)
    parser.add_argument(
        "--collection", default=None,
        help="named vector-store collection to search (defaults to the retriever wiring's own "
             "default) -- point this at a throwaway baseline/headered collection to compare them",
    )
    parser.add_argument("--k", type=int, default=_DEFAULT_K)
    parser.add_argument("--report-path", default=None, help="write the JSON report here")
    parser.add_argument(
        "--limit", type=int, default=None, help="score only the first N questions (smoke test)"
    )
    parser.add_argument(
        "--no-per-question", action="store_true",
        help="omit the report's per-question array (present by default) -- use if it bloats the "
             "report and only the aggregates are needed",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()

    # Deferred import: these pull in the real (GPU-backed) adapter wiring, which unit tests must
    # never touch (they exercise load_questions/score_question/run/build_report against a fake
    # retriever instead) -- see app/test_retrieval_eval.py.
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

    questions = load_questions(Path(args.ground_truth))
    if args.limit is not None:
        questions = questions[: args.limit]

    results = run(questions, server.retriever, args.k)
    report = build_report(results, args.k, include_per_question=not args.no_per_question)
    _print_summary(report)

    if args.report_path:
        Path(args.report_path).write_text(json.dumps(report, indent=2))
        print(f"\nWrote report to {args.report_path}")


if __name__ == "__main__":
    main()
