# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

The Python half of the `oracle` monorepo (repo-wide picture and cross-cutting `make` targets: root `CLAUDE.md`). One package, `oracle`, with two runnable apps sharing one `pyproject.toml` and venv:

- `src/oracle/cli/` — the CLI app
- `src/oracle/server/` — a FastAPI/uvicorn server
- `src/oracle/common/` — shared logic (`db`, `documents`, `chunks`, `ingest`, `embeddings`, `search`); check here before adding a helper.

## Commands

Prefer the repo-root `make` targets — they `cd backend` and run `uv` for you, and are the verified entry points:

```bash
make setup                       # install deps per uv.lock (also frontend + Playwright)
make backend-test                # full suite (CLI, server, common)
make cli-test                    # CLI + common only
make server-test                 # server + common only
make backend-lint                # ruff check + ty check
make server-run                  # dev server on 127.0.0.1:8000
make cli-run ARGS="--help"       # run the CLI
```

Drop to raw `uv` from `backend/` only for what the targets don't cover (never call `pip`/`venv` directly — `uv` owns the venv and lockfile):

```bash
uv run pytest tests/test_server_app.py::test_health    # single test
uv run uvicorn oracle.server.app:app --reload          # dev server with auto-reload
```

Entry points (`oracle-cli`, `oracle-server`) are `[project.scripts]` consoles, each a thin `main()`. Add server routes to `oracle/server/app.py` (the ASGI object uvicorn imports). Keep CLI and server decoupled — share through `common/`, don't import one app's internals from the other.

## Architecture & gotchas

- **Two-phase ingest.** `ingest.stage_file()` stores the upload as `pending`; `ingest.process_document()` chunks + embeds it and moves it to a terminal status (`ready`, or `failed` with the reason in `documents.error`). The server splits these (request + `BackgroundTasks`, returns 202); the CLI does both inline via `ingest_file()`. `process_document()` never raises (a background task has nobody to return to — it records failures on the doc) and clears a doc's chunks/vectors before (re)chunking, so it's safe to redo. Keep every path terminal — a doc stuck `pending` is polled forever. The server lifespan runs `reprocess_pending_documents()` at startup to resume anything left `pending`.
- Background tasks can't reuse the request connection (closed by then) — they open their own via `get_connection_factory`. Override that dependency in tests, or the task writes the real db.
- **Graceful shutdown is signal-driven, not lifespan-driven.** uvicorn drains in-flight background tasks *before* it fires the ASGI lifespan shutdown, so setting the stop flag in the lifespan is too late to interrupt a running ingest. `server.main._Server.handle_exit` sets `app._shutting_down` the instant SIGINT/SIGTERM lands; `ingest.process_document` polls `should_stop` between chunk lines and embed batches and bails by leaving the doc **pending** (never terminal — startup reprocess resumes it). Only then does the lifespan's `_shutdown_gracefully` run: WAL checkpoint (`wal_checkpoint(TRUNCATE)`) + `vector_index.close()`, bounded by `SHUTDOWN_INGEST_TIMEOUT_SECONDS` (also uvicorn's `timeout_graceful_shutdown` ceiling). Running the ASGI app directly (`uvicorn oracle.server.app:app --reload`) bypasses `_Server`, so in-flight ingests won't interrupt on Ctrl-C — that path is dev-only; `oracle-server` is the real entry.
- `ORACLE_DB_PATH`, `ORACLE_UPLOADS_DIR`, `ORACLE_VECTOR_DB_PATH`, `ORACLE_MODEL_CACHE_DIR` (all default under `data/`) are read **at import time** — set them before the process starts. Don't test the override with `importlib.reload`: it hands other modules a stale `UnsupportedFileTypeError`, silently breaking `app.py`'s `except`. Use a subprocess.
- **Migrations** are `.sql` files in `migrations/`, applied in filename order and tracked **by filename** — editing an already-applied file does nothing. After editing one, `oracle-cli --reset` (or delete `data/oracle.db`) to re-apply.
- **`chunks` has an FTS5 mirror `chunks_fts`** (external-content, synced by triggers). Always write through `chunks` (`create_chunk`, `delete_chunks_for_document`) — never insert into `chunks_fts` directly.
- **Search is hybrid, RRF-fused.** `search.search_hybrid()` takes `sources` (default both `bm25`+`vector`), runs top-10 of each selected index, fuses with RRF (k=60) to top 5; each `SearchResult.sources` lists the indexes that returned it. `vector_index` is always required, even when vector isn't selected. It also takes `document_ids` (`None` = all, `[]` = none). Both paths restrict to `documents.status = 'ready'` — a doc that failed during embedding still has committed chunks that must never surface. Vector search has no similarity threshold (always returns nearest), so it yields hits even with no keyword match; BM25-only can legitimately return zero.
- **The vector index (Chroma at `ORACLE_VECTOR_DB_PATH`, fastembed `BAAI/bge-small-en-v1.5`) is a second mirror of `chunks`, with no triggers.** `stage_file()` deletes replaced vectors and `process_document()` embeds after chunking, both via the `vector_index` param — passing `None` silently desyncs the mirror, so real callers must always pass one. Docs ingested before this index existed have chunks but no vectors (BM25-only until re-added).
- `embeddings.open_vector_index()` downloads the model on first use — the server calls it in the lifespan so that happens at startup. **Tests must never construct a real `TextEmbedding`**: use the `vector_index` fixture in `tests/conftest.py` (a `FakeEmbedder` over in-memory Chroma); CLI tests autouse-patch `open_vector_index`.
- Tests live in top-level `tests/`, mirroring source module names; server tests use FastAPI's `TestClient` (no live uvicorn). Build backend is `hatchling` with a `src/` layout — the package is importable only after `uv sync`/`uv run`; don't add a competing top-level `oracle/`.
