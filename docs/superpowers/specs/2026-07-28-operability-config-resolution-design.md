# T-DOC89 / T-DOC65 / T-DOC66 / T-DOC67 — making the system's location unambiguous

*2026-07-28. Four tickets, one change: they are the same root cause seen from four angles.
Foundation paths involved: `rag/config.py`, `config.yaml`, `.github/CODEOWNERS`.*

## Why one change

- **T-DOC89** — `load_config()` resolves against cwd, and two `config.yaml` files exist.
- **T-DOC65** — "document or script creating the data-dir `config.yaml`" — i.e. the *absence* of a
  supported way to produce the real config is why people fall back to the template.
- **T-DOC66** — "capture the `--no-capture-output` / `PYTHONPATH` / `cwd` requirements" — the same
  tribal knowledge, written down for the MCP path.
- **T-DOC67** — delete the stray repo-root `papers.db` — the *artifact* T-DOC89 produces.

Fixing T-DOC89 alone leaves 65 and 66 as documentation of a problem that no longer exists, and 67
as a file that can no longer be recreated. Doing them together is materially cheaper.

## The failure, restated

`load_config(path="config.yaml")` resolves relative to the **process's cwd**, and paths *inside* a
config are also cwd-relative. The tracked `config.yaml` is a template whose every path is relative;
the real config lives outside the repo with absolute paths. So `db_path: "papers.db"` does not mean
"the repo's database" — it means "a `papers.db` wherever you happen to be standing."

Four recurrences: **OG-33** (stray copies), **T-DOC56** (an empty stub produced a false
`Recall@10 = 0.000`), **T-DOC22** (cwd mismatch), and 2026-07-28 twice — `delete_docs` would have
silently deleted nothing from the repo root, and `ingest_local --dry-run` reported "no PDFs" from
the data dir. **Neither working directory was correct**; the rollout proceeded via a `--drop-dir`
override, which is a workaround.

Every failure mode is silent.

## Design

### 1. A config describes itself

Relative paths *inside* a config resolve against **that config file's own directory**, not cwd.
`drop_in` in a config then permanently means "the `drop_in` next to that config", from anywhere.
This alone removes the "ran from the wrong place" class.

### 2. The template stops being loadable — rename plus validation

**Rename** the tracked `config.yaml` → `config.example.yaml`. It is then not *named* `config.yaml`
and can never be discovered by accident. This is the structural half.

Blast radius, all of which must be updated in the same change:
- `.github/CODEOWNERS` — itself foundation-frozen
- `AGENTS.md:88`, `GIT-WORKFLOW.md:131`, `CONVENTIONS.md:41`, `CONVENTIONS.md:349` — all name
  `config.yaml` as a protected path
- `app/benchmark.py:399` — `--config` defaults to `"config.yaml"`; repoint to the example or make
  it required
- `app/benchmark.py:277` and `app/dashboard/controller.py` **write** a scratch/override
  `config.yaml` into a directory they control. Those are unaffected by the rename — verify, do not
  assume.

