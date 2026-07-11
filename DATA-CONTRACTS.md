# DATA-CONTRACTS — the authoritative shapes (V0)

**This file is the single source of truth for every object that crosses a module seam.**
If a shape is defined here, no other doc or module may redefine it — they *reference* it.
ARCHITECTURE.md describes behaviour; this describes the data. When they disagree, fix one to match — never fork.
**PRD.md is vision/rationale, written earlier and at points aspirational (e.g. §8.5's response-envelope
sketch predates this file) — where PRD.md names a concrete shape/field and this file disagrees, this file
wins; fix PRD.md's wording to match, never the other way.**

Why this file exists: five owners build in parallel. The only thing that keeps their modules composable is
agreeing, exactly, on the objects passed between them. A field invented in one module and missing in another
is the most common integration failure — this file removes the guesswork.

Types are shown as Python `@dataclass` / `TypedDict` because the stack (Qdrant, TEI/vLLM, SQLite clients) is
Python. Ship them as real dataclasses in one shared package (`contracts/`), owned by **Owner F**, imported by
everyone. **Do not** hand-copy these shapes into each module.

**Implementation note (T-F1):** the shapes actually ship as runtime-validating **pydantic models**
(`FrozenModel`, `contracts/_base.py`), not plain dataclasses — WORK-BREAKDOWN.md's T-F1 prefers a form that
raises loudly on a type mismatch at construction. The `@dataclass`/`TypedDict` notation throughout this file
is illustrative of *shape* only; it is not the implementation.

- Rule 1 — **These are frozen for V0 — provisionally, pending Phase 0.** Changing a shared type is a
  cross-team event: propose it, update this file, bump the package, tell every owner. Never quietly add a
  field in your own module. **The freeze is provisional until Spike 1 and Spike 2 (PHASE0-RUNBOOK.md) pass
  their gates.** `Anchor` in particular — the spine every shape hangs off — is a bet Spike 1's block-bbox +
  snippet round-trip (≥ ~95%) settles; if it misses, `Anchor`'s shape is the thing that changes. Spike 2
  (retrieval eval) similarly gates `Retriever`/`VectorIndex` tuning. M2 (Parser), M3 (Chunker), and anything
  consuming `Anchor` must not start before Spike 1 passes (WORK-BREAKDOWN.md); M1/Harvester is unaffected —
  it never touches `Anchor`.
- Rule 2 — **Every field is either required or has an explicit default.** No "sometimes present" fields.
- Rule 3 — **IDs are strings, stable, and deterministic** (see §IDs). Never auto-increment integers for
  anything that crosses a seam — they aren't reproducible on rebuild.

---

## IDs (the spine — read this first)

Everything hangs off deterministic string IDs so that **rebuilding the derived stores reproduces the same
references** (ADR-04). Never use random UUIDs or DB autoincrement for cross-seam IDs.

| ID | Format | Example |
|---|---|---|
| `paper_id` | base arXiv id, no version suffix | `2506.01234` |
| `block_id` | `{paper_id}:b{index}` (index = reading order) | `2506.01234:b0` |
| `chunk_id` | `{paper_id}:c{index}` | `2506.01234:c7` |
| `summary_id` | `{paper_id}:summary` | `2506.01234:summary` |

`version` (arXiv `v1`/`v2`) is stored as a **field**, not baked into `paper_id` — dedup keeps only the latest
version per base id (ARCHITECTURE M1).

---

## Provenance & structure

```python
Bbox = tuple[float, float, float, float]   # (x0, y0, x1, y1) in PDF page coordinates

@dataclass(frozen=True)
class Anchor:
    """What grounds any retrievable item to its source. No anchor -> the item is invalid (PRD §6A).
    Block-level, NOT char offsets (char offsets do not survive PDF->markdown; CONTEXT.md)."""
    paper_id: str
    block_id: str          # the source block this item came from
    page: int              # 0-indexed page in the PDF
    bbox: Bbox             # bounding box of the block on that page
    snippet: str           # short quotable verbatim text from the block (for display + re-grounding)
    section_path: str      # e.g. "3. Method > 3.2 Estimator"

BlockType = Literal["prose", "equation", "code", "table", "caption"]

@dataclass(frozen=True)
class Block:
    """One layout block from the parser, in reading order. The unit provenance anchors point at."""
    block_id: str
    paper_id: str
    text: str              # for equations: the LaTeX; for code: the code
    type: BlockType
    page: int
    bbox: Bbox
    section_path: str      # AUTHORITATIVE — assigned once by the Parser (M2). Every other copy
                           # of section_path (Chunk, Anchor) is a derived value, never re-derived.
    index: int             # reading-order position within the paper
```

