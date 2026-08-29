"""`python -m app.exp_agentic_loop_v0` -- SB-3, agentic loop prototype v0 (precision-95 programme).

Two independent, separately-verdicted arms, neither wired into the product surface (M8/MCP) --
this module only measures whether either mechanism is worth building for real:

  (a) A CRAG-style retrieval evaluator (Yan et al. 2024): one local generation-LLM call per
      question scores whether the RETRIEVED PASSAGES (not a generated answer) look sufficient to
      answer the question, mapped to one of {proceed, decompose, abstain}.
  (b) An IRCoT/Self-Ask-style decomposition arm (Trivedi et al. 2023 / Press et al. 2022):
      another LLM call breaks a question into sub-questions, each retrieved separately and
      merged, ROUTED by a stratum flag rather than applied globally.

FROZEN BEFORE ANY LABEL-BEARING RUN (this docstring, commit (1) of this ticket -- neither this
module nor any flag it exposes can retune the numbers below; NB-C2's own precedent, and the
programme's post-mortem on it, is why this line is drawn before the first real call, not after):

  **Arm (a) falsification criterion.** AUROC of the evaluator's `sufficiency` score, oriented
  "answerable scores higher than known-absent", computed SEPARATELY on `fixtures/eval/gt_wmr.json`
  and `fixtures/eval/waymo_gt_verified.json` ("ver84") via `app.retrieval_eval.load_questions`'s
  existing dedup -- must be >= 0.75 on **BOTH** fixtures to ADOPT. A miss on either fixture is a
  REJECT, reported plainly (see `docs/eval-reports/2026-08-25-nb-c2-anchor-probe.md`: a prior
  lane tried a different pre-generation signal for this exact separation and failed by a wide
  margin -- 0.4824 / 0.3563 -- so failure here is an expected, legitimate outcome, not a bug to
  chase). Label: `absent` iff `Question.gold_paper_ids` is empty after `load_questions`' own
  dedup (identical convention to NB-C2/NB-D3 -- a known-absent item carries no gold paper/passage
  by construction). No threshold, prompt wording, or passage count may change after any
  label-bearing run starts; a run with `n_errors > 0` is VOID (`scripts/nb_eval_runner.py`'s own
  rule) and must be discarded and re-run, never patched into a passing number.

  **Arm (a) action mapping is illustrative, not calibrated.** `sufficiency >= 0.66` ->
  "proceed"; `< 0.33` -> "abstain"; otherwise "decompose". These two cut points are arbitrary
  tertile splits fixed here for the sake of demonstrating the {proceed, decompose, abstain} seam
  end-to-end -- exactly like QW-2's raw score, NO fit, NO IN-2-style anchor grading backs them,
  and the report must never present the resulting action counts as a validated policy.

  **Arm (b) routing rule.** Route to decomposition iff, on that question's OWN fixture record
  (`gt_wmr.json`/`waymo_gt_verified.json`, read directly -- `Question` itself does not carry
  these fields): `difficulty == "hard"` OR `dimension in {"multi-paper synthesis", "negation and
  scope"}`. This is the ticket's own "multi-hop / hard / negation" language mapped onto the two
  fixtures' existing authored metadata (`dimension`, `difficulty`) -- no new labelling was
  invented for it. A question that doesn't clear this bar is UNROUTED and is compared against,
  never silently folded into, the routed population.

  **Process-metric definitions + reachability (house rule, lessons doc §7.2) -- fixed here:**
  - `hops_to_answer` := the number of sub-questions actually issued for a decomposed item,
    bounded above by `_MAX_SUBQUESTIONS`. REACHABLE ONLY for an item that went through the
    decomposition arm at all (a real sub-question trajectory exists for it) -- an item scored
    only at baseline (never decomposed) has no trajectory and this metric is not reported for
    it, not defaulted to 0 or 1.
  - `decomposition_coverage` := (# of an item's REQUIRED sub-goals whose gold evidence is
    retrieved by >= 1 issued sub-question) / (# REQUIRED sub-goals), where "required" means the
    W-A4 item's own `supported` sub-parts ONLY -- an `absent` sub-part has no gold evidence to
    retrieve by construction, so including it in the denominator would silently deflate the
    metric (exactly the mistake this definition exists to rule out). Defined per W-A4 item
    (`docs/eval-reports/data/2026-08-28-wa4-gt/crossverify/wa4_adjudicated.json`, filtered to
    `adjudication_status in {accepted, accepted_with_correction}`, 31 usable of 33 -- 2
    `rejected` items excluded per the ticket) -- the one fixture whose ground truth actually names
    required sub-goals; `gt_wmr`/`ver84` carry no sub-part structure, so coverage is not computed
    against them, only the routed-vs-global recall comparison is (arm (b)-1, a later commit).

SERVING POSTURE P0 (asserted + logged at the start of every command that calls the LLM; ADR-09):
model `qwen3-14b-16k` via Ollama at `localhost:11434`, `num_ctx=16384`, `think:false`. A run that
cannot prove this posture is not a measurement -- see `log_posture()`.

GPU-LOCK DISCIPLINE (lessons doc §9.1, applies once a later commit adds real LLM calls): the lock
must be acquired only around each individual generation-LLM call (`gpu_lock.acquire("crag-eval")`
/ `.acquire("self-ask")`), exactly like `app/judge_llm.py`/`app/generation_capture.py` -- never
across a whole capture loop, so a short job queued behind this one is never starved.

STAYS OUT OF THE PRODUCT SURFACE: no MCP tool, no `app/assembly.py`/`app/serve.py` edit. Real
retrieval (once wired) reads a real `Retriever` built the same way `app/retrieval_eval.py`'s own
`main()` does (`app.assembly.build_mcp_server`, collection ALWAYS passed explicitly).

**Commit (1) scope (this commit): stub only.** Posture constants + `log_posture()`, the frozen
falsification criterion and routing rule as callable pure functions (`evaluator_action`,
`route_to_decompose`), the AUROC implementation the criterion will be checked against
(`auroc_pos_higher`, self-verified against brute force on every call), the W-A4 loader, and the
`plumbing` subcommand (loads both retrieval fixtures + W-A4, prints counts, touches no GPU/LLM/
network). The evaluator/decomposer LLM adapters and the real capture runs land in later commits
of this ticket, per its stated commit sequence.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Serving posture P0 (frozen; see module docstring) ---------------------------------------
GENERATION_LLM_URL = "http://localhost:11434"
MODEL = "qwen3-14b-16k:latest"
NUM_CTX = 16384
THINK = False


def log_posture() -> None:
    """Posture assertion: logged (and printed, so it lands even under default logging config) at
    the start of every command that will call the LLM -- see module docstring's SERVING POSTURE."""
    line = f"SERVING POSTURE P0: model={MODEL} num_ctx={NUM_CTX} think={THINK} url={GENERATION_LLM_URL}"
    logger.info(line)
    print(line)


