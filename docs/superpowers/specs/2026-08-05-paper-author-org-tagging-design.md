# Paper Author-Org Tagging — Design

## 1. Context and motivation

Motivated by the Waymo AV-safety corpus expansion (`docs/superpowers/plans/2026-08-05-waymo-corpus-expansion.md`):
the user wants to ask the RAG system questions like "what tools did Waymo implement?" or "which
of these papers were actually written by Waymo's own team, versus researchers elsewhere using
Waymo's public datasets?" Today the corpus has no notion of paper authorship/affiliation beyond
the raw `authors: list[str]` string already stored on every `PaperRef`/`PaperRecord` — there is no
queryable, filterable signal for "who wrote this" at the organization level.

This is explicitly meant to generalize beyond Waymo: the user will keep dropping in PDFs from
other sources (OpenAlex, Waymo's own research pages) via `drop_in/`, and wants the same mechanism
usable for other organizations later, without a redesign each time.

## 2. Goals

- For every paper in the corpus (arXiv-harvested or drop-in PDF), determine: (a) which known
  organizations' authors actually wrote it, (b) which known organizations are merely *mentioned*
  in the paper (e.g. "we evaluate on the Waymo Open Motion Dataset") — these are different facts
  and must not be conflated.
- Make both facts queryable via the existing MCP tools (`search_papers`, `semantic_search`,
  `get_paper`), following the exact pattern already established for `doc_type` filtering.
- Adding a second organization later must not require re-parsing the corpus — only a cheap,
  re-runnable matching pass.
- Minimize both false positives (tagging a paper as Waymo-authored when it isn't) and false
  negatives (missing a real Waymo author) — validated empirically, not assumed.

## 3. Non-goals

- Per-author affiliation attribution (which specific co-author belongs to which affiliation,
  for multi-affiliation papers). We only need paper-level presence: "does this paper have *any*
  author affiliated with org X" — not who, specifically. This sidesteps needing to correlate
  superscript/footnote markers between author names and affiliation entries, which MinerU's
  block-level text output does not reliably preserve as structured links.
- Injecting the tag into the summarizer's prompt text (`rag/summarizer.py`). Raised during design
  as a possible follow-on (surfaces the fact via semantic search too, not just exact filters) but
  deferred — out of scope for this spec, revisit once the extraction/matching pipeline below is
  shipped and validated.
- Backfilling the tag onto the existing 12,390-paper causal-inference corpus. The mechanism must
  not *require* backfill to ship (see §7, legacy-record handling), but running it is a separate,
  later pass — this repo already has precedent for reprocessing stored papers without a full
  re-ingest (`app/reindex_idf.py`, `app/rechunk.py`).

## 4. Architecture: two-step pipeline

Splitting into two steps (rather than one "is this a Waymo paper" computation) is the central
design decision, and it directly serves the "generalize later" goal: extraction is the expensive
step (an LLM call or a parse-time regex scan); org-matching against extraction's output is cheap
string matching, re-runnable any time — including for a brand-new org added long after a paper
was first ingested — with **zero re-parsing**.

### Step 1 — Extraction: `raw_affiliations: list[str]`

General-purpose, no knowledge of Waymo or any specific organization. For a given paper, produces
whatever institutional affiliations are actually stated for its authors (e.g.
`["Waymo LLC, Mountain View, CA", "Massachusetts Institute of Technology"]`, or `[]` if none are
stated/extractable).

Runs once per paper, at the point where `PaperRecord` is assembled — i.e. **after** parsing, not
at harvest time, because the affiliation text only exists once `ParsedDoc.blocks` exists (arXiv's
metadata API does not carry structured affiliations; MinerU's parsed output is the only source
that has the actual printed affiliation text).

**Input scoping — the "first page, candidate affiliation region" heuristic:**
Real papers vary in where/how affiliations are printed (byline-adjacent, numbered/superscript
footnotes, a separate block), so the input isn't a fixed "the third paragraph" assumption. The
candidate region is: every `Block` (from `contracts/provenance.py::Block`) on page 0 where
**either** `section_path == ""` (MinerU's front-matter marker — see `rag/parser.py`'s
`_SectionTracker` comment: `text_level == 1` is excluded from section tracking specifically so
front-matter blocks — authors, affiliation, date — get `section_path == ""`) **or** the block's
text contains `@` (a corresponding-author email is a strong positional signal for "the affiliation
line is near here," per the design discussion — most papers list at least one email near the
affiliation statement). This is deliberately layout-position-agnostic beyond "front matter or has
an email," rather than assuming a fixed block index or page region.

**Two extraction methods to validate empirically (§6), not both necessarily shipped:**

- **Rule-based (regex)**: within the candidate region's text, (a) extract email addresses
  (`[\w.+-]+@[\w-]+\.[\w.-]+`) and check each domain against `KNOWN_ORGS` entries'
  `email_domains` (e.g. Waymo → `waymo.com`) — the higher-precision signal, since a `@waymo.com`
  address is hard to have without being employed there; (b) as a secondary signal, substring-match
  each org's keyword (e.g. "waymo") case-insensitively against the same region's text, catching
  affiliations printed without an accompanying email.
- **LLM-based**: one Ollama call per paper (reusing this repo's existing summarizer
  infrastructure — see `rag/summarizer.py`'s `_PROMPTS` dict pattern, which already supports
  multiple prompt "kind"s; this would add a new kind rather than a new LLM integration), scoped to
  page-0 text only (bounded context, cheap). Prompt requirements (both error directions must be
  engineered against, not just recall):
  - Explicitly instruct extraction of **only** affiliations *literally stated* in the given text
    — no inferring an author's employer from their name, nationality, or prior/outside knowledge.
    This is the false-positive guard.
  - Explicitly instruct scanning the **entire** given text, not just an assumed byline position —
    catches footnote-style/numbered affiliations elsewhere on the page. This is the false-negative
    guard.
  - Output: a JSON array of strings, `[]` if none stated. No categorization, no judgment calls —
    literal extraction, mirroring this repo's existing summarizer-prompt philosophy of never
    asking the model to state something it can't verify from the given text (see
    `rag/summarizer.py`'s `_SUMMARY_PROMPT` comment on the earlier book-summary hallucination
    incident this pattern already guards against elsewhere).
  - The prompt is iterated against the validation set (§6) until both false-positive and
    false-negative rates are acceptable — not shipped after a single untested draft.

### Step 2 — Org matching: `authored_by_orgs: list[str]`

Deterministic, cheap, re-runnable without touching the parsed document at all: keyword-match
`raw_affiliations` (Step 1's already-extracted, already-stored output) against `KNOWN_ORGS`
(`contracts/author_orgs.py`, a plain data constant — `list[AuthorOrgTag]`, each with an org name
and keyword(s)/domain(s) to match; Waymo is the first entry). Adding org #2 later, or re-scanning
the whole corpus for a newly-added org, is a matter of re-running this step over already-stored
`raw_affiliations` values — no re-parsing, no re-running the (potentially LLM-based) extraction
step.

### `mentions_orgs: list[str]` — separate, unchanged from earlier design iterations

A weaker, topical signal, independent of authorship: does the org's keyword appear anywhere in
the paper's `title`/`abstract` (from `PaperRef`, available at harvest time — this one *can* run
before parsing)? This catches "uses the Waymo Open Motion Dataset" papers by researchers with no
Waymo affiliation at all. Must not be conflated with `authored_by_orgs` — a paper can mention
Waymo without any Waymo author, or vice versa (unlikely but not impossible — an internal
methodology paper that never names "Waymo" in its abstract).

## 5. Data model changes

- `contracts/author_orgs.py` (new): `AuthorOrgTag` (org name, `email_domains: list[str]`,
  `keywords: list[str]`), `KNOWN_ORGS: list[AuthorOrgTag]` constant. Waymo entry seeded from
  `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md`.
- `contracts/document_store.py::PaperRecord` (existing, CODEOWNERS-protected): add
  `raw_affiliations: list[str] = Field(default_factory=list)`,
  `authored_by_orgs: list[str] = Field(default_factory=list)`,
  `mentions_orgs: list[str] = Field(default_factory=list)`.
- `contracts/vector_index.py`: `SearchFilters` gets `authored_by_orgs: list[str] | None = None`
  and `mentions_orgs: list[str] | None = None` (any-overlap match, exactly mirroring the existing
  `categories: list[str] | None` field's semantics). `VectorPayload` gets the same two fields
  (mirroring `doc_type`'s presence there).
- `contracts/mcp_server.py::PaperSummaryView`: add `authored_by_orgs: list[str]` and
  `mentions_orgs: list[str]` to `get_paper`'s return shape. (`raw_affiliations` is Step 1's
  internal/intermediate output — not necessarily exposed on this view; a planning-time decision,
  not blocking this spec.)
- `rag/author_org_tagger.py` (new): the Step 1 (`extract_affiliations`) and Step 2
  (`match_known_orgs`) functions, plus the `mentions_orgs` title/abstract check. Pure functions,
  no I/O beyond Step 1's LLM-based variant if that's the one validation selects.
- Wiring: `app/assembly.py`, at the seam where `PaperRecord` is currently constructed from
  `PaperRef` + `ParsedDoc` (exact call site to be identified during planning — this file already
  assembles both pieces, per `contracts/document_store.py::PaperRecord`'s `ref`/`parsed` fields).

## 6. Validation experiment

Follows this repo's existing `app/exp_*.py` convention (e.g. `app/exp3_hierarchy_sim.py`,
`app/exp_tdoc87_marker_repair.py`) — a throwaway/standalone script that validates an approach
against real data before it's wired into the pipeline, not a permanent module.

- **Positive set**: ~10 real papers by known Waymo authors — sourced from the Waymo corpus
  expansion's `au:Kusano_K`/`au:Scanlon_J`/`au:Favaro_F`/`au:Engström_J` author-field query hits
  (arXiv's own author-field search, high-confidence ground truth), parsed through the normal
  pipeline to get real `ParsedDoc.blocks`.
- **Negative set**: ~30 papers sampled from the existing 12,390-paper causal-inference corpus —
  already parsed (zero additional parse cost), near-certain non-Waymo, giving a real
  false-positive signal against genuine paper layouts (not synthetic test fixtures).
- **Metrics, both directions, for each candidate method** (rule-based, LLM-based): precision
  (of papers flagged Waymo-authored, how many really are — false-positive rate) and recall (of
  the known-Waymo positive set, how many were actually caught — false-negative rate).
- **Decision rule**: whichever method (or combination) achieves acceptable precision/recall on
  both sets is shipped; a losing method is dropped rather than kept as permanent dead weight in
  the codebase. If the rule-based method alone proves accurate, the LLM call (and its
  cost/latency) is avoided entirely — this is the "if the more general method proves accurate,
  make it the sole approach" outcome the user asked to test for, applied to method choice, not
  only to the earlier roster-vs-affiliation-location question this design already resolved in
  §4 (the author-roster idea from earlier design iterations is fully superseded by
  `KNOWN_ORGS`-based matching over extracted `raw_affiliations` — no separate roster-of-names
  concept remains in this design).

## 7. Backward compatibility

The 12,390 already-stored papers (and any future paper ingested before this feature merges) have
no `authored_by_orgs`/`mentions_orgs` payload keys in their stored `VectorPayload`, and no such
fields in their stored `PaperRecord` (pydantic `default_factory=list` handles this gracefully on
load — a missing optional field with a default is not a validation error under
`contracts/_base.py::FrozenModel`'s `extra="forbid"` config, which only rejects *unexpected extra*
keys, not *missing* ones with defaults).

Filtering must treat a legacy point's missing payload key as "no orgs" rather than erroring or
excluding it unexpectedly from unrelated queries — mirroring the exact existing fallback this
repo already uses for legacy points missing `doc_type`
(`rag/vector_index.py:141-150`'s `IsEmptyCondition` handling). This is a hard requirement, not an
optimization: it's what makes backfill genuinely optional rather than a shipping blocker.

## 8. Open items for the implementation plan (not blocking this spec)

- Exact call site in `app/assembly.py` for the Step 1/Step 2 wiring.
- Whether `raw_affiliations` itself is exposed on `PaperSummaryView` or kept internal.
- Exact `KNOWN_ORGS` Waymo entry's `email_domains`/`keywords` values (straightforward — "waymo",
  `waymo.com` — but worth a single confirming look during planning, not a design-level question).
- Summary-prompt injection (§3 non-goal) — explicitly deferred, not forgotten; worth a follow-up
  spec once this ships and its accuracy is confirmed in practice.
