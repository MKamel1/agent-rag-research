"""RI-M4: truncation census -- how often the reranker's and summarizer's fixed content ceilings
(`rag/reranker.py`'s `_MAX_BATCH_TOKENS`/`_MAX_ITEM_TOKENS`, `rag/summarizer.py`'s
`_TOKENS_PER_WORD_ESTIMATE`/`_NUM_CTX_CEILING`) actually bind against real stored corpus content,
and how much text is lost when they do.

INSTRUMENT ONLY (docs/superpowers/plans/2026-08-22-review-implementation.md, wave 4): this module
counts what already happened to stored content. Running it over a full corpus and acting on the
resulting numbers is operator work -- neither this file nor its tests do that.

Reuses the pipeline's own truncation functions (`rag.reranker`, `rag.summarizer`,
`rag.book_summarizer`) rather than re-deriving the token/word math, so a census can never silently
drift from what production actually does to a chunk or a paper.

    python scripts/truncation_census.py --data-dir waymo/data

Real-token calibration (see `calibrate_estimate`) needs a real per-unit token count, which this
system does not currently capture anywhere on its own (the generation server's own token count in
its response is read and discarded -- see `rag/summarizer.py`'s `summarize()`). Pass
`--real-tokens-json PATH` (a JSON object `{unit_id: real_token_count}`, unit ids as printed by
`--list-units`) to calibrate against counts gathered separately; without it, that half of the
report says plainly that it is not measured, rather than guessing.
"""

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contracts.document_store import PaperRecord  # noqa: E402
from rag.book_summarizer import _MAX_CHAPTER_WORDS, _split_chapters  # noqa: E402
from rag.document_store import DocumentStore  # noqa: E402
from rag.reranker import (  # noqa: E402
    _MAX_BATCH_SIZE,
    _MAX_BATCH_TOKENS,
    _estimate_tokens,
    _truncate_to_item_budget,
)
from rag.summarizer import (  # noqa: E402
    _NUM_CTX_CEILING,
    _PROMPT_OVERHEAD_TOKENS,
    _TOKENS_PER_WORD_ESTIMATE,
    _fit_for_summarization,
)

# Average `question_text` length measured over fixtures/eval/eval_questions_blind.json's 210
# questions (2026-08-22): a stand-in for realistic query length only, not real query content --
# `_pack_batches` counts the query's own token cost once per candidate, so getting the length
# right matters more here than the words themselves.
_REPRESENTATIVE_QUERY = "x" * 494


@dataclass
class BindTally:
    """Running count for one grouping key: how many units were seen, how many hit the ceiling,
    and how much was dropped (tokens for a reranker census, words for the summarizer census)
    across the bound units only."""

    total: int = 0
    bound: int = 0
    dropped: int = 0

    def record(self, is_bound: bool, dropped_amount: int = 0) -> None:
        self.total += 1
        if is_bound:
            self.bound += 1
            self.dropped += dropped_amount

    @property
    def bind_rate(self) -> float:
        return self.bound / self.total if self.total else 0.0


@dataclass
class GroupedCensus:
    """One ceiling's tally, sliced three ways so concentration is visible rather than averaged
    away: overall, by `doc_type`, by section/label, and by paper (top offenders only -- see
    `top_offenders`)."""

    overall: BindTally = field(default_factory=BindTally)
    by_doc_type: dict[str, BindTally] = field(default_factory=lambda: defaultdict(BindTally))
    by_section: dict[str, BindTally] = field(default_factory=lambda: defaultdict(BindTally))
    by_paper: dict[str, BindTally] = field(default_factory=lambda: defaultdict(BindTally))

    def record(
        self, *, doc_type: str, section: str, paper_id: str, is_bound: bool, dropped: int = 0
    ) -> None:
        self.overall.record(is_bound, dropped)
        self.by_doc_type[doc_type].record(is_bound, dropped)
        self.by_section[section].record(is_bound, dropped)
        self.by_paper[paper_id].record(is_bound, dropped)


