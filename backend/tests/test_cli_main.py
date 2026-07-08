import sqlite3
import sys

import pytest

from oracle.cli.main import main
from oracle.common import db, ingest


def test_main_runs_with_no_args_prints_usage(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "oracle.db")
    monkeypatch.setattr(sys, "argv", ["oracle-cli"])
    main()
    captured = capsys.readouterr()
    assert captured.out.startswith("usage: oracle-cli")


def test_main_runs_migrations_on_startup_even_with_no_command(tmp_path, monkeypatch):
    db_path = tmp_path / "oracle.db"
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(sys, "argv", ["oracle-cli"])

    main()

    conn = sqlite3.connect(db_path)
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone()
    assert table is not None


def test_main_add_ingests_file_and_records_document(tmp_path, capsys, monkeypatch):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"file contents")
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
    assert stored_files[0].read_bytes() == b"file contents"

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT filename, stored_filename, mime_type, size_bytes, status "
        "FROM documents"
    ).fetchone()
    assert row == (
        "report.pdf",
        stored_files[0].name,
        "application/pdf",
        len(b"file contents"),
        "pending",
    )


def test_main_add_missing_file_prints_friendly_error(tmp_path, capsys, monkeypatch):
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


def test_main_add_unsupported_extension_prints_friendly_error(
    tmp_path, capsys, monkeypatch
):
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
