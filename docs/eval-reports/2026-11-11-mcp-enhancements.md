# MCP surface enhancements MC-5a..e and MC-4 (2026-11-11)

Source: `docs/eval-reports/data/2026-11-10-system-review/RV-4-mcp-surface.md` (F-4.6 to F-4.9, F-4.11) and the parked ticket
MC-4. Branch `MC-5-mcp-enhancements`, one commit per item, not merged. No GPU, no service start/stop, no writes to any
`papers.db` or collection. `contracts/`, `migrations/`, `rag/config.py`, fakes, fixtures and CI are untouched.

## What changed, per item

| item | commit | before | after | tests |
|---|---|---|---|---|
| MC-5a cap `section_paths` | `fde471c` | `search_papers` shipped every distinct section path of every hit (standards median 68 = about 820 tokens per hit, max 1,285 = about 45k) | at most `_MAX_SECTION_PATHS = 30` paths (`rag/mcp_server.py`), then one marker entry `[truncated: first 30 of N section paths; get_paper returns all]`. `PaperSummaryView` is a frozen contract with no flag field, so the marker rides in the list. `get_paper` is unchanged (all paths) | `rag/test_mcp_server.py` |
| MC-5b `get_section` subtree | `af02bf5` | exact `section_path` match only | exact match first: unchanged, plain list, uncapped. If no block has that exact path: clause prefix (`9.4` matches the heading segment "9.4 ..." and everything beneath it, not `9.41`) or case-insensitive substring (non-digit queries). Returns `{blocks, truncated, total_blocks, matched_section_paths}` in document order, blocks capped at `_MAX_SECTION_BLOCKS = 100`. No new tool | `rag/test_mcp_server.py` |
| MC-5c `section_pattern` | `3f3ee2f` | `scan_corpus` filtered on text only | optional case-insensitive regex on `section_path`, ANDed with the text pattern (`pattern=""` takes every block of the matching sections); unset behaves exactly as before. Bad regex raises `ContractError` | `rag/test_document_store.py`, `rag/test_mcp_server.py` |
| MC-5d scoped cap | `b964d7c` | `max_hits_per_paper` applied with `paper_id` set, so `k` was unreachable (11 of 14 short standards results) | `Retriever.retrieve` ignores the cap when `filters.paper_id` is set. `retrieve_papers` already relaxed the cap when scoped | `rag/test_retriever.py` (`paper_id` + cap 2 + `k` 5 returns 5) |
| MC-5e error text | `7d3944a` | `get_paper: unknown paper_id 'X' [serving collection=C db=/abs/path]`; `scan_methods` ambiguity raised `ValueError` | `...unknown paper_id 'X'; use search_papers or corpus_stats to find a valid id [serving collection=C]`, plus the `arxiv:` prefix hint when the id has that prefix. Same text from `get_paper`, `get_section`, `get_figures` and the `filters.paper_id` check. `rag/method_aliases.resolve_method` raises `ContractError` | `rag/test_mcp_server.py`, `rag/test_method_aliases.py` |
| MC-4 wire projection | `97495e8` | full contract models on the wire | see below | `rag/test_mcp_server.py`, `app/test_serve.py`, `app/test_usage_log.py`, `scripts/test_mcp_wire_tokens.py` |

Self-description (`rag/mcp_server.py::build_instructions`, `app/serve.py` tool and filter docstrings): one `Recipes` line covering
`get_section` prefix, `section_pattern`, the scoped-cap rule, the find-similar recipe
(`search_papers(query=get_paper(id).summary_text)`) and the omitted fields. The word bound on the instructions test went from 190 to
220 (about 300 tokens).

## MC-4: the projection

