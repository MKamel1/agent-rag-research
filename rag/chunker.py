"""Chunker (M3) — see `contracts/chunker.py` for the `Chunk` shape (do not re-derive its fields
here) and DATA-CONTRACTS.md "Provenance & structure" for the multi-block anchoring rule this
module implements. ARCHITECTURE.md §M3 is the interface source of truth.

Zero-GPU, zero-network (ARCHITECTURE §M3 "Seam: none needed") — no vendor/LLM client is injected
here in V0. Do NOT add contextual-header generation (PRD ADR-07, V1-only) — see the
`contextual_header` docstring on `contracts/chunker.Chunk`; every `Chunk` emitted here carries
`contextual_header=None`.
"""

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor, Block

_SNIPPET_MAX_CHARS = 200


def _extract_title(markdown: str) -> str:
    """First H1 line (`# Title`) in the doc's markdown. `# ` (single hash) only — `## Section`
    must not match. No H1 found -> empty string (a missing title is a markdown-quality issue for
    upstream, not something this module invents a fallback title for).
    """
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _snippet(text: str) -> str:
    """First ~200 chars of `text`, truncated at the nearest preceding word boundary, verbatim
    (DATA-CONTRACTS.md "Provenance & structure" — the `Anchor.snippet` definition).
    """
    text = text.strip()
    if len(text) <= _SNIPPET_MAX_CHARS:
        return text
    truncated = text[:_SNIPPET_MAX_CHARS]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated


class Chunker:
    """`chunk(ParsedDoc) -> list[Chunk]` (ARCHITECTURE §M3 frozen interface)."""

    def __init__(self, config: Config):
        self._config = config

    def chunk(self, doc: ParsedDoc) -> list[Chunk]:
        title = _extract_title(doc.markdown)
        groups = self._group_blocks(doc.blocks)
        return [
            self._build_chunk(doc.paper_id, title, index, group)
            for index, group in enumerate(groups)
        ]

    def _group_blocks(self, blocks: list[Block]) -> list[list[Block]]:
        """`child_parent_expansion=False` -> one `Chunk` per `Block` (DATA-CONTRACTS §M3).

        `True` (V0 default) groups consecutive same-`section_path` blocks into one chunk (the
        multi-block anchoring rule, DATA-CONTRACTS.md "Provenance & structure"). This is a plain
        run-length grouping on `section_path` — no separate "attach equation to its prose"
        special case is needed: since the Parser assigns `section_path` once per block and an
        equation/table/code block shares its defining prose block's `section_path` by
        construction, grouping by contiguous `section_path` already keeps them together. Ambiguity
        this frozen interface doesn't resolve (no chunk-size cap exists in `Config`): a whole
        section becomes exactly one chunk, however long — deliberately not second-guessed with an
        invented size limit here; that knob isn't part of the V0 contract.
        """
        if not self._config.child_parent_expansion:
            return [[block] for block in blocks]
        groups: list[list[Block]] = []
        for block in blocks:
            if groups and groups[-1][-1].section_path == block.section_path:
                groups[-1].append(block)
            else:
                groups.append([block])
        return groups

    def _build_chunk(
        self, paper_id: str, title: str, index: int, group: list[Block]
    ) -> Chunk:
        # Multi-block anchoring rule: anchor/parent_id always pin the FIRST block in the group
        # (reading order) — never an average or the last block (DATA-CONTRACTS.md "Provenance &
        # structure").
        first = group[0]
        body = "\n\n".join(block.text for block in group)
        text = f"{title}\n{first.section_path}\n\n{body}"
        anchor = Anchor(
            paper_id=paper_id,
            block_id=first.block_id,
            page=first.page,
            bbox=first.bbox,
            snippet=_snippet(first.text),
            section_path=first.section_path,
        )
        return Chunk(
            chunk_id=f"{paper_id}:c{index}",
            paper_id=paper_id,
            text=text,
            anchor=anchor,
            section_path=first.section_path,
            parent_id=first.block_id,
            contextual_header=None,  # V1-only (ADR-07) — never populated in V0.
        )