**`snippet` definition (precise, so two implementers produce the same value):** the first ~200
characters of the anchoring block's `text`, truncated at the nearest preceding word boundary,
**verbatim** — never paraphrased, summarized, or reformatted. Used for (1) display previews and (2)
a cheap re-grounding sanity check (it must appear as a substring of what `get_span` returns for the
same anchor). It is intentionally shorter than the full block; call `get_span` for the complete text.

**Multi-block anchoring rule (resolves chunk↔block cardinality):** `Block`s are the parser's
fine-grained layout units (roughly paragraph/equation/table-sized). `Chunker` (M3) groups one or more
consecutive same-`section_path` blocks into a single `Chunk` sized for retrieval — this grouping, done
once at chunk-build time, is what `Config.child_parent_expansion` controls: `on` (V0 default) lets the
Chunker merge an equation/table block with its defining prose block into one `Chunk`, matching the
"equations/code never split from context" invariant (ARCHITECTURE §M3); `off` forces exactly one
`Chunk` per `Block`, splitting an equation from its prose rather than grouping. It is **not** a
query-time expansion step — there is no live "fetch the parent" call (see the note below). When a
`Chunk` spans more than one `Block`, its `anchor` and `parent_id` **always** point at the **first**
block in that group (reading order) — never an average, a synthetic merged region, or the last block. This keeps
the anchor a single, real, resolvable location at the cost of bbox precision on later blocks in a
multi-block chunk; storing one bbox per constituent block is out of scope for V0 (a V1+ enhancement,
not a rounding error to "fix" now — do not build a multi-bbox `Anchor` in V0).

**What this means for `GroundedResult.passage_text` (read together with §M7 below):** the text
returned to the agent for a passage match is **always the matched `Chunk.text` in full** — never a
`get_span(anchor)` fetch. `get_span` resolves only `anchor.block_id`, i.e. the *first* block of a
multi-block chunk (§M5 below); using it to build `passage_text` would silently drop the 2nd/3rd
block's content (e.g. the equation the grouping exists to keep) whenever a `Chunk` spans more than one
`Block`. `anchor` stays on `GroundedResult` for citation display and re-grounding
(`get_span(anchor)`, §M5, "verify my source") — it is not the source of the passage content itself.
The Chunker already did the "small-to-big" work at build time (via `child_parent_expansion` above); V0
does not additionally expand at query time.

---

## M1 Harvester output

```python
@dataclass(frozen=True)
class PaperRef:
    paper_id: str          # base arXiv id (no version)
    version: str           # "v1", "v2", ...
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]  # e.g. ["cs.LG", "stat.ME"]
    published: date
    updated: date
    pdf_url: str
    latex_url: str | None = None    # arXiv e-print source, if available (enables the LaTeX ingest path)
    relevance_score: float | None = None   # ALWAYS None from Harvester — the score needs summary_text,
        # which doesn't exist yet at harvest time. The authoritative value is `PaperRecord.relevance_score`
        # (§M5), computed by IngestionOrchestrator after Summarizer runs. Do not compute it here.
```

## M2 Parser output

```python
@dataclass(frozen=True)
class Figure:
    paper_id: str
    image_path: str        # filesystem path to extracted PNG (source-of-truth blob)
    caption: str
    page: int
    bbox: Bbox
    vlm_description: str | None = None    # ALWAYS None in V0; filled by the V3 VLM enricher

@dataclass(frozen=True)
class TableItem:
    paper_id: str
    markdown: str          # table rendered as markdown
    caption: str
    page: int
    bbox: Bbox

@dataclass(frozen=True)
class Reference:
    raw: str               # raw reference string (from GROBID)
    title: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None

@dataclass(frozen=True)
class ParsedDoc:
    paper_id: str
    markdown: str          # full body as markdown (equations as LaTeX, code fenced)
    blocks: list[Block]    # reading-order; EVERY block carries page+bbox (the anchor source)
    figures: list[Figure]
    tables: list[TableItem]
    references: list[Reference]
    parser_id: str         # which adapter produced this (e.g. "mineru-1.x") — for reproducibility
```

**Parser invariant:** every `Block` has a valid `page` and `bbox`. A block without them is a contract
violation → crash early, do not emit a block with `bbox=(0,0,0,0)` as a fake.

## M3 Chunker output

