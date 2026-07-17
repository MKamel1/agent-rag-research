"""`python -m app.reembed_experiment` -- T-DOC41 (Contextual Retrieval spike) A/B re-embed script.

Builds evidence for whether prepending a summary-conditioned "contextual header" to a chunk's text
before embedding (Approach A) improves retrieval over today's bare "title + section_path" glue-on
(`rag/chunker.py`'s `_build_chunk`, the `text` field). This script does the re-embedding for both
arms of that A/B; a separate eval slice + runner (another ticket) measures which one retrieves
better.

- `--no-headers` (the default, the baseline arm): embed text = the chunk's existing `text`,
  unchanged.
- `--with-headers`: embed text = the header the generation LLM writes (via
  `rag/contextual_header.ContextualHeaderGenerator`, conditioned on that paper's already-generated
  summary) followed by `"\\n\\n"` and the chunk's unmodified `text`. Generated headers are recorded
  to `--headers-out` as `{chunk_id: header}` -- never written into `contracts/vector_index.py`'s
  frozen `VectorPayload` shape, and never back into the corpus's `papers.db` (that contract's
  `contextual_header` field stays a V1-only, always-`None` column, PRD ADR-07 -- unrelated to this
  spike's own use of the same English word).

Both arms read the SAME `paper_ids` from the corpus store and upsert the SAME `chunk_id`s into the
target `--collection` -- only the text handed to the embedder differs between them. That matched
set is what lets the later measurement attribute a retrieval difference to the header itself, not
to a corpus-size difference between the two runs (module docstring's whole point).

This is a SPIKE script gathering before/after evidence, not a new production ingest path -- it
never touches the corpus's `papers.db` beyond reading it (`DocumentStore.get()`/`iter_papers()`
only; `put()`/`delete()` are never called here) and never upserts into the production vector-store
collection (`--collection` is required, with no default, and is checked against `Config.collection`
below so an operator can't point this at the live collection by omission).

Same GPU-serialization discipline as `app/benchmark.py`/`app/parse_phase.py`: one `GpuLock` (real
`rag.gpu_lock.FileGpuLock`, `Config.gpu_lock_path`) shared across the header generator and the
embedder, so this script's real (GPU) run never contends with a concurrently-running ingest/serve
process on the one GPU.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Protocol

import httpx

from contracts.document_store import PaperRecord
from contracts.embedder import EmbedderInfo, Vector
from contracts.errors import PermanentError
from contracts.vector_index import VectorPayload
from rag.config import load_config
from rag.contextual_header import ContextualHeaderGenerator
from rag.document_store import DocumentStore
from rag.embedder import TeiEmbedder
from rag.gpu_lock import FileGpuLock
from rag.vector_index import VectorIndex

logger = logging.getLogger(__name__)

# Service endpoints -- same "one dev workstation, nothing here varies yet" rationale as
# `app/assembly.py`'s own module-level constants (that file's docstring). What DOES vary across an
# A/B run here -- the target collection, whether headers are generated, the header model -- is a
# CLI arg (below), not a constant, since varying those is this whole script's job.
_EMBEDDER_URL = "http://localhost:8080"
_HEADER_LLM_URL = "http://localhost:11434"
_VECTOR_STORE_HOST = "localhost"
_VECTOR_STORE_PORT = 6333
# Must match the real embedder actually serving at `_EMBEDDER_URL` -- same values
# `app/assembly.py` uses, since this script's real (GPU) run re-embeds into a collection meant to
# be compared apples-to-apples against the production one.
_EMBEDDER_INFO = EmbedderInfo(model_id="Qwen3-Embedding-4B", dim=2560, version="v1")


class ReembedError(RuntimeError):
    """The requested run can't proceed as configured -- an unknown paper id, a missing
    `header_generator` in `--with-headers` mode, or `--collection` pointed at the live production
    collection. Distinct from `contracts/errors.py`'s three-class taxonomy: those classify a
    single chunk/paper's outcome mid-run (retry/quarantine); this classifies the run's own setup,
    which this script refuses to start rather than partially run.
    """


class _EmbedderSeam(Protocol):
    @property
    def info(self) -> EmbedderInfo: ...
    def embed(self, texts: list[str]) -> list[Vector]: ...


class _VectorStore(Protocol):
    def upsert(self, id: str, vector: Vector, payload: VectorPayload) -> None: ...


class _DocumentStore(Protocol):
    def get(self, paper_id: str) -> PaperRecord | None: ...


class _HeaderGenerator(Protocol):
    def generate(self, summary_text: str, chunk_text: str) -> str: ...


def reembed(
    *,
    document_store: _DocumentStore,
    embedder: _EmbedderSeam,
    vector_index: _VectorStore,
    header_generator: _HeaderGenerator | None,
    paper_ids: list[str],
    with_headers: bool,
) -> dict[str, str]:
    """Runs one A/B arm: embeds and upserts every chunk of every paper in `paper_ids` into
    `vector_index`, upserting the SAME `chunk_id`s regardless of `with_headers` -- what varies
    between the two arms is only the text handed to `embedder.embed()`, never which chunks get
    upserted (the matched-A/B property this module's docstring relies on downstream).

    Precondition: every id in `paper_ids` must resolve via `document_store.get()` -- an unknown
    paper id is a `ReembedError` (refuse the whole run rather than silently produce a
    smaller-than-requested, and therefore no-longer-matched-against-a-prior-run, corpus).
    `header_generator` must be given (non-`None`) when `with_headers=True`; ignored otherwise.

    Postcondition: returns `{chunk_id: header}` for every chunk a header was actually generated
    for -- empty in `--no-headers` mode. A chunk whose header generation is skipped (empty
    summary, `ContextualHeaderGenerator`'s own documented precondition) or fails
    (`PermanentError`, e.g. a bad generation-LLM response for that one chunk) is still embedded
    and upserted with its own unmodified `chunk.text` -- it is never dropped from the matched set,
    it just has no header entry in the returned dict.
    """
    if with_headers and header_generator is None:
        raise ReembedError("with_headers=True requires a header_generator")

    ids: list[str] = []
    texts: list[str] = []
    payloads: list[VectorPayload] = []
    headers_written: dict[str, str] = {}

    for paper_id in paper_ids:
        record = document_store.get(paper_id)
        if record is None:
            raise ReembedError(f"{paper_id}: not found in the corpus store")

        for chunk in record.chunks:
            embed_text = chunk.text
            if with_headers:
                assert header_generator is not None  # checked above; narrows the type for mypy
                try:
                    header = header_generator.generate(record.summary_text, chunk.text)
                except PermanentError:
                    logger.warning(
                        "%s: header generation failed for chunk %s -- embedding this chunk's "
                        "unmodified text instead so the matched A/B chunk set is preserved",
                        paper_id,
                        chunk.chunk_id,
                    )
                    header = ""
                if header:
                    embed_text = f"{header}\n\n{chunk.text}"
                    headers_written[chunk.chunk_id] = header

            ids.append(chunk.chunk_id)
            texts.append(embed_text)
            payloads.append(
                VectorPayload(
                    paper_id=paper_id,
                    kind="chunk",
                    section_path=chunk.section_path,
                    # Always the chunk's own real passage text -- NOT `embed_text` -- so the
                    # sparse/keyword channel indexes identical content in both arms; only the
                    # dense embedding differs between --no-headers/--with-headers, isolating the
                    # header's effect (module docstring).
                    text=chunk.text,
                    categories=list(record.ref.categories),
                    published=record.ref.published.isoformat(),
                    embedding_version=embedder.info.version,
                )
            )

    vectors = embedder.embed(texts)
    for chunk_id, vector, payload in zip(ids, vectors, payloads, strict=True):
        vector_index.upsert(chunk_id, vector, payload)

    return headers_written


def _check_collection_is_not_production(collection: str, production_collection: str) -> None:
    """Refuses to run against the live collection (`Config.collection`, default `"papers"`) --
    `--collection` has no default of its own specifically so an operator can't reach this by
    omission (`_parse_args` below)."""
    if collection == production_collection:
        raise ReembedError(
            f"--collection must not be the production collection ({production_collection!r}) -- "
            "pass a throwaway name for this experiment"
        )


def _write_headers_out(path: str | None, headers: dict[str, str]) -> None:
    if path:
        Path(path).write_text(json.dumps(headers, indent=2))


def _paper_ids_from_args(args: argparse.Namespace) -> list[str]:
    if args.paper_ids:
        return [p.strip() for p in args.paper_ids.split(",") if p.strip()]
    if args.paper_ids_file:
        return [
            line.strip()
            for line in Path(args.paper_ids_file).read_text().splitlines()
            if line.strip()
        ]
    raise ReembedError("one of --paper-ids / --paper-ids-file is required")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default="config.yaml", help="base config.yaml (db_path/blob_dir/gpu_lock_path)"
    )
    parser.add_argument("--paper-ids", default=None, help="comma-separated paper ids")
    parser.add_argument(
        "--paper-ids-file", default=None, help="path to a file of one paper id per line"
    )
    parser.add_argument(
        "--collection", required=True, help="throwaway target vector-store collection name"
    )
    headers_group = parser.add_mutually_exclusive_group()
    headers_group.add_argument("--with-headers", dest="with_headers", action="store_true")
    headers_group.add_argument("--no-headers", dest="with_headers", action="store_false")
    parser.set_defaults(with_headers=False)
    parser.add_argument(
        "--headers-out",
        default=None,
        help="write generated {chunk_id: header} JSON here (--with-headers only)",
    )
    parser.add_argument(
        "--header-model", default="qwen3:14b", help="model name the header generator requests"
    )
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()
    cfg = load_config(args.config)
    _check_collection_is_not_production(args.collection, cfg.collection)
    paper_ids = _paper_ids_from_args(args)

    gpu_lock = FileGpuLock(Path(cfg.gpu_lock_path))
    # Read-only usage discipline (module docstring): only `DocumentStore.get()` is called below --
    # `put()`/`delete()` are never invoked, so the production `papers.db` is never written.
    document_store = DocumentStore(cfg.db_path, cfg.blob_dir)
    embedder = TeiEmbedder(
        httpx.Client(base_url=_EMBEDDER_URL, timeout=60.0), gpu_lock, _EMBEDDER_INFO
    )
    vector_index = VectorIndex(
        _VECTOR_STORE_HOST, _VECTOR_STORE_PORT, args.collection, _EMBEDDER_INFO.dim
    )
    header_generator = (
        ContextualHeaderGenerator(
            httpx.Client(base_url=_HEADER_LLM_URL, timeout=300.0), gpu_lock, args.header_model
        )
        if args.with_headers
        else None
    )

    generated_headers = reembed(
        document_store=document_store,
        embedder=embedder,
        vector_index=vector_index,
        header_generator=header_generator,
        paper_ids=paper_ids,
        with_headers=args.with_headers,
    )

    _write_headers_out(args.headers_out, generated_headers)

    mode = "with-headers" if args.with_headers else "baseline (no headers)"
    print(
        f"reembed_experiment: upserted {len(paper_ids)} paper(s) into collection "
        f"{args.collection!r} ({mode}); {len(generated_headers)} header(s) generated"
    )
