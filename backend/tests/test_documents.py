import sqlite3

import pytest

from oracle.common.db import apply_migrations
from oracle.common.documents import create_document


@pytest.fixture
def conn(tmp_path):
    connection = sqlite3.connect(tmp_path / "test.db")
    apply_migrations(connection)
    return connection


def test_create_document_inserts_row_with_defaults(conn):
    document_id = create_document(
        conn,
        filename="report.pdf",
        stored_filename="123e4567-e89b-12d3-a456-426614174000.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
    )

    row = conn.execute(
        "SELECT filename, stored_filename, mime_type, size_bytes, status, error "
        "FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()

    assert row == (
        "report.pdf",
        "123e4567-e89b-12d3-a456-426614174000.pdf",
        "application/pdf",
        1024,
        "pending",
        None,
    )
