"""Tests for scripts/eval_protocol_tools.py -- pure functions on synthetic dicts."""

import json

from scripts.eval_protocol_tools import (
    ablate_ground_truth,
    ablate_question,
    check_hashes,
    points_plausible,
    sha256_of,
    split_report,
    wilson_halfwidth,
    wilson_table,
)


def test_check_hashes_ok_changed_null_missing(tmp_path):
    f = tmp_path / "gt.json"
    f.write_text("{}")
    h = tmp_path / "h.json"
    h.write_text(json.dumps({"fixtures": {"gt.json": sha256_of(f), "n.json": None}}))
    assert check_hashes(h, ["gt.json"], tmp_path) == []
    assert "not frozen" in check_hashes(h, ["n.json"], tmp_path)[0]
    assert "not listed" in check_hashes(h, ["x.json"], tmp_path)[0]
    f.write_text("{ }")
    assert "SHA-256" in check_hashes(h, ["gt.json"], tmp_path)[0]


def test_points_plausible_rejects_other_corpus():
    assert points_plausible(35_833, 35_714, 119)
    assert not points_plausible(412_000, 35_714, 119)
    assert not points_plausible(35_833, 399_676, 12_390)


def test_ablate_question_drops_title_words_keeps_clause_numbers():
    title = "ISO 26262-7-2018 Production, Operation"
    q = "Under clause 7.4.1.1 of ISO 26262-7, what must the field monitoring do?"
    out = ablate_question(q, title)
    assert "ISO" not in out and "26262-7," not in out
    assert "7.4.1.1" in out and "of" in out and "monitoring" in out


def _item(qid, dim="clause-lookup", tests="answerable", **kw):
    return {"question_id": qid, "dimension": dim, "tests": tests, **kw}


def test_ablate_ground_truth_omits_and_counts():
    gt = {
        "_metadata": {"n": 5},
        "ground_truth": [
            _item(
                "a",
                source_paper_title="Alpha Beta",
                question_text="What does Alpha Beta say about gamma delta epsilon?",
            ),
            _item(
                "b",
                dim="edition",
                source_paper_title="Alpha",
                question_text="Alpha 2019 edition question words here",
            ),
            _item("c", tests="absent", question_text="whatever you like"),
            _item("d", question_text="no title here"),
            _item("e", source_paper_title="Alpha", question_text="Alpha beta gamma"),
        ],
    }
    out = ablate_ground_truth(gt)
    assert [i["question_id"] for i in out["ground_truth"]] == ["a"]
    assert out["ground_truth"][0]["question_text"] == "What does say about gamma delta epsilon?"
    assert out["_metadata"]["omitted"] == {
        "no document name to remove": 2,
        "not answerable": 1,
        "fewer than 4 words left": 1,
    }


def test_split_report_groups_by_field():
    gt = {
        "ground_truth": [
            {"question_id": "a", "paper_topic": "on"},
            {"question_id": "b", "paper_topic": "off"},
        ]
    }
    rep = {"x": 1, "questions": [{"question_id": "a"}, {"question_id": "b"}]}
    parts = split_report(gt, rep, "paper_topic")
    assert set(parts) == {"off", "on"} and parts["on"]["questions"] == [{"question_id": "a"}]


def test_wilson():
    assert abs(wilson_halfwidth(4) - 0.35) < 0.01
    gt = {"ground_truth": [_item("a", gold_block_id="b"), _item("b"), _item("c", tests="absent")]}
    assert wilson_table(gt)[0][:3] == ("clause-lookup", 2, 1)
