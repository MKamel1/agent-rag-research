import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
import t1, t2, t3
T = t1.T
REPO = "/home/omar/ai-projects/research-system-rag/.claude/worktrees/EP-EP2-ticket-set"
PLAN = f"{REPO}/docs/superpowers/plans/2026-11-10-enhancement-programme.md"
ISS = f"{REPO}/docs/superpowers/plans/2026-11-10-enhancement-programme-issues"
BACKLOG = f"{REPO}/docs/BACKLOG.md"
ISSREL = "docs/superpowers/plans/2026-11-10-enhancement-programme-issues"
BY = {x["id"]: x for x in T}
EXT_PROGRESS = {"EV-4": "EP-EV4-focus-gt", "CQ-5": "EP-CQ5-standards-metadata", "CQ-4": "EP-CQ4-truncation-rechunk-plan", "EP-1": "EP-EP1-docs-drift"}
SERIAL = ["EV-16", "EV-18", "EV-19", "EV-20", "EV-21", "EV-22", "RQ-3", "CQ-10", "CQ-11", "CQ-15", "CQ-16", "CQ-18"]
serial_pred = {SERIAL[i]: SERIAL[i - 1] for i in range(1, len(SERIAL))}
WAVE_LABEL = {1: "wave:1-no-gpu", 2: "wave:2-gpu-measure", 3: "wave:3-gated-change", 4: "wave:4-rider"}
WAVE_NAME = {1: "W1 do now, no GPU", 2: "W2 first GPU session, measurements only", 3: "W3 gated changes after baselines", 4: "W4 rider and what it unblocks"}
BATCH = {1: "EP-3", 2: "EP-4", 3: "EP-5", 4: "EP-5"}
for x in T:
    x["deps_all"] = list(dict.fromkeys(x["deps"] + ([serial_pred[x["id"]]] if x["id"] in serial_pred else [])))
rev = {i: [] for i in BY}
for x in T:
    for d in x["deps_all"]:
        if d in rev: rev[d].append(x["id"])

def num(i): return "①②③④⑤⑥⑦⑧⑨⑩"[i]
def labels(x):
    L = [WAVE_LABEL[x["wave"]]] + [f"area:{a}" for a in x["area"]]
    if x["gpu"] == "y": L.append("needs-gpu")
    if x["signoff"].startswith("y"): L.append("needs-signoff")
    if not x["services"].startswith("none"): L.append("needs-services")
    L.append(f"size:{x['size']}")
    return L
def pyfiles(x):
    return " ".join(p for p in x["owns"] if p.endswith(".py"))
def std_verify(x):
    v = ['`conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m \'not real_adapter\'"` (zero GPU, zero network; report the summary line)',
         '`EV=$(mktemp) && echo \'{}\' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)']
    if pyfiles(x): v.append(f"`conda run -n agent-rag-research ruff check {pyfiles(x)}`")
    return v
def needs(x):
    q = [e for e in x["ext"] if re.fullmatch(r"F\d", e)]
    so = x["signoff"]
    so_txt = "n (no protected path is touched)" if so == "n" else so
    parts = [f"GPU: {x['gpu']}", f"services up: {x['services']}", f"operator sign-off: {so_txt}"
             + (f"; operator answers: {', '.join(q)}" if q else ""),
             f"re-embed: {x['reembed']}"]
    s = " · ".join(parts)
    if x.get("needs_note"): s += f". Also: {x['needs_note']}."
    return s
def depline(x):
    d = x["deps_all"]
    ext = [e for e in x["ext"] if e in EXT_PROGRESS]
    q = [e for e in x["ext"] if re.fullmatch(r"F\d", e)]
    s = "Depends on: " + (", ".join(d) if d else "none")
    if ext: s += f". In-progress tickets on other branches (merge order or inputs): {', '.join(ext)}"
    if q: s += f". Operator answers: {', '.join(q)}"
    g = rev[x["id"]]
    s += ". Gates: " + (", ".join(g) if g else "nothing further (programme close)")
    return s
def docs_line(x):
    b = BATCH[x["wave"]]
    return (x["docs"] + f" Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; {b} carries those entries from this ticket's merged SHA.") if x["id"] not in ("EP-3","EP-4","EP-5") else x["docs"]

