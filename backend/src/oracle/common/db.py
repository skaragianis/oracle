import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "oracle.db"
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def apply_migrations(
    conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR
) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )

    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}

    pending = sorted(
        path for path in migrations_dir.glob("*.sql") if path.name not in applied
    )

    applied_now = []
    for path in pending:
        conn.executescript(path.read_text())
        with conn:
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (path.name,)
            )
        applied_now.append(path.name)

    return applied_now


def run_migrations(
    db_path: Path = DEFAULT_DB_PATH, migrations_dir: Path = MIGRATIONS_DIR
) -> list[str]:
    conn = get_connection(db_path)
    try:
        return apply_migrations(conn, migrations_dir)
    finally:
        conn.close()
