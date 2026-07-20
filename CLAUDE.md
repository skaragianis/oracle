# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Oracle — ask questions of your documents with RAG (hybrid BM25 + vector search, RRF-fused). Local, single-user. A monorepo of two apps sharing one dataset:

- `backend/` — Python (uv): a CLI and a FastAPI server in one package. See `backend/CLAUDE.md`.
- `frontend/` — Vue 3 SPA (pnpm, Vite, PrimeVue) over the server's HTTP API. See `frontend/CLAUDE.md`.

Each app's CLAUDE.md is authoritative for its own commands, architecture, and gotchas — read it first. The two apps' conventions don't cross over.

## Conventions

- Confirm the affected app's tests pass before starting; don't finish until its tests, linter, and typechecker are all clean.
- **No narrating comments.** Comment only when the *why* is non-obvious — a real gotcha or non-local constraint. Otherwise let names and structure carry it.

## Commands

`make help` lists all targets. Common ones:

```bash
make up      # build image + run the whole app at http://localhost:8080 (docker)
make down    # stop/remove the container (data volume kept)
make test    # backend pytest + frontend vitest
make lint    # backend ruff + ty, frontend vue-tsc
```

Per-component targets exist (`cli-`, `server-`, `backend-`, `frontend-`). Dev = `make server-run` + `make frontend-run` in two terminals; docker is for running the app, not developing it.

## Docker & data

One root `Dockerfile` builds everything: a node stage builds the SPA, a debian stage runs uvicorn behind nginx that serves `dist/` and proxies `/api/` (same-origin, so no CORS). The nginx config and startup script are BuildKit heredocs in the Dockerfile — no separate config files to sync.

Persistent state is **one dataset on one volume** (`oracle-data` at `/data`): SQLite db (`ORACLE_DB_PATH`), uploads (`ORACLE_UPLOADS_DIR`), vector index (`ORACLE_VECTOR_DB_PATH`), and model cache (`ORACLE_MODEL_CACHE_DIR`, so the model downloads once per volume). Keep them pointing at the same place — a row without its file or vectors is corrupt state. `make up` is rerunnable and never touches the volume.
