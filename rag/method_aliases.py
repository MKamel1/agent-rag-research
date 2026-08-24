"""Curated method-vocabulary map — the synonym layer behind `McpServer.scan_methods`.

Why this exists: "which papers use method X" is an enumeration question, and enumeration recall
is 1.0 only *for the pattern given* (`DocumentStore.scan_blocks`). A method's many names — "RRF" /
r"\breciprocal rank fusion", "NIEON" / "non-impaired eyes-on" — are exactly where that recall dies.
This module is the maintained artifact that closes it: canonical method families, each with the
surface forms the corpus actually uses.

What it is NOT:
- Not a contract. The families are a curated, growing artifact — adding one is a normal
  `rag/` change, not a foundation change. The `scan_methods` docstring tells callers how to
  request an addition (or bypass via `scan_corpus` with their own pattern).
- Not query rewriting. `Retriever.retrieve()` is untouched — PRD §11A (agent-as-reasoner:
  the server never rewrites a *semantic* query) stays true. `scan_methods` is an explicitly
  lexical enumeration tool in `scan_corpus`'s mold; the expansion happens before a regex scan,
  in full view of the caller, never inside a ranked search.

Pattern grammar (each alias is a regex FRAGMENT, matched case-insensitively by `scan_blocks`):
- A fragment made only of lowercase letters, digits, spaces and hyphens ("nexar", "vision zero")
  is auto-guarded `\\b…\\b` — whole-word semantics.
- A fragment containing any other regex character is used VERBATIM and its author owns the
  boundaries. This is how stems are written: `\\bmais` matches "MAIS3+F" where `\\bmais\\b`
  would not (the digit kills the trailing boundary); `\\bcurv` matches "curves"; `\\brerank`
  matches "reranking"/"reranked".
Keep fragments lowercase — matching is case-insensitive, and mixed-case entries only lie about it.
"""

import re

# Canonical family name -> surface forms. Order within a family doesn't matter (the built
# pattern is an alternation); family names are what `list_methods()` shows callers.
METHOD_ALIASES: dict[str, tuple[str, ...]] = {
    # --- Waymo AV-safety corpus -----------------------------------------------------------
    "NIEON (non-impaired eyes-on driver reference model)": (
        "nieon", r"\bnon-impaired eyes",
    ),
    "collision avoidance testing (CAT)": (
        r"\bcat\b", r"\bcollision avoidance test", r"\bcollision-avoidance test",
    ),
    "injury risk curve/model": (
        r"\binjury risk curv", r"\binjury risk function", r"\binjury risk model", r"\binjury risk estim",
    ),
    "MAIS (maximum abbreviated injury scale)": (
        r"\bmais", r"\bmaximum abbreviated injury scale",
    ),
    "delta-V / PDOF (collision severity kinematics)": (
        "delta-v", "delta v", r"\bdv\b", "pdof", r"\bprincipal direction of force",
        r"\bdirection of force",
    ),
    "IPMM/CPMM (crashes per million miles)": (
        "ipmm", "cpmm", "per million miles", "per million vehicle miles",
    ),
    "power analysis": (
        r"\bpower analysis", "statistical power",
    ),
    "dynamic benchmark": (
        r"\bdynamic benchmark",
    ),
    "counterfactual simulation": (
        r"\bcounterfactual simulat", r"\bcounter-factual simulat",
    ),
    "reachability analysis / field of safe travel": (
        r"\breachability analysis", r"\breachable set", "field of safe travel", "field of safe motion",
        r"\bfst\b", r"\bfsm\b",
    ),
    "active inference": (
        r"\bactive.inference", r"\bexpected free energy", r"\bfree energy minimiz",
        r"\bfree-energy",
    ),
    "surprise-based response modeling": (
        "surprise-based", r"\bsurprise minimization", r"\bsurprise accumulat",
    ),
    "GIDAS (German in-depth accident study)": (
        "gidas", r"\bgerman in-depth accident study",
    ),
    "CISS (crash investigation sampling system)": (
        r"\bciss\b", r"\bcrash investigation sampling system",
    ),
    "NASS-CDS": (
        "nass-cds", "nass cds", r"\bnational automotive sampling system",
    ),
    "FARS (fatality analysis reporting system)": (
        r"\bfars\b", r"\bfatality analysis reporting system",
    ),
    "NHTSA Standing General Order (SGO)": (
        r"\bstanding general order", r"\bsgo\b",
    ),
    "UL 4600": (
        "ul 4600", "ul4600",
    ),
    "safety case / absence of unreasonable risk": (
        r"\bsafety case", r"\babsence of unreasonable risk", r"\baur\b",
    ),
    "RAVE checklist": (
        "rave checklist", r"\bretrospective automated vehicle evaluation",
    ),
    "safety management system": (
        r"\bsafety management system", r"\bsms\b",
    ),
    "operational design domain": (
        r"\boperational design domain",
    ),
    "vulnerable road user (VRU)": (
        r"\bvulnerable road user", r"\bvru\b",
    ),
    "powered two-wheeler (PTW)": (
        r"\bpowered two-wheeler", r"\bptw\b",
    ),
    "fatigue risk management": (
        r"\bfatigue risk management", r"\bfrm\b",
    ),
    "Vision Zero": (
        "vision zero",
    ),
    "Safe System approach": (
        r"\bsafe system",
    ),
    "cyclist dooring": (
        "dooring",
    ),
    "seat belt compliance": (
        r"\bseat belt", "seatbelt",
    ),
    "Nexar dash-camera naturalistic data": (
        "nexar",
    ),
    "police-reported crash data": (
        r"\bpolice-report", r"\bpolice report",
    ),
    "naturalistic driving study": (
        r"\bnaturalistic driving", r"\bnds\b",
    ),
    "auto liability insurance claims": (
        "swiss re", r"\bliability insurance claim", r"\bauto liability",
    ),
    "crash rate benchmark": (
        r"\bcrash rate benchmark", r"\bcrashed vehicle rate",
    ),
    # --- causal-methods corpus ------------------------------------------------------------
    "reciprocal rank fusion (RRF)": (
        r"\breciprocal rank fusion", r"\brrf\b", r"\brank fusion",
    ),
    "ColBERT / late interaction": (
        "colbert", r"\blate interaction", "late-interaction", "maxsim",
    ),
    "hybrid dense-sparse retrieval": (
        r"\bhybrid search", r"\bhybrid retrieval", r"\bdense retrieval", r"\bsparse retrieval", r"\bbm25\b",
    ),
    "cross-encoder reranking": (
        r"\bcross-encoder", r"\bcross encoder", r"\brerank",
    ),
    "propensity score methods": (
        r"\bpropensity score", r"\bpropensity matching",
    ),
    "instrumental variables": (
        r"\binstrumental variable",
    ),
    "difference-in-differences": (
        "difference-in-differences", r"\bdifference in differences", "diff-in-diff",
    ),
    "synthetic control": (
        r"\bsynthetic control",
    ),
    "randomized controlled trial": (
        r"\brandomized controlled trial", r"\brandomised controlled", r"\brct\b",
    ),
    "doubly robust / TMLE / AIPW": (
        r"\bdoubly robust", "tmle", r"\baugmented inverse propensity", "aipw",
    ),
    "causal discovery / structure learning": (
        r"\bcausal discovery", r"\bcausal structure learning", r"\bpc algorithm", r"\bges algorithm",
        "notears",
    ),
    "structural causal model / do-calculus": (
        r"\bstructural causal model", "do-calculus", "do calculus", "backdoor",
    ),
    "conformal prediction": (
        r"\bconformal prediction",
    ),
    "LoRA / low-rank adaptation": (
        r"\blora\b", r"\blow-rank adaptation",
    ),
    "retrieval-augmented generation": (
        r"\bretrieval-augmented", r"\bretrieval augmented",
    ),
    "approximate nearest neighbor index": (
        "hnsw", r"\bivf\b", r"\bapproximate nearest neighbou?r",
    ),
}

