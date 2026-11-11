"""Read-only embed-truncation exposure. CPU only. Usage: python measure.py"""
import json, re, sqlite3, random, statistics as st
from tokenizers import Tokenizer
TOK="/home/omar/docker-volumes/tei-data-hf/models--Qwen--Qwen3-Embedding-4B/snapshots/5cf2132abc99cad020ac570b19d031efec650f2b/tokenizer.json"
DBS={"main":"/home/omar/ai-projects/research-system-rag-data/papers.db",
 "waymo":"/home/omar/ai-projects/research-system-rag/waymo/data/papers.db",
 "standards":"/home/omar/ai-projects/research-system-rag-standards/data/papers.db"}
EMBED=4096; RERANK=8192; RR_CLIENT_CHARS=8000*3
tk=Tokenizer.from_file(TOK); tk.no_truncation(); tk.no_padding()
THRESH=3500  # tokenize all chunks above this many chars exactly; 4096 tok at <0.85 chars/tok is impossible
def cut(text,limit):
    e=tk.encode(text,add_special_tokens=False); n=len(e.ids)
    if n<=limit: return n,0
    return n,len(text)-e.offsets[limit-1][1]
out={}
for name,p in DBS.items():
    c=sqlite3.connect(f"file:{p}?mode=ro",uri=True)
    rows=c.execute("select c.chunk_id,c.paper_id,c.section_path,c.text,coalesce(p.doc_type,'?') from chunks c left join papers p using(paper_id)").fetchall()
    tot=len(rows); big=[r for r in rows if len(r[3])>THRESH]
    small=[r for r in rows if len(r[3])<=THRESH]
    random.seed(0); samp=random.sample(small,min(5000,len(small)))
    samp_over=sum(cut(r[3],EMBED)[0]>EMBED for r in samp)
    res=[]
    for cid,pid,sp,t,dt in big:
        n,lost=cut(t,EMBED); n2,lost2=cut(t,RERANK)
        res.append(dict(cid=cid,pid=pid,sp=sp,dt=dt,chars=len(t),tok=n,over=n>EMBED,lostc=lost,rr_over=n>RERANK,rr_lostc=max(lost2,len(t)-RR_CLIENT_CHARS if len(t)>RR_CLIENT_CHARS else 0),
          dollar=t.count("$"),pipe=t.count("|"),refs=len(re.findall(r"\[\d+\]|\(\d{4}\)",t)),
          cpt=len(t)/max(n,1)))
    ov=[r for r in res if r["over"]]
    tchars=sum(len(r[3]) for r in rows)
    d=dict(chunks=tot,chars_total=tchars,tokenized_exact=len(big),sample_small_over=f"{samp_over}/{len(samp)}",
      over_4096=len(ov),over_4096_pct=100*len(ov)/tot,chars_lost=sum(r["lostc"] for r in ov),chars_lost_pct=100*sum(r["lostc"] for r in ov)/tchars,
      median_lost_frac_of_oversized=st.median([r["lostc"]/r["chars"] for r in ov]) if ov else None,
      over_8192_rerank=sum(r["rr_over"] or r["rr_lostc"]>0 for r in res),rr_chars_lost=sum(r["rr_lostc"] for r in res),
      chars_gt_8000=sum(len(r[3])>8000 for r in rows),chars_gt_30000=sum(len(r[3])>30000 for r in rows),
      chars_per_token_median_big=st.median([r["cpt"] for r in res]) if res else None,
      by_doc_type={},
      kinds=dict(table_heavy=sum(r["pipe"]>50 for r in ov),eq_heavy=sum(r["dollar"]>100 for r in ov),ref_like=sum(r["refs"]>40 for r in ov)),
      top10=[{k:r[k] for k in("pid","sp","chars","tok","dt","dollar","pipe","refs")} for r in sorted(res,key=lambda r:-r["chars"])[:10]],
      gt30k=[dict(pid=r["pid"],sp=r["sp"][:80],chars=r["chars"],pipe=r["pipe"],dollar=r["dollar"],refs=r["refs"]) for r in res if r["chars"]>30000][:200])
    for r in res:
        b=d["by_doc_type"].setdefault(r["dt"],dict(n_big=0,over=0)); b["n_big"]+=1; b["over"]+=r["over"]
    d["gt30k_summary"]=dict(n=len([r for r in res if r["chars"]>30000]),
        distinct_papers=len({r["pid"] for r in res if r["chars"]>30000}),
        table_heavy=sum(r["pipe"]>200 for r in res if r["chars"]>30000),
        pipe_per_char_median=st.median([r["pipe"]/r["chars"] for r in res if r["chars"]>30000] or [0]))
    from collections import Counter
    d["gt30k_section_top"]=Counter(r["sp"].split(" > ")[0][:40] for r in res if r["chars"]>30000).most_common(8)
    out[name]=d
json.dump(out,open(__file__.replace("measure.py","results.json"),"w"),indent=1,default=str)
for k,v in out.items(): print(k,{x:v[x] for x in v if x not in("top10","gt30k")})
