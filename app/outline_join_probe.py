"""Read-only probe for Experiment 1's gate step (docs/PLAN-book-rag-experiments.md, Q1/Q2
prerequisite): does `pypdfium2.get_toc()` join onto `blocks.page` well enough to use as a chapter
splitter?

THROWAWAY SCRATCH SCRIPT, not part of the ingestion/retrieval pipeline. Kept only so the numbers
in `docs/eval-reports/2026-07-29-outline-join-feasibility.md` are reproducible, not hand-recorded.
No GPU, no writes: connects to `papers.db` with `?mode=ro`, reads PDFs from `drop_in/done/` with
pypdfium2 only (no summarizer, no embedder).

Usage:
    RAG_CONFIG=/home/omar/ai-projects/research-system-rag-data/config.yaml \
        python -m app.outline_join_probe
"""

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium

DB_PATH = "/home/omar/ai-projects/research-system-rag-data/papers.db"
PDF_DIR = Path("/home/omar/ai-projects/research-system-rag/drop_in/done")

BOOKS = [
    "local:f0929288d4f3",  # Causal Inference in Python
    "local:f6c64e1e8c7d",  # Elements of Causal Inference
    "local:dfe850b3281a",  # Causal Inference and Discovery in Python
    "local:54d6ca71dda9",  # Causal Inference and ML in Econ/Social/Health
    "local:14b7e283bdcd",  # Trustworthy OCE (control, outline-less)
]

_CHAPTER_OR_PART = re.compile(r"^\s*(chapter|part)\s+\S", re.IGNORECASE)
# Same marker family as rag/book_summarizer.py's _CHAPTER_MARKER (chapter/part/appendix + a
# numeral/letter/word-number), used here to auto-pick which outline LEVEL is "chapter" per book
# (Q5): the level containing the most such markers, or level 0 if no level has any -- covers both
# books that literally print "Chapter N" (at whatever depth) and books that don't print the word
# "chapter" at all but still put one heading per chapter at the top outline level.
_CHAPTER_APPENDIX_MARKER = re.compile(
    r"^\s*(?:chapter|part|appendix)\s+"
    r"(?:\d+|[ivxlcdm]+|[a-z]|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "your",
    "are",
    "was",
    "were",
    "have",
    "has",
    "not",
    "but",
    "you",
    "can",
    "its",
    "using",
    "how",
    "what",
    "when",
    "where",
    "why",
    "who",
    "our",
    "into",
    "over",
    "under",
}
_WORD = re.compile(r"[a-z']{3,}")
MAX_OFFSET = 8  # search window (pages) when looking for where a title actually landed


def _sig_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS}


@dataclass
class TocEntry:
    level: int
    title: str
    page_index: int | None  # None if get_dest() failed to resolve


@dataclass
class Block:
    idx: int
    page: int
    text: str


