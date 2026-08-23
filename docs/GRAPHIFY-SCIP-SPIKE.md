# T-G13 spike — SCIP-precision upgrade feasibility

Spike run 2026-08-23 in worktree `.worktrees/TG-tooling` (branch `TG-graphify-agent-tooling`),
scratch + artifacts under `/tmp/opencode/scip-spike/` (`venv/`, `index.scip`, `decode_scip.py`).

## Verdict: GO-WITH-CONDITIONS

SCIP indexing of this repo **works today, unmodified**: `npx @sourcegraph/scip-python index`
resolved all 235 project files in 12.6 s wall-clock and emitted a 9.2 MB index whose decoded
occurrence table yields **31,369 reference occurrences targeting in-repo symbols** — type-resolved
by pyright-grade semantic analysis, i.e. exactly the dynamic-dispatch resolution our tree-sitter AST
heuristics lack — versus the live AST graph's **14,475 edges total**. The toolchain is not a pip
install away, though: `scip-python` does not exist on PyPI (npm-only), Sourcegraph's `scip` PyPI
parser fails to build here (lxml/py3.13), so we must own a small SCIP→edges converter (~80 lines;
proven working in this spike, zero dependencies). Conditions: (1) accept node/npm as a dev-tooling
prerequisite; (2) index inside an environment with project deps resolvable — indexing from an empty
venv misattributes third-party symbols into the project namespace (observed below); (3) treat
"reference occurrence" ≈ call edge as *upper bound* until a precision spot-check passes.

## What was tried (exact commands, versions, wall-clock)

| # | Command | Result | Wall-clock |
|---|---|---|---|
| 1 | `python3 --version` | 3.13.11 (only interpreter present; **no python3.12** despite `pyproject.toml` `requires-python = "==3.12.*"`) | — |
| 2 | `/tmp/opencode/scip-spike/venv/bin/pip install scip-python` | **FAIL** — `No matching distribution found for scip-python (from versions: none)` | 0.24 s |
| 3 | `npx -y @sourcegraph/scip-python index --help` | OK — CLI help printed; npm distribution confirmed | 5.0 s |
| 4 | `venv/bin/pip install scip` | **FAIL** — `Failed to build 'lxml' when getting requirements to build wheel`; retried after `pip install "lxml>=5"` → same failure | 7.8 s |
| 5 | `npx -y @sourcegraph/scip-python index --cwd <worktree> --output /tmp/opencode/scip-spike/index.scip` | **OK** — `Total Project Files 235` … `Successfully wrote SCIP index` | **12.6 s** |
| 6 | `venv/bin/python decode_scip.py` (spike-written protobuf wire decoder, stdlib-only) | OK — counts below | <1 s |

