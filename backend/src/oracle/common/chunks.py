import sqlite3


def create_chunk(
    conn: sqlite3.Connection,
    *,
    doc_id: int,
    seq: int,
    text: str,
    page_number: int | None = None,
    paragraph_start: int | None = None,
    paragraph_end: int | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO chunks "
            "(doc_id, seq, text, page_number, paragraph_start, paragraph_end, "
            "char_start, char_end) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_id,
                seq,
                text,
                page_number,
                paragraph_start,
                paragraph_end,
                char_start,
                char_end,
            ),
        )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def delete_chunks_for_document(conn: sqlite3.Connection, doc_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
