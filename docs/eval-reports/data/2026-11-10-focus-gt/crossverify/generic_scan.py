import sqlite3,re,collections
P={"012 bandwidth width":("bandwidth",r"bandwidth.{0,100}(width|size|length).{0,30}(neighbo|window|interval)|(width|size|length) of the (neighbo|window|interval).{0,100}bandwidth"),
"011 just below/above":("cut",r"just (below|above).{0,120}cut.?o.{0,160}(counterfactual|comparison|comparable|similar|good as)|cut.?o.{0,80}just (below|above).{0,160}(counterfactual|comparison|comparable)"),
"016 collider spurious":("collider",r"(condition|adjust)\w* (on|for) (a |the |one )?colliders?.{0,120}(spurious|association|bias|dependence)"),
"018 adjustment set backdoor":("adjustment",r"adjustment set.{0,200}(block|clos).{0,80}back.?door|(block|clos)\w* (all |every )?(open )?back.?door paths?.{0,120}(without|not) (open|creat|introduc)"),
"002 exclusion only through":("exclusion",r"exclusion restriction.{0,160}(only|solely) (through|via)|(only|solely) (through|via).{0,60}exclusion restriction"),
"017 bad controls":("bad control",r"bad controls?.{0,160}(bias|invalid|condition)"),
"008 RD no interference":("interfer",r"(RD|regression discontinuity).{0,300}no interference|SUTVA.{0,200}(RD|discontinuity).{0,200}interference"),
}
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
rx={k:(t,re.compile(r,re.I|re.S)) for k,(t,r) in P.items()}
res={k:collections.OrderedDict() for k in P}
for cid,pid,text in con.execute("select chunk_id,paper_id,text from chunks"):
    low=text.lower()
    for k,(t,r) in rx.items():
        if t in low:
            m=r.search(text)
            if m: res[k].setdefault(pid,[]).append((cid,text[max(0,m.start()-60):m.end()+100].replace('\n',' ')))
out=[]
for k,v in res.items():
    out.append(f"## {k}: {len(v)} papers")
    for pid,l in list(v.items())[:12]: out.append(f"  {pid} {[c for c,_ in l][:4]} | {l[0][1][:260]}")
open('generic_scan.out','w').write('\n'.join(out))
