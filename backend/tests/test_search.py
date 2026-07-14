import sqlite3

import pytest

from oracle.common.chunks import create_chunk
from oracle.common.db import apply_migrations
from oracle.common.documents import create_document
from oracle.common.search import (
    SearchResult,
    build_fts_query,
    escape_fts_query,
    search_chunks,
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
    chunk_id = create_chunk(conn, doc_id=doc_id, seq=0, text="the quick brown fox")

    results = search_chunks(conn, "quick")

    assert results == [
        SearchResult(
            doc_id=doc_id,
            filename="report.pdf",
            chunk_id=chunk_id,
            seq=0,
            text="the quick brown fox",
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
