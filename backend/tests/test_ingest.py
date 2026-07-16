import os
import sqlite3
import subprocess
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

import docx
import fitz
import pytest
import tiktoken

from oracle.common.db import apply_migrations
from oracle.common.embeddings import ChunkToIndex, VectorIndex
from oracle.common.ingest import (
    CHUNK_ENCODING_NAME,
    UnsupportedFileTypeError,
    chunk_document,
    ingest_file,
    process_document,
    stage_file,
)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(tmp_path / "test.db")
    apply_migrations(connection)
    return connection


def _write_pdf(
    path: Path, pages_of_paragraphs: list[list[str]], page_height: int = 842
) -> None:
    """pages_of_paragraphs: list of pages, each a list of paragraph strings."""
    doc = fitz.open()
    for paragraphs in pages_of_paragraphs:
        page = doc.new_page(width=612, height=page_height)
        y = 72
        for paragraph in paragraphs:
            page.insert_text((72, y), paragraph)
            y += 20 * (paragraph.count("\n") + 1) + 20
    doc.save(path)
    doc.close()


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(str(path))


@pytest.mark.parametrize("suffix", [".pdf", ".PDF"])
def test_ingest_file_copies_pdf_with_uuid_name(
    tmp_path: Path, conn: sqlite3.Connection, suffix: str
) -> None:
    source = tmp_path / f"source{suffix}"
    _write_pdf(source, [["Hello world."]])
    uploads_dir = tmp_path / "uploads"

    result = ingest_file(conn, source, uploads_dir=uploads_dir)

    assert result.destination_path.parent == uploads_dir
    assert result.destination_path.suffix == suffix.lower()
    assert uuid.UUID(result.destination_path.stem)
    assert source.exists()


def test_ingest_file_copies_docx_with_uuid_name(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.docx"
    source.write_bytes(b"file contents")
    uploads_dir = tmp_path / "uploads"

    result = ingest_file(conn, source, uploads_dir=uploads_dir)

    assert result.destination_path.parent == uploads_dir
    assert result.destination_path.suffix == ".docx"
    assert uuid.UUID(result.destination_path.stem)
    assert result.destination_path.read_bytes() == b"file contents"
    assert source.exists()


def test_stage_file_leaves_document_pending(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    # Staging is the half of ingestion the HTTP request does; chunking, and with
    # it any move off 'pending', happens later in a background task.
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])

    staged = stage_file(conn, source, uploads_dir=tmp_path / "uploads")

    status = conn.execute(
        "SELECT status FROM documents WHERE id = ?", (staged.doc_id,)
    ).fetchone()[0]
    assert status == "pending"
    chunk_count = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE doc_id = ?", (staged.doc_id,)
    ).fetchone()[0]
    assert chunk_count == 0


def test_process_document_marks_a_chunked_pdf_ready(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])
    staged = stage_file(conn, source, uploads_dir=tmp_path / "uploads")

    result = process_document(conn, staged.doc_id, staged.destination_path)

    assert result.status == "ready"
    assert result.error is None
    assert conn.execute(
        "SELECT status, error FROM documents WHERE id = ?", (staged.doc_id,)
    ).fetchone() == ("ready", None)


