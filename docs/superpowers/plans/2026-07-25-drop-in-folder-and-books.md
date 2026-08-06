# Drop-in Folder + Book Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop any PDF (paper or book) into `drop_in/{papers,books}/`, run `python -m app.ingest_local`, and it lands in the corpus — books get map-reduce summarization with chapter summaries embedded as routing units, and MCP callers can filter/label results by `doc_type`.

**Architecture:** A thin staging script (`app/ingest_local.py`) writes `<paper_id>.pdf` + `<paper_id>.json` pairs into `pdf_cache_dir` (the exact format T-DOC48's `_cached_ref` already reads offline) and hands the ids to the existing `app.ingest --paper-ids-file` pipeline. Books differ from papers only where length matters: parse batch-of-1, and a new map-reduce summarizer (`rag/book_summarizer.py`) whose per-chapter outputs are persisted in the existing `summaries` table and embedded as `kind="summary"` vectors under `{paper_id}:summary:ch{n}` ids. All contract changes are additive with defaults.

**Tech Stack:** Python 3.12, pydantic FrozenModel contracts, SQLite (migrations/), pypdfium2 (already a dep), pytest with the repo's fakes (zero-GPU/zero-network).

**Spec:** `docs/superpowers/specs/2026-07-25-drop-in-folder-and-books-design.md`

## Global Constraints

- **Conda env for all test runs:** `source /home/omar/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && pytest ...` (chain in ONE shell call; activation doesn't persist across tool calls). Plain `pytest` fails collection with `ModuleNotFoundError: pypdfium2`.
- **Unit tests are zero-GPU, zero-network** (CI-enforced, CONVENTIONS §12). Never call arXiv, Ollama, TEI, or Qdrant in a unit test — inject fakes/fetchers.
- **NO AI attribution in commits** — no `Co-Authored-By: Claude`, no "Generated with Claude Code" lines, ever. This overrides any tool default.
- **NEVER use `git stash`** (shared stash stack across worktrees). Use `git show HEAD:<path>` or `git diff` instead.
- **Ticket id:** verify `T-DOC80` is unused (`git log --oneline | grep -o "T-DOC[0-9]*" | sort -u -V | tail -5`; WORK-BREAKDOWN.md tops out at T-DOC67 but commits reach T-DOC78). If taken, use the next free number and substitute it in every commit message below.
- **Foundation-protected paths** (`contracts/`, `config.yaml`, `migrations/`): edits are allowed on the branch, but the PR requires explicit approval from `@MKamel1` (CODEOWNERS) — call this out in the PR body.
- **Branch:** create `feat/t-doc80-drop-in-and-books` off `main` before the first commit (GIT-WORKFLOW.md).
- **Additive only:** every contract field gets a default so existing fixtures/sidecars/tests parse unchanged. Never remove or rename an existing field.
- **ID parsing:** `rag/retriever.py::_paper_id_from_summary_hit_id` stays the ONE sanctioned parser of summary-id strings (`ci/checks/id_slicing.py` fences it by name — don't rename it, don't add a second parse site).

---

### Task 1: Contract additions (doc_type, ChapterSummary, filters, envelopes, Config)

**Files:**
- Modify: `contracts/harvester.py` (PaperRef)
- Modify: `contracts/vector_index.py` (SearchFilters, VectorPayload)
- Modify: `contracts/document_store.py` (ChapterSummary, PaperRecord)
- Modify: `contracts/mcp_server.py` (PaperSearchResult)
- Modify: `contracts/retriever.py` (Citation)
- Modify: `contracts/ingest_state.py` (CheckpointArtifacts)
- Modify: `contracts/config.py` (drop_in_dir)
- Modify: `config.yaml` (drop_in_dir key)
- Test: `contracts/test_harvester.py`, `contracts/test_document_store.py`, `contracts/test_vector_index.py` (extend existing files, follow their style)

**Interfaces:**
- Produces (later tasks rely on these exact names):
  - `PaperRef.doc_type: Literal["paper", "book"] = "paper"`
  - `SearchFilters.doc_type: Literal["paper", "book"] | None = None`
  - `VectorPayload["doc_type"]: str` (new required TypedDict key)
  - `ChapterSummary(FrozenModel)` with `summary_id: str`, `title: str`, `text: str`
  - `PaperRecord.chapter_summaries: list[ChapterSummary] = Field(default_factory=list)`
  - `PaperSearchResult.chapter: str | None = None`
  - `Citation.doc_type: Literal["paper", "book"] = "paper"`
  - `CheckpointArtifacts.chapter_summaries: list[ChapterSummary] | None = None`
  - `Config.drop_in_dir: str = "drop_in"`

- [ ] **Step 1: Write failing tests** (append to the existing contract test files, matching their existing test style):

```python
# contracts/test_harvester.py
def test_paper_ref_doc_type_defaults_to_paper(make_ref):  # reuse the file's existing fixture/builder
    assert make_ref().doc_type == "paper"

def test_paper_ref_doc_type_book_round_trips_json(make_ref):
    ref = make_ref(doc_type="book")
    assert PaperRef.model_validate_json(ref.model_dump_json()).doc_type == "book"

def test_paper_ref_sidecar_without_doc_type_still_parses(make_ref):
    # T-DOC48 sidecars written before this change have no doc_type key — must default, not fail
    data = make_ref().model_dump_json(exclude={"doc_type"})
    assert PaperRef.model_validate_json(data).doc_type == "paper"

# contracts/test_document_store.py
def test_chapter_summary_shape():
    cs = ChapterSummary(summary_id="local:ab12cd34ef56:summary:ch0", title="Intro", text="...")
    assert cs.title == "Intro"

def test_paper_record_chapter_summaries_default_empty(make_record):
    assert make_record().chapter_summaries == []

# contracts/test_vector_index.py
def test_search_filters_doc_type_default_none():
    assert SearchFilters().doc_type is None
```

If a test file has no ref/record builder fixture, construct the objects inline the way that file's existing tests do.

- [ ] **Step 2: Run tests, verify they fail** (`AttributeError`/`ValidationError`):

`source /home/omar/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && pytest contracts/test_harvester.py contracts/test_document_store.py contracts/test_vector_index.py -v`

- [ ] **Step 3: Implement.** Exact additions (each below the existing fields of its class):

```python
# contracts/harvester.py — PaperRef, after relevance_score:
    # "paper" (default, incl. every arXiv harvest) or "book" — set by app/ingest_local.py from
    # the drop_in/ subfolder the file arrived in. Additive with default so pre-existing
    # T-DOC48 sidecars (no doc_type key) parse unchanged.
    doc_type: Literal["paper", "book"] = "paper"

# contracts/vector_index.py — SearchFilters, after kind:
    doc_type: Literal["paper", "book"] | None = None  # restrict to VectorPayload.doc_type

# contracts/vector_index.py — VectorPayload, after embedding_version:
    doc_type: str  # "paper" | "book" — mirrors PaperRef.doc_type

# contracts/document_store.py — new class above PaperRecord:
class ChapterSummary(FrozenModel):
    """One chapter's map-step summary for a doc_type="book" record. Persisted in the same
    `summaries` table as the whole-document summary (migration 0004 adds `title`), embedded as its
    own kind="summary" vector so search_papers can return individual chapters as routing hits."""

    summary_id: str  # f"{paper_id}:summary:ch{n}", n = 0-based chapter index (DATA-CONTRACTS §IDs)
    title: str       # chapter heading (top-level section_path); "" for the windowed fallback
    text: str        # non-empty chapter summary

# contracts/document_store.py — PaperRecord, after relevance_score:
    chapter_summaries: list[ChapterSummary] = Field(default_factory=list)  # non-empty only for books

# contracts/mcp_server.py — PaperSearchResult, after score:
    # Set when this routing hit resolved from a chapter summary ({paper_id}:summary:ch{n}) —
    # the chapter's title. None for whole-paper/whole-book hits.
    chapter: str | None = None

# contracts/retriever.py — Citation, after section_path:
    doc_type: Literal["paper", "book"] = "paper"

# contracts/ingest_state.py — CheckpointArtifacts, after relevance_score:
    chapter_summaries: list[ChapterSummary] | None = None  # books only; None until summarized

# contracts/config.py — after pdf_cache_dir:
    drop_in_dir: str = "drop_in"  # app/ingest_local.py scan root (papers/, books/ subfolders)
```

`contracts/ingest_state.py` needs `from contracts.document_store import ChapterSummary` — check for import cycles (document_store must not import ingest_state; it doesn't today).

Add to `config.yaml` next to `pdf_cache_dir`:

```yaml
drop_in_dir: "drop_in"  # app/ingest_local.py scan root (papers/, books/ subfolders)
```

- [ ] **Step 4: Run the same tests — PASS. Then run the full contracts suite** to catch anything the TypedDict key broke:

`... && pytest contracts/ -v`

Note: adding a required `doc_type` key to `VectorPayload` will surface every place that constructs a payload literal (orchestrator, fakes' tests, fixtures). If `contracts/` or `rag/` tests fail on missing `doc_type`, add `"doc_type": "paper"` to those constructor sites now — that's the point of making it required.

`... && pytest rag/ contracts/ -x -q`

- [ ] **Step 5: Commit**

```bash
git add contracts/ config.yaml rag/
git commit -m "T-DOC80: additive doc_type/ChapterSummary contract fields for drop-in + book ingestion"
```

---

### Task 2: Migration 0004 + DocumentStore persistence of doc_type and chapter summaries

**Files:**
- Create: `migrations/0004_doc_type_and_chapter_titles.sql`
- Modify: `rag/document_store.py` (put/get/delete round-trip)
- Test: `rag/test_document_store.py` (extend)

**Interfaces:**
- Consumes: `ChapterSummary`, `PaperRecord.chapter_summaries`, `PaperRef.doc_type` (Task 1).
- Produces: `DocumentStore.put()` persists `papers.doc_type` and one `summaries` row per chapter (with `title`); `DocumentStore.get()` returns a `PaperRecord` whose `ref.doc_type` and `chapter_summaries` round-trip exactly; `get_summary("{paper_id}:summary:ch{n}")` resolves chapter text.

- [ ] **Step 1: Write failing tests** (use the file's existing temp-SQLite fixture pattern):

```python
def test_put_get_round_trips_doc_type_and_chapters(store, make_record):
    chapters = [
        ChapterSummary(summary_id="local:ab12cd34ef56:summary:ch0", title="Intro", text="ch0 summary"),
        ChapterSummary(summary_id="local:ab12cd34ef56:summary:ch1", title="DAGs", text="ch1 summary"),
    ]
    record = make_record(paper_id="local:ab12cd34ef56", doc_type="book", chapter_summaries=chapters)
    store.put(record)
    got = store.get("local:ab12cd34ef56")
    assert got.ref.doc_type == "book"
    assert got.chapter_summaries == chapters

def test_chapter_order_is_numeric_not_lexical(store, make_record):
    # ch10 must come after ch2 — lexical ordering would break this at 10+ chapters
    chapters = [ChapterSummary(summary_id=f"local:ab12cd34ef56:summary:ch{i}", title=f"C{i}", text="t")
                for i in range(12)]
    store.put(make_record(paper_id="local:ab12cd34ef56", doc_type="book", chapter_summaries=chapters))
    got = store.get("local:ab12cd34ef56")
    assert [c.summary_id for c in got.chapter_summaries] == [c.summary_id for c in chapters]

def test_get_summary_resolves_chapter_ids(store, make_record):
    ...  # put a book record; assert store.get_summary("local:ab12cd34ef56:summary:ch1") == "ch1 summary"

def test_paper_without_chapters_unchanged(store, make_record):
    store.put(make_record())  # plain paper
    assert store.get(...).chapter_summaries == []

def test_delete_removes_chapter_rows(store, make_record):
    ...  # put book, delete paper_id, assert summaries table has no rows for it
```

- [ ] **Step 2: Run, verify failures** (`... && pytest rag/test_document_store.py -v` — expect `no such column: doc_type` / missing attribute assertions).

- [ ] **Step 3: Implement.**

```sql
-- migrations/0004_doc_type_and_chapter_titles.sql
-- T-DOC80: drop-in + book ingestion. Additive; every pre-existing row is a paper.
ALTER TABLE papers ADD COLUMN doc_type TEXT NOT NULL DEFAULT 'paper';
-- Chapter title for {paper_id}:summary:ch{n} rows; NULL for whole-document summary rows.
ALTER TABLE summaries ADD COLUMN title TEXT;
```

(Confirm `migrations/migrate.py` picks up new numbered files automatically — it applies in filename order; `rag/test_migrate.py`-style tests exist in `migrations/test_migrate.py`.)

In `rag/document_store.py`:
- `put()`: papers INSERT/UPSERT gains `doc_type` column ← `record.ref.doc_type`; after the existing whole-document summary INSERT (which now passes `title=NULL`), loop `record.chapter_summaries` inserting `(cs.summary_id, paper_id, cs.text, cs.title)`. The existing `DELETE FROM summaries WHERE paper_id = ?` before re-insert already handles re-put cleanly.
- `get()`: read `doc_type` from the papers row into the reconstructed `PaperRef`; from the `SELECT summary_id, text, title FROM summaries WHERE paper_id = ?` rows, the `summary_id == f"{paper_id}:summary"` row is `summary_text` (unchanged) and the rest become `chapter_summaries`, **sorted by the integer after the final `ch`** (`int(summary_id.rsplit("ch", 1)[1])`) — this sort lives inside DocumentStore, which per DATA-CONTRACTS owns ID-format knowledge.
- `delete()` already deletes by `paper_id` from `summaries` — verify the test passes without changes.

- [ ] **Step 4: Run — PASS**, plus the migration tests: `... && pytest rag/test_document_store.py migrations/ -v`

- [ ] **Step 5: Commit**

```bash
git add migrations/0004_doc_type_and_chapter_titles.sql rag/document_store.py rag/test_document_store.py
git commit -m "T-DOC80: persist doc_type + chapter summaries (migration 0004, DocumentStore round-trip)"
```

---

### Task 3: doc_type filtering in both VectorStore adapters

**Files:**
- Modify: `rag/fakes/fake_vector_store.py` (`_passes_filters`)
- Modify: `rag/vector_index.py` (`_qdrant_filter`)
- Test: `rag/fakes/test_fake_vector_store.py`, `rag/test_vector_index.py` (extend; the real adapter's filter-building is unit-testable without Qdrant — follow how existing `_qdrant_filter` tests do it)

**Interfaces:**
- Consumes: `SearchFilters.doc_type`, `VectorPayload["doc_type"]` (Task 1).
- Produces: both adapters honor `doc_type` identically (contract-test symmetry); **legacy points with no `doc_type` payload key count as `"paper"`** in both adapters.

- [ ] **Step 1: Write failing tests:**

```python
# rag/fakes/test_fake_vector_store.py — follow the file's existing upsert/search helpers
def test_doc_type_filter_book_only(...):
    # upsert one payload with doc_type="paper", one with doc_type="book"
    # hybrid_search(filters=SearchFilters(doc_type="book")) returns only the book point

def test_doc_type_filter_none_returns_both(...): ...

def test_legacy_payload_without_doc_type_counts_as_paper(...):
    # upsert a payload dict WITHOUT the doc_type key (pre-T-DOC80 point);
    # filters=SearchFilters(doc_type="paper") must still return it

# rag/test_vector_index.py
def test_qdrant_filter_doc_type_book():
    f = _qdrant_filter(SearchFilters(doc_type="book"))
    # assert a FieldCondition on key="doc_type" with MatchValue("book") in f.must

def test_qdrant_filter_doc_type_paper_includes_legacy_points():
    f = _qdrant_filter(SearchFilters(doc_type="paper"))
    # assert the paper case is a should-group: MatchValue("paper") OR IsEmptyCondition("doc_type")
```

- [ ] **Step 2: Run, verify failures.** `... && pytest rag/fakes/test_fake_vector_store.py rag/test_vector_index.py -v`

- [ ] **Step 3: Implement.**

```python
# fake_vector_store.py — inside _passes_filters, after the kind check:
        if filters.doc_type is not None:
            # .get: points upserted before T-DOC80 carry no doc_type key — they are all papers.
            if payload.get("doc_type", "paper") != filters.doc_type:
                return False

# rag/vector_index.py — inside _qdrant_filter, after the kind clause:
    if filters.doc_type == "book":
        must.append(models.FieldCondition(key="doc_type", match=models.MatchValue(value="book")))
    elif filters.doc_type == "paper":
        # Legacy points (pre-T-DOC80) have no doc_type payload key but are all papers —
        # match either the explicit value or the key's absence, mirroring the fake's .get default.
        must.append(
            models.Filter(
                should=[
                    models.FieldCondition(key="doc_type", match=models.MatchValue(value="paper")),
                    models.IsEmptyCondition(is_empty=models.PayloadField(key="doc_type")),
                ]
            )
        )
```

(Qdrant accepts a nested `models.Filter` inside `must`; if the installed client version rejects it, hold the should-group at the top level of the returned Filter instead — the test asserts semantics, adjust its introspection accordingly.)

- [ ] **Step 4: Run — PASS**: same command. Also `... && pytest rag/fakes/ -q` for regressions.

- [ ] **Step 5: Commit**

```bash
git add rag/fakes/fake_vector_store.py rag/fakes/test_fake_vector_store.py rag/vector_index.py rag/test_vector_index.py
git commit -m "T-DOC80: doc_type filtering in fake + Qdrant adapters (legacy points count as paper)"
```

---

### Task 4: Retriever — chapter-aware summary ids, chapter field, doc_type + local: citations

**Files:**
- Modify: `rag/retriever.py`
- Modify: `rag/mcp_server.py` (its one `Citation(` site in `get_paper`)
- Test: `rag/test_retriever.py`, `rag/test_mcp_server.py` (extend)

**Interfaces:**
- Consumes: `ChapterSummary`, `Citation.doc_type`, `PaperSearchResult.chapter` (Tasks 1–2).
- Produces:
  - `_paper_id_from_summary_hit_id("X:summary:ch3") == "X"` (and `"X:summary" → "X"` unchanged)
  - `source_url(paper_id: str, pdf_url: str) -> str` — module-level in `rag/retriever.py`; arXiv abs URL for arXiv ids, `pdf_url` verbatim for `local:` ids. Both `Citation` sites in retriever + the one in mcp_server use it.
  - `retrieve_papers()` sets `PaperSearchResult.chapter` from the matching `ChapterSummary.title` on chapter hits and `Citation.doc_type`/`view.summary_text` correctly (chapter hits show the chapter's own summary text — which they already do, since `texts[candidate.id]` resolves per-summary-id).

- [ ] **Step 1: Write failing tests** (seed the fakes the way the file's existing tests do):

```python
def test_summary_id_parser_handles_chapter_ids():
    assert _paper_id_from_summary_hit_id("2506.01234:summary") == "2506.01234"
    assert _paper_id_from_summary_hit_id("local:ab12cd34ef56:summary:ch3") == "local:ab12cd34ef56"

def test_source_url_local_vs_arxiv():
    assert source_url("2506.01234", "https://arxiv.org/pdf/2506.01234v1") == "https://arxiv.org/abs/2506.01234"
    assert source_url("local:ab12cd34ef56", "causality-pearl.pdf") == "causality-pearl.pdf"

def test_retrieve_papers_chapter_hit_sets_chapter_and_doc_type(...):
    # Seed: a book PaperRecord with chapter_summaries; upsert its ch1 summary vector into the fake
    # store; retrieve_papers(query) → the hit has chapter == "DAGs" (the ChapterSummary title),
    # view.summary_text == that chapter's text, citation.doc_type == "book".

def test_retrieve_papers_whole_paper_hit_chapter_is_none(...): ...

def test_retrieve_grounded_result_citation_doc_type_book(...):
    # a chunk hit from a book record → citation.doc_type == "book"
```

- [ ] **Step 2: Run, verify failures.** `... && pytest rag/test_retriever.py -v`

- [ ] **Step 3: Implement.**

```python
# rag/retriever.py — replace the parser's body (docstring updated to name both forms):
def _paper_id_from_summary_hit_id(hit_id: str) -> str:
    """... (keep existing rationale; add:) Handles both `{paper_id}:summary` and the book-chapter
    form `{paper_id}:summary:ch{n}` (T-DOC80). Split on the first ':summary' — paper_ids
    (arXiv `2506.01234` or `local:<hex12>`) can never contain that substring."""
    return hit_id.split(_SUMMARY_ID_SUFFIX, 1)[0]

# module-level, near the parser:
def source_url(paper_id: str, pdf_url: str) -> str:
    """Citation URL: local drop-ins have no arXiv page — cite the original filename we recorded
    in `pdf_url` at staging time (app/ingest_local.py) instead of fabricating a dead arXiv link."""
    return pdf_url if paper_id.startswith("local:") else f"https://arxiv.org/abs/{paper_id}"
```

- Both retriever `Citation(...)` sites: `arxiv_url=source_url(<paper_id>, ref.pdf_url)`, add `doc_type=ref.doc_type`. Same in `rag/mcp_server.py`'s `get_paper` (import `source_url` from `rag.retriever` — M8 composes M7, acceptable direction).
- In `retrieve_papers()`'s resolve loop, after `record` resolves:

```python
            chapter = None
            if candidate.id != f"{paper_id}{_SUMMARY_ID_SUFFIX}":
                # chapter hit: find its title on the record (DocumentStore round-trips these)
                cs = next((c for c in record.chapter_summaries if c.summary_id == candidate.id), None)
                chapter = cs.title if cs is not None else None
```

and pass `chapter=chapter` into `PaperSearchResult(...)`.

- [ ] **Step 4: Run — PASS**, plus `... && pytest rag/test_retriever.py rag/test_mcp_server.py -q` and the id-slicing CI check: `... && python ci/checks/id_slicing.py` (or however `ci/` runs it — see `ci/` README/workflow; it must still find the fenced function).

- [ ] **Step 5: Commit**

```bash
git add rag/retriever.py rag/test_retriever.py rag/mcp_server.py rag/test_mcp_server.py
git commit -m "T-DOC80: chapter-aware summary ids, PaperSearchResult.chapter, doc_type + local-source citations"
```

---

### Task 5: Map-reduce book summarizer (`rag/book_summarizer.py`)

**Files:**
- Create: `rag/book_summarizer.py`
- Test: `rag/test_book_summarizer.py` (new; use `rag.fakes.fake_summarizer.FakeSummarizer` — deterministic truncation of `ParsedDoc.markdown`, never raises on non-empty prose)

**Interfaces:**
- Consumes: `ParsedDoc`/`Block` (contracts), any `Summarizer` (`summarize(ParsedDoc) -> str`; both real and fake read `parsed.markdown`), `ChapterSummary` (Task 1).
- Produces: `summarize_book(parsed: ParsedDoc, summarizer) -> tuple[str, list[ChapterSummary]]` — `(book_summary_text, chapter_summaries)`. Book summary = overview + `"\n\nContents:\n"` + numbered chapter titles. Task 6's orchestrator branch calls exactly this.

- [ ] **Step 1: Write failing tests:**

```python
def _block(text, section_path, idx):  # helper: Block with dummy page/bbox per contracts/parser.py
    ...

def _parsed_doc(blocks):  # ParsedDoc with markdown="\n\n".join(b.text ...), empty figures/tables/refs
    ...

def test_splits_on_top_level_section_path():
    blocks = [_block("intro text", "Ch 1 Intro", 0), _block("s1", "Ch 1 Intro > 1.1", 1),
              _block("dags", "Ch 2 DAGs", 2)]
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert [c.title for c in chapters] == ["Ch 1 Intro", "Ch 2 DAGs"]
    assert chapters[0].summary_id.endswith(":summary:ch0")
    assert chapters[1].summary_id.endswith(":summary:ch1")

def test_book_summary_contains_toc():
    text, chapters = summarize_book(...)
    assert "Contents:" in text and "Ch 2 DAGs" in text

def test_flat_doc_falls_back_to_windows():
    # 450 blocks all sharing one section_path → windowed chapters of _FALLBACK_WINDOW_BLOCKS,
    # titles == "" per spec, ids still ch0..chN
    ...
    assert all(c.title == "" for c in chapters) and len(chapters) == 3

def test_oversized_chapter_summarized_in_windows():
    # one chapter whose word count exceeds _MAX_CHAPTER_WORDS → still exactly ONE ChapterSummary
    # for it (windows are internal), text non-empty
    ...

def test_chapter_summaries_are_nonempty_and_single_summary_per_chapter(): ...
```

- [ ] **Step 2: Run, verify failure** (`ModuleNotFoundError: rag.book_summarizer`): `... && pytest rag/test_book_summarizer.py -v`

- [ ] **Step 3: Implement** — full module:

```python
"""Map-reduce summarization for doc_type="book" (T-DOC80, spec:
docs/superpowers/specs/2026-07-25-drop-in-folder-and-books-design.md).

A book's markdown is 10-50x a paper's and cannot go through one `summarize()` call (the real
adapter's num_ctx ceiling truncates it to noise). Instead: split into chapters (top-level
`section_path` groups), summarize each (map), then summarize the chapter summaries into one
overview + table of contents (reduce). Chapter summaries are RETURNED, not discarded — the
orchestrator persists and embeds them as routing units (ARCHITECTURE §M7 search_papers).

Takes any `Summarizer` as an argument (accept-dependencies principle) — the GPU lock, eviction
hooks, retry taxonomy all stay the injected summarizer's concern, unchanged.
"""

from contracts.document_store import ChapterSummary
from contracts.parser import Block, ParsedDoc

# ponytail: fixed thresholds, not adaptive. _MAX_CHAPTER_WORDS stays under the real adapter's
# truncation point (_NUM_CTX_CEILING 16384 tok / 2.2 tok-per-word ≈ 7400 words) so a chapter is
# summarized whole, not silently truncated; retune both together if the ceiling moves.
_MAX_CHAPTER_WORDS = 6000
_FALLBACK_WINDOW_BLOCKS = 150  # flat/scanned books with no usable section structure


def _top_level(section_path: str) -> str:
    return section_path.split(" > ", 1)[0]  # separator per rag/parser.py's section-stack join


def _split_chapters(parsed: ParsedDoc) -> list[tuple[str, list[Block]]]:
    groups: list[tuple[str, list[Block]]] = []
    for block in parsed.blocks:
        top = _top_level(block.section_path)
        if groups and groups[-1][0] == top:
            groups[-1][1].append(block)
        else:
            groups.append((top, [block]))
    if len(groups) <= 1:
        blocks = parsed.blocks
        return [("", list(blocks[i : i + _FALLBACK_WINDOW_BLOCKS]))
                for i in range(0, len(blocks), _FALLBACK_WINDOW_BLOCKS)]
    return groups


def _doc_from_text(parsed: ParsedDoc, text: str) -> ParsedDoc:
    # Both real and fake Summarizer read only `parsed.markdown` (rag/summarizer.py line ~121);
    # blocks/figures/tables ride along untouched for shape-validity.
    return parsed.model_copy(update={"markdown": text})


def _summarize_text(parsed: ParsedDoc, summarizer, text: str) -> str:
    words = text.split()
    if len(words) <= _MAX_CHAPTER_WORDS:
        return summarizer.summarize(_doc_from_text(parsed, text))
    # bounded depth-2 windowing (spec): summarize fixed word-windows, then combine those.
    windows = [" ".join(words[i : i + _MAX_CHAPTER_WORDS])
               for i in range(0, len(words), _MAX_CHAPTER_WORDS)]
    partials = [summarizer.summarize(_doc_from_text(parsed, w)) for w in windows]
    return summarizer.summarize(_doc_from_text(parsed, "\n\n".join(partials)))


def summarize_book(parsed: ParsedDoc, summarizer) -> tuple[str, list[ChapterSummary]]:
    chapters: list[ChapterSummary] = []
    for n, (title, blocks) in enumerate(_split_chapters(parsed)):
        chapter_text = "\n\n".join(b.text for b in blocks)
        text = _summarize_text(parsed, summarizer, chapter_text)
        chapters.append(ChapterSummary(
            summary_id=f"{parsed.paper_id}:summary:ch{n}", title=title, text=text,
        ))
    joined = "\n\n".join(
        f"{c.title}: {c.text}" if c.title else c.text for c in chapters
    )
    overview = _summarize_text(parsed, summarizer, joined)
    toc = "\n".join(f"{n + 1}. {c.title}" for n, c in enumerate(chapters) if c.title)
    summary_text = overview + ("\n\nContents:\n" + toc if toc else "")
    return summary_text, chapters
```

- [ ] **Step 4: Run — PASS.** `... && pytest rag/test_book_summarizer.py -v`

- [ ] **Step 5: Commit**

```bash
git add rag/book_summarizer.py rag/test_book_summarizer.py
git commit -m "T-DOC80: map-reduce book summarizer (chapter split, windowed map, TOC reduce)"
```

---

### Task 6: Orchestrator integration — book branch, chapter embed/upsert, singleton parse batches

**Files:**
- Modify: `rag/orchestrator.py`
- Test: `rag/test_orchestrator.py` (extend; all-fakes pattern per TEST-STRATEGY)

**Interfaces:**
- Consumes: `summarize_book` (Task 5), `CheckpointArtifacts.chapter_summaries` (Task 1), `VectorPayload["doc_type"]` (Task 1).
- Produces: for a `ref.doc_type == "book"`: `_finish` summarizes via map-reduce, checkpoints chapters, embeds `[summary] + [chapters...] + [chunks...]` in ONE `embed()` call, upserts chapter vectors as `kind="summary"` under their `summary_id`s, and `PaperRecord` carries `chapter_summaries`. `parse_phase` puts each book in its own batch. Every upserted payload carries `doc_type`.

- [ ] **Step 1: Write failing tests:**

```python
def test_book_finish_persists_and_upserts_chapters(all_fakes_orchestrator, ...):
    # a book ref whose FakeSource/ParsedDoc fixture has 2 top-level sections; run ingest
    # assert: document_store record has 2 chapter_summaries;
    #         fake vector store contains ids {pid}:summary, {pid}:summary:ch0, ch1 (kind="summary")
    #         all payloads have doc_type == "book"

def test_book_single_embed_call_per_paper(...):
    # FakeEmbedder call-count: exactly 1 embed() for the paper's summary+chapters+chunks
    # (the topic_query_vec hoist is the only other call in the run — N+1 invariant intact)

def test_paper_flow_unchanged_no_chapter_vectors(...):
    # a plain paper → no :summary:ch ids in the store, payload doc_type == "paper"

def test_resume_from_summarized_restores_chapters(...):
    # checkpoint at "summarized" with chapter_summaries artifacts; resume → chapters upserted
    # without re-summarizing (FakeSummarizer call count unchanged after resume)

def test_parse_phase_books_are_singleton_batches(...):
    # parse_batch_size=4, refs = 5 papers + 2 books → parse_batch called with groups
    # [4 papers], [1 paper], [1 book], [1 book] (assert via recording fake parser)
```

- [ ] **Step 2: Run, verify failures.** `... && pytest rag/test_orchestrator.py -v`

- [ ] **Step 3: Implement.**

- `_finish`'s summarize branch:

```python
        if _at_least(stage, "summarized"):
            summary_text = artifacts.summary_text
            chapter_summaries = artifacts.chapter_summaries or []
        else:
            self._on_stage("summarize")
            if ref.doc_type == "book":
                pair = self._summarize_book_with_retry(paper_id, parsed)
                if pair is None:
                    return  # quarantined
                summary_text, chapter_summaries = pair
            else:
                summary_text = self._summarize_with_retry(paper_id, parsed)
                if summary_text is None:
                    return
                chapter_summaries = []
            self._state.checkpoint(paper_id, "summarized", artifacts=CheckpointArtifacts(
                parsed=parsed, chunks=chunks, summary_text=summary_text,
                chapter_summaries=chapter_summaries or None,
            ))
```

`_summarize_book_with_retry` mirrors `_summarize_with_retry`'s exact retry/quarantine shape (TransientError → bounded backoff retry; PermanentError → quarantine at stage "summarized"; returns `None` when quarantined) but calls `summarize_book(parsed, self._summarizer)`. Copy the existing method's structure — do not invent a new error taxonomy.

- The single batched embed call becomes:

```python
        texts = [summary_text] + [cs.text for cs in chapter_summaries] + [c.text for c in chunks]
        embedded = self._embed_with_retry(paper_id, texts)
        ...
        summary_vec = embedded[0]
        chapter_vecs = embedded[1 : 1 + len(chapter_summaries)]
        chunk_vecs = embedded[1 + len(chapter_summaries) :]
```

Same slicing in the `stored`-resume branch (chapters come off `record.chapter_summaries` there).

- `PaperRecord(..., chapter_summaries=chapter_summaries)` at the construction site before `put`.
- `_upsert_record(record, summary_vec, chapter_vecs, chunk_vecs)`: `payload_common` gains `"doc_type": record.ref.doc_type`; after the whole-document summary upsert, loop chapters: `upsert(cs.summary_id, vec, {**payload_common, "kind": "summary", "section_path": cs.title, "text": cs.text})`. Update `_upsert_with_retry`'s signature/passthrough to match (keep `list`, not `Iterable` — same retry-re-iteration reason as its docstring).
- `parse_phase` batching: before the existing grouping loop, partition `refs`:

```python
        # spec: a book is its own parse batch — a 400-page book next to 3 papers in one MinerU
        # call is the memory-pressure case parse_batch_size never budgeted for.
        books = [r for r in refs if r.doc_type == "book"]
        refs = [r for r in refs if r.doc_type != "book"]
```

and append each book as a `[book]` group after the paper groups (adapt to the actual loop shape; the recording-parser test pins the observable behavior).

- [ ] **Step 4: Run — PASS**, then the whole zero-GPU suite: `... && pytest rag/ contracts/ migrations/ -q`

- [ ] **Step 5: Commit**

```bash
git add rag/orchestrator.py rag/test_orchestrator.py
git commit -m "T-DOC80: orchestrator book branch — map-reduce summarize, chapter embed/upsert, singleton book parse batches"
```

---

### Task 7: `app/ingest_local.py` — staging core (id minting, metadata, sidecars, folder moves)

**Files:**
- Create: `app/ingest_local.py`
- Test: `app/test_ingest_local.py` (new; tmp dirs, injected fake fetcher, a `fixtures/golden/*.pdf` as the sample file — zero network)

**Interfaces:**
- Consumes: `PaperRef` (+`doc_type`), `app.prefetch_pdfs._write_sidecar` and `_pdf_path` (reuse — do NOT write a second sidecar serializer; `_cached_ref` must read what we write by construction).
- Produces:
  - `detect_arxiv_id(filename: str, first_page_text: str) -> str | None`
  - `mint_local_ref(pdf_bytes: bytes, filename: str, doc_type: str, mtime: date) -> PaperRef`
  - `stage_file(path: Path, doc_type: str, cache_dir: Path, *, fetch_by_ids) -> str | None` — returns `paper_id` on success (file moved to `done/`), `None` on failure (file moved to `failed/` + `<name>.err`); `fetch_by_ids: Callable[[list[str]], list[PaperRef]]` is injected (real caller passes a wrapper over `ArxivSource().fetch_by_ids`; tests pass a fake).
  - `scan_drop_dir(drop_dir: Path, cache_dir: Path, *, fetch_by_ids) -> list[str]` — stages every `*.pdf` under `papers/` and `books/`, creates the four subfolders if absent, returns staged ids.

- [ ] **Step 1: Write failing tests:**

```python
GOLDEN_PDF = Path("fixtures/golden/2409.01266.pdf")  # any of the committed golden PDFs

def test_detect_arxiv_id_from_filename():
    assert detect_arxiv_id("2409.01266v2.pdf", "") == "2409.01266"

def test_detect_arxiv_id_from_first_page_text():
    assert detect_arxiv_id("pearl-book.pdf", "... arXiv:2409.01266v1 [stat.ME] ...") == "2409.01266"

def test_detect_arxiv_id_none_for_plain_pdf():
    assert detect_arxiv_id("causality-pearl.pdf", "Causality: Models, Reasoning...") is None

def test_mint_local_ref_is_content_addressed_and_deterministic():
    ref1 = mint_local_ref(b"same bytes", "a.pdf", "book", date(2026, 7, 25))
    ref2 = mint_local_ref(b"same bytes", "b.pdf", "book", date(2026, 7, 25))
    assert ref1.paper_id == ref2.paper_id and ref1.paper_id.startswith("local:")
    assert len(ref1.paper_id) == len("local:") + 12
    assert ref1.doc_type == "book" and ref1.pdf_url == "a.pdf"

def test_stage_file_arxiv_path(tmp_path):
    # drop GOLDEN_PDF copy named 2409.01266.pdf into tmp drop dir; fake fetch_by_ids returns a
    # known PaperRef → stage_file writes cache/2409.01266.pdf + .json, moves file to done/,
    # returns "2409.01266"; assert _cached_ref(cache_dir, "2409.01266") reconstructs the ref
    # (round-trip through the REAL reader — the whole point).

def test_stage_file_arxiv_fetch_failure_falls_back_to_local_id(tmp_path):
    # fetch_by_ids raises TransientError → stage_file still succeeds with a local: id (spec:
    # metadata fetch failure must not fail the file)

def test_stage_file_non_arxiv_uses_pdf_meta_or_filename_title(tmp_path): ...

def test_stage_file_corrupt_pdf_goes_to_failed_with_err_file(tmp_path):
    # b"not a pdf" → returns None, file in failed/, sibling .err file non-empty, scan continues

def test_scan_drop_dir_sets_doc_type_by_subfolder(tmp_path):
    # one file in papers/, one in books/ → sidecars' doc_type differ accordingly

def test_restage_same_file_is_idempotent(tmp_path):
    # staging the same bytes twice → same paper_id, second run just overwrites sidecar + moves to done/
```

- [ ] **Step 2: Run, verify failure** (`ModuleNotFoundError: app.ingest_local`).

- [ ] **Step 3: Implement.** Core shapes (module docstring should cite the spec path and T-DOC48 reuse):

```python
_ARXIV_ID = re.compile(r"(?:arXiv[:\s/]*)?\b(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def detect_arxiv_id(filename: str, first_page_text: str) -> str | None:
    for source in (filename, first_page_text):
        m = _ARXIV_ID.search(source)
        if m:
            return m.group(1)
    return None


def _first_page_text(pdf_bytes: bytes) -> str:
    # pypdfium2 (already the repo's PDF-reading dep). Any parse failure → PermanentError,
    # caller quarantines the file to failed/.
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        return pdf[0].get_textpage().get_text_bounded() if len(pdf) else ""
    finally:
        pdf.close()


def _pdf_title_author(pdf_bytes: bytes) -> tuple[str | None, str | None]:
    # best-effort PDF metadata (Title/Author keys); pypdfium2 exposes document metadata via
    # PdfDocument — consult its API (get_metadata_value/get_metadata_dict depending on version);
    # wrap in try/except returning (None, None) — metadata is optional garnish, never a failure.
    ...


def mint_local_ref(pdf_bytes, filename, doc_type, mtime):
    digest = hashlib.sha256(pdf_bytes).hexdigest()[:12]
    title_meta, author_meta = _pdf_title_author(pdf_bytes)
    first_page = _safe_first_page(pdf_bytes)  # "" on extraction failure here; corrupt-PDF check happens earlier
    title = title_meta or _first_nonempty_line(first_page) or Path(filename).stem
    year = _YEAR.search(first_page or "")
    published = date(int(year.group(0)), 1, 1) if year else mtime
    return PaperRef(
        paper_id=f"local:{digest}", version="v1", title=title, abstract="",
        authors=[author_meta] if author_meta else [], categories=[],
        published=published, updated=mtime,
        pdf_url=filename,  # provenance note — source_url() shows this verbatim for local: ids
        doc_type=doc_type,
    )
```

`stage_file`: read bytes → validate PDF opens (corrupt → write `.err` + move to `failed/`, return None) → detect arXiv id → if found, `try: ref = fetch_by_ids([id])[0]` with fallback to `mint_local_ref` on ANY failure or empty result (set `doc_type` on the fetched ref via `ref.model_copy(update={"doc_type": doc_type})`) → write `cache_dir/<paper_id>.pdf` bytes (atomic tmp-rename, same discipline as `_write_sidecar`) → `_write_sidecar(cache_dir, ref)` → move source file to `done/` (collision-safe: append `-1`, `-2` if a same-named file already sits there) → return `paper_id`.

`scan_drop_dir`: `for sub, doc_type in (("papers", "paper"), ("books", "book")):` glob `*.pdf` sorted, `stage_file` each, collect non-None ids; `mkdir(parents=True, exist_ok=True)` the four subfolders first.

- [ ] **Step 4: Run — PASS.** `... && pytest app/test_ingest_local.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/ingest_local.py app/test_ingest_local.py
git commit -m "T-DOC80: ingest_local staging core — arXiv detection, local: id minting, T-DOC48 sidecar reuse"
```

---

### Task 8: `app/ingest_local.py` — CLI + hand-off to `app.ingest`

**Files:**
- Modify: `app/ingest_local.py` (add `main()`)
- Test: `app/test_ingest_local.py` (extend)

**Interfaces:**
- Consumes: `scan_drop_dir` (Task 7), `Config` loader the other `app/` scripts use (see how `app/ingest.py` loads config — same pattern), `Config.drop_in_dir`/`pdf_cache_dir`.
- Produces: `python -m app.ingest_local [--stage-only] [--drop-dir PATH]` — stages everything, writes `drop_in/manifest-<UTC timestamp>.txt` (one paper_id per line, the exact format `app.ingest --paper-ids-file` reads), then unless `--stage-only` runs `subprocess.run([sys.executable, "-m", "app.ingest", "--paper-ids-file", <manifest>], check=False)` and exits with that return code. Nothing staged → log + exit 0 without invoking ingest.

- [ ] **Step 1: Write failing tests:**

```python
def test_main_stage_only_writes_manifest_and_skips_ingest(tmp_path, monkeypatch):
    # monkeypatch subprocess.run to record calls; --stage-only → manifest exists with the staged
    # id, subprocess.run never called

def test_main_invokes_ingest_with_manifest(tmp_path, monkeypatch):
    # recorded argv == [sys.executable, "-m", "app.ingest", "--paper-ids-file", str(manifest)]

def test_main_empty_drop_dir_exits_zero_without_ingest(tmp_path, monkeypatch): ...
```

- [ ] **Step 2: Run, verify failures.**

- [ ] **Step 3: Implement `main()`** — argparse mirroring `app/prefetch_pdfs.py`'s structure (config load, logging setup). The real `fetch_by_ids` wrapper: `lambda ids: _fetch_by_ids_with_backoff(ArxivSource(), ids, sleep=time.sleep)` reusing `app/assembly.py`'s helper (import it — same package, same reason `harvest_refs` uses it: T-DOC49 backoff for free).

- [ ] **Step 4: Run — PASS**, plus `... && pytest app/ -q` for regressions.

- [ ] **Step 5: Commit**

```bash
git add app/ingest_local.py app/test_ingest_local.py
git commit -m "T-DOC80: ingest_local CLI — manifest + app.ingest hand-off"
```

---

### Task 9: MCP tool-description guidance + doc_type passthrough test

**Files:**
- Modify: `rag/mcp_server.py` (docstrings only, plus whatever the MCP tool-registration layer needs so `SearchFilters.doc_type` is accepted from callers — the tools already take `SearchFilters`, so this is likely zero code; prove it with a test)
- Test: `rag/test_mcp_server.py` (extend)

**Interfaces:**
- Consumes: everything upstream.
- Produces: `semantic_search`/`search_papers` docstrings carrying the books-vs-papers routing guidance; a passthrough test pinning `doc_type` filtering end-to-end through the MCP layer.

- [ ] **Step 1: Write failing test:**

```python
def test_semantic_search_doc_type_filter_passthrough(seeded_server):
    # seed one paper chunk + one book chunk (fake stores);
    # semantic_search(query, filters=SearchFilters(doc_type="book")) returns only book passages,
    # each with citation.doc_type == "book"

def test_search_papers_returns_chapter_hits_with_chapter_field(seeded_server): ...

def test_tool_docstrings_carry_routing_guidance():
    assert "books" in McpServer.semantic_search.__doc__ and "doc_type" in McpServer.semantic_search.__doc__
    assert "books" in McpServer.search_papers.__doc__
```

- [ ] **Step 2: Run, verify failures.**

- [ ] **Step 3: Implement.** Append to both docstrings (T-DOC34 precedent — routing lives in tool descriptions, agent-as-reasoner; keep the existing text, add):

> The corpus mixes research **papers** (latest methods/evidence) and **books** (foundational
> definitions/concepts). For conceptual/definitional questions, pass
> `filters={"doc_type": "book"}`; for state-of-the-art or empirical results, prefer
> `{"doc_type": "paper"}` (optionally with `published_after`); when cross-checking a paper's
> claim against textbook grounding, run both and cite each. `search_papers` returns individual
> book **chapters** as routing hits (`chapter` field set) — follow up with `semantic_search`
> for anchored passages.

- [ ] **Step 4: Run — PASS**, then the FULL suite one last time: `... && pytest contracts/ rag/ app/ migrations/ -q`

- [ ] **Step 5: Commit**

```bash
git add rag/mcp_server.py rag/test_mcp_server.py
git commit -m "T-DOC80: MCP books/papers routing guidance + doc_type passthrough tests"
```

---

### Task 10: Documentation sync (DATA-CONTRACTS, ARCHITECTURE, WORK-BREAKDOWN)

**Files:**
- Modify: `DATA-CONTRACTS.md`, `ARCHITECTURE.md`, `WORK-BREAKDOWN.md`

Docs are authoritative in this repo (AGENTS.md: DATA-CONTRACTS wins shape conflicts) — code that drifts from them is a bug, so this task is mandatory, not cosmetic.

- [ ] **Step 1: DATA-CONTRACTS.md** — update in place, matching surrounding style:
  - §IDs table: add `summary_id (chapter)` row — `{paper_id}:summary:ch{index}` — and a `local:{sha256[:12]}` note to the `paper_id` row (drop-in files with no arXiv id; T-DOC80).
  - §M1 `PaperRef`: add the `doc_type` field with its comment.
  - §M5 `PaperRecord`/`ChapterSummary`, DocumentStore getter notes (`get_summary` resolves chapter ids).
  - §M6 `SearchFilters.doc_type` + `VectorPayload.doc_type` (+ the legacy-points-count-as-paper rule).
  - §M7/§M8: `Citation.doc_type`, `PaperSearchResult.chapter`.
  - SQL schema block: `papers.doc_type`, `summaries.title` (migration 0004).
  - §Config: `drop_in_dir`.
- [ ] **Step 2: ARCHITECTURE.md** — M3B: note the book map-reduce path (`rag/book_summarizer.py`, chapters persisted+embedded as routing units); M9: book singleton parse batches; "Operational tooling" list: add `app/ingest_local.py` (one bullet, same style as `build_corpus`).
- [ ] **Step 3: WORK-BREAKDOWN.md** — add the T-DOC80 entry to the T-DOC series (implemented; spec + plan paths; one-line scope).
- [ ] **Step 4: Self-check** — grep the three docs for the exact names used in code (`doc_type`, `ChapterSummary`, `chapter_summaries`, `drop_in_dir`, `:summary:ch`) to confirm no naming drift.
- [ ] **Step 5: Commit**

```bash
git add DATA-CONTRACTS.md ARCHITECTURE.md WORK-BREAKDOWN.md
git commit -m "T-DOC80: doc sync — drop-in folder + book ingestion contracts and module notes"
```

---

## Post-plan verification (operator, not CI)

Not part of any task's DoD — real-hardware checks for after the PR lands, run by the human:
1. Drop one real arXiv PDF + one real non-arXiv paper into `drop_in/papers/`, a real book into `drop_in/books/`; run `python -m app.ingest_local`; confirm all three reach `done` in `ingest_state` and `search_papers`/`semantic_search` return them (with `doc_type`/`chapter` labels).
2. Watch `nvidia-smi` during the book's Pass 1 — the spec's open risk (MinerU on a 400-page book) has no unit-test proxy; if it OOMs, the spec's fallback is pre-splitting by page range (not built).
