# O-2: GROBID 500s — root cause and fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop one blank reference string from failing reference extraction for an entire paper.

**Architecture:** A filter in `rag/parser.py::_fetch_references` that drops empty/whitespace-only entries before the batched GROBID POST, plus a WARNING naming the paper and the number dropped so the scale of MinerU's blank-extraction problem is measurable.

**Tech Stack:** Python 3.12, `httpx`, pytest.

---

## Root cause — reproduced deterministically against the live GROBID (v0.8.0)

```
1 citation                 -> 200
1000 citations (130 KB)    -> 200     <- not volume
one 60 KB citation         -> 200     <- not length
empty citation             -> 500     <- THIS
whitespace-only citation   -> 500     <- and this
3 good + 1 empty           -> 500     <- one bad entry kills the whole batch
3 good, no empty           -> 200
```

`_fetch_references` (`rag/parser.py:607`) sends **every** extracted reference in a single batched
POST to `/api/processCitationList`. When MinerU's extraction yields even one blank entry — a stray
line, a page artifact, an empty list item — GROBID returns **HTTP 500 for the whole batch**, so
reference extraction fails for the entire paper and the paper is quarantined.

**This is not a service problem and no retry can fix it.** The same input produces the same 500
every time, which is exactly why these papers failed identically on every run despite being
recorded as `TransientError` by `_fetch_references`'s own `except httpx.HTTPError` handler.

Live corpus, 2026-08-01: **16 GROBID quarantines — 10 × HTTP 500, 6 × unparseable TEI.**

**Scope note:** this plan fixes the 10 × 500. The 6 × `unparseable TEI` are a *different* failure
(GROBID returned 200 with malformed XML) and are explicitly **out of scope** — do not attempt them
here. Record what you learn about them in the report if anything surfaces, but change nothing.

## Operator decisions (2026-08-01)

1. **Drop blank references entirely — but count them**, so the size of the underlying MinerU
   blank-extraction problem is visible. A blank reference carries no title, DOI, or arXiv id; there
   is nothing citable to preserve.
2. **No targeted re-ingest.** The 16 quarantined papers keep their cached PDFs, and quarantine does
   not block retry for `TransientError`, so the next ordinary build run picks them up with the
   fixed code. **Do not run an ingest against the real corpus.**

## Global Constraints

- **Do not modify** `contracts/`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`, `app/build_corpus.py`, or `app/prefetch_pdfs.py`.
- `rag/parser.py` is the **only** file permitted to name `mineru`/`grobid` tokens (`ci/checks/vendor_isolation.py` scopes them there). Keep every GROBID reference inside that file — a mention in another module fails check (a).
- **Never** write `<data_dir>/config.yaml` (mtime must stay `2026-07-17 12:22:42`), `tag_pool.json`, or `papers.db`. No ingest, rechunk, delete, snapshot, or corpus run.
- Do not restart or stop the operator's dashboard; it is running and is their control surface.
- Never `git stash`; never merge a PR; never `--admin`.
- Never add `Co-authored-by: Claude`, `Claude-Session:`, or "Generated with Claude Code" to any commit or PR body.
- Environment: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && <cmd>` — ONE shell call.
- Report real exit codes: `rc=$?` on the line **immediately** after the command, never after `echo`, never through a pipe.
- **Step zero:** `git fetch origin && git checkout -b grobid-empty-citation-fix origin/main`.
- Run pytest in the **foreground**; read its exit code. Do NOT write output to a shared `/tmp` path and poll for a summary string.
- Enforcement needs a synthesized payload (`labels` read without `.get`; `number` optional):

  ```bash
  EV=$(mktemp) && printf '{"number":0,"labels":[],"pull_request":{"base":{"sha":"%s"},"head":{"sha":"%s"}}}' \
    "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV"
  source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
    GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" python -m ci.run_enforcement
  rc=$?
  ```

- A PR is not done until `gh pr checks <n>` shows **both** `enforcement` and `unit-tests` as `pass`.

---

### Task 1: Filter blank references, and count them

**Files:** Modify `rag/parser.py` (`_fetch_references` at line 607, and its call site at line 288). Test: `rag/test_parser.py`.

**Interfaces:** `_fetch_references(raw_refs: list[str], grobid_url: str, paper_id: str) -> list[Reference]` — gains `paper_id` so the warning can name the paper. `paper_id` is already in scope at line 288.

- [ ] **Step 1: Write the failing tests**

`rag/test_parser.py` already injects fake `httpx` transports for this adapter — follow that
existing pattern rather than inventing a new one.