Operator ruling 2026-11-11: the MCP wire may be a lean projection of the frozen result contract. Implemented as
`rag.mcp_server.to_wire` (`model_dump(mode="json", exclude=...)`), called from `app/serve.py` for `semantic_search`,
`search_papers` and `get_paper`. Dropped from each passage result: `anchor.bbox`, `anchor.snippet`, `anchor.paper_id`,
`citation.paper_id`, `anchor.section_path` (equal to `citation.section_path` for 400 of 400 sampled chunks; the citation copy
is kept), and `evidence_tier`/`metadata` while they hold their V0 defaults (`"A"`, `{}`; a populated value is still sent).
`passage_text`, score, the result's own `paper_id` and all other citation content are identical. `search_papers` and `get_paper`
drop `citation.paper_id` (the view's `paper_id` stays).

`get_span` round trip: it needs only `anchor.block_id` (`DocumentStore.get_span` returns `get_block(block_id).text`). The tool
now takes a local model `_AnchorRef` (only `block_id` required, extras ignored) and calls the new `McpServer.get_span_text`, so a
slim wire anchor and a full contract anchor both work. Tests: the slim anchor from a projected response resolves; a full anchor
still validates through the tool's own argument model; the real stdio run below resolved a slim anchor.

### Token measurement (`python -m scripts.mcp_wire_tokens --db <papers.db>`)

Method as RV-4 F-4.6: standards `papers.db` opened `mode=ro`, 400 random chunks of at least 150 chars, 200 random response
batches per k, real `SearchResponse` models, `cl100k_base` via tiktoken, serialised as FastMCP does (`indent=2`), median.

| k | full contract | wire projection | change |
|---|---|---|---|
| 5 | 2,518 | 1,846 | -26.7% |
| 10 | 5,060 | 3,679 | -27.3% |
| 25 | 12,528 | 9,145 | -27.0% |

The bar (standards k=10 at least 25% smaller) is met. Note the three fields the ticket named (bbox, snippet, repeated paper_id)
alone gave -19.5% (4,071); the bar was reached by also dropping the duplicated `anchor.section_path` and the constant
`evidence_tier`/`metadata`. Absolute numbers are higher than the review's 4.2k because the review's figure is not `indent=2`
(compact serialisation of the full model is 4,692 on this sample); the percentage is what matters.

## What did NOT change

- `contracts/` and every protected path; the tool count (ten).
- Exact-path `get_section` (list, uncapped); `get_paper` section paths; `scan_corpus` without `section_pattern`.
- `retrieve_papers` cap behaviour; the frozen eval harness passes `filters=None` to `retrieve` (`app/retrieval_eval.py:683`) and no
  eval script combines `paper_id` with `max_hits_per_paper` (checked: `scripts/exp_diversity_strategies.py` and the standards
  `query_batch.py` use the cap without `paper_id`; `scripts/scratch_paperid_filter_eval.py` uses `paper_id` without the cap), so
  the 2026-11-11 baselines are unaffected.
- Not built: the async/thread-offload and lock-timeout part of F-4.9 (the ticket said text only); `get_section`/`get_figures`
  block payloads (still carry `bbox`); the `db=` path still appears in the instructions and `corpus_stats` `serving` string (only
  error suffixes were changed).

## Existing callers: what they now receive

- Search tools return the projected JSON: a client reading `anchor.bbox`, `anchor.snippet`, `anchor.paper_id`,
  `anchor.section_path`, `citation.paper_id`, or an always-present `evidence_tier`/`metadata` breaks. `app/mcp_verify_client.py`
  read `anchor['paper_id']` and was fixed to print `page`.
- `search_papers` section path lists over 30 end with a marker string, not a path.
- `get_section` with a path that is not an exact match used to return `[]`; it can now return the subtree dict.
- `scan_methods` ambiguity is a `ContractError`, not `ValueError`.
- `max_hits_per_paper` plus `paper_id` returns up to `k` results.
- `app/usage_log.py` reads coverage from the dict result, so `result_count`/`candidates` are still logged for search tools.

## How to verify

- Unit tests: `conda run -n agent-rag-research python -m pytest -q rag/test_mcp_server.py rag/test_document_store.py rag/test_retriever.py app/test_serve.py app/test_usage_log.py scripts/test_mcp_wire_tokens.py`.
- Real stdio run (CPU, no embedder): `app.serve` started over stdio against a scratch copy of the standards `papers.db` (so the
  usage log did not touch the real data dir): unknown id with the `arxiv:` prefix returned the new error text; `get_paper` citation
  has no `paper_id`; `get_section` exact path returned a block list, prefix `1` returned the subtree dict (17 blocks, 3 paths);
  `scan_corpus` with `section_pattern` matched; `get_span` with `{block_id, page}` returned the verbatim block. `semantic_search`
  was not run over stdio (needs the embedder/GPU); `app/mcp_verify_client.py` calls it, so it was not run.
- Tokens: `python -m scripts.mcp_wire_tokens --db /home/omar/ai-projects/research-system-rag-standards/data/papers.db --k 5 10 25`.