def top_offenders(groups: Mapping[str, BindTally], n: int = 10) -> list[tuple[str, BindTally]]:
    """Worst-`dropped`-first, silent about a group the limit never touched -- a census exists to
    find where loss concentrates, not to list every key that was never at risk."""
    return sorted(
        ((key, tally) for key, tally in groups.items() if tally.bound),
        key=lambda pair: -pair[1].dropped,
    )[:n]


# --------------------------------------------------------------------------------------------
# Reranker: per-chunk item ceiling (drops text) and per-chunk batch-budget pressure (splits an
# HTTP call, drops nothing -- see the docstring on `build_census`'s `reranker_batch_pressure`).
# --------------------------------------------------------------------------------------------


def _record_reranker_chunk(
    item_census: GroupedCensus, batch_census: GroupedCensus, doc_type: str, paper_id: str, chunk,
    *, query_tokens: int, fair_share_tokens: float,
) -> None:
    section = chunk.section_path or "(no section)"
    truncated = _truncate_to_item_budget(chunk.text)
    item_bound = len(truncated) < len(chunk.text)
    item_tokens = _estimate_tokens(truncated)
    dropped_tokens = _estimate_tokens(chunk.text) - item_tokens if item_bound else 0
    item_census.record(
        doc_type=doc_type, section=section, paper_id=paper_id,
        is_bound=item_bound, dropped=dropped_tokens,
    )
    # Nothing is ever dropped by the batch-token budget itself -- it only forces `_pack_batches`
    # to start a new HTTP request early. "Bound" here means this one chunk, on its own, already
    # exceeds the tokens a full `_MAX_BATCH_SIZE`-item batch could give it if every slot were
    # equal -- i.e. it alone would force an oversized batch to split, regardless of what else
    # shares the batch with it.
    over_fair_share = (query_tokens + item_tokens) > fair_share_tokens
    batch_census.record(
        doc_type=doc_type, section=section, paper_id=paper_id, is_bound=over_fair_share,
    )


# --------------------------------------------------------------------------------------------
# Summarizer: whole-document ceiling for doc_type="paper", per-chapter/window ceiling for
# doc_type="book" -- mirroring exactly what the real Summarizer adapter's `summarize()` is
# actually called on for each (rag/orchestrator.py's `_summarize_with_retry` vs.
# rag/book_summarizer.py's `summarize_book`/`_summarize_text`), not the raw whole-book markdown.
# --------------------------------------------------------------------------------------------


def _summarizer_units(record: PaperRecord) -> Iterable[tuple[str, str, str]]:
    """Yields `(unit_id, label, text)` for exactly the text blobs `summarize()` is actually
    called on for this record: the whole document (`doc_type="paper"`), or each book
    chapter/window (`doc_type="book"`) as `rag/book_summarizer.py` would split it.

    The window split below mirrors `rag/book_summarizer.py`'s `_summarize_text` (fixed
    `_MAX_CHAPTER_WORDS`-word windows) rather than importing it directly -- that function also
    calls a live summarizer, which this census never does. If that windowing logic changes, this
    needs to follow.
    """
    paper_id = record.ref.paper_id
    if record.ref.doc_type != "book":
        yield paper_id, "(whole document)", record.parsed.markdown.strip()
        return

    for n, (title, blocks) in enumerate(_split_chapters(record.parsed)):
        chapter_text = "\n\n".join(b.text for b in blocks)
        words = chapter_text.split()
        label = title or f"ch{n}"
        if len(words) <= _MAX_CHAPTER_WORDS:
            yield f"{paper_id}:ch{n}", label, chapter_text
        else:
            for i in range(0, len(words), _MAX_CHAPTER_WORDS):
                window = " ".join(words[i : i + _MAX_CHAPTER_WORDS])
                yield f"{paper_id}:ch{n}:win{i // _MAX_CHAPTER_WORDS}", f"{label} (window)", window


def _record_summarizer_unit(
    census: GroupedCensus, doc_type: str, paper_id: str, label: str, text: str,
) -> tuple[int, int]:
    """Records this unit's bind/drop and returns `(unit_id-scoped words_before, words_after)` --
    the caller keeps `words_after` (what actually gets sent) for calibration."""
    words_before = len(text.split())
    trimmed, _num_ctx = _fit_for_summarization(paper_id, text)
    words_after = len(trimmed.split())
    bound = words_after < words_before
    census.record(
        doc_type=doc_type, section=label, paper_id=paper_id,
        is_bound=bound, dropped=(words_before - words_after) if bound else 0,
    )
    return words_before, words_after


