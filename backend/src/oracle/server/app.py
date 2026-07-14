import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from oracle.common import db, documents, ingest, search
from oracle.common.ingest import UnsupportedFileTypeError


def allowed_origins() -> list[str]:
    configured = os.environ.get("ORACLE_ALLOWED_ORIGINS", "")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.run_migrations()
    yield


app = FastAPI(lifespan=lifespan)

if origins := allowed_origins():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def get_connection() -> Iterator[sqlite3.Connection]:
    conn = db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_uploads_dir() -> Path:
    return ingest.DEFAULT_UPLOADS_DIR


def get_connection_factory() -> Callable[[], sqlite3.Connection]:
    return db.get_connection


Connection = Annotated[sqlite3.Connection, Depends(get_connection)]
UploadsDir = Annotated[Path, Depends(get_uploads_dir)]
ConnectionFactory = Annotated[
    Callable[[], sqlite3.Connection], Depends(get_connection_factory)
]


class DocumentResponse(BaseModel):
    id: int
    filename: str
    status: str
    error: str | None = None


class UploadResponse(BaseModel):
    id: int
    filename: str
    replaced: bool
    status: str


class SearchRequest(BaseModel):
    query: str


class SearchResultResponse(BaseModel):
    doc_id: int
    filename: str
    chunk_id: int
    seq: int
    text: str
    page_number: int | None


class SearchResponse(BaseModel):
    results: list[SearchResultResponse]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def process_document_in_background(
    connection_factory: Callable[[], sqlite3.Connection],
    doc_id: int,
    stored_path: Path,
) -> None:
    conn = connection_factory()
    try:
        ingest.process_document(conn, doc_id, stored_path)
    finally:
        conn.close()


@app.post("/documents", status_code=202)
def add_document(
    conn: Connection,
    uploads_dir: UploadsDir,
    connection_factory: ConnectionFactory,
    background_tasks: BackgroundTasks,
    file: UploadFile,
) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="An uploaded file is required")

    filename = Path(file.filename).name

    with tempfile.TemporaryDirectory() as staging_dir:
        staged_path = Path(staging_dir) / filename
        with staged_path.open("wb") as staged_file:
            shutil.copyfileobj(file.file, staged_file)

        try:
            staged = ingest.stage_file(conn, staged_path, uploads_dir=uploads_dir)
        except UnsupportedFileTypeError as exc:
            raise HTTPException(status_code=415, detail=str(exc))

    background_tasks.add_task(
        process_document_in_background,
        connection_factory,
        staged.doc_id,
        staged.destination_path,
    )

    return UploadResponse(
        id=staged.doc_id,
        filename=filename,
        replaced=staged.replaced,
        status="pending",
    )


@app.get("/documents")
def list_documents(conn: Connection) -> list[DocumentResponse]:
    return [
        DocumentResponse(
            id=document.id,
            filename=document.filename,
            status=document.status,
            error=document.error,
        )
        for document in documents.list_documents(conn)
    ]


@app.get("/documents/{document_id}")
def get_document(conn: Connection, document_id: int) -> DocumentResponse:
    """Polled by clients waiting for a pending document to reach a terminal status."""
    document = documents.get_document(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        error=document.error,
    )


@app.post("/search")
def search_documents(conn: Connection, request: SearchRequest) -> SearchResponse:
    results = search.search_chunks(conn, request.query)
    return SearchResponse(
        results=[
            SearchResultResponse(
                doc_id=result.doc_id,
                filename=result.filename,
                chunk_id=result.chunk_id,
                seq=result.seq,
                text=result.text,
                page_number=result.page_number,
            )
            for result in results
        ]
    )
