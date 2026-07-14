import sqlite3

import pytest

from oracle.common.db import apply_migrations
from oracle.common.documents import Document, create_document, list_documents


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


def test_list_documents_returns_empty_list_when_no_documents(conn):
    assert list_documents(conn) == []


def test_list_documents_returns_id_filename_and_status_ordered_by_id(conn):
    first_id = create_document(
        conn,
        filename="a.pdf",
        stored_filename="uuid-a.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )
    second_id = create_document(
        conn,
        filename="b.pdf",
        stored_filename="uuid-b.pdf",
        mime_type="application/pdf",
        size_bytes=20,
    )

    assert list_documents(conn) == [
        Document(id=first_id, filename="a.pdf", status="pending"),
        Document(id=second_id, filename="b.pdf", status="pending"),
    ]
