# T-DOC84 / T-DOC85 / T-DOC86 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make document deletion complete and operator-reachable (T-DOC84), give size-merged book chapters titles that actually name their content (T-DOC85), and let an operator see what a drop-in file is before spending GPU hours on it (T-DOC86) — then re-ingest all five books once, correctly.

**Architecture:** Three independent fixes plus one operational rollout. T-DOC84 adds a `forget()` seam to the ingest-state adapter and calls it from the existing `delete_paper()` cross-store coordinator, then exposes deletion as a CLI. T-DOC85 replaces "title = first heading" with a deterministic heading scorer, falling back to a fourth summarizer `kind` only when a merged unit contains no usable heading at all. T-DOC86 adds a `--dry-run` to the existing drop-in CLI. Nothing here changes the paper ingest path.

**Tech Stack:** Python 3.11, SQLite (source of truth), Qdrant (derived index), Ollama (summarizer), pytest. Tests are colocated (`rag/test_*.py`, `app/test_*.py`).

## Global Constraints

- **Conda env:** every test command runs inside `agent-rag-research`. Chain it in ONE shell call: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && pytest ...`
- **Zero-GPU / zero-network unit tests** (TEST-STRATEGY.md). No test in this plan may call a real model, a real Qdrant, or the network. Use the existing fakes.
- **No AI attribution** in any commit message, PR body, or issue — no `Co-authored-by: Claude`, no `Claude-Session:` trailer, no "🤖 Generated with Claude Code" line.
- **Never `git stash`** (shared stash stack across worktrees). Use `git show HEAD:<path>` or `git diff`.
- **Never merge the PR**, never use `--admin` or a branch-protection bypass. The human operator merges.
- **Foundation freeze (CODEOWNERS):** `/contracts/`, `/rag/config.py`, `/config.yaml`, `/migrations/`, `/rag/fakes/`, `/fixtures/`, `/ci/`, `/.github/`. **Task 1 touches `rag/fakes/fake_ingest_state.py`** and therefore needs the foundation label on the PR — CI check (i) `foundation_label.py` fails without it.
- **CI enforcement checks that bite here:** (a) vendor isolation — `rag/` and `app/` must not import the vector-store vendor outside `rag/vector_index.py`; (b) no blind `except:`/`except Exception:` without re-raise or a typed error; (f) GPU-adapter naming; (h) `app/` reads config only through `rag/config.load_config`, never `os.environ` directly. Run `python -m ci.run_enforcement` before every commit.
- **No new dependencies.** Everything here is stdlib plus what is already installed.
- **Ordering rationale in `delete_paper` is load-bearing** — read its existing docstring (`rag/orchestrator.py:210-236`) before editing; the SQLite-then-vectors sequence is deliberate and documented, and Task 2 appends to it rather than reordering it.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `rag/ingest_state_sqlite.py` | Add `forget()`; refactor `quarantine()` to call it | 1 |
| `rag/fakes/fake_ingest_state.py` | Mirror `forget()` so zero-GPU tests can assert it | 1 |
| `rag/test_ingest_state_sqlite.py` | `forget()` behavior against real SQLite | 1 |
| `rag/orchestrator.py` | `delete_paper()` calls `state.forget()` last | 2 |
| `rag/test_orchestrator.py` | Extend the four existing `delete_paper` tests | 2 |
| `app/delete_docs.py` | **New.** Operator CLI for deletion | 3 |
| `app/test_delete_docs.py` | **New.** CLI arg handling + orchestrator wiring | 3 |
| `app/corpus_integrity.py` | LEFT JOIN so the papers-row-missing shape is visible | 4 |
| `app/test_corpus_integrity.py` | Regression pin for the orphan shape T-DOC84 creates | 4 |
| `rag/book_summarizer.py` | Heading scorer; title fallback wiring | 5, 6 |
| `rag/test_book_summarizer.py` | Scorer + fallback tests | 5, 6 |
| `rag/summarizer.py` | `kind="book_title"` + `_BOOK_TITLE_PROMPT` | 6 |
| `rag/test_summarizer.py` | Prompt selection for the new kind | 6 |
| `app/ingest_local.py` | `--dry-run` flag | 7 |
| `app/test_ingest_local.py` | Dry-run stages nothing | 7 |

**Branch:** `fix/t-doc84-86-delete-titles-dropin` off current `main`. One PR for Tasks 1-7. Task 8 is operational and lands after the merge.

---

## Task 1: `forget()` on the ingest-state adapter

The two DELETE statements already exist at `rag/ingest_state_sqlite.py:184-185`, buried inside `quarantine()`. Lift them into a public method so `delete_paper` has something to call, and have `quarantine()` use it so there is exactly one place that knows which tables hold ingest state.

**Files:**
- Modify: `rag/ingest_state_sqlite.py` (add `forget`; edit `_quarantine`'s inner function at ~184-185)
- Modify: `rag/fakes/fake_ingest_state.py` (**foundation-frozen — PR needs the foundation label**)
- Test: `rag/test_ingest_state_sqlite.py`

**Interfaces:**
- Produces: `SqliteIngestState.forget(paper_id: str) -> None` and `FakeIngestState.forget(paper_id: str) -> None`. Idempotent — forgetting an unknown id is a no-op, not an error. Task 2 consumes this.

- [ ] **Step 1: Write the failing test**

Add to `rag/test_ingest_state_sqlite.py`. Match the file's existing fixture style for building a temp DB — read the top of the file first and reuse whatever helper it already has rather than inventing a new one.

```python
def test_forget_removes_both_state_and_checkpoint_rows(tmp_path):
    state = _state(tmp_path)  # use this file's existing constructor helper
    state.checkpoint("2401.00001", "parsed", CheckpointArtifacts())
    assert state.stage_of("2401.00001") == "parsed"

    state.forget("2401.00001")

    assert state.stage_of("2401.00001") is None
    assert state.get("2401.00001") is None


