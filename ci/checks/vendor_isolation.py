"""Check (a) — CONVENTIONS.md §1 / §12: a vendor SDK name may appear only inside its own adapter
file. Deliberately blunt (a substring grep on the diff's added lines, not an import-statement
parser) — CONVENTIONS §0.1 wants this caught mechanically, and "the vendor name appears in exactly
one module" (§1) is itself phrased as a grep, not an AST rule.

Token list is curated, not "every word that ever names a vendor": each entry below is an
unambiguous SDK/package name (`qdrant`, `mineru`, `ollama`, ...), never a domain word. The arXiv
API client is deliberately *not* in this table — "arxiv" is this repo's own domain vocabulary
(paper ids, docstrings, doc titles all say it constantly), so a bare substring grep on it would be
noise, not signal; if a real arXiv HTTP client package gets a distinctive import name later, add
it here.

Adapter paths are the *planned* locations (this repo's existing convention of mirroring a
`contracts/<module>.py` interface with a same-named `rag/<module>.py` implementation — see
`rag/config.py` next to `contracts/config.py`). None of M2/M4/M6's real adapters exist yet
(Phase 0 hasn't landed); confirm/adjust `VENDOR_RULES` against the real path when each one does.

Scoped to `rag/`/`contracts/` (`model.in_pipeline_scope`) — this is a rule about the RAG pipeline's
own modules (CONVENTIONS §1), not the repo at large; without that scope this check would flag its
own implementation (this file necessarily names every vendor token as data) the moment it's added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ci.checks.model import DiffFile, Violation, in_pipeline_scope


@dataclass(frozen=True)
class VendorRule:
    vendor: str  # human-readable label for the violation message
    token: re.Pattern[str]  # what counts as "this vendor's name appears"
    allowed_paths: tuple[str, ...]  # repo-relative paths this token is allowed to appear in


# Curated, not derived -- extend this when a new vendor SDK/adapter lands (see module docstring).
VENDOR_RULES: tuple[VendorRule, ...] = (
    VendorRule("qdrant", re.compile(r"qdrant", re.I), ("rag/vector_index.py",)),
    VendorRule("mineru", re.compile(r"mineru", re.I), ("rag/parser.py",)),
    VendorRule("marker_pdf", re.compile(r"marker[_-]pdf", re.I), ("rag/parser.py",)),
    VendorRule("docling", re.compile(r"docling", re.I), ("rag/parser.py",)),
    VendorRule("grobid", re.compile(r"grobid", re.I), ("rag/parser.py",)),
    VendorRule("ollama", re.compile(r"ollama", re.I), ("rag/summarizer.py",)),
    # vLLM ADR-09 covers both the embedder and the summarizer's local-LLM serving.
    VendorRule("vllm", re.compile(r"vllm", re.I), ("rag/embedder.py", "rag/summarizer.py")),
    # environment.yml: "generic HTTP client -- arXiv (M1) + TEI/vLLM embedder (M4) adapters".
    # rag/harvester.py is the arXiv side (T-A1); rag/embedder.py's real adapter talks to the
    # TEI/vLLM server over plain HTTP (httpx is its actual vendor dependency, not vllm, which
    # only appears there as a docstring reference to ADR-09); rag/summarizer.py's real adapter
    # (T-C2) also talks to Ollama over plain HTTP. rag/test_harvester_arxiv_source.py and
    # rag/test_summarizer.py legitimately build httpx.MockTransport/Client fixtures to exercise
    # their adapters offline (zero network).
    VendorRule(
        "httpx",
        re.compile(r"httpx", re.I),
        (
            "rag/harvester.py",
            "rag/test_harvester_arxiv_source.py",
            "rag/embedder.py",
            "rag/summarizer.py",
            "rag/test_summarizer.py",
        ),
    ),
)


def check_a(files: list[DiffFile]) -> list[Violation]:
    violations = []
    for f in files:
        if not in_pipeline_scope(f.path):
            continue
        for rule in VENDOR_RULES:
            if f.path in rule.allowed_paths:
                continue
            for line_no, text in f.added_lines:
                if rule.token.search(text):
                    violations.append(
                        Violation(
                            check="a",
                            path=f.path,
                            line=line_no,
                            message=(
                                f"vendor name {rule.vendor!r} appears outside its adapter "
                                f"({'/'.join(rule.allowed_paths)}): {text.strip()!r}"
                            ),
                        )
                    )
    return violations
