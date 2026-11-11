import json,sys
sys.path.insert(0,'scripts')
import eval_strata_report as E
D='docs/eval-reports/data/'
R=D+'2026-11-10-standards-gt/runs/20261111T013215/'
g={i['question_id']:i for i in json.load(open(D+'2026-11-10-standards-gt/standards_gt.json'))['ground_truth']}
arms=['depth128-fused','depth128-fused-repeat','depth64-fused','depth32-fused','depth128-dense_only','depth128-sparse_only']
files={a:R+a+'.json' for a in arms}
files.update({a+'.abl':R+a+'.ablated.json' for a in arms if a!='depth128-fused-repeat'})
files['bm']=D+'2026-11-10-bm25-floor/standards-standard.report.json'
reps={k:json.load(open(v)) for k,v in files.items()}
ps=set()
for r in reps.values():
    for q in r['questions']: ps|=set(q['retrieved_paper_ids'][:10])|set(q['gold_paper_ids'])
for i in g.values(): ps|=set(i.get('additional_gold_paper_ids') or [])
maps=E.build_db_maps('/home/omar/ai-projects/research-system-rag-standards/data/papers.db',ps)
H={}
for k,r in reps.items():
    h={}
    for q in r['questions']:
        i=g[q['question_id']]
        if i['tests']!='answerable' or not i.get('gold_block_id'): continue
        a,m=E.passage_ranks(q,i,10,*maps[:2]); h[q['question_id']]=(m is not None,m==1,i['dimension'])
    H[k]=h
    print(k,'n',len(h),'H',sum(v[0] for v in h.values()),'P1',sum(v[1] for v in h.values()))
def flips(a,b):
    A,B=H[a],H[b]; w=sorted(q for q in A if A[q][0] and not B[q][0]); l=sorted(q for q in A if B[q][0] and not A[q][0])
    print(f'{a} vs {b}: only-{a} {len(w)} {w} | only-{b} {len(l)} {l}')
for a,b in [('depth128-fused','depth128-fused-repeat'),('depth128-fused','depth32-fused'),('depth128-fused','depth64-fused'),('depth128-fused.abl','depth32-fused.abl'),('depth128-dense_only','depth128-fused'),('depth128-dense_only.abl','depth128-fused.abl'),('depth128-sparse_only','depth128-fused'),('depth128-fused','bm')]:
    flips(a,b)
# repeat P1 diff and per-question retrieved list diffs
a=reps['depth128-fused']['questions'];b=reps['depth128-fused-repeat']['questions']
print('repeat top10 id lists differ on',sum(x['retrieved_block_ids']!=y['retrieved_block_ids'] for x,y in zip(a,b)),'of',len(a))
# strata stats by dim for bm vs 128
