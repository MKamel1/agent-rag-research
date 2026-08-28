"""`python -m app.exp_nb_rr_qwen_reranker` -- QW-3 (precision-95 programme): A/B the reranker
seat. Baseline shipped BGE-reranker-v2-m3 (`TeiReranker`, `rag/reranker.py`) vs candidate
Qwen3-Reranker-0.6B, on BOTH retrieval ground-truth fixtures (`gt_wmr`, `waymo_gt_verified` /
"ver84"), via the existing dual-fixture reuse seam (`scripts/nb_eval_runner.py`) -- no evaluation
logic rewritten here (module docstrings of that script and `app/retrieval_eval.py` remain the
source of truth for how a number gets computed; this file only ever calls them).

Two responsibilities packed into one file, dispatched by argv SHAPE (see `main()`):

1. ORCHESTRATOR (`python -m app.exp_nb_rr_qwen_reranker --arm {bge,qwen,both} ...`): drives
   `scripts/nb_eval_runner.py` once per arm, unmodified, via subprocess -- exactly the reuse seam
   the ticket names. The BGE arm is a byte-identical `nb_eval_runner.py` invocation (its default
   `--runner-module app.retrieval_eval`); the Qwen arm points `--runner-module` at THIS module
   instead, a feature `nb_eval_runner.py` already exposes ("overridable only for tests" per its
   own docstring -- reused here for a real measurement rather than a test double).

2. SHIM (`python -m app.exp_nb_rr_qwen_reranker --ground-truth ... --config ... --k ...`, i.e.
   `nb_eval_runner.py`'s own per-fixture argv, verbatim): monkeypatches `app.assembly.TeiReranker`
   to `Qwen3Reranker` (this module) BEFORE calling `app.retrieval_eval.main()` unmodified -- so the
   evaluation logic that actually runs is `app.retrieval_eval`'s, with only the reranker adapter
   swapped. Neither `app/assembly.py` nor `app/retrieval_eval.py` is edited on disk; the patch
   rebinds the module-GLOBAL name `TeiReranker`, which `build_mcp_server` resolves at CALL time
   (Python's late binding of a function body's free variables against its module's globals) --
   see `apply_qwen_patch()`.

Mode is picked by argv SHAPE, not an env var: `"--ground-truth"` is `app.retrieval_eval`'s own
flag and never appears in this module's own orchestrator CLI, so its presence is an unambiguous
discriminator. Deliberate: reading the process environment outside `rag/config.py` is a
CI-enforced violation in `app/` scope (CONVENTIONS.md §3, `ci/checks/env_leak.py` check (d)) -- an
environment-variable handoff between the orchestrator and the shim subprocess was the obvious
alternative and is exactly what that check exists to catch.

HOSTING DECISION (ticket-mandated, recorded here): Qwen3-Reranker-0.6B is a `Qwen3ForCausalLM`
(scores a (query, document) pair by the softmax-normalized logit of a "yes" vs "no" token after a
chat-formatted judge prompt -- see the model's card / config.json's `true_token_id`/
`false_token_id`) -- a structurally different serving shape than the classification-head
cross-encoder (BGE-reranker-v2-m3) the shared `rag-tei-reranker` TEI container already runs.
Retrofitting TEI for it would mean either a second TEI container (a new deployment artifact + port
-- reconfiguring shared infra other lanes depend on, exactly what the ticket says not to do) or
fighting TEI's `/rerank` route for a scoring scheme it wasn't built to serve. At 0.6B params it
fits beside the resident TEI pair on the shared card with room to spare (~13.4GB free; this model
needs on the order of 1-2GB in bfloat16), so it runs LOCALLY IN-PROCESS via `transformers` (already
installed in the `agent-rag-research` env) and never touches the `rag-tei-reranker` container --
the ticket's own suggested route for a model this small.

GPU-lock note: `Qwen3Reranker` plugs into the SAME `gpu_lock` object `build_mcp_server` already
threads through every real adapter (`FileGpuLock` at `Config.gpu_lock_path`) -- it wraps its
forward pass in `gpu_lock.acquire("rerank", timeout=...)`, identically to `TeiReranker`/
`TeiEmbedder`. That already serializes this candidate's GPU work against every other lane touching
the same lock file, with no new lock invented. A coarser *outer* lock held across an entire arm
(the shape `app/benchmark.py:acquire_gpu_lock_or_fail` uses) was considered and rejected: each
`nb_eval_runner.py` fixture run is itself a NESTED subprocess that acquires this identical lock
file for every embed/rerank call, so an orchestrator-level lock wrapping that whole subprocess tree
would self-deadlock (this process holds the lock; its own grandchild then blocks waiting on it
forever). The existing fine-grained per-call lock is the correct, non-self-deadlocking
serialization point here, and it is the one this module reuses.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from contracts.gpu_lock import GpuLock
from contracts.retriever import RerankCandidate
from scripts.nb_eval_runner import DEFAULT_COLLECTION, DEFAULT_CONFIG

REPO_ROOT = Path(__file__).resolve().parent.parent

_MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"
_TASK_INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"
# Generous vs. the corpus's ~400-566 estimated-token median chunk (rag/reranker.py's own
# _MAX_BATCH_TOKENS measurement) -- truncation only bites the long tail. Kept well under the
# model card recipe's own 8192: at this model's 151,669-token vocab, naively materializing
# per-position logits for a whole sub-batch (the model card's own `model(**inputs).logits`) scales
# as batch*seq_len*vocab -- measured OOM at batch=32/seq_len~2048 (an 18.5GB single allocation on a
# 24GB card already sharing ~11GB with the resident TEI pair). `_score_batch` below never computes
# those per-position logits at all (see its docstring), so this constant only bounds attention
# cost now, not a vocab-sized tensor -- still kept modest to stay a good citizen on a shared card.
_MAX_LENGTH = 1024
# Candidates scored per forward pass. rag/reranker.py's rerank_pool_size (config.rerank_depth) is
# 32 -- scoring all 32 in one batch is what produced the OOM above; sub-batching bounds peak
# attention memory (O(batch * seq_len^2)) to a small, safe slice instead of the whole pool at once.
_SUB_BATCH_SIZE = 8
# Verbatim from the model card's "Using Transformers" recipe (Qwen/Qwen3-Reranker-0.6B) -- the
# documented, non-negotiable prompt shape this model was trained to score against.
_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query "
    "and the Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n"
    "<|im_start|>user\n"
)
_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

_SUBPROCESS_TIMEOUT_S = 3600


class Qwen3Reranker:
    """Candidate `Reranker` adapter (QW-3): Qwen3-Reranker-0.6B run locally in-process via
    `transformers` (see module docstring's HOSTING DECISION) instead of TEI. Same public
    interface as `rag.reranker.TeiReranker` (`rerank(query, candidates) -> list[RerankCandidate]`,
    reordered by score descending, the same objects returned -- never fabricates new ones) and a
    constructor shape compatible with `app.assembly.build_mcp_server`'s existing call site (see
    the `_client` note below), so `apply_qwen_patch()` can rebind the class name it constructs
    with no other change needed.

    Loads the model lazily, on first `rerank()` call, not in `__init__` -- keeps construction
    cheap and GPU-free, matching `TeiReranker`'s own "the real work happens in rerank(), not
    __init__" shape. `gpu_lock.acquire("rerank")` wraps only the forward pass (module docstring's
    GPU-lock note); enforcement check (f) (`ci/checks/gpu_lock.py`) also requires any class named
    `*Reranker` to declare a `gpu_lock`-named `__init__` parameter.

    Note: `_client` above stands in for the transport object `build_mcp_server` passes as the
    first positional argument to whatever class name it constructs -- accepted-and-ignored so
    that composition root's call site needs no edit once `apply_qwen_patch()` rebinds the name.
    """

    def __init__(
        self,
        _client,
        gpu_lock: GpuLock,
        *,
        ensure_ready=None,
        gpu_lock_timeout: float | None = 300.0,
        **_ignored_tei_reranker_kwargs,
    ):
        self._gpu_lock = gpu_lock
        self._gpu_lock_timeout = gpu_lock_timeout
        self._ensure_ready = ensure_ready
        self._model = None
        self._tokenizer = None
        self._prefix_tokens: list[int] = []
        self._suffix_tokens: list[int] = []
        self._token_true_id = None
        self._token_false_id = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        tokenizer = AutoTokenizer.from_pretrained(_MODEL_ID, padding_side="left")
        # DTYPE TRAP -- real, but NARROWER than first suspected (see report's Finding section
        # for the full trail). This model is calibrated in bfloat16 (config.json's torch_dtype);
        # under float16, a short/simple isolated pair ("Paris is the capital of France" vs.
        # "bananas are a fruit") scores the irrelevant document higher, both logits collapsed near
        # the 0.5 coin-flip line -- reproducible, with no error/warning/crash. That result does
        # NOT generalize to this corpus's actual (longer, more distinguishing) chunk text: an
        # identical fp16-vs-bfloat16 A/B on the real --limit 5 subset moved block-P@1 by exactly
        # 0/5 -> 0/5 on both fixtures (MRR moved <0.002). bfloat16 is kept because it is the
        # model's documented native precision and the only dtype that reproduces the model card's
        # own worked example -- but it is NOT the explanation for this corpus's measured ranking
        # behavior. Direct per-candidate score inspection (real queries, real corpus pool, this
        # exact code path) found well-distributed, correctly-descending-sorted, non-degenerate
        # scores under bfloat16 -- the low block-P@1 traces to this reranker genuinely preferring
        # a paper's abstract chunk (which restates the headline finding) over the specific body
        # paragraph the fixture's gold_block_id points at, not to a coding defect. See the report.
        model = AutoModelForCausalLM.from_pretrained(_MODEL_ID, dtype=torch.bfloat16)
        model = model.to("cuda").eval()
        self._tokenizer = tokenizer
        self._model = model
        self._token_false_id = tokenizer.convert_tokens_to_ids("no")
        self._token_true_id = tokenizer.convert_tokens_to_ids("yes")
        self._prefix_tokens = tokenizer.encode(_PREFIX, add_special_tokens=False)
        self._suffix_tokens = tokenizer.encode(_SUFFIX, add_special_tokens=False)

    def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankCandidate]:
        if not candidates:
            return []
        if self._ensure_ready is not None:
            self._ensure_ready()
        self._ensure_loaded()

        pairs = [
            f"<Instruct>: {_TASK_INSTRUCTION}\n<Query>: {query}\n<Document>: {c.text}"
            for c in candidates
        ]
        with self._gpu_lock.acquire("rerank", timeout=self._gpu_lock_timeout):
            scores = self._compute_scores(pairs)

        order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
        return [candidates[i] for i in order]

    def _compute_scores(self, pairs: list[str]) -> list[float]:
        """Sub-batches `pairs` (see `_SUB_BATCH_SIZE`'s docstring comment) and scores each slice
        with `_score_batch`, concatenating results back into the caller's original order."""
        scores: list[float] = []
        for start in range(0, len(pairs), _SUB_BATCH_SIZE):
            scores.extend(self._score_batch(pairs[start : start + _SUB_BATCH_SIZE]))
        return scores

    @torch.no_grad()
    def _score_batch(self, pairs: list[str]) -> list[float]:
        """One forward pass, memory-bounded: score = P(token="yes") after a binary yes/no
        log-softmax -- same math as the model card's `compute_logits` recipe, but computed from
        the LAST hidden state projected through only the two rows of the LM head this needs
        (`true`/`false`), never the model card's own `model(**inputs).logits` (every position's
        full 151,669-vocab distribution) -- that shape is what produced the measured OOM this
        module's constants comment documents; scoring 2 vocab rows instead of 151,669 sidesteps it
        entirely rather than just shrinking the batch further.
        """
        tokenizer = self._tokenizer
        budget = _MAX_LENGTH - len(self._prefix_tokens) - len(self._suffix_tokens)
        inputs = tokenizer(
            pairs, padding=False, truncation="longest_first",
            return_attention_mask=True, max_length=budget,
        )
        for i, ids in enumerate(inputs["input_ids"]):
            inputs["input_ids"][i] = self._prefix_tokens + ids + self._suffix_tokens
        inputs = tokenizer.pad(inputs, padding=True, return_tensors="pt", max_length=_MAX_LENGTH)
        inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        # `padding_side="left"` (set at load time) means every sequence's real last token sits at
        # position -1 regardless of that row's own length -- same assumption the model card's own
        # `logits[:, -1, :]` relies on.
        backbone = self._model.model
        last_hidden = backbone(**inputs).last_hidden_state[:, -1, :]  # (batch, hidden)
        lm_head_weight = self._model.lm_head.weight  # (vocab, hidden), no bias (tied embeddings)
        true_logits = last_hidden @ lm_head_weight[self._token_true_id]
        false_logits = last_hidden @ lm_head_weight[self._token_false_id]
        stacked = torch.stack([false_logits, true_logits], dim=1)
        log_probs = torch.nn.functional.log_softmax(stacked, dim=1)
        return log_probs[:, 1].exp().tolist()


def apply_qwen_patch() -> None:
    """Rebinds `app.assembly.TeiReranker` (the module-global name `build_mcp_server` resolves at
    CALL time, not at its own def time) to `Qwen3Reranker` -- `app/assembly.py` is never edited on
    disk; the very next `build_mcp_server(...)` call in THIS process constructs the candidate
    reranker instead of the shipped one."""
    import app.assembly as assembly

    assembly.TeiReranker = Qwen3Reranker


def _looks_like_retrieval_eval_argv(argv: list[str]) -> bool:
    """`--ground-truth` is `app.retrieval_eval._parse_args`'s own flag and never appears in this
    module's own orchestrator CLI below -- argv shape is the dispatch key (module docstring: no
    env var allowed in `app/` scope)."""
    return "--ground-truth" in argv


def _arm_tag(arm: str) -> str:
    # No '.' in either tag: nb_eval_runner.py's output_paths() builds each output name via
    # Path.with_suffix(".json"/".md"), which replaces from the LAST '.' in the stem -- a tag like
    # "qwen3-0.6b" would get silently truncated to "...-qwen3-0" + ".json". Not our file to fix
    # (scripts/nb_eval_runner.py isn't in QW-3's owned-files list); picking a dot-free tag sidesteps
    # it instead.
    return {"bge": "bge-baseline", "qwen": "qwen3-0pt6b"}[arm]


def run_arm(arm: str, args: argparse.Namespace) -> int:
    """One arm, both fixtures, via the unmodified `scripts/nb_eval_runner.py` reuse seam."""
    cmd = [
        args.python_exe, str(REPO_ROOT / "scripts" / "nb_eval_runner.py"),
        "--config", args.config,
        "--collection", args.collection,
        "--k", str(args.k),
        "--sparse-mode", "fused",
        "--out-dir", str(args.out_dir),
        "--date", args.date,
        "--tag", _arm_tag(arm),
    ]
    if arm == "qwen":
        cmd += ["--runner-module", "app.exp_nb_rr_qwen_reranker"]
    if args.limit is not None:
        cmd += ["--limit", str(args.limit)]

    print(f"[qw3] {arm}: {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, timeout=_SUBPROCESS_TIMEOUT_S)  # noqa: S603
    if proc.returncode != 0:
        raise SystemExit(f"QW-3: arm {arm!r} exited {proc.returncode}")
    return proc.returncode


def _parse_orchestrator_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("bge", "qwen", "both"), default="both")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--out-dir", default="docs/eval-reports/data/2026-08-28-qw3")
    parser.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    parser.add_argument("--limit", type=int, default=None, help="smoke-test: first N questions")
    parser.add_argument("--python-exe", default=sys.executable)
    return parser.parse_args(argv)


def _orchestrate(argv: list[str]) -> int:
    args = _parse_orchestrator_args(argv)
    arms = ("bge", "qwen") if args.arm == "both" else (args.arm,)
    for arm in arms:
        run_arm(arm, args)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if _looks_like_retrieval_eval_argv(argv):
        apply_qwen_patch()
        from app.retrieval_eval import main as retrieval_eval_main

        retrieval_eval_main()
        return 0
    return _orchestrate(argv)


if __name__ == "__main__":
    sys.exit(main())
