import json,sys,statistics
sys.path.insert(0,'scripts'); 
import eval_strata_report as E
D='docs/eval-reports/data/'
R=D+'2026-11-10-papers-passage-gt/runs/20261111T004734/'
B=D+'2026-11-10-bm25-floor/'
lab=E.load_labels(__import__('pathlib').Path(D+'2026-11-10-topic-labels/topic_labels.tsv'))
db='/home/omar/ai-projects/research-system-rag-data/papers.db'
for name,gt,files in (('papers',D+'2026-11-10-papers-passage-gt/papers_passage_gt.json',{'sys':'papers.json','sys-abl':'papers.ablated.json','bm':B+'papers-standard.report.json','bm-abl':B+'papers-title-ablated.report.json'}),
                      ('books',D+'2026-11-10-causal-books-gt/causal_books_gt.json',{'sys':'books.json','sys-abl':'books.ablated.json','bm':B+'books-standard.report.json','bm-abl':B+'books-title-ablated.report.json'})):
    g={i['question_id']:i for i in json.load(open(gt))['ground_truth']}
    reps={k:json.load(open(v if v.startswith('docs') else R+v)) for k,v in files.items()}
    papers=set()
    for r in reps.values():
        for q in r['questions']: papers|=set(q['retrieved_paper_ids'][:10])|set(q['gold_paper_ids'])
    maps=E.build_db_maps(db,papers)
    print('==',name)
    for k,r in reps.items():
        print(k,'n_q',len(r['questions']),'gt',r.get('ground_truth_sha256_12'))
        rows={}
        for q in r['questions']:
            i=g[q['question_id']]
            if i['tests']!='answerable': continue
            a,m=E.passage_ranks(q,i,10,*maps[:2])
            gp=E.gold_papers(q,i)
            rows[q['question_id']]=(i.get('paper_topic'),i['dimension'],m,a,q['paper_level']['hit'],gp)
        def line(lbl,sel):
            n=len(sel)
            f=lambda x:f"{x}/{n}={x/n:.3f}"
            print(f"  {lbl:12} n={n} member {f(sum(v[2] is not None for v in sel))} P1 {f(sum(v[2]==1 for v in sel))} anchor {f(sum(v[3] is not None for v in sel))} paperR {f(sum(v[4] for v in sel))}")
        line('pooled',list(rows.values()))
        if name=='papers':
            for t in ('on','off','borderline'):
                line('topic='+t,[v for v in rows.values() if v[0]==t])
