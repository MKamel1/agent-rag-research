import json

from scripts.relevance_demotion_ab_table import extract, main, verdict


def _strata(contam=0.2, coll=20, legit=12, errs=0, rank1=2, dist=3, look=1):
    dims = {"collision": {"member_hit": {"hits": coll, "n": 26}},
            "offtopic-legit": {"member_hit": {"hits": legit, "n": 14},
                               "paper_recall": {"hits": legit, "n": 14}}}
    return {"r": {"per_dimension": dims, "n_errored_rows": errs, "focus": {
        "on_gold_answerable": {"mean_off_share_topk": contam, "off_at_rank1": {"hits": rank1, "n": 26},
                               "distractor_outranks_gold": {"hits": dist, "n": 26}},
        "offtopic_legit_lookalike_outranks_gold": {"hits": look, "n": 14}}}}


def _arm(root, name, **kw):
    d = root / name
    d.mkdir()
    one = {"per_dimension": {"x": {"member_hit": {"hits": kw.get("hit", 30), "n": 38}}}, "n_errored_rows": 0}
    for n, s in [("focus", _strata(**{k: v for k, v in kw.items() if k != "hit"})), ("papers", _strata(contam=0.1)),
                 ("papers-topic-on", {"r": one}), ("papers-topic-off", {"r": one}), ("books", {"r": one})]:
        (d / f"strata-{n}.json").write_text(json.dumps(s))
    for n in ("focus", "papers", "books"):
        (d / f"{n}.json").write_text(json.dumps({"questions": [{"retrieved_paper_ids": ["a"] * 10}]}))
    return d


def test_verdict_adopt_and_reject(tmp_path):
    base = extract(_arm(tmp_path, "baseline"))
    good = extract(_arm(tmp_path, "good", contam=0.05, coll=19))      # one question lost is tolerated
    bad = extract(_arm(tmp_path, "bad", contam=0.05, legit=9))        # three legit items lost
    flat = extract(_arm(tmp_path, "flat", contam=0.15))               # not halved
    assert verdict(base, good) == ("ADOPT-eligible", [])
    assert "offtopic-legit paper recall drop <= 1" in verdict(base, bad)[1]
    assert "focus contamination@10 <= 0.5 x baseline" in verdict(base, flat)[1]


def test_floor_clause_rejects_clean_baseline(tmp_path):
    base = extract(_arm(tmp_path, "baseline", contam=0.03))
    assert verdict(base, base)[0] == "REJECT"


def test_main_prints_table(tmp_path, capsys):
    _arm(tmp_path, "baseline")
    _arm(tmp_path, "tail@0.30", contam=0.05)
    assert main([str(tmp_path)]) == 0
    assert "| tail@0.30 |" in capsys.readouterr().out
