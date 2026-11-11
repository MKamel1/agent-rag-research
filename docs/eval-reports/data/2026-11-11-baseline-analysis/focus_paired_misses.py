import json,sys
sys.path.insert(0,'scripts')
import eval_strata_report as E
D='docs/eval-reports/data/'
g={i['question_id']:i for i in json.load(open(D+'2026-11-10-focus-gt/focus_gt.json'))['ground_truth']}
reps={'sys':json.load(open(D+'2026-11-10-papers-passage-gt/runs/20261111T012931/focus.json')),'bm':json.load(open(D+'2026-11-10-bm25-floor/focus-standard.report.json'))}
ps=set()
for r in reps.values():
    for q in r['questions']: ps|=set(q['retrieved_paper_ids'][:10])|set(q['gold_paper_ids'])
for i in g.values(): ps|=set(i.get('additional_gold_paper_ids') or [])
maps=E.build_db_maps('/home/omar/ai-projects/research-system-rag-data/papers.db',ps)
miss={}
for n,r in reps.items():
    m={};pm=set()
    for q in r['questions']:
        i=g[q['question_id']]
        if i['tests']!='answerable':continue
        a,mm=E.passage_ranks(q,i,10,*maps[:2]); m[q['question_id']]=(i['dimension'],mm)
        if not q['paper_level']['hit']: pm.add(q['question_id'])
    miss[n]=({k for k,v in m.items() if v[1] is None},pm,m)
    print(n,'member misses',sorted(miss[n][0]),'paper misses',sorted(pm))
s,b=miss['sys'][0],miss['bm'][0]
print('both',sorted(s&b),'sys only',sorted(s-b),'bm only',sorted(b-s))
