# ruff: noqa  (one-off corpus scan; output saved as scans/ev4b_batch2.out)
import re,sqlite3,collections
LAB="/home/omar/ai-projects/research-system-rag/.claude/worktrees/EP-EV4b-focus-fixes/docs/eval-reports/data/2026-11-10-topic-labels/topic_labels.tsv"
lab={l.split("\t")[0]:l.split("\t")[1] for l in open(LAB) if l.count("\t")>=2}
CTX={"Stein_paradox":r"Stein.s paradox","Semmelweis":r"Semmelweis","ring_vacc":r"ring vaccination","Uhlig":r"Uhlig","Granger_Sims":r"Sims.{0,10}(causality|exogeneity)",
"Cragg_Donald":r"Cragg.Donald","MTO":r"Moving to Opportunity","settler":r"settler mortality","Neyman_paradox":r"Neyman.{0,3}s? paradox","galaxy_causal":r"galax.{0,200}(propensity|instrumental variable|regression discontinuity|difference.in.dif+erences?)","Sims_Zha":r"Sims.{0,6}Zha"}
CNT={"Lucas_critique":r"Lucas critique","Goodhart":r"Goodhart","Hawthorne":r"Hawthorne effect","Chow":r"Chow test","DWH":r"Durbin.{0,3}Wu.{0,3}Hausman","Cochrane_Orcutt":r"Cochrane.Orcutt","Okun":r"Okun.s law","Phillips_curve":r"Phillips curve","Taylor_rule":r"Taylor rule","Latin_square":r"Latin square","Wright_path":r"Sewall Wright|path coefficient","Fisher_exact":r"Fisher.s exact","Berkeley_adm":r"Berkeley.{0,20}admission","Dickey_Fuller":r"Dickey.Fuller","Gauss_Markov":r"Gauss.Markov","Newey_West":r"Newey.West","Frisch_Waugh":r"Frisch.Waugh","Heckscher":r"Heckscher|Ohlin","Ricardian":r"Ricardian","Solow":r"Solow","Kuznets":r"Kuznets","Giffen":r"Giffen","Pigou":r"Pigou","Nash":r"Nash equilibri","Cobb_Douglas":r"Cobb.Douglas","Tobit":r"\bTobit\b","Poisson_pseudo":r"pseudo.?Poisson|PPML","Sobel":r"Sobel test","Baron_Kenny":r"Baron.{0,6}Kenny","VanderWeele_interven":r"interventional (direct|indirect) effect","Imai_mediation":r"sequential ignorability","Gelfand":r"Gelfand","Kaplan_Meier":r"Kaplan.Meier","Cox_model":r"Cox proportional","Mendelian":r"Mendelian randomi","Hume":r"\bHume\b","Mill_methods":r"Mill.s methods?|method of difference","Salmon":r"Salmon.{0,20}(causal|process)","Lewis_counterfactual":r"Lewis.{0,30}(counterfactual|possible world)","Woodward":r"Woodward","Pearl_ladder":r"ladder of causation","Reichenbach":r"Reichenbach|common cause principle","Granger_1969":r"Granger.{0,6}1969","Schwarz_BIC":r"\bBIC\b","Kalman":r"Kalman","Neyman_Scott":r"Neyman.Scott","Berkson":r"Berkson","Yule_Simpson":r"Yule.{0,10}Simpson"}
RC={k:re.compile(v,re.I) for k,v in {**CTX,**CNT}.items()}
MED=re.compile(r"mediation analysis|natural indirect|mediator",re.I)
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
cnt=collections.Counter(); ex=collections.defaultdict(list); ctx=collections.defaultdict(list); med=[]
for cid,pid,t in con.execute("select chunk_id,paper_id,text from chunks"):
    for k,r in RC.items():
        m=r.search(t)
        if m:
            cnt[k]+=1
            if len(ex[k])<8: ex[k].append(cid)
            if k in CTX and len(ctx[k])<12: ctx[k].append((cid,t[max(0,m.start()-150):m.end()+200].replace("\n"," ")))
    if lab.get(pid)=="on" and len(med)<400 and MED.search(t) and len(t)<1800:
        m=MED.search(t); med.append((cid,t[max(0,m.start()-120):m.end()+160].replace("\n"," ")))
print("### COUNTS")
for k in {**CTX,**CNT}: print(f"{cnt[k]:6d} {k} {ex[k] if cnt[k]<=8 else ''}")
print("### CONTEXTS")
for k,v in ctx.items():
    print("##",k)
    for c,s in v: print(" ",c,"|",s)
print("### ON-MEDIATION SAMPLES")
for c,s in med[::4]: print(" ",c,"|",s)
