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

# A whole section becomes one chunk (see `_group_blocks`) with no size cap -- fine for most
# sections, but a real corpus check found long unbroken proof/appendix sections with no internal
# sub-headings routinely produce one giant chunk: 7.6% of real chunks across a 34-paper sample
# exceeded ~4,000 tokens, in 71% of papers, up to a real 29,844-word (~65,700-token) single chunk
# -- larger than the embedding model's own 40,960-token capacity. Silently truncated by the
# embedding server today rather than ever reaching it whole, and even where it wouldn't be
# truncated, cramming an entire multi-page proof into one embedding vector defeats the point of
# chunking for retrieval regardless. 1,500 words sits at roughly this corpus's real p90 chunk size
# (measured, not guessed) -- most sections already fit; only the real long tail gets split.
# ponytail: a plain module constant, not a `Config` field -- `contracts/config.py` is a
# CODEOWNERS-protected foundation path (needs the foundation-change process), and this is a
# technical safety ceiling like `rag/summarizer.py`'s `_NUM_CTX_CEILING`, not a scope lever.
_MAX_CHUNK_WORDS = 1500

# A sub-chunk born from splitting an oversized section can open mid-argument ("as established
# above, we then have...") with "above" now in a *different* chunk -- carrying the immediately
# preceding sub-chunk's last block forward closes that gap, the same way `child_parent_expansion`
# already merges multiple blocks' text into one `Chunk.text` while `anchor`/`parent_id` stay
# pinned to only the first block (DATA-CONTRACTS.md "Provenance & structure": anchor is for
# citation display, not the source of the passage content). Gated by size, not block type -- the
# split point is always right before a *prose* block, and that prose often refers back to the
# *equation* just before it, so restricting to prose-only would exclude the useful case. 250 words
# comfortably covers a typical lead-in paragraph (real corpus median chunk is ~440 words) while
# skipping oversized trailing blocks, which are skipped rather than truncated -- truncating could
# bisect an equation, exactly the failure mode the split-point rule above exists to avoid.
# ponytail: a retrieval-quality tuning knob, not a semantic contract; reasonable range 150-300.
_OVERLAP_MAX_WORDS = 250


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
        sized_groups = [sub for group in groups for sub in self._split_oversized(group)]
        return [
            self._build_chunk(doc.paper_id, title, index, group, overlap)
            for index, (group, overlap) in enumerate(sized_groups)
        ]

    def _group_blocks(self, blocks: list[Block]) -> list[list[Block]]:
        """`child_parent_expansion=False` -> one `Chunk` per `Block` (DATA-CONTRACTS §M3).

        `True` (V0 default) groups consecutive same-`section_path` blocks into one chunk (the
        multi-block anchoring rule, DATA-CONTRACTS.md "Provenance & structure"). This is a plain
        run-length grouping on `section_path` — no separate "attach equation to its prose"
        special case is needed: since the Parser assigns `section_path` once per block and an
        equation/table/code block shares its defining prose block's `section_path` by
        construction, grouping by contiguous `section_path` already keeps them together. This
        method alone doesn't cap size — `_split_oversized` does that as a second pass over each
        group's result, not here, so this stays a pure "what belongs together" grouping.
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

    def _split_oversized(
        self, group: list[Block]
    ) -> list[tuple[list[Block], Block | None]]:
        """Splits a `_group_blocks` group once it exceeds `_MAX_CHUNK_WORDS`, in reading order.
        Each returned sub-group is paired with an overlap block (the immediately preceding
        sub-group's last block, carried forward -- see `_OVERLAP_MAX_WORDS`) or `None` for the
        first sub-group of a split and for the non-split fast path.

        A split point may only fall directly before a `type == "prose"` block -- never before an
        equation/code/table/caption block -- so a split can never separate one of those from the
        prose that introduces it (ARCHITECTURE.md §M3: "equations/code never split from defining
        context"). A single block bigger than the cap on its own is left whole either way (blocks
        are this module's atomic unit; that's a Parser-level anomaly, not this function's job).
        """
        if sum(len(block.text.split()) for block in group) <= _MAX_CHUNK_WORDS:
            return [(group, None)]
        sub_groups: list[list[Block]] = []
        current: list[Block] = []
        current_words = 0
        for block in group:
            block_words = len(block.text.split())
            over_cap_if_added = current_words + block_words > _MAX_CHUNK_WORDS
            if current and over_cap_if_added and block.type == "prose":
                sub_groups.append(current)
                current = []
                current_words = 0
            current.append(block)
            current_words += block_words
        sub_groups.append(current)

        result: list[tuple[list[Block], Block | None]] = [(sub_groups[0], None)]
        for prev, sub in zip(sub_groups, sub_groups[1:]):
            last = prev[-1]
            overlap = last if len(last.text.split()) <= _OVERLAP_MAX_WORDS else None
            result.append((sub, overlap))
        return result

    def _build_chunk(
        self,
        paper_id: str,
        title: str,
        index: int,
        group: list[Block],
        overlap: Block | None = None,
    ) -> Chunk:
        # Multi-block anchoring rule: anchor/parent_id always pin the FIRST block in the group
        # (reading order) — never an average or the last block (DATA-CONTRACTS.md "Provenance &
        # structure"). `overlap` (a carried-forward block from the *previous* sub-chunk, see
        # `_split_oversized`) is prepended into the body text only -- it never becomes `first`,
        # so anchor/parent_id/section_path stay pinned to this chunk's own true start.
        first = group[0]
        body_blocks = ([overlap.text] if overlap else []) + [b.text for b in group]
        body = "\n\n".join(body_blocks)
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