def test_process_document_records_failure_instead_of_raising(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    # A background task has nobody to return an error to, so a corrupt PDF has to
    # land on the document as 'failed' rather than propagate.
    source = tmp_path / "source.pdf"
    source.write_bytes(b"not a real pdf")
    staged = stage_file(conn, source, uploads_dir=tmp_path / "uploads")

    result = process_document(conn, staged.doc_id, staged.destination_path)

    assert result.status == "failed"
    status, error = conn.execute(
        "SELECT status, error FROM documents WHERE id = ?", (staged.doc_id,)
    ).fetchone()
    assert status == "failed"
    assert error == result.error


def test_ingest_file_fails_a_malformed_docx(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.docx"
    source.write_bytes(b"file contents")

    result = ingest_file(conn, source, uploads_dir=tmp_path / "uploads")

    assert result.status == "failed"
    assert result.error
    status = conn.execute(
        "SELECT status FROM documents WHERE id = ?", (result.doc_id,)
    ).fetchone()[0]
    assert status == "failed"


def test_ingest_file_re_adding_a_failed_document_resets_it_to_pending(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    # The failure and its reason belong to a specific upload, so a replacement
    # must not inherit them while it waits to be chunked.
    source = tmp_path / "source.docx"
    source.write_bytes(b"not a real docx")
    failed = ingest_file(conn, source, uploads_dir=tmp_path / "uploads")

    staged = stage_file(conn, source, uploads_dir=tmp_path / "uploads")

    assert staged.doc_id == failed.doc_id
    assert conn.execute(
        "SELECT status, error FROM documents WHERE id = ?", (staged.doc_id,)
    ).fetchone() == ("pending", None)


def test_ingest_file_creates_uploads_dir_if_missing(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])
    uploads_dir = tmp_path / "does" / "not" / "exist"

    result = ingest_file(conn, source, uploads_dir=uploads_dir)

    assert result.destination_path.exists()


def test_ingest_file_rejects_unsupported_extension(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"file contents")

    with pytest.raises(UnsupportedFileTypeError):
        ingest_file(conn, source, uploads_dir=tmp_path / "uploads")


def test_ingest_file_raises_for_missing_source(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "missing.pdf"

    with pytest.raises(FileNotFoundError):
        ingest_file(conn, source, uploads_dir=tmp_path / "uploads")


def test_ingest_file_first_add_is_not_marked_as_replaced(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])
    uploads_dir = tmp_path / "uploads"

    result = ingest_file(conn, source, uploads_dir=uploads_dir)

    assert result.replaced is False


def test_ingest_file_reingesting_same_filename_replaces_document(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])
    uploads_dir = tmp_path / "uploads"

    first = ingest_file(conn, source, uploads_dir=uploads_dir)

    _write_pdf(source, [["Goodbye world."]])
    second = ingest_file(conn, source, uploads_dir=uploads_dir)

    assert second.replaced is True
    assert second.doc_id == first.doc_id

    count = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE filename = ?", ("source.pdf",)
    ).fetchone()[0]
    assert count == 1


def test_ingest_file_reingesting_removes_previous_upload(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])
    uploads_dir = tmp_path / "uploads"

    first = ingest_file(conn, source, uploads_dir=uploads_dir)
    second = ingest_file(conn, source, uploads_dir=uploads_dir)

    assert not first.destination_path.exists()
    assert second.destination_path.exists()
    assert list(uploads_dir.iterdir()) == [second.destination_path]


def test_ingest_file_reingesting_recalculates_chunks(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])
    uploads_dir = tmp_path / "uploads"

    first = ingest_file(conn, source, uploads_dir=uploads_dir)

    _write_pdf(source, [["Goodbye world."]])
    second = ingest_file(conn, source, uploads_dir=uploads_dir)

    assert first.doc_id == second.doc_id
    chunk_rows = conn.execute(
        "SELECT text FROM chunks WHERE doc_id = ?", (second.doc_id,)
    ).fetchall()
    assert chunk_rows == [("Goodbye world.\n",)]


def test_ingest_file_records_document_and_chunks(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])

    result = ingest_file(conn, source, uploads_dir=tmp_path / "uploads")

    doc_row = conn.execute(
        "SELECT filename FROM documents WHERE id = ?", (result.doc_id,)
    ).fetchone()
    assert doc_row == ("source.pdf",)

    chunk_row = conn.execute(
        "SELECT doc_id, seq, text FROM chunks WHERE doc_id = ?", (result.doc_id,)
    ).fetchone()
    assert chunk_row == (result.doc_id, 0, "Hello world.\n")


