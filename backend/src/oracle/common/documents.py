import sqlite3
from dataclasses import dataclass


@dataclass
class Document:
    id: int
    filename: str
    status: str


def create_document(
    conn: sqlite3.Connection,
    *,
    filename: str,
    stored_filename: str,
    mime_type: str,
    size_bytes: int,
) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO documents (filename, stored_filename, mime_type, size_bytes) "
            "VALUES (?, ?, ?, ?)",
            (filename, stored_filename, mime_type, size_bytes),
        )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def list_documents(conn: sqlite3.Connection) -> list[Document]:
    rows = conn.execute(
        "SELECT id, filename, status FROM documents ORDER BY id"
    ).fetchall()
    return [Document(id=row[0], filename=row[1], status=row[2]) for row in rows]


def find_document_by_filename(
    conn: sqlite3.Connection, filename: str
) -> tuple[int, str] | None:
    """Return (id, stored_filename) for the document with this filename, if any."""
    return conn.execute(
        "SELECT id, stored_filename FROM documents WHERE filename = ?", (filename,)
    ).fetchone()


def mark_document_ready(conn: sqlite3.Connection, document_id: int) -> None:
    """Mark a document as chunked and therefore searchable."""
    with conn:
        conn.execute(
            "UPDATE documents SET status = 'ready', error = NULL WHERE id = ?",
            (document_id,),
        )


def replace_document_upload(
    conn: sqlite3.Connection,
    document_id: int,
    *,
    stored_filename: str,
    mime_type: str,
    size_bytes: int,
) -> None:
    with conn:
        conn.execute(
            "UPDATE documents SET stored_filename = ?, mime_type = ?, size_bytes = ?, "
            "status = 'pending', error = NULL WHERE id = ?",
            (stored_filename, mime_type, size_bytes, document_id),
        )
