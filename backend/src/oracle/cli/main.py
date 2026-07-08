import argparse
import mimetypes
import sqlite3
import sys
from pathlib import Path

from oracle.common import db, ingest
from oracle.common.documents import create_document
from oracle.common.ingest import UnsupportedFileTypeError


def main() -> None:
    parser = argparse.ArgumentParser(prog="oracle-cli")
    parser.add_argument(
        "--add",
        "-a",
        metavar="FILE_PATH",
        help="Add a PDF or DOCX file for later searching",
    )
    args = parser.parse_args()

    conn = _startup()
    try:
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


def _add(conn: sqlite3.Connection, file_path: str) -> None:
    source_path = Path(file_path)
    destination_path = ingest.ingest_file(
        source_path, uploads_dir=ingest.DEFAULT_UPLOADS_DIR
    )
    mime_type, _ = mimetypes.guess_type(source_path.name)

    create_document(
        conn,
        filename=source_path.name,
        stored_filename=destination_path.name,
        mime_type=mime_type,
        size_bytes=destination_path.stat().st_size,
    )
    print(f"Added {file_path} -> {destination_path}")


if __name__ == "__main__":
    main()
