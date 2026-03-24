from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from app.config import VECTOR_INDEX_DIR
from app.logging_utils import get_logger


logger = get_logger("app.vector_store")


def _paper_dir(paper_id: str) -> Path:
    return VECTOR_INDEX_DIR / paper_id


def _collection_name() -> str:
    return "paper_chunks"


def build_vector_index(
    paper_id: str, chunks: list[dict[str, Any]], embeddings: list[list[float]]
) -> bool:
    try:
        import chromadb
    except ImportError:
        logger.info("vector_index_skip | paper_id=%s | reason=chromadb_unavailable", paper_id)
        return False

    if not chunks or not embeddings:
        return False

    paper_dir = _paper_dir(paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(paper_dir))
    collection_name = _collection_name()
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(name=collection_name)
    collection.add(
        ids=[chunk["id"] for chunk in chunks],
        embeddings=embeddings,
        documents=[chunk["content"] for chunk in chunks],
        metadatas=[
            {
                "chunk_index": chunk["chunk_index"],
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
            }
            for chunk in chunks
        ],
    )
    logger.info("vector_index_built | paper_id=%s | chunks=%s", paper_id, len(chunks))
    return True


def search_vector_index(
    paper_id: str, query_embedding: list[float], top_k: int
) -> list[dict[str, Any]] | None:
    try:
        import chromadb
    except ImportError:
        return None

    paper_dir = _paper_dir(paper_id)
    if not paper_dir.exists():
        return None

    client = chromadb.PersistentClient(path=str(paper_dir))
    try:
        collection = client.get_collection(_collection_name())
    except Exception:
        return None
    response = collection.query(query_embeddings=[query_embedding], n_results=top_k)
    results: list[dict[str, Any]] = []
    ids = response.get("ids", [[]])[0]
    documents = response.get("documents", [[]])[0]
    metadatas = response.get("metadatas", [[]])[0]
    for chunk_id, document, metadata in zip(ids, documents, metadatas):
        if not chunk_id:
            continue
        metadata = metadata or {}
        results.append(
            {
                "id": chunk_id,
                "chunk_index": metadata.get("chunk_index"),
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "content": document or "",
            }
        )
    return results


def delete_vector_index(paper_id: str) -> None:
    paper_dir = _paper_dir(paper_id)
    if not paper_dir.exists():
        return
    shutil.rmtree(paper_dir, ignore_errors=True)
