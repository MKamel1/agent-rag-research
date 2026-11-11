# ruff: noqa  (one-off corpus scan; output saved as scans/ev4b_batch5.out)
import re,sqlite3,collections
P={"SCC_tol":r"su+f+icient.component cause|causal pies?|Rothman.{0,30}pie|minimal su+f+icient (set|cause)","SCC_synergy_tol":r"(su+f+icient|component) cause.{0,300}(synerg|interaction)|synergistic (interaction|action).{0,200}(cause|pie)","Wald_bomber":r"Wald.{0,80}(bomber|aircraft|armou?r|WWII|World War)|(bomber|returning aircraft).{0,120}(armou?r|bullet hole)","Snow_water":r"Snow.{0,300}(water|pump)|Lambeth|Southwark|Vauxhall|Broad Street","sunshine_stock":r"sunshine.{0,200}(stock|return|market)|Hirshleifer.{0,40}Shumway","survivorship":r"survivorship bias","BQ_name":r"Blanchard.{1,8}Quah","BQ_outputeffect":r"(Blanchard.{1,8}Quah|long.run restrictions?).{0,300}(demand|supply|transitory|permanent).{0,200}(output|GDP)"}
R={k:re.compile(v,re.I) for k,v in P.items()}
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
cnt=collections.Counter(); ex=collections.defaultdict(list); ctx=collections.defaultdict(list)
for cid,t in con.execute("select chunk_id,text from chunks"):
    for k,r in R.items():
        m=r.search(t)
        if m:
            cnt[k]+=1
            if len(ex[k])<8: ex[k].append(cid)
            if len(ctx[k])<6: ctx[k].append((cid,t[max(0,m.start()-150):m.end()+250].replace("\n"," ")))
print("### COUNTS")
for k in P: print(f"{cnt[k]:6d} {k} {ex[k] if cnt[k]<=8 else ''}")
print("### CONTEXTS (<=8 hits)")
for k,v in ctx.items():
    if cnt[k]<=8:
        print("##",k)
        for c,s in v: print(" ",c,"|",s)
