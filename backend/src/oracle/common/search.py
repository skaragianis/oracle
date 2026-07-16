import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from oracle.common.embeddings import VectorIndex

RESULTS_PER_INDEX = 10
FUSED_RESULT_LIMIT = 5
RRF_K = 60

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "if",
        "in",
        "into",
        "is",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "such",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "will",
        "with",
    }
)


@dataclass
class SearchResult:
    doc_id: int
    filename: str
    chunk_id: int
    seq: int
    text: str
    page_number: int | None
    sources: list[str]


def build_fts_query(user_input: str) -> str | None:
    terms = [
        word
        for word in (word.lower() for word in user_input.split())
        if len(word) > 1 and word not in STOP_WORDS
    ]
    if not terms:
        return None
    return " OR ".join(escape_fts_query(term) for term in terms)


def escape_fts_query(query: str) -> str:
    return '"' + query.replace('"', '""') + '"'


def search_chunks(
    conn: sqlite3.Connection, query: str, limit: int = RESULTS_PER_INDEX
) -> list[SearchResult]:
    fts_query = build_fts_query(query)
    if fts_query is None:
        return []

    rows = conn.execute(
        "SELECT documents.id, documents.filename, chunks.id, chunks.seq, chunks.text, "
        "chunks.page_number "
        "FROM chunks_fts "
        "JOIN chunks ON chunks.id = chunks_fts.rowid "
        "JOIN documents ON documents.id = chunks.doc_id "
        "WHERE chunks_fts MATCH ? "
        "ORDER BY chunks_fts.rank "
        "LIMIT ?",
        (fts_query, limit),
    ).fetchall()
    return [_row_to_result(row, source="bm25") for row in rows]


def search_vectors(
    conn: sqlite3.Connection,
    vector_index: VectorIndex,
    query: str,
    limit: int = RESULTS_PER_INDEX,
) -> list[SearchResult]:
    if not query.strip():
        return []

    matches = vector_index.search(query, limit)
    if not matches:
        return []

    placeholders = ", ".join("?" for _ in matches)
    rows = conn.execute(
        "SELECT documents.id, documents.filename, chunks.id, chunks.seq, chunks.text, "
        "chunks.page_number "
        "FROM chunks "
        "JOIN documents ON documents.id = chunks.doc_id "
        f"WHERE chunks.id IN ({placeholders})",
        [match.chunk_id for match in matches],
    ).fetchall()
    results_by_chunk_id = {row[2]: _row_to_result(row, source="vector") for row in rows}
    # Preserve the index's nearest-first order; drop ids the database no longer has.
    return [
        results_by_chunk_id[match.chunk_id]
        for match in matches
        if match.chunk_id in results_by_chunk_id
    ]


def search_hybrid(
    conn: sqlite3.Connection, vector_index: VectorIndex, query: str
) -> list[SearchResult]:
    return reciprocal_rank_fusion(
        [search_chunks(conn, query), search_vectors(conn, vector_index, query)]
    )


def reciprocal_rank_fusion(
    rankings: Sequence[list[SearchResult]],
    k: int = RRF_K,
    limit: int = FUSED_RESULT_LIMIT,
) -> list[SearchResult]:
    scores: dict[int, float] = {}
    fused: dict[int, SearchResult] = {}
    for ranking in rankings:
        for rank, result in enumerate(ranking, start=1):
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1 / (k + rank)
            if result.chunk_id in fused:
                merged = fused[result.chunk_id].sources + result.sources
                fused[result.chunk_id] = replace(
                    fused[result.chunk_id], sources=merged
                )
            else:
                fused[result.chunk_id] = result
    ordered = sorted(
        fused.values(), key=lambda result: (-scores[result.chunk_id], result.chunk_id)
    )
    return ordered[:limit]


def _row_to_result(row: sqlite3.Row | tuple[Any, ...], *, source: str) -> SearchResult:
    return SearchResult(
        doc_id=row[0],
        filename=row[1],
        chunk_id=row[2],
        seq=row[3],
        text=row[4],
        page_number=row[5],
        sources=[source],
    )
