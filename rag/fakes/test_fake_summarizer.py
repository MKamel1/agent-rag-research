"""Tests for FakeSummarizer (T-F4) — non-empty output, determinism, no invented summary_id."""

from contracts.parser import ParsedDoc
from rag.fakes.fake_summarizer import FakeSummarizer


def _parsed_doc(**overrides) -> ParsedDoc:
    fields = dict(
        paper_id="2506.01234",
        markdown="# A Causal Method\n\nWe propose a causal method for estimating treatment "
        "effects under confounding, building on the potential-outcomes framework.",
        blocks=[],
        figures=[],
        tables=[],
        references=[],
        parser_id="mineru-1.x",
    )
    fields.update(overrides)
    return ParsedDoc(**fields)


def test_non_empty_summary_for_non_trivial_input():
    summarizer = FakeSummarizer()
    summary = summarizer.summarize(_parsed_doc())
    assert isinstance(summary, str)
    assert summary.strip() != ""


def test_non_empty_summary_even_for_whitespace_only_markdown():
    summarizer = FakeSummarizer()
    summary = summarizer.summarize(_parsed_doc(markdown="   \n  "))
    assert summary.strip() != ""


def test_deterministic_for_same_input():
    summarizer = FakeSummarizer()
    doc = _parsed_doc()
    assert summarizer.summarize(doc) == summarizer.summarize(doc)


def test_truncates_to_max_chars():
    summarizer = FakeSummarizer(max_chars=10)
    summary = summarizer.summarize(_parsed_doc(markdown="x" * 1000))
    assert len(summary) == 10
