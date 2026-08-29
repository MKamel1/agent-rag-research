"""Unit tests for `app/exp_agentic_loop_v0.py` (SB-3). Zero-GPU, zero-network (TEST-STRATEGY.md
golden rule): commit (1) covers only pure functions -- the frozen routing rule, the frozen
(illustrative) action mapping, the AUROC implementation, and the W-A4 loader against a small
in-memory fixture. LLM-adapter tests land in the commits that add those adapters.
"""

import json
from pathlib import Path

import pytest

from app.exp_agentic_loop_v0 import (
    CragEvaluator,
    EvaluatorScore,
    SelfAskDecomposer,
    Wa4Item,
    Wa4SubPart,
    _RawResponse,
    analyze_crag,
    analyze_route,
    analyze_wa4,
    auroc_pos_higher,
    evaluator_action,
    load_raw_records,
    load_wa4_usable,
    merge_hits,
    route_to_decompose,
    run_crag_capture,
    run_route_capture,
    run_wa4_capture,
)
from contracts.errors import PermanentError
from contracts.provenance import Anchor
from contracts.retriever import Citation, GroundedResult
from rag.fakes.fake_gpu_lock import FakeGpuLock


# ---------------------------------------------------------------------------
# evaluator_action: frozen, illustrative tertile split
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sufficiency,expected",
    [(1.0, "proceed"), (0.66, "proceed"), (0.65, "decompose"), (0.33, "decompose"), (0.32, "abstain"), (0.0, "abstain")],
)
def test_evaluator_action_thresholds(sufficiency, expected):
    assert evaluator_action(sufficiency) == expected


# ---------------------------------------------------------------------------
# route_to_decompose: frozen routing rule
# ---------------------------------------------------------------------------


def test_route_to_decompose_hard_difficulty_routes_regardless_of_dimension():
    assert route_to_decompose("single-passage factual lookup", "hard") is True


def test_route_to_decompose_multi_paper_synthesis_routes_even_if_easy():
    assert route_to_decompose("multi-paper synthesis", "easy") is True


def test_route_to_decompose_negation_and_scope_routes():
    assert route_to_decompose("negation and scope", "medium") is True


def test_route_to_decompose_plain_medium_lookup_does_not_route():
    assert route_to_decompose("single-passage factual lookup", "medium") is False


# ---------------------------------------------------------------------------
# load_raw_records: question_id -> raw record join
# ---------------------------------------------------------------------------


def test_load_raw_records_joins_by_question_id(tmp_path: Path):
    gt = {
        "ground_truth": [
            {"question_id": "Q-1", "dimension": "numeric/quantitative", "difficulty": "easy"},
            {"question_id": "Q-2", "dimension": "negation and scope", "difficulty": "hard"},
        ]
    }
    path = tmp_path / "gt.json"
    path.write_text(json.dumps(gt))

    records = load_raw_records(path)

    assert records["Q-1"]["difficulty"] == "easy"
    assert records["Q-2"]["dimension"] == "negation and scope"


# ---------------------------------------------------------------------------
# auroc_pos_higher: known closed-form cases, self-verified against brute force internally
# ---------------------------------------------------------------------------


def test_auroc_perfect_separation_is_one():
    assert auroc_pos_higher(pos=[0.9, 0.8, 0.7], neg=[0.1, 0.2, 0.3]) == 1.0


def test_auroc_perfect_inversion_is_zero():
    assert auroc_pos_higher(pos=[0.1, 0.2], neg=[0.8, 0.9]) == 0.0


def test_auroc_all_tied_is_one_half():
    assert auroc_pos_higher(pos=[0.5, 0.5], neg=[0.5, 0.5]) == 0.5


def test_auroc_empty_arm_raises():
    with pytest.raises(ValueError):
        auroc_pos_higher(pos=[], neg=[0.1])


# ---------------------------------------------------------------------------
# load_wa4_usable: filters to accepted/accepted_with_correction, derives required sub-parts
# ---------------------------------------------------------------------------


