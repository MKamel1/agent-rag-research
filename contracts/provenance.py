"""Provenance & structure (DATA-CONTRACTS.md "Provenance & structure") — the shapes every
retrievable item's grounding is built from. `Block` is the parser's fine-grained layout unit;
`Anchor` is what a `Chunk`/`GroundedResult` points back at to prove where its text came from.
See DATA-CONTRACTS.md for the multi-block anchoring rule (a multi-block `Chunk`'s `anchor`
always points at the *first* block).
"""

from typing import Annotated, Literal

from pydantic import BeforeValidator, Field

from contracts._base import FrozenModel


def _coerce_bbox_sequence(value: object) -> object:
    """Let a `list` through as a `tuple` before pydantic's `strict=True` tuple check runs.

    Why: `DATA-CONTRACTS.md`'s SQLite schema stores `bbox`/`anchor` as JSON `TEXT`
    (`bbox_json TEXT`). `json.loads()` has no tuple type — it always hands back a `list` — so a
    `strict=True` model rejects a perfectly valid, round-tripped bbox with `ValidationError:
    bbox — Input should be a valid tuple`. That's a failure mode the pydantic translation
    *introduces* (the original `@dataclass` shape had no runtime type check to trip over); this
    validator closes it at the type definition instead of leaving every future caller to
    remember "cast to tuple before constructing" (APoSD: define the error out of existence).

    Only `list`/`tuple` are accepted here — anything else (e.g. a string) is passed through
    unchanged so pydantic's own strict-mode error still fires, with its normal message, instead
    of this validator silently attempting something clever with an unexpected type. Length/
    element-type checking (exactly 4 floats) still happens afterwards, in pydantic's normal
    strict validation of the tuple — this validator only fixes the container type, not arity.
    """
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return value


# Attached directly to the type alias (not repeated as a `@field_validator` on each model) so
# every field typed `bbox: Bbox` gets the coercion "for free," including `Figure`/`TableItem` in
# `contracts/parser.py`, which import this alias rather than redeclare the field. Considered
# putting the validator function in `contracts/_base.py` instead, next to `FrozenModel` — rejected
# because `_base.py` is about model-level config (frozen/strict/extra), a decision every shape
# shares; this is a field-level concern specific to one type, and belongs next to the type it
# fixes so a reader doesn't have to jump files to see why `Bbox` behaves this way.
Bbox = Annotated[
    tuple[float, float, float, float], BeforeValidator(_coerce_bbox_sequence)
]  # (x0, y0, x1, y1) in PDF page coordinates

BlockType = Literal["prose", "equation", "code", "table", "caption"]


class Anchor(FrozenModel):
    """What grounds any retrievable item to its source. No anchor -> the item is invalid (PRD §6A).
    Block-level, NOT char offsets (char offsets do not survive PDF->markdown; CONTEXT.md).

    `snippet`: the first ~200 characters of the anchoring block's `text`, truncated at the
    nearest preceding word boundary, verbatim — never paraphrased/summarized/reformatted. Used
    for (1) display previews and (2) a cheap re-grounding check (must be a substring of
    `DocumentStore.get_span` for the same anchor).
    """

    paper_id: str
    block_id: str  # the source block this item came from
    page: int = Field(ge=0)  # 0-indexed page in the PDF
    bbox: Bbox
    snippet: str
    section_path: str  # e.g. "3. Method > 3.2 Estimator"


class Block(FrozenModel):
    """One layout block from the parser, in reading order. The unit provenance anchors point at.

    Invariant (DATA-CONTRACTS.md "Parser invariant"): every `Block` must carry a valid
    `page`/`bbox` — a block missing them is a contract violation, never faked as
    `bbox=(0,0,0,0)`. This model does not enforce "valid" beyond typing (page >= 0); the parser
    adapter is responsible for never constructing a block it doesn't have real coordinates for.
    """

    block_id: str
    paper_id: str
    text: str  # for equations: the LaTeX; for code: the code
    type: BlockType
    page: int = Field(ge=0)
    bbox: Bbox
    section_path: str  # AUTHORITATIVE — assigned once by the Parser (M2). Every other copy of
    # section_path (Chunk, Anchor) is a derived value, never re-derived.
    index: int = Field(ge=0)  # reading-order position within the paper
