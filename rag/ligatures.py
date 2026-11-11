"""Repair of PDF-ligature-damaged words ("efect" -> "effect") for the keyword arm and regex scans.

PDF extraction dropped fi/ff/ffi/fl/ffl glyphs from ~a third of the corpus. Stored chunk and block
text is NEVER changed (that would force a re-embed and break fixtures quoting the damaged
spelling); only `rag.vector_index._sparse_vector` and `DocumentStore.scan_blocks` call this.

Pure, deterministic and dependency-free. The repair data is `ligature_map.json`, generated from the
corpora by `scripts/build_ligature_map.py`; it is a JSON file (not a literal here) because it is
regenerated data of a few hundred entries, not hand-edited code. A word is touched only if its
lowercase form is a key, so a correctly spelled word is never altered.
"""

import json
import re
from bisect import bisect_right
from pathlib import Path

_MAP: dict[str, str] = json.loads(Path(__file__).with_name("ligature_map.json").read_text())
_WORD = re.compile(r"[A-Za-z]+")


def repair_token(word: str) -> str:
    """Repair one alphabetic word, keeping lower / Title / UPPER case. Mixed case (camelCase
    identifiers) is left alone."""
    fixed = _MAP.get(word.lower())
    if fixed is None:
        return word
    if word.islower():
        return fixed
    if word.isupper():
        return fixed.upper()
    if word.istitle():
        return fixed.capitalize()
    return word


def _repair_word(match: re.Match) -> str:
    return repair_token(match.group())


def repair_ligatures(text: str) -> str:
    """Repair every damaged alphabetic word in `text`; punctuation/whitespace are untouched."""
    return _WORD.sub(_repair_word, text)


def repair_with_offsets(text: str):
    """Returns `(repaired, to_original)`. `to_original(pos, end=False)` maps an offset in
    `repaired` back to `text`: a position inside a repaired word snaps to that word's start (or
    its end when `end=True`), so a span found in repaired text always covers whole original words.
    """
    new_starts: list[int] = []
    new_ends: list[int] = []
    old_starts: list[int] = []
    old_ends: list[int] = []
    parts: list[str] = []
    last = 0
    new_len = 0
    for m in _WORD.finditer(text):
        fixed = repair_token(m.group())
        if fixed == m.group():
            continue
        parts.append(text[last:m.start()])
        new_len += m.start() - last
        new_starts.append(new_len)
        new_len += len(fixed)
        new_ends.append(new_len)
        old_starts.append(m.start())
        old_ends.append(m.end())
        parts.append(fixed)
        last = m.end()
    parts.append(text[last:])
    repaired = "".join(parts)

    def to_original(pos: int, end: bool = False) -> int:
        i = bisect_right(new_starts, pos) - 1  # last repaired word starting at or before pos
        if i < 0:
            return pos
        if pos < new_ends[i]:
            return old_ends[i] if end and pos > new_starts[i] else old_starts[i]
        return pos - new_ends[i] + old_ends[i]

    return repaired, to_original
