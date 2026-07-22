import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

from oracle.common import db, documents, embeddings, ingest, search
from oracle.common.ingest import UnsupportedFileTypeError


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _run(parser, args)


def _parse_sources(value: str) -> list[str]:
    sources = [source.strip() for source in value.split(",") if source.strip()]
    if not sources:
        raise argparse.ArgumentTypeError("--sources must not be empty")
    for source in sources:
        if source not in search.SEARCH_SOURCES:
            raise argparse.ArgumentTypeError(
                f"unknown source '{source}', expected one of "
                f"{', '.join(search.SEARCH_SOURCES)}"
            )
    return sources


def _parse_document_ids(value: str) -> list[int]:
    tokens = [token.strip() for token in value.split(",") if token.strip()]
    if not tokens:
        raise argparse.ArgumentTypeError("--documents must not be empty")
    try:
        return [int(token) for token in tokens]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--documents must be a comma-separated list of integers, got '{value}'"
        )


def _build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--delete",
        "-d",
        metavar="DOC_ID",
        type=int,
        help="Delete a document by id",
    )
    parser.add_argument(
        "--sources",
        metavar="SOURCES",
        type=_parse_sources,
        default=list(search.SEARCH_SOURCES),
        help="Comma-separated search sources to use with --search "
        "(default: bm25,vector)",
    )
    parser.add_argument(
        "--documents",
        metavar="DOC_IDS",
        type=_parse_document_ids,
        default=None,
        help="Comma-separated document ids to search with --search "
        "(default: all ready documents)",
    )
    return parser


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
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
            _search(conn, args.search, args.sources, args.documents)
            return
        if args.delete is not None:  # --delete 0 is falsy but still a passed value
            _delete(conn, args.delete)
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
        f"{ingest.DEFAULT_UPLOADS_DIR} and vectors at "
        f"{embeddings.DEFAULT_VECTOR_DB_PATH}"
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


def _search(
    conn: sqlite3.Connection,
    query: str,
    sources: list[str],
    document_ids: list[int] | None,
) -> None:
    results = search.search_hybrid(
        conn,
        embeddings.open_vector_index(),
        query,
        sources=sources,
        document_ids=document_ids,
    )
    if not results:
        print("No results found.")
        return
    for result in results:
        result_sources = "+".join(result.sources)
        print(
            f"[{result.doc_id}] {result.filename} "
            f"(chunk {result.seq}) [{result_sources}]"
        )
        print(result.text[:80])
        print()
    print(f"{len(results)} result chunks found.")


def _delete(conn: sqlite3.Connection, doc_id: int) -> None:
    deleted = ingest.delete_document(
        conn,
        doc_id,
        uploads_dir=ingest.DEFAULT_UPLOADS_DIR,
        vector_index=embeddings.open_vector_index(),
    )
    if not deleted:
        print(f"Error: no document found with id {doc_id}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Deleted document {doc_id}")


if __name__ == "__main__":
    main()
