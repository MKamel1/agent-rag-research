# CONVENTIONS — engineering guardrails (V0)

Read this before writing any code. It exists to stop the specific mistakes that break a parallel build:
leaked vendors, hidden singletons, silent failures, reinvented shapes, and "works but nobody knows why" code.
It is deliberately opinionated. When in doubt, do the thing this file says, not the clever thing.

The one test behind every rule (Pragmatic Programmer Tip 14): **does this make the system easier to understand
and change, or harder?** If a rule ever clearly makes things harder in a real case, raise it — don't silently
route around it.

---

## 0. Read this first: the build team is AI coding agents, not junior humans

This changes what "guardrails" have to mean. A junior human internalizes a rule after being told once, feels
friction before cutting a corner, and remembers yesterday's code review tomorrow. An AI agent does none of
that by default: each session may start with no memory of a previous correction, it can produce a plausible
-looking wrong shape with total confidence, and — per its own general instructions — it has a bias toward
being "helpful" by refactoring, adding abstractions, or fixing things beyond what the ticket asked for. None
of that is a character flaw to lecture away; it's a property of the workforce, so the mitigations have to be
**mechanical (caught by a machine before merge), not cultural (caught by a colleague's judgment).**

Concretely, for this build:

1. **A rule that only lives in prose is not a guardrail for an agent team — it's a suggestion.** Every rule
   in this file that *can* be checked by a script (§1 vendor imports, §3 no `os.getenv`, §4 no bare `except`,
   "no new shared type outside `contracts/`") **must** be a CI check that blocks merge, not a line item a
   reviewer reads. See §12 — the PR checklist is the spec for that CI job, not a manual chore.
2. **The shared foundation (`contracts/`, `Config`, the SQLite schema, the fakes — Owner F's output) is the
   single highest-blast-radius artifact in the build.** Every other agent codes against it in parallel; if it
   drifts after the fan-out, every module drifts with it and the failure surfaces late, expensively, at
   integration. Protect it like a public API, not a work-in-progress file:
   - It is **frozen** once Owner F's initial pass is reviewed (see WORK-BREAKDOWN M0).
   - **Any agent that believes it needs to change a frozen contract stops and flags it — it does not
     silently redefine a "close enough" local version, and does not patch around a mismatch in its own
     module.** A shape mismatch between a module and `contracts/` is *always* a bug in the module, never
     grounds for a second definition.
   - Changes to `contracts/`, `Config`, the schema, or the fakes require **explicit human sign-off** before
     merge (a CI rule: a diff touching those paths is auto-flagged, not auto-mergeable). This is a
     build-process gate, distinct from the *product's* agent-as-reasoner design (CONTEXT.md) — it's about
     protecting a shared dependency from silent drift, not about the RAG system's own human-in-the-loop
     policy (which is separately, deliberately, rejected — CONTEXT.md "Rejected/non-goals").
3. **Correctness is judged by tests passing against the interface, never by how plausible the code looks.**
   An agent's own confidence in its output is not signal. The contract tests (TEST-STRATEGY.md) are the
   actual arbiter of "did this module get the shape right" — treat a module as unverified until its tests
   are green, not when the agent reports it's done.
4. **No unsolicited scope expansion.** An agent building module X touches module X's files and its own
   tests — nothing else. It does not "while I'm in here" refactor a neighboring module, add a V1/V2 feature
   early (contextual headers are the running example — see §10), or introduce an abstraction not named in
   ARCHITECTURE.md. If a change seems to require touching something outside the ticket's scope, that's a
   signal to stop and flag it, not a green light to expand the diff.
5. **Integrate continuously, not at a big-bang milestone.** Because agents can produce a large diff quickly,
   run each module's tests against the shared fakes on every change, not just at the M2 integration
   milestone (WORK-BREAKDOWN) — catching a seam mismatch same-day is cheap; catching it after five modules
   built on the wrong assumption is not.
6. **Every ticket must be self-contained.** Don't assume an agent picking up a ticket remembers a
   conversation from another session. The reason DATA-CONTRACTS.md, this file, and the per-ticket acceptance
   criteria in WORK-BREAKDOWN.md are written down explicitly — rather than left as "ask the lead" — is that
   they are the only memory a fresh agent session has. Keep them accurate; an agent will follow a stale doc
   exactly as faithfully as a correct one.
7. **Tests are written before the implementation they test, mechanically checked, not left to "normal
   practice."** WORK-BREAKDOWN.md's M1 is split into **M1a (write the failing test suite against the frozen
   interface + fakes) then M1b (implement to green)** — see WORK-BREAKDOWN M1a/M1b. This exists for the same
   reason as points 1–6: an agent with no memory of "how we usually do TDD here" needs the ordering to be a
   gate it hits, not a convention it's assumed to already know.
8. **Depth and information-leakage are the one class of rule this file's mechanical checks cannot fully
   catch.** §12's CI list mechanizes lexical rules (vendor imports, bare `except`, `os.getenv`, contract
   shadowing) well, but "is this module actually deep" or "did a caller reach past an interface it should
   have used" needs a reviewer's judgment — precisely the thing point 0 above says the AI workforce is weak
   at by default. Where a cheap mechanical proxy exists (e.g. grepping for manual `chunk_id`/`block_id`/
   `summary_id` string-slicing outside `DocumentStore`, §12), take it; where none exists, flag it in review
   rather than assuming the mechanical gates already cover it.