def body(x, h="###"):
    L = []
    L.append(f"**Review cross-reference:** {', '.join(x['s'])}. **Wave:** {WAVE_NAME[x['wave']]}.")
    L.append("")
    L.append(f"**Why.** {x['why']}")
    L.append("")
    L.append("**Scope.**")
    L.append("- In:" + "".join(f"\n  - {i}" for i in x["in_"]))
    L.append("- Out (explicitly):" + "".join(f"\n  - {i}" for i in x["out"]))
    L.append("")
    L.append("**Owns** (files this ticket may touch; anything else is out of bounds):")
    L += [f"- `{p}`" for p in x["owns"]]
    L.append("")
    L.append("**Commits** (① is a stub, committed before any real work):")
    L += [f"{num(i)} {c}" for i, c in enumerate(x["commits"])]
    L.append("")
    L.append("**Verification:**")
    L += [f"- {v}" for v in std_verify(x) + x["verify"]]
    L.append("")
    L.append(f"**Acceptance / falsification criterion.** {x['accept']}")
    L.append("")
    L.append(f"**Gates / depends on.** {depline(x)}.")
    L.append("")
    L.append(f"**Needs.** {needs(x)}")
    L.append("")
    sz = {"S": "S (up to 2 h of agent work)", "M": "M (up to 1 day of agent work)"}[x["size"]]
    L.append(f"**Model tier and size.** {x['tier']}; {sz}." + (" Mechanical work, no judgement calls." if x["tier"] == "Haiku" else " Logic or authoring work; no Opus-level design adjudication is needed."))
    L.append("")
    L.append(f"**Risk and rollback.** {x['risk']}")
    L.append("")
    L.append(f"**Docs to update in the same PR.** {docs_line(x)}")
    return "\n".join(L)

def title_line(x): return f"{x['id']}: {x['title']}"

# ---------------- issue files ----------------
def write_issues():
    os.makedirs(ISS, exist_ok=True)
    for x in T:
        fn = f"{x['id']}-{x['slug']}.md"
        x["file"] = fn
        txt = f"Title: {title_line(x)}\nLabels: {', '.join(labels(x))}\n\n## {x['id']} -- {x['title']}\n\n" + body(x) + "\n"
        open(f"{ISS}/{fn}", "w").write(txt)

def write_index():
    L = ["# Enhancement programme: issue list for operator confirmation", "",
         "Nothing here has been posted to GitHub. Each file below is the body of one proposed issue; the first two lines of each file are the title and labels. "
         "The programme plan is `docs/superpowers/plans/2026-11-10-enhancement-programme.md`. Confirm, strike or change rows, then the list is mirrored. "
         "Tickets already done or in progress on other branches are in the plan (section 7), not here.", "",
         f"{len(T)} issues. Waves: " + ", ".join(f"{WAVE_NAME[w]} = {sum(1 for x in T if x['wave']==w)}" for w in (1,2,3,4)) + ".", "",
         "| id | title | labels | wave | depends on | file |", "|---|---|---|---|---|---|"]
    order = sorted(T, key=lambda x: (x["wave"], x["id"].split("-")[0] != "EP", x["id"]))
    for x in order:
        dep = ", ".join(x["deps_all"] + [e for e in x["ext"] if re.fullmatch(r"F\d|EV-4|CQ-4|CQ-5|EP-1", e)]) or "none"
        L.append(f"| {x['id']} | {x['title']} | {', '.join(labels(x))} | {x['wave']} | {dep} | [{x['file']}]({x['file']}) |")
    L += ["", "Dependency entries of the form F1..F8 are operator questions (plan section 3); EV-4, CQ-4, CQ-5, EP-1 are in-progress tickets on other branches. GPU-serial ordering edges inside wave 2/3 are included in 'depends on'."]
    open(f"{ISS}/INDEX.md", "w").write("\n".join(L) + "\n")