def _wa4_entry(item_id: str, status: str, sub_parts: list[dict]) -> dict:
    return {
        "id": item_id,
        "adjudication_status": status,
        "item": {"id": item_id, "question": f"question for {item_id}", "sub_parts": sub_parts},
    }


def test_load_wa4_usable_excludes_rejected(tmp_path: Path):
    data = {
        "items": [
            _wa4_entry("Q-A", "accepted", [{"text": "s1", "status": "supported", "gold_ref": {"block_id": "p:b1"}}]),
            _wa4_entry("Q-B", "accepted_with_correction", [{"text": "s1", "status": "absent"}]),
            _wa4_entry("Q-C", "rejected", [{"text": "s1", "status": "supported", "gold_ref": {"block_id": "p:b9"}}]),
        ]
    }
    path = tmp_path / "wa4.json"
    path.write_text(json.dumps(data))

    items = load_wa4_usable(path)

    assert {it.item_id for it in items} == {"Q-A", "Q-B"}


def test_load_wa4_usable_required_sub_parts_is_supported_only(tmp_path: Path):
    data = {
        "items": [
            _wa4_entry(
                "Q-A", "accepted",
                [
                    {"text": "s1", "status": "supported", "gold_ref": {"block_id": "p:b1"}},
                    {"text": "s2", "status": "absent"},
                ],
            ),
        ]
    }
    path = tmp_path / "wa4.json"
    path.write_text(json.dumps(data))

    items = load_wa4_usable(path)

    assert len(items[0].sub_parts) == 2
    assert len(items[0].required_sub_parts) == 1
    assert items[0].required_sub_parts[0].gold_block_id == "p:b1"


def test_load_wa4_usable_absent_sub_part_has_no_gold_block_id(tmp_path: Path):
    data = {"items": [_wa4_entry("Q-A", "accepted", [{"text": "s1", "status": "absent"}])]}
    path = tmp_path / "wa4.json"
    path.write_text(json.dumps(data))

    items = load_wa4_usable(path)

    assert items[0].sub_parts[0].gold_block_id is None


# ---------------------------------------------------------------------------
# CragEvaluator: fake `post` injection (no urllib, no network, no real model, no GPU) --
# `post` has the same signature as `_post_generate` and returns a `_RawResponse`.
# ---------------------------------------------------------------------------


def _ok_post(payload: dict):
    def post(url, model, prompt, num_predict, item_id):
        return _RawResponse(json.dumps({"response": json.dumps(payload)}).encode())

    return post


def test_crag_evaluator_parses_sufficiency_and_verdict():
    evaluator = CragEvaluator(FakeGpuLock(), "m", post=_ok_post({"sufficiency": 0.87, "verdict": "sufficient"}))
    score = evaluator("Q-1", "what color is the sky?", ("the sky is blue",))
    assert score == EvaluatorScore(sufficiency=0.87, verdict="sufficient")


def test_crag_evaluator_strips_markdown_code_fence():
    def post(url, model, prompt, num_predict, item_id):
        body = '```json\n{"sufficiency": 0.2, "verdict": "insufficient"}\n```'
        return _RawResponse(json.dumps({"response": body}).encode())

    evaluator = CragEvaluator(FakeGpuLock(), "m", post=post)
    score = evaluator("Q-1", "q?", ("p",))
    assert score.sufficiency == 0.2


def test_crag_evaluator_acquires_gpu_lock_around_the_call():
    lock = FakeGpuLock()
    evaluator = CragEvaluator(lock, "m", post=_ok_post({"sufficiency": 0.5, "verdict": "partial"}))
    evaluator("Q-1", "q?", ("p",))
    assert lock.acquired == ["crag-eval"]


def test_crag_evaluator_rejects_malformed_json():
    evaluator = CragEvaluator(FakeGpuLock(), "m", post=_ok_post({"sufficiency": "not-a-number", "verdict": "sufficient"}))
    with pytest.raises(PermanentError):
        evaluator("Q-1", "q?", ("p",))


