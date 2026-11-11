Title: RIDER-1: Raise the single foundation rider PR with only the adopted items
Labels: wave:4-rider, area:ops, area:eval, area:retrieval, needs-signoff, size:M

## RIDER-1 -- Raise the single foundation rider PR with only the adopted items

**Review cross-reference:** review (D), RV-5 F-5.6, RV-3 F-1.11, RV-6 F-A5, RV-1 F-1.10. **Wave:** W4 rider and what it unblocks.

**Why.** Several adopted changes can only land on protected paths (`contracts/`, `rag/config.py`, `config.example.yaml`, `rag/fakes/`, `fixtures/`, `.github/`), and every unrelated protected-path PR pays the same sign-off toll; batching them into one PR pays it once (`docs/AGENT-OPERATIONS-LESSONS.md` section 6.3). It is raised only after the wave-2 verdicts so only adopted items ride.

**Scope.**
- In:
  - (1) `Config` fields (in `contracts/config.py`, loader/defaults in `rag/config.py`, `config.example.yaml`) for whichever of `drop_stub_chunks` (EV-21), the focus lever (RQ-3) and the query-path `gpu_lock_timeout` (OP-5) were ADOPTED; none if none were.
  - (2) `relevance_filter="embedding"` fails validation until a gate exists (dead lever, RV-5 F-5.6).
  - (3) Only if EV-19's gate opened: the `rerank_score` metadata note in `contracts/retriever.py` and its DATA-CONTRACTS section M7 paragraph.
  - (4) `rag/fakes/fake_vector_store.py` imports the shared `sparse_tokens()` (RQ-5).
  - (5) Promote the three ground-truth sets to `fixtures/eval/` with one parametrised invariants test (unique ids, strata vocabulary, no gold on absent items, 6-word rule, excerpt verbatim in the live database with a skip when absent) and the SHA-256 in each set's metadata (RV-3 F-1.11), after the hash lock.
  - (6) `.github/`: a `ruff` step in CI and the nightly real-adapter workflow labelled manual-only (RV-6 F-A5).
  - Conditional item 7, present only if F7 = rewrite: DATA-CONTRACTS wording for `Block.section_path` (review S-24 sign-off need).
- Out (explicitly):
  - The `chunker_id` migration (explicitly not doing). Any logic change beyond the listed edits. Pushing to the default branch or merging (human only). Items whose verdict was REJECT or UNDERPOWERED: they drop out, the rider shrinks.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `contracts/config.py`
- `contracts/retriever.py`
- `rag/config.py`
- `config.example.yaml`
- `rag/fakes/fake_vector_store.py`
- `rag/fakes/test_fake_vector_store.py`
- `fixtures/eval/`
- `DATA-CONTRACTS.md`
- `.github/workflows/ci.yml`
- `.github/workflows/nightly-real-adapters.yml`

**Commits** (① is a stub, committed before any real work):
① stub: PR description draft listing each item, its source verdict and the operator decision it needs; empty diff
② items (4) and (5) (no verdict dependency)
③ items (1)-(3) for the adopted set only, each citing its verdict report
④ item (6) and conditional item 7
⑤ local enforcement transcript with the `foundation-change` label noted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check contracts/config.py contracts/retriever.py rag/config.py rag/fakes/fake_vector_store.py rag/fakes/test_fake_vector_store.py`
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (includes the new invariants test)
- `EV=$(mktemp) && printf '{"pull_request":{"number":0,"labels":["foundation-change"],"base":{"sha":"%s"},"head":{"sha":"%s"}}}' "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV" && GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement`
- Mutation proof for the invariants test: edit one question in a copy and watch it fail

**Acceptance / falsification criterion.** One PR only; every protected-path edit is traceable to a listed item with an ADOPT verdict or an operator decision; the invariants test passes on the three promoted sets and fails when one question is altered; the PR carries the `foundation-change` label and waits for the operator's merge. Falsified if the PR touches any protected path not listed.

**Gates / depends on.** Depends on: EV-11, EV-18, EV-19, EV-20, EV-21, RQ-3, RQ-5, OP-5, CQ-18. Operator answers: F4, F7. Gates: RQ-4, EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: y: this ticket IS the sign-off request; the operator merges (never an agent); operator answers: F4, F7 · re-embed: n. Also: operator sign-off and merge; push of the local commits so CI can judge them (F4).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A broad rider is slow to review. Mitigation: items with no adopted verdict are omitted, so it can be small. A wrong Config default could change serving: all new fields default to current behaviour. Rollback: revert the merge (single PR).

**Docs to update in the same PR.** DATA-CONTRACTS section M7 paragraph for item (3) (in this PR); PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.
