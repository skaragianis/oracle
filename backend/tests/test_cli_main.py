import sqlite3
import sys
from pathlib import Path

import fitz
import pytest
from conftest import make_vector_index

from oracle.cli.main import main
from oracle.common import db, embeddings, ingest
from oracle.common.embeddings import VectorIndex


@pytest.fixture(autouse=True)
def fake_embeddings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VectorIndex:
    """Keep CLI runs away from the real model download and the real vector db."""
    index = make_vector_index()
    monkeypatch.setattr(embeddings, "open_vector_index", lambda: index)
    monkeypatch.setattr(embeddings, "DEFAULT_VECTOR_DB_PATH", tmp_path / "vectors")
    return index


def test_main_runs_with_no_args_prints_usage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "oracle.db")
    monkeypatch.setattr(sys, "argv", ["oracle-cli"])
    main()
    captured = capsys.readouterr()
    assert captured.out.startswith("usage: oracle-cli")


def test_main_runs_migrations_on_startup_even_with_no_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "oracle.db"
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(sys, "argv", ["oracle-cli"])

    main()

    conn = sqlite3.connect(db_path)
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone()
    assert table is not None


def test_main_add_ingests_file_and_records_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "report.pdf"
    pdf_doc = fitz.open()
    pdf_doc.new_page().insert_text((72, 72), "Hello world.")
    pdf_doc.save(source)
    pdf_doc.close()
    uploads_dir = tmp_path / "uploads"
    db_path = tmp_path / "oracle.db"
    monkeypatch.setattr(ingest, "DEFAULT_UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--add", str(source)])

    main()

    captured = capsys.readouterr()
    assert "Added" in captured.out
    stored_files = list(uploads_dir.iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == source.read_bytes()

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT filename, stored_filename, mime_type, size_bytes, status FROM documents"
    ).fetchone()
    assert row == (
        "report.pdf",
        stored_files[0].name,
        "application/pdf",
        source.stat().st_size,
        "ready",
    )

    chunk_row = conn.execute(
        "SELECT text FROM chunks WHERE doc_id = (SELECT id FROM documents)"
    ).fetchone()
    assert chunk_row == ("Hello world.\n",)


def test_main_add_twice_prints_re_added_and_keeps_one_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "report.pdf"
    pdf_doc = fitz.open()
    pdf_doc.new_page().insert_text((72, 72), "Hello world.")
    pdf_doc.save(source)
    pdf_doc.close()
    uploads_dir = tmp_path / "uploads"
    db_path = tmp_path / "oracle.db"
    monkeypatch.setattr(ingest, "DEFAULT_UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--add", str(source)])
    main()
    capsys.readouterr()

    main()

    captured = capsys.readouterr()
    assert captured.out.startswith("Re-added")
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    assert count == 1
    assert len(list(uploads_dir.iterdir())) == 1


def test_main_add_missing_file_prints_friendly_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.pdf"
    monkeypatch.setattr(ingest, "DEFAULT_UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "oracle.db")
    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--add", str(missing)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: file not found" in captured.err
    assert str(missing) in captured.err


def test_main_reset_removes_existing_database_and_uploads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "oracle.db"
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(ingest, "DEFAULT_UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(sys, "argv", ["oracle-cli"])
    main()
    uploads_dir.mkdir()
    (uploads_dir / "stored.pdf").write_bytes(b"data")
    vector_db_path = embeddings.DEFAULT_VECTOR_DB_PATH
    vector_db_path.mkdir()
    (vector_db_path / "chroma.sqlite3").write_bytes(b"data")
    assert db_path.exists()

    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--reset"])
    main()

    captured = capsys.readouterr()
    assert "Reset database" in captured.out
    assert not db_path.exists()
    assert list(uploads_dir.iterdir()) == []
    assert not vector_db_path.exists()


def test_main_reset_is_a_noop_when_nothing_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "oracle.db"
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(ingest, "DEFAULT_UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--reset"])

    main()

    captured = capsys.readouterr()
    assert "Reset database" in captured.out
    assert not db_path.exists()


def test_main_list_prints_no_documents_message_when_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "oracle.db")
    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--list"])

    main()

    captured = capsys.readouterr()
    assert "No documents found." in captured.out


def test_main_list_prints_documents_with_emphasised_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "report.pdf"
    pdf_doc = fitz.open()
    pdf_doc.new_page().insert_text((72, 72), "Hello world.")
    pdf_doc.save(source)
    pdf_doc.close()
    uploads_dir = tmp_path / "uploads"
    db_path = tmp_path / "oracle.db"
    monkeypatch.setattr(ingest, "DEFAULT_UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--add", str(source)])
    main()

    monkeypatch.setattr(sys, "argv", ["oracle-cli", "-l"])
    main()

    captured = capsys.readouterr()
    assert "[1] report.pdf - ready" in captured.out


def test_main_search_prints_no_results_message_when_no_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "oracle.db")
    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--search", "nothing"])

    main()

    captured = capsys.readouterr()
    assert "No results found." in captured.out


def test_main_search_prints_matching_document_and_chunk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "report.pdf"
    pdf_doc = fitz.open()
    pdf_doc.new_page().insert_text((72, 72), "The quick brown fox.")
    pdf_doc.save(source)
    pdf_doc.close()
    uploads_dir = tmp_path / "uploads"
    db_path = tmp_path / "oracle.db"
    monkeypatch.setattr(ingest, "DEFAULT_UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--add", str(source)])
    main()

    monkeypatch.setattr(sys, "argv", ["oracle-cli", "-s", "quick"])
    main()

    captured = capsys.readouterr()
    assert "[1] report.pdf (chunk 0) [bm25+vector]" in captured.out
    assert "The quick brown fox." in captured.out


def test_main_search_with_only_stop_words_prints_no_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "oracle.db")
    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--search", "the"])

    main()

    captured = capsys.readouterr()
    assert "No results found." in captured.out


def test_main_add_unsupported_extension_prints_friendly_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("hello")
    monkeypatch.setattr(ingest, "DEFAULT_UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "oracle.db")
    monkeypatch.setattr(sys, "argv", ["oracle-cli", "--add", str(source)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Unsupported file type" in captured.err
