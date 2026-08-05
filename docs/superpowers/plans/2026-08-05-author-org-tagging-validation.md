# Author-Org Tagging — Extraction Methods + Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build both candidate affiliation-extraction methods (rule-based, LLM-based) from
`docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md`, and run the validation
experiment that decides which one (or both) actually ships.

**Architecture:** Per the spec, extraction (`raw_affiliations`) is method-dependent; org-matching
against `KNOWN_ORGS` is a separate, cheap, method-agnostic step. This plan stops at the validation
report — production wiring into the ingestion pipeline (`app/assembly.py`, `SearchFilters`/
`VectorPayload`, MCP exposure) is deliberately a SEPARATE follow-up plan, written after this
plan's Task 4 produces real precision/recall numbers, so that plan's task briefs can name the
actual winning method concretely instead of a conditional "if rule-based wins, do X, else do Y"
— the writing-plans "No Placeholders" rule doesn't allow guessing the outcome of an experiment
that hasn't run yet.

**Tech Stack:** Python 3, pydantic (contracts), `httpx` (Ollama HTTP, confined to
`rag/summarizer.py` per this repo's vendor-isolation CI check — see Task 3), this repo's existing
`app.ingest --scratch --paper-ids-file` tooling and `rag/document_store.py::DocumentStore` for
read access to already-parsed papers.

## Global Constraints

- The "ollama" token (and any Ollama-specific code) may ONLY appear in `rag/summarizer.py`,
  `rag/test_summarizer.py`, or an `app/exp_*.py` composition-root script that constructs
  `OllamaSummarizer` without naming "ollama" itself (`ci/checks/vendor_isolation.py`'s
  `VENDOR_RULES` enforces this in CI) — the LLM-based extraction method must be a method on
  `OllamaSummarizer`, never a standalone Ollama HTTP call in `rag/author_org_tagger.py`.
- `rag/author_org_tagger.py` (the rule-based extraction + org-matching module) must have zero
  vendor/HTTP dependencies — pure functions over `Block`/string data only.
- Org-matching (Step 2) must be re-runnable against already-extracted `raw_affiliations` without
  re-parsing or re-calling any extraction method — this is the design's central "generalize to
  new orgs later" property; do not couple Step 2's logic to Step 1's internals.
- This plan produces no changes to `contracts/document_store.py`, `contracts/vector_index.py`,
  `contracts/mcp_server.py`, or `app/assembly.py` — those are explicitly out of scope, deferred to
  the follow-up wiring plan (see Architecture above).

---

## File Structure

```
research-system-rag/
  contracts/
    author_orgs.py           # NEW — AuthorOrgTag, KNOWN_ORGS (Waymo entry)
  rag/
    author_org_tagger.py     # NEW — rule-based extraction, match_known_orgs, mentions_orgs
    test_author_org_tagger.py # NEW
    summarizer.py             # MODIFIED — OllamaSummarizer.extract_affiliations (LLM method)
    test_summarizer.py        # MODIFIED — tests for the new method
  app/
    exp_author_org_tagging.py # NEW — validation experiment (app/exp_*.py convention)
```

---

### Task 1: `contracts/author_orgs.py` — the org roster data model

**Files:**
- Create: `contracts/author_orgs.py`

**Interfaces:**
- Produces: `AuthorOrgTag` (FrozenModel: `name: str`, `email_domains: list[str]`,
  `keywords: list[str]`), `KNOWN_ORGS: list[AuthorOrgTag]` — consumed by Task 2's
  `match_known_orgs`/`mentions_orgs` and Task 4's experiment.

- [ ] **Step 1: Write the failing test**

```python
# contracts/test_author_orgs.py
from contracts.author_orgs import KNOWN_ORGS, AuthorOrgTag


def test_known_orgs_has_a_waymo_entry():
    names = [org.name for org in KNOWN_ORGS]
    assert "Waymo" in names


def test_waymo_entry_has_expected_domain_and_keyword():
    waymo = next(org for org in KNOWN_ORGS if org.name == "Waymo")
    assert "waymo.com" in waymo.email_domains
    assert "waymo" in [kw.lower() for kw in waymo.keywords]


def test_author_org_tag_is_frozen():
    tag = AuthorOrgTag(name="Test", email_domains=["test.com"], keywords=["test"])
    import pytest
    with pytest.raises(Exception):
        tag.name = "Changed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/omar/ai-projects/research-system-rag/.claude/worktrees/paper-author-org-tagging && /home/omar/miniconda3/envs/agent-rag-research/bin/python -m pytest contracts/test_author_orgs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'contracts.author_orgs'`.

- [ ] **Step 3: Write the implementation**

```python
# contracts/author_orgs.py
"""KNOWN_ORGS — the roster of organizations the author-org-tagging feature (see
docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md) matches extracted paper
affiliations against. A plain data constant, not a Config field: this roster is reference data
(which organizations does the user care about tracking), not a per-corpus scope lever the way
focus_area_queries is -- adding an organization is a code edit to this one file, not a config
change duplicated across every corpus's config.yaml.
"""

from contracts._base import FrozenModel


class AuthorOrgTag(FrozenModel):
    """One organization to match extracted paper affiliations against.

    `email_domains`: matched against email addresses found in a paper's extracted affiliation
    text (e.g. "waymo.com" matches "k.kusano@waymo.com") -- the higher-precision signal, hard to
    have without genuine employment there.

    `keywords`: matched as a case-insensitive substring against extracted affiliation text (e.g.
    "waymo" matches "Waymo LLC, Mountain View, CA") -- catches affiliations printed without an
    accompanying email. Also reused, separately, for the weaker `mentions_orgs` topical signal
    (org named in a paper's title/abstract, regardless of authorship).
    """

    name: str
    email_domains: list[str]
    keywords: list[str]


# Seeded from docs/ONBOARDING_AND_ARXIV_KEYWORDS.md's Waymo AV-safety corpus context.
KNOWN_ORGS: list[AuthorOrgTag] = [
    AuthorOrgTag(name="Waymo", email_domains=["waymo.com"], keywords=["waymo"]),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/omar/miniconda3/envs/agent-rag-research/bin/python -m pytest contracts/test_author_orgs.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/omar/ai-projects/research-system-rag/.claude/worktrees/paper-author-org-tagging
git add contracts/author_orgs.py contracts/test_author_orgs.py
git commit -m "Add KNOWN_ORGS author-org roster (Waymo entry)"
```

---

### Task 2: `rag/author_org_tagger.py` — rule-based extraction + org-matching + mentions_orgs

**Files:**
- Create: `rag/author_org_tagger.py`
- Test: `rag/test_author_org_tagger.py`

**Interfaces:**
- Consumes: `contracts.author_orgs.KNOWN_ORGS`, `contracts.provenance.Block` (fields: `page: int`,
  `section_path: str`, `text: str` — Task 1's dependency).
- Produces: `extract_affiliations_rule_based(blocks: list[Block]) -> list[str]`,
  `match_known_orgs(raw_affiliations: list[str]) -> list[str]`,
  `mentions_orgs(title: str, abstract: str) -> list[str]` — all consumed by Task 4's experiment
  (and, later, the follow-up wiring plan).

- [ ] **Step 1: Write the failing tests**

```python
# rag/test_author_org_tagger.py
"""Offline unit tests for rag/author_org_tagger.py -- no network, no GPU, canned Block fixtures.
Fixture shape mirrors rag/test_parser.py's `_block()` helper (Block's real required fields,
including `index`, which `contracts.provenance.Block` requires but is otherwise irrelevant here)."""
from contracts.provenance import Block
from rag.author_org_tagger import (
    extract_affiliations_rule_based,
    match_known_orgs,
    mentions_orgs,
)


def _block(text, page=0, section_path="", block_id="b1", index=0):
    return Block(
        block_id=block_id, paper_id="test", text=text, type="prose",
        page=page, bbox=(10.0, 20.0, 110.0, 220.0), section_path=section_path, index=index,
    )


def test_extract_picks_up_front_matter_blocks_on_page_zero():
    blocks = [
        _block("K. Kusano, J. Doe", section_path=""),
        _block("Introduction", section_path="Introduction"),  # not front matter -- excluded
        _block("We study rare events.", section_path="Introduction"),
    ]
    result = extract_affiliations_rule_based(blocks)
    assert result == ["K. Kusano, J. Doe"]


def test_extract_picks_up_blocks_with_an_email_even_outside_front_matter():
    blocks = [
        _block("Correspondence: k.kusano@waymo.com", section_path="Author Note"),
    ]
    result = extract_affiliations_rule_based(blocks)
    assert result == ["Correspondence: k.kusano@waymo.com"]


def test_extract_ignores_page_one_even_if_it_looks_like_front_matter():
    blocks = [_block("Some footer text", page=1, section_path="")]
    assert extract_affiliations_rule_based(blocks) == []


def test_extract_skips_blank_blocks():
    blocks = [_block("   ", section_path="")]
    assert extract_affiliations_rule_based(blocks) == []


def test_match_known_orgs_finds_waymo_by_email_domain():
    assert match_known_orgs(["Contact: k.kusano@waymo.com"]) == ["Waymo"]


def test_match_known_orgs_finds_waymo_by_keyword_without_email():
    assert match_known_orgs(["Waymo LLC, Mountain View, CA"]) == ["Waymo"]


def test_match_known_orgs_empty_when_no_match():
    assert match_known_orgs(["MIT, Cambridge, MA", "contact@mit.edu"]) == []


def test_match_known_orgs_empty_list_input():
    assert match_known_orgs([]) == []


def test_mentions_orgs_finds_waymo_in_abstract():
    result = mentions_orgs("A study of driving", "We evaluate on the Waymo Open Motion Dataset.")
    assert result == ["Waymo"]


def test_mentions_orgs_case_insensitive():
    result = mentions_orgs("WAYMO study", "")
    assert result == ["Waymo"]


def test_mentions_orgs_empty_when_absent():
    assert mentions_orgs("A study of driving", "We use naturalistic data.") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/omar/miniconda3/envs/agent-rag-research/bin/python -m pytest rag/test_author_org_tagger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rag.author_org_tagger'`.

- [ ] **Step 3: Write the implementation**

```python
# rag/author_org_tagger.py
"""Rule-based affiliation extraction + KNOWN_ORGS matching (see
docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md §4). Pure functions, no
vendor/HTTP dependency -- the LLM-based extraction alternative lives in
rag/summarizer.py::OllamaSummarizer.extract_affiliations instead, per this repo's vendor-isolation
rule confining "ollama" to that file (ci/checks/vendor_isolation.py).

extract_affiliations_rule_based is genuinely org-agnostic (returns raw candidate-region block
text, no KNOWN_ORGS awareness) -- match_known_orgs is the separate, cheap, re-runnable-without-
re-parsing step that actually checks against known organizations. Adding an organization later
only means re-running match_known_orgs over already-extracted raw_affiliations.
"""

import re

from contracts.author_orgs import KNOWN_ORGS
from contracts.provenance import Block

_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")


def _is_candidate_affiliation_block(block: Block) -> bool:
    """Page-0 blocks that are either front matter (section_path=="", MinerU's marker for
    everything before the first real section heading -- see rag/parser.py's _SectionTracker
    comment) or contain an email address (a corresponding-author email is a strong positional
    signal that an affiliation statement is nearby) -- deliberately layout-position-agnostic
    beyond these two conditions, since real papers vary in exactly where affiliations print."""
    return block.page == 0 and (block.section_path == "" or "@" in block.text)


def extract_affiliations_rule_based(blocks: list[Block]) -> list[str]:
    """Step 1 (rule-based variant): each candidate block's raw text, one entry per block, no
    matching against KNOWN_ORGS yet. Blank/whitespace-only blocks are dropped."""
    return [
        block.text for block in blocks
        if _is_candidate_affiliation_block(block) and block.text.strip()
    ]


def match_known_orgs(raw_affiliations: list[str]) -> list[str]:
    """Step 2: deterministic, cheap, re-runnable without re-parsing or re-extracting -- matches
    already-extracted raw_affiliations text against KNOWN_ORGS by email domain (higher precision)
    or keyword substring (catches affiliations printed without an email)."""
    combined = " ".join(raw_affiliations).lower()
    found_domains = {d.lower() for d in _EMAIL_RE.findall(combined)}
    matched = []
    for org in KNOWN_ORGS:
        domain_hit = any(d.lower() in found_domains for d in org.email_domains)
        keyword_hit = any(kw.lower() in combined for kw in org.keywords)
        if domain_hit or keyword_hit:
            matched.append(org.name)
    return matched


def mentions_orgs(title: str, abstract: str) -> list[str]:
    """A weaker, topical signal independent of authorship: does an org's keyword appear in the
    paper's own title/abstract (e.g. "we evaluate on the Waymo Open Motion Dataset")? Must not be
    conflated with match_known_orgs's authorship signal."""
    text = (title + " " + abstract).lower()
    return [org.name for org in KNOWN_ORGS if any(kw.lower() in text for kw in org.keywords)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/omar/miniconda3/envs/agent-rag-research/bin/python -m pytest rag/test_author_org_tagger.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/omar/ai-projects/research-system-rag/.claude/worktrees/paper-author-org-tagging
git add rag/author_org_tagger.py rag/test_author_org_tagger.py
git commit -m "Add rule-based affiliation extraction and KNOWN_ORGS matching"
```

---

### Task 3: `OllamaSummarizer.extract_affiliations` — LLM-based extraction method

**Files:**
- Modify: `rag/summarizer.py`
- Modify: `rag/test_summarizer.py`

**Interfaces:**
- Consumes: `OllamaSummarizer.__init__`'s existing `_client`/`_gpu_lock`/`_model` (already built by
  `summarize()`'s constructor — no new construction path).
- Produces: `OllamaSummarizer.extract_affiliations(self, first_page_text: str) -> list[str]` —
  consumed by Task 4's experiment as the LLM-method arm.

- [ ] **Step 1: Read the existing `summarize()` method and its prompt dict first**

Before writing anything, read `rag/summarizer.py` end to end (the file already open from Task
context) — `extract_affiliations` must follow the exact same error-handling shape `summarize()`
uses (`TransientError`/`PermanentError` on the same status-code split, `self._gpu_lock.acquire`
around the HTTP call, the same `/api/generate` endpoint), not a divergent new pattern.

- [ ] **Step 2: Write the failing tests**

Append to `rag/test_summarizer.py`, mirroring its existing `httpx.MockTransport` +
`_build_summarizer_with_client(client, FakeGpuLock())` pattern EXACTLY (see e.g.
`test_5xx_response_maps_to_transient_error` in the same file — same helper, same
`httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))`
construction):

```python
def test_extract_affiliations_parses_json_array_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        return httpx.Response(200, json={"response": '["Waymo LLC", "MIT"]'})

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    adapter = _build_summarizer_with_client(client, FakeGpuLock())
    result = adapter.extract_affiliations("K. Kusano1, J. Doe2\n1Waymo LLC 2MIT")
    assert result == ["Waymo LLC", "MIT"]


def test_extract_affiliations_empty_array_when_none_stated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "[]"})

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    adapter = _build_summarizer_with_client(client, FakeGpuLock())
    result = adapter.extract_affiliations("No affiliations printed here.")
    assert result == []


def test_extract_affiliations_permanent_error_on_malformed_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "not a json array"})

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    adapter = _build_summarizer_with_client(client, FakeGpuLock())
    with pytest.raises(PermanentError):
        adapter.extract_affiliations("some text")


def test_extract_affiliations_transient_error_on_503():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.Client(base_url="http://ollama.local", transport=httpx.MockTransport(handler))
    adapter = _build_summarizer_with_client(client, FakeGpuLock())
    with pytest.raises(TransientError):
        adapter.extract_affiliations("some text")
```

(`PermanentError`/`TransientError`/`httpx`/`pytest`/`FakeGpuLock`/`_build_summarizer_with_client`
are all already imported/defined at this file's top for the existing `summarize()` tests — reuse
them, don't re-add or reinvent.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `/home/omar/miniconda3/envs/agent-rag-research/bin/python -m pytest rag/test_summarizer.py -k extract_affiliations -v`
Expected: FAIL with `AttributeError: 'OllamaSummarizer' object has no attribute 'extract_affiliations'`.

- [ ] **Step 4: Write the implementation**

Add to `rag/summarizer.py`'s `_PROMPTS`-adjacent constants (near the top, alongside
`_SUMMARY_PROMPT`):

```python
# Author-org-tagging (docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md §4):
# engineered against BOTH error directions, not just recall --
# (a) "ONLY affiliations literally stated" + "do not infer from author names" guards false
#     positives (no inventing an affiliation the text doesn't actually say);
# (b) "scan the ENTIRE text, not just the author byline" guards false negatives (catches
#     footnote-style/numbered affiliations printed elsewhere on the page, not only inline).
_AFFILIATION_EXTRACTION_PROMPT = (
    "Below is the first page of an academic paper. List every institutional or company "
    "affiliation stated for the authors, as a JSON array of strings. Scan the entire text below, "
    "not only the line immediately after the author names -- affiliations are sometimes listed "
    "as numbered footnotes or in a separate block elsewhere on the page. Include ONLY "
    "affiliations that are literally written in the text below; do not guess or infer an "
    "affiliation from an author's name, nationality, or any outside knowledge. If no "
    "affiliations are stated, return an empty array: [].\n\n"
    "Respond with ONLY the JSON array, no other text.\n\n{page_text}"
)
```

Add the method to `OllamaSummarizer` (same class as `summarize()`, placed right after it):

```python
    def extract_affiliations(self, first_page_text: str) -> list[str]:
        """LLM-based candidate for Step 1 (extraction) of the author-org-tagging design (see
        docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md §4) -- general,
        org-agnostic: returns whatever affiliations are literally stated on the given page text,
        not matched against any known organization (that's the separate, cheap
        rag.author_org_tagger.match_known_orgs step). Scoped to page-0 text only (bounded
        context, cheap) by the caller.
        """
        with self._gpu_lock.acquire("extract_affiliations"):
            try:
                response = self._client.post(
                    "/api/generate",
                    json={
                        "model": self._model,
                        "prompt": _AFFILIATION_EXTRACTION_PROMPT.format(page_text=first_page_text),
                        "stream": False,
                        "think": False,
                        "options": {"num_ctx": _NUM_CTX_CEILING, "num_predict": _NUM_PREDICT},
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status in _RETRYABLE_STATUSES:
                    raise TransientError(
                        f"extract_affiliations: generation LLM server returned {status}"
                    ) from error
                raise PermanentError(
                    f"extract_affiliations: generation LLM server returned {status}"
                ) from error
            except httpx.HTTPError as error:
                raise TransientError(
                    f"extract_affiliations: generation LLM request failed: {error}"
                ) from error

            try:
                raw_response = response.json()["response"].strip()
            except KeyError as error:
                raise PermanentError(
                    "extract_affiliations: generation LLM response missing 'response' field"
                ) from error

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError as error:
            raise PermanentError(
                f"extract_affiliations: generation LLM did not return valid JSON: {raw_response!r}"
            ) from error
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise PermanentError(
                f"extract_affiliations: generation LLM returned non-list-of-strings JSON: {parsed!r}"
            )
        return parsed
```

Add `import json` at the top of `rag/summarizer.py` if not already present (check first — several
modules in this repo already import `json`, this one may not yet since `summarize()` doesn't need
it). Use the existing `_NUM_CTX_CEILING`/`_NUM_PREDICT`/`_RETRYABLE_STATUSES` constants already
defined in this file for `summarize()` — do not redefine them.

- [ ] **Step 5: Run tests to verify they pass**

Run: `/home/omar/miniconda3/envs/agent-rag-research/bin/python -m pytest rag/test_summarizer.py -v`
Expected: all tests pass, including the new ones (existing `summarize()` tests must still pass
unchanged — this is an addition, not a modification to existing methods).

- [ ] **Step 6: Commit**

```bash
cd /home/omar/ai-projects/research-system-rag/.claude/worktrees/paper-author-org-tagging
git add rag/summarizer.py rag/test_summarizer.py
git commit -m "Add OllamaSummarizer.extract_affiliations for LLM-based affiliation extraction"
```

---

### Task 4: Validation experiment — `app/exp_author_org_tagging.py`

**Files:**
- Create: `app/exp_author_org_tagging.py`

**Interfaces:**
- Consumes: Task 2's `extract_affiliations_rule_based`/`match_known_orgs`, Task 3's
  `OllamaSummarizer.extract_affiliations`, `rag.document_store.DocumentStore` (existing,
  read-only usage), `app.ingest`'s `--scratch --paper-ids-file` CLI (existing, unmodified).
- Produces: a printed precision/recall report for both extraction methods — the deliverable this
  whole plan exists to produce. No return value consumed by later code (this plan stops here).

- [ ] **Step 1: Build the positive-set id list from the parallel Waymo corpus-expansion effort**

The Waymo AV-safety corpus expansion (a separate, parallel in-flight plan/worktree) already
scouted ~1444 candidate papers with their author lists, written to an absolute,
worktree-independent path:
`/home/omar/ai-projects/research-system-rag/waymo/data/candidates.json`.

```bash
python3 -c "
import json
KNOWN_WAYMO_SURNAMES = [
    'Kusano', 'Scanlon', 'McMurry', 'Favaro', 'Fraade-Blanar', 'Engström',
    'Schnelle', 'Wichner', 'Campolettano', 'Schubert', 'Dinparastdjadid',
]  # excludes 'Chen'/'Johnson'/'Victor' -- too common to safely auto-select a positive set by
   # surname alone without the first-initial disambiguation the full design calls for; the
   # 11 remaining names are distinctive enough for THIS experiment's positive-set selection

candidates = json.load(open('/home/omar/ai-projects/research-system-rag/waymo/data/candidates.json'))
positive = []
for c in candidates:
    if any(any(surname in author for surname in KNOWN_WAYMO_SURNAMES) for author in c['authors']):
        positive.append(c['id'])
    if len(positive) >= 10:
        break

print(f'{len(positive)} positive-set candidates found')
with open('/tmp/waymo_positive_set_ids.txt', 'w') as f:
    f.write('\n'.join(positive) + '\n')
print('written to /tmp/waymo_positive_set_ids.txt')
"
```

If fewer than 5 ids are found, widen `KNOWN_WAYMO_SURNAMES` slightly (this is a one-off manual
step, not part of the committed script — the experiment script itself takes the resulting id
file as a fixed input, see Step 2) and report the actual count achieved rather than blocking.

- [ ] **Step 2: Parse the positive set into a scratch corpus (real infra, isolated from production)**

```bash
cd /home/omar/ai-projects/research-system-rag/.claude/worktrees/paper-author-org-tagging
/home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.doctor
/home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.ingest \
  --scratch --paper-ids-file /tmp/waymo_positive_set_ids.txt --parse-workers 1
```

`--scratch` (see `app/ingest.py::_scratch_overrides`) auto-provisions an isolated temp
`db_path`/`blob_dir`/Qdrant collection and prints the temp directory path — this never touches
production or the Waymo corpus's own data dir. Note the printed scratch `db_path`/`blob_dir` for
Step 4 (the experiment script takes them as `--positive-db`/`--positive-blob-dir` arguments).

- [ ] **Step 3: Write the experiment script**

```python
# app/exp_author_org_tagging.py
"""Validation experiment for docs/superpowers/specs/2026-08-05-paper-author-org-tagging-design.md
§6 -- measures precision AND recall (both false-positive and false-negative rates) for both
candidate affiliation-extraction methods (rule-based, LLM-based) against a real positive set
(known Waymo-authored papers) and a real negative set (sampled from the existing causal-inference
corpus). A throwaway validation script (app/exp_* convention -- see app/exp3_hierarchy_sim.py,
app/exp_tdoc87_marker_repair.py), not a permanent module; its output is a decision, not a library.

Constructs OllamaSummarizer directly (composition-root shape, same as app/exp1_outline_split.py)
-- names no vendor token itself, per ci/checks/vendor_isolation.py's VENDOR_RULES.
"""

import argparse
import random
from pathlib import Path

import httpx

from rag.author_org_tagger import extract_affiliations_rule_based, match_known_orgs
from rag.document_store import DocumentStore
from rag.gpu_lock import FileGpuLock
from rag.summarizer import OllamaSummarizer

_OLLAMA_URL = "http://localhost:11434"  # matches app/assembly.py's _OLLAMA_URL exactly
_MODEL = "qwen3:14b"  # matches app/assembly.py's _OLLAMA_MODEL exactly


def _first_page_text(blocks) -> str:
    return "\n".join(b.text for b in blocks if b.page == 0)


def _reservoir_sample(iterator, k: int) -> list:
    """Sample up to k items uniformly at random from a (possibly large) iterator without
    materializing it fully -- DocumentStore.iter_papers() streams from SQLite; the production
    corpus is 12,390+ full PaperRecords (parsed blocks/chunks included), too much to load into a
    list just to random.sample() 30 of them."""
    reservoir: list = []
    for i, item in enumerate(iterator):
        if i < k:
            reservoir.append(item)
        else:
            j = random.randint(0, i)
            if j < k:
                reservoir[j] = item
    return reservoir


def _score(predicted_true_ids: set[str], actual_true_ids: set[str], all_ids: set[str]) -> dict:
    tp = len(predicted_true_ids & actual_true_ids)
    fp = len(predicted_true_ids - actual_true_ids)
    fn = len(actual_true_ids - predicted_true_ids)
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall}


def run(
    positive_db: Path, positive_blob_dir: Path,
    production_db: Path, production_blob_dir: Path,
    negative_sample_size: int = 30,
) -> None:
    # DocumentStore.__init__ takes str, not Path -- explicit str() to match its declared contract.
    positive_store = DocumentStore(str(positive_db), str(positive_blob_dir))
    production_store = DocumentStore(str(production_db), str(production_blob_dir))

    positive_records = list(positive_store.iter_papers())
    print(f"positive set: {len(positive_records)} papers (expected Waymo-authored)")

    negative_records = _reservoir_sample(production_store.iter_papers(), negative_sample_size)
    print(f"negative set: {len(negative_records)} papers (sampled from causal-inference corpus)")

    client = httpx.Client(base_url=_OLLAMA_URL, timeout=120.0)
    gpu_lock = FileGpuLock(Path("/home/omar/ai-projects/research-system-rag/.gpu.lock"))
    summarizer = OllamaSummarizer(client, gpu_lock, _MODEL)

    all_ids = {r.ref.paper_id for r in positive_records} | {r.ref.paper_id for r in negative_records}
    actual_true = {r.ref.paper_id for r in positive_records}

    rule_based_true: set[str] = set()
    llm_true: set[str] = set()

    for record in positive_records + negative_records:
        pid = record.ref.paper_id
        page_text = _first_page_text(record.parsed.blocks)

        raw_rule = extract_affiliations_rule_based(record.parsed.blocks)
        if "Waymo" in match_known_orgs(raw_rule):
            rule_based_true.add(pid)

        try:
            raw_llm = summarizer.extract_affiliations(page_text)
            if "Waymo" in match_known_orgs(raw_llm):
                llm_true.add(pid)
        except Exception as error:  # noqa: BLE001 -- experiment script: log and continue, never crash the whole run over one paper
            print(f"  {pid}: LLM extraction failed ({error}) -- counted as no-match")

    print("\n=== Rule-based method ===")
    print(_score(rule_based_true, actual_true, all_ids))
    print("\n=== LLM-based method ===")
    print(_score(llm_true, actual_true, all_ids))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-db", required=True, type=Path)
    parser.add_argument("--positive-blob-dir", required=True, type=Path)
    parser.add_argument(
        "--production-db", type=Path,
        default=Path("/home/omar/ai-projects/research-system-rag-data/papers.db"),
    )
    parser.add_argument(
        "--production-blob-dir", type=Path,
        default=Path("/home/omar/ai-projects/research-system-rag-data/blobs"),
    )
    parser.add_argument("--negative-sample-size", type=int, default=30)
    args = parser.parse_args()
    run(
        args.positive_db, args.positive_blob_dir,
        args.production_db, args.production_blob_dir,
        args.negative_sample_size,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run it for real, against Step 2's scratch output**

```bash
cd /home/omar/ai-projects/research-system-rag/.claude/worktrees/paper-author-org-tagging
/home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.exp_author_org_tagging \
  --positive-db <scratch db_path from Step 2's printed output> \
  --positive-blob-dir <scratch blob_dir from Step 2's printed output>
```

Expected: prints positive/negative set sizes, then a `precision`/`recall` dict for each method.
`tp`/`fp`/`fn` counts let a human sanity-check the raw numbers behind the ratios (e.g. `precision:
nan` with `tp=0, fp=0` means the method never fired at all — a real finding, not a script bug, if
so investigate why before concluding either method "works").

- [ ] **Step 5: Write up the decision**

No further code — append a short, plain-language note to this task's SDD report (not a new file):
which method(s) achieved acceptable precision/recall on both sets, which (if either) is dropped,
and the raw numbers. This is the handoff artifact the follow-up wiring plan (see this plan's
Architecture section) will be written from.

- [ ] **Step 6: Commit**

```bash
cd /home/omar/ai-projects/research-system-rag/.claude/worktrees/paper-author-org-tagging
git add app/exp_author_org_tagging.py
git commit -m "Add author-org-tagging extraction-method validation experiment"
```

(The scratch DB/blob dir from Step 2 and `/tmp/waymo_positive_set_ids.txt` are throwaway —
`/tmp/app_ingest_scratch_*` per `_scratch_overrides()`'s own naming — no cleanup commit needed,
they're outside the repo entirely.)

---

## Self-Review

**1. Spec coverage:**
- §4 Step 1 (both extraction methods) → Tasks 2 (rule-based) and 3 (LLM-based).
- §4 Step 2 (org-matching) → Task 2's `match_known_orgs`.
- §4 `mentions_orgs` → Task 2.
- §5 `contracts/author_orgs.py` → Task 1.
- §6 validation experiment (positive/negative sets, precision AND recall, decision rule) → Task 4.
- §3 non-goals (summarizer-prompt injection, backfill, per-author attribution) → correctly absent
  from this plan's tasks.
- §7 backward compatibility, §5's remaining contract changes, §8 open items → correctly deferred
  to the follow-up wiring plan (this plan produces no `contracts/document_store.py`/
  `contracts/vector_index.py`/`contracts/mcp_server.py`/`app/assembly.py` changes at all).

**2. Placeholder scan:** none found — every step has real, complete code or a concrete command;
Task 4 Step 5's "write up the decision" is a genuine judgment call on real experiment output, not
a stand-in for missing design work (the decision CRITERIA are already in the spec §6).

**3. Type consistency:** `extract_affiliations_rule_based`/`OllamaSummarizer.extract_affiliations`
both return `list[str]` (raw affiliation strings); `match_known_orgs`/`mentions_orgs` both take
compatible inputs and return `list[str]` (org names) throughout Tasks 2-4, consistently.