```python
@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    paper_id: str
    text: str
    anchor: Anchor
    section_path: str              # derived — copied from the anchoring block at chunk time (see Block.section_path)
    parent_id: str | None          # ALWAYS a block_id, never a chunk_id (parent-child, ON in V0).
                                    # By construction this is the same block as `anchor.block_id`
                                    # (see the multi-block anchoring rule above) — Retriever never
                                    # needs to guess which one it is or resolve them separately.
    contextual_header: str | None = None   # ALWAYS None in V0 — see below
```

**`contextual_header` is a V1 feature, not a V0 toggle** — field exists now (nullable, `None` in V0) so V1
fills it with zero schema migration; do not populate it or add an on/off switch in V0. Full rationale +
V0's monitoring-only obligation: PRD ADR-07.

## M3B Summarizer output

**This module is in V0 scope**, even though it's easy to mistake for a V1 deferral by analogy to
`contextual_header` — it isn't. `PaperRecord.summary_text`/`summary_id` (§M5), `VectorPayload.kind ==
"summary"` (§M6), and `search_papers`/`get_paper` (§M8) all depend on it. CONTEXT.md's V0 definition
explicitly returns "grounded passages + summaries + citations", and `PaperRecord.summary_text` is a
required (non-nullable) field, unlike `contextual_header`, which V0 deliberately leaves `None`.

```python
# Summarizer.summarize(doc: ParsedDoc) -> str
#   Returns summary_text for the paper. summary_id is NOT returned by this call — it is always
#   derived deterministically as f"{paper_id}:summary" (see §IDs); Summarizer never invents it.
```

- **Invariants:** non-empty string; the local generation LLM (Qwen tier, ADR-08; served via the stack
  chosen in ADR-09) is a **GPU-bound stage** — subject to the single-GPU lock (`GpuLock`, above; ARCHITECTURE
  "Operational invariants" §3) exactly like the Embedder and reranker. It **cannot** run concurrently with
  them — enforced by the real adapter acquiring `gpu_lock.acquire("summarize")` around its inference call.
- **Dependency injection:** `Summarizer` accepts its LLM client **and its `GpuLock`** as constructor arguments
  (principle 3 — every module does this, not only the three "real seam" modules). This is a **hypothetical
  seam** in ARCHITECTURE's sense (V0 ships one local model, no plugin registry) — but the client is still
  injected so a `FakeSummarizer` (deterministic, e.g. a fixed-length truncation of the input text, paired
  with `FakeGpuLock`) can power zero-GPU tests of `IngestionOrchestrator`, exactly like `FakeEmbedder` does
  for the Embedder.
- **Errors:** an empty/degenerate `ParsedDoc` (no prose blocks) is a `PermanentError` → quarantine, not a
  crash — some papers genuinely can't be summarized (e.g. a corrupted parse that produced only figures).
- **Where it sits in the pipeline:** after `Chunker` (or in parallel with it — both consume `ParsedDoc`
  and neither depends on the other's output) and before `Embedder`, because `Embedder` must also embed
  `summary_text` (as a `kind="summary"` vector, §M6) before `DocumentStore.put` and `VectorIndex.upsert`
  run. See ARCHITECTURE's updated module map.

## M4 Embedder output

```python
@dataclass(frozen=True)
class EmbedderInfo:
    model_id: str          # e.g. "Qwen3-Embedding-4B"
    dim: int               # e.g. 2560
    version: str           # bump when weights/config change -> invalidates the vector collection

Vector = list[float]       # L2-normalized; length == EmbedderInfo.dim
# Embedder.embed(texts: list[str]) -> list[Vector]   (order-preserving, 1:1 with input)
# Embedder.info -> EmbedderInfo
```

The **real** adapter's constructor also takes a `gpu_lock: GpuLock` (see "GpuLock" section below) and
acquires `gpu_lock.acquire("embed")` around the batch inference call — GPU-bound, same rule as Summarizer
and Reranker. `FakeEmbedder` needs no lock (no GPU).

## M5 DocumentStore — what `put` persists

```python
@dataclass(frozen=True)
class PaperRecord:
    """The complete source-of-truth bundle for one paper. DocumentStore.put(PaperRecord) is atomic:
    either the whole paper is stored or none of it (so a crash never leaves half a paper)."""
    ref: PaperRef
    parsed: ParsedDoc
    chunks: list[Chunk]
    summary_text: str
    summary_id: str
    relevance_score: float | None = None   # AUTHORITATIVE value (unlike PaperRef.relevance_score, always
        # None). Computed by IngestionOrchestrator (M9) as cosine(embed(summary_text), topic_query_vec) —
        # full rule, incl. the "compute topic_query_vec exactly once per run" invariant: ARCHITECTURE.md
        # §M9. Persisted to papers.relevance_score (SQL schema below).
    # blobs (PDF, figure PNGs, markdown) are written to the filesystem; their paths live on ref/parsed.