---

## 1. The dependency rule (the one that breaks parallel builds if ignored)

**Vendor SDKs live only inside their adapter. Every other module depends on the interface, never the vendor.**

| Vendor / library | May be imported **only** by |
|---|---|
| `qdrant_client` | the `VectorStore` adapter (M6) |
| the embedding client (TEI/vLLM HTTP) | the `Embedder` adapter (M4) |
| MinerU / Marker / Docling / GROBID | `Parser` adapters (M2) |
| the arXiv API client | the `Source` adapter (M1) |
| `sqlite3` | the `DocumentStore` (M5) and `migrations/` — separate seams (applying the schema vs. querying it) that both legitimately touch SQLite directly |
| the cross-encoder client (BGE-reranker-v2-m3 or the Spike-2 choice, ADR-10) | the `Reranker` adapter (used by M7) |
| the local generation-LLM client (Qwen tier, ADR-08; Ollama/vLLM per ADR-09) | the `Summarizer` adapter (M3B) |

If you find yourself typing `import qdrant` in the Retriever, stop — you are dissolving the seam that makes the
database swappable. Go through the interface. The test: **grep the codebase for the vendor name; it must appear
in exactly one module.**

**Dependency direction:** modules depend *downward* on interfaces (`Retriever` → `VectorStore` interface →
Qdrant adapter). Never upward, never sideways into a peer's internals. No import cycles — if two modules import
each other, one of them owns a type that belongs in the shared `contracts/` package.

---

## 2. Accept dependencies, don't create them (no hidden singletons)

Every module **receives its collaborators as constructor/function arguments.** It never reaches out and builds
one, and never reads a global.

```python
# GOOD — testable, swappable
class Retriever:
    def __init__(self, embedder: Embedder, index: VectorStore, docs: DocumentStore, cfg: Config): ...

# BAD — un-testable, un-swappable, hides the real dependency graph
class Retriever:
    def __init__(self):
        self.index = QdrantClient("localhost:6333")   # NO. now every test needs a live Qdrant.
```

Consequences of getting this right: your module is tested with fakes (no GPU, no network), and the DB/model
swap is a one-line change at the composition root. This is not style — it is the whole reason the architecture
has seams.

**Composition root:** exactly one place wires the real adapters together — the orchestrator entrypoint and the
MCP server entrypoint. That is the *only* place `QdrantVectorStore(...)`, `TeiEmbedder(...)`, etc. are
constructed. Nowhere else.

---

## 3. Config: one object, injected (no scattered env reads)

