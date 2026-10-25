"""Golden regression tests for document extraction and chunking.

Each fixture under tests/fixtures/extraction is chunked and compared to a
committed `<fixture>.golden.json`. A dependency bump (pymupdf, python-docx,
tiktoken) or a chunker change that alters what gets indexed fails here with a
diff. If the change is intended, regenerate and review the golden diff:

    ORACLE_UPDATE_GOLDENS=1 uv run pytest tests/test_extraction_golden.py
"""

import difflib
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

import pymupdf
import pytest
import tiktoken

from oracle.common.db import apply_migrations
from oracle.common.documents import create_document, mark_document_ready
from oracle.common.embeddings import VectorIndex
from oracle.common.ingest import CHUNK_ENCODING_NAME, chunk_document
from oracle.common.search import SearchSource, search_hybrid

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "extraction"
UPDATE_GOLDENS_ENV = "ORACLE_UPDATE_GOLDENS"

FIXTURE_NAMES = [
    "text.pdf",
    "malformed.pdf",
    "scanned.pdf",
    "tables.pdf",
    "nested_table.docx",
]


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(tmp_path / "test.db")
    apply_migrations(connection)
    return connection


def _add_document(conn: sqlite3.Connection, filename: str) -> int:
    return create_document(
        conn,
        filename=filename,
        stored_filename=filename,
        mime_type="application/octet-stream",
        size_bytes=1,
    )


def _snapshot(
    conn: sqlite3.Connection, fixture_name: str, caplog: pytest.LogCaptureFixture
) -> dict[str, Any]:
    # MuPDF's warning buffer is process-global; drop leftovers from earlier
    # documents so they aren't logged against this one.
    pymupdf.TOOLS.mupdf_warnings()
    doc_id = _add_document(conn, fixture_name)
    with caplog.at_level(logging.WARNING, logger="oracle.common.ingest"):
        chunk_count = chunk_document(conn, doc_id, FIXTURES_DIR / fixture_name)

    encoding = tiktoken.get_encoding(CHUNK_ENCODING_NAME)
    rows = conn.execute(
        "SELECT seq, text, page_number, paragraph_start, paragraph_end, "
        "char_start, char_end FROM chunks WHERE doc_id = ? ORDER BY seq",
        (doc_id,),
    ).fetchall()
    return {
        "fixture": fixture_name,
        "chunk_count": chunk_count,
        "chunks": [
            {
                "seq": seq,
                "text": text,
                "token_count": len(encoding.encode(text)),
                "page_number": page_number,
                "paragraph_start": paragraph_start,
                "paragraph_end": paragraph_end,
                "char_start": char_start,
                "char_end": char_end,
            }
            for (
                seq,
                text,
                page_number,
                paragraph_start,
                paragraph_end,
                char_start,
                char_end,
            ) in rows
        ],
        # MuPDF messages carry the doc id, which is 1 in a fresh test db
        "warnings": [record.getMessage() for record in caplog.records],
    }


def _dump(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_extraction_matches_golden(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture, fixture_name: str
) -> None:
    golden_path = FIXTURES_DIR / f"{fixture_name}.golden.json"
    actual = _dump(_snapshot(conn, fixture_name, caplog))

    if os.environ.get(UPDATE_GOLDENS_ENV) == "1":
        golden_path.write_text(actual, encoding="utf-8")

    if not golden_path.exists():
        pytest.fail(
            f"No golden for {fixture_name}; create it with {UPDATE_GOLDENS_ENV}=1 "
            "and review the new file"
        )
    expected = golden_path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=f"{golden_path.name} (golden)",
                tofile=f"{fixture_name} (actual)",
            )
        )
        pytest.fail(
            f"Extraction of {fixture_name} changed. If intended, regenerate with "
            f"{UPDATE_GOLDENS_ENV}=1 and review the diff.\n{diff}"
        )


# (query, fixture, seq): the chunk that must rank in the BM25 top results
RETRIEVAL_CASES = [
    ("bakery 404 295", "text.pdf", 3),
    ("Lantern Anchor Tarpaulin units", "tables.pdf", 0),
    ("Inner gamma delta units", "nested_table.docx", 0),
]
RETRIEVAL_TOP_K = 2


@pytest.mark.parametrize(("query", "fixture_name", "seq"), RETRIEVAL_CASES)
def test_bm25_ranks_the_expected_chunk_in_top_k(
    conn: sqlite3.Connection,
    vector_index: VectorIndex,
    query: str,
    fixture_name: str,
    seq: int,
) -> None:
    for name in ("text.pdf", "tables.pdf", "nested_table.docx"):
        doc_id = _add_document(conn, name)
        chunk_document(conn, doc_id, FIXTURES_DIR / name)
        mark_document_ready(conn, doc_id)

    results = search_hybrid(conn, vector_index, query, sources=[SearchSource.BM25])

    ranked = [(result.filename, result.seq) for result in results[:RETRIEVAL_TOP_K]]
    assert (fixture_name, seq) in ranked
