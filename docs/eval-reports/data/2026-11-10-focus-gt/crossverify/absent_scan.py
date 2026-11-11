import sqlite3,re,json
P=[ # (item, name, trigger(lowercase substr, or None), regex)
("041","HT name","hausman",r"Hausman.{0,12}Tay"),
("041","HT abbrev",None,r"\bHT (estimator|model|approach|instrument)"),
("041","HT-related","time",r"time.{0,3}invariant.{0,250}(regressor|covariate|variable).{0,250}(correlat|endogen)"),
("041","Mundlak/CRE","mundlak",r"Mundlak"),
("041","correlated random effects","random",r"correlated\s+random\s+effects?"),
("041","FE vs RE time-invariant","invariant",r"(fixed|random).{0,3}effects?.{0,250}time.{0,3}invariant"),
("041","unit effect exog instruments","unit",r"(unit|individual).{0,3}(specific )?effects?.{0,200}(instrument|exogenous (variable|regressor)s?).{0,200}time.{0,3}invariant"),
("042","BQ name","quah",r"Blanchard.{0,12}Quah|Quah"),
("042","long-run restrictions","long",r"long.{0,3}(run|term).{0,3}(restriction|identif|zero|neutral)"),
("042","permanent/transitory shocks","permanent",r"(permanent|transitory).{0,60}(shock|disturbance).{0,120}(supply|demand|output|unemploy)"),
("042","supply demand shocks SVAR","svar",r"(supply|demand).{0,40}shocks?.{0,200}(SVAR|structural VAR|VAR)"),
("043","BM name","bernanke",r"Bernanke"),
("043","Mihov","mihov",r"Mihov"),
("043","CEE recursive","christiano",r"Christiano.{0,30}Eichenbaum"),
("043","monetary shock identification","monetary",r"monetary.{0,60}(policy )?(shock|innovation|surprise).{0,250}(identif|recursive|Cholesky|assum)"),
("043","fed funds / nonborrowed reserves","reserves",r"non.?borrowed reserves|federal funds (rate )?(shock|identif)"),
("043","high-frequency / narrative","monetary",r"(high.frequency|narrative|Romer|Kuttner|Gertler).{0,120}monetary"),
("044","Koch","koch",r"\bKoch"),
("044","Henle","henle",r"Henle"),
("044","Bradford Hill","hill",r"Bradford.{0,3}Hill|Hill.s (criteria|viewpoints|considerations)"),
("044","pathogen","pathogen",r"pathogen"),
("044","germ theory/Evans","germ",r"germ theory|Evans.{0,5}postulate"),
("044","causal criteria epi","criteria",r"causal (criteria|guidelines).{0,200}(disease|epidemi)"),
("044","sufficient component cause","sufficient",r"sufficient.component cause|causal pie"),
("045","Coase","coase",r"Coas(e|ian)"),
("045","property rights","property",r"property.{0,3}rights?"),
("045","bargaining causal","bargain",r"bargain.{0,200}(causal|treatment effect)|(causal|treatment effect).{0,200}bargain"),
("046","Neyman paradox","neyman",r"Neyman.{0,6}(paradox|puzzle)"),
("046","post-treatment cond","post",r"(conditioning|condition(ed)?|adjust(ing|ment)?) (on|for) (a |the |any )?post.{0,3}(treatment|intervention|exposure)"),
("046","post-treatment bias","post",r"post.{0,3}treatment (bias|confound|variable|collider)"),
("047","dark matter causal","dark matter",r"dark matter.{0,300}(causal (effect|inference|identif|discover)|instrumental var|difference.in.dif+eren|propensity)"),
("047","causal dark matter rev","causal",r"(causal (effect|inference|identif|discover)|instrumental var|propensity).{0,300}dark matter"),
("048","BH/neutrino causal","neutrino",r"(neutrino|black hole).{0,300}(causal (effect|inference)|propensity|treatment effect|instrumental var)"),
("048","causal BH/neutrino rev","causal",r"(causal (effect|inference)|propensity|treatment effect|instrumental var).{0,300}(neutrino|black hole)"),
("048","merger neutrino","merger",r"merger.{0,200}neutrino"),
("049","sunspot causal","sunspot",r"sunspots?.{0,300}(causal|instrument|stock|return|econom|GDP|financ)"),
("049","solar-econ rev","solar",r"(stock|financ|econom|GDP|return)[a-z]*.{0,200}(sunspot|solar (cycle|activity)|geomagnetic)"),
("049","IV weather/solar","instrumental",r"instrumental var.{0,200}(sunspot|solar|sunshine|rainfall|weather)"),
("050","lunar behaviour","lunar",r"(lunar|full moon|moon phase).{0,250}(birth|crime|fertil|admission|suicid|behavio|delivery|violence)"),
("050","behaviour lunar rev","moon",r"(birth|crime|fertil|admission|suicid|delivery|violence).{0,250}(lunar|full moon|moon phase)"),
("050","lunar phase","lunar",r"lunar phase|moon phase|full moon"),
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
open('absent_scan.out','w').write('\n'.join(out))
print('done')
