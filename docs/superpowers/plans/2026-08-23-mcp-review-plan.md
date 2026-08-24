# MCP review plan — serving students & researchers (method→papers, org→methods/data, synonyms)

Written 2026-08-23. This is the review plan, not the review. Grounded in the live code:
`rag/mcp_server.py` (272 lines, 5 tools), `app/serve.py` (FastMCP stdio composition root),
`contracts/mcp_server.py` (frozen envelope shapes), `contracts/vector_index.py::SearchFilters`
(frozen filter shape). No implementation happens until the review produces findings and tickets.

## 1. Who the MCP must serve, and their actual jobs

Two primary journeys, stated by the operator:

- **J1 — method → papers**: "which papers *implemented* method X, and how?" A student wants the
  papers that USE a method (Methods-section usage), not merely papers that cite it (Related Work).
- **J1b — method → why**: "WHY did they use it?" The rationale/motivation passage — the need that
  drove the choice, constraints cited, alternatives rejected. Typically lives in motivation prose,
  Methods justifications, and ablation discussions; almost never in the method's own name-bearing
  sentence, so a name-matched hit is usually NOT the why-answer.
- **J1c — method → stance**: "do the authors argue FOR or AGAINST other methods?" Comparative and
  contrastive argumentation — positioning against baselines/prior art ("unlike X, …", "X suffers
  from …", "we prefer Y over X because …"). The unit of value is the anchored argument quote, and
  the direction (pro/anti/neutral-toward which method) is the structure a researcher wants kept.
- **J2 — org → methods/data**: "what does organization X do — their methods, their datasets?"
  A researcher reverse-engineering an org's research programme from its publication record.
- **Cross-cutting — synonyms**: a method has many names ("RRF" / "reciprocal rank fusion" /
  "rank fusion"; "LoRA" / "low-rank adaptation"). Any vocabulary-sensitive path fails silently
  when the caller guesses the wrong synonym. J1b/J1c make this worse: the argument about a method
  often uses ONLY the synonym, so synonym recall failure silently drops rationale/stance evidence.

Secondary but in-scope: definition/abbreviation resolution ("what does SGMCMC mean in paper P"),
and the existing honesty contract (no relevance floor; `k` results are best-available, not
endorsements) which must survive any enhancement.

## 2. Current state (verified against code, not memory)

| tool | answers today | journey fit | synonym behavior |
|---|---|---|---|
| `semantic_search(query, filters, k)` | best-k passages, ranked | J1 partially — ranking, not enumeration | dense embeddings give *partial* fuzzy matching; the sparse/lexical arm and the reranker are vocabulary-bound |
| `search_papers(query, filters, k)` | best-k whole papers by summary | entry point for J1/J2 | same as above |
| `scan_corpus(pattern, paper_id, author_org, …)` | EVERY block matching a regex — recall 1.0 *for the pattern given* | J1's real workhorse — but the docstring pushes the synonym burden onto the caller: "widen it (`bootstrap\|resampl\|jackknife`)" | none — the caller hand-writes alternations |
| `get_paper(paper_id)` | summary + section paths + citation | definition resolution, J2 drill-down | n/a |
| `get_span(anchor)` | verbatim block text (citation round-trip) | grounding | n/a |

Structural facts the review must respect:

- **ADR (PRD §11A, agent-as-reasoner):** "this server never auto-rewrites or narrows a query on
  its own" (`rag/mcp_server.py:76-77`). Server-side query expansion *contradicts* this ADR as
  written. Synonym handling is therefore a design fork (§5), not a bug fix.
- **Foundation freeze:** envelope shapes live in `contracts/mcp_server.py`, the filter shape in
  `contracts/vector_index.py::SearchFilters`, and `fixtures/` is protected — any new tool, new
  filter field, or new eval fixture needs T-F7 sign-off. `rag/mcp_server.py` itself, `app/serve.py`,
  and `rag/` internals are free.
- **Org tiers already exist:** `author_org_curated_only` (exact, enumerated) vs the derived
  heuristic (measured precision 0.706 / recall 0.783 — ~3 in 10 wrong). J2's correctness hinges on
  callers actually using the curated tier; nothing aggregates per-org.
- **"Implement vs cite" is unstructured:** `scan_corpus` returns `section_path`, and its docstring
  notes a Methods-section hit is a use while Related-Work is a citation — but nothing computes it,
  and parsing "does not always recover headings" (`""` section paths exist).
- **Datasets are unstructured:** J2's "what data do they use" has no representation at all —
  dataset names live inside chunk text only.
- **MCP usage telemetry exists** (D-series dashboard work) — the review should read what it
  already captures before recommending more.

## 3. Review workstreams (each produces written findings)

### W1 — Journey coverage audit (J1, J2)
Walk both journeys end-to-end as a calling agent would, using only the 5 tools, on real queries.
Record every point where the agent must compensate (hand-written regex alternations, multi-call
fan-out, manual synthesis). Deliverable: a gap table mapping journey step → tool → gap severity.
Known gaps going in (to verify, not assume): no method-implementation enumeration; no org profile
aggregation; no dataset surface; definition resolution works but only if the caller already knows
the paper.

### W2 — Synonym / method-vocabulary review (the operator's core ask)
- Inventory the failure surfaces: sparse-arm lexical matching, `scan_corpus` regex, reranker
  cross-encoder vocabulary sensitivity, and summary-level `search_papers` (summaries are LLM-
  generated — do they even contain the method's alternate names?).
- Build the **method-synonym eval set FIRST** (eval-before-implementation, same discipline as the
  Waymo benchmark programme): ~30–50 items — (method, synonym set, gold papers that implement it) — plus W2b rationale and stance items
  — from the causal-methods corpus where we have operator knowledge. Frozen before any change.
- Measure the baseline: for each synonym, which tools find which gold papers? This quantifies how
  much of the synonym problem embeddings already absorb vs. what needs structure.
- Only then evaluate the §5 design fork with numbers.

### W2b — Rationale & stance review (J1b/J1c)
- **Cue-surface audit**: how much of why/stance is reachable today? `scan_corpus` with cue
  patterns ("in contrast to|unlike|we adopt .* because|suffers from|fails to|outperforms") against
  a handful of known methods; `section_path` distribution of the hits (motivation vs methods vs
  discussion); how often the why/argument passage even names the method vs uses only a synonym
  (this couples J1b/J1c directly to the synonym problem).
- **Summary audit**: do the LLM-generated paper/chapter summaries capture rationale and
  comparative stance today? (They are the `search_papers` matching surface — if summaries omit
  stance, J1c is invisible at summary level by construction.)
- **Eval dimensions added to the frozen set** (authored before any implementation): (i)
  rationale items — (method, gold paper, gold why-passage, verbatim excerpt); (ii) stance items —
  (method A, method B, gold paper, direction pro/anti, gold argument passage, verbatim excerpt).
  Both reuse the GT-WMR authoring discipline: excerpts machine-extracted verbatim, absence items
  for methods with no argued stance, live search logs.
- **Boundary that keeps this V0**: the deliverable is *anchored argument quotes* (who said what,
  where, verbatim) with a direction label where the text states one — never a judgment of who is
  right. Adjudicating claims is V1 reconciliation (CONTEXT.md) and stays out.

### W3 — Org research review (J2)
- Verify curated-tier completeness for orgs beyond Waymo (the curated list mechanism exists —
  `AuthorOrgTag.curated_ids_path` — but only Waymo populates it).
- Prototype-check (read-only, throwaway `app/exp_*` script, not a tool): can "org X's methods and
  datasets" be assembled from `scan_corpus(author_org=X)` + section_paths + existing fields? What
  aggregation is missing?
- Assess dataset-name extraction feasibility (chunk text vs. a structured field — the latter is a
  schema/migration question, foundation-protected).

### W4 — Contracts & foundation boundary map
For every candidate enhancement (new tool, new filter, alias store, dataset field), classify:
free (`rag/`+`app/`) vs T-F7 sign-off (`contracts/`, `fixtures/`, `migrations/`, `rag/config.py`).
Deliverable: the ticket list pre-sorted with sign-off flags, so the operator knows the approval
cost before any work starts.

### W5 — Honesty & grounding invariants
The docstrings carry hard-won contract language (no relevance floor / RI-M7, coverage semantics,
org-tier honesty, "never auto-rewrites"). Review that every proposed change either preserves the
language or explicitly amends it — an enhancement that quietly makes a docstring false is a
contract violation by this repo's standards.

### W6 — Caller ergonomics (the client is an LLM)
Tool-count and docstring-weight review (5 tools, several-hundred-word docstrings each — is the
guidance reachable?), response token weight (GroundedResult payloads), error messages
(`ContractError` text a student-facing agent can act on), `k` clamping behavior. Include the
student angle: can a weak caller model use this surface successfully, or does success require the
docstring-reading discipline of a strong one?

## 4. The synonym design fork (decide WITH W2 numbers, not before)

| option | what it is | ADR impact | cost/risk |
|---|---|---|---|
| A. Caller-side aliasing | ship alias knowledge as MCP tool docstring guidance / a `get_method_aliases` lookup tool; caller expands | none — caller rewrites, server stays passive | aliases must be curated + maintained; weak callers may skip it |
| B. Server-side expansion | retriever-internal OR-expansion over a curated alias map (sparse/lexical paths only; dense untouched) | **amends PRD §11A** — needs an explicit ADR update | deterministic, evaluable; alias map is a maintained artifact |
| C. LLM expansion at the edge | Ollama rewrites the query before retrieval | amends §11A; non-deterministic | latency + eval difficulty; ~0 API cost holds (local) |
| D. Method taxonomy (structural) | a `methods` table: canonical name ↔ aliases ↔ paper links (from scan-style matching, curated overrides) | new migration + contracts — T-F7 | strongest end-state ("papers implementing X" becomes a lookup); most work |
| E. Argument layer (J1b/J1c) | per-method rationale + pro/anti argument quotes with anchors — cue-pattern candidates (scan-style) refined by a local-LLM pass that must return verbatim spans; exposed as a tool (`method_arguments`) or as taxonomy fields on D | D-shape: migration + contracts — T-F7; LLM pass is rag/-internal | turns "which papers" into "which papers, why, and arguing against whom"; the LLM step is evaluable against the W2b stance/rationale gold set; must stay quote-not-verdict (V0 boundary) |

Recommended sequencing (to confirm with W2 data): A immediately (docstring guidance + alias tool
is cheap and unblocks students), then D as the real fix with B as its retrieval bridge, and E
built on top of D's method identity (argument quotes are only as good as the method resolution
under them — E without D re-learns synonyms per query). C only if W2 shows embeddings + aliases
still miss.

## 5. Deliverables & sequencing

1. **Review report** (`docs/eval-reports/` or `docs/`): findings from W1–W6, each with evidence.
2. **Method-synonym eval set + baseline numbers** (frozen fixture — T-F7 flag).
3. **Ticket batch** for `docs/BACKLOG.md` (new MCP series), pre-sorted free-vs-T-F7, each scoped
   against the frozen baseline numbers.
4. Estimated review effort: W1+W3+W5+W6 are mostly read-and-exercise (1 session); W2's eval-set
   authoring is the long pole (similar to GT construction, but smaller); W4 is an hour of mapping.

## 6. Out of scope

No re-litigating settled ADRs (Qdrant, SQLite, Ollama→vLLM, RRF k=60) — PRD §12. No V1 claims/
reconciliation/evidence-tier work (CONTEXT.md phasing). No new vector-store or embedding changes
as part of the synonym fix — the embedder is measured to be the *strongest* synonym path already;
the review may prove otherwise, and that would be a finding, not an assumption.
