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