def test_crag_evaluator_rejects_out_of_range_sufficiency():
    evaluator = CragEvaluator(FakeGpuLock(), "m", post=_ok_post({"sufficiency": 1.5, "verdict": "sufficient"}))
    with pytest.raises(PermanentError):
        evaluator("Q-1", "q?", ("p",))


def test_crag_evaluator_rejects_unknown_verdict():
    evaluator = CragEvaluator(FakeGpuLock(), "m", post=_ok_post({"sufficiency": 0.5, "verdict": "maybe"}))
    with pytest.raises(PermanentError):
        evaluator("Q-1", "q?", ("p",))


def test_crag_evaluator_drops_passages_from_the_tail_to_fit_num_ctx():
    """A pathologically long passage set must not silently truncate mid-passage -- whole
    passages are dropped from the tail (rank order) until the prompt fits NUM_CTX=16384."""
    # ~8000 words (~40,000 chars, ~11,400 est. tokens): ONE fits under the ~16,234-token usable
    # window (NUM_CTX - num_predict), but TWO together (~22,800 tokens) do not.
    huge_passage = "word " * 8000
    calls: list[str] = []

    def post(url, model, prompt, num_predict, item_id):
        calls.append(prompt)
        return _RawResponse(json.dumps({"response": '{"sufficiency": 0.5, "verdict": "partial"}'}).encode())

    evaluator = CragEvaluator(FakeGpuLock(), "m", post=post)
    evaluator("Q-1", "q?", (huge_passage, huge_passage, "short passage"))
    # Only ONE passage's worth (or fewer) survives the fit -- never all three at full length.
    assert len(calls) == 1
    assert calls[0].count("word ") < huge_passage.count("word ") * 2


# ---------------------------------------------------------------------------
# run_crag_capture / analyze_crag: fake retriever + fake evaluator, jsonl resumability
# ---------------------------------------------------------------------------


def _hit(paper_id: str, score: float, block_id: str = "b1") -> GroundedResult:
    return GroundedResult(
        passage_text="passage text",
        anchor=Anchor(paper_id=paper_id, block_id=block_id, page=0, bbox=(0.0, 0.0, 1.0, 1.0), snippet="s", section_path="1"),
        paper_id=paper_id,
        score=score,
        citation=Citation(paper_id=paper_id, title="T", authors=["A"], arxiv_url="https://x", section_path="1"),
    )


class _FakeRetriever:
    def __init__(self, hits_by_query: dict[str, list[GroundedResult]]):
        self._hits = hits_by_query

    def retrieve(self, query: str, filters, k: int):
        return self._hits.get(query, [])[:k], None


def _fake_evaluator(scores_by_id: dict[str, EvaluatorScore]):
    def evaluator(question_id: str, question_text: str, passages: tuple[str, ...]) -> EvaluatorScore:
        return scores_by_id[question_id]

    return evaluator


def test_run_crag_capture_writes_one_record_per_question_and_is_resumable(tmp_path: Path):
    gt = {
        "ground_truth": [
            {"question_id": "Q-1", "question_text": "answerable one?", "source_paper_id": "p1"},
            {"question_id": "Q-2", "question_text": "absent one?"},
        ]
    }
    fixture_path = tmp_path / "gt.json"
    fixture_path.write_text(json.dumps(gt))
    out_path = tmp_path / "crag.jsonl"

    retriever = _FakeRetriever({"answerable one?": [_hit("p1", 1.0)], "absent one?": []})
    evaluator = _fake_evaluator(
        {"Q-1": EvaluatorScore(0.9, "sufficient"), "Q-2": EvaluatorScore(0.1, "insufficient")}
    )
    run_crag_capture("gt_wmr", fixture_path, out_path, retriever, evaluator)

    records = [json.loads(line) for line in out_path.read_text().splitlines()]
    assert {r["question_id"]: r["label"] for r in records} == {"Q-1": "answerable", "Q-2": "absent"}
    assert {r["question_id"]: r["action"] for r in records} == {"Q-1": "proceed", "Q-2": "abstain"}

    # Re-run: no new evaluator calls needed for already-captured ids (a poisoned evaluator would
    # raise if invoked again -- this proves the resume-skip actually skips, not just re-agrees).
    def poison(question_id, question_text, passages):
        raise AssertionError("should not be called -- question already captured")

    run_crag_capture("gt_wmr", fixture_path, out_path, retriever, poison)
    records_after = [json.loads(line) for line in out_path.read_text().splitlines()]
    assert len(records_after) == 2


