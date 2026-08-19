"""Standing check: does `author_org_curated_only` actually exclude non-Waymo papers?

Run against the LIVE corpus (needs Qdrant + TEI up and `app.doctor` OK) -- it is deliberately not a
pytest test, because it asserts against real ingested data, not fixtures.

This exists because the failure it catches was invisible for 10 days: the corpus held every Waymo
paper, every filter code path was unit-tested and correct, and yet `papers.author_orgs` was NULL on
all 1,741 rows and no Qdrant point carried `curated_author_orgs` -- so every org-filtered query
silently returned nothing relevant. Unit tests could not see it; only a query against real data can.
Re-run after any ingest, and after `scripts/backfill_curated_author_orgs.py`.

    python scripts/verify_curated_filter.py     # exits nonzero on a leak
"""
import asyncio, json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT="/home/omar/ai-projects/research-system-rag"; DATA=ROOT+"/waymo/data"
PY_BIN="/home/omar/miniconda3/envs/agent-rag-research/bin/python"
CUR={l.strip() for l in open(ROOT+"/fixtures/waymo/waymo_authored_ids.txt") if l.strip()}

QUERIES=["deep reinforcement learning policy training",
         "pedestrian detection neural network architecture",
         "driver behavior modeling and human factors",
         "lidar point cloud semantic segmentation",
         "safety case assurance argument"]

async def main():
    p=StdioServerParameters(command=PY_BIN,args=["-m","app.serve","--data-dir",DATA],
        env={"PYTHONPATH":ROOT,"PATH":"/usr/bin:/bin"},cwd=ROOT)
    async with stdio_client(p) as (r,w):
        async with ClientSession(r,w) as s:
            await s.initialize()
            total_f=total_u=leaks=0
            for q in QUERIES:
                ru=await s.call_tool("semantic_search",{"query":q,"k":25})
                du=json.loads(ru.content[0].text)
                uids=[(x.get("anchor") or {}).get("paper_id") for x in du["results"]]
                u_non=[i for i in uids if i not in CUR]

                rf=await s.call_tool("semantic_search",{"query":q,
                    "filters":{"author_org":"Waymo","author_org_curated_only":True},"k":25})
                df=json.loads(rf.content[0].text)
                fids=[(x.get("anchor") or {}).get("paper_id") for x in df["results"]]
                f_non=[i for i in fids if i not in CUR]

                total_u+=len(uids); total_f+=len(fids); leaks+=len(f_non)
                print(f"{q[:44]:46s} unfiltered={len(uids):3d} (non-Waymo {len(u_non):3d}) | "
                      f"curated-only={len(fids):3d} (LEAKS {len(f_non)})")
                if f_non: print("    !! LEAKED:", f_non[:6])
            print(f"\nTOTAL: unfiltered {total_u} hits | curated-only {total_f} hits | "
                  f"non-Waymo leaks under filter: {leaks}")
            assert leaks==0, "FILTER IS BROKEN -- non-curated papers leaked through"
            print("PASS: every curated-only hit is on the Waymo curated list.")

            # And the filter must not be a no-op that just returns everything.
            rf=await s.call_tool("search_papers",{"query":"autonomous vehicle safety",
                "filters":{"author_org":"Waymo","author_org_curated_only":True},"k":50})
            ids={x["view"]["paper_id"] for x in json.loads(rf.content[0].text)["results"]}
            ru=await s.call_tool("search_papers",{"query":"autonomous vehicle safety","k":50})
            uids={x["view"]["paper_id"] for x in json.loads(ru.content[0].text)["results"]}
            print(f"\nsearch_papers k=50: curated-only returned {len(ids)} papers, "
                  f"unfiltered {len(uids)}; unfiltered non-Waymo = {len(uids-CUR)}")
            assert ids <= CUR, "search_papers leaked non-curated"
            assert uids-CUR, "unfiltered returned only Waymo -- query too narrow to prove anything"
            print("PASS: search_papers honours the filter, and the unfiltered query really does "
                  "contain non-Waymo papers (so the filter is doing work).")
asyncio.run(main())
