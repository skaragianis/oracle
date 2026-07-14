import sqlite3

import fitz
import pytest
from fastapi.testclient import TestClient

from oracle.common.db import apply_migrations
from oracle.server.app import (
    allowed_origins,
    app,
    get_connection,
    get_connection_factory,
    get_uploads_dir,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    # check_same_thread=False because one connection is shared across the whole
    # test while endpoints run on TestClient's threadpool. The app itself opens a
    # connection per request, on the thread that uses it, so it doesn't need this.
    connection = sqlite3.connect(db_path, check_same_thread=False)
    apply_migrations(connection)
    return connection


@pytest.fixture
def client(conn, db_path, tmp_path):
    uploads_dir = tmp_path / "uploads"
    app.dependency_overrides[get_connection] = lambda: conn
    app.dependency_overrides[get_uploads_dir] = lambda: uploads_dir
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


def _pdf_bytes(paragraphs):
    doc = fitz.open()
    page = doc.new_page(width=612, height=842)
    y = 72
    for paragraph in paragraphs:
        page.insert_text((72, y), paragraph)
        y += 40
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _upload(client, filename, paragraphs=("Hello world.",)):
    return client.post(
        "/documents",
        files={"file": (filename, _pdf_bytes(paragraphs), "application/pdf")},
    )


def test_allowed_origins_is_empty_when_unset(monkeypatch):
    # The SPA is same-origin with the API by default, so no CORS is configured.
    monkeypatch.delenv("ORACLE_ALLOWED_ORIGINS", raising=False)

    assert allowed_origins() == []


def test_allowed_origins_parses_a_comma_separated_list(monkeypatch):
    monkeypatch.setenv(
        "ORACLE_ALLOWED_ORIGINS", "http://192.168.1.2:5173, http://localhost:5173"
    )

    assert allowed_origins() == ["http://192.168.1.2:5173", "http://localhost:5173"]


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_add_document_stores_document_and_chunks(client, conn, tmp_path):
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


def test_add_document_replaces_existing_document_with_same_filename(client, conn):
    first = _upload(client, "source.pdf", ["Hello world."])
    second = _upload(client, "source.pdf", ["Goodbye world."])

    assert second.status_code == 202
    assert second.json()["replaced"] is True
    assert second.json()["id"] == first.json()["id"]

    chunk_rows = conn.execute(
        "SELECT text FROM chunks WHERE doc_id = ?", (second.json()["id"],)
    ).fetchall()
    assert chunk_rows == [("Goodbye world.\n",)]


def test_add_document_strips_path_from_client_supplied_filename(client, conn):
    response = client.post(
        "/documents",
        files={"file": ("../../etc/evil.pdf", _pdf_bytes(["Hi."]), "application/pdf")},
    )

    assert response.status_code == 202
    assert response.json()["filename"] == "evil.pdf"


def test_add_document_fails_a_document_it_cannot_chunk(client, conn):
    # A .docx is stored but cannot be chunked yet, so it isn't searchable and must
    # not be reported as ready. It must not stay 'pending' either: a client polls
    # until the status is terminal, and would wait on it forever.
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
    assert ".docx" in error


def test_add_document_rejects_unsupported_file_type(client):
    response = client.post(
        "/documents",
        files={"file": ("notes.txt", b"file contents", "text/plain")},
    )

    assert response.status_code == 415


def test_add_document_requires_a_file(client):
    response = client.post("/documents")

    assert response.status_code == 422


def test_list_documents_is_empty_without_uploads(client):
    response = client.get("/documents")

    assert response.status_code == 200
    assert response.json() == []


def test_list_documents_returns_uploaded_documents(client):
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


def test_search_returns_matching_chunks(client):
    uploaded = _upload(client, "source.pdf", ["The quick brown fox."])

    response = client.post("/search", json={"query": "brown fox"})

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["doc_id"] == uploaded.json()["id"]
    assert results[0]["filename"] == "source.pdf"
    assert results[0]["seq"] == 0
    assert results[0]["page_number"] == 1
    assert "quick brown fox" in results[0]["text"]


def test_search_returns_no_results_for_non_matching_query(client):
    _upload(client, "source.pdf", ["The quick brown fox."])

    response = client.post("/search", json={"query": "elephant"})

    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_search_returns_no_results_for_query_of_only_stop_words(client):
    _upload(client, "source.pdf", ["The quick brown fox."])

    response = client.post("/search", json={"query": "the and of"})

    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_search_requires_a_query(client):
    response = client.post("/search", json={})

    assert response.status_code == 422


def test_get_document_returns_a_ready_document(client):
    uploaded = _upload(client, "source.pdf")

    response = client.get(f"/documents/{uploaded.json()['id']}")

    assert response.status_code == 200
    assert response.json() == {
        "id": uploaded.json()["id"],
        "filename": "source.pdf",
        "status": "ready",
        "error": None,
    }


def test_get_document_reports_the_failure_reason(client):
    uploaded = client.post(
        "/documents",
        files={"file": ("notes.docx", b"file contents", "application/msword")},
    )

    response = client.get(f"/documents/{uploaded.json()['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert ".docx" in body["error"]


def test_get_document_404s_for_an_unknown_id(client):
    response = client.get("/documents/999")

    assert response.status_code == 404
