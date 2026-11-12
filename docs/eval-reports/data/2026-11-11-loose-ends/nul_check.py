"""Read-only CPU: chunks whose python len(text) > 3500 but SQL length(text) <= 3500 (embedded NUL), tokenised."""
import sqlite3
from tokenizers import Tokenizer
TOK="/home/omar/docker-volumes/tei-data-hf/models--Qwen--Qwen3-Embedding-4B/snapshots/5cf2132abc99cad020ac570b19d031efec650f2b/tokenizer.json"
tk=Tokenizer.from_file(TOK); tk.no_truncation(); tk.no_padding()
c=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
tot=0; sel=0; over=[]
for cid,t in c.execute("select chunk_id,text from chunks"):
    tot+=len(t)
    if len(t)>3500:
        sel+=1
        if len(t.encode()) and "\x00" in t and len(tk.encode(t,add_special_tokens=False).ids)>4096: over.append((cid,len(t),t.index("\x00")))
print("python chars_total",tot,"python len>3500",sel); print("NUL chunks over 4096 tokens",over)
