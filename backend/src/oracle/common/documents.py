import sqlite3


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
    return cursor.lastrowid
