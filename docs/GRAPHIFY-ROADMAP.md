# Graphify agent-tooling roadmap — T-G series

*2026-08-23. Plan + outcome ledger for making `graphify-out/graph.json` serve
cold-start onboarding, design planning, and code review by memoryless agents.
Design grounded in `docs/AGENT-OPERATIONS-LESSONS.md` failure classes; external
state-of-practice comparison (CodeGraph/GitNexus/orgraph/RANGER/RIG/SCIP) in
`docs/GRAPHIFY-SCIP-SPIKE.md` §Context.*

## Design stance

The scarce resource is agent **trust**: one stale edge is worse than a missing one
(lesson 2.1). Therefore: deterministic enrichment from repo sources of truth over
more LLM extraction; staleness surfaced mechanically (T-G10); every enrichment
artifact tagged `enrichment:` so re-runs replace cleanly.

## Tooling shipped

| script | ticket | what it does |
|---|---|---|
| `scripts/graphify_enrich.py` | T-G1/G4/G6/G7/G8 | Patches graph.json from PROJECT-STATUS §2/§7 tables, BACKLOG rows (+git SHAs), CODEOWNERS freeze flags, contract↔fake seams, test→module covers |
| `scripts/graphify_cochange.py` | T-G5 | Mines git history into `co_changed_with` edges (mass-commit guarded) |
| `scripts/graphify_obligations.py` | T-G9 | AGENT-PROCEDURES §B obligation table as a mechanical diff check |
| `scripts/graphify_validate.py` + `_hook.sh` | T-G10 | Post-build health gate; writes `.needs_update.json`, wired into post-commit |
| `scripts/graphify_rig.py` | T-G15 | RIG-lite: test inventory + covered modules + CI check registry, AST-only |
| `scripts/graphify_brief.py` | T-G14 | Deterministic ≤N-token cited brief (answer-shaped default over raw BFS) |
| `.opencode/opencode.json` | T-G12 | Project-scoped MCP server (`graphify-mcp`) |

## Outcome ledger (one line per ticket)

| id | outcome | evidence |
|---|---|---|
| T-G1 | doc_class patched on 44 doc nodes from §7 table; entry-point nodes wired to modules; 5 trap concept nodes | enrich run summary 2026-08-23 |
| T-G4 | ticket nodes with `[STATUS]` labels + git-SHA file links; skips counted, never guessed | enrich `skipped.ticket_*` |
| T-G5 | 38 co-change edges over 217 commits @ min-support 3 | `/tmp` run log; unit tests 15 |
| T-G6 | 721 nodes flagged `foundation_frozen` from CODEOWNERS | enrich summary |
| T-G7 | contract↔fake seam edges via name-resolved AST scan; unresolved seams skipped loudly | enrich `skipped.seam_no_contract=4` |
| T-G8 | covers edges test→module from RIG inventory imports | rig JSON layer |
| T-G9 | rules R1/R2/R3/R5 encoded; R4 suppression; always-on self-check | 9 unit tests |
| T-G10 | validator green post-enrich (0 dangling, 0 unlabeled); hook appends gated call | validate output 2026-08-23 |
| T-G11 | this doc + GRAPHIFY.md section + AGENT-PROCEDURES §A bullet | this PR |
| T-G12 | MCP handshake verified against live graph.json | initialize round-trip |
| T-G13 | **GO-WITH-CONDITIONS**: scip-python 12.6s index, 31,369 resolved refs (~2× AST edges), 9.2MB; needs node prereq + self-owned converter | docs/GRAPHIFY-SCIP-SPIKE.md |
| T-G14 | brief answers the canonical onboarding question with cited authoritative docs + live ticket states | probe transcript in PR body |
| T-G15 | 235-file inventory; test files + covered modules + ci/checks registry | rig collector output |

Deliberately NOT done here: full SCIP integration (T-G13 verdict conditions),
community relabeling after enrichment (new nodes inherit neighbors; next
`graphify label --missing-only` names any new cluster).

## Refresh procedure after this PR

```bash
python -m scripts.graphify_cochange --repo . --since HEAD~200 \
  --exclude 'docs/eval-reports/*' --out /tmp/cochange.json
python -m scripts.graphify_enrich --repo . --graph-dir graphify-out \
  --cochange /tmp/cochange.json
python -m scripts.graphify_validate --graph-dir graphify-out --repo .
```

(The post-commit hook runs validate automatically; enrich/cochange are
per-milestone or after editing PROJECT-STATUS/BACKLOG tables.)