# DocumentStore interface (all reads return the frozen types above):
#   put(record: PaperRecord) -> None            # atomic; upsert by paper_id (idempotent)
#   get(paper_id) -> PaperRecord | None
#   get_blocks(paper_id) -> list[Block]
#   get_block(block_id) -> Block                # ContractError if unknown — a dangling parent_id is a bug
#   get_chunk(chunk_id) -> Chunk                # ContractError if unknown
#   get_summary(summary_id) -> str              # ContractError if unknown; hides the "{paper_id}:summary"
#                                                # ID format from callers — Retriever never parses it
#   get_span(anchor: Anchor) -> str             # resolves an anchor to the FULL text of anchor.block_id
#                                                # (i.e. Block.text) — NOT the shorter Anchor.snippet.
#                                                # snippet is already inline on the Anchor for quick
#                                                # display; get_span is the deeper "verify my source" call.
#   iter_papers() -> Iterator[PaperRecord]      # used by VectorIndex.rebuild()
```

## M6 VectorIndex

```python
@dataclass(frozen=True)
class Hit:
    id: str                       # chunk_id or summary_id
    kind: Literal["chunk", "summary"]   # so Retriever branches on type without parsing the id string
    score: float                  # the fused RRF score (see formula below)

@dataclass(frozen=True)
class SearchFilters:
    """Replaces an untyped `filters: dict` — the one hot-path shape that was crossing the VectorStore
    seam with no agreed grammar. Every field maps to a `VectorPayload` field of the same name."""
    categories: list[str] | None = None        # any-overlap match against VectorPayload.categories
    published_after: date | None = None        # inclusive
    published_before: date | None = None       # inclusive
    kind: Literal["chunk", "summary"] | None = None   # restrict to VectorPayload.kind

# hybrid_search(qvec: Vector, qtext: str, filters: SearchFilters | None, k: int) -> list[Hit]
#   qvec -> dense side; qtext -> sparse/BM25 side; fused per the RRF formula below; top-k by fused score.
# upsert(id: str, vector: Vector, payload: VectorPayload) -> None
# rebuild() -> None    # drops + rebuilds the collection from DocumentStore.iter_papers()
```

**RRF fusion formula (frozen — both `FakeVectorStore` and the real Qdrant adapter must implement this
exact formula, or the contract test proves nothing):**

```
RRF_K = 60   # named constant in contracts/, not a Config lever — it's part of the fusion algorithm,
             # not a scope-defining lever (CONTEXT.md "Lever" definition)

score(d) = hybrid_dense_weight     * 1/(RRF_K + rank_dense(d))
         + (1 - hybrid_dense_weight) * 1/(RRF_K + rank_sparse(d))
```

`rank_dense`/`rank_sparse` are each item's 1-indexed rank in the dense-only and sparse/BM25-only result
lists respectively (a document missing from one list is simply excluded from that term, not given a
rank). `hybrid_dense_weight` (Config, default `0.5` = equal weighting — the vanilla-RRF case) is the one
existing Config lever this formula must honor. **If Qdrant's native fusion doesn't support this weighted
form,** the `VectorStore` adapter must compute it
itself by pulling separate dense and sparse ranked lists from Qdrant and fusing them in the adapter —
never approximate with Qdrant's built-in (unweighted) fusion, or the fake/real contract test stops
proving anything.

**This formula is a pure function, factored once into `contracts/fusion.py` (`rrf_fuse(dense_ranked_ids,
sparse_ranked_ids, hybrid_dense_weight, rrf_k=RRF_K) -> list[(id, score)]`), and both `FakeVectorStore`
and the real Qdrant adapter call it** — it must not be reimplemented separately in each adapter (that would
silently reintroduce the two-implementations-of-one-decision problem `contracts/` exists to prevent). See
TEST-STRATEGY.md for how this changes the contract test: the formula itself gets a direct unit test against
synthetic rank inputs; the fake-vs-Qdrant cross-adapter test is a **best-effort agreement smoke test**
(top-result overlap, not exact full-ordering equality), because `rank_dense`/`rank_sparse` come from
unrelated dense/sparse implementations (hash-cosine vs. a trained model; token-overlap vs. real BM25) that
have no reason to agree past the top few results even when `rrf_fuse` itself is correct on both sides.

`VectorPayload` (stored beside each vector — kept minimal; the DocumentStore holds the real text):

```python
class VectorPayload(TypedDict):
    paper_id: str
    kind: Literal["chunk", "summary"]
    section_path: str
    categories: list[str]      # for metadata filtering
    published: str             # ISO date, for date-range filters
    embedding_version: str     # must match the collection's model version