def test_run_crag_capture_records_error_without_aborting_the_rest(tmp_path: Path):
    gt = {
        "ground_truth": [
            {"question_id": "Q-1", "question_text": "will fail", "source_paper_id": "p1"},
            {"question_id": "Q-2", "question_text": "will succeed", "source_paper_id": "p1"},
        ]
    }
    fixture_path = tmp_path / "gt.json"
    fixture_path.write_text(json.dumps(gt))
    out_path = tmp_path / "crag.jsonl"

    retriever = _FakeRetriever({"will fail": [_hit("p1", 1.0)], "will succeed": [_hit("p1", 1.0)]})

    def flaky_evaluator(question_id, question_text, passages):
        if question_id == "Q-1":
            raise PermanentError("boom")
        return EvaluatorScore(0.8, "sufficient")

    run_crag_capture("gt_wmr", fixture_path, out_path, retriever, flaky_evaluator)
    records = {json.loads(line)["question_id"]: json.loads(line) for line in out_path.read_text().splitlines()}
    assert records["Q-1"]["error"] is not None
    assert records["Q-2"]["error"] is None


def test_analyze_crag_is_void_when_any_error_present():
    records = [
        {"question_id": "Q-1", "label": "answerable", "sufficiency": 0.9, "action": "proceed", "error": None},
        {"question_id": "Q-2", "label": "absent", "error": "boom"},
    ]
    summary = analyze_crag(records)
    assert summary["void"] is True
    assert summary["n_errors"] == 1


def test_analyze_crag_computes_auroc_and_verdict_when_clean():
    records = [
        {"question_id": "Q-1", "label": "answerable", "sufficiency": 0.9, "action": "proceed", "error": None},
        {"question_id": "Q-2", "label": "answerable", "sufficiency": 0.8, "action": "proceed", "error": None},
        {"question_id": "Q-3", "label": "absent", "sufficiency": 0.1, "action": "abstain", "error": None},
        {"question_id": "Q-4", "label": "absent", "sufficiency": 0.2, "action": "abstain", "error": None},
    ]
    summary = analyze_crag(records)
    assert summary["void"] is False
    assert summary["auroc_answerable_over_absent"] == 1.0
    assert summary["verdict"] == "ADOPT"


def test_load_wa4_usable_real_fixture_is_31_items_with_31_required_subgoals():
    """Cross-checks against the real committed W-A4 file, not just a synthetic one -- the counts
    the ticket itself names (31 usable of 33)."""
    real_path = Path(__file__).resolve().parent.parent / (
        "docs/eval-reports/data/2026-08-28-wa4-gt/crossverify/wa4_adjudicated.json"
    )
    items = load_wa4_usable(real_path)
    assert len(items) == 31
    assert sum(len(it.required_sub_parts) for it in items) == 31


# ---------------------------------------------------------------------------
# merge_hits: union of sub-question hit lists, deduped by block id, max score wins
# ---------------------------------------------------------------------------


def test_merge_hits_dedupes_by_block_id_keeping_max_score():
    a = _hit("p1", 0.5, block_id="b1")
    b = _hit("p1", 0.9, block_id="b1")  # same block, higher score from a different sub-question
    c = _hit("p2", 0.7, block_id="b2")

    merged = merge_hits([[a, c], [b]], k=10)

    by_block = {h.anchor.block_id: h.score for h in merged}
    assert by_block == {"b1": 0.9, "b2": 0.7}


