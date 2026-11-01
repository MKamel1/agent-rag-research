"""Chunker (M3) — see `contracts/chunker.py` for the `Chunk` shape (do not re-derive its fields
here) and DATA-CONTRACTS.md "Provenance & structure" for the multi-block anchoring rule this
module implements. ARCHITECTURE.md §M3 is the interface source of truth.

Zero-GPU, zero-network (ARCHITECTURE §M3 "Seam: none needed") — no vendor/LLM client is injected
here in V0. Do NOT add contextual-header generation (PRD ADR-07, V1-only) — see the
`contextual_header` docstring on `contracts/chunker.Chunk`; every `Chunk` emitted here carries
`contextual_header=None`.
"""

import re

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor, Block

_SNIPPET_MAX_CHARS = 200

# Derived retrieval text is deliberately smaller than the production MCP excerpt limit.
# These are implementation ceilings, not new frozen Config fields. Equation/code context
# remains atomic, so a scientific defining block can exceed the ceiling intentionally.
_MAX_CHUNK_WORDS = 220
_MAX_CHUNK_CHARS = 1200
_OVERLAP_MAX_WORDS = 40
_OVERLAP_MAX_CHARS = 200
_TINY_HEADING_WORDS = 25


def _normalize_text(text: str) -> str:
    """Repair conservative extraction artifacts in derived prose/table text only.

    Raw Blocks and citation snippets are never rewritten. Protected code/math spans are
    copied verbatim. Lowercase word joins are repaired only for observed unambiguous
    compounds; guessing arbitrary segmentation would corrupt technical vocabulary.
    """
    protected = re.compile(
        r"(```.*?```|`[^`]*`|\$\$.*?\$\$|\$[^$\n]*\$|\\\[.*?\\\]|\\\(.*?\\\))", re.S
    )
    repairs = {
        "moderateinjuries": "moderate injuries",
        "life-threateninginjuries": "life-threatening injuries",
        "injuries(survival": "injuries (survival",
        "ingeneral": "in general",
        "Simplycontrollable": "Simply controllable",
        "Normallycontrollable": "Normally controllable",
        "oruncontrollable": "or uncontrollable",
        "controlor": "control or",
        "andlife-threatening": "and life-threatening",
        "survivalprobable": "survival probable",
    }
    parts = protected.split(text)
    for i in range(0, len(parts), 2):
        part = parts[i]
        for old, new in repairs.items():
            part = re.sub(r"(?<![A-Za-z])" + re.escape(old) + r"(?![A-Za-z])", new, part)
        part = re.sub(r"(?<=[a-z]),(?=[A-Za-z])", ", ", part)
        part = re.sub(r"(?<=[a-z])\.(?=[A-Z][a-z])", ". ", part)
        # Only a class sequence on the same row disambiguates CO from carbon monoxide.
        lines = []
        for line in part.splitlines(keepends=True):
            def class_label(match: re.Match[str]) -> str:
                family = match.group(2)
                if re.search(r"\|\s*" + family + r"[123]\s*(?=\|)", line):
                    return match.group(1) + family + "0"
                return match.group(0)
            line = re.sub(r"(?<=\|)([ \t]*)([SEC])O(?=[ \t]*\|)", class_label, line)
            lines.append(line)
        part = "".join(lines)
        parts[i] = part
    return "".join(parts)


def _bounded_parts(text: str, words: int, chars: int) -> list[str]:
    """Lossless content windows, including a progress guarantee for a single huge token."""
    result: list[str] = []
    rest = text.strip()
    while rest:
        if len(rest) <= chars and len(rest.split()) <= words:
            result.append(rest)
            break
        matches = list(re.finditer(r"\S+", rest))
        end = min(chars, matches[min(words, len(matches)) - 1].end())
        boundary = rest.rfind(" ", 0, end + 1)
        if boundary > 0:
            end = boundary
        result.append(rest[:end])
        rest = rest[end:].lstrip()
    return result