```

## M7 Retriever output (the envelope — frozen shape, forward-compatible to V2)

```python
EvidenceTier = Literal["A", "B", "C", "D"]

@dataclass(frozen=True)
class Citation:
    paper_id: str
    title: str
    authors: list[str]
    arxiv_url: str
    section_path: str

@dataclass(frozen=True)
class GroundedResult:
    passage_text: str          # the matched Chunk's own text, in full (see "What this means for
                                 # GroundedResult.passage_text" above) — NOT a get_span(anchor) fetch.
                                 # This IS V0's small-to-big unit: the Chunker already grouped the right
                                 # blocks at chunk-build time (Config.child_parent_expansion); nothing
                                 # further is expanded at query time.
    anchor: Anchor              # == the matched Chunk's own anchor (its first block, multi-block
                                 # anchoring rule, §Provenance & structure). Used for citation display
                                 # and re-grounding (`get_span(anchor)`, §M5) — never the source of
                                 # `passage_text` itself.
    paper_id: str
    score: float
    citation: Citation
    evidence_tier: EvidenceTier = "A"     # PINNED to "A" in V0; B/C/D land in V1/V2 (PRD §8.5)
    metadata: dict = field(default_factory=dict)   # empty in V0; V1/V2 add status/conditions/confidence.
        # Populating this field is a `contracts/` shape change, not a free write by a downstream module —
        # it goes through the T-F7 foundation-change protocol (CONVENTIONS.md) like any other contracts/ edit.
```

**Why the envelope now (forward-compat):** V1/V2 add evidence tiers, `status: superseded_by`, and
`conditions`. Because `GroundedResult` is already a record with `evidence_tier` + `metadata`, those land as
**filled fields, not a changed type** — no V0 consumer breaks. Never return a bare string from retrieval.

**`GroundedResult` is passage-level only.** `Retriever.retrieve()` never returns a summary/whole-paper
match — a summary has no block to anchor to, so it cannot satisfy this type. Whole-paper search has its
own, unanchored return shape, `PaperSearchResult` — defined in §M8 below (it wraps `PaperSummaryView`,
so it's defined after that type exists, not forward-referenced here).

### Reranker (Retriever's internal collaborator — not a top-level module, but still injected)

`retrieve()`'s pipeline names a "cross-encoder rerank" step, and TEST-STRATEGY requires Retriever tests
to need **zero GPU** — those are only compatible if the reranker is a dependency `Retriever` accepts, not
a hardcoded model load.

```python
@dataclass(frozen=True)
class RerankCandidate:
    id: str                # chunk_id or summary_id — same id space as Hit
    text: str               # the text to score against the query (chunk/summary text)

