import json,sys
sys.path.insert(0,'scripts')
import eval_strata_report as E
D='docs/eval-reports/data/'
def load(gt,sysrep,bmrep,db):
    g={i['question_id']:i for i in json.load(open(gt))['ground_truth']}
    reps={n:json.load(open(p)) for n,p in (('sys',sysrep),('bm',bmrep))}
    papers=set()
    for r in reps.values():
        for q in r['questions']: papers|=set(q['retrieved_paper_ids'][:10])|set(q['gold_paper_ids'])
    for i in g.values(): papers|=set(i.get('additional_gold_paper_ids') or [])
    maps=E.build_db_maps(db,papers)
    out={}
    for n,r in reps.items():
        d={}
        for q in r['questions']:
            i=g[q['question_id']]
            if i['tests']!='answerable' or not i.get('gold_block_id'): continue
            a,m=E.passage_ranks(q,i,10,*maps[:2])
            d[q['question_id']]=(m,a,i['dimension'],q['paper_level']['hit'])
        out[n]=d
    return out
if __name__=='__main__':
    R=sys.argv[1]
    for name,gt,sysf,bmf in (('papers',D+'2026-11-10-papers-passage-gt/papers_passage_gt.json',R+'/papers.json',D+'2026-11-10-bm25-floor/papers-standard.report.json'),
                            ('books',D+'2026-11-10-causal-books-gt/causal_books_gt.json',R+'/books.json',D+'2026-11-10-bm25-floor/books-standard.report.json')):
        o=load(gt,sysf,bmf,'/home/omar/ai-projects/research-system-rag-data/papers.db')
        s,b=o['sys'],o['bm']
        ids=sorted(s)
        sm={q for q in ids if s[q][0] is None}; bmm={q for q in ids if b[q][0] is None}
        print(name,'n',len(ids),'sys member hits',len(ids)-len(sm),'bm hits',len(ids)-len(bmm))
        print(' both',len(sm&bmm),sorted(sm&bmm)); print(' sys only',len(sm-bmm),sorted(sm-bmm)); print(' bm only',len(bmm-sm),sorted(bmm-sm))
        print(' sys p1',sum(s[q][0]==1 for q in ids),'bm p1',sum(b[q][0]==1 for q in ids),'sys anchor',sum(s[q][1] is not None for q in ids),'bm anchor',sum(b[q][1] is not None for q in ids))
        for dim in sorted({s[q][2] for q in ids}):
            qs=[q for q in ids if s[q][2]==dim]
            print('  ',dim,len(qs),'sys',sum(s[q][0] is not None for q in qs),'bm',sum(b[q][0] is not None for q in qs),'sysP1',sum(s[q][0]==1 for q in qs),'bmP1',sum(b[q][0]==1 for q in qs))
        print(' paper miss sys',sorted(q for q in ids if not s[q][3]),'bm',sorted(q for q in ids if not b[q][3]))