# ---------------- plan ----------------
DONE = [
 ("EP-0", "Programme branch; three ground-truth sets (standards 128 items, causal books 74, paper passages 61); chunk-quality census; corpus audits (off-topic, ligature, embed truncation)", "`0021de1`", "commits `173fe4e` (standards GT), `f119f30` (books GT), `0c9483e` (papers GT), `09cb847` (audits), `368ce55` (census), `17b48ec`, `0021de1`"),
 ("EV-1", "Topic labels for all 12,385 main-corpus papers", "`5f54fb4`", "`docs/eval-reports/data/2026-11-10-topic-labels/`"),
 ("EV-2", "Label audit (weighted kappa 0.90, same model family as the labeller)", "`eb4d993`", "`docs/eval-reports/2026-11-10-topic-labels-audit.md`"),
 ("EV-3", "relevance_score against labels (AUROC 0.923)", "`eb4d993`", "same merge as EV-2; report above"),
 ("EV-5", "Three frozen protocols, run scripts that verify fixture hashes, fixture hashes, GPU-day runbook", "`b9be4c8`", "`docs/eval-reports/2026-11-10-*-benchmark-protocol.md`, `2026-11-10-GPU-DAY-RUNBOOK.md`, `data/2026-11-10-FIXTURE-HASHES.json`"),
 ("EV-6", "Per-stratum evaluation report script", "`c06b411`", "`scripts/eval_strata_report.py`"),
 ("CQ-1", "Ligature repair in the sparse arm (merged, applied to no index)", "`56d24d0`", "`docs/eval-reports/data/2026-11-10-ligature-census/repair-map-report.md`"),
 ("CQ-2", "`VectorIndex.resparse` / `set_payload` and their CLIs", "`655b384`", "`docs/eval-reports/2026-11-10-cq2-index-maintenance.md`"),
 ("CQ-3", "Stub filter (default off) and pre-registered A/B", "`720f77d`", "`docs/eval-reports/2026-11-10-cq3-stub-chunks.md`"),
 ("CQ-6", "Duplicate-document and reference-list census", "`23fc2d2`", "`docs/eval-reports/data/2026-11-10-dup-ref-census/`"),
 ("OP-1", "`doctor --cpu-only` and fail-fast degraded mode", "`564582a`", "`app/doctor.py`"),
 ("RV-1..RV-6", "Six review lanes", "`b4c2b43`, `e796cc9`", "`docs/eval-reports/data/2026-11-10-system-review/`"),
 ("RV-S", "Adjudicated system review (the primary input of this plan)", "`364aa13`", "`docs/eval-reports/2026-11-10-system-review.md`"),
]
INPROG = [("EV-4", "Topic-focus ground truth", "EP-EV4-focus-gt"), ("CQ-5", "Standards metadata (category tags)", "EP-CQ5-standards-metadata"),
          ("CQ-4", "Truncation re-chunk plan", "EP-CQ4-truncation-rechunk-plan"), ("EP-1", "Documentation drift pass over PROJECT-STATUS, README, AGENTS", "EP-EP1-docs-drift")]

