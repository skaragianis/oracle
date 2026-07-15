import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import chromadb

from oracle.common.db import PACKAGE_ROOT

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
COLLECTION_NAME = "chunks"

DEFAULT_VECTOR_DB_PATH = Path(
    os.environ.get("ORACLE_VECTOR_DB_PATH") or PACKAGE_ROOT / "data" / "vectors"
)
DEFAULT_MODEL_CACHE_DIR = Path(
    os.environ.get("ORACLE_MODEL_CACHE_DIR") or PACKAGE_ROOT / "data" / "models"
)


class Embedder(Protocol):
    def query_embed(self, query: str) -> Iterable[Any]: ...

    def passage_embed(self, texts: Iterable[str]) -> Iterable[Any]: ...


@dataclass
class ChunkToIndex:
    chunk_id: int
    text: str


@dataclass
class VectorMatch:
    chunk_id: int
    distance: float


class VectorIndex:
    def __init__(self, collection: chromadb.Collection, embedder: Embedder) -> None:
        self._collection = collection
        self._embedder = embedder

    def index_chunks(self, doc_id: int, chunks: Sequence[ChunkToIndex]) -> None:
        if not chunks:
            return
        embeddings = self._embedder.passage_embed(chunk.text for chunk in chunks)
        self._collection.upsert(
            ids=[str(chunk.chunk_id) for chunk in chunks],
            embeddings=[[float(value) for value in vector] for vector in embeddings],
            metadatas=[{"doc_id": doc_id} for _ in chunks],
        )

    def delete_document(self, doc_id: int) -> None:
        self._collection.delete(where={"doc_id": doc_id})

    def search(self, query: str, limit: int) -> list[VectorMatch]:
        vector = next(iter(self._embedder.query_embed(query)))
        result = self._collection.query(
            query_embeddings=[[float(value) for value in vector]],
            n_results=limit,
            include=["distances"],
        )
        distances = result["distances"]
        assert distances is not None
        return [
            VectorMatch(chunk_id=int(chunk_id), distance=distance)
            for chunk_id, distance in zip(result["ids"][0], distances[0])
        ]


def open_vector_index(
    vector_db_path: Path = DEFAULT_VECTOR_DB_PATH,
    model_cache_dir: Path = DEFAULT_MODEL_CACHE_DIR,
) -> VectorIndex:
    """Downloads the embedding model on first use — call at startup, not per request."""
    from fastembed import TextEmbedding

    embedder = TextEmbedding(EMBEDDING_MODEL_NAME, cache_dir=str(model_cache_dir))
    client = chromadb.PersistentClient(path=str(vector_db_path))
    collection = client.get_or_create_collection(
        COLLECTION_NAME, configuration={"hnsw": {"space": "cosine"}}
    )
    return VectorIndex(collection, embedder)


_default_vector_index: VectorIndex | None = None


def get_default_vector_index() -> VectorIndex:
    global _default_vector_index
    if _default_vector_index is None:
        _default_vector_index = open_vector_index()
    return _default_vector_index