def test_merge_hits_sorts_descending_and_truncates_to_k():
    hits = [_hit("p1", 0.1, "b1"), _hit("p1", 0.9, "b2"), _hit("p1", 0.5, "b3")]

    merged = merge_hits([hits], k=2)

    assert [h.anchor.block_id for h in merged] == ["b2", "b3"]


# ---------------------------------------------------------------------------
# SelfAskDecomposer: fake `post` injection, no network, no GPU
# ---------------------------------------------------------------------------


def _ok_decompose_post(subquestions: list[str]):
    def post(url, model, prompt, num_predict, item_id):
        return _RawResponse(json.dumps({"response": json.dumps(subquestions)}).encode())

    return post


def test_self_ask_decomposer_parses_subquestions():
    decomposer = SelfAskDecomposer(FakeGpuLock(), "m", post=_ok_decompose_post(["a?", "b?"]))
    subqs = decomposer("Q-1", "what is a and b?")
    assert subqs == ("a?", "b?")


def test_self_ask_decomposer_truncates_to_max_n():
    decomposer = SelfAskDecomposer(FakeGpuLock(), "m", max_n=2, post=_ok_decompose_post(["a?", "b?", "c?", "d?"]))
    subqs = decomposer("Q-1", "q?")
    assert subqs == ("a?", "b?")


def test_self_ask_decomposer_acquires_gpu_lock():
    lock = FakeGpuLock()
    decomposer = SelfAskDecomposer(lock, "m", post=_ok_decompose_post(["a?"]))
    decomposer("Q-1", "q?")
    assert lock.acquired == ["self-ask"]


def test_self_ask_decomposer_rejects_malformed_json():
    def post(url, model, prompt, num_predict, item_id):
        return _RawResponse(json.dumps({"response": "not json"}).encode())

    decomposer = SelfAskDecomposer(FakeGpuLock(), "m", post=post)
    with pytest.raises(PermanentError):
        decomposer("Q-1", "q?")


def test_self_ask_decomposer_rejects_empty_list():
    decomposer = SelfAskDecomposer(FakeGpuLock(), "m", post=_ok_decompose_post([]))
    with pytest.raises(PermanentError):
        decomposer("Q-1", "q?")


# ---------------------------------------------------------------------------
# run_route_capture / analyze_route: fake retriever + fake decomposer
# ---------------------------------------------------------------------------


def _fake_decomposer(subqs_by_id: dict[str, tuple[str, ...]]):
    def decomposer(question_id: str, question_text: str) -> tuple[str, ...]:
        return subqs_by_id[question_id]

    return decomposer


def test_run_route_capture_scopes_to_answerable_and_tags_routed(tmp_path: Path):
    gt = {
        "ground_truth": [
            {
                "question_id": "Q-1", "question_text": "routed question?", "source_paper_id": "p1",
                "gold_block_id": "b1", "dimension": "negation and scope", "difficulty": "medium",
            },
            {
                "question_id": "Q-2", "question_text": "plain question?", "source_paper_id": "p1",
                "gold_block_id": "b1", "dimension": "single-passage factual lookup", "difficulty": "medium",
            },
            {"question_id": "Q-3", "question_text": "absent question?"},  # excluded: not answerable
        ]
    }
    fixture_path = tmp_path / "gt.json"
    fixture_path.write_text(json.dumps(gt))
    out_path = tmp_path / "route.jsonl"

    retriever = _FakeRetriever(
        {
            "routed question?": [_hit("p1", 1.0, "b1")],
            "plain question?": [_hit("p1", 1.0, "b1")],
            "sub-a": [_hit("p1", 0.9, "b1")],
        }
    )
    decomposer = _fake_decomposer({"Q-1": ("sub-a",), "Q-2": ("sub-a",)})

    run_route_capture("gt_wmr", fixture_path, out_path, retriever, decomposer)

    records = {json.loads(line)["question_id"]: json.loads(line) for line in out_path.read_text().splitlines()}
    assert set(records) == {"Q-1", "Q-2"}  # Q-3 (absent) never captured by arm (b)-1
    assert records["Q-1"]["routed"] is True
    assert records["Q-2"]["routed"] is False
    assert records["Q-1"]["baseline_passage_rank"] == 1
    assert records["Q-1"]["hops_to_answer"] == 1


