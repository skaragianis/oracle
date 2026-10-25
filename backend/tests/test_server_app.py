import io
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from unittest import mock

import docx
import httpx2
import pymupdf
import pytest
from fastapi.testclient import TestClient

from oracle.common import db, documents, ingest
from oracle.common.db import apply_migrations
from oracle.common.embeddings import VectorIndex
from oracle.server import app as app_module
from oracle.server.app import (
    _ingest_slot,
    _process_document_in_background,
    _reprocess_pending_in_background,
    _shutdown_gracefully,
    _shutting_down,
    _startup,
    allowed_origins,
    app,
    get_connection,
    get_connection_factory,
    get_uploads_dir,
    get_vector_index,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    # check_same_thread=False because one connection is shared across the whole
    # test while endpoints run on TestClient's threadpool. The app itself opens a
    # connection per request, on the thread that uses it, so it doesn't need this.
    connection = sqlite3.connect(db_path, check_same_thread=False)
    apply_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def client(
    conn: sqlite3.Connection, db_path: Path, tmp_path: Path, vector_index: VectorIndex
) -> Iterator[TestClient]:
    uploads_dir = tmp_path / "uploads"
    app.dependency_overrides[get_connection] = lambda: conn
    app.dependency_overrides[get_uploads_dir] = lambda: uploads_dir
    # A fake embedder plus an in-memory Chroma collection: real vector search
    # without the model download that get_default_vector_index would trigger.
    app.dependency_overrides[get_vector_index] = lambda: vector_index
    # The background task must open its own connection, exactly as it does in
    # production — but to this test's database, not the real one. Overriding this
    # is what keeps a test upload from chunking into data/oracle.db.
    app.dependency_overrides[get_connection_factory] = lambda: (
        lambda: sqlite3.connect(db_path)
    )
    # Not used as a context manager: that would run the lifespan, which migrates
    # the real database at db.DEFAULT_DB_PATH rather than this test's.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_shutting_down() -> Iterator[None]:
    yield
    _shutting_down.clear()


def _pdf_bytes(paragraphs: Iterable[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=842)
    y = 72
    for paragraph in paragraphs:
        page.insert_text((72, y), paragraph)
        y += 40
    pdf_bytes = bytes(doc.tobytes())
    doc.close()
    return pdf_bytes


def _upload(
    client: TestClient, filename: str, paragraphs: Iterable[str] = ("Hello world.",)
) -> httpx2.Response:
    return client.post(
        "/documents",
        files={"file": (filename, _pdf_bytes(paragraphs), "application/pdf")},
    )


def _docx_bytes(paragraphs: Iterable[str]) -> bytes:
    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _write_pdf_file(path: Path, paragraphs: Iterable[str] = ("Hello world.",)) -> None:
    path.write_bytes(_pdf_bytes(paragraphs))


def _validation_errors(response: httpx2.Response) -> list[tuple[str, list[object]]]:
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    items = response.json()["detail"]
    for item in items:
        assert {"type", "loc", "msg"} <= item.keys()
    return [(item["type"], item["loc"]) for item in items]


def _stub_background_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "_process_document_in_background", lambda *a: None)


def test_allowed_origins_is_empty_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # The SPA is same-origin with the API by default, so no CORS is configured.
    monkeypatch.delenv("ORACLE_ALLOWED_ORIGINS", raising=False)

    assert allowed_origins() == []


def test_allowed_origins_parses_a_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ORACLE_ALLOWED_ORIGINS", "http://192.168.1.2:5173, http://localhost:5173"
    )

    assert allowed_origins() == ["http://192.168.1.2:5173", "http://localhost:5173"]


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}


