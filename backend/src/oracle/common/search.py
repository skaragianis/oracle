import sqlite3
from dataclasses import dataclass


@dataclass
class SearchResult:
    doc_id: int
    filename: str
    chunk_id: int
    seq: int
    text: str


def escape_fts5_query(query: str) -> str:
    """Wrap a raw user query as a single literal FTS5 phrase.

    FTS5 parses the MATCH value with its own query language (AND/OR/NOT,
    prefix *, column filters, quoted phrases, ...), so passing user input
    through unescaped lets it be interpreted as that syntax rather than as
    plain search text - at best raising a syntax error (e.g. "10.1"), at
    worst changing which rows match. Quoting it as one phrase forces it to
    be treated as literal text.
    """
    return '"' + query.replace('"', '""') + '"'


def search_chunks(conn: sqlite3.Connection, query: str) -> list[SearchResult]:
    rows = conn.execute(
        "SELECT documents.id, documents.filename, chunks.id, chunks.seq, chunks.text "
        "FROM chunks_fts "
        "JOIN chunks ON chunks.id = chunks_fts.rowid "
        "JOIN documents ON documents.id = chunks.doc_id "
        "WHERE chunks_fts MATCH ? "
        "ORDER BY chunks_fts.rank",
        (escape_fts5_query(query),),
    ).fetchall()
    return [
        SearchResult(doc_id=row[0], filename=row[1], chunk_id=row[2], seq=row[3], text=row[4])
        for row in rows
    ]
