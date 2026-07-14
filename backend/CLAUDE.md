# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Oracle: use LLMs to ask questions of provided documents. This `backend/` directory is one of two apps in the `oracle` monorepo (the other is `frontend/`, a sibling directory outside this one — Python conventions do not apply there).

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

Start work by confirming all tests pass first. Never finish work until all tests pass, the type checker shows no feedback, and the linter shows no feedback.

## Architecture

- Both apps are console-script entry points defined in `[project.scripts]` in `pyproject.toml` (`oracle-cli`, `oracle-server`), each a thin `main()` in its app's `main.py`. Keep this pattern when adding entry points — don't invoke app internals directly from outside their package.
- The server's ASGI app object lives in `oracle/server/app.py` (importable as `oracle.server.app:app`, used directly by `uvicorn`); `oracle/server/main.py` just wraps `uvicorn.run(...)` for the plain `oracle-server` command. Add new routes to `app.py`.
- The CLI and server are separate apps within the same package — avoid coupling one to the other's internals; shared logic should live in `src/oracle/common/` and be imported by both, rather than one importing the other's app-specific code. `common/` currently holds `db.py` (connection + migrations), `documents.py`, `chunks.py`, `ingest.py`, and `search.py` — check here before adding a new helper in case the logic already exists.
- Schema changes are new `.sql` files in `migrations/`, applied in filename order by `db.apply_migrations()`. Applied migrations are tracked by **filename** in a `schema_migrations` table, not by content — editing an already-applied migration file does nothing to a database that already recorded it as applied. After editing an existing migration, run `oracle-cli --reset` (or delete `data/oracle.db`) locally so it re-applies.
- `chunks` has a full-text mirror, `chunks_fts` (external-content FTS5, see `migrations/0002_create_chunks.sql`), kept in sync by `AFTER INSERT`/`AFTER DELETE` triggers on `chunks`. Always write through `chunks` (`create_chunk`, `delete_chunks_for_document`) — never insert into `chunks_fts` directly, or the mirror will drift.
- Tests live in top-level `tests/`, not alongside source, and mirror source modules by name (`tests/test_cli_main.py`, `tests/test_server_app.py`). `testpaths = ["tests"]` is set in `pyproject.toml`.
- Server tests use FastAPI's `TestClient` (backed by `httpx`, a dev dependency) rather than spinning up a live uvicorn process.
- Build backend is `hatchling`; the `src/` layout means the package is only importable after `uv sync`/`uv run` sets up the editable install — don't add a competing top-level `oracle/` directory.
