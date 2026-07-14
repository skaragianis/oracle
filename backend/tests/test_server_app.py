import sqlite3

import fitz
import pytest
from fastapi.testclient import TestClient

from oracle.common.db import apply_migrations
from oracle.server.app import app, get_connection, get_uploads_dir


@pytest.fixture
def conn(tmp_path):
    # check_same_thread=False because one connection is shared across the whole
    # test while endpoints run on TestClient's threadpool. The app itself opens a
    # connection per request, on the thread that uses it, so it doesn't need this.
    connection = sqlite3.connect(tmp_path / "test.db", check_same_thread=False)
    apply_migrations(connection)
    return connection


@pytest.fixture
def client(conn, tmp_path):
    uploads_dir = tmp_path / "uploads"
    app.dependency_overrides[get_connection] = lambda: conn
    app.dependency_overrides[get_uploads_dir] = lambda: uploads_dir
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


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_add_document_stores_document_and_chunks(client, conn, tmp_path):
    response = _upload(client, "source.pdf")

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "source.pdf"
    assert body["replaced"] is False

    doc_row = conn.execute(
        "SELECT filename, status FROM documents WHERE id = ?", (body["id"],)
    ).fetchone()
    assert doc_row == ("source.pdf", "pending")

    chunk_rows = conn.execute(
        "SELECT text FROM chunks WHERE doc_id = ?", (body["id"],)
    ).fetchall()
    assert chunk_rows == [("Hello world.\n",)]

    assert len(list((tmp_path / "uploads").iterdir())) == 1


def test_add_document_replaces_existing_document_with_same_filename(client, conn):
    first = _upload(client, "source.pdf", ["Hello world."])
    second = _upload(client, "source.pdf", ["Goodbye world."])

    assert second.status_code == 201
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

    assert response.status_code == 201
    assert response.json()["filename"] == "evil.pdf"


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
        {"id": first.json()["id"], "filename": "first.pdf", "status": "pending"},
        {"id": second.json()["id"], "filename": "second.pdf", "status": "pending"},
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
