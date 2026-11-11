Title: OP-6: Guard every corpus tool against a missing or mismatched database
Labels: wave:1-no-gpu, area:ops, needs-services, size:M

## OP-6 -- Guard every corpus tool against a missing or mismatched database

**Review cross-reference:** S-07. **Wave:** W1 do now, no GPU.

**Why.** Only `app.serve --data-dir` refuses a nonexistent database (`app/serve.py:80-82` has no exists check on the default branch). `app/corpus_integrity.py` opens the live database read-write, and the collection-versus-database pairing is checked nowhere, so a mispointed tool returns a confident empty or wrong corpus (the T-DOC56 shape; RV-6 F-A4, RV-3 F-1.2; review S-07). `app/dashboard/status.py:830` falls back to the literal collection name `papers`.

**Scope.**
- In:
  - One shared `require_existing_db()` (search for an existing helper first, e.g. the T-DOC56 `_resolve_store_paths`; add a module only if none fits) used by `corpus_integrity` (also opened `mode=ro`), `snapshot`, `reindex_idf`.
  - `app.doctor`: collection point count must match the database within 1% (stated tolerance), reported with both numbers.
  - Remove the `papers` fallback at `app/dashboard/status.py:830`.
- Out (explicitly):
  - The two `app/serve.py` branches (folded into OP-2, which owns that file's startup). Changing `migrate()` (protected).
  - Auto-snapshot before migration (RV-6 F-A7, not carried by the review).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/corpus_paths.py`
- `app/test_corpus_paths.py`
- `app/corpus_integrity.py`
- `app/test_corpus_integrity.py`
- `app/snapshot.py`
- `app/test_snapshot.py`
- `app/reindex_idf.py`
- `app/test_reindex_idf.py`
- `app/doctor.py`
- `app/test_doctor.py`
- `app/dashboard/status.py`
- `app/dashboard/test_status.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring of `require_existing_db()` stating precondition and error message; list of the five call sites
② failing tests per call site (nonexistent path exits non-zero, names the path)
③ helper + call sites to green; `corpus_integrity` opens `mode=ro` (test asserts a write attempt fails)
④ doctor point-count-vs-database check with injected counts; status fallback removed

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/corpus_paths.py app/test_corpus_paths.py app/corpus_integrity.py app/test_corpus_integrity.py app/snapshot.py app/test_snapshot.py app/reindex_idf.py app/test_reindex_idf.py app/doctor.py app/test_doctor.py app/dashboard/status.py app/dashboard/test_status.py`
- `conda run -n agent-rag-research python -m app.corpus_integrity --help` still works; each tool against a nonexistent data dir exits non-zero (shown in the PR)
- `conda run -n agent-rag-research python -m app.doctor --cpu-only` from each data dir still passes where services are up (needs services: run only when the vector store is up)

**Acceptance / falsification criterion.** Every named tool exits non-zero against a nonexistent path with a message that names the path; `corpus_integrity` cannot write; doctor run from each of the five data dirs passes its pairing check on the current corpora. Falsified if any tool still prints a result for a nonexistent path or if the doctor check fails on a correctly paired corpus.

**Gates / depends on.** Depends on: OP-3. Gates: EP-3, OP-5, OP-2.

**Needs.** GPU: n · services up: vector store (CPU container) only for the doctor smoke run; unit tests use fakes · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A false positive in the 1% tolerance blocks a healthy doctor run. Mitigation: tolerance is a named constant, the message prints both counts. Rollback: revert; the guards are additive.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (doctor behaviour) via EP-3; RUNBOOK via EP-7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
