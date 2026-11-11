"""Derive the ligature-repair map (rag/ligature_map.json) from the corpora themselves, read-only.

PDF extraction dropped fi/ff/ffi/fl/ffl glyphs, leaving the first "f" (or nothing) behind:
"efect" (ff), "specifc" (fi), "frst" (fi), "fow" (fl), "eficient"/"coefcient" (ffi). So a broken
token T is a real word W with one of {f, i, l, fi, fl} inserted right after one of its "f"s
removed. T -> W is accepted only when W is frequent, T is rare relative to W, EXACTLY ONE
candidate qualifies, and T is not a real English word (/usr/share/dict/words when present, else
corpus frequency alone -- the report says which).

Usage: python -m scripts.build_ligature_map [--db PATH ...] [--min-freq N] [--max-ratio R]
Opens every DB with mode=ro. Writes the map and the report.
"""

import argparse
import json
import random
import re
import sqlite3
from collections import Counter
from pathlib import Path

from scripts.census_common import rank_by_count

DEFAULT_DBS = [
    "/home/omar/ai-projects/research-system-rag-data/papers.db",
    "/home/omar/ai-projects/research-system-rag/waymo/data/papers.db",
    "/home/omar/ai-projects/research-system-rag-standards/data/papers.db",
]
DICT_PATH = Path("/usr/share/dict/words")
REPO = Path(__file__).resolve().parent.parent
MAP_PATH = REPO / "rag" / "ligature_map.json"
REPORT_PATH = (REPO / "docs/eval-reports/data/2026-11-10-ligature-census/repair-map-report.md")
# What a dropped glyph can leave behind: insert one of these right after an "f".
INSERTS = ("f", "i", "l", "fi", "fl")
# Real tokens a dictionary cannot know (surnames, jargon) that run 1 of the review wrongly repaired.
# Short tokens (<= 3 letters) are excluded wholesale by min_len: they are mostly acronyms
# (FNN, FCA, TIF, WIF) and the dictionary has none of them.
NEVER_REPAIR = frozenset({"fetcher", "hofman", "jefrey", "grifin", "clif", "fint", "feets",
                          "fash", "fies", "reft", "difs", "fips", "fres"})
_TOKEN = re.compile(r"[a-z]+")


def count_tokens(db_paths: list[str]) -> Counter:
    """Lowercase alphabetic token counts over every chunk text, DBs opened read-only."""
    counts: Counter = Counter()
    for path in db_paths:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            for (text,) in con.execute("SELECT text FROM chunks"):
                counts.update(_TOKEN.findall((text or "").lower()))
        finally:
            con.close()
    return counts


def candidates(token: str) -> set[str]:
    """Every word obtainable by re-inserting a dropped glyph remainder after one "f"."""
    return {token[: i + 1] + ins + token[i + 1:]
            for i, ch in enumerate(token) if ch == "f" for ins in INSERTS}


def load_dictionary() -> set[str] | None:
    if not DICT_PATH.exists():
        return None
    return {w.strip().lower() for w in DICT_PATH.read_text(errors="ignore").splitlines()}


def build_map(counts: Counter, real_words: set[str] | None, min_freq: int = 50,
              max_ratio: float = 5.0, min_len: int = 4,
              nondict_min_freq: int = 500
              ) -> tuple[dict[str, str], list[tuple[str, list[str]]]]:
    """Returns (mapping, skipped_ambiguous). T must not be a real word and W must be one (when a
    dictionary is available) -- a damaged-but-frequent form such as "coeficient" is thereby never
    chosen as a target. The ratio bound is loose (default 5x) because damage is so systematic that
    "efect" is MORE common than "effect" in the corpus; the dictionary, not rarity, carries the
    safety. A target missing from the dictionary ("differentiable") is still accepted when very
    frequent (`nondict_min_freq`) and not itself a damaged token the dictionary pass repairs
    ("coeficient"). `real_words=None` -> corpus frequency alone decides both."""
    if real_words is not None and nondict_min_freq < 10**18:
        base, _ = build_map(counts, real_words, min_freq, max_ratio, min_len, 10**18)
        broken = set(base)
    else:
        broken = set()

    def target_ok(w: str, n: int) -> bool:
        if real_words is None or w in real_words:
            return counts.get(w, 0) >= min_freq and n <= max_ratio * counts[w]
        return (counts.get(w, 0) >= nondict_min_freq and w not in broken
                and n <= max_ratio * counts[w])

    mapping: dict[str, str] = {}
    ambiguous: list[tuple[str, list[str]]] = []
    for token, n in counts.items():
        if len(token) < min_len or token in NEVER_REPAIR or "f" not in token:
            continue
        if real_words is not None and token in real_words:
            continue
        good = sorted(w for w in candidates(token) if target_ok(w, n))
        if len(good) == 1:
            mapping[token] = good[0]
        elif len(good) > 1:
            ambiguous.append((token, good))
    return dict(sorted(mapping.items())), sorted(ambiguous)


def write_report(mapping, ambiguous, counts, source, params, seed=0) -> str:
    top = rank_by_count({t: counts[t] for t in mapping}, 50)
    sample = random.Random(seed).sample(sorted(mapping.items()), min(100, len(mapping)))
    lines = [
        "# Ligature repair map report", "",
        f"- real-word check: {source}", f"- parameters: {params}",
        f"- mappings: {len(mapping)}", f"- skipped ambiguous: {len(ambiguous)}", "",
        "## 50 most frequent mappings", "",
        *[f"- {t} -> {mapping[t]} ({n})" for t, n in top], "",
        "## Skipped ambiguous tokens", "",
        *[f"- {t}: {', '.join(c)}" for t, c in ambiguous], "",
        f"## 100 random mappings (seed {seed})", "",
        *[f"- {t} -> {w} ({counts[t]} vs {counts[w]})" for t, w in sample], "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="append")
    ap.add_argument("--min-freq", type=int, default=50)
    ap.add_argument("--max-ratio", type=float, default=5.0)
    args = ap.parse_args()
    counts = count_tokens(args.db or DEFAULT_DBS)
    real = load_dictionary()
    mapping, ambiguous = build_map(counts, real, args.min_freq, args.max_ratio)
    MAP_PATH.write_text(json.dumps(mapping, indent=0, sort_keys=True) + "\n")
    source = f"{DICT_PATH} ({len(real)} words)" if real else "corpus frequency alone (no dict file)"
    REPORT_PATH.write_text(write_report(
        mapping, ambiguous, counts, source,
        f"min_freq={args.min_freq}, max_ratio={args.max_ratio}"))
    print(len(mapping), "mappings;", len(ambiguous), "ambiguous")


if __name__ == "__main__":
    main()