```python
def test_fetch_references_drops_blank_citations_before_posting():
    """A single empty or whitespace-only citation makes GROBID return HTTP 500 for the WHOLE
    batch (reproduced against GROBID 0.8.0, 2026-08-01), so one stray blank line from MinerU
    failed reference extraction for an entire paper. Verified: '3 good + 1 empty' -> 500,
    '3 good' -> 200."""
    posted = {}

    def handler(request):
        posted["body"] = request.content.decode()
        return httpx.Response(200, text=_TEI_WITH_TWO_BIBLSTRUCTS)

    # ... install handler via the module's existing MockTransport pattern ...
    refs = parser._fetch_references(
        ["Pearl, J. (2009). Causality.", "", "   ", "Rubin, D. (1974)."],
        "http://grobid.local",
        paper_id="2504.21062",
    )

    # Only the two real citations reach GROBID.
    assert posted["body"].count("citations=") == 2
    assert "Pearl" in posted["body"] and "Rubin" in posted["body"]
    # And only real ones come back -- a blank reference has no title, DOI or arXiv id to keep.
    assert [r.raw for r in refs] == ["Pearl, J. (2009). Causality.", "Rubin, D. (1974)."]


def test_fetch_references_logs_how_many_blanks_were_dropped(caplog):
    """Operator decision: drop them, but count them -- the number is how we learn how big the
    underlying MinerU blank-extraction problem is."""
    # ... handler returning a valid TEI ...
    with caplog.at_level(logging.WARNING):
        parser._fetch_references(
            ["Pearl, J. (2009). Causality.", "", "  ", "\n"],
            "http://grobid.local",
            paper_id="2504.21062",
        )
    msg = caplog.text
    assert "2504.21062" in msg
    assert "3" in msg          # three blanks dropped


def test_fetch_references_all_blank_makes_no_grobid_call_at_all():
    """Every reference blank => nothing to ask GROBID about. Posting an all-blank batch is the
    exact 500 this fixes, so it must not be sent."""
    called = []

    def handler(request):
        called.append(1)
        return httpx.Response(200, text="<TEI/>")

    refs = parser._fetch_references(["", "   ", "\t"], "http://grobid.local", paper_id="x")
    assert refs == []
    assert called == [], "must not POST when every citation is blank"


def test_fetch_references_unchanged_when_nothing_is_blank():
    """Regression guard: the ordinary path must be byte-identical to before."""
    # assert the posted body contains exactly the citations given, in order
```

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest rag/test_parser.py -k "blank or fetch_references" -v
rc=$?
```

- [ ] **Step 3: Implement**

In `_fetch_references`, before building the request:

```python
    # A single empty/whitespace-only citation makes GROBID return HTTP 500 for the ENTIRE batch
    # -- reproduced against GROBID 0.8.0 on 2026-08-01: "3 good + 1 empty" -> 500, "3 good" -> 200,
    # while 1000 citations / 130KB and a single 60KB citation both return 200 (so it is neither
    # volume nor length). MinerU's extraction yields a blank entry often enough that this failed
    # reference extraction for 10 papers, each quarantined as a TransientError that no retry could
    # ever clear.
    kept = [r for r in raw_refs if r.strip()]
    dropped = len(raw_refs) - len(kept)
    if dropped:
        # Counted, not silent: the number is how we learn how big MinerU's blank-extraction
        # problem actually is (operator decision, 2026-08-01).
        logger.warning(
            "parser: dropped %d blank reference(s) of %d before GROBID for paper %s",
            dropped, len(raw_refs), paper_id,
        )
    if not kept:
        return []
```

Then send `kept` (not `raw_refs`) in the POST **and** pass `kept` to `_parse_grobid_tei` — the
latter zips GROBID's `biblStruct` list against the raw strings **by index**, so passing the
unfiltered list would misalign every reference after the first blank. This is the subtle way to get
the fix wrong; make sure the test above would catch it.

Update the call site at line 288 to pass `paper_id`.

- [ ] **Step 4: Run the tests**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest rag/test_parser.py -q
rc=$?
```

Expected `rc=0` with every pre-existing `test_parser.py` test still passing.

- [ ] **Step 5: Verify against the REAL GROBID — read-only, no corpus writes**

The service is live at `localhost:8070`. Prove the fix's premise still holds:

```bash
python3 - <<'PY'
import urllib.parse, subprocess
good = "citations=" + urllib.parse.quote("Pearl, J. (2009). Causality. Cambridge University Press.")
for label, body in [
    ("3 good + 1 empty", "&".join([good, good, "citations=", good]) + "&consolidateCitations=0"),
    ("3 good (filtered)", "&".join([good, good, good]) + "&consolidateCitations=0"),
]:
    out = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-m", "60", "-w", "%{http_code}",
         "-X", "POST", "http://localhost:8070/api/processCitationList",
         "-H", "Accept: application/xml", "--data", body],
        capture_output=True, text=True).stdout
    print(f"{label} -> HTTP {out}")
PY
rc=$?
```

Expected: `500` then `200`. Report both verbatim. This only POSTs to GROBID; it touches no corpus
data.

- [ ] **Step 6: Full suite and enforcement** — both `rc=0`.

- [ ] **Step 7: Commit, push, open the PR**

```bash
git add rag/parser.py rag/test_parser.py
git commit -m "Drop blank references before the GROBID batch call

One empty or whitespace-only citation makes GROBID return HTTP 500 for the
ENTIRE batch -- reproduced against GROBID 0.8.0: '3 good + 1 empty' -> 500,
'3 good' -> 200, while 1000 citations/130KB and a single 60KB citation both
return 200 (neither volume nor length). MinerU emits a blank entry often
enough that this failed reference extraction for 10 papers, each quarantined
as a TransientError no retry could ever clear.

Blanks are dropped and COUNTED -- the log line is how we learn how big the
underlying blank-extraction problem is. The filtered list is passed to
_parse_grobid_tei too, since it zips biblStructs against raw strings by index."
```

PR title: `O-2: drop blank references before the GROBID batch call`. Do **not** merge. Poll
`gh pr checks <n>` until final; both must `pass`.

---

## Report contract

Write your report to the path given in your dispatch. Return only: status, commit SHA, PR number, real `rc` for pytest and enforcement, the Step 5 live GROBID output verbatim, confirmation that no corpus/ingest command was run and `config.yaml`'s mtime is unchanged, and the final CI conclusion for each check by name.