def test_analyze_route_reports_three_policies():
    records = [
        {
            "question_id": "Q-1", "routed": True, "passage_scored": True, "error": None,
            "baseline_passage_rank": None, "decomposed_passage_rank": 1, "hops_to_answer": 2,
        },
        {
            "question_id": "Q-2", "routed": False, "passage_scored": True, "error": None,
            "baseline_passage_rank": 1, "decomposed_passage_rank": None, "hops_to_answer": 1,
        },
    ]
    summary = analyze_route(records)
    assert summary["void"] is False
    # routed policy: Q-1 uses decomposed (hit), Q-2 uses baseline (hit) -> 2/2
    assert summary["policy_routed"]["recall_at_k"] == 1.0
    # never-decompose policy: Q-1 baseline is None (miss), Q-2 baseline hit -> 1/2
    assert summary["policy_never_decompose"]["recall_at_k"] == 0.5
    # global-decompose policy: Q-1 decomposed hit, Q-2 decomposed None (miss) -> 1/2
    assert summary["policy_global_decompose"]["recall_at_k"] == 0.5


def test_analyze_route_is_void_when_any_error_present():
    records = [{"question_id": "Q-1", "routed": True, "passage_scored": True, "error": "boom"}]
    summary = analyze_route(records)
    assert summary["void"] is True


# ---------------------------------------------------------------------------
# run_wa4_capture / analyze_wa4: fake retriever + fake decomposer, required-subgoal coverage
# ---------------------------------------------------------------------------


def test_run_wa4_capture_counts_required_subgoal_hits(tmp_path: Path, monkeypatch):
    item = Wa4Item(
        item_id="Q-WA4-1", question="top-level question?",
        sub_parts=(
            Wa4SubPart(text="s1", status="supported", gold_block_id="b1"),
            Wa4SubPart(text="s2", status="absent", gold_block_id=None),
        ),
    )
    monkeypatch.setattr("app.exp_agentic_loop_v0.load_wa4_usable", lambda: [item])

    out_path = tmp_path / "wa4.jsonl"
    retriever = _FakeRetriever(
        {"top-level question?": [_hit("p1", 1.0, "b2")], "sub-a": [_hit("p1", 0.9, "b1")]}
    )
    decomposer = _fake_decomposer({"Q-WA4-1": ("sub-a",)})

    run_wa4_capture(out_path, retriever, decomposer)

    record = json.loads(out_path.read_text())
    assert record["n_required_subparts"] == 1
    assert record["baseline_required_hits"] == 0  # baseline never retrieved b1
    assert record["decomposed_required_hits"] == 1  # sub-question did


def test_analyze_wa4_computes_pooled_coverage():
    records = [
        {"question_id": "Q-1", "n_required_subparts": 2, "baseline_required_hits": 1, "decomposed_required_hits": 2, "hops_to_answer": 2, "error": None},
        {"question_id": "Q-2", "n_required_subparts": 1, "baseline_required_hits": 0, "decomposed_required_hits": 1, "hops_to_answer": 3, "error": None},
    ]
    summary = analyze_wa4(records)
    assert summary["void"] is False
    assert summary["total_required_subgoals"] == 3
    assert summary["decomposition_coverage_baseline"] == pytest.approx(1 / 3)
    assert summary["decomposition_coverage_decomposed"] == 1.0


def test_analyze_wa4_is_void_when_any_error_present():
    records = [{"question_id": "Q-1", "error": "boom"}]
    summary = analyze_wa4(records)
    assert summary["void"] is True
