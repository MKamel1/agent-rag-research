# ruff: noqa  (one-off corpus scan; output saved as scans/ev4b_batch4.out)
import re,sqlite3,collections
P={"Perry_Abecedarian_HeadStart":r"Perry Preschool|Abecedarian|Head Start","Progresa":r"Progresa|Oportunidades","JobCorps_NSW":r"Job Corps|National Supported Work","Ashenfelter_dip":r"Ashenfelter.{0,3}s? dip","Haavelmo":r"Haavelmo","Cowles":r"Cowles Commission|Cowles Foundation","Reiersol":r"Reiers","Granger_Newbold":r"Granger.{0,6}Newbold|Engle.Granger|Johansen","Hendry":r"Hendry","Markov_switching":r"Markov.switching","border_county":r"border.county|Dube.{0,10}Lester","Tinbergen":r"Tinbergen","ProjectSTAR":r"Project STAR|Student.Teacher Achievement Ratio","SCC_pies":r"sufficient.component cause|causal pies?|Rothman.{0,30}pie","SCC_interaction":r"(sufficient|component) cause.{0,200}(interaction|synerg)","Rothman":r"Rothman","BQ_name":r"Blanchard.{1,8}Quah","BQ_outputeffect":r"(Blanchard.{1,8}Quah|long.run restrictions?).{0,300}(demand|supply|transitory|permanent).{0,200}(output|GDP)","sunspot_stock":r"sunspots?.{0,300}(stock|market|econom|GDP)|(stock|market|econom|GDP).{0,300}sunspots?","lunar_birth":r"(lunar|moon).{0,200}(birth|fertility|crime)","Cochrane_Orcutt":r"Cochrane.Orcutt","Prais_Winsten":r"Prais.Winsten","Lord_paradox":r"Lord.s paradox","Anscombe":r"Anscombe","Hirano_GPS":r"generalized propensity score","Kline_Moretti":r"Kline.{0,6}Moretti|Tennessee Valley","Autor_Dorn":r"Autor.{0,6}Dorn|China shock","Chetty_mobility":r"Chetty.{0,40}mobility|Opportunity Insights","Jaeger":r"Jaeger"}
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
