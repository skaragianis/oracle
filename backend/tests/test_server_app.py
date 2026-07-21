import io
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from unittest import mock

import docx
import fitz
import httpx
import pytest
from fastapi.testclient import TestClient

from oracle.common import db, documents, ingest
from oracle.common.db import apply_migrations
from oracle.common.embeddings import VectorIndex
from oracle.server.app import (
    _ingest_slot,
    _process_document_in_background,
    _shutdown_gracefully,
    _shutting_down,
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
def conn(db_path: Path) -> sqlite3.Connection:
    # check_same_thread=False because one connection is shared across the whole
    # test while endpoints run on TestClient's threadpool. The app itself opens a
    # connection per request, on the thread that uses it, so it doesn't need this.
    connection = sqlite3.connect(db_path, check_same_thread=False)
    apply_migrations(connection)
    return connection


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
    doc = fitz.open()
    page = doc.new_page(width=612, height=842)
    y = 72
    for paragraph in paragraphs:
        page.insert_text((72, y), paragraph)
        y += 40
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _upload(
    client: TestClient, filename: str, paragraphs: Iterable[str] = ("Hello world.",)
) -> httpx.Response:
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
    assert response.json() == {"status": "ok"}


def test_add_document_stores_document_and_chunks(
    client: TestClient, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    response = _upload(client, "source.pdf")

    # 202, not 201: the upload is accepted as 'pending' and chunked in a
    # background task, which TestClient runs before returning the response.
    assert response.status_code == 202
    body = response.json()
    assert body["filename"] == "source.pdf"
    assert body["replaced"] is False
    assert body["status"] == "pending"

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
    assert second.json()["replaced"] is True
    assert second.json()["id"] == first.json()["id"]

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


def test_add_document_requires_a_file(client: TestClient) -> None:
    response = client.post("/documents")

    assert response.status_code == 422


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

    assert response.status_code == 422


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

    assert response.status_code == 422


def test_search_rejects_an_empty_sources_list(client: TestClient) -> None:
    response = client.post("/search", json={"query": "brown fox", "sources": []})

    assert response.status_code == 422


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


def test_delete_document_removes_document_upload_and_chunks(
    client: TestClient, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    uploaded = _upload(client, "source.pdf")
    doc_id = uploaded.json()["id"]

    response = client.delete(f"/documents/{doc_id}")

    assert response.status_code == 204
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
