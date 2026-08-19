"""Compare three diversity strategies on real questions against the real causal corpus.

Claim under test: the ADDITIVE form (min_distinct_papers) dominates the SUBTRACTIVE one
(max_hits_per_paper) on recall while matching it on distinct-paper coverage -- and the only price
is a larger result set.
"""
import json, sys, statistics
sys.path.insert(0, "/home/omar/ai-projects/research-system-rag")
from app.assembly import build_mcp_server
from rag.config import load_config
from contracts.vector_index import SearchFilters

GT = "/home/omar/ai-projects/research-system-rag/fixtures/eval/eval_ground_truth.json"
# question_text lives in the sibling blind file, joined by question_id (see load_questions).
_gt = json.load(open(GT))["ground_truth"]
_blind = json.load(open(GT.replace("eval_ground_truth", "eval_questions_blind")))
_blind = _blind if isinstance(_blind, list) else _blind.get("questions", _blind.get("ground_truth", []))
_text = {r["question_id"]: r["question_text"] for r in _blind if "question_text" in r}
qs = [dict(r, question_text=_text[r["question_id"]]) for r in _gt if r["question_id"] in _text][:60]
print(f"loaded {len(qs)} questions with text")
cfg = load_config("/home/omar/ai-projects/research-system-rag-data/config.yaml")
server = build_mcp_server(cfg)
K = 10

modes = {
    "plain (uncapped)":        None,
    "capped max_hits=2":       SearchFilters(max_hits_per_paper=2),
    "additive min_papers=8":   SearchFilters(min_distinct_papers=8),
}
agg = {m: {"gold": 0, "papers": [], "size": [], "lost_vs_plain": 0} for m in modes}
plain_blocks = {}

for i, q in enumerate(qs):
    gold = set(q.get("gold_paper_ids") or [q.get("source_paper_id")])
    gold |= set(q.get("additional_gold_paper_ids") or [])
    for name, filt in modes.items():
        try:
            res, _cov = server.retriever.retrieve(q["question_text"], filt, K)
        except Exception as e:
            print(f"  Q{q['question_id']} {name}: {type(e).__name__}: {e}"); continue
        ids = {r.paper_id for r in res}
        blocks = {r.anchor.block_id for r in res}
        agg[name]["gold"] += 1 if ids & gold else 0
        agg[name]["papers"].append(len(ids))
        agg[name]["size"].append(len(res))
        if name == "plain (uncapped)":
            plain_blocks[i] = blocks
        else:
            agg[name]["lost_vs_plain"] += len(plain_blocks.get(i, set()) - blocks)
    if (i + 1) % 20 == 0:
        print(f"  ...{i+1}/{len(qs)}", flush=True)

n = len(qs)
print(f"\n{'mode':26s} {'gold found':>11s} {'distinct papers':>16s} {'result size':>12s} {'passages LOST':>14s}")
print("-" * 84)
for name in modes:
    a = agg[name]
    print(f"{name:26s} {a['gold']:>6d}/{n:<4d} {statistics.mean(a['papers']):>16.2f} "
          f"{statistics.mean(a['size']):>12.2f} {a['lost_vs_plain']:>14d}")
