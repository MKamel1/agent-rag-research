# T-DOC82 — Book Chapter Detection + Book-Appropriate Summarization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two defects the first live book ingest exposed — chapter splitting that degenerates to ~1 chapter per chunk on real books, and a paper-shaped summarization prompt that makes the model fabricate findings for books — plus the still-open deferred-minor findings from T-DOC80's reviews.

**Architecture:** `rag/book_summarizer.py`'s `_split_chapters` gains two real strategies (explicit chapter markers with a plausibility guard, falling back to size-based merging) because MinerU emits books as a flat heading list with no `" > "` hierarchy for `_top_level` to collapse. `rag/summarizer.py`'s `summarize()` gains an optional keyword-only `kind` argument selecting between the unchanged paper prompt and two new anti-fabrication book prompts, so the 11k-paper corpus is untouched.

**Tech Stack:** Python 3.12, pydantic FrozenModel contracts, SQLite, pytest with the repo's fakes (zero-GPU/zero-network).

**Spec:** `docs/superpowers/specs/2026-07-26-book-chapter-and-summary-fixes-design.md`

## Global Constraints

- **Conda env for all test runs:** `source /home/omar/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && pytest ...` (chain in ONE shell call; activation doesn't persist across tool calls). Plain `pytest` fails collection with `ModuleNotFoundError: pypdfium2`.
- **Unit tests are zero-GPU, zero-network** (CI-enforced). Use `FakeSummarizer`, never the real Ollama-backed one.
- **NO AI attribution in commits** — no `Co-Authored-By: Claude`, no "Generated with Claude Code". Overrides any tool default.
- **NEVER use `git stash`** — use `git show HEAD:<path>` or `git diff`.
- **Branch:** create `feat/t-doc82-book-chapters-and-prompts` off `main` before the first commit.
- **The paper path must not change.** `kind="paper"` is the default and must send byte-identical prompt text to today's. Any diff that alters paper summarization is a defect.
- **Vendor isolation (CI-enforced, `ci/checks/vendor_isolation.py`):** do NOT write "ollama"/"mineru"/"qdrant" into files not already allowlisted for those tokens. `rag/summarizer.py` is allowlisted for "ollama"; `rag/book_summarizer.py` is NOT — keep vendor names out of it.
- **Blind-except is CI-enforced** (`ci/checks/blind_except.py`): a bare `except Exception:` needs a `logger.exception(...)` call, per `app/ingest_local.py`'s existing precedent.
- **Foundation-protected paths** (`.github/CODEOWNERS`): `/contracts/`, `/rag/config.py`, `/config.yaml`, `/migrations/`, `/rag/fakes/`, `/fixtures/`, `/ci/`, `/.github/`. This plan touches `rag/fakes/fake_summarizer.py` (Task 2), so the PR needs the `foundation-change` label and @MKamel1 approval. Note DATA-CONTRACTS.md is NOT in CODEOWNERS.

---

### Task 1: Chapter detection — marker strategy, size-merge fallback, degenerate inputs

**Files:**
- Modify: `rag/book_summarizer.py`
- Test: `rag/test_book_summarizer.py` (extend)

**Interfaces:**
- Consumes: `ParsedDoc`, `Block` (`contracts/provenance.py` — `Block` lives there; `contracts/parser.py` re-exports it), `ChapterSummary` (`contracts/document_store.py`: `summary_id`, `title`, `text`).
- Produces: `_split_chapters(parsed) -> list[tuple[str, list[Block]]]` with the new behavior; module constants `_TARGET_CHAPTER_WORDS`, `_CHAPTER_MARKER`, `_MIN_MARKER_UNITS`, `_MAX_MARKER_UNITS`, `_MAX_UNIT_WORD_SHARE`. `summarize_book`'s signature is unchanged by this task (Task 2 adds the `kind` wiring).

**Why:** measured on the real corpus — an arXiv paper (`0705.1270`) has 113 blocks whose `section_path` contains `" > "`; a real book (`local:f0929288d4f3`, 2,520 blocks, ~144k words) has **zero**, and 306 distinct flat `section_path` values. So `_top_level` is an identity function on books and every heading became its own "chapter" (530 chapters vs 535 chunks).

- [ ] **Step 1: Write the failing tests** (append to `rag/test_book_summarizer.py`; reuse that file's existing `_block`/`_parsed_doc` helpers — read them first and match their signatures exactly):

```python
def test_flat_book_headings_do_not_become_one_chapter_each():
    """REGRESSION PIN (T-DOC82 D1): the exact real-world failure shape -- many distinct FLAT
    section_paths with no ' > ' hierarchy -- must NOT yield one chapter per heading."""
    blocks = []
    for i in range(60):                      # 60 headings x ~200 words = ~12k words
        for j in range(4):
            blocks.append(_block(" ".join(["word"] * 50), f"Heading {i}", len(blocks)))
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert len(chapters) < 15, f"expected size-merged units, got {len(chapters)}"
    assert len(chapters) >= 2


def test_explicit_chapter_markers_are_used_when_plausible():
    blocks = []
    for title in ["Front matter", "Chapter 1 Intro", "Some subsection",
                  "Chapter 2 DAGs", "Another subsection", "Chapter 3 Estimation"]:
        for _ in range(3):
            blocks.append(_block(" ".join(["word"] * 100), title, len(blocks)))
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    titles = [c.title for c in chapters]
    assert titles == ["", "Chapter 1 Intro", "Chapter 2 DAGs", "Chapter 3 Estimation"]


def test_marker_variants_part_appendix_numbered():
    for marker in ["Part II Foundations", "Appendix A Proofs", "3. Estimation"]:
        blocks = []
        for title in ["Preface", marker, "Body", f"{marker} second", "More", f"{marker} third"]:
            blocks.append(_block(" ".join(["word"] * 100), title, len(blocks)))
        units = _split_chapters(_parsed_doc(blocks))
        assert any(t == marker for t, _ in units), f"{marker!r} not detected as a chapter marker"


def test_too_few_markers_falls_back_to_size_merge():
    """One stray 'Chapter 3' heading must REJECT the marker strategy (count guard) rather than
    produce 2 wildly-unbalanced 'chapters'."""
    blocks = [
        _block(" ".join(["word"] * 100), "Intro", 0),
        _block(" ".join(["word"] * 12000), "Chapter 3 mentioned in passing", 1),
    ]
    units = _split_chapters(_parsed_doc(blocks))
    assert [t for t, _ in units] != ["", "Chapter 3 mentioned in passing"]


def test_marker_split_rejected_when_one_unit_dominates():
    """Word-share guard: 3 markers pass the COUNT guard, but one unit holding >50% of the words
    means those markers aren't real chapter boundaries."""
    blocks = [
        _block(" ".join(["word"] * 100), "Chapter 1 A", 0),
        _block(" ".join(["word"] * 100), "Chapter 2 B", 1),
        _block(" ".join(["word"] * 100), "Chapter 3 C", 2),
        _block(" ".join(["word"] * 5000), "Body text", 3),
    ]
    units = _split_chapters(_parsed_doc(blocks))
    assert [t for t, _ in units] != ["Chapter 1 A", "Chapter 2 B", "Chapter 3 C"]


def test_size_merge_targets_chapter_sized_units():
    blocks = [_block(" ".join(["word"] * 500), f"H{i}", i) for i in range(40)]  # 20k words
    units = _split_chapters(_parsed_doc(blocks))
    assert 3 <= len(units) <= 6, f"expected ~4 units of ~5000 words, got {len(units)}"
    assert units[0][0] == "H0", "unit title should be its first heading"


def test_small_trailing_remainder_merges_instead_of_stub_unit():
    blocks = [_block(" ".join(["word"] * 500), f"H{i}", i) for i in range(21)]  # 10.5k words
    units = _split_chapters(_parsed_doc(blocks))
    assert all(
        sum(len(b.text.split()) for b in bl) > _TARGET_CHAPTER_WORDS // 2 for _, bl in units
    ), "a tiny trailing unit should have merged into the previous one"


def test_single_group_keeps_its_title_through_windowing():
    """Deferred-minor fix: a genuinely single-section doc previously lost its title to ''."""
    blocks = [_block("word " * 10, "The Only Section", i) for i in range(400)]
    units = _split_chapters(_parsed_doc(blocks))
    assert len(units) > 1, "400 blocks should still be windowed"
    assert all(t == "The Only Section" for t, _ in units)


def test_empty_parsed_doc_raises_permanent_error():
    """Deferred-minor fix: zero blocks previously produced an empty summary nobody quarantined."""
    with pytest.raises(PermanentError):
        summarize_book(_parsed_doc([]), FakeSummarizer())
```

Add the imports these need at the top of the test file: `pytest`, `from contracts.errors import PermanentError`, and `from rag.book_summarizer import _TARGET_CHAPTER_WORDS, _split_chapters, summarize_book`.

- [ ] **Step 2: Run the tests, verify they fail**

Run: `source /home/omar/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && pytest rag/test_book_summarizer.py -v`
Expected: the new tests FAIL (ImportError on `_TARGET_CHAPTER_WORDS`/`_split_chapters` not exported, then assertion failures showing one-chapter-per-heading).

- [ ] **Step 3: Implement**

Replace `_split_chapters` and add the helpers. Keep `_top_level` — it is a no-op on books but correctly collapses any doc that *does* have hierarchy, preserving today's behavior there:

```python
import re

from contracts.errors import PermanentError

# T-DOC82: MinerU emits real books as a FLAT heading list (measured: 0 blocks with " > " across
# a 2,520-block book, vs 113 on a comparable arXiv paper), so `_top_level` collapses nothing and
# every heading used to become its own "chapter" -- 530 chapters for 535 chunks. Two strategies
# now run in order; see the spec for the measurements behind each threshold.
# `[a-z]\b` (with IGNORECASE) covers letter appendices -- "Appendix A Proofs". It cannot
# over-match a word like "Part of the story": one letter must be followed by a word boundary,
# and "o" in "of" is not.
_CHAPTER_MARKER = re.compile(
    r"^\s*(?:chapter|part|appendix)\s+"
    r"(?:\d+|[ivxlcdm]+|[a-z]|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b"
    r"|^\s*\d+\.\s+\S",
    re.IGNORECASE,
)
# ponytail: fixed thresholds tuned against one measured 144k-word book, not adaptive. The guard
# band is what stops a book that merely *mentions* "Chapter 3" from producing 2 lopsided units.
_TARGET_CHAPTER_WORDS = 5000
_MIN_MARKER_UNITS = 3
_MAX_MARKER_UNITS = 60
_MAX_UNIT_WORD_SHARE = 0.5


def _words(blocks: list[Block]) -> int:
    return sum(len(b.text.split()) for b in blocks)


def _heading_groups(parsed: ParsedDoc) -> list[tuple[str, list[Block]]]:
    """Consecutive blocks sharing a top-level section_path, in reading order."""
    groups: list[tuple[str, list[Block]]] = []
    for block in parsed.blocks:
        top = _top_level(block.section_path)
        if groups and groups[-1][0] == top:
            groups[-1][1].append(block)
        else:
            groups.append((top, [block]))
    return groups


def _split_by_markers(
    groups: list[tuple[str, list[Block]]]
) -> list[tuple[str, list[Block]]] | None:
    """Strategy A. Returns None when the split isn't plausible, so the caller falls back."""
    units: list[tuple[str, list[Block]]] = []
    for title, blocks in groups:
        if _CHAPTER_MARKER.match(title):
            units.append((title, list(blocks)))
        elif units:
            units[-1][1].extend(blocks)
        else:
            units.append(("", list(blocks)))  # front matter, before the first marker
    if sum(1 for title, _ in units if title) < _MIN_MARKER_UNITS:
        return None
    if len(units) > _MAX_MARKER_UNITS:
        return None
    total = sum(_words(blocks) for _, blocks in units)
    if total and max(_words(blocks) for _, blocks in units) / total > _MAX_UNIT_WORD_SHARE:
        return None
    return units


def _merge_to_target(groups: list[tuple[str, list[Block]]]) -> list[tuple[str, list[Block]]]:
    """Strategy B: accumulate consecutive heading groups until ~_TARGET_CHAPTER_WORDS.

    Title of a merged unit is its FIRST heading. Independent of heading text entirely, which is
    why it is the safe general path for any book's formatting.
    """
    units: list[tuple[str, list[Block]]] = []
    for title, blocks in groups:
        if units and _words(units[-1][1]) < _TARGET_CHAPTER_WORDS:
            units[-1][1].extend(blocks)
        else:
            units.append((title, list(blocks)))
    if len(units) > 1 and _words(units[-1][1]) < _TARGET_CHAPTER_WORDS // 2:
        _, tail = units.pop()
        units[-1][1].extend(tail)
    return units


def _split_chapters(parsed: ParsedDoc) -> list[tuple[str, list[Block]]]:
    groups = _heading_groups(parsed)
    if len(groups) <= 1:
        # No usable heading structure (flat/scanned). Window it, but keep the single group's
        # title rather than dropping it to "" (T-DOC82 deferred-minor fix).
        title = groups[0][0] if groups else ""
        blocks = parsed.blocks
        return [
            (title, list(blocks[i : i + _FALLBACK_WINDOW_BLOCKS]))
            for i in range(0, len(blocks), _FALLBACK_WINDOW_BLOCKS)
        ]
    return _split_by_markers(groups) or _merge_to_target(groups)
```

Then guard the degenerate case at the top of `summarize_book`, after computing chapters:

```python
    if not chapters:
        # T-DOC82 deferred-minor fix: an empty/figures-only parse previously produced an empty
        # summary_text that nothing quarantined. Same taxonomy the real Summarizer uses for the
        # same condition, so IngestionOrchestrator's existing retry/quarantine path handles it.
        raise PermanentError(
            f"{parsed.paper_id}: no usable blocks to summarize (empty or figures-only parse)"
        )
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `source /home/omar/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && pytest rag/test_book_summarizer.py -v`
Expected: PASS. Then the wider suite: `... && pytest rag/ contracts/ -q`

- [ ] **Step 5: Commit**

```bash
git add rag/book_summarizer.py rag/test_book_summarizer.py
git commit -m "T-DOC82: real chapter detection for books -- marker strategy + size-merge fallback"
```

---

### Task 2: Book-appropriate prompts (`kind` argument)

**Files:**
- Modify: `rag/summarizer.py`
- Modify: `rag/fakes/fake_summarizer.py`
- Modify: `rag/book_summarizer.py` (pass `kind` through)
- Test: `rag/test_summarizer.py`, `rag/test_book_summarizer.py` (extend both)

**Interfaces:**
- Consumes: `_split_chapters`/`summarize_book` from Task 1.
- Produces: `OllamaSummarizer.summarize(parsed, *, kind: str = "paper") -> str` where `kind` is one of `"paper"` / `"book"` / `"book_overview"`; unknown raises `ValueError`. `FakeSummarizer.summarize(parsed, *, kind: str = "paper")` accepts and ignores it. `book_summarizer._summarize_text(parsed, summarizer, text, kind)` threads it through.

**Why:** `_SUMMARY_PROMPT` asks for "the main quantitative result or effect size" and "dataset or sample size used". Applied to a Python textbook, the model invented them — the real stored summary for *Causal Inference and Discovery in Python* claims "a novel hybrid method ... improvement ... by approximately 15% ... measured by mean squared error on benchmark datasets". None of that is in the book.

- [ ] **Step 1: Write the failing tests**

In `rag/test_summarizer.py` (read the file first — it already has a fake-HTTP-client pattern for capturing request bodies; reuse it rather than inventing a second one):

```python
def test_paper_kind_sends_the_unchanged_paper_prompt():
    client, captured = _capturing_client()          # existing helper pattern in this file
    summarizer = OllamaSummarizer(client, FakeGpuLock(), "qwen3:14b")
    summarizer.summarize(_doc("some paper prose here"))
    assert "academic paper's contribution" in captured[0]["prompt"]


def test_book_kind_sends_the_book_prompt_and_forbids_invention():
    client, captured = _capturing_client()
    summarizer = OllamaSummarizer(client, FakeGpuLock(), "qwen3:14b")
    summarizer.summarize(_doc("some book prose here"), kind="book")
    prompt = captured[0]["prompt"]
    assert "book section" in prompt
    assert "Do not invent" in prompt
    assert "effect size" not in prompt.split("Do not invent")[0]


def test_book_overview_kind_sends_the_overview_prompt():
    client, captured = _capturing_client()
    summarizer = OllamaSummarizer(client, FakeGpuLock(), "qwen3:14b")
    summarizer.summarize(_doc("section summaries here"), kind="book_overview")
    assert "book as a whole" in captured[0]["prompt"]


def test_unknown_kind_raises_value_error():
    client, _ = _capturing_client()
    summarizer = OllamaSummarizer(client, FakeGpuLock(), "qwen3:14b")
    with pytest.raises(ValueError, match="unknown summarize kind"):
        summarizer.summarize(_doc("prose"), kind="nonsense")
```

In `rag/test_book_summarizer.py`:

```python
class _RecordingSummarizer:
    def __init__(self):
        self.kinds = []

    def summarize(self, parsed, *, kind="paper"):
        self.kinds.append(kind)
        return f"summary of {parsed.markdown[:20]}"


def test_summarize_book_uses_book_kinds_not_paper():
    blocks = [_block(" ".join(["word"] * 500), f"H{i}", i) for i in range(20)]
    rec = _RecordingSummarizer()
    summarize_book(_parsed_doc(blocks), rec)
    assert "paper" not in rec.kinds, "book path must never use the paper prompt"
    assert rec.kinds.count("book_overview") == 1, "exactly one reduce call"
    assert all(k == "book" for k in rec.kinds[:-1])
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `source /home/omar/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && pytest rag/test_summarizer.py rag/test_book_summarizer.py -v`
Expected: FAIL — `summarize()` takes no `kind` argument (TypeError), and `_RecordingSummarizer` records `"paper"`.

- [ ] **Step 3: Implement**

In `rag/summarizer.py`, add below the existing `_SUMMARY_PROMPT` (leave `_SUMMARY_PROMPT` itself **byte-identical**):

```python
# T-DOC82: books are not papers. The paper prompt above asks for "effect size" / "dataset or
# sample size", and asked those of a textbook the model INVENTS them -- a real stored book summary
# claimed a "15% improvement measured by mean squared error on benchmark datasets" that appears
# nowhere in the book. These two prompts drop every paper-shaped field and state the grounding
# constraint explicitly.
_BOOK_SECTION_PROMPT = (
    "Summarize what this book section actually covers, in 4-6 sentences: its main topics, the "
    "concepts or methods it explains, and how it fits into the book's subject matter. State only "
    "what the text says. Do not invent numbers, results, effect sizes, datasets, or findings -- "
    "if the text does not contain them, omit them entirely.\n\n{paper}"
)

_BOOK_OVERVIEW_PROMPT = (
    "These are section summaries from a single book. Describe what the book as a whole covers in "
    "4-6 sentences: its subject, scope, and the main topics it treats. State only what these "
    "summaries say. Do not invent numbers, results, or findings.\n\n{paper}"
)

_PROMPTS = {
    "paper": _SUMMARY_PROMPT,
    "book": _BOOK_SECTION_PROMPT,
    "book_overview": _BOOK_OVERVIEW_PROMPT,
}
```

Change the signature and prompt lookup in `OllamaSummarizer.summarize` (everything else in the method — the GPU lock, `_fit_for_summarization`, the error taxonomy — stays exactly as it is):

```python
    def summarize(self, parsed: ParsedDoc, *, kind: str = "paper") -> str:
        prompt_template = _PROMPTS.get(kind)
        if prompt_template is None:
            raise ValueError(
                f"unknown summarize kind {kind!r}; expected one of {sorted(_PROMPTS)}"
            )
```

and replace `_SUMMARY_PROMPT.format(paper=text)` in the request body with `prompt_template.format(paper=text)`.

In `rag/fakes/fake_summarizer.py`, accept and ignore it:

```python
    def summarize(self, parsed: ParsedDoc, *, kind: str = "paper") -> str:
        # `kind` (T-DOC82) selects a prompt in the real adapter; this fake is a deterministic
        # truncation with no prompt at all, so it accepts the argument and ignores it.
```

In `rag/book_summarizer.py`, thread it through — `_summarize_text` gains a `kind` parameter, the map step passes `"book"`, the reduce step passes `"book_overview"`:

```python
def _summarize_text(parsed: ParsedDoc, summarizer, text: str, kind: str) -> str:
    words = text.split()
    if len(words) <= _MAX_CHAPTER_WORDS:
        return summarizer.summarize(_doc_from_text(parsed, text), kind=kind)
    windows = [
        " ".join(words[i : i + _MAX_CHAPTER_WORDS])
        for i in range(0, len(words), _MAX_CHAPTER_WORDS)
    ]
    partials = [summarizer.summarize(_doc_from_text(parsed, w), kind=kind) for w in windows]
    return summarizer.summarize(_doc_from_text(parsed, "\n\n".join(partials)), kind=kind)
```

Call sites inside `summarize_book`: `_summarize_text(parsed, summarizer, chapter_text, "book")` for each chapter, and `_summarize_text(parsed, summarizer, joined, "book_overview")` for the overview.

- [ ] **Step 4: Run the tests, verify they pass**

Run: `... && pytest rag/test_summarizer.py rag/test_book_summarizer.py -v`
Then confirm the paper path is untouched: `... && pytest rag/ contracts/ app/ -q`

- [ ] **Step 5: Commit**

```bash
git add rag/summarizer.py rag/fakes/fake_summarizer.py rag/book_summarizer.py rag/test_summarizer.py rag/test_book_summarizer.py
git commit -m "T-DOC82: book-specific anti-fabrication prompts via summarize(kind=...)"
```

---

### Task 3: Deferred-minor fixes from T-DOC80's reviews

**Files:**
- Modify: `rag/document_store.py` (chapter-index sort guard)
- Modify: `rag/retriever.py` (comment on the deliberate `chapter=None` fallback)
- Modify: `app/obsidian_export.py` (duplicate link for `local:` ids)
- Modify: `app/ingest_local.py` (arXiv-id false positives)
- Test: `rag/test_document_store.py`, `rag/test_retriever.py`, `app/test_obsidian_export.py`, `app/test_ingest_local.py` (extend each)

**Interfaces:**
- Consumes: nothing from Tasks 1-2 (independent).
- Produces: no new public API. `detect_arxiv_id(filename, first_page_text)` keeps its signature; only its matching rules tighten.

**Why:** these are the still-open Minor findings from T-DOC80's per-task and final reviews, deferred at the time and explicitly pulled in now.

- [ ] **Step 1: Write the failing tests**

```python
# rag/test_document_store.py
def test_malformed_chapter_summary_id_raises_contract_error(store, make_record):
    """A summary row that is neither the whole-doc summary nor a parseable :ch{n} previously
    raised a bare ValueError out of get()."""
    record = make_record(paper_id="local:ab12cd34ef56", doc_type="book")
    store.put(record)
    store._con.execute(
        "INSERT INTO summaries (summary_id, paper_id, text, title) VALUES (?, ?, ?, ?)",
        ("local:ab12cd34ef56:summary:chXYZ", "local:ab12cd34ef56", "t", "T"),
    )
    store._con.commit()
    with pytest.raises(ContractError, match="chapter summary_id"):
        store.get("local:ab12cd34ef56")


# rag/test_retriever.py
def test_mixed_hits_whole_book_sibling_has_chapter_none(...):
    """Deferred minor: the mixed-hits test never asserted the sibling whole-book hit's chapter
    is None IN THE SAME result set."""
    # seed one book record; upsert BOTH its ":summary" and ":summary:ch1" vectors;
    # retrieve_papers(query) -> the whole-book hit has chapter is None, the chapter hit does not.


# app/test_obsidian_export.py
def test_local_id_note_does_not_duplicate_the_same_url_twice():
    ref = _ref(paper_id="local:ab12cd34ef56", pdf_url="causality-pearl.pdf")
    note = render_note(_record(ref))
    assert note.count("causality-pearl.pdf") == 1


# app/test_ingest_local.py
def test_bare_decimal_in_body_text_is_not_an_arxiv_id():
    """'Table 4.12345' must not false-positive into the arXiv lookup path."""
    assert detect_arxiv_id("causality-pearl.pdf", "See Table 4.12345 for results") is None


def test_prefixed_arxiv_id_still_detected():
    assert detect_arxiv_id("paper.pdf", "arXiv:2409.01266v1 [stat.ME]") == "2409.01266"


def test_bare_id_as_whole_filename_still_detected():
    assert detect_arxiv_id("2409.01266v2.pdf", "") == "2409.01266"
```

- [ ] **Step 2: Run them, verify they fail**

Run: `... && pytest rag/test_document_store.py rag/test_retriever.py app/test_obsidian_export.py app/test_ingest_local.py -v -k "malformed or sibling or duplicate or arxiv_id or decimal"`

- [ ] **Step 3: Implement**

`rag/document_store.py` — replace the bare `int(...rsplit("ch", 1)[1])` sort key (import `ContractError` from `contracts.errors` if not already imported):

```python
        def _chapter_index(summary_id: str) -> int:
            head, _, tail = summary_id.rpartition("ch")
            if not head or not tail.isdigit():
                raise ContractError(
                    f"unparseable chapter summary_id {summary_id!r} for paper {paper_id!r}"
                )
            return int(tail)

        chapter_rows.sort(key=lambda r: _chapter_index(r["summary_id"]))
```

`rag/retriever.py` — the `chapter = None` fallback is deliberate; say so where it happens:

```python
            chapter = None
            if candidate.id != f"{paper_id}{_SUMMARY_ID_SUFFIX}":
                cs = next(
                    (c for c in record.chapter_summaries if c.summary_id == candidate.id), None
                )
                # Deliberate (T-DOC82): a chapter-shaped id with no matching ChapterSummary means
                # an orphaned/stale vector. Degrade to an unlabelled result rather than failing the
                # whole query -- same skip-and-continue posture as the unresolvable-hit branch above.
                chapter = cs.title if cs is not None else None
```

`app/obsidian_export.py` — `source_url()` returns `pdf_url` verbatim for `local:` ids, so the line rendered the same URL twice under two labels:

```python
    source = source_url(ref.paper_id, ref.pdf_url)
    links = f"[PDF]({ref.pdf_url})"
    if source != ref.pdf_url:                     # arXiv: a genuinely different abs page
        links += f" · [Source]({source})"
    lines.append(f"**Source:** {links}")
```

(Adapt to the surrounding code's actual local variable/append style — read the function first.)

`app/ingest_local.py` — require either an explicit `arXiv` prefix, or the id standing alone as the whole filename stem. A bare `\d{4}\.\d{4,5}` anywhere in page text is too loose:

```python
_ARXIV_ID_PREFIXED = re.compile(r"arxiv[:\s/]*(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
_ARXIV_ID_BARE = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?$")


def detect_arxiv_id(filename: str, first_page_text: str) -> str | None:
    """T-DOC82: previously any bare `\\d{4}\\.\\d{4,5}` matched, so a body-text decimal like
    "Table 4.12345" false-positived into an arXiv metadata lookup. Now the id must either carry
    an explicit arXiv prefix, or be the entire filename stem (how arXiv PDFs are actually named).
    """
    stem = Path(filename).stem
    bare = _ARXIV_ID_BARE.match(stem)
    if bare:
        return bare.group(1)
    for source in (filename, first_page_text):
        prefixed = _ARXIV_ID_PREFIXED.search(source)
        if prefixed:
            return prefixed.group(1)
    return None
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `... && pytest rag/ app/ contracts/ -q`

- [ ] **Step 5: Commit**

```bash
git add rag/document_store.py rag/retriever.py app/obsidian_export.py app/ingest_local.py rag/test_document_store.py rag/test_retriever.py app/test_obsidian_export.py app/test_ingest_local.py
git commit -m "T-DOC82: deferred-minor fixes -- chapter-id guard, local: link dedupe, arXiv-id false positives"
```

---

### Task 4: Cap chapter hits per document in `search_papers`

**Files:**
- Modify: `rag/retriever.py`
- Test: `rag/test_retriever.py` (extend)

**Interfaces:**
- Consumes: `PaperSearchResult.chapter` and `.view.paper_id` (T-DOC80).
- Produces: module constant `_MAX_HITS_PER_PAPER = 3` and helper `_cap_per_paper(results, limit)` applied inside `retrieve_papers` **before** the existing `results[:k]` truncation.

**Why:** final-review finding #9 — one book's chapters can occupy every slot of `k` for a single `paper_id`, crowding papers out of a mixed-corpus query. Less acute now that Task 1 cuts chapters from ~530 to ~25 per book, but still real.

- [ ] **Step 1: Write the failing test**

```python
def test_search_papers_caps_chapter_hits_per_paper(...):
    """One book must not occupy every slot of k with its own chapters."""
    # seed ONE book record with 8 chapter summaries, all upserted as kind="summary" vectors,
    # all matching the query; retrieve_papers(query, k=8)
    results, _ = retriever.retrieve_papers("causal", k=8)
    assert len(results) <= _MAX_HITS_PER_PAPER
    assert len({r.view.paper_id for r in results}) == 1


def test_cap_does_not_reduce_results_across_distinct_papers(...):
    # seed 5 distinct PAPERS (one summary each); k=5 -> all 5 still returned
    results, _ = retriever.retrieve_papers("causal", k=5)
    assert len(results) == 5
```

- [ ] **Step 2: Run, verify it fails**

Run: `... && pytest rag/test_retriever.py -v -k "caps_chapter or distinct_papers"`
Expected: the first FAILS (8 results returned, all one book).

- [ ] **Step 3: Implement**

```python
# T-DOC82: a book contributes one vector per chapter, so a strong book match could fill every
# slot of `k` with chapters of the SAME paper_id and crowd papers out of a mixed-corpus query.
# Applied after rerank, before top-k truncation, so the cap selects the best N per paper.
_MAX_HITS_PER_PAPER = 3


def _cap_per_paper(
    results: list[PaperSearchResult], limit: int = _MAX_HITS_PER_PAPER
) -> list[PaperSearchResult]:
    seen: dict[str, int] = {}
    capped: list[PaperSearchResult] = []
    for result in results:
        paper_id = result.view.paper_id
        count = seen.get(paper_id, 0)
        if count >= limit:
            continue
        seen[paper_id] = count + 1
        capped.append(result)
    return capped
```

In `retrieve_papers`, change the final return from `return results[:k], RetrievalCoverage(...)` to:

```python
        return _cap_per_paper(results)[:k], RetrievalCoverage(candidate_count=len(hits))
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `... && pytest rag/test_retriever.py rag/test_mcp_server.py -q`

- [ ] **Step 5: Commit**

```bash
git add rag/retriever.py rag/test_retriever.py
git commit -m "T-DOC82: cap chapter hits per paper in search_papers so one book can't fill top-k"
```

---

### Task 5: Documentation sync

**Files:**
- Modify: `ARCHITECTURE.md` (M3B), `DATA-CONTRACTS.md` (§M3B), `WORK-BREAKDOWN.md` (T-DOC82 entry + T-DOC80 commit-range fix)

Docs are authoritative in this repo — code that drifts from them is a bug, so this task is mandatory.

- [ ] **Step 1: ARCHITECTURE.md** — in M3B, replace the "top-level `section_path` groups" description of book chapter splitting with the real two-strategy behavior (markers with plausibility guard → size-merge fallback → windowing for structureless docs), and note `summarize(kind=...)` selecting paper vs book prompts. Include the measured fact that MinerU emits books flat (0 blocks with `" > "`) — that is *why* the design is what it is.
- [ ] **Step 2: DATA-CONTRACTS.md** — §M3B: document `summarize(parsed, *, kind="paper"|"book"|"book_overview")`, that unknown kinds raise `ValueError`, and that `summarize_book` raises `PermanentError` on a doc with no usable blocks.
- [ ] **Step 3: WORK-BREAKDOWN.md** — add the T-DOC82 entry (both defects, how they were found, what changed, the deferred-minors folded in). Also fix T-DOC80's entry, which cites `commits ff461ae..b1d9d7a` — two commits short; the real range ends at the doc-sync fix. Get the actual range with `git log --oneline` and use it.
- [ ] **Step 4: Self-check** — grep the three docs for `_TARGET_CHAPTER_WORDS`, `kind=`, `book_overview`, `_MAX_HITS_PER_PAPER` and confirm the names match the code exactly.
- [ ] **Step 5: Commit**

```bash
git add ARCHITECTURE.md DATA-CONTRACTS.md WORK-BREAKDOWN.md
git commit -m "T-DOC82: doc sync -- book chapter strategies, summarize(kind=), per-paper hit cap"
```

---

### Task 6: Full-suite verification + CI checks

**Files:** none modified — this task is the safety gate the user explicitly asked for.

- [ ] **Step 1: Full suite**

```bash
source /home/omar/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && pytest
```
Expected: all pass. (Bare `pytest` is what CI runs — `pyproject.toml`'s `testpaths` covers `rag`, `contracts`, `ci/checks`, `fixtures/eval`, `app`. `migrations/` is outside it; run `pytest migrations/` separately and expect the ONE known pre-existing failure `test_0002_ingest_checkpoint_matches_data_contracts_schema`, which predates this branch — do not fix it here.)

- [ ] **Step 2: CI enforcement checks** — vendor isolation especially, since Task 1 adds prose to `rag/book_summarizer.py` and Task 2 touches `rag/summarizer.py`:

```bash
source /home/omar/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && python -m ci.run_enforcement
```
Expected: 0 violations. If "ollama"/"mineru"/"qdrant" appears in a newly-written comment in a non-allowlisted file, reword the comment — do not widen the allowlist.

- [ ] **Step 3: Lint**

```bash
source /home/omar/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && ruff check rag/ app/ contracts/
```

- [ ] **Step 4: Confirm the paper path is genuinely unchanged**

```bash
git diff main -- rag/summarizer.py | grep -E "^[-+].*_SUMMARY_PROMPT" || echo "paper prompt untouched"
```
Expected: the `_SUMMARY_PROMPT` **definition** appears in no `-` line. It may appear in a `+` line only as a `_PROMPTS` dict entry. If its text changed, that is a defect — revert it.

- [ ] **Step 5: Commit** (only if steps 1-4 required fixes; otherwise nothing to commit)

---

## Post-plan operator verification (human + GPU, not part of any task's DoD)

Run after the PR lands. The 5 books currently in the corpus carry fabricated summaries and ~1,380 junk chapter summaries; per the spec, **verify on one book before re-ingesting the rest**.

1. Pick one book (suggest `local:f0929288d4f3`, *Causal Inference in Python* — the one measured in the spec, 351 bad chapters).
2. Delete it through the real cross-store path so SQLite and Qdrant stay in sync (`IngestionOrchestrator.delete_paper`, which uses `DocumentStore.delete`'s returned vector ids — T-DOC80 Task 2's fix makes that include every chapter id).
3. Re-stage from `drop_in/done/` and re-ingest that single id.
4. **Inspect by eye before going further:**
   - chapter count is ~15-30, not ~300
   - chapter titles read like real sections, not `Italic` / `Contributors` / `About the author`
   - the whole-book summary describes *that book* and contains no invented numbers, benchmarks, or effect sizes
5. Only if all four hold, delete + re-ingest the remaining 4 books.
