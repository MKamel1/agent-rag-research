import re,sqlite3,collections
P=r"""Hodrick.Prescott
Nerlove
Lewbel
Baron.Kenny
Tinbergen|Haavelmo|Cowles
Wright.s path|path analysis
tetrad
John Snow|cholera
Semmelweis|scurvy|tasting tea
Hausman
time.invariant
system GMM|difference GMM|dynamic panel
Arellano
long.run restriction
structural VAR|SVAR
postulates?
germ theory|pathogen
local linear matching|kernel matching
Heckman
multilevel|hierarchical model
Coase|Pigou|externalit
Stuart Mill|John Stuart
instrumental variable.*(telescope|detector|spectrograph)
glitch
Hubble.*(causal|instrument)""".split("\n")
rx=[re.compile(p,re.I) for p in P]
lab={l.split("\t")[0]:l.split("\t")[1] for l in open("../2026-11-10-topic-labels/topic_labels.tsv")}
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
C=collections.Counter();L=collections.defaultdict(collections.Counter)
for pid,t in con.execute("select paper_id,text from chunks"):
    for p,r in zip(P,rx):
        if r.search(t): C[p]+=1; L[p][lab.get(pid,"?")]+=1
for p in P: print(p,C[p],dict(L[p]),sep="\t")
