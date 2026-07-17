import os
import shutil
import sqlite3
import tempfile
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from oracle.common import db, documents, embeddings, ingest, search
from oracle.common.ingest import UnsupportedFileTypeError


def allowed_origins() -> list[str]:
    configured = os.environ.get("ORACLE_ALLOWED_ORIGINS", "")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.run_migrations()
    # Downloads the embedding model on the very first startup; after that it
    # loads from the cache dir.
    vector_index = embeddings.get_default_vector_index()
    conn = db.get_connection()
    try:
        ingest.reprocess_pending_documents(conn, vector_index=vector_index)
    finally:
        conn.close()
    yield


app = FastAPI(lifespan=_lifespan)

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


def get_vector_index() -> embeddings.VectorIndex:
    return embeddings.get_default_vector_index()


Connection = Annotated[sqlite3.Connection, Depends(get_connection)]
UploadsDir = Annotated[Path, Depends(get_uploads_dir)]
ConnectionFactory = Annotated[
    Callable[[], sqlite3.Connection], Depends(get_connection_factory)
]
VectorIndexDep = Annotated[embeddings.VectorIndex, Depends(get_vector_index)]


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
    sources: list[str]


class SearchResponse(BaseModel):
    results: list[SearchResultResponse]


@app.get("/health")
def _health() -> dict[str, str]:
    return {"status": "ok"}


# Used to serialise concurrent upload processing
_ingest_slot = threading.Semaphore(1)


def _process_document_in_background(
    connection_factory: Callable[[], sqlite3.Connection],
    vector_index: embeddings.VectorIndex,
    doc_id: int,
    stored_path: Path,
) -> None:
    with _ingest_slot:
        conn = connection_factory()
        try:
            ingest.process_document(
                conn, doc_id, stored_path, vector_index=vector_index
            )
        finally:
            conn.close()


@app.post("/documents", status_code=202)
def _add_document(
    conn: Connection,
    uploads_dir: UploadsDir,
    connection_factory: ConnectionFactory,
    vector_index: VectorIndexDep,
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
            staged = ingest.stage_file(
                conn, staged_path, uploads_dir=uploads_dir, vector_index=vector_index
            )
        except UnsupportedFileTypeError as exc:
            raise HTTPException(status_code=415, detail=str(exc))

    background_tasks.add_task(
        _process_document_in_background,
        connection_factory,
        vector_index,
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
def _list_documents(conn: Connection) -> list[DocumentResponse]:
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
def _get_document(conn: Connection, document_id: int) -> DocumentResponse:
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


@app.delete("/documents/{document_id}", status_code=204)
def _delete_document(
    conn: Connection,
    uploads_dir: UploadsDir,
    vector_index: VectorIndexDep,
    document_id: int,
) -> None:
    deleted = ingest.delete_document(
        conn, document_id, uploads_dir=uploads_dir, vector_index=vector_index
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")


@app.post("/search")
def _search_documents(
    conn: Connection, vector_index: VectorIndexDep, request: SearchRequest
) -> SearchResponse:
    results = search.search_hybrid(conn, vector_index, request.query)
    return SearchResponse(
        results=[
            SearchResultResponse(
                doc_id=result.doc_id,
                filename=result.filename,
                chunk_id=result.chunk_id,
                seq=result.seq,
                text=result.text,
                page_number=result.page_number,
                sources=result.sources,
            )
            for result in results
        ]
    )