# Reranker.rerank(query: str, candidates: list[RerankCandidate]) -> list[RerankCandidate]
#   Returns the same candidates, reordered by the cross-encoder; length <= len(candidates).
```

- **Vendor:** the cross-encoder client (BGE-reranker-v2-m3 or the Spike-2 choice, ADR-10) is imported
  **only** by the real `Reranker` adapter — same dependency-direction rule as Embedder/VectorStore
  (CONVENTIONS §1).
- **GPU-bound:** the real adapter's constructor takes a `gpu_lock: GpuLock` (see "GpuLock" section) and
  acquires `gpu_lock.acquire("rerank")` around the cross-encoder call — same compute-level serialization
  as Embedder and Summarizer. It is expected to **co-reside** with them in VRAM within the 24GB budget;
  `McpServer`'s reranker in particular stays resident for the life of the process.
- **Test:** `FakeReranker` is deterministic but **must not be an identity reorder** — an identity fake makes
  every Retriever test pass identically whether or not `rerank()` is even called, which leaves the
  ship-critical rerank stage with zero unit-test coverage (a `retrieve()` that drops the rerank call, reranks
  the wrong slice, or mismatches ids would still pass). Use a **deterministic non-identity reorder** instead
  (reverse the input candidate order) and give it a call-recording `.calls`
  list (`(query, [c.id for c in candidates])` per invocation). Every Retriever test that exercises the
  reranked path must assert **both**: (a) `reranker.calls` is non-empty with the expected candidate ids, and
  (b) the final result order matches the fake's (reversed) order and **differs from** the pre-rerank RRF
  order — otherwise a broken wiring is indistinguishable from a correct one. The real adapter gets its own
  isolated test, not a contract test (V0 has only one reranker choice, so there's no second adapter to prove
  agreement against — see ARCHITECTURE principle 4).

## GpuLock — cross-process compute serialization

**Why this exists:** the single-GPU rule (ARCHITECTURE "Operational invariants" §3, CONVENTIONS §6) was
enforced only in prose ("the orchestrator holds a GPU lock"), with no type, no constructor argument, and
no CI check — exactly the kind of rule CONVENTIONS §0.1 says isn't a real guardrail for an agent team.
It's also a two-process problem, not a one-process problem: `IngestionOrchestrator` (M9) and `McpServer`
(M8) are the system's two composition roots (CONVENTIONS §2) and normally run as separate OS processes —
a multi-day ingest alongside an always-on query server. **V0 explicitly allows them to run concurrently**;
a same-process `threading.Lock` cannot serialize across that boundary, so the lock must be a real,
injected, cross-process primitive.

**What `GpuLock` does:** it is the **cross-process compute serializer, and only that.** It stops two
GPU-bound inference calls (an ingest embed/summarize/rerank vs. a query-path rerank) from executing at
the same instant. It does not manage residency or eviction. Per PRD ADR-02/ADR-08's VRAM arithmetic
(embedder ~8.5GB @ Q8, summarizer ~7-8GB 4-bit, reranker ~1-2GB, ≈ 17-18GB total), the three real models
are expected to **co-reside** within the 24GB budget for the life of the process — nobody evicts anybody.
This ~17-18GB estimate is unmeasured; PHASE0-RUNBOOK.md's S0 step confirms actual peak concurrent VRAM
with both composition roots running.

**V0 fairness/timeout stance:** `acquire()` has no priority and no timeout — a query simply queues behind
an in-flight ingest inference call until it releases. This is an accepted V0 simplification, not an
oversight; revisit only if it proves to be a real problem in practice.

```python
class GpuLock(Protocol):
    def acquire(self, stage: str) -> AbstractContextManager[None]:
        """Blocks until the single GPU slot is free, then yields; releases on exit (incl. on exception).
        `stage` is a label ("embed" | "rerank" | "summarize") used only for logging/timeout messages."""
```

- **Real adapter — `FileGpuLock(lock_path: Path)`:** wraps `filelock.FileLock(lock_path)`, so any process
  holding a `FileGpuLock` constructed with the same `lock_path` serializes against any other, in-process or
  not. `lock_path` comes from `Config.gpu_lock_path` (below) — both composition roots construct their
  `FileGpuLock` from the same `Config`, so they contend for the same file by construction, not by convention.
- **`FakeGpuLock`** (TEST-STRATEGY.md fakes): a no-op context manager (`contextlib.nullcontext`) that also
  records `(stage,)` into an `.acquired` list, so a test can assert a GPU-bound module actually acquired the
  lock around its inference call without needing a real file or a second process.
- **Where it's injected:** every constructor whose adapter loads a model onto the GPU takes `gpu_lock:
  GpuLock` — `Embedder` (M4, real adapter only — `FakeEmbedder` doesn't need it), `Summarizer` (M3B, real
  adapter), and `Reranker` (M7's collaborator, real adapter). **The adapter acquires the lock itself, inside
  its own `embed()`/`summarize()`/`rerank()` call**, not the caller — this is "pull complexity downward"
  (module-design): `IngestionOrchestrator` and `Retriever` call these methods exactly as they would without
  a lock at all; correctness doesn't depend on every caller remembering to wrap the call. This is also why
  it is a **constructor argument like every other dependency (principle 3)**, not an ambient singleton.
- **CI-checkable (T-F6):** the real `Embedder`/`Summarizer`/`Reranker` adapter classes' `__init__` must
  declare a `gpu_lock` parameter — grep-able, same style as the vendor-import check. This is a **necessary
  prefilter, not sufficient proof**: it only shows the parameter exists in the signature, not that
  `acquire()` wraps the real inference call. The actual guarantor of that is the per-adapter
  `FakeGpuLock.acquired` unit assertion (TEST-STRATEGY.md).

## M8 McpServer — response envelope

Every MCP tool returns results as **records, never bare text** (PRD §8.5). `filters?` below is always a
`SearchFilters | None` (§M6) — never a raw dict. V0 tools:

```python
@dataclass(frozen=True)
class PaperSummaryView:
    """get_paper's return shape — named here instead of left as prose so it isn't reinvented per caller."""
    paper_id: str
    title: str
    authors: list[str]
    summary_text: str
    section_paths: list[str]     # distinct Block.section_path values, in reading order
    citation: Citation

