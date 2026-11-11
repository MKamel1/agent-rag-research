# Embed-path truncation investigation (2026-11-10)

**Verdict: truncation HAPPENS, silently.** Every embedded text is cut to 4,096 tokens by TEI (`auto_truncate: true`, max-batch-tokens 4096); the client never sends `truncate` and nothing is rejected, logged or retried.
Verified from the container's own startup log (its effective-limit warning), not from a live request; the container is exited and the GPU busy.
One command to settle it live when the GPU is free: `python measure_live.py`-equivalent, i.e. start `rag-tei-embed`, then `curl -s localhost:<port>/info | jq '.max_input_length,.auto_truncate'` and POST `/embed` twice with `{"inputs":[T]}` and `{"inputs":[T[:N]]}` where T is a 40k-char text and N the char offset of token 4096; cosine == 1.0 (and HTTP 200, not 413) confirms silent truncation.

## Evidence

1. Client sends no truncate flag: `rag/embedder.py:159` is `self._client.post("/embed", json={"inputs": batch})`. grep for `truncate` in rag/embedder.py: no hits. grep for `auto-truncate|max-batch-tokens` in app/, rag/, config*: no hits in code (launch flags live only in the container definition). Adapter only classifies 429/5xx as transient, other 4xx as `PermanentError` (embedder.py:152-168); there is no split/quarantine-on-length path, and none is needed because TEI never returns 413/422 for length here.
2. Container args (`docker inspect rag-tei-embed`): `["--model-id","Qwen/Qwen3-Embedding-4B","--max-batch-tokens","4096"]`; no `--auto-truncate` flag, bind mount /home/omar/docker-volumes/tei-data-hf.
3. Container log (`docker logs rag-tei-embed`, repeated each start; line from 2026-07-16):
   `The maximum input length is 40960 which exceeds --max-batch-tokens=4096. Input sequences will be truncated to 4096 tokens, as --auto-truncate is either not provided (defaults to true) or provided as true.` and `Maximum number of tokens per request: 4096`. Args dump: `max_batch_tokens: 4096, max_client_batch_size: 32, auto_truncate: true`. (The model max is 40,960; the effective cap is the batch budget.)
