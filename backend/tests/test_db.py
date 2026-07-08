import sqlite3

from oracle.common.db import apply_migrations, get_connection, run_migrations


def test_apply_migrations_creates_schema_migrations_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "test.db")

    apply_migrations(conn, migrations_dir=tmp_path / "migrations")

    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    assert table is not None


def test_apply_migrations_runs_pending_sql_files_in_order(tmp_path):
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


def test_apply_migrations_skips_already_applied(tmp_path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_create_widgets.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY);"
    )
    conn = sqlite3.connect(tmp_path / "test.db")
    apply_migrations(conn, migrations_dir=migrations_dir)

    second_run = apply_migrations(conn, migrations_dir=migrations_dir)

    assert second_run == []


def test_apply_migrations_with_no_migrations_dir(tmp_path):
    conn = sqlite3.connect(tmp_path / "test.db")

    applied = apply_migrations(conn, migrations_dir=tmp_path / "does-not-exist")

    assert applied == []


def test_get_connection_creates_parent_dir(tmp_path):
    db_path = tmp_path / "nested" / "test.db"

    conn = get_connection(db_path)
    conn.close()

    assert db_path.parent.exists()


def test_project_migrations_create_documents_table(tmp_path):
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


def test_run_migrations_applies_and_persists(tmp_path):
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
