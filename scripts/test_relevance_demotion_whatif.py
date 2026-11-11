from scripts.relevance_demotion_whatif import below_share, gold_groups, render


def test_below_share_ignores_null_and_is_strict():
    assert below_share(["a", "b", "c", "d"], {"a": 0.1, "b": 0.3, "c": None, "d": 0.5}, 0.3) == (1, 4)


def test_gold_groups_and_render():
    gt = {"ground_truth": [
        {"tests": "answerable", "dimension": "collision", "paper_topic": "on", "source_paper_id": "a",
         "distractor_paper_ids": ["x"]},
        {"tests": "absent", "dimension": "focus-absent", "source_paper_id": "z"},
    ]}
    assert gold_groups(gt) == {"collision|on": ["a"], "collision:distractors": ["x"]}
    out = render({"a": 0.1, "x": 0.1}, {"a": "on", "x": "off"}, {"f": gt})
    assert "| collision|on | 1 | 1 (100.0%)" in out and "label=off" in out
