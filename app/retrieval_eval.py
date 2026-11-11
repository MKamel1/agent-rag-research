"""`python -m app.retrieval_eval` -- T-DOC41 (Contextual Retrieval spike): the measurement
runner. Loads a ground-truth question set, calls the real `Retriever.retrieve()` for each
question, and scores Recall@10/MRR at two granularities:

  * paper-level -- a hit if any returned chunk's `paper_id` is in the question's gold-paper set
    (`source_paper_id` plus, when present, `additional_gold_paper_ids` -- same multi-gold
    methodology as the 210-question eval, T-DOC42).
  * passage-level -- a hit only if a returned chunk's `anchor.block_id` equals the question's
    `gold_block_id`. This is the granularity `fixtures/eval/eval_ground_truth.json` cannot see
    (its own `_metadata.multi_gold_note` -- any chunk from the right paper passes) and
    `fixtures/eval/eval_equation_slice.json` was built to make visible: whether the *specific*
    equation/algorithm chunk was retrieved, not just the right paper.

Only questions carrying a `gold_block_id` are scored at passage level -- the 210-question set
doesn't have one (see that fixture's schema), so pointing this runner at it degrades gracefully to
paper-level-only reporting instead of crashing or silently scoring zero.

A third granularity, book-only (docs/DESIGN-book-chapters-and-hierarchy.md Part 3 Step 1):

  * chapter-level -- a hit only if `Retriever.retrieve_papers()` (what `search_papers` wraps)
    returns a `PaperSearchResult` whose `paper_id` is gold AND whose `chapter` string equals the
    question's `gold_chapter_title`. This is a DIFFERENT question from passage-level: passage-level
    asks whether `semantic_search` finds the right span; chapter-level asks whether the chapter
    *routing* step (what `ChapterSummary`/`book_summarizer.py` exist for) points an agent at the
    right chapter at all. Only questions carrying a `gold_chapter_title` are scored here -- same
    graceful-degrade posture as passage-level's `gold_block_id` gate, so pointing this runner at
    the 210-question or equation-slice fixtures (neither carries book fields) still just reports
    paper/passage level, chapter-level empty. `retrieve_papers()` is only called for questions that
    need it -- an unscored (paper) question costs no extra retrieval call.
  * `doc_type` ("paper" | "book", default "paper" for backward compatibility with the existing
    fixtures) rides along on every `Question`/`QuestionResult` so `build_report`'s `by_doc_type`
    breakdown can report books and papers separately from one mixed-fixture run, per the design
    doc's "must be able to evaluate books separately from papers, and report them separately."

Same real, production retrieval pipeline the 210-question eval already uses end to end
(`app.assembly.build_mcp_server`) -- no simplified stand-in, and this module never talks to the
vector store or LLM adapters directly (CONVENTIONS §1): it only ever imports the composition root.
`--collection` is threaded straight through to `build_mcp_server`'s own existing `collection=`
parameter, so the same runner can score a throwaway "headered" collection against a throwaway
baseline collection during the actual before/after measurement -- no new wiring, no foundation
edit.

Two report-level honesty features (RI-15):

  * `scoring_rule` -- every emitted report carries a string naming the hit rule in force and the
    truncation k, so two numbers produced under different rules cannot be compared silently: a
    number in a JSON file outlives everyone's memory of how it was computed. (Pinned by
    test_build_report_stamps_the_scoring_rule_with_k.)
  * `paper_level.title_leak` -- a verbatim diagnostic counting paper-level hits whose retrieved
    passage embeds the gold paper's own title (casefolded, whitespace runs collapsed), i.e.
    retrievals that may have succeeded on title overlap rather than passage semantics. It is
    reported ALONGSIDE Recall/MRR and deducted from nothing -- deciding what to do about the
    number is not the instrument's call. Matching is verbatim-after-normalization only, so
    paraphrase-level leaks go uncounted and the figure is a floor; the report itself says so.

Sparse-arm ablation (RI-M3): `--sparse-mode {fused,dense_only,sparse_only}` measures what the
hybrid retriever's sparse arm (`rag/vector_index.py::_sparse_vector`, raw per-token counts, no
stemming/stopwording) contributes on top of dense, and what dense contributes on top of sparse.

The honest disable is NOT "zero or perturb the sparse vector sent at query time" -- the sparse
field's IDF weighting (`_sparse_vector_params()`'s native modifier) runs server-side, computed by
the vector store from its own live document-frequency stats, and is not reproduced anywhere in
this repo. Sending a degenerate query vector would still get server-side-weighted, so it would not
reproduce genuine sparse absence. The seam this module actually uses is one layer up: the
client-side RRF fusion weight (`contracts/fusion.py::rrf_fuse`'s `hybrid_dense_weight`), which both
`VectorIndex` and `FakeVectorStore` already take as a plain constructor argument.
`hybrid_dense_weight=1.0` zeroes the sparse arm's contribution to every fused score without
touching what either query sends or how the server scores it; `=0.0` does the same to dense. See
`sparse_mode_weight`.

Known limitation, stated here and in every report's `scoring_rule` rather than silently carried:
zeroing a weight does not remove that arm's candidates from the fused pool -- `rrf_fuse` returns a
score for the union of both ranked lists (its own postcondition), so a document found ONLY by the
disabled arm still appears, at score 0.0, and can still occupy a result slot if the enabled arm
alone does not independently surface enough candidates to fill `k`. At real corpus scale each arm's
query is queried `_FUSION_DEPTH_CAP` deep (rag/vector_index.py), so this is not expected to matter
in practice, but it means "dense_only"/"sparse_only" measure "this arm's contribution to ranking,"
not "retrieval with the other arm physically removed."

Fusion-weight sweep (FUSE-1): `--dense-weight W` pins `hybrid_dense_weight` to any intermediate
value in [0, 1] for one run -- the modes above can only name the two extremes, and sweeping by
editing the corpus's own config.yaml would mutate a file other sessions share. The weight actually
used travels in every emitted report's `scoring_rule`, same as the modes do.

Score-distribution census (RI-M7): `QuestionResult.top_score` (and `_question_row`'s
`"top_score"`) carry the rank-1 result's own fused/reranked score for EVERY question, hit or
miss -- a known-absent question (no gold paper, `source_paper_id: null` in
`fixtures/eval/eval_known_absent.json`) still returns a top score whenever the corpus is
non-empty, since this retriever always returns its best-available top-k (RI-10's absence-honesty
docstrings) rather than refusing when nothing answers the question. `app/score_distribution_
census.py` reuses `load_questions`/`run`/`build_report` UNMODIFIED (no second eval runner) --
scoring the known-answerable arm (`eval_ground_truth.json` + `eval_equation_slice.json`) and the
known-absent arm separately, then comparing the two `top_score` distributions. See that module
for the summary statistics and the separation rule.

Answerable vs known-absent arms inside one report (BENCH-1): a ground-truth file can MIX the two
arms (`waymo_gt_verified.json`: 65 answerable items + 8 known-absent ones whose gold key set is
empty by construction). `_recall_mrr` puts every rank in the denominator, so an unpartitioned
aggregate over such a file deflates recall with guaranteed misses. `build_report` therefore also
emits `paper_level.by_gold_status` -- `answerable` (the false-negative measure) and
`known_absent` (what came back and at what scores; recall withheld, see
`_KNOWN_ABSENT_METRIC_NOTE`) -- while `overall` keeps its exact prior definition for backward
compatibility. `_print_summary` leads with the two arms whenever the absent arm is non-empty.

Passage-level text vs vision arms (VARM-1): four of waymo_gt_verified.json's answerable items are
`vision_derived` -- their answers exist only inside a figure, so the gold chunk's own text does not
contain them and a text retriever structurally cannot rank them; blended into one passage-level
number they cap it below any achievable target (60/64 = 0.9375 on that fixture). `build_report`
therefore also emits `passage_level.by_vision_status` -- `text_answerable` (the arm the operator's
>=0.95 passage-precision target applies to) and `vision` (its own denominator, its rank-1 rate,
and its paper-level recall@k, because paper-level is where those items already succeed and that
contrast is the finding) -- while `overall` keeps its exact prior definition. See
`_VISION_ARM_NOTE`. Same shape as BENCH-1's `paper_level.by_gold_status`, not a second convention.
Eval hardening (EV-7..EV-10; measurement-side only -- nothing here touches retrieval or ranking):

  * EV-7 -- `--collection` is REQUIRED (no silent default corpus). Every report stamps
    `ground_truth_sha256_12` (first 12 hex of the SHA-256 of the ground-truth file's bytes, same
    pattern as judge_eval's `rubric_sha256_12`), `code_commit` (git HEAD of this checkout) and
    `code_tree_dirty`. Before any retrieval runs, a gold-id preflight checks every gold paper /
    chunk / block id of the loaded questions resolves in the given DB and exits 2 naming the
    unresolved ids otherwise.
  * EV-8 -- additive `passage_excerpt_level` beside the unchanged anchor `passage_level`: a hit is
    a returned `passage_text` that contains the normalised gold `passage_excerpt` (or equals the
    text of an `alternative_gold_chunk_ids` / `gold_chunk_id` chunk resolved through the DB).
    Items with a null `excerpt_block_id` fall back to the anchor rule and are listed separately.
    Relation to the frozen protocols' member-passage metric: see `excerpt_hit`.
  * EV-9 -- each per-question row gains `retrieved_chunk_ids` (one list of candidate chunk ids per
    retrieved rank, recovered from (paper id, anchor block id, passage text) via the DB; more than
    one id for a rank marks the row `chunk_id_ambiguous`).
  * EV-10 -- a run in which any question errored on a GPU-lock timeout is INVALID: the report
    carries `run_valid: false` and `n_lock_timeouts`, the summary says so, and the process exits
    `EXIT_INVALID_RUN` (3) after writing the report. Same VOID convention as
    `scripts/nb_eval_runner.py` (a partially starved run is not a baseline).

"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import statistics
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_GROUND_TRUTH = "fixtures/eval/eval_ground_truth.json"
_DEFAULT_K = 10

# EV-7: exit code of a gold-id preflight failure (unresolvable gold ids -- nothing was measured).
EXIT_PREFLIGHT_FAILED = 2
# EV-10: exit code of a run that finished and wrote its report but is INVALID (GPU-lock timeout).
# scripts/nb_eval_runner.py mirrors this number to still collect the (VOID-flagged) report.
EXIT_INVALID_RUN = 3

# Stated in the emitted report itself (build_report), not just here: a verbatim predicate leaves
# paraphrase-level leaks uncounted, so the reported figure is a floor, not a measurement.
_TITLE_LEAK_NOTE = (
    "Floor, not a measurement: the predicate matches the gold title verbatim only (casefolded, "
    "whitespace runs collapsed), so paraphrase-level leaks go uncounted and true title-driven "
    "retrieval is at least this large. Diagnostic alongside Recall/MRR -- deducted from neither."
)

# RI-M3: the three sparse-arm ablation modes. See the module docstring's "Sparse-arm ablation"
# section for why the disable happens at the RRF fusion weight, not by perturbing the sparse
# vector itself.
SPARSE_MODES = ("fused", "dense_only", "sparse_only")


def sparse_mode_weight(mode: str, configured_weight: float) -> float:
    """Maps an ablation `mode` to the `hybrid_dense_weight` a vector store (`VectorIndex` or
    `FakeVectorStore`) must be CONSTRUCTED with -- both adapters already take this as a plain
    constructor argument (DATA-CONTRACTS.md §M6), so ablating needs no new seam. "fused" passes
    `configured_weight` straight through unchanged (whatever `Config`/the caller's fixture already
    uses); "dense_only"/"sparse_only" pin the weight to the extreme that zeroes the OTHER arm's
    contribution to the fused RRF score (module docstring: this zeroes a score contribution, it
    does not remove that arm's candidates from the fused pool).
    """
    if mode == "fused":
        return configured_weight
    if mode == "dense_only":
        return 1.0
    if mode == "sparse_only":
        return 0.0
    raise ValueError(f"unknown sparse mode {mode!r}, expected one of {SPARSE_MODES}")


def resolve_hybrid_weight(
    mode: str, configured_weight: float, override: float | None
) -> float:
    """FUSE-1: the one place a run's effective hybrid_dense_weight is decided -- the loaded
    config's own value unless something overrides it. The sparse-arm modes above can only name
    the two RRF extremes; the fusion-weight sweep needs every intermediate step WITHOUT editing
    the corpus config between points (the live config.yaml is shared with other sessions), so
    `override` (--dense-weight) wins whenever it is given. Range-checked here rather than left to
    rrf_fuse's later ContractError so a bad sweep value fails before any retrieval is spent; the
    weight that was actually used is stamped into every emitted report's scoring_rule either way.
    """
    if override is not None:
        if not (0.0 <= override <= 1.0):
            raise ValueError(f"--dense-weight must be in [0, 1], got {override}")
        return override
    return sparse_mode_weight(mode, configured_weight)


@dataclass(frozen=True)
class Question:
    question_id: str
    question_text: str
    question_type: str
    gold_paper_ids: frozenset[str]
    gold_block_id: str | None  # None -> not scorable at passage level (e.g. the 210-set today)
    doc_type: str = "paper"  # "paper" | "book" -- default keeps every existing fixture unchanged
    gold_chapter_title: str | None = None  # None -> not scorable at chapter level (papers today)
    # VARM-1: true when the answer exists only inside a figure -- the gold chunk's own text does
    # not contain it, so a text retriever has nothing to rank it on and passage-level scoring
    # against this item measures the fixture, not the retriever. Threaded like doc_type so
    # build_report can split the passage metric into text vs vision arms; the default keeps every
    # pre-VARM-1 fixture parsing unchanged.
    vision_derived: bool = False
    # EV-7/EV-8: gold chunk identity as recorded in the fixture (None / () when absent). Read for
    # the gold-id preflight; `alternative_gold_chunk_ids` also feeds the excerpt metric (EV-8).
    gold_chunk_id: str | None = None
    alternative_gold_chunk_ids: tuple[str, ...] = ()
    # EV-8: the fixture's verbatim excerpt text and the block it sits in (None for an item whose
    # excerpt spans blocks -> excerpt metric falls back to the anchor rule). `alt_chunk_texts` is
    # the DB text of the gold + alternative chunks, filled in by CorpusLookup.attach_gold_texts.
    passage_excerpt: str | None = None
    excerpt_block_id: str | None = None
    alt_chunk_texts: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuestionResult:
    question_id: str
    question_type: str
    paper_rank: int | None  # 1-indexed rank of the first paper-level hit, else None
    passage_rank: int | None  # 1-indexed rank of the first passage-level hit, else None
    passage_scored: bool  # whether this question had a gold_block_id to score against
    error: str | None = None
    # Carried through from Question so build_report's per-question breakdown (T-DOC57) can emit
    # gold ids without a second questions-by-id lookup at report time.
    gold_paper_ids: frozenset[str] = frozenset()
    gold_block_id: str | None = None
    doc_type: str = "paper"
    # VARM-1: carried from Question like doc_type so build_report's passage-level partition (and
    # the per-question row) keys on the result itself, not a re-join against the fixture at
    # report time.
    vision_derived: bool = False
    chapter_rank: int | None = None  # 1-indexed rank of the first chapter-routing hit, else None
    chapter_scored: bool = False  # whether this question had a gold_chapter_title to score against
    gold_chapter_title: str | None = None
    title_leak: bool = False  # a top-k gold passage embeds its own paper's title verbatim
    # RI-M7: the fused-and-reranked score of the rank-1 result (None if retrieve() returned zero
    # results, e.g. an empty corpus or an errored question) -- the one number the score-
    # distribution census (app/score_distribution_census.py) needs per question. Independent of
    # gold_paper_ids: recorded whether or not the question turns out to be a hit, since a
    # known-absent question is never a hit by construction (see load_questions' source_paper_id
    # handling) and still returns a top score every real corpus query is expected to.
    top_score: float | None = None
    # 2026-08-23 protocol instrumentation: the ordered top-k retrieved ids, so aggregate
    # precision (|top-k ∩ gold| / k) is computable from the report without re-running.
    # Purely additive outputs -- no input to any hit/rank/score above.
    retrieved_paper_ids: tuple[str, ...] = ()
    retrieved_block_ids: tuple[str, ...] = ()
    # EV-8: rank of the first excerpt-containment hit (see `excerpt_hit`); for an item with a null
    # `excerpt_block_id` the anchor rule's rank is copied here and `excerpt_fallback` is True.
    excerpt_rank: int | None = None
    excerpt_fallback: bool = False
    # EV-9: per retrieved rank, the corpus chunk id(s) recovered from (paper id, anchor block id,
    # passage text): one id = unique, several = ambiguous (identical text on one anchor), none =
    # unresolved. Empty tuple when no CorpusLookup was supplied to `run`.
    retrieved_chunk_ids: tuple[tuple[str, ...], ...] = ()
    # EV-10: "gpu_lock_timeout" when the error is a GPU-lock acquisition timeout (the question
    # never ran), else None -- including for ordinary errors, which stay plain `error` strings.
    error_class: str | None = None


def load_questions(ground_truth_path: Path, include_duplicates: bool = False) -> list[Question]:
    """Loads a ground-truth file into `Question`s. Two supported shapes, distinguished by
    whether a record already carries `question_text`:

      * the equation slice (`eval_equation_slice.json`): every record is self-contained.
      * the 210-question set (`eval_ground_truth.json`): `question_text` lives in the sibling
        `eval_questions_blind.json` (same directory), joined here by `question_id` -- mirrors the
        methodology `.phase0-data/teval/resolve_and_score_v2.py` already used for this file.

    Records carrying a truthy `duplicate_of` are independent rewordings of a fact another item
    already covers (waymo_gt_verified.json's dedup_policy). By default they are EXCLUDED so a
    double-counted fact cannot move an aggregate denominator; pass include_duplicates=True to
    score them alongside their primaries.
    """
    data = json.loads(ground_truth_path.read_text())
    records = [
        r for r in data["ground_truth"]
        if include_duplicates or not r.get("duplicate_of")
    ]

    text_by_id = {r["question_id"]: r["question_text"] for r in records if "question_text" in r}
    if len(text_by_id) < len(records):
        blind_path = ground_truth_path.parent / "eval_questions_blind.json"
        blind = json.loads(blind_path.read_text())["questions"]
        text_by_id.update({q["question_id"]: q["question_text"] for q in blind})

    questions = []
    for r in records:
        qid = r["question_id"]
        if qid not in text_by_id:
            raise ValueError(
                f"{qid}: no question_text in {ground_truth_path} or its blind sibling"
            )
        # RI-M7: `source_paper_id: null` (fixtures/eval/eval_known_absent.json) means "no gold
        # paper" -- a known-absent question, by construction, has none. Folding it into the set
        # as a bare `None` would make `gold_paper_ids` a `frozenset[str]` containing a non-str and
        # risk `sorted()` crashing the moment a real gold id sits alongside it (_question_row); an
        # empty set is both the correct semantics (no real paper_id ever equals None anyway) and
        # a clean `frozenset[str]`.
        # BENCH-1: waymo_gt_verified.json goes further -- its 8 known-absent items OMIT the key
        # outright, and its 4 multi-paper-synthesis items have NO top-level source_paper_id at
        # all, only supporting_passages each carrying its own paper_id. `.get()` handles the
        # omission; the supporting ids fold into the gold set under the same multi-gold
        # methodology as additional_gold_paper_ids (a co-source passage retrieved is a hit --
        # otherwise these items would carry an empty gold set and count as guaranteed misses,
        # silently deflating recall). supporting_sources plays the same role for items that also
        # have a primary.
        gold_papers = set(r.get("additional_gold_paper_ids", []))
        if r.get("source_paper_id") is not None:
            gold_papers.add(r["source_paper_id"])
        for passage in r.get("supporting_passages", []):
            gold_papers.add(passage["paper_id"])
        for source in r.get("supporting_sources", []):
            gold_papers.add(source["paper_id"])
        questions.append(
            Question(
                question_id=qid,
                question_text=text_by_id[qid],
                # waymo_gt_verified.json leaves question_type null on its 40 GT-B-authored
                # records; build_report sorts the distinct types, so None would crash there.
                # "Unlabeled" keeps the breakdown working while saying plainly none was assigned.
                question_type=r.get("question_type") or "Unlabeled",
                gold_paper_ids=frozenset(gold_papers),
                gold_block_id=r.get("gold_block_id"),
                doc_type=r.get("doc_type", "paper"),
                vision_derived=bool(r.get("vision_derived", False)),
                gold_chapter_title=r.get("gold_chapter_title"),
                gold_chunk_id=r.get("gold_chunk_id"),
                alternative_gold_chunk_ids=tuple(r.get("alternative_gold_chunk_ids") or ()),
                passage_excerpt=r.get("passage_excerpt"),
                excerpt_block_id=r.get("excerpt_block_id"),
            )
        )
    return questions


def file_sha256_12(path: Path) -> str:
    """First 12 hex of the SHA-256 of the file's bytes (== `sha256sum <path> | cut -c1-12`)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def code_commit(repo_dir: Path | None = None) -> tuple[str | None, bool | None]:
    """(`git rev-parse HEAD`, tree-has-tracked-changes) of the checkout this module runs from, or
    (None, None) when git is unavailable. Stamped into every report so a number names the code
    that produced it. Untracked files are ignored (run output dirs live inside the repo)."""
    cwd = repo_dir or Path(__file__).resolve().parent.parent
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=cwd, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None, None
    return head, bool(dirty)


def excerpt_hit(question: Question, passage_text: str) -> bool:
    """EV-8: does one returned `passage_text` contain the question's gold excerpt?

    True when the normalised (`_normalized`: casefold + whitespace collapse) `passage_excerpt` is a
    substring of the normalised passage, or the normalised passage EQUALS the text of the gold or
    an `alternative_gold_chunk_ids` chunk (`alt_chunk_texts`, resolved through the DB -- covers an
    excerpt the chunker re-rendered, e.g. a table). Chunk identity and anchor block never enter, so
    the rule survives a re-chunk and credits an alternative chunk the anchor rule misses.

    Ceiling: the gold chunk's own text satisfies this for every item with a non-null
    `excerpt_block_id` whose excerpt is verbatim in it (pinned by test).

    Relation to the frozen protocols' member-passage metric (scripts/eval_strata_report.py): that
    metric is anchor-based -- a result counts if its ANCHOR block is the gold block, anchors an
    alternative/gold chunk, or its member-block span contains `excerpt_block_id`. It answers "did
    retrieval land on a chunk covering the right block", independent of what text was served, and
    over-counts when chunks share an anchor. This metric asks "was the excerpt text actually in the
    served passage", independent of chunk identity. They agree where the chunk body is served in
    full and anchors are unique (the main corpus), and can differ for shared-anchor chunks (member
    counts, excerpt does not unless the text matches) and truncated/re-rendered bodies. The names do
    not collide (`passage_excerpt_level` vs `member_hit`); the protocols' metric of record stays
    member-passage and this one is reported beside it, never in place of it.
    """
    served = _normalized(passage_text)
    if question.passage_excerpt and _normalized(question.passage_excerpt) in served:
        return True
    return any(served == _normalized(t) for t in question.alt_chunk_texts if t)


class CorpusLookup:
    """Read-only (`mode=ro`) view of the corpus DB for the measurement side: the gold-id preflight
    (EV-7). Never writes; opened separately from the retriever's own store."""

    def __init__(self, db_path):
        self._con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self._chunks_by_paper: dict[str, dict[str, list[tuple[str, str]]]] = {}

    def close(self) -> None:
        self._con.close()

    def _missing(self, table: str, column: str, ids: set[str]) -> list[str]:
        found: set[str] = set()
        wanted = sorted(ids)
        for i in range(0, len(wanted), 500):  # stay under SQLite's bound-variable limit
            batch = wanted[i : i + 500]
            marks = ",".join("?" * len(batch))
            found |= {
                r[0]
                for r in self._con.execute(
                    f"SELECT {column} FROM {table} WHERE {column} IN ({marks})", batch
                )
            }
        return sorted(ids - found)

    def chunk_ids_for(self, paper_id: str, block_id: str, passage_text: str) -> list[str]:
        """EV-9: ids of the chunks of `paper_id` anchored on `block_id` whose text equals
        `passage_text` (GroundedResult carries no chunk id). Exactly one id when recoverable; ALL
        matches when identical text sits on one anchor (the caller marks the row ambiguous --
        never picks one); [] when nothing matches. Loaded and cached per paper."""
        if paper_id not in self._chunks_by_paper:
            by_anchor: dict[str, list[tuple[str, str]]] = {}
            for cid, text, anchor_json in self._con.execute(
                "SELECT chunk_id, text, anchor_json FROM chunks WHERE paper_id = ?", (paper_id,)
            ):
                by_anchor.setdefault(json.loads(anchor_json)["block_id"], []).append((cid, text))
            self._chunks_by_paper[paper_id] = by_anchor
        return sorted(
            cid
            for cid, text in self._chunks_by_paper[paper_id].get(block_id, ())
            if text == passage_text
        )

    def chunk_text(self, chunk_id: str) -> str | None:
        row = self._con.execute(
            "SELECT text FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        return row[0] if row else None

    def attach_gold_texts(self, questions: list[Question]) -> list[Question]:
        """Questions with `alt_chunk_texts` = DB text of each gold / alternative chunk (EV-8).
        Ids that do not resolve are skipped here (the preflight is what fails on them)."""
        out = []
        for q in questions:
            ids = [c for c in (q.gold_chunk_id, *q.alternative_gold_chunk_ids) if c]
            texts = tuple(t for t in (self.chunk_text(c) for c in ids) if t is not None)
            out.append(replace(q, alt_chunk_texts=texts) if texts else q)
        return out

    def unresolved_gold_ids(self, questions: list[Question]) -> dict[str, list[str]]:
        """{kind: sorted unresolved ids} for gold paper / block / chunk ids absent from this DB
        (empty dict = every gold id resolves). A mispointed `--db-path` otherwise yields a
        plausible low number with `n_errors = 0`."""
        papers = {p for q in questions for p in q.gold_paper_ids}
        blocks = {q.gold_block_id for q in questions if q.gold_block_id}
        chunks = {
            c
            for q in questions
            for c in (q.gold_chunk_id, *q.alternative_gold_chunk_ids)
            if c
        }
        missing = {
            "paper": self._missing("papers", "paper_id", papers),
            "block": self._missing("blocks", "block_id", blocks),
            "chunk": self._missing("chunks", "chunk_id", chunks),
        }
        return {kind: ids for kind, ids in missing.items() if ids}


def _normalized(text: str) -> str:
    """Casefold + collapse runs of whitespace -- the entire normalization behind the title_leak
    predicate. Nothing smarter (stemming, punctuation folding) on purpose: the diagnostic's
    honesty depends on matching being strictly verbatim-after-normalization."""
    return " ".join(text.casefold().split())


def _title_leak(result, gold_paper_ids: frozenset[str]) -> bool:
    """The verbatim title-leak predicate for one retrieved result (RI-15). Narrow by design:

      * scoped to would-be hits -- a result whose `paper_id` is outside the gold set is out of
        scope even when its passage quotes some title;
      * the title examined is the result's own citation title -- the one place a gold paper's
        title is observable at scoring time without a second corpus lookup;
      * matching is contiguous-substring after `_normalized`, so paraphrase-level overlap leaves
        this False, which is why the aggregate is reported as a floor (see `_TITLE_LEAK_NOTE`).

    Diagnostic input only: it qualifies a hit, it does not un-hit it.
    """
    if result.paper_id not in gold_paper_ids:
        return False
    title = _normalized(result.citation.title or "")
    return bool(title) and title in _normalized(result.passage_text)


def score_question(
    question: Question, results: list, k: int, chapter_results: list | None = None,
    chunk_lookup: "CorpusLookup | None" = None,
) -> QuestionResult:
    """`results` is the `list[GroundedResult]` a real (or fake) `Retriever.retrieve()` call
    returned -- already truncated to `k` by `Retriever` itself, but truncated again here so a
    test double that doesn't truncate still scores correctly.

    `chapter_results` is the `list[PaperSearchResult]` a real (or fake) `Retriever.
    retrieve_papers()` call returned, for `gold_chapter_title` questions only -- `run()` doesn't
    make that call at all for a question that isn't chapter-scored, so this is `None` in that
    case (never an empty list standing in for "not scored").

    `chunk_lookup` (EV-9) is only used to record `retrieved_chunk_ids`; it never feeds a hit rule.
    """
    truncated = results[:k]
    paper_rank = next(
        (i for i, r in enumerate(truncated, start=1) if r.paper_id in question.gold_paper_ids),
        None,
    )
    passage_scored = question.gold_block_id is not None
    passage_rank = None
    if passage_scored:
        passage_rank = next(
            (
                i
                for i, r in enumerate(truncated, start=1)
                if r.anchor.block_id == question.gold_block_id
            ),
            None,
        )
    # EV-8: additive excerpt-containment rank; items without an excerpt block fall back to the
    # anchor rule (and are flagged so build_report can list them).
    excerpt_fallback = passage_scored and (
        question.excerpt_block_id is None or not question.passage_excerpt
    )
    excerpt_rank = None
    if passage_scored:
        excerpt_rank = passage_rank if excerpt_fallback else next(
            (
                i
                for i, r in enumerate(truncated, start=1)
                if excerpt_hit(question, r.passage_text)
            ),
            None,
        )
    chapter_scored = question.gold_chapter_title is not None
    chapter_rank = None
    if chapter_scored and chapter_results is not None:
        chapter_rank = next(
            (
                i
                for i, r in enumerate(chapter_results[:k], start=1)
                if r.view.paper_id in question.gold_paper_ids
                and r.chapter == question.gold_chapter_title
            ),
            None,
        )
    return QuestionResult(
        retrieved_paper_ids=tuple(r.paper_id for r in truncated),
        retrieved_block_ids=tuple(r.anchor.block_id for r in truncated),
        excerpt_rank=excerpt_rank,
        excerpt_fallback=excerpt_fallback,
        retrieved_chunk_ids=(
            tuple(
                tuple(chunk_lookup.chunk_ids_for(r.paper_id, r.anchor.block_id, r.passage_text))
                for r in truncated
            )
            if chunk_lookup is not None
            else ()
        ),
        question_id=question.question_id,
        question_type=question.question_type,
        paper_rank=paper_rank,
        passage_rank=passage_rank,
        passage_scored=passage_scored,
        gold_paper_ids=question.gold_paper_ids,
        gold_block_id=question.gold_block_id,
        doc_type=question.doc_type,
        vision_derived=question.vision_derived,
        chapter_rank=chapter_rank,
        chapter_scored=chapter_scored,
        gold_chapter_title=question.gold_chapter_title,
        title_leak=any(_title_leak(r, question.gold_paper_ids) for r in truncated),
        # RI-M7: rank-1's own score, whatever hit rule says about it -- a known-absent question
        # has no gold_paper_ids to hit, but still has a top result (and a top score) whenever the
        # corpus is non-empty, which is exactly the number the score-distribution census reads.
        top_score=truncated[0].score if truncated else None,
    )


GPU_LOCK_TIMEOUT = "gpu_lock_timeout"


def _error_class(error: Exception) -> str | None:
    """EV-10: classify a per-question retrieval error. A lock timeout is raised by
    rag/gpu_lock.py as TransientError("gpu lock <path> not acquired within <n>s for stage ...");
    matched on that message (the retriever may wrap the exception type) over the cause chain."""
    seen = error
    while seen is not None:
        text = str(seen)
        if "gpu lock" in text and "not acquired within" in text:
            return GPU_LOCK_TIMEOUT
        seen = seen.__cause__
    return None


def run(
    questions: list[Question], retriever, k: int, chunk_lookup: "CorpusLookup | None" = None
) -> list[QuestionResult]:
    """Calls the real (or fake) `retriever.retrieve(question_text, filters, k)` for every
    question -- plus `retriever.retrieve_papers(question_text, filters, k)` too, but only for a
    question carrying a `gold_chapter_title` (a chapter-routing question doesn't get scored
    without it, so there's no point spending the extra retrieval call on every other question --
    in particular the existing 210-question/equation-slice fixtures, which carry no book fields
    at all, cost exactly what they did before this metric existed).

    A retrieval error for one question is recorded and skipped, not fatal to the whole run
    (mirrors `Retriever`'s own "drop the bad hit, keep going" posture, T-DOC38) -- a single
    orphaned/unresolvable corpus row shouldn't blank out every other question's score. Both calls
    for one question share a single try/except: if `retrieve()` succeeds but the follow-up
    `retrieve_papers()` then fails, the whole question is recorded as errored rather than
    half-scored on a retrieval pipeline that just proved itself unreliable for this query.
    """
    results = []
    for i, question in enumerate(questions, start=1):
        try:
            hits, _coverage = retriever.retrieve(question.question_text, None, k)
            chapter_hits = None
            if question.gold_chapter_title is not None:
                chapter_hits, _coverage2 = retriever.retrieve_papers(
                    question.question_text, None, k
                )
        except Exception as e:  # noqa: BLE001 -- deliberately broad, see docstring
            logger.warning("retrieve() failed for %s: %s", question.question_id, e)
            results.append(
                QuestionResult(
                    question_id=question.question_id,
                    question_type=question.question_type,
                    paper_rank=None,
                    passage_rank=None,
                    passage_scored=question.gold_block_id is not None,
                    error=str(e),
                    error_class=_error_class(e),
                    gold_paper_ids=question.gold_paper_ids,
                    gold_block_id=question.gold_block_id,
                    doc_type=question.doc_type,
                    vision_derived=question.vision_derived,
                    chapter_scored=question.gold_chapter_title is not None,
                    gold_chapter_title=question.gold_chapter_title,
                )
            )
            continue
        results.append(score_question(question, hits, k, chapter_hits, chunk_lookup))
        if i % 20 == 0:
            logger.info("scored %d/%d questions", i, len(questions))
    return results


def _recall_mrr(ranks: list[int | None]) -> dict:
    n = len(ranks)
    if n == 0:
        return {"recall_at_k": None, "mrr": None, "n": 0}
    hits = sum(1 for r in ranks if r is not None)
    rr_sum = sum(1.0 / r for r in ranks if r is not None)
    return {"recall_at_k": hits / n, "mrr": rr_sum / n, "n": n}


# BENCH-1: a fixture that mixes answerable items with known-absent ones (waymo_gt_verified.json's
# 8 no-gold items) must not let the guaranteed misses deflate the headline recall -- an item that
# CANNOT hit is a different fact from one the retriever failed to hit. The partition lives inside
# build_report (the artifact others read) rather than in caller discipline, because a rule that
# only some callers remember is how a deflated number ships silently. 'overall' keeps its exact
# pre-partition definition so reports over the existing all-answerable fixtures are unchanged;
# the two arms travel alongside it, additively.
_GOLD_STATUS_NOTE = (
    "Partition by gold-set presence (BENCH-1): a question whose gold_paper_ids set is empty has "
    "nothing to retrieve against -- a known-absent item, a guaranteed miss -- so blending it into "
    "recall deflates the headline with items that cannot hit rather than failures to hit. "
    "'answerable' is the false-negative measure; 'known_absent' is the false-positive arm, read "
    "through its top-score distribution because recall is undefined when no hit is possible. "
    "'overall' is retained unpartitioned exactly as earlier reports computed it, for diff "
    "compatibility -- do not quote it as the headline for a fixture that mixes the arms."
)

_KNOWN_ABSENT_METRIC_NOTE = (
    "recall/MRR withheld by design: an empty gold set misses by construction, so a number here "
    "would measure the fixture, not the retriever. Read this arm through n_with_top_result and "
    "the top_score distribution."
)

# VARM-1: same reasoning as _GOLD_STATUS_NOTE, one partition over -- a fixture can also mix items
# a text retriever CAN be fairly scored against with items it structurally cannot. The partition
# lives inside build_report (the artifact others read) for the same reason: a blended number is
# how an impossible target ships looking merely unmet.
_VISION_ARM_NOTE = (
    "Partition by vision-derivation among passage-scored questions (VARM-1): a vision_derived "
    "item's answer exists only inside a figure -- the gold chunk's own text does not contain it "
    "-- so no text retriever has anything to rank on, and blending such items into the passage "
    "headline caps it below any achievable target (60/64 = 0.9375 on waymo_gt_verified.json). "
    "'text_answerable' is the arm the >=0.95 passage-precision target applies to; 'vision' keeps "
    "its own denominator and reports paper-level recall@k alongside its passage metrics because "
    "paper-level retrieval already finds these items -- there the gap is reading figures, not "
    "finding the page. 'overall' is retained unpartitioned exactly as earlier reports computed "
    "it, for diff compatibility; when a fixture has no vision-derived items, text_answerable's "
    "recall/MRR/n equal overall's exactly."
)


def _rank_1_rate(ranks: list[int | None]) -> float | None:
    """Fraction of scored items whose FIRST result was already the hit -- the precision-at-1
    reading of a rank list. None for an empty arm (no denominator), mirroring _recall_mrr."""
    n = len(ranks)
    if n == 0:
        return None
    return sum(1 for r in ranks if r == 1) / n


def _vision_arm_summary(results: list[QuestionResult]) -> dict:
    """One arm of passage_level.by_vision_status (VARM-1): the passage metrics under the same
    hit rule as 'overall', plus rank_1_rate (the >=0.95 target is a precision-at-1 statement,
    which recall@k alone cannot answer) and the arm's own paper-level line -- the two
    granularities side by side is what makes the vision arm's number interpretable."""
    ranks = [r.passage_rank for r in results]
    return {
        **_recall_mrr(ranks),
        "rank_1_rate": _rank_1_rate(ranks),
        "paper_level": _recall_mrr([r.paper_rank for r in results]),
    }


def _top_score_summary(scores: list[float]) -> dict:
    """Lightweight distribution summary for build_report's known-absent arm -- what came back and
    at what scores. Deliberately not app.score_distribution_census.distribution_stats' richer
    shape: that module owns the IQR separation verdict and imports this module, so reaching back
    into it from here would invert the dependency; this arm needs min/median/mean/max, no IQR."""
    n = len(scores)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": n,
        "mean": statistics.mean(scores),
        "median": statistics.median(scores),
        "min": min(scores),
        "max": max(scores),
    }


def _question_row(r: QuestionResult) -> dict:
    """One `results` entry as a before/after-diffable dict: gold ids plus hit/rank at both
    granularities. `error` is carried at the top so a question that errored in one run but
    scored in another is visible without inferring it from `null` ranks (a null rank alone is
    ambiguous between "errored" and "ran clean but missed").
    """
    return {
        "question_id": r.question_id,
        "question_type": r.question_type,
        "doc_type": r.doc_type,
        "vision_derived": r.vision_derived,
        "gold_paper_ids": sorted(r.gold_paper_ids),
        "gold_block_id": r.gold_block_id,
        "gold_chapter_title": r.gold_chapter_title,
        "error": r.error,
        "error_class": r.error_class,
        # Diagnostic only -- see build_report's paper_level.title_leak note; not an input to
        # hit/rank above (pinned by test_build_report_reports_leaks_alongside_untouched_metrics).
        "title_leak": r.title_leak,
        # RI-M7: rank-1's score, independent of hit/miss -- see QuestionResult.top_score.
        "top_score": r.top_score,
        "retrieved_paper_ids": list(r.retrieved_paper_ids),
        "retrieved_block_ids": list(r.retrieved_block_ids),
        # EV-9: additive; one candidate list per rank (see QuestionResult.retrieved_chunk_ids).
        "retrieved_chunk_ids": [list(ids) for ids in r.retrieved_chunk_ids],
        "chunk_id_ambiguous": any(len(ids) > 1 for ids in r.retrieved_chunk_ids),
        "paper_level": {"hit": r.paper_rank is not None, "rank": r.paper_rank},
        "passage_level": {
            "scored": r.passage_scored,
            "hit": r.passage_rank is not None,
            "rank": r.passage_rank,
        },
        "chapter_level": {
            "scored": r.chapter_scored,
            "hit": r.chapter_rank is not None,
            "rank": r.chapter_rank,
        },
        # EV-8: additive; `passage_level` above is the unchanged anchor rule.
        "passage_excerpt_level": {
            "scored": r.passage_scored,
            "hit": r.excerpt_rank is not None,
            "rank": r.excerpt_rank,
            "fallback": r.excerpt_fallback,
        },
    }


_EXCERPT_SCORING_RULE = (
    "top-{k} truncation; passage_excerpt hit = first rank r <= {k} whose passage_text (casefolded, "
    "whitespace collapsed) contains the question's passage_excerpt or equals the text of its gold "
    "/ alternative_gold_chunk_ids chunk; questions with a null excerpt_block_id use the anchor "
    "rule (result.anchor.block_id == gold_block_id) and are listed in fallback_question_ids. "
    "Reported beside, never in place of, passage_level (anchor rule) and the protocols' "
    "member-passage metric (scripts/eval_strata_report.py)."
)


def _scoring_rule(k: int, mode: str, hybrid_dense_weight: float) -> str:
    """The hit rule in force, formatted with the k it was applied at, PLUS (RI-M3) which
    sparse-arm ablation mode produced this report and the RRF weight that means. Stamped into
    every emitted report (`build_report`) so two numbers produced under different rules -- or
    different ablation modes -- cannot be silently compared: a number in a JSON file outlives
    everyone's memory of how it was computed."""
    return (
        f"top-{k} truncation; sparse_mode={mode} (hybrid_dense_weight={hybrid_dense_weight} -- "
        f"zeroes a score contribution, does not remove that arm's candidates from the fused "
        f"pool, see module docstring); paper-level hit = first rank r <= {k} with "
        f"result.paper_id in question.gold_paper_ids; passage-level hit = first rank r <= {k} "
        f"with result.anchor.block_id == question.gold_block_id; chapter-level hit = first "
        f"retrieve_papers rank with paper_id in gold_paper_ids and chapter == "
        f"gold_chapter_title"
    )


def build_report(
    results: list[QuestionResult],
    k: int,
    *,
    mode: str = "fused",
    hybrid_dense_weight: float = 0.5,
    include_per_question: bool = True,
    ground_truth_sha256_12: str | None = None,
    code_commit: str | None = None,
    code_tree_dirty: bool | None = None,
) -> dict:
    question_types = sorted({r.question_type for r in results})
    doc_types = sorted({r.doc_type for r in results})
    passage_eligible = [r for r in results if r.passage_scored]
    chapter_eligible = [r for r in results if r.chapter_scored]
    # The leak aggregate is computed over the hits so leaking is structurally a subset of hitting,
    # whatever a hand-built QuestionResult claims.
    hits = [r for r in results if r.paper_rank is not None]
    n_leaking = sum(1 for r in hits if r.title_leak)
    # BENCH-1: see _GOLD_STATUS_NOTE. Partition by gold-set presence, not by fixture file, so any
    # mixed ground-truth file partitions correctly without a new per-fixture flag to remember.
    answerable_results = [r for r in results if r.gold_paper_ids]
    absent_results = [r for r in results if not r.gold_paper_ids]
    absent_scores = [r.top_score for r in absent_results if r.top_score is not None]
    # VARM-1: see _VISION_ARM_NOTE. Same posture as the gold-status partition above -- membership
    # comes from the results themselves (passage_scored x vision_derived), never from fixture-file
    # discipline, and 'overall' below stays untouched so existing fixtures' numbers do not move.
    text_arm_results = [r for r in passage_eligible if not r.vision_derived]
    vision_arm_results = [r for r in passage_eligible if r.vision_derived]
    excerpt_fallbacks = [r for r in passage_eligible if r.excerpt_fallback]
    n_lock_timeouts = sum(1 for r in results if r.error_class == GPU_LOCK_TIMEOUT)

    report = {
        # RI-15: names the hit rule and k in force, so reports produced under different rules are
        # not comparable by accident. RI-M3 extends this to also name the sparse-ablation mode
        # (and its RRF weight) rather than adding a second, parallel report field for it.
        # See _scoring_rule.
        "scoring_rule": _scoring_rule(k, mode, hybrid_dense_weight),
        # EV-7: what produced this number -- the ground-truth file (judge_eval's
        # `rubric_sha256_12` pattern) and the code commit. None when the caller did not supply
        # them (unit tests, in-process reuse by other experiment modules).
        "ground_truth_sha256_12": ground_truth_sha256_12,
        "code_commit": code_commit,
        "code_tree_dirty": code_tree_dirty,
        "k": k,
        "n_questions": len(results),
        "n_errors": sum(1 for r in results if r.error),
        # EV-10: a question that errored on a GPU-lock timeout never ran -- scoring it as a miss
        # (SB-1) makes the whole run a partially starved, untrustworthy measurement. Header-level
        # so a reader sees it before any metric; same VOID convention as scripts/nb_eval_runner.py.
        "run_valid": n_lock_timeouts == 0,
        "n_lock_timeouts": n_lock_timeouts,
        "invalid_reason": (
            f"{n_lock_timeouts} question(s) errored on a GPU-lock timeout and never ran; their "
            "rows are counted as misses below -- do not use any number in this report; re-run "
            "with no concurrent GPU-lock contention"
            if n_lock_timeouts
            else None
        ),
        # EV-9: ambiguity is counted, not hidden (rows with a rank matching >1 chunk; ranks that
        # matched no chunk -- nonzero only when a CorpusLookup was supplied to `run`).
        "n_chunk_id_ambiguous_rows": sum(
            1 for r in results if any(len(ids) > 1 for ids in r.retrieved_chunk_ids)
        ),
        "n_chunk_id_unresolved_ranks": sum(
            1 for r in results for ids in r.retrieved_chunk_ids if not ids
        ),
        "paper_level": {
            "overall": _recall_mrr([r.paper_rank for r in results]),
            # BENCH-1: the two arms a mixed fixture must be read through. Additive -- 'overall'
            # above is untouched, so reports over fixtures where every question is answerable
            # (the 210-set, the equation slice) carry numbers identical to pre-partition runs.
            "by_gold_status": {
                "note": _GOLD_STATUS_NOTE,
                "answerable": _recall_mrr([r.paper_rank for r in answerable_results]),
                "known_absent": {
                    "n": len(absent_results),
                    "recall_at_k": None,
                    "mrr": None,
                    "metric_note": _KNOWN_ABSENT_METRIC_NOTE,
                    "n_with_top_result": len(absent_scores),
                    "top_score": _top_score_summary(absent_scores),
                },
            },
            "by_question_type": {
                t: _recall_mrr([r.paper_rank for r in results if r.question_type == t])
                for t in question_types
            },
            # T-DOC-BOOK-EVAL: lets one mixed paper+book fixture be scored in a single run and
            # still reported separately -- "must be able to evaluate books separately from papers,
            # and report them separately" (docs/DESIGN-book-chapters-and-hierarchy.md Part 3 Step 1).
            "by_doc_type": {
                dt: _recall_mrr([r.paper_rank for r in results if r.doc_type == dt])
                for dt in doc_types
            },
            # RI-15 verbatim title-leak diagnostic. Reported alongside the metrics, deducted from
            # none of them (pinned by test_build_report_reports_leaks_alongside_untouched_metrics):
            # what to do about the number is not the instrument's call. `_TITLE_LEAK_NOTE` travels
            # inside the emitted JSON because the floor limitation belongs to the artifact, not
            # just this module's docstring.
            "title_leak": {
                "predicate": "verbatim-substring",
                "n_hits": len(hits),
                "n_leaking": n_leaking,
                "fraction_of_hits": (n_leaking / len(hits)) if hits else None,
                "note": _TITLE_LEAK_NOTE,
            },
        },
        "passage_level": {
            "n_scored": len(passage_eligible),
            "overall": _recall_mrr([r.passage_rank for r in passage_eligible]),
            # VARM-1: the three arms a passage-level target must be read through. Additive --
            # 'overall' above is untouched, and on a fixture with no vision_derived items the
            # text arm's recall/MRR/n equal 'overall' exactly (pinned by
            # test_build_report_no_vision_fixture_text_arm_equals_overall_and_vision_empty), so
            # 210-set/equation-slice reports carry numbers identical to pre-VARM-1 runs.
            "by_vision_status": {
                "note": _VISION_ARM_NOTE,
                "text_answerable": _vision_arm_summary(text_arm_results),
                "vision": _vision_arm_summary(vision_arm_results),
            },
            "by_question_type": {
                t: _recall_mrr(
                    [r.passage_rank for r in passage_eligible if r.question_type == t]
                )
                for t in sorted({r.question_type for r in passage_eligible})
            },
            "by_doc_type": {
                dt: _recall_mrr([r.passage_rank for r in passage_eligible if r.doc_type == dt])
                for dt in sorted({r.doc_type for r in passage_eligible})
            },
        },
        # EV-8: excerpt-containment passage metric, BESIDE the anchor `passage_level` (which is
        # untouched). Same denominator (questions with a gold_block_id); items without an excerpt
        # block use the anchor rule and are listed so the mix is never hidden.
        "passage_excerpt_level": {
            "scoring_rule": _EXCERPT_SCORING_RULE.format(k=k),
            "n_scored": len(passage_eligible),
            "n_fallback_anchor": len(excerpt_fallbacks),
            "fallback_question_ids": [r.question_id for r in excerpt_fallbacks],
            "overall": _recall_mrr([r.excerpt_rank for r in passage_eligible]),
            "by_question_type": {
                t: _recall_mrr(
                    [r.excerpt_rank for r in passage_eligible if r.question_type == t]
                )
                for t in sorted({r.question_type for r in passage_eligible})
            },
            "by_doc_type": {
                dt: _recall_mrr([r.excerpt_rank for r in passage_eligible if r.doc_type == dt])
                for dt in sorted({r.doc_type for r in passage_eligible})
            },
        },
        # Chapter-routing accuracy (search_papers) -- distinct from passage_level (semantic_search)
        # per the design doc: "This is what chapter summaries exist for" vs. "whether chapter work
        # affects retrieval at all, or only navigation." Empty/all-n=0 for any fixture with no
        # gold_chapter_title (the 210-question and equation-slice sets today).
        "chapter_level": {
            "n_scored": len(chapter_eligible),
            "overall": _recall_mrr([r.chapter_rank for r in chapter_eligible]),
            "by_question_type": {
                t: _recall_mrr(
                    [r.chapter_rank for r in chapter_eligible if r.question_type == t]
                )
                for t in sorted({r.question_type for r in chapter_eligible})
            },
        },
    }
    if include_per_question:
        # T-DOC57: lets a before/after diff (e.g. the T-EVAL re-measure) be computed from two
        # report JSONs alone -- no re-running the eval to find which questions moved.
        report["questions"] = [_question_row(r) for r in results]
    return report


def _print_summary(report: dict) -> None:
    def _fmt(m: dict) -> str:
        if m["n"] == 0:
            return "n=0 (no questions in this split)"
        return f"Recall@{report['k']}={m['recall_at_k']:.3f}  MRR={m['mrr']:.3f}  (n={m['n']})"

    if not report["run_valid"]:
        print(f"*** RUN INVALID: {report['invalid_reason']} ***")
    print(f"Scoring rule: {report['scoring_rule']}")
    print(f"Questions scored: {report['n_questions']} (errors: {report['n_errors']})")
    # BENCH-1: a mixed fixture prints its two arms, not the blend -- the unpartitioned 'overall'
    # stays in the JSON for diff compatibility only. An all-answerable fixture keeps the
    # historical single headline line, byte for byte.
    gold_status = report["paper_level"]["by_gold_status"]
    if gold_status["known_absent"]["n"]:
        print(f"Paper-level (answerable arm) {_fmt(gold_status['answerable'])}")
        absent = gold_status["known_absent"]
        ts = absent["top_score"]
        if ts["n"]:
            print(
                f"Known-absent arm n={absent['n']}  with a top result: {absent['n_with_top_result']}"
                f"  top_score median={ts['median']:.4f}  range=[{ts['min']:.4f}, {ts['max']:.4f}]"
            )
        else:
            print(f"Known-absent arm n={absent['n']}  (no top scores recorded)")
        print(f"  ({absent['metric_note']})")
    else:
        print(f"Paper-level   {_fmt(report['paper_level']['overall'])}")
    tl = report["paper_level"]["title_leak"]
    if tl["n_hits"]:
        print(
            f"Title-leak    {tl['n_leaking']}/{tl['n_hits']} of paper-level hits embed their gold "
            "title verbatim -- a floor estimate, paraphrase leaks go uncounted; diagnostic only, "
            "not deducted from the metrics above"
        )
    pl = report["passage_level"]
    if pl["n_scored"]:
        print(f"Passage-level {_fmt(pl['overall'])}  [{pl['n_scored']}/{report['n_questions']} "
              "questions carry a gold_block_id]")
    else:
        print("Passage-level: no question in this ground-truth file carries a gold_block_id "
              "-- nothing to score (this is expected for the 210-question set)")
    pe = report["passage_excerpt_level"]
    if pe["n_scored"]:
        print(f"Passage-excerpt {_fmt(pe['overall'])}  [{pe['n_fallback_anchor']} of "
              f"{pe['n_scored']} fell back to the anchor rule: null excerpt_block_id]")
    cl = report["chapter_level"]
    if cl["n_scored"]:
        print(f"Chapter-level {_fmt(cl['overall'])}  [{cl['n_scored']}/{report['n_questions']} "
              "questions carry a gold_chapter_title]")
    else:
        print("Chapter-level: no question in this ground-truth file carries a gold_chapter_title "
              "-- nothing to score (this is expected for a papers-only fixture)")

    print("\nBy question_type (paper-level):")
    for t, m in sorted(report["paper_level"]["by_question_type"].items()):
        print(f"  {t:30s} {_fmt(m)}")
    if pl["n_scored"]:
        print("\nBy question_type (passage-level):")
        for t, m in sorted(pl["by_question_type"].items()):
            print(f"  {t:30s} {_fmt(m)}")
    if cl["n_scored"]:
        print("\nBy question_type (chapter-level):")
        for t, m in sorted(cl["by_question_type"].items()):
            print(f"  {t:30s} {_fmt(m)}")

    dt = report["paper_level"]["by_doc_type"]
    if len(dt) > 1:
        print("\nBy doc_type (paper-level):")
        for t, m in sorted(dt.items()):
            print(f"  {t:30s} {_fmt(m)}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", default=_DEFAULT_GROUND_TRUTH)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--blob-dir", default=None)
    parser.add_argument(
        "--collection", required=True,
        help="REQUIRED (EV-7): named vector-store collection to search. There is no default -- "
             "an omitted flag used to fall through to the main `papers` corpus and a mispointed "
             "run printed a plausible low number with 0 errors",
    )
    parser.add_argument("--k", type=int, default=_DEFAULT_K)
    parser.add_argument("--report-path", default=None, help="write the JSON report here")
    parser.add_argument(
        "--limit", type=int, default=None, help="score only the first N questions (smoke test)"
    )
    parser.add_argument(
        "--no-per-question", action="store_true",
        help="omit the report's per-question array (present by default) -- use if it bloats the "
             "report and only the aggregates are needed",
    )
    parser.add_argument(
        "--sparse-mode", choices=SPARSE_MODES, default="fused",
        help="RI-M3 sparse-arm ablation: 'dense_only'/'sparse_only' pin hybrid_dense_weight to "
             "the RRF extreme that zeroes the other arm's score contribution; 'fused' (default) "
             "uses the loaded config's own hybrid_dense_weight unchanged. See module docstring.",
    )
    parser.add_argument(
        "--dense-weight", type=float, default=None,
        help="FUSE-1 sweep override: pin hybrid_dense_weight to this exact [0, 1] value instead "
             "of the config's own or --sparse-mode's mapped extreme; wins when both are given. "
             "The used value is stamped into the report's scoring_rule.",
    )
    parser.add_argument(
        "--drop-stub-chunks", action="store_true",
        help="CQ-3 A/B arm: drop heading-only chunks before reranking (Retriever's "
             "drop_stub_chunks). Default off = baseline.",
    )
    parser.add_argument(
        "--relevance-demotion", choices=["tail", "penalty"], default=None,
        help="RQ-2 A/B arm: after reranking, move results whose paper relevance_score < "
             "--relevance-tau down (never dropped). tail = behind all others; penalty = down "
             "--relevance-penalty ranks. Default off = baseline.",
    )
    parser.add_argument("--relevance-tau", type=float, default=0.30,
                        help="RQ-2: relevance_score threshold (only with --relevance-demotion).")
    parser.add_argument("--relevance-penalty", type=int, default=5,
                        help="RQ-2: rank positions a below-tau result drops (penalty mode only).")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()

    from rag.config import load_config

    questions = load_questions(Path(args.ground_truth))
    if args.limit is not None:
        questions = questions[: args.limit]

    # EV-7 preflight, BEFORE any service is touched: every gold id must resolve in the DB this run
    # will query, else exit 2 naming them. Read-only. `--db-path` wins, else the config's own --
    # the same precedence as app.assembly._resolve_store_paths.
    db_path = args.db_path or load_config(args.config).db_path
    lookup = CorpusLookup(db_path)
    unresolved = lookup.unresolved_gold_ids(questions)
    if unresolved:
        for kind, ids in unresolved.items():
            print(
                f"PREFLIGHT FAILED: {len(ids)} gold {kind} id(s) not found in {db_path}: "
                f"{', '.join(ids[:20])}{' ...' if len(ids) > 20 else ''}",
                file=sys.stderr,
            )
        sys.exit(EXIT_PREFLIGHT_FAILED)
    questions = lookup.attach_gold_texts(questions)
    # Deferred import: pulls in the real (GPU-backed) adapter wiring, which unit tests must never
    # touch (they exercise load_questions/score_question/run/build_report against a fake
    # retriever instead) -- see app/test_retrieval_eval.py. After the preflight so a bad fixture
    # or DB fails before any adapter is imported.
    from app.assembly import build_mcp_server

    config = load_config(args.config)
    # RI-M3: resolve the ablation mode to a concrete hybrid_dense_weight; FUSE-1 extends this
    # with an explicit --dense-weight that pins any intermediate value (the modes alone can only
    # name the extremes). build_mcp_server reads config.hybrid_dense_weight to construct its
    # VectorIndex, so this is the one place the override needs to land. `model_copy` (Config is a
    # frozen pydantic model, contracts/_base.py) produces a new instance rather than mutating the
    # frozen one build_mcp_server also gets.
    weight = resolve_hybrid_weight(
        args.sparse_mode, config.hybrid_dense_weight, args.dense_weight
    )
    if weight != config.hybrid_dense_weight:
        config = config.model_copy(update={"hybrid_dense_weight": weight})

    build_kwargs = {}
    if args.db_path is not None:
        build_kwargs["db_path"] = args.db_path
    if args.blob_dir is not None:
        build_kwargs["blob_dir"] = args.blob_dir
    build_kwargs["collection"] = args.collection
    if args.drop_stub_chunks:
        build_kwargs["drop_stub_chunks"] = True
    if args.relevance_demotion is not None:
        build_kwargs.update(
            relevance_demotion=args.relevance_demotion, relevance_tau=args.relevance_tau,
            relevance_penalty=args.relevance_penalty,
        )
    server = build_mcp_server(config, **build_kwargs)

    results = run(questions, server.retriever, args.k, chunk_lookup=lookup)
    lookup.close()
    commit, dirty = code_commit()
    report = build_report(
        results, args.k, mode=args.sparse_mode, hybrid_dense_weight=weight,
        include_per_question=not args.no_per_question,
        ground_truth_sha256_12=file_sha256_12(Path(args.ground_truth)),
        code_commit=commit, code_tree_dirty=dirty,
    )
    _print_summary(report)

    if args.report_path:
        Path(args.report_path).write_text(json.dumps(report, indent=2))
        print(f"\nWrote report to {args.report_path}")
    if not report["run_valid"]:
        sys.exit(EXIT_INVALID_RUN)


if __name__ == "__main__":
    main()
