"""Read-only CPU: recount main-corpus chunks over 4096 Qwen3 tokens; compare with the stored id list.
Reports the count under both measure.py's rule (n>4096) and a >= variant, and the diff vs the list."""
import sqlite3, sys
from tokenizers import Tokenizer
TOK="/home/omar/docker-volumes/tei-data-hf/models--Qwen--Qwen3-Embedding-4B/snapshots/5cf2132abc99cad020ac570b19d031efec650f2b/tokenizer.json"
DB="/home/omar/ai-projects/research-system-rag-data/papers.db"
LIST="/home/omar/ai-projects/research-system-rag/.claude/worktrees/EP-programme-20261110/docs/eval-reports/data/2026-11-10-truncation-rechunk/truncated_chunk_ids_main.txt"
tk=Tokenizer.from_file(TOK); tk.no_truncation(); tk.no_padding()
c=sqlite3.connect(f"file:{DB}?mode=ro",uri=True)
rows=c.execute("select chunk_id,text,paper_id from chunks where length(text)>3500").fetchall()
n={cid:len(tk.encode(t,add_special_tokens=False).ids) for cid,t,_ in rows}
gt={k for k,v in n.items() if v>4096}; ge={k for k,v in n.items() if v>=4096}
lst=set(open(LIST).read().split())
print("tokenized",len(rows),"n>4096",len(gt),"n>=4096",len(ge),"list",len(lst))
print("in list not >4096:",sorted(lst-gt)); print("in >4096 not list:",sorted(gt-lst))
print("exactly 4096 tokens:",[k for k,v in n.items() if v==4096])
print("chars<=3500 rows total",c.execute("select count(*) from chunks where length(text)<=3500").fetchone())
print("chunk_ids by paper dt:",c.execute("select count(*) from chunks").fetchone())
