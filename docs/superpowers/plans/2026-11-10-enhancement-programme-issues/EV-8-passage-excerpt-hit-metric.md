Title: EV-8: Add an excerpt-containment passage metric that honours alternative gold chunks
Labels: wave:1-no-gpu, area:eval, size:M

## EV-8 -- Add an excerpt-containment passage metric that honours alternative gold chunks

**Review cross-reference:** S-03. **Wave:** W1 do now, no GPU.

**Why.** `load_questions` never reads `alternative_gold_chunk_ids`, so passage hit is under-counted by up to 13% of items (papers 8 of 61, books 4 of 74) and scoring by chunk identity makes the sets incomparable across any re-chunk (RV-3 F-1.5, review S-03). Anchor-equality also credits any fragment of the gold block (5 of 119 gold anchors are shared by a sibling chunk: about 4% lenient false hits; RV-1 F-1.3).

**Scope.**
- In:
  - Additive metric `passage_excerpt_hit`: a returned `passage_text` contains the normalised gold excerpt or an alternative's excerpt (reuse `retrieval_eval._normalized`; alternatives resolved through the document store the harness already holds). Items with a null `excerpt_block_id` (excerpt spans blocks) fall back to the anchor rule and are listed separately.
  - The anchor rule stays byte-identical and the report stamps `scoring_rule` for both. State in the docstring how this relates to EV-6's member-passage metric (`scripts/eval_strata_report.py`) and the frozen protocols; if the names collide, add an addendum rather than redefining.
- Out (explicitly):
  - Editing any ground-truth file (EV-11). Chunk ids in reports (EV-9). Changing the Waymo frozen scoring rule.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring defining `passage_excerpt_hit`, its null-excerpt fallback and the ceiling arithmetic (an item can only be a hit if the excerpt is in some chunk the pool can contain)
② failing test: FakeRetriever returning an alternative chunk is a hit under the excerpt rule and a miss under the anchor rule
③ implementation to green; `scoring_rule` stamp
④ report fields and by-stratum split added

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_retrieval_eval.py -o addopts="--disable-socket"`
- Existing Waymo-fixture scoring tests unchanged and green (anchor rule untouched)

**Acceptance / falsification criterion.** A FakeRetriever test returning an alternative chunk is a hit under the excerpt rule and a miss under the anchor rule; Waymo anchor-rule results are byte-identical on the existing test fixtures. This is an instrument, not a retrieval change: its ceiling check is that on the gold chunk itself the excerpt metric equals 1 for every non-null-excerpt item. Falsified if the gold chunk fails its own excerpt check on any fixture item.

**Gates / depends on.** Depends on: EV-7 (ordering only: same file, not a data dependency). Gates: EV-9, EV-11, EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Two metrics diverge in meaning from EV-6's member-passage metric and confuse later reports. Mitigation: the docstring reconciliation and one stamped `scoring_rule`. Rollback: revert; additive.

**Docs to update in the same PR.** Section 2: the new `passage_excerpt_hit` report fields. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
