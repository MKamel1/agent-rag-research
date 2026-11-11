import sys,re,json,sqlite3
sys.path.insert(0,"/tmp/claude-1000/-home-omar-ai-projects/3426f8b7-1c1a-4487-ad8c-3b6a5cbe5792/scratchpad/b")
from data_ab import *
try:
    from data_c import ABSENT
except ImportError:
    ABSENT=[]
lab={l.split("\t")[0]:l.split("\t")[1] for l in open("../2026-11-10-topic-labels/topic_labels.tsv")}
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
def chunk(cid):
    r=con.execute("select paper_id,text,section_path from chunks where chunk_id=?",(cid,)).fetchone(); assert r,cid; return r
def title(p): return con.execute("select title from papers where paper_id=?",(p,)).fetchone()[0]
items=[];n=0;bad=[]
def nid():
    global n; n+=1; return f"Q-FOC-{n:03d}"
for term,gc,ex,q,a,d,qt in COLL:
    pid,text,sec=chunk(gc); assert lab[pid]=="on",(gc,lab[pid])
    dom,rx,dch=DIST[term]; ev=[]
    for dc in dch:
        dp,dt,_=chunk(dc)
        if lab[dp]!="off" or not re.search(rx,dt,re.I): bad.append((term,dc)); continue
        ev.append({"paper_id":dp,"chunk_id":dc})
    assert len(ev)>=2,(term,ev)
    items.append({"question_id":nid(),"tests":"answerable","dimension":"collision","difficulty":d,"question_type":qt,
     "source_paper_id":pid,"source_paper_title":title(pid),"section_path":sec,"question_text":q,"passage_excerpt":ex,"answer_text":a,
     "paper_topic":"on","collision_term":term,"colliding_domain":dom,
     "distractor_paper_ids":[e["paper_id"] for e in ev],"distractor_evidence":ev})
for gc,ex,q,a,d,qt,lk,term,rx in OFF:
    pid,text,sec=chunk(gc); assert lab[pid]=="off",(gc,lab[pid])
    lp,lt,_=chunk(lk); assert lab[lp]=="on" and re.search(rx,lt,re.I),(lk,)
    items.append({"question_id":nid(),"tests":"answerable","dimension":"offtopic-legit","difficulty":d,"question_type":qt,
     "source_paper_id":pid,"source_paper_title":title(pid),"section_path":sec,"question_text":q,"passage_excerpt":ex,"answer_text":a,
     "paper_topic":"off","shared_term":term,"causal_lookalike_paper_ids":[lp],"causal_lookalike_evidence":[{"paper_id":lp,"chunk_id":lk}]})
for it in ABSENT:
    it=dict(it); it["question_id"]=nid(); items.append(it)
import collections
meta={"author":"EV-4 focus-gt","model":"claude-sonnet-5-5","date":"2026-11-10",
 "n_items":len(items),"dimension_counts":dict(collections.Counter(i["dimension"] for i in items)),
 "difficulty_counts":dict(collections.Counter(i["difficulty"] for i in items)),
 "note":"authored blind to retrieval (GPU down); distractors/lookalikes verified by chunk text + topic label"}
json.dump({"_metadata":meta,"ground_truth":items},open("author/items.json","w"),indent=1,ensure_ascii=False)
print(meta,"BAD",bad)
