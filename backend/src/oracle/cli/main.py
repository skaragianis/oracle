import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

from oracle.common import db, documents, embeddings, ingest, search
from oracle.common.ingest import UnsupportedFileTypeError


def main() -> None:
    parser = argparse.ArgumentParser(prog="oracle-cli")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset all documents and uploads",
    )
    parser.add_argument(
        "--add",
        "-a",
        metavar="FILE_PATH",
        help="Add a PDF or DOCX file for later searching",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List processed documents and their status",
    )
    parser.add_argument(
        "--search",
        "-s",
        metavar="QUERY",
        help="Search document chunks based on provided terms",
    )
    args = parser.parse_args()

    if args.reset:
        _reset()
        return

    try:
        conn = _startup()
        if args.add:
            _add(conn, args.add)
            return
        if args.list:
            _list(conn)
            return
        if args.search:
            _search(conn, args.search)
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


def _reset() -> None:
    if db.DEFAULT_DB_PATH.exists():
        db.DEFAULT_DB_PATH.unlink()
    if ingest.DEFAULT_UPLOADS_DIR.exists():
        ingest.remove_document_uploads()
    shutil.rmtree(embeddings.DEFAULT_VECTOR_DB_PATH, ignore_errors=True)
    print(
        f"Reset database at {db.DEFAULT_DB_PATH}, removed documents at "
        f"{ingest.DEFAULT_UPLOADS_DIR} and vectors at {embeddings.DEFAULT_VECTOR_DB_PATH}"
    )


def _add(conn: sqlite3.Connection, file_path: str) -> None:
    source_path = Path(file_path)
    result = ingest.ingest_file(
        conn,
        source_path,
        uploads_dir=ingest.DEFAULT_UPLOADS_DIR,
        vector_index=embeddings.open_vector_index(),
    )
    verb = "Re-added" if result.replaced else "Added"
    print(f"{verb} {file_path} -> {result.destination_path}")

    if result.status != "ready":
        print(f"Warning: {result.error}", file=sys.stderr)


def _list(conn: sqlite3.Connection) -> None:
    documents_list = documents.list_documents(conn)
    if not documents_list:
        print("No documents found.")
        return
    for document in documents_list:
        print(f"[{document.id}] {document.filename} - {document.status}")
    print()
    print(f"{len(documents_list)} documents found.")


def _search(conn: sqlite3.Connection, query: str) -> None:
    results = search.search_hybrid(conn, embeddings.open_vector_index(), query)
    if not results:
        print("No results found.")
        return
    for result in results:
        sources = "+".join(result.sources)
        print(f"[{result.doc_id}] {result.filename} (chunk {result.seq}) [{sources}]")
        print(result.text[:80])
        print()
    print(f"{len(results)} result chunks found.")


if __name__ == "__main__":
    main()
