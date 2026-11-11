import sqlite3,sys
con=sqlite3.connect("file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro",uri=True)
L=int(sys.argv[1])
for cid in sys.argv[2:]:
    r=con.execute("select chunk_id,paper_id,text from chunks where chunk_id=?",(cid,)).fetchone()
    if not r: print("NOCHUNK",cid);continue
    t=r[2].replace("\n"," ")
    print(f"=== {r[0]}\n{t[:L]}\n")
