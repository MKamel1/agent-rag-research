# ruff: noqa  (one-off corpus scan; output saved as scans/ev4b_batch.out)
import re,sqlite3,collections,sys
LAB="/home/omar/ai-projects/research-system-rag/.claude/worktrees/EP-EV4b-focus-fixes/docs/eval-reports/data/2026-11-10-topic-labels/topic_labels.tsv"
lab={l.split("\t")[0]:l.split("\t")[1] for l in open(LAB) if l.count("\t")>=2}
ABS={
"BQ_refined_noLR_effect":r"(Blanchard.{1,8}Quah|long.run restrictions?).{0,400}(no|zero|neither|not have).{0,60}(long.run|permanent|cumulative).{0,60}(output|GDP)",
"BQ_demand_transitory":r"(demand|transitory|temporary).{0,80}(no|zero|do not have|does not have).{0,40}(long.run|permanent).{0,40}(effect|impact)",
"BQ_name":r"Blanchard.{1,8}Quah",
"Neyman_paradox":r"Neyman.{0,3}s? paradox|paradox.{0,60}Neyman",
"settler_mortality":r"settler mortality|Acemoglu.{0,40}Johnson.{0,40}Robinson",
"quarter_of_birth":r"quarter.of.birth|Angrist.{0,10}Krueger",
"Oregon_HIE":r"Oregon health insurance|Oregon Medicaid|Oregon Health",
"MTO":r"Moving to Opportunity",
"STAR":r"Tennessee STAR|Project STAR|STAR experiment",
"Hirshleifer_sunshine":r"Hirshleifer|sunshine",
"Oaxaca":r"Oaxaca|Blinder",
"Mantel":r"Mantel.Haenszel|Cochran.Mantel",
"Kitagawa":r"Kitagawa",
"Card_Krueger":r"Card.{0,6}Krueger",
"minwage":r"minimum wage",
"kink":r"regression kink|kink design|\bRKD\b",
"Rosenbaum_bounds":r"Rosenbaum bounds?",
"Roy_model":r"\bRoy model",
"Lalonde":r"LaLonde|Dehejia",
"Stein_paradox":r"Stein.s paradox",
"Uhlig":r"Uhlig",
"Sims_Zha":r"Sims.{0,6}Zha",
"Lee_bounds":r"Lee.{0,3}s? bounds",
"Heckman_two_step":r"Heckman.{0,20}(two.step|correction)",
"Hausman_spec":r"Hausman (specification )?test",
"Bartik":r"Bartik|shift.share",
"galaxy_causal":r"galax.{0,300}(propensity|instrumental variable|regression discontinuity|difference.in.dif+erences?)",
"Wald_ratio":r"Wald (ratio|estimator)",
"Fama_French":r"Fama.French",
"Granger_Sims":r"Sims.{0,10}(causality|exogeneity)",
"Cholesky_ordering":r"Cholesky",
"Jorda_LP":r"local projections?",
"Cragg_Donald":r"Cragg.Donald",
"Anderson_Rubin":r"Anderson.Rubin",
"Sargan":r"Sargan",
"Nickell":r"Nickell",
"Arellano_Bond":r"Arellano.Bond",
"Hansen_Hurwitz":r"Hansen.Hurwitz|Horvitz.Thompson",
"Manski_bounds":r"Manski",
"Pearl_frontdoor":r"front.?door",
"Cinelli_Hazlett":r"Cinelli.{0,10}Hazlett|robustness value",
"Imai_Kim":r"Imai.{0,6}Kim",
"two_way_FE_decomp":r"Goodman.Bacon",
"Callaway_SantAnna":r"Callaway.{0,10}Sant",
"Sun_Abraham":r"Sun.{0,6}Abraham",
"vaccine_trial_cluster":r"ring vaccination",
"smallpox":r"smallpox",
"Snow_cholera":r"cholera|John Snow",
"Semmelweis":r"Semmelweis",
"Bradford_Hill":r"Bradford.Hill",
"Doll_Hill_smoking":r"Doll.{0,10}Hill|lung cancer",
"Cornfield":r"Cornfield",
}
OFFTERMS={
"mediation":r"\bmediation\b",
"propensity":r"propensity",
"intervention":r"\binterventions?\b",
}
R={k:re.compile(v,re.I|re.S) for k,v in ABS.items()}
O={k:re.compile(v,re.I) for k,v in OFFTERMS.items()}
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
cnt=collections.Counter(); ex=collections.defaultdict(list); off=collections.defaultdict(list)
for cid,pid,t in con.execute("select chunk_id,paper_id,text from chunks"):
    for k,r in R.items():
        if r.search(t):
            cnt[k]+=1
            if len(ex[k])<6: ex[k].append(cid)
    if lab.get(pid)=="off":
        for k,r in O.items():
            m=r.search(t)
            if m and len(off[k])<60 and pid not in {c.split(':')[0] for c,_ in off[k]}:
                off[k].append((cid,t[max(0,m.start()-70):m.end()+70].replace("\n"," ")))
print("### ABSENT-CANDIDATE COUNTS (chunks)")
for k in ABS: print(f"{cnt[k]:6d} {k} {ex[k] if cnt[k]<=6 else ''}")
print("### OFF-LABELLED SAMPLES (one chunk per paper)")
for k in off:
    print("##",k)
    for c,s in off[k]: print(" ",c,"|",s)
