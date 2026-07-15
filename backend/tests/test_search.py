import sqlite3

import pytest

from oracle.common.chunks import create_chunk
from oracle.common.db import apply_migrations
from oracle.common.documents import create_document
from oracle.common.embeddings import ChunkToIndex
from oracle.common.search import (
    SearchResult,
    build_fts_query,
    escape_fts_query,
    reciprocal_rank_fusion,
    search_chunks,
    search_hybrid,
    search_vectors,
)


@pytest.fixture
def conn(tmp_path):
    connection = sqlite3.connect(tmp_path / "test.db")
    apply_migrations(connection)
    return connection


def test_search_chunks_returns_empty_list_when_no_matches(conn):
    assert search_chunks(conn, "hello") == []


def test_search_chunks_finds_matching_chunk_with_document(conn):
    doc_id = create_document(
        conn,
        filename="report.pdf",
        stored_filename="uuid-report.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )
    chunk_id = create_chunk(
        conn, doc_id=doc_id, seq=0, text="the quick brown fox", page_number=3
    )

    results = search_chunks(conn, "quick")

    assert results == [
        SearchResult(
            doc_id=doc_id,
            filename="report.pdf",
            chunk_id=chunk_id,
            seq=0,
            text="the quick brown fox",
            page_number=3,
            sources=["bm25"],
        )
    ]


def test_search_chunks_ignores_non_matching_chunks(conn):
    doc_id = create_document(
        conn,
        filename="report.pdf",
        stored_filename="uuid-report.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )
    create_chunk(conn, doc_id=doc_id, seq=0, text="the quick brown fox")
    create_chunk(conn, doc_id=doc_id, seq=1, text="an unrelated sentence")

    results = search_chunks(conn, "fox")

    assert [result.seq for result in results] == [0]


def test_search_chunks_orders_by_relevance(conn):
    doc_id = create_document(
        conn,
        filename="report.pdf",
        stored_filename="uuid-report.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )
    create_chunk(conn, doc_id=doc_id, seq=0, text="fox fox fox fox fox")
    create_chunk(conn, doc_id=doc_id, seq=1, text="a fox appears once")

    results = search_chunks(conn, "fox")

    assert [result.seq for result in results] == [0, 1]


def test_search_chunks_handles_query_with_special_fts5_characters(conn):
    doc_id = create_document(
        conn,
        filename="report.pdf",
        stored_filename="uuid-report.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )
    create_chunk(conn, doc_id=doc_id, seq=0, text="version 10.1 was released")

    results = search_chunks(conn, "10.1")

    assert [result.seq for result in results] == [0]


@pytest.mark.parametrize(
    "query",
    [
        '"unterminated quote',
        "OR NOT AND",
        "-excluded",
        "prefix*",
        "column:value",
        "(unbalanced",
    ],
)
def test_search_chunks_does_not_raise_on_fts5_syntax_characters(conn, query):
    search_chunks(conn, query)


def test_escape_fts_query_wraps_query_as_a_single_quoted_phrase():
    assert escape_fts_query("10.1") == '"10.1"'


def test_escape_fts_query_doubles_embedded_quotes():
    assert escape_fts_query('say "hi"') == '"say ""hi"""'


def test_build_fts_query_lowercases_and_ors_terms():
    assert build_fts_query("Quick BROWN Fox") == '"quick" OR "brown" OR "fox"'


def test_build_fts_query_drops_stop_words():
    assert build_fts_query("the quick and the brown") == '"quick" OR "brown"'


def test_build_fts_query_drops_single_character_tokens():
    assert build_fts_query("a b of quick") == '"quick"'


def test_build_fts_query_returns_none_when_nothing_remains():
    assert build_fts_query("the a of") is None


def test_build_fts_query_returns_none_for_empty_input():
    assert build_fts_query("") is None


def test_build_fts_query_escapes_special_characters_per_term():
    assert build_fts_query("10.1 fox") == '"10.1" OR "fox"'


def _create_indexed_chunks(conn, vector_index, texts, filename="report.pdf"):
    doc_id = create_document(
        conn,
        filename=filename,
        stored_filename=f"uuid-{filename}",
        mime_type="application/pdf",
        size_bytes=10,
    )
    chunks = [
        ChunkToIndex(
            chunk_id=create_chunk(conn, doc_id=doc_id, seq=seq, text=text), text=text
        )
        for seq, text in enumerate(texts)
    ]
    vector_index.index_chunks(doc_id, chunks)
    return doc_id, chunks


def test_search_chunks_limits_results(conn):
    doc_id = create_document(
        conn,
        filename="report.pdf",
        stored_filename="uuid-report.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )
    for seq in range(15):
        create_chunk(conn, doc_id=doc_id, seq=seq, text=f"fox sighting number {seq}")

    assert len(search_chunks(conn, "fox")) == 10
    assert len(search_chunks(conn, "fox", limit=3)) == 3


def test_search_vectors_returns_nearest_chunks_with_source(conn, vector_index):
    doc_id, chunks = _create_indexed_chunks(
        conn,
        vector_index,
        ["the quick brown fox", "annual financial revenue report"],
    )

    results = search_vectors(conn, vector_index, "quick fox")

    assert [result.chunk_id for result in results] == [
        chunks[0].chunk_id,
        chunks[1].chunk_id,
    ]
    assert results[0] == SearchResult(
        doc_id=doc_id,
        filename="report.pdf",
        chunk_id=chunks[0].chunk_id,
        seq=0,
        text="the quick brown fox",
        page_number=None,
        sources=["vector"],
    )


def test_search_vectors_returns_empty_for_blank_query(conn, vector_index):
    _create_indexed_chunks(conn, vector_index, ["the quick brown fox"])

    assert search_vectors(conn, vector_index, "   ") == []


def test_search_vectors_limits_results(conn, vector_index):
    _create_indexed_chunks(
        conn, vector_index, [f"fox sighting number {i}" for i in range(15)]
    )

    assert len(search_vectors(conn, vector_index, "fox")) == 10
    assert len(search_vectors(conn, vector_index, "fox", limit=3)) == 3


def test_search_vectors_drops_chunks_missing_from_the_database(conn, vector_index):
    doc_id, chunks = _create_indexed_chunks(
        conn, vector_index, ["the quick brown fox"]
    )
    conn.execute("DELETE FROM chunks WHERE id = ?", (chunks[0].chunk_id,))
    conn.commit()

    assert search_vectors(conn, vector_index, "quick fox") == []


def test_search_hybrid_fuses_both_indexes_and_merges_sources(conn, vector_index):
    _, chunks = _create_indexed_chunks(
        conn,
        vector_index,
        ["the quick brown fox", "annual financial revenue report"],
    )

    results = search_hybrid(conn, vector_index, "fox")

    # Chunk 0 matches by keyword and is the nearest vector, so it fuses to the
    # top with both sources; chunk 1 is vector-only (nearest-neighbour, no
    # keyword match) and ranks below it.
    assert [result.chunk_id for result in results] == [
        chunks[0].chunk_id,
        chunks[1].chunk_id,
    ]
    assert results[0].sources == ["bm25", "vector"]
    assert results[1].sources == ["vector"]


def test_search_hybrid_returns_at_most_five_results(conn, vector_index):
    _create_indexed_chunks(
        conn, vector_index, [f"fox sighting number {i}" for i in range(8)]
    )

    results = search_hybrid(conn, vector_index, "fox")

    assert len(results) == 5


def test_search_hybrid_returns_empty_when_nothing_is_indexed(conn, vector_index):
    assert search_hybrid(conn, vector_index, "anything") == []


def _result(chunk_id, sources):
    return SearchResult(
        doc_id=1,
        filename="report.pdf",
        chunk_id=chunk_id,
        seq=0,
        text=f"chunk {chunk_id}",
        page_number=None,
        sources=sources,
    )


def test_rrf_ranks_a_chunk_found_by_both_indexes_above_single_index_winners():
    bm25 = [_result(1, ["bm25"]), _result(3, ["bm25"])]
    vector = [_result(2, ["vector"]), _result(3, ["vector"])]

    fused = reciprocal_rank_fusion([bm25, vector])

    # Chunk 3 scores 2/(k+2), beating both rank-1 chunks at 1/(k+1).
    assert [result.chunk_id for result in fused] == [3, 1, 2]
    assert fused[0].sources == ["bm25", "vector"]


def test_rrf_breaks_score_ties_by_chunk_id():
    fused = reciprocal_rank_fusion([[_result(2, ["bm25"])], [_result(1, ["vector"])]])

    assert [result.chunk_id for result in fused] == [1, 2]


def test_rrf_respects_the_limit():
    bm25 = [_result(i, ["bm25"]) for i in range(10)]

    fused = reciprocal_rank_fusion([bm25], limit=5)

    assert [result.chunk_id for result in fused] == [0, 1, 2, 3, 4]
