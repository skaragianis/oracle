# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The Python half of the `oracle` monorepo — the repo-wide picture, cross-cutting `make` targets, and the conventions shared by both apps live in the root `CLAUDE.md`.

Within `backend/`, a single Python package (`oracle`) contains two independently runnable apps sharing one `pyproject.toml`, one virtualenv, and one dependency set:

- `src/oracle/cli/` — the CLI app
- `src/oracle/server/` — a FastAPI/uvicorn HTTP server

## Commands

All commands run from `backend/`, using `uv` (never call `pip`/`python -m venv` directly — `uv` manages the venv and lockfile).

```bash
uv sync                  # install/update deps into .venv, per uv.lock
uv run ty check          # run type checker
uv run ruff check        # run linter
uv run pytest            # run the full test suite
uv run pytest tests/test_server_app.py::test_health   # run a single test
uv run oracle-cli        # run the CLI app
uv run oracle-server     # run the server (plain, no reload) on 127.0.0.1:8000
uv run uvicorn oracle.server.app:app --reload   # run the server with autoreload for dev
uv add <package>         # add a runtime dependency
uv add --dev <package>   # add a dev-only dependency
```

## Architecture

- Both apps are console-script entry points defined in `[project.scripts]` in `pyproject.toml` (`oracle-cli`, `oracle-server`), each a thin `main()` in its app's `main.py`. Keep this pattern when adding entry points — don't invoke app internals directly from outside their package.
- The server's ASGI app object lives in `oracle/server/app.py` (importable as `oracle.server.app:app`, used directly by `uvicorn`); `oracle/server/main.py` just wraps `uvicorn.run(...)` for the plain `oracle-server` command. Add new routes to `app.py`.
- The CLI and server are separate apps within the same package — avoid coupling one to the other's internals; shared logic should live in `src/oracle/common/` and be imported by both, rather than one importing the other's app-specific code. `common/` currently holds `db.py` (connection + migrations), `documents.py`, `chunks.py`, `ingest.py`, `embeddings.py` (the Chroma/fastembed vector index), and `search.py` — check here before adding a new helper in case the logic already exists.
- **Ingestion is two-phase.** `ingest.stage_file()` stores the upload and records it `pending`; `ingest.process_document()` chunks it and moves it to a terminal status (`ready`, or `failed` with the reason in `documents.error`). The server does the first on the request and the second in a `BackgroundTasks` task, returning `202`; the CLI does both inline via `ingest.ingest_file()`. `process_document()` never raises — a background task has nobody to return an error to, so failures are recorded on the document. Keep every path terminal: a document stuck in `pending` is one an API client polls forever. There's no SIGTERM handling, so a killed server can still leave one stuck — `process_document()` clears any chunks/vectors for the doc_id before it (re)chunks, which is what makes it safe for `ingest.reprocess_pending_documents()` to redo a document from scratch. The server lifespan calls it once at startup, before serving requests, to resume anything left `pending` by the previous process.
- A background task cannot reuse the request's connection (it is closed by then), so it opens its own via the `get_connection_factory` dependency. Override that dependency in tests, or the task writes to the real `data/oracle.db`.
- `ORACLE_DB_PATH`, `ORACLE_UPLOADS_DIR`, `ORACLE_VECTOR_DB_PATH`, and `ORACLE_MODEL_CACHE_DIR` override where the data lives; all default to `data/` under the package. They are read **at import time**, so set them before the process starts (the frontend's Playwright suite launches `oracle-server` this way, against a throwaway database). Keep them pointing at the same place — the rows, the files, and the vectors are one dataset. Don't test the override with `importlib.reload`: it hands other modules a stale `UnsupportedFileTypeError` class, and `app.py`'s `except` silently stops matching. Use a subprocess.
- Schema changes are new `.sql` files in `migrations/`, applied in filename order by `db.apply_migrations()`. Applied migrations are tracked by **filename** in a `schema_migrations` table, not by content — editing an already-applied migration file does nothing to a database that already recorded it as applied. After editing an existing migration, run `oracle-cli --reset` (or delete `data/oracle.db`) locally so it re-applies.
- `chunks` has a full-text mirror, `chunks_fts` (external-content FTS5, see `migrations/0002_create_chunks.sql`), kept in sync by `AFTER INSERT`/`AFTER DELETE` triggers on `chunks`. Always write through `chunks` (`create_chunk`, `delete_chunks_for_document`) — never insert into `chunks_fts` directly, or the mirror will drift.
- **Search is hybrid, fused with RRF, over selectable sources.** `search.search_hybrid()` takes a `sources` sequence (default `SEARCH_SOURCES = ("bm25", "vector")`), conditionally runs the top 10 BM25 (FTS5) and/or top 10 vector results, merges whichever ran with reciprocal rank fusion (`reciprocal_rank_fusion`, k=60), and returns the top 5, each `SearchResult` carrying `sources` — the list of indexes that returned it (`["bm25"]`, `["vector"]`, or both); fusion happens here, never in a client. `vector_index` stays a required parameter even when `sources` excludes `"vector"`. Vector search returns the *nearest* chunks unconditionally — there is no similarity threshold, so a query that matches nothing by keyword still returns vector-sourced results once anything is indexed; BM25-only has no such guarantee and can legitimately return zero results. `search_hybrid()` also takes `document_ids` (`None` = all documents, `[]` = none, short-circuiting before either index runs), which filters both paths: BM25 via `AND chunks.doc_id IN (…)` and vector via a Chroma `where={"doc_id": {"$in": [...]}}` metadata filter. Both `search_chunks` and `search_vectors` also restrict to `documents.status = 'ready'` — a document that failed during embedding, or was interrupted mid-ingest, can still have committed chunks in `chunks`/`chunks_fts`, and those must never surface in search.
- **The vector index is a second mirror of `chunks`**, in Chroma at `ORACLE_VECTOR_DB_PATH`, embedded with fastembed (`BAAI/bge-small-en-v1.5`, cached at `ORACLE_MODEL_CACHE_DIR`). Unlike `chunks_fts` there are no triggers keeping it in sync: `stage_file()` deletes a replaced document's vectors and `process_document()` embeds after chunking, both via the `vector_index` parameter — passing `None` skips vector work and quietly desyncs the mirror, so real callers (server, CLI) must always pass one. An embedding failure marks the document `failed`, same as a chunking failure. Documents ingested before this index existed have chunks but no vectors, and only surface via BM25 until re-added.
- `embeddings.open_vector_index()` downloads the model on first use — the server calls it (via `get_default_vector_index()`) in the lifespan so the download happens at startup, not on the first upload. Tests must never construct a real `TextEmbedding`: use the `vector_index` fixture in `tests/conftest.py` (a deterministic `FakeEmbedder` over an in-memory Chroma collection), and note CLI tests autouse-patch `open_vector_index` for the same reason.
- Tests live in top-level `tests/`, not alongside source, and mirror source modules by name (`tests/test_cli_main.py`, `tests/test_server_app.py`). `testpaths = ["tests"]` is set in `pyproject.toml`.
- Server tests use FastAPI's `TestClient` (backed by `httpx`, a dev dependency) rather than spinning up a live uvicorn process.
- Build backend is `hatchling`; the `src/` layout means the package is only importable after `uv sync`/`uv run` sets up the editable install — don't add a competing top-level `oracle/` directory.