Path taken: primary pip route (#2) is a dead end by itself — that is a finding, not a blocker; npm
route (#3/#5) is the real one. Protobuf parsing via PyPI `scip` (#4) is unusable on this machine, so
the spike wrote a minimal wire-format decoder (`decode_scip.py`) instead of guessing from strings.

## Measured (every number carries its command)

Artifact & index shape:

- `ls -la /tmp/opencode/scip-spike/index.scip` → **9,204,139 bytes** (≈9.2 MB).
- `decode_scip.py index.scip` → documents=**235**, external_symbols=**480**, occurrences_total=**89,468**,
  definitions (occurrence role-bit 1)=**19,811**, SymbolInformation messages=19,481.
- Reference split (`decode_scip.py`, non-definition occurrences): → in-repo symbols **31,369**,
  → external symbols **38,288**. The 480 explicitly-emitted external symbols replace the
  "~786 dangling symbol refs" problem class: externals resolve to named packages, they don't dangle.
- Is-a/override relationships are sparse in this index (field-4 submessages: 91 hits per
  SI-field histogram over first 8000 SIs, `fields()` probe in scratch) — call/use edges come from
  *occurrences*, not `Relationship`s; any converter must be occurrence-driven.

Baseline comparison (live AST graph):

- `python -c "json.load(.../graphify-out/graph.json)"` (main worktree artifact, 7.3 MB) →
  **total_edges=14,475, nodes=5,384**. The ticket's "15.7k edges / 15.7k CALLS" figure was **not**
  reproduced against this artifact — measured 14,475 total edges of all kinds (ticket figure marked
  UNVERIFIED here; may refer to a newer build or CALLS-only subset).
- So SCIP offers ≥2× more resolved use-sites than the entire current edge set. Caveats on the 31,369:
  (a) it includes attribute loads/imports/type refs, not only calls (UNVERIFIED what fraction);
  (b) indexed from an empty venv, top targets show `pathlib/Path#` and `` `httpx._models`/Response#``
  tagged under the *project* namespace — dependency misattribution that a deps-resolvable env should
  fix; (c) schema fields were reverse-engineered from the wire format (Document=path:1,
  occurrences:2, symbol-infos:3; Occurrence=range:1,symbol:2,roles:3; Relationship=symbol-string:1),
  cross-checked against sourcegraph/scip proto semantics but not against a generated binding.

## Integration sketch (IF GO)

- Ticket assumed `scripts/graphify_enrich.py` as the pipeline slot — **that file does not exist** in
  this worktree (verified `ls scripts/`). Actual integration points: the post-commit hook installed
  by `graphify hook install` (re-runs `graphify extract . --code-only`, main worktree only), and the
  pattern of `scripts/graphify_rig.py` (stdlib-only, deterministic, emits JSON, T-G15).
- Converter: new `scripts/graphify_scip.py` following the `graphify_rig.py` house style — reads
  `index.scip`, walks documents→occurrences, maps each non-definition occurrence to an edge
  (containing file → definition site of the target symbol), plus the sparse relationship entries as
  IS-A edges; drops/relabels the external-package edges. Logic already prototyped:
  `/tmp/opencode/scip-spike/decode_scip.py`. No new runtime deps (pure wire-format decoding).
- Freshness story: full re-index is 12.6 s locally, so per-post-commit is *feasible*, but unlike the
  current hook it needs node+npx AND a python env with deps synced (see risks). Recommended
  sequencing: ship converter + manual command first; wire into the post-commit hook only behind an
  availability check (`command -v npx`), falling back silently to the AST pass otherwise.

## Costs & risks

- Distribution/maintenance: npm-only upstream (`@sourcegraph/scip-python`); adds node to the dev
  toolchain and an npm supply-chain surface; indexer bundles its own pyright — version drift vs our
  `py312` ruff target is possible. Machine has only python3.13 while the repo pins `==3.12.*`;
  indexing succeeded regardless, but resolution fidelity against the 3.12 target is UNVERIFIED.
- Environment coupling: correct external attribution requires project deps importable/resolvable in
  the indexing env (observed misattribution from an empty venv) — every freshness story must include
  env sync or accept polluted namespaces.
- Parser ownership: `scip` PyPI unusable here (lxml build failure ×2) → we own the converter forever
  (small, but it encodes wire-format assumptions; a schema bump can break it silently → add a
  round-trip self-test like `test_graphify_rig.py` does).
- Edge semantics: reference-occurrences ≠ calls precisely; expect precision work (filter by symbol
  descriptor suffix `().` vs `#`/`(` property/class descriptors) before swapping CALLS edges over.
- CI time: 12.6 s + npm fetch locally; CI-runner behavior (cold cache, socket policy) UNVERIFIED.

## Decision owner + date

Decision owner: human operator (`@MKamel1`) on recommendation of the T-G tooling track; spike date
2026-08-23. Recommended next ticket before any swap-in: precision spot-check of N≥30 sampled
in-repo reference edges against ground truth call sites, plus a deps-synced re-index to quantify the
misattribution delta (31,369 upper bound → true call-edge count).
