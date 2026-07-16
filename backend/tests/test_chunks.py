import sqlite3
from pathlib import Path

import pytest

from oracle.common.chunks import create_chunk
from oracle.common.db import apply_migrations
from oracle.common.documents import create_document


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(tmp_path / "test.db")
    apply_migrations(connection)
    return connection


@pytest.fixture
def doc_id(conn: sqlite3.Connection) -> int:
    return create_document(
        conn,
        filename="report.pdf",
        stored_filename="123e4567-e89b-12d3-a456-426614174000.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
    )


def test_create_chunk_inserts_row_with_defaults(
    conn: sqlite3.Connection, doc_id: int
) -> None:
    chunk_id = create_chunk(conn, doc_id=doc_id, seq=0, text="hello world")

    row = conn.execute(
        "SELECT doc_id, seq, text, page_number, paragraph_start, paragraph_end, "
        "char_start, char_end FROM chunks WHERE id = ?",
        (chunk_id,),
    ).fetchone()

    assert row == (doc_id, 0, "hello world", None, None, None, None, None)


def test_create_chunk_inserts_row_with_optional_fields(
    conn: sqlite3.Connection, doc_id: int
) -> None:
    chunk_id = create_chunk(
        conn,
        doc_id=doc_id,
        seq=1,
        text="hello world",
        page_number=3,
        paragraph_start=1,
        paragraph_end=2,
        char_start=100,
        char_end=150,
    )

    row = conn.execute(
        "SELECT doc_id, seq, text, page_number, paragraph_start, paragraph_end, "
        "char_start, char_end FROM chunks WHERE id = ?",
        (chunk_id,),
    ).fetchone()

    assert row == (doc_id, 1, "hello world", 3, 1, 2, 100, 150)