def test_add_document_stores_document_and_chunks(
    client: TestClient, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    response = _upload(client, "source.pdf")

    # 202, not 201: the upload is accepted as 'pending' and chunked in a
    # background task, which TestClient runs before returning the response.
    assert response.status_code == 202
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert body == {
        "id": body["id"],
        "filename": "source.pdf",
        "replaced": False,
        "status": "pending",
    }
    assert type(body["id"]) is int

    doc_row = conn.execute(
        "SELECT filename, status FROM documents WHERE id = ?", (body["id"],)
    ).fetchone()
    assert doc_row == ("source.pdf", "ready")

    chunk_rows = conn.execute(
        "SELECT text FROM chunks WHERE doc_id = ?", (body["id"],)
    ).fetchall()
    assert chunk_rows == [("Hello world.\n",)]

    assert len(list((tmp_path / "uploads").iterdir())) == 1


def test_add_document_replaces_existing_document_with_same_filename(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    first = _upload(client, "source.pdf", ["Hello world."])
    second = _upload(client, "source.pdf", ["Goodbye world."])

    assert second.status_code == 202
    assert second.json() == {
        "id": first.json()["id"],
        "filename": "source.pdf",
        "replaced": True,
        "status": "pending",
    }
    assert [doc["filename"] for doc in client.get("/documents").json()] == [
        "source.pdf"
    ]

    chunk_rows = conn.execute(
        "SELECT text FROM chunks WHERE doc_id = ?", (second.json()["id"],)
    ).fetchall()
    assert chunk_rows == [("Goodbye world.\n",)]


def test_add_document_strips_path_from_client_supplied_filename(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    response = client.post(
        "/documents",
        files={"file": ("../../etc/evil.pdf", _pdf_bytes(["Hi."]), "application/pdf")},
    )

    assert response.status_code == 202
    assert response.json()["filename"] == "evil.pdf"


def test_add_document_chunks_a_docx(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    response = client.post(
        "/documents",
        files={
            "file": (
                "notes.docx",
                _docx_bytes(["Hello world."]),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 202
    status, error = conn.execute(
        "SELECT status, error FROM documents WHERE id = ?", (response.json()["id"],)
    ).fetchone()
    assert status == "ready"
    assert error is None
    chunk_rows = conn.execute(
        "SELECT text FROM chunks WHERE doc_id = ?", (response.json()["id"],)
    ).fetchall()
    assert chunk_rows == [("Hello world.\n",)]


def test_add_document_fails_a_malformed_docx(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    # A malformed .docx is stored but fails to parse, so it isn't searchable and
    # must not be reported as ready. It must not stay 'pending' either: a client
    # polls until the status is terminal, and would wait on it forever.
    response = client.post(
        "/documents",
        files={
            "file": (
                "notes.docx",
                b"file contents",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 202
    status, error = conn.execute(
        "SELECT status, error FROM documents WHERE id = ?", (response.json()["id"],)
    ).fetchone()
    assert status == "failed"
    assert error


def test_add_document_rejects_unsupported_file_type(client: TestClient) -> None:
    response = client.post(
        "/documents",
        files={"file": ("notes.txt", b"file contents", "text/plain")},
    )

    assert response.status_code == 415
    assert response.headers["content-type"] == "application/json"
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert ".pdf" in detail and ".docx" in detail


def test_add_document_requires_a_file(client: TestClient) -> None:
    response = client.post("/documents")

    assert _validation_errors(response) == [("missing", ["body", "file"])]


def test_background_processing_serializes_concurrent_uploads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two large uploads processed at once is what OOM-killed the server;
    background ingestion must never overlap regardless of how many uploads
    arrive together."""
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_process_document(
        conn: object,
        doc_id: int,
        stored_path: Path,
        *,
        vector_index: object,
        should_stop: object = None,
    ) -> None:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1

    monkeypatch.setattr(ingest, "process_document", fake_process_document)

    class _NullConnection:
        def close(self) -> None:
            pass

    threads = [
        threading.Thread(
            target=_process_document_in_background,
            args=(_NullConnection, None, doc_id, Path("unused")),
        )
        for doc_id in (1, 2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active == 1


def test_list_documents_is_empty_without_uploads(client: TestClient) -> None:
    response = client.get("/documents")

    assert response.status_code == 200
    assert response.json() == []


def test_list_documents_returns_uploaded_documents(client: TestClient) -> None:
    first = _upload(client, "first.pdf")
    second = _upload(client, "second.pdf")

    response = client.get("/documents")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": first.json()["id"],
            "filename": "first.pdf",
            "status": "ready",
            "error": None,
        },
        {
            "id": second.json()["id"],
            "filename": "second.pdf",
            "status": "ready",
            "error": None,
        },
    ]


def test_search_fuses_bm25_and_vector_matches_into_one_result(
    client: TestClient,
) -> None:
    uploaded = _upload(client, "source.pdf", ["The quick brown fox."])

    response = client.post("/search", json={"query": "brown fox"})

    assert response.status_code == 200
    results = response.json()["results"]
    # The one chunk matches by keyword and is also the nearest vector; RRF
    # fuses those two hits into a single result carrying both sources.
    assert len(results) == 1
    assert response.headers["content-type"] == "application/json"
    assert set(results[0]) == {
        "doc_id",
        "filename",
        "chunk_id",
        "seq",
        "text",
        "page_number",
        "sources",
    }
    assert set(response.json()) == {"results"}
    assert type(results[0]["chunk_id"]) is int
    assert type(results[0]["seq"]) is int
    assert type(results[0]["page_number"]) is int
    assert results[0]["sources"] == ["bm25", "vector"]
    assert results[0]["doc_id"] == uploaded.json()["id"]
    assert results[0]["filename"] == "source.pdf"
    assert results[0]["seq"] == 0
    assert results[0]["page_number"] == 1
    assert "quick brown fox" in results[0]["text"]


def test_search_returns_at_most_five_fused_results(client: TestClient) -> None:
    # Eight documents, not eight paragraphs: short paragraphs would buffer into
    # a single chunk and the cap would pass vacuously.
    for i in range(8):
        _upload(client, f"source{i}.pdf", [f"The fox sighting number {i}."])

    response = client.post("/search", json={"query": "fox"})

    assert response.status_code == 200
    assert len(response.json()["results"]) == 5


def test_search_without_keyword_match_still_returns_nearest_vectors(
    client: TestClient,
) -> None:
    _upload(client, "source.pdf", ["The quick brown fox."])

    response = client.post("/search", json={"query": "elephant"})

    assert response.status_code == 200
    results = response.json()["results"]
    assert [result["sources"] for result in results] == [["vector"]]


def test_search_returns_no_results_when_nothing_is_indexed(client: TestClient) -> None:
    response = client.post("/search", json={"query": "elephant"})

    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_search_requires_a_query(client: TestClient) -> None:
    response = client.post("/search", json={})

    assert _validation_errors(response) == [("missing", ["body", "query"])]


def test_search_with_explicit_sources_forwards_them(client: TestClient) -> None:
    _upload(client, "source.pdf", ["The quick brown fox."])

    response = client.post("/search", json={"query": "brown fox", "sources": ["bm25"]})

    assert response.status_code == 200
    results = response.json()["results"]
    assert results
    assert all(result["sources"] == ["bm25"] for result in results)


def test_search_sources_default_to_both(client: TestClient) -> None:
    _upload(client, "source.pdf", ["The quick brown fox."])

    response = client.post("/search", json={"query": "brown fox"})

    assert response.status_code == 200
    assert response.json()["results"][0]["sources"] == ["bm25", "vector"]


def test_search_with_document_ids_restricts_results_to_those_documents(
    client: TestClient,
) -> None:
    first = _upload(client, "first.pdf", ["The quick brown fox."])
    _upload(client, "second.pdf", ["Another quick brown fox report."])

    response = client.post(
        "/search",
        json={"query": "fox", "document_ids": [first.json()["id"]]},
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert results
    assert all(result["doc_id"] == first.json()["id"] for result in results)


def test_search_omitting_document_ids_searches_all_documents(
    client: TestClient,
) -> None:
    first = _upload(client, "first.pdf", ["The quick brown fox."])
    second = _upload(client, "second.pdf", ["Another quick brown fox report."])

    response = client.post("/search", json={"query": "fox"})

    assert response.status_code == 200
    doc_ids = {result["doc_id"] for result in response.json()["results"]}
    assert doc_ids == {first.json()["id"], second.json()["id"]}


def test_search_with_explicit_empty_document_ids_returns_no_results(
    client: TestClient,
) -> None:
    _upload(client, "source.pdf", ["The quick brown fox."])

    response = client.post("/search", json={"query": "fox", "document_ids": []})

    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_search_rejects_an_unknown_source(client: TestClient) -> None:
    response = client.post("/search", json={"query": "brown fox", "sources": ["bogus"]})

    assert _validation_errors(response) == [("enum", ["body", "sources", 0])]


def test_search_rejects_an_empty_sources_list(client: TestClient) -> None:
    response = client.post("/search", json={"query": "brown fox", "sources": []})

    assert _validation_errors(response) == [("too_short", ["body", "sources"])]


def test_get_document_returns_a_ready_document(client: TestClient) -> None:
    uploaded = _upload(client, "source.pdf")

    response = client.get(f"/documents/{uploaded.json()['id']}")

    assert response.status_code == 200
    assert response.json() == {
        "id": uploaded.json()["id"],
        "filename": "source.pdf",
        "status": "ready",
        "error": None,
    }


def test_get_document_reports_the_failure_reason(client: TestClient) -> None:
    uploaded = client.post(
        "/documents",
        files={"file": ("notes.docx", b"file contents", "application/msword")},
    )

    response = client.get(f"/documents/{uploaded.json()['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"]


def test_get_document_404s_for_an_unknown_id(client: TestClient) -> None:
    response = client.get("/documents/999")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Document not found"}


def test_delete_document_removes_document_upload_and_chunks(
    client: TestClient, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    uploaded = _upload(client, "source.pdf")
    doc_id = uploaded.json()["id"]

    response = client.delete(f"/documents/{doc_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE doc_id = ?", (doc_id,)
        ).fetchone()[0]
        == 0
    )
    assert list((tmp_path / "uploads").iterdir()) == []


def test_delete_document_404s_for_an_unknown_id(client: TestClient) -> None:
    response = client.delete("/documents/999")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Document not found"}


def test_background_processing_bails_when_shutting_down(
    conn: sqlite3.Connection,
    db_path: Path,
    tmp_path: Path,
    vector_index: VectorIndex,
) -> None:
    doc_id = documents.create_document(
        conn,
        filename="source.pdf",
        stored_filename="source.pdf",
        mime_type="application/pdf",
        size_bytes=1,
    )
    _shutting_down.set()

    # vector_index is never touched: the shutdown check bails before the
    # background task reaches process_document.
    _process_document_in_background(
        lambda: sqlite3.connect(db_path),
        vector_index,
        doc_id,
        tmp_path / "source.pdf",
    )

    document = conn.execute(
        "SELECT status FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert document == ("pending",)
    chunk_count = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE doc_id = ?", (doc_id,)
    ).fetchone()[0]
    assert chunk_count == 0


def test_reprocess_pending_in_background_drains_the_backlog(
    conn: sqlite3.Connection,
    db_path: Path,
    tmp_path: Path,
    vector_index: VectorIndex,
) -> None:
    uploads_dir = tmp_path / "uploads"
    first_source = tmp_path / "first.pdf"
    second_source = tmp_path / "second.pdf"
    _write_pdf_file(first_source, ["First document."])
    _write_pdf_file(second_source, ["Second document."])
    first = ingest.stage_file(
        conn, first_source, uploads_dir=uploads_dir, vector_index=vector_index
    )
    second = ingest.stage_file(
        conn, second_source, uploads_dir=uploads_dir, vector_index=vector_index
    )

    _reprocess_pending_in_background(
        lambda: sqlite3.connect(db_path), uploads_dir, vector_index
    )

    statuses = conn.execute("SELECT id, status FROM documents ORDER BY id").fetchall()
    assert statuses == [(first.doc_id, "ready"), (second.doc_id, "ready")]


def test_reprocess_pending_in_background_bails_when_shutting_down(
    conn: sqlite3.Connection,
    db_path: Path,
    tmp_path: Path,
    vector_index: VectorIndex,
) -> None:
    uploads_dir = tmp_path / "uploads"
    source = tmp_path / "source.pdf"
    _write_pdf_file(source, ["Hello world."])
    staged = ingest.stage_file(
        conn, source, uploads_dir=uploads_dir, vector_index=vector_index
    )
    _shutting_down.set()

    _reprocess_pending_in_background(
        lambda: sqlite3.connect(db_path), uploads_dir, vector_index
    )

    status = conn.execute(
        "SELECT status FROM documents WHERE id = ?", (staged.doc_id,)
    ).fetchone()[0]
    assert status == "pending"


def test_reprocess_pending_in_background_fails_a_document_with_missing_upload(
    conn: sqlite3.Connection,
    db_path: Path,
    tmp_path: Path,
    vector_index: VectorIndex,
) -> None:
    uploads_dir = tmp_path / "uploads"
    doc_id = documents.create_document(
        conn,
        filename="source.pdf",
        stored_filename="missing.pdf",
        mime_type="application/pdf",
        size_bytes=1,
    )

    _reprocess_pending_in_background(
        lambda: sqlite3.connect(db_path), uploads_dir, vector_index
    )

    status, error = conn.execute(
        "SELECT status, error FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert status == "failed"
    assert error is not None
    assert "Uploaded file missing" in error


def test_reprocess_pending_in_background_warns_about_a_missing_upload(
    conn: sqlite3.Connection,
    db_path: Path,
    tmp_path: Path,
    vector_index: VectorIndex,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uploads_dir = tmp_path / "uploads"
    doc_id = documents.create_document(
        conn,
        filename="source.pdf",
        stored_filename="missing.pdf",
        mime_type="application/pdf",
        size_bytes=1,
    )

    with caplog.at_level(logging.WARNING, logger="oracle.server.app"):
        _reprocess_pending_in_background(
            lambda: sqlite3.connect(db_path), uploads_dir, vector_index
        )

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    assert any(
        f"document {doc_id}" in message and "missing" in message for message in warnings
    )


def test_startup_returns_before_the_backlog_finishes(
    db_path: Path,
    vector_index: VectorIndex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()

    def fake_reprocess(
        connection_factory: object, uploads_dir: object, vector_index: object
    ) -> None:
        release.wait(timeout=5)

    monkeypatch.setattr(app_module, "_reprocess_pending_in_background", fake_reprocess)
    monkeypatch.setattr(
        app_module.embeddings, "get_default_vector_index", lambda: vector_index
    )
    monkeypatch.setattr(app_module.db, "run_migrations", lambda: None)

    start = time.monotonic()
    returned_index = _startup(connection_factory=lambda: sqlite3.connect(db_path))
    elapsed = time.monotonic() - start
    reprocess_thread = app_module._reprocess_thread
    assert reprocess_thread is not None

    try:
        assert elapsed < 1.0
        assert returned_index is vector_index
        assert reprocess_thread.is_alive()
    finally:
        release.set()
        reprocess_thread.join(timeout=5)


def test_shutdown_gracefully_checkpoints_wal_and_closes_vector_index(
    db_path: Path, vector_index: VectorIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ephemeral Chroma clients share one underlying System keyed by settings and
    # only tear it down once every client sharing it has closed, so closing just
    # this test's client wouldn't reliably make a later real operation raise.
    # Spy on the client's own close() instead of relying on that side effect.
    close_spy = mock.Mock(wraps=vector_index._client.close)
    monkeypatch.setattr(vector_index._client, "close", close_spy)

    # Kept open past the checkpoint: closing the last WAL connection triggers
    # its own automatic checkpoint, which would make this test pass vacuously.
    setup_conn = db.get_connection(db_path)
    apply_migrations(setup_conn)
    documents.create_document(
        setup_conn,
        filename="source.pdf",
        stored_filename="source.pdf",
        mime_type="application/pdf",
        size_bytes=1,
    )

    wal_path = db_path.with_name(db_path.name + "-wal")
    assert wal_path.exists() and wal_path.stat().st_size > 0

    try:
        _shutdown_gracefully(
            vector_index, connection_factory=lambda: db.get_connection(db_path)
        )

        assert not wal_path.exists() or wal_path.stat().st_size == 0
        count = setup_conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert count == 1
    finally:
        setup_conn.close()

    close_spy.assert_called_once()


def test_shutdown_gracefully_falls_through_when_ingest_holds_the_slot(
    db_path: Path, vector_index: VectorIndex
) -> None:
    held = threading.Event()
    release = threading.Event()

    def hold_ingest_slot() -> None:
        _ingest_slot.acquire()
        held.set()
        release.wait()
        _ingest_slot.release()

    holder = threading.Thread(target=hold_ingest_slot)
    holder.start()
    assert held.wait(timeout=1)

    try:
        start = time.monotonic()
        _shutdown_gracefully(
            vector_index,
            timeout=0.2,
            connection_factory=lambda: db.get_connection(db_path),
        )
        elapsed = time.monotonic() - start
    finally:
        release.set()
        holder.join(timeout=1)

    assert elapsed < 1.0


def test_shutdown_gracefully_warns_when_ingest_outlasts_the_timeout(
    db_path: Path, vector_index: VectorIndex, caplog: pytest.LogCaptureFixture
) -> None:
    held = threading.Event()
    release = threading.Event()

    def hold_ingest_slot() -> None:
        _ingest_slot.acquire()
        held.set()
        release.wait()
        _ingest_slot.release()

    holder = threading.Thread(target=hold_ingest_slot)
    holder.start()
    assert held.wait(timeout=1)

    try:
        with caplog.at_level(logging.WARNING, logger="oracle.server.app"):
            _shutdown_gracefully(
                vector_index,
                timeout=0.2,
                connection_factory=lambda: db.get_connection(db_path),
            )
    finally:
        release.set()
        holder.join(timeout=1)

    # Abandoning an in-flight ingest at the timeout must leave a trace
    assert any(
        record.levelno == logging.WARNING and "still running" in record.getMessage()
        for record in caplog.records
    )


# HTTP contract: status codes, validation-error bodies, content types and response
# models. These pin behaviour FastAPI/Starlette/Pydantic own, so a framework bump
# that changes request parsing or serialisation fails here rather than in the SPA.


def test_unknown_route_404s_with_a_json_detail(client: TestClient) -> None:
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/health"),
        ("put", "/documents"),
        ("delete", "/documents"),
        ("post", "/documents/1"),
        ("put", "/documents/1"),
        ("get", "/search"),
    ],
)
def test_wrong_method_405s_with_an_allow_header(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path)

    assert response.status_code == 405
    assert response.json() == {"detail": "Method Not Allowed"}


def test_add_document_with_a_differently_named_multipart_field_422s(
    client: TestClient,
) -> None:
    response = client.post(
        "/documents", files={"upload": ("source.pdf", b"x", "application/pdf")}
    )

    assert _validation_errors(response) == [("missing", ["body", "file"])]


def test_add_document_with_a_json_body_422s(client: TestClient) -> None:
    response = client.post("/documents", json={"file": "source.pdf"})

    assert _validation_errors(response) == [("missing", ["body", "file"])]


def test_add_document_with_a_plain_form_field_instead_of_a_file_422s(
    client: TestClient,
) -> None:
    response = client.post("/documents", data={"file": "source.pdf"})

    assert _validation_errors(response) == [("value_error", ["body", "file"])]


def test_add_document_with_an_empty_filename_422s(client: TestClient) -> None:
    # An empty filename makes the multipart parser treat the part as a plain form
    # field rather than a file, so the 400 branch never sees it.
    response = client.post("/documents", files={"file": ("", b"x", "application/pdf")})

    assert _validation_errors(response) == [("value_error", ["body", "file"])]


def test_add_document_with_a_filename_that_reduces_to_nothing_400s(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    response = client.post("/documents", files={"file": ("/", b"x", "application/pdf")})

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "An uploaded file is required"}
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


@pytest.mark.parametrize("filename", [".", "..", "x/..", "../..", "a/b/.."])
def test_add_document_with_a_dot_filename_400s(
    client: TestClient, conn: sqlite3.Connection, tmp_path: Path, filename: str
) -> None:
    response = client.post(
        "/documents", files={"file": (filename, b"x", "application/pdf")}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "An uploaded file is required"}
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert not (tmp_path / "uploads").exists() or not any(
        (tmp_path / "uploads").iterdir()
    )


@pytest.mark.parametrize("filename", ["x" * 300 + ".pdf", "é" * 130 + ".pdf"])
def test_add_document_with_a_filename_over_255_bytes_400s(
    client: TestClient, conn: sqlite3.Connection, tmp_path: Path, filename: str
) -> None:
    response = client.post(
        "/documents", files={"file": (filename, b"x", "application/pdf")}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Filename is too long (max 255 bytes)"}
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert not (tmp_path / "uploads").exists() or not any(
        (tmp_path / "uploads").iterdir()
    )


def test_add_document_with_a_nul_in_the_filename_400s(
    client: TestClient, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    boundary = "oracleboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="a\x00b.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\nx\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    response = client.post(
        "/documents",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Filename contains a NUL byte"}
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert not (tmp_path / "uploads").exists() or not any(
        (tmp_path / "uploads").iterdir()
    )


@pytest.mark.parametrize("filename", ["x" * 251 + ".pdf", "é" * 125 + "x.pdf"])
def test_add_document_accepts_a_filename_of_exactly_255_bytes(
    client: TestClient, filename: str
) -> None:
    assert len(filename.encode()) == 255

    response = client.post(
        "/documents",
        files={"file": (filename, _pdf_bytes(["Hi."]), "application/pdf")},
    )

    assert response.status_code == 202
    assert response.json()["filename"] == filename


@pytest.mark.parametrize("filename", ["noextension", "archive.pdf.zip"])
def test_add_document_rejects_unsupported_suffixes_with_a_415_detail(
    client: TestClient, conn: sqlite3.Connection, filename: str
) -> None:
    response = client.post(
        "/documents", files={"file": (filename, b"x", "application/octet-stream")}
    )

    assert response.status_code == 415
    assert response.headers["content-type"] == "application/json"
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert ".pdf" in detail and ".docx" in detail
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_add_document_accepts_an_uppercase_suffix(client: TestClient) -> None:
    response = client.post(
        "/documents",
        files={"file": ("SOURCE.PDF", _pdf_bytes(["Hi."]), "application/pdf")},
    )

    assert response.status_code == 202
    assert response.json()["filename"] == "SOURCE.PDF"


def test_add_document_ignores_the_client_content_type(client: TestClient) -> None:
    response = client.post(
        "/documents",
        files={"file": ("source.pdf", _pdf_bytes(["Hi."]), "text/plain")},
    )

    assert response.status_code == 202
    assert client.get(f"/documents/{response.json()['id']}").json()["status"] == "ready"


def test_add_document_accepts_an_empty_file_then_fails_it(client: TestClient) -> None:
    response = client.post(
        "/documents", files={"file": ("empty.pdf", b"", "application/pdf")}
    )

    assert response.status_code == 202
    polled = client.get(f"/documents/{response.json()['id']}").json()
    assert polled["status"] == "failed"
    assert polled["error"]


def test_add_document_accepts_a_two_megabyte_upload(
    client: TestClient, tmp_path: Path
) -> None:
    # Large enough to be spooled to disk by the multipart parser rather than
    # held in memory.
    content = _pdf_bytes(["Hello world."]) + b"\n%" + b"0123456789abcdef" * 131072
    assert len(content) > 2 * 1024 * 1024

    response = client.post(
        "/documents", files={"file": ("big.pdf", content, "application/pdf")}
    )

    assert response.status_code == 202
    polled = client.get(f"/documents/{response.json()['id']}").json()
    assert polled["status"] == "ready"
    (stored,) = (tmp_path / "uploads").iterdir()
    assert stored.stat().st_size == len(content)


def test_add_document_accepts_a_non_ascii_filename(client: TestClient) -> None:
    response = client.post(
        "/documents",
        files={"file": ("résumé 日本.pdf", _pdf_bytes(["Hi."]), "application/pdf")},
    )

    assert response.status_code == 202
    assert response.json()["filename"] == "résumé 日本.pdf"


def test_polling_reports_pending_then_ready(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with monkeypatch.context() as patch:
        _stub_background_processing(patch)
        uploaded = _upload(client, "source.pdf")
    doc_id = uploaded.json()["id"]

    pending = client.get(f"/documents/{doc_id}")

    assert pending.status_code == 200
    assert pending.json() == {
        "id": doc_id,
        "filename": "source.pdf",
        "status": "pending",
        "error": None,
    }
    assert [d["status"] for d in client.get("/documents").json()] == ["pending"]

    (stored,) = (tmp_path / "uploads").iterdir()
    _process_document_in_background(
        app.dependency_overrides[get_connection_factory](),
        app.dependency_overrides[get_vector_index](),
        doc_id,
        stored,
    )

    ready = client.get(f"/documents/{doc_id}")
    assert ready.json() == {
        "id": doc_id,
        "filename": "source.pdf",
        "status": "ready",
        "error": None,
    }


def test_polling_reports_pending_then_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with monkeypatch.context() as patch:
        _stub_background_processing(patch)
        uploaded = client.post(
            "/documents", files={"file": ("bad.pdf", b"not a pdf", "application/pdf")}
        )
    doc_id = uploaded.json()["id"]
    assert client.get(f"/documents/{doc_id}").json()["status"] == "pending"

    (stored,) = (tmp_path / "uploads").iterdir()
    _process_document_in_background(
        app.dependency_overrides[get_connection_factory](),
        app.dependency_overrides[get_vector_index](),
        doc_id,
        stored,
    )

    failed = client.get(f"/documents/{doc_id}").json()
    assert failed["status"] == "failed"
    assert isinstance(failed["error"], str) and failed["error"]


def test_list_documents_includes_failure_reasons_as_strings(
    client: TestClient,
) -> None:
    _upload(client, "good.pdf")
    client.post("/documents", files={"file": ("bad.pdf", b"nope", "application/pdf")})

    response = client.get("/documents")

    assert response.headers["content-type"] == "application/json"
    good, bad = response.json()
    assert good["error"] is None and good["status"] == "ready"
    assert bad["status"] == "failed" and isinstance(bad["error"], str)
    for document in (good, bad):
        assert set(document) == {"id", "filename", "status", "error"}
        assert type(document["id"]) is int


def test_get_document_404s_for_a_negative_id(client: TestClient) -> None:
    assert client.get("/documents/-1").status_code == 404


SQLITE_INT_MAX = 2**63 - 1
SQLITE_INT_MIN = -(2**63)
OUT_OF_RANGE_IDS = [2**63, 10**30, SQLITE_INT_MIN - 1]


@pytest.mark.parametrize("doc_id", OUT_OF_RANGE_IDS)
@pytest.mark.parametrize("method", ["get", "delete"])
def test_document_routes_422_for_ids_beyond_sqlite_integer(
    client: TestClient, method: str, doc_id: int
) -> None:
    response = getattr(client, method)(f"/documents/{doc_id}")

    errors = _validation_errors(response)
    assert [loc for _, loc in errors] == [["path", "document_id"]]


@pytest.mark.parametrize("doc_id", [SQLITE_INT_MAX, SQLITE_INT_MIN])
@pytest.mark.parametrize("method", ["get", "delete"])
def test_document_routes_404_at_the_sqlite_integer_boundaries(
    client: TestClient, method: str, doc_id: int
) -> None:
    response = getattr(client, method)(f"/documents/{doc_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found"}


@pytest.mark.parametrize("doc_id", OUT_OF_RANGE_IDS)
def test_search_422s_for_document_ids_beyond_sqlite_integer(
    client: TestClient, doc_id: int
) -> None:
    response = client.post(
        "/search", json={"query": "fox", "document_ids": [1, doc_id]}
    )

    errors = _validation_errors(response)
    assert len(errors) == 1
    assert errors[0][1] == ["body", "document_ids", 1]


def test_search_accepts_document_ids_at_the_sqlite_integer_boundaries(
    client: TestClient,
) -> None:
    response = client.post(
        "/search",
        json={"query": "fox", "document_ids": [SQLITE_INT_MIN, SQLITE_INT_MAX]},
    )

    assert response.status_code == 200
    assert response.json() == {"results": []}


@pytest.mark.parametrize("bad_id", ["abc", "1.5", "0x10"])
def test_get_document_422s_for_a_non_integer_id(
    client: TestClient, bad_id: str
) -> None:
    response = client.get(f"/documents/{bad_id}")

    assert _validation_errors(response) == [("int_parsing", ["path", "document_id"])]


@pytest.mark.parametrize("bad_id", ["abc", "1.5"])
def test_delete_document_422s_for_a_non_integer_id(
    client: TestClient, bad_id: str
) -> None:
    response = client.delete(f"/documents/{bad_id}")

    assert _validation_errors(response) == [("int_parsing", ["path", "document_id"])]


def test_delete_document_twice_204s_then_404s(client: TestClient) -> None:
    doc_id = _upload(client, "source.pdf").json()["id"]

    assert client.delete(f"/documents/{doc_id}").status_code == 204
    assert client.delete(f"/documents/{doc_id}").status_code == 404
    assert client.get(f"/documents/{doc_id}").status_code == 404
    assert client.get("/documents").json() == []


def test_delete_document_removes_it_from_search(client: TestClient) -> None:
    doc_id = _upload(client, "source.pdf", ["The quick brown fox."]).json()["id"]
    assert client.post("/search", json={"query": "fox"}).json()["results"]

    client.delete(f"/documents/{doc_id}")

    assert client.post("/search", json={"query": "fox"}).json() == {"results": []}


def test_search_serialises_a_docx_result_with_a_null_page_number(
    client: TestClient,
) -> None:
    client.post(
        "/documents",
        files={
            "file": (
                "notes.docx",
                _docx_bytes(["The quick brown fox."]),
                "application/octet-stream",
            )
        },
    )

    results = client.post("/search", json={"query": "brown fox"}).json()["results"]

    assert results[0]["page_number"] is None


@pytest.mark.parametrize(
    ("send", "expected"),
    [
        (lambda c: c.post("/search"), [("missing", ["body"])]),
        (
            lambda c: c.post("/search", json={"query": None}),
            [("string_type", ["body", "query"])],
        ),
        (
            lambda c: c.post("/search", json={"query": 5}),
            [("string_type", ["body", "query"])],
        ),
        (
            lambda c: c.post("/search", json={"query": ["a"]}),
            [("string_type", ["body", "query"])],
        ),
        (
            lambda c: c.post("/search", json=["query"]),
            [("model_attributes_type", ["body"])],
        ),
        (
            lambda c: c.post("/search", json="query"),
            [("model_attributes_type", ["body"])],
        ),
        (
            lambda c: c.post("/search", content=b'{"query": "x"}'),
            [("model_attributes_type", ["body"])],
        ),
    ],
)
def test_search_422s_for_a_missing_or_malformed_body(
    client: TestClient,
    send: Callable[[TestClient], httpx2.Response],
    expected: list[tuple[str, list[object]]],
) -> None:
    assert _validation_errors(send(client)) == expected


def test_search_422s_for_invalid_json(client: TestClient) -> None:
    response = client.post(
        "/search", content=b"{", headers={"content-type": "application/json"}
    )

    errors = _validation_errors(response)
    assert [error_type for error_type, _ in errors] == ["json_invalid"]
    assert errors[0][1][0] == "body"


@pytest.mark.parametrize("sources", [None, "bm25", 3])
def test_search_422s_for_non_list_sources(client: TestClient, sources: object) -> None:
    response = client.post("/search", json={"query": "x", "sources": sources})

    assert _validation_errors(response) == [("list_type", ["body", "sources"])]


def test_search_422s_for_non_integer_document_ids_naming_the_element(
    client: TestClient,
) -> None:
    response = client.post(
        "/search", json={"query": "x", "document_ids": [1, "a", 2.5]}
    )

    assert _validation_errors(response) == [
        ("int_parsing", ["body", "document_ids", 1]),
        ("int_from_float", ["body", "document_ids", 2]),
    ]


def test_search_422s_for_non_list_document_ids(client: TestClient) -> None:
    response = client.post("/search", json={"query": "x", "document_ids": 3})

    assert _validation_errors(response) == [("list_type", ["body", "document_ids"])]


def test_search_with_unknown_document_ids_returns_no_results(
    client: TestClient,
) -> None:
    _upload(client, "source.pdf", ["The quick brown fox."])

    response = client.post("/search", json={"query": "fox", "document_ids": [999]})

    assert response.status_code == 200
    assert response.json() == {"results": []}


def _cors_probe(allowed_origins: str | None) -> list[str]:
    # Origins are read at import time, so the app must be imported in a fresh
    # process with the variable set (or removed) to exercise either branch.
    script = (
        "from fastapi.testclient import TestClient\n"
        "from oracle.server.app import app\n"
        "c = TestClient(app)\n"
        "o = 'http://localhost:5173'\n"
        "pre = c.options('/documents', headers={'Origin': o,"
        " 'Access-Control-Request-Method': 'POST'})\n"
        "bad = c.options('/documents', headers={'Origin': 'http://evil.example',"
        " 'Access-Control-Request-Method': 'POST'})\n"
        "simple = c.get('/health', headers={'Origin': o})\n"
        "print(pre.status_code, pre.headers.get('access-control-allow-origin'),"
        " bad.headers.get('access-control-allow-origin'),"
        " simple.headers.get('access-control-allow-origin'))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "ORACLE_ALLOWED_ORIGINS"}
    if allowed_origins is not None:
        env["ORACLE_ALLOWED_ORIGINS"] = allowed_origins
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split()


def test_cors_headers_are_absent_without_configured_origins() -> None:
    status, preflight, evil, simple = _cors_probe(None)

    assert status == "405"
    assert (preflight, evil, simple) == ("None", "None", "None")


def test_cors_allows_only_the_configured_origins() -> None:
    status, preflight, evil, simple = _cors_probe("http://localhost:5173")

    assert status == "200"
    assert preflight == "http://localhost:5173"
    assert evil == "None"
    assert simple == "http://localhost:5173"
