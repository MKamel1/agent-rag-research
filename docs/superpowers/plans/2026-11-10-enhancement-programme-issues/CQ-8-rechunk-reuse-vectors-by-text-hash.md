Title: CQ-8: Make rechunk re-embed only chunks whose text changed
Labels: wave:1-no-gpu, area:corpus, size:M

## CQ-8 -- Make rechunk re-embed only chunks whose text changed

**Review cross-reference:** S-14. **Wave:** W1 do now, no GPU.

**Why.** `app/rechunk.py:189` re-embeds every chunk of a re-chunked paper, including unchanged text, which multiplies the cost of every re-chunk the later tickets want (RV-2 F-2.3 step 1; review S-14). Chunk ids are positional, so reuse must key on a text hash, not on the id.

**Scope.**
- In:
  - Look up stored vectors for identical chunk text (hash of the embedded text) in the same collection, reuse them, and embed only new text. Guard: reuse only from the same collection and embedder model name.
- Out (explicitly):
  - Content-addressed chunk ids (explicitly rejected: 'Will not do' table). Changing the chunker. Applying to any live index.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/rechunk.py`
- `app/test_rechunk.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the reuse rule and its guards
② failing test: a text-only change to one chunk of a 10-chunk paper re-embeds exactly one chunk (fake embedder call count)
③ implementation to green
④ dry-run report line 'reused N, embedded M'

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/rechunk.py app/test_rechunk.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_rechunk.py -o addopts="--disable-socket"`
- Mutation proof: disable the reuse path and the call-count test fails

**Acceptance / falsification criterion.** Dry run on a fixture of 10 papers with a text-only change: re-embedded count equals changed-text count and reused count equals the rest; a changed embedder model name disables reuse. Falsified if the call-count test passes with reuse disabled.

**Gates / depends on.** Depends on: none. Gates: EP-3, CQ-15.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A wrongly reused vector silently pairs old text with a new position. Mitigation: vectors depend only on the embedded text (which includes title and section path prefix), guarded by model name. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
