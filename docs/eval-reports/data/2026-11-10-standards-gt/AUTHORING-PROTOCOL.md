# Standards-corpus ground truth — authoring protocol

Frozen 2026-11-10, before any item was authored and before any retrieval output existed for this
corpus (the retrieval services were down for the whole authoring window, so authoring is blind to
retrieval by construction).

Corpus: `av_standards` — 119 documents (standards, regulations, guidance, reports, slides, 10 books).
DB (read-only): `/home/omar/ai-projects/research-system-rag-standards/data/papers.db`.

## Hard rules

1. **Read-only.** Touch the corpus only through `gt_tools.py` in this directory (or your own
   `mode=ro` SQLite queries). Never write to any `papers.db`, never start services, never use a GPU.
2. **Write only inside your own author directory.** Nothing else in the repo. No git commits.
3. **Author from the document text, never from memory.** Every answerable item is grounded in a
   passage you actually read via `gt_tools.py chunks`. If the corpus text and your memory of a
   standard disagree, the corpus text wins.
4. **`passage_excerpt` is verbatim** — 1 to 3 sentences copied exactly from ONE chunk whose body (the text under
   its title/section header) is at least 60 characters. It must contain the answer. Never pick a heading-only chunk.
5. **The question must not copy the excerpt.** No run of 6+ consecutive words shared with the
   excerpt. Paraphrase, as a real user would ask it.
6. **Questions are self-contained.** Name the standard/document when a real user would (most
   strata). Do not write "according to the passage".
7. **You supply `source_paper_id` + `passage_excerpt`; the tool fills in chunk and block ids.** Do
   not invent ids. Run `python gt_tools.py verify <your file> --write` until it reports 0 failures.
8. **Kill, don't bend.** If an item cannot pass verification honestly, drop it and note it in your
   log. Fewer honest items beat more shaky ones.
9. Prefer seeding from real user intent: `logged_queries.json` holds 242 queries actually asked of
   this corpus. When an item is inspired by one, record it in `seed_query`.

## Strata (`dimension`)

| dimension | what it tests | gold |
|---|---|---|
| `clause-lookup` | question names a clause/section number or title of a standard | the chunk of that clause |
| `definition-lookup` | "how does X define Y" | the definition text (not a bare term number) |
| `table-requirement` | a requirement, threshold, level or table cell (ASIL, PMHF, severity classes, shall-statements) | the chunk carrying the value |
| `guidance-factual` | factual lookup in a regulation, best practice, report or slide deck | one passage |
| `authority` | question asks what a *standard itself* requires where commentary/slides on the same topic also exist in the corpus | the normative document; list the commentary docs in `commentary_paper_ids` |
| `edition` | a fact that differs between two editions held in the corpus, question names the edition | the named edition; list the other in `other_edition_paper_ids` |
| `book-passage` | a specific point made in one of the 10 books | one passage |
| `cross-document` | answer needs passages from 2+ documents (comparison or synthesis) | `supporting_passages` |
| `partial-absent` | the document exists but the specific thing asked for is not in it (wrong part number, a clause that does not exist, a value it never states) | none |
| `absent` | topic not covered anywhere in the corpus, but plausible for this corpus | none |

## Item shape

Answerable, single document:

```json
{
 "question_id": "Q-STD-A-001",
 "tests": "answerable",
 "dimension": "table-requirement",
 "difficulty": "easy | medium | hard",
 "question_type": "Fact-Lookup | Definition | Requirement | Comparison | Procedure | Rationale",
 "source_paper_id": "local:...",
 "source_paper_title": "...",
 "section_path": "as shown by gt_tools",
 "question_text": "...",
 "passage_excerpt": "verbatim",
 "answer_text": "short correct answer, supported by the excerpt alone",
 "seed_query": "optional, from logged_queries.json",
 "commentary_paper_ids": ["authority items only"],
 "other_edition_paper_ids": ["edition items only"]
}
```

Cross-document — NO top-level `source_paper_id`:

```json
{"question_id": "...", "tests": "answerable", "dimension": "cross-document", "...": "...",
 "supporting_passages": [
   {"paper_id": "local:...", "passage_excerpt": "verbatim"},
   {"paper_id": "local:...", "passage_excerpt": "verbatim"}]}
```

Absent / partial-absent — no gold at all, `tests: "absent"`:

```json
{"question_id": "...", "tests": "absent", "dimension": "absent", "...": "...",
 "answer_text": "Not in the corpus: <one line on why>",
 "absence_evidence": [
   {"pattern": "regex you scanned", "hits": 0},
   {"pattern": "second, broader regex", "paper_id": "optional scope", "hits": 3,
    "note": "the 3 hits are about something else: ..."}],
 "nearest_distractor_paper_id": "the document most likely to be wrongly returned"}
```

Every `absence_evidence` scan is re-run by the verifier and its hit count must reproduce exactly
(`hits` = number of chunks matching, as printed by `gt_tools.py scan`). Use at least two scans, one
of them broad. Non-zero hits are fine if you read them and they do not answer the question — say so
in `note`.

## Output

`author-<X>/items.json` = `{"_metadata": {...author, model, date, counts per dimension...},
"ground_truth": [ ...items... ]}` and `author-<X>/authoring-log.md` (what you covered, what you
killed and why, anything odd you noticed about the corpus text — parsing damage, duplicated
documents, stub chunks; these observations are valuable).

Difficulty mix target: roughly 30% easy / 50% medium / 20% hard. Spread items across your assigned
documents; no more than 3 items from any one document unless your brief says otherwise.