def test_forget_is_idempotent_and_scoped_to_one_id(tmp_path):
    state = _state(tmp_path)
    state.checkpoint("2401.00001", "parsed", CheckpointArtifacts())
    state.checkpoint("2401.00002", "parsed", CheckpointArtifacts())

    state.forget("2401.00001")
    state.forget("2401.00001")  # second call must not raise

    assert state.stage_of("2401.00001") is None
    assert state.stage_of("2401.00002") == "parsed"


def test_quarantine_still_clears_state_after_the_refactor(tmp_path):
    # Pins the behavior Task 1 refactors THROUGH forget(): quarantine has always removed the
    # ingest_state/ingest_checkpoint rows as part of dead-lettering, and must keep doing so.
    state = _state(tmp_path)
    state.checkpoint("2401.00001", "parsed", CheckpointArtifacts())

    state.quarantine("2401.00001", "parsed", PermanentError("boom"))

    assert state.stage_of("2401.00001") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest rag/test_ingest_state_sqlite.py -v -k "forget or quarantine_still"
```

Expected: the two `forget` tests FAIL with `AttributeError: 'SqliteIngestState' object has no attribute 'forget'`. The third test PASSES already (it pins existing behavior) — that is correct and expected.

- [ ] **Step 3: Implement `forget()`**

Add to `SqliteIngestState`, placed after `quarantine()` and before `stage_of()`:

```python
    def forget(self, paper_id: str) -> None:
        """Drops `paper_id`'s ingest-state rows so a later ingest treats it as never-seen.

        T-DOC84: `IngestionOrchestrator.delete_paper()` removes a document's `papers`/`chunks`/
        `summaries` rows and its vectors, but a leftover `ingest_state.stage = 'done'` row makes a
        re-ingest of the same id a silent no-op -- the resume logic sees `done` and skips every
        stage, so the document never comes back and nothing raises. This is the missing third
        delete. Idempotent by construction (DELETE of a nonexistent row affects 0 rows), so it is
        safe to call on an id that was never ingested and safe to re-run after a partial failure.
        """

        def _forget(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM ingest_state WHERE paper_id = ?", (paper_id,))
            conn.execute("DELETE FROM ingest_checkpoint WHERE paper_id = ?", (paper_id,))

        self._with_connection(_forget)
```

Then in `_quarantine`'s inner function, replace the two DELETE statements at ~184-185 with a call to the same two statements via a shared private helper. **Do not call `self.forget()` from inside `_quarantine`** — `_quarantine` already runs inside `_with_connection`, and nesting a second connection acquisition inside an open transaction risks a lock. Extract instead:

```python
def _delete_state_rows(conn: sqlite3.Connection, paper_id: str) -> None:
    """The two statements that constitute "this paper has no ingest state" -- one definition,
    used by both `forget()` (T-DOC84) and `quarantine()` (which has always cleared these rows as
    part of dead-lettering). Module-level and connection-taking so `quarantine()` can call it
    inside its own already-open transaction."""
    conn.execute("DELETE FROM ingest_state WHERE paper_id = ?", (paper_id,))
    conn.execute("DELETE FROM ingest_checkpoint WHERE paper_id = ?", (paper_id,))
```

`forget`'s `_forget` body becomes `_delete_state_rows(conn, paper_id)`, and `_quarantine`'s two lines become the same call.

- [ ] **Step 4: Mirror on the fake**

`rag/fakes/fake_ingest_state.py` — read the class first (`~line 29`, in-memory dicts). Add, matching the real adapter's docstring intent in one line:

```python
    def forget(self, paper_id: str) -> None:
        """T-DOC84: mirrors SqliteIngestState.forget -- drops this id's state so a re-ingest
        treats it as never-seen. Idempotent."""
        self._checkpoints.pop(paper_id, None)
```

Use whatever the fake's actual attribute names are — read the `__init__` at line 37 rather than trusting `_checkpoints`. If the fake tracks stage and artifacts in separate dicts, clear both.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest rag/test_ingest_state_sqlite.py -v
```

Expected: all PASS, including every pre-existing test in the file (the `quarantine()` refactor must not change its behavior).

- [ ] **Step 6: Run enforcement and commit**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m ci.run_enforcement && \
  git add rag/ingest_state_sqlite.py rag/fakes/fake_ingest_state.py rag/test_ingest_state_sqlite.py && \
  git commit -m "T-DOC84: add IngestState.forget(), the missing third delete"
```

---

## Task 2: `delete_paper()` clears ingest state

**Files:**
- Modify: `rag/orchestrator.py:210-236` (`delete_paper`)
- Test: `rag/test_orchestrator.py:1231-1275` (four existing `delete_paper` tests)

**Interfaces:**
- Consumes: `state.forget(paper_id)` from Task 1.

- [ ] **Step 1: Write the failing test**

Append to `rag/test_orchestrator.py` in the existing `delete_paper` block (after line ~1275). Read `test_delete_paper_removes_the_paper_from_both_stores` at line 1240 first and reuse its exact fixture setup.

```python
def test_delete_paper_clears_ingest_state_so_a_reingest_is_not_a_no_op():
    # T-DOC84 regression pin. The live failure: deleting local:f0929288d4f3 dropped its papers/
    # chunks/summaries rows and its vectors, but left ingest_state.stage='done' -- so the
    # re-ingest skipped every stage and the book stayed permanently missing, with no error.
    orch, stores = _orchestrator_with_two_papers()  # use this file's existing helper
    stores.state.checkpoint(FIRST_ID, "done", CheckpointArtifacts())
    assert stores.state.stage_of(FIRST_ID) == "done"

    orch.delete_paper(FIRST_ID)

    assert stores.state.stage_of(FIRST_ID) is None


def test_delete_paper_does_not_clear_other_papers_ingest_state():
    orch, stores = _orchestrator_with_two_papers()
    stores.state.checkpoint(FIRST_ID, "done", CheckpointArtifacts())
    stores.state.checkpoint(SECOND_ID, "done", CheckpointArtifacts())

    orch.delete_paper(FIRST_ID)

    assert stores.state.stage_of(SECOND_ID) == "done"
```

The helper name `_orchestrator_with_two_papers` is illustrative — use whatever the existing tests at 1240-1274 actually use, and reach the state adapter however those tests reach the document store.

- [ ] **Step 2: Run to verify it fails**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest rag/test_orchestrator.py -v -k "delete_paper"
```

Expected: the two new tests FAIL (`assert 'done' is None`); the four existing ones PASS.

- [ ] **Step 3: Implement**

In `rag/orchestrator.py`, `delete_paper`'s body becomes:

```python
        vector_ids = self._document_store.delete(paper_id)
        self._vector_index.delete(vector_ids)
        self._state.forget(paper_id)
```

Extend the existing docstring's ordering-rationale comment block (do not replace it) with:

```python
        # T-DOC84: ingest state is cleared LAST, deliberately, for the same reason the two store
        # deletes are ordered as they are. If the process dies before `forget()`, the leftover
        # state row describes a document whose rows and vectors are already gone -- an operator
        # re-running `delete_paper(paper_id)` fixes it, and the corpus-integrity check (widened in
        # T-DOC84 to a LEFT JOIN) reports it. Clearing state FIRST would invert that: a crash
        # would leave a document that ingest believes is unstarted but whose rows are still
        # present, and the next ingest would re-`put()` over live rows.
```

- [ ] **Step 4: Run to verify it passes**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest rag/test_orchestrator.py -v -k "delete_paper"
```

Expected: all six PASS.

- [ ] **Step 5: Commit**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m ci.run_enforcement && \
  git add rag/orchestrator.py rag/test_orchestrator.py && \
  git commit -m "T-DOC84: delete_paper() clears ingest state so re-ingest actually re-ingests"
```

---

## Task 3: `app/delete_docs.py` operator CLI

Deletion currently has zero non-test callers. Every deletion is throwaway Python plus hand-written SQL — which is exactly how the Task 2 trap got hit in the first place.

**Files:**
- Create: `app/delete_docs.py`
- Create: `app/test_delete_docs.py`

**Interfaces:**
- Consumes: `build_ingestion_orchestrator(cfg)` from `app/assembly.py:471`; `orchestrator.delete_paper` as fixed in Task 2.
- Produces: `main(argv: list[str] | None = None) -> int` — 0 on success, 1 on refusal.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for app/delete_docs.py -- zero-GPU, zero-network (TEST-STRATEGY)."""

import pytest

from app.delete_docs import _parse_args, main


class _RecordingOrchestrator:
    def __init__(self):
        self.deleted: list[str] = []

    def delete_paper(self, paper_id: str) -> None:
        self.deleted.append(paper_id)


def test_parse_args_takes_one_or_more_paper_ids():
    args = _parse_args(["2401.00001", "local:f0929288d4f3"])
    assert args.paper_ids == ["2401.00001", "local:f0929288d4f3"]


def test_parse_args_requires_at_least_one_id():
    with pytest.raises(SystemExit):
        _parse_args([])


def test_main_deletes_every_id_in_order(monkeypatch):
    orch = _RecordingOrchestrator()
    monkeypatch.setattr("app.delete_docs._build", lambda: orch)

    rc = main(["--yes", "2401.00001", "local:f0929288d4f3"])

    assert rc == 0
    assert orch.deleted == ["2401.00001", "local:f0929288d4f3"]


def test_main_without_yes_refuses_and_deletes_nothing(monkeypatch):
    # Deletion is irreversible and there is no undo -- an unattended run must not proceed.
    orch = _RecordingOrchestrator()
    monkeypatch.setattr("app.delete_docs._build", lambda: orch)

    rc = main(["2401.00001"])

    assert rc == 1
    assert orch.deleted == []
```

- [ ] **Step 2: Run to verify it fails**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest app/test_delete_docs.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.delete_docs'`.

- [ ] **Step 3: Implement**

```python
"""Operator CLI: delete one or more documents from the corpus, completely.

T-DOC84. Before this existed, deletion was reachable only from Python -- `delete_paper` had zero
non-test callers -- so every real deletion was an ad-hoc script plus hand-written SQL. That is
how the stale-`ingest_state` trap got hit during the T-DOC82 rollout: an ad-hoc script has no
reason to know a third table is involved. This module is the one supported way to remove a
document, and it goes through `IngestionOrchestrator.delete_paper`, which owns all three deletes
(SQLite rows, vectors, ingest state).

Deletion is irreversible -- there is no undo and no tombstone. `--yes` is required.

    python -m app.delete_docs --yes local:f0929288d4f3
"""

import argparse
import logging

from app.assembly import build_ingestion_orchestrator
from rag.config import load_config

logger = logging.getLogger(__name__)


def _build():
    # Indirection exists so tests can substitute a recording double without standing up the real
    # assembly (which would need a live Qdrant). Same seam app/test_ingest.py already uses.
    return build_ingestion_orchestrator(load_config())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper_ids", nargs="+", metavar="PAPER_ID",
                        help="One or more paper_ids to delete (e.g. 2401.00001, local:abc123)")
    parser.add_argument("--yes", action="store_true",
                        help="Required. Confirms the deletion is intended -- it cannot be undone.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)
    if not args.yes:
        logger.error(
            "delete_docs: refusing to delete %d document(s) without --yes. Deletion removes the "
            "SQLite rows, the vectors, and the ingest state, and cannot be undone. Ids: %s",
            len(args.paper_ids), ", ".join(args.paper_ids),
        )
        return 1
    orchestrator = _build()
    for paper_id in args.paper_ids:
        orchestrator.delete_paper(paper_id)
        logger.info("delete_docs: deleted %s (rows, vectors, ingest state)", paper_id)
    logger.info("delete_docs: %d document(s) deleted", len(args.paper_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Confirm `build_ingestion_orchestrator`'s real signature at `app/assembly.py:471` before writing `_build` — if it takes more than `cfg`, match it.

- [ ] **Step 4: Run to verify it passes**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest app/test_delete_docs.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m ci.run_enforcement && \
  git add app/delete_docs.py app/test_delete_docs.py && \
  git commit -m "T-DOC84: add app/delete_docs.py so deletion has an operator entrypoint"
```

---

## Task 4: `corpus_integrity` can see the orphan `delete_paper` creates

`app/corpus_integrity.py:32` inner-joins `papers`, so a `done` state row whose `papers` row is gone is dropped from the result set — the one shape `delete_paper` produces is the one shape the checker structurally cannot report.

**Files:**
- Modify: `app/corpus_integrity.py` (`_QUERY` at ~28-38, `IntegrityOffender`, `find_done_papers_without_chunks`)
- Test: `app/test_corpus_integrity.py`

- [ ] **Step 1: Write the failing test**

```python
def test_done_state_row_with_no_papers_row_is_reported(conn):
    # T-DOC84: this is the orphan shape delete_paper() creates -- state says 'done', every other
    # row is gone. The original INNER JOIN on papers dropped it from the result set entirely.
    conn.execute("INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, 'done', 0)",
                 ("local:f0929288d4f3",))

    offenders = find_done_papers_without_chunks(conn)

    assert [o.paper_id for o in offenders] == ["local:f0929288d4f3"]
    assert offenders[0].chunk_count == 0
    assert offenders[0].block_count == 0
```

Use this file's existing `conn` fixture and its existing row-insertion helpers — read the file first; do not hand-roll schema DDL in the test.

- [ ] **Step 2: Run to verify it fails**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest app/test_corpus_integrity.py -v
```

Expected: the new test FAILS with `assert [] == ['local:f0929288d4f3']`. All existing tests PASS.

- [ ] **Step 3: Implement**

Change `_QUERY`'s `JOIN` to `LEFT JOIN` and select the id from `ingest_state` rather than `papers`, so a missing `papers` row still yields a row:

```python
_QUERY = """
SELECT s.paper_id,
       (SELECT count(*) FROM chunks c WHERE c.paper_id = s.paper_id) AS chunk_count,
       (SELECT count(*) FROM blocks b WHERE b.paper_id = s.paper_id) AS block_count
FROM ingest_state s
LEFT JOIN papers p ON p.paper_id = s.paper_id
WHERE s.stage = 'done' AND (chunk_count = 0 OR block_count = 0)
ORDER BY s.paper_id
"""
```

Extend `find_done_papers_without_chunks`'s docstring:

```python
    """Every `ingest_state='done'` paper with zero `chunks` rows and/or zero `blocks` rows --
    silently unretrievable despite looking fully ingested. Empty list means the corpus is clean.

    T-DOC84 widened the join to a LEFT JOIN: a `done` state row whose `papers` row is also gone is
    the exact orphan `IngestionOrchestrator.delete_paper()` used to leave behind, and the original
    INNER JOIN dropped it from the result set -- the checker could not see the shape it most
    needed to catch. Both shapes now report: paper-present-chunks-missing (T-DOC23/T-DOC35) and
    everything-gone-but-state (T-DOC84).
    """
```

Note the `p` alias is now unused by the SELECT list — keep the LEFT JOIN anyway only if a later
column needs it; if nothing references `p`, drop the join entirely and query `ingest_state` alone.
Prefer dropping it: fewer moving parts, identical results.

- [ ] **Step 4: Run to verify it passes**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest app/test_corpus_integrity.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m ci.run_enforcement && \
  git add app/corpus_integrity.py app/test_corpus_integrity.py && \
  git commit -m "T-DOC84: corpus_integrity reports done-state rows whose paper row is gone"
```

---

## Task 5: score headings instead of taking the first

`_merge_to_target` titles each unit by its first heading group. On the verified re-ingest that produced `Assign`, `See Also`, `F`, and `\* and : Operators` alongside the good titles. Each merged unit contains roughly ten heading groups — so the fix is to pick the best of them, not to invent one.

**Files:**
- Modify: `rag/book_summarizer.py`
- Test: `rag/test_book_summarizer.py`

**Interfaces:**
- Produces: `_title_score(heading: str) -> int` and `_best_heading(headings: list[str]) -> str` (returns `""` when nothing scores above the floor — Task 6 consumes that empty return as its fallback trigger).
- `_merge_to_target` keeps its existing signature and return type; only the title it chooses changes.

- [ ] **Step 1: Write the failing test**

```python
from rag.book_summarizer import _best_heading, _merge_to_target, _title_score


def test_title_score_rejects_single_characters_and_short_fragments():
    assert _title_score("F") == 0
    assert _title_score("") == 0
    assert _title_score("A.") == 0


def test_title_score_prefers_longer_content_words():
    # "See Also" and "Regularized Regression" both have two words -- scoring by total content
    # characters, not word count, is what separates them.
    assert _title_score("Regularized Regression") > _title_score("See Also")
    assert _title_score("Canonical Difference-in-Differences") > _title_score("Assign")


def test_title_score_rejects_punctuation_heavy_headings():
    # Observed live: "\\* and : Operators" was a chapter title.
    assert _title_score("\\* and : Operators") == 0


def test_title_score_rejects_headings_long_enough_to_be_a_misparsed_paragraph():
    assert _title_score("word " * 40) == 0


def test_best_heading_picks_the_highest_scoring_not_the_first():
    headings = ["See Also", "Regularized Regression", "F"]
    assert _best_heading(headings) == "Regularized Regression"


def test_best_heading_breaks_ties_toward_the_earliest():
    headings = ["Neutral Controls", "Optimal Switchback"]
    assert _best_heading(headings) in headings  # both plausible; assert determinism below
    assert _best_heading(headings) == _best_heading(headings)


def test_best_heading_returns_empty_when_nothing_is_usable():
    assert _best_heading(["F", "", "A."]) == ""


def test_merge_to_target_titles_a_unit_by_its_best_heading(make_groups):
    # Regression pin for T-DOC85: the unit's FIRST heading is junk, a later one is real. Before
    # the fix this unit was titled "See Also".
    groups = make_groups([
        ("See Also", 100),
        ("Regularized Regression", 2000),
        ("F", 100),
    ])
    units = _merge_to_target(groups)
    assert [title for title, _ in units] == ["Regularized Regression"]
```

`make_groups` is a fixture you add to this file: it takes `list[tuple[str, int]]` of `(heading, word_count)` and returns the `list[tuple[str, list[Block]]]` shape `_merge_to_target` consumes, building `Block`s with the right number of whitespace-separated words. Read the file's existing block-construction helper first — if one exists, extend it rather than adding a second.

- [ ] **Step 2: Run to verify it fails**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest rag/test_book_summarizer.py -v -k "title_score or best_heading or best_heading or merge_to_target_titles"
```

Expected: FAIL with `ImportError: cannot import name '_title_score'`.

- [ ] **Step 3: Implement**

Add to `rag/book_summarizer.py`, after the existing threshold constants:

```python
# T-DOC85: `_merge_to_target` used to title each unit by its FIRST heading group, which is
# arbitrary with respect to the unit's content -- the verified re-ingest of a 144k-word book
# produced "Assign", "See Also", "F", and "\* and : Operators" as chapter titles, and those
# strings are what `search_papers` returns as the routing label an agent picks a chapter by. A
# merged unit contains ~10 heading groups, so the fix is to rank them, not to invent a title.
# Deliberately structural, with no word blocklist: the T-DOC82 spec rejected a front-matter
# blocklist because heading names vary per publisher and the list would be endless. Scoring by
# total content characters (not word count) is what ranks "Regularized Regression" over
# "See Also" -- both are two words.
_MIN_TITLE_SCORE = 8  # "See Also" scores 7 and is rejected outright when nothing better exists
_MAX_TITLE_CHARS = 80  # longer than this is a misparsed paragraph, not a heading
_MAX_TITLE_PUNCT_SHARE = 0.15
_TITLE_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")


def _title_score(heading: str) -> int:
    """Total content characters in a heading, or 0 if it is unusable as a routing label.

    0 means "do not use this" -- callers treat it as a hard reject, not a low rank.
    """
    text = heading.strip()
    if not text or len(text) > _MAX_TITLE_CHARS:
        return 0
    punct = sum(1 for c in text if not c.isalnum() and not c.isspace())
    if punct / len(text) > _MAX_TITLE_PUNCT_SHARE:
        return 0
    score = sum(len(m.group()) for m in _TITLE_WORD.finditer(text))
    return score if score >= _MIN_TITLE_SCORE else 0


def _best_heading(headings: list[str]) -> str:
    """The highest-scoring usable heading, earliest on a tie; "" when none is usable."""
    best, best_score = "", 0
    for heading in headings:
        score = _title_score(heading)
        if score > best_score:
            best, best_score = heading.strip(), score
    return best
```

`re` is already imported at the top of the module.

Then change `_merge_to_target` to accumulate each unit's headings and title it at the end. The current loop appends `(title, list(blocks))` and extends `units[-1][1]`; it needs a parallel list of the headings that went into each unit:

```python
def _merge_to_target(groups: list[tuple[str, list[Block]]]) -> list[tuple[str, list[Block]]]:
    """Strategy B: accumulate consecutive heading groups until ~_TARGET_CHAPTER_WORDS.

    T-DOC85: the unit's title is the best-scoring of ALL headings merged into it (`_best_heading`),
    not the first one -- see that function. Still independent of any particular book's formatting,
    which is why B remains the safe general path.
    """
    units: list[list[Block]] = []
    headings: list[list[str]] = []
    for title, blocks in groups:
        if units and _words(units[-1]) < _TARGET_CHAPTER_WORDS:
            units[-1].extend(blocks)
            headings[-1].append(title)
        else:
            units.append(list(blocks))
            headings.append([title])
    if len(units) > 1 and _words(units[-1]) < _TARGET_CHAPTER_WORDS // 2:
        tail = units.pop()
        units[-1].extend(tail)
        headings[-1].extend(headings.pop())
    return [(_best_heading(h), blocks) for h, blocks in zip(headings, units)]
```

- [ ] **Step 4: Run the whole file to verify nothing else broke**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest rag/test_book_summarizer.py -v
```

Expected: all PASS. **If a pre-existing strategy-B test asserts a specific first-heading title, it encodes the bug** — update it and note in the commit message that the assertion changed and why.

- [ ] **Step 5: Verify the thresholds are not tautological**

The scorer's constants must be load-bearing. Temporarily set `_MIN_TITLE_SCORE = 0` and confirm `test_best_heading_returns_empty_when_nothing_is_usable` FAILS; set `_MAX_TITLE_PUNCT_SHARE = 1.0` and confirm the punctuation test FAILS. Restore both. If either test still passes with the constant neutered, it is asserting nothing — rewrite it against fixed literals.

- [ ] **Step 6: Commit**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m ci.run_enforcement && \
  git add rag/book_summarizer.py rag/test_book_summarizer.py && \
  git commit -m "T-DOC85: title a merged chapter by its best heading, not its first"
```

---

## Task 6: LLM title fallback when a unit has no usable heading

Task 5 handles the common case. A unit whose headings are *all* junk still gets `""`. Fill that gap with a fourth summarizer `kind`, called on the chapter's own already-computed summary — short input, one cheap call, and the title stays anchored to text the grounding-constrained prompt already produced.

Deliberately **not** parsing a title line out of the existing `kind="book"` response: that would change the prompt for every unit including the ones with good headings, require parsing that can fail into the summary body, and put a generated string where an extracted one was fine.

**Files:**
- Modify: `rag/summarizer.py` (`_BOOK_TITLE_PROMPT`, `_PROMPTS`)
- Modify: `rag/book_summarizer.py` (`summarize_book`)
- Test: `rag/test_summarizer.py`, `rag/test_book_summarizer.py`

**Interfaces:**
- Consumes: `_best_heading` returning `""` (Task 5).
- Produces: `kind="book_title"` accepted by `Summarizer.summarize`.

- [ ] **Step 1: Write the failing tests**

In `rag/test_summarizer.py`, alongside the existing `kind`-selection tests (which use a fake HTTP client capturing the request body — reuse that exact harness):

```python
def test_book_title_kind_sends_its_own_prompt(fake_http):
    summarizer = _summarizer(fake_http)
    summarizer.summarize(_parsed("some chapter summary text"), kind="book_title")
    sent = fake_http.last_request_body()
    assert "short title" in sent
    assert "4-6 sentences" not in sent  # not a summary prompt


def test_unknown_kind_still_raises(fake_http):
    with pytest.raises(ValueError):
        _summarizer(fake_http).summarize(_parsed("x"), kind="chapter")
```

In `rag/test_book_summarizer.py`:

```python
def test_unit_with_no_usable_heading_gets_an_llm_title(make_groups):
    summarizer = _KindRecorder()  # existing helper in this file
    parsed = _parsed_from_groups(make_groups([("F", 3000), ("A.", 3000)]))

    _, chapters = summarize_book(parsed, summarizer)

    assert "book_title" in summarizer.kinds
    assert chapters[0].title != ""


def test_unit_with_a_usable_heading_makes_no_title_call(make_groups):
    # The fallback must stay a fallback -- a book with good headings pays nothing for it.
    summarizer = _KindRecorder()
    parsed = _parsed_from_groups(make_groups([("Regularized Regression", 3000)]))

    summarize_book(parsed, summarizer)

    assert "book_title" not in summarizer.kinds
```

Reuse the existing `_KindRecorder` from the T-DOC82 work — do **not** name any new test double with a `*Summarizer`/`*Adapter` suffix, which trips CI check (f)'s GPU-adapter naming pattern.

- [ ] **Step 2: Run to verify they fail**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest rag/test_summarizer.py rag/test_book_summarizer.py -v -k "title"
```

Expected: FAIL — `ValueError: unknown summarize kind 'book_title'`.

- [ ] **Step 3: Add the prompt**

In `rag/summarizer.py`, after `_BOOK_OVERVIEW_PROMPT`:

```python
# T-DOC85: used only when a merged book unit contains no heading usable as a routing label
# (rag/book_summarizer.py::_best_heading returned ""). Input is that unit's own already-grounded
# section summary, not the raw chapter -- short, cheap, and anchored to text the anti-fabrication
# prompt above already produced. Extractive wording is demanded for the same reason the section
# prompt forbids invented numbers: this string is what an agent picks a chapter by.
_BOOK_TITLE_PROMPT = (
    "Write a short title, at most eight words, naming what this book section covers. Use only "
    "wording that appears in the text below. Output the title alone -- no quotation marks, no "
    "punctuation at the end, no explanation.\n\n{paper}"
)
```

Add `"book_title": _BOOK_TITLE_PROMPT` to `_PROMPTS`.

- [ ] **Step 4: Wire the fallback**

In `rag/book_summarizer.py`, `summarize_book`'s loop becomes:

```python
    for n, (title, blocks) in enumerate(_split_chapters(parsed)):
        chapter_text = "\n\n".join(b.text for b in blocks)
        text = _summarize_text(parsed, summarizer, chapter_text, "book")
        if not title:
            # T-DOC85: no heading in this unit was usable as a routing label. Title from the
            # summary we just computed -- short input, one call, and it inherits that summary's
            # grounding rather than the raw chapter's noise. Whitespace-collapsed because the
            # model occasionally returns a trailing newline.
            title = " ".join(
                summarizer.summarize(_doc_from_text(parsed, text), kind="book_title").split()
            )
```

Leave the rest of the loop unchanged.

Note this only fires for `_merge_to_target` units and the structureless-fallback windows. Strategy-A
units always carry a real marker heading, so they never reach it.

- [ ] **Step 5: Run to verify they pass**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest rag/test_summarizer.py rag/test_book_summarizer.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m ci.run_enforcement && \
  git add rag/summarizer.py rag/book_summarizer.py rag/test_summarizer.py rag/test_book_summarizer.py && \
  git commit -m "T-DOC85: fall back to an LLM-written title when a unit has no usable heading"
```

---

## Task 7: `--dry-run` on the drop-in CLI

An off-topic PDF ingested silently on the first live drop-in run and was caught only by a human reading page one by hand. One operator read against a whole book's ingest cost is the right trade; a relevance *score* needs a threshold nobody has data to set and would run only after the expensive stages anyway.

**Files:**
- Modify: `app/ingest_local.py` (`_parse_args` at 297, `main` at 311)
- Test: `app/test_ingest_local.py`

- [ ] **Step 1: Write the failing test**

```python
def test_dry_run_stages_nothing_and_writes_no_manifest(tmp_path, monkeypatch):
    # T-DOC86: dropping a wrong file into a directory is a much easier mistake than writing a
    # wrong arXiv query, and a book costs GPU-minutes to find out.
    drop_dir, cache_dir = _drop_dir_with_one_pdf(tmp_path)  # this file's existing helper

    rc = main(["--dry-run", "--drop-dir", str(drop_dir)])

    assert rc == 0
    assert list(cache_dir.glob("*.pdf")) == []
    assert list(drop_dir.glob("manifest-*.txt")) == []
    assert list((drop_dir / "done").iterdir()) == []
```

Read the file's existing fixtures first and reuse them; `_drop_dir_with_one_pdf` is illustrative.

- [ ] **Step 2: Run to verify it fails**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest app/test_ingest_local.py -v -k dry_run
```

Expected: FAIL — `unrecognized arguments: --dry-run`.

- [ ] **Step 3: Implement**

Add to `_parse_args`:

```python
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what WOULD be staged -- detected id, title, and the first lines of "
             "extracted text per file -- without staging anything or invoking app.ingest",
    )
```

In `main`, after `drop_dir`/`cache_dir` are resolved and **before** `scan_drop_dir`:

```python
    if args.dry_run:
        return _report_dry_run(drop_dir)
```

And the reporter — extract text with the parser dependency `app/ingest_local.py` already uses for
`detect_arxiv_id`; do not add a new one:

```python
def _report_dry_run(drop_dir: Path) -> int:
    """T-DOC86: print enough of each file for an operator to spot a wrong one, and stage nothing.

    Deliberately not a relevance *score*: thresholding a summary against `focus_area` needs a
    cutoff nobody has data to set, and would only run after parse+summarize have already been
    paid for. This costs one read and no model.
    """
    pdfs = sorted(p for p in drop_dir.glob("*.pdf"))
    if not pdfs:
        logger.info("ingest_local --dry-run: no PDFs in %s", drop_dir)
        return 0
    for path in pdfs:
        arxiv_id = detect_arxiv_id(path)
        preview = _first_page_text(path)[:500].replace("\n", " ")
        logger.info(
            "\n--- %s\n    id:      %s\n    preview: %s",
            path.name, arxiv_id or mint_local_ref(path).paper_id, preview,
        )
    logger.info(
        "ingest_local --dry-run: %d file(s) would be staged. Re-run without --dry-run to "
        "proceed, or move unwanted files out of %s first.", len(pdfs), drop_dir,
    )
    return 0
```

`_first_page_text(path)` is a small new helper using the PDF library `detect_arxiv_id` already
imports — read that function first and reuse its reader rather than importing a second one.
Handle an unreadable PDF by logging the failure and continuing to the next file, with a typed
`except` (never a bare `except Exception` — CI check (b)).

- [ ] **Step 4: Run to verify it passes**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  pytest app/test_ingest_local.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit and open the PR**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m ci.run_enforcement && \
  pytest rag/ app/ contracts/ -q && \
  git add app/ingest_local.py app/test_ingest_local.py && \
  git commit -m "T-DOC86: add --dry-run to app/ingest_local so an operator can see what stages"
```

Then push and `gh pr create`. **The PR needs the foundation label** (Task 1 touched
`rag/fakes/`). Body: the three ticket numbers, what each changed, and the note that Task 8 is
operational and follows the merge. No AI attribution.

---

## Task 8: re-ingest all five books (operational, after merge)

Runs on `main` after the PR merges. Not a code task — no commits.

Per T-DOC85, the four not-yet-redone books get correct titles on their first and only re-ingest,
and `local:f0929288d4f3` is redone a second time so all five carry the same titling.

- [ ] **Step 1: Confirm the merged fixes are present**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  git -C /home/omar/ai-projects/research-system-rag pull --ff-only && \
  python -c "from rag.book_summarizer import _best_heading; from rag.summarizer import _PROMPTS; \
             print('book_title' in _PROMPTS, _best_heading(['F','Neutral Controls']))" && \
  python -m app.doctor
```

Expected: `True Neutral Controls`, and doctor OK.

- [ ] **Step 2: Record the baseline**

For each of the five ids, capture chapter count and titles before deleting, so the comparison is
concrete:

```
local:dfe850b3281a  local:f0929288d4f3  local:54d6ca71dda9
local:14b7e283bdcd  local:f6c64e1e8c7d
```

- [ ] **Step 3: Delete through the new CLI**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m app.delete_docs --yes \
    local:dfe850b3281a local:f0929288d4f3 local:54d6ca71dda9 \
    local:14b7e283bdcd local:f6c64e1e8c7d
```

**No hand-written SQL.** If this leaves any `ingest_state` row behind, Tasks 1-2 did not work and
the re-ingest must not proceed — verify before continuing:

```bash
python -c "
import sqlite3
ids = ('local:dfe850b3281a','local:f0929288d4f3','local:54d6ca71dda9','local:14b7e283bdcd','local:f6c64e1e8c7d')
con = sqlite3.connect('file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro', uri=True)
q = ','.join('?' * len(ids))
print('stale state rows (must be 0):',
      con.execute(f'SELECT COUNT(*) FROM ingest_state WHERE paper_id IN ({q})', ids).fetchone()[0])
print('papers rows (must be 0):',
      con.execute(f'SELECT COUNT(*) FROM papers WHERE paper_id IN ({q})', ids).fetchone()[0])"
```

- [ ] **Step 4: Re-ingest**

The five PDFs are already in `drop_in/done/`. Move them back to `drop_in/`, then run
`app.ingest_local` — **with `--dry-run` first**, which is now the supported way to confirm the
right five files are staged. Capture the real exit code (`rc=$?` immediately after the command,
never after a redirect or an `echo`).

Budget roughly 350s of GPU per book based on the verified run — about 30 minutes total, versus the
76 minutes one book took before T-DOC82.

- [ ] **Step 5: Verify**

Per book: chapter count in the 15-40 band, no title scoring 0 under `_title_score`, the whole-book
summary describes that book with no invented numbers, and SQLite/Qdrant counts agree
(`chunks + chapters + 1 == qdrant points for that id`). Run `python -m app.corpus_integrity` —
it now reports the T-DOC84 orphan shape too, so a clean result means more than it used to.

The eyeball gate from the T-DOC82 spec still applies and is still a human read, not an assertion.

---

## Self-Review

**Spec coverage.** T-DOC84's three fix parts map to Tasks 1-3, with the optional `corpus_integrity`
widening as Task 4. T-DOC85's chosen hybrid maps to Tasks 5 (heading pick) and 6 (LLM fallback).
T-DOC86's dry-run maps to Task 7. The rollout the T-DOC82 spec left unfinished is Task 8.

**Known soft spots, called out rather than hidden:**
- `_MIN_TITLE_SCORE = 8` is tuned to reject `See Also` (7) and accept two real words. It is a
  judgment call against one measured book, same class of threshold as T-DOC82's `3/60/50%` guards.
  Step 5 of Task 5 exists to prove it is at least load-bearing rather than decorative.
- The LLM title is model-generated, so it carries the grounding caution T-DOC82 raised. It is
  constrained to extractive wording and fed a grounded summary rather than raw text, and it fires
  only where the deterministic path found nothing — but it cannot be proven fabrication-free by a
  unit test, only observed in Task 8.
- Task 4's LEFT JOIN may make `p` unused; the task says to drop the join entirely in that case
  rather than leave a decorative one.