@dataclass(frozen=True)
class Coverage:
    """How big was the haystack. Only meaningful for tools that return a top-k SAMPLE of a larger
    candidate set — get_paper/get_span each resolve one specific, fully-specified thing, so there is no
    'you're seeing part of it' concept for them and they are NOT wrapped in this envelope."""
    returned: int      # len(results) — after rerank + top_k truncation
    candidates: int     # len(Hit list) returned by VectorIndex.hybrid_search, i.e. the fused candidate
                         # pool BEFORE rerank/top_k truncation — "how many were in the running"

@dataclass(frozen=True)
class SearchResponse:
    """semantic_search's return shape. Replaces a bare `list[GroundedResult]` — the shape that
    crosses the M8 seam is fully typed so the 'coverage note' is a real, testable field, not prose."""
    results: list[GroundedResult]
    coverage: Coverage

@dataclass(frozen=True)
class PaperSearchResult:
    """`search_papers`'s per-item shape — a whole-paper/summary-level match, produced by
    `Retriever.retrieve_papers()` (§M7). Deliberately NOT a `GroundedResult`: a summary has no
    block/page/bbox to anchor to (`Anchor` is block-level only, §Provenance & structure), so forcing it
    through the anchored envelope would require either a nullable `anchor` (breaks the "every result is
    grounded" invariant, ARCHITECTURE §M7) or a dummy/abstract-block anchor (a fabricated citation that
    would pass the snippet re-grounding check on text that isn't what was actually matched). Wraps
    `PaperSummaryView` (the exact shape `get_paper` returns for one paper) with the ranking `score`
    search adds, instead of duplicating its fields."""
    view: PaperSummaryView
    score: float

@dataclass(frozen=True)
class PaperSearchResponse:
    """search_papers's return shape — mirrors `SearchResponse` but for whole-paper results, which carry
    no `evidence_tier`/`metadata` envelope (that envelope stages passage-level grounding claims — tier
    A/B/C/D — which don't apply here; `PaperSummaryView.summary_text` already says in prose that this is
    a paraphrase, CONTEXT.md tier C, with no separate field needed to say it twice)."""
    results: list[PaperSearchResult]
    coverage: Coverage
```

| Tool | Returns |
|---|---|
| `search_papers(query, filters?, k)` | `PaperSearchResponse` (whole-paper/summary-level `PaperSearchResult`s, via `Retriever.retrieve_papers()`) |
| `semantic_search(query, filters?, k)` | `SearchResponse` (passage-level `GroundedResult`s, via `Retriever.retrieve()`) |
| `get_paper(paper_id)` | `PaperSummaryView` |
| `get_span(anchor)` | the exact verbatim source text for an anchor (the check-my-source tool) |

`search_papers`/`semantic_search` carry a **`Coverage`** so the agent knows when it is seeing a sample, not
the whole picture (PRD §8.5 anti-miss) — this is a real field on both response types now, not a prose promise;
the McpServer test "coverage note present" (TEST-STRATEGY.md) asserts `response.coverage.candidates >=
response.coverage.returned` for each.

---

## Config (the levers — one injected object, never scattered env reads)

```python
@dataclass(frozen=True)
class Config:
    # scope levers (CONTEXT.md registry) — the knobs that must never be buried constants
    focus_area_queries: list[str]      # arXiv search queries defining the topic
    corpus_cap: int = 15_000
    ordering: Literal["freshest_first"] = "freshest_first"
    ingestion_mode: Literal["one_shot_seed"] = "one_shot_seed"
    sources: list[str] = field(default_factory=lambda: ["arxiv"])
    relevance_filter: Literal["off", "embedding"] = "off"
    # retrieval knobs (tuned in Spike 2)
    # NOTE: no `contextual_header` toggle — it's not built in V0 (PRD ADR-07).
    child_parent_expansion: bool = True
    top_k: int = 10
    rerank_depth: int = 50
    hybrid_dense_weight: float = 0.5
    gpu_lock_path: str = ".gpu.lock"   # both composition roots build their real GpuLock from this path
                                        # (see "GpuLock" section) so they contend for the same file.
