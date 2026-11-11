import re,sqlite3,json
PAIRS=[(r"Hausman.{1,8}Taylor",r"Hausman"),(r"Blundell.{1,8}Bond",r"system GMM|difference GMM|dynamic panel"),
(r"Blanchard.{1,8}Quah",r"long.run restriction"),(r"Koch.{0,3}s? postulates?|Henle.Koch",r"postulates?"),
(r"Heckman.{1,30}Ichimura",r"local linear matching|kernel matching"),(r"Gelman.{1,8}Hill",r"multilevel|hierarchical model"),
(r"instruments?.{0,80}(telescope|detector|spectrograph)",r"\binstruments?\b"),(r"Coase",r"externalit"),
(r"Imbens.{1,8}Rubin",r"potential outcome"),(r"Neyman.s paradox",r"paradox")]
lab={l.split("\t")[0]:l.split("\t")[1] for l in open("../2026-11-10-topic-labels/topic_labels.tsv")}
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
R=[(re.compile(a,re.I),re.compile(b,re.I)) for a,b in PAIRS]
cnt=[[0,0,None] for _ in PAIRS]
for cid,pid,t in con.execute("select chunk_id,paper_id,text from chunks"):
    for i,(a,b) in enumerate(R):
        if a.search(t): cnt[i][0]+=1; print("SPEC HIT",i,cid,t[:100].replace("\n"," "))
        if b.search(t):
            cnt[i][1]+=1
            if cnt[i][2] is None and lab.get(pid)=="off" and len(t)>500: cnt[i][2]=cid
for p,c in zip(PAIRS,cnt): print(p,c)
