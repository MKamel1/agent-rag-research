import json,re,sys,subprocess
exec(open('src1.py').read())
S=json.load(open('../sample-G.json')); T={s['paper_id']:s['title'] for s in S}
P='/tmp/claude-1000/-home-omar-ai-projects/3426f8b7-1c1a-4487-ad8c-3b6a5cbe5792/scratchpad/p/'
norm=lambda t:re.sub(r'\s+',' ',t).strip().lower()
ALT={"2210.11186":["2210.11186:c23"],"2105.00416":["2105.00416:c16"]}
out=[]
for n,i in enumerate(I,1):
    parts=re.split(r'(?m)^=== ',open(P+i['p']+'.txt').read())[1:]
    sp=[x.split('\n')[0].split('|')[1].strip() for x in parts if norm(i['ex']) in norm(x)]
    assert sp,i['p']
    o=dict(question_id=f"Q-PAPG-{n:03d}",tests="answerable",dimension=i['dim'],difficulty=i['diff'],question_type=i['qt'],
      source_paper_id=i['p'],source_paper_title=T[i['p']],section_path=sp[0],question_text=i['q'],passage_excerpt=i['ex'],answer_text=i['ans'])
    if i['p'] in ALT:o['alternative_gold_chunk_ids']=ALT[i['p']]
    out.append(o)
from collections import Counter
md=dict(author="G",model="claude-sonnet-5-5",date="2026-11-10",corpus="main paper corpus, sample-G.json (32 papers; 30 items)",counts=dict(Counter(o['dimension'] for o in out)),difficulty=dict(Counter(o['difficulty'] for o in out)))
json.dump({"_metadata":md,"ground_truth":out},open('items.json','w'),indent=1,ensure_ascii=False)
print(md)
