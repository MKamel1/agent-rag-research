import re,sqlite3,sys,random,argparse
ap=argparse.ArgumentParser();ap.add_argument("label");ap.add_argument("pats",nargs="+");ap.add_argument("-n",type=int,default=6);ap.add_argument("-w",type=int,default=250)
ap.add_argument("--seed",type=int,default=0);ap.add_argument("--full",action="store_true");ap.add_argument("--minlen",type=int,default=400)
a=ap.parse_args()
lab={l.split("\t")[0]:l.split("\t")[1] for l in open("../2026-11-10-topic-labels/topic_labels.tsv")}
rx=[re.compile(p,re.I) for p in a.pats]
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
title={p:t for p,t in con.execute("select paper_id,title from papers")}
hits=[]
for cid,pid,t in con.execute("select chunk_id,paper_id,text from chunks"):
    if lab.get(pid)!=a.label or len(t)<a.minlen: continue
    if all(r.search(t) for r in rx): hits.append((cid,pid,t))
print("total",len(hits),"papers",len({h[1] for h in hits}))
random.Random(a.seed).shuffle(hits)
seen=set()
for cid,pid,t in hits:
    if pid in seen: continue
    seen.add(pid)
    if len(seen)>a.n: break
    m=rx[0].search(t)
    s=t if a.full else t[max(0,m.start()-a.w):m.end()+a.w]
    print(f"--- {cid} | {pid} | {title[pid][:80]}\n{s.replace(chr(10),' ')}\n")
