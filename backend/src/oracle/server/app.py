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
from pydantic import BaseModel, Field

from oracle.common import db, documents, embeddings, ingest, search
from oracle.common.ingest import UnsupportedFileTypeError
from oracle.common.search import SearchSource

SHUTDOWN_INGEST_TIMEOUT_SECONDS = 10


def allowed_origins() -> list[str]:
    configured = os.environ.get("ORACLE_ALLOWED_ORIGINS", "")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


_shutting_down = threading.Event()
_reprocess_thread: threading.Thread | None = None


def request_shutdown() -> None:
    _shutting_down.set()


def _startup(
    *,
    connection_factory: Callable[[], sqlite3.Connection] = db.get_connection,
    uploads_dir: Path = ingest.DEFAULT_UPLOADS_DIR,
) -> embeddings.VectorIndex:
    global _reprocess_thread
    _shutting_down.clear()
    db.run_migrations()
    vector_index = embeddings.get_default_vector_index()
    _reprocess_thread = threading.Thread(
        target=_reprocess_pending_in_background,
        args=(connection_factory, uploads_dir, vector_index),
        name="reprocess-pending",
        daemon=True,
    )
    _reprocess_thread.start()
    return vector_index


def _shutdown_gracefully(
    vector_index: embeddings.VectorIndex,
    *,
    timeout: float = SHUTDOWN_INGEST_TIMEOUT_SECONDS,
    connection_factory: Callable[[], sqlite3.Connection] = db.get_connection,
) -> None:
    _shutting_down.set()
    acquired = _ingest_slot.acquire(timeout=timeout)
    try:
        conn = connection_factory()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        vector_index.close()
    finally:
        if acquired:
            _ingest_slot.release()


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    vector_index = _startup()
    yield
    _shutdown_gracefully(vector_index)


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
    sources: list[SearchSource] = Field(default=list(SearchSource), min_length=1)
    document_ids: list[int] | None = None


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
    if _shutting_down.is_set():
        return
    with _ingest_slot:
        # A second queued task can have been blocked on the semaphore above
        # already passing this check, so it must be checked again once held.
        if _shutting_down.is_set():
            return
        conn = connection_factory()
        try:
            ingest.process_document(
                conn,
                doc_id,
                stored_path,
                vector_index=vector_index,
                should_stop=_shutting_down.is_set,
            )
        finally:
            conn.close()


def _reprocess_pending_in_background(
    connection_factory: Callable[[], sqlite3.Connection],
    uploads_dir: Path,
    vector_index: embeddings.VectorIndex,
) -> None:
    conn = connection_factory()
    try:
        pending = documents.list_pending_documents(conn)
    finally:
        conn.close()

    for doc_id, stored_filename in pending:
        if _shutting_down.is_set():
            return
        stored_path = uploads_dir / stored_filename
        if not stored_path.is_file():
            conn = connection_factory()
            try:
                documents.mark_document_failed(
                    conn, doc_id, f"Uploaded file missing: {stored_path}"
                )
            finally:
                conn.close()
            continue
        _process_document_in_background(
            connection_factory, vector_index, doc_id, stored_path
        )


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
    results = search.search_hybrid(
        conn,
        vector_index,
        request.query,
        sources=request.sources,
        document_ids=request.document_ids,
    )
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