TRACE = [
 ("S-01", "No backup since 07-30, none off-device", "OP-4 (snapshot now), OP-3 (quick_check + checksums). Off-device copy and deletions: no ticket until a target exists (F1)"),
 ("S-02", "Eval inputs not frozen", "Folded into EV-5 (done: run scripts verify hashes, no run-time fixture rewrite, run from the worktree under test, point-count guard, protocols and addenda, title-ablation tool); residual EV-7 (required `--collection`, hash in report, gold-id preflight); EV-15 (BM25 floor, the 'EV-5b' of the protocols)"),
 ("S-03", "Chunk-identity scoring ignores alternatives", "EV-8 (excerpt metric), EV-11 (alternatives recorded, hashes re-frozen)"),
 ("S-04", "Cross-encoder score never captured", "EV-13 (capture + census tool), EV-19 (the run)"),
 ("S-05", "CQ-3 pre-registration wrong fixtures, no minimum effect", "EV-12 (addendum); EV-9 (chunk ids in rows, enabler)"),
 ("S-06", "GPU contention unnamed and slow to fail", "OP-5 (holder file, 20 s query path, doctor), EV-10 (eval invalid on lock timeout)"),
 ("S-07", "Wrong-corpus guards cover one path", "OP-6 (helper, tools, doctor, status fallback), OP-2 (the two serve call sites)"),
 ("S-08", "Unknown paper_id returns empty", "MC-1"),
 ("S-09", "Three one-line retrieval defects", "RQ-1"),
 ("S-10", "Cold agent cannot see filters/corpus", "MC-2"),
 ("S-11", "Telemetry blind on scan/get tools", "MC-3"),
 ("S-12", "Containers not reproducible", "OP-7"),
 ("S-13", "Docs drift, chunker provenance, Decision 1", "EP-1 (in progress: PROJECT-STATUS, README, AGENTS rows); EP-6 (CORPORA.md, DECISIONS-PENDING, HANDOFF, precision-95 plan rows, no-ingest rule); EP-3 (BACKLOG rows 1, 5, 6, 17, 18); EP-7 (RUNBOOK sections, row 22)"),
 ("S-14", "rechunk re-embeds unchanged text", "CQ-8"),
 ("S-15", "Filtered dense search without payload indexes", "EV-14"),
 ("S-16", "No baselines, reranker score untested", "EV-16 (main), EV-17 (focus), EV-18 (standards), EV-19 (census); TEI `/info` check folded into EV-16"),
 ("S-17", "Ligature repair in sparse arm", "CQ-7 (CPU clone), EV-22 (A/B, stratified by damaged vs clean gold)"),
 ("S-18", "Stub filter", "EV-21"),
 ("S-19", "Depth and weight per corpus", "EV-20"),
 ("S-20", "Expose cross-encoder score", "RQ-4 (after RIDER-1 item 3), gate = EV-19"),
 ("S-21", "Focus lever: post-rerank demotion", "RQ-2 (build, default off), RQ-3 (A/B and verdict), RIDER-1 item 1"),
 ("S-22", "Payload indexes on live collections", "CQ-9 (clone and verdict; live application is an on-ADOPT follow-on), gate = EV-14"),
 ("S-23", "Bounded re-chunk of oversized main papers", "CQ-10, CQ-11 (with CQ-8, and CQ-4's plan, in progress)"),
 ("S-24", "Standards structure bundle", "CQ-12 (tracker + golden tests), CQ-13 (furniture pre-pass, table sup/sub/spans), CQ-14 (stub folding, regex guard), CQ-15 (re-derive + clone re-chunk), CQ-16 (verdict); gate counted in EV-18; F7"),
 ("S-25", "BM25 saturation and length normalisation", "CQ-17 (flag-gated implementation), CQ-18 (A/B)"),
 ("S-26", "Envelope slimming on the MCP wire", "MC-4 (gate F5)"),
 ("(D)", "Single foundation rider", "RIDER-1 (items 1 to 6; conditional item 7 for F7)"),
 ("(E)", "Not worth doing", "Section 9 'Will not do' table; no ticket"),
 ("(F)", "Open operator questions", "Section 3, each linked to the tickets it blocks"),
]
LANE = [
 ("Review 1a (score discarded, RV-1 F-1.1, RV-4 F-4.1)", "EV-13, EV-19, RQ-4 (=S-04, S-20)"),
 ("Review 1b (no payload index, RV-1 F-1.2)", "EV-14, CQ-9 (=S-15, S-22)"),
 ("Review 1c (`_SectionTracker`, RV-2 F-2.1)", "CQ-12 to CQ-16 (=S-24); flat books (D5) not fixable by the tracker and not ticketed (needs the PDF outline join, RV-2 F-2.11, not carried)"),
 ("Review 1d (patches vs re-chunk rule, RV-2 F-2.2/F-2.3)", "Rule applied in CQ-10/CQ-11 and CQ-8 (text-hash reuse); full re-chunk and `chunker_id` in section 9; no-ingest rule in EP-6"),
 ("Review 1e (saturation, run-time fixture rewrite, wrong checkout; RV-3 F-1.3, F-1.4)", "EV-5 (done), EV-7, EV-15, EV-8, EV-11; passage-level headline and title-ablated arm are in the frozen protocols (EV-5)"),
 ("Review 1f (contamination cause, RV-5 F-5.1)", "Section 9 (arXiv curl); the lexical gate is built with the next harvest"),
 ("Review 1g (backups, RV-6 F-A1)", "OP-4, OP-3"),
 ("Review 1h (CQ-1 hazard refuted as regression)", "No ticket for the refuted part. Residual risk 1 (ingest into a live collection mixes chunkers/sparse versions): EP-6 no-ingest rule. Residual risk 2 (fake tokenizer): RQ-5 and RIDER-1 item 4"),
 ("Review 'other claims': RV-4 F-4.2", "MC-1"),
 ("RV-1 F-1.3 shared anchors (confirmed)", "Folded into EV-8 (excerpt metric removes the anchor-equality blind spot) and EV-9 (chunk ids). The member-block (QW-1 Variant A) helper must treat fragments; QW-1 remains parked on T-F7 and is not part of this programme"),
 ("RV-1 F-1.9 300 s lock wait, RV-6 F-A3, F-A8", "OP-5, EV-10"),
 ("RV-3 F-1.2 `--collection` default", "EV-7"),
 ("RV-1 F-1.11 critique of CQ-3 (refuted)", "No action. CQ-3 overfetches and stops once the pool is full"),
 ("RV-6 F-A6 / Decision 1 (refuted as open)", "EP-6 closes Decision 1 with the config evidence; `reindex_idf` default flip in section 9"),
 ("RV-5 foundation-protection notes; F-5.5 (refuted)", "RIDER-1 item 2 carries the real protected change (`relevance_filter`); labels are in git, so no ticket"),
 ("RV-5 F-5.6 inert config", "RIDER-1 item 2"),
 ("RV-3 F-1.11 promotion of the three sets", "RIDER-1 item 5"),
 ("RV-6 F-A5 CI (ruff step, nightly manual-only, push)", "RIDER-1 item 6; push is operator question F4. Self-hosted runner: section 9"),
 ("RV-3 F-1.14 ligature stratification", "EV-22"),
 ("RV-3 F-1.10 abstention minimum data", "EV-19 (census only); no MCP wiring is proposed anywhere in this programme"),
 ("RV-2 F-2.5 / F-2.6 / F-2.8 (a) / F-2.10", "CQ-13, CQ-14 (regex guard), CQ-13 (table sup/sub/spans), CQ-14 (stub folding)"),
 ("RV-4 F-4.3, F-4.4", "MC-2"), ("RV-4 F-4.5", "MC-3"), ("RV-4 F-4.6", "MC-4"), ("RV-4 F-4.11", "RQ-1"),
 ("RV-1 F-1.4 (focus lever options)", "RQ-2, RQ-3 (option A only); option B payload route only if RQ-3 sees starvation; C blending and D collection split rejected by the review's reasoning and the operator decision"),
 ("RV-1 F-1.5 (depth/weight)", "EV-20"), ("RV-1 F-1.6 (BM25 weighting)", "CQ-17, CQ-18"), ("RV-1 F-1.7, F-1.8 #7", "RQ-1"), ("RV-1 F-1.10 shared tokenizer", "RQ-5, RIDER-1 item 4"),
 ("RV-6 F-A2", "OP-7"), ("RV-6 B.1 punch list rows 1-23", "EP-1 (PROJECT-STATUS, README, AGENTS rows), EP-3 (BACKLOG rows), EP-6 (HANDOFF, DECISIONS-PENDING, precision-95 plan), EP-7 (RUNBOOK)"),
 ("Review section 2: CQ-1 'no test pins the map checksum'", "RQ-5 (checksum test)"),
 ("Review section 2: OP-1 covers only 'TEI down'", "OP-5"),
 ("Review section 2: EV-6 'not reviewed by any lane'", "Not ticketed; its first exercise is EV-16, where every strata number is cross-checked against the raw report (stated in EV-16's acceptance via the validity checks)"),
]
UNPLACED = [
 ("RV-3 F-1.1 one-command regression gate (manifest + `--baseline`)", "Not carried by the synthesis. Candidate after the first baselines exist (the stored baselines from EV-16/18 are its input)."),
 ("RV-3 F-1.6 question-style realism controls (logged-query comparison, human 30-item slice, keywordised arm)", "Not carried. The protocols already report the title-ablated arm; the realism slice needs operator time."),
 ("RV-3 F-1.12 chapter-level is a heading-string match (caveat)", "Not carried; one-line docs caveat, can ride EV-11 if the operator asks."),
 ("RV-2 F-2.7 front/back-matter role classifier and payload tag", "Not carried. Revisit if EV-21 shows reference/TOC chunks occupying top-10 slots."),
 ("RV-2 F-2.11 books outline join for chapter paths", "Not carried (12.5k chunks, GPU re-embed). Needed to fix flat books; CQ-12 explicitly does not."),
 ("RV-2 F-2.13 chunks over 3,500 characters metric in `scripts/truncation_census.py`", "Not carried (low)."),
 ("RV-4 F-4.7 `get_section` clause-prefix match, `scan_corpus` `section_pattern`", "Not carried; the logs show 4 clause references in 242 queries. Reopen on MC-3 telemetry."),
 ("RV-4 F-4.9 error text without absolute path, nearest-id hints, async tool wrappers", "Not carried (low)."),
 ("RV-4 F-4.10 reorder BACKLOG MCP-E rows", "Not carried as a ticket; the evidence ranking is recorded in section 9 (MCP-E1, E4 not doing)."),
 ("RV-6 F-A7 pre-migration snapshot guard, `busy_timeout`, `quick_check` on snapshot", "Only the `quick_check` part is carried (OP-3). The migration guard and `busy_timeout` are not."),
 ("RV-6 F-A9 canary eval slice and usage-log top-score columns", "Not carried."),
 ("RV-6 F-A10 dashboard bind default, doctor disk check on cwd only, `.phase0-data` naming", "Not carried (low)."),
 ("RV-5 F-5.7 on-topic supply understated; F-5.11 other corpora not rebuildable from tracked files; F-5.12 first-seed runs not reproducible", "Not carried."),
 ("RV-1 F-1.12 per-paper diversity default", "Not carried (no change recommended by the lane)."),
]
WNT = [
 ("Full main-corpus re-chunk (RV-2 F-2.3 option)", "About 1.35M embeds, about 13.8 GB of vectors against 4.1 GB today on a disk with 91 GB free, and about 700 fixture references broken.", "Only the paired old-vs-new chunker test of the review's rule (d)(3) (66 papers, two scratch collections, about 45k embeds, at least +5 net excerpt hits, flips at least 3:1, 2x disk headroom) can justify it."),
 ("Content-addressed chunk ids (RV-2 F-2.3 step 2)", "Touches the frozen IDs spine and rewrites fixtures. The excerpt metric (EV-8) removes the main reason.", "A re-chunk that must preserve ids across chunkers."),
 ("`chunker_id` payload stamp and migration (RV-2 F-2.2)", "No ingest is planned. `docs/CORPORA.md` plus the no-ingest rule (EP-6) carry the same fact at zero schema cost.", "Before the next ingest into a mixed collection."),
 ("Dense-side ligature repair and a 129k re-embed (RV-2 F-2.9)", "No evidence the dense arm suffers (subword tokenizer); repaired excerpts would diverge from `get_span`.", "EV-22 shows a sparse gain and dense-only misses on damaged gold."),
 ("Harvest lexical gate, attribution table, stop-loss, `paper_topic` migration (RV-5 F-5.2, F-5.3, F-5.5)", "Supply is exhausted (BACKLOG O-1), no harvest is scheduled, the operator keeps the mix, labels are in git.", "Build the gate together with the next harvest."),
 ("arXiv contamination curl (RV-5 F-5.1)", "Settles a cause that matters only to a future harvest.", "A harvest is scheduled."),
 ("`relevance_score` max-cos recompute, version refresh, quarantine cleanup, duplicates (RV-5 F-5.4, F-5.8, F-5.9, F-5.10)", "Low decision value; only a stratifier reads these and the labels already serve it.", "None stated."),
 ("`reindex_idf` default flip and snapshot checks (RV-6 F-A6)", "IDF is already applied on all five collections, so the tool is a no-op everywhere. Mark the tool historical.", "A new collection built without the IDF modifier."),
 ("Judge determinism and repeats (RV-3 F-1.9); different-family GT read (F-1.8)", "No answer-level claim is on the table; the retrieval work does not depend on them.", "Before any groundedness number is quoted."),
 ("Persist `content_list` and table HTML; GROBID persist/remove (RV-2 F-2.4, F-2.12)", "No parse is planned.", "In the same ticket as the next parse."),
 ("MCP-E1 find-similar, MCP-E4 taxonomy, federation (RV-4 F-4.10, F-4.4)", "Zero log evidence (2 `scan_methods` calls in 1,198).", "MC-3 telemetry shows more than 30% of hand-written scan patterns are alias-style alternations of one method (E4), or find-similar demand appears (E1)."),
 ("Self-hosted CI runner (RV-6 F-A5)", "An always-on cost on a GPU workstation; manual-only and documented is enough (RIDER-1 item 6).", "None stated."),
 ("`_normalize_text` per-corpus table (RV-2 F-2.8)", "23 blocks affected; only the regex guard is worth doing and it is folded into CQ-14.", "None stated."),
]
QS = [
 ("F1", "Backups: is there any device or remote for an off-disk copy (the only other disk is the photo project's read-only source)? After a fresh verified snapshot, may the five July `.bak` files (6.4 GB), the 07-28 `.partial`, and two of the three July snapshots be deleted?", "OP-4 (off-device copy and deletions only; the snapshot itself is not blocked), EP-7 (restore section's target)"),
 ("F2", "May the vector store (CPU container only) be started for clone measurements? Each clone needs about 6-8 GB of the 91 GB free.", "EV-14, CQ-7, CQ-9, CQ-10, CQ-15, CQ-18"),
 ("F3", "Who owns the wedged foreign model process holding 18.6 GB of VRAM, and may it be stopped? It is what blocks the GPU.", "Every wave-2 ticket (EV-16 to EV-22) and every GPU ticket in wave 3 (RQ-3, CQ-10, CQ-11, CQ-15, CQ-16, CQ-18)"),
 ("F4", "Push the local commits (67 at review time) so CI judges them: yes or no?", "RIDER-1 (a CI verdict on the rider); every 'CI passes' claim in this plan is local until then"),
 ("F5", "May the MCP wire be a projection of the frozen envelope (drop `bbox` and the duplicated `snippet`/`paper_id`)?", "MC-4"),
 ("F6", "Focus lever: is 'demote, never drop, opt-in' the only acceptable form? What off-topic share in the top 10 counts as material?", "RQ-3 (starts only above the bar), EV-17 (reports the number, does not set the bar), RIDER-1 item 1"),
 ("F7", "If the standards structure gate passes, may stored `Block.section_path` be rewritten for standards (and a 35k re-embed run), or must the corrected path live in a derived column?", "CQ-15 (default is the derived column until answered), CQ-16, RIDER-1 conditional item 7"),
 ("F8", "P0-2 metric ratification: sign it, or retire it in favour of the EV-5 protocols and EV-7/EV-8 addenda?", "Any headline quoted from wave-2 reports (they cite the EV-5 protocols, never P0-2, until answered); EP-4 records the answer"),
]
EMBED = [
 "Programme-embedded decisions that are NOT blocking questions (the operator decides them in PR review of the named ticket): the 20 s query-path lock timeout (OP-5), the Qdrant version pin (OP-7), the amended CQ-3 ADOPT rule (EV-12), the standards protocol addendum (EV-11), whether unsupported per-corpus defaults are reset to 32/0.5 as the review says or stay as frozen rule G-1 says (EV-20), the bare-clause-number folding rule (CQ-14), and applying any adopted index change to a live collection (follow-on tickets, written only on ADOPT).",
]
CONSTRAINTS_DECIDED = [
 "The roughly 37% off-topic papers STAY in the main corpus. The goal is to measure and improve whether retrieval stays on focus, never to delete them.",
 "No GPU for now. Everything in waves 1 is written and unit-tested without it; the first GPU session is wave 2 and is entered only after the operator answers F3.",
 "Protected paths (`contracts/`, `rag/config.py`, `config.example.yaml`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`) change only through the single sign-off rider, RIDER-1. No other ticket may touch them; a ticket that finds it needs to stops and reports.",
 "Tickets live in markdown and will be mirrored as GitHub issues only after the operator confirms the list (`INDEX.md` in the issues directory). Nothing has been posted.",
 "Subagents do the work. Each ticket names a model tier: Haiku for mechanical work, Sonnet for logic and authoring, Opus only for hard design adjudication with a one-line justification. No ticket in this set needs Opus; if a verdict is contested at review time, adjudication by Opus is justified by 'independent re-derivation of a pre-registered rule' and is the operator's call.",
]
