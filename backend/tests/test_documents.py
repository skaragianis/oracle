import sqlite3
from pathlib import Path

import pytest

from oracle.common.db import apply_migrations
from oracle.common.documents import (
    Document,
    create_document,
    list_documents,
    mark_document_failed,
    mark_document_ready,
)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(tmp_path / "test.db")
    apply_migrations(connection)
    return connection


def test_create_document_inserts_row_with_defaults(conn: sqlite3.Connection) -> None:
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


def test_mark_document_failed_records_the_reason(conn: sqlite3.Connection) -> None:
    doc_id = create_document(
        conn,
        filename="a.pdf",
        stored_filename="uuid-a.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )

    mark_document_failed(conn, doc_id, "Broken PDF.")

    assert conn.execute(
        "SELECT status, error FROM documents WHERE id = ?", (doc_id,)
    ).fetchone() == ("failed", "Broken PDF.")


def test_mark_document_ready_clears_a_previous_failure(
    conn: sqlite3.Connection,
) -> None:
    doc_id = create_document(
        conn,
        filename="a.pdf",
        stored_filename="uuid-a.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )
    mark_document_failed(conn, doc_id, "Broken PDF.")

    mark_document_ready(conn, doc_id)

    assert conn.execute(
        "SELECT status, error FROM documents WHERE id = ?", (doc_id,)
    ).fetchone() == ("ready", None)


def test_list_documents_returns_empty_list_when_no_documents(
    conn: sqlite3.Connection,
) -> None:
    assert list_documents(conn) == []


def test_list_documents_returns_id_filename_and_status_ordered_by_id(
    conn: sqlite3.Connection,
) -> None:
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
