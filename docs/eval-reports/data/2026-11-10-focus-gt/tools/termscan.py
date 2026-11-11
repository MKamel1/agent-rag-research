import re,sqlite3,collections,json
lab={l.split("\t")[0]:l.split("\t")[1] for l in open("../2026-11-10-topic-labels/topic_labels.tsv")}
T={
"instrument":r"\binstruments?\b","treatment":r"\btreatments?\b","intervention":r"\binterventions?\b",
"ef+ect":r"\beffects?\b","exposure":r"\bexposures?\b","dose":r"\bdos(e|es|age)\b","counterfactual":r"counterfactual",
"propensity":r"propensity","confounding":r"confound","matching":r"\bmatching\b","discontinuity":r"discontinuit",
"mediation":r"\bmediat","shock":r"\bshocks?\b","attribution":r"\battribution","causal structure":r"causal structure",
"causal ordering":r"causal order","selection":r"\bselection\b","interference":r"\binterference\b","spillover":r"spill-?over",
"control":r"\bcontrols?\b","potential outcome":r"potential outcome","backdoor":r"back-?door","do-operator":r"\bdo\(|do-operator|do-calculus",
"uplift":r"\buplift","collider":r"collider","causal attention":r"causal (self-)?attention|causal mask","causal convolution":r"causal convolution",
"causality(physics)":r"\bcausality\b","randomi[sz]ation":r"randomi[sz]","weak instrument":r"weak instrument","bias":r"\bbias\b",
"endogenous":r"endogen","lag":r"\blags?\b","synthetic control":r"synthetic control","regression discontinuity":r"regression discontinuity",
"difference-in-differences":r"difference-in-differences?|dif+erence-in-dif+erences?","identifiability":r"identifiab","ignorability":r"ignorab",
"overlap":r"\boverlap\b","covariate shift":r"covariate shift","granger":r"granger","transfer entropy":r"transfer entropy",
"counterfactual(opt)":r"counterfactual","placebo":r"placebo","heterogeneous":r"heterogene","treatment effect":r"treatment ef+ect",
"intervene":r"\bintervene","ablation":r"\bablat","trigger":r"\btrigger","bandit":r"\bbandit","policy evaluation":r"off-policy",
"sensitivity analysis":r"sensitivity analysis","balance":r"\bbalanc","stratification":r"stratif","kernel":r"\bkernel","do":r"\bdo-",
"cause":r"\bcaus(e|es|ed|ing)\b","causal":r"\bcausal\b",
}
R={k:re.compile(v,re.I) for k,v in T.items()}
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
P={k:collections.defaultdict(set) for k in T}; C={k:collections.Counter() for k in T}
for pid,t in con.execute("select paper_id,text from chunks"):
    l=lab.get(pid,"?")
    for k,r in R.items():
        if r.search(t): P[k][l].add(pid); C[k][l]+=1
print("term\ton_papers\toff_papers\tbord_papers\ton_chunks\toff_chunks")
for k in T: print(k,len(P[k]["on"]),len(P[k]["off"]),len(P[k]["borderline"]),C[k]["on"],C[k]["off"],sep="\t")
