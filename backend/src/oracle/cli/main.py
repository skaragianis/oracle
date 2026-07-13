import argparse
import sqlite3
import sys
from pathlib import Path

from oracle.common import db, ingest
from oracle.common.ingest import UnsupportedFileTypeError


def main() -> None:
    parser = argparse.ArgumentParser(prog="oracle-cli")
    parser.add_argument(
        "--init",
        "-i",
        action="store_true",
        help="Delete the database if it exists, then recreate it and run migrations",
    )
    parser.add_argument(
        "--add",
        "-a",
        metavar="FILE_PATH",
        help="Add a PDF or DOCX file for later searching",
    )
    args = parser.parse_args()

    if args.init:
        _init()
        return

    try:
        conn = _startup()
        if args.add:
            _add(conn, args.add)
            return
        parser.print_usage()
    except FileNotFoundError as exc:
        print(f"Error: file not found: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except UnsupportedFileTypeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        conn.close()


def _startup() -> sqlite3.Connection:
    conn = db.get_connection(db.DEFAULT_DB_PATH)
    db.apply_migrations(conn, db.MIGRATIONS_DIR)
    return conn


def _init() -> None:
    if db.DEFAULT_DB_PATH.exists():
        db.DEFAULT_DB_PATH.unlink()
    try:
        conn = _startup()
    finally:
        conn.close()
    print(f"Initialized database at {db.DEFAULT_DB_PATH}")


def _add(conn: sqlite3.Connection, file_path: str) -> None:
    source_path = Path(file_path)
    result = ingest.ingest_file(
        conn, source_path, uploads_dir=ingest.DEFAULT_UPLOADS_DIR
    )
    print(f"Added {file_path} -> {result.destination_path}")


if __name__ == "__main__":
    main()
