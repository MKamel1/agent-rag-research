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

Scoped to `rag/`/`contracts/`/`app/` (`model.in_pipeline_scope`; `app/` added by T-DOC29) — this is
a rule about the RAG pipeline's own modules (CONVENTIONS §1), not the repo at large; without that
scope this check would flag its own implementation (this file necessarily names every vendor token
as data) the moment it's added.
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
    # rag/test_vector_index.py (T-DOC80) legitimately names Qdrant in its `_qdrant_filter` unit
    # tests -- they exercise the real Qdrant adapter's filter-building function directly, same
    # reasoning as the mineru/ollama test-file exemptions below.
    # app/exp1_outline_split.py (Experiment 1, docs/PLAN-book-rag-experiments.md) is a composition
    # root the same shape as app/reembed_experiment.py/app/rechunk.py below -- it clones the
    # production Qdrant collection into a throwaway one via VectorIndex.clone_points_into and
    # names no vendor itself, only in comments/docstrings describing that call.
    # T-DOC87: app/exp_tdoc87_marker_repair.py is the same composition-root shape again --
    # re-summarizes the 2 regex-repair-affected books and clones production into a throwaway
    # collection via the same VectorIndex.clone_points_into call, names no vendor itself.
    VendorRule(
        "qdrant",
        re.compile(r"qdrant", re.I),
        (
            "rag/vector_index.py",
            "rag/test_vector_index.py",
            "app/exp1_outline_split.py",
            "app/exp_tdoc87_marker_repair.py",
        ),
    ),
    # rag/test_parser.py (T-DOC16) legitimately injects a fake `mineru.cli.common` module into
    # `sys.modules` (by that exact dotted name -- `rag.parser`'s own lazy `from mineru.cli.common
    # import do_parse`) to exercise `Parser.parse`/`parse_batch`'s do_parse-calling plumbing
    # offline, without the real (torch-heavy) `mineru` package -- same reasoning as the
    # ollama/vllm/httpx test-file exemptions below.
    VendorRule("mineru", re.compile(r"mineru", re.I), ("rag/parser.py", "rag/test_parser.py")),
    VendorRule("marker_pdf", re.compile(r"marker[_-]pdf", re.I), ("rag/parser.py",)),
    VendorRule("docling", re.compile(r"docling", re.I), ("rag/parser.py",)),
    VendorRule("grobid", re.compile(r"grobid", re.I), ("rag/parser.py",)),
    # rag/test_summarizer.py legitimately builds httpx.MockTransport fixtures with an
    # "http://ollama.local" stand-in URL (and a docstring/comment naming Ollama) to exercise the
    # adapter offline -- same reasoning as the httpx rule's own test-file exemptions below.
    # app/exp1_outline_split.py: same composition-root shape as app/reembed_experiment.py/
    # app/rechunk.py -- constructs the real OllamaSummarizer to re-summarize the 4 outline-split
    # books, names no vendor itself beyond the class import and its own service-URL constant.
    # T-DOC87: app/exp_tdoc87_marker_repair.py, same shape -- constructs the real OllamaSummarizer
    # to re-summarize the 2 regex-repair-affected books.
    # app/exp_author_org_tagging.py: same composition-root shape again -- constructs the real
    # OllamaSummarizer to run its extract_affiliations method against the validation experiment's
    # positive/negative sets, names no vendor itself beyond the class import and its own
    # service-URL constant.
    VendorRule(
        "ollama",
        re.compile(r"ollama", re.I),
        (
            "rag/summarizer.py",
            "rag/test_summarizer.py",
            "app/exp1_outline_split.py",
            "app/exp_tdoc87_marker_repair.py",
            "app/exp_author_org_tagging.py",
        ),
    ),
    # vLLM ADR-09 covers both the embedder and the summarizer's local-LLM serving; rag/test_summarizer.py
    # mentions vLLM in the same comment as Ollama, for the same reason.
    VendorRule(
        "vllm",
        re.compile(r"vllm", re.I),
        ("rag/embedder.py", "rag/summarizer.py", "rag/test_summarizer.py"),
    ),
    # environment.yml: "generic HTTP client -- arXiv (M1) + TEI/vLLM embedder (M4) adapters".
    # rag/harvester.py is the arXiv side (T-A1); rag/embedder.py's real adapter talks to the
    # TEI/vLLM server over plain HTTP (httpx is its actual vendor dependency, not vllm, which
    # only appears there as a docstring reference to ADR-09); rag/summarizer.py's real adapter
    # (T-C2) also talks to Ollama over plain HTTP; rag/parser.py's real adapter (T-B1) also talks
    # to GROBID's REST API over plain HTTP for reference resolution; rag/reranker.py's real adapter
    # likewise talks to TEI's cross-encoder endpoint over plain HTTP. rag/test_harvester_arxiv_source.py,
    # rag/test_summarizer.py, rag/test_embedder.py, and rag/test_reranker.py legitimately build
    # httpx.MockTransport/Client fixtures to exercise their adapters offline (zero network).
    #
    # app/test_prefetch_pdfs.py (app/prefetch_pdfs.py's test, moved from rag/test_prefetch_pdfs.py
    # by T-DOC29 -- it tests an app/ module, so it belongs next to it, same-directory-sibling
    # convention check (g) also relies on) builds the same kind of httpx.MockTransport/Client
    # fixtures to exercise app/prefetch_pdfs.py's real arXiv-PDF download adapter offline (zero
    # network) -- same pattern as the other adapter test files above. `PIPELINE_SCOPE_PREFIXES`
    # gained `"app/"` in that same ticket (previously app/ was entirely excluded from rule (a), an
    # accident of scope, not a designed exemption); app/prefetch_pdfs.py's `import httpx` line
    # isn't listed below yet because no PR has actually touched/added it since scope widened -- add
    # it here the moment one does (§12's "add the matching entry in the same PR" rule), rather than
    # widening this allowlist speculatively for lines nothing has touched.
    #
    # T-DOC41 (Contextual Retrieval spike): rag/contextual_header.py is a new real adapter over the
    # same local generation-LLM server rag/summarizer.py already talks to, built the same way (an
    # injected httpx.Client) -- rag/test_contextual_header.py exercises it offline with the same
    # httpx.MockTransport pattern as rag/test_summarizer.py. app/reembed_experiment.py is the
    # throwaway A/B re-embed script that constructs the real httpx-backed adapters (this ticket's
    # own composition root, mirroring app/assembly.py) -- it names no vendor itself, only httpx as
    # the shared HTTP client, same as every other composition-root/adapter entry in this list.
    #
    # T-DOC78: app/tei_lifecycle.py talks to the TEI containers' health endpoints over the same
    # httpx client; app/test_tei_lifecycle.py exercises it offline via httpx.MockTransport, same
    # pattern as every other adapter test above. app/assembly.py is this rule's composition root
    # (already allowlisted implicitly by not being scanned before -- now explicit since its
    # TeiEmbedder/TeiReranker construction lines were reformatted by an unrelated diff and now
    # register as "added" lines containing "httpx").
    #
    # T-DOC62: app/rechunk.py's `main()` is a composition root the same shape as
    # app/reembed_experiment.py's -- it constructs the real httpx-backed TeiEmbedder to re-embed
    # re-chunked papers, names no vendor itself.
    #
    # Experiment 1 (docs/PLAN-book-rag-experiments.md): app/exp1_outline_split.py is the same
    # composition-root shape again -- it constructs the real httpx-backed OllamaSummarizer and
    # TeiEmbedder to re-summarize/re-embed the 4 outline-split books, names no vendor itself.
    #
    # Experiment 3 (docs/PLAN-book-rag-experiments.md): app/exp3_hierarchy_sim.py is the same
    # composition-root shape as app/exp1_outline_split.py -- it constructs the real httpx-backed
    # TeiEmbedder to embed ad hoc Part-level query vectors for the hierarchy simulation, names no
    # vendor itself, only httpx as the shared HTTP client.
    #
    # T-DOC87: app/exp_tdoc87_marker_repair.py, same composition-root shape -- constructs the real
    # httpx-backed OllamaSummarizer/TeiEmbedder to re-summarize/re-embed the 2 regex-repair-
    # affected books, names no vendor itself, only httpx as the shared HTTP client.
    #
    # app/exp_author_org_tagging.py: same composition-root shape as the exp1/exp3/exp_tdoc87
    # entries above -- constructs a real httpx.Client to hand to OllamaSummarizer for the
    # author-org-tagging validation experiment, names no vendor itself, only httpx as the shared
    # HTTP client.
    #
    # app/test_assembly.py (RI-23): its _PdfDownloadParser tests build the same
    # httpx.MockTransport/Client fixtures over "%PDF-fake" bodies as app/test_prefetch_pdfs.py
    # above -- this repo's established zero-network adapter-test idiom. The file gained them in
    # RI-18 without the matching entry being added in the same PR, and the enforcement gate went
    # red on lines no check had ever complained about when they landed.
    #
    # JUDGE-1: app/judge_llm.py is the real `Judge` adapter for app/judge_eval.py's seam -- same
    # injected-httpx.Client construction as rag/summarizer.py/rag/contextual_header.py, living in
    # app/ rather than rag/ because the Judge Protocol it implements is itself defined in app/
    # (see the module's own docstring for the dependency-direction reasoning). Names no other
    # vendor. app/test_judge_llm.py exercises it offline via httpx.MockTransport, same pattern as
    # every other adapter test above.
    #
    # FAB-1: app/generation_capture.py is the real generation-run capture harness -- same
    # injected-httpx.Client + GpuLock + model-name construction as app/judge_llm.py, living in
    # app/ for the same reason. Names no vendor itself, only httpx as the shared HTTP client.
    # app/test_generation_capture.py exercises it offline via httpx.MockTransport, same pattern as
    # every other adapter test above.
    VendorRule(
        "httpx",
        re.compile(r"httpx", re.I),
        (
            "rag/harvester.py",
            "rag/test_harvester_arxiv_source.py",
            "rag/embedder.py",
            "rag/test_embedder.py",
            "rag/summarizer.py",
            "rag/test_summarizer.py",
            "rag/parser.py",
            "rag/reranker.py",
            "rag/test_reranker.py",
            "app/test_prefetch_pdfs.py",
            "app/test_assembly.py",
            "rag/contextual_header.py",
            "rag/test_contextual_header.py",
            "app/reembed_experiment.py",
            "app/tei_lifecycle.py",
            "app/test_tei_lifecycle.py",
            "app/assembly.py",
            "app/rechunk.py",
            "app/exp1_outline_split.py",
            "app/exp3_hierarchy_sim.py",
            "app/exp_tdoc87_marker_repair.py",
            "app/exp_author_org_tagging.py",
            "app/judge_llm.py",
            "app/test_judge_llm.py",
            "app/generation_capture.py",
            "app/test_generation_capture.py",
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