# --- Fixtures ----------------------------------------------------------------------------------
FIXTURES: dict[str, Path] = {
    "gt_wmr": REPO_ROOT / "fixtures/eval/gt_wmr.json",
    "ver84": REPO_ROOT / "fixtures/eval/waymo_gt_verified.json",
}
_WA4_PATH = (
    REPO_ROOT
    / "docs/eval-reports/data/2026-08-28-wa4-gt/crossverify/wa4_adjudicated.json"
)
_COLLECTION_DEFAULT = "waymo_av_safety"
_RETRIEVAL_K = 10
# Passages a later commit will actually serve to the CRAG evaluator, dropped from the tail by
# rank -- same precedent as app/generation_capture.py's _GENERATION_K.
_SERVED_PASSAGES = 5
_MAX_SUBQUESTIONS = 3


# --- Arm (a): action mapping (illustrative, uncalibrated -- see module docstring) --------------
_PROCEED_THRESHOLD = 0.66
_ABSTAIN_THRESHOLD = 0.33


def evaluator_action(sufficiency: float) -> str:
    if sufficiency >= _PROCEED_THRESHOLD:
        return "proceed"
    if sufficiency < _ABSTAIN_THRESHOLD:
        return "abstain"
    return "decompose"


# --- Arm (b): routing rule (frozen -- see module docstring) -------------------------------------
_ROUTE_DIMENSIONS = frozenset({"multi-paper synthesis", "negation and scope"})