**Plus stub validation**, as the belt-and-braces half. After resolution, if the resolved `db_path`
falls **inside the repo working tree**, that is the template's signature — no legitimate setup puts
the corpus there (`.gitignore` calls those files "local data cruft ... the REAL store lives in the
sibling `research-system-rag-data/` dir"). Log a prominent warning, and make `app/doctor.py` fail
on it.

Deliberately **not** validating "database has 0 rows" — a genuinely fresh corpus legitimately has
zero papers, and refusing would break bootstrap. Repo-tree containment is the precise signature;
row count is a proxy that misfires.

### 3. Discovery that finds the right file unaided

Precedence: explicit `--config` → `RAG_CONFIG` env var → `config.yaml` in cwd → walk up parent
directories → then an error naming **every location tried** and both ways to fix it.

The operator requirement is explicit: this must not become a tool that fails repeatedly. It should
resolve correctly on its own, and be loud only when it genuinely cannot. Rollout therefore
establishes the link once — a gitignored `config.yaml` symlink at the repo root pointing at the
real config, so the repo root and the data dir both resolve to the same real file.

`rag/config.py` reading `RAG_CONFIG` is the one legitimate environment read in this codebase; it is
*the* config loader, and CONVENTIONS §"No module calls `os.getenv`" exists to stop config reads
leaking into modules, not to stop the loader from loading. Note this explicitly so a future
reviewer doesn't read it as a violation.

### 4. Always report what was resolved

Every `app/` entrypoint logs its resolved absolute `db_path`, `blob_dir`, and `collection` at
startup. `app/delete_docs.py` already does exactly this — added after a review caught it deleting
from the wrong database — so this generalizes a proven pattern.

**Correction (part 2 review):** this section originally said `db_path`/`collection`/`drop_in_dir`,
which disagreed with its own cited example (`delete_docs.py` logs `db_path`/`blob_dir`/
`collection`). Resolved in favor of the working precedent: `db_path`/`blob_dir`/`collection`
everywhere, with `drop_in_dir` added ONLY in `app/ingest_local.py`, where it's the field that
actually decides that module's behavior (the directory it scans).

Also: "every `app/` entrypoint" means every entrypoint with real startup logic to log from,
including ones with no `main()` function — `app/ingest.py`, `app/parse_phase.py`, and
`app/serve.py` all do their real work directly in a bare `if __name__ == "__main__":` block (or,
for `app/serve.py`, at module import time) rather than inside a `main()`, and are covered the same
as every other entrypoint. `app/ingest.py` in particular must log the EFFECTIVE config (after
`_effective_config`'s CLI/dashboard-override handling), not the plain `load_config()` result —
logging the pre-override value would print a database the run isn't going to touch (OG-49#1).

### 5. T-DOC65 — a supported way to produce the real config

`python -m app.init_config --data-dir <path>` writes a data-dir `config.yaml` from the example with
absolute paths filled in, and offers to create the gitignored repo-root symlink. Refuses to
overwrite an existing config without `--force`. This is what makes step 3's "establish the link
once" a command rather than tribal knowledge.

### 6. T-DOC66 — MCP deploy check

`app/doctor.py` gains a check that the MCP server actually launches and answers `list_tools`, and
`docs/RUNBOOK.md` captures the `--no-capture-output` / `PYTHONPATH` / cwd requirements — which
currently appear nowhere (grep returns nothing).

### 7. T-DOC67 — remove the artifacts

Delete the stray repo-root `papers.db` (0 rows) and `pdf_cache/` (20 files). `.gitignore` already
lists both. Prevention now comes from §2 rather than from discipline.

## Testing

- Internal relative paths resolve against the config's directory, not cwd — assert by loading the
  same config file from two different working directories and getting identical absolute paths.
- Discovery precedence, each rung, including the walk-up.
- The error names every location tried.
- Repo-tree `db_path` triggers the warning and fails `doctor`.
- A fresh 0-row database **outside** the repo does NOT trigger it (pins the deliberate
  non-validation of row count).
- `init_config` writes a loadable config with absolute paths; refuses to overwrite without
  `--force`.
- `app/benchmark.py`'s scratch-config path still works after the rename.

## Risks

- **`.github/CODEOWNERS` is itself foundation-frozen.** Editing it to reflect the rename is
  governance, not just refactoring. Needs the `foundation-change` label and an explicit callout.
- **The rename is wide but shallow** — six mechanical edits. The risk is missing one, not any single
  one being hard. Grep for `config.yaml` across all tracked files after the change and confirm every
  remaining hit is either a writer of its own scratch file or intentionally referring to the real
  config.
- **`app/dashboard/controller.py` writes a run-scoped override `config.yaml`.** If the dashboard
  relies on cwd-relative discovery finding it, §1 and §3 could change its behaviour. Verify before
  assuming it is unaffected.

## Out of scope

- Changing where the real corpus lives.
- Any change to `Config`'s fields or validation beyond path resolution.
- Retrofitting resolved-path logging into non-`app/` modules.