def _table_parts(text: str, caption: str) -> list[str]:
    """Pack Markdown rows with repeated caption/header; never drop a data row.

    Ordinary headers/captions repeat in full. If the header or caption itself exceeds
    the ceiling, repeat a bounded preview and retain its complete content in the payload.
    An oversized single row is continued in bounded pieces instead of defeating the cap.
    """
    lines = text.splitlines()
    separator = next((i for i, line in enumerate(lines)
                      if re.fullmatch(r"[\s|:\-]+", line) and "---" in line), None)
    header_end = separator + 1 if separator is not None else 0
    # PDF table parsers often put an empty row before the separator and real column labels
    # immediately afterwards. Keep those short label rows, but not an entire long data row.
    if header_end and not re.search(r"[A-Za-z0-9]", lines[0]):
        while header_end < min(len(lines), separator + 4):
            line = lines[header_end]
            if len(line) > 160 or len(line.split()) > 25:
                break
            cells = [c.strip() for c in line.split("|") if c.strip()]
            labels = all(re.fullmatch(r"(?:[SEC](?:O|[0-9])|[ABCD])", c) for c in cells)
            named_header = bool(re.search(
                r"\b(?:class|methods?|ASIL|name|value|description|parameter|units?|date|type)\b",
                line, re.I,
            ))
            if not cells or not (labels or named_header):
                break
            header_end += 1
    full_header = "\n".join(lines[:header_end])
    context = "\n".join(t for t in [caption, full_header] if t)
    if len(context) > 400 or len(context.split()) > 65:
        short = _bounded_parts(context, 65, 400)[0]
        rows = lines
        # The caption lives in its own source block too; retain it here for a standalone table.
        if caption:
            rows = [caption] + rows
        context = short
    else:
        rows = lines[header_end:]
    if not rows:
        rows = [text]
        context = caption[:200]
    budget_words = max(1, _MAX_CHUNK_WORDS - len(context.split()))
    budget_chars = max(1, _MAX_CHUNK_CHARS - len(context) - 2)
    payloads: list[str] = []
    current: list[str] = []
    for row in rows:
        for part in _bounded_parts(row, budget_words, budget_chars):
            candidate = "\n".join(current + [part])
            if current and (len(candidate) > budget_chars or len(candidate.split()) > budget_words):
                payloads.append("\n".join(current))
                current = []
            current.append(part)
    if current:
        payloads.append("\n".join(current))
    return ["\n".join(t for t in [context, body] if t) for body in payloads]


