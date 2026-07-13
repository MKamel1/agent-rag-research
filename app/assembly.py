"""Composition roots: wires real (non-fake) adapters into `IngestionOrchestrator` (M9) and
`McpServer` (M8) — the two places ARCHITECTURE.md's "Operational invariants" §3 says a real
`GpuLock` must be shared across process boundaries.

# ponytail: service endpoints/model ids are constants here, not `Config` fields — they don't vary
# yet (one dev workstation, one model per seam). Promote to `Config` if a second environment or
# model choice ever needs to differ.
"""

from pathlib import Path

import httpx

from contracts.config import Config
from contracts.embedder import EmbedderInfo
from contracts.errors import PermanentError
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from rag.chunker import Chunker
from rag.document_store import DocumentStore
from rag.embedder import TeiEmbedder
from rag.gpu_lock import FileGpuLock
from rag.harvester import ArxivSource, Harvester
from rag.ingest_state_sqlite import SqliteIngestState
from rag.mcp_server import McpServer
from rag.orchestrator import IngestionOrchestrator
from rag.parser import parse as parse_pdf_bytes
from rag.reranker import TeiReranker
from rag.retriever import Retriever
from rag.summarizer import OllamaSummarizer
from rag.vector_index import VectorIndex

_TEI_EMBED_URL = "http://localhost:8080"
_TEI_RERANK_URL = "http://localhost:8082"
_OLLAMA_URL = "http://localhost:11434"
_OLLAMA_MODEL = "qwen3:14b"
_RERANK_MODEL = "BGE-reranker-v2-m3"
_EMBEDDER_INFO = EmbedderInfo(model_id="Qwen3-Embedding-4B", dim=2560, version="v1")
_QDRANT_HOST = "localhost"
_QDRANT_PORT = 6333


class _PdfDownloadParser:
    """Bridges `IngestionOrchestrator`'s `parser.parse(ref: PaperRef)` call to the real Parser
    module's frozen `parse(raw: bytes) -> ParsedDoc` interface — the Orchestrator hands a
    `PaperRef`, the real Parser wants PDF bytes. Lives here, not in `rag/parser.py`: downloading
    is composition-root wiring, not part of the Parser module's own contract.
    """

    def __init__(self, client: httpx.Client):
        self._client = client

    def parse(self, ref: PaperRef) -> ParsedDoc:
        try:
            resp = self._client.get(ref.pdf_url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise PermanentError(f"failed to download PDF from {ref.pdf_url}: {e}") from e
        return parse_pdf_bytes(resp.content)


def build_ingestion_orchestrator(
    config: Config, *, db_path: str | None = None, blob_dir: str | None = None,
    collection: str = "papers",
) -> IngestionOrchestrator:
    gpu_lock = FileGpuLock(Path(config.gpu_lock_path))
    db_path = db_path or "papers.db"
    blob_dir = blob_dir or "blobs"

    harvester = Harvester(ArxivSource())
    parser = _PdfDownloadParser(httpx.Client(timeout=60.0))
    chunker = Chunker(config)
    summarizer = OllamaSummarizer(
        httpx.Client(base_url=_OLLAMA_URL, timeout=300.0), gpu_lock, _OLLAMA_MODEL
    )
    embedder = TeiEmbedder(httpx.Client(base_url=_TEI_EMBED_URL, timeout=60.0), gpu_lock, _EMBEDDER_INFO)
    document_store = DocumentStore(db_path, blob_dir)
    vector_index = VectorIndex(
        _QDRANT_HOST, _QDRANT_PORT, collection, _EMBEDDER_INFO.dim, config.hybrid_dense_weight
    )
    state = SqliteIngestState(db_path)

    return IngestionOrchestrator(
        harvester, parser, chunker, summarizer, embedder, document_store, vector_index,
        state, gpu_lock, config,
    )


def build_mcp_server(
    config: Config, *, db_path: str | None = None, blob_dir: str | None = None,
    collection: str = "papers",
) -> McpServer:
    gpu_lock = FileGpuLock(Path(config.gpu_lock_path))  # same path as the ingest root -> same file
    db_path = db_path or "papers.db"
    blob_dir = blob_dir or "blobs"

    embedder = TeiEmbedder(httpx.Client(base_url=_TEI_EMBED_URL, timeout=60.0), gpu_lock, _EMBEDDER_INFO)
    document_store = DocumentStore(db_path, blob_dir)
    vector_index = VectorIndex(
        _QDRANT_HOST, _QDRANT_PORT, collection, _EMBEDDER_INFO.dim, config.hybrid_dense_weight
    )
    reranker = TeiReranker(httpx.Client(base_url=_TEI_RERANK_URL, timeout=60.0), gpu_lock, _RERANK_MODEL)
    retriever = Retriever(embedder, vector_index, document_store, reranker)

    return McpServer(retriever, document_store)