def load_toc(pdf_path: Path) -> tuple[list[TocEntry], int]:
    """Returns (entries, num_pages). page_index is whatever get_dest().get_index() returns --
    verified 0-based against blocks.page below, not assumed."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    entries = []
    for e in pdf.get_toc():
        dest = e.get_dest()
        page_index = dest.get_index() if dest is not None else None
        entries.append(TocEntry(level=e.level, title=e.get_title(), page_index=page_index))
    return entries, len(pdf)


def load_blocks(conn: sqlite3.Connection, paper_id: str) -> list[Block]:
    cur = conn.execute(
        "SELECT idx, page, text FROM blocks WHERE paper_id = ? ORDER BY idx", (paper_id,)
    )
    return [Block(idx=r[0], page=r[1], text=r[2]) for r in cur.fetchall()]


def page_word_index(blocks: list[Block]) -> dict[int, set[str]]:
    """page -> set of significant lowercase words across all blocks on that page."""
    idx: dict[int, set[str]] = {}
    for b in blocks:
        idx.setdefault(b.page, set()).update(_sig_words(b.text))
    return idx


@dataclass
class MatchResult:
    entry: TocEntry
    offset: int | None  # pages between outline page_index and where title text was actually found
    overlap: float  # best word-overlap ratio found (0..1)


def find_match(entry: TocEntry, pages: dict[int, set[str]]) -> MatchResult:
    words = _sig_words(entry.title)
    if not words or entry.page_index is None:
        return MatchResult(entry, offset=None, overlap=0.0)
    best_offset, best_overlap = None, 0.0
    for delta in range(-MAX_OFFSET, MAX_OFFSET + 1):
        page = entry.page_index + delta
        page_words = pages.get(page)
        if not page_words:
            continue
        overlap = len(words & page_words) / len(words)
        # prefer smaller |delta| on ties, since that's the more "constant offset"-friendly read
        if overlap > best_overlap or (
            overlap == best_overlap and best_offset is not None and abs(delta) < abs(best_offset)
        ):
            best_offset, best_overlap = delta, overlap
    # 0.6 overlap threshold: titles are short (often 2-6 significant words), so this tolerates one
    # OCR/rendering mismatch word without accepting a coincidental single-word hit.
    if best_overlap >= 0.6:
        return MatchResult(entry, offset=best_offset, overlap=best_overlap)
    return MatchResult(entry, offset=None, overlap=best_overlap)


@dataclass
class BookReport:
    paper_id: str
    title: str
    num_toc_entries: int
    levels: list[int]
    num_pages: int
    results: list[MatchResult] = field(default_factory=list)
    front_matter_cutoff_page: int | None = None  # first Chapter/Part entry's page_index


def analyze_book(
    conn: sqlite3.Connection, paper_id: str, pdf_filename: str, title: str
) -> BookReport:
    entries, num_pages = load_toc(PDF_DIR / pdf_filename)
    blocks = load_blocks(conn, paper_id)
    pages = page_word_index(blocks)
    results = [find_match(e, pages) for e in entries]
    chapter_like = [
        e.page_index
        for e in entries
        if _CHAPTER_OR_PART.match(e.title) and e.page_index is not None
    ]
    cutoff = min(chapter_like) if chapter_like else None
    return BookReport(
        paper_id=paper_id,
        title=title,
        num_toc_entries=len(entries),
        levels=sorted({e.level for e in entries}),
        num_pages=num_pages,
        results=results,
        front_matter_cutoff_page=cutoff,
    )


@dataclass
class UnitStat:
    level: int
    num_units: int
    word_shares: list[float]  # each unit's share of total book words, sorted ascending


def units_at_level(blocks: list[Block], entries: list[TocEntry], level: int) -> UnitStat | None:
    """Build chapter units by cutting at each outline entry's page_index for the given level,
    entirely from already-loaded blocks/entries (no re-read). Returns None if <2 usable
    boundaries exist at this level."""
    boundaries = sorted(
        {e.page_index for e in entries if e.level == level and e.page_index is not None}
    )
    if len(boundaries) < 2:
        return None
    total_words = sum(len(b.text.split()) for b in blocks)
    if total_words == 0:
        return None
    unit_words = [0] * len(boundaries)
    for b in blocks:
        # last boundary <= b.page wins; blocks before the first boundary fall into unit 0
        # (pre-first-boundary content, e.g. front matter above this level's first entry)
        u = 0
        for i, start in enumerate(boundaries):
            if b.page >= start:
                u = i
        unit_words[u] += len(b.text.split())
    shares = sorted(w / total_words for w in unit_words)
    return UnitStat(level=level, num_units=len(boundaries), word_shares=shares)


def pick_chapter_level(entries: list[TocEntry]) -> int:
    """Q5 rule: the level with the most Chapter/Part/Appendix-marker titles, else level 0."""
    counts: dict[int, int] = {}
    for e in entries:
        if _CHAPTER_APPENDIX_MARKER.match(e.title):
            counts[e.level] = counts.get(e.level, 0) + 1
    return max(counts, key=lambda lv: counts[lv]) if counts else 0


def main() -> None:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = conn.execute(
        "SELECT paper_id, title, pdf_path FROM papers WHERE paper_id IN (%s)"
        % ",".join("?" for _ in BOOKS),
        BOOKS,
    )
    rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    for paper_id in BOOKS:
        title, pdf_path = rows[paper_id]
        print(f"\n{'=' * 90}\n{paper_id}  {title}\n{'=' * 90}")

        entries, num_pages = load_toc(PDF_DIR / pdf_path)
        print(
            f"get_toc(): {len(entries)} entries, levels {sorted({e.level for e in entries})}, "
            f"pdf has {num_pages} pages, blocks.page range assumption: 0-based like page_index"
        )

        if not entries:
            print("No outline -- control book, nothing to join. Skipping.")
            continue

        cur2 = conn.execute(
            "SELECT COUNT(*) FROM summaries WHERE paper_id = ? AND summary_id LIKE '%:summary:ch%'",
            (paper_id,),
        )
        current_chapter_count = cur2.fetchone()[0]
        print(f"current (today's, live) size-merge chapter count: {current_chapter_count}")

        blocks = load_blocks(conn, paper_id)
        pages = page_word_index(blocks)
        block_page_min = min(b.page for b in blocks)
        block_page_max = max(b.page for b in blocks)
        print(f"blocks: {len(blocks)} rows, page range [{block_page_min}, {block_page_max}]")

        results = [find_match(e, pages) for e in entries]
        chapter_like_pages = [
            e.page_index
            for e in entries
            if _CHAPTER_OR_PART.match(e.title) and e.page_index is not None
        ]
        cutoff = min(chapter_like_pages) if chapter_like_pages else None
        print(f"front-matter cutoff (first Chapter/Part entry's page_index): {cutoff}")

        matched = [r for r in results if r.offset is not None]
        unmatched = [r for r in results if r.offset is None]
        print(
            f"\nTITLE MATCH RATE: {len(matched)}/{len(results)} = {len(matched) / len(results):.3f}"
        )

        def bucket(rs: list[MatchResult], label: str) -> None:
            if not rs:
                print(f"  {label}: n=0")
                return
            m = [r for r in rs if r.offset is not None]
            offsets = [r.offset for r in m]
            print(
                f"  {label}: n={len(rs)}, matched={len(m)} ({len(m) / len(rs):.3f}), "
                f"offsets={sorted(set(offsets)) if offsets else '[]'}, "
                f"offset_mode_count={max((offsets.count(o) for o in set(offsets)), default=0)}"
            )

        if cutoff is not None:
            fm = [
                r
                for r, e in zip(results, entries)
                if e.page_index is not None and e.page_index < cutoff
            ]
            body = [
                r
                for r, e in zip(results, entries)
                if e.page_index is not None and e.page_index >= cutoff
            ]
            bucket(fm, "front matter")
            bucket(body, "body")
        bucket(results, "overall")

        print("\nUnmatched entries (first 15, for manual inspection):")
        for r in unmatched[:15]:
            print(
                f"  level={r.entry.level} page_index={r.entry.page_index} "
                f"best_overlap={r.overlap:.2f} title={r.entry.title!r}"
            )

        chosen = pick_chapter_level(entries)
        print(
            f"\nQ5 auto-picked chapter level: {chosen} (most Chapter/Part/Appendix markers, else 0)"
        )
        print("Candidate chapter units per outline level:")
        for level in sorted({e.level for e in entries}):
            stat = units_at_level(blocks, entries, level)
            marker = " <-- Q5 pick" if level == chosen else ""
            if stat is None:
                print(f"  level {level}: <2 boundaries, skipped{marker}")
                continue
            shares = stat.word_shares
            n = len(shares)
            median = shares[n // 2] if n % 2 else (shares[n // 2 - 1] + shares[n // 2]) / 2
            print(
                f"  level {level}: {stat.num_units} units, word-share min={shares[0]:.3f} "
                f"median={median:.3f} max={shares[-1]:.3f}{marker}"
            )

    conn.close()


if __name__ == "__main__":
    main()
