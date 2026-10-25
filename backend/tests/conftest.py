import sqlite3
import uuid
import zlib
from collections.abc import Iterable, Iterator
from contextlib import closing
from pathlib import Path
from typing import cast

import chromadb
import chromadb.api.client
import pytest

from oracle.common.db import apply_migrations
from oracle.common.embeddings import VectorIndex

FAKE_DIMENSIONS = 16


class FakeEmbedder:
    """Deterministic hashed bag-of-words vectors: shared words -> nearby vectors."""

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * FAKE_DIMENSIONS
        for word in text.lower().split():
            vector[zlib.crc32(word.encode()) % FAKE_DIMENSIONS] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [value / norm for value in vector]

    def query_embed(self, query: str) -> Iterator[list[float]]:
        yield self._embed(query)

    def passage_embed(
        self, texts: Iterable[str], **kwargs: object
    ) -> Iterator[list[float]]:
        del kwargs
        for text in texts:
            yield self._embed(text)


def make_vector_index() -> VectorIndex:
    # A unique collection name per index: EphemeralClient instances with equal
    # settings share one in-memory system, so a fixed name would leak state
    # between tests.
    client = cast(chromadb.api.client.Client, chromadb.EphemeralClient())
    collection = client.create_collection(
        f"chunks-{uuid.uuid4().hex}", configuration={"hnsw": {"space": "cosine"}}
    )
    return VectorIndex(collection, FakeEmbedder(), client=client)


@pytest.fixture
def vector_index() -> VectorIndex:
    return make_vector_index()


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(tmp_path / "test.db")) as connection:
        apply_migrations(connection)
        yield connection
