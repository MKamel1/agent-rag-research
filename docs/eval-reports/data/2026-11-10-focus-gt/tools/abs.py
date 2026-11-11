import re,sqlite3,collections
P=r"""Hausman.Taylor
Blundell.Bond
Arellano.Bond
Ashenfelter
Mundlak
Hodges.Lehmann
Fama.MacBeth
Berry.Levinsohn|\bBLP\b
Stock.Yogo
Lord.s paradox
Tobit
Durbin.Wu|Wu.Hausman
Sargan
Hansen.s J|J.test of overidentif
Kitagawa
Rosenbaum bounds
design sensitivity
Oster
Altonji
Conley bounds|plausibly exogenous
Bartik|shift.share
judge.?leniency|examiner design
Lee bounds
Manski
Wald.Wolfowitz
Fisher.s exact test
Mantel.Haenszel
Cochran.Mantel
Peters.Clark
Hodges
Neyman.Pearson
Gelman.Hill
Nevo
quantile treatment ef+ect
Bonferroni
Benjamini.Hochberg
Tukey
Wilcoxon
Kaplan.Meier
Cox proportional hazards
Fine.Gray
frailty
stepped.wedge
crossover trial|cross-over trial
cluster.randomi[sz]ed trial
factorial design
Latin square
split.plot
Taguchi
fractional factorial
Plackett.Burman
response surface
sequential probability ratio
alpha.spending|group sequential
Thompson sampling
Gittins
Kelly criterion
Pigou
Coase
Lucas critique
Phillips curve
Taylor rule
Granger.Newbold|spurious regression
Johansen
cointegrat
Engle.Granger
Dickey.Fuller
vector error correction
Hamilton filter
Kalman
GARCH
Diebold.Mariano
local projections?
Jorda
Cholesky
sign restrictions
narrative identification
proxy.SVAR|external instruments? SVAR
Romer
Blanchard.Quah
heteroscedasticity.based identification
Rigobon
Sims
Chetty
Autor
Card.Krueger
Angrist.Krueger
Lalonde
Dehejia.Wahba
Heckman.Ichimura
Imbens.Rubin
Pearl.s causal hierarchy
Reichenbach
common cause principle
Salmon
Lewis.s counterfactual|possible world semantics
Mill.s methods
Bradford Hill
Koch.s postulates
Rothman.s pie|sufficient.component cause
Hume
Kant
Simpson.s paradox
Berkson
Neyman.s paradox
Lindley
Stein.s paradox
Monty Hall
Newcomb
Sleeping Beauty
trolley
Gettier""".split("\n")
rx=[re.compile(p,re.I) for p in P]
lab={l.split("\t")[0]:l.split("\t")[1] for l in open("../2026-11-10-topic-labels/topic_labels.tsv")}
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
C=collections.Counter();L=collections.defaultdict(collections.Counter)
for pid,t in con.execute("select paper_id,text from chunks"):
    for p,r in zip(P,rx):
        if r.search(t): C[p]+=1; L[p][lab.get(pid,"?")]+=1
for p in P: print(p,C[p],dict(L[p]),sep="\t")