def _extract_title(markdown: str) -> str:
    """First H1 line (`# Title`) in the doc's markdown. `# ` (single hash) only — `## Section`
    must not match. No H1 found -> empty string (a missing title is a markdown-quality issue for
    upstream, not something this module invents a fallback title for).
    """
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _strip_duplicate_heading(text: str, section_path: str) -> str:
    """Drop `text`'s leading line if it duplicates `section_path` (whitespace-normalized).

    `_build_chunk` already prefixes every chunk with `title\\n{section_path}` as deliberate
    embedding context (do not remove that prefix). But a group's first block is usually the
    section heading itself, so without this the heading text would also open `body` -- appearing
    twice in the embedded/displayed text. Only an exact (whitespace-normalized) match on the
    first line is stripped; real prose that happens to start a block is left untouched, and a
    first block that isn't a heading is unaffected.
    """
    first_line, _, rest = text.partition("\n")
    if " ".join(first_line.split()) == " ".join(section_path.split()):
        return rest.lstrip("\n")
    return text


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
        if self._config.child_parent_expansion:
            groups = self._merge_tiny_headings(groups)
        sources = {block.block_id: block for block in doc.blocks}
        sized_groups = [sub for group in groups for sub in self._split_oversized(group)]
        return [
            self._build_chunk(
                doc.paper_id, title, index, group, overlap, sources[group[0].block_id]
            )
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

    def _merge_tiny_headings(self, groups: list[list[Block]]) -> list[list[Block]]:
        """Attach orphan heading/term groups to their immediate definition in reading order.

        A numeric terms-clause marker can be followed by a term then an acronym whose parser
        section paths have lost their common parent. That narrow shape is recognized without
        merging arbitrary unrelated short sections or completed short definitions.
        """
        merged: list[list[Block]] = []
        index = 0
        definitions_active = False
        while index < len(groups):
            current = list(groups[index])
            path = current[0].section_path
            if re.search(r"terms and definitions", path, re.I):
                definitions_active = True
            elif re.match(r"^\d+\s", path) and not re.match(r"^3\s", path):
                definitions_active = False
            index += 1
            while (index < len(groups)
                   and sum(len(b.text.split()) for b in current) < _TINY_HEADING_WORDS):
                heading_only = all(
                    " ".join(b.text.split()) == " ".join(b.section_path.split(" > ")[-1].split())
                    or re.fullmatch(r"\d+(?:\.\d+)+", b.text.strip())
                    for b in current
                )
                if not heading_only:
                    break
                following = groups[index]
                left = current[0].section_path
                right = following[0].section_path
                same_parent = (" > " in left and " > " in right
                               and left.rsplit(" > ", 1)[0] == right.rsplit(" > ", 1)[0])
                definition_marker = definitions_active and any(
                    re.fullmatch(r"3\.\d+(?:\.\d+)*", b.text.strip()) for b in current
                )
                definition_context = bool(re.search(r"terms and definitions", left, re.I))
                if not (same_parent or definition_marker or definition_context):
                    break
                # Never swallow the next numbered term into the preceding definition.
                if re.fullmatch(r"\d+(?:\.\d+)+", following[0].text.strip()):
                    break
                current.extend(following)
                index += 1
            merged.append(current)
        return merged

    def _split_oversized(
        self, group: list[Block]
    ) -> list[tuple[list[Block], Block | None]]:
        """Bound derived prose/tables while retaining source block identity and scientific context.

        Equation/code blocks and their immediately defining prose stay atomic. Tables are
        independently row-split with repeated header/caption. All fragments retain the real
        source block id; _build_chunk takes its citation snippet from the untouched source.
        """
        if not self._config.child_parent_expansion:
            return [(group, None)]
        expanded: list[Block] = []
        for index, block in enumerate(group):
            text = block.text
            next_type = group[index + 1].type if index + 1 < len(group) else None
            previous = group[index - 1] if index else None
            if block.type == "table":
                caption = (previous.text if previous and (
                    previous.type == "caption" or re.match(r"^Table\s+\w+", previous.text)
                ) else "")
                pieces = _table_parts(_normalize_text(text), _normalize_text(caption))
            elif block.type == "prose" and next_type not in ("equation", "code"):
                pieces = _bounded_parts(_normalize_text(text), _MAX_CHUNK_WORDS, _MAX_CHUNK_CHARS)
            else:
                pieces = [text]
            expanded.extend(block.model_copy(update={"text": part}) for part in pieces)
        sub_groups: list[list[Block]] = []
        current: list[Block] = []
        for block in expanded:
            candidate = current + [block]
            over = (sum(len(b.text.split()) for b in candidate) > _MAX_CHUNK_WORDS
                    or sum(len(b.text) + 2 for b in candidate) > _MAX_CHUNK_CHARS)
            table_boundary = block.type == "table" or (current and current[-1].type == "table")
            if current and ((over and block.type not in ("equation", "code")) or table_boundary):
                sub_groups.append(current)
                current = []
            current.append(block)
        if current:
            sub_groups.append(current)
        result: list[tuple[list[Block], Block | None]] = []
        for index, sub in enumerate(sub_groups):
            overlap = None
            if index and sub[0].type != "table" and sub_groups[index - 1][-1].type != "table":
                last = sub_groups[index - 1][-1]
                if (len(last.text.split()) <= _OVERLAP_MAX_WORDS
                        and len(last.text) <= _OVERLAP_MAX_CHARS
                        and len(last.text) + sum(len(b.text) + 2 for b in sub) <= _MAX_CHUNK_CHARS
                        and len(last.text.split()) + sum(len(b.text.split()) for b in sub)
                        <= _MAX_CHUNK_WORDS):
                    overlap = last
            result.append((sub, overlap))
        return result

    def _build_chunk(
        self,
        paper_id: str,
        title: str,
        index: int,
        group: list[Block],
        overlap: Block | None = None,
        source_first: Block | None = None,
    ) -> Chunk:
        # Multi-block anchoring rule: anchor/parent_id always pin the FIRST block in the group
        # (reading order) — never an average or the last block (DATA-CONTRACTS.md "Provenance &
        # structure"). `overlap` (a carried-forward block from the *previous* sub-chunk, see
        # `_split_oversized`) is prepended into the body text only -- it never becomes `first`,
        # so anchor/parent_id/section_path stay pinned to this chunk's own true start.
        first = group[0]
        source_first = source_first or first
        # The duplicate-heading check (`_strip_duplicate_heading`) must run on `overlap`, `first`,
        # AND every block in `group[1:]` INDEPENDENTLY -- any of them can independently be a
        # heading-duplicate block (T-DOC95: a PDF extractor can emit a section heading as two (or
        # more) adjacent blocks, e.g. a running header repeated by the parser -- `group[1:]`'s
        # blocks are ordinary body content and were previously joined in raw, so a second
        # heading-only block there duplicated `section_path` in `body` exactly like `first` or
        # `overlap` could). `overlap` (a carried-forward block from the *previous* sub-chunk, see
        # `_split_oversized`) is prepended ahead of `first.text`, so checking only index 0 would
        # silently stop checking `first.text` whenever `overlap` is present -- a split's first
        # sub-group can be the section heading alone, and EITHER that heading (as the next
        # sub-chunk's `overlap`) OR the next sub-group's own opening block can independently
        # duplicate `section_path`. `first.text` itself (used for `anchor.snippet` below) is
        # untouched either way -- this only affects what goes into `body`.
        body_blocks = ([overlap] if overlap else []) + group
        raw_body_blocks = [
            _strip_duplicate_heading(
                _normalize_text(b.text) if b.type in ("prose", "table", "caption") else b.text,
                first.section_path,
            )
            for b in body_blocks
        ]
        body = "\n\n".join(t for t in raw_body_blocks if t)
        text = f"{title}\n{first.section_path}\n\n{body}"
        anchor = Anchor(
            paper_id=paper_id,
            block_id=first.block_id,
            page=first.page,
            bbox=first.bbox,
            snippet=_snippet(source_first.text),
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