```

**Loaded once at startup from one file** (e.g. `config.yaml`), passed down by the orchestrator/MCP entrypoint.
No module calls `os.getenv` or reads the file itself. Changing scope = edit the file + re-run (ADR-18).

---

## SQLite schema (source of truth — Owner D; V1 columns are noted but NOT created in V0)

```sql
CREATE TABLE papers (
  paper_id     TEXT PRIMARY KEY,
  version      TEXT NOT NULL,
  title        TEXT NOT NULL,
  abstract     TEXT NOT NULL,
  authors_json TEXT NOT NULL,       -- JSON array
  categories_json TEXT NOT NULL,
  published    TEXT NOT NULL,        -- ISO date
  updated      TEXT NOT NULL,
  pdf_path     TEXT NOT NULL,
  markdown_path TEXT NOT NULL,
  relevance_score REAL              -- written by IngestionOrchestrator via put(PaperRecord), post-summarize;
                                      -- NULL only if a row predates the paper reaching that stage. Unused
                                      -- by V0 filtering (relevance_filter="off"), but must not be silently
                                      -- left NULL after "done" — see TEST-STRATEGY Orchestrator test.
);

CREATE TABLE blocks (
  block_id     TEXT PRIMARY KEY,
  paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
  idx          INTEGER NOT NULL,
  type         TEXT NOT NULL,
  text         TEXT NOT NULL,
  page         INTEGER NOT NULL,
  bbox_json    TEXT NOT NULL,        -- JSON [x0,y0,x1,y1]
  section_path TEXT NOT NULL
);

CREATE TABLE chunks (
  chunk_id     TEXT PRIMARY KEY,
  paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
  text         TEXT NOT NULL,
  anchor_json  TEXT NOT NULL,        -- serialized Anchor
  section_path TEXT NOT NULL,
  parent_id    TEXT,
  contextual_header TEXT
);

-- DocumentStore reconstruction (get/get_paper) filters blocks and chunks by paper_id; without these
-- indexes each lookup full-scans these ~1-5M-row tables on the always-on query server at corpus_cap ~15k.
CREATE INDEX idx_blocks_paper_id ON blocks(paper_id);
CREATE INDEX idx_chunks_paper_id ON chunks(paper_id);

CREATE TABLE summaries (
  summary_id   TEXT PRIMARY KEY,
  paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
  text         TEXT NOT NULL
);

-- The idempotency spine (CONVENTIONS "operational invariants"):
CREATE TABLE ingest_state (
  paper_id     TEXT PRIMARY KEY,
  stage        TEXT NOT NULL,        -- harvested|parsed|chunked|summarized|embedded|stored|done —
                                       -- full `stored`-vs-`done` resume semantics (why they're
                                       -- distinct stages): ARCHITECTURE.md "Operational invariants" §1.
  updated_at   TEXT NOT NULL
);

CREATE TABLE quarantine (            -- dead-letter: one bad paper must not kill the run
  paper_id     TEXT PRIMARY KEY,
  stage        TEXT NOT NULL,
  error        TEXT NOT NULL,
  ts           TEXT NOT NULL
);

-- V1+ (DO NOT CREATE IN V0): claims(claim_id, paper_id, method, dataset, metric, value,
--   conditions_json, anchor_json, ...), claim_relations(...), citation_edges(...). Named here only so
--   Owner D leaves room; the schema is additive (new tables), never a migration of the above.
```

Run SQLite in **WAL mode** (ADR-05 — the relational-store decision; WAL is an implementation detail of
that choice, not ADR-07, which is the unrelated chunking/contextual-header decision).
`authors_json`/`categories_json`/`bbox_json`/`anchor_json` are JSON
because they are read whole, never queried by inner field in V0.

**V0 does not enforce foreign keys.** `PRAGMA foreign_keys` is off by default in SQLite, is
per-connection and non-persistent, and the migration script does not set it — so the `REFERENCES
papers(paper_id)` clauses above are documentation of intent, not enforced constraints, until whoever
owns the long-lived connection (`DocumentStore`, Owner D/M5) deliberately turns the pragma on for that
connection. This is the V0 decision, not an oversight to silently fix in the migration script.

---

## What is NOT in V0 (so nobody builds it)

`claims`, `claim_relations`, `citation_edges`, evidence tiers B–D, reconciliation, Obsidian notes,
`synthesize`/`find_contradictions`/`compare_on_benchmark` tools, VLM figure descriptions, the
self-describing MCP scaffolding (`describe_capabilities`/`corpus_stats`/prompts/resources), and
**contextual-header generation** (ADR-07 — V0 only monitors the signal, V1 builds it). These are V1–V3
(PRD §9). The V0 shapes above leave room for them (nullable fields, additive tables) — that is the extent of
V0's obligation to the future.