def route_to_decompose(dimension: str | None, difficulty: str | None) -> bool:
    return difficulty == "hard" or dimension in _ROUTE_DIMENSIONS


def load_raw_records(fixture_path: Path) -> dict[str, dict]:
    """question_id -> raw fixture record, for the `dimension`/`difficulty` fields `Question`
    itself doesn't carry (`app.retrieval_eval.Question` is deliberately narrower)."""
    data = json.loads(fixture_path.read_text())
    return {r["question_id"]: r for r in data["ground_truth"]}


# --- AUROC (rank-based, cross-checked against brute force on every call) -----------------------


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # 1-indexed
        for idx in range(i, j + 1):
            ranks[order[idx]] = avg_rank
        i = j + 1
    return ranks


def _brute_force_auroc(pos: list[float], neg: list[float]) -> float:
    total = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                total += 1.0
            elif p == n:
                total += 0.5
    return total / (len(pos) * len(neg))


def auroc_pos_higher(pos: list[float], neg: list[float]) -> float:
    """AUROC for "pos scores higher than neg" = P(pos > neg) + 0.5*P(pos == neg), Mann-Whitney
    rank formula, verified against brute-force pairwise counting on every call (NB-C2's own
    posture: a fixture-comparison number must never ship from an unverified formula) -- raises if
    the two disagree beyond floating-point tolerance."""
    if not pos or not neg:
        raise ValueError("auroc_pos_higher: both pos and neg must be non-empty")
    ranks = _average_ranks(pos + neg)
    n_pos, n_neg = len(pos), len(neg)
    rank_auroc = (sum(ranks[:n_pos]) - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    brute = _brute_force_auroc(pos, neg)
    if abs(rank_auroc - brute) > 1e-9:
        raise AssertionError(f"AUROC implementations disagree: rank={rank_auroc} brute={brute}")
    return rank_auroc


# --- W-A4 loading --------------------------------------------------------------------------------
_WA4_USABLE_STATUSES = frozenset({"accepted", "accepted_with_correction"})


@dataclass(frozen=True)
class Wa4SubPart:
    text: str
    status: str  # "supported" | "absent"
    gold_block_id: str | None  # None for an "absent" sub-part (no gold evidence exists)


@dataclass(frozen=True)
class Wa4Item:
    item_id: str
    question: str
    sub_parts: tuple[Wa4SubPart, ...]

    @property
    def required_sub_parts(self) -> tuple[Wa4SubPart, ...]:
        """"Required" == this item's own `supported` sub-parts -- the denominator
        `decomposition_coverage` must use (module docstring's process-metric definition)."""
        return tuple(sp for sp in self.sub_parts if sp.status == "supported")


def load_wa4_usable(path: Path = _WA4_PATH) -> list[Wa4Item]:
    """The 31 usable W-A4 items: 28 `accepted` + 3 `accepted_with_correction`, excluding the 2
    `rejected` -- filtered on `adjudication_status`, per the ticket."""
    data = json.loads(path.read_text())
    items = []
    for entry in data["items"]:
        if entry["adjudication_status"] not in _WA4_USABLE_STATUSES:
            continue
        raw_item = entry["item"]
        sub_parts = tuple(
            Wa4SubPart(
                text=sp["text"],
                status=sp["status"],
                gold_block_id=(sp.get("gold_ref") or {}).get("block_id"),
            )
            for sp in raw_item["sub_parts"]
        )
        items.append(
            Wa4Item(item_id=raw_item["id"], question=raw_item["question"], sub_parts=sub_parts)
        )
    return items


# --- CLI -----------------------------------------------------------------------------------------


def _out_dir_default() -> Path:
    return REPO_ROOT / "docs/eval-reports/data/2026-08-28-sb3"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plumbing")
    args = parser.parse_args(argv)

    if args.cmd == "plumbing":
        from app.retrieval_eval import load_questions

        for name, path in FIXTURES.items():
            qs = load_questions(path)
            n_absent = sum(1 for q in qs if not q.gold_paper_ids)
            print(f"{name}: {len(qs)} questions ({len(qs) - n_absent} answerable / {n_absent} absent)")
        wa4 = load_wa4_usable()
        n_required = sum(len(it.required_sub_parts) for it in wa4)
        print(f"wa4: {len(wa4)} usable items, {n_required} required sub-goals")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
