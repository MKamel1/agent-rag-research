# ruff: noqa  (one-off corpus scan; output saved as scans/ev4b_batch3.out)
import re,sqlite3,collections
P={"Maimonides":r"Maimonides","Thistlethwaite":r"Thistlethwaite","Oster":r"Oster.{0,12}(2019|bounds?)|Oster bounds","Altonji":r"Altonji","Rothman_pie":r"Rothman.{0,30}pie|sufficient.component cause","Hodges_Lehmann":r"Hodges.Lehmann","BLP":r"Berry.{0,15}Levinsohn|\bBLP\b","Olley_Pakes":r"Olley.Pakes|Levinsohn.Petrin","Dunning":r"Dunning","tea":r"tea.tasting|lady tasting","Hawthorne":r"Hawthorne effect","Cochrane_Orcutt":r"Cochrane.Orcutt","Lucas":r"Lucas critique","Pigou":r"Pigou","Giffen":r"Giffen","Okun":r"Okun","Ricardian":r"Ricardian","Hotelling":r"Hotelling","Meyer_Viscusi":r"Meyer.{0,10}Viscusi|workers.{0,3} compensation","Bertrand_Duflo":r"Bertrand.{0,10}Duflo","Heckman_Singer":r"Heckman.{0,6}Singer","Nevo":r"\bNevo\b","kink_galaxy":r"kink.{0,200}galax|galax.{0,200}kink"}
R={k:re.compile(v,re.I) for k,v in P.items()}
CT={"Hawthorne","Cochrane_Orcutt","Lucas","Pigou","Giffen","Okun"}
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
cnt=collections.Counter(); ex=collections.defaultdict(list); ctx=collections.defaultdict(list)
for cid,t in con.execute("select chunk_id,text from chunks"):
    for k,r in R.items():
        m=r.search(t)
        if m:
            cnt[k]+=1
            if len(ex[k])<8: ex[k].append(cid)
            if k in CT and len(ctx[k])<8: ctx[k].append((cid,t[max(0,m.start()-200):m.end()+250].replace("\n"," ")))
print("### COUNTS")
for k in P: print(f"{cnt[k]:6d} {k} {ex[k] if cnt[k]<=8 else ''}")
print("### CONTEXTS")
for k,v in ctx.items():
    print("##",k)
    for c,s in v: print(" ",c,"|",s)