_PLAIN = re.compile(r"^[a-z0-9][a-z0-9 \-]*$")


def _guard(fragment: str) -> str:
    """`\\b`-guard plain word fragments; pass regex fragments through untouched."""
    if _PLAIN.match(fragment):
        return rf"\b{fragment}\b" if not fragment[0].isspace() else fragment
    return fragment


def build_method_regex(patterns: list[str]) -> str:
    """Alternation over `patterns`, each `\\b`-guarded if plain. Non-empty input assumed —
    `scan_methods` always has at least the literal method name to fall back to."""
    return "|".join(_guard(p) for p in patterns)


def resolve_method(method: str) -> tuple[str, list[str]]:
    """`method` -> `(canonical_family, alias_fragments)`. Exact canonical match wins, then
    case-insensitive canonical match, then a unique alias substring hit, then the literal input
    as a single plain fragment (unknown methods still scan — the corpus may use a name this map
    has not learned yet, and a literal scan is the honest fallback, not an error)."""
    for canonical, aliases in METHOD_ALIASES.items():
        if method == canonical:
            return canonical, list(aliases)
    for canonical, aliases in METHOD_ALIASES.items():
        if method.lower() == canonical.lower():
            return canonical, list(aliases)
    # Callers type either the short form ("RRF" -- probe-in-alias) or a long/inflected form
    # ("reranking", "injury risk curves" -- alias stem at a word boundary of the probe). Stems
    # shorter than 4 characters ("cat") are excluded from the reverse direction: too collision-
    # prone to resolve a family from, and the ambiguity guard below refuses to guess anyway.
    lowered = method.lower()
    hits = []
    for canonical, aliases in METHOD_ALIASES.items():
        for alias in aliases:
            stem = alias.lower().lstrip("\\b").strip()
            if lowered in alias.lower() or (
                len(stem) >= 4 and re.search(rf"\b{re.escape(stem)}", lowered)
            ):
                hits.append((canonical, list(aliases)))
                break
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        # Ambiguous substring ("risk" would hit several families): refuse to guess — the caller
        # sees the candidate families in the error and picks one. Silent first-hit would make
        # results depend on dict order.
        candidates = ", ".join(sorted(c for c, _ in hits))
        raise ValueError(
            f"method {method!r} matches multiple families; name one of: {candidates}"
        )
    return method, [method]


def list_methods() -> list[str]:
    """Canonical family names, sorted — `list_methods()`' payload."""
    return sorted(METHOD_ALIASES)