All levers/knobs come from one `Config` object (DATA-CONTRACTS §Config), loaded once at startup and passed
down. **No module calls `os.getenv` or reads `config.yaml`.** A buried `os.getenv("TOP_K", 10)` is exactly the
"buried constant" ADR-18 forbids — the next person will never find it.

---

## 4. Error handling: three classes, and crash early on bugs

Do not invent ad-hoc exceptions per module. Use these three (defined in `contracts/errors.py`, Owner F):

| Class | Means | What the pipeline does |
|---|---|---|
| `TransientError` | temporary (network timeout, 503, rate limit) | retry with backoff (bounded); then quarantine |
| `PermanentError` | this paper is bad (unparseable PDF, corrupt e-print) | **quarantine and continue** — never kills the run |
| `ContractError` | a broken invariant / a bug (a block with no bbox, a vector of wrong dim) | **crash early** — do not limp on |

- **Quarantine, don't swallow.** A `PermanentError` writes a row to the `quarantine` table (paper_id, stage,
  error, ts) and moves on. A bare `except: pass` is a firing-offense bug — it turns a data problem into an
  invisible one. Quarantine is visible and re-runnable.
- **Crash early on `ContractError`** (Pragmatic Programmer "crash early"). If an invariant this system relies
  on is violated, a wrong result is worse than a stack trace. Do not "handle" it by defaulting — that hides
  the bug and corrupts the store. Fail loud, fix the cause.
- **Never catch `Exception` broadly.** Catch the specific class you can actually handle.

---

## 5. Idempotency & resume (the `ingest_state` pattern — do not freelance this)

Juniors reliably get idempotency wrong. Follow the pattern exactly:

1. Before doing a stage's work for a paper, **read its `ingest_state` row**. If it's already past this stage,
   skip.
2. All persistent writes are **upserts keyed by the stable id** (DATA-CONTRACTS §IDs) — never a blind
   `INSERT` that duplicates on re-run.
3. After the stage succeeds, **update `ingest_state`** to the new stage.
4. Because ids are deterministic, re-running the whole 15k job is safe: done papers are skipped, half-done
   papers resume, nothing duplicates.

Do **not** rely on "the file exists so skip" or in-memory sets that vanish on crash. The state table is the
one source of truth for progress.

---

## 6. The single-GPU rule (the hardest constraint — DoD "critical constrained resource")

24 GB holds **one** GPU-bound model at working precision at a time. Embedder, reranker, and any summarizer
**cannot co-reside** — and this has to hold **across processes**, not just within one: `IngestionOrchestrator`
and `McpServer` are separate composition roots (§2) that V0 explicitly allows to run concurrently (a
multi-day ingest next to an always-on query server), so an in-process `threading.Lock` cannot be the
mechanism.

- The mechanism is a typed `GpuLock` (DATA-CONTRACTS.md), constructor-injected into every real
  `Embedder`/`Summarizer`/`Reranker` adapter, backed by a cross-process file lock keyed off
  `Config.gpu_lock_path`. **The adapter acquires the lock itself around its own inference call** — callers
  (`IngestionOrchestrator`, `Retriever`) call `embed()`/`summarize()`/`rerank()` exactly as they would with
  no lock at all. Two GPU stages never run concurrently, in one process or two.
- There is no "or accept the load cost" fallback. If a real GPU-bound adapter's constructor doesn't declare
  a `gpu_lock: GpuLock` parameter, that is a bug, not a judgment call — T-F6 greps for it, same as a vendor
  import outside its adapter (§1, §12).
- If you see CUDA OOM, the answer is almost never "reduce batch size a bit" — it's "two models are resident
  that shouldn't be." Check that both processes are pointed at the same `gpu_lock_path` before anything else.

---

## 7. Design-by-contract at every interface

Each public method states its **preconditions, postconditions, and invariants** in the docstring — and
enforces the preconditions it can cheaply check (raising `ContractError`). Examples juniors miss:

- `embed(texts)` — precondition: `texts` non-empty, no `None`. Postcondition: output length == input length,
  each vector length == `info.dim`, L2-normalized.
- `hybrid_search(qvec, qtext, filters: SearchFilters | None, k)` — precondition: `k >= 1`,
  `len(qvec) == collection dim`. `filters` is the typed `SearchFilters` dataclass (DATA-CONTRACTS §M6) —
  never a raw `dict`; there is no ad-hoc filter grammar to reinvent.
- `get_span(anchor)` — precondition: anchor resolves to a stored block; else `ContractError` (a dangling
  anchor is a grounding bug, not a normal "not found").

"Define errors out of existence where you can" (APoSD): e.g. `retrieve()` on an empty corpus returns `[]`, not
an error — empty is a valid answer. But a *broken invariant* is never defined away.

---

## 8. Never program by coincidence

If you can't say *why* your code works, it doesn't work — you just haven't seen it fail yet. Specifically:

- Don't depend on undocumented behaviour of a parser/DB ("MinerU happens to emit blocks top-to-bottom"). If
  you rely on reading order, assert it.
- Don't tune magic numbers until a test passes and move on. Name the constant, say why, put it in `Config` if
  it's a knob.
- Don't leave a `# TODO: not sure why this is needed` in and ship it. Find out. That comment is a broken
  window (Pragmatic Programmer) — the next person copies the pattern.

---

## 9. Naming & comments (APoSD Ch 13–14)

- **Names carry the meaning.** `chunk_id`, not `cid`/`id2`. A name you struggle to pick usually means the
  thing is doing two jobs — split it.
- **Comments say *why*, not *what*.** `# RRF fuses dense+sparse without needing comparable score scales`, not
  `# loop over hits`. A comment that restates the code is noise; delete it.
- **Interface docstrings describe the contract** (§7), not the implementation. Implementation notes go inside
  the function body, near the code they explain.
- **Consistency beats personal preference** (APoSD Ch 17). Match the shapes in DATA-CONTRACTS and the patterns
  in this file. Don't introduce a second way to do something that already has a way.

---

## 10. Cost landmines (things that are cheap on 10 papers and painful on 15,000)

Confirm the plan before you write these — they are silent budget killers at corpus scale:

- **Contextual headers** = one LLM call *per chunk* → 15,000 papers × one call each. This is **not a V0
  feature at all** — it's cleanly deferred to V1 (PRD ADR-07), not a Spike-2-gated toggle. **Do not
  implement header generation in V0.** V0's only job is to record the monitoring signal (context-poor
  chunk rate, tagged during the Spike-2 eval) so V1 starts with evidence. If you find yourself writing an
  LLM call inside the Chunker, stop — that ticket is out of scope for V0.
- **Re-embedding** the whole corpus is the most expensive operation in the system. Never trigger it casually;
  it's a deliberate model-swap event (ADR-04) via `VectorIndex.rebuild()`.
- **Loading a model per paper** instead of per batch. Load once, process a batch, unload. Model load is
  seconds; doing it 15k times is hours.
- **Unbounded queues / reading the whole corpus into memory.** Stream with iterators (`iter_papers()`), bound
  your queues.

---

## 11. Definition of Done (per module)

A module isn't done when it runs once. It's done when:

- [ ] Its test suite was committed in M1a, against the frozen interface + fakes, **before** this module's
      implementation code existed (WORK-BREAKDOWN M1a/M1b) — not just "tests exist and pass now."
- [ ] Its interface matches ARCHITECTURE.md and uses only shapes from DATA-CONTRACTS.md (no invented types).
- [ ] It accepts its dependencies as arguments; no vendor import outside its own adapter; no `os.getenv`.
- [ ] Preconditions/postconditions are in the docstring and cheaply-checkable ones are enforced.
- [ ] Errors use the three-class taxonomy; no bare `except`.
- [ ] A **fake** exists for it if it sits at a seam (Embedder/VectorStore/Source), matching TEST-STRATEGY.md.
- [ ] Unit tests pass through the interface using fakes — **zero GPU, zero network** for downstream modules.
- [ ] For swap seams: the **contract test** passes against both the fake and the real adapter.
- [ ] `ingest_state` is updated for any stage that does persistent work; failures quarantine, not crash the run.