# --------------------------------------------------------------------------------------------
# Estimate calibration: is `_TOKENS_PER_WORD_ESTIMATE` actually close to real usage?
# --------------------------------------------------------------------------------------------


@dataclass
class EstimateCalibration:
    measured: bool
    note: str = ""
    n: int = 0
    mean_abs_pct_error: float = 0.0
    median_abs_pct_error: float = 0.0
    underestimate_rate: float = 0.0  # fraction of samples where the estimate ran LOW
    max_underestimate_tokens: int = 0
    false_fit_count: int = 0  # estimate said "fits the ceiling", real token count would not have


_NOT_MEASURED_NOTE = (
    "not recoverable from stored corpus content: this system never captures the generation "
    "server's own real token count anywhere -- the response field that carries it is read and "
    "discarded (rag/summarizer.py's summarize()). Pass real_token_counts (e.g. sampled "
    "separately from that field) to calibrate; until then, treat every ceiling-bind count above "
    "as measured against an ESTIMATE, not a verified token count."
)


def calibrate_estimate(
    words_sent: Mapping[str, int], real_token_counts: Mapping[str, int] | None,
) -> EstimateCalibration:
    """Compares `_TOKENS_PER_WORD_ESTIMATE`'s prediction for each unit's actually-sent word count
    against a real measured token count for that same unit, when one is supplied.

    `false_fit_count` is the sharp number: how often the estimate said a unit fit under
    `_NUM_CTX_CEILING` when the real token count would not have -- that's the direction of error
    that lets truncation happen silently, unmeasured by the bind counts above (which only see the
    estimate's own opinion of itself).
    """
    if not real_token_counts:
        return EstimateCalibration(measured=False, note=_NOT_MEASURED_NOTE)

    abs_pct_errors: list[float] = []
    underestimates = 0
    max_under = 0
    false_fits = 0
    for unit_id, words in words_sent.items():
        real = real_token_counts.get(unit_id)
        if real is None:
            continue
        estimated = int(words * _TOKENS_PER_WORD_ESTIMATE)
        abs_pct_errors.append(abs(estimated - real) / real if real else 0.0)
        if estimated < real:
            underestimates += 1
            max_under = max(max_under, real - estimated)
        estimated_fits = estimated + _PROMPT_OVERHEAD_TOKENS <= _NUM_CTX_CEILING
        real_fits = real + _PROMPT_OVERHEAD_TOKENS <= _NUM_CTX_CEILING
        if estimated_fits and not real_fits:
            false_fits += 1

    n = len(abs_pct_errors)
    if n == 0:
        return EstimateCalibration(
            measured=False,
            note="real_token_counts had no unit id in common with anything this census measured",
        )
    abs_pct_errors.sort()
    return EstimateCalibration(
        measured=True,
        n=n,
        mean_abs_pct_error=sum(abs_pct_errors) / n,
        median_abs_pct_error=abs_pct_errors[n // 2],
        underestimate_rate=underestimates / n,
        max_underestimate_tokens=max_under,
        false_fit_count=false_fits,
    )


# --------------------------------------------------------------------------------------------
# Top-level census
# --------------------------------------------------------------------------------------------


@dataclass
class TruncationCensus:
    papers_scanned: int
    reranker_item: GroupedCensus
    reranker_batch_pressure: GroupedCensus
    summarizer_ceiling: GroupedCensus
    estimate_calibration: EstimateCalibration


def build_census(
    records: Iterable[PaperRecord], *, real_token_counts: Mapping[str, int] | None = None,
) -> TruncationCensus:
    """Single streaming pass over `records` (CONVENTIONS.md §10: never load a whole corpus into
    memory) -- one `DocumentStore.iter_papers()` sweep feeds all three ceilings at once rather
    than scanning the corpus three times.
    """
    reranker_item = GroupedCensus()
    reranker_batch = GroupedCensus()
    summarizer = GroupedCensus()
    words_sent: dict[str, int] = {}
    papers_scanned = 0

    query_tokens = _estimate_tokens(_REPRESENTATIVE_QUERY)
    fair_share_tokens = _MAX_BATCH_TOKENS / _MAX_BATCH_SIZE

    for record in records:
        papers_scanned += 1
        doc_type = record.ref.doc_type
        paper_id = record.ref.paper_id

        for chunk in record.chunks:
            _record_reranker_chunk(
                reranker_item, reranker_batch, doc_type, paper_id, chunk,
                query_tokens=query_tokens, fair_share_tokens=fair_share_tokens,
            )

        for unit_id, label, text in _summarizer_units(record):
            _, words_after = _record_summarizer_unit(summarizer, doc_type, paper_id, label, text)
            words_sent[unit_id] = words_after

    calibration = calibrate_estimate(words_sent, real_token_counts)
    return TruncationCensus(
        papers_scanned=papers_scanned,
        reranker_item=reranker_item,
        reranker_batch_pressure=reranker_batch,
        summarizer_ceiling=summarizer,
        estimate_calibration=calibration,
    )


# --------------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------------


def _format_grouped(name: str, census: GroupedCensus, unit: str) -> list[str]:
    lines = [
        f"{name}: {census.overall.bound}/{census.overall.total} bound "
        f"({census.overall.bind_rate:.1%}), {census.overall.dropped} {unit} dropped",
    ]
    for label, tally in census.by_doc_type.items():
        lines.append(
            f"  doc_type={label}: {tally.bound}/{tally.total} bound ({tally.bind_rate:.1%}), "
            f"{tally.dropped} {unit} dropped"
        )
    offenders = top_offenders(census.by_paper)
    if offenders:
        lines.append("  top papers by dropped amount:")
        for paper_id, tally in offenders:
            lines.append(f"    {paper_id}: {tally.dropped} {unit} across {tally.bound} unit(s)")
    section_offenders = top_offenders(census.by_section)
    if section_offenders:
        lines.append("  top sections/labels by dropped amount:")
        for section, tally in section_offenders:
            lines.append(f"    {section!r}: {tally.dropped} {unit} across {tally.bound} unit(s)")
    return lines


def format_report(census: TruncationCensus) -> str:
    lines = [f"papers scanned: {census.papers_scanned}", ""]
    lines += _format_grouped("reranker item ceiling (_MAX_ITEM_TOKENS)", census.reranker_item,
                              "tokens")
    lines.append("")
    lines += _format_grouped(
        "reranker batch-budget pressure (_MAX_BATCH_TOKENS, drops nothing -- see docstring)",
        census.reranker_batch_pressure, "tokens (always 0 -- no drop, just an extra HTTP call)",
    )
    lines.append("")
    lines += _format_grouped("summarizer ceiling (_NUM_CTX_CEILING)", census.summarizer_ceiling,
                              "words")
    lines.append("")
    calibration = census.estimate_calibration
    if not calibration.measured:
        lines.append(f"_TOKENS_PER_WORD_ESTIMATE calibration: NOT MEASURED -- {calibration.note}")
    else:
        lines.append(
            f"_TOKENS_PER_WORD_ESTIMATE calibration over {calibration.n} unit(s): "
            f"mean abs error {calibration.mean_abs_pct_error:.1%}, "
            f"median abs error {calibration.median_abs_pct_error:.1%}, "
            f"underestimated {calibration.underestimate_rate:.1%} of units "
            f"(worst underestimate {calibration.max_underestimate_tokens} tokens), "
            f"{calibration.false_fit_count} unit(s) the estimate said fit the ceiling but a "
            f"real token count would not have"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="corpus data dir (papers.db + blobs/)")
    parser.add_argument(
        "--real-tokens-json", default=None,
        help="JSON object {unit_id: real_token_count} to calibrate against (see module docstring)",
    )
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    store = DocumentStore(str(data_dir / "papers.db"), str(data_dir / "blobs"))
    real_token_counts = None
    if args.real_tokens_json:
        real_token_counts = json.loads(Path(args.real_tokens_json).read_text())

    census = build_census(store.iter_papers(), real_token_counts=real_token_counts)
    print(format_report(census))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
