import os
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from oracle.common import db, documents, ingest, search
from oracle.common.ingest import UnsupportedFileTypeError


def allowed_origins() -> list[str]:
    """Browser origins permitted to call the API cross-origin.

    Empty by default, because the SPA is normally served on the same origin as
    the API (the Vite dev proxy, or a reverse proxy in production) and so needs
    no CORS at all. Set ORACLE_ALLOWED_ORIGINS to a comma-separated list only
    when the SPA really is served from somewhere else.
    """
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
    # A sqlite3 connection may only be used on the thread that created it, and
    # FastAPI runs sync endpoints on a threadpool, so open one per request.
    conn = db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_uploads_dir() -> Path:
    return ingest.DEFAULT_UPLOADS_DIR


Connection = Annotated[sqlite3.Connection, Depends(get_connection)]
UploadsDir = Annotated[Path, Depends(get_uploads_dir)]


class DocumentResponse(BaseModel):
    id: int
    filename: str
    status: str


class UploadResponse(BaseModel):
    id: int
    filename: str
    replaced: bool


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


@app.post("/documents", status_code=201)
def add_document(
    conn: Connection, uploads_dir: UploadsDir, file: UploadFile
) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="An uploaded file is required")

    # Only the basename is trusted: a client-supplied filename may contain path
    # separators or traversal segments.
    filename = Path(file.filename).name

    with tempfile.TemporaryDirectory() as staging_dir:
        # ingest_file works from a path on disk and takes the document's
        # filename from it, so stage the upload under its original name.
        staged_path = Path(staging_dir) / filename
        with staged_path.open("wb") as staged_file:
            shutil.copyfileobj(file.file, staged_file)

        try:
            result = ingest.ingest_file(conn, staged_path, uploads_dir=uploads_dir)
        except UnsupportedFileTypeError as exc:
            raise HTTPException(status_code=415, detail=str(exc))

    return UploadResponse(id=result.doc_id, filename=filename, replaced=result.replaced)


@app.get("/documents")
def list_documents(conn: Connection) -> list[DocumentResponse]:
    return [
        DocumentResponse(
            id=document.id, filename=document.filename, status=document.status
        )
        for document in documents.list_documents(conn)
    ]


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