## 12. Pull-request checklist — automate every checkable item (§0), don't rely on a reader

The first items below are mechanical — grep/static-analysis, no judgment required — and **must run as a
blocking CI job**, not a box a reviewer ticks by eye (§0.1). The last two need a human/reviewing-agent's
judgment and stay as review items.

- [ ] **CI:** grep — does any vendor name (`qdrant`, `mineru`, embedding client) appear outside its adapter
      file? → fail the build.
- [ ] **CI:** does the diff define a dataclass/TypedDict with a name already in `contracts/`, or touch
      `contracts/`/`Config`/schema/fakes without the "foundation change" label + human sign-off? → fail the
      build.
- [ ] **CI:** any `except Exception:` / `except:` in the diff? → fail the build.
- [ ] **CI:** any `os.getenv`/`os.environ` outside the Config loader? → fail the build.
- [ ] **CI:** does the real `Embedder`/`Summarizer`/`Reranker` adapter's `__init__` declare a `gpu_lock:
      GpuLock` parameter? → fail the build if a GPU-bound real adapter omits it (§6).
- [ ] **CI:** does every module source file have a sibling test file that imports its public interface? →
      fail the build if not (§0.7's mechanical existence-proxy; the *ordering* half — test committed before
      implementation — is checked at the M1a→M1b milestone gate in WORK-BREAKDOWN.md, not per-push).
- [ ] **CI:** grep for direct slicing/parsing of `chunk_id`/`block_id`/`summary_id` strings (e.g.
      `.split(":")` on one of these fields) outside `DocumentStore`'s own module → fail the build (§0.8;
      DATA-CONTRACTS §IDs — Retriever/McpServer must resolve via `get_chunk`/`get_block`/`get_summary`).
- [ ] **CI:** run the non-adapter unit-test suites (M1, M3, M5, M7, M8, M9) with network sockets blocked
      (`pytest-socket --disable-socket` or equivalent) and `CUDA_VISIBLE_DEVICES=""` set → any test that
      bypasses its fake and reaches for a live Qdrant/HF download/GPU crashes loudly instead of silently
      passing on a CI box (or local dev machine) that happens to have network or a GPU attached. The
      "downstream tests are zero-GPU/zero-network" rule (TEST-STRATEGY.md golden rule) is otherwise only
      prose — see §0.1: a rule an agent can bypass by reaching for a live dependency isn't a real guardrail.

**These two checks are curated allowlists, not derived.** The vendor-isolation check
(`ci/checks/vendor_isolation.py`, `VENDOR_RULES`) and the GPU-adapter check (`ci/checks/gpu_lock.py`,
`_ADAPTER_SUFFIXES`) only guard the vendor tokens and adapter class-name suffixes actually listed in them — a
green CI run does **not** prove isolation or lock-coverage for a vendor or adapter class that isn't listed yet.
So whenever a PR introduces a new real vendor import (§1 table) or a new GPU-bound adapter class (§6), it
**must** add the matching entry to the corresponding list in `ci/checks/` in the *same* PR; otherwise the check
passes green while guarding nothing — the exact "green but not enforcing" failure §0.1 exists to prevent.

- [ ] *(review)* Any dependency constructed inside a module instead of injected? → reject.
- [ ] *(review)* Does a "simple change" here force edits in several files? (change amplification) → discuss
      the design.
- [ ] *(review)* Could a new reader predict what this does without running it? (obviousness) → if not,
      rename/comment.

---

## 13. When you think a rule is wrong

Good — that's how design improves. But raise it as a change to *this file* (so everyone moves together), don't
route around it in your module. A convention that half the team follows is worse than none: it creates the
"which way is it here?" cognitive load this file exists to remove. Conceptual integrity is the point.
