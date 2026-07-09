"""FakeSummarizer — the default `Summarizer` dependency for every zero-GPU test of
`IngestionOrchestrator` and any module needing a `PaperRecord.summary_text` (T-F4).

Real interface (ARCHITECTURE.md M3B, owner C): `summarize(parsed: ParsedDoc) -> str`, returning
only `summary_text` — `summary_id` is always `f"{paper_id}:summary"`, computed by the caller,
never invented by the Summarizer itself (ARCHITECTURE.md M3B / DATA-CONTRACTS.md §IDs). This fake
follows that rule: it has no notion of `summary_id` at all.
"""

from contracts.parser import ParsedDoc


class FakeSummarizer:
    """Deterministic fixed-length truncation of `ParsedDoc.markdown`. No model, no GPU.

    Guarantees non-empty output (the real Summarizer's invariant, ARCHITECTURE.md M3B) even for a
    `ParsedDoc` whose `markdown` is empty or whitespace-only — the real adapter raises
    `PermanentError` in that case (no usable prose to summarize); this fake instead falls back to
    a deterministic placeholder so it never raises, since it isn't the fake's job to reproduce
    that error path.
    """

    def __init__(self, max_chars: int = 500):
        self._max_chars = max_chars

    def summarize(self, parsed: ParsedDoc) -> str:
        text = parsed.markdown.strip()
        if not text:
            return f"[fake summary: {parsed.paper_id}]"
        return text[: self._max_chars]
