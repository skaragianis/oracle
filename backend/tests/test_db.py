import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from oracle.common.db import apply_migrations, get_connection, run_migrations


def test_apply_migrations_creates_schema_migrations_table(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "test.db")

    apply_migrations(conn, migrations_dir=tmp_path / "migrations")

    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    assert table is not None


def test_apply_migrations_runs_pending_sql_files_in_order(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_create_widgets.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY);"
    )
    (migrations_dir / "0002_add_widget_name.sql").write_text(
        "ALTER TABLE widgets ADD COLUMN name TEXT;"
    )
    conn = sqlite3.connect(tmp_path / "test.db")

    applied = apply_migrations(conn, migrations_dir=migrations_dir)

    assert applied == ["0001_create_widgets.sql", "0002_add_widget_name.sql"]
    conn.execute("INSERT INTO widgets (name) VALUES ('foo')")
    row = conn.execute("SELECT name FROM widgets").fetchone()
    assert row == ("foo",)


def test_apply_migrations_skips_already_applied(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_create_widgets.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY);"
    )
    conn = sqlite3.connect(tmp_path / "test.db")
    apply_migrations(conn, migrations_dir=migrations_dir)

    second_run = apply_migrations(conn, migrations_dir=migrations_dir)

    assert second_run == []


def test_apply_migrations_with_no_migrations_dir(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "test.db")

    applied = apply_migrations(conn, migrations_dir=tmp_path / "does-not-exist")

    assert applied == []


def test_get_connection_creates_parent_dir(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "test.db"

    conn = get_connection(db_path)
    conn.close()

    assert db_path.parent.exists()


def test_get_connection_enables_foreign_keys(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.db")

    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_chunks_cascade_delete_on_document_removal(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.db")
    apply_migrations(conn)

    conn.execute(
        "INSERT INTO documents (id, filename, stored_filename, mime_type, size_bytes)"
        " VALUES (1, 'a.txt', 'uuid-a', 'text/plain', 10)"
    )
    conn.execute(
        "INSERT INTO chunks (doc_id, seq, text) VALUES (1, 0, 'hello')"
    )

    conn.execute("DELETE FROM documents WHERE id = 1")

    remaining = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert remaining == 0


def test_chunks_fts_insert_trigger_mirrors_new_chunk(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.db")
    apply_migrations(conn)

    conn.execute(
        "INSERT INTO documents (id, filename, stored_filename, mime_type, size_bytes)"
        " VALUES (1, 'a.txt', 'uuid-a', 'text/plain', 10)"
    )
    conn.execute(
        "INSERT INTO chunks (id, doc_id, seq, text) VALUES (1, 1, 0, 'hello world')"
    )

    matches = conn.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'hello'"
    ).fetchall()
    assert matches == [(1,)]


def test_chunks_fts_delete_trigger_removes_deleted_chunk(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.db")
    apply_migrations(conn)

    conn.execute(
        "INSERT INTO documents (id, filename, stored_filename, mime_type, size_bytes)"
        " VALUES (1, 'a.txt', 'uuid-a', 'text/plain', 10)"
    )
    conn.execute(
        "INSERT INTO chunks (id, doc_id, seq, text) VALUES (1, 1, 0, 'hello world')"
    )

    conn.execute("DELETE FROM chunks WHERE id = 1")

    remaining = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    assert remaining == 0


def test_chunks_fts_delete_trigger_fires_on_cascade_delete(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.db")
    apply_migrations(conn)

    conn.execute(
        "INSERT INTO documents (id, filename, stored_filename, mime_type, size_bytes)"
        " VALUES (1, 'a.txt', 'uuid-a', 'text/plain', 10)"
    )
    conn.execute(
        "INSERT INTO chunks (id, doc_id, seq, text) VALUES (1, 1, 0, 'hello world')"
    )

    conn.execute("DELETE FROM documents WHERE id = 1")

    remaining = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    assert remaining == 0


def test_project_migrations_create_documents_table(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "test.db")

    apply_migrations(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    assert columns == {
        "id",
        "filename",
        "stored_filename",
        "mime_type",
        "size_bytes",
        "status",
        "error",
        "created_at",
    }


def test_project_migrations_create_chunks_table(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "test.db")

    apply_migrations(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(chunks)")}
    assert columns == {
        "id",
        "doc_id",
        "seq",
        "text",
        "page_number",
        "paragraph_start",
        "paragraph_end",
        "char_start",
        "char_end",
    }

    index = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='chunks'"
    ).fetchone()
    assert index is not None


def test_run_migrations_applies_and_persists(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_create_widgets.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY);"
    )
    db_path = tmp_path / "test.db"

    applied = run_migrations(db_path=db_path, migrations_dir=migrations_dir)

    assert applied == ["0001_create_widgets.sql"]
    conn = sqlite3.connect(db_path)
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='widgets'"
    ).fetchone()
    assert table is not None


def test_get_connection_can_be_used_from_another_thread(tmp_path: Path) -> None:
    # FastAPI opens a request's connection on one threadpool worker and may run
    # the endpoint on another, so a connection that insists on its creating
    # thread turns any upload into a 500 the moment the workers differ.
    conn = get_connection(tmp_path / "test.db")
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(
                lambda: conn.execute("SELECT 1").fetchone()
            ).result()
    finally:
        conn.close()

    assert result == (1,)


def test_db_path_can_be_overridden_by_environment(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from oracle.common import db; print(db.DEFAULT_DB_PATH)",
        ],
        env={**os.environ, "ORACLE_DB_PATH": str(tmp_path / "elsewhere.db")},
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == str(tmp_path / "elsewhere.db")
