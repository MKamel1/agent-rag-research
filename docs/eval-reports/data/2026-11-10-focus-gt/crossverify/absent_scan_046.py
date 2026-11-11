import sqlite3,re,json
P=[("046","Neyman paradox","neyman",r"Neyman.{0,6}(paradox|puzzle)"),
("046","post-treatment cond","post",r"(conditioning|condition(ed)?|adjust(ing|ment)?) (on|for) (a |the |any )?post.{0,3}(treatment|intervention|exposure)"),
("046","post-treatment bias","post",r"post.{0,3}treatment (bias|confound|variable|collider)"),
]
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
rx=[(i,n,t,re.compile(r,re.I|re.S)) for i,n,t,r in P]
cnt={ (i,n):0 for i,n,_,_ in P}; samp={k:[] for k in cnt}
for cid,pid,text in con.execute("select chunk_id,paper_id,text from chunks"):
    low=text.lower()
    for i,n,t,r in rx:
        if t and t not in low: continue
        m=r.search(text)
        if m:
            cnt[(i,n)]+=1
            if len(samp[(i,n)])<6:
                s=max(0,m.start()-150); samp[(i,n)].append((cid,text[s:m.end()+250].replace('\n',' ')))
out=[]
for k,v in cnt.items():
    out.append(f"## item {k[0]} | {k[1]} | hits={v}")
    for cid,s in samp[k]: out.append(f"  [{cid}] {s}")
open('absent_scan_046.out','w').write('\n'.join(out))
print('done')