def test_process_document_marks_a_chunked_docx_ready(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "source.docx"
    _write_docx(source, ["Hello world."])
    staged = stage_file(conn, source, uploads_dir=tmp_path / "uploads")

    result = process_document(conn, staged.doc_id, staged.destination_path)

    assert result.status == "ready"
    assert result.error is None
    chunk_row = conn.execute(
        "SELECT text, page_number FROM chunks WHERE doc_id = ?", (staged.doc_id,)
    ).fetchone()
    assert chunk_row == ("Hello world.\n", None)


def test_chunk_document_splits_long_docx_into_multiple_chunks(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "long.docx"
    encoding = tiktoken.get_encoding(CHUNK_ENCODING_NAME)
    # Unique numbered paragraphs make it possible to verify overlap precisely,
    # rather than incidentally matching on repeated filler text.
    paragraphs = [f"Paragraph {i:04d} filler filler filler filler." for i in range(200)]
    _write_docx(source, paragraphs)

    doc_id = conn.execute(
        "INSERT INTO documents (filename, stored_filename, mime_type, size_bytes) "
        "VALUES ('long.docx', 'stored.docx', "
        "'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 1)"
    ).lastrowid
    conn.commit()
    assert doc_id is not None

    chunk_count = chunk_document(conn, doc_id, source)

    rows = conn.execute(
        "SELECT seq, text, page_number, paragraph_start, paragraph_end, "
        "char_start, char_end FROM chunks WHERE doc_id = ? ORDER BY seq",
        (doc_id,),
    ).fetchall()

    assert chunk_count == len(rows)
    assert chunk_count > 1

    for (
        seq,
        text,
        page_number,
        paragraph_start,
        paragraph_end,
        char_start,
        char_end,
    ) in rows:
        token_count = len(encoding.encode(text))
        assert token_count >= 800 or seq == chunk_count - 1
        assert page_number is None
        assert paragraph_start <= paragraph_end
        assert char_start < char_end


def test_chunk_document_returns_zero_for_blank_docx(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "blank.docx"
    _write_docx(source, [])

    doc_id = conn.execute(
        "INSERT INTO documents (filename, stored_filename, mime_type, size_bytes) "
        "VALUES ('blank.docx', 'stored.docx', "
        "'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 1)"
    ).lastrowid
    conn.commit()
    assert doc_id is not None

    chunk_count = chunk_document(conn, doc_id, source)

    assert chunk_count == 0
    remaining = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE doc_id = ?", (doc_id,)
    ).fetchone()[0]
    assert remaining == 0


def test_chunk_document_splits_long_pdf_into_multiple_chunks(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "long.pdf"
    encoding = tiktoken.get_encoding(CHUNK_ENCODING_NAME)
    # Unique numbered lines make it possible to verify overlap precisely,
    # rather than incidentally matching on repeated filler text. Each page is
    # made tall enough that PyMuPDF doesn't clip lines past the page bottom.
    lines_per_page = 100
    line_numbers_by_page = [
        range(page * lines_per_page, (page + 1) * lines_per_page) for page in range(4)
    ]
    pages = [
        ["\n".join(f"Line {i:04d} filler filler filler filler." for i in numbers)]
        for numbers in line_numbers_by_page
    ]
    _write_pdf(source, pages, page_height=5000)

    doc_id = conn.execute(
        "INSERT INTO documents (filename, stored_filename, mime_type, size_bytes) "
        "VALUES ('long.pdf', 'stored.pdf', 'application/pdf', 1)"
    ).lastrowid
    conn.commit()
    assert doc_id is not None

    chunk_count = chunk_document(conn, doc_id, source)

    rows = conn.execute(
        "SELECT seq, text, page_number, paragraph_start, paragraph_end, "
        "char_start, char_end FROM chunks WHERE doc_id = ? ORDER BY seq",
        (doc_id,),
    ).fetchall()

    assert chunk_count == len(rows)
    assert chunk_count > 1

    seqs = [row[0] for row in rows]
    assert seqs == list(range(chunk_count))

    for (
        seq,
        text,
        page_number,
        paragraph_start,
        paragraph_end,
        char_start,
        char_end,
    ) in rows:
        token_count = len(encoding.encode(text))
        assert token_count >= 800 or seq == chunk_count - 1
        assert page_number >= 1
        assert paragraph_start <= paragraph_end
        assert char_start < char_end

    # Consecutive chunks overlap by ~100 tokens: the first line of a chunk
    # should be a line that also appears verbatim, at the same relative
    # position, near the end of the previous chunk.
    for previous, current in zip(rows, rows[1:]):
        previous_lines = previous[1].splitlines(keepends=True)
        current_first_line = current[1].splitlines(keepends=True)[0]
        assert current_first_line in previous_lines
        overlap_index = previous_lines.index(current_first_line)
        # the overlap should be a suffix of the previous chunk, not a coincidental
        # match somewhere in the middle
        assert overlap_index > len(previous_lines) // 2
        assert (
            previous_lines[overlap_index:]
            == current[1].splitlines(keepends=True)[
                : len(previous_lines) - overlap_index
            ]
        )


def test_chunk_document_returns_zero_for_blank_pdf(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    source = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(source)
    doc.close()

    doc_id = conn.execute(
        "INSERT INTO documents (filename, stored_filename, mime_type, size_bytes) "
        "VALUES ('blank.pdf', 'stored.pdf', 'application/pdf', 1)"
    ).lastrowid
    conn.commit()
    assert doc_id is not None

    chunk_count = chunk_document(conn, doc_id, source)

    assert chunk_count == 0
    remaining = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE doc_id = ?", (doc_id,)
    ).fetchone()[0]
    assert remaining == 0


def test_process_document_indexes_chunk_vectors(
    tmp_path: Path, conn: sqlite3.Connection, vector_index: VectorIndex
) -> None:
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])
    staged = stage_file(conn, source, uploads_dir=tmp_path / "uploads")

    process_document(
        conn, staged.doc_id, staged.destination_path, vector_index=vector_index
    )

    chunk_id = conn.execute(
        "SELECT id FROM chunks WHERE doc_id = ?", (staged.doc_id,)
    ).fetchone()[0]
    matches = vector_index.search("hello world", limit=10)
    assert [match.chunk_id for match in matches] == [chunk_id]


def test_ingest_file_replacement_removes_stale_vectors(
    tmp_path: Path, conn: sqlite3.Connection, vector_index: VectorIndex
) -> None:
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])
    uploads_dir = tmp_path / "uploads"
    ingest_file(conn, source, uploads_dir=uploads_dir, vector_index=vector_index)

    _write_pdf(source, [["Goodbye world."]])
    second = ingest_file(
        conn, source, uploads_dir=uploads_dir, vector_index=vector_index
    )

    current_chunk_ids = {
        row[0]
        for row in conn.execute(
            "SELECT id FROM chunks WHERE doc_id = ?", (second.doc_id,)
        )
    }
    matches = vector_index.search("world", limit=10)
    assert {match.chunk_id for match in matches} == current_chunk_ids


def test_process_document_records_an_embedding_failure(
    tmp_path: Path,
    conn: sqlite3.Connection,
    vector_index: VectorIndex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(doc_id: int, chunks: Sequence[ChunkToIndex]) -> None:
        raise RuntimeError("embedding blew up")

    monkeypatch.setattr(vector_index, "index_chunks", explode)
    source = tmp_path / "source.pdf"
    _write_pdf(source, [["Hello world."]])
    staged = stage_file(conn, source, uploads_dir=tmp_path / "uploads")

    result = process_document(
        conn, staged.doc_id, staged.destination_path, vector_index=vector_index
    )

    assert result.status == "failed"
    assert result.error is not None and "embedding blew up" in result.error


def test_uploads_dir_can_be_overridden_by_environment(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from oracle.common import ingest; print(ingest.DEFAULT_UPLOADS_DIR)",
        ],
        env={**os.environ, "ORACLE_UPLOADS_DIR": str(tmp_path / "elsewhere")},
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == str(tmp_path / "elsewhere")