4. Effective per-input limit: **4,096 tokens** (TEI caps a single input at max-batch-tokens; confirmed by the log text above rather than by the docs). Note the model could take 40,960; the 4096 flag is the binding limit, so raising `--max-batch-tokens` is the lever.
5. Ingest logs (/home/omar/ai-projects/research-system-rag-data/*.log): grep hits for "413"/"truncat" are noise (MinerU page counters like `413/684`, summarizer "truncating to the first 7356 words"). No `embedding server returned 413/422` line anywhere (grep -c = 0 for that phrase). Consistent with silent truncation: no oversize ever errored. Inferred: the absence of errors is expected, not proof of absence of truncation.
6. Embedded text is raw `chunk.text` (rag/orchestrator.py:675, `[c.text for c in chunks]`), no header prepended, so all of chunk.text beyond 4096 tokens is lost from the vector. Chunk text stays complete in the DB (used for display and the reranker).

## Method (verified)
CPU only, read-only DBs (`mode=ro`). Tokenizer: the real Qwen3-Embedding-4B `tokenizer.json` from the TEI volume (tokenizers 0.22.2). ALL chunks > 3,500 chars were tokenized exactly (not just >6,000); a random sample of 5,000 chunks <= 3,500 chars per corpus had 0 over 4,096 tokens. Special tokens ignored (+1 or 2 tokens; immaterial). Script: `measure.py`; raw output: `results.json`.

## Exposure (limit 4,096 tokens)

| Corpus | Chunks | > 8,000 chars | Chunks > 4096 tok (truncated) | % of chunks | Chars cut / total chars | Median fraction cut per affected chunk |
|---|---|---|---|---|---|---|
| main (research-system-rag-data) | 399,676 | 8,487 | **3,138** | 0.79% | 16.3M / 1,080M = **1.51%** | 24% |
| waymo | 47,771 | 845 | **126** | 0.26% | 0.38M / 99.5M = 0.39% | 19% |
| standards | 35,714 | 0 | **0** | 0% | 0 | n/a |

Most >8,000-char chunks still fit (tables/numbers are token-dense at ~3.0 chars/token median in main, so 4,096 tokens is ~12k chars of such text; prose ~4 chars/token ~16k chars). Median chars/token among tokenized chunks: main 2.99, waymo 4.11.

## What is oversized (main)
- doc_type: 3,135 papers, 3 books (nothing else exists in the corpus).
- Kind of the 3,138: table-heavy (>50 `|`) 1,861 (59%); equation-heavy (>100 `$`) 662 (21%); reference-list-like by a weak citation-regex 71 (undercount; see below).
- >30,000 chars: 91 chunks in 80 papers; 89 of 91 are table-dominated (median 11% of characters are `|`). Section names include REFERENCES x9 and References x9 (18 reference lists glued into one chunk), appendices, "Supplementary Tables", coefficient tables. This is a parsing/chunking failure (whole tables or whole reference sections emitted as a single chunk by the older chunker), not whole documents. Chunker now bounds chunks (`rag/chunker.py:23-24`, `_MAX_CHUNK_WORDS=220`, `_MAX_CHUNK_CHARS=1200`; commit 2026-11-01 "repair ... oversized table chunks"); the standards corpus, built with it, has 0 oversized.
- Top 10 largest (paper_id, section_path, chars, tokens):
  1. 2607.07980, APPENDIX 6 SUPPLEMENTARY DOCUMENT INDEX, 709,987, 266,029
  2. 1208.4360, REFERENCES, 472,146, 384,805
  3. 2602.07915, "T Figure results aggregated over all hyperparameters", 194,403, 128,974
  4. 2012.00370, B Covariates, 132,613, 88,518
  5. 2208.00114, Supplementary Tables, 105,676, 70,111
  6. 2212.07379, A.3 Local average treatment efects for each DGP, 99,261, 67,023
  7-10: see `results.json` -> main.top10.
  Of the max chunk, 710k chars -> only the first ~1.5% is embedded.
- Waymo: top is a REFERENCES chunk of 31,460 chars (14,925 tokens); only 1 chunk > 30k.

## Query-time (reranker)
rag/reranker.py:75-78 caps each document at `_MAX_ITEM_TOKENS * 3 = 24,000` chars client-side, then TEI truncates the (query, doc) pair at its own `max_input_length` 8,192 (cited from `/info` in the comment at reranker.py:55; not re-verified live). Measured with the real Qwen tokenizer (the reranker uses an XLM-R tokenizer, so token counts here are approximate): main 556 chunks exceed 8,192 tokens or 24,000 chars, losing ~6.2M chars; waymo 12 chunks, ~57k chars. So the reranker sees more than the embedder for chunks of 4,096-8,192 tokens (~2,580 main chunks): their tail is invisible to dense retrieval but visible to rerank, only if the chunk is retrieved via its head or other signals. Beyond 8,192 tokens, both stages are blind to the tail. The reranker's truncation is declared and lossless-by-design in its comment; the embedder's is not declared anywhere (scripts/truncation_census.py does not cover it).

## Verified vs inferred
- Verified: container flags, TEI log line, `auto_truncate: true`, client request body, tokenized counts (exact, real tokenizer), no 413/422 in ingest logs.
- Inferred: that every historical embedding was produced under the same flags (logs show these flags from 2026-07-16 on; earlier ingests are not in the container log); reranker figures use the wrong tokenizer family.
- Not verified: live HTTP behaviour (service down).

## Options, cheapest first
1. **Re-chunk only the oversized chunks** with the bounded chunker (<=1,200 chars) and re-embed just those pieces: 3,138 main + 126 waymo chunks become roughly 15-20k small chunks (main: ~16M chars lost to cover at 1.2k each = few thousand to ~20k chunks); a few minutes of GPU. Needs a targeted op (replace chunk rows, update vector store, FTS). Cheapest in compute; moderate in code.
2. Drop/flag the pathological chunks (89 table-dominated >30k, 18 reference lists) from retrieval: nearly free, reduces noise, but loses table content.
3. Raise `--max-batch-tokens` to 16384 or 40960 with `--auto-truncate false` so nothing is silently cut: config only, but VRAM-heavier, and the 710k-char chunks would then 413 (adapter treats as PermanentError, quarantining papers); only useful after option 1.
4. Add an embedder-side guard/log: count chunks over ~12k chars at embed time and add the embedder to truncation_census.py, so it cannot recur silently.
5. Full re-ingest with the new chunker for the main corpus: highest cost, only if you want all of the older chunk boundaries fixed.
